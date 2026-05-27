#!/usr/bin/env bash
# Command router - dispatches commands to their handlers

route_command() {
  local cmd="${1:-list}"
  shift || true

  case "$cmd" in
    # Core commands
    install|setup)     cmd_install "$@" ;;
    list)              cmd_list "$@" ;;
    add|create|new)    cmd_add "$@" ;;
    info|show)         cmd_info "$@" ;;
    delete|remove|rm)  cmd_delete "$@" ;;

    # New unified commands
    maintain)          cmd_maintain "$@" ;;
    mode)              cmd_mode "$@" ;;
    context)           cmd_context "$@" ;;

    # Telegram
    wire)              cmd_wire "$@" ;;
    unwire)            cmd_unwire "$@" ;;
    telegram)          cmd_wire "$@" ;;  # Alias for wire

    # Configuration
    scope)             cmd_scope "$@" ;;
    profile|tier)      cmd_profile "$@" ;;
    keys|key|secret)   cmd_keys "$@" ;;

    # Team & Workflows
    team)              cmd_team "$@" ;;
    workflow|wf)       cmd_workflow "$@" ;;

    # Utilities
    logs|log)          cmd_logs "$@" ;;
    edit)              cmd_edit "$@" ;;
    cost|usage)        cmd_cost "$@" ;;
    doctor|check)      cmd_doctor "$@" ;;
    help|--help|-h)    cmd_help "$@" ;;

    # DEPRECATED commands (with warnings)
    reset)
      warn "⚠ 'rack reset' is deprecated. Use 'rack maintain [id] <clean|reset|rebuild>'"
      echo ""
      echo "  ${GREEN}rack maintain $1 clean${RESET}    Clear memory logs (was: reset 1)"
      echo "  ${GREEN}rack maintain $1 reset${RESET}    Clear memory + heartbeat (was: reset 2)"
      echo "  ${GREEN}rack maintain $1 rebuild${RESET}  Regenerate workspace (was: reset 3)"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_reset "$@"
      ;;
    repair|fix)
      warn "⚠ 'rack repair' is deprecated. Use 'rack maintain [id] check'"
      echo ""
      echo "  ${GREEN}rack maintain $1 check${RESET}    Health check & auto-fix"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_repair "$@"
      ;;
    cleanup|clean)
      warn "⚠ 'rack cleanup' is deprecated. Use 'rack maintain [id] sessions'"
      echo ""
      echo "  ${GREEN}rack maintain $1 sessions${RESET}    Clean large/old sessions"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_cleanup "$@"
      ;;
    model)
      warn "⚠ 'rack model' is deprecated. Use 'rack profile [id] [tier]'"
      echo ""
      echo "  ${GREEN}rack profile $1 economy${RESET}     Use haiku-4-5"
      echo "  ${GREEN}rack profile $1 standard${RESET}    Use sonnet-4-6"
      echo "  ${GREEN}rack profile $1 premium${RESET}     Use opus-4-6"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_model "$@"
      ;;
    billing|credits)
      warn "⚠ 'rack billing' is deprecated. Use 'rack cost [id]'"
      echo ""
      echo "  ${GREEN}rack cost${RESET}              Show usage for all agents"
      echo "  ${GREEN}rack cost $1${RESET}           Show usage for specific agent"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_billing "$@"
      ;;
    monitor|mon)
      warn "⚠ 'rack monitor' is deprecated. Use 'rack cost [id] <subcommand>'"
      echo ""
      echo "  ${GREEN}rack cost $1${RESET}           Show usage"
      echo "  ${GREEN}rack cost $1 log${RESET}       Show interaction log"
      echo "  ${GREEN}rack cost $1 watch${RESET}     Real-time dashboard"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_monitor "$@"
      ;;
    memory|mem)
      warn "⚠ 'rack memory' is deprecated. Use 'rack context [id] <subcommand>'"
      echo ""
      echo "  ${GREEN}rack context $1${RESET}           Show recent activity"
      echo "  ${GREEN}rack context $1 search <q>${RESET}  Search memory"
      echo "  ${GREEN}rack context $1 snapshot${RESET}    Create snapshot"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_memory "$@"
      ;;
    smart|ai)
      warn "⚠ 'rack smart' is deprecated. Use 'rack mode [id] smart'"
      echo ""
      echo "  ${GREEN}rack mode $1 smart${RESET}       Enable smart routing"
      echo "  ${GREEN}rack mode $1 standard${RESET}    Disable smart routing"
      echo "  ${GREEN}rack mode $1${RESET}             Show current mode"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_smart "$@"
      ;;
    terminal|term)
      warn "⚠ 'rack terminal' is deprecated. Use 'rack mode [id] terminal'"
      echo ""
      echo "  ${GREEN}rack mode $1 terminal${RESET}    Enable terminal mode (zero cost)"
      echo "  ${GREEN}rack mode $1 api${RESET}         Disable terminal mode"
      echo "  ${GREEN}rack mode $1${RESET}             Show current mode"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_terminal "$@"
      ;;
    browser|brave)
      warn "⚠ 'rack browser' is deprecated. Use 'rack doctor browser'"
      echo ""
      echo "  ${GREEN}rack doctor browser${RESET}        Browser diagnostics"
      echo "  ${GREEN}rack doctor browser --fix${RESET}  Auto-fix browser issues"
      echo ""
      read -rp "Continue with old command? [y/N]: " confirm
      [[ "$confirm" =~ ^[Yy]$ ]] && cmd_browser "$@"
      ;;

    # Unknown command
    *)
      error_hint "Unknown command '$cmd'" "Run: rack help"
      ;;
  esac
}
