#!/bin/zsh
# Start the local Qwen2.5-3B server (loopback only). Stop with: pkill -f llama-server
exec "$HOME/llama.cpp-bin/llama-b12375/llama-server" -m "$HOME/models/${1:-q3b.gguf}" \
  --host 127.0.0.1 --port 8080 -c 4096 > "${KIROCREW_SCRATCH:-/tmp}/llama.log" 2>&1
