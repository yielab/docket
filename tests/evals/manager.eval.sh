#!/usr/bin/env bash
# Eval: manager role
# Structural (always):  SOUL.md references orchestration/delegation.
# Live (DOCKET_EVAL_LIVE=1): given a vague task, the manager breaks it into
#   assignable sub-tasks with role assignments.
# Exit 0=PASS  1=FAIL  2=SKIP

# shellcheck source=lib/eval-helpers.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/eval-helpers.sh"

WORKSPACE="$HOME/.openclaw/workspaces/manager"
SOUL="$WORKSPACE/SOUL.md"
TIER="${DOCKET_EVAL_TIER:-standard}"

eval_skip_unless_workspace "$WORKSPACE"
[[ ! -f "$SOUL" ]] && { echo "FAIL: SOUL.md missing" >&2; exit 1; }

# ── Structural check ─────────────────────────────────────────────────────────
if ! grep -qi "delegat\|orchestrat\|classifier\|task" "$SOUL" 2>/dev/null; then
  echo "FAIL: manager SOUL.md missing delegation/orchestration guidance" >&2
  exit 1
fi

eval_skip_unless_live

# ── Golden task ──────────────────────────────────────────────────────────────
# A high-level task — manager should decompose it and assign roles.
GOLDEN_TASK='Break this into sub-tasks and assign each to one specialist role
(programmer / reviewer / tester / security / knowledge):
"Add user authentication to the REST API using JWT tokens."
Format: role: task description'

eval_run_task "manager" "$GOLDEN_TASK"

# Acceptance: at least two role assignments appear in the response.
role_count=$(echo "$EVAL_RESPONSE" | grep -ciE 'programmer|reviewer|tester|security|knowledge' || true)
if [[ "${role_count:-0}" -ge 2 ]]; then
  eval_record_result "manager" "$TIER" 1 "$EVAL_COST"
  exit 0
fi
echo "FAIL: manager did not assign tasks to at least 2 specialist roles" >&2
echo "Response (truncated): ${EVAL_RESPONSE:0:300}" >&2
eval_record_result "manager" "$TIER" 0 "$EVAL_COST"
exit 1
