"""The shape of every identifier docket mints, and the durable key a task step runs under.

The prefix tells a reader what an id names (``apr-`` an approval token, ``task-`` a queued task),
and callers and tests match on it, so the shape lives here rather than at each call site.
Secrets that must stay unpredictable (serve token, wire challenge) are not ids and are not here.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote as _url_quote


def new_uuid() -> str:
    """A bare random uuid4, for values that carry no prefix."""
    return str(uuid.uuid4())


def new_id(prefix: str) -> str:
    """``<prefix>-<uuid4>`` -- an id that is stored and must never collide."""
    return f"{prefix}-{uuid.uuid4()}"


def new_short_id(prefix: str) -> str:
    """``<prefix>-<12 hex chars>`` -- an id a person types or a container is named after."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def step_session_key(member_id: str, project: str, task_id: str, step_id: str) -> str:
    """Collision-free durable-history key (member + globally-unique step id) so repeated
    roles and parallel children never replay each other's raw turns.
    """
    member = _url_quote(member_id, safe="")
    project_part = _url_quote(project, safe="")
    task = _url_quote(task_id, safe="")
    step = _url_quote(step_id, safe="")
    return f"agent:{member}:{project_part}:task:{task}:step:{step}"
