"""The MCP `resolve` tool, and the older approval and answer tools settling the same record.

The tool functions are called directly (plain Python, no `mcp` SDK), over a seeded pod whose
pauses carry an escalation; the oracles are the returned value, the raised `McpToolError`, the
escalation record, the task and the `mcp.*` audit lines.
"""

from __future__ import annotations

import pytest
from tests.support import escalations as _support_escalations
from tests.support.escalations import (
    PROJECT,
    approval_escalation,
    consult_escalation,
    input_escalation,
)
from tests.support.tasks import stored_task
from tests.support.trace import audit_entries

from docket.governance import approval as _approval
from docket.interfaces.cli.commands import mcp as _mcp
from docket.platform import read_escalation

SUBJECT = "docket.interfaces.cli.commands.mcp"


demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("demo_pod")


class TestToolResolve:
    def test_it_settles_a_consult_and_says_so(self) -> None:
        escalation = consult_escalation()

        result = _mcp.tool_resolve(escalation.id, "redis", {"note": "hot path"})

        assert result == {"ok": True, "escalation": escalation.id, "state": "resolved"}
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert (stored.resolution.channel, stored.resolution.by) == ("mcp", "mcp")
        assert stored_task(PROJECT, escalation.task).status == "pending"
        assert len(audit_entries("mcp.resolve")) == 1

    def test_it_grants_an_approval_through_the_same_grant(self) -> None:
        escalation = approval_escalation("gate")

        _mcp.tool_resolve(escalation.id, "approve_once")

        assert _approval.approval_get(escalation.legacy["token"])["state"] == "granted"
        (line,) = audit_entries("approval.grant")
        assert "channel=mcp" in line["detail"]
        assert stored_task(PROJECT, escalation.task).gate_override_pipeline_index == 1

    def test_a_second_call_raises_and_changes_nothing(self) -> None:
        escalation = input_escalation()
        _mcp.tool_resolve(escalation.id, None, {"answer": "ship it"})
        settled = read_escalation(escalation.id)

        with pytest.raises(_mcp.McpToolError):
            _mcp.tool_resolve(escalation.id, None, {"answer": "again"})

        assert read_escalation(escalation.id) == settled
        assert len(audit_entries("mcp.resolve")) == 2

    def test_an_unknown_escalation_raises(self) -> None:
        with pytest.raises(_mcp.McpToolError):
            _mcp.tool_resolve("esc-000000000000", "deny")

    def test_an_option_it_does_not_offer_raises_naming_the_ids(self) -> None:
        escalation = consult_escalation()

        with pytest.raises(_mcp.McpToolError, match="redis, sqlite, decline"):
            _mcp.tool_resolve(escalation.id, "mongo")

        assert stored_task(PROJECT, escalation.task).status == "waiting_input"

    def test_it_is_one_of_the_tools_the_server_exposes(self) -> None:
        assert "resolve" in _mcp._TOOL_NAMES


class TestTheOlderToolsSettleTheRecord:
    def test_granting_the_token_resolves_its_escalation(self) -> None:
        escalation = approval_escalation("gate")

        result = _mcp.tool_approvals_grant(escalation.legacy["token"])

        assert result["state"] == "granted"
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.state == "resolved"
        assert stored.resolution is not None and stored.resolution.channel == "mcp"

    def test_denying_the_token_resolves_its_escalation(self) -> None:
        escalation = approval_escalation("gate")

        _mcp.tool_approvals_deny(escalation.legacy["token"])

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.state == "resolved"
        assert stored.resolution is not None and stored.resolution.option_id == "deny"
        assert stored_task(PROJECT, escalation.task).status == "failed"

    def test_a_repeat_grant_raises_without_the_token_leaving_the_record(self) -> None:
        escalation = approval_escalation("gate")
        _mcp.tool_approvals_grant(escalation.legacy["token"])

        with pytest.raises(_mcp.McpToolError):
            _mcp.tool_approvals_grant(escalation.legacy["token"])

    def test_answering_the_task_resolves_its_escalation(self) -> None:
        escalation = input_escalation()

        result = _mcp.tool_task_answer(PROJECT, escalation.task, "accept", {"answer": "ship it"})

        assert result["action"] == "accept"
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.state == "resolved"

    def test_a_repeat_answer_raises(self) -> None:
        escalation = input_escalation()
        _mcp.tool_task_answer(PROJECT, escalation.task, "accept", {"answer": "ship it"})

        with pytest.raises(_mcp.McpToolError):
            _mcp.tool_task_answer(PROJECT, escalation.task, "accept", {"answer": "ship it"})
