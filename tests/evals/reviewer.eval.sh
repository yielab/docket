#!/usr/bin/env bash
# Eval: reviewer role
# Golden check: reviewer SOUL.md must reference the mandatory checklist
# and veto power (core of the RACK reviewer contract).
# Exit 0=PASS, 1=FAIL, 2=SKIP

WORKSPACE="$HOME/.openclaw/workspaces/reviewer"
[[ ! -d "$WORKSPACE" ]] && exit 2

SOUL="$WORKSPACE/SOUL.md"
[[ ! -f "$SOUL" ]] && exit 2

if grep -qi "checklist\|veto\|security" "$SOUL" 2>/dev/null; then
  exit 0
else
  echo "reviewer SOUL.md missing checklist/veto guidance" >&2
  exit 1
fi
