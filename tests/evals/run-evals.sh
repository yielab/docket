#!/usr/bin/env bash
# Eval harness — runs all *.eval.sh files in this directory.
#
# Modes:
#   ./run-evals.sh                    structural checks only (fast, no LLM calls)
#   DOCKET_EVAL_LIVE=1 ./run-evals.sh   + live golden-task checks via openclaw
#   DOCKET_EVAL_TIER=economy ./...      override the tier label written to results
#   ./run-evals.sh --recommend        print tier recommendations from stored results
#
# Each eval exits 0 (PASS), 1 (FAIL), or 2 (SKIP).
# The harness exits 0 if all evals pass or skip; exits 1 on any FAIL.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

# ── --recommend: print tier hints from stored results and exit ────────────────
if [[ "${1:-}" == "--recommend" ]]; then
  source "$SCRIPT_DIR/lib/eval-helpers.sh"
  echo ""
  echo -e "${BOLD}Tier recommendations (from stored eval results):${RESET}"
  eval_recommendation_hint
  echo ""
  exit 0
fi

PASS=0; FAIL=0; SKIP=0
LIVE_MODE="${DOCKET_EVAL_LIVE:-0}"

echo ""
echo "========================================"
echo "  docket-cli Eval Harness"
[[ "$LIVE_MODE" == "1" ]] && echo "  Mode: LIVE (golden-task checks enabled)" \
                          || echo "  Mode: structural only  (set DOCKET_EVAL_LIVE=1 for live)"
echo "========================================"
echo ""

shopt -s nullglob
evals=("$SCRIPT_DIR"/*.eval.sh)
shopt -u nullglob

if [[ ${#evals[@]} -eq 0 ]]; then
  echo -e "${DIM}  No eval files found (*.eval.sh).${RESET}"
  echo ""
  echo "========================================"
  echo -e "  ${YELLOW}SKIPPED${RESET} — no evals to run"
  echo "========================================"
  echo ""
  exit 0
fi

for eval_file in "${evals[@]}"; do
  name="$(basename "$eval_file" .eval.sh)"
  output=$(bash "$eval_file" 2>&1)
  rc=$?
  case $rc in
    0) echo -e "  ${GREEN}PASS${RESET}  $name"; PASS=$((PASS + 1)) ;;
    2) echo -e "  ${DIM}SKIP  $name${RESET}"; SKIP=$((SKIP + 1)) ;;
    *) echo -e "  ${RED}FAIL${RESET}  $name"
       [[ -n "$output" ]] && echo -e "${DIM}       ${output}${RESET}"
       FAIL=$((FAIL + 1)) ;;
  esac
done

echo ""
echo "========================================"
printf "  Pass: %d   Skip: %d   Fail: %d\n" "$PASS" "$SKIP" "$FAIL"
[[ "$LIVE_MODE" != "1" ]] && \
  echo -e "  ${DIM}Run with DOCKET_EVAL_LIVE=1 for live golden-task checks${RESET}"
echo "========================================"
echo ""

# If live results were recorded, show a tier hint inline.
if [[ "$LIVE_MODE" == "1" && -d "$SCRIPT_DIR/results" ]]; then
  source "$SCRIPT_DIR/lib/eval-helpers.sh"
  hints=$(eval_recommendation_hint 2>/dev/null || true)
  if [[ -n "$hints" ]]; then
    echo -e "${BOLD}Tier recommendations (from this run):${RESET}"
    echo "$hints"
    echo ""
  fi
fi

[[ $FAIL -eq 0 ]]
