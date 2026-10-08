"""The root command group: usage errors that name the live commands a word could mean."""

from __future__ import annotations

import importlib
from difflib import get_close_matches
from typing import TYPE_CHECKING

from typer.core import TyperGroup

if TYPE_CHECKING:
    from typer import _click as click
else:
    # The click TyperGroup is built on: typer's vendored copy when it has one, else click itself.
    click = importlib.import_module(TyperGroup.__mro__[1].__module__.rpartition(".")[0])

DAILY = "Daily"
POD = "The pod"
MACHINE = "Machine"

PANELS: dict[str, tuple[str, ...]] = {
    DAILY: ("init", "status", "inbox", "task", "run"),
    POD: ("pod", "log"),
    MACHINE: ("setup", "start", "stop", "exec"),
}
_ORDER = [name for names in PANELS.values() for name in names]


def _group_verbs(group: TyperGroup) -> dict[str, list[str]]:
    """Map each verb to the 'group verb' paths that provide it, read from the live tree."""
    found: dict[str, list[str]] = {}
    for name, cmd in group.commands.items():
        if hasattr(cmd, "commands") and not cmd.hidden:
            for verb in cmd.commands:
                found.setdefault(verb, []).append(f"{name} {verb}")
    return found


def _join(options: list[str]) -> str:
    quoted = [f"'docket {o}'" for o in options]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " or " + quoted[-1]


class DocketGroup(TyperGroup):
    """Root group whose unknown-word error offers live top-level names and group verbs."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.exceptions.UsageError as err:
            word = args[0] if args else ""
            visible = [n for n, c in self.commands.items() if not c.hidden]
            options = get_close_matches(word, visible)
            options += [p for p in _group_verbs(self).get(word, []) if p not in options]
            err.message = f"No such command {word!r}."
            if options:
                err.message += f" Did you mean {_join(options)}?"
            raise

    def list_commands(self, ctx: click.Context) -> list[str]:
        names = list(self.commands)
        return sorted(names, key=lambda n: _ORDER.index(n) if n in _ORDER else len(_ORDER))
