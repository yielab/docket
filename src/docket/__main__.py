"""Entry point for `python -m docket` (the thin bin/docket launcher execs this).

Mirrors the command aliasing and removed-command guidance that used to live in
lib/core/router.sh, so the Bash→Python cutover preserves every invocation users
already type.
"""

from __future__ import annotations

import sys

from docket.cli import app

# Alias → canonical command name (mirrors router.sh's case fall-throughs).
_ALIASES = {
    "setup": "install",
    "create": "add",
    "new": "add",
    "show": "info",
    "remove": "delete",
    "rm": "delete",
    "telegram": "wire",
    "tier": "profile",
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

# Removed / renamed commands → one-or-more guidance lines, then exit 1.
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
    "billing": ("docket billing was renamed → use: docket cost [id]",),
    "credits": ("docket billing was renamed → use: docket cost [id]",),
    "monitor": ("docket monitor was renamed → use: docket cost [id]",),
    "mon": ("docket monitor was renamed → use: docket cost [id]",),
    "memory": (
        "docket memory was renamed → use: docket context [id] <search|snapshot|index|compress>",
    ),
    "mem": (
        "docket memory was renamed → use: docket context [id] <search|snapshot|index|compress>",
    ),
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
}


def main() -> None:
    argv = sys.argv[1:]
    # Skip a leading global flag (e.g. --debug) when locating the command token.
    idx = 0
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
