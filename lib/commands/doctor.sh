#!/usr/bin/env bash
# Command: doctor

# Single Python pass: read budgetUsd from each agent's .rack-meta.json and aggregate
# cost+turns from the cost index. Replaces 2N separate (meta_get + _aggregate_cost)
# spawns in the budget/runaway loops with one process over all agents.
# Output: COST\t<id>\t<budgetUsd>\t<cost_float>\t<turns_int>
_doctor_batch_cost() {
  python3 - "$PROJECTS_DIR" "$META_FILE" "$OPENCLAW_DIR" "$@" <<'PY'
import json, os, sys, glob
projects_dir, meta_file, openclaw_dir = sys.argv[1], sys.argv[2], sys.argv[3]
agent_ids = sys.argv[4:]
use_index = os.environ.get("RACK_NO_COST_INDEX") != "1"

def parse_file(path):
    t = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0, "turns": 0}
    try:
        with open(path) as fh:
            for line in fh:
                try: data = json.loads(line)
                except Exception: continue
                msg = data.get("message", {})
                usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
                if usage:
                    t["input"]      += usage.get("input", 0)
                    t["output"]     += usage.get("output", 0)
                    t["cacheRead"]  += usage.get("cacheRead", 0)
                    t["cacheWrite"] += usage.get("cacheWrite", 0)
                    c = usage.get("cost", {})
                    t["cost"] += c.get("total", 0) if isinstance(c, dict) else 0
                    t["turns"] += 1
    except Exception: pass
    return t

for aid in agent_ids:
    try:    budget = str(json.load(open(os.path.join(projects_dir, aid, meta_file))).get("budgetUsd", "") or "")
    except: budget = ""

    sessions_dir = os.path.join(openclaw_dir, "agents", aid, "sessions")
    index_path   = os.path.join(openclaw_dir, "agents", aid, ".cost-index.json")
    index = {}
    if use_index:
        try:
            with open(index_path) as fh: index = json.load(fh)
        except Exception: pass

    total_cost = 0.0; total_turns = 0; changed = False; seen = set()
    if os.path.isdir(sessions_dir):
        for f in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
            name = os.path.basename(f)
            seen.add(name)
            try: st = os.stat(f); sig = [int(st.st_mtime), st.st_size]
            except OSError: continue
            ent = index.get(name)
            if use_index and ent and ent.get("sig") == sig:
                t = ent["totals"]
            else:
                t = parse_file(f)
                index[name] = {"sig": sig, "totals": t}; changed = True
            total_cost  += t.get("cost",  0.0)
            total_turns += t.get("turns", 0)

    if use_index:
        for name in list(index.keys()):
            if name not in seen: del index[name]; changed = True
        if changed:
            try:
                tmp = index_path + ".tmp"
                with open(tmp, "w") as fh: json.dump(index, fh)
                os.chmod(tmp, 0o600)
                os.replace(tmp, index_path)
            except Exception: pass

    print(f"COST\t{aid}\t{budget}\t{total_cost:.6f}\t{total_turns}")
PY
}

_doctor_json() {
  # Collect binary/service facts in bash, pass everything to Python for assembly.
  local has_oc=0 oc_path="" has_py=0 py_path="" has_fzf=0 fzf_path=""
  command -v openclaw &>/dev/null && { has_oc=1; oc_path=$(command -v openclaw); }
  command -v python3  &>/dev/null && { has_py=1; py_path=$(command -v python3);  }
  command -v fzf      &>/dev/null && { has_fzf=1; fzf_path=$(command -v fzf);   }

  local gw_status; gw_status=$(service_ctl is-active 2>/dev/null) || true
  [[ -z "$gw_status" ]] && gw_status="unknown"

  local gate_line route_line iso_line cfg_mode key_report
  gate_line=$(_security_gate_report)
  route_line=$(_approval_routing_status)
  iso_line=$(_isolation_status)
  cfg_mode=$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || stat -f '%Lp' "$CONFIG_FILE" 2>/dev/null || echo "")
  key_report=$(_keys_age_report)

  # Cost data per agent: pid\tmodel\tbudget\tcost\tturns
  local cost_tmp; cost_tmp=$(mktemp)
  local ids; ids=$(project_ids)
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    local _model; _model=$(meta_get "$pid" "model" "$DEFAULT_MODEL")
    local _budget; _budget=$(meta_get "$pid" "budgetUsd" "")
    local _cdata; _cdata=$(_aggregate_cost "$pid")
    local _cost _turns
    IFS='|' read -r _ _ _ _ _cost _turns <<< "$_cdata"
    printf '%s\t%s\t%s\t%s\t%s\n' "$pid" "$_model" "$_budget" "$_cost" "$_turns" >> "$cost_tmp"
  done <<< "$ids"

  HAS_OC="$has_oc" OC_PATH="$oc_path" HAS_PY="$has_py" PY_PATH="$py_path" \
  HAS_FZF="$has_fzf" FZF_PATH="$fzf_path" GW_STATUS="$gw_status" \
  GATE_LINE="$gate_line" ROUTE_LINE="$route_line" ISO_LINE="$iso_line" \
  CFG_MODE="$cfg_mode" KEY_REPORT="$key_report" \
    python3 - "$CONFIG_FILE" "$PROJECTS_DIR" "$META_FILE" \
               "$OPENCLAW_DIR" "${TEMPLATE_VERSION:-1}" "$cost_tmp" \
               $ids <<'PY'
import json, sys, os

config_file  = sys.argv[1]
projects_dir = sys.argv[2]
meta_file    = sys.argv[3]
openclaw_dir = sys.argv[4]
tmpl_ver     = int(sys.argv[5] or 1)
cost_file    = sys.argv[6]
agent_ids    = sys.argv[7:]
e = os.environ.get

has_oc  = e("HAS_OC")  == "1"; oc_path  = e("OC_PATH",  "")
has_py  = e("HAS_PY")  == "1"; py_path  = e("PY_PATH",  "")
has_fzf = e("HAS_FZF") == "1"; fzf_path = e("FZF_PATH", "")
gw_status  = e("GW_STATUS",  "unknown")
gate_line  = e("GATE_LINE",  "")
route_line = e("ROUTE_LINE", "")
iso_line   = e("ISO_LINE",   "")
cfg_mode   = e("CFG_MODE",   "")
key_report = e("KEY_REPORT", "")

issues = 0
if not has_oc: issues += 1
if not has_py: issues += 1

cfg = {}; config_ok = False; config_data = {}
try:
    cfg = json.load(open(config_file))
    config_ok = True
    config_data = {"ok": True, "path": config_file,
                   "agents": len(cfg.get("agents", {}).get("list", [])),
                   "bindings": len(cfg.get("bindings", []))}
except Exception as ex:
    config_data = {"ok": False, "path": config_file, "error": str(ex)}
    issues += 1

gw_ok = gw_status == "active"
if not gw_ok: issues += 1

tg_enabled = bool(cfg.get("channels", {}).get("telegram", {}).get("enabled")) if config_ok else False

# per-agent: workspace files, registration, TG binding
agents_json = []
oc_agent_map = {a.get("id"): a for a in cfg.get("agents", {}).get("list", [])} if config_ok else {}
bindings     = cfg.get("bindings", []) if config_ok else []
def tg_peer(aid):
    for b in bindings:
        if b.get("agentId") == aid and b.get("match", {}).get("channel") == "telegram":
            return b.get("match", {}).get("peer", {}).get("id", "")
    return ""
for aid in agent_ids:
    a_issues = []
    for f in ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"):
        if not os.path.exists(os.path.join(projects_dir, aid, f)):
            a_issues.append(f"missing {f}")
    if not os.path.exists(os.path.join(projects_dir, aid, meta_file)):
        a_issues.append(f"no {meta_file}")
    if aid not in oc_agent_map:
        a_issues.append("not registered in openclaw")
    if a_issues: issues += 1
    agents_json.append({"id": aid, "ok": not a_issues, "tg": tg_peer(aid), "issues": a_issues})

# stale model aliases
STALE = {"anthropic/claude-haiku-3-5": "anthropic/claude-haiku-4-5",
         "anthropic/claude-haiku-3":   "anthropic/claude-haiku-4-5",
         "anthropic/claude-sonnet-3-5": "anthropic/claude-sonnet-4-6"}
invalid_models = []
for a in cfg.get("agents", {}).get("list", []) if config_ok else []:
    if a.get("model") in STALE:
        invalid_models.append({"id": a.get("id"), "model": a["model"], "suggest": STALE[a["model"]]})
        issues += 1

# drift
drift_results = []
for aid in agent_ids:
    mp = os.path.join(projects_dir, aid, meta_file)
    try:    meta_model = json.load(open(mp)).get("model", "")
    except: continue
    if not meta_model: continue
    oc_model = oc_agent_map.get(aid, {}).get("model", "")
    synced = not oc_model or meta_model == oc_model
    if not synced: issues += 1
    drift_results.append({"id": aid, "metaModel": meta_model, "ocModel": oc_model, "synced": synced})

# budget + runaway
budget_results = []; runaway_results = []
try:
    for line in open(cost_file):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 5: continue
        pid, model, budget, cost, turns = parts[:5]
        cost_f = float(cost or 0); budget_f = float(budget) if budget and budget != "0" else None
        turns_i = int(turns or 0)
        if budget_f:
            pct = int(cost_f / budget_f * 100)
            if pct >= 100: issues += 1
            budget_results.append({"id": pid, "costUsd": round(cost_f,6), "budgetUsd": budget_f, "pct": pct, "ok": pct < 100})
        else:
            budget_results.append({"id": pid, "costUsd": round(cost_f,6), "budgetUsd": None, "ok": True})
        runaway = turns_i > 200 or cost_f >= 20
        if runaway: issues += 1
        runaway_results.append({"id": pid, "turns": turns_i, "costUsd": round(cost_f,6), "ok": not runaway})
except Exception: pass

# key hygiene
keys_list = []
for line in key_report.splitlines():
    parts = line.split("|")
    if len(parts) >= 3:
        keys_list.append({"name": parts[1], "state": parts[0], "detail": parts[2]})

# provider key coverage
PKEY = {"anthropic":"ANTHROPIC_API_KEY","openai":"OPENAI_API_KEY",
        "google":"GOOGLE_AI_API_KEY","openrouter":"OPENROUTER_API_KEY",
        "groq":"GROQ_API_KEY","mistral":"MISTRAL_API_KEY",
        "xai":"XAI_API_KEY","cerebras":"CEREBRAS_API_KEY"}
secrets = {}
try: secrets = json.load(open(os.path.join(openclaw_dir, "secrets.json")))
except Exception: pass
missing_keys = []
for aid in agent_ids:
    try: model = json.load(open(os.path.join(projects_dir, aid, meta_file))).get("model","")
    except: continue
    prov = model.split("/")[0] if "/" in model else ""
    exp = PKEY.get(prov, "")
    if exp and exp not in secrets:
        missing_keys.append({"agent": aid, "model": model, "needsKey": exp})
        issues += 1

# security gates
gs_p = (gate_line + "||").split("|"); r_p = (route_line + "|").split("|")
perms_ok = not (cfg_mode and cfg_mode[-2:] != "00")
if not perms_ok: issues += 1
security = {"configPerms": cfg_mode or None, "permsOk": perms_ok,
            "gateState": gs_p[0], "policy": gs_p[1], "gateCounts": gs_p[2],
            "approvalRouting": r_p[0], "routingMode": r_p[1] if len(r_p)>1 else "",
            "isolation": iso_line}

# template drift
tmpl_results = []
for aid in agent_ids:
    try: tv = json.load(open(os.path.join(projects_dir, aid, meta_file))).get("templateVersion")
    except: tv = None
    tv_i = int(tv) if tv is not None else None
    tmpl_results.append({"id": aid, "agentVersion": tv_i, "currentVersion": tmpl_ver, "ok": tv_i == tmpl_ver})

print(json.dumps({
    "healthy": issues == 0,
    "issues":  issues,
    "checks": {
        "openclaw":      {"ok": has_oc,  "path": oc_path  or None},
        "python3":       {"ok": has_py,  "path": py_path  or None},
        "fzf":           {"available": has_fzf, "path": fzf_path or None},
        "config":        config_data,
        "gateway":       {"ok": gw_ok, "status": gw_status},
        "telegram":      {"enabled": tg_enabled},
        "agents":        agents_json,
        "modelConfig":   {"ok": not invalid_models, "invalid": invalid_models},
        "drift":         drift_results,
        "budget":        budget_results,
        "runaway":       runaway_results,
        "keyHygiene":    {"keys": keys_list, "missingForAgents": missing_keys},
        "securityGates": security,
        "templateDrift": tmpl_results,
    }
}, indent=2))
PY
  rm -f "$cost_tmp"
}

cmd_doctor() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      *)      shift ;;
    esac
  done

  if [[ "$json" -eq 1 ]]; then
    _doctor_json
    return
  fi

  header "Rack Doctor — System Health Check"
  echo ""
  local issues=0

  # 1. openclaw binary
  if command -v openclaw &>/dev/null; then
    success "openclaw: $(command -v openclaw)"
    dbg "openclaw version: $(openclaw --version 2>/dev/null || echo 'n/a')"
  else
    fail "openclaw not found in PATH"
    echo "  Install from: https://openclaw.dev"
    issues=$(( issues + 1 ))
  fi

  # 2. python3
  if command -v python3 &>/dev/null; then
    success "python3: $(command -v python3)"
  else
    fail "python3 not found — required for JSON operations"
    issues=$(( issues + 1 ))
  fi

  # 3. fzf (optional)
  if command -v fzf &>/dev/null; then
    success "fzf: $(command -v fzf)"
  else
    warn "fzf not installed — interactive pickers will use numbered fallback"
    echo "  Install with: brew install fzf"
  fi

  # 4. Config file
  if [[ ! -f "$CONFIG_FILE" ]]; then
    fail "Config missing: $CONFIG_FILE"
    echo "  Run: openclaw onboard"
    issues=$(( issues + 1 ))
  elif python3 -c "import json; json.load(open('$CONFIG_FILE'))" 2>/dev/null; then
    success "Config JSON valid: $CONFIG_FILE"
    dbg "Agents in config: $(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(len(c.get('agents',{}).get('list',[])))" 2>/dev/null)"
    dbg "Bindings in config: $(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(len(c.get('bindings',[])))" 2>/dev/null)"
  else
    fail "Config JSON is invalid: $CONFIG_FILE"
    echo "  Run: openclaw doctor"
    issues=$(( issues + 1 ))
  fi

  # 5. Gateway service
  local svc_status="unknown"
  svc_status=$(service_ctl is-active 2>/dev/null) || true
  [[ -z "$svc_status" ]] && svc_status="unknown"
  if [[ "$svc_status" == "active" ]]; then
    success "Gateway service: active"
    if [[ "$DEBUG" == "1" && "$(service_manager)" == "systemd" ]]; then
      service_ctl status 2>/dev/null | head -12 | sed 's/^/  /'
    fi
  else
    fail "Gateway service: $svc_status"
    echo "  Run: $(service_hint start)"
    issues=$(( issues + 1 ))
  fi

  # 6. Telegram channel
  if [[ -f "$CONFIG_FILE" ]]; then
    local tg_enabled
    tg_enabled=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print('yes' if c.get('channels',{}).get('telegram',{}).get('enabled') else 'no')
" 2>/dev/null || echo "unknown")
    if [[ "$tg_enabled" == "yes" ]]; then
      success "Telegram channel: enabled"
    else
      warn "Telegram channel: disabled or not configured"
      echo "  Run: openclaw onboard  (to configure Telegram)"
    fi
  fi

  # 7. Per-project checks
  local ids; ids=$(project_ids)
  if [[ -z "$ids" ]]; then
    echo ""
    warn "No project agents found — run: rack add"
  else
    echo ""
    echo -e "${BOLD}Project agents:${RESET}"
    while IFS= read -r id; do
      local proj_issues=()
      local tg; tg=$(get_tg_binding "$id")

      for f in SOUL.md AGENTS.md TOOLS.md HEARTBEAT.md; do
        [[ ! -f "$PROJECTS_DIR/$id/$f" ]] && proj_issues+=("missing $f")
      done
      [[ ! -f "$PROJECTS_DIR/$id/$META_FILE" ]] && proj_issues+=("no $META_FILE")

      if ! openclaw agents list 2>/dev/null | grep -q "^- ${id}$"; then
        proj_issues+=("not registered in openclaw")
      fi

      if [[ "${#proj_issues[@]}" -gt 0 ]]; then
        fail "  $id: ${proj_issues[*]}"
        echo "    Fix with: rack repair $id"
        issues=$(( issues + 1 ))
      elif [[ -z "$tg" ]]; then
        warn "  $id: OK, no Telegram binding  →  rack wire $id"
      else
        success "  $id: OK  →  group $tg"
      fi
    done <<< "$ids"
  fi

  # 8. Brave browser connection (for OpenClaw web UI)
  echo ""
  local brave_procs
  # `|| true` so a no-match grep (exit 1) doesn't trip `set -e`/pipefail and abort
  # doctor before the later checks run. wc still prints 0 on empty input.
  brave_procs=$( { ps aux | grep "openclaw/browser" | grep -v grep | wc -l; } 2>/dev/null || true )
  brave_procs=${brave_procs:-0}
  if [[ "$brave_procs" -gt 0 ]]; then
    # Check if processes are stale (older than 3 days)
    local oldest_brave
    oldest_brave=$(ps -eo pid,etimes,cmd | grep "openclaw/browser" | grep -v grep | awk '{print $2}' | sort -n | tail -1)
    local days_old=$(( oldest_brave / 86400 ))

    if [[ "$days_old" -gt 2 ]]; then
      warn "Brave browser: $brave_procs processes (oldest: ${days_old} days old)"
      echo "  ${DIM}Old browser processes can cause disconnections${RESET}"
      echo "  ${YELLOW}Fix: RACK_EXPERIMENTAL=1 rack browser restart${RESET}"
    else
      success "Brave browser: $brave_procs processes running"
    fi
  else
    dim "  Brave browser: not running (OpenClaw will auto-start when needed)"
  fi

  # 9. Today's log
  echo ""
  if [[ -f "$LOG_FILE" ]]; then
    local lines; lines=$(wc -l < "$LOG_FILE" | tr -d ' ')
    success "Today's log: $LOG_FILE ($lines lines)"

    # Check for disconnection patterns
    if grep -qi "disconnect\|timeout\|connection.*closed" "$LOG_FILE" 2>/dev/null; then
      local disconnect_count
      disconnect_count=$(grep -ci "disconnect\|timeout\|connection.*closed" "$LOG_FILE" 2>/dev/null)
      warn "  Found $disconnect_count disconnect/timeout events in log"
      echo "  ${DIM}If Brave disconnects frequently, run: ${RESET}${YELLOW}RACK_EXPERIMENTAL=1 rack browser restart${RESET}"
    fi

    if [[ "$DEBUG" == "1" && "$lines" -gt 0 ]]; then
      echo ""
      echo -e "${DIM}Last 5 log lines:${RESET}"
      tail -5 "$LOG_FILE" 2>/dev/null | sed 's/^/  /'
    fi
  else
    dim "  No log today: $LOG_FILE"
    dim "  (Normal if the gateway hasn't received messages yet)"
  fi

  # 10. Check for invalid model names
  echo ""
  echo -e "${BOLD}Model Configuration${RESET}"
  local invalid_models
  invalid_models=$(python3 << 'PYEOF'
import json, os
config_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(config_path, 'r') as f:
    config = json.load(f)

invalid = []
aliases = {
    'anthropic/claude-haiku-3-5': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-haiku-3': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-sonnet-3-5': 'anthropic/claude-sonnet-4-6',
}

# Check all agents
for agent in config.get('agents', {}).get('list', []):
    if 'model' in agent and agent['model'] in aliases:
        invalid.append(f"{agent.get('id')}: {agent['model']}")

for line in invalid:
    print(line)
PYEOF
)

  if [[ -z "$invalid_models" ]]; then
    success "  All agent models are valid"
  else
    fail "  Found invalid model configurations:"
    echo "$invalid_models" | sed 's/^/    /'
    echo "  ${YELLOW}Fix with: rack doctor --fix${RESET}"
    issues=$(( issues + 1 ))
  fi

  # 11. Config drift detection (meta vs openclaw.json)
  # Run as a single Python call over all project agents to avoid heredoc-in-loop warnings.
  local drift_ids; drift_ids=$(project_ids)
  if [[ -n "$drift_ids" ]]; then
    echo ""
    echo -e "${BOLD}Config drift check (meta ↔ openclaw.json):${RESET}"

    local _drift_script
    _drift_script=$(cat <<'PYEOF'
import json, sys, os

config_path  = sys.argv[1]
projects_dir = sys.argv[2]
meta_file    = sys.argv[3]
agent_ids    = sys.argv[4:]

config = json.load(open(config_path))
oc_agents = {a.get('id'): a for a in config.get('agents', {}).get('list', [])}

drift = []
ok    = []
for aid in agent_ids:
    meta_path = os.path.join(projects_dir, aid, meta_file)
    if not os.path.exists(meta_path):
        continue
    meta_model = json.load(open(meta_path)).get('model', '')
    if not meta_model:
        continue
    oc_model = oc_agents.get(aid, {}).get('model', '')
    if oc_model and meta_model != oc_model:
        drift.append(f"DRIFT {aid} meta={meta_model} openclaw={oc_model}")
    else:
        ok.append(f"OK {aid}")

for line in ok:
    print(line)
for line in drift:
    print(line)
PYEOF
)

    local _drift_results
    _drift_results=$(python3 -c "$_drift_script" \
      "$CONFIG_FILE" "$PROJECTS_DIR" "$META_FILE" $drift_ids 2>/dev/null || true)

    local drift_found=0
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      local _id="${line#* }"; _id="${_id%% *}"
      if [[ "$line" == DRIFT* ]]; then
        local _meta="${line##*meta=}"; _meta="${_meta%% *}"
        local _oc="${line##*openclaw=}"
        fail "  $_id: drift — model meta=${_meta} openclaw=${_oc}"
        issues=$(( issues + 1 ))
        drift_found=$(( drift_found + 1 ))
      else
        success "  $_id: in sync"
      fi
    done <<< "$_drift_results"

    if [[ "$drift_found" -gt 0 ]]; then
      echo "  Fix with: rack doctor --fix"
    fi
  fi

  # 12. Budget and runaway session check — one Python pass over all agents
  local budget_ids; budget_ids=$(project_ids)
  if [[ -n "$budget_ids" ]]; then
    # shellcheck disable=SC2086
    local _cost_batch; _cost_batch=$(_doctor_batch_cost $budget_ids)
    declare -A _dc_budget _dc_cost _dc_turns
    while IFS=$'\t' read -r rectype aid bgt cst trns; do
      [[ "$rectype" != "COST" ]] && continue
      _dc_budget[$aid]="$bgt"; _dc_cost[$aid]="$cst"; _dc_turns[$aid]="$trns"
    done <<< "$_cost_batch"

    echo ""
    echo -e "${BOLD}Budget check:${RESET}"
    while IFS= read -r bid; do
      local b_budget="${_dc_budget[$bid]:-}"
      if [[ -z "$b_budget" || "$b_budget" == "0" ]]; then
        dim "  $bid: no cap"
        continue
      fi
      local b_cost="${_dc_cost[$bid]:-0.0}"
      local b_pct
      b_pct=$(awk "BEGIN{printf \"%d\", ($b_cost/$b_budget)*100}" 2>/dev/null || echo "0")
      if [[ "$b_pct" -ge 100 ]]; then
        fail "  $bid: over budget — ${b_pct}% of \$$b_budget (\$$b_cost used)"
        issues=$(( issues + 1 ))
      elif [[ "$b_pct" -ge 80 ]]; then
        warn "  $bid: ${b_pct}% of \$$b_budget (\$$b_cost used)"
      else
        success "  $bid: \$$b_cost / \$$b_budget (${b_pct}%)"
      fi
    done <<< "$budget_ids"

    echo ""
    echo -e "${BOLD}Runaway session check:${RESET}"
    while IFS= read -r rid; do
      local r_cost="${_dc_cost[$rid]:-0.0}"
      local r_turns="${_dc_turns[$rid]:-0}"
      local r_flag=0
      [[ "$r_turns" -gt "${RUNAWAY_TURNS_THRESHOLD:-200}" ]] && r_flag=1
      awk "BEGIN{exit ($r_cost >= ${RUNAWAY_COST_THRESHOLD:-20}) ? 0 : 1}" && r_flag=1
      if [[ "$r_flag" -eq 1 ]]; then
        fail "  $rid: runaway — $r_turns turns, \$$r_cost"
        issues=$(( issues + 1 ))
      else
        success "  $rid: ok ($r_turns turns, \$$r_cost)"
      fi
    done <<< "$budget_ids"
  fi

  # 13. API key hygiene (backend + age since add/rotation)
  local key_report; key_report=$(_keys_age_report)
  if [[ -n "$key_report" ]]; then
    echo ""
    echo -e "${BOLD}API key hygiene:${RESET}"
    local sec_backend; sec_backend=$(secrets_backend)
    if [[ "$sec_backend" == "keyring" ]]; then
      success "  Backend: keyring (values in OS keyring, not plaintext at rest)"
    else
      warn "  Backend: file — secrets are plaintext at rest in $OPENCLAW_DIR/secrets.json"
      echo "    ${DIM}For at-rest protection: RACK_SECRETS_BACKEND=keyring (libsecret)${RESET}"
    fi
    local stale_keys=0
    while IFS='|' read -r k_state k_name k_detail; do
      [[ -z "$k_name" ]] && continue
      case "$k_state" in
        STALE)
          warn "  $k_name: $k_detail — consider: rack keys rotate $k_name"
          stale_keys=$(( stale_keys + 1 ))
          ;;
        UNKNOWN)
          dim "  $k_name: $k_detail"
          ;;
        *)
          success "  $k_name: $k_detail"
          ;;
      esac
    done <<< "$key_report"
    [[ "$stale_keys" -gt 0 ]] && echo "  ${DIM}Rotate keys older than ${RACK_KEY_MAX_AGE_DAYS:-90} days${RESET}"
  fi

  # 13b. Provider key coverage — warn if any agent's model provider has no key stored
  {
    local secrets_file; secrets_file="$OPENCLAW_DIR/secrets.json"
    local -a missing_key_agents=()
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      local agent_model; agent_model=$(meta_get "$pid" "model" "$DEFAULT_MODEL")
      local agent_provider="${agent_model%%/*}"
      # LOCAL_PROVIDERS need no key; skip
      local is_local=0
      for lp in "${LOCAL_PROVIDERS[@]:-}"; do [[ "$lp" == "$agent_provider" ]] && is_local=1 && break; done
      [[ "$is_local" -eq 1 ]] && continue
      # Derive expected key name from provider (uppercase + _API_KEY suffix)
      local expected_key
      case "$agent_provider" in
        anthropic)   expected_key="ANTHROPIC_API_KEY" ;;
        openai)      expected_key="OPENAI_API_KEY" ;;
        google)      expected_key="GOOGLE_AI_API_KEY" ;;
        openrouter)  expected_key="OPENROUTER_API_KEY" ;;
        groq)        expected_key="GROQ_API_KEY" ;;
        mistral)     expected_key="MISTRAL_API_KEY" ;;
        xai)         expected_key="XAI_API_KEY" ;;
        cerebras)    expected_key="CEREBRAS_API_KEY" ;;
        *)           expected_key="" ;;  # unknown provider — skip
      esac
      [[ -z "$expected_key" ]] && continue
      local key_stored=0
      python3 -c "
import json, sys
try:
    s = json.load(open(sys.argv[1]))
    sys.exit(0 if sys.argv[2] in s else 1)
except Exception:
    sys.exit(1)
" "$secrets_file" "$expected_key" 2>/dev/null && key_stored=1
      if [[ "$key_stored" -eq 0 ]]; then
        missing_key_agents+=("$pid ($agent_model) — needs $expected_key")
        issues=$((issues + 1))
      fi
    done <<< "$(project_ids)"
    if [[ "${#missing_key_agents[@]}" -gt 0 ]]; then
      echo ""
      echo -e "${BOLD}Provider key coverage:${RESET}"
      for _entry in "${missing_key_agents[@]}"; do
        fail "  Missing key: $_entry"
        echo "    Add with: rack keys add ${_entry##*needs }"
      done
    fi
  }

  # 14. Security gates (config hardening + exec-approval policy + daemon audit)
  echo ""
  echo -e "${BOLD}Security gates:${RESET}"

  # Capture the daemon audit once; it owns issue-counting for its findings when
  # available, so the config-perms check below doesn't double-count.
  local audit_out; audit_out=$(_security_audit_report)
  local audit_available=0; [[ -n "$audit_out" ]] && audit_available=1

  # G2 — config-file hardening: openclaw.json must not be group/other-accessible.
  local cfg_mode
  cfg_mode=$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || stat -f '%Lp' "$CONFIG_FILE" 2>/dev/null || echo "")
  if [[ -n "$cfg_mode" && "${cfg_mode: -2}" != "00" ]]; then
    fail "  Config group/other-accessible (mode $cfg_mode): $CONFIG_FILE"
    echo "    Another local user could change tool/auth policy. Fix: chmod 600 \"$CONFIG_FILE\""
    issues=$(( issues + 1 ))
  elif [[ -n "$cfg_mode" ]]; then
    success "  Config perms: $cfg_mode (owner-only)"
  fi

  # G1 — exec-approval policy (advisory: gates are spec'd as Planned, so an
  # inactive policy warns but does not fail the health check).
  local gate_line gs_state gs_policy gs_counts
  gate_line=$(_security_gate_report)
  IFS='|' read -r gs_state gs_policy gs_counts <<< "$gate_line"
  case "$gs_state" in
    OK)    success "  Exec approvals: $gs_policy ($gs_counts)" ;;
    OPEN)  warn "  Exec approvals: $gs_policy — host exec is ungated ($gs_counts)" ;;
    UNSET) warn "  Exec approvals: not configured — gates inactive"
           echo "    ${DIM}Enable via rack gates enable (spec: specs/functional/security-gates.spec.md)${RESET}" ;;
    *)     dim "  Exec approvals: ${gs_policy:-status unavailable}" ;;
  esac

  # G4 — approval routing (how prompts reach an approver)
  local route_line r_state r_mode
  route_line=$(_approval_routing_status)
  IFS='|' read -r r_state r_mode <<< "$route_line"
  case "$r_state" in
    on)  success "  Approval routing: on (mode=${r_mode:-?})" ;;
    off) [[ "$gs_state" == "OK" ]] && warn "  Approval routing: off — gated prompts won't reach chat" ;;
    *)   [[ "$gs_state" == "OK" ]] && dim "  Approval routing: not configured — rack gates enable" ;;
  esac

  # G5 — workspace isolation (Docker sandbox)
  local iso; iso=$(_isolation_status)
  case "$iso" in
    non-main|all) success "  Workspace isolation: $iso (Docker sandbox)" ;;
    *)            dim "  Workspace isolation: off — rack gates isolate on (needs Docker)" ;;
  esac

  # G1 — daemon security audit summary (config-perms finding excluded; rack owns it).
  if [[ "$audit_available" -eq 1 ]]; then
    local summary_line a_crit a_warn a_info
    summary_line=$(printf '%s\n' "$audit_out" | head -1)
    IFS='|' read -r a_crit a_warn a_info <<< "$summary_line"
    if [[ "${a_crit:-0}" -gt 0 ]]; then
      fail "  openclaw security audit: ${a_crit} critical, ${a_warn} warning(s)"
      issues=$(( issues + a_crit ))
      printf '%s\n' "$audit_out" | tail -n +2 | while IFS='|' read -r title remediation; do
        [[ -z "$title" ]] && continue
        echo "    ${RED}•${RESET} $title"
        [[ -n "$remediation" ]] && echo "      ${DIM}fix: $remediation${RESET}"
      done
      echo "    ${DIM}Remediate: openclaw security audit --fix${RESET}"
    elif [[ "${a_warn:-0}" -gt 0 ]]; then
      warn "  openclaw security audit: ${a_warn} warning(s), 0 critical"
      echo "    ${DIM}Details: openclaw security audit${RESET}"
    else
      success "  openclaw security audit: clean"
    fi
  fi

  # 15. Template/prompt version drift (advisory — agents still run on an old
  # template, but their SOUL/AGENTS/TOOLS prompts predate the current text).
  local tmpl_ids; tmpl_ids=$(project_ids)
  if [[ -n "$tmpl_ids" ]]; then
    echo ""
    echo -e "${BOLD}Template version (current: v${TEMPLATE_VERSION:-1}):${RESET}"
    local tmpl_drift=0
    while IFS= read -r tid; do
      [[ -z "$tid" ]] && continue
      local tv; tv=$(meta_get "$tid" "templateVersion" "")
      if [[ -z "$tv" ]]; then
        warn "  $tid: unstamped (pre-versioning) — rack maintain $tid rebuild"
        tmpl_drift=$(( tmpl_drift + 1 ))
      elif [[ "$tv" != "${TEMPLATE_VERSION:-1}" ]]; then
        warn "  $tid: on v$tv, current v${TEMPLATE_VERSION:-1} — rack maintain $tid rebuild"
        tmpl_drift=$(( tmpl_drift + 1 ))
      else
        success "  $tid: v$tv (current)"
      fi
    done <<< "$tmpl_ids"
    [[ "$tmpl_drift" -gt 0 ]] && \
      echo "  ${DIM}Rebuild regenerates prompts from metadata; edit metadata first if needed.${RESET}"
  fi

  # 15b. Agent metadata backfill — one taxonomy for specialists and project
  # agents. Specialists predating .rack-meta.json get one created; project
  # agents predating kind/modelSource get those inferred. Idempotent.
  echo ""
  echo -e "${BOLD}Agent metadata (taxonomy):${RESET}"
  {
    local backfilled=0 spec
    for spec in "${RACK_SPECIALISTS[@]}"; do
      local sdir="$OPENCLAW_DIR/workspaces/$spec"
      [[ -d "$sdir" ]] || continue
      [[ -f "$sdir/$META_FILE" ]] && continue
      local sm
      sm=$(python3 - "$CONFIG_FILE" "$spec" <<'PY' 2>/dev/null
import json, sys
c = json.load(open(sys.argv[1]))
for a in c.get('agents', {}).get('list', []):
    if a.get('id') == sys.argv[2]:
        print(a.get('model', '')); break
PY
)
      [[ -z "$sm" ]] && sm=$(resolve_role_model "$spec")
      meta_set "$spec" "kind"  "specialist"
      meta_set "$spec" "role"  "$spec"
      meta_set "$spec" "name"  "$spec"
      meta_set "$spec" "model" "$sm"
      meta_set "$spec" "modelSource" "$(agent_model_source "$spec")"
      success "  $spec: meta backfilled (kind=specialist, model=$sm)"
      backfilled=$(( backfilled + 1 ))
    done
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      local fixed=""
      if [[ -z "$(meta_get "$pid" "kind" "")" ]]; then
        meta_set "$pid" "kind" "project"
        fixed+="kind "
      fi
      if [[ -z "$(meta_get "$pid" "modelSource" "")" ]]; then
        meta_set "$pid" "modelSource" "$(agent_model_source "$pid")"
        fixed+="modelSource"
      fi
      if [[ -n "$fixed" ]]; then
        success "  $pid: backfilled ${fixed% }"
        backfilled=$(( backfilled + 1 ))
      fi
    done <<< "$(project_ids)"
    [[ "$backfilled" -eq 0 ]] && success "  All agents have kind/role/modelSource metadata"
  }

  # 16. Eval results — tier recommendations from the last RACK_EVAL_LIVE=1 run.
  #   Only shown when results exist; purely advisory (no issue count bump).
  local eval_results_dir
  eval_results_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../tests/evals/results" && pwd 2>/dev/null)" || true
  if [[ -d "$eval_results_dir" ]]; then
    local latest_results; latest_results=$(ls -t "$eval_results_dir"/*.jsonl 2>/dev/null | head -1)
    if [[ -n "$latest_results" ]]; then
      echo ""
      local results_date; results_date=$(basename "$latest_results" .jsonl)
      echo -e "${BOLD}Eval results (${results_date}):${RESET}"
      python3 - "$latest_results" <<'PY'
import json, sys, collections
recs = []
try:
    for line in open(sys.argv[1]):
        try: recs.append(json.loads(line))
        except Exception: pass
except Exception: pass
if not recs:
    print("  (no records in results file)")
    sys.exit(0)
TIER_ORDER = {"economy": 0, "standard": 1, "premium": 2}
by_role = collections.defaultdict(list)
for r in recs:
    by_role[r["role"]].append(r)
for role, results in sorted(by_role.items()):
    passing = [r for r in results if r.get("passed")]
    failing  = [r for r in results if not r.get("passed")]
    if not passing and not failing:
        continue
    if not passing:
        print(f"  {role}: all {len(failing)} run(s) FAILED")
        continue
    min_tier = min(passing, key=lambda r: TIER_ORDER.get(r.get("tier","standard"), 1))["tier"]
    avg_cost = sum(r.get("costUsd",0) for r in passing) / len(passing)
    current_tier = results[-1].get("tier","?")
    if TIER_ORDER.get(min_tier,1) < TIER_ORDER.get(current_tier,1):
        print(f"  \033[1;33m⚠\033[0m  {role}: passes on a cheaper model class ({min_tier}, avg ${avg_cost:.4f}/run) — rack models set {role} <provider/model>")
    else:
        print(f"  \033[0;32m✓\033[0m  {role}: {min_tier} minimum (avg ${avg_cost:.4f}/run, {len(passing)}/{len(results)} passed)")
PY
      dim "  Re-run: RACK_EVAL_LIVE=1 rack eval"
    fi
  fi

  # Summary
  echo ""
  if [[ "$issues" -eq 0 ]]; then
    success "All checks passed — rack is healthy."
  else
    echo -e "${RED}${BOLD}${issues} critical issue(s) found.${RESET}"
    echo "  Project issues:  rack repair [id]"
    echo "  Gateway issues:  openclaw doctor"
    echo "  Model issues:    rack doctor --fix"
    exit 1
  fi
}

