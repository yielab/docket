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
    printf "${BOLD}%-16s %-10s %10s %10s %10s %10s %12s  %-8s${RESET}\n" \
      "AGENT" "MODEL" "INPUT" "OUTPUT" "CACHE-R" "CACHE-W" "COST (USD)" "PROFILE"
    printf '%0.s─' {1..100}; echo ""

    local total_cost=0
    local ids; ids=$(project_ids)
    if [[ -z "$ids" ]]; then
      warn "No project agents found."
      return
    fi

    while IFS= read -r pid; do
      local model; model=$(meta_get "$pid" "model" "$DEFAULT_MODEL")
      local profile; profile=$(model_to_profile "$model")
      local cost_data
      cost_data=$(_aggregate_cost "$pid")
      # cost_data format: "input_tokens|output_tokens|cache_read|cache_write|total_cost|turns"
      IFS='|' read -r c_in c_out c_cr c_cw c_cost c_turns <<< "$cost_data"

      local model_short; model_short=$(echo "$model" | sed 's|anthropic/||')
      printf "%-16s %-10s %10s %10s %10s %10s %12s  %-8s\n" \
        "$pid" "$model_short" \
        "$(numfmt --to=si "$c_in" 2>/dev/null || echo "$c_in")" \
        "$(numfmt --to=si "$c_out" 2>/dev/null || echo "$c_out")" \
        "$(numfmt --to=si "$c_cr" 2>/dev/null || echo "$c_cr")" \
        "$(numfmt --to=si "$c_cw" 2>/dev/null || echo "$c_cw")" \
        "\$$(printf '%.4f' "$c_cost")" \
        "$profile"

      total_cost=$(python3 -c "print($total_cost + $c_cost)")
    done <<< "$ids"

    echo ""
    printf "${BOLD}%79s %12s${RESET}\n" "Total:" "\$$(printf '%.4f' "$total_cost")"
    echo ""
    dim "  Costs from session data in ~/.openclaw/agents/*/sessions/*.jsonl"
    dim "  Pricing: haiku \$0.80/\$4 · sonnet \$3/\$15 · opus \$15/\$75 (per MTok in/out)"
  fi
  echo ""
}

