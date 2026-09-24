#!/bin/bash
# Installs (or refreshes) the two MAVIS LaunchAgents so Johnny is running from
# login without a terminal:
#
#   com.mavis.backend  -- uvicorn on :8000, restarted if it ever dies
#   com.mavis.avatar   -- the Panda3D window + wake-word listener
#
# Run it once:  mavis/scripts/install_launch_agents.sh
# Undo it:      mavis/scripts/install_launch_agents.sh --uninstall
# Test it:      mavis/scripts/install_launch_agents.sh --dry-run
#
# --dry-run writes the env file and both plists but does NOT touch launchd.
# It exists because there is no other safe way to exercise this script: with
# HOME pointed at a temp dir the generated plists land in the temp dir, but
# `launchctl bootstrap gui/$UID` still registers the labels in the REAL login
# session, leaving two agents behind that point at files you just deleted.
#
# Secrets never enter this repo (it is public) and never enter the plists
# (which are plain text and world-readable by default). They are written once
# to ~/.mavis/env with mode 600 and sourced by both wrappers.
set -euo pipefail

MAVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs"
ENV_FILE="$HOME/.mavis/env"
BACKEND_LABEL="com.mavis.backend"
AVATAR_LABEL="com.mavis.avatar"

unload() {
    # bootout is the modern spelling; fall back for older macOS. Neither
    # failing is fatal -- on a first install there is nothing loaded yet.
    launchctl bootout "gui/$UID/$1" 2>/dev/null \
        || launchctl unload "$AGENTS/$1.plist" 2>/dev/null \
        || true
}

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
    shift
fi

if [ "${1:-}" = "--uninstall" ]; then
    unload "$BACKEND_LABEL"
    unload "$AVATAR_LABEL"
    rm -f "$AGENTS/$BACKEND_LABEL.plist" "$AGENTS/$AVATAR_LABEL.plist"
    echo "Uninstalled. ~/.mavis/env was left in place (delete it yourself if you want the keys gone)."
    exit 0
fi

mkdir -p "$AGENTS" "$LOGS" "$(dirname "$ENV_FILE")"
chmod 700 "$(dirname "$ENV_FILE")"

# --- keys -------------------------------------------------------------
# Existing file wins, so re-running this never silently rotates a key out
# from under a running process.
if [ -r "$ENV_FILE" ]; then
    # shellcheck source=/dev/null
    set -a; . "$ENV_FILE"; set +a
fi

if [ -z "${GROQ_API_KEY:-}" ]; then
    echo "GROQ_API_KEY is not set in this shell and not in $ENV_FILE." >&2
    echo "Export it and re-run:  export GROQ_API_KEY=... " >&2
    exit 1
fi

# MAVIS_API_KEY is a SELF-CHOSEN shared secret, not a third-party key: auth.py
# just compares it against the X-API-Key header with hmac.compare_digest. Any
# random string works, but backend and avatar must agree. Generating it here
# and storing it in one file both wrappers read is what removes the documented
# footgun of setting it in two shells and getting a 401.
if [ -z "${MAVIS_API_KEY:-}" ]; then
    # `tr </dev/urandom | head -c 40` is the obvious spelling and it does NOT
    # work under `set -o pipefail`: head exits at 40 bytes, tr takes SIGPIPE,
    # and the non-zero pipeline status kills the script right here. Bound the
    # randomness at the FRONT instead, so every consumer downstream reads its
    # input to completion and nothing exits early.
    MAVIS_API_KEY="$(head -c 64 /dev/urandom | LC_ALL=C base64 | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-40)"
    echo "Generated a new MAVIS_API_KEY (self-chosen shared secret)."
fi

umask 077
cat > "$ENV_FILE" <<EOF
# Written by mavis/scripts/install_launch_agents.sh. Mode 600, outside the
# repo on purpose -- graywind is a public repo.
GROQ_API_KEY=$GROQ_API_KEY
MAVIS_API_KEY=$MAVIS_API_KEY
EOF
chmod 600 "$ENV_FILE"

chmod +x "$MAVIS_DIR/scripts/mavis-backend.sh" "$MAVIS_DIR/scripts/mavis-avatar.sh"

# --- plists -----------------------------------------------------------
# Backend: unconditional KeepAlive. It is a server; if it dies we always want
# it back. The wrapper exits 78 (EX_CONFIG) on a missing/!incomplete env file,
# and ThrottleInterval keeps even that case to one attempt per 30s rather than
# a hot loop.
cat > "$AGENTS/$BACKEND_LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$BACKEND_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$MAVIS_DIR/scripts/mavis-backend.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>$LOGS/mavis-backend.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGS/mavis-backend.log</string>
</dict>
</plist>
EOF

# Avatar: KeepAlive ONLY on unsuccessful exit, and never on a config fault.
# A clean quit (he was dismissed, or Escape) must stay quit -- unconditional
# KeepAlive would resurrect the window the moment it was closed, which is
# indistinguishable from a haunting. And if the Panda3D window cannot open at
# all (a missing keanu.bam after a rebuild, say) this bounds the damage to one
# retry per 30s instead of a respawn loop that eats the machine.
cat > "$AGENTS/$AVATAR_LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$AVATAR_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$MAVIS_DIR/scripts/mavis-avatar.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>$LOGS/mavis-avatar.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGS/mavis-avatar.log</string>
</dict>
</plist>
EOF

if [ "$DRY_RUN" = "1" ]; then
    echo "DRY RUN -- launchd untouched. Wrote:"
    echo "  $ENV_FILE"
    echo "  $AGENTS/$BACKEND_LABEL.plist"
    echo "  $AGENTS/$AVATAR_LABEL.plist"
    exit 0
fi

unload "$BACKEND_LABEL"
unload "$AVATAR_LABEL"
launchctl bootstrap "gui/$UID" "$AGENTS/$BACKEND_LABEL.plist" 2>/dev/null \
    || launchctl load "$AGENTS/$BACKEND_LABEL.plist"
launchctl bootstrap "gui/$UID" "$AGENTS/$AVATAR_LABEL.plist" 2>/dev/null \
    || launchctl load "$AGENTS/$AVATAR_LABEL.plist"

echo "Installed $BACKEND_LABEL and $AVATAR_LABEL."
echo "  keys:  $ENV_FILE (mode 600)"
echo "  logs:  $LOGS/mavis-backend.log, $LOGS/mavis-avatar.log"
echo "  stop:  $0 --uninstall"
