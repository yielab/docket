"""One render for an escalation: what each surface may print of it at a content level.

Every surface that shows a pause (``docket inbox``, ``docket task show``, the foreground progress
view, Telegram ``/status``, a notification) draws from ``render_escalation``, so the three content
levels are applied in one place. An option id is what a reply names, so ids are present at every
level; a prompt and a model's labels wait for the level that allows them. Pure: no I/O, and no
command string, because each surface prints its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

from docket.kernel.operator_contract import EscalationKind, EscalationView, Option

__all__ = [
    "RenderedEscalation",
    "RenderedOption",
    "clean_label",
    "ids_line",
    "render_escalation",
    "render_options",
]

_LABEL_MAX = 80
_QUESTION_KINDS: frozenset[EscalationKind] = frozenset({"consult", "input"})
_CONVERSATION_LEVELS = frozenset({"conversation", "full"})
_ACTION_LEVELS = frozenset({"actions", "conversation", "full"})
# The title is fixed text so that no level can leak model or tool text through it.
_TITLES: dict[EscalationKind, str] = {
    "approval": "tool call needs approval",
    "gate": "approval gate",
    "check_changed": "task changed its own check",
    "consult": "consultation",
    "input": "input requested",
}
# A question's own decline is answered by its own verb (`--decline`), never by naming an option.
_DECLINE = "decline"


class RenderedOption(NamedTuple):
    """One option as a surface prints it; *label* is empty where the level withholds it."""

    id: str
    label: str
    recommended: bool


@dataclass(frozen=True)
class RenderedEscalation:
    """An escalation cut to a content level."""

    title: str
    prompt: str | None
    options: tuple[RenderedOption, ...]
    expires_at: str | None


def clean_label(label: str) -> str:
    """Model text bound for a chat or a terminal: control characters dropped, length capped."""
    text = "".join(ch for ch in label if ch.isprintable())
    return text[:_LABEL_MAX]


def render_options(
    options: Iterable[Option], recommended: str | None, *, labels: bool
) -> tuple[RenderedOption, ...]:
    """*options* as rendered options: ids always, labels only when *labels*."""
    return tuple(
        RenderedOption(
            clean_label(o.id),
            clean_label(o.label) if labels else "",
            o.id == recommended,
        )
        for o in options
    )


def ids_line(options: Iterable[RenderedOption]) -> str:
    """``a, b (recommended a)``: the ids a reply may name, the recommended one last."""
    shown = list(options)
    line = ", ".join(o.id for o in shown)
    recommended = next((o.id for o in shown if o.recommended), None)
    return f"{line} (recommended {recommended})" if recommended else line


def render_escalation(view: EscalationView, level: str) -> RenderedEscalation:
    """*view* as a surface at content *level* may print it; an unknown level renders as ``minimal``."""
    question = view.kind in _QUESTION_KINDS
    allowed = _CONVERSATION_LEVELS if question else _ACTION_LEVELS
    options = [o for o in view.options if not (question and o.id == _DECLINE)]
    recommended = view.recommendation.option_id if view.recommendation else None
    # Docket wrote an approval's labels; a question's come from the model.
    labels = not question or level in _CONVERSATION_LEVELS
    return RenderedEscalation(
        title=_TITLES[view.kind],
        prompt=view.prompt if level in allowed else None,
        options=render_options(options, recommended, labels=labels),
        expires_at=view.expires_at,
    )
