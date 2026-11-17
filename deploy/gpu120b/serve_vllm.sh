#!/usr/bin/env bash
# gpu-120b tier: run this ON the GPU box you rent. Serves openai/gpt-oss-120b (MXFP4, about 65 GB of weights) with
# vLLM, OpenAI-compatible. Setup and the GPU table: docs/handoff/tier_120b.md.
#
# Two ways to run, picked by RUNNER (default auto: docker when it works, else native when `vllm` is on PATH):
#   docker : your own box with Docker and the NVIDIA runtime. Bound to 127.0.0.1:$PORT of the box only; reach it from
#            the Mac through an SSH tunnel and never open the port to the internet.
#   native : a box that already is the vLLM image (a Daytona H100 sandbox made from vllm/vllm-openai, no Docker inside).
#            The weights are pulled first (timed), then `vllm serve` runs in the background. HOST=0.0.0.0 lets the
#            sandbox's preview proxy reach it; the vLLM API key then guards every /v1 route.
#
# Key: the same random value as CHIMERA_120B_KEY in the Mac's .env. It reaches vLLM as VLLM_API_KEY through the
# environment (not argv, not this file).
#
#   export CHIMERA_120B_KEY=<the value from your .env>
#   bash serve_vllm.sh          # starts vLLM, waits until /health answers (first start downloads weights)
#   docker logs -f chimera-120b # docker: watch it.  native: tail -f ~/chimera-120b.log
#   docker rm -f chimera-120b   # docker: stop it.   native: kill the number in ~/chimera-120b.pid
#                               # (the weights stay in ~/.cache/huggingface either way)
set -euo pipefail
: "${CHIMERA_120B_KEY:?export CHIMERA_120B_KEY first (same value as in the Mac .env)}"
MODEL=${MODEL:-openai/gpt-oss-120b}
PORT=${PORT:-8000}
IMAGE=${IMAGE:-vllm/vllm-openai:v0.33.0}   # the tag that served gpt-oss-120b on the Modal H200 (bench/results_modal.md)
MAXLEN=${MAXLEN:-32768}
WAIT_S=${WAIT_S:-1800}
RUNNER=${RUNNER:-auto}
if [ "$RUNNER" = auto ]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then RUNNER=docker
  elif command -v vllm >/dev/null 2>&1; then RUNNER=native
  else echo "neither a working docker nor vllm on PATH" >&2; exit 2; fi
fi

N=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l | tr -d ' ')
CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')  # MiB per GPU
echo "GPUs: $N x ${MEM} MiB, compute capability $CC, runner $RUNNER"
if [ "${CC%%.*}" -lt 9 ]; then
  # vLLM's gpt-oss recipe lists Hopper and Blackwell (H100, H200, B200); Ampere and Ada are still in progress.
  echo "compute capability $CC: vLLM does not serve gpt-oss MXFP4 here. See 'Other GPUs' in docs/handoff/tier_120b.md (llama.cpp)." >&2
  exit 2
fi
if [ $((N * MEM)) -lt 80000 ]; then
  echo "only $((N * MEM)) MiB of GPU memory; gpt-oss-120b needs one 80 GB GPU or more" >&2
  exit 2
fi
TP=1
[ "$MEM" -lt 80000 ] && TP=$N   # no single GPU holds the weights: split them over all GPUs
ARGS=(--served-model-name "$MODEL" --port "$PORT" --tensor-parallel-size "$TP" --max-model-len "$MAXLEN"
      --gpu-memory-utilization 0.90 --enable-prefix-caching --max-logprobs 20)

healthy() {  # curl is not in every image; python is
  python3 -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORT/health', timeout=3)" 2>/dev/null
}

if [ "$RUNNER" = docker ]; then
  docker rm -f chimera-120b >/dev/null 2>&1 || true
  VLLM_API_KEY="$CHIMERA_120B_KEY" docker run -d --name chimera-120b --gpus all --ipc=host \
    --restart unless-stopped -p "127.0.0.1:$PORT:$PORT" -e VLLM_API_KEY \
    -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
    "$IMAGE" --model "$MODEL" --host 0.0.0.0 "${ARGS[@]}" >/dev/null
  alive() { docker ps -q -f name=chimera-120b | grep -q .; }
  logs() { docker logs --tail 40 chimera-120b; }
else
  HOST=${HOST:-127.0.0.1}
  LOG="$HOME/chimera-120b.log"
  t0=$(date +%s)
  python3 -c "from huggingface_hub import snapshot_download as s; s('$MODEL', ignore_patterns=['original/*', 'metal/*'])"
  echo "weights on disk after $(( $(date +%s) - t0 )) s"
  VLLM_API_KEY="$CHIMERA_120B_KEY" setsid nohup vllm serve "$MODEL" --host "$HOST" "${ARGS[@]}" >"$LOG" 2>&1 </dev/null &
  echo $! >"$HOME/chimera-120b.pid"
  alive() { kill -0 "$(cat "$HOME/chimera-120b.pid")" 2>/dev/null; }
  logs() { tail -n 40 "$LOG"; }
fi
echo "started chimera-120b ($RUNNER, tensor parallel $TP); waiting for /health (first start downloads about 65 GB)"
t1=$(date +%s)
for _ in $(seq 1 $((WAIT_S / 10))); do
  if healthy; then
    echo "ready on port $PORT of this box after $(( $(date +%s) - t1 )) s of vLLM start"
    exit 0
  fi
  if ! alive; then
    echo "vLLM stopped; last log lines:" >&2
    logs >&2 || true
    exit 1
  fi
  sleep 10
done
echo "not ready after ${WAIT_S}s; last log lines:" >&2
logs >&2 || true
exit 1
