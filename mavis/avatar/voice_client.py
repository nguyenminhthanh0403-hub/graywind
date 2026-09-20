"""Owns the warm ChatterboxVC worker subprocess.

Every failure here degrades to plain `say` rather than silence, and sets
`degraded` so the UI can show it. A voice assistant that goes quiet with no
explanation is the failure mode this project explicitly rejects.

The worker's output is drained by a background thread into a queue rather than
read with `proc.stdout.readline()`. That is not incidental: a bare readline()
blocks with no deadline, so both timeouts here would be decorative -- a worker
that starts but never speaks would hang the avatar at startup forever, and a
wedged model would block the render loop with no way out. Reading through a
queue is what makes `ready_timeout` and `CONVERT_TIMEOUT` real.

Non-JSON lines are skipped everywhere. torch and chatterbox print progress bars
and warnings, and a stray line read as a response would leave every later reply
answering the previous request. The worker also redirects library output away
from stdout; this is the second half of that defence.
"""
import collections
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

NARRATION_PYTHON = os.environ.get(
    "MAVIS_VOICE_PYTHON",
    str(Path.home() / "minhthanh0403/claude-projects/claudekit/bullion-live-map"
        "/.venv-narration/bin/python"),
)
ACTOR_REF_WAV = os.environ.get(
    "MAVIS_ACTOR_REF",
    str(Path.home() / "minhthanh0403/claude-projects/claudekit/bullion-live-map"
        "/audio/voice_sample/actor_sample.wav"),
)
WORKER_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "voice_worker.py")

READY_TIMEOUT = 90.0
CONVERT_TIMEOUT = 120.0
# How long a shutdown request is given before the worker is killed. A healthy
# worker answers at once; this only costs time when one is already wedged.
STOP_TIMEOUT = 5.0

# ChatterboxVC emits at this rate regardless of the reference clip's rate, and
# it is what Task 7 must hand to lipsync.envelope(). Passing the reference's
# 22050 instead would stretch the envelope against the audio and drift the
# mouth out of sync over a long answer.
OUTPUT_SAMPLE_RATE = 24000

_EOF = object()


def say_to_wav(text: str, path: str) -> None:
    """macOS `say` scaffold that ChatterboxVC re-colours into Johnny."""
    subprocess.run(
        ["say", "-v", "Tom", "-o", path, "--data-format=LEF32@22050", text],
        check=True,
    )


class VoiceClient:
    def __init__(self, python_exe=NARRATION_PYTHON, worker_script=WORKER_SCRIPT,
                 ref_wav=ACTOR_REF_WAV, ready_timeout=READY_TIMEOUT,
                 stop_timeout=STOP_TIMEOUT):
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.ref_wav = ref_wav
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.proc = None
        self.ready = False
        self.degraded = False
        self.last_error = None
        self.device = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._messages = queue.Queue()
        self._stderr = collections.deque(maxlen=40)

    @property
    def pid(self):
        return self.proc.pid if self.proc and self.proc.poll() is None else None

    def _drain_stdout(self, stream):
        for line in stream:
            self._messages.put(line)
        self._messages.put(_EOF)

    def _drain_stderr(self, stream):
        for line in stream:
            self._stderr.append(line.rstrip())

    def _stderr_tail(self, limit=3):
        lines = [line for line in self._stderr if line.strip()]
        return " | ".join(lines[-limit:])

    def _next_message(self, deadline):
        """Next JSON object from the worker, or None on timeout or exit.

        Skips anything that is not JSON so library chatter cannot be mistaken
        for a protocol message.
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = self._messages.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is _EOF:
                return None
            try:
                return json.loads(line)
            except ValueError:
                continue

    def start(self) -> None:
        try:
            self.proc = subprocess.Popen(
                [self.python_exe, self.worker_script, self.ref_wav],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )
        except OSError as exc:
            self._degrade(f"could not launch voice worker: {exc}")
            return

        for target, stream in ((self._drain_stdout, self.proc.stdout),
                               (self._drain_stderr, self.proc.stderr)):
            thread = threading.Thread(target=target, args=(stream,), daemon=True)
            thread.start()

        deadline = time.monotonic() + self.ready_timeout
        while True:
            message = self._next_message(deadline)
            if message is None:
                detail = self._stderr_tail()
                if self.proc.poll() is not None:
                    reason = "voice worker exited before becoming ready"
                elif time.monotonic() >= deadline:
                    reason = "voice worker did not become ready in time"
                else:
                    reason = "voice worker closed its output before ready"
                self._degrade(f"{reason}{': ' + detail if detail else ''}")
                return
            if message.get("ready"):
                self.ready = True
                self.device = message.get("device")
                return
            if "ready" in message:
                detail = message.get("error") or self._stderr_tail()
                self._degrade(f"voice worker failed to load: {detail}")
                return

    def convert(self, in_path: str, out_path: str, timeout=CONVERT_TIMEOUT) -> bool:
        """True if `out_path` now holds Johnny-voiced audio."""
        if not self.ready or self.pid is None:
            return False

        with self._lock:
            self._next_id += 1
            request = {"id": self._next_id, "op": "convert",
                       "input": in_path, "output": out_path}
            try:
                self.proc.stdin.write(json.dumps(request) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._degrade(f"voice worker pipe broke: {exc}")
                return False

            message = self._next_message(time.monotonic() + timeout)

        if message is None:
            if self.proc.poll() is not None:
                self._degrade("voice worker died mid-conversion")
            else:
                # Still running but unresponsive: the reply for this request may
                # yet arrive and would be read as the answer to the next one, so
                # the worker cannot be trusted again.
                self._degrade(f"voice worker did not answer within {timeout:.0f}s")
            return False

        if not message.get("ok"):
            self.last_error = message.get("error", "voice conversion failed")
            return False
        return True

    def _degrade(self, reason: str) -> None:
        self.ready = False
        self.degraded = True
        self.last_error = reason

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=self.stop_timeout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.proc.kill()
            try:
                self.proc.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                pass
        finally:
            self.proc = None
            self.ready = False
