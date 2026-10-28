"""``handoff``: the tool a hop is offered to record its outcome and finish."""

from __future__ import annotations

import json

import pytest

from docket.agent.tools.registry import ToolContext
from docket.hops.application.handoff_tool import handoff_tool, parse_values

SUBJECT = "docket.hops.application.handoff_tool"
VALUES = ("APPROVE", "REQUEST-CHANGES")


class TestSchema:
    def test_a_gated_step_requires_a_verdict_enum_of_the_gates_values(self) -> None:
        tool = handoff_tool(VALUES)

        assert tool.name == "handoff"
        assert tool.parameters["required"] == ["verdict"]
        assert tool.parameters["properties"]["verdict"]["enum"] == list(VALUES)
        assert list(tool.parameters["properties"]) == [
            "summary",
            "filesChanged",
            "verdict",
            "assumptions",
            "questions",
        ]

    def test_an_ungated_step_requires_nothing_and_leaves_the_verdict_free(self) -> None:
        tool = handoff_tool()

        assert "required" not in tool.parameters
        assert "enum" not in tool.parameters["properties"]["verdict"]

    def test_description_and_kind(self) -> None:
        tool = handoff_tool(VALUES)

        assert (
            tool.description
            == "Record your handoff and finish. Call this once, as your last action."
        )
        assert tool.kind == "read"
        assert tool.ends_turn is True


class TestHandler:
    @pytest.mark.parametrize(
        ("given", "recorded"),
        [("APPROVE", "APPROVE"), ("approve", "APPROVE"), (" request-changes ", "REQUEST-CHANGES")],
    )
    def test_a_verdict_in_the_enum_is_recorded_in_its_canonical_form(
        self, given: str, recorded: str
    ) -> None:
        outcome = handoff_tool(VALUES).handler({"verdict": given}, ToolContext())

        assert outcome.ok is True
        assert outcome.content == recorded

    def test_a_case_sensitive_gate_keeps_the_exact_value(self) -> None:
        tool = handoff_tool(("ship", "hold"), case_sensitive=True)

        assert tool.handler({"verdict": "ship"}, ToolContext()).ok is True
        assert tool.handler({"verdict": "SHIP"}, ToolContext()).ok is False

    @pytest.mark.parametrize("given", ["maybe", "", "APPROVE it"])
    def test_any_other_verdict_fails_and_names_the_allowed_ones(self, given: str) -> None:
        outcome = handoff_tool(VALUES).handler({"verdict": given}, ToolContext())

        assert outcome.ok is False
        assert "APPROVE, REQUEST-CHANGES" in outcome.error

    def test_an_ungated_call_closes_with_its_summary(self) -> None:
        outcome = handoff_tool().handler(
            {"summary": "Added the widget.", "assumptions": ["python 3"]}, ToolContext()
        )

        assert outcome.ok is True
        assert outcome.content == "Added the widget."

    def test_arguments_that_break_the_schema_fail_the_call(self) -> None:
        outcome = handoff_tool().handler({"assumptions": "not a list"}, ToolContext())

        assert outcome.ok is False


class TestEnvironmentCoordinate:
    def test_the_values_and_the_case_rule_round_trip(self) -> None:
        raw = json.dumps({"values": list(VALUES), "caseSensitive": False})

        assert parse_values(raw) == (VALUES, False)

    @pytest.mark.parametrize(
        "raw", [None, "", "not json", "[]", '{"values": []}', '{"values": [1]}']
    )
    def test_anything_unusable_offers_no_tool(self, raw: str | None) -> None:
        assert parse_values(raw) is None
