# MAVIS Night 4 — Johnny Avatar Execution — Session Handoff

**Written:** 2026-09-19 · **For:** whoever resumes MAVIS Night 4 — the brainstorm is finished, a spec and plan are committed, and Task 1 of 7 is implemented but **not committed and not approved**. Resume by getting Task 1 approved, then running the Task 2 render gate.

This **replaces** `graywind-mavis-night4-avatar-brainstorm-handoff.md` (2026-09-19, earlier the same night). That file is still on disk and is still useful as history, but **most of its open questions are now answered** — read this file first, and only fall back to it for background on decisions already locked.

## Goal

A wake-word-triggered desktop presence: say **"Wake up, Johnny"** and a real 3D rendered, animated Johnny Silverhand appears, answers a spoken question in a Johnny-styled voice with his mouth moving, and disappears when told to stop. Night 3 (MCP wrapper) is done and unrelated — don't reopen it.

- Spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md` (committed, `f78ecd1`)
- Plan: `docs/superpowers/plans/2026-09-19-mavis-avatar.md` (committed, `c8ec0bb`, revised `bde13f3`) — 7 TDD tasks
- Progress ledger: none separate; the plan's checkboxes are the ledger. **Task 1 is done but its boxes are unticked** because it has not been approved.
- Prior handoff (background only): `docs/superpowers/graywind-mavis-night4-avatar-brainstorm-handoff.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind && git log --oneline -4 main && git status --short | grep mavis` — confirm the three docs commits are on `main` and Task 1's files are still uncommitted.
2. Re-invoke the `delegate` skill — the user chose **delegate-first execution** (option 1 of 3) for this plan. Claude is the reviewer/QC layer; `code-review` after each task and an explicit approval gate before committing are both mandatory.
3. The plan file is the authority on what each task builds. Trust it and `git log` over any recollection.
4. **Immediate next action:** ask the user to approve Task 1's commit (it is finished and reviewed, see below), then get them to run the **Task 2 render gate** — the single unverified premise of the whole design.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, **0 commits ahead of `main`** (`bde13f3`). The spec/plan commits landed on `main` *before* the branch was cut, which is why `git log main..HEAD` is empty. All of Task 1's work is uncommitted.

**Task 1 — implemented, reviewed, UNCOMMITTED, UNAPPROVED.** `git add -An mavis/` stages exactly these seven:
- `mavis/tools/repair_gltf.py` — strips aliased `TEXCOORD_1..7` so `panda3d-gltf` can convert the model
- `mavis/tools/__init__.py` — makes `from tools import repair_gltf` resolve
- `mavis/tests/test_repair_gltf.py` — 9 tests
- `mavis/assets/avatar/jonny.glb` — 2MB source asset (Sketchfab "Original format")
- `mavis/assets/avatar/ATTRIBUTION.md` — CC-BY credit; **licence condition, not decoration**
- `mavis/requirements.txt` — adds panda3d/panda3d-gltf/panda3d-simplepbr/openwakeword/sounddevice/numpy
- `mavis/.gitignore` — excludes the two build artifacts

**Build artifacts (correctly gitignored, regenerate rather than hunt for them):**
- `mavis/assets/avatar/jonny_fixed.glb` and `jonny_fixed.bam` (22MB) — rebuild with
  `.venv/bin/python -m tools.repair_gltf && .venv/bin/gltf2bam assets/avatar/jonny_fixed.glb assets/avatar/jonny_fixed.bam`

**Files later tasks create (nothing exists yet):** `mavis/avatar/` (scene, lipsync, dismiss, voice_client, wake, capture, stt, brain, app), `mavis/scripts/voice_worker.py`, `mavis/assets/wakeword/wake_up_johnny.onnx`.

**Scratch workspace / traps:**
- ⚠️ `~/Documents/jonny-silverhand-extracted/` — the original scratch dir. `jonny_fixed.glb`/`.bam`/`strip_uvs.py` there are **superseded** by the repo copies; don't edit them expecting the repo to change. `render_test.py` there is a **throwaway** with its own inline lighting and slider walk — useful for the gain sweep, but it does **not** exercise `avatar/scene.py`, so it cannot satisfy the Task 2 gate on its own.
- ⚠️ `~/Documents/jonny-silverhand-extracted/textures/` — **24 dead files.** All 20 textures are embedded in the GLB's binary chunk as `bufferView`s with no external `uri`. Do not copy them into the repo; the plan was corrected on this point.
- ⚠️ `~/Documents/jonny_silverhand.glb` (the "GLB Converted format" download) and the untried `.gltf` format — **both moot.** See "What has changed". Do not re-download or re-test them.

**Not mine — leave alone:** `git status` shows many untracked files from other concurrent Graywind threads (`.DS_Store`, `.claude/`, `dashboard-data/*.json`, and handoffs/plans for tier-rebalance, punch-list, MCP-wrapper). Two of those are *other threads' current* handoffs (`graywind-punch-list-execution-handoff.md`, `graywind-tier-rebalance-and-split-fix-handoff.md`); they were deliberately **not archived** by this session despite the 2-file retention convention, because archiving another live thread's handoff would break its resume. Archive them only if those threads are actually closed.

## What has changed

Since `35f0ce6` (Night 3's merge), on `main`:

- `f78ecd1` — design spec.
- `c8ec0bb` — 7-task implementation plan.
- `bde13f3` — plan revisions after review: Task 2's gate now runs the shipped `avatar/scene.py` rather than the throwaway script; the dead `textures/` copy dropped; subpackage import verified in Task 1 rather than Task 7; the four human-only steps flagged.

Uncommitted on the branch: Task 1, with **59 tests passing** (50 pre-existing + 9 new).

**Two findings overturned the prior handoff's blockers. Do not re-litigate either.**

1. **The model's mouth works.** The prior handoff recorded "this avatar has no mechanism to move its mouth at all." Wrong. The file is a Ready Player Me export whose `Wolf3D_Outfit_Bottom` aliases `TEXCOORD_1..7` onto one accessor; `panda3d-gltf` miscounts vertex rows from that and dies on the *next* mesh. Nothing is malformed — every accessor count is a consistent 1004. Deleting the redundant attribute references (JSON-chunk edit, binary byte-for-byte, **no Blender**) yields **77 joints and 10 `mouthOpen`/`mouthSmile` morphs**. Verified by measured deformation: 720/2162 head vertices and all 84 teeth vertices move at slider 1.0, max displacement 0.011 units.

  > ⚠️ **CORRECTED 2026-09-19 (`1c5ebce`) — delete SIX, not seven.** Keep `TEXCOORD_1`. That primitive is interleaved at `byteStride` 60 and panda3d-gltf sizes the vertex buffer from the *declared attributes*, not the stride, so the declared sum must equal 60: all seven kept → 108 → 557 rows (the original crash); all seven deleted → 52 → **1158 rows, garbage geometry, exit code 0**; exactly one kept → 60 → 1004 rows, correct. Deleting all seven explodes `Wolf3D_Outfit_Bottom` to ±18 units and puts the camera inside it, which renders as a featureless grey mass. The "68 joints" and the "~189 harmless `jvtmap` warnings" both came from that broken build; the correct build has 77 joints and zero warnings.
2. **Why it was missed:** `findAllMatches("**/+CharacterSlider")` **cannot** find sliders — they live in the character's `PartBundle`, not the scene graph, so that search always returns 0. Walk `bundle.getChild(...)`. Drive with `applyFreezeScalar()` + `forceUpdate()` (there is no `setValue`), and read results via `GeomVertexData.animateVertices` with `hardware-animated-vertices false` — the source vertex data never changes and will look like nothing happened.

## What has failed / risks / caveats

- **Nothing has failed.** Every component has a verified path except the one below.
- **UNVERIFIED — the biggest risk in the project: no Panda3D window has ever been opened on this machine.** Every check so far ran `window-type none`. Panda3D 1.10.16 uses a deprecated OpenGL path on Apple Silicon. **Task 2 Step 6 is a hard stop:** if the window does not open, do not continue to Task 3 — the renderer choice reopens and the spec needs revisiting. That is a design decision, not a bug to work around.
- **UNVERIFIED — `MOUTH_GAIN`.** 0.011 units is ~11mm of jaw travel, which may read as a twitch rather than speech. The value in `scene.py` (currently planned at 2.0) must be set from what a human actually sees during the Task 2 gate.
- **Architectural constraint with teeth:** ChatterboxVC lives in `bullion-live-map/.venv-narration` on **Python 3.12**; Panda3D runs **3.14**. Separate processes are forced, and the voice worker **must be persistent/warm**. A `subprocess.run()` per reply looks correct and silently adds ~16s of model load to *every* response, breaking the approved 12-15s budget. Task 5 has a pid-stability regression test for exactly this. **Never install torch into `mavis/.venv`.**
- **Latency is a rate, not a flat cost.** Voice conversion runs ~1.4x realtime (6.67s in → 9.19s out). A 20s answer costs ~28s. `brain.MAX_ANSWER_CHARS` exists for this reason; don't raise it casually.
- **Known latent issue, documented not fixed:** `openwakeword==0.6.0` declares `tflite-runtime` on Linux, which ships no wheel past cp311 — so `mavis/requirements.txt` will not install on Linux with Python ≥3.12. Harmless here (macOS desktop app, `inference_framework="onnx"`), and there is a comment in the file explaining it.
- **Delegate produced a defective draft on Task 1.** Its GLB writer never emitted chunk padding (`_pad(b'', 0x20)[:n]` always returns `b''`) while declaring the unpadded length, which would push the BIN chunk off 4-byte alignment. The shipped module is the plan's version, not delegate's. `test_chunks_stay_four_byte_aligned` is the permanent guard. Expect to review delegate output rather than trust it.
- **The wake model does not exist yet.** "Wake up, Johnny" is not one of openWakeWord's six shipped models (`alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather` — there is no "hey mavis"). Task 6 Step 1 is a one-time ~1hr Google Colab training run producing `wake_up_johnny.onnx`.

## What's next (ordered)

1. **Get Task 1 approved and committed.** It is finished and reviewed; the gate is the user's explicit approval per the `delegate` workflow.
   ```bash
   cd ~/Projects/graywind
   git add mavis/tools mavis/assets mavis/requirements.txt mavis/.gitignore mavis/tests/test_repair_gltf.py
   git commit -m "feat(mavis): vendor Johnny avatar asset and its glTF repair tool"
   ```
2. **Task 2 — build `avatar/scene.py`** per the plan (delegate first, then `code-review`, then approval).
3. **Task 2 Step 6 — THE GATE. A human must run this and look at the screen.** It must exercise the shipped module, not the throwaway:
   ```bash
   cd ~/Projects/graywind/mavis
   .venv/bin/python -c "
   from panda3d.core import loadPrcFileData
   loadPrcFileData('', 'window-title Johnny\nhardware-animated-vertices false')
   from direct.showbase.ShowBase import ShowBase
   from avatar import scene as m
   import math
   base = ShowBase(); s = m.AvatarScene(base)
   base.taskMgr.add(lambda t: (s.idle(t.time),
       s.set_mouth(math.sin(t.time*5)*0.5+0.5), t.cont)[-1], 'sweep')
   base.run()"
   ```
   Confirm: the Stuxed credit is visible, a lit textured figure appears (not a black rectangle), it sways, the mouth visibly opens and closes. Then set `MOUTH_GAIN`.
4. Tasks 3-7 in plan order: lipsync → dismiss → warm voice worker → wake/STT/brain → state machine + live acceptance.
5. Finish with `superpowers:finishing-a-development-branch` for how `feat/mavis-avatar` lands.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — currently **59 passing**. Keep it green; 50 of those predate this work.
- **Never trust a library/wheel claim without a real install.** Every dependency here was confirmed with an actual `pip install --dry-run --only-binary=:all:`, which is how the `sounddevice==0.5.3` pin was validated rather than guessed.
- **Never trust a "feature is missing" claim without checking the right API.** The whole mouth-animation blocker was a false negative from searching the wrong object graph. Inspect the real structure before concluding something is absent.
- **Measure, don't estimate, latency** — with a warm second call, not the first (which includes one-time setup). This is how ChatterboxTTS was ruled out and ChatterboxVC chosen.
- **The render/audio pipeline needs a real live run.** Automated tests cover the non-GUI logic; four plan steps (Task 2/6, 5/6, 6/9, 7/6) require a human at the keyboard looking at a window or listening to audio. No subagent can sign those off.
