"""Long-lived ChatterboxVC process. RUNS UNDER PYTHON 3.12, NOT 3.14.

ChatterboxVC needs torch, which lives in bullion-live-map's .venv-narration
(py3.12); Panda3D needs py3.14. The two cannot share a process, so voice
conversion happens here, behind a pipe.

This process stays alive for the whole MAVIS session on purpose. Model load is
~15s and embedding the reference clip ~1s; paying that once at startup is the
difference between a ~12-15s reply and a ~30s one. Anything that restarts this
per request has broken the design.

**stdout is reserved for the protocol and nothing else.** torch, chatterbox and
their dependencies print progress bars and warnings on import and during
inference. A single stray line on stdout would be read by the client as a
response and desynchronise every reply after it. So the real stdout is
duplicated to a private handle before anything else is imported, and `sys.stdout`
is then pointed at stderr -- any library that prints lands harmlessly in the
client's stderr tail, which is surfaced in error messages.

Protocol: one JSON object per line, both directions.
  in :  {"id": 1, "op": "convert", "input": "/tmp/a.wav", "output": "/tmp/b.wav"}
  in :  {"id": 2, "op": "ping"}
  in :  {"op": "shutdown"}
  out:  {"ready": true, "device": "mps"}      (once, after model load)
  out:  {"id": 1, "ok": true, "seconds": 9.2}
  out:  {"id": 1, "ok": false, "error": "..."}
"""
import json
import os
import sys
import time

# Peak level converted speech is scaled to. Just under full scale to leave
# headroom for playback resampling without clipping.
TARGET_PEAK = 0.89

# Claim stdout before any noisy import can write to it.
_PROTOCOL = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
sys.stdout = sys.stderr

import torch  # noqa: E402
import torchaudio  # noqa: E402
from chatterbox.vc import ChatterboxVC  # noqa: E402


def _emit(obj):
    _PROTOCOL.write(json.dumps(obj) + "\n")
    _PROTOCOL.flush()


def _normalise(wav):
    """Bring the clip up to a consistent speaking level.

    ChatterboxVC's output tracks the reference clip's level, which for the
    actor sample lands around 0.135 peak -- roughly 17dB down, quiet enough
    that it could not be judged against room noise. Normalising per clip also
    keeps replies at an even volume instead of varying with whatever the
    scaffold happened to produce.

    Near-silence is left alone: scaling it to the target would only amplify
    the noise floor into an audible hiss.
    """
    peak = float(wav.abs().max())
    if peak < 1e-4:
        return wav
    return wav * (TARGET_PEAK / peak)


def _convert(model, request):
    started = time.monotonic()
    wav = model.generate(request["input"])
    if hasattr(wav, "dim") and wav.dim() == 1:
        wav = wav.unsqueeze(0)
    wav = _normalise(wav)
    torchaudio.save(request["output"], wav, model.sr)
    return round(time.monotonic() - started, 2)


def main():
    if len(sys.argv) < 2:
        _emit({"ready": False, "error": "usage: voice_worker.py <reference.wav>"})
        return 2

    reference = sys.argv[1]
    try:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model = ChatterboxVC.from_pretrained(device=device)
        model.set_target_voice(reference)
    except Exception as exc:  # noqa: BLE001 - report, never crash silently
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _emit({"ready": True, "device": device, "sample_rate": model.sr})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue

        op = request.get("op")
        if op == "shutdown":
            return 0
        if op == "ping":
            _emit({"id": request.get("id"), "ok": True})
            continue
        if op != "convert":
            _emit({"id": request.get("id"), "ok": False,
                   "error": f"unknown op {op!r}"})
            continue

        try:
            seconds = _convert(model, request)
            _emit({"id": request.get("id"), "ok": True, "seconds": seconds})
        except Exception as exc:  # noqa: BLE001 - one bad clip must not kill the worker
            _emit({"id": request.get("id"), "ok": False,
                   "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
