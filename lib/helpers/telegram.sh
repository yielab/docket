#!/usr/bin/env bash
# telegram.sh — outbound Telegram send helper for HITL notifications.
#
# tg_send <agent_id> <text> — resolves the agent's Telegram binding, POSTs
# via the bot sendMessage API. Always redacts text before sending (GR8).
# If no bot token or binding is configured, degrades to CLI-only mode (warn,
# never hard-fail). This is notify-only; Telegram reply-routing (approve/deny
# via Telegram message) is PENDING daemon support.

tg_send() {
  local agent_id="$1" text="$2"
  [[ -z "$agent_id" || -z "$text" ]] && return 0

  # Redact before any transmission.
  local safe_text
  safe_text=$(redact "$text" 2>/dev/null || echo "$text")

  # Resolve Telegram binding (chat_id).
  local chat_id
  chat_id=$(get_tg_binding "$agent_id" 2>/dev/null || echo "")
  if [[ -z "$chat_id" ]]; then
    warn "tg_send: no Telegram binding for '$agent_id' — notification not sent."
    return 0
  fi

  # Resolve bot token from secrets or environment.
  local bot_token=""
  if declare -f secret_get >/dev/null 2>&1; then
    bot_token=$(secret_get "TELEGRAM_BOT_TOKEN" 2>/dev/null || echo "")
  fi
  [[ -z "$bot_token" ]] && bot_token="${TELEGRAM_BOT_TOKEN:-}"

  if [[ -z "$bot_token" ]]; then
    warn "tg_send: TELEGRAM_BOT_TOKEN not set — notification not sent."
    dim "  Message would be: $safe_text"
    return 0
  fi

  # Send via curl (best-effort; ignore errors so docket never hard-fails on Telegram).
  local api_url="https://api.telegram.org/bot${bot_token}/sendMessage"
  if command -v curl >/dev/null 2>&1; then
    curl -s -m 10 -X POST "$api_url" \
      -d "chat_id=${chat_id}" \
      --data-urlencode "text=${safe_text}" \
      -o /dev/null 2>/dev/null || true
  else
    warn "tg_send: curl not available — notification not sent."
  fi
}

# tg_send_approval <agent_id> <project> <role> <token> <action>
# Sends a formatted HITL approval request message.
tg_send_approval() {
  local agent_id="$1" project="$2" role="$3" token="$4" action="$5"
  local safe_action
  safe_action=$(redact "$action" 2>/dev/null || echo "$action")
  local msg
  msg="[docket APPROVAL NEEDED]
Project: $project  Role: $role
Action:  $safe_action
Token:   $token

To approve:  docket approve $token
To deny:     docket deny $token
(Expires in $(( APPROVAL_TIMEOUT / 60 )) min)"

  tg_send "$agent_id" "$msg"
}
