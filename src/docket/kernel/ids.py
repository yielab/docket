"""The shape of every identifier docket mints.

The prefix tells a reader what an id names (``apr-`` an approval token, ``task-`` a queued task),
and callers and tests match on it, so the shape lives here rather than at each call site.
Secrets that must stay unpredictable (serve token, wire challenge) are not ids and are not here.
"""

from __future__ import annotations

import uuid


def new_uuid() -> str:
    """A bare random uuid4, for values that carry no prefix."""
    return str(uuid.uuid4())


def new_id(prefix: str) -> str:
    """``<prefix>-<uuid4>`` -- an id that is stored and must never collide."""
    return f"{prefix}-{uuid.uuid4()}"


def new_short_id(prefix: str) -> str:
    """``<prefix>-<12 hex chars>`` -- an id a person types or a container is named after."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
