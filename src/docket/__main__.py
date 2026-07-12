"""Entry point for `python -m docket` (the thin bin/docket launcher execs this)."""

from __future__ import annotations

import sys

from docket.cli import app

_ALIASES = {
    "setup": "install",
    "create": "add",
    "new": "add",
    "show": "info",
    "remove": "delete",
    "rm": "delete",
    "telegram": "wire",
    "key": "keys",
    "secret": "keys",
    "wf": "workflow",
    "log": "logs",
    "usage": "cost",
    "check": "doctor",
    "security": "gates",
    "evals": "eval",
    "export": "snapshot",
    "completion": "completions",
    "policy": "policies",
}

_REMOVED: dict[str, tuple[str, ...]] = {
    "reset": ("docket reset was renamed → use: docket maintain [id] <clean|reset|rebuild>",),
    "repair": ("docket repair was renamed → use: docket maintain [id] check",),
    "fix": ("docket repair was renamed → use: docket maintain [id] check",),
    "cleanup": ("docket cleanup was renamed → use: docket maintain [id] sessions",),
    "clean": ("docket cleanup was renamed → use: docket maintain [id] sessions",),
    "model": (
        "docket model was renamed → use: docket profile [id] <provider/model|default>, "
        "or docket models for the role policy",
    ),
    "tier": (
        "docket tier was removed — tier names (economy/standard/premium) are no longer "
        "accepted anywhere (D-2 exit, 0.2.0).",
        "Use: docket profile [id] <provider/model|default> to pin/unpin one agent, or "
        "docket models for the role policy",
    ),
    "billing": ("docket billing was renamed → use: docket cost [id]",),
    "credits": ("docket billing was renamed → use: docket cost [id]",),
    "monitor": ("docket monitor was renamed → use: docket cost [id]",),
    "mon": ("docket monitor was renamed → use: docket cost [id]",),
    "memory": ("docket memory was renamed → use: docket context [id] [show|project]",),
    "mem": ("docket memory was renamed → use: docket context [id] [show|project]",),
    "smart": (
        "docket smart was removed — smart routing was placebo (prose in SOUL.md does not "
        "change the gateway model)",
        "Use: docket models (role policy) or docket profile [id] <provider/model> to set "
        "the actual model",
    ),
    "ai": (
        "docket smart was removed — smart routing was placebo (prose in SOUL.md does not "
        "change the gateway model)",
        "Use: docket models (role policy) or docket profile [id] <provider/model> to set "
        "the actual model",
    ),
    "mode": (
        "docket mode / docket terminal has been removed.",
        "Use: docket models (role policy) or docket profile [id] <provider/model> to "
        "choose models.",
    ),
    "terminal": (
        "docket mode / docket terminal has been removed.",
        "Use: docket models (role policy) or docket profile [id] <provider/model> to "
        "choose models.",
    ),
    "term": (
        "docket mode / docket terminal has been removed.",
        "Use: docket models (role policy) or docket profile [id] <provider/model> to "
        "choose models.",
    ),
    "team": (
        "docket team was retired — pods own delegation now, with real execution "
        "(the old manager queue was never dispatched).",
        'Use: docket pod <project> delegate "<task>"  (was: team delegate "<task>")',
        "Use: docket pod <project> queue                (was: team queue)",
        "Use: docket pod <project> dispatch              to actually run queued tasks",
        "Org-wide view: docket install --portfolio       (Portfolio Manager)",
        "Any old queue file at ~/.openclaw/workspaces/manager/TASK_LIST.json is preserved, "
        "untouched, but no longer read by docket.",
    ),
}


def main() -> None:
    argv = sys.argv[1:]
    idx = 0  # skip leading global flags (e.g. --debug) before the command token
    while idx < len(argv) and argv[idx] in ("--debug",):
        idx += 1
    if idx < len(argv):
        cmd = argv[idx]
        if cmd in _REMOVED:
            for line in _REMOVED[cmd]:
                print(line)
            raise SystemExit(1)
        if cmd in _ALIASES:
            sys.argv[sys.argv.index(cmd)] = _ALIASES[cmd]
    app()


main()
