"""``teams.prompt_tests``: the tests file, a run against a model, and the record per hash."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec
from docket.teams import prompt_tests as pt

SUBJECT = "docket.teams.prompt_tests"


class _Model:
    """Answers each exchange with the next scripted response and keeps what it was asked."""

    def __init__(self, *responses: ChatResponse) -> None:
        self._responses = list(responses)
        self.tools: list[list[str]] = []
        self.sent: list[list[ChatMessage]] = []

    def complete(
        self, messages: list[ChatMessage], *, tools: list[ToolSpec] = (), **_kw: object
    ) -> ChatResponse:  # type: ignore[assignment]
        self.sent.append(list(messages))
        self.tools.append([t.name for t in tools])
        return self._responses.pop(0)


def _say(text: str, *calls: str, out: int = 0) -> ChatResponse:
    message = ChatMessage(
        role="assistant",
        content=text,
        tool_calls=[ToolCall(id=f"c{i}", name=n, arguments="{}") for i, n in enumerate(calls)],
    )
    return ChatResponse(ok=True, message=message, usage=TokenUsage(output_tokens=out))


def _tests(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "p.tests.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_FULL = """
cases:
  - name: approves
    input: "diff: ok"
    assert:
      - contains: APPROVE
      - calledHandoff: true
      - underTokens: 50
"""


def test_a_tests_file_parses_into_cases_and_assertions(tmp_path: Path) -> None:
    (case,) = pt.load_cases(_tests(tmp_path, _FULL))

    assert (case.name, case.input) == ("approves", "diff: ok")
    assert [a.kind for a in case.assertions] == ["contains", "calledHandoff", "underTokens"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("cases: []", "non-empty list"),
        ("cases:\n  - input: x\n    assert: []", "non-empty list"),
        (
            "cases:\n  - input: x\n    assert:\n      - startsWith: a",
            "unknown assertion 'startsWith'",
        ),
        ("cases:\n  - input: x\n    assert:\n      - underTokens: -1", "wrong type"),
        ("cases:\n  - name: n\n    assert:\n      - contains: a", "`input` string"),
    ],
)
def test_a_bad_tests_file_is_refused_naming_the_file(
    tmp_path: Path, body: str, message: str
) -> None:
    path = _tests(tmp_path, body)

    with pytest.raises(pt.PromptTestsError, match=message) as raised:
        pt.load_cases(path)

    assert str(path) in str(raised.value)


def test_a_reply_that_meets_every_assertion_passes_and_a_handoff_tool_is_offered(
    tmp_path: Path,
) -> None:
    model = _Model(_say("APPROVE, looks fine", "handoff", out=10))

    outcome = pt.run_cases(
        "You review.", pt.load_cases(_tests(tmp_path, _FULL)), model, handoff=True
    )

    assert (outcome.result, outcome.cases, outcome.failed) == ("pass", 1, ())
    assert model.tools == [["handoff"]]
    assert [m.role for m in model.sent[0]] == ["system", "user"]


def test_a_model_that_never_calls_handoff_fails_the_case(tmp_path: Path) -> None:
    model = _Model(_say("APPROVE", out=10))

    outcome = pt.run_cases("You review.", pt.load_cases(_tests(tmp_path, _FULL)), model)

    assert (outcome.result, outcome.failed) == ("fail", ("approves",))
    assert model.tools == [[]]
    assert "calledHandoff is False" in outcome.lines[0]


def test_under_tokens_reads_the_reported_output_and_estimates_when_none_is_reported(
    tmp_path: Path,
) -> None:
    body = "cases:\n  - input: x\n    assert:\n      - underTokens: 5\n"
    cases = pt.load_cases(_tests(tmp_path, body))

    assert pt.run_cases("s", cases, _Model(_say("a", out=4))).result == "pass"
    assert pt.run_cases("s", cases, _Model(_say("a", out=9))).result == "fail"
    assert pt.run_cases("s", cases, _Model(_say("x" * 400))).result == "fail"


def test_matches_schema_checks_the_reply_as_json(tmp_path: Path) -> None:
    body = (
        "cases:\n  - input: x\n    assert:\n      - matchesSchema:\n"
        "          type: object\n          required: [verdict]\n"
        "          properties:\n            verdict: {enum: [APPROVE, REQUEST-CHANGES]}\n"
    )
    cases = pt.load_cases(_tests(tmp_path, body))

    assert pt.run_cases("s", cases, _Model(_say('{"verdict": "APPROVE"}'))).result == "pass"
    assert pt.run_cases("s", cases, _Model(_say('{"verdict": "MAYBE"}'))).result == "fail"
    assert pt.run_cases("s", cases, _Model(_say("{}"))).result == "fail"
    assert pt.run_cases("s", cases, _Model(_say("not json"))).result == "fail"


def test_a_failed_model_call_fails_the_case(tmp_path: Path) -> None:
    body = "cases:\n  - input: x\n    assert:\n      - contains: a\n"
    model = _Model(ChatResponse(ok=False, error="HTTP 500"))

    outcome = pt.run_cases("s", pt.load_cases(_tests(tmp_path, body)), model)

    assert outcome.result == "fail"
    assert "HTTP 500" in outcome.lines[0]


def test_a_record_is_kept_per_model_and_hash() -> None:
    assert pt.recorded("local/m", "abc") is None

    pt.record("local/m", "abc", "hop/reviewer", pt.PromptTestResult("fail", 2, ("a",)))
    pt.record("local/m", "def", "hop/reviewer", pt.PromptTestResult("pass", 2, ()))

    assert pt.recorded("local/m", "abc") == {
        "prompt": "hop/reviewer",
        "result": "fail",
        "cases": 2,
        "failed": ["a"],
    }
    assert pt.recorded("local/m", "def") is not None
    assert pt.recorded("other/m", "abc") is None
