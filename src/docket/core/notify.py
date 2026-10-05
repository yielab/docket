"""Operator events, derived from inbox transitions, and their delivery (ADR 0016 SS7).

``diff_events``/``render_data``/``render_text`` are pure: no clock, no I/O, no vendor
knowledge. ``flush`` is the one impure orchestrator -- it builds the current inbox, diffs it
against the persisted dedupe snapshot, saves the new snapshot BEFORE delivering (a crash
mid-delivery must never re-emit: at-most-once, not at-least-once), then hands each event to
whatever ``sink_for`` returns for a channel's dialect. This module never imports
``edges/adapters`` itself -- it receives a sink factory from its caller, the same seam
``core/telemetry.py``'s ``start(specs, sink_for)`` uses. A failed delivery is recorded in
``channels-health.json`` and is never retried on a later flush -- only within the one flush
call that discovered it.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import docket.config as _cfg
from docket.core.operator_contract import (
    ApprovalView,
    CloudEvent,
    InboxView,
    QuestionV11,
    TaskView,
    make_event,
)
from docket.edges import store as _store

__all__ = [
    "Deliver",
    "DeliveryOutcome",
    "FlushReport",
    "NotifyEvent",
    "SinkFactory",
    "build_test_event",
    "diff_events",
    "flush",
    "read_state",
    "render_data",
    "render_text",
    "resolve_secret",
]

# The `on:` values a "needs_you" subscription stands for -- every transition that puts an
# item in the inbox's `needsYou` section, plus the one warning that fires while an item is
# still there (`approval.expiring`). `task.failed`/`task.rejected`/`task.completed` are
# deliberately excluded: a channel wants those only by naming them explicitly.
_NEEDS_YOU_KINDS: frozenset[str] = frozenset(
    {"task.input_required", "approval.requested", "task.blocked", "approval.expiring"}
)

# How much of an approval's life must have elapsed before `approval.expiring` fires, once,
# per token (ADR 0016 SS7).
_EXPIRING_FRACTION = 0.8
_LABEL_MAX = 80

_DELIVERY_TIMEOUT_S = 5.0
_DELIVERY_ATTEMPTS = 3  # one try plus two retries, within this one flush call only
_RETRY_SLEEP_S = 0.5


@dataclass(frozen=True)
class NotifyEvent:
    """One derived transition, not yet rendered for a recipient. `flush` builds one
    `CloudEvent` per channel from this, with a stable `id` but per-channel `data`."""

    kind: str
    pod: str
    subject: str
    version: str
    time: str
    item: TaskView | ApprovalView


@dataclass(frozen=True)
class FlushReport:
    """What one `flush` call did. `events` is the count of distinct transitions found;
    `delivered`/`failed` count individual channel deliveries (one event to three matching
    channels is three); `skipped` counts a match with no wired dialect."""

    events: int = 0
    delivered: int = 0
    failed: int = 0
    skipped: int = 0


class DeliveryOutcome(Protocol):
    """The shape `flush` reads off whatever a `Deliver` call returns. Matched structurally
    against `edges/adapters/channels/webhook.py::DeliveryResult`'s field names, never imported
    by name -- this module never imports `edges/adapters` (see the module docstring)."""

    @property
    def ok(self) -> bool: ...
    @property
    def error(self) -> str: ...


class Deliver(Protocol):
    """What `sink_for(spec)` returns: one dialect's send function."""

    def __call__(
        self, spec: Any, event: CloudEvent, *, secret: str | None, timeout: float
    ) -> DeliveryOutcome: ...


SinkFactory = Callable[[Any], "Deliver | None"]


# ── pure: item identity, diffing, rendering ──────────────────────────────────


def _item_key(item: TaskView | ApprovalView) -> str:
    if isinstance(item, ApprovalView):
        return f"approval:{item.token}"
    return f"task:{item.pod}:{item.id}"


def _item_version(item: TaskView | ApprovalView) -> str:
    """The status plus the question id or token -- so a task re-asking a new question, or an
    approval resolving, is always seen as a changed version even when the status string
    itself repeats (e.g. two different questions both leave a task `waiting_input`)."""
    if isinstance(item, ApprovalView):
        return f"{item.state}:{item.token}"
    extra = ""
    if item.question is not None:
        extra = item.question.id
    elif item.approval_token:
        extra = item.approval_token
    return f"{item.status}:{extra}"


def _needs_you_kind(item: TaskView | ApprovalView) -> str:
    if isinstance(item, ApprovalView):
        return "approval.requested"
    if item.status == "waiting_approval":
        return "approval.requested"
    if item.status == "blocked":
        return "task.blocked"
    return "task.input_required"


def _failed_kind(item: TaskView) -> str:
    return "task.rejected" if item.a2a_state == "REJECTED" else "task.failed"


def _parse_iso(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.UTC)
    return parsed


def _expiring_events(inbox: InboxView, already_warned: set[str], now: str) -> list[NotifyEvent]:
    now_dt = _parse_iso(now)
    if now_dt is None:
        return []
    events: list[NotifyEvent] = []
    for item in inbox.needs_you:
        if not isinstance(item, ApprovalView) or item.token in already_warned:
            continue
        created = _parse_iso(item.created_at)
        expires = _parse_iso(item.expires_at)
        if created is None or expires is None:
            continue
        total = (expires - created).total_seconds()
        if total <= 0:
            continue
        elapsed = (now_dt - created).total_seconds()
        if elapsed / total < _EXPIRING_FRACTION:
            continue
        events.append(
            NotifyEvent(
                kind="approval.expiring",
                pod=item.pod,
                subject=f"approval:{item.token}",
                version=f"expiring:{item.token}",
                time=now,
                item=item,
            )
        )
    return events


def diff_events(
    prev: dict[str, Any], inbox: InboxView, now: str
) -> tuple[list[NotifyEvent], dict[str, Any]]:
    """Which items in *inbox* are new or changed into a notifiable state since *prev*, plus
    the snapshot to persist next. Pure; *now* is the caller's own reading, never the clock.
    Also emits `approval.expiring` once per approval at 80% of its life."""
    raw_versions = prev.get("items")
    versions: dict[str, str] = dict(raw_versions) if isinstance(raw_versions, dict) else {}
    raw_expiring = prev.get("expiring")
    expiring: set[str] = set(raw_expiring) if isinstance(raw_expiring, list) else set()

    events: list[NotifyEvent] = []

    def _consider(item: TaskView | ApprovalView, kind: str) -> None:
        key = _item_key(item)
        version = _item_version(item)
        if versions.get(key) != version:
            events.append(
                NotifyEvent(
                    kind=kind, pod=item.pod, subject=key, version=version, time=now, item=item
                )
            )
        versions[key] = version

    for needs_you_item in inbox.needs_you:
        _consider(needs_you_item, _needs_you_kind(needs_you_item))
    for failed_item in inbox.failed:
        _consider(failed_item, _failed_kind(failed_item))
    for done_item in inbox.done_since:
        _consider(done_item, "task.completed")

    for expiring_event in _expiring_events(inbox, expiring, now):
        events.append(expiring_event)
        expiring.add(expiring_event.subject.removeprefix("approval:"))

    snapshot = {"items": versions, "expiring": sorted(expiring)}
    return events, snapshot


def render_data(item: TaskView | ApprovalView, level: str) -> dict[str, Any]:
    """The event payload for *item* at content *level* (`minimal < actions < conversation`).
    `minimal` never carries a command line or question text; `actions` adds the rendered
    `action` (approvals only); `conversation` adds `question`/`brief` (tasks only)."""
    if isinstance(item, ApprovalView):
        data: dict[str, Any] = {"pod": item.pod, "role": item.role, "token": item.token}
        if item.task_id:
            data["taskId"] = item.task_id
        if item.policy:
            data["reasonCode"] = item.policy
        if item.expires_at:
            data["expiresAt"] = item.expires_at
        data["respond"] = {
            "cli": f"docket approve {item.token}",
            "http": f"/approvals/{item.token}",
        }
        if level != "minimal" and item.action:
            data["action"] = item.action
        return data

    data = {"pod": item.pod, "taskId": item.id}
    if item.reason:
        data["reasonCode"] = item.reason
    if item.approval_token:
        data["token"] = item.approval_token
    if item.question is not None:
        data["questionId"] = item.question.id
        if item.question.expires_at:
            data["expiresAt"] = item.question.expires_at
    data["respond"] = {"cli": "docket inbox", "http": f"/tasks/{item.id}"}
    if level == "conversation":
        if item.question is not None:
            data["question"] = item.question.message
        if item.brief is not None:
            data["brief"] = item.brief.model_dump(by_alias=True, mode="json")
        if isinstance(item.question, QuestionV11) and item.question.options:
            data["options"] = [
                {"id": o.id, "label": _clean_label(o.label)} for o in item.question.options
            ]
            if item.question.recommendation is not None:
                data["recommendation"] = {"optionId": item.question.recommendation.option_id}
    return data


def _clean_label(label: str) -> str:
    """Model text bound for a chat or a terminal: control characters dropped, length capped."""
    text = "".join(ch for ch in label if ch.isprintable())
    return text[:_LABEL_MAX]


def render_text(event: CloudEvent) -> tuple[str, str]:
    """(title, body) for a text-only dialect. Reads only what *event*'s own already-leveled
    `data` carries, so a `minimal` event's text never surfaces what its data omitted."""
    kind = event.type.removeprefix("dev.docket.")
    pod = str(event.data.get("pod", ""))
    title = f"docket: {kind} ({pod})" if pod else f"docket: {kind}"

    parts: list[str] = []
    task_id = event.data.get("taskId")
    if task_id:
        parts.append(f"task {task_id}")
    token = event.data.get("token")
    if token:
        parts.append(f"token {token}")
    reason = event.data.get("reasonCode")
    if reason:
        parts.append(str(reason))
    action = event.data.get("action")
    if action:
        parts.append(f"$ {action}")
    question = event.data.get("question")
    if question:
        parts.append(str(question))
    body = " -- ".join(parts) if parts else kind
    options = event.data.get("options")
    if isinstance(options, list) and options:
        recommended = (event.data.get("recommendation") or {}).get("optionId")
        lines = [
            f"{_clean_label(str(o['id']))} - {o['label']}"
            + (" (recommended)" if o["id"] == recommended else "")
            for o in options
        ]
        lines.append(f"reply: /answer {task_id} <id>")
        body = "\n".join([body, *lines])
    return title, body


def build_test_event(spec: Any, *, now: str) -> CloudEvent:
    """A synthetic `channel.test` event for `docket channels test <name>` -- an operator
    verifying one channel's delivery path before relying on it. Source pod is `cli`: a test
    is triggered by an operator command, not by any real pod's state."""
    data = {"pod": "cli", "channel": spec.name, "message": "docket channel test"}
    return make_event("channel.test", "cli", f"channel:{spec.name}", data, time=now, version=now)


# ── impure: state, secrets, delivery ─────────────────────────────────────────


def read_state() -> dict[str, Any]:
    """The persisted dedupe snapshot (`config.NOTIFY_STATE_FILE`), through `edges/store.py`
    like every other docket-owned JSON read. `{}` before the first flush."""
    return _store.read_json(_cfg.NOTIFY_STATE_FILE)


def _save_state(snapshot: dict[str, Any]) -> None:
    _store.write_json(_cfg.NOTIFY_STATE_FILE, snapshot)


def _load_health() -> dict[str, Any]:
    raw = _store.read_json(_cfg.CHANNELS_HEALTH_FILE)
    return dict(raw) if isinstance(raw, dict) else {}


def resolve_secret(spec: Any) -> str | None:
    """The credential *value* named by `spec.secret`, through `core.secrets.secret_value` --
    a channel document only ever stores a credential name."""
    name = getattr(spec, "secret", None)
    if not name:
        return None
    from docket.core import secrets as _secrets

    return _secrets.secret_value(name)


def _matches_on(spec: Any, kind: str) -> bool:
    on = getattr(spec, "on", None) or []
    if kind in on:
        return True
    return "needs_you" in on and kind in _NEEDS_YOU_KINDS


def _deliver_with_retry(
    deliver: Deliver,
    spec: Any,
    event: CloudEvent,
    secret: str | None,
    sleep: Callable[[float], None],
) -> tuple[bool, str]:
    error = ""
    for attempt in range(_DELIVERY_ATTEMPTS):
        try:
            result = deliver(spec, event, secret=secret, timeout=_DELIVERY_TIMEOUT_S)
        except Exception as exc:  # a dialect must never raise; flush never trusts that alone
            error = str(exc)
        else:
            if result.ok:
                return True, ""
            error = result.error
        if attempt < _DELIVERY_ATTEMPTS - 1:
            sleep(_RETRY_SLEEP_S)
    return False, error


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def flush(
    specs: Sequence[Any],
    sink_for: SinkFactory,
    *,
    now: str,
    sleep: Callable[[float], None] = _default_sleep,
) -> FlushReport:
    """Diff the current inbox against the persisted snapshot, save the new snapshot BEFORE
    delivering (so a crash mid-delivery never re-emits), then deliver each event to every
    enabled channel with `notify` whose `on` matches. Never raises."""
    from docket.core import inbox as _inbox

    prev = read_state()
    inbox_view = _inbox.build_inbox(now=now)
    events, snapshot = diff_events(prev, inbox_view, now)
    _save_state(snapshot)

    if not events:
        return FlushReport(events=0)

    channels = [
        spec
        for spec in specs
        if getattr(spec, "enabled", False)
        and "notify" in (getattr(spec, "capabilities", None) or [])
    ]
    health = _load_health()
    delivered = 0
    failed = 0
    skipped = 0

    for notify_event in events:
        matching = [spec for spec in channels if _matches_on(spec, notify_event.kind)]
        for spec in matching:
            deliver = sink_for(spec)
            if deliver is None:
                skipped += 1
                continue
            cloud_event = make_event(
                notify_event.kind,
                notify_event.pod,
                notify_event.subject,
                render_data(notify_event.item, getattr(spec, "content", "minimal")),
                time=notify_event.time,
                version=notify_event.version,
            )
            secret = resolve_secret(spec)
            ok, error = _deliver_with_retry(deliver, spec, cloud_event, secret, sleep)
            entry = dict(health.get(spec.name) or {})
            if ok:
                delivered += 1
                entry["delivered"] = int(entry.get("delivered", 0)) + 1
                entry["lastOk"] = now
            else:
                failed += 1
                entry["failed"] = int(entry.get("failed", 0)) + 1
                entry["lastError"] = error
                entry["lastErrorAt"] = now
            health[spec.name] = entry

    if channels:
        _store.write_json(_cfg.CHANNELS_HEALTH_FILE, health)

    return FlushReport(events=len(events), delivered=delivered, failed=failed, skipped=skipped)
