"""Durable pending-approval store for HITL gating.

Records persist to ``$APPROVALS_DIR/<token>.json`` (atomic, 0600) with the
shape ``{token, project, role, action, state, created, context}``. The CLI
``approve`` / ``deny`` commands transition pending → granted / denied.
``context`` is an optional, caller-supplied dict stored verbatim (``{}`` when
omitted) — the seam that lets a consumer created elsewhere (today:
``core/dispatch.py``'s require_approval gate) find what a token gated once
it's resolved; see ``approval_create``.

Approval records are docket-owned artefacts, so writes go through the
``edges/store.py`` single-writer chokepoint.
Trace emission and secret redaction are best-effort and isolated behind the thin
``_emit_trace`` / ``_redact`` hooks so tests can stub them. Grant/deny also write
an ``audit_log()`` entry (action ``approval.grant``/``approval.deny``) tagged
with the calling channel so ``docket audit`` has a record of who approved what
and through which surface. The recognised channel vocabulary is the closed set
in ``APPROVAL_CHANNELS`` below (``cli``, ``http``, ``mcp``, ``telegram``,
``timeout``, ``tack``) — core owns this list precisely so a caller (e.g.
``serve.py``'s ``POST /approvals/<token>``) can reject an arbitrary
caller-supplied string before it ever reaches the hash-chained audit log,
rather than trusting free text into a record whose whole value is honest
provenance.

The expiry sweep (``approval_sweep_expired``) resolves a stale pending record
to **denied** (fail-closed) rather than a read-by-nobody ``"expired"`` state,
and best-effort notifies ``core/dispatch.py`` so a task waiting on that token
is actually failed, not left stranded in ``waiting_approval`` forever.

``wait_for_approval`` is a second, *synchronous* consumer of this store for
``core/tools.py``'s in-turn gate. Unlike the async producer above —
which creates a token and returns immediately, leaving the task
``waiting_approval`` for some later call to resolve — an in-turn tool call has
nowhere to go while it waits, so this function blocks the calling thread
instead. It shares the same fail-closed timeout contract as
``approval_sweep_expired`` (denied, never left pending) via the private
``_resolve_timeout_as_denied`` helper both now call, and uses its own,
shorter ``config.TOOL_APPROVAL_TIMEOUT`` — see config.py for why the two
timeouts differ.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import time as _time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import docket.config as _cfg
from docket.core.audit import audit_log
from docket.edges import store as _store

# The closed set of channels a grant/deny may be tagged with in the audit log
# (see the module docstring). ``timeout`` is the fail-closed expiry path
# (``_resolve_timeout_as_denied``), never a human-driven caller. Callers that
# accept a channel from outside the process (``serve.py``'s
# ``POST /approvals/<token>``) MUST validate against this set rather than
# passing an arbitrary string through to ``approval_grant``/``approval_deny``.
APPROVAL_CHANNELS: frozenset[str] = frozenset({"cli", "http", "mcp", "telegram", "timeout", "tack"})


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
    """Conditionally make one pending record terminal under the store lock.

    The caller must use the returned record for all follow-on side effects.
    Reading first and then writing later lets two human decisions both observe
    ``pending`` and both report success; keeping the state check inside
    ``read_modify_write`` makes one decision the sole transition winner.
    """
    path = _approval_path(token)

    def transition(data: dict[str, Any]) -> dict[str, Any]:
        # ``read_modify_write`` represents a missing file as ``{}``; preserve
        # approval_get's public missing-token error instead of treating it as
        # an invalid, empty approval record.
        if not path.is_file():
            raise ApprovalError(f"Approval not found: {token}")

        state = str(data.get("state", ""))
        if new_state == "granted":
            if state == "granted":
                raise ApprovalNoop(f"Already granted: {token}")
            if state != "pending":
                raise ApprovalError(f"Cannot grant approval in state '{state}': {token}")
        elif new_state == "denied":
            if state in ("denied", "expired"):
                raise ApprovalNoop(f"Already {state}: {token}")
            if state != "pending":
                raise ApprovalError(f"Cannot deny approval in state '{state}': {token}")
        else:  # private callers only use the two terminal states above.
            raise ApprovalError(f"Unknown approval state: {new_state}")

        data["state"] = new_state
        return data

    return _store.read_modify_write(path, transition)


def approval_create(
    project: str, role: str, action: str, *, context: dict[str, Any] | None = None
) -> str:
    """Persist a pending approval and return its token.

    *context* is optional, caller-supplied structured data stored on the
    record verbatim (never redacted — callers must not put secrets in it), so
    whatever eventually resolves the grant/deny can find what it gated. The
    only documented consumer today is ``core/dispatch.py``'s require_approval
    gate, which stores ``{"taskId": ..., "pipelineIndex": ...}`` — see
    ``core/dispatch.py``'s ``resolve_waiting_approval``. Always persisted
    (``{}`` when omitted) so every record has the same shape.
    """
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
        "context": context or {},
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


def approval_grant(token: str, channel: str = "unknown") -> None:
    """Transition pending → granted.

    ``channel`` identifies the surface the grant came through (``"cli"``,
    ``"http"``, ``"telegram"``, ...) and is recorded in the audit log alongside
    the existing trace event.

    Raises ApprovalNoop if already granted, ApprovalError on any other state.
    """
    data = _set_state(token, "granted")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"
    _emit_trace(project, f"{project}-approval", role, "approval_granted", {"token": token})
    audit_log("approval.grant", f"token={token} project={project} channel={channel}")


def approval_deny(token: str, channel: str = "unknown") -> None:
    """Transition pending → denied.

    ``channel`` identifies the surface the denial came through (``"cli"``,
    ``"http"``, ``"telegram"``, ...) and is recorded in the audit log alongside
    the existing trace event.

    Raises ApprovalNoop if already denied/expired, ApprovalError on any other state.
    """
    data = _set_state(token, "denied")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"
    _emit_trace(project, f"{project}-approval", role, "approval_denied", {"token": token})
    audit_log("approval.deny", f"token={token} project={project} channel={channel}")


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


def _resolve_timeout_as_denied(token: str) -> bool:
    """Fail-closed timeout resolution shared by the sweep and the in-turn waiter.

    Conditionally transitions a pending record to **denied**. Returns ``True``
    only for the transition winner, which alone writes the matching
    ``approval.deny`` / ``channel=timeout`` audit entry and notifies
    ``core/dispatch.py``. A grant, deny, expiry, or deletion that wins first is
    a harmless ``False`` outcome rather than a stale timeout overwrite.
    """
    try:
        data = _set_state(token, "denied")
    except (ApprovalError, ApprovalNoop):
        return False
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"
    _emit_trace(project, f"{project}-approval", role, "approval_denied", {"token": token})
    audit_log("approval.deny", f"token={token} project={project} channel=timeout")
    with contextlib.suppress(Exception):
        from docket.core import dispatch as _dispatch

        _dispatch.resolve_waiting_approval(token, "denied")
    return True


def approval_sweep_expired() -> int:
    """Expire pending approvals older than APPROVAL_TIMEOUT — resolved as
    **denied** (fail-closed), not a read-by-nobody ``"expired"``
    state. Returns the number of records swept. Called by the serve loop.

    Each swept record is treated exactly like an explicit ``docket deny`` via
    ``_resolve_timeout_as_denied`` — see that helper for what it writes.
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
            token = str(data.get("token", ""))
            if token and _resolve_timeout_as_denied(token):
                swept += 1
    return swept


@dataclass(frozen=True)
class ApprovalWaitResult:
    """Outcome of blocking on one token until it resolves or times out.

    ``state`` is always a final state (never ``"pending"`` — by the time this
    returns, the wait is over). ``timed_out`` distinguishes an explicit deny
    from a fail-closed expiry, which is useful for the message handed back to
    the model and for a human reading ``docket audit`` afterwards.
    """

    state: Literal["granted", "denied"]
    token: str
    timed_out: bool = False
    cancelled: bool = False


def wait_for_approval(
    token: str,
    *,
    timeout: float | None = None,
    poll_interval: float | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    cancellation_check: Callable[[], bool] | None = None,
) -> ApprovalWaitResult:
    """Block the calling thread on *token* until it resolves, then fail closed.

    Unlike ``core/dispatch.py``'s require_approval gate — which creates a
    token and leaves the task ``waiting_approval`` for some *later* call to
    resolve — an in-turn tool call (``core/tools.py``'s ``dispatch_tool``) has
    nowhere else to go while it waits: the model is blocked on this exact
    answer. So this function blocks instead of returning early, polling the
    record every *poll_interval* seconds (default
    ``config.TOOL_APPROVAL_POLL_INTERVAL_S`` — never busy-spins) until either
    it resolves or *timeout* seconds elapse (default
    ``config.TOOL_APPROVAL_TIMEOUT``; deliberately much shorter than the async
    ``APPROVAL_TIMEOUT`` — see config.py for why).

    A timeout resolves the record to **denied** via the same
    ``_resolve_timeout_as_denied`` helper the expiry sweep uses — never left
    dangling in ``pending``.

    ``sleep``/``clock`` are injectable two ways, both real, both exercised by
    the test suite: pass them explicitly (a direct unit test of this
    function), or leave them ``None`` and monkeypatch the module's ``_time``
    reference (``docket.core.approval._time``) — the callers this function
    exists for (``core/tools.py``'s ``dispatch_tool``) call this with no
    override, so an end-to-end test of *that* path fakes time the second way.
    This is why the fallback is resolved in the body rather than as an
    ordinary default-argument value: a default bound at function-definition
    time would capture the real ``time.sleep`` once and never see a later
    monkeypatch of the module attribute.
    """
    effective_timeout = _cfg.TOOL_APPROVAL_TIMEOUT if timeout is None else timeout
    effective_poll = _cfg.TOOL_APPROVAL_POLL_INTERVAL_S if poll_interval is None else poll_interval
    do_sleep = sleep if sleep is not None else _time.sleep
    do_clock = clock if clock is not None else _time.monotonic
    deadline = do_clock() + effective_timeout

    while True:
        data = _read(token)
        state = str(data.get("state", ""))
        if state == "granted":
            return ApprovalWaitResult("granted", token)
        if state in ("denied", "expired"):
            return ApprovalWaitResult("denied", token)
        if cancellation_check is not None and cancellation_check():
            try:
                approval_deny(token, channel="cancellation")
            except (ApprovalNoop, ApprovalError):
                # A concurrent terminal decision won. Preserve and report it;
                # the caller still performs its post-wait cancellation check
                # before allowing a granted call to reach the handler.
                final_state = str(_read(token).get("state", ""))
                if final_state == "granted":
                    return ApprovalWaitResult("granted", token, cancelled=True)
                if final_state not in ("denied", "expired"):
                    raise
            return ApprovalWaitResult("denied", token, cancelled=True)
        if do_clock() >= deadline:
            if _resolve_timeout_as_denied(token):
                return ApprovalWaitResult("denied", token, timed_out=True)
            # A concurrent decision won after this polling read. Observe the
            # persisted winner rather than returning a stale timeout denial.
            final_state = str(_read(token).get("state", ""))
            if final_state == "granted":
                return ApprovalWaitResult("granted", token)
            return ApprovalWaitResult("denied", token)
        do_sleep(effective_poll)
