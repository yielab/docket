#!/usr/bin/env bash
# Eval: security role
# Golden check: security agent workspace exists and SOUL.md references
# threat modeling, audits, or penetration testing.
# Exit 0=PASS, 1=FAIL, 2=SKIP

WORKSPACE="$HOME/.openclaw/workspaces/security"
[[ ! -d "$WORKSPACE" ]] && exit 2

SOUL="$WORKSPACE/SOUL.md"
[[ ! -f "$SOUL" ]] && exit 2

if grep -qi "threat\|audit\|penetration\|security\|vulnerabilit\|compliance" "$SOUL" 2>/dev/null; then
  exit 0
else
  echo "security SOUL.md missing threat/audit guidance" >&2
  exit 1
fi
