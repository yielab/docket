"""The console voice: the only module that knows symbols, colour roles and layout.

Five symbols, five colour roles, one plain mode. Output is plain (no colour, no
boxes, ASCII symbols) when stdout is not a TTY or ``NO_COLOR`` is set.
"""

from __future__ import annotations

import os
import shutil
import sys

from rich import box
from rich.console import Console
from rich.table import Table

TAGLINE = "docket runs teams of coding agents and governs what they may do"

# Rich hard-wraps at the detected console width (80 when stdout is piped),
# breaking byte-parity with the golden test suite. Pin a very large width to
# disable wrapping entirely.
_NO_WRAP_WIDTH = 10_000

# highlight=False keeps Rich from auto-colourising numbers, strings, etc. so
# our explicit markup stays authoritative.
console = Console(highlight=False, width=_NO_WRAP_WIDTH, soft_wrap=True)

_err = Console(stderr=True, highlight=False, width=_NO_WRAP_WIDTH, soft_wrap=True)

SYMBOLS = {"done": "✓", "failed": "✗", "attention": "⚠", "next": "→", "detail": "·"}
_PLAIN_SYMBOLS = {"done": "ok", "failed": "x", "attention": "!", "next": "->", "detail": "-"}

ROLES = {
    "success": "green",
    "error": "red",
    "warn": "yellow",
    "accent": "cyan",
    "dim": "dim",
}


def is_plain() -> bool:
    """True when output carries no colour, boxes or non-ASCII symbols."""
    return bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


def _sym(name: str) -> str:
    return (_PLAIN_SYMBOLS if is_plain() else SYMBOLS)[name]


def _line(target: Console, symbol: str, role: str, text: str) -> None:
    plain = is_plain()
    target.no_color = plain
    mark = _sym(symbol)
    if plain:
        target.print(f"{mark} {text}")
    else:
        target.print(f"[{ROLES[role]}]{mark}[/{ROLES[role]}] {text}")


def header(noun: str, name: str = "") -> None:
    """Blank line, then ``docket · <noun> <name>`` when a name is given, else the bare text."""
    console.no_color = is_plain()
    console.print()
    if name:
        dot = _sym("detail") if not is_plain() else "-"
        console.print(f"docket {dot} {noun} [{ROLES['accent']}]{name}[/{ROLES['accent']}]")
    else:
        console.print(f"[bold]{noun}[/bold]")


def section(title: str) -> None:
    """A shared section name (Needs you, Running, Done, Failed) after a blank line."""
    console.no_color = is_plain()
    console.print()
    console.print(f"[bold]{title}[/bold]")


def success(text: str) -> None:
    _line(console, "done", "success", text)


def warn(text: str) -> None:
    _line(console, "attention", "warn", text)


def error(what: str, do: str = "") -> None:
    """One line on stderr. With ``do``: ``<what>. <do>``; without, the ``Error:`` form."""
    if do:
        _line(_err, "failed", "error", f"{what.rstrip('.')}. {do}")
    else:
        _line(_err, "failed", "error", f"[{ROLES['error']}]Error:[/{ROLES['error']}] {what}")


def fail(text: str) -> None:
    _line(_err, "failed", "error", text)


def info(text: str) -> None:
    _line(console, "next", "accent", text)


def hint(command: str) -> None:
    """The one ``Next:`` line a state-changing command ends with, on stderr."""
    _line(_err, "next", "accent", f"Next: {command}")


def guide(lines: list[tuple[str, str]]) -> None:
    """The bare-command guide: the tagline, one line per command, then the setup pointer."""
    console.no_color = is_plain()
    console.print(TAGLINE)
    console.print()
    width = max(len(command) for command, _ in lines)
    for command, meaning in lines:
        console.print(f"  [{ROLES['accent']}]{command.ljust(width)}[/{ROLES['accent']}]  {meaning}")
    console.print()
    console.print("Not set up yet? [" + ROLES["accent"] + "]docket setup[/" + ROLES["accent"] + "]")


def dim(text: str) -> None:
    console.no_color = is_plain()
    console.print(f"[dim]{text}[/dim]")


def table(rows: list[list[str]], columns: list[str], *, width: int | None = None) -> None:
    """Print a table whose cells wrap at word boundaries; no cell is ever cut."""
    plain = is_plain()
    tbl = Table(box=None if plain else box.SIMPLE_HEAD, pad_edge=False, show_edge=False)
    for col in columns:
        tbl.add_column(col, overflow="fold", no_wrap=False, style=None if plain else "bold")
    for row in rows:
        tbl.add_row(*[str(c) for c in row])
    cols = width or shutil.get_terminal_size((100, 24)).columns
    out = Console(
        file=sys.stdout, width=cols, highlight=False, no_color=plain, force_terminal=not plain
    )
    out.print(tbl)
