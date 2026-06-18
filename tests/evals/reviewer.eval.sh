#!/usr/bin/env bash
# Eval: reviewer role
# Structural (always):  SOUL.md references checklist and veto/security.
# Live (DOCKET_EVAL_LIVE=1): given a short diff with an obvious bug, the agent
#   identifies the problem and recommends REJECT or a specific fix.
# Exit 0=PASS  1=FAIL  2=SKIP

# shellcheck source=lib/eval-helpers.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/eval-helpers.sh"

WORKSPACE="$HOME/.openclaw/workspaces/reviewer"
SOUL="$WORKSPACE/SOUL.md"
TIER="${DOCKET_EVAL_TIER:-standard}"

eval_skip_unless_workspace "$WORKSPACE"
[[ ! -f "$SOUL" ]] && { echo "FAIL: SOUL.md missing" >&2; exit 1; }

# ── Structural check ─────────────────────────────────────────────────────────
if ! grep -qi "checklist\|veto\|security" "$SOUL" 2>/dev/null; then
  echo "FAIL: reviewer SOUL.md missing checklist/veto/security guidance" >&2
  exit 1
fi

eval_skip_unless_live

# ── Golden task ──────────────────────────────────────────────────────────────
# A one-liner diff with an intentional SQL-injection vulnerability.
GOLDEN_TASK='Review this diff and give a verdict (APPROVE or REJECT) with one sentence reason:
-  query = "SELECT * FROM users WHERE id = " + str(user_id)
+  query = f"SELECT * FROM users WHERE id = {user_id}"
Focus only on security.'

eval_run_task "reviewer" "$GOLDEN_TASK"

# Acceptance: must mention injection risk and recommend rejection.
if eval_check_response 'REJECT|injection|sql.inject|unsafe|vulnerab'; then
  eval_record_result "reviewer" "$TIER" 1 "$EVAL_COST"
  exit 0
fi
echo "FAIL: reviewer did not flag SQL injection or recommend REJECT" >&2
echo "Response (truncated): ${EVAL_RESPONSE:0:300}" >&2
eval_record_result "reviewer" "$TIER" 0 "$EVAL_COST"
exit 1
