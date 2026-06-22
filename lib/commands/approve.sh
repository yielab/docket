#!/usr/bin/env bash
# Command: approve — grant a pending HITL approval by token.
#
# docket approve <token>

cmd_approve() {
  local token="${1:-}"
  if [[ -z "$token" ]]; then
    _approve_list
    return 0
  fi
  [[ "$token" == "-h" || "$token" == "--help" ]] && { _approve_help; return 0; }

  approval_grant "$token" || return 1
  success "Approval granted: $token"
  dim "  The waiting action may now proceed."
}

_approve_help() {
  header "docket approve"
  echo ""
  echo "  docket approve <token>    Grant a pending HITL approval"
  echo "  docket approve            List pending approvals"
  echo ""
  echo "  Approvals are stored at: $APPROVALS_DIR"
  echo ""
}

_approve_list() {
  header "Pending Approvals"
  echo ""
  [[ -d "$APPROVALS_DIR" ]] || { dim "  No approvals directory found."; echo ""; return 0; }

  local found=0
  for f in "$APPROVALS_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    python3 - "$f" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    if d.get("state") != "pending":
        sys.exit(0)
    tok     = d.get("token", "?")
    project = d.get("project", "?")
    role    = d.get("role", "?")
    action  = (d.get("action") or "")[:60]
    created = d.get("created", "?")[:19]
    print(f"  {tok}")
    print(f"    project={project}  role={role}  created={created}")
    print(f"    action: {action}")
    print()
except Exception:
    pass
PY
    found=$((found + 1))
  done

  [[ "$found" -eq 0 ]] && dim "  No pending approvals."
  echo ""
}
