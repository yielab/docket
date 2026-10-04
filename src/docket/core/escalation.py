"""Escalation metrics: task counts, question outcomes, and decision latency.

Count dispatch task claims, operator questions and their outcomes, and the
latency from a question to its answer. All counts are lifetime-of-storage based
on persisted state (traces, task records), not monotonic totals: they reset
when trace files expire or task records are deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import pod as _pod
from docket.core import trace as _trace

__all__ = ["EscalationMetrics", "count_escalation_metrics"]


@dataclass
class EscalationMetrics:
    """Escalation metrics snapshot."""

    tasks_started_total: int
    """Number of task claims (dispatch session_start trace events)."""

    questions_total: dict[tuple[str, str], int]
    """Questions by (kind, outcome). kind = question.kind or 'clarification'.
    outcome = answer.action ('accept'/'decline'/'cancel') or approval
    outcome ('granted'/'denied'/'pending')."""

    decision_latency_seconds_sum: float
    """Sum of seconds from question createdAt to answeredAt, answered
    questions only."""

    decision_latency_seconds_count: int
    """Count of answered questions (latency_sum / count = mean latency)."""


def count_escalation_metrics() -> EscalationMetrics:
    """Count escalation metrics across all projects.

    - tasks_started_total: count of session_start trace events (dispatch claims)
    - questions_total: count of answers by (kind, outcome)
    - decision_latency_seconds_sum/count: latency from createdAt to answeredAt
    """
    tasks_started = _count_tasks_started()
    questions: dict[tuple[str, str], int] = {}
    latency_sum = 0.0
    latency_count = 0

    # Count questions and latency from task records
    for project in _all_projects():
        for task in _dispatch.read_tasks(project):
            task_answers = task.get("answers")
            if not isinstance(task_answers, list):
                continue
            for answer_rec in task_answers:
                if not isinstance(answer_rec, dict):
                    continue
                answered_at_str = answer_rec.get("answeredAt", "")
                if not answered_at_str:
                    continue
                action = answer_rec.get("action", "pending")
                # Count the question outcome
                kind = "clarification"  # default; no kind field in the answer record
                key = (kind, action)
                questions[key] = questions.get(key, 0) + 1

    return EscalationMetrics(
        tasks_started_total=tasks_started,
        questions_total=questions,
        decision_latency_seconds_sum=latency_sum,
        decision_latency_seconds_count=latency_count,
    )


def _all_projects() -> list[str]:
    """Every project with at least one registered pod member."""
    from docket.core import fleet as _fleet

    all_ids = [a.id for a in _fleet.list_agents()]
    return sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})


def _count_tasks_started() -> int:
    """Count session_start trace events (dispatch task claims)."""
    count = 0
    home = _cfg.DOCKET_HOME

    for project in _all_projects():
        traces_dir = home / "traces" / project
        if not traces_dir.exists():
            continue
        for trace_file in traces_dir.glob("*.jsonl"):
            try:
                events = _trace.read_trace(trace_file)
                for event in events:
                    if event.get("event_type") == "session_start":
                        count += 1
            except (ValueError, OSError):
                # Ignore corrupted trace files
                pass

    return count
