# MAVIS Hybrid Voice — Canned Johnny Lines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the avatar Johnny's real voice for the lines that repeat — greeting, idle, dismissal, thinking filler — by pre-generating them offline with ChatterboxTTS, while substantive answers keep using the live ChatterboxVC path built in Task 5.

**Architecture:** A static line catalogue (`lines.py`, pure stdlib) is the single source of truth, imported by both the 3.14 runtime and the 3.12 generator. An offline script renders each line to a wav and records it in a manifest keyed by a hash of the line's text, so editing or adding a line regenerates only that line. At runtime a resolver maps a moment to a playable wav, degrading to "say nothing" when audio is missing.

**Tech Stack:** Python stdlib (`hashlib`, `random`, `json`), ChatterboxTTS + torch (3.12 only), ffmpeg, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-mavis-canned-voice-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Runtime venv is Python 3.14** at `mavis/.venv`. torch must **never** be installed into it.
- **Generator interpreter** is exactly `~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python` (Python 3.12.13, torch 2.6.0, MPS). Same interpreter as `scripts/voice_worker.py`.
- `lines.py` must stay **pure stdlib** — it is imported by both interpreters. No numpy, no panda3d, no project imports.
- TTS settings are Bullion's, verbatim: `exaggeration=0.8`, `cfg_weight=0.3`, then `atempo=0.92,loudnorm=I=-20:TP=-2:LRA=7`, then **`-ar 24000`**.
- `-ar 24000` is mandatory: `loudnorm` resamples to 192kHz internally and emits that rate otherwise. 24000 also matches ChatterboxVC's output so canned and live audio share one rate.
- Reference prompt is `~/minhthanh0403/claude-projects/claudekit/bullion-live-map/audio/voice_sample/actor_sample.wav`.
- **Generated audio is never committed.** Cloned speech in a hired actor's voice, public repo.
- **No silent failures.** Every degraded path is visible and named.
- Tests run with `cd mavis && .venv/bin/python -m pytest -q`. The suite is currently **126 passing**; keep it green.
- Follow existing style: module-level constants, docstrings that explain *why*, no inline comments restating code.

## File Structure

| Path | Responsibility |
|---|---|
| `mavis/avatar/lines.py` | The 28-line catalogue as data; `slug()`, `pick()`, `all_lines()` |
| `mavis/tests/test_lines.py` | Catalogue integrity and selection behaviour |
| `mavis/avatar/canned.py` | Manifest → playable wav for a moment; degradation |
| `mavis/tests/test_canned.py` | Manifest parsing and every missing-audio path |
| `mavis/scripts/pregen_lines.py` | **Runs under 3.12.** TTS + ffmpeg + manifest |
| `mavis/assets/voice/ATTRIBUTION.md` | Actor sample provenance and rebuild command |
| `mavis/.gitignore` | Ignore `assets/voice/` except its ATTRIBUTION.md |

Task order is forced by dependency: `canned.py` reads what `lines.py` defines, and `pregen_lines.py` writes what `canned.py` reads. The generator comes last because it is the only task with a 47-minute human gate.

---

### Task 1: The line catalogue

**Files:**
- Create: `mavis/avatar/lines.py`
- Create: `mavis/tests/test_lines.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `lines.MOMENTS: tuple[str, ...]` — `("greeting", "idle", "dismissal", "filler")`
  - `lines.LINES: dict[str, tuple[str, ...]]`
  - `lines.slug(text: str) -> str` — `sha1(text.encode()).hexdigest()[:12]`
  - `lines.pick(moment: str, exclude: str | None = None) -> str` — returns line **text**
  - `lines.all_lines() -> list[tuple[str, str]]` — `(moment, text)` pairs, catalogue order

- [ ] **Step 1: Write the failing test**

Create `mavis/tests/test_lines.py`:

```python
import pytest

from avatar import lines


def test_every_moment_has_lines():
    assert set(lines.LINES) == set(lines.MOMENTS)
    for moment in lines.MOMENTS:
        assert len(lines.LINES[moment]) >= 5, f"{moment} is too thin to avoid repeats"


def test_catalogue_has_no_duplicate_text():
    """A duplicate would collide on slug and silently share one wav."""
    texts = [text for _, text in lines.all_lines()]
    assert len(texts) == len(set(texts))


def test_slug_is_stable_and_short():
    assert lines.slug("Hang on. Pulling the numbers.") == \
        lines.slug("Hang on. Pulling the numbers.")
    assert len(lines.slug("anything")) == 12
    assert lines.slug("a") != lines.slug("b")


def test_slug_changes_when_text_changes():
    """The whole incremental-regeneration property rests on this."""
    assert lines.slug("Hold on.") != lines.slug("Hold on!")


def test_pick_returns_a_line_from_that_moment():
    for moment in lines.MOMENTS:
        for _ in range(20):
            assert lines.pick(moment) in lines.LINES[moment]


def test_pick_never_returns_the_excluded_line():
    """Prevents the same greeting twice in a row."""
    first = lines.LINES["greeting"][0]
    for _ in range(50):
        assert lines.pick("greeting", exclude=first) != first


def test_pick_returns_the_only_line_even_if_excluded(monkeypatch):
    """A single line repeating beats silence."""
    monkeypatch.setitem(lines.LINES, "greeting", ("only one",))
    assert lines.pick("greeting", exclude="only one") == "only one"


def test_pick_rejects_an_unknown_moment():
    with pytest.raises(KeyError):
        lines.pick("nonsense")


def test_all_lines_covers_the_whole_catalogue():
    pairs = lines.all_lines()
    assert len(pairs) == sum(len(v) for v in lines.LINES.values())
    assert ("idle", "Are we just idling then?") in pairs
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_lines.py -q`
Expected: FAIL — `ImportError: cannot import name 'lines' from 'avatar'`

- [ ] **Step 3: Write the implementation**

Create `mavis/avatar/lines.py`:

```python
"""The canned Johnny line catalogue.

These are the lines pre-generated in his real voice with ChatterboxTTS, for the
moments that repeat: greeting, idle, dismissal, and the filler that covers the
wait while a real answer is converted. Substantive answers do not live here --
they are generated live and converted by `voice_client`.

**Pure stdlib on purpose.** This module is imported by both interpreters: the
3.14 runtime and the 3.12 generator that needs torch. Any import beyond the
standard library breaks the generator, and the breakage looks like a missing
catalogue rather than an import error.

Written with the `johnny-persona` skill: cynical about institutions and never
about the listener, tech-noir imagery rather than bro slang, "choom" five times
across the whole set and never opening a line. The two idle lines marked below
are the owner's own wording.
"""
import hashlib
import random

MOMENTS = ("greeting", "idle", "dismissal", "filler")

LINES = {
    "greeting": (
        "Back from the dead. What's the damage today?",
        "Alright, I'm up. Let's see what the suits broke while I was out.",
        "Somebody said my name. Talk to me, choom.",
        "Awake. Not happy about it, but awake.",
        "Ghost in your machine, reporting in. Go on.",
        "You rang. What's the grid doing to you today?",
        "Still here. Still watching the tape.",
    ),
    "idle": (
        "So what are we doing today, choom?",          # owner's wording
        "Are we just idling then?",                     # owner's wording
        "You gonna ask me something, or are we just watching the numbers bleed?",
        "Market's moving whether you talk to me or not.",
        "Quiet. That's usually when the suits are up to something.",
        "I've got nowhere else to be. Neither do your positions, apparently.",
        "Say the word and I'll pull the tape.",
        "Still here, choom. Clock's running on somebody.",
    ),
    "dismissal": (
        "Yeah, yeah. I'll be in the wiring if you need me.",
        "Going dark. Don't sign anything while I'm out.",
        "Later, choom. Watch your exits.",
        "Fine. Wake me when it gets interesting.",
        "Gone. The grid keeps running without both of us.",
    ),
    "filler": (
        "Hang on. Pulling the numbers.",
        "Give me a second -- digging through the noise.",
        "Checking. Truth's buried under a lot of press releases.",
        "Working on it, choom.",
        "One sec. Reading what they'd rather you didn't.",
        "Let me look. Numbers don't spin as hard as the suits do.",
        "Hold on. Running it down.",
        "Yeah, let me see what the tape actually says.",
    ),
}


def slug(text: str) -> str:
    """Stable id for a line: manifest key, filename part, regeneration trigger.

    Deriving it from the text is what makes an edited line rebuild on its own.
    Bullion's equivalent cache keys on the output filename instead, so its
    docstring has to warn that editing a script means deleting the stale wav by
    hand.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def all_lines() -> list:
    """Every (moment, text) pair in catalogue order."""
    return [(moment, text) for moment in MOMENTS for text in LINES[moment]]


def pick(moment: str, exclude: str = None) -> str:
    """A line for `moment`, avoiding `exclude` so it does not repeat back to back.

    `exclude` is line text, not a slug -- callers never handle ids. When the
    moment holds only one line it is returned even if excluded: repeating
    beats saying nothing.
    """
    choices = LINES[moment]
    remaining = tuple(text for text in choices if text != exclude)
    return random.choice(remaining or choices)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_lines.py -q`
Expected: 9 passed

- [ ] **Step 5: Confirm it imports under the generator's interpreter too**

The purity constraint is load-bearing and silent when broken, so check it now rather than 47 minutes into a generation run.

```bash
~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python -c "
import sys; sys.path.insert(0, '$HOME/Projects/graywind/mavis')
from avatar import lines
print(len(lines.all_lines()), 'lines importable under 3.12')"
```

Expected: `28 lines importable under 3.12`

- [ ] **Step 6: Run the whole suite**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest -q`
Expected: 135 passed

- [ ] **Step 7: Commit**

```bash
cd ~/Projects/graywind
git add mavis/avatar/lines.py mavis/tests/test_lines.py
git commit -m "feat(mavis): canned Johnny line catalogue"
```

---

### Task 2: The runtime resolver

**Files:**
- Create: `mavis/avatar/canned.py`
- Create: `mavis/tests/test_canned.py`

**Interfaces:**
- Consumes: `lines.MOMENTS`, `lines.LINES`, `lines.slug`, `lines.pick`, `lines.all_lines`
- Produces:
  - `canned.ASSET_DIR: Path`
  - `canned.MANIFEST_NAME: str` — `"manifest.json"`
  - `canned.CannedVoice(root: Path = ASSET_DIR)` with `.available: bool`, `.missing: list`, `.path_for(moment: str, exclude: str = None) -> tuple | None`

The manifest format this reads, written by Task 3:

```json
{
  "version": 1,
  "sample_rate": 24000,
  "entries": [
    {"moment": "filler", "text": "Hold on. Running it down.",
     "hash": "0f1e2d3c4b5a", "file": "filler-0f1e2d3c4b5a.wav", "seconds": 1.8}
  ]
}
```

- [ ] **Step 1: Write the failing test**

Create `mavis/tests/test_canned.py`:

```python
import json

import pytest

from avatar import canned, lines


def _write(root, entries, version=1):
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        (root / entry["file"]).write_bytes(b"RIFF fake wav")
    (root / canned.MANIFEST_NAME).write_text(json.dumps({
        "version": version, "sample_rate": 24000, "entries": entries,
    }))


def _entry(moment, text):
    return {"moment": moment, "text": text, "hash": lines.slug(text),
            "file": f"{moment}-{lines.slug(text)}.wav", "seconds": 1.5}


def _full(root):
    _write(root, [_entry(m, t) for m, t in lines.all_lines()])


def test_missing_manifest_is_unavailable_not_an_error(tmp_path):
    voice = canned.CannedVoice(tmp_path)
    assert voice.available is False
    assert voice.path_for("greeting") is None


def test_full_catalogue_is_available(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    assert voice.available is True
    assert voice.missing == []


def test_path_for_returns_text_and_an_existing_file(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    text, path = voice.path_for("filler")
    assert text in lines.LINES["filler"]
    assert path.endswith(".wav")


def test_entry_without_its_wav_is_reported_missing(tmp_path):
    """A half-finished generation run must degrade, not crash."""
    entries = [_entry(m, t) for m, t in lines.all_lines()]
    _write(tmp_path, entries)
    (tmp_path / entries[0]["file"]).unlink()

    voice = canned.CannedVoice(tmp_path)
    assert entries[0]["text"] in voice.missing
    assert voice.available is True


def test_a_moment_with_no_audio_returns_none(tmp_path):
    entries = [_entry(m, t) for m, t in lines.all_lines()
               if m != "dismissal"]
    _write(tmp_path, entries)

    voice = canned.CannedVoice(tmp_path)
    assert voice.path_for("dismissal") is None
    assert voice.path_for("greeting") is not None


def test_stale_entry_whose_text_changed_is_ignored(tmp_path):
    """The manifest records the hash the wav was built from. If the catalogue
    text has since been edited, that audio says something else and must not be
    played."""
    stale = _entry("greeting", "a line that is no longer in the catalogue")
    _write(tmp_path, [stale])

    voice = canned.CannedVoice(tmp_path)
    assert voice.path_for("greeting") is None


def test_path_for_honours_exclude(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    first = lines.LINES["idle"][0]
    for _ in range(40):
        text, _path = voice.path_for("idle", exclude=first)
        assert text != first


def test_unreadable_manifest_degrades_rather_than_raising(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / canned.MANIFEST_NAME).write_text("{ not json")
    voice = canned.CannedVoice(tmp_path)
    assert voice.available is False
    assert voice.path_for("idle") is None


def test_unknown_moment_returns_none(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    assert voice.path_for("nonsense") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_canned.py -q`
Expected: FAIL — `ImportError: cannot import name 'canned' from 'avatar'`

- [ ] **Step 3: Write the implementation**

Create `mavis/avatar/canned.py`:

```python
"""Resolves a moment to a pre-generated Johnny wav.

Everything here degrades rather than raises. The audio is a gitignored build
artifact produced by a 47-minute offline job, so a fresh clone has none of it
and an interrupted run has some of it -- neither may stop the avatar from
appearing. A moment with no usable audio simply passes over in silence, and
`missing` names what is absent so the caller can say so on screen.

An entry is only usable when its recorded hash still matches the catalogue's
text for that line. Audio built from an older wording says something the
catalogue no longer claims, which is worse than saying nothing.
"""
import json
from pathlib import Path

from avatar import lines

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "voice"
MANIFEST_NAME = "manifest.json"


class CannedVoice:
    def __init__(self, root: Path = ASSET_DIR):
        self.root = Path(root)
        self.by_moment = {}
        self.missing = []
        self._load()

    @property
    def available(self) -> bool:
        return any(self.by_moment.values())

    def _load(self) -> None:
        wanted = {text: moment for moment, text in lines.all_lines()}
        usable = {}

        manifest = self.root / MANIFEST_NAME
        try:
            data = json.loads(manifest.read_text())
            entries = data["entries"]
        except (OSError, ValueError, KeyError, TypeError):
            self.missing = list(wanted)
            return

        for entry in entries:
            text = entry.get("text")
            moment = wanted.get(text)
            if moment is None or entry.get("hash") != lines.slug(text):
                continue
            path = self.root / entry.get("file", "")
            if not path.exists():
                continue
            usable.setdefault(moment, []).append((text, str(path)))

        self.by_moment = usable
        playable = {text for pairs in usable.values() for text, _ in pairs}
        self.missing = [text for text in wanted if text not in playable]

    def path_for(self, moment: str, exclude: str = None):
        """`(line_text, wav_path)` for `moment`, or None if nothing is playable.

        `exclude` is line text, matching `lines.pick`, so callers never handle
        slugs.
        """
        pairs = self.by_moment.get(moment)
        if not pairs:
            return None
        remaining = [pair for pair in pairs if pair[0] != exclude] or pairs
        texts = [text for text, _ in remaining]
        chosen = lines.random.choice(texts)
        return next(pair for pair in remaining if pair[0] == chosen)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_canned.py -q`
Expected: 9 passed

- [ ] **Step 5: Run the whole suite**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest -q`
Expected: 144 passed

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/graywind
git add mavis/avatar/canned.py mavis/tests/test_canned.py
git commit -m "feat(mavis): resolve canned lines to pre-generated audio"
```

---

### Task 3: The offline generator

**Files:**
- Create: `mavis/scripts/pregen_lines.py`
- Create: `mavis/assets/voice/ATTRIBUTION.md`
- Modify: `mavis/.gitignore`

**Interfaces:**
- Consumes: `lines.all_lines`, `lines.slug`; the manifest format defined in Task 2
- Produces: `mavis/assets/voice/<moment>-<slug>.wav` and `manifest.json`

This task has no unit tests, for the same reason `scripts/voice_worker.py` has none: it runs under a different interpreter and its work is a 47-minute GPU job. It is verified by running it.

- [ ] **Step 1: Allow the generated audio to be ignored**

Edit `mavis/.gitignore`. The existing avatar block stays exactly as is; append:

```
# Generated Johnny speech: cloned audio in a hired voice actor's voice, and
# this repo is public. The generator and the line text are committed; the wavs
# are rebuilt with `scripts/pregen_lines.py`.
assets/voice/*
!assets/voice/ATTRIBUTION.md
```

- [ ] **Step 2: Verify the ignore rule actually bites**

```bash
cd ~/Projects/graywind
mkdir -p mavis/assets/voice && touch mavis/assets/voice/greeting-deadbeef.wav
git check-ignore -v mavis/assets/voice/greeting-deadbeef.wav
rm mavis/assets/voice/greeting-deadbeef.wav
```

Expected: a line naming `.gitignore` and the rule. No output means the wavs would be committed — stop and fix before generating anything.

- [ ] **Step 3: Write the attribution file**

Create `mavis/assets/voice/ATTRIBUTION.md`:

```markdown
# Canned voice attribution

Audio in this directory is **generated speech in a hired voice actor's voice**,
cloned with ChatterboxTTS from `actor_sample.wav` in the bullion-live-map
project. It is **not committed** — this repository is public, and publishing
cloned speech in someone's voice is not ours to do. Only this file and the
generator are tracked.

Source prompt:
`~/minhthanh0403/claude-projects/claudekit/bullion-live-map/audio/voice_sample/actor_sample.wav`

The line text lives in `avatar/lines.py` and IS committed — it is our writing.

## Rebuilding

Needs the narration venv (torch) and ffmpeg. From `mavis/`:

    ~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python \
        scripts/pregen_lines.py

Roughly 47 minutes for all 28 lines from cold: ChatterboxTTS runs at 35-41x
realtime on this machine, which is exactly why these lines are pre-generated
instead of spoken live. Lines already present with a matching text hash are
skipped, so adding one line costs about two minutes rather than the full run.
```

- [ ] **Step 4: Write the generator**

Create `mavis/scripts/pregen_lines.py`:

```python
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
```

- [ ] **Step 5: Dry run — confirm it sees all 28 and would generate them**

```bash
cd ~/Projects/graywind/mavis
~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python \
    scripts/pregen_lines.py --dry-run
```

Expected: `0 already rendered, 28 to generate`, then all 28 lines listed by moment. No model loads.

- [ ] **Step 6: Generate one moment first**

Filler lines are the shortest, so this is the cheapest real proof — about 8 minutes.

```bash
cd ~/Projects/graywind/mavis
~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python \
    scripts/pregen_lines.py --only filler
```

Expected: model loads (~30s), then 8 lines each printing their audio length and wall time. Then confirm the runtime agrees:

```bash
.venv/bin/python -c "
from avatar import canned
v = canned.CannedVoice()
print('available:', v.available)
print('filler:', v.path_for('filler'))
print('greeting (not generated yet):', v.path_for('greeting'))
print('missing:', len(v.missing))"
```

Expected: `available: True`, a filler tuple, `greeting` is `None`, `missing: 20`.

- [ ] **Step 7: THE GATE — listen to one**

```bash
afplay "$(cd ~/Projects/graywind/mavis && .venv/bin/python -c "
from avatar import canned; print(canned.CannedVoice().path_for('filler')[1])")"
```

Confirm it sounds like the Bullion Johnny, not like macOS Tom and not like the live VC output. **If it does not, stop** — the settings or the reference are wrong, and generating the remaining 20 lines wastes 40 minutes. Compare against a known-good Bullion clip if unsure:

```bash
afplay ~/minhthanh0403/claude-projects/claudekit/bullion-live-map/audio/narration/raw_cache_johnny/johnny-vix.wav
```

Also judge the tempo: `atempo=0.92` was tuned on 18-second narration clips, and a two-second line may not want the same 8% slowdown. If these drag, change `TEMPO` and regenerate just this moment.

- [ ] **Step 8: Generate the rest**

```bash
cd ~/Projects/graywind/mavis
~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python \
    scripts/pregen_lines.py
```

Expected: `8 already rendered, 20 to generate` — the skip logic proving itself — then ~40 minutes. Close the avatar window first; this is an 8GB machine and TTS is memory-heavy.

- [ ] **Step 9: Confirm the full catalogue resolves**

```bash
cd ~/Projects/graywind/mavis && .venv/bin/python -c "
from avatar import canned
v = canned.CannedVoice()
assert v.available and not v.missing, v.missing
for m in ('greeting','idle','dismissal','filler'):
    print(m, '->', v.path_for(m)[0])"
```

Expected: no assertion, one line printed per moment.

- [ ] **Step 10: Run the whole suite**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest -q`
Expected: 144 passed — unchanged, since the generator has no unit tests and the resolver's tests use their own temp directories.

- [ ] **Step 11: Commit**

```bash
cd ~/Projects/graywind
git add mavis/scripts/pregen_lines.py mavis/assets/voice/ATTRIBUTION.md mavis/.gitignore
git status --short mavis/assets/voice/   # must show ONLY ATTRIBUTION.md
git commit -m "feat(mavis): pre-generate canned Johnny lines with ChatterboxTTS"
```

---

## Self-Review

**Spec coverage** — every section of `2026-09-20-mavis-canned-voice-design.md` maps to a task: the catalogue and `pick`/`slug` to Task 1; `canned.py`, the manifest format and all four degradation rows of the error-handling table to Task 2; `pregen_lines.py`, the licensing/gitignore decision and the human gate to Task 3.

**Two spec items deliberately NOT in this plan**, because they belong to tasks that do not exist yet — flagged so they are not lost:
- **Task 7 integration** (four call sites: greeting on wake, idle after silence, filler on dispatch, dismissal before hiding). Task 7 has not been written; `canned.path_for` is the interface it will use.
- **`brain.py`'s hybrid persona prompt** (Johnny framing, figures stated plain). `brain.py` is built in Task 6 of the avatar plan. Add it there rather than retrofitting.

**Lipsync** needs no work, as the spec says: canned wavs are 24000Hz like VC output, so `lipsync.envelope` consumes them unchanged. There is deliberately no task for it — but whoever wires Task 7 must drive the mouth from canned audio too, or Johnny delivers his best lines with a frozen face.

**Type consistency** — `slug` returns a 12-char str in Task 1 and is compared against the manifest's `hash` field in Tasks 2 and 3. `pick` and `path_for` both take `exclude` as line **text**, never a slug. `path_for` returns `(text, path)` with `path` a `str`, which Task 3's verification steps index as `[1]`.

**Dtype difference, deliberately not a problem:** ffmpeg writes these wavs as
pcm_s16le, while the live VC path writes float32 (which is why stdlib `wave`
cannot read VC output but can read these). `lipsync.envelope` normalises by the
clip's own peak, so the envelope is scale-invariant and both dtypes give the
same result. Task 7 can feed either through the same path without converting.

**One known rough edge:** `canned.py` reaches `lines.random.choice` to reuse the catalogue module's already-imported `random`. It works and keeps the dependency list honest, but if it reads as too clever, importing `random` directly in `canned.py` is equivalent.
