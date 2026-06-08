#!/usr/bin/env bash
# Eval: programmer role
# Golden task: given a one-line bug description as a "compressed brief",
# the programmer agent's SOUL.md should reference brief-only reading
# and <5K token targets.
# Exit 0=PASS, 1=FAIL, 2=SKIP

WORKSPACE="$HOME/.openclaw/workspaces/programmer"
[[ ! -d "$WORKSPACE" ]] && exit 2   # SKIP — agent not installed

SOUL="$WORKSPACE/SOUL.md"
[[ ! -f "$SOUL" ]] && exit 2        # SKIP — SOUL.md missing

# Acceptance: programmer template mentions context efficiency
if grep -qi "brief\|<5K\|token\|compressed" "$SOUL" 2>/dev/null; then
  exit 0  # PASS
else
  echo "programmer SOUL.md missing brief/token-efficiency guidance" >&2
  exit 1  # FAIL
fi
