#!/usr/bin/env bash
# gpu-120b tier: run this ON the GPU box you rent. Serves openai/gpt-oss-120b (MXFP4, about 65 GB of weights) with
# vLLM, OpenAI-compatible, on 127.0.0.1:$PORT of the box only. Reach it from the Mac through an SSH tunnel; never
# open the port to the internet. Setup and the GPU table: docs/handoff/tier_120b.md.
#
# Needs: an NVIDIA driver, Docker with the NVIDIA container runtime, about 70 GB of free disk for the weights.
# Token: the same random value as CHIMERA_120B_TOKEN in the Mac's .env. It reaches vLLM as VLLM_API_KEY through the
# environment (not argv, not this file).
#
#   export CHIMERA_120B_TOKEN=<the value from your .env>
#   bash serve_vllm.sh          # starts the container, waits until /health answers (first start downloads weights)
#   docker logs -f chimera-120b # watch it
#   docker rm -f chimera-120b   # stop it (the weights stay in ~/.cache/huggingface)
set -euo pipefail
: "${CHIMERA_120B_TOKEN:?export CHIMERA_120B_TOKEN first (same value as in the Mac .env)}"
MODEL=${MODEL:-openai/gpt-oss-120b}
PORT=${PORT:-8000}
IMAGE=${IMAGE:-vllm/vllm-openai:v0.33.0}   # the tag that served gpt-oss-120b on the Modal H200 (bench/results_modal.md)
MAXLEN=${MAXLEN:-32768}
WAIT_S=${WAIT_S:-1800}

N=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l | tr -d ' ')
CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')  # MiB per GPU
echo "GPUs: $N x ${MEM} MiB, compute capability $CC"
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

docker rm -f chimera-120b >/dev/null 2>&1 || true
VLLM_API_KEY="$CHIMERA_120B_TOKEN" docker run -d --name chimera-120b --gpus all --ipc=host \
  --restart unless-stopped -p "127.0.0.1:$PORT:8000" -e VLLM_API_KEY \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  "$IMAGE" --model "$MODEL" --served-model-name "$MODEL" --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size "$TP" --max-model-len "$MAXLEN" --gpu-memory-utilization 0.90 \
  --enable-prefix-caching --max-logprobs 20 >/dev/null
echo "started chimera-120b (tensor parallel $TP); waiting for /health (first start downloads about 65 GB)"
for _ in $(seq 1 $((WAIT_S / 10))); do
  if curl -fs -o /dev/null -m 3 "http://127.0.0.1:$PORT/health"; then
    echo "ready on 127.0.0.1:$PORT of this box"
    exit 0
  fi
  if ! docker ps -q -f name=chimera-120b | grep -q .; then
    echo "the container stopped; last log lines:" >&2
    docker logs --tail 40 chimera-120b >&2 || true
    exit 1
  fi
  sleep 10
done
echo "not ready after ${WAIT_S}s; see docker logs chimera-120b" >&2
exit 1
