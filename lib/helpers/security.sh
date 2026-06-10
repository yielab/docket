#!/usr/bin/env bash
# Security posture helpers.
#
# rack does not implement enforcement — the OpenClaw daemon provides exec
# approvals, tool policy, and a security audit natively (see
# internal-docs/SECURITY-GATES-FEASIBILITY.md). These helpers HARDEN the local
# state files (G2) and SURFACE the daemon's gate/audit status for `rack doctor`
# (G1). The daemon enforces; rack configures and reports.

# G2 — tighten permissions on sensitive OpenClaw state files.
# chmod 600 any of openclaw.json / secrets.json that is currently accessible by
# group or other (a writable config lets another local user change tool/auth
# policy). Only tightens — never loosens. Echoes one path per file it changed.
# Idempotent; safe to call repeatedly.
secure_config_perms() {
  local f mode
  for f in "$CONFIG_FILE" "$OPENCLAW_DIR/secrets.json"; do
    [[ -f "$f" ]] || continue
    mode=$(stat -c '%a' "$f" 2>/dev/null || stat -f '%Lp' "$f" 2>/dev/null || echo "")
    [[ -z "$mode" ]] && continue
    # Any group/other bit set => last two octal digits are not "00".
    if [[ "${mode: -2}" != "00" ]]; then
      chmod 600 "$f" && echo "$f"
    fi
  done
}

# G1 — report the daemon's exec-approval policy as one machine-parseable line:
#   "<STATE>|<policy summary>|<counts>"
# STATE: OK (deny/allowlist) · OPEN (full) · UNSET (no policy) · NA (unavailable).
_security_gate_report() {
  command -v openclaw &>/dev/null || { echo "NA|openclaw CLI not found|"; return 0; }
  local json
  json=$(openclaw approvals get --json 2>/dev/null || true)
  [[ -z "$json" ]] && { echo "NA|approvals snapshot unavailable|"; return 0; }

  local _script
  _script=$(cat <<'PYEOF'
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("NA|approvals snapshot unparseable|"); sys.exit(0)
f = d.get("file", {}) or {}
defaults = f.get("defaults", {}) or {}
agents = f.get("agents", {}) or {}
sec = defaults.get("security") or "unset"
ask = defaults.get("ask") or "unset"
fb  = defaults.get("askFallback") or "unset"
allow_total = 0
for a in agents.values():
    allow_total += len((a or {}).get("allowlist", []) or [])
state = "OK" if sec in ("deny", "allowlist") else ("OPEN" if sec == "full" else "UNSET")
print(f"{state}|security={sec} ask={ask} askFallback={fb}|agents={len(agents)} allowlisted={allow_total}")
PYEOF
)
  printf '%s' "$json" | python3 -c "$_script" 2>/dev/null || echo "NA|approvals parse failed|"
}

# G1 — summarize `openclaw security audit --json` for `rack doctor`.
# First line: "<crit>|<warn>|<info>". Then one "<title>|<remediation>" line per
# critical finding (max 5). The config-perms finding is excluded — rack owns and
# reports that one itself (see secure_config_perms / the doctor perms check), so
# excluding it here prevents double-counting. Empty output if audit unavailable.
_security_audit_report() {
  command -v openclaw &>/dev/null || return 0
  local json
  json=$(openclaw security audit --json 2>/dev/null || true)
  [[ -z "$json" ]] && return 0

  local _script
  _script=$(cat <<'PYEOF'
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
OWNED = {"fs.config.perms_writable"}  # rack reports/fixes this natively
ext = [f for f in (d.get("findings", []) or []) if f.get("checkId") not in OWNED]
crit = sum(1 for f in ext if f.get("severity") == "critical")
warn = sum(1 for f in ext if f.get("severity") == "warn")
info = sum(1 for f in ext if f.get("severity") == "info")
print(f"{crit}|{warn}|{info}")
shown = 0
for f in ext:
    if f.get("severity") == "critical" and shown < 5:
        print(f'{f.get("title","?")}|{f.get("remediation","")}')
        shown += 1
PYEOF
)
  printf '%s' "$json" | python3 -c "$_script" 2>/dev/null || true
}
