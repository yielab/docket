"""Durable turn history + compaction (`agent/session_compaction.py`).

Covers the summarisation rounds over a history whose units are larger than the summary prompt:
the prompt-only projection of a unit that does not fit, a compaction summary never summarized
alone, and the typed refusal when the guard (not the summarizer) stops a compaction.
"""

from __future__ import annotations

import re

from tests.support import home as _support_home
from tests.support.llm import summarizing_driver as _summarizing_driver

from docket.agent import ports as _ports
from docket.agent import session as _sess
from docket.agent import session_compaction as _session_compaction
from docket.agent import session_units as _session_units
from docket.agent.ports import ChatMessage, ToolCall, TurnResult, assistant, tool_result, user

_isolate_sessions_dir = _support_home.isolate_sessions_dir

SUBJECT = "docket.agent.session_compaction"

_BUDGET = 6_000
_PROMPT = "MEMORY RULES for ${label}.\n${turns}\nReply with the sections only."
_PROMPT_SHA = "f" * 64
_KEY = "agent:reader:default"
_MARKER = re.compile(
    r"\[\.\.\. \d+ characters of this tool result not shown to the summarizer \.\.\.\]"
)


def _reading_unit(index: int, results: int, chars: int) -> list[ChatMessage]:
    """One assistant message with parallel ``fetch`` calls and their results, filler text only."""
    calls = [
        ToolCall(id=f"u{index}-c{n}", name="fetch", arguments='{"url":"page"}')
        for n in range(results)
    ]
    body = f"filler words for page {index} " * (chars // 24)
    return [
        assistant(f"UNIT-{index:02d} reading", tool_calls=calls),
        *(tool_result(call, body[:chars]) for call in calls),
    ]


def _reading_history() -> list[ChatMessage]:
    """13 atomic units; four of them hold 3-4 results worth 7,000-8,400 estimated tokens."""
    big = {5: (4, 7_000), 6: (4, 7_400), 7: (4, 7_800), 11: (3, 11_000)}
    messages: list[ChatMessage] = []
    for index in range(13):
        if index in big:
            results, chars = big[index]
            messages += _reading_unit(index, results, chars)
        elif index in (0, 4):
            messages.append(user(f"UNIT-{index:02d} ask " + "question text " * 500))
        else:
            messages += _reading_unit(index, 2, 2_000)
    return messages


def _recording_summarizer(tokens: int = 1_000) -> tuple[_sess.SessionSummaryRunner, list[str]]:
    prompts: list[str] = []

    def _driver(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        prompts.append(message)
        return TurnResult(True, "summary text " * (tokens * 4 // 13), {})

    return _driver, prompts


def _compact(
    summarizer: _sess.SessionSummaryRunner, **overrides: int
) -> _session_compaction.CompactionResult:
    return _session_compaction.compact_session(
        _KEY,
        role="writer",
        agent_id="reader",
        summarizer=summarizer,
        prompt_text=_PROMPT,
        prompt_sha256=_PROMPT_SHA,
        budget_tokens=overrides.get("budget_tokens", _BUDGET),
        summary_input_budget_tokens=overrides.get("summary_input_budget_tokens", _BUDGET),
    )


class TestAUnitLargerThanThePromptIsSummarizedFromAProjection:
    """The measured failure: a lone summary was summarized because the next unit did not fit."""

    def test_every_raw_unit_is_folded_and_no_prompt_is_a_summary_alone(self) -> None:
        history = _reading_history()
        assert (
            max(_session_units._unit_tokens(u) for u in _session_units.group_atomic_units(history))
            > _BUDGET
        )
        _sess.append_messages(_KEY, history)
        driver, prompts = _recording_summarizer()

        result = _compact(driver)

        assert result.ok, result.error
        assert result.compacted
        assert not result.refused_by_guard
        assert result.after_estimated_tokens < result.before_estimated_tokens
        assert result.max_summary_prompt_estimated_tokens <= _BUDGET
        assert all(_ports.estimate_tokens(p) <= _BUDGET for p in prompts)
        assert all(re.search(r"UNIT-\d\d", p) for p in prompts)
        assert any(_MARKER.search(p) for p in prompts)
        final = _sess.load_messages(_KEY)
        assert sum(m.content.startswith("[compacted summary of ") for m in final) == 1
        assert [m.content for m in final if "UNIT-" in m.content] == ["UNIT-12 reading"]
        assert _session_units.find_orphaned_tool_messages(final) == []
        assert _session_units.find_unanswered_tool_calls(final) == []

    def test_the_projection_is_in_the_prompt_only(self) -> None:
        history = _reading_history()
        _sess.append_messages(_KEY, history)
        driver, prompts = _recording_summarizer()

        _compact(driver)

        assert all(
            "not shown to the summarizer" not in m.content for m in _sess.load_messages(_KEY)
        )
        full = history[
            history.index(next(m for m in history if m.content == "UNIT-05 reading")) + 1
        ]
        assert full.content not in "\n".join(prompts)


class TestTheGuardRefusesWithoutWriting:
    """Requirement 26: nothing is written, and the refusal is typed apart from a summarizer failure."""

    def test_one_user_message_larger_than_the_prompt_is_refused_and_untouched(self) -> None:
        _sess.append_messages(_KEY, [user("x" * 40_000), user("recent")])
        path = _sess._session_path(_KEY, None)
        before = path.read_bytes()
        driver, prompts = _recording_summarizer()

        result = _compact(driver, budget_tokens=10, summary_input_budget_tokens=1_000)

        assert not result.ok
        assert result.refused_by_guard
        assert result.failure_kind == "invalid_output"
        assert prompts == []
        assert path.read_bytes() == before

    def test_a_summary_that_gains_nothing_is_refused_and_untouched(self) -> None:
        _sess.append_messages(_KEY, [user("old " * 600), user("recent")])
        path = _sess._session_path(_KEY, None)
        before = path.read_bytes()
        driver, _ = _recording_summarizer(tokens=2_000)

        result = _compact(driver, budget_tokens=10, summary_input_budget_tokens=1_000)

        assert not result.ok
        assert result.refused_by_guard
        assert "did not reduce" in result.error
        assert path.read_bytes() == before

    def test_a_summarizer_failure_is_not_a_guard_refusal(self) -> None:
        _sess.append_messages(_KEY, [user("old " * 600), user("recent")])

        def _failing(
            agent_id: str, session_key: str, message: str, timeout: int, env: object = None
        ) -> TurnResult:
            return TurnResult(False, "", {}, "boom", failure_kind="timeout")

        result = _compact(_failing, budget_tokens=10, summary_input_budget_tokens=1_000)

        assert not result.ok
        assert not result.refused_by_guard
        assert result.failure_kind == "timeout"

    def test_a_clean_compaction_is_not_a_refusal(self) -> None:
        _sess.append_messages(_KEY, [user("old " * 600), user("recent")])

        result = _compact(_summarizing_driver("short"), budget_tokens=10)

        assert result.ok and result.compacted and not result.refused_by_guard


def _padded_history() -> list[ChatMessage]:
    pad = "padding words " * 200
    return [user("UNIT-A ask " + pad), assistant("UNIT-B reply " + pad), user("UNIT-C ask")]


class TestThePromptIsTheCallersDocument:
    """The summarizer prompt is the caller's resolved text with both inputs substituted."""

    def test_it_starts_with_the_document_and_carries_the_rendered_units(self) -> None:
        _sess.append_messages(_KEY, _padded_history())
        driver, prompts = _recording_summarizer(tokens=20)

        result = _compact(driver, budget_tokens=50)

        assert result.compacted
        assert prompts[0].startswith(f"MEMORY RULES for {_KEY}.\n[user] UNIT-A ask")
        assert "[assistant] UNIT-B reply" in prompts[0]
        assert prompts[0].endswith("\nReply with the sections only.")
        assert "${" not in prompts[0]

    def test_the_result_reports_the_hash_of_the_prompt_it_ran(self) -> None:
        _sess.append_messages(_KEY, _padded_history())
        driver, _ = _recording_summarizer(tokens=20)

        assert _compact(driver, budget_tokens=50).prompt_sha256 == _PROMPT_SHA

    def test_the_input_budget_counts_the_documents_own_length(self) -> None:
        _sess.append_messages(_KEY, _padded_history())
        driver, prompts = _recording_summarizer()

        result = _session_compaction.compact_session(
            _KEY,
            role="writer",
            agent_id="reader",
            summarizer=driver,
            prompt_text="LONG RULES " * 2_000 + "${turns}",
            prompt_sha256=_PROMPT_SHA,
            budget_tokens=1,
            summary_input_budget_tokens=500,
        )

        assert not result.ok
        assert result.refused_by_guard
        assert prompts == []

    def test_a_prompt_that_never_places_the_turns_is_refused_before_any_call(self) -> None:
        _sess.append_messages(_KEY, _padded_history())
        before = _sess.load_messages(_KEY)
        driver, prompts = _recording_summarizer()

        result = _session_compaction.compact_session(
            _KEY,
            role="writer",
            agent_id="reader",
            summarizer=driver,
            prompt_text="Summarize the history.",
            prompt_sha256=_PROMPT_SHA,
            budget_tokens=1,
        )

        assert (result.ok, result.failure_kind) == (False, "invalid_output")
        assert "${turns}" in result.error
        assert prompts == []
        assert _sess.load_messages(_KEY) == before
