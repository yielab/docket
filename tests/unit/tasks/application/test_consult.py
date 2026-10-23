"""The ``consult`` built-in (`tasks/application/consult.py`, registered by `agent/tools/registry.py`): a model asks
the operator a decision question with options and a recommendation, bounded per turn."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from docket.agent.llm import ToolCall
from docket.agent.tools.builtin_tools import builtin_registry
from docket.agent.tools.registry import ToolContext, ToolResult, dispatch_tool
from docket.kernel.home import current_home, use_home
from docket.observability import trace as _trace
from docket.tasks.application import consult as _consult
from docket.teams import roles as _arch

SUBJECT = "docket.tasks.application.consult"


@pytest.fixture(autouse=True)
def _short_waits(tmp_path: Path) -> Iterator[None]:
    with use_home(
        dataclasses.replace(
            current_home(), tool_approval_timeout=1, policies_dir_override=tmp_path / "_policies"
        )
    ):
        yield


def _args(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "decision",
        "message": "Which store should the cache use?",
        "options": [
            {"id": "redis", "label": "Redis", "description": "fast", "risks": ["ops cost"]},
            {"id": "sqlite", "label": "SQLite", "description": "simple", "estimatedTokens": 900},
        ],
        "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
    }
    base.update(over)
    return base


def _call(args: dict[str, Any], ctx: ToolContext, call_id: str = "c1") -> ToolResult:
    call = ToolCall(id=call_id, name="consult", arguments=json.dumps(args))
    return dispatch_tool(call, ctx, builtin_registry())


def _ctx(**over: Any) -> ToolContext:
    base: dict[str, Any] = {
        "agent_id": "a1",
        "session_key": "agent:a1:default",
        "role": "lead",
        "project": "a1",
        "approval_mode": "wait",
    }
    base.update(over)
    return ToolContext(**base)


def _events() -> tuple[list[dict[str, Any]], Callable[[], None]]:
    seen: list[dict[str, Any]] = []
    unsubscribe = _trace.add_subscriber(
        lambda r: seen.append(r) if r.get("event_type") == "question_asked" else None
    )
    return seen, unsubscribe


class TestRegistration:
    def test_consult_is_a_read_kind_builtin(self) -> None:
        tool = builtin_registry().get("consult")
        assert tool is not None and tool.kind == "read"
        assert _arch.BUILTIN_TOOL_KINDS["consult"] == "read"

    def test_a_reviewer_keeps_consult(self) -> None:
        registry = _arch.registry_for_role(builtin_registry(), "reviewer")
        assert "consult" in registry.names()
        assert "write" not in registry.names()


class TestValidation:
    def test_a_consult_without_a_recommendation_is_an_error_result(self) -> None:
        args = _args()
        del args["recommendation"]
        seen, off = _events()
        try:
            result = _call(args, _ctx(approval_mode="refuse"))
        finally:
            off()
        assert not result.ok and "recommendation" in result.as_tool_output()
        assert result.denial_kind is None
        assert seen == []

    def test_fewer_than_two_options_is_an_error_result(self) -> None:
        result = _call(_args(options=_args()["options"][:1]), _ctx())
        assert not result.ok and "options" in result.as_tool_output()

    def test_a_recommendation_naming_no_option_is_an_error_result(self) -> None:
        result = _call(_args(recommendation={"optionId": "nope", "rationale": "x"}), _ctx())
        assert not result.ok and "nope" in result.as_tool_output()

    def test_an_unknown_kind_is_an_error_result(self) -> None:
        result = _call(_args(kind="approval"), _ctx())
        assert not result.ok and "kind" in result.as_tool_output()


class TestWait:
    def test_a_wait_mode_consult_has_nobody_to_ask_and_tells_the_model_to_decide(self) -> None:
        seen, off = _events()
        try:
            result = _call(_args(), _ctx())
        finally:
            off()
        assert result.ok and result.content == "no answer; decide yourself"
        assert seen == []


class TestRefuse:
    def test_refuse_ends_the_turn_blocked_and_still_records_the_question(self) -> None:
        seen, off = _events()
        try:
            result = _call(_args(), _ctx(approval_mode="refuse"))
        finally:
            off()
        assert result.denial_kind == "approval_unavailable"
        assert result.tool == "consult" and result.call_id == "c1"
        (event,) = seen
        assert event["payload"]["question"]["kind"] == "decision"

    def test_park_outside_pod_dispatch_behaves_like_refuse(self) -> None:
        result = _call(_args(), _ctx(approval_mode="park"))
        assert result.denial_kind == "approval_unavailable"

    def test_pod_dispatch_parks_a_consult_and_leaves_its_question_for_dispatch(self) -> None:
        result = _call(_args(), _ctx(approval_mode="wait", consult_park=True))
        assert result.denial_kind == "approval_parked"
        question = _consult.parked_question(result.approval_token)
        assert question is not None and question.kind == "decision"
        assert not hasattr(_consult, "take_parked")

    def test_the_question_survives_the_real_error_string_and_dispatch_parser(self) -> None:
        from docket.agent import loop as _loop
        from docket.hops.application import record as _record

        result = _call(_args(), _ctx(approval_mode="wait", consult_park=True))
        error = _loop.approval_parked_error(result)
        token = _record._parked_approval_token(error)
        assert token == result.approval_token
        assert token is not None
        assert "message" not in token and len(token) < 40
        question = _consult.parked_question(token)
        assert question is not None and token == f"consult:{question.id}"
        assert _consult.parked_question(token) is None  # taken once, then gone
        assert [o.id for o in question.options] == [o["id"] for o in _args()["options"]]

    def test_a_token_without_a_question_yields_none(self) -> None:
        assert _consult.parked_question("consult:q_abc") is None
        assert _consult.parked_question("approval-1") is None

    def test_question_task_id_prefers_the_context_task_id(self) -> None:
        result = _call(_args(), _ctx(approval_mode="wait", consult_park=True, task_id="run-7"))
        question = _consult.parked_question(result.approval_token)
        assert question is not None and question.task_id == "run-7"
        bare = _call(_args(), _ctx(approval_mode="wait", consult_park=True))
        fallback = _consult.parked_question(bare.approval_token)
        assert fallback is not None and fallback.task_id == "agent:a1:default"

    def test_refuse_wins_over_pod_dispatch_parking(self) -> None:
        result = _call(_args(), _ctx(approval_mode="refuse", consult_park=True))
        assert result.denial_kind == "approval_unavailable"


class TestCap:
    def test_the_call_past_the_cap_is_refused_as_budget_exhausted(self) -> None:
        ctx = _ctx()
        for n in range(3):
            assert _call(_args(), ctx, f"c{n}").ok
        fourth = _call(_args(), ctx, "c4")
        assert not fourth.ok
        assert "consultation budget exhausted; decide yourself" in fourth.as_tool_output()

    def test_the_cap_is_the_contexts_own_setting(self) -> None:
        ctx = _ctx(max_consultations=0)
        result = _call(_args(), ctx)
        assert not result.ok and "budget exhausted" in result.as_tool_output()
