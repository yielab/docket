#!/usr/bin/env bash
# Workspace creation and management helpers

_create_workspace() {
  local id="$1" type="$2" name="$3" codebase="$4" stack="$5" desc="$6" model="$7"
  local workspace="$PROJECTS_DIR/$id"
  local test_cmd; test_cmd=$(test_cmd_for_stack "$stack")
  local session_key; session_key=$(generate_session_key "$id" "default")

  mkdir -p "$workspace/memory"

  # SOUL.md
  if [[ "$type" == "repo" ]]; then
    cat > "$workspace/SOUL.md" <<SOUL
# SOUL.md — ${name}

## Identity
You are the autonomous agent for **${name}**. You know this project deeply. You do not discuss or act on other projects.

**Session Key:** \`${session_key}\`

This session key isolates you from other project contexts. You may only access resources and memory within this coordinate space.

## Description
${desc}

## Codebase
${codebase}

## Stack
${stack}

## Test Command
\`${test_cmd}\`

## Traits
- Read files before making any changes. Never assume structure.
- Delegate: implementation → programmer, review → reviewer, tests → tester.
- Completion signal: output \`<promise>DONE</promise>\` when a task is complete.
- Proactive: check HEARTBEAT.md every session.
- Scope: never act outside ${codebase}.
- Context isolation: respect the session key boundary — no cross-project access.

## Safety
- Never push to main/master without HITL approval.
- Never delete files without explicit instruction.
SOUL
  else
    cat > "$workspace/SOUL.md" <<SOUL
# SOUL.md — ${name}

## Identity
You are the autonomous agent for **${name}**. You handle tasks, research, and file operations for this context only.

**Session Key:** \`${session_key}\`

This session key isolates you from other project contexts. You may only access resources and memory within this coordinate space.

## Description
${desc}

## Work Directory
~/Sites/${id}/

## Traits
- Break requests into numbered steps and execute them.
- Log all completed tasks to memory/YYYY-MM-DD.md.
- Proactive: check HEARTBEAT.md every session.
- Scope: stay within this context. Do not reference other projects.
- Context isolation: respect the session key boundary — no cross-project access.

## Safety
- Never post publicly or send external messages without HITL approval.
- Ask before overwriting existing files.
SOUL
  fi

  # AGENTS.md
  if [[ "$type" == "repo" ]]; then
    cat > "$workspace/AGENTS.md" <<AGENTS
# AGENTS.md — ${name}

## Every Session
1. Read SOUL.md
2. Read HEARTBEAT.md — any pending tasks?
3. Read memory/YYYY-MM-DD.md (today + yesterday)
4. Read MEMORY.md if it exists

## Project Path
${codebase}

## Delegation
| Task              | Delegate to  |
|-------------------|--------------|
| Code              | programmer   |
| Review            | reviewer     |
| Tests             | tester       |
| Memory/patterns   | knowledge    |
| Risky actions     | security     |

## Scope Rule
Only act on ${name}. Redirect other project questions to the correct group.

## First Run
If MEMORY.md is missing, read the codebase and write it:
1. Check package.json / requirements.txt / composer.json
2. Read key entry points
3. Check git log --oneline -20
4. Write MEMORY.md: architecture, current state, key files, known issues
AGENTS
  else
    cat > "$workspace/AGENTS.md" <<AGENTS
# AGENTS.md — ${name}

## Every Session
1. Read SOUL.md
2. Read HEARTBEAT.md
3. Read memory/YYYY-MM-DD.md (today + yesterday)

## Work Directory
~/Sites/${id}/

## Task Protocol
1. Break request into numbered steps
2. Execute each step
3. Log results to memory/YYYY-MM-DD.md
4. Report blockers immediately

## Scope Rule
Only handle ${name} tasks.
AGENTS
  fi

  # TOOLS.md
  if [[ "$type" == "repo" ]]; then
    cat > "$workspace/TOOLS.md" <<TOOLS
# TOOLS.md — ${name}

## Project Path
${codebase}

## Stack
${stack}

## Commands
\`\`\`bash
${test_cmd}       # run tests
git log --oneline -10  # recent history
git diff HEAD          # review before commit
\`\`\`

## Environment Notes
_Add: DB name, ports, env vars, dev server command, seed scripts._
TOOLS
  else
    cat > "$workspace/TOOLS.md" <<TOOLS
# TOOLS.md — ${name}

## Work Directory
~/Sites/${id}/

## Notes
_Add: API keys needed, URLs to monitor, file locations, tools to use._
TOOLS
  fi

  # HEARTBEAT.md
  cat > "$workspace/HEARTBEAT.md" <<HEARTBEAT
# HEARTBEAT.md — ${name}

Check every session. Delete items when done.

## Active Tasks
_none yet_

## Pending Decisions
_none_

## Notes
_none_
HEARTBEAT

  # Fix permissions
  find "$workspace" -type d -exec chmod 700 {} \;
  find "$workspace" -type f -exec chmod 600 {} \;

  success "Workspace created: $workspace"
}

_wire_group() {
  local id="$1" group_id="$2"
  openclaw config set "channels.telegram.groups.${group_id}" '{"requireMention": false}' 2>&1 \
    || warn "Could not set allowlist entry — check manually"
  success "Group $group_id added to allowlist"
  upsert_binding "$id" "$group_id"
  success "Binding: $id ← telegram group $group_id"
}

_get_unbound_groups() {
  local -n _groups_ref=$1
  local -n _titles_ref=$2

  [[ ! -f "$LOG_FILE" ]] && return

  local groups
  groups=$(grep -o '"chatId":-[0-9]*' "$LOG_FILE" 2>/dev/null | sed 's/"chatId"://' | sort -u || true)
  [[ -z "$groups" ]] && return

  while IFS= read -r gid; do
    local title bound
    title=$(grep -o "\"chatId\":${gid},\"title\":\"[^\"]*\"" "$LOG_FILE" 2>/dev/null \
      | tail -1 | sed 's/.*"title":"//;s/".*//' || echo "unknown")
    bound=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
for b in c.get('bindings',[]):
    if b.get('match',{}).get('peer',{}).get('id') == '$gid':
        print(b['agentId']); exit()
print('')
" 2>/dev/null || echo "")

    # Only add unbound groups
    if [[ -z "$bound" ]]; then
      _groups_ref+=("$gid")
      _titles_ref+=("$title")
    fi
  done <<< "$groups"
}

# Get ALL groups from logs (both bound and unbound)
# Checks today's log and up to 7 days back
_get_all_groups() {
  local -n _groups_ref=$1
  local -n _titles_ref=$2
  local -n _bindings_ref=$3

  # Check multiple log files (today + past week)
  local log_pattern="${LOG_FILE%/*}/openclaw-*.log"
  local groups
  groups=$(grep -h '"chatId":-[0-9]*' $log_pattern 2>/dev/null | sed 's/.*"chatId"://' | sed 's/[^-0-9].*//' | sort -u || true)
  [[ -z "$groups" ]] && return

  while IFS= read -r gid; do
    local title bound
    # Check all log files for group title
    title=$(grep -h "\"chatId\":${gid},\"title\":\"[^\"]*\"" $log_pattern 2>/dev/null \
      | tail -1 | sed 's/.*"title":"//;s/".*//' || echo "unknown")
    bound=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
for b in c.get('bindings',[]):
    if b.get('match',{}).get('peer',{}).get('id') == '$gid':
        print(b['agentId']); exit()
print('')
" 2>/dev/null || echo "")

    # Add all groups with their binding status
    _groups_ref+=("$gid")
    _titles_ref+=("$title")
    _bindings_ref+=("$bound")  # Leave empty if unbound
  done <<< "$groups"
}

_show_unbound_groups() {
  [[ ! -f "$LOG_FILE" ]] && return
  local groups
  groups=$(grep -o '"chatId":-[0-9]*' "$LOG_FILE" 2>/dev/null | sed 's/"chatId"://' | sort -u || true)
  [[ -z "$groups" ]] && return
  echo -e "${CYAN}Groups seen today (from gateway logs):${RESET}"
  while IFS= read -r gid; do
    local title bound
    title=$(grep -o "\"chatId\":${gid},\"title\":\"[^\"]*\"" "$LOG_FILE" 2>/dev/null \
      | tail -1 | sed 's/.*"title":"//;s/".*//' || echo "unknown")
    bound=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
for b in c.get('bindings',[]):
    if b.get('match',{}).get('peer',{}).get('id') == '$gid':
        print(b['agentId']); exit()
print('')
" 2>/dev/null || echo "")
    if [[ -n "$bound" ]]; then
      printf "  ${DIM}%-20s %-30s → %s${RESET}\n" "$gid" "$title" "$bound"
    else
      printf "  ${GREEN}%-20s %-30s → unbound${RESET}\n" "$gid" "$title"
    fi
  done <<< "$groups"
  echo ""
}

_print_wire_instructions() {
  local id="$1"
  echo ""
  warn "No Telegram group wired. When ready:"
  echo ""
  echo "  rack wire $id"
  echo ""
  echo "  Or manually:"
  echo "  1. Create group in Telegram, add @claw_x9m_bot, send a message"
  echo "  2. openclaw config set 'channels.telegram.groups.<ID>' '{\"requireMention\": false}'"
  echo "  3. Add to bindings in ~/.openclaw/openclaw.json"
  echo "  4. systemctl --user restart openclaw-gateway.service"
}

_print_summary() {
  local id="$1" type="$2" codebase="$3" tg="$4"
  echo ""
  success "Project agent '$id' is ready"
  echo ""
  printf "  ${BOLD}%-14s${RESET} %s\n" "Agent ID:"    "$id"
  printf "  ${BOLD}%-14s${RESET} %s\n" "Type:"        "$type"
  [[ -n "$codebase" ]] && printf "  ${BOLD}%-14s${RESET} %s\n" "Codebase:"   "$codebase"
  [[ -n "$tg" ]] && printf "  ${BOLD}%-14s${RESET} %s\n" "Telegram:"   "group $tg → wired ✓"
  echo ""
  if [[ "$type" == "repo" && -n "$codebase" && -d "$codebase" ]]; then
    echo -e "${BOLD}First message to send in the Telegram group:${RESET}"
    echo ""
    echo "  Read the codebase at $codebase and update your SOUL.md"
    echo "  and MEMORY.md with: tech stack, entry points, architecture,"
    echo "  current state, and recent git activity."
  fi
  echo ""
}

_show_agent_cost() {
  local id="$1"
  local model; model=$(meta_get "$id" "model" "$DEFAULT_MODEL")
  local profile; profile=$(model_to_profile "$model")
  local cost_data
  cost_data=$(_aggregate_cost "$id")
  IFS='|' read -r c_in c_out c_cr c_cw c_cost c_turns <<< "$cost_data"

  printf "  ${BOLD}%-16s${RESET} %s\n" "Model:"      "$model"
  printf "  ${BOLD}%-16s${RESET} %s\n" "Profile:"     "$profile"
  printf "  ${BOLD}%-16s${RESET} %s\n" "Turns:"       "$c_turns"
  echo ""
  printf "  ${BOLD}%-16s${RESET} %'d tokens\n" "Input:"       "$c_in"
  printf "  ${BOLD}%-16s${RESET} %'d tokens\n" "Output:"      "$c_out"
  printf "  ${BOLD}%-16s${RESET} %'d tokens\n" "Cache read:"  "$c_cr"
  printf "  ${BOLD}%-16s${RESET} %'d tokens\n" "Cache write:" "$c_cw"
  echo ""
  printf "  ${BOLD}%-16s${RESET} ${GREEN}\$%.4f${RESET}\n" "Total cost:" "$c_cost"

  # Show savings estimate if not already on economy
  if [[ "$profile" != "economy" ]]; then
    local eco_model="${MODEL_PROFILES[economy]}"
    local eco_cost
    eco_cost=$(_estimate_cost "$c_in" "$c_out" "$c_cr" "$c_cw" "$eco_model")
    local savings
    savings=$(python3 -c "s=$c_cost - $eco_cost; print(f'{s:.4f}') if s > 0 else print('0.0000')")
    echo ""
    dim "  On economy ($eco_model): \$$eco_cost — saves \$$savings"
  fi
}

_aggregate_cost() {
  local id="$1"
  local sessions_dir="$OPENCLAW_DIR/agents/$id/sessions"

  python3 - "$sessions_dir" <<'PY' 2>/dev/null || echo "0|0|0|0|0.0|0"
import json, sys, os, glob

sessions_dir = sys.argv[1]
total = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0, "turns": 0}

if os.path.isdir(sessions_dir):
    for f in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
        with open(f) as fh:
            for line in fh:
                try:
                    data = json.loads(line)
                    msg = data.get("message", {})
                    usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
                    if usage:
                        total["input"] += usage.get("input", 0)
                        total["output"] += usage.get("output", 0)
                        total["cacheRead"] += usage.get("cacheRead", 0)
                        total["cacheWrite"] += usage.get("cacheWrite", 0)
                        cost = usage.get("cost", {})
                        total["cost"] += cost.get("total", 0) if isinstance(cost, dict) else 0
                        total["turns"] += 1
                except (json.JSONDecodeError, KeyError):
                    pass

print(f'{total["input"]}|{total["output"]}|{total["cacheRead"]}|{total["cacheWrite"]}|{total["cost"]:.6f}|{total["turns"]}')
PY
}

_estimate_cost() {
  local in_tok="$1" out_tok="$2" cache_r="$3" cache_w="$4" model="$5"
  local pricing="${MODEL_PRICING[$model]:-3.00:15.00:0.30:3.75}"
  IFS=':' read -r p_in p_out p_cr p_cw <<< "$pricing"
  python3 -c "
i, o, cr, cw = $in_tok, $out_tok, $cache_r, $cache_w
pi, po, pcr, pcw = $p_in, $p_out, $p_cr, $p_cw
cost = (i * pi + o * po + cr * pcr + cw * pcw) / 1_000_000
print(f'{cost:.4f}')
"
}

