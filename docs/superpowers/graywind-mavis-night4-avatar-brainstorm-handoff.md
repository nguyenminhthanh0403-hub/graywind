# MAVIS Night 4 — Avatar Brainstorm — Session Handoff

**Written:** 2026-09-19 · **For:** whoever resumes MAVIS next — specifically to finish brainstorming, then design, then plan, then build Night 4 (the 3D-avatar desktop frontend). Written mid-brainstorm because the user is switching to the Fable 5.1 model for the rest of the build and wants a clean resume point rather than losing the thread. This **replaces** the 2026-09-18 handoff of the same name — most of its "locked decisions" are now superseded; see below.

## Goal

MAVIS Night 4 is the avatar frontend. The scope changed significantly since the last handoff: the user now explicitly wants a **real 3D rendered, animated Johnny Silverhand avatar** (Cyberpunk 2077), not the previously-locked 2D Tkinter/Canvas stylized shape. North star is unchanged: *"is it possible for the assistant to be like johnny silverhand in cp2077, appearing animation when needed and disappearing when i tell it to stop"* — an ambient presence, wake-word triggered, that talks back in a Johnny-styled voice.

This is **still mid-brainstorm** via `superpowers:brainstorming` (architectural path). Several major decisions locked this session (rendering engine, 3D asset, voice mechanism, latency budget); several structural questions remain open. No spec exists yet.

- Original 6-night plan (context only, superseded): `~/Downloads/mavis-cloud-avatar-plan.md`
- Prior handoff for this exact thread (now superseded by this file, most content voided): `docs/superpowers/graywind-mavis-night4-avatar-brainstorm-handoff.md` (2026-09-18 version — this file replaces it in place, same path)
- Night 3 (MCP wrapper) is done and unrelated — see `docs/superpowers/archive/graywind-mavis-mcp-wrapper-handoff.md`; don't reopen it.
- Spec: none yet.
- Plan: none yet.
- Progress ledger: none yet.

## How to resume (do this first)

1. `cd ~/Projects/graywind && git log --oneline -8` — confirm you're on `main`, Night 3's 5 commits (`ce340fc`..`35f0ce6`) are already there. Nothing for Night 4 is committed yet.
2. Re-invoke `superpowers:brainstorming` (architectural path) and resume from "What's next" below — do NOT restart the brainstorm from scratch. The "Locked this session" decisions were made with the user directly, not guessed.
3. **The brainstorming skill's HARD-GATE is still in effect:** no code, no `writing-plans`, no scaffolding until the design is presented in chat and the user explicitly approves it, then written to `docs/superpowers/specs/<date>-mavis-avatar-design.md` for their review.
4. **Immediate next action:** one technical check remains before the design can be written — see item 1 under "What's next" (the `.gltf` format test was started but never finished before this handoff was written; `openwakeword` is already confirmed installable, see below).

## Current state (active files)

**Branch:** `main`. Night 3 fully merged (`ce340fc`..`35f0ce6`). No Night 4 branch exists yet — start one when implementation begins (`feat/mavis-<name>` convention).

**Files created / changed:** none committed yet for Night 4.

**New, not-yet-committed environment changes:**
- `mavis/.venv` now has `panda3d`, `panda3d-gltf`, and `panda3d-simplepbr` installed (added this session via `pip install`, verified working — see below). **Not yet added to `mavis/requirements.txt`** — do that when implementation starts.

**Scratch files from this session — currently OUTSIDE the repo, need to move before/during implementation:**
- `~/Documents/jonny-silverhand.zip` — the Sketchfab "Original format" download (source/jonny.glb + textures). Has morph targets but its glb crashes the Panda3D converter (see below).
- `~/Documents/jonny_silverhand.glb` — the Sketchfab "GLB Converted format" download (separate re-export). This is the one that actually works — converts cleanly, full skeleton, but zero morphs.
- `~/Documents/jonny-silverhand-extracted/` — unzipped contents of the zip, plus `jonny_converted.bam` (the working Panda3D-format conversion of `jonny_silverhand.glb`).
- **Action needed:** move all of this into `mavis/assets/avatar/` (or similar) once implementation starts. Don't leave it in `~/Documents`.

**Not mine — leave alone:** repo's `git status` shows many untracked files from other concurrent Graywind efforts (`.DS_Store`, `.claude/`, `dashboard-data/*.json`, and handoffs/plans for tier-rebalance, punch-list, MCP-wrapper, etc. — all from other threads, some from other active sessions the same evening). Leave them alone.

## What has changed

**Voided from the 2026-09-18 handoff:**
- Locked decision #2 (Tkinter + Canvas, "stylized glowing form, not a modeled character") — **superseded.** User wants a real 3D rendered/animated avatar. Scope explicitly and knowingly expanded (user's words: "let's expand the scope... it is a very very big scope").
- The assumption that Johnny's voice = the Tom(Enhanced)/Jamie(Premium) Apple-voice blend — **this was wrong**, corrected this session (see below). That blend is Alfred's mechanism, not Johnny's.

**Resolved this session:**

1. **Siri integration — investigated twice, ruled out / subsumed both times.** (a) "Siri's logic/reasoning" — closed, no third-party API surface, not needed (MAVIS already has its own wake-word + STT + LLM answer pipeline that covers everything Siri would offer). (b) "Siri's voice" specifically — checked this machine directly: no voice named "Siri" is installed (`say -v '?'` on macOS 26.6.2 shows nothing Siri-branded) and none exists in `/System/Library/Speech/Voices/`. Not needed either way: Apple's Enhanced/Premium voices (already in the pipeline via `say`) are the same tier of on-device neural TTS tech that powers Siri's own speech output, just not the specific branded identity.

2. **3D-model extraction from the actual game (WolvenKit) is a dead end — do not re-attempt.** Two independent blockers, both confirmed: (a) No Cyberpunk 2077 install on this machine — checked the Steam library directly (`~/Library/Application Support/Steam/steamapps/`), only Hades II and Total War: Warhammer III are installed. (b) WolvenKit (the standard CP2077 asset-extraction tool) has no native macOS build — Windows/Linux only, confirmed via web search. Even with the game installed, the tooling wouldn't run here.

3. **Community-sourced model (Option D) succeeded instead.** Sourced from Sketchfab: **"Jonny Silverhand" by Stuxed** (https://sketchfab.com/3d-models/jonny-silverhand-806032afcab34b118809e864a5c54ee4) — **CC Attribution license** (must credit "Stuxed" in-app somewhere; commercial use allowed), free, 19.3k triangles (lightweight, good for the 8GB M2), A-pose (rig-ready). Note: it's a stylized fan interpretation, not screen-accurate — creator's own description admits "the metal arm is on the wrong side."
   - Sketchfab gates all downloads behind a logged-in account (confirmed via a direct `401` on its download endpoint pre-login) — this is a platform requirement, not something to route around. The user logged in via Chrome (not Safari — **Safari and Chrome do not share login sessions**, this cost real time this session, don't repeat the mistake).
   - **Two different download formats behave very differently — this is the load-bearing finding:**
     - **"Original format" (`.glb`, inside `jonny-silverhand.zip`):** HAS morph targets (`mouthOpen`, `mouthSmile` per the glTF's `extras.targetNames`) and a 67-joint skin — but **crashes `panda3d-gltf`** (both v1.3.0 and v1.2.1 tested, same crash — confirmed NOT a version regression) with `GeomTriangles references vertices up to 1003, but GeomVertexData has only 557 rows` — a buffer/vertex corruption in how this specific file was packaged.
     - **"GLB Converted format" (`jonny_silverhand.glb`, a separate Sketchfab re-export):** Converts cleanly with `gltf2bam`, **zero errors**. Verified by loading in Panda3D: full **70-joint humanoid skeleton** intact (Hips → Spine → Spine1 → Spine2 → Neck → Head, full finger rig on both hands, LeftEye/RightEye) — genuinely animatable for body/gesture. But **zero morph targets / `CharacterSlider` nodes survived**, confirmed by direct inspection.
   - **No jaw bone exists in either skeleton** (confirmed via full joint dump — only Head/Neck/LeftEye/RightEye near the face, no Jaw). **This means: as things stand, this avatar has no mechanism to move its mouth at all** — not a "pick the fallback" situation, a "nothing to drive" situation, unless the untried third format works.
   - **Neither downloaded file has any embedded animation clips** (checked both — `gltf.get('animations', [])` is empty on both). Idle/talk/gesture animations will need a separate source — Mixamo is the obvious candidate, and it's also a login-gated web tool like Sketchfab was; expect similar friction (account login, can't be automated headlessly).
   - **Untried option, worth trying before concluding mouth animation is impossible:** Sketchfab also offers a `.gltf` "Converted format" (3MB) — a third, separate re-export pathway distinct from both files already tested. Nobody has downloaded or converted this one yet. This is the immediate next technical check (see "What's next").

4. **Rendering engine locked: Panda3D + `panda3d-gltf`.** Chosen over a heavier game engine (Unity/Godot/external VTuber software) specifically because of the 8GB M2 RAM constraint — see the design principle below. Installs cleanly via `pip install panda3d panda3d-gltf` as a native `cp314` universal2 wheel in `mavis/.venv` (python 3.14.6) — verified this session, no wheel-availability blocker (this was a real risk worth checking, given `openwakeword` has a similar risk still untested — see "What's next").
   - **Design principle locked alongside this:** decouple heavy local compute from rendering. Generate the full spoken-answer audio first (STT → LLM → TTS/voice-conversion, one local neural net running at a time), *then* animate the avatar while that finished audio plays back. Never run two heavy local neural steps concurrently — this is what makes an 8GB M2 workable at all for both a 3D renderer and a local voice model.

5. **Voice mechanism corrected, then re-decided, with a hard latency finding.**
   - **Correction:** the original assumption (Johnny's voice = ChatterboxVC blend of Tom(Enhanced)/Jamie(Premium)/user's voice) is **wrong**. Reading Bullion's actual `bullion-live-map/scripts/generate_narration.py` (lines 10-18) shows that's Alfred's mechanism only. **Johnny is generated by `ChatterboxTTS`** (generative diffusion TTS, not voice conversion) using a **hired voice actor's recording** (`audio/voice_sample/actor_sample.wav`) as the sole cloning reference — no `say` scaffold, no blending. User has confirmed the actor's voice rights are open for reuse in other projects (not scoped to Bullion only) — this was asked and confirmed this session.
   - **Critical latency finding — `ChatterboxTTS` is ruled out for MAVIS.** Measured on this machine (MPS device): 44s model load + 176s first generation + **80s steady-state generation for one short sentence (~2s of output audio)**. This is a hard real-time blocker, not a soft one — two orders of magnitude from usable.
   - **Fallback mechanism chosen and locked instead: `ChatterboxVC`** (voice conversion — Alfred's existing production mechanism), applied to a fast `say` reading, but re-targeted at the **actor's single reference clip** (not Alfred's Tom/Jamie/user blend) to get a Johnny-*styled* voice. Measured: 14.85s model load + 1.14s reference embedding (both one-time per session) + **9.19s generation for 6.67s of input audio — a ~1.4x-realtime RATE, not a fixed cost.** A 20-second spoken answer would take roughly 28s to convert, not 9s. **The design must express this as a rate against response length, and either cap answer length or budget latency that scales with it** — do not carry forward "~9-10s per response" as a flat number, that was an imprecise summary corrected later the same session.
   - Total round-trip estimate (Groq STT + Groq LLM + this VC step) is roughly 12-15s+ for a short answer, scaling up for longer ones. User approved this mechanism and this latency profile as the locked voice path for MAVIS.
   - Caveat to carry forward: this VC-based voice is **not literally identical** to Bullion's existing `ChatterboxTTS`-generated Johnny clips — same target voice identity (the actor's clip), different generation mechanism, so delivery/character may differ somewhat. Not tested side-by-side for how close it sounds.

## What has failed / risks / caveats

- **Nothing has failed outright** — the session converged on a working path for every piece except mouth animation, which is a real, unresolved gap, not a failure.
- **RESOLVED, no longer a risk:** `openwakeword` installs cleanly in `mavis/.venv` (python 3.14) — confirmed this session via `pip install openwakeword`, no wheel-availability failure (it pulled a native `cp314` `onnxruntime` wheel fine). Its `Model` class imports successfully. **Its shipped pretrained models are:** `alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather` — confirmed by inspecting `openwakeword.MODELS` directly, not assumed. Note there is **no `hey_mavis` or literal "hey mavis" option** — pick one of the six above for the wake phrase (the original handoff's guess of "hey jarvis" is in fact still current and available).
- **STILL UNRESOLVED — mouth/lip-sync.** The chosen asset literally has no morph targets and no jaw bone in its working (skeleton-intact) form. **The `.gltf` "Converted format" download (the last untried option) was started but never completed this session** — the browser download was clicked and hit Chrome's "Keep this file?" hold, but the model was switched away before the user confirmed it, so no `.gltf` file exists on disk yet. This is now the single most important unfinished technical check — see "What's next" #1. If it doesn't yield morphs either, fall back to: (a) find/fix a different asset, (b) ship v1 with body/idle animation only, no mouth movement during speech, (c) attempt to repair the "Original format" file's corrupted buffer (would likely need Blender, which is **not installed** on this machine — would be a new dependency to add).
- **Latency is a real, accepted constraint, not a blocker** — ~12-15s+ round-trip for short answers, scaling with response length. The user explicitly accepted this after seeing the real measured numbers (not the initial estimate). If a resuming session's design assumes sub-5s response times, that contradicts what was actually measured and approved.
- **Scope risk carried forward from the original handoff, now larger:** the original handoff flagged "full wake-word Silverhand mode" as 2-3x the build surface of push-to-talk. Since then, scope grew further (2D Canvas → real 3D rendering + animation pipeline + asset sourcing/conversion + a second voice-mechanism pivot). **If a resuming session's build runs long, land a smaller working slice** (e.g., avatar renders + wake word works + text-only reply first, voice/animation layered in after) rather than force-finishing everything in one sitting.

## What's next (ordered)

1. **Finish the Sketchfab `.gltf` "Converted format" download (3MB)** for the Jonny Silverhand model (https://sketchfab.com/3d-models/jonny-silverhand-806032afcab34b118809e864a5c54ee4, logged in via Chrome — not Safari, see the login-session trap above) — separate re-export pathway from both files already tested. Convert with `gltf2bam` and check for surviving morph targets (`CharacterSlider` nodes) the same way the other two formats were checked. This determines whether mouth animation is possible at all with this asset. **This was started and interrupted mid-download this session — pick it up here first, don't skip it as "probably already tried."**
2. **Ask the user one combined question** (per the brainstorming skill, still one topic at a time is fine, but these two are small enough to combine): (a) mouth-animation fallback given the finding above, and (b) dismiss mechanics — spoken phrase / timeout / both (never asked this session).
3. **Pick the wake phrase** from `openwakeword`'s actual confirmed shipped set: `alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather` — likely `hey_jarvis` given the Silverhand/assistant framing, but confirm with the user rather than assuming.
4. **State, don't re-ask, the direct-HTTP-vs-MCP architecture question** from the original handoff — the reasoning already in that handoff (same-machine simple GUI app, `httpx` direct to `/ask`, same pattern as `mavis/mcp_tools.py`'s `call_ask`) is sound; present it as a decision in the design and let the user veto rather than opening it as a fresh question.
5. Once the above resolve, present the full design in chat per the brainstorming skill's architectural path (architecture, components, data flow, error handling, testing — scaled sections, approval after each). Several sections are effectively pre-approved from this session's live discussion (rendering engine, asset, voice mechanism, latency budget, wake-word library) — state them as settled rather than re-litigating.
6. Write the spec to `docs/superpowers/specs/<date>-mavis-avatar-design.md`, commit it, get the user to review that file specifically.
7. `superpowers:writing-plans` for the implementation plan. Include moving the scratch asset files (see "Current state") into the repo, and adding `panda3d`/`panda3d-gltf`/`panda3d-simplepbr`/`openwakeword` to `mavis/requirements.txt` (none of the four are in it yet — all were pip-installed ad hoc this session).
8. Implement — default to the `delegate` skill first, Claude subagents/direct-write only for pieces that genuinely need live tool access or are security-sensitive.
9. Live-verify before calling it done: actually speak the wake phrase, watch the avatar render and animate, hear the converted voice — this project's established discipline (every MAVIS session so far) is "hit it live, don't trust tests alone."

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — MAVIS's existing suite, 50/50 as of Night 3's merge; nothing for Night 4 exists to test yet.
- Model/library installs: verify with a real `pip install` + a real load/convert/inspect script, not just "should work" — this is exactly how the Panda3D wheel check and both glTF-conversion checks were done this session, and exactly the pattern to repeat for `openwakeword`.
- Timing/latency claims: measure with a real script and a warm second call (steady-state), not the first call alone (which includes one-time setup cost) — this is how the ChatterboxTTS-vs-ChatterboxVC decision was actually made this session, and caught an initial rough estimate that was too optimistic once corrected against the real numbers.
- The real acceptance test for the finished avatar: wake word audible → window/avatar appears and animates → question answered in the converted voice → dismiss phrase or timeout → avatar disappears. Automated tests can cover the non-GUI logic; the render/audio pipeline itself needs a real live run before being called done.

## Locked decisions (superseding the 2026-09-18 handoff's list)

1. **Runtime surface:** Desktop app with a real 3D rendered avatar (not a 2D Canvas shape — this supersedes the prior handoff's decision #1/#2).
2. **Rendering engine:** Panda3D + `panda3d-gltf`. Confirmed installable and working on this machine (python 3.14, cp314 wheel).
3. **3D asset:** Sketchfab's "Jonny Silverhand" by Stuxed, CC Attribution (credit required). Use the "GLB Converted format" file (working skeleton, no morphs, no animations) unless the untried `.gltf` format proves better.
4. **Voice scope:** Full wake-word "Silverhand mode" (always-listening) — unchanged from the original handoff.
5. **Wake-word mechanism:** Pretrained `openWakeWord` — confirmed installable on python 3.14 this session (native `onnxruntime` wheel, no issues). Confirmed shipped pretrained models: `alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather` (no "hey mavis" option exists). Exact phrase choice still open — see "What's next" #3.
6. **STT:** Groq's Whisper endpoint — unchanged, unchallenged this session.
7. **Voice output mechanism:** `ChatterboxVC` (voice conversion) targeting the Bullion Johnny actor's reference clip, applied to a fast `say` reading — NOT `ChatterboxTTS` (too slow, measured and ruled out) and NOT the Tom/Jamie/user blend (that's Alfred's, a different persona). Latency: ~1.4x-realtime rate, not a flat per-response cost.
8. **Compute sequencing:** Never run two heavy local neural steps concurrently (voice conversion and 3D rendering) — generate full audio first, then animate during playback. This is the load-bearing decision that keeps the 8GB M2 viable at all.
