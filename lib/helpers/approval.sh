#!/usr/bin/env bash
# approval.sh — durable pending-approval store for HITL gating.
#
# approval_create <project> <role> <action> → prints approval_token
# Persists {token,project,role,action,state:pending,created} to
# $APPROVALS_DIR/<token>.json (atomic, 0600).

approval_create() {
  local project="$1" role="$2" action="$3"
  [[ -z "$project" || -z "$role" || -z "$action" ]] && {
    fail "approval_create: missing arguments"
    return 1
  }

  mkdir -p "$APPROVALS_DIR" || { fail "Cannot create approvals dir"; return 1; }
  chmod 700 "$APPROVALS_DIR" 2>/dev/null || true

  local token
  token=$(python3 -c "import uuid; print('apr-' + str(uuid.uuid4()))" 2>/dev/null) || {
    token="apr-$(date +%s)-$$"
  }

  local created
  created=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local aprf="$APPROVALS_DIR/$token.json"

  # Redact action before persisting (GR8).
  local redacted_action
  redacted_action=$(redact "$action" 2>/dev/null || echo "$action")

  DOCKET_APR_TOKEN="$token" \
  DOCKET_APR_PROJECT="$project" \
  DOCKET_APR_ROLE="$role" \
  DOCKET_APR_ACTION="$redacted_action" \
  DOCKET_APR_CREATED="$created" \
  DOCKET_APR_FILE="$aprf" \
    python3 - <<'PY' 2>/dev/null || { fail "Failed to persist approval record"; return 1; }
import json, os

data = {
    "token":   os.environ["DOCKET_APR_TOKEN"],
    "project": os.environ["DOCKET_APR_PROJECT"],
    "role":    os.environ["DOCKET_APR_ROLE"],
    "action":  os.environ["DOCKET_APR_ACTION"],
    "state":   "pending",
    "created": os.environ["DOCKET_APR_CREATED"],
}
path = os.environ["DOCKET_APR_FILE"]
tmp  = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY

  echo "$token"

  # Emit trace event (H1).
  trace_event "$project" "${project}-approval-$$" "$role" "approval_requested" \
    "{\"token\":\"$token\",\"action\":\"$(redact "$action" 2>/dev/null || echo "$action")\"}" \
    2>/dev/null || true
}

# approval_get <token> → prints JSON record or exits 1 if not found.
approval_get() {
  local token="$1"
  [[ -z "$token" ]] && { fail "approval_get: token required"; return 1; }
  local aprf="$APPROVALS_DIR/$token.json"
  [[ -f "$aprf" ]] || { fail "Approval not found: $token"; return 1; }
  cat "$aprf"
}

# _approval_set_state <token> <new_state>
_approval_set_state() {
  local token="$1" new_state="$2"
  local aprf="$APPROVALS_DIR/$token.json"
  [[ -f "$aprf" ]] || { fail "Approval not found: $token"; return 1; }

  python3 - "$aprf" "$new_state" <<'PY' 2>/dev/null || { fail "Failed to update approval"; return 1; }
import json, os, sys
path, new_state = sys.argv[1], sys.argv[2]
data = json.load(open(path))
data["state"] = new_state
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
}

# approval_grant <token> — transition pending → granted.
approval_grant() {
  local token="$1"
  [[ -z "$token" ]] && error "Usage: docket approve <token>"
  local aprf="$APPROVALS_DIR/$token.json"
  [[ -f "$aprf" ]] || error "Approval not found: $token"

  local state
  state=$(python3 -c "import json; print(json.load(open('$aprf')).get('state',''))" 2>/dev/null)
  [[ "$state" == "granted" ]] && { warn "Already granted: $token"; return 0; }
  [[ "$state" != "pending" ]] && error "Cannot grant approval in state '$state': $token"

  _approval_set_state "$token" "granted"

  # Emit trace event (H4).
  local project role
  project=$(python3 -c "import json; print(json.load(open('$aprf')).get('project',''))" 2>/dev/null)
  role=$(python3    -c "import json; print(json.load(open('$aprf')).get('role',''))"    2>/dev/null)
  trace_event "${project:-operator}" "${project:-operator}-approval" "${role:-operator}" \
    "approval_granted" "{\"token\":\"$token\"}" 2>/dev/null || true
}

# approval_deny <token> — transition pending → denied.
approval_deny() {
  local token="$1"
  [[ -z "$token" ]] && error "Usage: docket deny <token>"
  local aprf="$APPROVALS_DIR/$token.json"
  [[ -f "$aprf" ]] || error "Approval not found: $token"

  local state
  state=$(python3 -c "import json; print(json.load(open('$aprf')).get('state',''))" 2>/dev/null)
  [[ "$state" == "denied" || "$state" == "expired" ]] && { warn "Already $state: $token"; return 0; }
  [[ "$state" != "pending" ]] && error "Cannot deny approval in state '$state': $token"

  _approval_set_state "$token" "denied"

  local project role
  project=$(python3 -c "import json; print(json.load(open('$aprf')).get('project',''))" 2>/dev/null)
  role=$(python3    -c "import json; print(json.load(open('$aprf')).get('role',''))"    2>/dev/null)
  trace_event "${project:-operator}" "${project:-operator}-approval" "${role:-operator}" \
    "approval_denied" "{\"token\":\"$token\"}" 2>/dev/null || true
}

# approval_sweep_expired — called by serve loop. Expires pending approvals older
# than $APPROVAL_TIMEOUT seconds (treat as denied — fail-closed). (H5)
approval_sweep_expired() {
  [[ -d "$APPROVALS_DIR" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  DOCKET_APPROVALS_DIR="$APPROVALS_DIR" \
  DOCKET_APPROVAL_TIMEOUT="$APPROVAL_TIMEOUT" \
    python3 - <<'PY' 2>/dev/null || true
import json, os, glob, time, datetime

appr_dir = os.environ["DOCKET_APPROVALS_DIR"]
timeout  = int(os.environ.get("DOCKET_APPROVAL_TIMEOUT", "900"))
now = time.time()

for aprf in glob.glob(os.path.join(appr_dir, "*.json")):
    try:
        data = json.load(open(aprf))
    except Exception:
        continue
    if data.get("state") != "pending":
        continue
    created_str = data.get("created", "")
    if not created_str:
        continue
    try:
        dt = datetime.datetime.strptime(created_str[:19], "%Y-%m-%dT%H:%M:%S")
        created_epoch = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        continue
    if (now - created_epoch) > timeout:
        data["state"] = "expired"
        tmp = aprf + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, aprf)
PY
}
