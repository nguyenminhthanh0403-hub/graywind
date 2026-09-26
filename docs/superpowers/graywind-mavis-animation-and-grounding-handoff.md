# MAVIS / Johnny — Animation Fixes + Ungrounded-Answer Guard — Session Handoff

**Written:** 2026-09-25 · **For:** whoever resumes Johnny. Everything below is
**committed AND pushed** (`9f21df2`). Work was driven by the owner's first
numeric ratings of Johnny — start at "What's next", which is an ordered queue
he asked to be worked one at a time.

This **supersedes** `graywind-mavis-captions-mic-bundle-handoff.md` (written
earlier the same day) for current state. That file is still the authority on
the **mic/TCC diagnosis** and the **wake-word Colab repairs**, both summarised
but not repeated here. Do not read the older pile; it is tracked in git.

## Goal

Make Johnny good enough to use, judged by the owner's own ratings
(2026-09-25): **animation 3/10, script 4/10, responsiveness 5/10.** His model
and the "I'm checking the numbers" filler-line mechanic were explicitly
praised — do not change those.

- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- Avatar plan (ledger): `docs/superpowers/plans/2026-09-19-mavis-avatar.md`
  — ⚠️ **the ledger under-reports; trust `git log` and the files over its checkboxes.**
- Voice spec/plan: `specs/2026-09-20-mavis-canned-voice-design.md`, `plans/2026-09-20-mavis-canned-voice.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind-johnny` — **a dedicated worktree pinned to
   `feat/mavis-avatar`, and where Johnny actually runs from.** NOT
   `~/Projects/graywind`, whose `mavis/avatar/` is an empty stale `__pycache__`.
2. `git log --oneline -4` — expect `9f21df2`, `02b8850`, `b158052`, `fc07db6`.
   **54 commits** ahead of base `bde13f3`; pushed and in sync at handoff time.
3. `cd mavis && .venv/bin/python -m pytest -q` — expect **193 passed**
   (was 180 at the start of the session). The root suite is separate and
   unchanged; see "Verification idioms".
4. **Immediate next action:** item 1 of "What's next" — instrument where the
   spoken-answer latency actually goes. It needs no decision from the owner
   and tells us whether the remaining lever is worth pulling.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 54 commits ahead of `bde13f3`, pushed, tree clean.

**Committed this session:**
- `a55eb7f` `avatar/scene.py`, `avatar/app.py` — on-screen captions.
  `show_caption()` + `_answer()` now returns `(wav, text)`.
- `419fbdf` `mavis/.gitignore` — a bare `.venv` entry.
- `df801d8` `scripts/build_app_bundle.sh` (new), `scripts/install_launch_agents.sh` —
  `~/Applications/Johnny.app`, and the agent now launches it via `open -W -a`.
- `b158052` `avatar/scene.py`, `tools/render_pose.py` (new) — cigarette fit.
- `02b8850` `avatar/scene.py` — clip cross-fade + minimum dwell.
- `9f21df2` `graywind_grounding.py`, `app.py` — ungrounded-answer refusal.

**Files later work will modify (untouched so far):**
- `mavis/data/graywind_grounding.json` — the 6-fact corpus. ⚠️ **Regenerating
  it does NOT fix the hole**: `scripts/extract_graywind_grounding.py` reads
  live CSV state only, and Graywind's *mechanics* were never in its scope.
  Filling it needs a NEW fact source (item 2 below).
- `mavis/assets/wakeword/` — directory EXISTS and is EMPTY. The model must land
  at exactly `wake_up_johnny.onnx`; `avatar/wake.py` looks for that literal name.
  ⚠️ It is **not** covered by `mavis/.gitignore` (which allowlists
  `assets/avatar/*` and `assets/voice/*` only), so it will show as a commit
  candidate in a PUBLIC repo — decide deliberately.

**Scratch workspace / traps:**
- ⚠️ **The avatar agent is currently NOT running** (`launchctl list` shows `-`
  for `com.mavis.avatar`). This is by design, not a fault: `KeepAlive` is
  `SuccessfulExit: false`, so a clean exit stays exited — otherwise closing him
  would be indistinguishable from a haunting. Bring him back with
  `launchctl kickstart -k gui/$UID/com.mavis.avatar`; he also returns at next
  login via `RunAtLoad`. The backend IS running and serving.
- ⚠️ `mavis/.venv` and the gitignored files under `mavis/assets/` are
  **symlinks into `~/Projects/graywind/mavis/`**. Deleting the main checkout's
  venv or assets breaks Johnny. `mavis/assets` itself is a real tracked
  directory — link the individual gitignored FILES, never the whole directory.
- ⚠️ `~/.mavis/env` held a **4-character placeholder** where `GROQ_API_KEY`
  belongs until this session. The installer **cannot repair this**: it sources
  the existing env file *before* its emptiness check, so a junk value
  overwrites the good shell one and then wins. Fix by rewriting that line in
  place, never by re-running the installer.
- ⚠️ The owner's Groq API key was printed into a session transcript on
  2026-09-25 by a careless shell expansion. **Rotating it is outstanding.**

**Not mine — leave alone:** `.DS_Store`, `.claude/`, the untracked
`dashboard-data/*performance_report.json` files.

## What has changed

- **Captions ship** (`a55eb7f`). In-app, deliberately NOT macOS Live Captions:
  the app already holds the exact answer string, so captioning its own audio
  through STT would only add latency and a way to be wrong.
- **Johnny has his own TCC identity** (`df801d8`). The mic re-prompt was a
  code-signing problem: Homebrew python3.14 is ad-hoc signed, no team
  identifier, at a version-pinned Cellar path. `launchctl` now lists
  `application.com.mavis.johnny.*`, `mdls` reports the app as "Johnny", and the
  avatar's python runs as a descendant of the bundle executable.
- **The cigarette is seated in his fingers** (`b158052`). It had been fitted
  against the BIND POSE: invisible inside the hand at frame 0, speared through
  the fingers by frame 30. Re-fitted against the clip.
- **Pose changes cross-fade and hold** (`02b8850`). `actor.loop()` restarted at
  frame 0 (the "glitch"), and the moment table flashed `smoking` for a short
  think then snapped back to `idle`.
- **He refuses instead of inventing** (`9f21df2`). Verified live: "what is the
  macro gate" returned a description of an ELECTRONICS component and "how much
  capital does tier 1 get" returned Basel III, both with zero citations.
- **Owner ratings captured**, with what NOT to change: the model is "fine" and
  the filler lines are "a good step in the right direction". The voice
  complaint was **withdrawn** ("I misspoke, it will do") — do not tune the voice.

## What has failed / risks / caveats

- **The wake word is still not trained, and two Colab runs died.** Neither was
  the Mac's fault — it is on AC power with `sleep 0` configured, verified. Free
  Colab reaps sessions nobody is interacting with ("disconnected due to
  inactivity or reaching its maximum duration"). **Do not build an auto-clicker
  to defeat that; it is what Colab's terms prohibit.** The owner must run it
  while present, or use Colab Pro.
- ⚠️ **A saved Colab copy carries five repairs and must be used instead of the
  GitHub original:** https://colab.research.google.com/drive/1DOSpcmTYB5hWwHjitbU0jslccniD5rLD
  Phrase `wake up johnny`; **`datasets>=3.0,<4.0` — the upper bound is
  load-bearing**, since 4.x replaces `row['audio']['array']` with a torchcodec
  `AudioDecoder`; `exist_ok=True` on cell 1's `makedirs`; a new cell pulling
  background noise from AudioSet's **parquet** split (the notebook's
  `bal_train09.tar` 404s — that repo has 943 parquet files and zero tars); and
  the broken noise cell deleted, which also removes the FMA `trust_remote_code`
  prompt. **Decline that prompt if it ever reappears.**
- **UNVERIFIED — everything visual.** The owner has not seen the captions, the
  re-seated cigarette, the cross-faded poses, the transparent window, or the
  200-char latency fix. He said plainly he "can't judge for it visually yet".
- **UNVERIFIED — the mic prompt has never actually fired.** The bundle is
  registered and the process tree is correct, but nobody has seen the dialog
  say "Johnny". Press W, speak, and look. Also unproven: that it survives a
  Homebrew Python upgrade, which is the thing that was breaking it.
- **The grounding hole is NOT fixed, only made honest.** Still 6 facts; still
  0 retrieval hits for macro gate, tier 1, tier pools, volatility gate,
  position sizing and drawdown breaker. The corpus is also stale (it claims
  the watchlist is AAPL/SERV while live positions are SPY and AAPL).
- **A correction worth keeping:** mid-session I believed animation blending
  left clips at zero weight, so `loop()` would freeze him in the bind pose, and
  "fixed" it. Measured: 6943 head vertices move either way — `loop()` already
  sets full weight under `animBlend`. The real cause was a test helper zeroing
  every effect on a MODULE-SCOPED fixture. The helper now restores them; that
  hazard is real and the freeze was not.

## What's next (ordered)

The owner asked for these **one at a time**, in this order.

1. **Instrument the spoken-answer latency.** His responsiveness rating is 5/10
   and "takes too long". `/ask` was measured at **~3s**, so the wait is the
   voice stage, consistent with the earlier arithmetic (ChatterboxVC ~1.5x
   realtime dominates). Measure the real split before changing anything. The
   main remaining lever, **chunked VC, needs the owner's explicit yes** — it
   breaks the voice spec's "audio is finished before the renderer animates"
   rule. Caveats for it are in the 2026-09-23 handoff.
2. **Fill the Graywind corpus.** ⚠️ **Needs an owner decision first, do not
   guess:** the mechanics live in `docs/superpowers/*.md`, but many of those
   handoffs are explicitly SUPERSEDED, so naive extraction would teach him
   stale rules. Ask which sources are authoritative. The vocabulary is already
   known — frequencies taken from the repo: `tier_pools` 303, `macro_gate` 190,
   `vix_gate` 98, `drawdown breaker` 30, `deflated sharpe` 17.
3. **Blinking / idle motion.** His eyes never close. Absence is objective even
   though "convincing" is not, so it can be verified without him via
   `tools/render_pose.py`. The full brief, with the exact joints the CDPR rig
   exposes (70 eyelid joints, `LeftEye`/`RightEye`, neck, spine, 26 brow
   joints), is appended to the plan doc under "Deferred: Task 8". Hard
   constraint: stay model-agnostic via `scene.AVATARS`, because `jonny` has
   none of those joints and is the only model the tests can load.
4. **Train the wake word** (owner present) — see the Colab link above.
5. **Rotate the Groq API key.**
6. Then `superpowers:finishing-a-development-branch`.

## Verification idioms used in this project (for the resuming session)

- **Two suites, two commands.** `cd mavis && .venv/bin/python -m pytest -q` →
  **193**. The root suite is separate (`pytest.ini` excludes `mavis/`) and this
  branch is ~160 commits behind `main`, so its count differs from main's — that
  is not a regression. A green root run does not cover MAVIS and vice versa.
- **Render it and look.** `tools/render_pose.py --clip smoking --frames 0,30
  --look ValveBiped.Bip01_R_Hand` writes a PNG. Animation defects are invisible
  to the suite and to `getTightBounds`. Two traps inside it: step the **task
  manager**, not `graphicsEngine.render_frame()`, because simplepbr feeds
  `camera_world_position` from a task; and set a near plane of 0.01, since the
  default 1.0 clips away anything closer than a metre and renders an empty
  frame that reads as "the prop is missing".
- **`Actor` is a Python class and gets none of Panda3D's snake_case aliasing.**
  `setBlend(animBlend=True)`, `setControlEffect` — and there is **no getter**
  for the control effect, so tests record the call instead of reading it back.
- **Mutation-test every behavioural change.** Each fix this session was proven
  by reverting it and confirming the right test fails: the old cigarette offset
  fails with "29mm from the grip", removing the dwell fails the defer tests,
  hard-cutting fails the blend test, removing the guard fails the refusal test.
- **Verify against the LIVE backend, not only tests:**
  `curl -s -X POST localhost:8000/ask -H "X-API-Key: $(grep '^MAVIS_API_KEY=' ~/.mavis/env | cut -d= -f2-)" -H 'Content-Type: application/json' -d '{"query":"what is the macro gate"}'`
  — expect `grounded: false` and an honest refusal.
- **`launchctl list` column 2 is the LAST EXIT STATUS, not health.** A `-15`
  beside a running service is just a `kickstart -k` SIGTERM. Check for a PID
  plus a real 200.
- **Check `lsof -nP -iTCP:8000 -sTCP:LISTEN` before blaming the backend agent** —
  a hand-started uvicorn from days earlier was once still squatting on the port.
- **Read pushed live state, never the local checkout:**
  `git show origin/main:state/tier_pools.csv`.
