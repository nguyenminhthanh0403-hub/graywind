# MAVIS Night 4 — Johnny Avatar, Tasks 1-4 + 8 — Session Handoff

**Written:** 2026-09-20 · **For:** whoever resumes MAVIS Night 4. Tasks 1, 2, 3, 4 and the
deferred Task 8 are **done, committed and green**. The avatar renders CD Projekt Red's actual
Johnny, moves his jaw, idles convincingly, and understands "that's all". Resume at **Task 5,
the warm voice worker** — the plan's own most failure-prone task.

This **replaces** `graywind-mavis-avatar-execution-handoff.md` (2026-09-19). That file is
still on disk and correct about the *architecture*, but several of its factual claims have
since been disproved — see "What has changed". Read this file first; fall back to it only
for background on locked decisions.

## Goal

A wake-word-triggered desktop presence: say **"Wake up, Johnny"** and a rendered, animated
Johnny Silverhand appears, answers a spoken question in a Johnny-styled voice with his mouth
moving, and disappears when told to stop. Nights 1-3 (Groq `/ask`, Bullion grounding, MCP
wrapper) are done and unrelated — don't reopen them.

- Spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- Plan: `docs/superpowers/plans/2026-09-19-mavis-avatar.md` — 7 TDD tasks **plus a deferred
  Task 8 appended at the end**
- Progress ledger: the plan's own checkboxes. Tasks 1-4 are ticked; Tasks 5-7 are not.
- Prior handoff (background only): `docs/superpowers/graywind-mavis-avatar-execution-handoff.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind && git log --oneline bde13f3..HEAD` — expect **14 commits** on
   `feat/mavis-avatar`, newest `308e11c`.
2. `cd mavis && .venv/bin/python -m pytest -q` — expect **113 passed**. If the three
   `keanu` tests *skip*, the gitignored model has not been built on this machine; see
   "Rebuilding the avatar model" below.
3. Re-invoke the `delegate` skill — delegate-first execution, Claude as reviewer/QC, with an
   explicit approval gate before each commit. **Note the standing exception:** where the plan
   already contains the implementation verbatim, delegating is transcription with no token
   saving, and delegate's Task 1 draft was defective and discarded. Tasks 1-4 were written
   directly for that reason. Task 5 is substantial new code, so delegate genuinely applies.
4. The plan is the authority on what each task builds. **Trust the plan's checkboxes and
   `git log` over any recollection** — but see the warning in "risks": the plan's code blocks
   have now been wrong three times, and only measurement caught it.
5. **Immediate next action:** Task 5, Step 1 — write `mavis/scripts/voice_worker.py`. Read
   the whole of Task 5 first; its central trap is described below and in the plan.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, **14 commits ahead** of base `bde13f3` on `main`. Nothing is
uncommitted. **113 tests pass.**

**Shipped this session (newest first):**

| Commit | What |
|---|---|
| `308e11c` | Task 4 — spoken dismissal (`avatar/dismiss.py`) |
| `2526bda` | Task 8 — idle motion on real joints |
| `de337b1` | Fix: last 6 materials textured; simplepbr double-init |
| `96baee1` | Docs: model swap noted in Task 2 as-built |
| `dee78e6` | **Model swapped to the CDPR Johnny**, jaw-driven mouth |
| `d306f45` | `.bam` guard + framing fallback (**see trap below**) |
| `6546a82` | `MOUTH_GAIN` set from corrected framing; gate recorded |
| `1c5ebce` | **Fix: the Task 1 repair silently corrupted the model** |
| `98f0106` | Docs: corrected an overstated gate record |
| `8912b59` | Task 3 — audio envelope → mouth (`avatar/lipsync.py`) |
| `7aeefd4` | Task 2 — `avatar/scene.py` |
| `53b6e19` | Task 1 — asset + `tools/repair_gltf.py` |

**Files created / changed:**
- `mavis/avatar/scene.py` — window, model, framing, lighting, mouth, idle. Supports **two
  models with two different mouth mechanisms**; see below.
- `mavis/avatar/lipsync.py` — `envelope()` / `amount_at()`, pure, no I/O.
- `mavis/avatar/dismiss.py` — `is_dismissal()`, pure.
- `mavis/tools/repair_gltf.py` — strips redundant aliased UV sets from `jonny.glb`.
- `mavis/tools/fbx_to_glb.py` — Blender headless FBX → GLB converter for the CDPR model.
- `mavis/assets/avatar/ATTRIBUTION.md` — **both models' provenance and rebuild commands.**
  Read this before touching assets; it is the only copy of the keanu build recipe.
- `mavis/.gitignore` — `assets/avatar/` is now **ignore-by-default with an allowlist**.
- `mavis/tests/test_{scene,lipsync,dismiss,repair_gltf}.py`

**Files later tasks create (nothing exists yet):** `mavis/scripts/voice_worker.py`,
`mavis/avatar/{voice_client,wake,capture,stt,brain,app}.py`,
`mavis/assets/wakeword/wake_up_johnny.onnx`.

### The two models — this shapes everything

| | `jonny` | `keanu` |
|---|---|---|
| Source | Stuxed, Sketchfab, **CC BY** | KonnieGFX DeviantArt port of **CDPR's actual asset** |
| In git? | **Yes** (`jonny.glb`) | **No, and never** |
| Mouth | `mouthOpen` morph sliders | **no morphs at all** — rotate `mid_J_jaw_JNT` on axis `r` |
| Used by | the test suite | what you actually see |

`keanu` is an extracted game asset; its uploader states outright they hold no rights
("Model belongs to CD Projekt Red"), and **this repo is public**. It is therefore gitignored,
which means **`jonny` is the only model the suite can load on a fresh clone** — that is why
`scene.py` keeps both mouth mechanisms rather than the better model simply replacing the
other. Do not "simplify" that away.

`MAVIS_AVATAR=jonny|keanu` overrides selection; otherwise `keanu` is used when built.

### Rebuilding the avatar model

Both recipes are in `mavis/assets/avatar/ATTRIBUTION.md`. In short:

```bash
# jonny (committed source)
cd ~/Projects/graywind/mavis
.venv/bin/python -m tools.repair_gltf
.venv/bin/gltf2bam assets/avatar/jonny_fixed.glb assets/avatar/jonny_fixed.bam

# keanu — needs Blender (installed: /Applications/Blender.app, 5.2.2) and the
# "Keanu 3D model.rar" from DeviantArt, extracted somewhere local
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
    --python tools/fbx_to_glb.py -- "<extracted>/keanu.fbx" /tmp/keanu.glb "<extracted>" 1.8
.venv/bin/gltf2bam /tmp/keanu.glb assets/avatar/keanu.bam
```

The source archive currently sits at `~/Downloads/Keanu 3D model.rar`.

**Scratch workspace / traps:**
- ⚠️ **`docs/superpowers/graywind-mavis-avatar-execution-handoff.md` has disproved claims.**
  It says delete *seven* TEXCOORD refs, reports *68 joints*, and calls gltf2bam's ~189
  `jvtmap` warnings "harmless". All three are wrong — it carries a correction block now, but
  don't skim past it.
- ⚠️ **`~/Documents/jonny-silverhand-extracted/`** — original scratch dir from an earlier
  session. Superseded; don't edit those copies expecting the repo to change.
- ⚠️ **The session scratchpad** (`/private/tmp/claude-501/.../scratchpad/`) held all the
  throwaway probes — `probe.py`, `sheet.py`, `final_render.py`, `live_keanu.py`,
  `fbx2glb.py`. **It is session-scoped and is gone.** The one that mattered,
  `fbx2glb.py`, was promoted into the repo as `tools/fbx_to_glb.py`. The rest are trivially
  rewritten; the technique is under "Verification idioms".
- ⚠️ **`d306f45` committed 16 documents belonging to other Graywind threads.** I ran
  `git add docs/superpowers/` and swept in the punch-list and tier-rebalance handoffs (both
  *live* threads), 9 archived handoffs, and 3 unrelated plans. Its commit message does not
  mention them. Nothing was lost — they were untracked and are now preserved — but if this
  branch merges, those files land on `main` too. Decide deliberately: `git rm --cached` them
  before merging if they should stay untracked.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `dashboard-data/*.json` are untracked
leftovers from other threads.

## What has changed

Fourteen commits since `bde13f3`. The three that a resuming session most needs to understand:

**1. Task 1 shipped a silent corruption, and the Task 2 human gate is what caught it
(`1c5ebce`).** `Wolf3D_Outfit_Bottom` is interleaved at `byteStride` 60; panda3d-gltf sizes
the vertex buffer from *declared attributes*, not the stride, so the sum must equal 60:

| aliases kept | declared | rows read | result |
|---|---|---|---|
| all 7 | 108 | 557 | the original crash |
| **0 — what Task 1 shipped** | 52 | 1158 | **garbage geometry, exit code 0** |
| exactly 1 | 60 | 1004 | correct |

Deleting all seven exploded the trousers to ±18 units and put the camera *inside* the model,
which rendered as a featureless grey mass. Keeping `TEXCOORD_1` fixes it; joints went 68 → 77
and the "harmless" `jvtmap` warnings vanished entirely.
`test_declared_attributes_fill_the_byte_stride` guards the tool;
`test_no_mesh_escapes_the_model_bounds` guards the built artifact.

**2. The model was swapped (`dee78e6`)** at the owner's request, after the Stuxed likeness was
judged poor. Two candidates were ruled out and should **not** be re-hunted: Tristan McGuire's
Sketchfab fanart is view-only with no licence and a NoAI tag; Alexandrppp's CC-BY model was
never needed once the CDPR port worked.

**3. Task 8 (idle motion) was pulled forward** at the owner's request — "make him feel alive
and then do task 4" — so it shipped before Task 4 rather than after Task 7.

## What has failed / risks / caveats

- **Nothing is failing.** 113 tests pass; the working tree is clean.

- **The plan's code blocks have been wrong three times, each time in a way its own tests
  passed.** Task 1's repair (silent corruption), Task 3's framing (61 frames for one second of
  audio, then half-a-sample-per-frame drift), Task 4's matcher (ranked a question *above* a
  dismissal — `"that's a lot"` 0.818 vs `"that's all thanks"` 0.765, so no threshold could
  separate them). In every case only **measurement against real data** exposed it. Treat Task
  5's code block as a draft to verify, not as correct.

- **UNVERIFIED — Task 5's entire premise.** No voice worker has ever been started. The
  interpreter it needs is
  `~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python`
  (Python 3.12.13, torch 2.6.0, MPS). Nothing in this session touched it.

- **Task 5's central trap, restated:** ChatterboxVC lives on Python 3.12, Panda3D runs 3.14,
  so separate processes are forced and the worker **must be persistent/warm**. A
  `subprocess.run()` per reply looks correct and silently adds ~16s of model load to *every*
  response, breaking the approved 12-15s budget. Task 5 has a pid-stability regression test
  for exactly this. **Never install torch into `mavis/.venv`.**

- **Memory is genuinely tight, and this bit once.** A live avatar window was killed by the OS
  for low memory during this session. The avatar itself is modest — **~256-300MB RSS**,
  measured with `ps` — so the kill was caused by running it alongside Blender conversions and
  repeated probe renders on an 8GB M2, not by the avatar alone. But Task 5 adds a *persistent*
  torch process (~2-3GB warm). Renderer + warm worker + OS is workable but not roomy. Close
  the avatar window before running heavy conversions.

- **Rendering costs ~16ms/frame (~63fps) at 820×820.** Almost all of it is CPU vertex skinning
  of 355 joints over ~200k verts — `idle()` and `set_mouth()` are 0.05ms each.
  `hardware-animated-vertices` makes no difference at this joint count. Acceptable, and it does
  not contend with the voice worker, which by design finishes *before* the renderer animates.
  If it ever needs cutting, the hair mesh alone is 82,934 verts.

- **Latency is a rate, not a flat cost.** Voice conversion runs ~1.4x realtime (6.67s in →
  9.19s out). A 20s answer costs ~28s. `brain.MAX_ANSWER_CHARS` exists for this; don't raise
  it casually.

- **Known latent issue, documented not fixed:** `openwakeword==0.6.0` declares
  `tflite-runtime` on Linux, which ships no wheel past cp311, so `requirements.txt` will not
  install on Linux with Python ≥3.12. Harmless here (macOS, `inference_framework="onnx"`).

- **The wake model does not exist.** "Wake up, Johnny" is not one of openWakeWord's six
  shipped models. Task 6 Step 1 is a one-time ~1hr Google Colab training run.

- **Three plan steps still need a human at the keyboard:** Task 5 Step 6 (listening to the
  converted voice), Task 6 Step 9 (speaking the wake phrase), Task 7 Step 6 (full live
  acceptance). No subagent can sign these off. Task 2's gate is already passed.

### Decisions carried forward that override the plan

- **`MOUTH_GAIN` no longer exists.** Mouth config is per-model inside `scene.AVATARS`. The
  public interface Tasks 5-7 depend on is unchanged: `set_mouth(0.0..1.0)`.
- **No blink, despite 70 eyelid joints on the rig.** An earlier note called blinking the
  biggest win per unit effort; that is wrong for *this* model — he wears opaque aviators and
  the eyes are not visible at all. Verified by rendering the face close up.
- **Idle motion must stay model-agnostic.** Channels name Valve/CDPR bones; `jonny` has none
  of them and must degrade to the whole-actor sway. That path is tested.

## What's next (ordered)

1. **Task 5 — the warm voice worker.** Plan line ~947. Delegate-first, then `code-review`,
   then approval before commit.
   - Step 1: `mavis/scripts/voice_worker.py` (runs under 3.12, newline-JSON protocol)
   - Step 2-5: `avatar/voice_client.py` + `tests/test_voice_client.py`
   - **Step 6 is a human gate** — listen to the converted audio.
   - Before writing: measure the real model-load cost with a *warm* second call, not the
     first. That is how ChatterboxTTS was ruled out and ChatterboxVC chosen.
2. **Task 6** — wake word, capture, STT, answers. Step 1 is the out-of-band Colab training run
   producing `wake_up_johnny.onnx`; start it early, it is ~1hr of wall time.
3. **Task 7** — the state machine and the full live acceptance run.
4. Finish with `superpowers:finishing-a-development-branch` to decide how `feat/mavis-avatar`
   lands — and settle the `d306f45` stray-files question before merging.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — currently **113 passing**. Keep it green.
  Three `keanu` tests skip automatically where the gitignored asset is absent.
- **Render offscreen and look at the pixels yourself.** This is the single highest-value
  technique found this session — it localised the grey-mass bug in one step after two rounds
  of asking the owner to describe what they saw:
  ```python
  loadPrcFileData("", "window-type offscreen\nwin-size 420 420\n")
  ...
  img = PNMImage(); base.win.getScreenshot(img); img.write(path)
  ```
  Two traps: step `base.taskMgr.step()` rather than `renderFrame()` (simplepbr feeds
  `camera_world_position` from a task, and `renderFrame()` alone trips a shader assertion),
  and `getScreenshot()` with no argument returns a `Texture`, not an image. Reserve the
  owner's eyes for judgement calls pixels cannot settle — "does this read as talking".
- **Measure against realistic data before trusting a matcher or a signal path.** Task 3 and
  Task 4 both passed their own tests while being wrong. A 20-line probe over realistic inputs
  caught both.
- **`bundle.forceUpdate()` after moving any slider or controlled joint.** Every mouth and idle
  mechanism in this project has needed it; without it the change is a silent no-op. This has
  now cost debugging time twice.
- **Never trust a "feature is missing" claim without checking the right API.** The original
  "this model has no mouth" blocker was a false negative from searching the scene graph for
  `CharacterSlider`s, which live in the `PartBundle`.
- **Never trust a library/wheel claim without a real install** — `pip install --dry-run
  --only-binary=:all:` is how the `sounddevice==0.5.3` pin was validated rather than guessed.
