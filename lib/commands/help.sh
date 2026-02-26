#!/usr/bin/env bash
# Command: help

cmd_help() {
  cat <<HELP

${BOLD}rack — OpenClaw project manager${RESET}

${BOLD}USAGE${RESET}
  rack [--debug] <command> [agent-id]

${BOLD}SETUP${RESET}
  ${GREEN}install${RESET}           Bootstrap OpenClaw with rack best practices
                      (Run this first on a clean system)

${BOLD}LIFECYCLE${RESET}
  ${GREEN}list${RESET}              List all project agents and their status
  ${GREEN}add${RESET}               Add a new project agent (interactive)
  ${GREEN}info${RESET}   [id]       Detailed status and info for a project
  ${GREEN}delete${RESET} [id]       Remove a project agent (with confirmation)
  ${GREEN}reset${RESET}  [id]       Clear memory / reset workspace (keeps identity)
  ${GREEN}repair${RESET} [id]       Fix permissions, re-register, fix routing

${BOLD}TELEGRAM${RESET}
  ${GREEN}wire${RESET}   [id]       Wire or update a Telegram group binding
  ${GREEN}unwire${RESET} [id]       Remove Telegram binding from a project

${BOLD}UTILITIES${RESET}
  ${GREEN}logs${RESET}     [id]       View memory logs and gateway entries for a project
  ${GREEN}edit${RESET}     [id]       Open workspace files in \$EDITOR
  ${GREEN}model${RESET}    [id] [m]   View or change the model for a project
  ${GREEN}profile${RESET}  [id] [t]   Set model tier: economy, standard, or premium
  ${GREEN}scope${RESET}    [id] [a]   Manage session scopes for multi-project isolation
  ${GREEN}workflow${RESET} [id] [a]   Manage Lobster workflows (deterministic pipelines)
  ${GREEN}keys${RESET}     <action>   Manage API keys (add/list/remove) - syncs to all agents
  ${GREEN}cost${RESET}     [id]       Token usage and cost breakdown (all or per-project)
  ${GREEN}doctor${RESET}              Check gateway, projects, and config for issues

${BOLD}PROFILES${RESET}
  ${GREEN}economy${RESET}   claude-haiku-4-5     \$0.80/\$4 per MTok   Routine tasks, triage
  ${GREEN}standard${RESET}  claude-sonnet-4-6    \$3/\$15 per MTok     Active dev, code review
  ${GREEN}premium${RESET}   claude-opus-4-6      \$15/\$75 per MTok    Architecture, security

  If [id] is omitted, an interactive picker is shown (fzf or numbered list).

${BOLD}FLAGS${RESET}
  --debug, -D       Verbose mode: show debug trace and extra log output
                    Or set in env: DEBUG=1 rack <command>

${BOLD}EXAMPLES${RESET}
  rack                        # show project list
  rack add                    # add a new project
  rack doctor                 # health check everything
  rack doctor --debug         # health check with verbose output
  rack info coreapp      # inspect one project
  rack repair sensorapp       # fix any issues
  rack wire corpbot       # attach a Telegram group
  rack reset sideproject       # clear memory logs
  rack delete marketing       # remove a project

${BOLD}DEBUG${RESET}
  rack --debug <command>      # trace execution + extra output
  DEBUG=1 rack repair foo     # same, via environment variable

${BOLD}PATHS${RESET}
  Workspaces:  ~/.openclaw/workspaces/projects/
  Config:      ~/.openclaw/openclaw.json
  Logs:        /tmp/openclaw/openclaw-YYYY-MM-DD.log

HELP
}

