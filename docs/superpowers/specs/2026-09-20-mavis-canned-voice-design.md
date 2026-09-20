# MAVIS — Hybrid Voice: Pre-generated Johnny + Live Conversion

**Date:** 2026-09-20
**Status:** Approved, not yet implemented
**Amends:** `2026-09-19-mavis-avatar-design.md`, key decision #4

## Problem

Decision #4 of the avatar spec chose `ChatterboxVC` over `ChatterboxTTS` on latency and
ruled TTS out entirely. The latency call was right. The "entirely" was too broad, and the
result does not sound like Johnny.

Measured on this machine (8GB M2, MPS) during Task 5:

| Path | Cost | A 10s answer |
|---|---|---|
| `ChatterboxVC` (in use) | ~1.5x realtime; 3.1-5.0s per short clip | ~15s |
| `ChatterboxTTS` (real Johnny) | **35-41x realtime**; 86.6s for 2.1s of audio | **~6 minutes** |

TTS load is 29.7s; VC load is 13-15s.

The deeper finding is that Bullion builds its two narrators by **different pipelines**, and
MAVIS adopted the wrong one:

| Narrator | Pipeline | Settings |
|---|---|---|
| **Alfred** (formal) | ChatterboxVC + a blended reference | — |
| **Johnny** (the target) | **ChatterboxTTS** | `exaggeration=0.8`, `cfg_weight=0.3`, then `atempo=0.92`, then `loudnorm=I=-20:TP=-2:LRA=7` |

Both prompt from the same `actor_sample.wav`, so the reference was never wrong — Johnny's
*character* comes from TTS plus that post-processing. MAVIS has been running Alfred's
pipeline and expecting Johnny's voice. Bullion never hit the latency wall because it
pre-generates all 78 node clips offline into `raw_cache_johnny/`.

## Decision

**Hybrid.** Pay TTS's cost once, offline, for the lines that repeat; keep VC live for the
lines that cannot be known in advance.

- **Pre-generated (ChatterboxTTS, real Johnny):** greeting on wake, idle prompts,
  dismissal, and thinking filler.
- **Live (ChatterboxVC, as built in Task 5):** substantive answers.

This is not a compromise on the moments that shape the impression. The user hears a canned
line *first* (greeting), *between* questions (idle), *during* every wait (filler) and
*last* (dismissal). Only the answer itself — where accuracy matters more than timbre — is
the faster, less characterful voice.

**Rejected:** running TTS live with a hard answer-length cap. At 40x realtime even a
three-second reply costs two minutes. No cap makes this viable; the ceiling is hardware,
which is exactly the abort gate in the project's own workflow.

## The line catalogue

28 lines. Written with the `johnny-persona` skill: cynical about institutions and never
about the listener, tech-noir imagery rather than bro slang, `choom` five times across the
whole set and never opening a line. No invented figures — the persona guide requires
cynicism to be anchored to a real number, and these are conversational interjections with
no figure to anchor to, so they carry attitude and imagery instead.

**greeting** (7)
1. Back from the dead. What's the damage today?
2. Alright, I'm up. Let's see what the suits broke while I was out.
3. Somebody said my name. Talk to me, choom.
4. Awake. Not happy about it, but awake.
5. Ghost in your machine, reporting in. Go on.
6. You rang. What's the grid doing to you today?
7. Still here. Still watching the tape.

**idle** (8) — items 1 and 2 are the owner's own wording, kept verbatim
1. So what are we doing today, choom?
2. Are we just idling then?
3. You gonna ask me something, or are we just watching the numbers bleed?
4. Market's moving whether you talk to me or not.
5. Quiet. That's usually when the suits are up to something.
6. I've got nowhere else to be. Neither do your positions, apparently.
7. Say the word and I'll pull the tape.
8. Still here, choom. Clock's running on somebody.

**dismissal** (5)
1. Yeah, yeah. I'll be in the wiring if you need me.
2. Going dark. Don't sign anything while I'm out.
3. Later, choom. Watch your exits.
4. Fine. Wake me when it gets interesting.
5. Gone. The grid keeps running without both of us.

**filler** (8) — shortest by design; these cover a 4-8s gap, not fill airtime
1. Hang on. Pulling the numbers.
2. Give me a second — digging through the noise.
3. Checking. Truth's buried under a lot of press releases.
4. Working on it, choom.
5. One sec. Reading what they'd rather you didn't.
6. Let me look. Numbers don't spin as hard as the suits do.
7. Hold on. Running it down.
8. Yeah, let me see what the tape actually says.

## Components

| Path | Responsibility | Interpreter |
|---|---|---|
| `mavis/avatar/lines.py` | The catalogue as data; `pick(moment, exclude=None)` | 3.14 |
| `mavis/scripts/pregen_lines.py` | Render lines to wav + manifest | **3.12** (torch) |
| `mavis/avatar/canned.py` | Resolve a moment to a playable wav path | 3.14 |
| `mavis/assets/voice/` | Generated wavs + `manifest.json` | — (gitignored) |

### `lines.py`

```python
MOMENTS = ("greeting", "idle", "dismissal", "filler")
LINES: dict[str, tuple[str, ...]]          # moment -> line texts

def slug(text: str) -> str                 # sha1(text).hexdigest()[:12]
def pick(moment: str, exclude: str = None) -> str
```

`slug` is the single identity for a line: it is the manifest's `hash` field, the filename
component, and what makes an edited line regenerate. There is no second identifier.

`pick` returns a random line's **text**, never the text passed as `exclude`, so the caller
can avoid an immediate repeat. `exclude` is line text throughout, not a slug, so callers
never handle ids. With one line in a moment, `pick` returns it even if excluded — a single
line repeating beats silence. Pure and fully testable with no audio present; this is the
module the test suite actually exercises.

### `pregen_lines.py`

Runs under the narration venv, the same interpreter as `voice_worker.py`. For each line:

1. Skip if the manifest already has an entry whose `hash` matches the current text **and**
   whose wav exists. This is the incremental property: adding a 29th line costs ~2 minutes,
   not 47.
2. `tts.generate(text, audio_prompt_path=ACTOR_SAMPLE, exaggeration=0.8, cfg_weight=0.3)`
3. `ffmpeg -filter:a "atempo=0.92,loudnorm=I=-20:TP=-2:LRA=7" -ar 24000`
4. Write `assets/voice/<moment>-<slug>.wav`; record `{moment, text, hash, file, seconds}`.

Keying the cache on a **hash of the text** rather than on the filename is a deliberate fix
to a known footgun in Bullion's equivalent: `synthesize_johnny` caches by output filename,
so its docstring has to warn that editing a script means manually deleting the stale wav.
Hashing makes an edited line regenerate on its own.

`-ar 24000` is not optional. `loudnorm` resamples to 192kHz internally and will emit that
rate unless told otherwise; 24000 also matches `ChatterboxVC`'s output, so canned and live
audio share one rate downstream.

### `canned.py`

```python
class CannedVoice:
    def __init__(self, root: Path = ASSET_DIR)
    available: bool            # manifest loaded and at least one wav present
    missing: list[str]         # lines in the catalogue with no audio
    def path_for(self, moment: str, exclude: str = None) -> tuple[str, str] | None
```

Returns `(line_text, wav_path)`, with `exclude` again being line text, so the caller can
show the text on screen and drive lipsync from the wav. Returns `None` when that moment has no usable audio, which the state machine
treats as "say nothing" rather than an error — a half-generated catalogue must degrade, not
crash.

## Integration

**Lipsync is unchanged.** Canned lines are wav files at 24000Hz, so `lipsync.envelope`
consumes them identically to converted audio. His mouth moves for the greeting exactly as
it does for an answer; nothing new is needed, but it must not be skipped, or Johnny delivers
his best lines with a frozen face.

**Task 7 (state machine)** gains four call sites: greeting on wake, idle after a silence
timeout, filler when a question is dispatched, dismissal before hiding. Each is
`canned.path_for(moment)` → play → animate, with `None` meaning skip.

**Task 6 (`brain.py`)** adopts the hybrid persona agreed with the owner: a short
Johnny-styled framing sentence, then the figures stated plainly. Persona never touches the
numbers. This keeps canned and spoken registers from clashing without putting flourish near
data the owner acts on.

## Licensing

The generated wavs are cloned speech in a hired voice actor's voice, and this repository is
public. They are **gitignored**; only the generator and the line text are committed. This
follows the precedent already set for the CDPR avatar model: `assets/` is ignore-by-default
with an explicit allowlist. `ATTRIBUTION.md` gains a section recording the actor sample's
origin and the rebuild command.

## Error handling

Per the project's no-silent-failure rule:

| Failure | Behaviour |
|---|---|
| `manifest.json` absent | `available = False`; avatar runs silent-but-visible, on-screen notice names the generator command |
| A line's wav missing | That line is excluded from `pick`; `missing` lists it |
| Every line for a moment missing | `path_for` returns `None`; that moment is skipped silently, others still work |
| `ffmpeg` absent at generation time | Generator fails loudly before spending 47 minutes in TTS |

## Testing

`lines.py` and `canned.py` are pure and get real unit tests: catalogue integrity (every
moment non-empty, no duplicate text, slugs stable), `pick` never returning `exclude`,
manifest parsing, and the degraded paths above driven with a temp directory.

`pregen_lines.py` is not unit-tested for the same reason `voice_worker.py` is not — it runs
under a different interpreter and its work is a 47-minute GPU job. It gets one human gate:
generate, listen, confirm it is Johnny.

## Out of scope

- Changing the live VC path built in Task 5. It stays exactly as committed.
- Dynamic/generated canned lines. The catalogue is static text under version control.
- Streaming or chunked TTS. At 40x realtime, chunking changes nothing.
