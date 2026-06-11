#!/usr/bin/env bash
# Eval: knowledge role
# Structural (always):  SOUL.md references memory, distillation, or indexing.
# Live (RACK_EVAL_LIVE=1): given a short list of facts, the agent produces a
#   bullet-point summary — the core "distil to MEMORY.md" task.
# Exit 0=PASS  1=FAIL  2=SKIP

# shellcheck source=lib/eval-helpers.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/eval-helpers.sh"

WORKSPACE="$HOME/.openclaw/workspaces/knowledge"
SOUL="$WORKSPACE/SOUL.md"
TIER="${RACK_EVAL_TIER:-economy}"

eval_skip_unless_workspace "$WORKSPACE"
[[ ! -f "$SOUL" ]] && { echo "FAIL: SOUL.md missing" >&2; exit 1; }

# ── Structural check ─────────────────────────────────────────────────────────
if ! grep -qi "memory\|distill\|index\|pattern\|knowledge\|document" "$SOUL" 2>/dev/null; then
  echo "FAIL: knowledge SOUL.md missing memory/distillation guidance" >&2
  exit 1
fi

eval_skip_unless_live

# ── Golden task ──────────────────────────────────────────────────────────────
GOLDEN_TASK='Distil these facts into bullet points for MEMORY.md (bullets only):
- The API uses JWT tokens that expire after 1 hour.
- Rate limit is 100 req/min per user.
- The /health endpoint requires no auth.
- Deployed on Render; env vars in render.yaml.'

eval_run_task "knowledge" "$GOLDEN_TASK"

# Acceptance: response has at least two bullet markers and mentions key facts.
if eval_check_response '^\s*[-*•]|^-\s' && eval_check_response 'JWT|token|rate|health|render|deploy'; then
  eval_record_result "knowledge" "$TIER" 1 "$EVAL_COST"
  exit 0
fi
echo "FAIL: knowledge did not produce a bullet-point summary of key facts" >&2
echo "Response (truncated): ${EVAL_RESPONSE:0:300}" >&2
eval_record_result "knowledge" "$TIER" 0 "$EVAL_COST"
exit 1
