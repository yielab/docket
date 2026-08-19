"""Durable turn history + compaction (`core/session.py`).

Pure `core/` coverage -- no CLI, no subprocess, no live daemon, no foreign
session-format knowledge. Mirrors `test_memory_distillation.py`'s style (custom
driver functions matching the `DistillRunner`/`SessionSummaryRunner` 5-arg
shape) since compaction's summarisation step is the same call pattern.

Covers:

* **Isolation** -- one session's history never bleeds into another's, even
  for session keys that share characters a naive encoding could collide on.
* **Round trip** -- `tool_calls`, `tool_call_id` and `name` all survive an
  append + reload with no loss.
* **Atomicity, the real trap** -- an assistant `tool_calls` message and the
  `tool` messages answering it are never split by compaction, including the
  boundary case where a naive flat-token cut would land in the middle of the
  group.
* **Budgeting honesty** -- measured (`TokenUsage`) and estimated
  (`estimate_tokens`) token counts are recorded and used independently.
* **Fail-closed summarisation** -- a failing or empty-reply driver call
  leaves the stored session completely untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import session as _sess
from docket.core.llm import ChatMessage, TokenUsage, ToolCall, assistant, system, tool_result, user
from docket.core.runtime_driver import TurnResult

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


def _recording_driver() -> tuple[_sess.SessionSummaryRunner, list[str]]:
    calls: list[str] = []

    def _driver(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        calls.append(message)
        return TurnResult(True, "ok summary", 0.0, {})

    return _driver, calls


def _failing_driver(
    agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None = None
) -> TurnResult:
    return TurnResult(False, "", 0.0, {}, "boom", failure_kind="timeout")


def _empty_reply_driver(
    agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None = None
) -> TurnResult:
    return TurnResult(True, "   ", 0.0, {})


@pytest.fixture(autouse=True)
def _isolate_sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", tmp_path / "sessions", raising=True)


# ── helpers ──────────────────────────────────────────────────────────────────


def _tool_call_turn(
    call_id: str = "c1", name: str = "read_file", arguments: str = "{}"
) -> list[ChatMessage]:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return [assistant("", tool_calls=[call]), tool_result(call, f"result for {call_id}")]


# ── storage isolation ────────────────────────────────────────────────────────


class TestStorageIsolation:
    def test_two_sessions_never_share_messages(self) -> None:
        _sess.append_messages("agent:foo-lead:foo", [user("hello foo")])
        _sess.append_messages("agent:bar-lead:bar", [user("hello bar")])

        foo = _sess.load_messages("agent:foo-lead:foo")
        bar = _sess.load_messages("agent:bar-lead:bar")

        assert [m.content for m in foo] == ["hello foo"]
        assert [m.content for m in bar] == ["hello bar"]

    def test_similar_keys_resolve_to_different_files(self) -> None:
        """Keys that share every character except a delimiter must not collide."""
        _sess.append_messages("agent:a:b", [user("first")])
        _sess.append_messages("agent:a_b:default", [user("second")])

        assert [m.content for m in _sess.load_messages("agent:a:b")] == ["first"]
        assert [m.content for m in _sess.load_messages("agent:a_b:default")] == ["second"]

    def test_unknown_session_loads_empty_not_an_error(self) -> None:
        record = _sess.load_session("agent:never-seen:default")
        assert record.messages == []
        assert record.session_key == "agent:never-seen:default"

    def test_sessions_land_in_separate_files_on_disk(self, tmp_path: Path) -> None:
        _sess.append_messages("agent:foo-lead:foo", [user("x")])
        _sess.append_messages("agent:bar-lead:bar", [user("y")])

        session_files = sorted(p for p in (tmp_path / "sessions").rglob("session.json"))
        assert len(session_files) == 2

    def test_drift_planted_shared_directory_breaks_isolation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard evidence: force every session into the *same* file (the bug
        this design prevents) and confirm the isolation assertion above would
        actually catch it -- i.e. this test is not vacuous."""
        shared = tmp_path / "shared-session.json"
        monkeypatch.setattr(_sess, "_session_path", lambda session_key, sessions_dir=None: shared)

        _sess.append_messages("agent:foo-lead:foo", [user("hello foo")])
        _sess.append_messages("agent:bar-lead:bar", [user("hello bar")])

        # With the planted drift, bar's append lands in foo's "session" too.
        foo = _sess.load_messages("agent:foo-lead:foo")
        assert [m.content for m in foo] == ["hello foo", "hello bar"]


# ── round-trip serialisation ─────────────────────────────────────────────────


class TestRoundTripSerialization:
    def test_plain_messages_round_trip(self) -> None:
        _sess.append_messages(
            "agent:x:default", [system("be helpful"), user("hi"), assistant("hello there")]
        )
        loaded = _sess.load_messages("agent:x:default")
        assert loaded == [system("be helpful"), user("hi"), assistant("hello there")]

    def test_tool_call_and_result_round_trip_losslessly(self) -> None:
        call = ToolCall(id="call_42", name="grep", arguments='{"pattern": "foo"}')
        turn = [assistant("checking...", tool_calls=[call]), tool_result(call, "3 matches")]
        _sess.append_messages("agent:x:default", turn)

        loaded = _sess.load_messages("agent:x:default")

        assert loaded == turn
        assistant_msg, tool_msg = loaded
        assert assistant_msg.tool_calls == [call]
        assert tool_msg.tool_call_id == "call_42"
        assert tool_msg.name == "grep"

    def test_multiple_tool_calls_on_one_assistant_message_round_trip(self) -> None:
        c1 = ToolCall(id="a", name="read", arguments="{}")
        c2 = ToolCall(id="b", name="write", arguments='{"path": "x"}')
        msg = assistant("", tool_calls=[c1, c2])
        _sess.append_messages("agent:x:default", [msg])

        loaded = _sess.load_messages("agent:x:default")
        assert loaded == [msg]
        assert [c.id for c in loaded[0].tool_calls] == ["a", "b"]

    def test_appends_accumulate_in_order(self) -> None:
        _sess.append_messages("agent:x:default", [user("one")])
        _sess.append_messages("agent:x:default", [assistant("two")])
        _sess.append_messages("agent:x:default", [user("three")])

        loaded = _sess.load_messages("agent:x:default")
        assert [m.content for m in loaded] == ["one", "two", "three"]


# ── measured usage (distinct from estimated tokens) ───────────────────────────


class TestMeasuredUsage:
    def test_usage_accumulates_additively_across_appends(self) -> None:
        _sess.append_messages(
            "agent:x:default", [user("hi")], usage=TokenUsage(input_tokens=10, output_tokens=5)
        )
        _sess.append_messages(
            "agent:x:default",
            [assistant("hello")],
            usage=TokenUsage(input_tokens=20, output_tokens=8, cached_tokens=4),
        )

        record = _sess.load_session("agent:x:default")
        assert record.usage.input_tokens == 30
        assert record.usage.output_tokens == 13
        assert record.usage.cached_tokens == 4
        assert record.usage.turns == 2

    def test_no_usage_argument_leaves_totals_unchanged(self) -> None:
        _sess.append_messages("agent:x:default", [user("hi")], usage=TokenUsage(input_tokens=10))
        _sess.append_messages("agent:x:default", [assistant("hello")])  # no usage

        record = _sess.load_session("agent:x:default")
        assert record.usage.input_tokens == 10
        assert record.usage.turns == 1

    def test_measured_usage_is_independent_of_estimated_token_size(self) -> None:
        """A tiny message can carry a huge *measured* usage figure (e.g. a
        large cached system prompt) -- the two numbers must never be derived
        from each other."""
        tiny_content = "hi"
        huge_usage = TokenUsage(input_tokens=200_000, output_tokens=100_000)
        _sess.append_messages("agent:x:default", [user(tiny_content)], usage=huge_usage)

        record = _sess.load_session("agent:x:default")
        from docket.core.context import estimate_tokens

        assert record.usage.input_tokens == 200_000
        assert estimate_tokens(tiny_content) < 10
        # Compaction planning must not be influenced by the measured figure --
        # a budget big enough for the *estimated* content, tiny compared to
        # the measured usage, still reports nothing to compact.
        plan = _sess.plan_compaction(_sess.load_messages("agent:x:default"), budget_tokens=1000)
        assert not plan.needed


# ── atomic grouping ───────────────────────────────────────────────────────────


class TestGroupAtomicUnits:
    def test_plain_messages_are_each_their_own_unit(self) -> None:
        msgs = [system("s"), user("u"), assistant("a")]
        assert _sess.group_atomic_units(msgs) == [[m] for m in msgs]

    def test_tool_call_and_its_result_group_together(self) -> None:
        turn = _tool_call_turn()
        groups = _sess.group_atomic_units(turn)
        assert groups == [turn]

    def test_multiple_tool_calls_group_with_all_their_results(self) -> None:
        c1 = ToolCall(id="a", name="read", arguments="{}")
        c2 = ToolCall(id="b", name="write", arguments="{}")
        asst = assistant("", tool_calls=[c1, c2])
        r1 = tool_result(c1, "res-a")
        r2 = tool_result(c2, "res-b")
        groups = _sess.group_atomic_units([asst, r1, r2])
        assert groups == [[asst, r1, r2]]

    def test_group_closes_once_matching_results_are_exhausted(self) -> None:
        """A later, unrelated message after a fully-answered tool call starts
        a new unit rather than being swept into the group."""
        turn = _tool_call_turn()
        tail = user("next question")
        groups = _sess.group_atomic_units([*turn, tail])
        assert groups == [turn, [tail]]

    def test_unanswered_tool_call_still_forms_its_own_unit(self) -> None:
        call = ToolCall(id="c1", name="read", arguments="{}")
        asst = assistant("", tool_calls=[call])
        groups = _sess.group_atomic_units([asst])
        assert groups == [[asst]]

    def test_preexisting_orphan_tool_message_is_its_own_unit(self) -> None:
        orphan = ChatMessage(role="tool", content="stray", tool_call_id="ghost", name="x")
        groups = _sess.group_atomic_units([user("hi"), orphan])
        assert groups == [[user("hi")], [orphan]]


class TestOrphanDetection:
    def test_no_orphans_in_a_well_formed_history(self) -> None:
        history = [user("q"), *_tool_call_turn(), assistant("done")]
        assert _sess.find_orphaned_tool_messages(history) == []
        assert _sess.find_unanswered_tool_calls(history) == []

    def test_detects_a_tool_message_with_no_preceding_call(self) -> None:
        orphan = ChatMessage(role="tool", content="x", tool_call_id="ghost", name="y")
        history = [user("q"), orphan]
        assert _sess.find_orphaned_tool_messages(history) == [1]

    def test_detects_an_unanswered_tool_call(self) -> None:
        call = ToolCall(id="c1", name="read", arguments="{}")
        history = [assistant("", tool_calls=[call])]
        assert _sess.find_unanswered_tool_calls(history) == ["c1"]

    def test_drift_planted_a_split_group_is_caught(self) -> None:
        """Guard evidence: manually split an atomic unit (the exact bug
        compaction must never introduce) and confirm the checker flags it
        both ways -- an orphaned result and, on the other half, an unanswered
        call."""
        turn = _tool_call_turn()
        assistant_only = [turn[0]]
        tool_only = [turn[1]]
        assert _sess.find_unanswered_tool_calls(assistant_only) == ["c1"]
        assert _sess.find_orphaned_tool_messages(tool_only) == [0]


# ── plan_compaction: budgeting + the atomicity boundary case ──────────────────


class TestPlanCompactionBasics:
    def test_fits_within_budget_is_a_no_op_plan(self) -> None:
        msgs = [system("s"), user("hi"), assistant("hello")]
        plan = _sess.plan_compaction(msgs, budget_tokens=100_000)
        assert not plan.needed
        assert plan.keep_head == [system("s")]
        assert plan.keep_tail == [user("hi"), assistant("hello")]

    def test_leading_system_messages_are_always_kept(self) -> None:
        msgs = [system("s1"), system("s2"), user("hi")]
        plan = _sess.plan_compaction(msgs, budget_tokens=1)
        assert plan.keep_head == [system("s1"), system("s2")]

    def test_at_least_the_most_recent_unit_survives_a_tiny_budget(self) -> None:
        msgs = [user("a" * 5000), user("final question")]
        plan = _sess.plan_compaction(msgs, budget_tokens=1)
        assert plan.keep_tail == [user("final question")]
        assert plan.to_summarize == [[user("a" * 5000)]]

    def test_no_messages_at_all(self) -> None:
        plan = _sess.plan_compaction([], budget_tokens=1000)
        assert plan.keep_head == []
        assert plan.to_summarize == []
        assert plan.keep_tail == []
        assert not plan.needed


class TestPlanCompactionAtomicityBoundary:
    """The card's named trap: a cut that would land inside a tool-call group."""

    def test_boundary_cut_never_splits_the_tool_call_group(self) -> None:
        from docket.core.context import estimate_tokens

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
            return estimate_tokens(_sess._render_message_for_estimate(msg))

        budget = _tok(m4) + _tok(m3) + _tok(m2)

        plan = _sess.plan_compaction(history, budget_tokens=budget)

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
        from docket.core.context import estimate_tokens

        call = ToolCall(id="c1", name="read_file", arguments="{}")
        m0 = user("padding " * 20)
        m1 = assistant("checking", tool_calls=[call])
        m2 = tool_result(call, "contents")
        m3 = user("q2")
        m4 = assistant("a2")
        _sess.append_messages("agent:x:default", [m0, m1, m2, m3, m4])

        def _tok(msg: ChatMessage) -> int:
            return estimate_tokens(_sess._render_message_for_estimate(msg))

        budget = _tok(m4) + _tok(m3) + _tok(m2)
        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_summarizing_driver(),
            budget_tokens=budget,
        )

        assert result.ok
        assert result.compacted
        final = _sess.load_messages("agent:x:default")
        assert _sess.find_orphaned_tool_messages(final) == []
        assert _sess.find_unanswered_tool_calls(final) == []
        # The tool call and its result are either both gone (folded into the
        # summary) or both present -- never one without the other.
        has_call = any(m.tool_calls for m in final)
        has_result = any(m.role == "tool" for m in final)
        assert has_call == has_result


# ── compact_session: fail-closed contract ─────────────────────────────────────


class TestCompactSessionFailClosed:
    def _seed_over_budget_session(self) -> None:
        _sess.append_messages(
            "agent:x:default", [user("a" * 2000), assistant("b" * 2000), user("final")]
        )

    def test_driver_failure_leaves_history_completely_untouched(self) -> None:
        self._seed_over_budget_session()
        before = _sess.load_messages("agent:x:default")

        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_failing_driver,
            budget_tokens=1,
        )

        assert not result.ok
        assert result.failure_kind == "timeout"
        assert _sess.load_messages("agent:x:default") == before

    def test_empty_summary_reply_leaves_history_completely_untouched(self) -> None:
        self._seed_over_budget_session()
        before = _sess.load_messages("agent:x:default")

        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_empty_reply_driver,
            budget_tokens=1,
        )

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert _sess.load_messages("agent:x:default") == before

    def test_drift_planted_bare_drop_on_failure_would_lose_history(self) -> None:
        """Guard evidence: a compactor that drops old units *before* checking
        the driver result (the regression this contract forbids) would lose
        data on a failing driver. Simulate that bug directly and show it
        would indeed produce a shorter history than the fail-closed
        implementation does."""
        self._seed_over_budget_session()
        messages = _sess.load_messages("agent:x:default")
        plan = _sess.plan_compaction(messages, budget_tokens=1)
        assert plan.needed  # there is something a buggy compactor could drop

        buggy_result_after_drop = [*plan.keep_head, *plan.keep_tail]
        assert len(buggy_result_after_drop) < len(messages)

        # The real implementation must not match the buggy behaviour above.
        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_failing_driver,
            budget_tokens=1,
        )
        assert not result.ok
        assert len(_sess.load_messages("agent:x:default")) == len(messages)


class TestCompactSessionSuccess:
    def test_no_compaction_needed_makes_no_driver_call(self) -> None:
        _sess.append_messages("agent:x:default", [user("hi")])
        driver, calls = _recording_driver()

        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=driver,
            budget_tokens=100_000,
        )

        assert result.ok
        assert not result.compacted
        assert calls == []

    def test_summarizer_uses_an_isolated_key(self) -> None:
        _sess.append_messages("agent:x:default", [user("old " * 200), user("keep me")])
        seen_keys: list[str] = []

        def _driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            seen_keys.append(session_key)
            return TurnResult(True, "summary", 0.0, {})

        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_driver,
            budget_tokens=1,
        )

        assert result.ok
        assert seen_keys == ["agent:x:default:compaction"]

    def test_nested_compaction_is_rejected_before_another_summarizer_call(self) -> None:
        _sess.append_messages("agent:x:default", [user("old " * 200), user("keep me")])
        nested: list[_sess.CompactionResult] = []
        calls = 0

        def _driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            nonlocal calls
            calls += 1
            nested.append(
                _sess.compact_session(
                    "agent:y:default",
                    role="lead",
                    agent_id="y-lead",
                    summarizer=_driver,
                    budget_tokens=1,
                )
            )
            return TurnResult(True, "summary", 0.0, {})

        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_driver,
            budget_tokens=1,
        )

        assert result.ok
        assert calls == 1
        assert len(nested) == 1
        assert not nested[0].ok
        assert nested[0].failure_kind == "invalid_output"

    def test_successful_compaction_replaces_old_units_with_a_summary(self) -> None:
        _sess.append_messages(
            "agent:x:default", [system("sys"), user("old stuff " * 50), user("keep me")]
        )
        result = _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_summarizing_driver("the gist of it"),
            budget_tokens=5,
        )

        assert result.ok
        assert result.compacted
        assert result.groups_summarized >= 1
        assert result.before_message_count == 3
        assert result.after_message_count <= result.before_message_count
        assert result.after_estimated_tokens < result.before_estimated_tokens

        final = _sess.load_messages("agent:x:default")
        assert final[0] == system("sys")  # leading system message survives verbatim
        assert any("the gist of it" in m.content for m in final)
        assert final[-1] == user("keep me")

    def test_large_history_uses_multiple_bounded_atomic_summary_rounds(self) -> None:
        key = "agent:large:default"
        real_system = system("immutable operator instruction")
        call = ToolCall(id="atomic", name="read", arguments='{"path":"fixture"}')
        messages = [real_system]
        for index in range(8):
            messages.append(user(f"old-{index} " * 30))
        messages.extend(
            [
                assistant("ATOMIC_CALL", tool_calls=[call]),
                tool_result(call, "ATOMIC_RESULT"),
                user("recent unit must remain"),
            ]
        )
        _sess.append_messages(key, messages)
        prompts: list[str] = []

        def _driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            prompts.append(message)
            return TurnResult(True, f"bounded round {len(prompts)}", 0.0, {})

        result = _sess.compact_session(
            key,
            role="lead",
            agent_id="large-lead",
            summarizer=_driver,
            budget_tokens=80,
            summary_input_budget_tokens=180,
        )

        assert result.ok
        assert result.compacted
        assert result.summary_rounds == len(prompts)
        assert result.summary_rounds > 1
        assert result.max_summary_prompt_estimated_tokens <= 180
        assert all(_sess._context.estimate_tokens(prompt) <= 180 for prompt in prompts)
        assert any("[compacted summary" in prompt for prompt in prompts[1:])
        assert all(("ATOMIC_CALL" in prompt) == ("ATOMIC_RESULT" in prompt) for prompt in prompts)
        final = _sess.load_messages(key)
        assert final[0] == real_system
        assert final[-1] == user("recent unit must remain")
        assert _sess._messages_estimated_tokens(final) < result.before_estimated_tokens
        assert _sess.find_orphaned_tool_messages(final) == []
        assert _sess.find_unanswered_tool_calls(final) == []

    def test_failure_in_a_later_round_writes_no_intermediate_candidate(self) -> None:
        key = "agent:late-failure:default"
        _sess.append_messages(key, [user(f"old-{index} " * 30) for index in range(10)])
        path = _sess._session_path(key, None)
        before = path.read_bytes()
        calls = 0

        def _driver(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> TurnResult:
            nonlocal calls
            calls += 1
            if calls == 2:
                return TurnResult(False, "", 0.0, {}, "later timeout", "timeout")
            return TurnResult(True, "first bounded summary", 0.0, {})

        result = _sess.compact_session(
            key,
            role="lead",
            agent_id="late-failure-lead",
            summarizer=_driver,
            budget_tokens=60,
            summary_input_budget_tokens=180,
        )

        assert not result.ok
        assert result.failure_kind == "timeout"
        assert calls == 2
        assert path.read_bytes() == before

    def test_one_oversized_atomic_unit_fails_closed_without_calling_summarizer(self) -> None:
        key = "agent:oversized:default"
        _sess.append_messages(key, [user("x" * 4000), user("recent")])
        path = _sess._session_path(key, None)
        before = path.read_bytes()
        driver, calls = _recording_driver()

        result = _sess.compact_session(
            key,
            role="lead",
            agent_id="oversized-lead",
            summarizer=driver,
            budget_tokens=10,
            summary_input_budget_tokens=150,
        )

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert calls == []
        assert path.read_bytes() == before

    def test_compaction_preserves_measured_usage_totals(self) -> None:
        _sess.append_messages(
            "agent:x:default",
            [user("old " * 200), user("keep me")],
            usage=TokenUsage(input_tokens=999, output_tokens=111),
        )
        _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_summarizing_driver(),
            budget_tokens=1,
        )
        record = _sess.load_session("agent:x:default")
        assert record.usage.input_tokens == 999
        assert record.usage.output_tokens == 111

    def test_summarizer_receives_the_content_being_replaced(self) -> None:
        _sess.append_messages(
            "agent:x:default", [user("very important old context"), user("keep me")]
        )
        driver, calls = _recording_driver()
        _sess.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=driver,
            budget_tokens=1,
        )
        assert calls
        assert "very important old context" in calls[0]

    def test_explicit_budget_overrides_role_resolution(self) -> None:
        """A role with no archetype entry still works when budget_tokens is given
        explicitly -- compact_session must not require a real role registry."""
        _sess.append_messages("agent:x:default", [user("a" * 4000), user("keep")])
        result = _sess.compact_session(
            "agent:x:default",
            role="not-a-real-role",
            agent_id="x-lead",
            summarizer=_summarizing_driver(),
            budget_tokens=1,
        )
        assert result.ok
        assert result.compacted
