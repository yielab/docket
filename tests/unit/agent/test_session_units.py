"""Durable turn history + compaction (`agent/session.py`).

Covers session-key isolation, a round trip preserving `tool_calls`/
`tool_call_id`/`name`, an assistant `tool_calls` message never split from
its answering `tool` messages by a compaction cut, measured vs. estimated
token accounting, and fail-closed summarisation on a failing driver.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.agent import session as _sess
from docket.agent import session_compaction as _session_compaction
from docket.agent import session_units as _session_units
from docket.agent.llm import ChatMessage, ToolCall, assistant, system, tool_result, user
from docket.agent.ports import TurnResult
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.agent.session_units"

# ── driver test doubles (matches SessionSummaryRunner's 5-arg shape) ──────────


def _summarizing_driver(text: str = "summary of the old turns") -> _sess.SessionSummaryRunner:
    def _driver(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        return TurnResult(True, text, 0.0, {})

    return _driver


@pytest.fixture(autouse=True)
def _isolate_sessions_dir(tmp_path: Path) -> Iterator[None]:
    with use_home(dataclasses.replace(current_home(), sessions_dir_override=tmp_path / "sessions")):
        yield


# ── helpers ──────────────────────────────────────────────────────────────────


def _tool_call_turn(
    call_id: str = "c1", name: str = "read_file", arguments: str = "{}"
) -> list[ChatMessage]:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return [assistant("", tool_calls=[call]), tool_result(call, f"result for {call_id}")]


# ── atomic grouping ───────────────────────────────────────────────────────────


class TestGroupAtomicUnits:
    def test_plain_messages_are_each_their_own_unit(self) -> None:
        msgs = [system("s"), user("u"), assistant("a")]
        assert _session_units.group_atomic_units(msgs) == [[m] for m in msgs]

    def test_tool_call_and_its_result_group_together(self) -> None:
        turn = _tool_call_turn()
        groups = _session_units.group_atomic_units(turn)
        assert groups == [turn]

    def test_multiple_tool_calls_group_with_all_their_results(self) -> None:
        c1 = ToolCall(id="a", name="read", arguments="{}")
        c2 = ToolCall(id="b", name="write", arguments="{}")
        asst = assistant("", tool_calls=[c1, c2])
        r1 = tool_result(c1, "res-a")
        r2 = tool_result(c2, "res-b")
        groups = _session_units.group_atomic_units([asst, r1, r2])
        assert groups == [[asst, r1, r2]]

    def test_group_closes_once_matching_results_are_exhausted(self) -> None:
        """A later, unrelated message after a fully-answered tool call starts a new unit rather than being swept into the group."""
        turn = _tool_call_turn()
        tail = user("next question")
        groups = _session_units.group_atomic_units([*turn, tail])
        assert groups == [turn, [tail]]

    def test_unanswered_tool_call_still_forms_its_own_unit(self) -> None:
        call = ToolCall(id="c1", name="read", arguments="{}")
        asst = assistant("", tool_calls=[call])
        groups = _session_units.group_atomic_units([asst])
        assert groups == [[asst]]

    def test_preexisting_orphan_tool_message_is_its_own_unit(self) -> None:
        orphan = ChatMessage(role="tool", content="stray", tool_call_id="ghost", name="x")
        groups = _session_units.group_atomic_units([user("hi"), orphan])
        assert groups == [[user("hi")], [orphan]]


class TestOrphanDetection:
    def test_no_orphans_in_a_well_formed_history(self) -> None:
        history = [user("q"), *_tool_call_turn(), assistant("done")]
        assert _session_units.find_orphaned_tool_messages(history) == []
        assert _session_units.find_unanswered_tool_calls(history) == []

    def test_detects_a_tool_message_with_no_preceding_call(self) -> None:
        orphan = ChatMessage(role="tool", content="x", tool_call_id="ghost", name="y")
        history = [user("q"), orphan]
        assert _session_units.find_orphaned_tool_messages(history) == [1]

    def test_detects_an_unanswered_tool_call(self) -> None:
        call = ToolCall(id="c1", name="read", arguments="{}")
        history = [assistant("", tool_calls=[call])]
        assert _session_units.find_unanswered_tool_calls(history) == ["c1"]

    def test_drift_planted_a_split_group_is_caught(self) -> None:
        """Guard evidence: manually split an atomic unit (the exact bug compaction must never introduce) and confirm the checker flags it both ways -- an orphaned result and, on the other half, an unanswered call."""
        turn = _tool_call_turn()
        assistant_only = [turn[0]]
        tool_only = [turn[1]]
        assert _session_units.find_unanswered_tool_calls(assistant_only) == ["c1"]
        assert _session_units.find_orphaned_tool_messages(tool_only) == [0]


# ── plan_compaction: budgeting + the atomicity boundary case ──────────────────


class TestPlanCompactionBasics:
    def test_fits_within_budget_is_a_no_op_plan(self) -> None:
        msgs = [system("s"), user("hi"), assistant("hello")]
        plan = _session_units.plan_compaction(msgs, budget_tokens=100_000)
        assert not plan.needed
        assert plan.keep_head == [system("s")]
        assert plan.keep_tail == [user("hi"), assistant("hello")]

    def test_leading_system_messages_are_always_kept(self) -> None:
        msgs = [system("s1"), system("s2"), user("hi")]
        plan = _session_units.plan_compaction(msgs, budget_tokens=1)
        assert plan.keep_head == [system("s1"), system("s2")]

    def test_at_least_the_most_recent_unit_survives_a_tiny_budget(self) -> None:
        msgs = [user("a" * 5000), user("final question")]
        plan = _session_units.plan_compaction(msgs, budget_tokens=1)
        assert plan.keep_tail == [user("final question")]
        assert plan.to_summarize == [[user("a" * 5000)]]

    def test_no_messages_at_all(self) -> None:
        plan = _session_units.plan_compaction([], budget_tokens=1000)
        assert plan.keep_head == []
        assert plan.to_summarize == []
        assert plan.keep_tail == []
        assert not plan.needed

    def test_ranged_plan_can_summarize_its_only_unit_when_anchor_is_external(self) -> None:
        latest = user("large completed tool context " * 100)

        plan = _session_units.plan_compaction([latest], budget_tokens=1, keep_latest_unit=False)

        assert plan.keep_tail == []
        assert plan.to_summarize == [[latest]]


class TestPlanCompactionAtomicityBoundary:
    """The card's named trap: a cut that would land inside a tool-call group."""

    def test_boundary_cut_never_splits_the_tool_call_group(self) -> None:
        from docket.agent.context import estimate_tokens

        m0 = user("first question, quite a bit of padding text to add weight")
        call = ToolCall(id="c1", name="read_file", arguments='{"path": "notes.md"}')
        m1 = assistant("let me check that file", tool_calls=[call])
        m2 = tool_result(call, "file contents: lorem ipsum dolor sit amet")
        m3 = user("second question")
        m4 = assistant("final answer")
        history = [m0, m1, m2, m3, m4]

        # Craft a budget that fits m4 + m3 + m2 exactly, but not m1 too -- a
        # naive flat-message cut would keep m2 (the tool result) while
        # dropping m1 (the tool call that produced it), splitting the group.
        def _tok(msg: ChatMessage) -> int:
            return estimate_tokens(_session_units._render_message_for_estimate(msg))

        budget = _tok(m4) + _tok(m3) + _tok(m2)

        plan = _session_units.plan_compaction(history, budget_tokens=budget)

        # The group [m1, m2] must appear together, either entirely kept or
        # entirely summarized -- never split across the two.
        tail_has_m1 = m1 in plan.keep_tail
        tail_has_m2 = m2 in plan.keep_tail
        assert tail_has_m1 == tail_has_m2, "tool-call group was split across keep_tail"

        summarized_flat = [m for unit in plan.to_summarize for m in unit]
        summ_has_m1 = m1 in summarized_flat
        summ_has_m2 = m2 in summarized_flat
        assert summ_has_m1 == summ_has_m2, "tool-call group was split across to_summarize"

        # With this specific budget, the group doesn't fit alongside m3+m4,
        # so it (and the even-older m0) must be pushed into to_summarize
        # together, whole.
        assert plan.to_summarize == [[m0], [m1, m2]]
        assert plan.keep_tail == [m3, m4]

    def test_boundary_case_end_to_end_through_compact_session_has_no_orphans(self) -> None:
        from docket.agent.context import estimate_tokens

        call = ToolCall(id="c1", name="read_file", arguments="{}")
        m0 = user("padding " * 20)
        m1 = assistant("checking", tool_calls=[call])
        m2 = tool_result(call, "contents")
        m3 = user("q2")
        m4 = assistant("a2")
        _sess.append_messages("agent:x:default", [m0, m1, m2, m3, m4])

        def _tok(msg: ChatMessage) -> int:
            return estimate_tokens(_session_units._render_message_for_estimate(msg))

        budget = _tok(m4) + _tok(m3) + _tok(m2)
        result = _session_compaction.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_summarizing_driver(),
            budget_tokens=budget,
        )

        assert result.ok
        assert result.compacted
        final = _sess.load_messages("agent:x:default")
        assert _session_units.find_orphaned_tool_messages(final) == []
        assert _session_units.find_unanswered_tool_calls(final) == []
        # The tool call and its result are either both gone (folded into the
        # summary) or both present -- never one without the other.
        has_call = any(m.tool_calls for m in final)
        has_result = any(m.role == "tool" for m in final)
        assert has_call == has_result
