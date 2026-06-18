#!/usr/bin/env bash
# Command: help

cmd_help() {
  cat <<HELP

${BOLD}docket — OpenClaw project manager${RESET}

${BOLD}AGENT TYPES${RESET}
  ${CYAN}Specialist Agents${RESET}   Created by 'docket install' — shared team members
                        → programmer, reviewer, tester, knowledge, security, manager
                        → Work across ALL projects (don't create/delete manually)

  ${CYAN}Project Agents${RESET}      Created by 'docket add' — one per project/codebase
                        → Each has its own workspace, memory, and Telegram group

${BOLD}USAGE${RESET}
  docket [--debug] <command> [agent-id] [args]
  If agent-id is omitted an interactive picker is shown (fzf or numbered list).

${BOLD}SETUP${RESET}
  ${GREEN}install${RESET}            Bootstrap OpenClaw + create specialist agents

${BOLD}LIFECYCLE${RESET}
  ${GREEN}list${RESET}               List all project agents and their status
  ${GREEN}add${RESET}                Add a new project agent (interactive)
  ${GREEN}add${RESET} ${DIM}--from <f>${RESET}     Provision agent(s) from a YAML/JSON spec (declarative)
  ${GREEN}info${RESET}     [id]      Detailed status for a project
  ${GREEN}delete${RESET}   [id]      Remove a project agent
  ${GREEN}maintain${RESET} [id]      Health check & maintenance (see subcommands below)

${BOLD}MAINTENANCE  (docket maintain [id] <subcommand>)${RESET}
  ${GREEN}check${RESET}              Health check + auto-fix (default)
  ${GREEN}clean${RESET}              Clear memory logs only
  ${GREEN}reset${RESET}              Clear memory + heartbeat
  ${GREEN}rebuild${RESET}            Deep rebuild from .docket-meta.json
  ${GREEN}sessions${RESET}           Archive large/old sessions (>5 MB or >30 days)

${BOLD}TELEGRAM${RESET}
  ${GREEN}wire${RESET}   [id]        Wire or update a Telegram group binding
  ${GREEN}unwire${RESET} [id]        Remove Telegram binding from a project

${BOLD}CONFIGURATION${RESET}
  ${GREEN}profile${RESET}  [id] [m]  Pin an agent's model (<provider/model>) or 'default' to
                        follow the role policy; --budget <USD> sets a spending cap
  ${GREEN}models${RESET}             View/change the role→model policy; switch provider presets
  ${GREEN}scope${RESET}    [id] [a]  Manage session scopes for multi-project isolation
  ${GREEN}keys${RESET}     <action>  Manage API keys — syncs to all agents

${BOLD}CONTEXT & MEMORY  (docket context [id] <subcommand>)${RESET}
  ${GREEN}show${RESET}               Recent activity, active tasks, stats (default)
  ${GREEN}search${RESET}  <query>    Search indexed memory
  ${GREEN}snapshot${RESET}           Create SNAPSHOT.md for fast agent context
  ${GREEN}index${RESET}              Index memory files for search
  ${GREEN}compress${RESET}           Archive logs older than 30 days
  ${GREEN}project${RESET}            Quick-reference: codebase, stack, decisions

${BOLD}MONITORING${RESET}
  ${GREEN}cost${RESET}     [id]      Token usage and cost breakdown with budget status
  ${GREEN}doctor${RESET}             System health: gateway, config, drift, budget, runaway
  ${GREEN}gates${RESET}              Exec-approval gates: status / enable / disable (opt-in)
  ${GREEN}audit${RESET}    [N]       Recent mutating operations (keys, gates, profile, agents)
  ${GREEN}eval${RESET}               Specialist-role evals: structural checks + live golden tasks

${BOLD}TEAM & WORKFLOWS${RESET}
  ${GREEN}team status${RESET}        Specialist agent health and DOCKET status
  ${GREEN}team upgrade${RESET}       Upgrade specialists to current templates
  ${GREEN}team roles${RESET}         Show agent roles
  ${GREEN}team check${RESET}         Verify all specialists exist
  ${GREEN}team delegate${RESET}      Queue a task for the manager agent
  ${GREEN}team queue${RESET}         Show pending manager tasks
  ${GREEN}team done${RESET}          Mark a task as complete
  ${GREEN}workflow${RESET} [id]      Manage Lobster YAML pipelines

${BOLD}UTILITIES${RESET}
  ${GREEN}logs${RESET}      [id]     View memory logs and gateway entries
  ${GREEN}edit${RESET}      [id]     Open workspace files in \$EDITOR
  ${GREEN}snapshot${RESET}           JSON dump of all agents, bindings, costs (--output <file>)
  ${GREEN}serve${RESET}              Live JSON endpoint for dashboards (--port 7331 --interval 30)
  ${GREEN}completions${RESET}        Shell completion script — eval "\$(docket completions bash|zsh)"
  ${GREEN}help${RESET}               This help message

${BOLD}MODEL POLICY${RESET}  (default: Anthropic — change with 'docket models preset')
  Each agent role maps to the cheapest adequate model:
  ${GREEN}cheap${RESET}   ${ROLE_MODELS[tester]:-${MODEL_PROFILES[economy]}}   manager reviewer tester knowledge task
  ${GREEN}strong${RESET}  ${ROLE_MODELS[programmer]:-${MODEL_PROFILES[standard]}}  programmer security repo
  'docket models' shows the full role→model table with pricing; 'docket profile <id>'
  pins one agent to any model (incl. opus-class) without changing the policy.

${BOLD}FLAGS${RESET}
  --debug         Verbose mode — or set DEBUG=1 in env

${BOLD}EXAMPLES${RESET}
  docket                            # show project list
  docket add                        # add a new project (interactive)
  docket add --from agents.yaml     # provision a fleet from a spec file
  docket doctor                     # full health check
  docket info myproject             # inspect one project
  docket maintain myproject clean   # clear memory logs
  docket profile myproject default  # follow the role policy model
  docket profile myproject anthropic/claude-opus-4-6  # pin a stronger model
  docket profile myproject --budget 5  # set \$5 spending cap
  docket context myproject search "auth bug"  # search memory
  docket cost                       # cost breakdown for all agents
  docket team delegate "Fix login bug"  # queue task for manager
  docket team queue                 # show pending tasks

${BOLD}PATHS${RESET}
  Workspaces:  ~/.openclaw/workspaces/projects/
  Config:      ~/.openclaw/openclaw.json
  Logs:        /tmp/openclaw/openclaw-YYYY-MM-DD.log

HELP
}
