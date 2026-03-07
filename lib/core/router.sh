#!/usr/bin/env bash
# Command router - dispatches commands to their handlers

route_command() {
  local cmd="${1:-list}"
  shift || true

  case "$cmd" in
    install|setup)     cmd_install "$@" ;;
    list)              cmd_list "$@" ;;
    add|create|new)    cmd_add "$@" ;;
    info|show)         cmd_info "$@" ;;
    delete|remove|rm)  cmd_delete "$@" ;;
    reset)             cmd_reset "$@" ;;
    repair|fix)        cmd_repair "$@" ;;
    wire)              cmd_wire "$@" ;;
    unwire)            cmd_unwire "$@" ;;
    logs|log)          cmd_logs "$@" ;;
    edit)              cmd_edit "$@" ;;
    model)             cmd_model "$@" ;;
    profile|tier)      cmd_profile "$@" ;;
    scope)             cmd_scope "$@" ;;
    workflow|wf)       cmd_workflow "$@" ;;
    keys|key|secret)   cmd_keys "$@" ;;
    cost|usage)        cmd_cost "$@" ;;
    billing|credits)   cmd_billing "$@" ;;
    doctor|check)      cmd_doctor "$@" ;;
    browser|brave)     cmd_browser "$@" ;;
    team)              cmd_team "$@" ;;
    memory|mem)        cmd_memory "$@" ;;
    monitor|mon)       cmd_monitor "$@" ;;
    smart|ai)          cmd_smart "$@" ;;
    help|--help|-h)    cmd_help "$@" ;;
    *)                 error_hint "Unknown command '$cmd'" "Run: rack help" ;;
  esac
}
