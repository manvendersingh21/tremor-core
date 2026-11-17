#!/usr/bin/env bash
# Self-test of watchdog.sh with a fake nvidia-smi and a fake server (a sleep). Touches no GPU.
#   bash selftest.sh <empty scratch folder>
# Checks: it starts on a clear GPU, yields within ~10 s when a foreign pid appears on that GPU, and logs the yield.
set -u
T=${1:?scratch folder}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$T/bin" "$T/fake" "$T/run" "$T/logs"
cp "$HERE/watchdog.sh" "$T/bin/"
cat > "$T/bin/serve.sh" <<'EOF'
#!/usr/bin/env bash
setsid nohup sleep 1000 > /dev/null 2>&1 < /dev/null &
echo $! > "$A6000_ROOT/run/gpu$1.pid"
echo "$A6000_ROOT/fake/apps_ours $1 $!" > "$A6000_ROOT/fake/started"
EOF
cat > "$T/fake/nvidia-smi" <<'EOF'
#!/usr/bin/env bash
F=$(dirname "$0")
case "$*" in
  *"--query-gpu=uuid"*) echo "GPU-zero"; echo "GPU-one" ;;
  *"-i 0"*) cat "$F/mem0" 2>/dev/null || echo 12 ;;
  *"-i 1"*) cat "$F/mem1" 2>/dev/null || echo 12 ;;
  *"--query-compute-apps"*) cat "$F/apps" 2>/dev/null ;;
esac
EOF
chmod +x "$T/fake/nvidia-smi"
echo "GPU-zero, 999999, 18000" > "$T/fake/apps"   # GPU 0 busy with someone else's job, as on the real box
echo 18012 > "$T/fake/mem0"
sed -e 's/^CLEAR_FIRST=60/CLEAR_FIRST=5/' "$T/bin/watchdog.sh" > "$T/bin/w.sh"
echo run > "$T/run/want"
PATH="$T/fake:$PATH" A6000_ROOT=$T setsid nohup bash "$T/bin/w.sh" > "$T/logs/watchdog.log" 2>&1 < /dev/null &
W=$!
for _ in $(seq 1 30); do [ -s "$T/run/gpu1.pid" ] && break; sleep 1; done
OURS=$(cat "$T/run/gpu1.pid" 2>/dev/null)
[ -n "$OURS" ] || { echo "FAIL: never started on GPU 1"; kill "$W"; exit 1; }
[ -s "$T/run/gpu0.pid" ] && { echo "FAIL: started on busy GPU 0"; kill "$W"; exit 1; }
echo "started on GPU 1 as pid $OURS (GPU 0 left alone)"
# our process on GPU 1, then a stranger arrives
printf 'GPU-zero, 999999, 18000\nGPU-one, %s, 20000\n' "$OURS" > "$T/fake/apps"; echo 20012 > "$T/fake/mem1"
sleep 6
printf 'GPU-zero, 999999, 18000\nGPU-one, %s, 20000\nGPU-one, 424242, 900\n' "$OURS" > "$T/fake/apps"; echo 20912 > "$T/fake/mem1"
t0=$(date +%s)
while kill -0 "$OURS" 2>/dev/null; do sleep 0.5; [ $(( $(date +%s) - t0 )) -gt 20 ] && break; done
dt=$(( $(date +%s) - t0 ))
echo exit > "$T/run/want"; sleep 6; kill "$W" 2>/dev/null
if kill -0 "$OURS" 2>/dev/null; then echo "FAIL: our pid still alive after ${dt}s"; kill "$OURS"; exit 1; fi
grep -q "yielded GPU 1 .* pid 424242" "$T/logs/yield_events.log" || { echo "FAIL: no yield logged"; exit 1; }
echo "PASS: yielded to pid 424242 in ${dt}s; log: $(cat "$T/logs/yield_events.log")"
