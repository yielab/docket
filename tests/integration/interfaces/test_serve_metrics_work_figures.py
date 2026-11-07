"""`GET /metrics` says whether the work goes well: six figures by pod and role, with their samples."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.support.http import metric_sample
from tests.support.pods import seed_pod

from docket.governance import approval as _approval
from docket.governance.audit import audit_log
from docket.interfaces.http.routes import metrics
from docket.kernel import clock as _clock
from docket.kernel.handoff import HandoffArtifact
from docket.kernel.home import current_home
from docket.observability.trace import trace_event
from docket.tasks.application import queue as _queue
from docket.tasks.application.accepted import terminal_task_outcomes
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import HopResult, TaskRecord

SUBJECT = "docket.interfaces.http.routes.metrics"

NAMES = (
    "docket_task_success_ratio",
    "docket_rework_cycles_per_task",
    "docket_reviewer_rejection_ratio",
    "docket_human_denials_per_100_asks",
    "docket_asks_per_100_calls",
    "docket_asks_granted_share",
)


def _hop(role: str, verdict: str | None = None) -> HopResult:
    artifact = HandoffArtifact(summary="s", verdict=verdict)
    return HopResult(role=role, ok=True, output="o", artifact=artifact)


def _settle(project: str, status: Status, hops: list[HopResult]) -> None:
    queued, _ = _queue.enqueue_task_once(project, f"goal {len(hops)} {status}", channel="cli")

    def _fn(task: TaskRecord) -> None:
        task.status = status
        task.completed_at = _clock.iso()
        task.hops = hops

    assert TaskRepository.for_pod(project).update(queued.id, _fn) is not None


def _seed_tasks(project: str) -> None:
    _settle(project, Status.done, [_hop("implementer"), _hop("reviewer", "approve")])
    _settle(
        project, Status.done, [_hop("reviewer", "request-changes"), _hop("reviewer", "approve")]
    )
    _settle(project, Status.failed, [_hop("implementer")])


def _seed_traces(project: str) -> None:
    d = current_home().traces_dir / project
    d.mkdir(parents=True)
    session = f"agent:{project}:t1".replace(":", "-")
    trace_event(project, session, "lead", "session_start", json.dumps({"source": "dispatch"}))
    trace_event(project, session, "reviewer", "rework_started", json.dumps({"cycle": 1}))
    for decision in ["allow"] * 8 + ["ask"] * 2:
        trace_event(
            project, session, "implementer", "tool_result", json.dumps({"decision": decision})
        )


def _seed_asks(project: str) -> None:
    detail = (
        f"tool=bash agent=a role=implementer project={project} policy_id='' policy_action='': x"
    )
    for _ in range(4):
        audit_log("tool.ask", detail)
    for channel, action in (("cli", "grant"), ("http", "deny"), ("timeout", "deny")):
        token = _approval.approval_create(project, "implementer", "run bash")
        audit_log(f"approval.{action}", f"token={token} project={project} channel={channel}")


def _lines() -> list[str]:
    return metrics.render_metrics().splitlines()


def _figure(lines: list[str], name: str) -> float:
    return metric_sample(lines, name + '{pod="demo",role="implementer"} ')


def test_metrics_lists_the_six_names_once_each_with_their_samples(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        _seed_tasks("demo")
        _seed_traces("demo")
        _seed_asks("demo")

        lines = _lines()

    for name in NAMES:
        assert len([ln for ln in lines if ln.startswith("# TYPE " + name + " ")]) == 1
    assert metric_sample(lines, 'docket_task_success_ratio{pod="demo",role="reviewer"} ') == 1.0
    assert metric_sample(lines, 'docket_task_success_ratio{pod="demo",role="implementer"} ') == 0.0
    assert (
        metric_sample(lines, 'docket_reviewer_rejection_ratio{pod="demo",role="reviewer"} ')
        == 1 / 3
    )
    assert metric_sample(lines, 'docket_rework_cycles_per_task{pod="demo",role="reviewer"} ') == 1.0
    assert _figure(lines, "docket_asks_per_100_calls") == 40.0
    assert _figure(lines, "docket_human_denials_per_100_asks") == 25.0
    assert _figure(lines, "docket_asks_granted_share") == 0.25
    samples = (
        'docket_figure_samples{figure="human_denials_per_100_asks",pod="demo",role="implementer"} '
    )
    assert metric_sample(lines, samples) == 4


def test_a_rotation_of_the_audit_log_does_not_change_a_figure(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        _seed_asks("demo")
        before = _lines()

        logf = current_home().audit_log
        os.replace(logf, str(logf) + ".1")
        audit_log("keys.add", "unrelated")
        after = _lines()

    for name in ("docket_human_denials_per_100_asks", "docket_asks_granted_share"):
        assert _figure(after, name) == _figure(before, name)


def test_terminal_task_outcomes_name_the_last_role_and_the_verdicts(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        _seed_tasks("demo")

        outcomes = terminal_task_outcomes()

    assert sorted((o.role, o.done) for o in outcomes) == [
        ("implementer", False),
        ("reviewer", True),
        ("reviewer", True),
    ]
    assert sorted(v for o in outcomes for v in o.verdicts) == [
        ("reviewer", "approve"),
        ("reviewer", "approve"),
        ("reviewer", "request-changes"),
    ]
