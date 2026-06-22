#!/usr/bin/env bash
# Command: deny — deny a pending HITL approval by token.
#
# docket deny <token>

cmd_deny() {
  local token="${1:-}"
  [[ -z "$token" || "$token" == "-h" || "$token" == "--help" ]] && {
    _deny_help; return 0
  }

  approval_deny "$token" || return 1
  success "Approval denied: $token"
  dim "  The waiting action has been blocked."
}

_deny_help() {
  header "docket deny"
  echo ""
  echo "  docket deny <token>    Deny a pending HITL approval"
  echo ""
  echo "  List pending: docket approve"
  echo ""
}
