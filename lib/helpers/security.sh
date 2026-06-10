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

# Curated set of common, lower-risk binaries that should skip the approval
# prompt. Destructive/sensitive bins (rm, rmdir, dd, shred, docker, systemctl,
# shutdown, reboot, kill, mkfs, mount, sudo, curl, wget) and shells/interpreters
# acting as wrappers (bash/sh/zsh) are deliberately OMITTED so they fall through
# to the gate under security:allowlist + ask:on-miss.
_GATES_SAFE_BINS=(
  ls cat head tail wc sort uniq cut tr nl
  grep egrep rg fd find file stat tree realpath dirname basename
  sed awk jq yq diff comm
  git node npm npx pnpm yarn python3 pip pip3 go cargo rustc make cmake
  date env printf which xargs tee less
  mkdir touch cp mv ln
)

# Echo space-separated agent ids registered in openclaw.json (plus implicit main).
_all_agent_ids() {
  [[ -f "$CONFIG_FILE" ]] || { echo "main"; return 0; }
  python3 -c "import json,sys
try:
    c = json.load(open(sys.argv[1]))
    ids = [a.get('id','') for a in c.get('agents',{}).get('list',[]) if a.get('id')]
except Exception:
    ids = []
print(' '.join(ids))" "$CONFIG_FILE" 2>/dev/null || echo ""
}

# G3 — apply conservative exec-approval enforcement (opt-in).
#
# Writes defaults { security: allowlist, ask: on-miss, askFallback: deny } and
# seeds each agent the curated safe-bin allowlist (resolved to absolute paths),
# so dangerous/non-allowlisted commands prompt and, absent an approver, are
# denied (fail-closed). Existing config is PRESERVED (version/socket/agents) and
# defaults are only overwritten when empty — unless --force is given. The merged
# file is applied via the daemon's validated `openclaw approvals set` when
# available, else written directly to the local exec-approvals.json (0600).
#
# Echoes "<applied-via-daemon|applied-direct>|defaults_changed=N|seeded=...|bins=N".
apply_exec_approval_gates() {
  local force=0
  [[ "${1:-}" == "--force" ]] && force=1

  command -v python3 &>/dev/null || { fail "python3 is required to apply gates"; return 1; }

  # Resolve curated bins to absolute (symlink-resolved) paths.
  local paths="" n p
  for n in "${_GATES_SAFE_BINS[@]}"; do
    p=$(command -v "$n" 2>/dev/null) || continue
    p=$(realpath "$p" 2>/dev/null || echo "$p")
    paths+="$p"$'\n'
  done

  local appr_file="$OPENCLAW_DIR/exec-approvals.json"
  local agent_ids; agent_ids=$(_all_agent_ids)

  local _builder
  _builder=$(cat <<'PYEOF'
import json, os, sys, uuid
existing_path, out_path = sys.argv[1], sys.argv[2]
agent_ids = sys.argv[3:]
force = os.environ.get("RACK_GATES_FORCE") == "1"
paths = [p for p in os.environ.get("RACK_ALLOWLIST_PATHS", "").splitlines() if p.strip()]

try:
    with open(existing_path) as f:
        data = json.load(f)
except Exception:
    data = {}
if not isinstance(data, dict):
    data = {}
data.setdefault("version", 1)  # socket (if present) is preserved untouched

defaults = data.get("defaults") or {}
defaults_changed = 0
if not defaults or force:
    data["defaults"] = {"security": "allowlist", "ask": "on-miss",
                        "askFallback": "deny", "autoAllowSkills": False}
    defaults_changed = 1
else:
    data["defaults"] = defaults

def make_allowlist():
    return [{"id": str(uuid.uuid4()), "pattern": p} for p in paths]

agents = data.get("agents") or {}
ids = list(dict.fromkeys(list(agent_ids) + ["main"]))  # dedupe; ensure 'main'
seeded = []
for aid in ids:
    a = agents.get(aid) or {}
    if not a.get("allowlist") or force:
        a["security"] = a.get("security") or "allowlist"
        a["ask"] = a.get("ask") or "on-miss"
        a["askFallback"] = a.get("askFallback") or "deny"
        a["allowlist"] = make_allowlist()
        seeded.append(aid)
    agents[aid] = a
data["agents"] = agents

tmp = out_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, out_path)
print(f"defaults_changed={defaults_changed}")
print(f"seeded={','.join(seeded)}")
print(f"bins={len(paths)}")
PYEOF
)

  local tmp_out result
  tmp_out=$(mktemp)
  result=$(RACK_ALLOWLIST_PATHS="$paths" RACK_GATES_FORCE="$force" \
    python3 -c "$_builder" "$appr_file" "$tmp_out" $agent_ids 2>/dev/null) \
    || { rm -f "$tmp_out"; fail "Failed to build exec-approval config"; return 1; }
  # Flatten the three result lines into one pipe-delimited summary.
  result=$(printf '%s' "$result" | tr '\n' '|' | sed 's/|$//')

  if command -v openclaw &>/dev/null && openclaw approvals set "$tmp_out" &>/dev/null; then
    rm -f "$tmp_out"
    echo "applied-via-daemon|$result"
  else
    install -m 600 "$tmp_out" "$appr_file" 2>/dev/null || { cp "$tmp_out" "$appr_file"; chmod 600 "$appr_file"; }
    rm -f "$tmp_out"
    echo "applied-direct|$result"
  fi
}

# G3 — disable enforcement: reset exec-approval defaults to empty (unconfigured)
# so the daemon falls back to its tools.exec policy. Seeded allowlists are left
# in place (harmless, and useful if re-enabled). Reversible escape hatch.
disable_exec_approval_gates() {
  command -v python3 &>/dev/null || { fail "python3 is required"; return 1; }
  local appr_file="$OPENCLAW_DIR/exec-approvals.json"
  [[ -f "$appr_file" ]] || { warn "No exec-approvals file to disable"; return 0; }

  local tmp_out
  tmp_out=$(mktemp)
  python3 -c "import json,sys
data = json.load(open(sys.argv[1]))
data['defaults'] = {}
json.dump(data, open(sys.argv[2], 'w'), indent=2)
open(sys.argv[2], 'a').write('\n')" "$appr_file" "$tmp_out" 2>/dev/null \
    || { rm -f "$tmp_out"; fail "Failed to update exec-approvals"; return 1; }

  if command -v openclaw &>/dev/null && openclaw approvals set "$tmp_out" &>/dev/null; then
    rm -f "$tmp_out"
  else
    install -m 600 "$tmp_out" "$appr_file" 2>/dev/null || { cp "$tmp_out" "$appr_file"; chmod 600 "$appr_file"; }
    rm -f "$tmp_out"
  fi
}
