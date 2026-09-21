# MAVIS Night 4 — Voice and Animation — Session Handoff

**Written:** 2026-09-21 · **For:** whoever resumes MAVIS Night 4. Tasks 1-5 and the
deferred Task 8 are done, plus a whole hybrid-voice sub-project and real retargeted
animation. Johnny renders, moves, speaks in his own voice and lip-syncs. Resume at
**Task 6 (wake word, capture, STT)** — and start its Colab training run early, it is
~1hr of wall time that nothing else depends on.

This **replaces** `graywind-mavis-avatar-tasks-1-4-handoff.md` (2026-09-20). That file
is still accurate about Tasks 1-4 and the two models; read this one first and fall back
to it for detail on the `.bam` repair and the CDPR model swap.

## Goal

A wake-word-triggered desktop presence: say **"Wake up, Johnny"** and a rendered,
animated Johnny Silverhand appears, answers a spoken question in his own voice with his
mouth moving, and disappears when told to stop.

- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md` (decision #4
  is **amended** — see the voice spec)
- Avatar plan: `docs/superpowers/plans/2026-09-19-mavis-avatar.md` — 7 tasks + a
  deferred Task 8. **Tasks 1-5 and 8 ticked; 6 and 7 are not.**
- Voice spec: `docs/superpowers/specs/2026-09-20-mavis-canned-voice-design.md`
- Voice plan: `docs/superpowers/plans/2026-09-20-mavis-canned-voice.md` — all 3 tasks
  complete, final review clean
- Prior handoff (background): `docs/superpowers/graywind-mavis-avatar-tasks-1-4-handoff.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind && git log --oneline bde13f3..HEAD` — expect **28 commits**
   on `feat/mavis-avatar`, newest `fdb28c4`.
2. `cd mavis && .venv/bin/python -m pytest -q` — expect **148 passed**. If several
   `keanu` tests *skip*, the gitignored model has not been built here; see "Rebuilding".
3. Read the avatar plan's checkboxes — they are the ledger. Trust them and `git log`
   over any recollection.
4. **Immediate next action:** Task 6, Step 1 — the one-time openWakeWord Colab run that
   produces `wake_up_johnny.onnx`. It blocks nothing else, so start it, then write
   `avatar/wake.py`, `capture.py`, `stt.py`, `brain.py` while it trains.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 28 commits ahead of base `bde13f3`. Working tree clean.
**148 tests pass.**

**Shipped since the last handoff:**

| Commit | What |
|---|---|
| `5dd3c7c` `b6a92b3` | **Task 5** — warm ChatterboxVC worker + output normalisation |
| `8962217` `ad5b701` | Hybrid-voice spec and plan |
| `4de6a76`→`5924a4c` | Voice plan Tasks 1-3: catalogue, resolver, generator |
| `0732523` | **Animation** — Mixamo clips retargeted onto the rig |
| `cf484ab` | Fix: frame against the pose actually shown |
| `fdb28c4` | Fix: stop blending opaque materials |

**Modules now live:** `avatar/{scene,lipsync,dismiss,voice_client,lines,canned}.py`,
`scripts/voice_worker.py`, `tools/{repair_gltf,fbx_to_glb,retarget_anim}.py`.

**Files Tasks 6-7 create (nothing exists yet):** `avatar/{wake,capture,stt,brain,app}.py`,
`assets/wakeword/wake_up_johnny.onnx`.

### The voice is hybrid, and the reason is the important part

Bullion builds its two narrators by **different pipelines**, and MAVIS originally adopted
the wrong one:

| Narrator | Pipeline |
|---|---|
| Alfred (formal) | ChatterboxVC |
| **Johnny** | **ChatterboxTTS**, `exaggeration=0.8`, `cfg_weight=0.3`, then `atempo=0.92` + `loudnorm` |

Both prompt from the same `actor_sample.wav`, so the reference was never wrong. Live TTS
is impossible here — **measured 35-41x realtime**, 86.6s for 2.1s of audio, so a 10s
answer costs ~6 minutes. That is why Bullion pre-generates all its clips.

So: **28 canned lines** (greeting / idle / dismissal / filler) pre-rendered offline with
TTS in his real voice; **live VC only for substantive answers**, where accuracy matters
more than timbre. `avatar/lines.py` is the catalogue, `avatar/canned.py` resolves a
moment to a wav, `scripts/pregen_lines.py` generates them.

### Animation

The model ships with **no animation** — a rip is a mesh in its authoring bind pose, arms
out at 45°, which was most of why it read as a mannequin. `tools/retarget_anim.py` maps
Mixamo clips onto the ValveBiped skeleton by transferring each bone's **world-space**
rotation delta:

    tgt_rot = (src_rot @ src_rest^-1) @ tgt_rest

Identity at rest, frame-independent, so it survives the two rigs disagreeing completely
about bone orientation. Copying *local* rotations is the obvious approach and puts arms
inside the torso.

Ships `idle` and `smoking`, 250 frames each at 30fps, 22/22 bones mapped. Source clips
are Mixamo's (Adobe, free, licensed) and are **not** redistributed — currently at
`~/Documents/{Breathing Idle,Smoking}.fbx`.

**Clips and the procedural `_IdleMotion` cannot coexist.** `controlJoint` detaches a
joint from animation, and they want the same head/neck/clavicle joints. A model with
clips plays them and the procedural channels stand down; `jonny`, whose skeleton shares
none of these bones, keeps the procedural path. Both are tested.

### Rebuilding the models (neither is committed)

    # keanu, with animation — what ships
    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python tools/retarget_anim.py -- \
        "<extracted>/keanu.fbx" "<extracted>" /tmp/keanu.glb \
        "idle=<path>/Breathing Idle.fbx" "smoking=<path>/Smoking.fbx"
    .venv/bin/gltf2bam /tmp/keanu.glb assets/avatar/keanu.bam

    # canned voice — ~47 min from cold, skips lines already rendered
    <narration-venv>/bin/python scripts/pregen_lines.py

`assets/avatar/ATTRIBUTION.md` and `assets/voice/ATTRIBUTION.md` carry the full recipes
and the licence reasoning.

**Scratch workspace / traps:**
- ⚠️ **The session scratchpad is gone** — it held every probe (`retarget.py`,
  `render_pose.py`, `live_anim.py`, `desktop_test.py`). Everything that mattered was
  promoted into `tools/`. The rest are trivially rewritten.
- ⚠️ `~/Documents/Breathing Idle (1).fbx` is a byte-identical duplicate of
  `Breathing Idle.fbx`. Ignore it.
- ⚠️ **`keanu.bam` was rebuilt three times on 2026-09-21.** It is gitignored, so a fresh
  clone has nothing until the tool is re-run.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `dashboard-data/*.json`.

## What has changed

Thirteen commits since the last handoff. The three that most affect future work:

1. **The voice approach changed** (`8962217`). Avatar spec decision #4 said "not
   ChatterboxTTS — ruled out". The latency call was right; ruling it out *entirely* was
   too broad, and the result sounded like neither Tom nor the actor. Now hybrid.
2. **Animation replaced procedural idle for `keanu`** (`0732523`). Task 8's layered-sine
   motion still exists and is still tested, but only `jonny` uses it now.
3. **Two rendering bugs fixed that had been shipping since the first conversion**
   (`cf484ab`, `fdb28c4`). See below — both are the kind that hide.

## What has failed / risks / caveats

- **Nothing is failing.** 148 tests pass, tree clean, final review on the voice plan came
  back *ready to merge*.

- **UNVERIFIED — Tasks 6 and 7 entirely.** No wake word has ever been detected, no mic
  captured, no STT call made, no state machine run.

- **The wake model does not exist.** "Wake up, Johnny" is not one of openWakeWord's six
  shipped models. Task 6 Step 1 is a ~1hr Colab run.

- **Memory is genuinely tight and bit three times today.** The OS killed a generation run
  and two live windows. The avatar itself is modest (~256-300MB RSS, measured with `ps`)
  — the kills came from running it alongside Blender conversions and repeated renders on
  an 8GB M2. **Task 7 is where this gets real:** the state machine wants the renderer
  *and* a warm ~2-3GB torch worker resident simultaneously, which nothing has done yet.
  Close the avatar window before starting anything heavy.

- **The generator survives interrupts, and this was proven for real.** When the OOM kill
  landed mid-run, 22 wavs and 22 manifest entries stayed consistent and the resume
  reported "22 already rendered, 6 to generate".

- **Latency is a rate, not a flat cost.** VC runs ~1.4x realtime. `brain.MAX_ANSWER_CHARS`
  exists for this; do not raise it casually.

- **Known latent:** `openwakeword==0.6.0` declares `tflite-runtime` on Linux, which ships
  no wheel past cp311, so `requirements.txt` will not install on Linux with Python ≥3.12.
  Harmless on macOS with `inference_framework="onnx"`.

- **Three plan steps still need a human:** Task 6 Step 9 (speaking the wake phrase),
  Task 7 Step 6 (full live acceptance), and any re-judging of voice or pose.

### Decisions carried forward that override the plans

- **`MOUTH_GAIN` no longer exists.** Mouth config is per-model in `scene.AVATARS`. The
  interface Tasks 6-7 rely on is unchanged: `set_mouth(0.0..1.0)`.
- **ChatterboxVC outputs 24000Hz float32**, not the reference clip's 22050. Task 7 must
  pass 24000 to `lipsync.envelope` or the mouth drifts ~1.8s over a 20s answer. Canned
  wavs are 24000 pcm_s16le; `envelope` normalises, so both dtypes work unchanged.
- **stdlib `wave` cannot read the VC worker's output** (float32, format 3). `scipy` is
  installed and handles it.
- **`brain.py` gets a hybrid persona** — a short Johnny-styled lead-in, figures stated
  plain. Persona never touches the numbers. Agreed with the owner; not yet built.
- **No blink**, despite 70 eyelid joints: he wears opaque aviators and the eyes are not
  visible. Verified by rendering the face close up.

### Three traps that cost real time — all now in code comments

1. **Blanket `blend_method=BLEND` erased the chrome arm.** Its textures carry alpha, but
   as a spec mask, not transparency (`arm_misc` 100% non-opaque, `arm_wires` 98%).
   Blending let the torso show through the limb. Only hair-type cutouts, lenses and
   decals may blend — `fbx_to_glb.ALPHA_MATERIALS` is an explicit list because alpha
   content cannot distinguish the two cases.
2. **`actor.loop()` does not apply the pose until a frame is drawn**, so framing measured
   the bind pose and then displayed him animated.
3. **`_frame_head` centred only Z.** Fine until a clip shifted his weight off the
   centreline. These last two hid each other: measuring the bind pose always returned
   head centre x=0.000, so fixing the centring alone changed nothing.

## Desktop-presence investigation (2026-09-21, owner's request)

**Question:** can Johnny sit on the desktop without running a script and without the
grey window behind him?

**Findings — better than expected. Both work natively in Panda3D, no new dependency:**

| Want | Status |
|---|---|
| Transparent background | **WORKS.** `framebuffer-alpha true` + clear colour alpha 0. 8 alpha bits available. Owner confirmed wallpaper shows through. |
| No window chrome | **WORKS.** `WindowProperties.setUndecorated(True)`. |
| Sits behind other windows | **WORKS.** `setZOrder(WindowProperties.Z_bottom)`. Owner confirmed. |
| Clicks pass through | **NOT POSSIBLE natively.** Panda3D exposes only `M_absolute/M_confined/M_relative`, which are capture modes. Needs PyObjC to set `NSWindow.ignoresMouseEvents = True`. PyObjC is **not installed** in `mavis/.venv` or system python3. |
| Behind desktop *icons* | **Untested.** `Z_bottom` sinks below windows; true wallpaper level needs `NSWindow.level = kCGDesktopWindowLevel`, i.e. PyObjC again. |
| Launch without a terminal | **Untested.** A `.app` wrapper or a LaunchAgent plist; neither attempted. |

The working probe was `desktop_test.py` in the (now gone) scratchpad — it is ~25 lines:
set the three PRC/WindowProperties flags above, `base.win.setClearColor(Vec4(0,0,0,0))`,
then build an `AvatarScene` as normal.

**One more constraint, learned the hard way minutes after the probe succeeded:** the
OS killed the probe window for low memory. A desktop presence is by definition
*permanently resident* — unlike the showcase windows, it never closes — and it would
hold ~300MB for the whole session on a machine that has now OOM-killed this project four
times in one day. That does not sink the feature, but it means "always on the desktop"
and "warm 2-3GB voice worker" are competing for the same 8GB, and the feature should be
designed knowing that (idle the renderer when hidden? unload the model between
questions?).

**Recommendation if this is picked up:** it is a genuine feature, not a tweak — it
changes how the app is launched and how it behaves against the rest of the desktop. Worth
a brainstorm and its own small plan rather than bolting onto Task 7. The open questions
are click-through and launch, and both point at one decision: whether to add PyObjC as a
dependency.

## What's next (ordered)

1. **Task 6 Step 1 — start the Colab wake-model run now.** ~1hr, blocks nothing.
2. **Task 6** — `wake.py`, `capture.py`, `stt.py`, `brain.py`. Remember `brain.py` owes
   the hybrid persona prompt and `MAX_ANSWER_CHARS`.
3. **Task 7** — the state machine. It gains four canned-line call sites (greeting on
   wake, idle after silence, filler on dispatch, dismissal before hiding) via
   `canned.path_for(moment)`, with `None` meaning "say nothing". **Drive lipsync from
   canned wavs too**, or Johnny delivers his best lines with a frozen face.
4. **Then** `superpowers:finishing-a-development-branch` for how `feat/mavis-avatar`
   lands. Two things to settle first: the stray other-thread docs swept into `d306f45`,
   and the home path with the owner's username still in `voice_client.py`,
   `pregen_lines.py` and `bullion_grounding.json`.
5. Optional: the desktop-presence feature above.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — **148 passing**. `keanu` tests skip where
  the gitignored model is absent.
- **Render offscreen and look at the pixels yourself.** The single highest-value
  technique here. `window-type offscreen`, then
  `img = PNMImage(); base.win.getScreenshot(img); img.write(path)` and Read the file.
  Step `base.taskMgr.step()` rather than `renderFrame()` — simplepbr feeds
  `camera_world_position` from a task. Reserve the owner's eyes for judgement calls
  pixels cannot settle.
- **Compare against a controlled baseline.** The "retarget broke the arm" scare was
  settled in one render: same camera, pose cleared, artifact still there — so it was
  pre-existing, not the retarget.
- **Measure against realistic data before trusting anything.** Task 3's framing, Task 4's
  matcher and Task 5's client all passed their own tests while being wrong.
- **`bundle.forceUpdate()` after moving any slider or controlled joint**, or the change
  is a silent no-op. This has cost debugging time three times now.
- **Never trust a "feature is missing" claim without checking the right API** — the
  original "this model has no mouth" was a false negative from searching the scene graph
  for `CharacterSlider`s, which live in the `PartBundle`.
