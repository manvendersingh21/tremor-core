#!/usr/bin/env bash
# Keep the SSH tunnel to your GPU box (Ollama, the GPU 30B tier) up, and heal it when it dies or hangs.
# Reads from .env (names only, values stay there):
#   CHIMERA_GPU_SSH  ssh alias of the GPU box (a Host entry in your ssh config)
#   CHIMERA_GPU_URL  local end of the tunnel, http://127.0.0.1:<port>
#   CHIMERA_GPU_REMOTE  optional, Ollama on the box, default 127.0.0.1:11434
# Only a local port forward is opened. Nothing on the GPU box is started, stopped or changed.
# Health probe: GET <CHIMERA_GPU_URL>/api/tags every PROBE_S seconds; FAILS_MAX misses in a row kill this
# script's own ssh, and the loop reconnects 2 s later.
# Usage: scripts/gpu_tunnel_keep.sh   (make gpu-keep; log: bench/.scratch/gpu_tunnel.log)
# Stop: pkill -f gpu_tunnel_keep.sh, then lsof -ti tcp:<port> and kill that number.
cd "$(dirname "$0")/.." || exit 1
mkdir -p bench/.scratch
LOG=bench/.scratch/gpu_tunnel.log
env_get() { [ -n "${!1:-}" ] && { echo "${!1}"; return; }; grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
HOST=$(env_get CHIMERA_GPU_SSH)
URL=$(env_get CHIMERA_GPU_URL)
REMOTE=$(env_get CHIMERA_GPU_REMOTE); REMOTE=${REMOTE:-127.0.0.1:11434}
PORT=${URL##*:}; PORT=${PORT%%/*}
PROBE_S=${PROBE_S:-5}
FAILS_MAX=${FAILS_MAX:-2}
if [ -z "$HOST" ] || [ -z "$PORT" ]; then
  echo "set CHIMERA_GPU_SSH and CHIMERA_GPU_URL in .env" >&2; exit 2
fi
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
while true; do
  ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 \
      -o ServerAliveInterval=10 -o ServerAliveCountMax=2 \
      -L "127.0.0.1:$PORT:$REMOTE" "$HOST" </dev/null >> "$LOG" 2>&1 &
  pid=$!
  log "tunnel start pid $pid"
  fails=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep "$PROBE_S"
    if curl -s -o /dev/null -m 3 "$URL/api/tags"; then
      [ "$fails" -gt 0 ] && log "probe ok again"
      fails=0
    else
      fails=$((fails + 1))
      log "probe miss $fails/$FAILS_MAX"
      if [ "$fails" -ge "$FAILS_MAX" ]; then
        log "tunnel hung: kill pid $pid"
        kill "$pid" 2>/dev/null
        sleep 3
        kill -9 "$pid" 2>/dev/null
        break  # a killed child stays a zombie (kill -0 passes) until wait reaps it below
      fi
    fi
  done
  wait "$pid" 2>/dev/null
  log "tunnel exit code $?; reconnect in 2 s"
  sleep 2
done
