#!/usr/bin/env bash
# policy.sh — declarative guardrail policy engine.
#
# Policies live at $POLICIES_DIR/*.json. Each policy is:
#   { "id": str, "applies_to": ["role"|"*"], "hook": str,
#     "match": {"type":"regex","pattern":str}, "action": str, "message": str }
#
# Hooks:    pre_input | pre_tool_call | pre_output
# Actions:  allow | warn | redact | require_approval | block
#
# policy_eval <role> <hook> <text> → prints winning action (most restrictive wins).
# Emits guardrail_check into the trace for every evaluation; guardrail_block /
# approval_requested for non-allow outcomes.

# Load and validate policies from $POLICIES_DIR into the in-memory cache.
# Returns 0 always; malformed policies emit an error but do not abort.
_POLICY_CACHE_LOADED=0

# Policy validation script — assigned once at source time via cat <<'PY'.
_POLICY_VALIDATE_SCRIPT=$(cat <<'PY'
import json, sys
path = sys.argv[1]
REQUIRED = {"id", "applies_to", "hook", "match", "action"}
HOOKS    = {"pre_input", "pre_tool_call", "pre_output"}
ACTIONS  = {"allow", "warn", "redact", "require_approval", "block"}
try:
    p = json.load(open(path))
except Exception as e:
    print("Cannot parse {}: {}".format(path, e), file=sys.stderr); sys.exit(1)
missing = REQUIRED - set(p.keys())
if missing:
    print("{}: missing fields: {}".format(path, missing), file=sys.stderr); sys.exit(1)
if p["hook"] not in HOOKS:
    print("{}: unknown hook '{}' (valid: pre_input, pre_tool_call, pre_output)".format(path, p["hook"]), file=sys.stderr); sys.exit(1)
if p["action"] not in ACTIONS:
    print("{}: unknown action '{}'".format(path, p["action"]), file=sys.stderr); sys.exit(1)
match = p.get("match") or {}
if match.get("type") not in ("regex",):
    print("{}: match.type must be 'regex'".format(path), file=sys.stderr); sys.exit(1)
if not match.get("pattern"):
    print("{}: match.pattern is required".format(path), file=sys.stderr); sys.exit(1)
PY
)

_load_policies() {
  [[ "$_POLICY_CACHE_LOADED" -eq 1 ]] && return 0
  _POLICY_CACHE_LOADED=1
  [[ -d "$POLICIES_DIR" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local f msg
  for f in "$POLICIES_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    msg=$(python3 -c "$_POLICY_VALIDATE_SCRIPT" "$f" 2>&1) || {
      [[ -n "$msg" ]] && warn "policy: $msg"
    }
  done
}

# policy_eval <role> <hook> <text> [--trusted]
# Prints the winning action to stdout.
# --trusted: skip injection/untrusted-input policies (source=operator).
# Emits trace events as a side-effect.
policy_eval() {
  local role="$1" hook="$2" text="$3" trusted=0
  [[ "${4:-}" == "--trusted" ]] && trusted=1

  _load_policies

  [[ -d "$POLICIES_DIR" ]] || { echo "allow"; return 0; }
  command -v python3 >/dev/null 2>&1 || { echo "allow"; return 0; }

  local _eval_script
  _eval_script=$(cat <<'PY'
import json, os, re, glob
role      = os.environ["DOCKET_POLICY_ROLE"]
hook      = os.environ["DOCKET_POLICY_HOOK"]
text      = os.environ["DOCKET_POLICY_TEXT"]
trusted   = os.environ.get("DOCKET_POLICY_TRUSTED", "0") == "1"
pol_dir   = os.environ["DOCKET_POLICIES_DIR"]
RANK = {"block": 4, "require_approval": 3, "redact": 2, "warn": 1, "allow": 0}
best_action = "allow"
best_rank   = 0
INJECTION_IDS = {"prompt-injection"}
for path in sorted(glob.glob(os.path.join(pol_dir, "*.json"))):
    try:
        p = json.load(open(path))
    except Exception:
        continue
    if p.get("hook") != hook:
        continue
    applies = p.get("applies_to", [])
    if "*" not in applies and role not in applies:
        continue
    if trusted and p.get("id") in INJECTION_IDS:
        continue
    pattern = (p.get("match") or {}).get("pattern", "")
    if not pattern:
        continue
    try:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            action = p.get("action", "allow")
            rank   = RANK.get(action, 0)
            if rank > best_rank:
                best_rank   = rank
                best_action = action
    except Exception:
        continue
print(best_action)
PY
)

  local action
  action=$(DOCKET_POLICY_ROLE="$role" \
           DOCKET_POLICY_HOOK="$hook" \
           DOCKET_POLICY_TEXT="$text" \
           DOCKET_POLICY_TRUSTED="$trusted" \
           DOCKET_POLICIES_DIR="$POLICIES_DIR" \
             python3 -c "$_eval_script" 2>/dev/null)

  action="${action:-allow}"
  echo "$action"

  # Emit trace events as a side-effect (best-effort, no hard failure).
  local trace_project="${DOCKET_TRACE_PROJECT:-operator}"
  local trace_session="${DOCKET_TRACE_SESSION:-guardrail-$$}"
  trace_event "$trace_project" "$trace_session" "$role" "guardrail_check" \
    "{\"hook\":\"$hook\",\"action\":\"$action\",\"trusted\":$trusted}" 2>/dev/null || true

  if [[ "$action" != "allow" ]]; then
    local guard_type="guardrail_block"
    [[ "$action" == "require_approval" ]] && guard_type="approval_requested"
    [[ "$action" == "warn" || "$action" == "redact" ]] && guard_type="guardrail_check"
    if [[ "$action" == "block" || "$action" == "require_approval" ]]; then
      trace_event "$trace_project" "$trace_session" "$role" "$guard_type" \
        "{\"hook\":\"$hook\",\"action\":\"$action\"}" 2>/dev/null || true
    fi
  fi
}

# policy_test <hook> <role> <text> — dry-run the evaluator, print result without
# emitting traces. For docket policies test.
policy_test() {
  local hook="$1" role="$2" text="$3"
  DOCKET_NO_TRACE=1 policy_eval "$role" "$hook" "$text"
}
