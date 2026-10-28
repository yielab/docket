"""`GET /metrics` folds escalation counters and waits from the `escalation_*` trace events.

A real pod is parked at an `input` step by actually dispatching; the route is read over HTTP
before and after the answer, so the wait is the one the trace records. Nothing writes
`escalation_resolved` yet, so the answer step writes it the way the resolve step will.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

import pytest
from tests.support.http import metric_sample
from tests.support.pods import seed_parked_task

from docket.interfaces.http.routes import metrics
from docket.interfaces.http.server import _DocketHandler
from docket.kernel import clock as _clock
from docket.kernel.operator_contract import QuestionV11
from docket.kernel.threads import ContextHTTPServer
from docket.observability.trace import trace_event
from docket.platform import list_escalations
from docket.tasks.application import escalations as _escalations

SUBJECT = "docket.interfaces.http.routes.metrics"

_CONSULT = QuestionV11.model_validate(
    {
        "id": "q-1",
        "taskId": "t-9",
        "pod": "demo",
        "step": "implementer",
        "message": "Which store?",
        "requestedSchema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": [],
        },
        "createdAt": "2026-10-25T10:00:00Z",
        "kind": "decision",
        "options": [
            {"id": "redis", "label": "Redis", "description": "fast"},
            {"id": "sqlite", "label": "SQLite", "description": "simple"},
        ],
        "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
    }
)


class _Ahead:
    """The wall clock *seconds* ahead of the system's."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def now(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self._seconds)

    def monotonic(self) -> float:
        return time.monotonic()


def _offset(seconds: float) -> AbstractContextManager[object]:
    return _clock.use_clock(_Ahead(seconds))


@pytest.fixture()
def metrics_url() -> Iterator[str]:
    class _Handler(_DocketHandler):
        serve_token = "unused"

    server = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/metrics"
    server.shutdown()


def _scrape(url: str) -> list[str]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode().splitlines()


def test_a_parked_then_answered_task_is_counted_with_its_wait(metrics_url: str) -> None:
    parked = seed_parked_task()
    (escalation,) = list_escalations(state="pending")
    assert escalation.task == parked.id

    waiting = _scrape(metrics_url)
    assert not any(ln.startswith("docket_escalations_total{") for ln in waiting)
    assert not any(ln.startswith("docket_escalation_wait_seconds_") for ln in waiting)

    with _offset(90):
        _escalations.resolve(escalation.id, None, {"answer": "ship it"}, by="alice", channel="cli")

    answered = _scrape(metrics_url)
    assert (
        metric_sample(
            answered,
            'docket_escalations_total{kind="input",outcome="resolved",by="person",level="L3"}',
        )
        == 1
    )
    assert metric_sample(answered, 'docket_escalation_wait_seconds_count{kind="input"}') == 1
    assert 89 <= metric_sample(answered, 'docket_escalation_wait_seconds_sum{kind="input"}') < 120


def test_a_pod_decided_consult_is_counted_apart_from_a_human_one(metrics_url: str) -> None:
    seed_parked_task()
    _escalations.decided_consult(_CONSULT, role="implementer", option_id="sqlite")

    lines = _scrape(metrics_url)

    assert (
        metric_sample(
            lines,
            'docket_escalations_total{kind="consult",outcome="decided",by="policy",level="none"}',
        )
        == 1
    )
    assert not any('by="person"' in ln for ln in lines)


def test_the_old_question_metrics_are_gone_and_task_claims_stay(metrics_url: str) -> None:
    text = "\n".join(_scrape(metrics_url))

    assert "docket_questions_total" not in text
    assert "docket_decision_latency_seconds" not in text
    assert "docket_tasks_started_total" in text


def _traced(event_type: str, ts_offset_s: float, **payload: object) -> None:
    """Write *event_type* for a demo task with the clock *ts_offset_s* seconds ahead."""
    base: dict[str, object] = {
        "escalation": "esc-0123456789ab",
        "kind": "consult",
        "task": "t-1",
        "step": "s",
        "policy": "person",
        "askedAt": _clock.iso(),
    }
    with _offset(ts_offset_s):
        trace_event(
            "demo",
            "agent:demo:t-1",
            "lead",
            event_type,
            json.dumps({**base, **payload}),
        )


class TestFold:
    def test_each_settlement_counts_under_its_kind_outcome_and_who(self) -> None:
        _traced("escalation_resolved", 60, by="person")
        _traced("escalation_resolved", 60, by="person")
        _traced("escalation_expired", 3600, by="timeout")
        _traced("escalation_decided", 0, by="policy", policy="recommendation")
        _traced("escalation_resolved", 5, kind="approval", by="person")

        lines = metrics.render_metrics().splitlines()

        def total(kind: str, outcome: str, by: str) -> float:
            return metric_sample(
                lines,
                f'docket_escalations_total{{kind="{kind}",outcome="{outcome}",by="{by}",level="none"}}',
            )

        assert total("consult", "resolved", "person") == 2
        assert total("consult", "expired", "timeout") == 1
        assert total("consult", "decided", "policy") == 1
        assert total("approval", "resolved", "person") == 1

    def test_the_level_of_the_pause_is_a_label_and_a_missing_one_reads_none(self) -> None:
        _traced("escalation_decided", 0, by="policy", policy="deny", kind="approval", level="L5")
        _traced("escalation_decided", 0, by="policy", policy="deny", kind="approval", level="L5")
        _traced("escalation_resolved", 5, by="person", level="L3")
        _traced("escalation_resolved", 5, by="person")

        lines = metrics.render_metrics().splitlines()

        def total(kind: str, outcome: str, by: str, level: str) -> float:
            return metric_sample(
                lines,
                "docket_escalations_total{"
                f'kind="{kind}",outcome="{outcome}",by="{by}",level="{level}"' + "}",
            )

        assert total("approval", "decided", "policy", "L5") == 2
        assert total("consult", "resolved", "person", "L3") == 1
        assert total("consult", "resolved", "person", "none") == 1

    def test_the_wait_sums_every_settled_escalation_of_a_kind(self) -> None:
        _traced("escalation_resolved", 60, by="person")
        _traced("escalation_expired", 3600, by="timeout")

        lines = metrics.render_metrics().splitlines()

        assert metric_sample(lines, 'docket_escalation_wait_seconds_count{kind="consult"}') == 2
        wait = metric_sample(lines, 'docket_escalation_wait_seconds_sum{kind="consult"}')
        assert 3659 <= wait < 3700

    def test_a_settlement_dated_before_its_ask_adds_no_wait(self) -> None:
        _traced("escalation_resolved", -600, by="person")

        lines = metrics.render_metrics().splitlines()

        assert (
            metric_sample(
                lines,
                'docket_escalations_total{kind="consult",outcome="resolved",by="person",level="none"}',
            )
            == 1
        )
        assert not any(ln.startswith("docket_escalation_wait_seconds_") for ln in lines)

    def test_a_pause_that_was_only_asked_is_not_counted(self) -> None:
        _traced("escalation_asked", 0, prompt="q", options=["a"])
        _traced("escalation_delivered", 0, channel="ntfy")

        lines = metrics.render_metrics().splitlines()

        assert not any(ln.startswith("docket_escalations_total{") for ln in lines)

    def test_a_resumed_claim_is_not_a_new_start(self) -> None:
        for resumed in (False, True):
            trace_event(
                "demo",
                "agent:demo:t-1",
                "lead",
                "session_start",
                json.dumps({"source": "dispatch", "task": "t-1", "resumed": resumed}),
            )
        trace_event(
            "demo", "run-1", "lead", "session_start", json.dumps({"source": "cli", "task": "t-2"})
        )

        assert (
            metric_sample(metrics.render_metrics().splitlines(), "docket_tasks_started_total") == 1
        )
