"""The public API a predicate plugin file imports. Nothing here imports from ``core/``: a
plugin is operator code loaded by convention (see ``core/plugins.py``'s loader), never part of
the policy engine itself.

A predicate is ``fn(call: ToolCall, ctx: PolicyContext, **with_) -> bool``, registered by
decorating it with ``@predicate("name")``; ``core/plugins.py::discover`` drains ``REGISTRY``
after importing each file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PLUGIN_API_VERSION = "1.0.0"

# Drained by core/plugins.py::discover after each file import; a plugin file registers into
# this same process-wide list regardless of which directory loaded it.
REGISTRY: list[tuple[str, Callable[..., bool]]] = []


@dataclass(frozen=True)
class ToolCall:
    """The call a predicate is asked about: its tool name, raw arguments, and the hook's
    rendered text."""

    tool: str
    args: dict[str, Any]
    rendered: str


@dataclass(frozen=True)
class PolicyContext:
    """Where the call is happening: the evaluating role, its pod project, the worktree's
    current branch, and its root path."""

    role: str
    project: str
    branch: str
    worktree_root: str


def predicate(name: str) -> Callable[[Callable[..., bool]], Callable[..., bool]]:
    """Register the decorated function under *name* on ``REGISTRY`` for a loader to drain."""

    def _register(fn: Callable[..., bool]) -> Callable[..., bool]:
        REGISTRY.append((name, fn))
        return fn

    return _register
