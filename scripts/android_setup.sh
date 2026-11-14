#!/bin/zsh
# Prints the commands to run inside Termux on the phone. Nothing runs on the Mac.
# Usage: scripts/android_setup.sh [3b|1.5b]   (use 1.5b if the phone has < 6 GB RAM)
SIZE=${1:-3b}
if [ "$SIZE" = "1.5b" ]; then REPO=Qwen/Qwen2.5-1.5B-Instruct-GGUF; FILE=qwen2.5-1.5b-instruct-q4_k_m.gguf
else REPO=Qwen/Qwen2.5-3B-Instruct-GGUF; FILE=qwen2.5-3b-instruct-q4_k_m.gguf; fi
cat <<EOT
# 1. Install Termux from F-Droid (not the Play Store build). Then in Termux:
pkg update -y && pkg install -y git cmake clang curl
# 2. Build llama.cpp (about 10 min)
git clone --depth 1 https://github.com/ggml-org/llama.cpp ~/llama.cpp
cd ~/llama.cpp && cmake -B build -DGGML_NATIVE=ON && cmake --build build --config Release -j4 --target llama-server
# 3. Download the model (about 2 GB for 3B)
mkdir -p ~/models && curl -L -o ~/models/$FILE https://huggingface.co/$REPO/resolve/main/$FILE
# 4. Serve on the phone's loopback only. The Mac reaches it through adb.
termux-wake-lock
~/llama.cpp/build/bin/llama-server -m ~/models/$FILE --host 127.0.0.1 --port 8080 -c 2048 -t 4
# 5. On the Mac: scripts/phone_check.sh
EOT
