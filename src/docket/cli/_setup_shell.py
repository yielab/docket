"""`docket setup shell bash|zsh`: print the completion script for the live command tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import typer
from typer.core import TyperGroup
from typer.main import get_command


class Shell(StrEnum):
    bash = "bash"
    zsh = "zsh"


@dataclass
class _Node:
    """One command in the live tree: its verbs, long options and what it completes after."""

    path: str
    help: str = ""
    verbs: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    pod_option: bool = False
    takes_task_id: bool = False


def _long_options(cmd: object) -> list[str]:
    found: list[str] = []
    for param in getattr(cmd, "params", []):
        for opt in getattr(param, "opts", []):
            if opt.startswith("--") and opt not in found:
                found.append(opt)
    return found


def _short_help(cmd: object) -> str:
    get = getattr(cmd, "get_short_help_str", None)
    return (get(limit=200) if get else "").rstrip(".")


def _walk(cmd: object, path: str, out: list[_Node]) -> None:
    opts = [o for o in _long_options(cmd) if o != "--help"]
    node = _Node(path=path, help=_short_help(cmd), options=[*opts, "--help"])
    node.pod_option = any(o in ("--pod",) for o in opts)
    children = getattr(cmd, "commands", None)
    out.append(node)
    if children is None:
        node.takes_task_id = path.startswith("task ") and any(
            getattr(p, "name", "") == "ref" for p in getattr(cmd, "params", [])
        )
        return
    for name, sub in children.items():
        if getattr(sub, "hidden", False):
            continue
        node.verbs.append(name)
        _walk(sub, f"{path} {name}".strip(), out)


def _tree() -> list[_Node]:
    from docket.cli import app

    root = get_command(app)
    assert isinstance(root, TyperGroup)
    nodes: list[_Node] = []
    _walk(root, "", nodes)
    nodes[0].options = ["--version", "--help"]
    return nodes


def _case_arms(nodes: list[_Node], pick: str) -> str:
    arms = []
    for node in nodes:
        value = " ".join(getattr(node, pick))
        if value:
            arms.append(f'    "{node.path}") echo "{value}" ;;')
    return "\n".join(arms)


def _flag_arms(nodes: list[_Node], pick: str) -> str:
    paths = [f'"{n.path}"' for n in nodes if getattr(n, pick)]
    return f"    {'|'.join(paths)}) echo yes ;;" if paths else ""


def _helpers(nodes: list[_Node]) -> str:
    return f"""\
_docket_verbs() {{
  case "$1" in
{_case_arms(nodes, "verbs")}
  esac
}}

_docket_options() {{
  case "$1" in
{_case_arms(nodes, "options")}
  esac
}}

_docket_takes_pod() {{
  case "$1" in
{_flag_arms(nodes, "pod_option")}
  esac
}}

_docket_takes_task_id() {{
  case "$1" in
{_flag_arms(nodes, "takes_task_id")}
  esac
}}

_docket_pods() {{
  local dh="${{DOCKET_HOME:-$HOME/.docket}}" d b
  for d in "$dh"/workspaces/projects/*-lead/; do
    [[ -d "$d" ]] || continue
    b="${{d%/}}"; b="${{b##*/}}"; echo "${{b%-lead}}"
  done
}}

_docket_task_ids() {{
  local dh="${{DOCKET_HOME:-$HOME/.docket}}" f
  for f in "$dh"/workspaces/projects/*-lead/TASK_LIST.json; do
    [[ -f "$f" ]] && grep -o '"id": *"[^"]*"' "$f" | sed 's/.*: *"\\(.*\\)"/\\1/'
  done
}}
"""


_NODE_WALK = """\
  for (( i=%(first)s; i<%(stop)s; i++ )); do
    w="${%(words)s[i]}"
    if (( skip )); then skip=0; continue; fi
    if [[ "$w" == --pod || "$w" == -p ]]; then skip=1; continue; fi
    [[ "$w" == -* ]] && continue
    [[ " $(_docket_verbs "$node") " == *" $w "* ]] || break
    node="${node:+$node }$w"
  done"""

_BASH_MAIN = (
    """\
_docket_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}" prev="" node="" w i skip=0 words
  (( COMP_CWORD > 0 )) && prev="${COMP_WORDS[COMP_CWORD-1]}"
"""
    + _NODE_WALK % {"first": "1", "stop": "COMP_CWORD", "words": "COMP_WORDS"}
    + """
  if [[ "$prev" == --pod || "$prev" == -p ]] && [[ -n "$(_docket_takes_pod "$node")" ]]; then
    mapfile -t COMPREPLY < <(compgen -W "$(_docket_pods)" -- "$cur")
    return
  fi
  words="$(_docket_verbs "$node") $(_docket_options "$node")"
  [[ -n "$(_docket_takes_task_id "$node")" ]] && words+=" $(_docket_task_ids)"
  mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")
}
complete -F _docket_complete docket
"""
)

_ZSH_MAIN = (
    """\
_docket() {
  local node="" w i skip=0 prev="${words[CURRENT-1]}"
  local -a cand commands
  _docket_commands
"""
    + _NODE_WALK % {"first": "2", "stop": "CURRENT", "words": "words"}
    + """
  if [[ "$prev" == --pod || "$prev" == -p ]] && [[ -n "$(_docket_takes_pod "$node")" ]]; then
    cand=(${(f)"$(_docket_pods)"})
    compadd -a cand
    return
  fi
  if [[ -z "$node" ]]; then
    _describe 'docket command' commands
  else
    cand=(${=$(_docket_verbs "$node")})
    compadd -a cand
  fi
  cand=(${=$(_docket_options "$node")})
  [[ -n "$(_docket_takes_task_id "$node")" ]] && cand+=(${(f)"$(_docket_task_ids)"})
  compadd -a cand
}
if [[ "${funcstack[1]}" == _docket ]]; then
  _docket "$@"
else
  compdef _docket docket
fi
"""
)


def _zsh_escape(text: str) -> str:
    return text.replace("'", "'\\''")


def render_bash() -> str:
    header = '# docket(1) bash completion -- eval "$(docket setup shell bash)"\n\n'
    return header + _helpers(_tree()) + "\n" + _BASH_MAIN


def render_zsh() -> str:
    nodes = _tree()
    entries = "\n".join(
        f"    '{node.path}:{_zsh_escape(node.help)}'"
        for node in nodes
        if node.path in nodes[0].verbs
    )
    return (
        '#compdef docket\n# docket(1) zsh completion -- eval "$(docket setup shell zsh)"\n\n'
        + _helpers(nodes)
        + f"\n_docket_commands() {{\n  commands=(\n{entries}\n  )\n}}\n\n"
        + _ZSH_MAIN
    )


def cmd_shell(shell: Shell = typer.Argument(..., help="bash or zsh")) -> None:
    """Print the completion script for bash or zsh.

    Enable it for the current shell with: eval "$(docket setup shell bash)"

    Example: docket setup shell zsh"""
    print(render_bash() if shell is Shell.bash else render_zsh(), end="")
