"""How the terminal prints an escalation's options and the command that answers it.

The terminal surfaces (``docket inbox``, ``docket task show``, the foreground progress view) share
these lines; ``operator.render`` holds what a content level lets them print, and the command
strings live here because only the CLI knows its own verbs.
"""

from __future__ import annotations

from docket.operator import RenderedOption

__all__ = ["answer_command", "options_line"]


def options_line(options: tuple[RenderedOption, ...]) -> str:
    """``id (label), id (label) (recommended)``: one option per entry, labels included."""
    return ", ".join(
        f"{o.id} ({o.label})" + (" (recommended)" if o.recommended else "") for o in options
    )


def answer_command(task_id: str, options: tuple[RenderedOption, ...]) -> str:
    """``docket task answer <id>``, naming the recommended option (else the first) when the
    pause offers any."""
    chosen = next((o for o in options if o.recommended), options[0] if options else None)
    command = f"docket task answer {task_id}"
    return f"{command} --option {chosen.id}" if chosen else command
