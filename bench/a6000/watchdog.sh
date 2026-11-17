#!/usr/bin/env bash
# Polite GPU supervisor for the shared two-GPU A6000 box (bench/results_a6000.md).
#
#   A6000_ROOT=<run folder on the box> setsid nohup bash watchdog.sh > $A6000_ROOT/logs/watchdog.log 2>&1 &
#   echo run  > $A6000_ROOT/run/want     # serve on any free GPU
#   echo stop > $A6000_ROOT/run/want     # stop our servers, keep watching
#   echo exit > $A6000_ROOT/run/want     # stop our servers and exit
#
# Poll every 5 s. Per GPU i (one Ollama per GPU, port 11500+i, started by serve.sh):
#   START  only when GPU i has no compute process that is not ours and under 300 MiB not held by our pids,
#          for CLEAR_FIRST s before its first use (GPU 0: CLEAR_GPU0 s, its owner's job may have stages)
#          and RESUME_CLEAR s after a yield.
#   YIELD  at once, when on a GPU we use: a compute process appears that is not ours, or memory not held by
#          our pids rises above 300 MiB (re-read after 1 s to skip a race), or one of our pids shows on a GPU we
#          did not start it on, or the box 1-minute load passes its core count. Kill = the literal pids we
#          recorded: TERM, then KILL after 3 s. VRAM is free within about 10 s of the other job appearing.
# Every yield and resume is a line in $A6000_ROOT/logs/yield_events.log.
# shortcut: a job another user has queued but not started (no process on the GPU yet) cannot be seen from here;
# it is seen, and yielded to, the moment it touches the GPU.
set -u
R=${A6000_ROOT:?set A6000_ROOT}
HERE=$(cd "$(dirname "$0")" && pwd)
POLL=5
LIMIT_MIB=300
CLEAR_FIRST=60
CLEAR_GPU0=600
RESUME_CLEAR=300
mkdir -p "$R/run" "$R/logs"
EV=$R/logs/yield_events.log
CORES=$(nproc)
mapfile -t UUIDS < <(nvidia-smi --query-gpu=uuid --format=csv,noheader | tr -d ' ')
N=${#UUIDS[@]}
declare -a CLEAR YIELDED
for ((i = 0; i < N; i++)); do CLEAR[i]=0; YIELDED[i]=0; done
echo "watchdog start $(date -Is) gpus=$N cores=$CORES poll=${POLL}s limit=${LIMIT_MIB}MiB"

tree() {  # a pid and all its descendants (Ollama runs the model in child "runner" processes)
  local p=$1 k
  kill -0 "$p" 2>/dev/null || return
  echo "$p"
  for k in $(pgrep -P "$p" 2>/dev/null); do tree "$k"; done
}

ours_of() { local s; s=$(cat "$R/run/gpu$1.pid" 2>/dev/null) && [ -n "$s" ] && tree "$s" | tr '\n' ' '; }

# prints "<foreign pid or -> <MiB not held by our pids>" for GPU $1; also sets MISPLACED to our pids seen elsewhere
scan() {
  local i=$1 used omb=0 fpid="-" u p m all_ours="" j
  for ((j = 0; j < N; j++)); do all_ours="$all_ours $(ours_of $j)"; done
  local mine=" $(ours_of "$i") "
  used=$(nvidia-smi -i "$i" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
  while IFS=, read -r u p m; do
    u=${u// /}; p=${p// /}; m=${m// /}
    [ -z "$p" ] || [ "$u" != "${UUIDS[i]}" ] && continue
    case "$mine" in
      *" $p "*) omb=$((omb + ${m:-0})) ;;
      *) case " $all_ours " in *" $p "*) MISPLACED=$p ;; *) fpid=$p ;; esac ;;
    esac
  done < <(nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits)
  local f=$((used - omb - 20))   # ~12-20 MiB is the idle driver baseline on this card
  [ $f -lt 0 ] && f=0
  echo "$fpid $f"
}

stop_gpu() {  # literal pids (server tree, proxy, tunnel), TERM, then KILL after 3 s; the public URL dies with the tunnel
  local i=$1 pids p t
  pids="$(ours_of "$i") $(cat "$R/run/gpu$i.aux" 2>/dev/null)"
  rm -f "$R/run/gpu$i.url"
  for p in $pids; do kill -TERM "$p" 2>/dev/null; done
  for t in 1 2 3; do
    sleep 1
    local alive=""; for p in $pids; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ -z "$alive" ] && break
  done
  for p in $pids; do kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null; done
  rm -f "$R/run/gpu$i.pid" "$R/run/gpu$i.aux"
}

while true; do
  want=$(cat "$R/run/want" 2>/dev/null || echo stop)
  load=$(awk '{print int($1)}' /proc/loadavg)
  for ((i = 0; i < N; i++)); do
    MISPLACED=""
    read -r fpid fmb <<< "$(scan "$i")"
    why=""
    if [ "$fpid" != "-" ]; then why="pid $fpid"
    elif [ -n "$MISPLACED" ]; then why="our pid $MISPLACED seen on the wrong GPU"
    elif [ "$fmb" -gt "$LIMIT_MIB" ]; then
      sleep 1; read -r fpid fmb <<< "$(scan "$i")"
      [ "$fmb" -gt "$LIMIT_MIB" ] && why="unlisted process (${fmb} MiB not ours)"
      [ "$fpid" != "-" ] && why="pid $fpid"
    elif [ "$load" -gt "$CORES" ]; then why="box load $load above $CORES cores"
    fi
    mine=$(ours_of "$i")
    if [ -n "$why" ]; then
      CLEAR[i]=0
      if [ -n "$mine" ]; then
        stop_gpu "$i"
        YIELDED[i]=1
        echo "yielded GPU $i at $(date -Is) to $why (${fmb} MiB not ours)" | tee -a "$EV"
      fi
      continue
    fi
    CLEAR[i]=$((CLEAR[i] + POLL))
    need=$CLEAR_FIRST; [ "$i" = 0 ] && need=$CLEAR_GPU0; [ "${YIELDED[i]}" = 1 ] && need=$RESUME_CLEAR
    if [ -z "$mine" ] && [ "$want" = "run" ] && [ "${CLEAR[i]}" -ge "$need" ]; then
      [ "${YIELDED[i]}" = 1 ] && echo "resumed GPU $i at $(date -Is) after ${CLEAR[i]} s clear" | tee -a "$EV"
      YIELDED[i]=0
      [ -f "$R/run/gpu$i.aux" ] && stop_gpu "$i"   # a proxy or tunnel left from a server that died
      A6000_ROOT=$R bash "$HERE/serve.sh" "$i" "${UUIDS[i]}"
      echo "started GPU $i at $(date -Is) pid $(cat "$R/run/gpu$i.pid" 2>/dev/null)"
    elif [ -n "$mine" ] && [ "$want" != "run" ]; then
      stop_gpu "$i"
      echo "stopped GPU $i at $(date -Is) (want=$want)"
    fi
  done
  [ "$want" = "exit" ] && { echo "watchdog exit $(date -Is)"; exit 0; }
  sleep "$POLL"
done
