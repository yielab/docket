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
    snapshot|export)   cmd_snapshot "$@" ;;
    serve)             cmd_serve    "$@" ;;
    help|--help|-h)    cmd_help     "$@" ;;

    # ── Removed / renamed commands ──────────────────────────────────────────
    reset)
      echo "rack reset was renamed → use: rack maintain [id] <clean|reset|rebuild>"
      exit 1
      ;;
    repair|fix)
      echo "rack repair was renamed → use: rack maintain [id] check"
      exit 1
      ;;
    cleanup|clean)
      echo "rack cleanup was renamed → use: rack maintain [id] sessions"
      exit 1
      ;;
    model)
      echo "rack model was renamed → use: rack profile [id] <economy|standard|premium>"
      exit 1
      ;;
    billing|credits)
      echo "rack billing was renamed → use: rack cost [id]"
      exit 1
      ;;
    monitor|mon)
      echo "rack monitor was renamed → use: rack cost [id]"
      exit 1
      ;;
    memory|mem)
      echo "rack memory was renamed → use: rack context [id] <search|snapshot|index|compress>"
      exit 1
      ;;
    smart|ai)
      echo "rack smart was removed — smart routing was placebo (prose in SOUL.md does not change the gateway model)"
      echo "Use: rack profile [id] <economy|standard|premium> to set the actual model"
      exit 1
      ;;
    mode|terminal|term)
      echo "rack mode / rack terminal has been removed."
      echo "Use: rack profile [id] <economy|standard|premium> to choose a model tier."
      exit 1
      ;;
    browser|brave)
      if [[ "${RACK_EXPERIMENTAL:-0}" == "1" ]]; then
        cmd_browser "$@"
      else
        echo "rack browser is experimental"
        echo "  Enable: RACK_EXPERIMENTAL=1 rack browser <status|restart|kill|clean>"
        echo "  Or use: rack doctor  (browser health is section 8)"
        exit 1
      fi
      ;;

    # Unknown command
    *)
      echo "Unknown command '$cmd'"
      echo "Run: rack help"
      exit 1
      ;;
  esac
}
