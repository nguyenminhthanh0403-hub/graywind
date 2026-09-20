# Canned voice attribution

Audio in this directory is **generated speech in a hired voice actor's voice**,
cloned with ChatterboxTTS from `actor_sample.wav` in the bullion-live-map
project. It is **not committed** — this repository is public, and publishing
cloned speech in someone's voice is not ours to do. Only this file and the
generator are tracked.

Source prompt:
`~/minhthanh0403/claude-projects/claudekit/bullion-live-map/audio/voice_sample/actor_sample.wav`

The line text lives in `avatar/lines.py` and IS committed — it is our writing.

## Rebuilding

Needs the narration venv (torch) and ffmpeg. From `mavis/`:

    ~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python \
        scripts/pregen_lines.py

Roughly 47 minutes for all 28 lines from cold: ChatterboxTTS runs at 35-41x
realtime on this machine, which is exactly why these lines are pre-generated
instead of spoken live. Lines already present with a matching text hash are
skipped, so adding one line costs about two minutes rather than the full run.
