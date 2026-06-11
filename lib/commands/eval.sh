#!/usr/bin/env bash
# Command: eval
# rack eval [--live] [--tier economy|standard|premium] [--role <role>] [--recommend]
#
# Runs the specialist-role eval harness under tests/evals/.
#   --live        enable live golden-task checks (sets RACK_EVAL_LIVE=1)
#   --tier <t>    record results under this tier label (default: standard)
#   --role <r>    run only <r>.eval.sh instead of all evals
#   --recommend   print tier recommendations from stored results; no evals run

cmd_eval() {
  local live=0 tier="standard" role="" recommend=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --live)        live=1; shift ;;
      --tier)        tier="${2:-standard}"; shift 2 ;;
      --tier=*)      tier="${1#--tier=}"; shift ;;
      --role)        role="${2:-}"; shift 2 ;;
      --role=*)      role="${1#--role=}"; shift ;;
      --recommend)   recommend=1; shift ;;
      -*)            warn "Unknown flag: $1"; shift ;;
      *)             shift ;;
    esac
  done

  local evals_dir; evals_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../tests/evals" && pwd 2>/dev/null)" \
    || { error "Cannot locate tests/evals/ relative to lib/commands/eval.sh"; }

  if [[ "$recommend" -eq 1 ]]; then
    header "Eval tier recommendations"
    echo ""
    bash "$evals_dir/run-evals.sh" --recommend
    return $?
  fi

  if [[ -n "$role" ]]; then
    local eval_file="$evals_dir/${role}.eval.sh"
    [[ -f "$eval_file" ]] || error "No eval found for role '$role'. Available: $(ls "$evals_dir"/*.eval.sh 2>/dev/null | xargs -n1 basename | sed 's/.eval.sh//' | tr '\n' ' ')"
    header "Eval: $role${live:+ (live)}"
    echo ""
    RACK_EVAL_LIVE="$live" RACK_EVAL_TIER="$tier" bash "$eval_file"
    local rc=$?
    echo ""
    case $rc in
      0) success "PASS — $role" ;;
      2) warn "SKIP — $role (agent not installed or live mode off)" ;;
      *) fail "FAIL — $role" ;;
    esac
    return $rc
  fi

  RACK_EVAL_LIVE="$live" RACK_EVAL_TIER="$tier" bash "$evals_dir/run-evals.sh"
}
