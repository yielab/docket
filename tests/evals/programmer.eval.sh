#!/usr/bin/env bash
# Eval: programmer role
# Structural (always):  SOUL.md references context-efficiency guidance.
# Live (RACK_EVAL_LIVE=1): given a minimal bug description the agent produces
#   a plausible code fix containing a corrected slice, assignment, or function.
# Exit 0=PASS  1=FAIL  2=SKIP

# shellcheck source=lib/eval-helpers.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/eval-helpers.sh"

WORKSPACE="$HOME/.openclaw/workspaces/programmer"
SOUL="$WORKSPACE/SOUL.md"
TIER="${RACK_EVAL_TIER:-standard}"

eval_skip_unless_workspace "$WORKSPACE"
[[ ! -f "$SOUL" ]] && { echo "FAIL: SOUL.md missing" >&2; exit 1; }

# ── Structural check ─────────────────────────────────────────────────────────
if ! grep -qi "brief\|<5K\|token\|compress\|context\|efficient" "$SOUL" 2>/dev/null; then
  echo "FAIL: programmer SOUL.md missing context-efficiency guidance" >&2
  exit 1
fi

eval_skip_unless_live

# ── Golden task ──────────────────────────────────────────────────────────────
# Minimal bug brief — programmer should output a corrected slice.
GOLDEN_TASK="Fix this Python bug, code only:
  # utils.py line 42
  items = data[0:len(data)-1]   # drops the last element — fix it"

eval_run_task "programmer" "$GOLDEN_TASK"

if eval_check_response 'data\[|len\(|:\]|-1\]|\bslice\b|items\s*='; then
  eval_record_result "programmer" "$TIER" 1 "$EVAL_COST"
  exit 0
fi
echo "FAIL: programmer did not produce a plausible slice fix" >&2
echo "Response (truncated): ${EVAL_RESPONSE:0:300}" >&2
eval_record_result "programmer" "$TIER" 0 "$EVAL_COST"
exit 1
