# MAVIS/Johnny — Captions, Mic Identity, Wake-Word Training — Session Handoff

**Written:** 2026-09-25 · **For:** whoever resumes Johnny. Everything code-side is
**committed AND pushed** (`df801d8`). The only unfinished thread is the wake-word
model, whose Colab run did **not** complete — start at "What's next".

This **supersedes** `graywind-stop-fix-and-mavis-launch-agents-handoff.md` for MAVIS
current state. That file is still the authority on the **Graywind stop fix** (`ebd105f`)
and the **two-suite verification idioms**.

## Goal

Three owner requests, in his words: load the map into Johnny's head; captions because
"sometimes I can't hear his words since I'm in the public"; and mic access that does not
re-prompt "every time". Plus finishing the wake word.

## How to resume (do this first)

1. `cd ~/Projects/graywind-johnny` — **this is a dedicated worktree pinned to
   `feat/mavis-avatar`, and it is where Johnny runs from.** Not `~/Projects/graywind`.
2. `git log --oneline -3` — expect `df801d8`, `419fbdf`, `a55eb7f`. Pushed; `git rev-parse
   HEAD origin/feat/mavis-avatar` matched at handoff time.
3. `cd mavis && .venv/bin/python -m pytest -q` — expect **186 passed** (was 180).
4. `launchctl list | grep -iE "mavis|johnny"` — expect three entries: `com.mavis.backend`,
   `com.mavis.avatar`, and **`application.com.mavis.johnny.*`**. That third one is the
   proof the bundle identity is live; its absence means the mic fix is not in effect.
5. **Immediate next action:** re-run the wake-word training (see "What's next").

## Current state

**Committed and pushed (3 commits):**
- `a55eb7f` on-screen captions. `scene.show_caption()` + `_answer` returns `(wav, text)`.
- `419fbdf` `.gitignore` gets a bare `.venv` (the trailing-slash rule matches dirs only,
  so this worktree's **symlink** was a commit candidate in a public repo).
- `df801d8` `~/Applications/Johnny.app` bundle + the LaunchAgent rewiring.

**Live on this Mac (not in git):**
- `~/Applications/Johnny.app` — rebuild any time with `mavis/scripts/build_app_bundle.sh`.
- `~/.mavis/env` — mode 600. ⚠️ **Its GROQ_API_KEY was a 4-char placeholder** until this
  session; fixed by rewriting that line in place.
- `mavis/.venv` and `mavis/assets/*` are **symlinks into `~/Projects/graywind/mavis/`**.
  Deleting the main checkout's venv breaks Johnny.

## What has changed

- **The Bullion map was already in his head** — verified, not assumed. Re-ran
  `extract_bullion_grounding.js` against the live `bullion_mkultra.html` and diffed:
  nodes and links **byte-identical** to the committed corpus (39 nodes / 93 merged links).
  Nothing to rebuild. The Graywind-mechanics hole is unchanged and still the real gap.
- **Captions ship.** In-app, not macOS Live Captions, because the app already holds the
  exact answer string — captioning our own audio through STT could mis-hear and adds lag.
- **The mic re-prompt is a code-signing problem, not a config one.** Homebrew python3.14
  is `Signature=adhoc`, `TeamIdentifier=not set`, at a version-pinned Cellar path, so TCC
  has no stable identity to remember and lists it as "Python". The bundle fixes both.
- **A silent install bug was found and fixed:** `launchctl bootout` returns before the
  service is gone, so the immediately-following bootstrap failed with a bare "Bad request"
  and left the backend **not installed** while the script printed "Installed".

## What has failed / risks / caveats

- ⚠️ **THE WAKE-WORD RUN DID NOT FINISH AND ITS RUNTIME IS GONE.** It died mid 16.5GB
  feature download when the owner left. Colab state is not recoverable; the compute must
  be redone. **The notebook EDITS are saved** — see below.
- ⚠️ **UNVERIFIED, and it is the whole point of `df801d8`:** nobody has yet seen the
  microphone prompt say "Johnny". The bundle is registered (`application.com.mavis.johnny.*`
  in launchctl, `kMDItemDisplayName = "Johnny"`, python confirmed running as a descendant
  of the bundle executable) but the prompt itself has not fired. **Press W, speak, and
  look at the dialog.** Also unproven: that it survives a Homebrew Python upgrade.
- ⚠️ **UNVERIFIED, carried forward:** the 200-char latency fix, lipsync on real speech,
  the dismissal path, the transparent window, the cigarette hand — and now the captions.
- **The notebook is bit-rotted against Colab's current image; four separate fixes were
  needed** and a naive re-run will hit all four again. They are all saved in the Drive
  copy (link below), so USE THAT COPY, not the GitHub original.
- **Owner withdrew the voice complaint** ("I misspoke, it will do"). Do not tune the voice.

## What's next (ordered)

1. **Re-run the wake word from the SAVED COPY:**
   `https://colab.research.google.com/drive/1DOSpcmTYB5hWwHjitbU0jslccniD5rLD`
   It already contains all four fixes: the phrase set to `wake up johnny`; a
   `datasets>=3.0,<4.0` pin in the imports cell (**the upper bound matters** — 4.x replaces
   `row['audio']['array']` with a torchcodec `AudioDecoder` and the notebook breaks); a new
   cell that pulls background noise from AudioSet's **parquet** split (the notebook's
   `bal_train09.tar` 404s — that repo has 943 parquet files and zero tars); and `./fma`
   dropped from `background_paths`.
   Two things it cannot save: **cell 1's `os.makedirs` has no `exist_ok`**, so it fails on
   any re-run against a warm disk — skip cell 1 or add `exist_ok=True`. And **FMA will ask
   to execute remote code (`trust_remote_code`) — decline it**, which is why `./fma` is
   gone from the config. AudioSet needs no remote code (zero `.py` files in that repo).
   ⚠️ **Sequencing:** `Run cell and below` snapshots the cell list, so the inserted
   AudioSet cell is skipped by a run started before it existed. It must execute before
   **Step 2 (augment)**; Step 1 does not use backgrounds.
2. **Drop the model at** `~/Projects/graywind-johnny/mavis/assets/wakeword/wake_up_johnny.onnx`
   (that literal filename; the dir exists). ⚠️ It is **not** covered by `mavis/.gitignore`
   (which allowlists `assets/avatar/*` and `assets/voice/*` only), so it will appear as a
   commit candidate in a public repo — decide deliberately.
   Then `launchctl kickstart -k gui/$UID/com.mavis.avatar`.
3. **Confirm the mic prompt says "Johnny"** (item 1 under caveats).
4. **Live acceptance with the owner:** wake, a real question, captions, lipsync, dismissal.
5. **Fix the Graywind grounding corpus** — still 6 facts, still answers Basel III for
   "tier 1". Prerequisite for the "Johnny reads Bullion and Graywind" direction.
6. Then `superpowers:finishing-a-development-branch`.

## Verification idioms (additions this session)

- **Never trust an anchor position for an overlap test.** `OnscreenText` grows downward and
  `wordwrap` breaks on whitespace only, so row count follows token length, not character
  count: 420 hyphen-heavy chars reached z=-1.198 where prose took four rows. Assert
  `getTightBounds()` against the credit's top.
- **Prove a LaunchAgent installed, don't read its exit code** — `launchctl print gui/$UID/<label>`.
- **`launchctl list` column 2 is the LAST EXIT STATUS, not health.** A `-15` next to a
  running service is just the SIGTERM from a `kickstart -k`. Check for a PID plus a real 200.
- **Check `lsof -nP -iTCP:8000 -sTCP:LISTEN` before blaming the backend agent** — a
  hand-started uvicorn from days earlier was still orphaned on the port.
