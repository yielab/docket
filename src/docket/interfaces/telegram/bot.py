"""docket-owned Telegram approval channel.

docket owns the complete approval path. This module makes docket itself the
bot -- long-polling the Bot API
(``interfaces/telegram/client.py``, wire format only) and routing every message
through docket's own, already-existing approval store and pod-delegation
APIs. Nothing here reimplements approval logic: :func:`_handle_decision`
calls ``tasks.application.escalations.resolve_approval_token`` exactly the way
``interfaces/cli/commands/task.py``'s approve and deny do, which grants or denies the
approval and runs the ``resolve_waiting_approval`` follow-up.

## Security model -- read this before touching authorization

**A Telegram message is untrusted input from the open internet.** A bot
token is effectively a public endpoint: anyone who learns the bot's handle
can message it. Two independent checks stand between an inbound message and
anything happening:

1. **Sender authorization** (:func:`_authorize`). Only a chat that is
   *explicitly bound* to an agent via ``docket setup notify bind`` (``fleet.json``'s
   bindings -- ``teams.fleet.find_binding``) may approve, deny, check status,
   or delegate anything. An unbound chat gets a plain refusal and the
   attempt is **audited** (``telegram.unauthorized``) -- never silently
   dropped, never granted. This is checked first, before any command is even
   parsed, so nothing below it ever runs for an unauthorized sender.
2. **Content screening** (:func:`_handle_delegate`). Message text that is
   about to become agent input (a delegated task) is run through the
   existing ``pre_input`` policy hook's ``prompt-injection`` policy, exactly
   the way ``agent/tools/mcp_tools.py`` screens a remote MCP server's tool
   descriptions before they reach a model -- the same untrusted-external-text
   threat class, the same evaluator, no new hook invented. ``block``/
   ``require_approval`` refuse before ``tasks.application.queue.enqueue_task_once`` is ever
   called (fail closed); ``warn``/``redact`` proceed with an audit trail.

**Fail closed, always.** An unknown sender, an unparseable command, a
missing/ambiguous token, or a blocked policy verdict all refuse -- none of
them ever default to granting or denying an approval. Approve/deny/status/
delegate/answer are the only five operational actions this module recognizes.
The inert ``/wire <code>`` setup handshake only confirms a binding that the
CLI already created; anything else is an "unrecognized command" reply, not a
guess at what the sender meant.

``/answer <id> <option|text>`` settles an escalation (a parked question, or an approval by its
option id) through the same ``tasks.application.escalations.resolve`` every other surface (CLI,
HTTP, MCP) calls -- see :func:`_handle_answer`. It is the one verb whose *outbound*
counterpart also exists: an operator who enables the ``telegram`` channel
document (``kind: channel``, dialect ``telegram``) gets a *push* to every
chat id it lists in ``actors`` when a task needs input, through
``operator/adapters/telegram.py::deliver`` -- a separate, explicitly
operator-configured path, not a change to this module's own reply-only
behaviour (see the module-level ``send_message`` call-site pin in
``tests/integration/test_telegram_channel.py``).

**The bot token is never handled here.** This module reads it once (from
``governance.secrets``, the same store ``docket setup provider`` uses) to hand to
``interfaces/telegram/client.py``'s functions; it is never interpolated into an
audit entry, a trace payload, or a reply message. See that module's own
docstring for the wire-level half of this guarantee (the token never
surfaces in a returned error string either).

**Message bodies are not logged beyond what a human already sees.** The only
audit entries this module writes carry a chat id, an update id, and (for the
delegate path) a policy id/action -- never the raw message text. A human
reading ``docket log`` sees that *something* was blocked or refused, not
the untrusted content that triggered it (the same discipline
``governance.approval``'s ``action`` field already applies via ``_redact`` at
creation time).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from docket.governance import approval as _approval
from docket.governance import policy as _policy
from docket.governance import secrets as _secrets
from docket.governance.audit import audit_log
from docket.interfaces.telegram import client as _client
from docket.interfaces.telegram.client import GetUpdatesResult
from docket.kernel import clock as _clock
from docket.kernel import operator_contract as _oc
from docket.kernel.errors import DispatchError, DocketError
from docket.kernel.home import current_home
from docket.operator import (
    build_inbox,
    escalation_view,
    escalation_views,
    ids_line,
    question_escalation,
    render_escalation,
)
from docket.platform import read_escalation, read_json, write_json
from docket.tasks.application import queue as _queue
from docket.tasks.application.escalations import resolve, resolve_approval_token, resolve_question
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.resolution import EscalationRefused
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

__all__ = [
    "InboundMessage",
    "PollSummary",
    "TelegramActionResult",
    "TelegramGroup",
    "WireDiscoveryResult",
    "discover_wire_groups",
    "handle_message",
    "poll_once",
    "wire_discovery_configured",
]

# Command grammar. Deliberately narrow (five operational verbs plus the inert
# setup handshake; no inline keyboards, no
# rich UI) -- see the module docstring's "fail closed, always" note. The verb
# is matched independently of its argument (the trailing group is OPTIONAL on
# approve/deny/delegate) so `/approve` with a missing token is still
# recognized as an incomplete *approve* command -- and refused with a usage
# reply, per-verb -- rather than falling through to the generic "unrecognized
# command" bucket, which would blur "you typed nonsense" together with "you
# typed a real command wrong". `re.DOTALL` on delegate/answer so a multi-line
# task description/answer survives.
_APPROVE_RE = re.compile(r"^/approve(?:@\w+)?(?:\s+(\S+)(?:\s+(task))?)?\s*$")
_DENY_RE = re.compile(r"^/deny(?:@\w+)?(?:\s+(\S+))?\s*$")
_STATUS_RE = re.compile(r"^/status(?:@\w+)?\s*$")
_DELEGATE_RE = re.compile(r"^/delegate(?:@\w+)?(?:\s+(.*))?$", re.DOTALL)
_ANSWER_RE = re.compile(r"^/answer(?:@\w+)?\s+(\S+)\s+(.+)$", re.DOTALL)
# Matches `/answer` on its own or with only a task id -- a recognized verb with a missing
# argument, per the same "usage reply, not unparseable" rule as approve/deny above. Checked
# only once `_ANSWER_RE` itself has failed to match.
_ANSWER_PREFIX_RE = re.compile(r"^/answer(?:@\w+)?\b")
_WIRE_RE = re.compile(r"^/wire(?:@\w+)?\s+\S+\s*$", re.IGNORECASE)

_ANSWER_USAGE = "Usage: /answer <id> <option or answer text>"
_PROMPT_MAX = 500

_UNRECOGNIZED_REPLY = (
    "Unrecognized command. Use:\n"
    "  /approve <token> [task]\n"
    "  /deny <token>\n"
    "  /status\n"
    "  /delegate <task description>\n"
    "  /answer <id> <option or answer text>"
)


@dataclass(frozen=True)
class InboundMessage:
    """One Telegram message, already unwrapped from the update envelope by
    ``interfaces/telegram/client.py``. Pure data -- no wire format leaks in."""

    chat_id: str
    user_id: str
    text: str
    update_id: int


@dataclass(frozen=True)
class TelegramActionResult:
    """Outcome of handling one inbound message. ``reply`` never contains raw
    untrusted input beyond what the sender already typed; ``action`` buckets
    it (approve/deny/status/delegate/answer/wire/unauthorized/unparseable)."""

    ok: bool
    reply: str
    authorized: bool
    action: str = ""


@dataclass(frozen=True)
class TelegramGroup:
    """A Telegram group found during the guided ``setup notify bind`` flow."""

    chat_id: str
    title: str = ""


@dataclass(frozen=True)
class WireDiscoveryResult:
    """Read-only result of looking for a one-time ``/wire`` challenge."""

    ok: bool
    configured: bool
    groups: tuple[TelegramGroup, ...] = ()
    error: str = ""


def _authorize(chat_id: str) -> str | None:
    """Return the bound agent id for *chat_id*, or ``None`` if unbound. The
    one and only authorization check in this module. Reads ``fleet.json``
    fresh every call (no caching) so an unwire takes effect immediately."""
    binding = _fleet.find_binding("telegram", chat_id)
    return binding.agent_id if binding is not None else None


def _lead_project(agent_id: str) -> str | None:
    """The pod project *agent_id* leads, or ``None`` if it isn't a pod Lead.
    Only a pod Lead has a task queue to delegate against; a non-Lead pod
    member can still approve/deny/status but not delegate."""
    project = _pod.pod_of(agent_id)
    if project is None:
        return None
    parsed = _pod.parse_member_id(agent_id, project)
    if parsed is None or parsed[0] != "lead":
        return None
    return project


def _approval_scope(agent_id: str) -> str:
    """The ``project`` value to scope a ``/status`` reply's approvals by. A
    pod Lead scopes to its own project; anything else scopes to its own
    agent id -- a chat is never shown another agent's pending approvals."""
    return _lead_project(agent_id) or agent_id


def _decision_pod_refusal(agent_id: str, token: str, action: str) -> TelegramActionResult | None:
    """A refusal when *token* is an approval of a pod other than the chat's bound pod, else
    ``None``. An unreadable token is left to the transition, which reports it as not found."""
    try:
        owner = str(_approval.approval_get(token).get("project", ""))
    except _approval.ApprovalError:
        return None
    bound = _pod.pod_of(agent_id) or agent_id
    if owner == bound:
        return None
    audit_log("telegram.cross_pod_refused", f"agent={agent_id!r} token={token} action={action}")
    return TelegramActionResult(
        False, f"Approval {token} does not belong to this chat's pod.", True, action
    )


def _handle_decision(
    agent_id: str, token: str, *, grant: bool, task_wide: bool = False
) -> TelegramActionResult:
    """Grant or deny *token* as ``interfaces/cli/commands/task.py``'s approve and deny do: the
    approval's escalation is resolved, so a dispatch task blocked on this token actually resumes
    or fails, not just its record."""
    action = "approve" if grant else "deny"
    if not token:
        return TelegramActionResult(False, f"Usage: /{action} <token>", True, action)

    refusal = _decision_pod_refusal(agent_id, token, action)
    if refusal is not None:
        return refusal

    option = ("approve_task" if task_wide else "approve_once") if grant else "deny"
    try:
        note = resolve_approval_token(token, option, channel="telegram", actor="telegram")
    except DocketError as exc:
        return TelegramActionResult(False, exc.message, True, action)

    verb = "granted" if grant else "denied"
    reply = f"Approval {verb}: {token}" + (f"\n{note}" if note else "")
    return TelegramActionResult(True, reply, True, action)


def _question_lines(item: _oc.TaskView, escalations: list[_oc.EscalationView]) -> list[str]:
    """What a chat needs to answer a parked question: the question, the option ids and the reply
    to send. The operator asked from their own bound chat, so the prompt is shown (the
    ``conversation`` level) and the ids are never withheld."""
    escalation = question_escalation(escalations, item.pod, item.id)
    if escalation is None:
        return []
    rendered = render_escalation(escalation, "conversation")
    lines = [f"    Q: {(rendered.prompt or '')[:_PROMPT_MAX]}"]
    if rendered.options:
        lines.append(f"    options: {ids_line(rendered.options)}")
        lines.append(f"    reply: /answer {item.id} <option>")
    else:
        lines.append(f"    reply: /answer {item.id} <your answer>")
    return lines


def _handle_status(agent_id: str) -> TelegramActionResult:
    """Render the derived inbox (:func:`docket.operator.inbox.build_inbox`) scoped to *agent_id*'s
    project -- see :func:`_approval_scope`. Needs-you items first. Read-only; never mutates
    anything."""
    scope = _approval_scope(agent_id)
    now = _clock.iso()
    view = build_inbox(now=now)
    needs_you = [item for item in view.needs_you if item.pod == scope]
    failed = [t for t in view.failed if t.pod == scope]
    if not needs_you and not failed:
        return TelegramActionResult(True, f"Nothing needs you in '{scope}'.", True, "status")

    lines = [f"Needs you in '{scope}':"] if needs_you else []
    for item in needs_you:
        if isinstance(item, _oc.ApprovalView):
            # `action` was already redacted at approval_create() time (governance/approval.py's
            # own _redact) -- safe to echo back verbatim, same as `docket inbox`'s listing.
            action_text = str(item.action or "")[:120]
            lines.append(f"  approval {item.token}  role={item.role}  {action_text}")
        else:
            label = (item.description or item.reason or "")[:120]
            lines.append(f"  task {item.id}  status={item.status}  {label}")
            lines.extend(_question_lines(item, view.escalations))
    if failed:
        lines.append("Failed:")
        for t in failed:
            lines.append(f"  task {t.id}  {(t.reason or '')[:120]}")
    return TelegramActionResult(True, "\n".join(lines), True, "status")


def _handle_delegate(agent_id: str, text: str) -> TelegramActionResult:
    """Queue *text* as a task for *agent_id*'s pod. Runs the ``pre_input``
    content-screening gate (see module docstring) before
    ``tasks.application.queue.enqueue_task_once`` is ever called."""
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
    # agent/tools/mcp_tools.py's _screen_description).
    hit = _policy.policy_eval_detail("lead", "pre_input", text, trusted=False, project=project)
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
        task, _created = _queue.enqueue_task_once(project, text, "normal", channel="telegram")
    except DispatchError as exc:
        return TelegramActionResult(False, str(exc), True, "delegate")

    return TelegramActionResult(True, f"Queued for pod '{project}': [{task.id}]", True, "delegate")


def _options_reply(view: _oc.EscalationView) -> str:
    """The ids a reply may name, as `/status` prints them."""
    rendered = render_escalation(view, "conversation")
    return f"options: {ids_line(rendered.options)}"


def _text_content(properties: dict[str, Any], text: str, ref: str) -> dict[str, Any] | str:
    """The content *text* makes for a one-property schema, else the reply that refuses it: a single
    chat message cannot be split across fields."""
    if len(properties) != 1:
        return (
            "This question has more than one field -- answer it with "
            f"'docket task answer {ref} --field name=value ...'."
        )
    (prop_name,) = properties
    return {prop_name: text}


def _settle(
    project: str, task_id: str, escalation_id: str | None, option: str | None, content: Any
) -> TelegramActionResult:
    """Resolve what the chat answered and say how it went; an escalation id wins over the task."""
    try:
        if escalation_id is not None:
            resolved = resolve(escalation_id, option, content, by="telegram", channel="telegram")
            reply = f"Resolved {escalation_id}." + (f"\n{resolved.note}" if resolved.note else "")
        else:
            resolve_question(
                project, task_id, "accept", content, channel="telegram", actor="telegram"
            )
            reply = f"Answered task {task_id}."
    except EscalationRefused as exc:
        audit_log(
            "telegram.answer_blocked",
            f"project={project!r} task={task_id!r} policy={exc.policy_id!r}",
        )
        return TelegramActionResult(
            False, f"Answer blocked by policy {exc.policy_id!r}.", True, "answer"
        )
    except DocketError as exc:
        return TelegramActionResult(False, exc.message, True, "answer")
    return TelegramActionResult(True, reply, True, "answer")


def _answer_escalation(agent_id: str, escalation_id: str, text: str) -> TelegramActionResult:
    """`/answer esc-... <option|text>`: an option id resolves it; anything else resolves a question
    with no options (text filling its one property) and otherwise lists the ids."""
    bound = _pod.pod_of(agent_id) or agent_id
    record = read_escalation(escalation_id)
    if record is None or record.pod != bound:
        return TelegramActionResult(
            False, f"Escalation {escalation_id!r} not found in pod {bound!r}.", True, "answer"
        )
    view = escalation_view(record)
    # A settled escalation takes the same path, so that `resolve` says why it is refused.
    if view.state != "pending" or text in view.affordances.options:
        return _settle(record.pod, record.task, record.id, text, None)
    offers_options = any(o != "decline" for o in view.affordances.options)
    if offers_options or record.kind in ("approval", "gate", "check_changed"):
        return TelegramActionResult(False, _options_reply(view), True, "answer")
    content = _text_content(
        (record.requested_schema or {}).get("properties", {}), text, record.task
    )
    if isinstance(content, str):
        return TelegramActionResult(False, content, True, "answer")
    return _settle(record.pod, record.task, record.id, None, content)


def _handle_answer(agent_id: str, ref: str, text: str) -> TelegramActionResult:
    """Accept *text* as the answer to the escalation or parked question *ref* names: an option id
    picks it, a one-property schema fills from the message, text for a question with options
    replies with their ids, and a multi-property schema is refused with the CLI guidance."""
    if _oc.is_escalation_id(ref):
        return _answer_escalation(agent_id, ref, text)
    project = _lead_project(agent_id)
    if project is None:
        return TelegramActionResult(
            False,
            "This binding cannot answer tasks (bound agent is not a pod Lead).",
            True,
            "answer",
        )

    task = next((t for t in TaskRepository.for_pod(project).list() if t.id == ref), None)
    if task is None:
        return TelegramActionResult(
            False, f"Task {ref!r} not found in pod {project!r}.", True, "answer"
        )
    question = task.question
    if question is None:
        return TelegramActionResult(False, f"Task {ref!r} has no pending question.", True, "answer")
    option_ids = (
        {o.id for o in question.options} if isinstance(question, _oc.QuestionV11) else set()
    )
    if text in option_ids:
        return _settle(project, ref, None, None, {"optionId": text})
    if option_ids:
        asked = question_escalation(escalation_views(pod=project, task=ref), project, ref)
        listing = (
            _options_reply(asked)
            if asked is not None
            else "options: " + ", ".join(sorted(option_ids))
        )
        return TelegramActionResult(False, listing, True, "answer")
    content = _text_content(question.requested_schema.get("properties", {}), text, ref)
    if isinstance(content, str):
        return TelegramActionResult(False, content, True, "answer")
    return _settle(project, ref, None, None, content)


def handle_message(
    msg: InboundMessage, *, unauthorized: dict[str, list[int]] | None = None
) -> TelegramActionResult:
    """Route one inbound message; enforces the module's security model.
    ``unauthorized`` collects refused update ids instead of auditing each one."""
    agent_id = _authorize(msg.chat_id)
    if agent_id is None:
        if unauthorized is not None:
            unauthorized.setdefault(msg.chat_id, []).append(msg.update_id)
        else:
            audit_log("telegram.unauthorized", f"chat_id={msg.chat_id!r} update_id={msg.update_id}")
        return TelegramActionResult(
            False, "This chat is not wired to a docket agent.", False, "unauthorized"
        )

    text = msg.text.strip()

    m = _APPROVE_RE.match(text)
    if m:
        return _handle_decision(
            agent_id, m.group(1) or "", grant=True, task_wide=m.group(2) == "task"
        )
    m = _DENY_RE.match(text)
    if m:
        return _handle_decision(agent_id, m.group(1) or "", grant=False)
    if _STATUS_RE.match(text):
        return _handle_status(agent_id)
    m = _DELEGATE_RE.match(text)
    if m:
        return _handle_delegate(agent_id, (m.group(1) or "").strip())
    m = _ANSWER_RE.match(text)
    if m:
        return _handle_answer(agent_id, m.group(1), m.group(2).strip())
    if _ANSWER_PREFIX_RE.match(text):
        return TelegramActionResult(False, _ANSWER_USAGE, True, "answer")
    if _WIRE_RE.match(text):
        return TelegramActionResult(
            True, f"Telegram setup complete for '{agent_id}'.", True, "wire"
        )

    return TelegramActionResult(True, _UNRECOGNIZED_REPLY, True, "unparseable")


# ── the poll loop `interfaces/http/server.py` drives ─────────────────────────────────────────


@dataclass(frozen=True)
class PollSummary:
    """Outcome of one :func:`poll_once` call -- what `interfaces/http/server.py`'s loop logs."""

    ok: bool
    configured: bool
    processed: int = 0
    error: str = ""
    # Non-fatal: set when `_resolved_request_timeout` had to override a
    # misconfigured `TELEGRAM_REQUEST_TIMEOUT_S` (see that function). The
    # poll still proceeds with the corrected value -- this is surfaced so
    # `interfaces/http/server.py` can tell the operator their env var is not doing what they
    # think, not to abort a channel that is in fact working.
    warning: str = ""


def load_token() -> str:
    return _secrets.secret_value(current_home().telegram_bot_token_key) or ""


def wire_discovery_configured() -> bool:
    """Whether guided Telegram discovery can use a stored bot token."""

    return bool(load_token())


def _load_offset() -> int:
    raw = read_json(current_home().telegram_offset_file)
    value = raw.get("offset") if isinstance(raw, dict) else None
    return int(value) if isinstance(value, int) else 0


def _save_offset(offset: int) -> None:
    write_json(current_home().telegram_offset_file, {"offset": offset})


# The two operations `interfaces/telegram/client.py` implements. Injectable so
# this module's tests never touch the real Bot API or a socket -- the same
# shape `agent/tools/mcp_tools.py`'s `ListToolsFn`/`CallToolFn` use for the MCP
# client's SDK boundary.
GetUpdatesFn = Callable[..., GetUpdatesResult]
SendMessageFn = Callable[..., bool]


def _default_get_updates() -> GetUpdatesFn:
    return _client.get_updates


def _default_send_message() -> SendMessageFn:
    return _client.send_message


def discover_wire_groups(
    challenge: str,
    *,
    get_updates: GetUpdatesFn | None = None,
) -> WireDiscoveryResult:
    """Find group messages matching ``/wire <challenge>`` exactly. Read-only:
    starts at the poller's durable offset but never advances it, routes, or
    replies; the one-time challenge stops stale activity becoming a binding."""

    token = load_token()
    if not token:
        return WireDiscoveryResult(ok=True, configured=False)

    get_updates_fn = get_updates if get_updates is not None else _default_get_updates()
    result = get_updates_fn(
        token,
        offset=_load_offset(),
        timeout=2,
        request_timeout=12.0,
    )
    if not result.ok:
        return WireDiscoveryResult(ok=False, configured=True, error=result.error)

    command = re.compile(rf"/wire(?:@\w+)?\s+{re.escape(challenge)}", re.IGNORECASE)
    found: dict[str, TelegramGroup] = {}
    for update in result.updates:
        if update.chat_type not in {"group", "supergroup"}:
            continue
        if command.fullmatch(update.text.strip()) is None:
            continue
        found[update.chat_id] = TelegramGroup(update.chat_id, update.chat_title)

    return WireDiscoveryResult(ok=True, configured=True, groups=tuple(found.values()))


# The gap the built-in defaults (poll=25, request=35) leave above the poll
# wait -- applied when a configured `TELEGRAM_REQUEST_TIMEOUT_S` violates the
# invariant `Home.telegram_request_timeout_s` documents on the pair (request MUST exceed poll).
# Room for the getUpdates round trip itself (connect + TLS + the response
# arriving after the server-side wait ends), not just the wait.
_REQUEST_TIMEOUT_MARGIN_S = 10.0


def _resolved_request_timeout() -> tuple[float, str]:
    """This process's own `getUpdates` socket timeout; must exceed
    ``TELEGRAM_POLL_TIMEOUT_S`` (see kernel/home.py) or an empty long-poll misreads
    as a local timeout.

    Clamped up, not refused: a bad pair has an obvious safe fix, and refusing
    would take the whole approval channel down over a one-line env var
    mistake. Returns ``(value, warning)``; warning is empty when the
    configured value already satisfied the invariant.
    """
    poll = current_home().telegram_poll_timeout_s
    configured = current_home().telegram_request_timeout_s
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
    ``interfaces/telegram/client.py`` functions) so tests avoid any network call.

    Never raises: an unconfigured bot or a network failure both come back as
    a typed, non-``ok``/non-``configured`` summary for the caller to log and
    back off on, instead of raising.
    """
    token = load_token()
    if not token:
        return PollSummary(ok=True, configured=False)

    get_updates_fn = get_updates if get_updates is not None else _default_get_updates()
    send_message_fn = send_message if send_message is not None else _default_send_message()

    offset = _load_offset()
    request_timeout, timeout_warning = _resolved_request_timeout()
    result = get_updates_fn(
        token,
        offset=offset,
        timeout=current_home().telegram_poll_timeout_s,
        request_timeout=request_timeout,
    )
    if not result.ok:
        return PollSummary(ok=False, configured=True, error=result.error, warning=timeout_warning)

    processed = 0
    max_update_id = offset - 1
    unauthorized: dict[str, list[int]] = {}
    for update in result.updates:
        max_update_id = max(max_update_id, update.update_id)
        msg = InboundMessage(
            chat_id=update.chat_id,
            user_id=update.user_id,
            text=update.text,
            update_id=update.update_id,
        )
        try:
            outcome = handle_message(msg, unauthorized=unauthorized)
            if outcome.reply:
                send_message_fn(token, update.chat_id, outcome.reply)
        except Exception as exc:
            # One update that raises must not pin the poller on this batch forever:
            # record it, skip it, and let the offset move past it.
            audit_log(
                "telegram.update_failed",
                f"chat_id={update.chat_id} update_id={update.update_id} error={type(exc).__name__}",
            )
        processed += 1

    for chat_id, update_ids in unauthorized.items():
        audit_log(
            "telegram.unauthorized",
            f"chat_id={chat_id!r} update_id={update_ids[-1]} count={len(update_ids)}",
        )

    if result.updates:
        _save_offset(max_update_id + 1)

    return PollSummary(ok=True, configured=True, processed=processed, warning=timeout_warning)
