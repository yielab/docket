#!/usr/bin/env bash
# Command: cost

# Machine-readable per-agent cost (rack cost --json), backed by the incremental
# cost index. Emits {agents:[{id,model,input,output,costUsd,turns,budgetUsd}],totalUsd}.
_cost_json() {
  local ids; ids=$(project_ids)
  {
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      local model budget cost_data c_in c_out c_cr c_cw c_cost c_turns
      model=$(meta_get "$pid" "model" "$DEFAULT_MODEL")
      budget=$(meta_get "$pid" "budgetUsd" "")
      cost_data=$(_aggregate_cost "$pid")
      IFS='|' read -r c_in c_out c_cr c_cw c_cost c_turns <<< "$cost_data"
      # pricing_known: 1 if model is in MODEL_PRICING, 0 otherwise
      local pricing_known=0
      [[ -n "${MODEL_PRICING[$model]:-}" ]] && pricing_known=1
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$pid" "$model" "$c_in" "$c_out" "$c_cost" "$c_turns" "$budget" "$pricing_known"
    done <<< "$ids"
  } | python3 -c '
import json, sys
agents, total = [], 0.0
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    parts = line.split("\t")
    pid, model, c_in, c_out, c_cost, c_turns, budget = parts[:7]
    pricing_known = (parts[7] == "1") if len(parts) > 7 else True
    cost = float(c_cost or 0)
    total += cost
    agents.append({
        "id": pid, "model": model,
        "input": int(c_in or 0), "output": int(c_out or 0),
        "costUsd": (round(cost, 6) if pricing_known else None),
        "pricingKnown": pricing_known,
        "turns": int(c_turns or 0),
        "budgetUsd": (float(budget) if budget and budget != "0" else None),
    })
print(json.dumps({"agents": agents, "totalUsd": round(total, 6)}, indent=2))
'
}

# Daily cost/turn/token history for one agent or all (rack cost --history [id]).
# --days N limits to the last N days; --json emits {scope,history:[...]}.
# Human view flags any day whose cost exceeds 2x its trailing 3-day average.
_cost_history_view() {
  local id="$1" days="$2" json="$3"
  local -a agents=()
  if [[ -n "$id" ]]; then
    [[ -d "$PROJECTS_DIR/$id" ]] || error "Project '$id' not found."
    agents=("$id")
  else
    local pid
    while IFS= read -r pid; do [[ -n "$pid" ]] && agents+=("$pid"); done <<< "$(project_ids)"
  fi

  local tmp; tmp=$(mktemp)
  local a
  for a in "${agents[@]}"; do _cost_history "$a"; done > "$tmp" 2>/dev/null

  [[ "$json" -ne 1 ]] && header "Cost history — ${id:-all agents}" && echo ""

  RACK_HIST_DAYS="$days" RACK_HIST_JSON="$json" RACK_HIST_LABEL="${id:-all agents}" \
    python3 - "$tmp" <<'PY'
import json, os, sys
days = int(os.environ.get("RACK_HIST_DAYS", "0") or 0)
as_json = os.environ.get("RACK_HIST_JSON") == "1"
label = os.environ.get("RACK_HIST_LABEL", "all agents")

agg = {}
for line in open(sys.argv[1]):
    line = line.rstrip("\n")
    if not line:
        continue
    try:
        day, turns, inp, out, cost = line.split("|")
    except ValueError:
        continue
    b = agg.setdefault(day, {"turns": 0, "input": 0, "output": 0, "cost": 0.0})
    b["turns"] += int(turns); b["input"] += int(inp); b["output"] += int(out); b["cost"] += float(cost)

ordered = sorted(agg.keys())
if days > 0:
    ordered = ordered[-days:]
rows = [{"date": d, "turns": agg[d]["turns"], "input": agg[d]["input"],
         "output": agg[d]["output"], "costUsd": round(agg[d]["cost"], 6)} for d in ordered]

if as_json:
    print(json.dumps({"scope": label, "history": rows}, indent=2))
    sys.exit(0)

if not rows:
    print("  (no dated session data yet)")
    sys.exit(0)

print(f"  {'DATE':<12} {'TURNS':>7} {'INPUT':>12} {'OUTPUT':>12} {'COST (USD)':>12}")
costs = [r["costUsd"] for r in rows]
for i, r in enumerate(rows):
    flag = ""
    if i >= 3:
        avg = sum(costs[i - 3:i]) / 3
        if avg > 0 and r["costUsd"] > 2 * avg:
            flag = "  <- spike (>2x trailing avg)"
    print(f"  {r['date']:<12} {r['turns']:>7} {r['input']:>12} {r['output']:>12} {r['costUsd']:>12.4f}{flag}")
print(f"  {'':<12} {'':>7} {'':>12} {'':>12} {sum(costs):>12.4f}  total")
PY
  rm -f "$tmp"
  [[ "$json" -ne 1 ]] && echo ""
}

cmd_cost() {
  local id="" json=0 history=0 days=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)    json=1; shift ;;
      --history) history=1; shift ;;
      --days)    days="${2:-0}"; shift 2 ;;
      --days=*)  days="${1#--days=}"; shift ;;
      -*)        shift ;;
      *)         [[ -z "$id" ]] && id="$1"; shift ;;
    esac
  done
  local agents_dir="$OPENCLAW_DIR/agents"

  if [[ "$history" -eq 1 ]]; then
    _cost_history_view "$id" "$days" "$json"
    return 0
  fi

  if [[ "$json" -eq 1 ]]; then
    _cost_json
    return 0
  fi

  # If an ID is given, show cost for that project only; otherwise show all
  if [[ -n "$id" ]]; then
    local workspace="$PROJECTS_DIR/$id"
    [[ ! -d "$workspace" ]] && error "Project '$id' not found."
    local name; name=$(meta_get "$id" "name" "$id")
    header "Token Usage: $name ($id)"
    echo ""
    _show_agent_cost "$id"
  else
    header "Token Usage — All Project Agents"
    echo ""
    printf "${BOLD}%-16s %-10s %10s %10s %12s  %-8s  %-12s${RESET}\n" \
      "AGENT" "MODEL" "INPUT" "OUTPUT" "COST (USD)" "SOURCE" "BUDGET"
    printf '%0.s─' {1..90}; echo ""

    local total_cost=0
    local ids; ids=$(project_ids)
    if [[ -z "$ids" ]]; then
      warn "No project agents found."
      return
    fi

    local runaway_agents=()
    while IFS= read -r pid; do
      local model; model=$(meta_get "$pid" "model" "$DEFAULT_MODEL")
      local profile; profile=$(agent_model_source "$pid")
      local budget;  budget=$(meta_get "$pid" "budgetUsd" "")
      local cost_data
      cost_data=$(_aggregate_cost "$pid")
      IFS='|' read -r c_in c_out c_cr c_cw c_cost c_turns <<< "$cost_data"

      local model_short="${model##*/}"
      local budget_col="—"
      if [[ -n "$budget" && "$budget" != "0" ]]; then
        local pct
        pct=$(python3 -c "print(int(float('$c_cost') / float('$budget') * 100))" 2>/dev/null || echo "0")
        budget_col="\$${budget} (${pct}%)"
      fi

      printf "%-16s %-10s %10s %10s %12s  %-8s  %-12s\n" \
        "$pid" "$model_short" \
        "$(numfmt --to=si "$c_in" 2>/dev/null || echo "$c_in")" \
        "$(numfmt --to=si "$c_out" 2>/dev/null || echo "$c_out")" \
        "\$$(printf '%.4f' "$c_cost")" \
        "$profile" \
        "$budget_col"

      total_cost=$(python3 -c "print($total_cost + $c_cost)")

      # Flag runaway agents for summary below
      local is_runaway=0
      [[ "$c_turns" -gt "${RUNAWAY_TURNS_THRESHOLD:-200}" ]] && is_runaway=1
      python3 -c "import sys; sys.exit(0 if float('$c_cost') >= ${RUNAWAY_COST_THRESHOLD:-20} else 1)" 2>/dev/null \
        && is_runaway=1
      [[ "$is_runaway" -eq 1 ]] && runaway_agents+=("$pid ($c_turns turns, \$$c_cost)")
    done <<< "$ids"

    echo ""
    printf "${BOLD}%69s %12s${RESET}\n" "Total:" "\$$(printf '%.4f' "$total_cost")"

    if [[ "${#runaway_agents[@]}" -gt 0 ]]; then
      echo ""
      for r in "${runaway_agents[@]}"; do
        warn "  Runaway session: $r"
      done
    fi

    echo ""
    dim "  Costs from session data in ~/.openclaw/agents/*/sessions/*.jsonl"
    dim "  Pricing per configured tier — see: rack models"
  fi
  echo ""
}

