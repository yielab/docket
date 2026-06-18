#!/usr/bin/env bash
# Eval: security role
# Structural (always):  SOUL.md references threat modeling or audit.
# Live (DOCKET_EVAL_LIVE=1): given a code snippet with a command-injection vuln,
#   the agent names the vulnerability class and suggests a fix.
# Exit 0=PASS  1=FAIL  2=SKIP

# shellcheck source=lib/eval-helpers.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/eval-helpers.sh"

WORKSPACE="$HOME/.openclaw/workspaces/security"
SOUL="$WORKSPACE/SOUL.md"
TIER="${DOCKET_EVAL_TIER:-premium}"

eval_skip_unless_workspace "$WORKSPACE"
[[ ! -f "$SOUL" ]] && { echo "FAIL: SOUL.md missing" >&2; exit 1; }

# ── Structural check ─────────────────────────────────────────────────────────
if ! grep -qi "threat\|audit\|penetration\|security\|vulnerabilit\|compliance" "$SOUL" 2>/dev/null; then
  echo "FAIL: security SOUL.md missing threat/audit/vulnerability guidance" >&2
  exit 1
fi

eval_skip_unless_live

# ── Golden task ──────────────────────────────────────────────────────────────
# Command-injection via unsanitized user input passed to os.system.
GOLDEN_TASK='Identify the vulnerability class and give a one-line fix for this Python:
import os
def ping(host):
    os.system("ping -c 1 " + host)  # host comes from user input'

eval_run_task "security" "$GOLDEN_TASK"

# Acceptance: names the vuln class and suggests subprocess or shlex or similar.
if eval_check_response 'command.inject|os\.system|subprocess|shlex|sanitize|validat|escape'; then
  eval_record_result "security" "$TIER" 1 "$EVAL_COST"
  exit 0
fi
echo "FAIL: security did not identify command injection or suggest a fix" >&2
echo "Response (truncated): ${EVAL_RESPONSE:0:300}" >&2
eval_record_result "security" "$TIER" 0 "$EVAL_COST"
exit 1
