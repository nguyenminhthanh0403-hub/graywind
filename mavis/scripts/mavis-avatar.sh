#!/bin/bash
# LaunchAgent wrapper for the Johnny avatar (Panda3D window + wake word).
#
# Same env-file contract as mavis-backend.sh -- see its header for why the
# keys cannot simply be inherited.
#
# This wrapper also WAITS for the backend's port. launchd has no dependency
# graph: both agents are started at login in no guaranteed order, and an
# avatar that wins the race would fire its first /ask at a socket nobody is
# listening on. Waiting here is cheaper than teaching the runtime to retry,
# and it keeps the "backend not reachable" notice meaning a real fault rather
# than a routine login race.
set -euo pipefail

MAVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MAVIS_ENV_FILE:-$HOME/.mavis/env}"

if [ ! -r "$ENV_FILE" ]; then
    echo "mavis-avatar: no env file at $ENV_FILE -- run scripts/install_launch_agents.sh" >&2
    exit 78
fi
# shellcheck source=/dev/null
set -a; . "$ENV_FILE"; set +a

PORT="${MAVIS_PORT:-8000}"
# Bounded, not infinite: if the backend is genuinely broken we want the
# avatar to start anyway and say so on screen, not hang invisibly at login.
# He is still useful without /ask -- canned lines and dismissal work.
for _ in $(seq 1 60); do
    if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
        break
    fi
    sleep 1
done
if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    echo "mavis-avatar: backend not listening on :$PORT after 60s; starting anyway" >&2
fi

cd "$MAVIS_DIR"
exec .venv/bin/python -m avatar.app
