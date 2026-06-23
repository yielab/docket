"""Rich console helpers — Python equivalent of lib/helpers/output.sh.

All output goes through a Rich Console so ANSI codes are handled portably:
colours render in a TTY and are suppressed when stdout is piped/captured
(CI, tests, shell redirection) without any extra configuration.

Stderr outputs (warn, error, info) mirror the Bash conventions where those
functions write to >&2.
"""

from __future__ import annotations

from rich.console import Console

# Primary output (stdout) — highlight=False keeps Rich from auto-colourising
# numbers, strings, etc. so our explicit markup stays authoritative.
console = Console(highlight=False)

# Diagnostic stream (stderr) — same Console API, different fd.
_err = Console(stderr=True, highlight=False)


def header(text: str) -> None:
    """Bold section header preceded by a blank line (mirrors Bash header())."""
    console.print()
    console.print(f"[bold]{text}[/bold]")


def success(text: str) -> None:
    """Green tick prefix to stdout (mirrors Bash success())."""
    console.print(f"[green]✓[/green] {text}")


def warn(text: str) -> None:
    """Yellow warning prefix to stderr (mirrors Bash warn())."""
    _err.print(f"[yellow]⚠[/yellow]  {text}")


def error(text: str) -> None:
    """Red cross + 'Error:' prefix to stderr (mirrors Bash error(), no exit)."""
    _err.print(f"[red]✗[/red] [red]Error:[/red] {text}")


def info(text: str) -> None:
    """Cyan arrow prefix to stdout (mirrors Bash info())."""
    console.print(f"[cyan]→[/cyan]  {text}")


def dim(text: str) -> None:
    """Dim (grey) text to stdout (mirrors Bash dim())."""
    console.print(f"[dim]{text}[/dim]")
