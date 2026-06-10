#!/usr/bin/env bash
# Audit log for mutating operations (Phase 4 / observability).
#
# Appends a JSON line per change to $OPENCLAW_DIR/audit.log (0600) recording
# who/when/what — table stakes for "what changed this agent/binding/key, and when".
# Secret VALUES are never logged: callers pass only the key name / action target.
# Disable with RACK_NO_AUDIT=1.

# audit_log <action> [detail]
# action: dotted verb, e.g. keys.add, gates.enable, agent.delete
# detail: human-readable target (an id, key name, tier — never a secret value)
audit_log() {
  [[ "${RACK_NO_AUDIT:-0}" == "1" ]] && return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local action="$1" detail="${2:-}"
  local logf="${OPENCLAW_DIR:-$HOME/.openclaw}/audit.log"
  [[ -d "$(dirname "$logf")" ]] || return 0
  local ts user
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  user=$(id -un 2>/dev/null || echo "?")
  RACK_AUDIT_TS="$ts" RACK_AUDIT_USER="$user" \
    python3 - "$logf" "$action" "$detail" <<'PY' 2>/dev/null || true
import json, os, sys
logf, action, detail = sys.argv[1], sys.argv[2], sys.argv[3]
entry = {
    "ts": os.environ.get("RACK_AUDIT_TS", ""),
    "user": os.environ.get("RACK_AUDIT_USER", ""),
    "pid": os.getppid(),
    "action": action,
    "detail": detail,
}
new = not os.path.exists(logf)
with open(logf, "a") as f:
    f.write(json.dumps(entry) + "\n")
if new:
    os.chmod(logf, 0o600)
PY
}
