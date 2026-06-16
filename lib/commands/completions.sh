#!/usr/bin/env bash
# Command: completions — emit a shell completion script for rack.
#
#   rack completions bash   # source with: eval "$(rack completions bash)"
#   rack completions zsh    # source with: eval "$(rack completions zsh)"
#
# The scripts are emitted (not shipped as dotfiles) so they always match the
# installed version. Agent ids are completed live from the workspace dirs, so new
# `rack add` agents are available to tab-completion immediately. The command and
# subcommand tables here are drift-guarded by tests/unit/test-helpers.sh.

_rack_emit_bash() {
  cat <<'BASH_EOF'
# rack(1) bash completion — eval "$(rack completions bash)"
_rack_complete() {
  local cur prev cword
  cur="${COMP_WORDS[COMP_CWORD]}"
  cword=$COMP_CWORD

  local commands="install list add info delete maintain context wire unwire telegram scope profile keys team workflow logs edit cost doctor gates audit eval snapshot serve models completions help version"

  # Live agent ids (project + specialist) from the workspace tree, basenames only.
  local _oc="${OPENCLAW_DIR:-$HOME/.openclaw}"
  local _ids="" _d _b
  if [[ -d "$_oc/workspaces/projects" ]]; then
    for _d in "$_oc/workspaces/projects"/*/; do
      [[ -d "$_d" ]] || continue; _b="${_d%/}"; _ids+=" ${_b##*/}"
    done
  fi
  if [[ -d "$_oc/workspaces" ]]; then
    for _d in "$_oc/workspaces"/*/; do
      [[ -d "$_d" ]] || continue; _b="${_d%/}"; _b="${_b##*/}"
      [[ "$_b" == "projects" ]] && continue; _ids+=" $_b"
    done
  fi

  if [[ $cword -eq 1 ]]; then
    mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$cur")
    return
  fi

  local cmd="${COMP_WORDS[1]}"
  local words=""
  case "$cmd" in
    maintain)        [[ $cword -eq 2 ]] && words="$_ids" || words="check clean reset rebuild sessions" ;;
    scope)           [[ $cword -eq 2 ]] && words="$_ids" || words="show set reset" ;;
    context)         [[ $cword -eq 2 ]] && words="$_ids" || words="show search snapshot index compress" ;;
    workflow|wf)     [[ $cword -eq 2 ]] && words="$_ids" || words="list create show delete" ;;
    team)            words="status delegate queue done" ;;
    gates|security)  words="status enable disable isolate" ;;
    keys|key|secret) words="add list remove rotate setup validate export" ;;
    models)          words="set preset reset" ;;
    completions)     words="bash zsh" ;;
    cost|usage)      [[ $cword -eq 2 ]] && words="$_ids --history --json" || words="--history --json --days" ;;
    info|show|delete|remove|rm|profile|tier|wire|unwire|telegram|logs|log|edit|snapshot|export|audit)
                     [[ $cword -eq 2 ]] && words="$_ids" ;;
    *)               words="" ;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")
}
complete -F _rack_complete rack
BASH_EOF
}

_rack_emit_zsh() {
  cat <<'ZSH_EOF'
#compdef rack
# rack(1) zsh completion — eval "$(rack completions zsh)"
_rack() {
  local -a commands
  commands=(
    'install:Bootstrap OpenClaw + specialist agents'
    'list:List project agents'
    'add:Add a new project agent'
    'info:Detailed status of one project'
    'delete:Remove an agent (and optionally its workspace)'
    'maintain:Health/clean/reset/rebuild/sessions'
    'context:Show/search/snapshot/index/compress memory'
    'wire:Wire a Telegram group binding'
    'unwire:Remove a Telegram binding'
    'scope:Manage session scope keys'
    'profile:Pin/unpin an agent model'
    'keys:Manage API keys'
    'team:Coordinate specialist agents'
    'workflow:Lobster pipelines'
    'logs:View memory + gateway logs'
    'edit:Open workspace files in $EDITOR'
    'cost:Token usage and cost'
    'doctor:System health check'
    'gates:Security exec-approval gates'
    'audit:Audit log'
    'eval:Specialist-role evals'
    'snapshot:Export a workspace snapshot'
    'serve:Local HTTP view'
    'models:Role→model policy'
    'completions:Emit a shell completion script'
    'help:Show help'
  )

  _rack_ids() {
    local oc="${OPENCLAW_DIR:-$HOME/.openclaw}"
    local -a ids
    ids=(${oc}/workspaces/projects/*(/N:t) ${oc}/workspaces/*(/N:t))
    ids=(${ids:#projects})
    compadd -a ids
  }

  if (( CURRENT == 2 )); then
    _describe 'rack command' commands
    return
  fi

  case "${words[2]}" in
    maintain)        (( CURRENT == 3 )) && _rack_ids || compadd check clean reset rebuild sessions ;;
    scope)           (( CURRENT == 3 )) && _rack_ids || compadd show set reset ;;
    context)         (( CURRENT == 3 )) && _rack_ids || compadd show search snapshot index compress ;;
    workflow|wf)     (( CURRENT == 3 )) && _rack_ids || compadd list create show delete ;;
    team)            compadd status delegate queue done ;;
    gates|security)  compadd status enable disable isolate ;;
    keys|key|secret) compadd add list remove rotate setup validate export ;;
    models)          compadd set preset reset ;;
    completions)     compadd bash zsh ;;
    cost|usage)      (( CURRENT == 3 )) && { _rack_ids; compadd --history --json } || compadd --history --json --days ;;
    info|show|delete|remove|rm|profile|tier|wire|unwire|telegram|logs|log|edit|snapshot|export|audit)
                     (( CURRENT == 3 )) && _rack_ids ;;
  esac
}
_rack "$@"
ZSH_EOF
}

cmd_completions() {
  case "${1:-}" in
    bash) _rack_emit_bash ;;
    zsh)  _rack_emit_zsh ;;
    ""|-h|--help|help)
      cat <<'USAGE'
Usage: rack completions <bash|zsh>

Enable now (current shell):
  bash:  eval "$(rack completions bash)"
  zsh:   eval "$(rack completions zsh)"

Enable permanently:
  bash:  echo 'eval "$(rack completions bash)"' >> ~/.bashrc
  zsh:   echo 'eval "$(rack completions zsh)"' >> ~/.zshrc
USAGE
      ;;
    *) error "Unknown shell '$1' (supported: bash, zsh)" ;;
  esac
}
