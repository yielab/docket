#!/usr/bin/env bash
# Eval: tester role
# Golden check: tester SOUL.md must reference behavior-only validation
# (the defining constraint — tester does NOT read code).
# Exit 0=PASS, 1=FAIL, 2=SKIP

WORKSPACE="$HOME/.openclaw/workspaces/tester"
[[ ! -d "$WORKSPACE" ]] && exit 2

SOUL="$WORKSPACE/SOUL.md"
[[ ! -f "$SOUL" ]] && exit 2

if grep -qi "behavior\|PASS\|FAIL\|validation" "$SOUL" 2>/dev/null; then
  exit 0
else
  echo "tester SOUL.md missing behavior/PASS-FAIL validation guidance" >&2
  exit 1
fi
