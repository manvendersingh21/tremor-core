#!/usr/bin/env bash
# Keep the one web server (castle, dashboard, API) up: restart it 2 s after any exit.
# Usage: scripts/web_keep.sh          (logs to bench/.scratch/web.log; stop with: pkill -f web_keep.sh; pkill -f hud-web/server.py)
cd "$(dirname "$0")/.." || exit 1
mkdir -p bench/.scratch
LOG=bench/.scratch/web.log
while true; do
  echo "$(date '+%F %T') start" >> "$LOG"
  make web >> "$LOG" 2>&1
  echo "$(date '+%F %T') exit code $?; restart in 2 s" >> "$LOG"
  sleep 2
done
