"""Rich output helpers.

All output goes through a Rich Console so ANSI codes are handled portably:
colours render in a TTY and are suppressed when stdout is piped/captured
(CI, tests, shell redirection) without any extra configuration.
"""

from __future__ import annotations

from rich.console import Console

# Rich hard-wraps at the detected console width (80 when stdout is piped),
# breaking byte-parity with the golden test suite. Pin a very large width to
# disable wrapping entirely.
_NO_WRAP_WIDTH = 10_000

# Primary output (stdout) — highlight=False keeps Rich from auto-colourising
# numbers, strings, etc. so our explicit markup stays authoritative.
console = Console(highlight=False, width=_NO_WRAP_WIDTH, soft_wrap=True)

_err = Console(stderr=True, highlight=False, width=_NO_WRAP_WIDTH, soft_wrap=True)


def header(text: str) -> None:
    """Bold section header preceded by a blank line."""
    console.print()
    console.print(f"[bold]{text}[/bold]")


def success(text: str) -> None:
    console.print(f"[green]✓[/green] {text}")


def warn(text: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {text}")


def error(text: str) -> None:
    _err.print(f"[red]✗[/red] [red]Error:[/red] {text}")


def fail(text: str) -> None:
    _err.print(f"[red]✗[/red] {text}")


def info(text: str) -> None:
    console.print(f"[cyan]→[/cyan] {text}")


def dim(text: str) -> None:
    console.print(f"[dim]{text}[/dim]")
