"""The ``when.command`` predicate of a policy: a shell command line read by invocation.

``command`` is a mapping with any of ``program`` (names of the program an invocation runs, glob
allowed), ``verb`` (a subcommand word among its non-option arguments, so an option before it, as
in ``kubectl -n prod apply``, does not hide it), ``args`` (any of its arguments) and ``writes``
(globs over the paths it writes, by redirect or by a program that writes). Every key present must
hold for the same invocation, and the predicate holds when any invocation of the command does.
The invocations are ``governance.security.command_segments``: the ones the classifier reads, with
quoting undone and wrappers such as ``env`` and ``xargs`` peeled.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from docket.governance import security as _security

COMMAND_KEYS: frozenset[str] = frozenset({"program", "verb", "args", "writes"})
# The one built-in tool whose `command` argument is a shell command line.
COMMAND_TOOL = "bash"


def names(value: Any) -> list[str] | None:
    """*value* as a list of non-empty strings (a lone string is a list of one), else ``None``."""
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items:
        return None
    if not all(isinstance(i, str) and i.strip() for i in items):
        return None
    return list(items)


def validate_command(command: Any, label: str) -> str:
    """Validate a ``when.command`` mapping: '' if valid, else the error."""
    if not isinstance(command, dict) or not command:
        return f"{label}: when.command must be a non-empty mapping"
    unknown = set(command) - COMMAND_KEYS
    if unknown:
        return (
            f"{label}: unknown when.command key(s) {sorted(unknown)} "
            "(valid: program, verb, args, writes)"
        )
    for key, value in command.items():
        if names(value) is None:
            return f"{label}: when.command.{key} must be a string or a non-empty list of strings"
    return ""


def _arg_matches(entry: str, token: str) -> bool:
    """Whether one argument *token* is what a ``when.command.args`` *entry* names: a single-letter
    short option (``-f``) also names it inside a cluster (``-rf``); an entry with a glob character
    is an ``fnmatch`` pattern; anything else is an exact word."""
    if len(entry) == 2 and entry[0] == "-" and entry[1] != "-":
        return token.startswith("-") and not token.startswith("--") and entry[1] in token[1:]
    if any(ch in entry for ch in "*?["):
        return fnmatchcase(token, entry)
    return token == entry


def _segment_matches(spec: dict[str, Any], segment: _security.CommandSegment) -> bool:
    """Whether every key of the ``when.command`` *spec* holds for one invocation: ``program`` names
    it (glob allowed), ``verb`` is one of its non-option arguments (so an option before the
    subcommand does not hide it), ``args`` is any of its arguments, ``writes`` is a glob over any
    path it writes."""
    programs = names(spec.get("program"))
    if programs is not None and not any(fnmatchcase(segment.program, p) for p in programs):
        return False
    verbs = names(spec.get("verb"))
    if verbs is not None and not any(
        arg in verbs for arg in segment.args if not arg.startswith("-")
    ):
        return False
    wanted = names(spec.get("args"))
    if wanted is not None and not any(_arg_matches(e, t) for e in wanted for t in segment.args):
        return False
    globs = names(spec.get("writes"))
    return globs is None or any(fnmatchcase(w, g) for w in segment.writes for g in globs)


def command_matches(spec: dict[str, Any], tool: str, args: dict[str, Any]) -> bool:
    """Whether any invocation of the shell command in a call to *tool* with *args* satisfies the
    ``when.command`` *spec*. Only a ``bash`` call carries a command; a command the lexer cannot
    read matches nothing here (the classifier asks for it)."""
    if tool != COMMAND_TOOL:
        return False
    text = args.get("command")
    if not isinstance(text, str):
        return False
    try:
        segments = _security.command_segments(text)
    except ValueError:
        return False
    return any(_segment_matches(spec, segment) for segment in segments)
