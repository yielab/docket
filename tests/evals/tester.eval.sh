#!/usr/bin/env bash
# Eval: tester role
# Structural (always):  SOUL.md references behavior/PASS/FAIL validation.
# Live (RACK_EVAL_LIVE=1): given a function signature and description, the
#   agent writes a test case with at least one assertion.
# Exit 0=PASS  1=FAIL  2=SKIP

# shellcheck source=lib/eval-helpers.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/eval-helpers.sh"

WORKSPACE="$HOME/.openclaw/workspaces/tester"
SOUL="$WORKSPACE/SOUL.md"
TIER="${RACK_EVAL_TIER:-standard}"

eval_skip_unless_workspace "$WORKSPACE"
[[ ! -f "$SOUL" ]] && { echo "FAIL: SOUL.md missing" >&2; exit 1; }

# ── Structural check ─────────────────────────────────────────────────────────
if ! grep -qi "behavior\|PASS\|FAIL\|validation\|assert\|test" "$SOUL" 2>/dev/null; then
  echo "FAIL: tester SOUL.md missing behavior/validation guidance" >&2
  exit 1
fi

eval_skip_unless_live

# ── Golden task ──────────────────────────────────────────────────────────────
GOLDEN_TASK='Write a single pytest test for this function (code only, no explanation):
def add(a, b):
    """Return the sum of a and b."""
    return a + b'

eval_run_task "tester" "$GOLDEN_TASK"

# Acceptance: response contains an assert statement or pytest call.
if eval_check_response 'assert|assertEqual|pytest|def test_'; then
  eval_record_result "tester" "$TIER" 1 "$EVAL_COST"
  exit 0
fi
echo "FAIL: tester did not produce a test with an assertion" >&2
echo "Response (truncated): ${EVAL_RESPONSE:0:300}" >&2
eval_record_result "tester" "$TIER" 0 "$EVAL_COST"
exit 1
