# MAVIS Night 4 — Latency Fix and the Grounding Hole — Session Handoff

**Written:** 2026-09-23 · **For:** whoever resumes MAVIS Night 4. Spoken-answer latency is
diagnosed and roughly halved, and the wake phrase is settled — but the wake word still does
not exist, and a **much larger grounding problem surfaced** that gates the owner's stated
next direction. Start at "What's next".

This **supersedes** `graywind-mavis-task7-state-machine-handoff.md` (2026-09-22) for
current state. That file is still the authority on **Task 7's design, the poses, the
cigarette, the retarget bugs and the owner's verbatim live-run verdicts** — read this one
first and fall back to it for that detail. Do not read the older three; they are tracked in
git if you need them.

## Goal

A wake-word-triggered desktop presence: say **"Wake up, Johnny"** and a rendered, animated
Johnny Silverhand appears, answers a spoken question in his own voice with his mouth
moving, and disappears when told to stop.

- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- Avatar plan (the ledger): `docs/superpowers/plans/2026-09-19-mavis-avatar.md` — 7 tasks
  plus deferred Task 8. **⚠️ The ledger under-reports — see the trap in "Current state".**
- Voice spec/plan: `specs/2026-09-20-mavis-canned-voice-design.md`,
  `plans/2026-09-20-mavis-canned-voice.md` — complete.
- Prior handoff (Task 7 design detail): `graywind-mavis-task7-state-machine-handoff.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind && git rev-parse --abbrev-ref HEAD` — expect
   **`feat/mavis-avatar`**, ~41 commits ahead of base `bde13f3`, clean tree.
   **Don't expect an exact commit count**; every handoff edit adds one.
2. `cd mavis && .venv/bin/python -m pytest -q` — expect **180 passed**.
3. **Rebuild `assets/avatar/keanu.bam`** (recipe at the bottom) — it is gitignored, and any
   build made before 2026-09-22 carries both retarget bugs.
4. Read the prior handoff's "Owner feedback" section. It is the standing direction and it
   is still accurate; only its latency item has been acted on.
5. **Immediate next action:** the **openWakeWord Colab run** for the phrase
   `wake up johnny` (plan Task 6, step 1, ~1hr mostly unattended). This is the owner's
   top-priority complaint and nothing else he asked for unblocks without it.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, **41 commits** ahead of base `bde13f3`. **Tree clean.**

**Files changed this session — committed in `7ccafef`:**
- `mavis/avatar/brain.py` — `MAX_ANSWER_CHARS` 420 → **200**, overridable via
  `MAVIS_MAX_ANSWER_CHARS`; sends `max_chars` to `/ask`. Carries the measured latency
  arithmetic in comments so the number is not re-litigated from memory.
- `mavis/providers.py` — `groq_answer(..., max_chars=None)` and `_brevity_instruction()`,
  which prepends a system message asking for a short, spoken-style, markdown-free answer.
- `mavis/app.py` — `AskRequest.max_chars: int | None = None`, passed through to the provider.
- `mavis/tests/test_app.py` — two tests pinning that the default is `None`, i.e. **the MCP
  wrapper and CLI still get full answers**. Also fixed two stale fake signatures.
- `mavis/tests/test_providers.py` — **new**; pins that no budget means no system message.
- `docs/superpowers/plans/2026-09-19-mavis-avatar.md` — wake phrase settled at Task 6 step 1.

**Committed in `35557e1`:**
- `mavis/avatar/brain.py` — `_budget_from_env()`. A bare `int()` on the override raised at
  **import time**, so a mistyped or empty env value stopped the avatar from starting at
  all. Falls back to 200 on empty/malformed/non-positive.
- `mavis/tests/test_brain.py` — a test per bad-input shape.
- `graywind-mavis-task7-state-machine-handoff.md` — latency + grounding sections, corrected
  stale resume numbers, closed the wake-phrase warning.

**Committed in `29d3ef5`, `c503a68`:** handoff hash corrections, then removal of the
self-referential commit count that caused them. Docs only.

**Files later work will modify (untouched so far):**
- `mavis/assets/wakeword/` — **does not exist yet.** `wake_up_johnny.onnx` goes here. The
  filename is load-bearing: `avatar/wake.py` looks for exactly that name.
- `mavis/data/graywind_grounding.json` — the near-empty corpus (see caveats). Regenerated
  by a snapshot script, not hand-edited.
- No LaunchAgent plist or `.app` wrapper exists anywhere yet.

**Scratch workspace / traps:**
- ⚠️ **The plan ledger under-reports what shipped.** Task 5's steps are **all unticked**,
  but the warm voice worker demonstrably shipped (`5dd3c7c`, `b6a92b3`;
  `avatar/voice_client.py`, `scripts/voice_worker.py`, `tests/test_voice_client.py` all
  exist and are tested). Task 7's steps are likewise unticked with the code committed. The
  prior handoff's claim that "Tasks 1-6 and 8 [are] ticked" is **wrong about Task 5**.
  **Trust `git log` and the files over the ledger's checkboxes.**
- ⚠️ **`mavis/assets/avatar/keanu.bam` is gitignored** and absent on a fresh clone. The
  current local build (2026-09-22, ~93MB) holds idle (299), smoking (538), dismiss (68)
  with both retarget fixes. Any build older than 2026-09-22 is wrong twice over.
- ⚠️ **The extracted CDPR source is gone** — it lived in a previous session's scratchpad,
  which is wiped. Re-extract from `~/Downloads/Keanu 3D model.rar` with `bsdtar -xf`;
  `unar`/`unrar`/`7z` are NOT installed.
- ⚠️ **There is no `MAVIS_API_KEY` in the environment.** It is a **self-chosen** shared
  secret (`mavis/auth.py` compares it against the `X-API-Key` header), not a third-party
  key. Any random string works, but the backend and the avatar must export the **same**
  one, or `/ask` returns 401 (mismatch) or 500 (unset server-side). `GROQ_API_KEY` is the
  real third-party key and **is** already in the environment.
- ⚠️ `~/Documents/Breathing Idle (1).fbx` is a byte-identical duplicate. Ignore it.
- ⚠️ `delegate` hung twice on long prompts in a prior session. Cap it with a timeout and
  keep prompts small.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `dashboard-data/*.json` (all untracked
and pre-existing).

## What has changed

1. **Spoken-answer latency diagnosed with a real measurement**, not an estimate. 386 chars
   of real answer text = **21.9s** of `say -v Tom` audio (~17.6 chars/sec). ChatterboxVC
   converts at ~1.5x realtime, so the old 420-char cap meant ~24s of speech and **~36s of
   conversion** — roughly 90% of the wait. Trailing-silence detection, STT and `/ask` are
   ~4s combined; the filler line masks ~3s.
2. **The warm worker was exonerated, not changed.** A dead worker degrades to the plain
   scaffold, which is *faster*, and raises the on-screen notice. The Task 7 warm-worker
   design is holding.
3. **The cap is now 200 and the model is asked to write short.** Truncation alone stops him
   mid-thought; the brevity system message returns a *complete* short answer instead.
   Verified against the real Groq model: grounded answers came back at 95-162 chars, full
   sentences. Citations ride in a separate JSON field, outside the char budget.
4. **The `/ask` contract was widened** — this is more than a constant change. `max_chars`
   defaults to `None` so every existing caller is byte-identical; two tests pin it.
5. **Wake phrase settled: "Wake up, Johnny".** The owner said "wake up johnny boy" during
   the live run; asked directly, he confirmed the spec's phrase is fine. Recorded in the
   plan at Task 6 step 1. No retraining hour lost.
6. **A large grounding hole was found** (see caveats — it is the most important finding).
7. Suite **172 → 180**.

## What has failed / risks / caveats

- **Nothing is failing in the tests.** 180 pass.
- **⚠️ THE BIG ONE — Graywind grounding is nearly empty, and the model hallucinates over
  the gap.** `mavis/data/graywind_grounding.json` holds **6 facts**: one watchlist line,
  four per-account decision lines, one pending trade. It contains **nothing about how
  Graywind works** — no macro gate, no tier-pool definitions, no volatility gate, no sizing
  rules — and Bullion's corpus covers the financial system, not Graywind internals.
  Measured: `grounding.retrieve()` returns **0 hits** for `"macro gate"`, `"tier 1"` and
  `"tier pools"`, against **5** for `"gold"` and **5** for `"federal reserve"`.
  With zero citations the model answers anyway, confidently and wrongly — *"how much
  capital does tier 1 get?"* returned **Basel III bank capital ratios**, and *"what is the
  macro gate?"* described a **network traffic filter**. Both read as authoritative.
  The prior handoff logged this as a single missed question about "tier pools"; it is far
  wider. The six facts are also stamped **2026-09-15** and were still live on 09-23, so
  **check whether the snapshot regenerates at all.**
- **UNVERIFIED — the owner has not judged the latency fix.** He said explicitly he would
  not be able to look soon. Everything in "What has changed" is test-verified and
  model-verified but not human-verified.
- **UNVERIFIED — still open from the prior session:** lipsync against real speech, the
  dismissal path end to end, the transparent undecorated window, and the cigarette in the
  right hand. All shipped after his last look.
- **UNRESOLVED and blocking any voice tuning:** it was never confirmed whether the answer
  he judged ("doesn't fit his character") was VC output at all, or the plain Tom fallback.
  The log showed a scaffold read, which can mean either. **Confirm `voice.degraded` /
  `last_error` on the next run BEFORE tuning anything.**
- **The wake model still does not exist.** Until `assets/wakeword/wake_up_johnny.onnx` is
  there, **W in the window is the only way to wake him** — which is precisely the owner's
  loudest complaint.
- **A LaunchAgent will not inherit the shell environment.** When launch-at-login starts,
  `GROQ_API_KEY` and `MAVIS_API_KEY` must go in the plist or a wrapper script, or Johnny
  starts at login with no STT and no backend auth. This is why `_budget_from_env` was
  hardened now rather than later.
- **He never actually takes the drag.** The Mixamo Smoking clip keeps his fingertips
  ~175mm from the jaw. Only a different source clip changes it. Not a bug.
- **Memory:** a permanent presence holds ~300MB for the session alongside a 2-3GB voice
  worker on an 8GB machine. Close the avatar before running Blender.
- **Decisions carried forward that override the plan:** the spec's "chunked TTS changes
  nothing" (line 209) is about **ChatterboxTTS at 35-41x realtime** and does **not** apply
  to **VC at ~1.5x**, where chunking is the single biggest remaining lever. See "What's
  next" item 4 for the two caveats and why it needs the owner's explicit yes.

## What's next (ordered)

1. **Train the wake word.** Plan Task 6, step 1: openWakeWord's
   `automatic_model_training.ipynb` in Colab, target phrase **`wake up johnny`** (settled —
   do not substitute "johnny boy"). ~1hr mostly unattended. Drop the `.onnx` at
   `mavis/assets/wakeword/wake_up_johnny.onnx`. **Do not `pip install` the training deps
   into `mavis/.venv`** — they pull torch, and the runtime venv must stay torch-free.
   Then tick plan Task 6 step 9 after verifying it fires on his real voice.
2. **Launch without a terminal** — a `.app` wrapper or a LaunchAgent plist, carrying both
   API keys explicitly. Together with (1) this is the owner's actual request; neither half
   answers it alone. Decide whether he idles cheaply while hidden.
3. **Finish the live acceptance run** with the owner at the keyboard: wake, a real
   question, voice, lipsync, dismissal, the transparent window, the cigarette — and judge
   whether 200 chars is short enough. Confirm the VC-vs-Tom question above in the same run.
4. **Only if he still says it is slow: chunked VC.** Convert sentence by sentence and play
   as you go; time-to-first-word drops to single digits. Two caveats: at 1.5x conversion
   against 1.0x playback you accrue a ~0.5x deficit per chunk, so pre-buffer a sentence or
   he stalls mid-answer; and `voice_worker._normalise` scales **per clip** to
   `TARGET_PEAK = 0.89`, so chunks would jump in loudness without fixed gain or
   whole-answer normalisation. It breaks the spec's "audio is finished before the renderer
   animates" rule — **needs the owner's explicit yes, not a quiet edit.**
5. **Fix the grounding corpus.** Prerequisite for the owner's stated next direction
   (below), and independently the difference between Johnny being useful and Johnny being
   confidently wrong. Start by finding whether the snapshot regenerates, then widen it to
   cover Graywind's own mechanics.
6. **Tick the plan's Task 5, 6 and 7 checkboxes** to match reality, once 1-3 are done.
7. Then `superpowers:finishing-a-development-branch`. Two things to settle first: the stray
   other-thread docs swept into `d306f45`, and the owner's username still hard-coded in
   `voice_client.py`, `pregen_lines.py` and `bullion_grounding.json`.
8. Optional, owner-requested "later": more poses (the retarget takes any number of Mixamo
   clips as `name=path.fbx`), and Task 8 idle motion — **blinking is the biggest win per
   unit effort**.

## Direction set for AFTER Johnny (owner, 2026-09-22) — do not start yet

The owner's stated next focus is **Bullion and Graywind**, with Johnny as the figure who
"appears in those projects and reads them." **Explicitly gated behind finishing Johnny.**

It is smaller than it sounds — **three of four pieces already exist**: Johnny is already
Bullion's second narrator (the shipped ChatterboxTTS voice-blend work); `/ask` is already
grounded in both projects at once (`grounding.py` + `graywind_grounding.py` feed the same
answer); and the rendered, lip-synced avatar shipped in Night 4. **The missing piece is
only the bridge** — pointing him at a specific node or position and having him narrate it,
rather than answering ad-hoc spoken questions. Scope it as that bridge, not a new project.

Two blockers to settle before scoping: Bullion's front door is a **web** map while Johnny
is a native Panda3D window and the owner has ruled out an HTML frontend for MAVIS — so
decide whether he is a separate always-on desktop presence alongside the browser. And live
TTS in his real voice remains impossible (35-41x realtime), so anything he "reads" must be
pre-generated as Bullion's narration already is, or go through VC at its ~1.5x cost.

**And the grounding hole above is a hard prerequisite** — he cannot narrate Graywind's
mechanics while they are absent from the corpus.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — **180 passing**. `keanu` tests skip when the
  gitignored model is absent.
- **Measure, don't estimate, anything about latency.** `say -v Tom -o /tmp/x.wav
  --data-format=LEF32@22050 "<text>"` then read the duration from the WAV header. That is
  what turned "the voice is slow" into a number and pointed at the right lever.
- **Check a prompt change against the real model, not just tests.** Tests prove the message
  is *sent*; only a live call proves the model *honours* it. One throwaway
  `providers.groq_answer(q, ctx, max_chars=200)` in the venv is enough — and it is how the
  grounding hole was found.
- **Render offscreen and look at the pixels yourself** — the highest-value technique here.
  `window-type offscreen`, `base.taskMgr.step()` (not `renderFrame()`), `PNMImage` +
  `getScreenshot`, then Read the file. `PNMImage.copySubImage` builds a contact sheet
  without PIL, which is **not installed** in this venv.
- **Render the chrome arm against a DARK background** — on white it aliases into a
  featureless smear that reads as a broken material.
- **Measure, don't eyeball, anything spatial.** Joint distances settled which hand smokes.
- **`bundle.forceUpdate()` after posing or moving any joint or slider**, or it is a silent
  no-op.
- **Rebuild the model** (needs Blender + the extracted rar):
  `Blender --background --factory-startup --python tools/retarget_anim.py -- <keanu.fbx>
  <texdir> /tmp/keanu.glb "idle=~/Documents/Breathing Idle.fbx"
  "smoking=~/Documents/Smoking.fbx" "dismiss=~/Documents/Dismissing Gesture.fbx"`
  then `.venv/bin/gltf2bam /tmp/keanu.glb assets/avatar/keanu.bam`.
