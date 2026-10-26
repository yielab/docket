"""``verdict``: the tool a verdict-gated hop is offered to record its verdict and finish."""

from __future__ import annotations

import json

import pytest

from docket.agent.tools.registry import ToolContext
from docket.hops.application.verdict_tool import parse_values, verdict_tool

SUBJECT = "docket.hops.application.verdict_tool"
VALUES = ("APPROVE", "REQUEST-CHANGES")


class TestSchema:
    def test_one_required_value_parameter_whose_enum_is_the_gates_values(self) -> None:
        tool = verdict_tool(VALUES)

        assert tool.name == "verdict"
        assert tool.parameters["required"] == ["value"]
        assert list(tool.parameters["properties"]) == ["value"]
        assert tool.parameters["properties"]["value"]["enum"] == list(VALUES)
        assert tool.parameters["properties"]["value"]["type"] == "string"

    def test_description_and_kind(self) -> None:
        tool = verdict_tool(VALUES)

        assert (
            tool.description
            == "Record your verdict and finish. Call this once, as your last action."
        )
        assert tool.kind == "read"
        assert tool.ends_turn is True


class TestHandler:
    @pytest.mark.parametrize(
        ("given", "recorded"),
        [("APPROVE", "APPROVE"), ("approve", "APPROVE"), (" request-changes ", "REQUEST-CHANGES")],
    )
    def test_a_value_in_the_enum_is_recorded_in_its_canonical_form(
        self, given: str, recorded: str
    ) -> None:
        outcome = verdict_tool(VALUES).handler({"value": given}, ToolContext())

        assert outcome.ok is True
        assert outcome.content == recorded

    def test_a_case_sensitive_gate_keeps_the_exact_value(self) -> None:
        tool = verdict_tool(("ship", "hold"), case_sensitive=True)

        assert tool.handler({"value": "ship"}, ToolContext()).ok is True
        assert tool.handler({"value": "SHIP"}, ToolContext()).ok is False

    @pytest.mark.parametrize("given", ["maybe", "", "APPROVE it"])
    def test_any_other_value_fails_and_names_the_allowed_ones(self, given: str) -> None:
        outcome = verdict_tool(VALUES).handler({"value": given}, ToolContext())

        assert outcome.ok is False
        assert "APPROVE, REQUEST-CHANGES" in outcome.error


class TestEnvironmentCoordinate:
    def test_the_values_and_the_case_rule_round_trip(self) -> None:
        raw = json.dumps({"values": list(VALUES), "caseSensitive": False})

        assert parse_values(raw) == (VALUES, False)

    @pytest.mark.parametrize(
        "raw", [None, "", "not json", "[]", '{"values": []}', '{"values": [1]}']
    )
    def test_anything_unusable_offers_no_tool(self, raw: str | None) -> None:
        assert parse_values(raw) is None
