#!/bin/bash
# Runs ON the GPU box. Start: bash /root/chimera-verify/start_verifier.sh   Stop: pkill -f verify_server.py
# Loopback only. Same GGUF blob Ollama uses (read-only). ~12 GB VRAM budget via 24 GPU layers.
cd /root/chimera-verify && . venv/bin/activate && . ./env.sh
BLOB=/root/quarantinepay/.local/models/blobs/sha256-78b329e716e7e9775973d392cd132b1f1ff1c8287a992887caeb6fd6c56ba9cc
setsid nohup python verify_server.py --model "$BLOB" --port "${PORT:-18101}" \
  --n-gpu-layers "${NGL:-24}" > server.log 2>&1 < /dev/null &
echo started
