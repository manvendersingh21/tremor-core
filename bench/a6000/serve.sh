#!/usr/bin/env bash
# Start our Ollama on ONE GPU of the shared A6000 box, behind a bearer-token proxy and a Cloudflare quick tunnel.
# Called by watchdog.sh only (it decides when a GPU is free): serve.sh <gpu index> <gpu uuid>
#   Ollama   127.0.0.1:(11500+i), CUDA_VISIBLE_DEVICES=<that GPU's UUID> (no index mix-up between tools)
#   proxy    127.0.0.1:(11600+i), needs "Authorization: Bearer <key>" (key file $A6000_ROOT/run/key, mode 600)
#   tunnel   cloudflared quick tunnel to the proxy; its https URL goes to $A6000_ROOT/run/gpu<i>.url (mode 600)
# Everything lives under $A6000_ROOT; HOME points there so nothing lands in the user's home.
set -u
R=${A6000_ROOT:?set A6000_ROOT}
I=${1:?gpu index}
UUID=${2:?gpu uuid}
HERE=$(cd "$(dirname "$0")" && pwd)
umask 077
mkdir -p "$R/run" "$R/logs" "$R/home" "$R/models"
[ -s "$R/run/key" ] || { echo "no $R/run/key: refusing to serve without a token"; exit 1; }

export HOME=$R/home OLLAMA_MODELS=$R/models OLLAMA_HOST=127.0.0.1:$((11500 + I))
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$UUID
export OLLAMA_NUM_PARALLEL=${OLLAMA_NUM_PARALLEL:-16} OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH:-16384}
export OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_LOAD_TIMEOUT=15m OLLAMA_NOHISTORY=1
setsid nohup "$R/ollama/bin/ollama" serve >> "$R/logs/ollama_gpu$I.log" 2>&1 < /dev/null &
echo $! > "$R/run/gpu$I.pid"

setsid nohup python3 "$HERE/auth_proxy.py" "$((11600 + I))" "$((11500 + I))" "$R/run/key" \
  >> "$R/logs/proxy_gpu$I.log" 2>&1 < /dev/null &
PROXY=$!
TLOG=$R/logs/tunnel_gpu$I.log
: > "$TLOG"
setsid nohup "$R/bin/cloudflared" tunnel --no-autoupdate --url "http://127.0.0.1:$((11600 + I))" \
  >> "$TLOG" 2>&1 < /dev/null &
echo "$PROXY $!" > "$R/run/gpu$I.aux"
for _ in $(seq 1 60); do  # the quick-tunnel URL shows in the log within a few seconds
  u=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TLOG" | head -1)
  [ -n "$u" ] && { echo "$u" > "$R/run/gpu$I.url"; break; }
  sleep 1
done
[ -s "$R/run/gpu$I.url" ] || echo "tunnel URL not seen for GPU $I (see $TLOG)"
