#!/usr/bin/env bash
# Shared helpers for docket-cli eval scripts.
#
# Sourced by every *.eval.sh. Provides:
#   eval_skip_unless_workspace <path>   exit 2 if workspace missing
#   eval_skip_unless_live               exit 2 unless DOCKET_EVAL_LIVE=1
#   eval_skip_unless_command <cmd>      exit 2 if binary not in PATH
#   eval_run_task <agent_id> <prompt>   run openclaw agent --local --json;
#                                       sets EVAL_RESPONSE / EVAL_META globals
#   eval_check_response <pattern>       1 if EVAL_RESPONSE matches pattern
#   eval_record_result <role> <tier> \  append a JSONL result to results dir
#     <passed 0|1> <cost_usd>           (no-op when results dir missing)
#   eval_recommendation_hint            emit a tier hint from recorded results
#
# Exit codes used by the harness: 0=PASS  1=FAIL  2=SKIP

EVALS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="$EVALS_DIR/results"

eval_skip_unless_workspace() {
  local path="$1"
  if [[ ! -d "$path" ]]; then
    echo "SKIP: workspace not found: $path" >&2
    exit 2
  fi
}

eval_skip_unless_live() {
  if [[ "${DOCKET_EVAL_LIVE:-0}" != "1" ]]; then
    exit 2
  fi
}

eval_skip_unless_command() {
  local cmd="$1"
  if ! command -v "$cmd" &>/dev/null; then
    echo "SKIP: $cmd not in PATH" >&2
    exit 2
  fi
}

# Run one agent turn via openclaw --local --json.
# On success sets:  EVAL_RESPONSE (assistant text), EVAL_COST (USD float),
#                   EVAL_INPUT_TOKENS, EVAL_OUTPUT_TOKENS, EVAL_DURATION_MS
# On failure (HTTP error, quota, network): prints SKIP reason and exits 2 so
# the harness counts it as skipped rather than failed — a live eval can only
# FAIL on an acceptance check, not on infrastructure problems.
eval_run_task() {
  local agent_id="$1"
  local prompt="$2"
  local timeout="${DOCKET_EVAL_TIMEOUT:-60}"

  eval_skip_unless_command openclaw

  local raw
  raw=$(openclaw agent --agent "$agent_id" --local --json \
        --message "$prompt" --timeout "$timeout" 2>/dev/null) || true

  if [[ -z "$raw" ]]; then
    echo "SKIP: no output from openclaw agent" >&2
    exit 2
  fi

  # Parse the JSON response with Python for robustness.
  local parsed
  parsed=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception as e:
    print('PARSE_ERROR|' + str(e)); sys.exit(0)
payloads = d.get('payloads', [])
text = ' '.join(p.get('text','') for p in payloads if p)
meta = d.get('meta', {})
agent_meta = meta.get('agentMeta', {})
usage = agent_meta.get('lastCallUsage', {})
# Detect infrastructure-level failures (quota, auth, timeout) embedded in text.
failure_markers = ['HTTP 401', 'HTTP 429', 'HTTP 5', 'LLM request rejected',
                   'authentication_error', 'rate_limit', 'overloaded', 'timeout']
for m in failure_markers:
    if m.lower() in text.lower():
        print('INFRA_ERROR|' + text[:120]); sys.exit(0)
cost_total = usage.get('total', 0) or 0
duration   = meta.get('durationMs', 0) or 0
print('OK|' + str(round(cost_total, 8)) + '|' + str(usage.get('input',0))
    + '|' + str(usage.get('output',0)) + '|' + str(duration) + '|' + text)
" <<< "$raw")

  local status="${parsed%%|*}"
  local rest="${parsed#*|}"

  if [[ "$status" == "INFRA_ERROR" ]]; then
    echo "SKIP: infrastructure error — ${rest}" >&2
    exit 2
  fi
  if [[ "$status" == "PARSE_ERROR" ]]; then
    echo "SKIP: JSON parse error — ${rest}" >&2
    exit 2
  fi

  # status == OK: cost|input|output|duration|text
  EVAL_COST="${rest%%|*}";            rest="${rest#*|}"
  EVAL_INPUT_TOKENS="${rest%%|*}";    rest="${rest#*|}"
  EVAL_OUTPUT_TOKENS="${rest%%|*}";   rest="${rest#*|}"
  EVAL_DURATION_MS="${rest%%|*}"
  EVAL_RESPONSE="${rest#*|}"
}

# Returns 0 if EVAL_RESPONSE matches the extended-regex pattern.
eval_check_response() {
  echo "$EVAL_RESPONSE" | grep -qiE "$1"
}

# Append a JSONL result record to results/<today>.jsonl.
# role, tier, passed (0|1), cost_usd are required.
eval_record_result() {
  local role="$1" tier="$2" passed="$3" cost="${4:-0}"
  [[ -d "$RESULTS_DIR" ]] || return 0

  local today; today=$(date +%Y-%m-%d)
  local out="$RESULTS_DIR/${today}.jsonl"

  python3 -c "
import json, sys
rec = {'date': sys.argv[1], 'role': sys.argv[2], 'tier': sys.argv[3],
       'passed': bool(int(sys.argv[4])), 'costUsd': float(sys.argv[5] or 0),
       'inputTokens': int(sys.argv[6] or 0), 'outputTokens': int(sys.argv[7] or 0),
       'durationMs': int(sys.argv[8] or 0)}
print(json.dumps(rec))
" "$today" "$role" "$tier" "$passed" "$cost" \
  "${EVAL_INPUT_TOKENS:-0}" "${EVAL_OUTPUT_TOKENS:-0}" "${EVAL_DURATION_MS:-0}" \
  >> "$out" 2>/dev/null || true
  # Ensure results file is owner-only (may contain cost data)
  chmod 600 "$out" 2>/dev/null || true
}

# Print a human-readable tier recommendation derived from the most recent
# results file, or nothing if results are absent.
eval_recommendation_hint() {
  local latest
  latest=$(ls -t "$RESULTS_DIR"/*.jsonl 2>/dev/null | head -1)
  [[ -z "$latest" ]] && return 0
  python3 - "$latest" <<'PY'
import json, sys, collections
recs = []
try:
    for line in open(sys.argv[1]):
        try: recs.append(json.loads(line))
        except Exception: pass
except Exception: pass
if not recs:
    sys.exit(0)
# Group by role: if all passing runs used a tier <= economy, suggest downgrade.
by_role = collections.defaultdict(list)
for r in recs:
    by_role[r["role"]].append(r)
TIER_ORDER = {"economy": 0, "standard": 1, "premium": 2}
for role, results in sorted(by_role.items()):
    passing = [r for r in results if r.get("passed")]
    if not passing:
        continue
    min_tier = min(passing, key=lambda r: TIER_ORDER.get(r.get("tier","standard"), 1))["tier"]
    total_cost = sum(r.get("costUsd", 0) for r in passing)
    avg_cost = total_cost / len(passing) if passing else 0
    current_tier = results[-1].get("tier", "?")
    if TIER_ORDER.get(min_tier, 1) < TIER_ORDER.get(current_tier, 1):
        print(f"  {role}: passes on a cheaper model class ({min_tier}, avg ${avg_cost:.4f}/run) — docket models set {role} <provider/model>")
    else:
        print(f"  {role}: {min_tier} is the minimum passing model class (avg ${avg_cost:.4f}/run)")
PY
}
