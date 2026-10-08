"""`docket setup shell bash|zsh`: print the completion script for the live command tree."""

from __future__ import annotations

from enum import StrEnum

import typer
from typer.core import TyperGroup
from typer.main import get_command


class Shell(StrEnum):
    bash = "bash"
    zsh = "zsh"


def _top_level_commands() -> list[tuple[str, str]]:
    """(name, one-line help) for every visible top-level command, read live from the app."""
    from docket.cli import app

    click_group = get_command(app)
    assert isinstance(click_group, TyperGroup)
    pairs: list[tuple[str, str]] = []
    for name, cmd in click_group.commands.items():
        if getattr(cmd, "hidden", False):
            continue
        help_text = (cmd.get_short_help_str(limit=200) or "").rstrip(".")
        pairs.append((name, help_text))
    return pairs


def _zsh_escape(text: str) -> str:
    return text.replace("'", "'\\''")


# bash completion script template; __COMMANDS__ is substituted at runtime
# with the space-joined live command names (see _top_level_commands).
_BASH_TEMPLATE = """\
# docket(1) bash completion — eval "$(docket setup shell bash)"
_docket_complete() {
  local cur prev cword
  cur="${COMP_WORDS[COMP_CWORD]}"
  cword=$COMP_CWORD

  local commands="__COMMANDS__"

  # Live agent ids (pod members) from the workspace tree, basenames only.
  local _dh="${DOCKET_HOME:-$HOME/.docket}"
  local _ids="" _d _b
  if [[ -d "$_dh/workspaces/projects" ]]; then
    for _d in "$_dh/workspaces/projects"/*/; do
      [[ -d "$_d" ]] || continue; _b="${_d%/}"; _ids+=" ${_b##*/}"
    done
  fi
  if [[ -d "$_dh/workspaces" ]]; then
    for _d in "$_dh/workspaces"/*/; do
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
    status)          words="--all --json" ;;
    maintain)        [[ $cword -eq 2 ]] && words="$_ids" || words="check clean reset rebuild sessions distill" ;;
    pod)             [[ $cword -eq 2 ]] && words="$_ids" || words="list add remove delegate queue config apply export" ;;
    setup)           words="provider model notify export sandbox mcp shell --json --fix" ;;
    pipeline)        words="validate plan" ;;
    runs)            words="list show cancel prune" ;;
    audit)           words="verify --json" ;;
    trace)           words="tail export ingest expire" ;;
    policies)        words="list show init test validate" ;;
    recipes)         words="list show" ;;
    roles)           words="list show add validate" ;;
    info|delete|profile)
                     [[ $cword -eq 2 ]] && words="$_ids" ;;
    *)               words="" ;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")
}
complete -F _docket_complete docket
"""

# zsh completion script template; __ZSH_COMMANDS__ is substituted at runtime
# with 'name:help' entries (one per line, see _top_level_commands).
_ZSH_TEMPLATE = """\
#compdef docket
# docket(1) zsh completion — eval "$(docket setup shell zsh)"
_docket() {
  local -a commands
  commands=(
__ZSH_COMMANDS__
  )

  _docket_ids() {
    local dh="${DOCKET_HOME:-$HOME/.docket}"
    local -a ids
    ids=(${dh}/workspaces/projects/*(/N:t) ${dh}/workspaces/*(/N:t))
    ids=(${ids:#projects})
    compadd -a ids
  }

  if (( CURRENT == 2 )); then
    _describe 'docket command' commands
    return
  fi

  case "${words[2]}" in
    status)          compadd --all --json ;;
    maintain)        (( CURRENT == 3 )) && _docket_ids || compadd check clean reset rebuild sessions distill ;;
    pod)             (( CURRENT == 3 )) && _docket_ids || compadd list add remove delegate queue config apply export ;;
    setup)           compadd provider model notify export sandbox mcp shell --json --fix ;;
    pipeline)        compadd validate plan ;;
    runs)            compadd list show cancel prune ;;
    audit)           compadd verify --json ;;
    trace)           compadd tail export ingest expire ;;
    policies)        compadd list show init test validate ;;
    recipes)         compadd list show ;;
    roles)           compadd list show add validate ;;
    info|delete|profile)
                     (( CURRENT == 3 )) && _docket_ids ;;
  esac
}
_docket "$@"
"""


def render_bash() -> str:
    names = [name for name, _help in _top_level_commands()]
    return _BASH_TEMPLATE.replace("__COMMANDS__", " ".join(names))


def render_zsh() -> str:
    lines = [f"    '{name}:{_zsh_escape(help_text)}'" for name, help_text in _top_level_commands()]
    return _ZSH_TEMPLATE.replace("__ZSH_COMMANDS__", "\n".join(lines))


def cmd_shell(shell: Shell = typer.Argument(..., help="bash or zsh")) -> None:
    """Print the completion script for bash or zsh.

    Enable it for the current shell with: eval "$(docket setup shell bash)"

    Example: docket setup shell zsh"""
    print(render_bash() if shell is Shell.bash else render_zsh(), end="")
