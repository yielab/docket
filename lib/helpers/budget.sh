#!/usr/bin/env bash
# Budget enforcement helpers

# Check whether an agent has exceeded or approached its spending cap.
# Reads budgetUsd from .rack-meta.json; 0/unset = no cap.
# Returns: 0=ok, 1=warning (≥80%), 2=over budget (≥100%, agent flagged paused)
# Idempotent: won't re-flag an already-paused agent with a redundant warning.
check_budget() {
  local id="$1"
  local budget; budget=$(meta_get "$id" "budgetUsd" "")

  # No cap set — nothing to enforce
  [[ -z "$budget" || "$budget" == "0" ]] && return 0

  local cost_data; cost_data=$(_aggregate_cost "$id")
  local c_cost
  IFS='|' read -r _ _ _ _ c_cost _ <<< "$cost_data"

  local pct
  pct=$(python3 -c "print(int(float('$c_cost') / float('$budget') * 100))" 2>/dev/null || echo "0")

  if [[ "$pct" -ge 100 ]]; then
    local already_paused; already_paused=$(meta_get "$id" "paused" "")
    if [[ "$already_paused" != "true" ]]; then
      meta_set "$id" "paused" "true"
      meta_set "$id" "pausedReason" "budget"
      warn "Agent '$id' hit its \$${budget} budget cap (${pct}% used). Marked as paused."
      warn "  Resume: rack profile $id --budget <higher-amount>"
    else
      warn "Agent '$id' is over budget (${pct}% of \$${budget}) and already paused."
    fi
    return 2
  elif [[ "$pct" -ge 80 ]]; then
    warn "Agent '$id' is at ${pct}% of its \$${budget} budget (\$${c_cost} used)."
    return 1
  fi

  return 0
}

# Run check_budget for every project agent. Used by rack doctor.
# Returns the worst exit code seen (0=all ok, 1=warning, 2=over budget).
check_all_budgets() {
  local ids; ids=$(project_ids)
  [[ -z "$ids" ]] && return 0

  local worst=0
  while IFS= read -r id; do
    local rc=0
    check_budget "$id" || rc=$?
    [[ "$rc" -gt "$worst" ]] && worst=$rc
  done <<< "$ids"

  return "$worst"
}
