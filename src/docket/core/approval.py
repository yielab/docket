"""Durable pending-approval store for HITL gating.

Records persist to ``$APPROVALS_DIR/<token>.json`` (atomic, 0600) with the
shape ``{token, project, role, action, state, created}``. The CLI ``approve`` /
``deny`` commands transition pending → granted / denied.

Approval records are docket-owned artefacts (not openclaw config), so writes
go through the ``edges/store.py`` single-writer chokepoint (D-12) rather than
the ACL.
Trace emission and secret redaction are best-effort and isolated behind the thin
``_emit_trace`` / ``_redact`` hooks so tests can stub them.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.edges import store as _store


class ApprovalError(Exception):
    """Raised for invalid approval transitions or missing tokens."""


class ApprovalNoop(Exception):
    """Raised when a transition is a benign no-op (already in target state)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _redact(text: str) -> str:
    """Best-effort secret redaction via the trace/redact port.

    A redaction failure must never break approval, so on any error the original
    text is returned unchanged. Local import avoids an import cycle with trace.
    """
    try:
        from docket.core import trace as _trace

        return _trace.redact(text)
    except Exception:
        return text


def _emit_trace(
    project: str,
    session: str,
    role: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort trace hook → docket.core.trace.trace_event.

    Any failure is swallowed so a trace problem never breaks the approval.
    Local import avoids a cycle.
    """
    try:
        from docket.core import trace as _trace

        _trace.trace_event(project, session, role, event_type, json.dumps(payload))
    except Exception:
        return None


def _approval_path(token: str) -> Path:
    return _cfg.APPROVALS_DIR / f"{token}.json"


def _utc_now() -> str:
    """Return current UTC time as YYYY-MM-DDTHH:MM:SSZ."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(token: str) -> dict[str, Any]:
    path = _approval_path(token)
    if not path.is_file():
        raise ApprovalError(f"Approval not found: {token}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _set_state(token: str, new_state: str) -> dict[str, Any]:
    data = _read(token)
    data["state"] = new_state
    _store.write_json(_approval_path(token), data)
    return data


def approval_create(project: str, role: str, action: str) -> str:
    """Persist a pending approval and return its token."""
    if not project or not role or not action:
        raise ApprovalError("approval_create: missing arguments")

    _cfg.APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_cfg.APPROVALS_DIR, 0o700)

    token = f"apr-{uuid.uuid4()}"
    created = _utc_now()
    redacted_action = _redact(action)

    data: dict[str, Any] = {
        "token": token,
        "project": project,
        "role": role,
        "action": redacted_action,
        "state": "pending",
        "created": created,
    }
    _store.write_json(_approval_path(token), data)

    _emit_trace(
        project,
        f"{project}-approval-{os.getpid()}",
        role,
        "approval_requested",
        {"token": token, "action": redacted_action},
    )
    return token


def approval_get(token: str) -> dict[str, Any]:
    """Return the approval record, raising ApprovalError if missing."""
    if not token:
        raise ApprovalError("approval_get: token required")
    return _read(token)


def approval_grant(token: str) -> None:
    """Transition pending → granted.

    Raises ApprovalNoop if already granted, ApprovalError on any other state.
    """
    data = _read(token)
    state = str(data.get("state", ""))
    if state == "granted":
        raise ApprovalNoop(f"Already granted: {token}")
    if state != "pending":
        raise ApprovalError(f"Cannot grant approval in state '{state}': {token}")

    _set_state(token, "granted")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"
    _emit_trace(project, f"{project}-approval", role, "approval_granted", {"token": token})


def approval_deny(token: str) -> None:
    """Transition pending → denied.

    Raises ApprovalNoop if already denied/expired, ApprovalError on any other state.
    """
    data = _read(token)
    state = str(data.get("state", ""))
    if state in ("denied", "expired"):
        raise ApprovalNoop(f"Already {state}: {token}")
    if state != "pending":
        raise ApprovalError(f"Cannot deny approval in state '{state}': {token}")

    _set_state(token, "denied")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"
    _emit_trace(project, f"{project}-approval", role, "approval_denied", {"token": token})


def list_pending() -> list[dict[str, Any]]:
    """Return every pending approval record in filename order.

    Records that fail to parse are skipped.
    """
    if not _cfg.APPROVALS_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(_cfg.APPROVALS_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception:
            continue
        if data.get("state") == "pending":
            out.append(data)
    return out


def approval_sweep_expired() -> int:
    """Expire pending approvals older than APPROVAL_TIMEOUT (treated as denied).

    Returns the number of records flipped to "expired". Called by the serve loop.
    """
    if not _cfg.APPROVALS_DIR.is_dir():
        return 0
    now = _dt.datetime.now(_dt.UTC).timestamp()
    timeout = _cfg.APPROVAL_TIMEOUT
    swept = 0
    for path in _cfg.APPROVALS_DIR.glob("*.json"):
        try:
            with path.open(encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception:
            continue
        if data.get("state") != "pending":
            continue
        created_str = str(data.get("created", ""))
        if not created_str:
            continue
        try:
            dt = _dt.datetime.strptime(created_str[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=_dt.UTC
            )
        except ValueError:
            continue
        if (now - dt.timestamp()) > timeout:
            data["state"] = "expired"
            _store.write_json(path, data)
            swept += 1
    return swept
