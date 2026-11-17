#!/usr/bin/env bash
# Minor result: same-box speculative decoding on ONE free GPU (llama.cpp; Ollama has no draft model).
#   A6000_ROOT=... bash spec_job.sh <gpu index> <gpu uuid> <30B gguf> <draft gguf> <prompts.jsonl>
# Run with run/want = manual, so watchdog.sh starts nothing but still kills our llama-server (pid in run/gpu<i>.pid)
# the moment someone else touches the GPU. Plain run first, then the same model with the draft, 48 prompts each.
set -u
R=${A6000_ROOT:?}; I=$1; UUID=$2; BIG=$3; DRAFT=$4; P=$5
HERE=$(cd "$(dirname "$0")" && pwd)
LS=$R/llama.cpp/build/bin/llama-server
PORT=$((11700 + I))
OUT=$R/rows/spec_rows.jsonl
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$UUID HOME=$R/home

serve() {  # $1 label, rest: extra llama-server args
  local label=$1; shift
  setsid nohup "$LS" -m "$BIG" -ngl 99 -c 8192 -fa on --host 127.0.0.1 --port $PORT -np 1 "$@" \
    >> "$R/logs/llama_$label.log" 2>&1 < /dev/null &
  echo $! > "$R/run/gpu$I.pid"
  for _ in $(seq 1 180); do curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && return 0; sleep 1; done
  echo "server $label did not come up"; return 1
}
stop() { local p; p=$(cat "$R/run/gpu$I.pid" 2>/dev/null); [ -n "$p" ] && kill "$p"; sleep 3; [ -n "$p" ] && kill -0 "$p" 2>/dev/null && kill -9 "$p"; rm -f "$R/run/gpu$I.pid"; }

for label in ${LABELS:-plain spec}; do
  if [ "$label" = plain ]; then serve plain || exit 1
  else serve spec --spec-type draft-simple -md "$DRAFT" -ngld 99 --spec-draft-n-max 16 --spec-draft-n-min 1 || exit 1; fi
  python3 "$HERE/spec_run.py" "http://127.0.0.1:$PORT" "$P" 48 "$OUT" "$label" || echo "run $label failed"
  stop
done
echo SPEC_DONE
