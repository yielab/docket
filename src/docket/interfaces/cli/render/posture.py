"""``docket pod check --posture``: the three powers a pod holds and, at all three, the warning."""

from __future__ import annotations

from rich.markup import escape

from docket.interfaces.cli.render import ui
from docket.teams.posture import Powers


def render_posture(pod: str, held: Powers) -> None:
    """One line per power with what grants it (``none`` when the pod lacks it), then the warning."""
    ui.console.print()
    ui.console.print(f"  Pod: {escape(pod)}")
    for label, granted in (
        ("Untrusted input", held.untrusted_input),
        ("Private data", held.private_data),
        ("Outward action", held.outward),
    ):
        ui.console.print(f"  {label + ':':<17}{escape('; '.join(granted) or 'none')}")
    if held.holds_all:
        ui.warn(held.warning())
    ui.console.print()
