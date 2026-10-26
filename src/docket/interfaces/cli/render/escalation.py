"""How the terminal prints an escalation's options and the command that answers it.

The terminal surfaces (``docket inbox``, ``docket task show``, the foreground progress view) share
these lines; ``operator.render`` holds what a content level lets them print, and the command
strings live here because only the CLI knows its own verbs.
"""

from __future__ import annotations

from docket.kernel.operator_contract import EscalationView
from docket.operator import RenderedOption, render_escalation

__all__ = ["answer_command", "decision_line", "options_line"]


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


def decision_line(view: EscalationView) -> str:
    """What the pod chose for a pause it settled alone: ``chose sqlite (SQLite) -- policy
    recommendation at L4``."""
    resolution = view.resolution
    option_id = resolution.option_id if resolution and resolution.option_id else "-"
    label = next(
        (o.label for o in render_escalation(view, "full").options if o.id == option_id), ""
    )
    chosen = f"{option_id} ({label})" if label else option_id
    where = f" at {view.level}" if view.level else ""
    return f"chose {chosen} -- policy {view.policy}{where}"
