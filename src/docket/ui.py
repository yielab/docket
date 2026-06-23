"""Rich console helpers — Python equivalent of lib/helpers/output.sh.

All output goes through a Rich Console so ANSI codes are handled portably:
colours render in a TTY and are suppressed when stdout is piped/captured
(CI, tests, shell redirection) without any extra configuration.

Stderr outputs (warn, error, info) mirror the Bash conventions where those
functions write to >&2.
"""

from __future__ import annotations

from rich.console import Console

# The Bash CLI built each output line as a complete string and emitted it
# verbatim — the terminal soft-wrapped for display but no newline was ever
# inserted into the byte stream. Rich, by contrast, hard-wraps at the detected
# console width (falling back to 80 columns when stdout is piped), which breaks
# byte-parity with the goldens. We build full lines ourselves and never rely on
# Rich for layout (no Tables/rules), so we pin a very large width to disable
# wrapping entirely and reproduce the Bash behaviour on any terminal.
_NO_WRAP_WIDTH = 10_000

# Primary output (stdout) — highlight=False keeps Rich from auto-colourising
# numbers, strings, etc. so our explicit markup stays authoritative.
console = Console(highlight=False, width=_NO_WRAP_WIDTH, soft_wrap=True)

# Diagnostic stream (stderr) — same Console API, different fd.
_err = Console(stderr=True, highlight=False, width=_NO_WRAP_WIDTH, soft_wrap=True)


def header(text: str) -> None:
    """Bold section header preceded by a blank line (mirrors Bash header())."""
    console.print()
    console.print(f"[bold]{text}[/bold]")


def success(text: str) -> None:
    """Green tick prefix to stdout (mirrors Bash success())."""
    console.print(f"[green]✓[/green] {text}")


def warn(text: str) -> None:
    """Yellow warning prefix to stdout (mirrors Bash warn(), which is not >&2)."""
    console.print(f"[yellow]⚠[/yellow] {text}")


def error(text: str) -> None:
    """Red cross + 'Error:' prefix to stderr (mirrors Bash error(), no exit)."""
    _err.print(f"[red]✗[/red] [red]Error:[/red] {text}")


def fail(text: str) -> None:
    """Red cross prefix to stderr, no 'Error:' label (mirrors Bash fail())."""
    _err.print(f"[red]✗[/red] {text}")


def info(text: str) -> None:
    """Cyan arrow prefix to stdout (mirrors Bash info())."""
    console.print(f"[cyan]→[/cyan] {text}")


def dim(text: str) -> None:
    """Dim (grey) text to stdout (mirrors Bash dim())."""
    console.print(f"[dim]{text}[/dim]")
