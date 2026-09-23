# MAVIS Night 4 — Task 7, Poses and Props — Session Handoff

**Written:** 2026-09-22 · **Owner feedback section added the same day.** · **For:** whoever resumes MAVIS Night 4. Task 7's code is
written, reviewed, committed and runs end to end, but the **live acceptance run is
only partly done** and the wake word still does not exist. Start at "What's next".

This **replaces** `graywind-mavis-voice-and-animation-handoff.md` (2026-09-21). That
file is still the authority on the hybrid voice, the two models and the desktop-presence
probe; read this one first and fall back to it for that detail.

## Goal

A wake-word-triggered desktop presence: say **"Wake up, Johnny"** and a rendered,
animated Johnny Silverhand appears, answers a spoken question in his own voice with his
mouth moving, and disappears when told to stop.

- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- Avatar plan (the ledger): `docs/superpowers/plans/2026-09-19-mavis-avatar.md` — 7 tasks
  plus deferred Task 8. **Tasks 1-6 and 8 ticked. Task 7's steps are NOT ticked**, because
  its code is written but uncommitted and its live acceptance (step 6) is incomplete.
- Voice spec/plan: `specs/2026-09-20-mavis-canned-voice-design.md`,
  `plans/2026-09-20-mavis-canned-voice.md` — complete.
- **Deferred live-run findings** are appended to the END of the avatar plan (added this
  session). Read that section before touching voice or grounding.

## How to resume (do this first)

1. `cd ~/Projects/graywind && git log --oneline bde13f3..HEAD` — expect **39 commits** on
   `feat/mavis-avatar`, newest `7ccafef`. The tree is clean.
   (The handoff commit was amended after this doc was written, so the `97008ea` named
   below is now `d163fe8`; two later commits are the latency fix, see "Latency".)
2. `cd mavis && .venv/bin/python -m pytest -q` — expect **180 passed**.
3. **Rebuild `assets/avatar/keanu.bam`** (recipe at the bottom) — it is gitignored, and any
   build made before 2026-09-22 carries both retarget bugs.
4. **Immediate next action:** finish the live acceptance run with the owner at the
   keyboard, then the wake-word Colab run.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 37 commits ahead of base `bde13f3`. **Tree clean.**

**Committed this session — `0743ba0`:**
- `mavis/tools/retarget_anim.py` — bake each clip at its **own** length. Every clip had
  been baked over Blender's factory 1-250 range: Smoking (538 frames) shipped at under
  half, Breathing Idle (299) was clipped so its loop popped, and the 68-frame Dismissing
  Gesture would have been padded with six seconds of frozen hold.
- `mavis/assets/avatar/ATTRIBUTION.md` — the rebuild recipe gains `dismiss`.

**Committed as `79baf48`** — the retarget rest-pose fix, and the removal of hip travel
(it compared pose bones with `is`, so bpy's fresh wrappers meant it never fired on any
shipped clip; making it fire sent the pelvis 18 metres, because the two rigs sit at
different unit scales. Every clip used here is in-place, so nothing was lost. Re-derive
it properly only if a clip that actually walks is ever retargeted).

**Committed as `81d7141`:**
- `mavis/avatar/states.py` — the pure state machine (sleeping/listening/thinking/
  speaking/dismissing). Picks the pose and the canned line for each moment. Render-thread
  only; no I/O, no threads. **Drafted by `delegate`, reviewed and tested here.**
- `mavis/avatar/app.py` — the runtime. Panda3D owns the main thread; wake word, capture,
  STT, `/ask`, voice conversion and playback run on one worker thread that talks to the
  scene only through `Runtime.on_render`. Entry point `python -m avatar.app`.
- `mavis/avatar/props.py` — procedural cigarette (three cylinders: filter, paper, lit
  ember). Built in code so no third-party prop asset needs licensing.
- `mavis/tests/test_app_states.py` — 14 tests over the state machine, including one that
  checks every model's `poses` config names clips that actually exist.

**Committed as `4676d1b`:**
- `mavis/avatar/props.py` — the cigarette (listed above).
- `mavis/avatar/scene.py` — `poses` per-moment clip table, `show_notice`, prop attachment
  (`_attach_prop`/`_show_prop`), `animated` now keyed on the idle clip alone, `play()`
  no longer restarts a clip already looping.
**Committed as `97008ea`:** this handoff and the plan's deferred live-run findings.

**Scratch workspace / traps:**
- ⚠️ **`mavis/assets/avatar/keanu.bam` was rebuilt three times this session** and is
  gitignored. It now holds **idle (299), smoking (538), dismiss (68)** and was built with
  the fixed retarget. A fresh clone has nothing until the tool is re-run; a `.bam` built
  before today has the 250-frame truncation AND the old arm mapping.
- ⚠️ The extracted CDPR source lives only in this session's scratchpad
  (`/private/tmp/claude-501/.../scratchpad/keanu/`), which will be wiped. Re-extract from
  `~/Downloads/Keanu 3D model.rar` (`bsdtar -xf`) — `unar`/`unrar`/`7z` are NOT installed.
- ⚠️ `~/Documents/Breathing Idle (1).fbx` is a byte-identical duplicate. Ignore it.
- ⚠️ A backend was started this session with a **throwaway** `MAVIS_API_KEY` generated by
  `openssl rand`, stored only in the scratchpad. There is **no MAVIS_API_KEY in the
  environment** — any live run must set the same value for backend and avatar.
- ⚠️ `delegate` **hung twice** on long prompts (5+ min, no output, killed) before
  succeeding on a shorter one; a third attempt on another model returned unusable code.
  Cap it with a timeout and keep prompts small.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `dashboard-data/*.json`.

## What has changed

1. **Task 7 is written** — state machine, runtime, entry point, tests. 172 pass.
2. **The retarget was wrong for every clip, in two independent ways**, both fixed:
   - Frame range (committed, above).
   - **Rest-pose mismatch (uncommitted).** Mixamo rests in a T-pose; this model rests in
     an A-pose with bent forearms — upper arms **52°** apart, forearms **67°**. Deltas
     taken from one rest and applied to the other carried that gap into every frame:
     forearms folded across the stomach, elbows flared on raised arms. The fix swings each
     target rest bone to point where its source bone points **before** transferring, and
     does the whole computation in **world space** (the two FBX imports leave the armature
     objects 90° apart, so bone-space matrices from one rig mean something else in the
     other). Measured result: every arm bone **0.0°** off the source, down from 14-64°.
   - **Only the arm chain is rest-aligned** (`REST_ALIGNED` in the tool). Spine, neck and
     head stand upright in both rests but their bone axes differ; aligning those threw the
     head all the way back. Do not widen that set without rendering the result.
3. **Poses are now per-moment**, in `scene.AVATARS[...]["poses"]`: listening/speaking =
   idle, prompting/thinking = smoking, dismissing = dismiss. Changing the mapping is a
   config edit, not a refactor.
4. **The cigarette** is attached to the **right (flesh) hand** — the one the smoking clip
   raises (index tip 175mm from the jaw at frame 114, against the chrome hand's 194mm at
   196). Hand joints carry the rig's 0.025 unit scale, so a prop parented to one arrives
   40x too small; `_attach_prop` cancels that and keeps `pos` in honest metres.
5. **The window is now undecorated with a transparent background** (`framebuffer-alpha
   true` + clear colour alpha 0). **Escape is the only way to quit** — there is no close
   button any more.

## What has failed / risks / caveats

- **Nothing is failing in the tests.** 172 pass.
- **UNVERIFIED — the live acceptance run (plan Task 7, step 6) is incomplete.** The owner
  has now judged the pose (accepted) and the voice (tolerated — see his feedback below),
  but there is **no confirmed report** on: lipsync against real speech, the dismissal path
  end to end, the second-answer latency check (does the warm worker hold?), the
  transparent undecorated window, or the cigarette in the right hand. Those last two
  shipped after his last look.
- **Reviewed.** Two `code-review` passes ran, five findings each, all ten fixed. The second
  pass is what surfaced the dead hip-travel code and the `exposeJoint` guard that never
  fired. The owner approved the commits.
- **The wake model still does not exist.** `assets/wakeword/wake_up_johnny.onnx` needs the
  ~1hr openWakeWord Colab run (plan Task 6, step 1). Until then the app falls back to
  **W** in the window, and plan Task 6 step 9 stays unticked.
- **He never actually takes the drag.** The Mixamo Smoking clip keeps his fingertips
  ~175mm from the jaw joint. The cigarette is held and gestured with, never smoked. A
  different source clip is the only fix.
- **Memory:** this session ran Blender, repeated offscreen renders, the avatar and the
  2-3GB voice worker. Nothing was OOM-killed today, but close the avatar before Blender.
- **Backend grounding missed "tier pools"** — `/ask` answered "which tier pools do you
  mean?" with no citations. Not a Task 7 bug; logged in the plan's deferred section.
- **Hybrid persona still owed** in `brain.py` (short Johnny-styled lead-in, figures plain).
  This is also the cheapest lever on the owner's "doesn't fit his character" complaint:
  it changes the words he says, which no amount of voice tuning does.

## Owner feedback from the 2026-09-22 live run (verbatim, with what it implies)

The owner ran him and gave three judgements. These are **his words**, not a summary of
test output, and they are the standing direction for what to fix next.

1. **Smoking pose — ACCEPTED.** *"the smoking pose is not too unconvincing for me"*.
   The rest-pose retarget fix cleared the complaint that opened this thread (forearms
   folded together, elbows flaring). Treat the pose as good enough; do not re-litigate it.
   He still never takes an actual drag (fingertips stay ~175mm from the jaw) — that is a
   clip limitation, and only a different source clip changes it.

2. **Voice — TOLERATED, NOT LIKED.** *"the voice is a bit slow but tolerable even if it
   doesn't fit his character a lot"*. Two distinct complaints in one sentence:
   - **Slow.** ChatterboxVC runs ~1.4x realtime and the answer is generated in full before
     a word is spoken, so a long answer is a long silence. `brain.MAX_ANSWER_CHARS` (420)
     is the only lever currently pulled. Streaming or sentence-by-sentence conversion would
     cut time-to-first-word, but breaks the "audio is finished before the renderer
     animates" rule in the spec — that rule needs an explicit decision, not a quiet edit.
   - **Doesn't sound like him.** Expected, and the reason the voice is hybrid at all: the
     28 canned lines are real ChatterboxTTS in the actor's voice, while **live answers are
     VC over a macOS `say` scaffold**, which carries the words but not the character. See
     the voice spec. Options not yet costed: a better scaffold voice, VC parameter tuning,
     or pre-generating more of what he says. **Unresolved:** it was never confirmed whether
     the answer he judged was VC output at all or the plain Tom fallback — the log showed a
     scaffold read, which can mean either. Confirm that BEFORE tuning anything.

3. **Launching — THE BIGGEST COMPLAINT.** *"i dislike how i have to run a script to open
   him instead of saying, wake up johnny boy and he would wake up"*. He does not want an
   app he starts; he wants a presence that is already there and listens. This is two
   pieces of work, both known and both unstarted:
   - **The wake word itself** — plan Task 6 step 1, the ~1hr openWakeWord Colab run. Until
     `assets/wakeword/wake_up_johnny.onnx` exists, **W in the window is the only way to
     wake him**, which is exactly what he is objecting to.
   - **Launching without a terminal** — listed "untested" in the desktop-presence section
     of the previous handoff and still untested: a `.app` wrapper or a LaunchAgent plist so
     he starts at login and simply exists. The transparent, undecorated window shipped this
     session is the other half of that same feature.
   - ✅ **Phrase SETTLED 2026-09-22.** Asked directly, the owner confirmed **"Wake up,
     Johnny"** is fine; "wake up johnny boy" was just how he said it in the moment. Train
     `wake up johnny` exactly as plan Task 6 step 1 already writes it.

## Latency — diagnosed and halved (2026-09-23)

The owner said the second answer was "kinda long". **Measured, not estimated:** 386 chars
of real answer text is **21.9s** of `say -v Tom` audio (~17.6 chars/sec), and ChatterboxVC
converts at ~1.5x realtime. So the old 420-char cap was ~24s of speech and **~36s of
conversion** — roughly 90% of the wait. Trailing-silence detection, STT and `/ask` are ~4s
combined; the filler line masks ~3s.

**The warm worker was not the cause and was not touched.** A dead worker degrades to the
plain scaffold, which is *faster*, and raises the on-screen notice.

Shipped as `7ccafef` + `ab26d8a`:
- `brain.MAX_ANSWER_CHARS` 420 → **200**, overridable via `MAVIS_MAX_ANSWER_CHARS` (parse
  is guarded — an empty value from a LaunchAgent plist falls back instead of killing import).
- `/ask` gained an optional **`max_chars`**, which prepends a brevity system message. The
  cap alone only truncates, which stops him mid-thought; asking the model to write short
  returns a *complete* short answer. Defaults to `None`, so **the MCP wrapper and CLI are
  unchanged** — two tests pin that.
- Verified against the real Groq model: grounded answers came back at 95-162 chars,
  complete sentences. Citations ride in a separate JSON field, outside the char budget.

**Still unverified (needs the owner):** whether this feels better, and the handoff's
standing question of whether what he judged was VC output or the plain Tom fallback.

**Next lever, if 200 is still too slow: chunked VC.** The voice spec's line 209
("streaming or chunked TTS changes nothing") is about **ChatterboxTTS at 35-41x realtime**,
where it is true. **VC runs ~1.5x** — a different regime, where converting sentence by
sentence and playing as you go cuts time-to-first-word to single digits. Two caveats:
at 1.5x conversion against 1.0x playback you accrue a ~0.5x deficit per chunk, so
pre-buffer a sentence or he stalls mid-answer; and `voice_worker._normalise` scales **per
clip** to `TARGET_PEAK = 0.89`, so chunks would jump in loudness without fixed gain or
whole-answer normalisation. It also breaks the spec's "audio is finished before the
renderer animates" rule — **needs the owner's explicit yes**, not a quiet edit.

## ⚠️ Grounding is far worse than this doc previously recorded

Found while A/B-testing the brevity change. The earlier note said `/ask` "missed tier
pools". The real scope: **`data/graywind_grounding.json` holds only 6 facts** — one
watchlist line, four per-account decision lines, one pending trade. It contains **nothing
about how Graywind works**: no macro gate, no tier-pool definitions, no volatility gate,
no sizing rules. Bullion's corpus covers the financial system, not Graywind internals.

Measured hit counts: `retrieve("macro gate")` → **0**, `retrieve("tier 1")` → **0**,
`retrieve("tier pools")` → **0** (against `"gold"` → 5, `"federal reserve"` → 5).

With zero citations the model answers anyway, confidently and wrongly — "how much capital
does tier 1 get?" returned **Basel III bank capital ratios**, and "what is the macro gate"
returned a description of a *network traffic* filter. Both read as authoritative.

Also: the six facts are timestamped **2026-09-15** and were still the live corpus on
09-23 — check whether the snapshot is regenerated at all.

This matters beyond MAVIS: the owner's stated next direction is Johnny "reading" Bullion
and Graywind, and he cannot read Graywind's mechanics while they are absent from the
corpus. Treat corpus coverage as the prerequisite for that work.

## What's next (ordered)

1. **Finish the live acceptance run** with the owner: wake, real question, voice, lipsync,
   dismissal, plus the transparent window and cigarette. Latency is now ~200 chars rather
   than 420 — judge whether that is enough before building chunked VC.
2. **Task 6 step 1 — the openWakeWord Colab run — is now the owner's top priority**, with
   step 9 (a real voice) straight after. Settle the phrase first ("Wake up, Johnny" vs his
   "wake up johnny boy"). Pair it with the launch-at-login work below: on their own,
   neither one answers his complaint.
3. **Launch without a terminal** — `.app` wrapper or LaunchAgent, plus deciding whether he
   idles cheaply while hidden (a permanent presence holds ~300MB for the whole session on
   an 8GB machine, alongside a 2-3GB voice worker).
4. **Tick the plan's Task 7 checkboxes** only once 1-2 are done.
5. Then `superpowers:finishing-a-development-branch`. Two things still to settle first:
   the stray other-thread docs swept into `d306f45`, and the owner's username still
   hard-coded in `voice_client.py`, `pregen_lines.py` and `bullion_grounding.json`.
6. Optional, owner-requested "later": more poses (Mixamo clips are free downloads; the
   retarget now takes any number as `name=path.fbx`), and Task 8 idle motion.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — **180 passing**. `keanu` tests skip when
  the gitignored model is absent.
- **Render offscreen and look at the pixels yourself** — the highest-value technique here,
  and how both the arm bug and the cigarette placement were settled. `window-type
  offscreen`, `base.taskMgr.step()` (not `renderFrame()`), `PNMImage` + `getScreenshot`,
  then Read the file. `PNMImage.copySubImage` builds a contact sheet without PIL, which is
  **not installed** in this venv.
- **Render the chrome arm against a DARK background.** On white it aliases into a
  featureless white smear that reads as a broken material.
- **Measure, don't eyeball, anything spatial.** The camera made a hand 21cm from the mouth
  look like it was at the lips; joint distances settled which hand smokes.
- **`bundle.forceUpdate()` after posing or moving any joint or slider**, or the change is a
  silent no-op.
- **Rebuild the model** (needs Blender + the extracted rar):
  `Blender --background --factory-startup --python tools/retarget_anim.py -- <keanu.fbx>
  <texdir> /tmp/keanu.glb "idle=~/Documents/Breathing Idle.fbx"
  "smoking=~/Documents/Smoking.fbx" "dismiss=~/Documents/Dismissing Gesture.fbx"`
  then `.venv/bin/gltf2bam /tmp/keanu.glb assets/avatar/keanu.bam`.
