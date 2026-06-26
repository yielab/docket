"""docket completions — emit a shell completion script.

`run_completions(shell)` prints the bash or zsh completion script to stdout
and returns the process exit code. Only bash and zsh are supported.
"""

from __future__ import annotations

from docket import ui

# bash completion script
_BASH = """\
# docket(1) bash completion — eval "$(docket completions bash)"
_docket_complete() {
  local cur prev cword
  cur="${COMP_WORDS[COMP_CWORD]}"
  cword=$COMP_CWORD

  local commands="install list add info delete maintain context wire unwire telegram scope profile keys pod team workflow logs edit cost doctor gates audit eval snapshot serve models trace metrics policies approve deny completions help version"

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
    pod)             [[ $cword -eq 2 ]] && words="$_ids" || words="add remove delegate queue dispatch" ;;
    team)            words="delegate queue start done cancel" ;;
    gates|security)  words="status enable disable isolate" ;;
    keys|key|secret) words="add list remove rotate setup validate export" ;;
    models)          words="set preset reset" ;;
    trace)           words="tail export ingest" ;;
    policies|policy) words="list show init test" ;;
    completions)     words="bash zsh" ;;
    cost|usage)      [[ $cword -eq 2 ]] && words="$_ids --history --json" || words="--history --json --days" ;;
    info|show|delete|remove|rm|profile|tier|wire|unwire|telegram|logs|log|edit|snapshot|export|audit)
                     [[ $cword -eq 2 ]] && words="$_ids" ;;
    *)               words="" ;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")
}
complete -F _docket_complete docket
"""

# zsh completion script
_ZSH = """\
#compdef docket
# docket(1) zsh completion — eval "$(docket completions zsh)"
_docket() {
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
    'pod:Inspect/manage a project pod'
    'team:Org manager task queue'
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
    'trace:View/tail/export agent-action traces'
    'metrics:Success rate, latency, cost, guardrail stats'
    'policies:Manage guardrail policies'
    'approve:Grant a pending HITL approval'
    'deny:Deny a pending HITL approval'
    'completions:Emit a shell completion script'
    'help:Show help'
  )

  _docket_ids() {
    local oc="${OPENCLAW_DIR:-$HOME/.openclaw}"
    local -a ids
    ids=(${oc}/workspaces/projects/*(/N:t) ${oc}/workspaces/*(/N:t))
    ids=(${ids:#projects})
    compadd -a ids
  }

  if (( CURRENT == 2 )); then
    _describe 'docket command' commands
    return
  fi

  case "${words[2]}" in
    maintain)        (( CURRENT == 3 )) && _docket_ids || compadd check clean reset rebuild sessions ;;
    scope)           (( CURRENT == 3 )) && _docket_ids || compadd show set reset ;;
    context)         (( CURRENT == 3 )) && _docket_ids || compadd show search snapshot index compress ;;
    workflow|wf)     (( CURRENT == 3 )) && _docket_ids || compadd list create show delete ;;
    pod)             (( CURRENT == 3 )) && _docket_ids || compadd add remove delegate queue dispatch ;;
    team)            compadd delegate queue start done cancel ;;
    gates|security)  compadd status enable disable isolate ;;
    keys|key|secret) compadd add list remove rotate setup validate export ;;
    models)          compadd set preset reset ;;
    trace)           compadd tail export ingest ;;
    policies|policy) compadd list show init test ;;
    completions)     compadd bash zsh ;;
    cost|usage)      (( CURRENT == 3 )) && { _docket_ids; compadd --history --json } || compadd --history --json --days ;;
    info|show|delete|remove|rm|profile|tier|wire|unwire|telegram|logs|log|edit|snapshot|export|audit)
                     (( CURRENT == 3 )) && _docket_ids ;;
  esac
}
_docket "$@"
"""

_USAGE = """\
Usage: docket completions <bash|zsh>

Enable now (current shell):
  bash:  eval "$(docket completions bash)"
  zsh:   eval "$(docket completions zsh)"

Enable permanently:
  bash:  echo 'eval "$(docket completions bash)"' >> ~/.bashrc
  zsh:   echo 'eval "$(docket completions zsh)"' >> ~/.zshrc
"""


def run_completions(shell: str | None) -> int:
    """Emit a shell completion script for ``shell`` (bash|zsh).

    Empty / help → usage text (exit 0). Unknown shell → error (exit 1).
    Returns the process exit code; the coordinator wraps it in typer.Exit.
    """
    if shell == "bash":
        # print() adds the trailing newline that the heredoc closes with.
        print(_BASH, end="")
        return 0
    if shell == "zsh":
        print(_ZSH, end="")
        return 0
    if shell in (None, "", "-h", "--help", "help"):
        print(_USAGE, end="")
        return 0
    ui.error(f"Unknown shell '{shell}' (supported: bash, zsh)")
    return 1
