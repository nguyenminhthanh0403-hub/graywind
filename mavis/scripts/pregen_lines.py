"""Pre-render the canned Johnny lines. RUNS UNDER PYTHON 3.12, NOT 3.14.

ChatterboxTTS needs torch, which lives in bullion-live-map's .venv-narration.
It generates at 35-41x realtime on this machine -- 86.6s for 2.1s of audio --
which is why these lines are rendered once, offline, rather than spoken live.
Substantive answers take the fast ChatterboxVC path instead.

Settings are Bullion's, verbatim, because they are what makes the voice Johnny
rather than the formal narrator: exaggeration 0.8, cfg_weight 0.3, then a
0.92 tempo stretch and loudnorm.

Work is skipped when the manifest already holds an entry whose hash matches the
line's current text and whose wav exists. The hash is of the text itself, so
editing a line rebuilds exactly that line.

Usage, from mavis/:
    <narration-venv>/bin/python scripts/pregen_lines.py [--only MOMENT] [--dry-run]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from avatar import lines  # noqa: E402

OUT_DIR = ROOT / "assets" / "voice"
MANIFEST = OUT_DIR / "manifest.json"
ACTOR_REF = Path.home() / (
    "minhthanh0403/claude-projects/claudekit/bullion-live-map"
    "/audio/voice_sample/actor_sample.wav"
)

EXAGGERATION = 0.8
CFG_WEIGHT = 0.3
TEMPO = 0.92
LOUDNORM = "loudnorm=I=-20:TP=-2:LRA=7"
SAMPLE_RATE = 24000


def load_manifest():
    try:
        return json.loads(MANIFEST.read_text())["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def save_manifest(entries):
    MANIFEST.write_text(json.dumps(
        {"version": 1, "sample_rate": SAMPLE_RATE, "entries": entries},
        indent=2,
    ))


def duration(path):
    try:
        with wave.open(str(path)) as handle:
            return round(handle.getnframes() / handle.getframerate(), 2)
    except (OSError, wave.Error):
        return None


def render(tts, text, target, torchaudio):
    """TTS the line, then apply Johnny's tempo and loudness through ffmpeg."""
    raw = target.with_suffix(".raw.wav")
    wav = tts.generate(str(text), audio_prompt_path=str(ACTOR_REF),
                       exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT)
    torchaudio.save(str(raw), wav, tts.sr)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
         "-filter:a", f"atempo={TEMPO},{LOUDNORM}",
         "-ar", str(SAMPLE_RATE), str(target)],
        check=True,
    )
    raw.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=lines.MOMENTS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Fail before spending 47 minutes in TTS, not after.
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found; install it before generating")
    if not ACTOR_REF.exists():
        raise SystemExit(f"reference clip missing: {ACTOR_REF}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = {entry["hash"]: entry for entry in load_manifest()}

    wanted = [(moment, text) for moment, text in lines.all_lines()
              if args.only is None or moment == args.only]

    todo = []
    keep = []
    for moment, text in wanted:
        digest = lines.slug(text)
        entry = existing.get(digest)
        if entry and (OUT_DIR / entry["file"]).exists():
            keep.append(entry)
            continue
        todo.append((moment, text, digest))

    print(f"{len(keep)} already rendered, {len(todo)} to generate")
    for moment, text, digest in todo:
        print(f"  [{moment}] {text}")
    if args.dry_run or not todo:
        return

    import torchaudio
    from chatterbox.tts import ChatterboxTTS
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"loading ChatterboxTTS on {device}...")
    started = time.monotonic()
    tts = ChatterboxTTS.from_pretrained(device=device)
    print(f"loaded in {time.monotonic() - started:.1f}s")

    for index, (moment, text, digest) in enumerate(todo, 1):
        target = OUT_DIR / f"{moment}-{digest}.wav"
        began = time.monotonic()
        render(tts, text, target, torchaudio)
        seconds = duration(target)
        keep.append({"moment": moment, "text": text, "hash": digest,
                     "file": target.name, "seconds": seconds})
        save_manifest(keep)          # after each line, so an interrupt keeps progress
        print(f"[{index}/{len(todo)}] {moment}: {seconds}s audio "
              f"in {time.monotonic() - began:.0f}s -- {text}")

    print(f"done: {len(keep)} lines in {OUT_DIR}")


if __name__ == "__main__":
    main()
