"""Durable turn history + compaction (`agent/session.py`).

Covers session-key isolation, a round trip preserving `tool_calls`/
`tool_call_id`/`name`, an assistant `tool_calls` message never split from
its answering `tool` messages by a compaction cut, measured vs. estimated
token accounting, and fail-closed summarisation on a failing driver.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support.llm import summarizing_driver as _summarizing_driver
from tests.support.llm import tool_call_turn as _tool_call_turn

from docket.agent import context as _agent_context
from docket.agent import session as _sess
from docket.agent import session_compaction as _session_compaction
from docket.agent import session_units as _session_units
from docket.agent.llm import ChatMessage, TokenUsage, ToolCall, assistant, system, tool_result, user
from docket.agent.ports import TurnResult

_isolate_sessions_dir = _support_home.isolate_sessions_dir

SUBJECT = "docket.agent.session"

# ── driver test doubles (matches SessionSummaryRunner's 5-arg shape) ──────────


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


# ── helpers ──────────────────────────────────────────────────────────────────


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
        """Guard evidence: force every session into the *same* file (the bug this design prevents) and confirm the isolation assertion above would actually catch it -- i.e. this test is not vacuous."""
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

    def test_cache_writes_accumulate(self) -> None:
        _sess.append_messages(
            "agent:x:default", [user("hi")], usage=TokenUsage(input_tokens=10, cache_write_tokens=6)
        )
        record = _sess.append_messages(
            "agent:x:default", [], usage=TokenUsage(input_tokens=10, cache_write_tokens=2)
        )

        assert record.usage.cache_write_tokens == 8
        assert record.usage.model_dump(by_alias=True)["cacheWriteTokens"] == 8

    def test_no_usage_argument_leaves_totals_unchanged(self) -> None:
        _sess.append_messages("agent:x:default", [user("hi")], usage=TokenUsage(input_tokens=10))
        _sess.append_messages("agent:x:default", [assistant("hello")])  # no usage

        record = _sess.load_session("agent:x:default")
        assert record.usage.input_tokens == 10
        assert record.usage.turns == 1

    def test_measured_usage_is_independent_of_estimated_token_size(self) -> None:
        """A tiny message can carry a huge *measured* usage figure (e.g. a large cached system prompt) -- the two numbers must never be derived from each other."""
        tiny_content = "hi"
        huge_usage = TokenUsage(input_tokens=200_000, output_tokens=100_000)
        _sess.append_messages("agent:x:default", [user(tiny_content)], usage=huge_usage)

        record = _sess.load_session("agent:x:default")
        from docket.agent.context import estimate_tokens

        assert record.usage.input_tokens == 200_000
        assert estimate_tokens(tiny_content) < 10
        # Compaction planning must not be influenced by the measured figure --
        # a budget big enough for the *estimated* content, tiny compared to
        # the measured usage, still reports nothing to compact.
        plan = _session_units.plan_compaction(
            _sess.load_messages("agent:x:default"), budget_tokens=1000
        )
        assert not plan.needed


# ── compact_session: fail-closed contract ─────────────────────────────────────


class TestCompactSessionFailClosed:
    def _seed_over_budget_session(self) -> None:
        _sess.append_messages(
            "agent:x:default", [user("a" * 2000), assistant("b" * 2000), user("final")]
        )

    def test_driver_failure_leaves_history_completely_untouched(self) -> None:
        self._seed_over_budget_session()
        before = _sess.load_messages("agent:x:default")

        result = _session_compaction.compact_session(
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

        result = _session_compaction.compact_session(
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
        """Guard evidence: a compactor that drops old units *before* checking the driver result (the regression this contract forbids) would lose data on a failing driver. Simulate that bug directly and show it would indeed produce a shorter history than the fail-closed implementation does."""
        self._seed_over_budget_session()
        messages = _sess.load_messages("agent:x:default")
        plan = _session_units.plan_compaction(messages, budget_tokens=1)
        assert plan.needed  # there is something a buggy compactor could drop

        buggy_result_after_drop = [*plan.keep_head, *plan.keep_tail]
        assert len(buggy_result_after_drop) < len(messages)

        # The real implementation must not match the buggy behaviour above.
        result = _session_compaction.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_failing_driver,
            budget_tokens=1,
        )
        assert not result.ok
        assert len(_sess.load_messages("agent:x:default")) == len(messages)


class TestCompactSessionSuccess:
    def test_ranged_compaction_preserves_external_messages_verbatim(self) -> None:
        call = ToolCall(id="c-range", name="read", arguments='{"path":"large.txt"}')
        task = user("current task must remain exact")
        tool_unit = [assistant("", tool_calls=[call]), tool_result(call, "large " * 400)]
        final = assistant("later durable answer")
        _sess.append_messages("agent:x:default", [task, *tool_unit, final])

        result = _session_compaction.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_summarizing_driver("tool outcome retained"),
            budget_tokens=1,
            compact_range=(1, 3),
            keep_latest_unit=False,
        )

        assert result.ok and result.compacted
        stored = _sess.load_messages("agent:x:default")
        assert stored[0] == task
        assert stored[-1] == final
        assert stored[1].content.startswith("[compacted summary of ")
        assert not _session_units.find_orphaned_tool_messages(stored)
        assert not _session_units.find_unanswered_tool_calls(stored)

    def test_ranged_compaction_rejects_a_boundary_inside_tool_unit(self) -> None:
        task = user("task")
        tool_unit = _tool_call_turn()
        _sess.append_messages("agent:x:default", [task, *tool_unit])
        path = _sess._session_path("agent:x:default", None)
        before = path.read_bytes()

        result = _session_compaction.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=_summarizing_driver(),
            budget_tokens=1,
            compact_range=(2, 3),
            keep_latest_unit=False,
        )

        assert not result.ok
        assert "atomic" in result.error
        assert path.read_bytes() == before

    def test_no_compaction_needed_makes_no_driver_call(self) -> None:
        _sess.append_messages("agent:x:default", [user("hi")])
        driver, calls = _recording_driver()

        result = _session_compaction.compact_session(
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

        result = _session_compaction.compact_session(
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
        nested: list[_session_compaction.CompactionResult] = []
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
                _session_compaction.compact_session(
                    "agent:y:default",
                    role="lead",
                    agent_id="y-lead",
                    summarizer=_driver,
                    budget_tokens=1,
                )
            )
            return TurnResult(True, "summary", 0.0, {})

        result = _session_compaction.compact_session(
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
        result = _session_compaction.compact_session(
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

        result = _session_compaction.compact_session(
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
        assert all(_agent_context.estimate_tokens(prompt) <= 180 for prompt in prompts)
        assert any("[compacted summary" in prompt for prompt in prompts[1:])
        assert all(("ATOMIC_CALL" in prompt) == ("ATOMIC_RESULT" in prompt) for prompt in prompts)
        final = _sess.load_messages(key)
        assert final[0] == real_system
        assert final[-1] == user("recent unit must remain")
        assert _session_units._messages_estimated_tokens(final) < result.before_estimated_tokens
        assert _session_units.find_orphaned_tool_messages(final) == []
        assert _session_units.find_unanswered_tool_calls(final) == []

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

        result = _session_compaction.compact_session(
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

        result = _session_compaction.compact_session(
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
        _session_compaction.compact_session(
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
        _session_compaction.compact_session(
            "agent:x:default",
            role="lead",
            agent_id="x-lead",
            summarizer=driver,
            budget_tokens=1,
        )
        assert calls
        assert "very important old context" in calls[0]

    def test_explicit_budget_overrides_role_resolution(self) -> None:
        """A role with no archetype entry still works when budget_tokens is given explicitly -- compact_session must not require a real role registry."""
        _sess.append_messages("agent:x:default", [user("a" * 4000), user("keep")])
        result = _session_compaction.compact_session(
            "agent:x:default",
            role="not-a-real-role",
            agent_id="x-lead",
            summarizer=_summarizing_driver(),
            budget_tokens=1,
        )
        assert result.ok
        assert result.compacted


# ── request projection: condense_history ──────────────────────────────────────


def _read_exchange(n: int, body: str | None = None) -> list[ChatMessage]:
    call = ToolCall(id=f"c{n}", name="read", arguments=f'{{"path":"src/f{n}.py"}}')
    content = body if body is not None else "\n".join(f"{i}\tline {n}-{i}" for i in range(1, 41))
    return [assistant("", tool_calls=[call]), tool_result(call, content)]


def _history(count: int) -> list[ChatMessage]:
    out: list[ChatMessage] = [user("the task")]
    for n in range(count):
        out.extend(_read_exchange(n))
    return out


class TestCondenseHistory:
    """The built request names old tool results in one line; the stored history is untouched."""

    def test_keeps_k_whole_results_and_notices_for_the_rest(self) -> None:
        """Six read results with K=2 leave two whole and four one-line notices."""
        messages = _history(6)
        out = _sess.condense_history(messages, keep=2, budget=0)
        results = [m for m in out if m.role == "tool"]
        whole = [m for m in results if m.content.count("\n") > 5]
        notices = [m for m in results if m.content.startswith("[read src/f")]
        assert (len(whole), len(notices)) == (2, 4)
        assert [m.tool_call_id for m in results] == [f"c{n}" for n in range(6)]
        assert results[0].content == (
            "[read src/f0.py: 40 lines, 501 characters, already seen and omitted; "
            "call read again only for exact text you still need]"
        )
        assert all(m.content.count("\n") > 5 for m in results[-2:])

    def test_input_is_never_mutated_and_the_task_stays_whole(self) -> None:
        """The projection returns new messages; user messages and the input list stay as given."""
        messages = _history(5)
        before = list(messages)
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert messages == before
        assert out[0] == user("the task")

    def test_is_deterministic_and_prefix_stable_between_requests(self) -> None:
        """Two consecutive requests agree byte for byte up to the newly condensed message."""
        first = _sess.condense_history(_history(5), keep=2, budget=0)
        second = _sess.condense_history(_history(6), keep=2, budget=0)
        assert _sess.condense_history(_history(6), keep=2, budget=0) == second
        shared = next(i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b)
        assert first[:shared] == second[:shared]
        assert second[shared].role == "tool"
        assert second[shared].tool_call_id == "c3"

    def test_a_short_result_is_left_alone(self) -> None:
        """A result no longer than its notice is not rewritten."""
        messages = [user("t"), *_read_exchange(0, "ok"), *_read_exchange(1), *_read_exchange(2)]
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert out[2].content == "ok"
        assert out[4].content.startswith("[read src/f1.py")

    def test_errors_stay_short_and_whole(self) -> None:
        """A short error is kept verbatim and a long one keeps only its head."""
        short = "ERROR: not a file: src/f0.py"
        long = "ERROR: " + "x" * 3000
        messages = [
            user("t"),
            *_read_exchange(0, short),
            *_read_exchange(1, long),
            *_read_exchange(2),
        ]
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert out[2].content == short
        assert out[4].content.startswith("ERROR: xxx")
        assert len(out[4].content) < 600
        assert "more characters" in out[4].content

    def test_large_write_arguments_in_old_messages_become_a_count(self) -> None:
        """An old write keeps valid JSON arguments with the large string replaced."""
        body = "w" * 5000
        args = f'{{"path":"content/x.md","content":"{body}"}}'
        call = ToolCall(id="w1", name="write", arguments=args)
        messages = [
            user("t"),
            assistant("", tool_calls=[call]),
            tool_result(call, "wrote 5000 characters to content/x.md"),
            *_read_exchange(1),
            *_read_exchange(2),
        ]
        out = _sess.condense_history(messages, keep=2, budget=0)
        import json

        sent = json.loads(out[1].tool_calls[0].arguments)
        assert sent == {"path": "content/x.md", "content": "[wrote content/x.md: 5,000 characters]"}
        assert out[1].tool_calls[0].id == "w1"
        assert _sess.condense_history(messages, keep=3, budget=0)[1] == messages[1]

    def test_unparseable_arguments_are_left_untouched(self) -> None:
        """Arguments that are not a JSON object are never rewritten."""
        call = ToolCall(id="w1", name="write", arguments="{not json" + "x" * 900)
        messages = [
            user("t"),
            assistant("", tool_calls=[call]),
            tool_result(call, "r" * 900),
            *_read_exchange(1),
        ]
        assert _sess.condense_history(messages, keep=1, budget=0)[1] == messages[1]

    def test_small_results_stay_whole_within_the_budget(self) -> None:
        """Results that fit the character budget together are never condensed, whatever K is."""
        messages = _history(6)
        out = _sess.condense_history(messages, keep=1, budget=10_000)
        assert out == messages

    def test_the_budget_condenses_from_the_first_result_that_does_not_fit(self) -> None:
        """Newest first, results stay whole while they fit; that one and every older one go."""
        messages = _history(6)
        size = len(messages[-1].content)
        out = _sess.condense_history(messages, keep=1, budget=3 * size)
        results = [m for m in out if m.role == "tool"]
        assert [m.content.startswith("[read src/f") for m in results] == [True] * 3 + [False] * 3

    def test_a_condensed_result_stays_condensed_as_results_arrive(self) -> None:
        """Under the budget a result only moves from whole to notice, so the prefix stays stable."""
        size = len(_history(1)[-1].content)
        seen: set[str] = set()
        for count in range(1, 9):
            out = _sess.condense_history(_history(count), keep=2, budget=3 * size)
            condensed = {m.tool_call_id for m in out if m.role == "tool" and m.content[0] == "["}
            assert seen <= condensed
            seen = condensed
        assert seen


class TestCondenseHistoryBatches:
    """The cut moves in batches, so the request prefix survives the calls between boundaries."""

    def test_the_prefix_is_identical_between_batch_boundaries(self) -> None:
        """With 2,000-character results the prefix moves at five of twelve steps, not nine."""

        def grown(count: int) -> list[ChatMessage]:
            out: list[ChatMessage] = [user("the task")]
            for n in range(count):
                out.extend(_read_exchange(n, body=str(n).ljust(2_000, "x")))
            return out

        previous = _sess.condense_history(grown(1))
        boundaries = 0
        for count in range(2, 13):
            current = _sess.condense_history(grown(count))
            if current[: len(previous) - 2] != previous[:-2]:
                boundaries += 1
            previous = current
        assert boundaries == 5

    def test_the_low_water_mark_leaves_room_before_the_next_cut(self) -> None:
        """After a cut the whole results fit the low-water mark, so the next few arrivals add none."""
        size = 1_000

        def grown(count: int) -> list[ChatMessage]:
            out: list[ChatMessage] = [user("the task")]
            for n in range(count):
                out.extend(_read_exchange(n, body="y" * size))
            return out

        def condensed(count: int) -> int:
            out = _sess.condense_history(grown(count), keep=1)
            return sum(1 for m in out if m.role == "tool" and m.content.startswith("[read"))

        assert [condensed(n) for n in range(5, 12)] == [0, 0, 4, 4, 4, 4, 8]
