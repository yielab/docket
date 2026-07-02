"""docket completions — emit a shell completion script.

`run_completions(shell)` prints the bash or zsh completion script to stdout
and returns the process exit code. Only bash and zsh are supported.

CH-8: the top-level command table used to be a hand-maintained string literal
and it drifted — it kept advertising `team`/`tier` after they were removed,
and never learned `auth`/`policies`/`approve`/`deny`/`metrics`. It is now
derived at *call time* from the live Typer `app` registry (see
`_top_level_commands`), so it can never disagree with `docket --help` again.

Every docket command here is a flat Typer command (none are Click sub-groups
— second-level verbs like `maintain check|clean|reset` are parsed by hand
inside each command body, not registered with Click). That means the
sub-command word lists embedded in `_BASH_TEMPLATE` / `_ZSH_TEMPLATE` below
cannot be introspected the same way and remain hand-maintained — keep them in
sync with the relevant command's own action parsing if you add, rename, or
remove a subcommand action. The custom agent-id completion (reads live
workspace ids from the filesystem) is unrelated to the Typer registry and is
untouched by this generation.
"""

from __future__ import annotations

from docket import ui


def _top_level_commands() -> list[tuple[str, str]]:
    """(name, one-line help) for every visible top-level command, in
    registration order, read live from `docket.cli.app` — see module
    docstring. Hidden commands (e.g. the internal `_json` bridge) are
    excluded; they're not part of the public CLI surface.
    """
    from typer.core import TyperGroup
    from typer.main import get_command

    from docket.cli import app

    click_group = get_command(app)
    assert isinstance(click_group, TyperGroup)  # narrows for the .commands access below
    pairs: list[tuple[str, str]] = []
    for name, cmd in click_group.commands.items():
        if getattr(cmd, "hidden", False):
            continue
        help_text = (cmd.get_short_help_str(limit=200) or "").rstrip(".")
        pairs.append((name, help_text))
    return pairs


def _zsh_escape(text: str) -> str:
    """Escape a string for embedding inside a single-quoted zsh literal."""
    return text.replace("'", "'\\''")


# bash completion script template; __COMMANDS__ is substituted at runtime
# with the space-joined live command names (see _top_level_commands).
_BASH_TEMPLATE = """\
# docket(1) bash completion — eval "$(docket completions bash)"
_docket_complete() {
  local cur prev cword
  cur="${COMP_WORDS[COMP_CWORD]}"
  cword=$COMP_CWORD

  local commands="__COMMANDS__"

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
    context)         [[ $cword -eq 2 ]] && words="$_ids" || words="show search snapshot index compress project" ;;
    workflow|wf)     [[ $cword -eq 2 ]] && words="$_ids" || words="list create show validate plan delete" ;;
    pod)             [[ $cword -eq 2 ]] && words="$_ids" || words="list add remove delegate queue dispatch" ;;
    gates|security)  words="status enable disable isolate" ;;
    keys|key|secret) words="add list remove rotate setup validate export" ;;
    models)          words="list set preset reset provider" ;;
    auth)            words="status login key setup" ;;
    trace)           words="tail export ingest" ;;
    policies|policy) words="list show init test" ;;
    completions|completion) words="bash zsh" ;;
    cost|usage)      [[ $cword -eq 2 ]] && words="$_ids --history --json" || words="--history --json --days" ;;
    info|show|delete|remove|rm|profile|wire|unwire|telegram|logs|log|edit)
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
# docket(1) zsh completion — eval "$(docket completions zsh)"
_docket() {
  local -a commands
  commands=(
__ZSH_COMMANDS__
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
    context)         (( CURRENT == 3 )) && _docket_ids || compadd show search snapshot index compress project ;;
    workflow|wf)     (( CURRENT == 3 )) && _docket_ids || compadd list create show validate plan delete ;;
    pod)             (( CURRENT == 3 )) && _docket_ids || compadd list add remove delegate queue dispatch ;;
    gates|security)  compadd status enable disable isolate ;;
    keys|key|secret) compadd add list remove rotate setup validate export ;;
    models)          compadd list set preset reset provider ;;
    auth)            compadd status login key setup ;;
    trace)           compadd tail export ingest ;;
    policies|policy) compadd list show init test ;;
    completions|completion) compadd bash zsh ;;
    cost|usage)      (( CURRENT == 3 )) && { _docket_ids; compadd --history --json } || compadd --history --json --days ;;
    info|show|delete|remove|rm|profile|wire|unwire|telegram|logs|log|edit)
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


def _render_bash() -> str:
    names = [name for name, _help in _top_level_commands()]
    return _BASH_TEMPLATE.replace("__COMMANDS__", " ".join(names))


def _render_zsh() -> str:
    lines = [f"    '{name}:{_zsh_escape(help_text)}'" for name, help_text in _top_level_commands()]
    return _ZSH_TEMPLATE.replace("__ZSH_COMMANDS__", "\n".join(lines))


def run_completions(shell: str | None) -> int:
    """Emit a shell completion script for ``shell`` (bash|zsh).

    Empty / help → usage text (exit 0). Unknown shell → error (exit 1).
    Returns the process exit code; the coordinator wraps it in typer.Exit.
    """
    if shell == "bash":
        # print() adds the trailing newline that the heredoc closes with.
        print(_render_bash(), end="")
        return 0
    if shell == "zsh":
        print(_render_zsh(), end="")
        return 0
    if shell in (None, "", "-h", "--help", "help"):
        print(_USAGE, end="")
        return 0
    ui.error(f"Unknown shell '{shell}' (supported: bash, zsh)")
    return 1
