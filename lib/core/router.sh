#!/usr/bin/env bash
# Command router - dispatches commands to their handlers

route_command() {
  local cmd="${1:-list}"
  shift || true

  case "$cmd" in
    # Core commands
    install|setup)     cmd_install "$@" ;;
    list)              cmd_list    "$@" ;;
    add|create|new)    cmd_add     "$@" ;;
    info|show)         cmd_info    "$@" ;;
    delete|remove|rm)  cmd_delete  "$@" ;;

    # Unified maintenance (replaces reset/repair/cleanup)
    maintain)          cmd_maintain "$@" ;;

    # Context & memory (replaces memory)
    context)           cmd_context "$@" ;;

    # Telegram
    wire)              cmd_wire   "$@" ;;
    unwire)            cmd_unwire "$@" ;;
    telegram)          cmd_wire   "$@" ;;

    # Configuration
    scope)             cmd_scope   "$@" ;;
    profile|tier)      cmd_profile "$@" ;;
    keys|key|secret)   cmd_keys    "$@" ;;

    # Team & Workflows
    team)              cmd_team     "$@" ;;
    workflow|wf)       cmd_workflow "$@" ;;

    # Utilities
    logs|log)          cmd_logs     "$@" ;;
    edit)              cmd_edit     "$@" ;;
    cost|usage)        cmd_cost     "$@" ;;
    doctor|check)      cmd_doctor   "$@" ;;
    gates|security)    cmd_gates    "$@" ;;
    audit)             cmd_audit    "$@" ;;
    eval|evals)        cmd_eval     "$@" ;;
    snapshot|export)   cmd_snapshot "$@" ;;
    serve)             cmd_serve    "$@" ;;
    models)            cmd_models   "$@" ;;
    completions|completion) cmd_completions "$@" ;;

    # Observability (Phase 8)
    trace)             cmd_trace    "$@" ;;
    metrics)           cmd_metrics  "$@" ;;
    policies|policy)   cmd_policies "$@" ;;
    approve)           cmd_approve  "$@" ;;
    deny)              cmd_deny     "$@" ;;

    help|--help|-h)    cmd_help     "$@" ;;

    # ── Removed / renamed commands ──────────────────────────────────────────
    reset)
      echo "docket reset was renamed → use: docket maintain [id] <clean|reset|rebuild>"
      exit 1
      ;;
    repair|fix)
      echo "docket repair was renamed → use: docket maintain [id] check"
      exit 1
      ;;
    cleanup|clean)
      echo "docket cleanup was renamed → use: docket maintain [id] sessions"
      exit 1
      ;;
    model)
      echo "docket model was renamed → use: docket profile [id] <provider/model|default>, or docket models for the role policy"
      exit 1
      ;;
    billing|credits)
      echo "docket billing was renamed → use: docket cost [id]"
      exit 1
      ;;
    monitor|mon)
      echo "docket monitor was renamed → use: docket cost [id]"
      exit 1
      ;;
    memory|mem)
      echo "docket memory was renamed → use: docket context [id] <search|snapshot|index|compress>"
      exit 1
      ;;
    smart|ai)
      echo "docket smart was removed — smart routing was placebo (prose in SOUL.md does not change the gateway model)"
      echo "Use: docket models (role policy) or docket profile [id] <provider/model> to set the actual model"
      exit 1
      ;;
    mode|terminal|term)
      echo "docket mode / docket terminal has been removed."
      echo "Use: docket models (role policy) or docket profile [id] <provider/model> to choose models."
      exit 1
      ;;
    browser|brave)
      if [[ "${DOCKET_EXPERIMENTAL:-0}" == "1" ]]; then
        cmd_browser "$@"
      else
        echo "docket browser is experimental"
        echo "  Enable: DOCKET_EXPERIMENTAL=1 docket browser <status|restart|kill|clean>"
        echo "  Or use: docket doctor  (browser health is section 8)"
        exit 1
      fi
      ;;

    # Unknown command
    *)
      echo "Unknown command '$cmd'"
      echo "Run: docket help"
      exit 1
      ;;
  esac
}
