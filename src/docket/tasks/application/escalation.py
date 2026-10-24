"""Escalation metrics: task counts, question outcomes, and decision latency.

Count dispatch task claims, operator questions and their outcomes, and the
latency from a question to its answer. All counts are lifetime-of-storage based
on persisted state (traces, task records), not monotonic totals: they reset
when trace files expire or task records are deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.operator_contract import QuestionV11
from docket.observability import trace as _trace
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

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
    """Count escalation metrics across all projects (see ``EscalationMetrics`` for each
    field's source)."""
    tasks_started = _count_tasks_started()
    questions: dict[tuple[str, str], int] = {}
    latency_sum = 0.0
    latency_count = 0

    # Count questions and latency from task records
    for project in _all_projects():
        for task in TaskRepository.for_pod(project).list():
            if not task.answers:
                continue

            # An answered question is gone from the task; its answer keeps the kind and
            # createdAt. A record without them falls back to a question still on the task.
            question = task.question
            question_kind = question.kind if isinstance(question, QuestionV11) else "clarification"
            question_created_at = question.created_at if question is not None else ""

            for answer in task.answers:
                if not answer.answered_at:
                    continue

                key = (answer.kind or question_kind, answer.action)
                questions[key] = questions.get(key, 0) + 1

                created_str = answer.created_at or question_created_at
                question_created = _clock.parse_iso(created_str) if created_str else None
                if question_created:
                    answered_at = _clock.parse_iso(answer.answered_at)
                    if answered_at is not None:
                        delta = (answered_at - question_created).total_seconds()
                        if delta >= 0:  # Only count valid positive latencies
                            latency_sum += delta
                            latency_count += 1

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

    all_ids = [a.id for a in _fleet.list_agents()]
    return sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})


def _count_tasks_started() -> int:
    """Count dispatch-sourced session_start trace events (dispatch task claims)."""
    import json as _json

    count = 0
    for project in _all_projects():
        traces_dir = current_home().traces_dir / project
        if not traces_dir.exists():
            continue
        for trace_file in traces_dir.glob("*.jsonl"):
            try:
                events = _trace.read_trace(trace_file)
                for event in events:
                    if event.get("event_type") == "session_start":
                        # Count only dispatch-sourced claims
                        payload = event.get("payload", {})
                        if isinstance(payload, str):
                            try:
                                payload = _json.loads(payload)
                            except (ValueError, TypeError):
                                continue
                        # A resumed task writes a second session_start; it is not a new claim.
                        if payload.get("source") == "dispatch" and not payload.get("resumed"):
                            count += 1
            except (ValueError, OSError):
                # Ignore corrupted trace files
                pass

    return count


def _add_approval_metrics(questions: dict[tuple[str, str], int]) -> None:
    """Add approvals to questions_total with kind='approval': resolutions from the audit log's
    ``approval.grant``/``approval.deny`` entries, plus the ones still pending."""

    outcomes = {"approval.grant": "granted", "approval.deny": "denied"}
    for entry in _audit.read_audit():
        outcome = outcomes.get(str(entry.get("action", "")))
        if outcome:
            questions[("approval", outcome)] = questions.get(("approval", outcome), 0) + 1
    pending = len(_approval.list_pending())
    if pending:
        questions[("approval", "pending")] = questions.get(("approval", "pending"), 0) + pending
