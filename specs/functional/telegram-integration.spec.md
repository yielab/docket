# Telegram Integration Specification

**Version**: 2.5.0
**Status**: Implemented. Docket owns the whole channel: `docket setup notify enable telegram
--chat <id>` connects it in one operation (token, allowed chats, a binding per pod Lead in
`fleet.json`), `docket setup notify bind`/`unbind` handle the per-pod exception (guided
discovery from a one-time `/wire <code>` message, manual entry as a fallback), and `docket serve
--telegram` long-polls the Telegram Bot API (`edges/adapters/telegram.py`, stdlib `urllib`, zero
new dependencies) and routes `/approve`, `/deny`, `/status`, `/delegate` through docket's
*existing* approval store and pod-delegation APIs (`core/telegram.py`). Telegram is now a real,
fourth docket approval channel alongside CLI/HTTP/MCP — every grant/deny through it writes an
`audit_log()` entry tagged `channel="telegram"`, exactly like the other three.
**Last Updated**: 2026-09-29

## Purpose

This specification defines two things: (1) how docket records which Telegram peer/group maps to
which agent (`docket setup notify enable telegram` and `bind`/`unbind`), and (2) how docket's
own bot (`docket serve --telegram`) turns an inbound message on a bound chat into an approve/
deny/status/delegate action against Docket's real state and approval mechanism.

## Scope

This specification covers:

- Recording a Telegram peer/group ID binding for an agent (`docket setup notify bind`/`unbind`)
- Connecting Telegram in one step (`docket setup notify enable telegram`)
- The binding's storage in `fleet.json` (`core/fleet.py`) and its role as the channel's **entire
  authorization boundary** (see Security below)
- The bot's wire protocol: `getUpdates` long-poll, `sendMessage` reply (`edges/adapters/
  telegram.py`)
- The command grammar and routing to docket's existing approval/dispatch APIs
  (`core/telegram.py`)
- `docket serve --telegram`'s poll loop and its degrade-gracefully behavior when unconfigured

This specification does NOT cover:

- Tool-approval gate semantics or the approval record's own state machine (see
  security-gates.spec.md, `core/approval.py`)
- Audit log shape/tamper-evidence (see audit.spec.md)
- Webhook mode, inline keyboards, or any rich UI — out of scope by design (long-poll only, plain
  text only; see Non-Goals)

## Security model (read this before anything else)

A Telegram message is untrusted input from the open internet, and a bot token is effectively a
public endpoint. Two independent checks stand between an inbound message and anything happening:

1. **Sender authorization.** Only a chat id with an existing `fleet.json` binding
   (`core.fleet.find_binding("telegram", chat_id)`) may approve, deny, check status, or delegate
   anything. **The binding recorded by `docket setup notify bind` (or `enable telegram`) is the entire authorization boundary** —
   there is no second allowlist, no per-user check beyond it. An unbound chat's message is
   refused (`"This chat is not wired to a docket agent."`) and the attempt is audited
   (`telegram.unauthorized`, carrying the chat id and update id, never the message body) —
   never silently dropped, never granted.
2. **Content screening.** Text that is about to become agent input (a `/delegate` task
   description) is run through the existing `pre_input` policy hook (the `prompt-injection`
   policy, `trusted=False`) before `core.dispatch.enqueue_task` is ever called — the same
   evaluator and the same untrusted-external-text reasoning `core/mcp_tools.py` (P19-10) applies
   to a remote MCP server's tool descriptions. `block`/`require_approval` refuse outright (there
   is no per-message human-approval channel for a chat message the way there is for a tool
   call); `warn`/`redact` proceed with an audit trail.

Fail closed always: an unknown sender, an unparseable command, a missing/ambiguous token, or a
blocked policy verdict never default to granting or denying anything.

## Requirements

### Connecting Telegram (docket setup notify)

1. For Telegram, when `TELEGRAM_BOT_TOKEN` is configured, **MUST** offer guided discovery before
   manual entry: show a short one-time `/wire <code>` command, read Telegram updates after the
   operator confirms it was sent, and accept only a group/supergroup message whose command and
   code match exactly. The operator **MUST NOT** need `curl`, JSON inspection, or prior knowledge
   of Telegram's numeric chat id.
2. Discovery **MUST NOT** acknowledge, route, or reply to any Telegram update; the normal poller
   remains responsible for the durable offset and for processing messages. A transport error, a
   missing token, or no matching message **MUST** fall back to manual ID entry with a useful
   explanation rather than inventing a binding.
3. **MUST** write a binding mapping the discovered or entered peer ID to the target agent into `fleet.json`
   (`core/fleet.py`'s `upsert_binding`).
4. **MUST** state plainly that the binding is the channel's entire authorization boundary: anyone
   who can post in the bound chat can act as that agent's operator once the bot is running.
5. **SHOULD** show an existing binding for the agent, if any, before prompting for a new one.
6. **MUST** refuse off a TTY when no `--chat` is supplied, naming `--chat`; it never opens an agent picker.
7. **MUST NOT** invent a binding from empty manual input; an empty entry **MUST** abort cleanly
   (exit 0, "Aborted").
8. `enable telegram --chat <id> [--token T] [--test]` **MUST** be one operation: it stores the bot
   token (`--token`, then `TELEGRAM_BOT_TOKEN` in the environment, then a hidden prompt on a TTY;
   a stored token is kept when none is given), enables the `telegram` channel with `actors` set to
   the chat ids, upserts one binding per pod Lead (to the first chat id), and prints what it wrote
   in each store. Every precondition (a chat id, a token) **MUST** be checked before the first
   write, so a refusal writes nothing.
9. `enable telegram` **MUST NOT** send any message unless `--test` is passed; with `--test` it
   sends exactly one. `core/telegram.py` still never messages a wired chat first.
10. `show telegram` **MUST** list the bindings in `fleet.json` and the open Telegram conversations
    in `docket-conversations.json`; `bind` seeds the conversation registry entry.

### Unbinding a group (docket setup notify unbind)

1. **MUST** remove the binding for the given agent from `fleet.json`. Because the binding is the
   authorization boundary, this is the operative "revoke access" action for the channel — it
   takes effect on the very next inbound message (no caching).
2. **SHOULD** succeed silently (idempotent) if no binding exists.

### The bot (docket serve --telegram)

1. **MUST** be opt-in (`docket serve --telegram`), matching the existing `--dispatch` flag's
   shape — a real externally-reachable channel is not something `docket serve` starts
   unconditionally.
2. **MUST** read the bot token from docket's own secrets store (`docket setup notify
   enable telegram`) — never a bespoke config file, never a CLI argument (which would land in
   shell history).
3. **MUST** degrade to an idle, periodically-retried wait — never crash `docket serve` — when no
   token is configured. The same degrade-not-crash contract applies to a Telegram-side transport
   failure (network unreachable, bad token, malformed response).
4. **MUST** long-poll (`getUpdates`), never operate in webhook mode.
5. **MUST** persist the last-processed `update_id` (`TELEGRAM_OFFSET_FILE`) so a `docket serve`
   restart resumes forward rather than Telegram redelivering the whole backlog.
6. **MUST NOT** let an unexpected exception in one poll iteration crash the loop or the server —
   caught, printed, and the loop continues (D-17: a bare `contextlib.suppress(Exception)` around
   the delegate path's `core.dispatch.enqueue_task` call is banned; the exception must be
   *visible*, not merely survived).

### Command grammar (core/telegram.py)

1. **MUST** recognize four operational verbs: `/approve <token>`, `/deny <token>`, `/status`,
   `/delegate <task description>`, plus the inert `/wire <code>` setup handshake. `/wire` never
   creates or changes a binding inside the bot; after the CLI has bound the group, the normal
   poller acknowledges the retained setup message with a plain confirmation. No inline keyboards,
   no Markdown/HTML rich replies — a plain text reply is the entire UI surface.
1a. `/approve <token> task` **MUST** behave as `/approve <token>` and also choose the
   `approve_task` option (`approval_set_option` before the grant), so a parked pod approval
   covers the same exact call for the rest of its task (operator-loop requirement 5a). Any other
   trailing word is unparseable. The chat authorisation is unchanged and the module stays
   inbound-only.
2. **MUST** route `/approve`/`/deny` through the *existing* `core.approval.approval_grant`/
   `approval_deny` (`channel="telegram"`) followed by `core.dispatch.resolve_waiting_approval` —
   the identical sequence `cli/_approve.py`/`cli/_deny.py` already use. This module never
   reimplements approval state transitions.
3. **MUST** render `/status` from the derived operator inbox (`core.inbox.build_inbox`,
   `operator-loop.spec.md` requirement area 5), scoped to the bound agent's own project (a pod
   Lead's own pod; an org specialist's own agent id) — never another agent's tasks or pending
   approvals. The reply lists needs-you items (waiting/blocked tasks and pending approvals not
   already carried by a task) first, then failed tasks; it stays plain text.
4. **MUST** refuse `/delegate` when the bound agent is not a pod Lead (`core.dispatch.
   enqueue_task` requires a pod task queue, which only a Lead has).
5. **MUST** reply with a usage message (not a silent drop, not a guess) on a recognized verb with
   a missing/malformed argument (e.g. `/approve` with no token).
6. **MUST** treat any other text as unrecognized — never as an implicit delegate or an implicit
   approval of the most-recent pending token.
7. **MUST** be inbound-only from `core/telegram.py`'s own perspective: the module replies to a
   message it received and never sends anything on its own initiative — `poll_once`'s reply is
   this module's only `send_message` call site, and `core/approval.py` holds no reference to
   this module. **A separate, operator-configured push now exists alongside it** (P34-16): the
   `telegram` channel dialect (`edges/adapters/channels/telegram.py::deliver`, see the new
   "Telegram as a channel" section below) can notify a chat when a task needs input, but only a
   chat id the operator explicitly listed in that channel document's own `actors` — never every
   `fleet.json` binding, and never triggered from inside this module. Nothing about approve/deny/
   status/delegate/answer routing changed: this module still only ever *replies*.
8. **MUST** answer `/delegate` with the queued task's id, not the pipeline's output. The channel
   queues work; it does not carry results back. `/answer` (see the new section below) is the
   equivalent contract for a parked question: it answers with a confirmation naming the task id,
   never the agent's own output. Output is read through `docket pod <project> queue`,
   `docket trace`, or the HTTP control plane.

### Non-Goals (explicitly out of scope for this card)

- Webhook mode (long-poll only)
- Any outbound/unprompted message *from `core/telegram.py` itself* — see Command grammar 7's
  amendment: the operator-configured `telegram` channel push (new section below) is the one
  deliberate exception, gated by an explicit `actors` allow-list a human must set
- Conversational chat: prose that is not one of the five operational verbs or the inert `/wire`
  setup handshake is refused, never routed
  to the bound agent as a turn
- Inline keyboards or any rich UI beyond a plain-text reply
- Discord/Slack/other chat platforms
- A per-user allowlist beyond the chat-level binding (the binding IS the authorization unit)
- Migrating any daemon-era Telegram configuration (D-19: clean break, no migration)

### Telegram as a channel (`/answer` and the outbound `telegram` dialect)

**Status: Implemented (P34-16).** ADR 0016 §7 makes Telegram one `kind: channel` dialect among
several (`templates/channels/07-telegram.yaml`; `capabilities: [notify, converse, decide]`,
`console` and `telegram` being the only two dialects allowed to `converse`/`decide`). This section
amends the command grammar above with the fifth verb and documents the dialect's `notify` half;
`converse`/`decide` remain entirely inbound, unchanged from Command grammar 1-6 above.

1. **MUST** recognize `/answer <task-id> <answer text>` (`core/telegram.py`'s `_ANSWER_RE`),
   resolving through `core.answers.answer_task(project, task_id, "accept", content,
   channel="telegram", actor="telegram")` — the identical function `docket pod <project> answer`,
   `docket chat`, `POST /tasks/<id>/answer`, and the MCP `task_answer` tool already call. This
   module never reimplements answer/resume semantics.
2. **MUST** resolve *project* the same way `/delegate` does (`_lead_project`): the bound agent's
   own pod. A task id belonging to another pod is refused by `answer_task` itself (it only reads
   that one project's task list), the same fail-closed behavior `answer_task` already gives every
   other channel.
3. **MUST** reply with a usage message on `/answer` with a missing task id or missing answer text,
   per Command grammar 5's existing rule for a recognized verb with a malformed argument.
4. **MUST** refuse `/answer` when the bound agent is not a pod Lead, when the named task has no
   pending question, or when the question's schema has more than one property — a single chat
   message cannot be split across fields; the reply names `docket pod <project> answer
   <task-id> --field name=value ...` or `docket chat` as the multi-field path, mirroring
   `cli/_pod.py::_pod_answer`'s own bare-text restriction.
5. **MUST** screen the answer text through the same `pre_input` evaluator every other answer
   channel uses — this is `answer_task`'s own screen (`core/answers.py`), not a second check in
   this module; a `block` verdict raises `AnswerRejected`, which this module reports as
   `Answer blocked by policy '<policy id>'` and audits as `telegram.answer_blocked` (chat
   id/policy id only, never the answer text, matching the `telegram.delegate_blocked`
   precedent).
   When the pending question carries options and the answer text exactly equals one option id,
   `/answer` **MUST** send `{"optionId": <id>}` through the same `answer_task` call; any other
   text keeps the single-property path above. This adds no outbound call site.
6. **MUST** implement the dialect's `notify` capability as `edges/adapters/channels/
   telegram.py::deliver(spec, event, *, secret, timeout) -> DeliveryResult` (the same shape every
   other dialect under `edges/adapters/channels/` implements, wired into `sink_for`). It **MUST**
   send the rendered event (`core.notify.render_text`) to every chat id in `spec.actors` via
   `edges/adapters/telegram.py::send_message`, using `secret` (the channel's own resolved
   credential — the built-in document names `TELEGRAM_BOT_TOKEN`, the same secret `docket keys
   add TELEGRAM_BOT_TOKEN` stores and `core/telegram.py`'s poll loop reads) as the bot token.
   It **MUST NOT** send to any chat id outside `spec.actors`, and in particular **MUST NOT**
   enumerate `fleet.json` bindings — the channel's own allow-list is the only recipient list.
   A missing secret, an empty `actors` list, or a failed send **MUST** all report a failed
   `DeliveryResult` without raising, per the shared dialect contract.
7. **MUST NOT** let this dialect's `deliver` initiate a conversation or resolve an approval —
   it is a one-shot, fire-and-forget push; a chat that wants to act on the notification still
   does so through the normal inbound `/approve`/`/answer` path, authorized the normal way.

## Interface Contracts

### CLI Command Signatures

```bash
# Connect Telegram: store the token, allow the chat, bind every pod Lead (sends nothing)
docket setup notify enable telegram --chat <id> [--token T] [--test]

# Bind one pod member to a group/peer (guided discovery, manual ID fallback)
docket setup notify bind <member> [--channel <name>] [--chat <id>]

# Remove a member's channel binding
docket setup notify unbind <member> [--channel <name>] [--yes]

# Start docket's own bot (long-poll; idle if no token is stored)
docket serve --telegram
```

### Return Codes

- `0`: Success (connected / bound / unbound / nothing to do / aborted on empty entry)
- `1`: Any error (unknown agent, a missing chat id or token — CLI-wide convention, see ../api/cli-interface.spec.md)

### Bot command grammar

```text
/approve <token>          Grant a pending approval (channel="telegram" audit entry)
/deny <token>              Deny a pending approval (channel="telegram" audit entry)
/status                    List pending approvals scoped to the bound agent's project
/delegate <task text>      Queue a task for the bound agent's pod (Lead bindings only)
/wire <setup code>          Confirm an already-completed guided wire (no state change)
```

## Examples

### Connecting Telegram in one step

```bash
$ docket setup notify enable telegram --chat -1001234567890
Telegram connected.
  secrets.json     TELEGRAM_BOT_TOKEN
  channel catalog  actors -1001234567890
  fleet.json       mywebsite-lead
```

### Binding one member to a group

```bash
$ docket setup notify bind mywebsite-lead --chat -1001234567890
Binding: mywebsite-lead <- telegram chat -1001234567890
  This binding is the whole authorization story for that chat.
```

### Removing a binding (revokes channel access immediately)

```bash
$ docket setup notify unbind mywebsite-lead --yes
Binding removed
```

### Starting the bot

```bash
$ docket serve --telegram
docket serve  port=7331  refresh=30s  telegram=on  (Ctrl-C to stop)
...
```

### An approval answered from a bound chat

```text
(a require_approval pre_tool_call gate created token apr-1234...)

Human, in the bound chat: /approve apr-1234-5678
Bot reply:                Approval granted: apr-1234-5678
```

This writes the same `audit_log("approval.grant", "token=apr-1234-5678 project=... channel=telegram")`
entry `docket approve`/`POST /approvals/<token>` would write for the CLI/HTTP channels.

## Validation

### Pre-conditions

- No daemon-related pre-conditions — there is none. The operator **MUST** already know the
  peer/group ID only when using the manual fallback.
- The bot **MUST** have a stored `TELEGRAM_BOT_TOKEN` for guided discovery or polling
  (`docket setup notify enable telegram`); manual ID entry remains available without it.

### Post-conditions

- After `docket setup notify bind`, `fleet.json` **MUST** contain a binding linking the entered
  peer ID to the agent; after `enable telegram --chat <id>`, `secrets.json` holds the token, the
  channel catalog holds `actors: [<id>]` enabled, and every pod Lead has a binding.
- After `docket setup notify unbind`, no binding for the agent **MUST** remain in `fleet.json`, and the next
  inbound message on that peer **MUST** be refused as unauthorized.
- After a `/approve`/`/deny` from a bound chat, the approval record **MUST** be in its granted/
  denied state and an `audit_log()` entry tagged `channel="telegram"` **MUST** exist.
- After a `/delegate` from a bound Lead's chat, the pod's task queue **MUST** contain the new
  task, unless a `pre_input` policy blocked it (in which case the queue **MUST** be unchanged).

### Invariants

- A peer **MUST** map to at most one agent at a time (per channel).
- An unbound chat **MUST NEVER** be able to approve, deny, check status, or delegate anything,
  regardless of message content — including a syntactically valid, real, pending token.
- The bot token **MUST NEVER** appear in an audit entry, a trace payload, a `--json` response, or
  a returned error string (`edges/adapters/telegram.py` reports HTTP status/Telegram's own
  `description` field/socket-exception detail — never the request URL the token is embedded in).
- Message bodies **MUST NOT** be logged beyond what a human already sees in the reply; audit
  entries for a refusal carry only the chat id/update id/policy id, never the raw text.

## Changelog

### Version 2.5.0 (2026-10-07)

- Phase 39 (P39-13): connecting Telegram is one operation, `docket setup notify enable telegram
  --chat <id>` (Connecting Telegram 8-10): the token, the allowed chats and a binding for every pod
  Lead are written together, nothing is sent unless `--test`. `docket wire`/`unwire` are replaced
  by `setup notify bind`/`unbind`; the inbound-only pins on `core/telegram.py` are unchanged.

### Version 2.4.0 (2026-10-05)

Waves 89-90 close (W89-10): the entries below were Unreleased and are now this version.

- `/approve <token> task` grants a parked call for the rest of its task (Command grammar 1a).
- `/answer <task> <option-id>` picks an option of a consult question (`optionId`).

### Version 2.3.0 (2026-09-29)

- **New "Telegram as a channel" section, amending Command grammar 7 (Phase 34, D-50, ADR 0016
  §9, P34-16).** A fifth verb, `/answer <task-id> <text>`, resolves through the same
  `core.answers.answer_task` every other surface calls (the bound agent's own pod; a foreign
  task id is refused by `answer_task` itself). The outbound `telegram` `kind: channel` dialect
  (`edges/adapters/channels/telegram.py`) pushes a rendered notification to every chat id in the
  channel's own `actors` list, never enumerating `fleet.json` bindings and never called from
  `core/telegram.py` itself. The inbound-only guard is amended and renamed
  `TestOutboundOnlyThroughTheChannel`: outbound Telegram messages now exist through exactly two
  structurally-pinned call sites (`core.telegram.poll_once`'s reply, and the channel dialect's
  `actors`-scoped push) instead of one, an AST walk over `src/` refuses a third, and a real
  false positive it found along the way (the new `email` dialect's unrelated
  `smtplib.SMTP.send_message` method) is allow-listed by path, not by weakening the scan.

### Version 2.2.1 (2026-09-18)

- The `docket wire` example now shows the real three-step "Easy setup" prompt
  (`cli/__init__.py`'s `cmd_wire`). No requirement changed.

### Version 2.2.0 (2026-08-20)

- Replaced Telegram's manual-ID-first setup with guided discovery: `docket wire` gives the
  operator a one-time `/wire <code>` command and resolves the matching group/supergroup directly
  from the existing Bot API adapter. Manual ID entry remains the fallback for missing tokens,
  transport failures, and advanced use.
- Discovery is read-only with respect to Telegram's durable update offset: it neither consumes
  nor routes unrelated messages, and an exact one-time code prevents stale activity in another
  group from being selected accidentally.
- The normal poller treats the retained `/wire` update as an inert setup confirmation after the
  CLI has created the binding, avoiding a misleading “unrecognized command” reply.

### Version 2.1.0 (2026-08-19)

- Removed retired channel-runtime comparisons from the live contract; Docket's bot, fleet
  binding, and approval store are now stated directly as the complete implementation.

### Version 2.0.0 (2026-08-03)

- **ROADMAP Phase 19 P19-8 — docket owns its own Telegram bot.** This is the change the 1.1.0
  Status line's "no docket-owned channel bot exists yet" caveat was written to be superseded by.
  With no daemon left (P19-7b) there is nothing else to defer to, so docket itself long-polls the
  Bot API (`edges/adapters/telegram.py`) and answers `/approve`/`/deny`/`/status`/`/delegate`
  through its own, unmodified approval store and pod-delegation APIs (`core/telegram.py`).
  Telegram becomes a real, fourth approval channel alongside CLI/HTTP/MCP; every grant/deny
  writes an `audit_log()` entry tagged `channel="telegram"`, closing the gap CLAUDE.md has had to
  explicitly deny since Phase 15 (G-5's unbridgeable daemon-native-prompt gap — the other side of
  that gap no longer exists to bridge to).
- **Rewrote the Scope, added a Security model section, and rewrote every "not yet" claim.** The
  binding `docket wire` records is now explicitly documented as the channel's entire
  authorization boundary — no second allowlist exists or is planned.
- **`docket wire`'s output changed**: it no longer says "nothing listens on this yet"; it states
  the authorization consequence of the binding instead. `docket unwire` gained an operational
  meaning it didn't have in 1.1.0 — it is now the "revoke this chat's access" action, effective
  on the very next message.
- **New requirements**: the bot's opt-in `docket serve --telegram` flag, its degrade-not-crash
  contract (unconfigured token, transport failure, an unexpected exception), the four-verb
  command grammar, and the `pre_input` content-screening requirement on `/delegate` text.
- **New Interface Contracts**: `docket keys add TELEGRAM_BOT_TOKEN`, `docket serve --telegram`,
  and the bot's own command grammar.

### Version 1.1.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7b — the OpenClaw daemon is deleted; this spec's entire ownership
  model is rewritten.** Pre-P19-7b, docket "owned the wiring" and the daemon "owned message
  delivery" — a real division of labor when the daemon existed. It doesn't any more, so:
  - `docket wire` **no longer discovers groups** from daemon activity logs
    (`scan_telegram_groups` is deleted along with the gateway log it read) — it prompts for
    the peer/group ID directly. Rewrote requirement 1 and the Examples section accordingly.
  - Bindings are written to `fleet.json` (`core/fleet.py`'s `upsert_binding`), not
    `openclaw.json` (deleted, no successor for the daemon side).
  - `docket wire`/`docket unwire` no longer restart a gateway to "pick up the change" — there
    is no gateway process; `restart_gateway()` is an honest `status="no_daemon"` no-op kept
    for call-site compatibility.
  - **Added the honesty requirement this version exists to state**: `docket wire`'s output
    MUST say plainly that no docket-owned channel bot exists yet (P19-8) and nothing listens
    on a newly recorded binding until then. Retitled the Status line "Binding-only (manual
    entry)" to make this impossible to miss.
  - Corrected the Pre-conditions (no daemon-running requirement left) and Invariants (a
    binding is "recorded intent," not "this channel is live").

### Version 1.0.1 (2026-07-30)

- Truth pass (Platformization baseline): return codes corrected to the real 0/1
  convention (the spec'd codes 2/7 never existed).

### Version 1.0.0 (2026-06-09)

- Initial Telegram integration specification
- Defined wire/unwire binding contract and the docket/daemon ownership boundary
