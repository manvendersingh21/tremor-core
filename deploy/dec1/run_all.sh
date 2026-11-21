#!/usr/bin/env bash
# Dec-1 one-command big-model runner.
#
# Usage (on the GPU box, or locally for a dry-run / Crusoe-only smoke):
#
#   bash deploy/dec1/run_all.sh                # auto-detect: no GPU -> Crusoe only + watchdog skip
#   SKIP_120B=1 bash deploy/dec1/run_all.sh    # force-skip the 120B tier
#   DRY_RUN=1   bash deploy/dec1/run_all.sh    # print commands, do not run them
#
# Needs in .env (never printed here):
#   CRUSOE_API_KEY     Crusoe DeepSeek-V4.1-Flash 763B
#   CHIMERA_DB_URL     Supabase cache + bank
#   CHIMERA_120B_URL   (optional) vLLM gpt-oss-120b endpoint
#   CHIMERA_120B_KEY   (optional) vLLM bearer token
#   A6000_ROOT         (optional) path on the GPU box for the watchdog
#
# No GPU?  The script detects nvidia-smi absence and sets SKIP_GPU=1 automatically.
# No CHIMERA_120B_URL?  The 120B step is skipped cleanly (SKIP_120B defaults to 1).
#
# Output: bench/.scratch/dec1/  (git-ignored, one row per item, resumable)
# Logs:   bench/.scratch/dec1/run_all.log
#
# shortcut: the watchdog and 120B tier are only started when A6000_ROOT and
#   CHIMERA_120B_URL are set; otherwise this is a Crusoe + cache-only run.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
LOG=$ROOT/bench/.scratch/dec1/run_all.log
mkdir -p "$ROOT/bench/.scratch/dec1"
exec > >(tee -a "$LOG") 2>&1

echo "=== Dec-1 runner started $(date -Iseconds) ==="
cd "$ROOT"

# ---- load .env (variable names only, no values printed) ----
if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source <(grep -v '^\s*#' "$ROOT/.env" | grep '=')
    set +a
fi

# ---- detect GPU ----
if command -v nvidia-smi >/dev/null 2>&1; then
    HAS_GPU=1
    echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
else
    HAS_GPU=0
    echo "GPU: none detected, running Crusoe + cache only"
fi

# ---- check required credentials ----
if [ -z "${CRUSOE_API_KEY:-}" ]; then
    echo "ERROR: CRUSOE_API_KEY not set in .env — aborting" >&2
    exit 1
fi
echo "CRUSOE_API_KEY: set (${#CRUSOE_API_KEY} chars)"

if [ -z "${CHIMERA_DB_URL:-}" ]; then
    echo "ERROR: CHIMERA_DB_URL not set in .env — aborting" >&2
    exit 1
fi
echo "CHIMERA_DB_URL: set"

# ---- 120B tier ----
SKIP_120B=${SKIP_120B:-}
if [ -z "${CHIMERA_120B_URL:-}" ]; then
    SKIP_120B=1
    echo "120B tier: CHIMERA_120B_URL not set, skipping"
else
    echo "120B tier: CHIMERA_120B_URL set"
fi

# ---- watchdog for the GPU ----
if [ "$HAS_GPU" = "1" ] && [ -n "${A6000_ROOT:-}" ]; then
    echo "Starting watchdog on GPU box..."
    if [ "${DRY_RUN:-}" = "1" ]; then
        echo "[DRY_RUN] A6000_ROOT=$A6000_ROOT bash bench/a6000/watchdog.sh &"
    else
        A6000_ROOT="$A6000_ROOT" setsid nohup bash "$ROOT/bench/a6000/watchdog.sh" \
            >> "$ROOT/bench/.scratch/dec1/watchdog.log" 2>&1 &
        echo "watchdog PID: $!"
        echo "run" > "$A6000_ROOT/run/want" 2>/dev/null || true
    fi
else
    echo "watchdog: skipped (no GPU or A6000_ROOT not set)"
fi

# ---- deploy 120B vLLM if needed ----
if [ "${SKIP_120B:-1}" != "1" ] && [ "$HAS_GPU" = "1" ]; then
    echo "Starting 120B vLLM server..."
    if [ "${DRY_RUN:-}" = "1" ]; then
        echo "[DRY_RUN] CHIMERA_120B_KEY=<redacted> bash deploy/gpu120b/serve_vllm.sh"
    else
        CHIMERA_120B_KEY="${CHIMERA_120B_KEY:?CHIMERA_120B_KEY must be set}" \
            bash "$ROOT/deploy/gpu120b/serve_vllm.sh"
    fi
else
    echo "120B vLLM: skipped"
fi

PY="$ROOT/.venv/bin/python"

run_cmd() {
    if [ "${DRY_RUN:-}" = "1" ]; then
        echo "[DRY_RUN] $*"
    else
        "$@"
    fi
}

# ---- Step 1: cost-case 301 tasks ----
echo ""
echo "=== Step 1: cost-case 301 tasks (top tier) ==="
run_cmd "$PY" "$ROOT/bench/cost_case/run_tiers.py" top

# ---- Step 2: cost-case 301 tasks on 120B (if available) ----
if [ "${SKIP_120B:-1}" != "1" ]; then
    echo ""
    echo "=== Step 2: cost-case 301 tasks on 120B ==="
    run_cmd "$PY" "$ROOT/bench/cost_case/run_120b.py" gen 4
    run_cmd "$PY" "$ROOT/bench/cost_case/run_120b.py" grade 4
else
    echo ""
    echo "=== Step 2: 120B cost-case skipped ==="
fi

# ---- Step 3: 40 hard questions, full ladder ----
echo ""
echo "=== Step 3: 40 moderately-hard questions, Crusoe top ==="
# Top-only run to get the 763B-alone baseline (no GPU needed)
run_cmd "$PY" "$ROOT/bench/run_hard_live.py" run TOP

# ---- Step 4: same-box speculative (requires the GPU 120B) ----
if [ "${SKIP_120B:-1}" != "1" ] && [ "$HAS_GPU" = "1" ]; then
    echo ""
    echo "=== Step 4: same-box speculative on 120B ==="
    # shortcut: spec_job.sh requires the GPU box; run it there via the watchdog
    if [ -n "${A6000_ROOT:-}" ]; then
        run_cmd bash "$ROOT/bench/a6000/spec_job.sh"
    else
        echo "spec_job: A6000_ROOT not set, skipping"
    fi
else
    echo ""
    echo "=== Step 4: same-box speculative skipped (no 120B) ==="
fi

# ---- Step 5: generate cost-case report ----
echo ""
echo "=== Step 5: cost-case report ==="
run_cmd "$PY" "$ROOT/bench/cost_case/report.py"

# ---- shutdown 120B ----
if [ "${SKIP_120B:-1}" != "1" ] && [ "$HAS_GPU" = "1" ]; then
    echo ""
    echo "=== Shutting down 120B vLLM ==="
    if [ "${DRY_RUN:-}" = "1" ]; then
        echo "[DRY_RUN] docker rm -f chimera-120b || kill \$(cat ~/chimera-120b.pid)"
    else
        docker rm -f chimera-120b 2>/dev/null || {
            pid_file="$HOME/chimera-120b.pid"
            [ -f "$pid_file" ] && kill "$(cat "$pid_file")" 2>/dev/null || true
        }
        echo "120B stopped"
    fi
fi

# ---- stop watchdog ----
if [ "$HAS_GPU" = "1" ] && [ -n "${A6000_ROOT:-}" ]; then
    if [ "${DRY_RUN:-}" = "1" ]; then
        echo "[DRY_RUN] echo stop > \$A6000_ROOT/run/want"
    else
        echo "stop" > "$A6000_ROOT/run/want" 2>/dev/null || true
        echo "watchdog: stop signal sent"
    fi
fi

echo ""
echo "=== Dec-1 runner finished $(date -Iseconds) ==="
echo "Output: bench/.scratch/dec1/"
