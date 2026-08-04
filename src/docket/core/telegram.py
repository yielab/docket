"""docket-owned Telegram approval channel.

docket's own docs used to have to explicitly deny that Telegram was a real
approval channel: the OpenClaw daemon had its own native exec-approval
prompt, a Telegram reply answered *that* prompt, docket never saw it, and no
audit entry was written (a spike found no practical bridge). That daemon-side
gap is gone along with the daemon itself; this module closes the other
side by making docket itself the bot -- long-polling the Bot API
(``edges/adapters/telegram.py``, wire format only) and routing every message
through docket's own, already-existing approval store and pod-delegation
APIs. Nothing here reimplements approval logic: :func:`_handle_decision`
calls ``core.approval.approval_grant``/``approval_deny`` exactly the way
``cli/_approve.py``/``cli/_deny.py`` do, including the
``core.dispatch.resolve_waiting_approval`` follow-up.

## Security model -- read this before touching authorization

**A Telegram message is untrusted input from the open internet.** A bot
token is effectively a public endpoint: anyone who learns the bot's handle
can message it. Two independent checks stand between an inbound message and
anything happening:

1. **Sender authorization** (:func:`_authorize`). Only a chat that is
   *explicitly bound* to an agent via ``docket wire`` (``fleet.json``'s
   bindings -- ``core.fleet.find_binding``) may approve, deny, check status,
   or delegate anything. An unbound chat gets a plain refusal and the
   attempt is **audited** (``telegram.unauthorized``) -- never silently
   dropped, never granted. This is checked first, before any command is even
   parsed, so nothing below it ever runs for an unauthorized sender.
2. **Content screening** (:func:`_handle_delegate`). Message text that is
   about to become agent input (a delegated task) is run through the
   existing ``pre_input`` policy hook's ``prompt-injection`` policy, exactly
   the way ``core/mcp_tools.py`` screens a remote MCP server's tool
   descriptions before they reach a model -- the same untrusted-external-text
   threat class, the same evaluator, no new hook invented. ``block``/
   ``require_approval`` refuse before ``core.dispatch.enqueue_task`` is ever
   called (fail closed); ``warn``/``redact`` proceed with an audit trail.

**Fail closed, always.** An unknown sender, an unparseable command, a
missing/ambiguous token, or a blocked policy verdict all refuse -- none of
them ever default to granting or denying an approval. Approve/deny/status/
delegate are the only four actions this module recognizes; anything else is
an "unrecognized command" reply, not a guess at what the sender meant.

**The bot token is never handled here.** This module reads it once (from
``core.secrets``, the same store ``docket keys`` uses) to hand to
``edges/adapters/telegram.py``'s functions; it is never interpolated into an
audit entry, a trace payload, or a reply message. See that module's own
docstring for the wire-level half of this guarantee (the token never
surfaces in a returned error string either).

**Message bodies are not logged beyond what a human already sees.** The only
audit entries this module writes carry a chat id, an update id, and (for the
delegate path) a policy id/action -- never the raw message text. A human
reading ``docket audit`` sees that *something* was blocked or refused, not
the untrusted content that triggered it (the same discipline
``core.approval``'s ``action`` field already applies via ``_redact`` at
creation time).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import docket.config as _cfg
from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core import policy as _policy
from docket.core import secrets as _secrets
from docket.core.audit import audit_log
from docket.edges import store as _store
from docket.edges.adapters.telegram import GetUpdatesResult

__all__ = [
    "InboundMessage",
    "PollSummary",
    "TelegramActionResult",
    "handle_message",
    "poll_once",
]

# Command grammar. Deliberately narrow (four verbs, no inline keyboards, no
# rich UI) -- see the module docstring's "fail closed, always" note. The verb
# is matched independently of its argument (the trailing group is OPTIONAL on
# approve/deny/delegate) so `/approve` with a missing token is still
# recognized as an incomplete *approve* command -- and refused with a usage
# reply, per-verb -- rather than falling through to the generic "unrecognized
# command" bucket, which would blur "you typed nonsense" together with "you
# typed a real command wrong". `re.DOTALL` on delegate so a multi-line task
# description survives.
_APPROVE_RE = re.compile(r"^/approve(?:@\w+)?(?:\s+(\S+))?\s*$")
_DENY_RE = re.compile(r"^/deny(?:@\w+)?(?:\s+(\S+))?\s*$")
_STATUS_RE = re.compile(r"^/status(?:@\w+)?\s*$")
_DELEGATE_RE = re.compile(r"^/delegate(?:@\w+)?\s*(.*)$", re.DOTALL)

_UNRECOGNIZED_REPLY = (
    "Unrecognized command. Use:\n"
    "  /approve <token>\n"
    "  /deny <token>\n"
    "  /status\n"
    "  /delegate <task description>"
)


@dataclass(frozen=True)
class InboundMessage:
    """One Telegram message, already unwrapped from the update envelope by
    ``edges/adapters/telegram.py``. Pure data -- no wire format leaks in."""

    chat_id: str
    user_id: str
    text: str
    update_id: int


@dataclass(frozen=True)
class TelegramActionResult:
    """Outcome of handling one inbound message.

    ``reply`` (never containing raw untrusted input beyond what a human
    already typed to the bot themselves) is what the poll loop sends back,
    if anything. ``action`` buckets the outcome for tests/observability:
    ``"approve"``/``"deny"``/``"status"``/``"delegate"``/``"unauthorized"``/
    ``"unparseable"``.
    """

    ok: bool
    reply: str
    authorized: bool
    action: str = ""


def _authorize(chat_id: str) -> str | None:
    """Return the bound agent id for *chat_id*, or ``None`` if unbound.

    The one and only authorization check in this module -- see the module
    docstring's security model. Deliberately reads ``fleet.json`` fresh on
    every call (no caching) so a binding removed via ``docket unwire`` takes
    effect on the very next message, not after some cache TTL.
    """
    binding = _fleet.find_binding("telegram", chat_id)
    return binding.agent_id if binding is not None else None


def _lead_project(agent_id: str) -> str | None:
    """The pod project *agent_id* leads, or ``None`` if it isn't a pod Lead.

    Delegation only makes sense against a pod's task queue
    (``core.dispatch.enqueue_task`` requires one), and only the pod's Lead
    has one -- see ``core/pod.py``'s ``member_id``/``parse_member_id``. A
    binding to an org specialist (security/knowledge/manager) or a non-Lead
    pod member can still approve/deny/status; it simply cannot delegate.
    """
    project = _pod.pod_of(agent_id)
    if project is None:
        return None
    parsed = _pod.parse_member_id(agent_id, project)
    if parsed is None or parsed[0] != "lead":
        return None
    return project


def _approval_scope(agent_id: str) -> str:
    """The ``project`` value to scope a ``/status`` reply's approvals by.

    A pod Lead's binding scopes to its own project (never another pod's
    pending approvals); anything else scopes to its own agent id -- either
    way, a chat is never shown another agent's pending approvals just
    because it is authorized for one.
    """
    return _lead_project(agent_id) or agent_id


def _handle_decision(agent_id: str, token: str, *, grant: bool) -> TelegramActionResult:
    """Grant or deny *token*, mirroring ``cli/_approve.py``/``cli/_deny.py``
    exactly -- including the ``resolve_waiting_approval`` follow-up so a
    dispatch task actually blocked on this token resumes or fails for real,
    not just the approval record's own state.
    """
    action = "approve" if grant else "deny"
    if not token:
        return TelegramActionResult(False, f"Usage: /{action} <token>", True, action)

    channel = "telegram"
    try:
        if grant:
            _approval.approval_grant(token, channel=channel)
        else:
            _approval.approval_deny(token, channel=channel)
    except _approval.ApprovalNoop as exc:
        _dispatch.resolve_waiting_approval(token, "granted" if grant else "denied")
        return TelegramActionResult(False, exc.message, True, action)
    except _approval.ApprovalError as exc:
        return TelegramActionResult(False, str(exc), True, action)

    _dispatch.resolve_waiting_approval(token, "granted" if grant else "denied")
    verb = "granted" if grant else "denied"
    return TelegramActionResult(True, f"Approval {verb}: {token}", True, action)


def _handle_status(agent_id: str) -> TelegramActionResult:
    """List pending approvals scoped to *agent_id*'s project -- see
    :func:`_approval_scope`. Read-only; never mutates anything."""
    scope = _approval_scope(agent_id)
    pending = [d for d in _approval.list_pending() if d.get("project") == scope]
    if not pending:
        return TelegramActionResult(True, f"No pending approvals for '{scope}'.", True, "status")
    lines = [f"Pending approvals for '{scope}':"]
    for rec in pending:
        token = rec.get("token", "?")
        role = rec.get("role", "?")
        # `action` was already redacted at approval_create() time (core/approval.py's
        # own _redact) -- safe to echo back verbatim, same as `docket approve`'s listing.
        action_text = str(rec.get("action") or "")[:120]
        lines.append(f"  {token}  role={role}  {action_text}")
    return TelegramActionResult(True, "\n".join(lines), True, "status")


def _handle_delegate(agent_id: str, text: str) -> TelegramActionResult:
    """Queue *text* as a task for *agent_id*'s pod -- see the module
    docstring's content-screening section for the ``pre_input`` gate this
    runs before ``core.dispatch.enqueue_task`` is ever called.
    """
    if not text:
        return TelegramActionResult(False, "Usage: /delegate <task description>", True, "delegate")

    project = _lead_project(agent_id)
    if project is None:
        return TelegramActionResult(
            False,
            "This binding cannot delegate tasks (bound agent is not a pod Lead).",
            True,
            "delegate",
        )

    # The same precedent applied to inbound-channel text instead of a remote
    # MCP tool description: untrusted external text is screened through the
    # real pre_input evaluator, trusted=False, before it is treated as agent
    # input. block/require_approval refuse outright -- there is no per-message
    # human-approval channel for a chat message the way there is for a tool
    # call, so the safe default folds require_approval into the same
    # fail-closed outcome as block (identical reasoning to
    # core/mcp_tools.py's _screen_description).
    hit = _policy.policy_eval_detail("lead", "pre_input", text, trusted=False)
    if hit.action in ("block", "require_approval"):
        audit_log(
            "telegram.delegate_blocked",
            f"project={project!r} policy={hit.policy_id!r} action={hit.action}",
        )
        return TelegramActionResult(
            False, f"Message blocked by policy {hit.policy_id!r}.", True, "delegate"
        )
    if hit.action in ("warn", "redact"):
        audit_log(
            "telegram.delegate_warn",
            f"project={project!r} policy={hit.policy_id!r} action={hit.action}",
        )

    try:
        task = _dispatch.enqueue_task(project, text, "normal")
    except _dispatch.DispatchError as exc:
        return TelegramActionResult(False, str(exc), True, "delegate")

    return TelegramActionResult(
        True, f"Queued for pod '{project}': [{task['id']}]", True, "delegate"
    )


def handle_message(msg: InboundMessage) -> TelegramActionResult:
    """Route one inbound message to an action. The one entry point this
    module exposes to a caller (the poll loop) -- see the module docstring
    for the security model this function enforces.
    """
    agent_id = _authorize(msg.chat_id)
    if agent_id is None:
        audit_log("telegram.unauthorized", f"chat_id={msg.chat_id!r} update_id={msg.update_id}")
        return TelegramActionResult(
            False, "This chat is not wired to a docket agent.", False, "unauthorized"
        )

    text = msg.text.strip()

    m = _APPROVE_RE.match(text)
    if m:
        return _handle_decision(agent_id, m.group(1) or "", grant=True)
    m = _DENY_RE.match(text)
    if m:
        return _handle_decision(agent_id, m.group(1) or "", grant=False)
    if _STATUS_RE.match(text):
        return _handle_status(agent_id)
    m = _DELEGATE_RE.match(text)
    if m:
        return _handle_delegate(agent_id, m.group(1).strip())

    return TelegramActionResult(True, _UNRECOGNIZED_REPLY, True, "unparseable")


# ── the poll loop `serve.py` drives ─────────────────────────────────────────


@dataclass(frozen=True)
class PollSummary:
    """Outcome of one :func:`poll_once` call -- what `serve.py`'s loop logs."""

    ok: bool
    configured: bool
    processed: int = 0
    error: str = ""
    # Non-fatal: set when `_resolved_request_timeout` had to override a
    # misconfigured `TELEGRAM_REQUEST_TIMEOUT_S` (see that function). The
    # poll still proceeds with the corrected value -- this is surfaced so
    # `serve.py` can tell the operator their env var is not doing what they
    # think, not to abort a channel that is in fact working.
    warning: str = ""


def _load_token() -> str:
    return _secrets.load_secrets().get(_cfg.TELEGRAM_BOT_TOKEN_KEY, "").strip()


def _load_offset() -> int:
    raw = _store.read_json(_cfg.TELEGRAM_OFFSET_FILE)
    value = raw.get("offset") if isinstance(raw, dict) else None
    return int(value) if isinstance(value, int) else 0


def _save_offset(offset: int) -> None:
    _store.write_json(_cfg.TELEGRAM_OFFSET_FILE, {"offset": offset})


# The two operations `edges/adapters/telegram.py` implements. Injectable so
# this module's tests never touch the real Bot API or a socket -- the same
# shape `core/mcp_tools.py`'s `ListToolsFn`/`CallToolFn` use for the MCP
# client's SDK boundary.
GetUpdatesFn = Callable[..., GetUpdatesResult]
SendMessageFn = Callable[..., bool]


def _default_get_updates() -> GetUpdatesFn:
    from docket.edges.adapters import telegram as _client

    return _client.get_updates


def _default_send_message() -> SendMessageFn:
    from docket.edges.adapters import telegram as _client

    return _client.send_message


# The gap the built-in defaults (poll=25, request=35) leave above the poll
# wait -- applied when a configured `TELEGRAM_REQUEST_TIMEOUT_S` violates the
# invariant `config.py` documents on the pair (request MUST exceed poll).
# Room for the getUpdates round trip itself (connect + TLS + the response
# arriving after the server-side wait ends), not just the wait.
_REQUEST_TIMEOUT_MARGIN_S = 10.0


def _resolved_request_timeout() -> tuple[float, str]:
    """This process's own `getUpdates` socket timeout, honouring
    ``config.TELEGRAM_REQUEST_TIMEOUT_S`` but never letting it violate the
    invariant documented on that constant: it MUST exceed
    ``TELEGRAM_POLL_TIMEOUT_S``, or a legitimately empty long-poll reads as a
    local socket timeout instead of "nothing happened".

    Clamped up, not refused: unlike an unconfigured token (nothing this
    process can do about that), a bad pair of timeouts has an obvious safe
    correction, and refusing to poll at all would take the whole approval
    channel down over what is, for the operator, a one-line env var fix.
    Returns ``(value, warning)`` -- ``warning`` is empty when the configured
    value already satisfied the invariant and was used as-is.
    """
    poll = _cfg.TELEGRAM_POLL_TIMEOUT_S
    configured = _cfg.TELEGRAM_REQUEST_TIMEOUT_S
    if configured > poll:
        return configured, ""
    clamped = poll + _REQUEST_TIMEOUT_MARGIN_S
    warning = (
        f"TELEGRAM_REQUEST_TIMEOUT_S={configured}s does not exceed "
        f"TELEGRAM_POLL_TIMEOUT_S={poll}s -- an empty long-poll would look "
        f"like a local timeout; using {clamped}s for this process's own "
        "socket timeout instead. Fix TELEGRAM_REQUEST_TIMEOUT_S so it "
        "exceeds TELEGRAM_POLL_TIMEOUT_S."
    )
    return clamped, warning


def poll_once(
    *,
    get_updates: GetUpdatesFn | None = None,
    send_message: SendMessageFn | None = None,
) -> PollSummary:
    """Long-poll once, handle every returned message, advance the offset.

    ``get_updates``/``send_message`` are injectable (default: the real
    ``edges/adapters/telegram.py`` functions, resolved lazily) -- the same
    shape ``core/mcp_tools.py``'s ``load_mcp_tools`` uses, and how this
    module's own tests avoid any real network call.

    Never raises: an unconfigured bot (no stored token) or a network failure
    both come back as a typed, non-``ok``/non-``configured`` summary for the
    caller (``serve.py``'s poll loop) to log and back off on, exactly like
    ``edges/adapters/telegram.py``'s own functions never raise for a
    transport failure.
    """
    token = _load_token()
    if not token:
        return PollSummary(ok=True, configured=False)

    get_updates_fn = get_updates if get_updates is not None else _default_get_updates()
    send_message_fn = send_message if send_message is not None else _default_send_message()

    offset = _load_offset()
    request_timeout, timeout_warning = _resolved_request_timeout()
    result = get_updates_fn(
        token,
        offset=offset,
        timeout=_cfg.TELEGRAM_POLL_TIMEOUT_S,
        request_timeout=request_timeout,
    )
    if not result.ok:
        return PollSummary(ok=False, configured=True, error=result.error, warning=timeout_warning)

    processed = 0
    max_update_id = offset - 1
    for update in result.updates:
        max_update_id = max(max_update_id, update.update_id)
        msg = InboundMessage(
            chat_id=update.chat_id,
            user_id=update.user_id,
            text=update.text,
            update_id=update.update_id,
        )
        outcome = handle_message(msg)
        processed += 1
        if outcome.reply:
            send_message_fn(token, update.chat_id, outcome.reply)

    if result.updates:
        _save_offset(max_update_id + 1)

    return PollSummary(ok=True, configured=True, processed=processed, warning=timeout_warning)
