# Telegram Integration Specification

**Version**: 2.0.0
**Status**: Implemented — **ROADMAP Phase 19 P19-8 shipped docket's own Telegram bot.** With no
external daemon left (P19-7b), docket owns the whole channel: `docket wire`/`docket unwire`
record a peer/group binding in `fleet.json` (unchanged from 1.1.0), and `docket serve
--telegram` long-polls the Telegram Bot API (`edges/adapters/telegram.py`, stdlib `urllib`, zero
new dependencies) and routes `/approve`, `/deny`, `/status`, `/delegate` through docket's
*existing* approval store and pod-delegation APIs (`core/telegram.py`). Telegram is now a real,
fourth docket approval channel alongside CLI/HTTP/MCP — every grant/deny through it writes an
`audit_log()` entry tagged `channel="telegram"`, exactly like the other three. This closes the
gap CLAUDE.md has had to explicitly deny since Phase 15 (G-5: a Telegram reply used to answer the
daemon's own native exec-approval prompt, which docket never saw and never audited — that prompt
no longer exists).
**Last Updated**: 2026-08-03

## Purpose

This specification defines two things: (1) how docket records which Telegram peer/group maps to
which agent (`docket wire`/`docket unwire`, unchanged in shape since 1.1.0), and (2) how docket's
own bot (`docket serve --telegram`) turns an inbound message on a bound chat into an approve/
deny/status/delegate action against docket's real state — never a daemon, never a second
approval mechanism.

## Scope

This specification covers:

- Recording a Telegram peer/group ID binding for an agent (`docket wire`/`docket unwire`)
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
   anything. **The binding recorded by `docket wire` is the entire authorization boundary** —
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

### Wiring a group (docket wire)

1. **MUST** prompt for the peer/group ID directly (manual entry) — ROADMAP Phase 19 P19-7b
   removed log-based Telegram group auto-discovery (`scan_telegram_groups`) along with the
   daemon gateway log it read; there is no list of "recently active groups" to present any more.
2. **MUST** write a binding mapping the entered peer ID to the target agent into `fleet.json`
   (`core/fleet.py`'s `upsert_binding`), not `openclaw.json` (deleted).
3. **MUST** state plainly that the binding is the channel's entire authorization boundary: anyone
   who can post in the bound chat can act as that agent's operator once the bot is running.
4. **SHOULD** show an existing binding for the agent, if any, before prompting for a new one.
5. **MUST** fall back to the interactive agent picker when no agent id is supplied.
6. **MUST NOT** invent a binding from empty input; an empty entry **MUST** abort cleanly
   (exit 0, "Aborted").

### Unwiring a group (docket unwire)

1. **MUST** remove the binding for the given agent from `fleet.json`. Because the binding is the
   authorization boundary, this is the operative "revoke access" action for the channel — it
   takes effect on the very next inbound message (no caching).
2. **SHOULD** succeed silently (idempotent) if no binding exists.

### The bot (docket serve --telegram)

1. **MUST** be opt-in (`docket serve --telegram`), matching the existing `--dispatch` flag's
   shape — a real externally-reachable channel is not something `docket serve` starts
   unconditionally.
2. **MUST** read the bot token from docket's own secrets store (`docket keys add
   TELEGRAM_BOT_TOKEN`) — never a bespoke config file, never a CLI argument (which would land in
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

1. **MUST** recognize exactly four verbs: `/approve <token>`, `/deny <token>`, `/status`,
   `/delegate <task description>`. No inline keyboards, no Markdown/HTML rich replies — a plain
   text reply is the entire UI surface.
2. **MUST** route `/approve`/`/deny` through the *existing* `core.approval.approval_grant`/
   `approval_deny` (`channel="telegram"`) followed by `core.dispatch.resolve_waiting_approval` —
   the identical sequence `cli/_approve.py`/`cli/_deny.py` already use. This module never
   reimplements approval state transitions.
3. **MUST** scope `/status`'s pending-approval listing to the bound agent's own project (a pod
   Lead's own pod; an org specialist's own agent id) — never another agent's pending approvals.
4. **MUST** refuse `/delegate` when the bound agent is not a pod Lead (`core.dispatch.
   enqueue_task` requires a pod task queue, which only a Lead has).
5. **MUST** reply with a usage message (not a silent drop, not a guess) on a recognized verb with
   a missing/malformed argument (e.g. `/approve` with no token).
6. **MUST** treat any other text as unrecognized — never as an implicit delegate or an implicit
   approval of the most-recent pending token.

### Non-Goals (explicitly out of scope for this card)

- Webhook mode (long-poll only)
- Inline keyboards or any rich UI beyond a plain-text reply
- Discord/Slack/other chat platforms
- A per-user allowlist beyond the chat-level binding (the binding IS the authorization unit)
- Migrating any daemon-era Telegram configuration (D-19: clean break, no migration)

## Interface Contracts

### CLI Command Signatures

```bash
# Bind a Telegram group/peer to an agent (manual peer/group ID entry)
docket wire [agent-id] [--channel <name>]

# Remove an agent's channel binding
docket unwire [agent-id] [--channel <name>]

# Store the bot token (read by core/telegram.py; excluded from per-agent .env sync)
docket keys add TELEGRAM_BOT_TOKEN

# Start docket's own bot (long-poll; idle if no token is stored)
docket serve --telegram
```

### Return Codes

- `0`: Success (bound / unbound / nothing to do / aborted on empty entry)
- `1`: Any error (unknown agent — CLI-wide convention, see ../api/cli-interface.spec.md)

### Bot command grammar

```text
/approve <token>          Grant a pending approval (channel="telegram" audit entry)
/deny <token>              Deny a pending approval (channel="telegram" audit entry)
/status                    List pending approvals scoped to the bound agent's project
/delegate <task text>      Queue a task for the bound agent's pod (Lead bindings only)
```

## Examples

### Wiring an agent to a group

```bash
$ docket wire mywebsite
Wire Telegram: My Shop (mywebsite)

Enter the peer/group ID from your telegram setup.

Telegram peer/group ID: -1001234567890
[SUCCESS] Binding: mywebsite ← telegram group -1001234567890
  This binding is the whole authorization story: whoever can post in this chat can now
  /approve, /deny, /status, or /delegate for 'mywebsite' once docket's own bot is running
  (docket serve --telegram, with TELEGRAM_BOT_TOKEN configured). Keep the chat restricted
  to people who should hold that power.
[SUCCESS] Done. 'mywebsite' is now wired to telegram peer -1001234567890
```

### Removing a binding (revokes channel access immediately)

```bash
$ docket unwire mywebsite
Unwire Telegram: My Shop (mywebsite)

This will remove the telegram binding for peer -1001234567890
Confirm? [y/N]: y
[SUCCESS] Binding removed
```

### Starting the bot

```bash
$ docket keys add TELEGRAM_BOT_TOKEN
Enter value for TELEGRAM_BOT_TOKEN (hidden): ****
[SUCCESS] Key 'TELEGRAM_BOT_TOKEN' stored.

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
  peer/group ID to enter for `docket wire` (no auto-discovery exists).
- The bot **MUST** have a stored `TELEGRAM_BOT_TOKEN` to do anything beyond idling
  (`docket keys add TELEGRAM_BOT_TOKEN`).

### Post-conditions

- After `docket wire`, `fleet.json` **MUST** contain a binding linking the entered peer ID to
  the agent.
- After `docket unwire`, no binding for the agent **MUST** remain in `fleet.json`, and the next
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
