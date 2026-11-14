#!/bin/zsh
# Check the Android phone tier: adb device, USB port forward, llama-server health. Never fails hard.
PORT=${PHONE_PORT:-8081}
command -v adb >/dev/null || { echo "adb not found. Install: brew install android-platform-tools"; exit 0; }
adb devices
adb get-state >/dev/null 2>&1 || { echo "No Android device connected (enable USB debugging, plug in, accept the prompt)."; exit 0; }
adb forward tcp:$PORT tcp:8080 && echo "forward: 127.0.0.1:$PORT -> phone:8080"
if curl -s -m 5 127.0.0.1:$PORT/health; then echo; echo "phone-3b healthy. Set enabled = true for it in chimera.toml."
else echo "No answer. Start llama-server in Termux (scripts/android_setup.sh prints the steps)."; fi
