"""The ``escalation_*`` trace events: one payload for every way a task stops for a decision.

An approval, a consult, an ``input`` step, a gate and a changed check each wrote a different event
with a different payload. These five describe the same pause the same way, so a span, a metric or
a log reads them without knowing which kind it is. The payload is built from the escalation record
alone; the writers (the store's opener, the two expiry sweeps, a pod-decided consult) only say
which event.

A trace problem never breaks the pause it describes, so ``emit`` swallows every failure.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from docket.kernel.operator_contract import Escalation
from docket.kernel.ports import tracer as _tracer

__all__ = [
    "ASKED",
    "DECIDED",
    "DELIVERED",
    "EVENT_TYPES",
    "EXPIRED",
    "RESOLVED",
    "emit",
    "payload",
    "task_session",
]

ASKED = "escalation_asked"
DELIVERED = "escalation_delivered"
RESOLVED = "escalation_resolved"
EXPIRED = "escalation_expired"
DECIDED = "escalation_decided"

EVENT_TYPES: frozenset[str] = frozenset({ASKED, DELIVERED, RESOLVED, EXPIRED, DECIDED})

# Who settled the pause, as a class and never a name: a name is unbounded for a metric label and
# belongs in the audit log.
_BY: dict[str, str] = {RESOLVED: "person", EXPIRED: "timeout", DECIDED: "policy"}


def task_session(escalation: Escalation) -> str:
    """The trace session of *escalation*: its task's, else the pod's approval session."""
    if escalation.task:
        return f"agent:{escalation.pod}:{escalation.task}"
    return f"{escalation.pod}-approval"


def payload(
    event_type: str, escalation: Escalation, *, channel: str = "", option_id: str = ""
) -> dict[str, Any]:
    """The payload of *event_type* for *escalation*: the identifying fields every event carries,
    then what that event adds. *channel* and *option_id* default to the record's resolution."""
    body: dict[str, Any] = {
        "escalation": escalation.id,
        "kind": escalation.kind,
        "task": escalation.task,
        "step": escalation.step,
        "policy": escalation.policy,
        "askedAt": escalation.asked_at,
    }
    if escalation.level:
        body["level"] = escalation.level
    resolution = escalation.resolution
    if event_type == ASKED:
        body["causedBy"] = escalation.caused_by
        body["onExpiry"] = escalation.on_expiry
        if escalation.expires_at:
            body["expiresAt"] = escalation.expires_at
        body["options"] = [o.id for o in escalation.options]
        body["prompt"] = escalation.prompt
    if event_type in _BY:
        body["by"] = _BY[event_type]
        # The settling process is often not the asking one; its exporter sends the whole pause.
        body["prompt"] = escalation.prompt
    chosen = option_id or (resolution.option_id if resolution and resolution.option_id else "")
    if chosen and event_type in (RESOLVED, DECIDED):
        body["optionId"] = chosen
    via = channel or (resolution.channel if resolution and event_type == RESOLVED else "")
    if via and event_type in (DELIVERED, RESOLVED):
        body["channel"] = via
    return body


def emit(
    event_type: str,
    escalation: Escalation,
    *,
    channel: str = "",
    option_id: str = "",
    session_id: str = "",
) -> None:
    """Write *event_type* for *escalation* to the trace: the task's session unless *session_id*
    names another, the record's task as the event's task id, its role (``operator`` when it has
    none) as the agent role."""
    with contextlib.suppress(Exception):
        _tracer.trace_event(
            escalation.pod,
            session_id or task_session(escalation),
            escalation.role or "operator",
            event_type,
            json.dumps(payload(event_type, escalation, channel=channel, option_id=option_id)),
            task_id=escalation.task,
        )
