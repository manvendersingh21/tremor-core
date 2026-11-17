#!/usr/bin/env bash
# Polite GPU supervisor for the shared two-GPU A6000 box (bench/results_a6000.md). Our only GPU host.
#
#   A6000_ROOT=<run folder on the box> setsid nohup bash watchdog.sh > $A6000_ROOT/logs/watchdog.log 2>&1 &
#   echo run  > $A6000_ROOT/run/want     # serve on every free GPU (one Ollama per GPU, port 11500+i, serve.sh)
#   echo stop > $A6000_ROOT/run/want     # stop our servers, keep watching
#   echo exit > $A6000_ROOT/run/want     # stop our servers and exit
#   echo manual > $A6000_ROOT/run/want   # start nothing; a server we started by hand writes run/gpu<i>.pid and is
#                                        # still killed at once on contention
#
# Poll every 5 s.
#   START  GPU i only when it has no compute process that is not ours and under 300 MiB not held by our pids, for
#          CLEAR_FIRST s (GPU 0: CLEAR_GPU0 s, its owner's job may run in stages). After a yield, also only when the
#          whole box has been quiet for RESUME_CLEAR s. Both GPUs free: both run (two servers; the runner spreads
#          its streams over them).
#   YIELD  ALL our GPUs at once when anyone else touches EITHER GPU while we hold any:
#          - on a GPU we use: any compute process that is not ours, or over 300 MiB not held by our pids;
#          - on a GPU we do not use: a compute process that was not there when we started, or memory not ours
#            rising over 300 MiB above what it was when we started (their job growing);
#          - one of our pids on a GPU we did not start it on, or the box 1-minute load above its core count.
#          Memory readings are re-read after 1 s to skip a race. Kill = the literal pids we recorded (server tree,
#          token proxy, tunnel): TERM, KILL after 3 s, so all our VRAM is free within about 10 s.
# Every yield and resume is a line in $A6000_ROOT/logs/yield_events.log.
# shortcut: a job another user has queued but not started (no process on a GPU yet) cannot be seen from here;
# it is seen, and yielded to, the moment it touches either GPU.
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
declare -a CLEAR BASE_P BASE_M FP FM
for ((i = 0; i < N; i++)); do CLEAR[i]=0; BASE_P[i]=""; BASE_M[i]=0; done
YIELDED=0
QUIET=$RESUME_CLEAR
echo "watchdog start $(date -Is) gpus=$N cores=$CORES poll=${POLL}s limit=${LIMIT_MIB}MiB yield=all-gpus"

tree() {  # a pid and all its descendants (Ollama runs the model in child "runner" processes)
  local p=$1 k
  kill -0 "$p" 2>/dev/null || return
  echo "$p"
  for k in $(pgrep -P "$p" 2>/dev/null); do tree "$k"; done
}

ours_of() { local s; s=$(cat "$R/run/gpu$1.pid" 2>/dev/null) && [ -n "$s" ] && tree "$s" | tr '\n' ' '; }

held() { local j; for ((j = 0; j < N; j++)); do [ -n "$(ours_of $j)" ] && return 0; done; return 1; }

# fills FP[i] (sorted foreign pids, space separated) and FM[i] (MiB not held by our pids); MISPLACED = our pid off its GPU
scan_all() {
  local i j u p m used omb all_ours="" mine
  for ((j = 0; j < N; j++)); do all_ours="$all_ours $(ours_of $j)"; done
  local apps; local -a USED
  # GPU totals first, then the per-process list: while our model loads, its memory grows between the two reads, so the
  # later list holds at least what the earlier total did. The other order counted our own load as "not ours" (a false
  # yield, 2026-11-17 15:57). A stranger's memory still shows: as their pid, or as total minus listed.
  for ((i = 0; i < N; i++)); do USED[i]=$(nvidia-smi -i "$i" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' '); done
  apps=$(nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits)
  for ((i = 0; i < N; i++)); do
    mine=" $(ours_of "$i") "
    used=${USED[i]}
    omb=0; FP[i]=""
    while IFS=, read -r u p m; do
      u=${u// /}; p=${p// /}; m=${m// /}
      { [ -z "$p" ] || [ "$u" != "${UUIDS[i]}" ]; } && continue
      case "$mine" in
        *" $p "*) omb=$((omb + ${m:-0})) ;;
        *) case " $all_ours " in *" $p "*) MISPLACED=$p ;; *) FP[i]="${FP[i]} $p" ;; esac ;;
      esac
    done <<< "$apps"
    FP[i]=$(echo ${FP[i]} | tr ' ' '\n' | sort -n | tr '\n' ' ' | sed 's/ *$//')
    FM[i]=$((used - omb - 20))   # ~12-20 MiB is the idle driver baseline on this card
    [ "${FM[i]}" -lt 0 ] && FM[i]=0
  done
}

stop_gpu() {  # literal pids (server tree, proxy, tunnel), TERM, then KILL after 3 s; the tunnel URL dies with it
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

new_pid() {  # a pid in $1 that is not in $2
  local p; for p in $1; do case " $2 " in *" $p "*) ;; *) echo "$p"; return ;; esac; done
}

contention() {  # prints the reason, empty if none; only called while we hold a GPU
  local i np
  [ -n "$MISPLACED" ] && { echo "our pid $MISPLACED seen on the wrong GPU"; return; }
  for ((i = 0; i < N; i++)); do
    if [ -n "$(ours_of "$i")" ]; then
      [ -n "${FP[i]}" ] && { echo "pid ${FP[i]%% *} on GPU $i (ours)"; return; }
      [ "${FM[i]}" -gt "$LIMIT_MIB" ] && { echo "${FM[i]} MiB not ours on GPU $i (ours)"; return; }
    else
      np=$(new_pid "${FP[i]}" "${BASE_P[i]}")
      [ -n "$np" ] && { echo "new pid $np on GPU $i"; return; }
      [ "${FM[i]}" -gt $((BASE_M[i] + LIMIT_MIB)) ] && { echo "others' memory on GPU $i rose ${BASE_M[i]} -> ${FM[i]} MiB"; return; }
    fi
  done
  [ "$(awk '{print int($1)}' /proc/loadavg)" -gt "$CORES" ] && echo "box load above $CORES cores"
}

while true; do
  want=$(cat "$R/run/want" 2>/dev/null || echo stop)
  MISPLACED=""
  scan_all
  if held; then
    why=$(contention)
    if [ -n "$why" ]; then  # re-read once (1 s) so a reading taken mid-change does not kill a run
      sleep 1; MISPLACED=""; scan_all; why=$(contention)
    fi
    if [ -n "$why" ]; then
      gone=""
      for ((i = 0; i < N; i++)); do [ -n "$(ours_of "$i")" ] && { stop_gpu "$i"; gone="$gone $i"; }; CLEAR[i]=0; done
      YIELDED=1; QUIET=0
      echo "yielded GPU(s)${gone} at $(date -Is) to $why; others now: $(for ((i = 0; i < N; i++)); do printf 'GPU %s [%s] %s MiB; ' "$i" "${FP[i]}" "${FM[i]}"; done)" | tee -a "$EV"
      sleep "$POLL"; continue
    fi
  else  # nothing of ours runs: the box's current state is the baseline; any change in it means someone is active
    for ((i = 0; i < N; i++)); do
      d=$((FM[i] - BASE_M[i])); d=${d#-}
      { [ "${FP[i]}" != "${BASE_P[i]}" ] || [ "$d" -gt "$LIMIT_MIB" ]; } && QUIET=0
      BASE_P[i]=${FP[i]}; BASE_M[i]=${FM[i]}
    done
  fi
  QUIET=$((QUIET + POLL))
  for ((i = 0; i < N; i++)); do
    mine=$(ours_of "$i")
    if [ -n "${FP[i]}" ] || [ "${FM[i]}" -gt "$LIMIT_MIB" ]; then CLEAR[i]=0; else CLEAR[i]=$((CLEAR[i] + POLL)); fi
    need=$CLEAR_FIRST; [ "$i" = 0 ] && need=$CLEAR_GPU0
    if [ -z "$mine" ] && [ "$want" = "run" ] && [ "${CLEAR[i]}" -ge "$need" ] \
       && { [ "$YIELDED" = 0 ] || [ "$QUIET" -ge "$RESUME_CLEAR" ]; }; then
      [ "$YIELDED" = 1 ] && echo "resumed GPU $i at $(date -Is) after ${QUIET} s quiet" | tee -a "$EV"
      [ -f "$R/run/gpu$i.aux" ] && stop_gpu "$i"   # a proxy or tunnel left from a server that died
      A6000_ROOT=$R bash "$HERE/serve.sh" "$i" "${UUIDS[i]}"
      echo "started GPU $i at $(date -Is) pid $(cat "$R/run/gpu$i.pid" 2>/dev/null)"
    elif [ -n "$mine" ] && { [ "$want" = "stop" ] || [ "$want" = "exit" ]; }; then
      stop_gpu "$i"
      echo "stopped GPU $i at $(date -Is) (want=$want)"
    fi
  done
  held && YIELDED=0   # back up after a yield; the next yield needs a fresh quiet period again
  [ "$want" = "exit" ] && { echo "watchdog exit $(date -Is)"; exit 0; }
  sleep "$POLL"
done
