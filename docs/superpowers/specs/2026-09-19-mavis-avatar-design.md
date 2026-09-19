# MAVIS Night 4 — Johnny Silverhand Avatar — Design

**Written:** 2026-09-19 · **Status:** approved in chat, pending user review of this file
· **Supersedes:** the open questions in `docs/superpowers/graywind-mavis-night4-avatar-brainstorm-handoff.md`

## Goal

An ambient desktop presence: say **"Wake up, Johnny"** and a real 3D rendered,
animated Johnny Silverhand appears, answers a spoken question in a Johnny-styled
voice with his mouth moving, and disappears when told to stop.

Night 3 (MCP wrapper) is done and unrelated. This is the frontend.

## What this session resolved before designing

Two findings changed the architecture. Both were measured, not assumed.

### 1. The 3D asset's mouth works — the earlier "no morphs" read was a false negative

The handoff recorded the Sketchfab "Original format" `.glb` as corrupt
(`GeomTriangles references vertices up to 1003, but GeomVertexData has only 557
rows`) and the "GLB Converted format" as having a working skeleton but zero morph
targets — leaving the avatar with no mechanism to move its mouth at all.

Neither conclusion holds.

The model is a **Ready Player Me** export (`asset.generator`, plus `Wolf3D_*` mesh
and texture names). The "corruption" is that `Wolf3D_Outfit_Bottom` declares
`TEXCOORD_1` through `TEXCOORD_7` **all pointing at the same accessor** (index 35)
— eight UV slots aliasing one buffer. `panda3d-gltf` miscounts vertex rows from
that and dies on the following mesh. Every accessor `count` in the file is
internally consistent at 1004; nothing is actually malformed.

Deleting those seven redundant attribute *references* — a JSON-chunk edit, binary
chunk copied through byte-for-byte, ~40 lines of Python, **no Blender** — produces
a file that converts at exit 0 and retains:

- **77 joints** (Hips → Spine → Neck → Head, full finger rig, LeftEye/RightEye).
  Recorded as 68 until 2026-09-19; that count came from a build whose
  `Wolf3D_Outfit_Bottom` was being read at the wrong stride. See `1c5ebce`.
- **10 `CharacterSlider` morphs** — `mouthOpen`/`mouthSmile` on head, teeth, beard,
  and both eyes

The "zero morphs" finding came from `findAllMatches("**/+CharacterSlider")`, which
**cannot** work: sliders live in the character's `PartBundle`, not the scene graph.
Walking `bundle.getChild(...)` finds them.

Verified deformation, not just presence: driving `mouthOpen` to 1.0 via
`applyFreezeScalar` + `forceUpdate`, then reading the **animated** vertex data
(`GeomVertexData.animateVertices`, with `hardware-animated-vertices false`), moves
**720 of 2162 head vertices and all 84 teeth vertices**, max displacement
**0.011 units** on a ~1.7-unit model.

Consequences: the untried Sketchfab `.gltf` download is **moot — do not chase it**.
The repaired original beats both downloads (morphs *and* skeleton in one file).
The Blender fallback is not needed. Body-only v1 is not needed.

Artifacts live in `~/Documents/jonny-silverhand-extracted/`: `jonny_fixed.glb`,
`jonny_fixed.bam`, `strip_uvs.py`, `render_test.py`.

### 2. Chatterbox cannot share a process with the renderer

`ChatterboxVC` lives in `bullion-live-map/.venv-narration` on **Python 3.12**
(torch 2.6.0, MPS available, verified importable). MAVIS runs **Python 3.14** with
Panda3D. Two Pythons, two processes — forced, not chosen.

This invalidates the handoff's latency arithmetic unless designed around. "14.85s
model load + 1.14s reference embedding, one-time per session" holds **only if the
Chatterbox process stays alive**. The obvious implementation — `subprocess.run()`
per answer — pays ~16s of setup on *every reply*, turning the approved 12-15s into
roughly 30s.

**Therefore the voice worker is a persistent warm process.** Not an optimization;
the approved latency budget is false without it.

## Architecture

Three processes.

```
┌─ Avatar app (py3.14, mavis/.venv) ────────────┐
│  wake word · mic · Panda3D render · orchestr. │
└───────┬───────────────────────────┬───────────┘
        │ stdin/stdout JSON         │ httpx
        ▼                           ▼
┌─ Voice worker ──────────┐   ┌─ Cloud ─────────┐
│ py3.12 .venv-narration  │   │ Groq Whisper STT│
│ ChatterboxVC, warm      │   │ /ask endpoint   │
└─────────────────────────┘   └─────────────────┘
```

**Direct HTTP to `/ask`, not MCP** — settled per the handoff, carried forward
without re-litigation. Same-machine GUI app; `httpx` direct, mirroring
`mavis/mcp_tools.py`'s `call_ask`.

## Components

| File | Responsibility | Depends on |
|---|---|---|
| `avatar/wake.py` | openWakeWord custom `.onnx`, mic stream | `openwakeword`, `sounddevice` |
| `avatar/capture.py` | Record utterance post-wake, endpoint on silence | `sounddevice` |
| `avatar/stt.py` | Groq Whisper transcription | `httpx` |
| `avatar/brain.py` | `httpx` → `/ask` | `httpx` |
| `avatar/voice_client.py` | Warm-worker protocol + restart/fallback policy | stdlib |
| `scripts/voice_worker.py` | **Runs under `.venv-narration`**; ChatterboxVC warm | torch, chatterbox |
| `avatar/lipsync.py` | RMS envelope of finished audio → slider values | `numpy` |
| `avatar/scene.py` | ShowBase, model, idle motion, slider driving | `panda3d` |
| `avatar/app.py` | State machine wiring it together | all of the above |

Assets: `mavis/assets/avatar/` (repaired `.glb`/`.bam`, `strip_uvs.py`, textures,
attribution) and `mavis/assets/wakeword/wake_up_johnny.onnx`.

## Data flow

1. **Sleeping** — `openwakeword` scores mic frames. Cheap; no window shown.
2. **Wake** — score crosses threshold → window appears, idle animation starts.
3. **Capture** — record until silence endpoints the utterance.
4. **Think** — Groq Whisper → transcript → `/ask` → answer text.
5. **Speak** — `say` renders a fast scaffold WAV → warm worker converts it to the
   actor's voice → returns converted audio **plus its RMS envelope**.
6. **Animate** — play the finished audio while driving `mouthOpen` from the
   precomputed envelope.
7. **Dismiss** — transcript fuzzy-matches a dismissal phrase → window hides →
   back to Sleeping.

Step 6 reads an envelope of **already-finished** audio. That is what honors the
locked "never two heavy local neural steps concurrently" rule: by the time the
renderer animates, no neural work is running.

## Key decisions

1. **Wake phrase: "Wake up, Johnny"** — four syllables, in keyword-spotting range.
   Not one of openWakeWord's six shipped models (`alexa`, `hey_mycroft`,
   `hey_jarvis`, `hey_rhasspy`, `timer`, `weather` — there is no "hey mavis").
2. **Custom model via openWakeWord's Colab training notebook**, a one-time
   out-of-band run producing `wake_up_johnny.onnx`. Runtime loads it with
   `Model(wakeword_models=[path], inference_framework="onnx")` — note the default
   framework is `tflite` and **must** be overridden. `openwakeword.train` requires
   torch; training deps therefore **never enter the runtime venv**.
3. **Dismissal: spoken phrase only** (user's choice). Once awake we are already
   transcribing, so dismissal is a fuzzy match on the transcript against a small
   configurable list — `"that's all"`, `"go away"`, `"shut up Johnny"`. No second
   wake model needed.
4. **Voice: `ChatterboxVC`** against the actor's `actor_sample.wav` (66.8s, 22050Hz),
   applied to a `say` reading. **Not `ChatterboxTTS`** (measured 80s steady-state
   for ~2s of audio — ruled out). Latency is a **~1.4x-realtime rate**, not a flat
   cost: a 20s answer takes ~28s to convert. Cap answer length rather than pretend
   the cost is fixed.
5. **Renderer: Panda3D + `panda3d-gltf`**, chosen for the 8GB M2 constraint.
6. **Mouth overdrive gain** — 0.011 units ≈ 11mm of jaw travel at slider 1.0 may
   read as a twitch rather than speech. `MOUTH_GAIN` is a named tuning constant,
   set from the render test (candidates 1.0 / 1.5 / 2.0 / 3.0). Morph targets
   extrapolate linearly, so values above 1.0 are expected to work.
7. **Attribution** — the model is CC-BY: **"Jonny Silverhand" by Stuxed** must be
   credited on screen. Non-negotiable licence term. (It is a stylized fan
   interpretation; the creator notes the metal arm is on the wrong side.)

## Error handling

Per the project's no-silent-failure rule, every degraded path is **visible**:

| Failure | Behavior |
|---|---|
| Voice worker crashes | Restart once; if it fails again, fall back to plain `say` **with an on-screen notice**. Never silently mute. |
| Worker slow to start | Avatar still wakes and answers in text; voice joins when ready. |
| Groq unreachable | Answer shown as on-screen text, spoken fallback via `say`. |
| STT returns empty | Johnny says a short in-character "didn't catch that"; stays awake. |
| Wake model missing | Refuse to start with a specific message naming the expected path. |
| Mic permission denied | Explicit message; do not spin silently on a dead stream. |

## Testing

- **Unit** — envelope math, dismissal fuzzy matching, worker protocol framing
  (mocked subprocess), `MOUTH_GAIN` clamping.
- **Integration** — real warm-worker round trip on a short clip; assert the second
  request is dramatically faster than the first (this is the regression test that
  catches a spawn-per-request reintroduction).
- **Live acceptance** (the real gate, per this project's discipline): say
  "Wake up, Johnny" → window appears and animates → question answered in the
  converted voice with visible mouth movement → dismissal phrase → window hides.

## Implementation sequence

Full pipeline in one plan (user's choice), ordered so something is demoable early:

1. **Render foundation** — window opens, model loads, idle motion, `MOUTH_GAIN`
   fixed from the render test. Move assets into the repo; add `panda3d`,
   `panda3d-gltf`, `panda3d-simplepbr`, `openwakeword`, `sounddevice` to
   `requirements.txt` (none are in it yet).
2. **Wake word** — Colab training, drop in `.onnx`, wake/sleep state machine.
3. **Brain** — capture → STT → `/ask` → on-screen text reply.
4. **Voice** — warm worker, protocol, restart/fallback.
5. **Lip-sync** — envelope → sliders during playback.
6. **Live acceptance run.**

## Open items at time of writing

- **Render test not yet run.** Every check so far used `window-type none`. That a
  Panda3D window actually opens and draws on this Apple Silicon Mac (1.10.16 uses a
  deprecated OpenGL path) is the **single largest unverified assumption** in this
  design. `render_test.py` exists and is step 1 of implementation. If the window
  fails to open, the renderer choice — not the rest of the design — is what
  reopens.
- `MOUTH_GAIN` value pending that same run.
- The VC-based voice is **not identical** to Bullion's `ChatterboxTTS` Johnny clips:
  same target identity, different generation mechanism. Not compared side by side.
