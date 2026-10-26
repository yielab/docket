"""Approval tokens for tests that drive a pause the way a person's surface does.

No surface takes a token any more: a person names the escalation. A test that creates or inspects
an approval record by its token reaches the escalation behind it through these two functions.
"""

from __future__ import annotations

from docket.governance import approval as _approval
from docket.kernel.operator_contract import Escalation, new_escalation_id
from docket.platform import list_escalations
from docket.tasks.application import escalations as _escalations
from docket.tasks.domain.resolution import EscalationNotFound


def escalation_record(**fields: object) -> Escalation:
    """A pending `approval` escalation record of task-1 in pod demo, *fields* overriding the base."""
    base: dict[str, object] = {
        "id": new_escalation_id(),
        "task": "task-1",
        "pod": "demo",
        "step": "implementer",
        "role": "implementer",
        "kind": "approval",
        "causedBy": "call-1",
        "prompt": "run rm",
        "askedAt": "2026-10-25T10:00:00+00:00",
        "onExpiry": "deny",
    }
    return Escalation.model_validate({**base, **fields})


def escalation_of(token: str) -> str:
    """The id of the escalation the approval record *token* backs."""
    found = next((e for e, t in _approval.approvals_of().items() if t == token), None)
    if found is None:
        raise EscalationNotFound(f"no escalation backs approval {token!r}")
    return found


def pending_token(project: str = "", task_id: str = "") -> str:
    """The token of the approval behind the newest pending escalation of *project* (and *task_id*
    when given); ``""`` when there is none."""
    tokens = _approval.approvals_of()
    for e in reversed(list_escalations(state="pending")):
        if (
            (not project or e.pod == project)
            and (not task_id or e.task == task_id)
            and e.id in tokens
        ):
            return tokens[e.id]
    return ""


def resolve_token(
    token: str, option: str, *, channel: str = "cli", actor: str = "", reason: str = ""
) -> str:
    """Resolve the escalation behind approval *token* with *option*; the note a refused task-wide
    grant produces."""
    return _escalations.resolve(
        escalation_of(token),
        option,
        {"reason": reason} if reason else None,
        by=actor,
        channel=channel,
    ).note


def answer_question(
    project: str,
    task_id: str,
    action: str,
    content: dict[str, object] | None = None,
    *,
    actor: str = "op",
    channel: str = "cli",
) -> None:
    """Answer the question *task_id* is parked on as a person's surface does: `decline` declines
    it, anything else accepts it with *content*. The claim of the task applies the answer."""
    (pending,) = [
        e
        for e in list_escalations(state="pending")
        if (e.pod, e.task) == (project, task_id) and e.kind in ("consult", "input")
    ]
    if action == "decline":
        _escalations.resolve(pending.id, "decline", None, by=actor, channel=channel)
        return
    body = dict(content or {})
    option = body.pop("optionId", None)
    _escalations.resolve(pending.id, option, body or None, by=actor, channel=channel)
