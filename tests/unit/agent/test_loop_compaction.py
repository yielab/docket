"""Turn-loop compaction (`agent/loop_compaction.py`): the tool-free summariser's refusals and
the request-fit helpers around the incoming task message."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

from docket.agent.loop_budget import TurnBudget
from docket.agent.loop_compaction import TurnCompaction
from docket.agent.loop_state import TurnState
from docket.agent.loop_types import LoopConfig
from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    ToolCall,
    assistant,
    role_composer_port,
    system,
    tool_result,
    user,
)
from docket.agent.session import _session_path, append_messages, load_messages
from docket.kernel.home import current_home
from docket.teams.role_composer import TeamsRoleComposer

SUBJECT = "docket.agent.loop_compaction"

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

MakeState = Callable[..., TurnState]


class _OneReply:
    """Answers the summariser's single exchange with a fixed response."""

    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> ChatResponse:
        self.calls.append({"messages": messages, **kwargs})
        return self.response


class _Replies:
    """Answers each exchange with the next scripted response."""

    def __init__(self, *responses: ChatResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> ChatResponse:
        self.calls.append({"messages": messages, **kwargs})
        return self.responses.pop(0)


def _compaction(state: TurnState) -> TurnCompaction:
    return TurnCompaction(state, TurnBudget(state))


def _summarize(compaction: TurnCompaction, key: str = "agent:demo-agent:demo:compaction"):
    return compaction.summarize_without_reentry("demo-agent", key, "summarise", 30)


class TestSummarizeWithoutReentry:
    """One tool-free exchange; every rejection records why compaction stopped the turn."""

    def test_a_summary_key_equal_to_the_target_session_is_refused(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state()
        compaction = _compaction(state)
        result = _summarize(compaction, key=state.session_key)
        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert compaction.compaction_failure_stop_reason == "compaction_failed"

    def test_an_exhausted_wall_clock_is_refused_before_any_call(
        self, make_turn_state: MakeState
    ) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("summary")))
        state = make_turn_state(
            LoopConfig(wall_clock_timeout_s=10), backend=backend, clock=lambda: 11.0
        )
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.failure_kind == "timeout"
        assert backend.calls == []
        assert compaction.compaction_failure_stop_reason == "compaction_failed"

    def test_a_good_summary_is_returned_and_its_usage_is_kept_apart(
        self, make_turn_state: MakeState
    ) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("the summary")))
        state = make_turn_state(backend=backend)
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.ok
        assert result.output == "the summary"
        assert backend.calls[0]["tools"] == ()
        assert compaction.compaction_failure_stop_reason is None
        assert state.total_usage.total_tokens == 0

    def test_a_tool_requesting_summary_is_rejected(self, make_turn_state: MakeState) -> None:
        reply = assistant("x", [ToolCall(id="c", name="echo")])
        state = make_turn_state(backend=_OneReply(ChatResponse(ok=True, message=reply)))
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert not result.ok
        assert "requested tools" in result.error
        assert compaction.compaction_failure_stop_reason == "compaction_failed"

    def test_an_empty_summary_is_rejected(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(backend=_OneReply(ChatResponse(ok=True, message=assistant("   "))))
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert "empty summary" in result.error

    def test_a_truncated_summary_is_rejected(self, make_turn_state: MakeState) -> None:
        response = ChatResponse(ok=True, message=assistant("cut"), finish_reason="length")
        state = make_turn_state(backend=_OneReply(response))
        result = _summarize(_compaction(state))
        assert "truncated" in result.error

    def test_a_cancelled_run_never_calls_the_backend(self, make_turn_state: MakeState) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("summary")))
        base = make_turn_state()
        state = make_turn_state(
            backend=backend, ctx=dataclasses.replace(base.ctx, cancellation_check=lambda: True)
        )
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.failure_kind == "run_cancelled"
        assert backend.calls == []
        assert compaction.compaction_failure_stop_reason == "run_cancelled"


class TestRequestFitHelpers:
    """The durable position of the task message and the request built around it."""

    def test_messages_for_durable_prepends_the_system_prompt(
        self, make_turn_state: MakeState
    ) -> None:
        compaction = _compaction(make_turn_state(system_prompt="you are an agent"))
        messages = compaction.messages_for_durable([user("hello")])
        assert [m.role for m in messages] == ["system", "user"]
        assert messages[0] == system("you are an agent")

    def test_messages_for_durable_omits_an_empty_system_prompt(
        self, make_turn_state: MakeState
    ) -> None:
        compaction = _compaction(make_turn_state(system_prompt=""))
        assert [m.role for m in compaction.messages_for_durable([user("hello")])] == ["user"]

    def test_seed_task_message_records_its_durable_position(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state()
        append_messages(state.session_key, [user("earlier"), assistant("reply")])
        compaction = _compaction(state)
        compaction.seed_task_message("the task")
        assert compaction.task_message_index == 2
        assert load_messages(state.session_key)[2] == compaction.incoming == user("the task")

    def test_convergence_error_names_the_window_or_says_unknown(
        self, make_turn_state: MakeState
    ) -> None:
        known = _compaction(make_turn_state(context_window=1_000, output_reserve=100))
        error = known.context_fit_convergence_error("no luck", 400)
        assert "estimated request 500 tokens (input 400 + output reserve 100)" in error
        assert error.endswith("registered context window 1000: no luck")
        unknown = _compaction(make_turn_state(context_window=None))
        assert "registered context window unknown" in unknown.context_fit_convergence_error("x", 1)


class TestASummaryRequestIsRetried:
    """The summary request goes through the same retrying send as the task request."""

    def test_a_timeout_then_a_summary_compacts(self, make_turn_state: MakeState) -> None:
        backend = _Replies(
            ChatResponse(ok=False, error="slow", failure_kind="timeout"),
            ChatResponse(ok=True, message=assistant("the summary")),
        )
        sleeps: list[float] = []
        state = make_turn_state(
            LoopConfig(request_timeout_s=30, request_retries=1),
            backend=backend,
            sleep=sleeps.append,
        )
        result = _summarize(_compaction(state))
        assert result.ok and result.output == "the summary"
        assert len(backend.calls) == 2 and sleeps == [2.0]
        assert state.request_retries == 1

    def test_a_summary_cut_to_the_clock_left_that_times_out_ends_the_turn_on_time(
        self, make_turn_state: MakeState
    ) -> None:
        backend = _Replies(ChatResponse(ok=False, error="slow", failure_kind="timeout"))
        state = make_turn_state(
            LoopConfig(wall_clock_timeout_s=100, request_timeout_s=30, request_retries=2),
            backend=backend,
            clock=lambda: 80.0,
        )
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.failure_kind == "timeout" and len(backend.calls) == 1
        assert backend.calls[0]["timeout"] == 20
        assert compaction.compaction_failure_stop_reason == "timeout"


class TestTurnStartCompactionUsesTheHistoryBudget:
    """A session of 21,000 tokens fits a 25,000-token history budget and not the role's 8,000."""

    @staticmethod
    def _session(state: TurnState) -> None:
        for n in range(6):
            append_messages(state.session_key, [user(f"ask {n} " + "x" * 14_000), assistant("ok")])

    def test_a_wide_history_budget_leaves_the_session_alone(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(history_budget_tokens=25_000))
        self._session(state)
        before = load_messages(state.session_key)

        assert _compaction(state).apply_initial_history_compaction() is None
        assert load_messages(state.session_key) == before

    def test_the_role_budget_compacts_it(self, make_turn_state: MakeState) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("the summary")))
        state = make_turn_state(LoopConfig(history_budget_tokens=8_000), backend=backend)
        self._session(state)
        before = load_messages(state.session_key)

        assert _compaction(state).apply_initial_history_compaction() is None
        assert len(backend.calls) >= 1
        assert len(load_messages(state.session_key)) < len(before)


class TestTheRequestProjectionFollowsTheWindow:
    """Answered results stay whole while the request fits the window, and condense when not."""

    @staticmethod
    def _results(count: int) -> list[ChatMessage]:
        out: list[ChatMessage] = [user("the task")]
        for n in range(count):
            call = ToolCall(id=f"c{n}", name="read", arguments=f'{{"path":"f{n}"}}')
            out += [assistant("", tool_calls=[call]), tool_result(call, "x" * 2_000)]
        return out

    @staticmethod
    def _condensed(messages: list[ChatMessage]) -> int:
        return sum(1 for m in messages if m.role == "tool" and m.content[0] == "[")

    def test_a_wide_window_keeps_older_results_whole(self, make_turn_state: MakeState) -> None:
        durable = self._results(6)
        wide = _compaction(make_turn_state(context_window=1_000_000, output_reserve=8_000))

        assert wide.messages_for_durable(durable) == durable

    def test_the_history_share_does_not_widen_it(self, make_turn_state: MakeState) -> None:
        durable = self._results(6)
        state = make_turn_state(LoopConfig(history_budget_tokens=250_000))

        assert self._condensed(_compaction(state).messages_for_durable(durable)) > 0

    def test_a_window_the_results_overflow_condenses_them(self, make_turn_state: MakeState) -> None:
        durable = self._results(6)
        narrow = _compaction(make_turn_state(context_window=4_000, output_reserve=1_000))

        assert self._condensed(narrow.messages_for_durable(durable)) > 0

    def test_an_unknown_window_projects_with_the_default_budget(
        self, make_turn_state: MakeState
    ) -> None:
        kept = _compaction(make_turn_state(context_window=None)).messages_for_durable(
            self._results(6)
        )
        assert self._condensed(kept) > 0

    def test_the_system_prompt_and_tools_take_their_room_first(
        self, make_turn_state: MakeState
    ) -> None:
        durable = self._results(12)
        free = _compaction(make_turn_state(context_window=9_000, output_reserve=500))
        crowded = _compaction(
            make_turn_state(context_window=9_000, output_reserve=500, system_prompt="s" * 16_000)
        )

        assert self._condensed(free.messages_for_durable(durable)) < self._condensed(
            crowded.messages_for_durable(durable)
        )


class TestAResearchTurnOnAWideWindow:
    """A ten-iteration research turn replayed iteration by iteration through the projection."""

    SHAPE = json.loads(
        (_FIXTURES / "research-turn" / "v1" / "shape.json").read_text(encoding="utf-8")
    )

    @classmethod
    def _requests(cls, make_turn_state: MakeState, **state: Any) -> list[list[ChatMessage]]:
        """The projected request at each iteration: the rounds so far, the newest unanswered."""
        compaction = _compaction(make_turn_state(**state))
        durable: list[ChatMessage] = [user(cls.SHAPE["task"])]
        out: list[list[ChatMessage]] = []
        for n, rnd in enumerate(cls.SHAPE["rounds"]):
            calls = [
                ToolCall(
                    id=f"r{n}c{k}",
                    name="fetch",
                    arguments=f'{{"url":"https://example.test/{n}/{k}"}}',
                )
                for k, _ in enumerate(rnd["fetch_result_chars"])
            ]
            durable.append(assistant(f"round {n}", tool_calls=calls))
            durable += [
                tool_result(call, f"page {n}.{k} " + "filler " * (size // 7))
                for k, (call, size) in enumerate(zip(calls, rnd["fetch_result_chars"], strict=True))
            ]
            out.append(compaction.messages_for_durable(durable))
        return out

    def test_a_million_token_window_condenses_nothing_and_keeps_the_prefix(
        self, make_turn_state: MakeState
    ) -> None:
        requests = self._requests(make_turn_state, context_window=1_000_000, output_reserve=8_192)

        for before, after in pairwise(requests):
            assert after[: len(before)] == before
        assert all(m.content[0] != "[" for m in requests[-1] if m.role == "tool")

    def test_a_32k_window_condenses_and_moves_the_prefix_in_few_batches(
        self, make_turn_state: MakeState
    ) -> None:
        requests = self._requests(make_turn_state, context_window=32_768, output_reserve=4_096)

        last = requests[-1]
        assert any(m.role == "tool" and m.content[0] == "[" for m in last)
        assert all(m.content[0] != "[" for m in last[-3:] if m.role == "tool")
        moved = sum(after[: len(before)] != before for before, after in pairwise(requests))
        assert 1 <= moved <= 3


class TestAPreTurnCompactionTheGuardRefuses:
    """A compaction that gains nothing leaves the history alone and lets the turn run."""

    @staticmethod
    def _session(state: TurnState) -> None:
        for n in range(3):
            append_messages(state.session_key, [user(f"ask {n} " + "x" * 6_000), assistant("ok")])

    @staticmethod
    def _events(state: TurnState) -> list[dict[str, Any]]:
        trace = current_home().traces_dir / state.project / f"{state.trace_key}.jsonl"
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        return [r["payload"] for r in records if r["event_type"] == "session_compaction"]

    def test_a_summary_that_gains_nothing_does_not_end_the_turn(
        self, make_turn_state: MakeState
    ) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("S" * 40_000)))
        state = make_turn_state(LoopConfig(history_budget_tokens=1_000), backend=backend)
        self._session(state)
        path = _session_path(state.session_key, None)
        before = path.read_bytes()

        assert _compaction(state).apply_initial_history_compaction() is None

        assert len(backend.calls) == 1
        assert path.read_bytes() == before
        [event] = self._events(state)
        assert event["status"] == "failed"
        assert "did not reduce" in event["reason"]

    def test_a_summarizer_timeout_still_ends_the_turn(self, make_turn_state: MakeState) -> None:
        response = ChatResponse(ok=False, error="slow", failure_kind="timeout")
        state = make_turn_state(
            LoopConfig(history_budget_tokens=1_000), backend=_OneReply(response)
        )
        self._session(state)
        before = load_messages(state.session_key)

        result = _compaction(state).apply_initial_history_compaction()

        assert result is not None and not result.ok
        assert result.stop_reason == "compaction_failed"
        assert load_messages(state.session_key) == before
        assert self._events(state)[0]["status"] == "failed"


class _OverlayComposer(TeamsRoleComposer):
    """The real composer except for the compaction prompt, which it answers with a fixed one."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def compaction_prompt(self, role: str, project: str) -> tuple[str, str]:
        self.asked.append((role, project))
        return "FROM THE PORT\n${turns}", "ab" * 32


class TestRunCompactionAsksThePortForThePrompt:
    """The summarizer prompt is whatever the role composer resolves for this role and pod."""

    def test_the_prompt_text_and_hash_come_from_the_port(self, make_turn_state: MakeState) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("the summary")))
        state = make_turn_state(backend=backend)
        append_messages(
            state.session_key,
            [user("first ask " + "detail " * 200), assistant("reply " * 200), user("second")],
        )
        composer = _OverlayComposer()

        with role_composer_port.use(composer):
            result, stop = _compaction(state).run_compaction(budget_tokens=1)

        assert result.compacted, result.error
        assert stop is None
        assert composer.asked == [("implementer", "demo")]
        sent = backend.calls[0]["messages"][0].content
        assert sent.startswith("FROM THE PORT\n[user] first ask")
        assert result.prompt_sha256 == "ab" * 32
