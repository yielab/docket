"""Escalation metrics: task counts, question outcomes, and decision latency.

Count dispatch task claims, operator questions and their outcomes, and the
latency from a question to its answer. All counts are lifetime-of-storage based
on persisted state (traces, task records), not monotonic totals: they reset
when trace files expire or task records are deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import docket.config as _cfg
from docket.core import audit as _audit
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
    - questions_total: count of answers by (kind, outcome) + approvals
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

            # Get the question from the task to find its createdAt
            question_rec = task.get("question")
            question_created: datetime | None = None
            if isinstance(question_rec, dict):
                created_str = question_rec.get("createdAt", "")
                if created_str:
                    try:
                        question_created = datetime.fromisoformat(
                            created_str.replace("Z", "+00:00")
                        )
                        if question_created.tzinfo is None:
                            question_created = question_created.replace(tzinfo=timezone.utc)
                    except (ValueError, AttributeError):
                        pass

            for answer_rec in task_answers:
                if not isinstance(answer_rec, dict):
                    continue
                answered_at_str = answer_rec.get("answeredAt", "")
                if not answered_at_str:
                    continue

                action = answer_rec.get("action", "pending")
                # Get kind from the question record if available
                kind = "clarification"  # default
                if isinstance(question_rec, dict):
                    kind = question_rec.get("kind", "clarification")

                key = (kind, action)
                questions[key] = questions.get(key, 0) + 1

                # Calculate latency if we have both timestamps
                if question_created:
                    try:
                        answered_at = datetime.fromisoformat(answered_at_str.replace("Z", "+00:00"))
                        if answered_at.tzinfo is None:
                            answered_at = answered_at.replace(tzinfo=timezone.utc)
                        delta = (answered_at - question_created).total_seconds()
                        if delta >= 0:  # Only count valid positive latencies
                            latency_sum += delta
                            latency_count += 1
                    except (ValueError, AttributeError):
                        pass

    # Add approval metrics as kind="approval"
    _add_approval_metrics(questions)

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
    """Count dispatch-sourced session_start trace events (dispatch task claims)."""
    import json as _json

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
                        # Count only dispatch-sourced claims, not harness-mode runs
                        payload = event.get("payload", {})
                        if isinstance(payload, str):
                            try:
                                payload = _json.loads(payload)
                            except (ValueError, TypeError):
                                continue
                        if payload.get("source") == "dispatch":
                            count += 1
            except (ValueError, OSError):
                # Ignore corrupted trace files
                pass

    return count


def _add_approval_metrics(questions: dict[tuple[str, str], int]) -> None:
    """Add approval resolutions to questions_total with kind='approval'."""
    # Map audit action to approval outcome
    action_to_outcome = {"approval_granted": "granted", "approval_denied": "denied"}

    for entry in _audit.read_audit():
        action = str(entry.get("action", ""))
        if action in action_to_outcome:
            outcome = action_to_outcome[action]
            key = ("approval", outcome)
            questions[key] = questions.get(key, 0) + 1
