"""One render for an escalation (``operator/render.py``): what each content level lets a surface
print. Option ids are never withheld; a prompt and a model's labels wait for the level that allows
them."""

from __future__ import annotations

from typing import Any

import pytest

from docket.kernel.operator_contract import (
    EscalationAffordances,
    EscalationView,
    Option,
    Recommendation,
)
from docket.operator import render as _render

SUBJECT = "docket.operator.render"


def _view(kind: str = "consult", **over: Any) -> EscalationView:
    options = [
        Option(id="redis", label="Redis", description="fast"),
        Option(id="sqlite", label="SQLite", description="simple"),
    ]
    fields: dict[str, Any] = {
        "id": "esc-0123456789ab",
        "task": "task-1",
        "pod": "demo",
        "step": "implementer",
        "role": "implementer",
        "kind": kind,
        "causedBy": "c1",
        "prompt": "Which store should the cache use?",
        "options": options,
        "recommendation": Recommendation(option_id="sqlite", rationale="SECRETWHY"),
        "askedAt": "2026-10-25T00:00:00+00:00",
        "expiresAt": "2026-10-25T01:00:00+00:00",
        "onExpiry": "block",
        "seq": 1,
        "affordances": EscalationAffordances(
            options=["redis", "sqlite"],
            acceptsText=True,
            resolveUrl="/escalations/esc-0123456789ab",
        ),
    }
    fields.update(over)
    return EscalationView.model_validate(fields)


def _approval_view(**over: Any) -> EscalationView:
    options = [
        Option(id="approve_once", label="Approve once", description="this call"),
        Option(id="approve_task", label="Approve for the task", description="this task"),
        Option(id="deny", label="Deny", description="refuse"),
    ]
    return _view(
        "approval",
        prompt="tool call 'bash': rm -rf build",
        options=options,
        recommendation=None,
        onExpiry="deny",
        **over,
    )


class TestConsult:
    @pytest.mark.parametrize("level", ["minimal", "actions"])
    def test_a_question_below_conversation_keeps_its_option_ids_and_hides_the_rest(
        self, level: str
    ) -> None:
        rendered = _render.render_escalation(_view(), level)

        assert rendered.prompt is None
        assert [o.id for o in rendered.options] == ["redis", "sqlite"]
        assert all(o.label == "" for o in rendered.options)
        assert "SECRETWHY" not in repr(rendered)
        assert "Redis" not in repr(rendered)

    @pytest.mark.parametrize("level", ["conversation", "full"])
    def test_conversation_adds_the_prompt_and_the_labels(self, level: str) -> None:
        rendered = _render.render_escalation(_view(), level)

        assert rendered.prompt == "Which store should the cache use?"
        assert [(o.id, o.label, o.recommended) for o in rendered.options] == [
            ("redis", "Redis", False),
            ("sqlite", "SQLite", True),
        ]

    def test_the_recommendation_is_marked_at_every_level(self) -> None:
        rendered = _render.render_escalation(_view(), "minimal")

        assert [o.recommended for o in rendered.options] == [False, True]

    def test_the_decline_of_a_question_is_not_an_option_to_name(self) -> None:
        decline = Option(id="decline", label="Decline", description="no")
        view = _view(options=[*_view().options, decline])

        rendered = _render.render_escalation(view, "conversation")

        assert [o.id for o in rendered.options] == ["redis", "sqlite"]

    def test_a_label_loses_control_characters_and_is_capped(self) -> None:
        label = "A\x1b[31mB\nC" + "x" * 500
        view = _view(options=[Option(id="a", label=label, description="d")], recommendation=None)

        shown = _render.render_escalation(view, "conversation").options[0].label

        assert "\x1b" not in shown and "\n" not in shown
        assert len(shown) <= 80

    def test_the_title_is_fixed_text_and_the_expiry_is_carried(self) -> None:
        rendered = _render.render_escalation(_view(), "minimal")

        assert rendered.title == "consultation"
        assert rendered.expires_at == "2026-10-25T01:00:00+00:00"


class TestApproval:
    def test_actions_adds_the_prompt_minimal_does_not(self) -> None:
        assert _render.render_escalation(_approval_view(), "minimal").prompt is None
        assert "rm -rf build" in (
            _render.render_escalation(_approval_view(), "actions").prompt or ""
        )

    def test_the_options_docket_wrote_keep_their_labels_at_every_level(self) -> None:
        rendered = _render.render_escalation(_approval_view(), "minimal")

        assert [(o.id, o.label) for o in rendered.options] == [
            ("approve_once", "Approve once"),
            ("approve_task", "Approve for the task"),
            ("deny", "Deny"),
        ]
        assert not any(o.recommended for o in rendered.options)


def test_the_ids_line_marks_the_recommended_option() -> None:
    rendered = _render.render_escalation(_view(), "minimal")

    assert _render.ids_line(rendered.options) == "redis, sqlite (recommended sqlite)"
    assert _render.ids_line(()) == ""


def test_an_unknown_level_renders_as_minimal() -> None:
    rendered = _render.render_escalation(_view(), "everything")

    assert rendered.prompt is None
    assert all(o.label == "" for o in rendered.options)
