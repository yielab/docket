#!/usr/bin/env bash
# Command: help

cmd_help() {
  cat <<HELP

${BOLD}rack — OpenClaw project manager${RESET}

${BOLD}AGENT TYPES${RESET}
  ${CYAN}Specialist Agents${RESET}   Created by 'rack install' — shared team members
                        → programmer, reviewer, tester, knowledge, security, manager
                        → Work across ALL projects (don't create/delete manually)

  ${CYAN}Project Agents${RESET}      Created by 'rack add' — one per project/codebase
                        → Each has its own workspace, memory, and Telegram group

${BOLD}USAGE${RESET}
  rack [--debug] <command> [agent-id] [args]
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

${BOLD}MAINTENANCE  (rack maintain [id] <subcommand>)${RESET}
  ${GREEN}check${RESET}              Health check + auto-fix (default)
  ${GREEN}clean${RESET}              Clear memory logs only
  ${GREEN}reset${RESET}              Clear memory + heartbeat
  ${GREEN}rebuild${RESET}            Deep rebuild from .rack-meta.json
  ${GREEN}sessions${RESET}           Archive large/old sessions (>5 MB or >30 days)

${BOLD}TELEGRAM${RESET}
  ${GREEN}wire${RESET}   [id]        Wire or update a Telegram group binding
  ${GREEN}unwire${RESET} [id]        Remove Telegram binding from a project

${BOLD}CONFIGURATION${RESET}
  ${GREEN}profile${RESET}  [id] [t]  Set model tier: economy | standard | premium
                        rack profile [id] --budget <USD>  (set spending cap)
  ${GREEN}scope${RESET}    [id] [a]  Manage session scopes for multi-project isolation
  ${GREEN}keys${RESET}     <action>  Manage API keys — syncs to all agents

${BOLD}CONTEXT & MEMORY  (rack context [id] <subcommand>)${RESET}
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

${BOLD}TEAM & WORKFLOWS${RESET}
  ${GREEN}team status${RESET}        Specialist agent health and RACK status
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
  ${GREEN}help${RESET}               This help message

${BOLD}MODEL PROFILES${RESET}
  ${GREEN}economy${RESET}   claude-haiku-4-5     \$0.80/\$4 per MTok   Routine tasks, triage
  ${GREEN}standard${RESET}  claude-sonnet-4-6    \$3/\$15 per MTok     Active development
  ${GREEN}premium${RESET}   claude-opus-4-6      \$15/\$75 per MTok    Architecture, security

${BOLD}FLAGS${RESET}
  --debug         Verbose mode — or set DEBUG=1 in env

${BOLD}EXAMPLES${RESET}
  rack                            # show project list
  rack add                        # add a new project (interactive)
  rack add --from agents.yaml     # provision a fleet from a spec file
  rack doctor                     # full health check
  rack info myproject             # inspect one project
  rack maintain myproject clean   # clear memory logs
  rack profile myproject economy  # switch to haiku
  rack profile myproject --budget 5  # set \$5 spending cap
  rack context myproject search "auth bug"  # search memory
  rack cost                       # cost breakdown for all agents
  rack team delegate "Fix login bug"  # queue task for manager
  rack team queue                 # show pending tasks

${BOLD}PATHS${RESET}
  Workspaces:  ~/.openclaw/workspaces/projects/
  Config:      ~/.openclaw/openclaw.json
  Logs:        /tmp/openclaw/openclaw-YYYY-MM-DD.log

HELP
}
