#!/usr/bin/env bash
# Eval: knowledge role
# Golden check: knowledge agent workspace exists and SOUL.md references
# memory distillation or indexing.
# Exit 0=PASS, 1=FAIL, 2=SKIP

WORKSPACE="$HOME/.openclaw/workspaces/knowledge"
[[ ! -d "$WORKSPACE" ]] && exit 2

SOUL="$WORKSPACE/SOUL.md"
[[ ! -f "$SOUL" ]] && exit 2

if grep -qi "memory\|distill\|index\|pattern\|knowledge" "$SOUL" 2>/dev/null; then
  exit 0
else
  echo "knowledge SOUL.md missing memory/distillation guidance" >&2
  exit 1
fi
