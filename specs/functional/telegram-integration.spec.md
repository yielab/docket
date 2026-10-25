# Telegram Integration Specification

**Version**: 4.2.0
**Status**: Implemented. `docket setup notify enable telegram --chat <id>` connects the channel in
one operation, `bind`/`unbind` handle the per-pod exception, and `docket start --telegram`
long-polls the Bot API and routes five verbs through docket's own approval, answer and dispatch
operations; every grant or deny through it is audited with `channel=telegram`.
**Last Updated**: 2026-10-25

## Purpose

This specification defines two things: (1) how docket records which Telegram peer/group maps to
which agent (`docket setup notify enable telegram`, `bind` and `unbind`), and (2) how docket's own
bot (`docket start --telegram`) turns an inbound message on a bound chat into an approve, deny,
status, delegate or answer action against docket's real state and approval mechanism.

## Scope

This specification covers:

- Recording a Telegram peer/group ID binding for an agent (`docket setup notify bind`/`unbind`)
- Connecting Telegram in one step (`docket setup notify enable telegram`)
- The binding's storage in `fleet.json` and its role as the channel's **entire authorization
  boundary** (see Security below)
- The bot's wire protocol: `getUpdates` long-poll, `sendMessage` reply
- The command grammar and routing to docket's existing approval, answer and dispatch operations
- `docket start --telegram`'s poll loop and its degrade-gracefully behavior when unconfigured

This specification does NOT cover:

- Outbound notifications to Telegram: the `telegram` channel dialect, its `actors` allow-list and
  delivery are owned by `operator-loop.spec.md` (area 6.1, item 6)
- Tool-approval gate semantics or the approval record's own state machine (see
  security-gates.spec.md)
- Audit log shape/tamper-evidence (see audit.spec.md)
- Webhook mode, inline keyboards, or any rich UI — out of scope by design (long-poll only, plain
  text only; see Non-Goals)

## Security model (read this before anything else)

A Telegram message is untrusted input from the open internet, and a bot token is effectively a
public endpoint. Two independent checks stand between an inbound message and anything happening:

1. **Sender authorization.** Only a chat id with an existing `fleet.json` binding may approve,
   deny, check status, delegate or answer anything. **The binding recorded by `docket setup notify
   bind` (or `enable telegram`) is the entire authorization boundary** — there is no second
   allowlist and no per-user check beyond it. The binding is read fresh on every message. An
   unbound chat's message is refused (`"This chat is not wired to a docket agent."`) and the
   attempt is audited (`telegram.unauthorized`, carrying the chat id and update id, never the
   message body) — never silently dropped, never granted. `/approve` and `/deny` act only on a token
   whose approval belongs to the bound agent's own pod (a pod member's pod, else the agent id
   itself): a token of any other pod is refused, left pending, and audited as
   `telegram.cross_pod_refused`, and the reply does not name the other pod.
2. **Content screening.** Text that is about to become agent input (a `/delegate` task
   description) is run through the `pre_input` policy hook as untrusted text (`trusted=False`,
   role `lead`) before `enqueue_task_once` is ever called — the same evaluator and the same
   untrusted-external-text reasoning the MCP client applies to a remote server's tool
   descriptions. `block`/`require_approval` refuse outright (there is no per-message
   human-approval channel for a chat message the way there is for a tool call); `warn`/`redact`
   proceed with an audit trail. An `/answer` is screened by `answer_task` itself (see
   "Answering a parked question").

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
3. **MUST** write a binding mapping the discovered or entered peer ID to the target agent into
   `fleet.json`, and seed the conversation registry entry for it.
4. **MUST** state plainly that the binding is the channel's entire authorization boundary: anyone
   who can post in the bound chat can act as that agent's operator once the bot is running.
5. **SHOULD** show an existing binding for the agent, if any, before prompting for a new one.
6. **MUST** refuse off a TTY when no `--chat` is supplied, naming `--chat` (exit 1); it never
   opens an agent picker.
7. **MUST NOT** invent a binding from empty manual input; an empty entry **MUST** abort cleanly
   (exit 0, "Aborted").
8. `enable telegram --chat <id> [--token T] [--test]` **MUST** be one operation: it stores the bot
   token (`--token`, then `TELEGRAM_BOT_TOKEN` in the environment, then a hidden prompt on a TTY;
   a stored token is kept when none is given), enables the `telegram` channel with `actors` set to
   the chat ids, upserts one binding per pod Lead (to the first chat id), and prints what it wrote
   in each store. Every precondition (a chat id, a token, and a credential backend that can take
   the write: `DOCKET_SECRETS_BACKEND=keyring` without `secret-tool` on `PATH` refuses rather
   than falling back to `secrets.json`) **MUST** be checked before the first write, so a refusal
   writes nothing.
9. `enable telegram` **MUST NOT** send any message unless `--test` is passed; with `--test` it
   sends one test event to the channel's `actors` and exits 1 if that delivery fails. The inbound
   bot still never messages a wired chat first (requirement 7 of the command grammar).
10. `show telegram` **MUST** list the bindings in `fleet.json` and the open Telegram conversations
    in `docket-conversations.json`.

### Unbinding a group (docket setup notify unbind)

1. **MUST** remove the binding for the given agent from `fleet.json`. Because the binding is the
   authorization boundary, this is the operative "revoke access" action for the channel — it
   takes effect on the very next inbound message (no caching). Off a TTY it **MUST** refuse
   (exit 1, naming `--yes`) unless `--yes` is passed; declining the prompt aborts with exit 0.
2. With no binding to remove it **MUST** exit 0 after saying the agent has no such binding
   (idempotent); an unknown agent exits 1.

### The bot (docket start --telegram)

1. **MUST** be opt-in (`docket start --telegram`), matching the existing `--dispatch` flag's
   shape — a real externally-reachable channel is not something `docket start` starts
   unconditionally.
2. **MUST** read the bot token through the secrets backend (`secret_value`, so a keyring-stored
   token resolves, not the empty index entry in `secrets.json`) that `docket setup notify
   enable telegram` wrote — never a bespoke config file, never a CLI argument (which would land in
   shell history), never the environment.
3. **MUST** degrade to an idle, periodically-retried wait (re-checked about every 30 seconds, so a
   token added while `docket start` runs is picked up) — never crash `docket start` — when no
   token is configured. The same degrade-not-crash contract applies to a Telegram-side transport
   failure (network unreachable, bad token, malformed response), which is printed and retried
   after a short back-off.
4. **MUST** long-poll (`getUpdates`), never operate in webhook mode.
5. **MUST** persist the last-processed `update_id` (`docket-telegram-offset.json`) so a `docket
   start` restart resumes forward rather than Telegram redelivering the whole backlog.
6. **MUST NOT** let an unexpected exception in one poll iteration crash the loop or the server —
   caught, printed, and the loop continues (D-17: a bare `contextlib.suppress(Exception)` around
   the delegate path's `enqueue_task_once` call is banned; the exception must be *visible*, not merely
   survived).
7. The long-poll wait is `TELEGRAM_POLL_TIMEOUT_S` (default 25) and the process's own socket
   timeout is `TELEGRAM_REQUEST_TIMEOUT_S` (default 35). The socket timeout **MUST** exceed the
   poll wait; a configured value that does not is raised to the poll wait plus 10 seconds and a
   warning is printed once, rather than the channel being refused.

### Command grammar

1. **MUST** recognize five operational verbs: `/approve <token> [task]`, `/deny <token>`,
   `/status`, `/delegate <task description>` and `/answer <id> <option|text>`, plus the inert
   `/wire <code>` setup handshake. Each verb **MUST** also be accepted with a bot-name suffix
   (`/status@my_bot`); a verb followed directly by other characters (`/delegatefoo`) is not that
   verb and is unrecognized. `/wire` never creates or changes a binding inside the bot; after the CLI
   has bound the group, the normal poller acknowledges the retained setup message with a plain
   confirmation. No inline keyboards, no Markdown/HTML rich replies — a plain text reply is the
   entire UI surface.
1a. `/approve <token> task` **MUST** behave as `/approve <token>` and also choose the
   `approve_task` option (recorded on the approval before the grant), so a parked pod approval
   covers the same exact call for the rest of its task (operator-loop requirement 5a). Any other
   trailing word is unparseable. The chat authorisation is unchanged and the bot stays
   inbound-only.
2. **MUST** route `/approve`/`/deny` through `resolve_approval_token` (`channel="telegram"`,
   `operator-loop.spec.md` area 10 item 6) — the same call `docket task approve`/`docket task
   deny` make: it resolves the approval's escalation, which runs `approval_grant`/`approval_deny`
   followed by `resolve_waiting_approval_detail`, and the bot replies with any note it returns. A
   repeated decision on an already-decided token is a benign no-op (the dispatch follow-up still
   runs and the reply is the approval store's own message). The bot never reimplements approval
   state transitions.
3. **MUST** render `/status` from the derived operator inbox (`build_inbox`, `operator-loop.spec.md`
   requirement area 5), scoped to the bound agent's own project (a pod Lead's own pod; any other
   member is scoped to its own agent id, which holds no pod items) — never another agent's tasks
   or pending approvals. The reply lists needs-you items (waiting/blocked tasks and pending
   approvals not already carried by a task) first, then failed tasks, and says nothing needs the
   operator when both are empty; it stays plain text. Under a `waiting_input` task with a pending
   `consult` or `input` escalation it prints the question, `options: <ids> (recommended <id>)`
   and `reply: /answer <task> <option>` (or `<your answer>` when it offers no options), rendered by `render_escalation` at the `conversation`
   level (the operator asked in their own chat; option ids are never withheld).
4. **MUST** refuse `/delegate` when the bound agent is not a pod Lead (`enqueue_task_once` requires a
   pod task queue, which only a Lead has).
5. **MUST** reply with a usage message (not a silent drop, not a guess) on a recognized verb with
   a missing/malformed argument (e.g. `/approve` with no token).
6. **MUST** treat any other text as unrecognized — a reply listing the verbs, never an implicit
   delegate or an implicit approval of the most-recent pending token.
7. **MUST** be inbound-only: the bot replies to a message it received and never sends anything on
   its own initiative — the poll loop's reply is the bot's only `send_message` call site, and the
   approval store holds no reference to the bot. The operator-configured outbound push is a
   different path (`operator-loop.spec.md`, area 6.1 item 6), never triggered from the bot.
8. **MUST** answer `/delegate` with the queued task's id, not the pipeline's output. The channel
   queues work; it does not carry results back. `/answer` is the equivalent contract for a parked
   question or approval: it answers with a confirmation naming the id, never the agent's own output.
   Output is read through `docket task list`, `docket task trace`, or the HTTP control plane.

### Answering an escalation (`/answer`)

1. **MUST** resolve `/answer <id> <option|text>` through `resolve` (`channel="telegram"`,
   `by="telegram"`, `operator-loop.spec.md` area 10) — the identical function `docket task answer`,
   `POST /escalations/<id>` and the MCP `resolve` tool call. *id* is an escalation id (`esc-...`),
   or the id of a task parked on a question (its pending escalation). The bot never reimplements
   answer/resume semantics.
2. **MUST** resolve *project* the same way `/delegate` does: the bound agent's own pod. A task id
   belonging to another pod is refused (the task is not found in the bound pod), the same
   fail-closed behavior every other channel gets.
3. **MUST** reply with a usage message on `/answer` with a missing task id or missing answer text,
   per Command grammar 5.
4. **MUST** refuse `/answer` when the bound agent is not a pod Lead, when the named task has no
   pending question, or when the question's schema does not have exactly one property and the
   text is not an option id — a single chat message cannot be split across fields; the reply
   names `docket task answer <task-id> --field name=value ...` as the multi-field path, mirroring
   `docket task answer`'s own bare-text restriction.
4a. When the escalation offers options and the text is none of their ids, `/answer` **MUST** reply
   with the option ids (`options: a, b (recommended a)`, as `/status` prints them) and resolve
   nothing, instead of sending the text as free-form content. An approval, gate or changed-check
   is answered by an option id only (`approve_once`, `approve_task`, `deny`); an escalation
   already settled is refused with the resolve error's sentence. An escalation of another pod is
   refused as not found in the bound pod.
5. **MUST** screen the answer text through the same `pre_input` evaluator every other answer
   channel uses — this is `resolve`'s own screen, not a second check in the bot; a `block`
   verdict raises `EscalationRefused`, which the bot reports as `Answer blocked by policy '<policy
   id>'` and audits as `telegram.answer_blocked` (project, task id and policy id only, never the
   answer text). When the text exactly equals one option id, `/answer` **MUST** resolve that
   option; any other text on an escalation with no options keeps the single-property path
   above.

### Non-Goals (explicitly out of scope)

- Webhook mode (long-poll only)
- Any unprompted message from the bot itself (the operator-configured channel push in
  `operator-loop.spec.md` is the one deliberate exception, gated by an explicit `actors` list a
  human must set)
- Conversational chat: prose that is not one of the five operational verbs or the inert `/wire`
  setup handshake is refused, never routed to the bound agent as a turn
- Inline keyboards or any rich UI beyond a plain-text reply
- Discord/Slack/other chat platforms
- A per-user allowlist beyond the chat-level binding (the binding IS the authorization unit)
- Migrating any daemon-era Telegram configuration (D-19: clean break, no migration)

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
docket start --telegram
```

### Return Codes

- `0`: Success (connected / bound / unbound / nothing to do / aborted on empty entry or a declined
  prompt)
- `1`: Any error (unknown agent, a missing chat id or token, a missing confirmation off a TTY, a
  failed `--test` delivery — CLI-wide convention, see ../api/cli-interface.spec.md)

### Bot command grammar

```text
/approve <token> [task]    Grant a pending approval (channel="telegram" audit entry);
                           with `task`, cover the same call for the rest of its task
/deny <token>              Deny a pending approval (channel="telegram" audit entry)
/status                    List needs-you items and failed tasks for the bound agent's pod
/delegate <task text>      Queue a task for the bound agent's pod (Lead bindings only)
/answer <id> <option|text> Resolve an escalation: an option id, or the answer text of a question
                           with no options (Lead bindings only)
/wire <setup code>         Confirm an already-completed guided wire (no state change)
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
$ docket start --telegram
docket start  port=7331  refresh=30s  telegram=on  (Ctrl-C to stop)
...
```

### An approval answered from a bound chat

```text
(a require_approval pre_tool_call gate created token apr-1234...)

Human, in the bound chat: /approve apr-1234-5678
Bot reply:                Approval granted: apr-1234-5678
```

This writes the same `audit_log("approval.grant", "token=apr-1234-5678 project=... channel=telegram")`
entry `docket task approve`/`POST /approvals/<token>` would write for the CLI/HTTP channels.

## Validation

### Pre-conditions

- The operator **MUST** already know the peer/group ID only when using the manual fallback.
- The bot **MUST** have a stored `TELEGRAM_BOT_TOKEN` for guided discovery or polling
  (`docket setup notify enable telegram`); manual ID entry remains available without it.

### Post-conditions

- After `docket setup notify bind`, `fleet.json` **MUST** contain a binding linking the entered
  peer ID to the agent; after `enable telegram --chat <id>`, `secrets.json` holds the token, the
  channel catalog holds `actors: [<id>]` enabled, and every pod Lead has a binding.
- After `docket setup notify unbind`, no binding for the agent **MUST** remain in `fleet.json`, and the next
  inbound message on that peer **MUST** be refused as unauthorized.
- After a `/approve`/`/deny` from a bound chat, the approval record **MUST** be in its granted/
  denied state and an `audit_log()` entry tagged `channel=telegram` **MUST** exist.
- After a `/delegate` from a bound Lead's chat, the pod's task queue **MUST** contain the new
  task, unless a `pre_input` policy blocked it (`telegram.delegate_blocked` audited, queue
  unchanged). A `warn`/`redact` verdict queues the task and audits `telegram.delegate_warn`.

### Invariants

- A peer **MUST** map to at most one agent at a time (per channel).
- An unbound chat **MUST NEVER** be able to approve, deny, check status, delegate or answer
  anything, regardless of message content — including a syntactically valid, real, pending token.
- The bot token **MUST NEVER** appear in an audit entry, a trace payload, a `--json` response, or
  a returned error string (the Bot API adapter reports HTTP status/Telegram's own `description`
  field/socket-exception detail — never the request URL the token is embedded in).
- Message bodies **MUST NOT** be logged beyond what a human already sees in the reply; audit
  entries for a refusal carry only the chat id/update id/project/task/policy id, never the raw
  text.

### Poison updates

One update whose handling raises **MUST NOT** pin the poller on its batch: the poll records it
(`telegram.update_failed chat_id=… update_id=… error=<type>`), skips it, replies to nothing for it,
and still advances the durable offset past the whole batch, so the next poll never replays it.

### Unbound chats in one batch

An update from a chat id with no binding is refused, and its audit entry is **coalesced**: the poll
writes one `telegram.unauthorized` entry per chat id per batch, with `chat_id`, `update_id` (the
last one in the batch from that chat) and `count=<n>`, rather than one entry per message. A flood
from one unbound chat therefore adds one line per batch, not one line per message. Each message
still receives its own refusal reply. A batch holding one message from that chat writes one entry
with `count=1`. A message handled outside a poll batch still audits its own refusal.

## Implementation

Where the names above live today:

- `src/docket/interfaces/telegram/bot.py`: `handle_message`, `poll_once`, `discover_wire_groups`,
  `wire_discovery_configured`, `InboundMessage`, `TelegramActionResult`, `PollSummary`
- `src/docket/interfaces/telegram/client.py`: `get_updates`, `send_message`, `TelegramUpdate`,
  `GetUpdatesResult`, `API_ROOT` (the only module that knows the Bot API wire format)
- `src/docket/operator/adapters/telegram.py`: `deliver` (the outbound dialect; its
  requirements are `operator-loop.spec.md`'s)
- `src/docket/interfaces/cli/commands/setup_notify.py`: `docket setup notify` (`enable_telegram`, `bind`, `unbind`,
  `show`)
- `src/docket/interfaces/cli/commands/service.py`, `src/docket/interfaces/telegram/poll.py`: `docket start --telegram` and its poll loop
  with the idle and error back-offs
- `src/docket/kernel/home.py`: the `Home` members `telegram_bot_token_key`, `telegram_offset_file`,
  `telegram_poll_timeout_s`, `telegram_request_timeout_s`
- `src/docket/teams/fleet.py`: `find_binding`, `upsert_binding`, `remove_binding`
- `src/docket/governance/approval.py`, `src/docket/tasks/application/actions.py`,
  `src/docket/tasks/application/queue.py`, `src/docket/hops/application/answers.py`,
  `src/docket/operator/inbox.py`: `approval_grant`/`approval_deny`, `resolve_waiting_approval_detail`
  and `enqueue_task_once`, `answer_task`, `build_inbox`
- `src/docket/templates/channels/07-telegram.yaml`: the built-in `telegram` channel document
- `tests/integration/interfaces/telegram/test_bot_inbound.py`, `tests/integration/interfaces/test_delete_bind_unbind.py`,
  `tests/unit/interfaces/telegram/test_poll__pacing.py`: the bot, bind/unbind and poll-loop tests
