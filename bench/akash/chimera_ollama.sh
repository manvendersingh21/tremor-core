#!/usr/bin/env bash
# Our own Ollama server on the GPU box, in /root/chimera-llm only (own binary, own model store, own port).
# It never touches any other Ollama server, model store or app on the box.
#   chimera_ollama.sh install   download the official Ollama build into /root/chimera-llm/ollama
#   chimera_ollama.sh start     start `ollama serve` with the tuned settings below (setsid nohup, log in serve.log)
#   chimera_ollama.sh pull      pull qwen3:30b-instruct into /root/chimera-llm/models
#   chimera_ollama.sh stop      stop only this server (PID from serve.pid)
# Settings come from the environment, defaults are the tuned values from bench/results_akash_tuning.md.
set -u
D=/root/chimera-llm
BIN=$D/ollama/bin/ollama
export OLLAMA_MODELS=$D/models
export OLLAMA_HOST=${CHIMERA_OLLAMA_HOST:-127.0.0.1:11500}
export OLLAMA_NUM_PARALLEL=${OLLAMA_NUM_PARALLEL:-4}
export OLLAMA_FLASH_ATTENTION=${OLLAMA_FLASH_ATTENTION:-1}
export OLLAMA_KV_CACHE_TYPE=${OLLAMA_KV_CACHE_TYPE:-q8_0}
export OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH:-8192}
export OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE:--1}
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NO_CLOUD=1
mkdir -p "$D/models"
cd "$D" || exit 1
case "${1:-}" in
  install)
    mkdir -p "$D/ollama"
    curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | zstd -d | tar -xf - -C "$D/ollama" ;;
  start)
    setsid nohup "$BIN" serve > "$D/serve.log" 2>&1 < /dev/null &
    echo $! > "$D/serve.pid"; echo "started $(cat "$D/serve.pid")" ;;
  pull)
    "$BIN" pull qwen3:30b-instruct ;;
  stop)
    p=$(cat "$D/serve.pid" 2>/dev/null) && [ -n "$p" ] && kill "$p" && echo "stopped $p" ;;
  *) sed -n 2,9p "$0" ;;
esac
