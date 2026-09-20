import textwrap

import pytest

from avatar import voice_client

FAKE_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True,
                                     "seconds": 0.1}) + "\\n")
        sys.stdout.flush()
""")

CRASHING_WORKER = 'import sys; sys.exit(1)'

SLOW_FAILING_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": False,
                                     "error": "boom"}) + "\\n")
        sys.stdout.flush()
""")

# Starts, prints nothing, never exits. The plan's readline() loop blocks here
# forever and ready_timeout never fires.
SILENT_WORKER = 'import time\nwhile True: time.sleep(0.5)\n'

# Becomes ready, then ignores every request without exiting -- a wedged model.
HANGING_WORKER = textwrap.dedent("""
    import json, sys, time
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        time.sleep(30)
""")

# Emits the library noise real torch/chatterbox produce, on stdout, around the
# protocol messages.
NOISY_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write("Loading checkpoint shards:  50%|#####     |\\n")
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        sys.stdout.write("FutureWarning: torch.load is deprecated\\n")
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True}) + "\\n")
        sys.stdout.flush()
""")

FAILS_LOUDLY_WORKER = textwrap.dedent("""
    import sys
    sys.stderr.write("ModuleNotFoundError: No module named 'chatterbox'\\n")
    sys.exit(1)
""")


def _client(tmp_path, source, **kwargs):
    script = tmp_path / "worker.py"
    script.write_text(source)
    return voice_client.VoiceClient(
        python_exe="python3", worker_script=str(script),
        ref_wav=str(tmp_path / "ref.wav"), **kwargs)


def test_start_waits_for_ready(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        assert client.ready is True
        assert client.degraded is False
    finally:
        client.stop()


def test_convert_returns_true_on_success(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is True
    finally:
        client.stop()


def test_process_is_reused_across_conversions(tmp_path):
    """The regression test for the whole design: a spawn-per-request
    implementation would show a different pid on the second call and cost
    ~16s of model load every reply."""
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        client.convert("a.wav", "b.wav")
        first_pid = client.pid
        client.convert("c.wav", "d.wav")
        assert client.pid == first_pid
    finally:
        client.stop()


def test_worker_that_fails_to_start_marks_degraded(tmp_path):
    client = _client(tmp_path, CRASHING_WORKER, ready_timeout=3.0)
    try:
        client.start()
        assert client.degraded is True
        assert client.ready is False
    finally:
        client.stop()


def test_convert_while_degraded_returns_false_instead_of_raising(tmp_path):
    client = _client(tmp_path, CRASHING_WORKER, ready_timeout=3.0)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is False
    finally:
        client.stop()


def test_conversion_error_returns_false_and_keeps_worker_alive(tmp_path):
    client = _client(tmp_path, SLOW_FAILING_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is False
        assert client.pid is not None
    finally:
        client.stop()


def test_stop_is_safe_to_call_twice(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    client.start()
    client.stop()
    client.stop()


# --- defects found reviewing the planned implementation --------------------

def test_silent_worker_times_out_instead_of_hanging_forever(tmp_path):
    """`ready_timeout` must actually fire.

    A plain `proc.stdout.readline()` blocks with no deadline, so a worker that
    starts but never prints -- a model download stalling on a dead network, say
    -- hangs the avatar at startup forever. The deadline is only checked
    between reads, so it is never reached. The crashing-worker test above does
    not catch this: that worker exits, which ends readline() immediately.
    """
    client = _client(tmp_path, SILENT_WORKER, ready_timeout=1.5, stop_timeout=0.5)
    try:
        client.start()
        assert client.ready is False
        assert client.degraded is True
        assert "in time" in client.last_error
    finally:
        client.stop()


def test_convert_times_out_on_a_wedged_worker(tmp_path):
    """CONVERT_TIMEOUT existed in the plan but was never referenced, so a
    wedged worker blocked the render loop indefinitely with no way out."""
    client = _client(tmp_path, HANGING_WORKER, ready_timeout=5.0, stop_timeout=0.5)
    try:
        client.start()
        assert client.ready is True
        assert client.convert("in.wav", "out.wav", timeout=1.0) is False
        assert client.degraded is True
    finally:
        client.stop()


def test_library_noise_on_stdout_does_not_break_the_protocol(tmp_path):
    """torch and chatterbox print progress bars and warnings. If a stray line
    is read as a response, every reply afterwards is answering the previous
    request. Non-JSON lines must be skipped, at ready and at convert."""
    client = _client(tmp_path, NOISY_WORKER)
    try:
        client.start()
        assert client.ready is True
        assert client.convert("in.wav", "out.wav") is True
    finally:
        client.stop()


def test_startup_failure_reports_the_workers_stderr(tmp_path):
    """The plan sent stderr to DEVNULL, so every startup failure looked
    identical and said nothing about the cause. This project's stated rule is
    that nothing fails silently."""
    client = _client(tmp_path, FAILS_LOUDLY_WORKER, ready_timeout=5.0)
    try:
        client.start()
        assert client.degraded is True
        assert "chatterbox" in client.last_error
    finally:
        client.stop()


def test_pid_is_none_before_start(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    assert client.pid is None
    assert client.convert("in.wav", "out.wav") is False


def test_say_to_wav_writes_real_audio(tmp_path):
    """The scaffold ChatterboxVC re-colours. Cheap to check for real, and it
    catches a missing `say` voice, which would otherwise surface as silence."""
    path = tmp_path / "scaffold.wav"
    voice_client.say_to_wav("Wake up, samurai.", str(path))
    assert path.exists() and path.stat().st_size > 1000
