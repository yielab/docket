"""Durable pending-approval store for HITL gating. Records persist to
``$APPROVALS_DIR/<token>.json`` (atomic, 0600); as docket-owned artefacts, writes go through
``platform/store.py``. ``context`` is optional caller data stored verbatim, a seam letting a
later resolver (e.g. ``tasks/application/actions.py``) find what a token gated. Trace and redaction are
best-effort behind ``_emit_trace``/``_redact`` so tests can stub them; grant/deny also
audit-log the calling channel, restricted to the closed ``APPROVAL_CHANNELS`` set so a caller
(e.g. ``interfaces/http/server.py``) cannot inject an arbitrary string into the record. The expiry sweep
(``tasks/application/escalation_sweep.py``) resolves a stale pending record to **denied** (fail-closed, not ``"expired"``) and notifies
``tasks/application/actions.py`` so a waiting task is not left stranded. ``wait_for_approval`` blocks the
calling thread instead for ``agent/tools/registry.py``'s in-turn gate, sharing the same fail-closed
resolution via ``expire_approval``.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from docket.governance import escalation_expiry as _escalation_expiry
from docket.governance import policy as _policy
from docket.governance import secrets as _secrets
from docket.governance.audit import audit_log
from docket.governance.ports import approval_follow_up as _follow_up
from docket.kernel import clock as _clock
from docket.kernel import ids as _ids
from docket.kernel.errors import NotFound
from docket.kernel.home import current_home
from docket.kernel.operator_contract import Option
from docket.kernel.ports import tracer as _tracer
from docket.platform import read_modify_write, with_lock, write_json

# The closed set of channels a grant/deny may be tagged with in the audit log
# (see the module docstring). ``timeout`` is the fail-closed expiry path
# (``expire_approval``), never a human-driven caller. Callers that
# accept a channel from outside the process (``interfaces/http/routes/approvals.py``'s
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


_TASK_WIDE = "approve_task"


def approval_options(deletes: bool = False) -> list[dict[str, Any]]:
    """The pack options, built through the operator-v1.1 ``Option`` model: the three, or for a
    call that *deletes* only ``approve_once`` and ``deny``, since a delete is never granted for
    the rest of a task."""

    return [
        Option(id=i, label=label, description=desc).model_dump(by_alias=True, exclude_none=True)
        for i, label, desc in _PACK_OPTIONS
        if not (deletes and i == _TASK_WIDE)
    ]


def screen_rationale(text: str, project: str = "") -> tuple[str, bool]:
    """Screen the assistant text behind a gated call as untrusted input (with *project*'s own
    policies when it is a pod's), then bound it. Returns ``(rationale, blocked)``; a blocked rationale is ``""``."""
    text = (text or "").strip()
    if not text:
        return "", False

    hit = _policy.policy_eval_detail("lead", "pre_input", text, trusted=False, project=project)
    if hit.action == "block":
        return "", True
    return _redact(text)[:APPROVAL_RATIONALE_MAX_CHARS], False


APPROVAL_CHANNELS: frozenset[str] = frozenset({"cli", "http", "mcp", "telegram", "timeout", "tack"})

# Every state a resolved approval record can end in. Only "pending" is live; the sweep
# below must never touch a pending record regardless of age.
_TERMINAL_APPROVAL_STATES: frozenset[str] = frozenset({"granted", "denied", "expired"})


class ApprovalError(NotFound):
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
    """Best-effort secret redaction. A redaction failure must never break approval, so any
    error returns the original text unchanged."""
    try:
        return _secrets.redact(text)
    except Exception:
        return text


_AUDIT_FIELD_MAX = 512


def _audit_field(text: str) -> str:
    """Redact, then cap at 512 characters with a visible marker (audit.spec.md Requirement 7)."""
    clean = _redact(text)
    return clean if len(clean) <= _AUDIT_FIELD_MAX else clean[:_AUDIT_FIELD_MAX] + "…"


def _emit_trace(
    project: str,
    session: str,
    role: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort trace hook to the tracer port; any failure is swallowed so a trace problem
    never breaks the approval."""
    try:
        _tracer.trace_event(project, session, role, event_type, json.dumps(payload))
    except Exception:
        return None


# Every approval and pre-grant token is minted below as ``apr-<uuid4>``. The HTTP route,
# Telegram, MCP and the CLI all hand caller text to ``_approval_path``, so the form is
# checked here, at the one place a token becomes a filename, rather than per channel.
APPROVAL_TOKEN_RE = re.compile(r"apr-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _approval_path(token: str) -> Path:
    if not APPROVAL_TOKEN_RE.fullmatch(token):
        raise ApprovalError("Approval not found")
    return current_home().approvals_dir / f"{token}.json"


def _read(token: str) -> dict[str, Any]:
    path = _approval_path(token)
    if not path.is_file():
        raise ApprovalError(f"Approval not found: {token}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _record_project(token: str) -> str:
    """The pod an approval record belongs to; ``""`` for a record that is missing or has none,
    which the transition after the screen then refuses on its own."""
    try:
        return str(_read(token).get("project", ""))
    except (ApprovalError, OSError, ValueError):
        return ""


def set_state(token: str, new_state: str) -> dict[str, Any]:
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
        data.pop("call", None)  # a settled approval never holds the call it was asked about
        return data

    return read_modify_write(path, transition)


def _annotate(token: str, **extra: Any) -> dict[str, Any]:
    """Write *extra* keys on the record *token* under the store lock; the record as stored."""
    path = _approval_path(token)

    def write(data: dict[str, Any]) -> dict[str, Any]:
        data.update(extra)
        return data

    return read_modify_write(path, write)


def approval_create(
    project: str,
    role: str,
    action: str,
    *,
    context: dict[str, Any] | None = None,
    expires_at: str | None = None,
    rationale: str | None = None,
    rationale_blocked: bool = False,
    call: str | None = None,
    deletes: bool = False,
) -> str:
    """Persist a pending approval and return its token. ``context`` is optional caller
    data stored verbatim, never redacted; always ``{}`` when omitted. ``call`` is the whole
    outward call a person approves, already redacted for credentials by the caller and kept
    uncut until the record is settled (``set_state`` drops it). ``expires_at``,
    is the record's own deadline; omitted, it is ``created + APPROVAL_TIMEOUT``.
    ``rationale`` (already screened and bounded; ``""`` when none) makes this a gated-call
    pack: the record gains ``rationale`` and the three ``options``, and ``rationaleBlocked`` when
    the model's rationale was withheld by a policy. ``None`` leaves all of them out. ``deletes``
    narrows the options to ``approve_once`` and ``deny``."""
    if not project or not role or not action:
        raise ApprovalError("approval_create: missing arguments")

    current_home().approvals_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(current_home().approvals_dir, 0o700)

    token = _ids.new_id("apr")
    created = _clock.stamp()
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
    data["expiresAt"] = expires_at or _iso_after(created, current_home().approval_timeout)
    if rationale is not None:
        data["rationale"] = rationale
        data["options"] = approval_options(deletes)
        if rationale_blocked:
            data["rationaleBlocked"] = True
    if call is not None:
        data["call"] = call
    write_json(_approval_path(token), data)

    return token


def approval_link(token: str, escalation_id: str) -> None:
    """Record on approval *token* the escalation it backs: the one place the two meet, so the
    escalation record never holds a token and a surface names the pause by its escalation id."""
    _annotate(token, escalation=escalation_id)


def approvals_of() -> dict[str, str]:
    """The approval token behind each escalation id that has one, read in one pass."""
    return {
        str(data["escalation"]): str(data.get("token", ""))
        for data in list_records()
        if data.get("escalation") and data.get("token")
    }


def approval_of(escalation_id: str) -> str:
    """The token of the approval record that backs *escalation_id*, else ``""`` (a pause that waits
    on no approval: a parked question)."""
    return approvals_of().get(escalation_id, "")


def approval_call(escalation_id: str) -> str | None:
    """The whole call of the still-pending approval that backs *escalation_id*, else ``None``:
    the one text an operator's own view shows, which no settled record holds."""
    token = approval_of(escalation_id)
    if not token:
        return None
    try:
        data = _read(token)
    except (ApprovalError, OSError, ValueError):
        return None
    call = data.get("call")
    return str(call) if data.get("state") == "pending" and call is not None else None


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
        offered = [str(o.get("id")) for o in data.get("options") or [] if isinstance(o, dict)]
        if offered and option_id not in offered:
            raise ApprovalError(f"option {option_id!r} is not offered; choose one of: {offered}")
        ctx = dict(data.get("context") or {})
        ctx["optionId"] = option_id
        data["context"] = ctx
        return data

    read_modify_write(path, record)


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
        hit = _policy.policy_eval_detail(
            "lead", "pre_input", reason, trusted=False, project=_record_project(token)
        )
        if hit.action == "block":
            raise ApprovalError(f"Reason blocked by policy {hit.policy_id}")

    data = set_state(token, "granted")
    # Who granted it and through what stays on the record: a task-wide grant mints its later
    # pre-grants from here (``approval_pregrant.task_grants``). Only the winner of the transition
    # reaches this line.
    data = _annotate(token, grantedVia=channel, grantedBy=actor)
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"

    # Build trace payload with actor and reason only when non-empty
    trace_payload: dict[str, Any] = {"token": token}
    if actor:
        trace_payload["actor"] = _audit_field(actor)
    if reason:
        trace_payload["reason"] = _audit_field(reason)

    _emit_trace(project, f"{project}-approval", role, "approval_granted", trace_payload)

    # Build audit detail with actor and reason only when non-empty
    audit_detail = f"token={token} project={project} channel={channel}"
    if actor:
        audit_detail += f" actor={_audit_field(actor)}"
    if reason:
        audit_detail += f" reason={_audit_field(reason)}"
    audit_log("approval.grant", audit_detail)


def approval_deny(
    token: str, channel: str = "unknown", *, actor: str = "", reason: str = ""
) -> None:
    """Transition pending → denied. Reason is screened against pre_input policy;
    blocked reasons raise ApprovalError before resolving."""
    # Screen the reason against pre_input policies if non-empty
    if reason:
        hit = _policy.policy_eval_detail(
            "lead", "pre_input", reason, trusted=False, project=_record_project(token)
        )
        if hit.action == "block":
            raise ApprovalError(f"Reason blocked by policy {hit.policy_id}")

    data = set_state(token, "denied")
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"

    # Build trace payload with actor and reason only when non-empty
    trace_payload: dict[str, Any] = {"token": token}
    if actor:
        trace_payload["actor"] = _audit_field(actor)
    if reason:
        trace_payload["reason"] = _audit_field(reason)

    _emit_trace(project, f"{project}-approval", role, "approval_denied", trace_payload)

    # Build audit detail with actor and reason only when non-empty
    audit_detail = f"token={token} project={project} channel={channel}"
    if actor:
        audit_detail += f" actor={_audit_field(actor)}"
    if reason:
        audit_detail += f" reason={_audit_field(reason)}"
    audit_log("approval.deny", audit_detail)


def list_records() -> list[dict[str, Any]]:
    """Return every approval record, whatever its state, in filename order; records that fail
    to parse are skipped."""
    if not current_home().approvals_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(current_home().approvals_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception:
            continue
        out.append(data)
    return out


def list_pending() -> list[dict[str, Any]]:
    """Return every pending approval record in filename order; records that fail to
    parse are skipped."""
    return [data for data in list_records() if data.get("state") == "pending"]


def prune_resolved(
    retention_s: int | None = None,
    *,
    dry_run: bool = False,
    now: float | None = None,
) -> int:
    """Delete resolved approval records (granted/denied/expired) whose file mtime is
    past the retention window (default ``Home.trace_retention_s``). Returns the
    count removed (or, under *dry_run*, that would be)."""
    # A state transition is a record's only write after creation, so mtime is a
    # faithful "resolved at" proxy without a schema change. A pending record is never
    # touched regardless of age -- see the expiry sweep for that separate,
    # timeout-driven path. Each candidate is deleted under its own file lock so a
    # concurrent grant/deny can never race the removal.
    if not current_home().approvals_dir.is_dir():
        return 0
    window = current_home().trace_retention_s if retention_s is None else retention_s
    cutoff = (now if now is not None else _clock.epoch()) - window
    removed = 0
    for path in sorted(current_home().approvals_dir.glob("*.json")):
        with with_lock(path):
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


def expire_approval(token: str) -> bool:
    """Fail-closed timeout resolution shared by the expiry sweep and the in-turn waiter. Returns ``True``
    only for the transition winner, which writes the audit entry and notifies ``tasks/application/actions.py``;
    a grant, deny, expiry, or deletion winning first is a harmless ``False``, not an overwrite."""
    try:
        data = set_state(token, "denied")
    except (ApprovalError, ApprovalNoop):
        return False
    project = str(data.get("project", "")) or "operator"
    role = str(data.get("role", "")) or "operator"
    _emit_trace(project, f"{project}-approval", role, "approval_denied", {"token": token})
    audit_log("approval.deny", f"token={token} project={project} channel=timeout")
    escalation_id = str(data.get("escalation", ""))
    if escalation_id:
        with contextlib.suppress(Exception):
            _escalation_expiry.expire(escalation_id)
    with contextlib.suppress(Exception):
        _follow_up.resolve_waiting_approval(token, "denied")
    return True


def _iso_after(stamp: str, seconds: float) -> str:
    base = _clock.parse_epoch(stamp) or _clock.epoch()
    moment = _dt.datetime.fromtimestamp(base + seconds, _dt.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _expiry_deadline(data: dict[str, Any]) -> float | None:
    """A pending record's own ``expiresAt`` epoch seconds, or ``None`` when absent."""
    expires_at = data.get("expiresAt")
    return _clock.parse_epoch(str(expires_at)) if expires_at else None


def _expire_unconsumed_pregrant(token: str, project: str, role: str) -> bool:
    """Fail-closed: deny an unconsumed pre-grant once past its own ``expiresAt``.
    Unlike ``expire_approval`` this skips ``set_state``: a pre-grant is
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

    read_modify_write(path, transition)
    if expired:
        _emit_trace(project, f"{project}-approval", role, "approval_denied", {"token": token})
        audit_log("approval.deny", f"token={token} project={project} channel=timeout")
    return expired


def pending_past_deadline(now: float | None = None) -> list[str]:
    """The tokens of every pending approval past its own ``expiresAt`` at *now* (epoch seconds,
    default the clock)."""
    if not current_home().approvals_dir.is_dir():
        return []
    moment = _clock.epoch() if now is None else now
    expired: list[str] = []
    for path in sorted(current_home().approvals_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception:
            continue
        deadline = _expiry_deadline(data)
        if data.get("state") == "pending" and deadline is not None and moment > deadline:
            expired.append(str(data.get("token", "")))
    return [token for token in expired if token]


def prune_unconsumed_pregrants(now: float | None = None) -> int:
    """Deny every unconsumed pre-grant past its own ``expiresAt`` at *now* (fail closed); how many."""
    if not current_home().approvals_dir.is_dir():
        return 0
    moment = _clock.epoch() if now is None else now
    pruned = 0
    for path in sorted(current_home().approvals_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception:
            continue
        token = str(data.get("token", ""))
        if (
            not token
            or data.get("state") != "granted"
            or data.get("consumedAt")
            or str((data.get("context") or {}).get("kind", "")) != "pregrant"
        ):
            continue
        deadline = _expiry_deadline(data)
        if deadline is None or moment <= deadline:
            continue
        project = str(data.get("project", "")) or "operator"
        role = str(data.get("role", "")) or "operator"
        if _expire_unconsumed_pregrant(token, project, role):
            pruned += 1
    return pruned


@dataclass(frozen=True)
class ApprovalWaitResult:
    """Outcome of blocking on one token until it resolves or times out. ``state`` is always
    final (never ``"pending"``); ``timed_out`` is a fail-closed expiry rather than an explicit
    deny."""

    state: Literal["granted", "denied"]
    token: str
    timed_out: bool = False
    cancelled: bool = False


def pause(seconds: float) -> None:
    """Wait between two polls of a pending approval."""
    time.sleep(seconds)


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

    Unlike ``hops/gates/pre_hop.py``'s require_approval gate — which creates a token and leaves
    the task ``waiting_approval`` for a later call to resolve — an in-turn tool call
    (``agent/tools/registry.py``'s ``dispatch_tool``) has nowhere else to go while it waits: the model
    is blocked on this exact answer. So this function polls the record every
    *poll_interval* seconds (default ``Home.tool_approval_poll_interval_s``; never
    busy-spins) until it resolves or *timeout* seconds elapse (default
    ``Home.tool_approval_timeout``, deliberately much shorter than the async
    ``APPROVAL_TIMEOUT`` — see kernel/home.py for why). A timeout resolves the record to
    **denied** via the same ``expire_approval`` helper the expiry sweep uses —
    never left dangling in ``pending``.

    ``sleep``/``clock`` are injectable two ways, both exercised by the suite: pass them
    explicitly for a direct unit test, or leave them ``None`` and replace the module's ``pause``
    (the real callers pass no override, so an end-to-end test answers the pending call from
    there). The fallback is resolved in the body rather than as a default-argument value so a
    later replacement of ``pause`` is seen.
    """
    effective_timeout = current_home().tool_approval_timeout if timeout is None else timeout
    effective_poll = (
        current_home().tool_approval_poll_interval_s if poll_interval is None else poll_interval
    )
    do_sleep = sleep if sleep is not None else pause
    do_clock = clock if clock is not None else _clock.monotonic
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
            if expire_approval(token):
                return ApprovalWaitResult("denied", token, timed_out=True)
            # A concurrent decision won after this polling read. Observe the
            # persisted winner rather than returning a stale timeout denial.
            final_state = str(_read(token).get("state", ""))
            if final_state == "granted":
                return ApprovalWaitResult("granted", token)
            return ApprovalWaitResult("denied", token)
        do_sleep(effective_poll)
