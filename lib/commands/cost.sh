#!/usr/bin/env bash
# Command: cost

cmd_cost() {
  local id="${1:-}"
  local agents_dir="$OPENCLAW_DIR/agents"

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
      "AGENT" "MODEL" "INPUT" "OUTPUT" "COST (USD)" "PROFILE" "BUDGET"
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
      local profile; profile=$(model_to_profile "$model")
      local budget;  budget=$(meta_get "$pid" "budgetUsd" "")
      local cost_data
      cost_data=$(_aggregate_cost "$pid")
      IFS='|' read -r c_in c_out c_cr c_cw c_cost c_turns <<< "$cost_data"

      local model_short; model_short=$(echo "$model" | sed 's|anthropic/||')
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
    dim "  Pricing: haiku \$0.80/\$4 · sonnet \$3/\$15 · opus \$15/\$75 (per MTok in/out)"
  fi
  echo ""
}

