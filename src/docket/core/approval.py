"""Durable pending-approval store for HITL gating. Records persist to
``$APPROVALS_DIR/<token>.json`` (atomic, 0600); as docket-owned artefacts, writes go through
``edges/store.py``. ``context`` is optional caller data stored verbatim, a seam letting a
later resolver (e.g. ``core/dispatch.py``) find what a token gated. Trace and redaction are
best-effort behind ``_emit_trace``/``_redact`` so tests can stub them; grant/deny also
audit-log the calling channel, restricted to the closed ``APPROVAL_CHANNELS`` set so a caller
(e.g. ``serve.py``) cannot inject an arbitrary string into the record. The expiry sweep
resolves a stale pending record to **denied** (fail-closed, not ``"expired"``) and notifies
``core/dispatch.py`` so a waiting task is not left stranded. ``wait_for_approval`` blocks the
calling thread instead for ``core/tools.py``'s in-turn gate, sharing the same fail-closed
resolution via ``_resolve_timeout_as_denied``.
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
APPROVAL_RATIONALE_MAX_CHARS = 500

# The three choices every gated call offers (ADR 0018 decision 3): id, label, description.
_PACK_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("approve_once", "Approve once", "Run this call now; ask again next time."),
    ("approve_task", "Approve for this task", "Run this call and any identical one in this task."),
    ("deny", "Deny", "Refuse this call; a reason can be given."),
)
APPROVAL_OPTION_IDS: frozenset[str] = frozenset(o[0] for o in _PACK_OPTIONS)


def approval_options() -> list[dict[str, Any]]:
    """The three pack options, built through the operator-v1.1 ``Option`` model."""
    from docket.core.operator_contract import Option

    return [
        Option(id=i, label=label, description=desc).model_dump(by_alias=True, exclude_none=True)
        for i, label, desc in _PACK_OPTIONS
    ]


def screen_rationale(text: str) -> tuple[str, bool]:
    """Screen the assistant text behind a gated call as untrusted input, then bound it.
    Returns ``(rationale, blocked)``; a blocked rationale is ``""``."""
    text = (text or "").strip()
    if not text:
        return "", False
    from docket.core import policy as _policy

    hit = _policy.policy_eval_detail("lead", "pre_input", text, trusted=False)
    if hit.action == "block":
        return "", True
    return _redact(text)[:APPROVAL_RATIONALE_MAX_CHARS], False


APPROVAL_CHANNELS: frozenset[str] = frozenset(
    {"cli", "http", "mcp", "telegram", "timeout", "tack", "harness"}
)

# Every state a resolved approval record can end in. Only "pending" is live; the sweep
# below must never touch a pending record regardless of age.
_TERMINAL_APPROVAL_STATES: frozenset[str] = frozenset({"granted", "denied", "expired"})


class ApprovalError(Exception):
    """Raised for invalid approval transitions or missing tokens."""


class ApprovalConflict(ApprovalError):
    """Raised when the opposite decision already won (grant-after-deny or
    deny-after-grant), unlike the same-action no-op (:class:`ApprovalNoop`).
    Carries ``winning_state``; still an ``ApprovalError`` for existing callers."""

    def __init__(self, message: str, winning_state: str) -> None:
        super().__init__(message)
        self.winning_state = winning_state


class ApprovalNoop(Exception):
    """Raised when a transition is a benign no-op (already in target state)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _redact(text: str) -> str:
    """Best-effort secret redaction via the trace/redact port. A redaction failure must
    never break approval, so any error returns the original text unchanged; the local
    import avoids a cycle with trace."""
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
    """Best-effort trace hook to docket.core.trace.trace_event; any failure is swallowed
    so a trace problem never breaks the approval. Local import avoids a cycle."""
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
    """Conditionally make one pending record terminal under the store lock; the caller must
    use the returned record for side effects. Checking state inside ``read_modify_write``
    (not before) makes one decision the sole transition winner under concurrent callers."""
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
                raise ApprovalConflict(
                    f"Cannot grant approval in state '{state}': {token}", winning_state=state
                )
        elif new_state == "denied":
            if state in ("denied", "expired"):
                raise ApprovalNoop(f"Already {state}: {token}")
            if state != "pending":
                raise ApprovalConflict(
                    f"Cannot deny approval in state '{state}': {token}", winning_state=state
                )
        else:  # private callers only use the two terminal states above.
            raise ApprovalError(f"Unknown approval state: {new_state}")

        data["state"] = new_state
        return data

    return _store.read_modify_write(path, transition)


def approval_create(
    project: str,
    role: str,
    action: str,
    *,
    context: dict[str, Any] | None = None,
    expires_at: str | None = None,
    rationale: str | None = None,
    rationale_blocked: bool = False,
) -> str:
    """Persist a pending approval and return its token. ``context`` is optional caller
    data stored verbatim, never redacted; always ``{}`` when omitted. ``expires_at``,
    when given, is the record's own deadline -- the sweep honours it over ``APPROVAL_TIMEOUT``.
    ``rationale`` (already screened and bounded; ``""`` when none) makes this a gated-call
    pack: the record and ``approval_requested`` gain ``rationale`` and the three ``options``.
    ``None`` leaves both out."""
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
    if expires_at:
        data["expiresAt"] = expires_at
    if rationale is not None:
        data["rationale"] = rationale
        data["options"] = approval_options()
    _store.write_json(_approval_path(token), data)

    # The call a paused approval is for, when the caller names it. A caller answering
    # the request (``docket harness run --answers stdin``) needs these to know which
    # call it is resolving; nothing else in the payload changes.
    requested: dict[str, Any] = {"token": token, "action": redacted_action}
    for key in ("tool", "callId"):
        if (context or {}).get(key):
            requested[key] = str((context or {})[key])
    if rationale is not None:
        requested["rationale"] = rationale
        requested["options"] = data["options"]
        if rationale_blocked:
            requested["rationaleBlocked"] = True
    _emit_trace(
        project,
        f"{project}-approval-{os.getpid()}",
        role,
        "approval_requested",
        requested,
    )
    return token


def approval_set_option(token: str, option_id: str) -> None:
    """Record the pack option a caller chose on a still-pending approval, so the waiting
    turn can act on it once the grant lands. Unknown ids and resolved records raise."""
    if option_id not in APPROVAL_OPTION_IDS:
        raise ApprovalError(f"unknown option {option_id!r}")
    path = _approval_path(token)

    def record(data: dict[str, Any]) -> dict[str, Any]:
        if not path.is_file():
            raise ApprovalError(f"Approval not found: {token}")
        if data.get("state") != "pending":
            raise ApprovalNoop(f"Not pending: {token}")
        ctx = dict(data.get("context") or {})
        ctx["optionId"] = option_id
        data["context"] = ctx
        return data

    _store.read_modify_write(path, record)


def create_pregrant(
    project: str,
    role: str,
    tool: str,
    args_digest: str,
    *,
    task_id: str | None = None,
    expires_at: str | None = None,
    channel: str,
    actor: str = "",
) -> str:
    """Persist a single-use pre-grant, already ``granted``, for one exact tool call a
    human approved ahead of the turn that will make it -- unlike ``approval_create``,
    this record is born resolved. ``consume_pregrant`` is the only way it is ever spent."""
    if not project or not role or not tool or not args_digest:
        raise ApprovalError("create_pregrant: missing arguments")
    if channel not in APPROVAL_CHANNELS:
        raise ApprovalError(f"create_pregrant: unknown channel {channel!r}")

    _cfg.APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_cfg.APPROVALS_DIR, 0o700)

    token = f"apr-{uuid.uuid4()}"
    created = _utc_now()
    context: dict[str, Any] = {"kind": "pregrant", "tool": tool, "argsDigest": args_digest}
    if task_id:
        context["taskId"] = task_id

    data: dict[str, Any] = {
        "token": token,
        "project": project,
        "role": role,
        "action": f"pre-grant: {tool} (argsDigest={args_digest})",
        "state": "granted",
        "created": created,
        "context": context,
    }
    if expires_at:
        data["expiresAt"] = expires_at
    _store.write_json(_approval_path(token), data)

    audit_log(
        "approval.pregrant",
        f"token={token} project={project} tool={tool} channel={channel} actor={actor or '?'}",
    )
    return token


def consume_pregrant(token: str) -> bool:
    """Spend one single-use pre-grant. Returns ``True`` only once, for a record still
    ``granted`` and not past its own ``expiresAt``; a second call, or one past expiry,
    is a safe ``False`` no-op. Atomic, so a concurrent caller can never spend it twice."""
    if not token:
        return False
    path = _approval_path(token)
    consumed = False

    def transition(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal consumed
        if not path.is_file():
            return None
        if data.get("state") != "granted" or data.get("consumedAt"):
            return None
        expires_at = data.get("expiresAt")
        if expires_at:
            deadline = _parse_iso(str(expires_at))
            if deadline is not None and _dt.datetime.now(_dt.UTC).timestamp() > deadline:
                return None
        data["consumedAt"] = _utc_now()
        consumed = True
        return data

    data = _store.read_modify_write(path, transition)
    if consumed:
        tool = str((data.get("context") or {}).get("tool", ""))
        audit_log("approval.consume", f"token={token} tool={tool}")
    return consumed


def approval_get(token: str) -> dict[str, Any]:
    """Return the approval record, raising ApprovalError if missing."""
    if not token:
        raise ApprovalError("approval_get: token required")
    return _read(token)


def approval_grant(
    token: str, channel: str = "unknown", *, actor: str = "", reason: str = ""
) -> None:
    """Transition pending → granted. Reason is screened against pre_input policy;
    blocked reasons raise ApprovalError before resolving. See approval_deny for details."""
    # Screen the reason against pre_input policies if non-empty
    if reason:
        from docket.core import policy as _policy

        hit = _policy.policy_eval_detail("lead", "pre_input", reason, trusted=False)
        if hit.action == "block":
            raise ApprovalError(f"Reason blocked by policy {hit.policy_id}")

    data = _set_state(token, "granted")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"

    # Build trace payload with actor and reason only when non-empty
    trace_payload: dict[str, Any] = {"token": token}
    if actor:
        trace_payload["actor"] = actor
    if reason:
        trace_payload["reason"] = _redact(reason)

    _emit_trace(project, f"{project}-approval", role, "approval_granted", trace_payload)

    # Build audit detail with actor and reason only when non-empty
    audit_detail = f"token={token} project={project} channel={channel}"
    if actor:
        audit_detail += f" actor={_redact(actor)}"
    if reason:
        audit_detail += f" reason={_redact(reason)}"
    audit_log("approval.grant", audit_detail)


def approval_deny(
    token: str, channel: str = "unknown", *, actor: str = "", reason: str = ""
) -> None:
    """Transition pending → denied. Reason is screened against pre_input policy;
    blocked reasons raise ApprovalError before resolving."""
    # Screen the reason against pre_input policies if non-empty
    if reason:
        from docket.core import policy as _policy

        hit = _policy.policy_eval_detail("lead", "pre_input", reason, trusted=False)
        if hit.action == "block":
            raise ApprovalError(f"Reason blocked by policy {hit.policy_id}")

    data = _set_state(token, "denied")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"

    # Build trace payload with actor and reason only when non-empty
    trace_payload: dict[str, Any] = {"token": token}
    if actor:
        trace_payload["actor"] = actor
    if reason:
        trace_payload["reason"] = _redact(reason)

    _emit_trace(project, f"{project}-approval", role, "approval_denied", trace_payload)

    # Build audit detail with actor and reason only when non-empty
    audit_detail = f"token={token} project={project} channel={channel}"
    if actor:
        audit_detail += f" actor={_redact(actor)}"
    if reason:
        audit_detail += f" reason={_redact(reason)}"
    audit_log("approval.deny", audit_detail)

    # Record the denial reason to the corrections ledger (only if reason is given and project exists)
    if reason and project != "operator":
        from docket.core import corrections as _corrections

        task_id = str(data.get("taskId", ""))
        _corrections.record(
            project,
            "deny_reason",
            task_id=task_id,
            role=role,
            text=reason,
            source=channel,
        )


def list_pending() -> list[dict[str, Any]]:
    """Return every pending approval record in filename order; records that fail to
    parse are skipped."""
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


def prune_resolved(
    retention_s: int | None = None,
    *,
    dry_run: bool = False,
    now: float | None = None,
) -> int:
    """Delete resolved approval records (granted/denied/expired) whose file mtime is
    past the retention window (default ``config.TRACE_RETENTION_S``). Returns the
    count removed (or, under *dry_run*, that would be)."""
    # A state transition is a record's only write after creation, so mtime is a
    # faithful "resolved at" proxy without a schema change. A pending record is never
    # touched regardless of age -- see approval_sweep_expired for that separate,
    # timeout-driven path. Each candidate is deleted under its own file lock so a
    # concurrent grant/deny can never race the removal.
    if not _cfg.APPROVALS_DIR.is_dir():
        return 0
    window = _cfg.TRACE_RETENTION_S if retention_s is None else retention_s
    cutoff = (now if now is not None else _dt.datetime.now(_dt.UTC).timestamp()) - window
    removed = 0
    for path in sorted(_cfg.APPROVALS_DIR.glob("*.json")):
        with _store.with_lock(path):
            try:
                with path.open(encoding="utf-8") as f:
                    data: dict[str, Any] = json.load(f)
            except Exception:
                continue
            if data.get("state") not in _TERMINAL_APPROVAL_STATES:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            if dry_run:
                removed += 1
                continue
            try:
                path.unlink()
            except OSError:
                continue
            removed += 1
    return removed


def _resolve_timeout_as_denied(token: str) -> bool:
    """Fail-closed timeout resolution shared by the sweep and the in-turn waiter. Returns ``True``
    only for the transition winner, which writes the audit entry and notifies ``core/dispatch.py``;
    a grant, deny, expiry, or deletion winning first is a harmless ``False``, not an overwrite."""
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


def _parse_iso(text: str) -> float | None:
    """Parse a ``YYYY-MM-DDTHH:MM:SS...`` UTC timestamp to epoch seconds, or ``None``
    for anything unparseable (fail-open on parsing, never on the expiry decision
    itself: an unparseable ``expiresAt`` is treated as "no expiry recorded")."""
    try:
        return (
            _dt.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
            .replace(tzinfo=_dt.UTC)
            .timestamp()
        )
    except ValueError:
        return None


def _expiry_deadline(data: dict[str, Any]) -> float | None:
    """A pending record's own ``expiresAt`` wins when present (a parked call may carry
    one); otherwise fall back to ``created + APPROVAL_TIMEOUT``, unchanged from before
    pre-grants existed."""
    expires_at = data.get("expiresAt")
    if expires_at:
        return _parse_iso(str(expires_at))
    created_str = str(data.get("created", ""))
    if not created_str:
        return None
    created_ts = _parse_iso(created_str)
    if created_ts is None:
        return None
    return created_ts + _cfg.APPROVAL_TIMEOUT


def _expire_unconsumed_pregrant(token: str, project: str, role: str) -> bool:
    """Fail-closed: deny an unconsumed pre-grant once past its own ``expiresAt``.
    Unlike ``_resolve_timeout_as_denied`` this skips ``_set_state``: a pre-grant is
    *born* ``granted``, so this prunes an unused offer, not a grant/deny race."""
    path = _approval_path(token)
    expired = False

    def transition(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal expired
        if not path.is_file():
            return None
        if data.get("state") != "granted" or data.get("consumedAt"):
            return None
        data["state"] = "denied"
        expired = True
        return data

    _store.read_modify_write(path, transition)
    if expired:
        _emit_trace(project, f"{project}-approval", role, "approval_denied", {"token": token})
        audit_log("approval.deny", f"token={token} project={project} channel=timeout")
    return expired


def approval_sweep_expired() -> int:
    """Expire pending approvals past their deadline (own ``expiresAt``, else
    ``APPROVAL_TIMEOUT``) via ``_resolve_timeout_as_denied``, and separately prune
    unconsumed pre-grants past theirs -- both resolved to **denied** (fail-closed)."""
    if not _cfg.APPROVALS_DIR.is_dir():
        return 0
    now = _dt.datetime.now(_dt.UTC).timestamp()
    swept = 0
    for path in _cfg.APPROVALS_DIR.glob("*.json"):
        try:
            with path.open(encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception:
            continue

        token = str(data.get("token", ""))
        if not token:
            continue
        state = data.get("state")

        if state == "pending":
            deadline = _expiry_deadline(data)
            if deadline is not None and now > deadline and _resolve_timeout_as_denied(token):
                swept += 1
            continue

        if (
            state == "granted"
            and not data.get("consumedAt")
            and str((data.get("context") or {}).get("kind", "")) == "pregrant"
        ):
            expires_at = data.get("expiresAt")
            deadline = _parse_iso(str(expires_at)) if expires_at else None
            if deadline is not None and now > deadline:
                project = str(data.get("project", "")) or "operator"
                role = str(data.get("role", "")) or "operator"
                if _expire_unconsumed_pregrant(token, project, role):
                    swept += 1
    return swept


@dataclass(frozen=True)
class ApprovalWaitResult:
    """Outcome of blocking on one token until it resolves or times out. ``state`` is always
    final (never ``"pending"``); ``timed_out`` distinguishes an explicit deny from a
    fail-closed expiry, useful both for the message handed to the model and for audit review."""

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

    Unlike ``core/dispatch.py``'s require_approval gate — which creates a token and leaves
    the task ``waiting_approval`` for a later call to resolve — an in-turn tool call
    (``core/tools.py``'s ``dispatch_tool``) has nowhere else to go while it waits: the model
    is blocked on this exact answer. So this function polls the record every
    *poll_interval* seconds (default ``config.TOOL_APPROVAL_POLL_INTERVAL_S``; never
    busy-spins) until it resolves or *timeout* seconds elapse (default
    ``config.TOOL_APPROVAL_TIMEOUT``, deliberately much shorter than the async
    ``APPROVAL_TIMEOUT`` — see config.py for why). A timeout resolves the record to
    **denied** via the same ``_resolve_timeout_as_denied`` helper the expiry sweep uses —
    never left dangling in ``pending``.

    ``sleep``/``clock`` are injectable two ways, both exercised by the suite: pass them
    explicitly for a direct unit test, or leave them ``None`` and monkeypatch the module's
    ``_time`` reference (the real callers pass no override, so an end-to-end test fakes time
    this second way). The fallback is resolved in the body rather than as a default-argument
    value because a default bound at definition time would capture the real ``time.sleep``
    once and never see a later monkeypatch of the module attribute.
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
