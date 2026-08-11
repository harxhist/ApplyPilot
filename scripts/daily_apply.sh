#!/usr/bin/env bash
# Daily Harsh apply loop — target ≥50 applications / hour.
#
# LLM: Cursor Agent (LLM_PROVIDER=cursor, LLM_MODEL=default / Auto).
#   Gemini stays in the fallback chain if Cursor usage is exhausted.
#   LLM_MIN_INTERVAL_SEC=2 (Cursor); raise if you hit limits.
#
# Throughput sketch (50 applies / 60 min):
#   tailor+cover via Cursor ~10–45s/call (reused agent); apply: 3–4 workers
#
# Usage:
#   ./scripts/daily_apply.sh                 # pipeline + apply 50
#   ./scripts/daily_apply.sh --overnight     # apply --no-hitl
#   ./scripts/daily_apply.sh --pipeline-only
#   ./scripts/daily_apply.sh --apply-only
#   LIMIT=50 WORKERS=4 LLM_MIN_INTERVAL_SEC=6 ./scripts/daily_apply.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -f "$HOME/.applypilot/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.applypilot/.venv/bin/activate"
fi

export APPLYPILOT_DIR="${APPLYPILOT_DIR:-$HOME/.applypilot}"

# Prefer Cursor Agent for tailor/cover (Gemini as fallback in chain)
export LLM_PROVIDER="${LLM_PROVIDER:-cursor}"
export LLM_MIN_INTERVAL_SEC="${LLM_MIN_INTERVAL_SEC:-2}"
export LLM_QUOTA_COOLDOWN_SEC="${LLM_QUOTA_COOLDOWN_SEC:-600}"
# Cursor Auto routing — works when composer usage is exhausted
export LLM_MODEL="${LLM_MODEL:-default}"
export LLM_MODEL_QUALITY="${LLM_MODEL_QUALITY:-default}"
export APPLY_MODEL="${APPLY_MODEL:-${LLM_MODEL:-default}}"

OVERNIGHT=0
PIPELINE=1
APPLY=1
WORKERS="${WORKERS:-4}"
LIMIT="${LIMIT:-50}"
MIN_SCORE="${MIN_SCORE:-8}"

for arg in "$@"; do
  case "$arg" in
    --overnight) OVERNIGHT=1 ;;
    --pipeline-only) APPLY=0 ;;
    --apply-only) PIPELINE=0 ;;
    --workers=*) WORKERS="${arg#*=}" ;;
    --limit=*) LIMIT="${arg#*=}" ;;
    --min-score=*) MIN_SCORE="${arg#*=}" ;;
    --model=*) APPLY_MODEL="${arg#*=}" ;;
  esac
done

echo "== ApplyPilot hourly target (Cursor Agent) =="
echo "dir=$APPLYPILOT_DIR target_applies=$LIMIT workers=$WORKERS min_score=$MIN_SCORE"
echo "LLM_MIN_INTERVAL_SEC=$LLM_MIN_INTERVAL_SEC LLM_MODEL=$LLM_MODEL APPLY_MODEL=$APPLY_MODEL overnight=$OVERNIGHT"

if [[ ! -f "$APPLYPILOT_DIR/.env" ]]; then
  echo "Missing $APPLYPILOT_DIR/.env (need CURSOR_API_KEY, GEMINI_API_KEY, CAPSOLVER_API_KEY)"
  exit 1
fi

HOUR_START=$(date +%s)

if [[ "$PIPELINE" -eq 1 ]]; then
  echo "-- pipeline: tailor + cover (limit=$LIMIT, workers=1 for rate limit) --"
  # Serial LLM workers — parallel tailor multiplies 429s on free tier
  set +e
  applypilot run tailor cover --min-score "$MIN_SCORE" --limit "$LIMIT" --workers 1
  pipe_rc=$?
  set -e
  # 130 = Ctrl+C — do not fall through into apply
  if [[ "$pipe_rc" -eq 130 ]] || [[ "$pipe_rc" -eq 143 ]]; then
    echo "Pipeline interrupted (rc=$pipe_rc) — skipping apply."
    exit "$pipe_rc"
  fi
fi

if [[ "$APPLY" -eq 1 ]]; then
  APPLY_CMD=(
    applypilot apply
    --workers "$WORKERS"
    --limit "$LIMIT"
    --min-score "$MIN_SCORE"
    --model "$APPLY_MODEL"
  )
  if [[ "$OVERNIGHT" -eq 1 ]]; then
    APPLY_CMD+=(--no-hitl)
  fi
  echo "-- apply: ${APPLY_CMD[*]} --"
  "${APPLY_CMD[@]}"
fi

ELAPSED=$(( $(date +%s) - HOUR_START ))
applypilot status || true
echo "Elapsed ${ELAPSED}s. Target was ≥${LIMIT} applies/hour."
echo "Done. Review: applypilot dashboard"
