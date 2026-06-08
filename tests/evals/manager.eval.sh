#!/usr/bin/env bash
# Eval: manager role
# Golden check: manager workspace has TASK_LIST.json and SOUL.md references
# orchestration/delegation (the core of the manager contract).
# Exit 0=PASS, 1=FAIL, 2=SKIP

WORKSPACE="$HOME/.openclaw/workspaces/manager"
[[ ! -d "$WORKSPACE" ]] && exit 2

SOUL="$WORKSPACE/SOUL.md"
[[ ! -f "$SOUL" ]] && exit 2

# Must have TASK_LIST.json (created on first rack team delegate — skip if not yet initialized)
if [[ ! -f "$WORKSPACE/TASK_LIST.json" ]]; then
  exit 2  # SKIP — delegation not yet initialized
fi

# Must reference delegation/orchestration
if grep -qi "delegat\|orchestrat\|classifier\|task" "$SOUL" 2>/dev/null; then
  exit 0
else
  echo "manager SOUL.md missing delegation/orchestration guidance" >&2
  exit 1
fi
