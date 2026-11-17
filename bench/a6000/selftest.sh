#!/usr/bin/env bash
# Self-test of watchdog.sh with a fake nvidia-smi and fake servers (sleeps). Touches no GPU.
#   bash selftest.sh <new scratch folder>
# 1. GPU 0 busy (someone's job), GPU 1 free: we start on GPU 1 only, and their steady job does not make us yield.
# 2. A NEW pid appears on GPU 0 (not our GPU): we kill our GPU 1 server too, within ~10 s, and log it.
# 3. After the box is quiet again and GPU 0's job ends: we start on BOTH GPUs.
# 4. A stranger appears on GPU 1: BOTH our servers die within ~10 s.
set -u
T=${1:?scratch folder}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$T/bin" "$T/fake" "$T/run" "$T/logs"
cat > "$T/bin/serve.sh" <<'EOF'
#!/usr/bin/env bash
setsid nohup sleep 1000 > /dev/null 2>&1 < /dev/null &
echo $! > "$A6000_ROOT/run/gpu$1.pid"
EOF
cat > "$T/fake/nvidia-smi" <<'EOF'
#!/usr/bin/env bash
F=$(dirname "$0")
case "$*" in
  *"--query-gpu=uuid"*) echo "GPU-zero"; echo "GPU-one" ;;
  *"-i 0"*) cat "$F/mem0" ;;
  *"-i 1"*) cat "$F/mem1" ;;
  *"--query-compute-apps"*) cat "$F/apps" 2>/dev/null ;;
esac
EOF
chmod +x "$T/fake/nvidia-smi"
sed -e 's/^CLEAR_FIRST=60/CLEAR_FIRST=5/' -e 's/^CLEAR_GPU0=600/CLEAR_GPU0=10/' -e 's/^RESUME_CLEAR=300/RESUME_CLEAR=15/' \
  "$HERE/watchdog.sh" > "$T/bin/watchdog.sh"
F=$T/fake
set_state() {  # $1 = apps lines, $2 = mem0, $3 = mem1
  printf '%b' "$1" > "$F/apps"; echo "$2" > "$F/mem0"; echo "$3" > "$F/mem1"
}
pid_of() { cat "$T/run/gpu$1.pid" 2>/dev/null; }
wait_for() { local n=$1; shift; for _ in $(seq 1 "$n"); do "$@" && return 0; sleep 1; done; return 1; }
gone() { ! kill -0 "$1" 2>/dev/null; }
fail() { echo "FAIL: $*"; echo exit > "$T/run/want"; sleep 6; exit 1; }

set_state 'GPU-zero, 999999, 18000\n' 18012 12
echo run > "$T/run/want"
PATH="$F:$PATH" A6000_ROOT=$T setsid nohup bash "$T/bin/watchdog.sh" > "$T/logs/watchdog.log" 2>&1 < /dev/null &

# 1
wait_for 30 test -s "$T/run/gpu1.pid" || fail "never started on GPU 1"
P1=$(pid_of 1)
set_state "GPU-zero, 999999, 18000\nGPU-one, $P1, 20000\n" 18012 20012
sleep 12
[ -s "$T/run/gpu0.pid" ] && fail "started on busy GPU 0"
kill -0 "$P1" 2>/dev/null || fail "yielded to the steady GPU 0 job"
echo "1 ok: on GPU 1 only; GPU 0's steady job left alone"

# 2
set_state "GPU-zero, 999999, 18000\nGPU-zero, 555555, 4000\nGPU-one, $P1, 20000\n" 22012 20012
t0=$(date +%s)
wait_for 15 gone "$P1" || fail "GPU 1 server not killed after a new pid on GPU 0"
echo "2 ok: new pid on GPU 0 -> our GPU 1 server killed in $(( $(date +%s) - t0 )) s"
set_state 'GPU-zero, 999999, 18000\nGPU-zero, 555555, 4000\n' 22012 12

# 3
sleep 6
set_state '' 12 12   # their jobs end
wait_for 60 test -s "$T/run/gpu0.pid" || fail "did not start on GPU 0 once it was free"
wait_for 10 test -s "$T/run/gpu1.pid" || fail "did not restart on GPU 1"
A=$(pid_of 0); B=$(pid_of 1)
set_state "GPU-zero, $A, 20000\nGPU-one, $B, 20000\n" 20012 20012
sleep 6
echo "3 ok: both GPUs ours"

# 4
set_state "GPU-zero, $A, 20000\nGPU-one, $B, 20000\nGPU-one, 424242, 900\n" 20012 20912
t0=$(date +%s)
wait_for 15 gone "$A" || fail "GPU 0 server not killed after a stranger on GPU 1"
wait_for 5 gone "$B" || fail "GPU 1 server not killed"
echo "4 ok: stranger on GPU 1 -> both servers killed in $(( $(date +%s) - t0 )) s"
echo exit > "$T/run/want"; sleep 6
echo "PASS"; cat "$T/logs/yield_events.log"
