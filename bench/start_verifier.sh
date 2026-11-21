#!/bin/bash
# Runs ON the GPU box. Start: bash /root/chimera-verify/start_verifier.sh   Stop: pkill -f "[v]erify_server.py"
# Loopback only. Same GGUF blob Ollama uses (read-only). 30 of 49 GPU layers = ~11.4 GB VRAM.
# Load takes ~3-4 min (slow disk). Tunnel from the Mac:
#   ssh -f -N -L 127.0.0.1:18101:127.0.0.1:18101 <gpu-host>   # an SSH tunnel to your GPU box
cd /root/chimera-verify && . venv/bin/activate && . ./env.sh
BLOB=/root/quarantinepay/.local/models/blobs/sha256-78b329e716e7e9775973d392cd132b1f1ff1c8287a992887caeb6fd6c56ba9cc
setsid nohup python verify_server.py --model "$BLOB" --port "${PORT:-18101}" \
  --n-gpu-layers "${NGL:-30}" > server.log 2>&1 < /dev/null &
echo started
