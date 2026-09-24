#!/bin/bash
# LaunchAgent wrapper for the MAVIS backend (uvicorn on :8000).
#
# A LaunchAgent does NOT inherit the shell environment, so GROQ_API_KEY and
# MAVIS_API_KEY have to come from somewhere explicit. They live in
# ~/.mavis/env (chmod 600), written by install_launch_agents.sh -- NOT in the
# plist and NOT in this repo, which is public. Both this wrapper and the
# avatar wrapper source the same file, which is also what guarantees the two
# processes agree on MAVIS_API_KEY: a mismatch makes /ask return 401, and an
# unset key server-side makes it return 500.
set -euo pipefail

MAVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MAVIS_ENV_FILE:-$HOME/.mavis/env}"

if [ ! -r "$ENV_FILE" ]; then
    echo "mavis-backend: no env file at $ENV_FILE -- run scripts/install_launch_agents.sh" >&2
    exit 78   # EX_CONFIG: a config fault, not a crash. See the plist's KeepAlive.
fi
# shellcheck source=/dev/null
set -a; . "$ENV_FILE"; set +a

if [ -z "${GROQ_API_KEY:-}" ]; then
    echo "mavis-backend: GROQ_API_KEY missing from $ENV_FILE" >&2
    exit 78
fi
if [ -z "${MAVIS_API_KEY:-}" ]; then
    echo "mavis-backend: MAVIS_API_KEY missing from $ENV_FILE -- /ask would 500 on every call" >&2
    exit 78
fi

cd "$MAVIS_DIR"
exec .venv/bin/uvicorn app:app --port "${MAVIS_PORT:-8000}"
