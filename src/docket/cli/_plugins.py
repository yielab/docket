"""docket plugins — list predicate plugins an operator has applied.

  docket plugins list [--pod <p>]   Table of every applied predicate: name, scope, file, sha256.

``run_plugins(args)`` returns the process exit code, wiring ``core/plugins.py::discover`` --
the same lookup a policy's ``when: {plugin: ...}`` uses. Plugins are never listed from a
codebase, only from ``~/.docket/plugins/`` and a pod's own ``config/plugins/``.
"""

from __future__ import annotations

from docket import ui
from docket.cli._flags import find_unknown_flag
from docket.core import plugins as _plugins


def _extract_pod(args: list[str]) -> tuple[str, str]:
    """Pull ``--pod <p>`` out of *args*. Returns ``(pod, error)``; *pod* is ``""`` when absent."""
    if "--pod" in args:
        idx = args.index("--pod")
        if idx + 1 >= len(args):
            return "", "--pod requires a pod name"
        return args[idx + 1], ""
    return "", ""


def _list(pod: str) -> int:
    try:
        registry = _plugins.discover(pod)
    except _plugins.PluginError as exc:
        ui.fail(str(exc))
        return 1
    if not registry:
        ui.warn("No plugins applied.")
        return 0

    ui.header("Predicate Plugins")
    ui.console.print()
    print(f"  {'NAME':<24} {'SCOPE':<12} {'FILE':<44} SHA256")
    print(f"  {'-' * 100}")
    for name in sorted(registry):
        pred = registry[name]
        print(f"  {name:<24} {pred.scope:<12} {pred.file!s:<44} {pred.sha256}")
    ui.console.print()
    return 0


def run_plugins(args: list[str] | None = None) -> int:
    """Dispatch the plugins subcommand (``list``, the default) and return the exit code."""
    rest = list(args or [])
    sub = "list"
    if rest and not rest[0].startswith("-"):
        sub = rest[0]
        rest = rest[1:]
    if sub != "list":
        ui.error("Usage: docket plugins list [--pod <p>]")
        return 1

    bad = find_unknown_flag(rest, frozenset({"--pod"}))
    if bad is not None:
        ui.error(f"docket plugins: unrecognized flag '{bad}'")
        return 2

    pod, err = _extract_pod(rest)
    if err:
        ui.error(err)
        return 1
    return _list(pod)
