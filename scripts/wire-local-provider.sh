#!/usr/bin/env bash
# wire-local-provider.sh — register a local OpenAI-compatible model endpoint
# (llama.cpp / LM Studio / vLLM) with the OpenClaw daemon so docket can route
# agent roles to it (e.g. `docket models set programmer local/qwen3-30b-a3b`).
#
# Run this ONCE, AFTER your local inference server is up and answering on its
# /v1 endpoint. Idempotent — safe to re-run to update the model/context.
#
# Usage:
#   scripts/wire-local-provider.sh [--provider local] [--base-url URL]
#                                  [--model ID] [--name "Display"]
#                                  [--ctx 16384] [--max-tokens 8192]
#
# Defaults match the Qwen3-30B-A3B llama.cpp setup (server on :8080, -c 16384).
set -euo pipefail

PROVIDER="local"
BASE_URL="http://127.0.0.1:8080/v1"
MODEL_ID="qwen3-30b-a3b"
MODEL_NAME="Qwen3 30B-A3B (local)"
CTX=16384
MAX_TOKENS=8192

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider)   PROVIDER="$2"; shift 2 ;;
    --base-url)   BASE_URL="$2"; shift 2 ;;
    --model)      MODEL_ID="$2"; shift 2 ;;
    --name)       MODEL_NAME="$2"; shift 2 ;;
    --ctx)        CTX="$2"; shift 2 ;;
    --max-tokens) MAX_TOKENS="$2"; shift 2 ;;
    -h|--help)    sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v openclaw >/dev/null 2>&1 || { echo "openclaw CLI not found." >&2; exit 1; }

echo "▶ Checking the endpoint is alive: $BASE_URL/models"
if ! curl -fsS --max-time 5 "$BASE_URL/models" >/dev/null 2>&1; then
  echo "  ⚠ Could not reach $BASE_URL/models — make sure your llama.cpp/LM Studio"
  echo "    server is running first. Continuing to write config anyway."
fi

# Build the provider config JSON. apiKey is a literal dummy — llama.cpp ignores
# it, but OpenClaw requires the field present. Cost is zero (local/free).
PROVIDER_JSON=$(python3 - "$BASE_URL" "$MODEL_ID" "$MODEL_NAME" "$CTX" "$MAX_TOKENS" <<'PY'
import json, sys
base_url, model_id, name, ctx, max_tokens = sys.argv[1:6]
print(json.dumps({
    "baseUrl": base_url,
    "apiKey": "local",                 # llama.cpp ignores; OpenClaw needs it set
    "api": "openai-completions",
    "models": [{
        "id": model_id,
        "name": name,
        "reasoning": False,            # Instruct (non-thinking) — better for tool loops
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": int(ctx),     # MUST match the server's -c value
        "maxTokens": int(max_tokens),
    }],
}))
PY
)

echo "▶ Registering provider '$PROVIDER' with OpenClaw"
openclaw config set "models.providers.$PROVIDER" "$PROVIDER_JSON"

echo "▶ Verifying OpenClaw sees the local model"
openclaw models list --provider "$PROVIDER" 2>&1 || openclaw models list --local 2>&1 || true

cat <<EOF

✓ Local provider wired: $PROVIDER/$MODEL_ID  →  $BASE_URL

Next — apply the smart-planner / local-executor role split:

  docket models set manager    anthropic/claude-sonnet-4-6   # architecture & delegation (smart)
  docket models set reviewer   anthropic/claude-sonnet-4-6   # catches local mistakes (recommended)
  docket models set programmer $PROVIDER/$MODEL_ID            # implementation (local, free)
  docket models set tester     $PROVIDER/$MODEL_ID
  docket models set knowledge  $PROVIDER/$MODEL_ID
  docket models set repo       $PROVIDER/$MODEL_ID            # project agents execute locally
  docket models set task       $PROVIDER/$MODEL_ID
  docket models                                               # confirm the role→model table

Then smoke-test the split:

  docket team status
  docket team delegate "Write hello.py with a pytest test, then run it"
  docket team queue                                           # manager(Claude) plan → programmer(local)
  openclaw models status --agent programmer                  # confirm it resolves to $PROVIDER/$MODEL_ID
EOF
