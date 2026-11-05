"""Recall of the shipped compaction prompt: a model's summary keeps the facts a later turn needs."""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest
from tests.support import home as _support_home

from docket.agent import session as _sess
from docket.agent.ports import ChatMessage, Endpoint, ToolCall, TurnResult, assistant, user
from docket.agent.session_compaction import compact_session
from docket.models.adapters.openai_http import OpenAIChatClient
from docket.teams.prompts import shipped_prompt

LANE = "context"
REASON = (
    "The summary's recall is a model behaviour no unit test can read: a section list that drops "
    "a decision, a fix, a file or an open item loses it for the next request."
)
RETIRE_WHEN = (
    "a recall figure is published per model and tracked by the bench, which then replaces "
    "this single-model check."
)

_ENDPOINT = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id="local")
_KEY = "agent:recall:default"


_isolate_sessions_dir = _support_home.isolate_sessions_dir


def _reachable() -> bool:
    try:
        urllib.request.urlopen(f"{_ENDPOINT.base_url}/models", timeout=3).close()
    except (urllib.error.URLError, OSError):
        return False
    return True


def _seeded_history() -> list[ChatMessage]:
    """Four facts in a long session: a decision, a failing command and its fix, a file, an open item."""
    run = ToolCall(id="c1", name="bash", arguments='{"command":"pytest tests/test_invoice.py"}')
    fix = ToolCall(id="c2", name="edit", arguments='{"path":"src/billing/rounding.py"}')
    return [
        user("Invoices are off by a cent. Find out why and fix it."),
        assistant(
            "Decision: we will round half-even with decimal, not float, because bank totals must match."
        ),
        assistant("", tool_calls=[run]),
        ChatMessage(
            role="tool",
            content="FAILED test_invoice.py::test_total - AssertionError: 10.01 != 10.00\nexit 1",
            tool_call_id="c1",
            name="bash",
        ),
        assistant("The failure is float rounding in the total.", tool_calls=[fix]),
        ChatMessage(
            role="tool",
            content="edited src/billing/rounding.py: total now uses Decimal.quantize",
            tool_call_id="c2",
            name="edit",
        ),
        assistant(
            "The test passes now. Still open: the monthly report in reports/monthly.py rounds the same way."
        ),
        user("Thanks. Pause here."),
    ]


@pytest.mark.skipif(not _reachable(), reason="no local model endpoint at 127.0.0.1:8081")
def test_the_summary_names_the_decision_the_fix_the_file_and_the_open_item() -> None:
    _sess.append_messages(_KEY, _seeded_history())
    client = OpenAIChatClient(_ENDPOINT)
    prompt = shipped_prompt("compaction", "history")

    def summarizer(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        reply = client.complete([user(message)], max_tokens=1_200, timeout=timeout)
        return TurnResult(reply.ok, reply.message.content, reply.raw, reply.error)

    result = compact_session(
        _KEY,
        role="implementer",
        agent_id="recall",
        summarizer=summarizer,
        prompt_text=prompt.text,
        prompt_sha256=prompt.sha256,
        budget_tokens=1,
        timeout=300,
    )

    assert result.ok and result.compacted, result.error
    summary = next(m.content for m in _sess.load_messages(_KEY) if "compacted summary" in m.content)
    lowered = summary.lower()
    assert "decimal" in lowered
    assert "float" in lowered and "10.01" in summary
    assert "src/billing/rounding.py" in summary
    assert "reports/monthly.py" in summary
