# Operator Loop Specification

**Version**: 2.5.0
**Status**: Implemented. Every requirement area below is on the live path: the inbox, the
outbound channels, answers, the interruption forecast, pre-grants and consultations.
**Last Updated**: 2026-10-25

## Purpose

A docket operator who assigns work to a pod's Lead and walks away needs a way to learn that
something needs them, be asked a question rather than only a permission, and trust that
answering late never loses the work. This specification defines the shared `operator-v1`
contract every surface and channel builds through (one module, the operator contract).
It adopts existing standards rather than inventing docket-only vocabulary — A2A 1.0.0 task
states, an MCP-elicitation-shaped question/answer, CloudEvents 1.0 event envelopes — so a client
that already understands one of those standards understands the matching part of docket's
operator loop unchanged.

## Scope

This specification covers:

- The task lifecycle vocabulary and its mapping onto the A2A 1.0.0 `TaskState` names
- The typed intake brief (`TaskBrief`) and the surfaces that accept one
- A question posed to a human and its answer, shaped as an MCP elicitation request/result
  (`Question`, `QuestionSchema`, `AnswerResult`, `validate_requested_schema`, `validate_answer`),
  and the operator-v1.1 extension (`QuestionV11`, `AnswerResultV11`, `validate_answer_v11`)
- The read views every surface renders (`ApprovalView`, `TaskView`, `InboxView`) and the derived
  inbox (`build_inbox`) behind `docket inbox`, `GET /inbox`, the MCP `inbox` tool, `GET /metrics`
  and Telegram's `/status`
- The CloudEvents 1.0 envelope every notification uses (`CloudEvent`, `make_event`,
  `EVENT_KINDS`)
- Outbound channels: the `kind: channel` document and catalog, `docket setup notify`, the
  diff/render/delivery framework and every delivery dialect, the outbound `telegram` dialect
  included
- Answering a parked question (`answer_task`), question expiry, and the trace events
  `input_requested`, `question_asked`, `input_answered` and `input_expired`
- The stable digest that matches a tool call to a single-use pre-grant
  (`canonical_args_digest`), the interruption forecast and the pre-grant surfaces
- The `consult` built-in tool, the corrections ledger, the `lights-out` profile lines and the
  check-changed approval as the operator sees them
- The generated JSON Schema documents under `docs/contracts/operator-v1/` and
  `docs/contracts/operator-v1.1/`

This specification does NOT cover:

- The inbound Telegram bot — its verbs (`/approve`, `/deny`, `/status`, `/delegate`,
  `/answer`), bindings and polling are `telegram-integration.spec.md`'s
- Dispatch mechanics behind parking and resuming (resume position, pre-grant matching inside a
  hop, the input step's executor, the brief's resource pre-check): `pod-dispatch.spec.md`
  ("Parked approvals", "Operator input steps and answers", "Task brief")
- The HTTP routes' shared conventions (auth, error envelope, cursors): `operator-api.spec.md`

## Requirements

### 1. Task status and its A2A mapping

1. `a2a_state(status, blocked_reason=None, failure_kind=None)` MUST return exactly one of the
   eight `A2AState` names for every docket task `status` this specification enumerates:

   | docket `status` | `blocked_reason` / `failure_kind` | `a2aState` |
   | --- | --- | --- |
   | `pending` | — | `SUBMITTED` |
   | `running` | — | `WORKING` |
   | `waiting_input` | — | `INPUT_REQUIRED` |
   | `waiting_approval` | — | `INPUT_REQUIRED` |
   | `blocked` | `blocked_reason == "resources"` | `AUTH_REQUIRED` |
   | `blocked` | any other reason (including none) | `INPUT_REQUIRED` |
   | `done` | — | `COMPLETED` |
   | `failed` | `failure_kind == "rejected"` | `REJECTED` |
   | `failed` | any other kind (including none) | `FAILED` |
   | `cancelled` | — | `CANCELED` |

2. `a2a_state` MUST raise `ValueError` for a `status` outside this table. It MUST NOT guess or
   fall back to a default state.
3. `A2AState` MUST be a `Literal` of exactly these eight names: `SUBMITTED`, `WORKING`,
   `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`. It MUST be
   the only place that vocabulary is enumerated; `a2a_state` is annotated with it.

### 2. Park, don't block

An unattended pod's in-turn `ask` records the exact call and durably parks the task for a human
(`approvalMode: "park"`, the `approval_parked` denial kind and stop reason), instead of blocking
a thread or losing the call. This area states the operator-level contract; the dispatch
mechanics are `pod-dispatch.spec.md` "Parked approvals".

1. A parked task's docket `status` MUST be `waiting_approval`, mapping to `INPUT_REQUIRED` via
   requirement area 1's table — the same `a2aState` a pre-hop `require_approval` gate's
   `waiting_approval` carries. A client reading `a2aState` alone cannot distinguish the two
   triggers, and MUST NOT need to: both mean "nothing runs until a human decides."
2. `canonical_args_digest(tool, args)` MUST be the one digest a parked call's record, the
   pre-grant a parked grant appends, and the pre-grant `docket task approve --for` records
   (area 9 item 5) all key against, so a CLI-issued pre-grant and an in-turn parked approval are
   matched identically by the tool-call gate's single matcher.
3. An unset pod `approvalMode` MUST NOT resolve to a single fixed posture across every caller.
   The `docket start --dispatch` sweep and a non-interactive `docket run` MUST resolve it to
   `"park"`; an interactive `docket run` (stdin is a TTY) MUST resolve it to `"wait"`. An
   explicit stored `approvalMode` always overrides the caller's own default.
4. A parked approval MUST carry its own `expiresAt` (now plus the pod's `approvalExpiryHours`,
   computed per hop) and MUST be expired by the same fail-closed sweep that expires every
   pending approval, resolving to **denied** past deadline — never a silent indefinite wait,
   and never a second expiry mechanism.
5. Granting a parked approval MUST NOT set the pre-hop gate's `gateOverridePipelineIndex`
   single-use override: that field skips a gate at a position no hop ever ran, which does not
   describe an already-attempted, parked hop. The grant MUST instead reopen the task `pending`
   with `{token, tool, argsDigest}` appended to the task's `pregrants`; every later hop of the
   task is given the task's pre-grants, so the model's identical next call passes once without
   asking again.
5a. Granting a parked approval with the `approve_task` option (`docket task approve <task>
   --task`, `POST /approvals/<token>` with `option: "approve_task"`, the MCP approval tool's
   option, Telegram `/approve <token> task`; each records the option on the approval before
   the grant) MUST also record a task-wide grant `{tool, argsDigest, role, token, grantedAt,
   actor, channel}` in the task's `taskGrants`, where `role` is the parked approval's role,
   audited as `approval.task_grant`. An identical `(tool, argsDigest, role)` is recorded once.
   Every later hop of that role MUST be given one freshly minted single-use pre-grant per
   matching entry (`create_pregrant`, bound to the project and that role, task-scoped, expiring
   after the pod's `approvalExpiryHours`), so each use is consumed and audited as any pre-grant;
   a hop of another role gets none. The match is exact on `(tool, argsDigest)`; the grant
   exists only on the `ask` path (a `deny` or policy block never creates an approval, so is
   never widened). A task holds at most 20: the 21st is approved once only, audited as
   `approval.task_grant_refused`, and the granting command reports that note to the operator.
   `taskGrants` MUST be dropped when the task reaches a terminal status (done, failed,
   cancelled, approval denied) and is never read by another task. Under `approvalMode: "wait"`
   a granted in-turn approval that chose `approve_task` adds one single-use pre-grant for the
   identical call to the rest of that turn.
6. Non-goal (ADR 0016): resuming the live model-turn session with the granted call's result
   injected in place of a hop re-run.

### 3. The Lead's intake

1. `TaskBrief` MUST require a non-empty `objective`, MUST accept only `resources[]` entries equal
   to `verify` or prefixed `secret:` or `path:`, and MUST carry `expectedRiskyActions` as the wire
   alias of `expected_risky_actions`. How a Lead's reply becomes a brief, the deterministic
   resource pre-check, the per-question schema derived from `questions[]` and the Implementer's
   `## Brief` view are `pod-dispatch.spec.md` "Task brief".

### 4. Task assignment in a standard shape

1. `TaskBrief` MUST be the pre-brief shape `docket task add --brief FILE.json` and
   `POST /tasks/<project>`'s optional `brief` accept; area 10 items 3-4 state the exact contract.

### 5. One inbox, derived

`build_inbox(*, now, since=None) -> InboxView` is pure over state it reads: it takes the
caller's current time and cursor as data and performs no writes and no clock reads of its own.

1. `build_inbox` MUST enumerate every project that has at least one registered pod member —
   every provisioned pod, paused included — not only the pods eligible for dispatch.
2. For every pod, `build_inbox` MUST read its task list and sort each task into exactly one of
   `needsYou`, `failed`, `doneSince` or `running` by its `status`, or omit it (`pending`,
   `cancelled`):
   - `needsYou`: any status starting `waiting_`, plus `blocked`.
   - `failed`: `status == "failed"`.
   - `doneSince`: `status == "done"` and, when `since` is given, only a task whose timestamp
     (below) is strictly later than `since`; every `done` task when `since` is omitted.
   - `running`: `status == "running"`.
3. `build_inbox` MUST read every pending approval and add one `ApprovalView` to `needsYou` for
   each **unless** its `context.taskId` is set or a task in `needsYou` holds its token as
   `approvalToken` — an approval already surfaced through its task MUST NOT also appear
   standalone, so nothing needing a decision is shown (or notified) twice. A parked in-turn call
   MUST record `context.taskId` when the turn serves a task.
4. Each `TaskView`/`ApprovalView` MUST carry its `a2aState` via `a2a_state`, passing the task's
   own `blockedReason`/`failureKind` fields.
5. A task's timestamp, for sorting into `doneSince` and for `InboxView.next`, MUST be
   `completedAt`, else `startedAt`, else `created` (the caller's `now` only when none is set).
   An approval's timestamp is its `created` field. `next` MUST be the maximum timestamp across
   every task read and every standalone approval added (compared by parsed instant, not string
   order, since an ISO-with-offset timestamp and a `Z`-suffixed one are not lexicographically
   comparable), or `None` when nothing was seen.
6. `docket inbox [--json] [--since <iso>] [--peek]` MUST render the four sections (`Needs you`,
   `Failed`, `Done`, `Running`), `Needs you` first, or `Nothing needs you.` when all are empty.
   Without `--peek` and without an explicit `--since`, it MUST read its cursor from, and advance
   it to `InboxView.next` in, `inbox-cursor.json` under `DOCKET_HOME`, so a later plain call's
   `doneSince` only shows tasks that completed after the previous call. `--peek` and an explicit
   `--since` MUST NOT write the cursor. An undeclared flag MUST exit 2. Every item MUST print the
   exact command that moves it forward (`docket task approve|deny <id>` for an approval or a
   `waiting_approval` task, `docket task answer <id>` for `waiting_input`, `docket task retry
   <id>` for `blocked`/`failed`, `docket task show <id>` for `done`/`running`, `docket run --pod
   <pod>` for an approved, ready task), and a held command or question in full, never
   truncated; every continuation line of a multi-line question, held command or label MUST be
   indented to the column of its first line's text, so no line of an item starts at column 0.
   A `pending` task carrying `pregrants` or a `gateOverridePipelineIndex` MUST appear under
   `Needs you` as `approved ready` (`state: "approved_ready"`) with the `docket run` command.
   `--json` MUST emit `InboxView` (`by_alias`, JSON mode) with `state` and `command` added to
   each item, those approved-ready tasks and the memory items of item 11 appended to `needsYou`,
   and no escape codes.
7. `GET /inbox?since=<iso>` MUST require the same `Authorization: Bearer <token>` as
   `GET /approvals` and return the `InboxView` for the same state (`by_alias`, JSON mode): the
   view `docket inbox --json` starts from, without the `state`/`command` keys, the
   approved-ready tasks or the memory items that command adds. A task's `question` MUST carry
   `kind`, `options` and `recommendation` whenever the stored question has a `kind`, so a client
   can offer the options without a second read.
8. `docket start --mcp`'s `inbox(since=None)` tool MUST return the same shape as `GET /inbox`.
9. `GET /metrics` MUST expose `docket_inbox_items{section="needsYou"|"failed"|"doneSince"|
   "running"}` as a gauge, one line per section, computed from `build_inbox(now=..., since=None)`.
10. Telegram's `/status` (an inbound verb owned by `telegram-integration.spec.md`) MUST render
    from `build_inbox`, filtered by each item's `pod` to the bound agent's own pod, `needsYou`
    first, then `failed`.
11. **Pending pod memory.** `pending_memory() -> list[MemoryItem]` MUST return one item per
    `pending` entry of every pod's memory, oldest first within a pod, carrying `pod`, `id`,
    `kind`, `subject`, `note`, `reason` and `task`. It is not part of `InboxView` and not of the
    operator-v1 contract: `build_inbox`, `GET /inbox`, `GET /metrics`, notifications and
    Telegram `/status` do not carry it. `docket inbox` MUST list each item under `Needs you` as
    `memory <id>  pod=<pod>  <kind>`, its subject and note, why it is held, the command `docket
    pod memory approve <id> --pod <pod>` and the refusal `docket pod memory refuse <id> --pod
    <pod> --reason "<why>"`; `--json` MUST add it to `needsYou` as `{kind: "memory", pod, id,
    entryKind, subject, note, reason, task, state: "needs_memory_approval", command}`. It does
    not move `InboxView.next` and does not advance the cursor.

### 6. Notifications

Items 1-8 are the `kind: channel` document, catalog and CLI; items 9-17 are the
diff/render/delivery framework, the `console`/`webhook`/`command` dialects and the warning when
nothing delivers. `CloudEvent`, `make_event` and the closed `EVENT_KINDS` vocabulary satisfy the
CloudEvents 1.0 structured-mode shape. Area 6.1 holds the remaining dialects.

1. `ChannelSpec` (`kind: channel`) MUST declare `dialect` (one of `console`, `desktop`,
   `webhook`, `command`, `ntfy`, `email`, `telegram`), `capabilities` (a subset of `{notify,
   converse, decide}`), `on` (event types this channel receives, from `EVENT_KINDS` plus the
   `needs_you` shorthand), `content` (`minimal | actions | conversation`, default `minimal` —
   never the export-only `full`; ADR 0016), `actors` (identities allowed to converse or decide
   through it), `config` (dialect-specific string settings), and `secret` (a credential
   **name**, never a value; a value-shaped string is refused).
2. Each dialect MUST have a closed maximum capability set (`DIALECT_MAX`): `console` and
   `telegram` may include `decide` and `converse`; every other dialect may only `notify`. A
   document declaring a capability past its dialect's maximum MUST be refused, naming the
   maximum, at parse time, whether or not the document is enabled.
3. A document whose `capabilities` include `decide` or `converse` and whose `actors` is empty
   MUST be refused only once `enabled` is true, and never for `dialect: console` (the operator's
   own terminal, trusted without an allow-list). A dormant document (`enabled: false`, the
   default) MAY declare `decide`/`converse` with empty `actors` — the shape the built-in
   `telegram` document ships.
4. The channel catalog (`load_catalog`) MUST merge two scopes nearest-wins by name: the seven
   built-in documents shipped with docket (`console`, `desktop`, `webhook`, `command`, `ntfy`,
   `email`, `telegram`) and the operator's own entries in `docket-channels.json` under
   `DOCKET_HOME`; a global entry inherits every field it does not set from the built-in of the
   same name. Only `console` MUST ship enabled. Every built-in subscribes to `needs_you`;
   `desktop` and `ntfy`, the two that reach an operator who walked away, MUST also subscribe to
   `task.failed`. None subscribes to `task.completed` by default (the inbox's `doneSince`
   carries it).
5. `enable_channel(name, overrides)` MUST refuse, without writing, a channel whose resulting
   document fails a dialect precondition: `ntfy` requires a non-empty `config["topic"]`;
   `telegram` requires a non-empty `actors`. No other built-in has an enable precondition.
   Enabling and disabling are audited (`channel.enable`, `channel.disable`).
6. `set_content(name, level)` MUST accept only `minimal`, `actions` or `conversation`, on the
   closed order `minimal < actions < conversation`, and audit `channel.content` with the old and
   new level; `is_widening(old, new)` MUST return `True` exactly when `new` is strictly richer
   than `old`. `docket setup notify privacy <name> <level>` MUST treat a widening change as a
   confirmed command, with the same rule as `docket setup export privacy`: `--yes` proceeds, a
   TTY is asked `y/N`, and a non-TTY refuses (exit 1) naming `--yes` without asking. Narrowing
   never asks. Without `<level>` it prints the current level; an unknown level exits 1.
7. `docket setup notify` MUST offer `list`, `show`, `enable <name> [--set k=v]... [--test]`,
   `disable`, `add <file>`, `remove <name> [--yes]`, `export <name> [<file>]`, `privacy <name>
   [<level>] [--yes]`, `test <name>` and `flush [--dry-run]`, plus the Telegram-specific
   `enable telegram --chat <id> [--token]`, `bind` and `unbind` that `telegram-integration.spec.md`
   owns. `--set content=...` MUST be refused (exit 1, naming `privacy`); `--chat`/`--token` on
   any channel but `telegram` MUST be refused (exit 1). Only `test`, `enable --test` and `flush`
   send anything to a dialect's destination.
8. `docket pod validate` MUST accept `kind: channel`, validating it with the same loader as
   `docket setup notify add`, and the generated `docs/contracts/config-v1/channel.schema.json`
   (and its copy shipped in the package) MUST be rendered from `ChannelSpec`, the same way as
   `exporter`.
9. `diff_events(prev, inbox, now) -> (events, snapshot)` MUST be pure (no clock, no I/O) and
   MUST emit one `NotifyEvent` per item in `inbox.needsYou`/`failed`/`doneSince` whose dedupe key
   is new, or whose version has changed, since `prev`. The dedupe key MUST be `task:<pod>:<id>`
   for a `TaskView` or `approval:<token>` for an `ApprovalView`; the version MUST be the item's
   status (or state) plus its question id or approval token, so a task re-asking a different
   question is treated as changed even when `status` itself repeats. The event kind MUST be
   `task.input_required` (`waiting_input`), `approval.requested` (`waiting_approval` or a
   standalone `ApprovalView`), `task.blocked`, `task.rejected` (a failed task whose `a2aState`
   is `REJECTED`), `task.failed` (any other failed task), or `task.completed`.
10. `diff_events` MUST additionally emit `approval.expiring` at most once per approval token,
    the first time 80% or more of the interval between its `createdAt` and `expiresAt` has
    elapsed; a token already recorded in the returned `snapshot`'s `expiring` list MUST NOT
    fire again.
11. `render_data(item, level)` MUST enforce the three content levels on the `CloudEvent.data` it
    builds: `minimal` MUST NOT include an approval's rendered `action` or a task's
    `question`/`brief`; `actions` and `conversation` MUST add `action` (approvals only);
    `conversation` MUST add `question` and, when present, `brief` (tasks only).
    `render_text(event)` MUST derive `(title, body)` only from *event*'s own already-leveled
    `data`, never from the source item, so a `minimal` event's text carries nothing a `minimal`
    event's data omitted. When a task's question is a `QuestionV11` with options, `conversation`
    MUST also add `options` (`[{id, label}]`, labels stripped of non-printable characters and
    capped at 80 characters) and, when recommended, `recommendation` (`{optionId}` only — never
    the rationale or evidence); `minimal` and `actions` MUST carry neither. `render_text` MUST
    then add one `<id> - <label>` line per option, `(recommended)` on the recommended one, and a
    final `reply: /answer <task> <id>` line. The `TaskView` these read MUST carry the task's
    stored `question` and `brief`: `task_view` (the one builder, used by the inbox and by
    `POST /tasks/<id>/answer`) validates a stored question that has a `kind` as `QuestionV11`
    and any other as `Question`, so options reach `render_data` and the JSON views.
12. `flush(specs, sink_for, *, now) -> FlushReport` MUST load the persisted dedupe snapshot
    (`notify-state.json` under `DOCKET_HOME`), compute `diff_events` over `build_inbox(now=now)`,
    and save the new snapshot **before** delivering anything, so a crash mid-delivery never
    re-emits an event on the next flush — delivery is at-most-once by construction. For every
    event, `flush` MUST call the dialect `sink_for` returns once per enabled channel with
    `notify` in `capabilities` whose `on` matches the event's kind (directly, or via the
    `needs_you` shorthand for `task.input_required`/`approval.requested`/`task.blocked`/
    `approval.expiring`), building one `CloudEvent` per channel at that channel's `content`
    level; retry a failing delivery up to two further times within the same call; count a
    channel whose dialect has no `deliver` as `skipped`; and record the outcome in
    `channels-health.json` under `DOCKET_HOME` (`delivered`/`failed` counters,
    `lastOk`/`lastError`/`lastErrorAt`). `flush` MUST NOT import the delivery adapters itself —
    `sink_for` is supplied by its caller. A dialect that raises MUST count as a failed attempt;
    a sink factory or secret lookup that raises MUST count as one failed delivery without
    stopping the other channels; a failing inbox build or store read or write MUST end the flush
    with `FlushReport.error` set, and `flush` MUST NOT raise.
13. The `webhook` dialect MUST POST the `CloudEvent` as `application/cloudevents+json` to
    `config["url"]` with the Standard Webhooks headers: `webhook-id` (the event's `id`),
    `webhook-timestamp` (Unix seconds), and, when a secret is resolved, `webhook-signature:
    v1,<base64>` over `hmac-sha256(base64-decode(secret.removeprefix("whsec_")),
    f"{id}.{ts}.{body}")`. A missing `config.url`, a transport failure, or a non-2xx response
    MUST all report a failed `DeliveryResult` without raising.
14. The `command` dialect MUST run `config["argv"]` (a JSON-encoded list of strings, since
    `config` is `dict[str, str]`) — or, when `argv` is absent, a single-element argv from
    `config["command"]` (the built-in document's shape) — with the event JSON on stdin, a
    timeout of at most 10 seconds, never through a shell. A non-zero exit, a missing binary, a
    timeout, or a missing `argv`/`command` MUST all report a failed `DeliveryResult` without
    raising.
15. The `console` dialect MUST always succeed without sending anything — the console is already
    the inbox.
16. Bare `docket setup notify` MUST print usage without calling `flush`, and an undeclared
    action MUST exit 2. `docket setup notify flush` MUST call `flush` over the full channel
    catalog and print the event, delivered, failed and skipped counts (or `Nothing to send.`),
    exiting 1 when a delivery failed or the flush reported an `error` (printed); `--dry-run`
    MUST print each pending event's kind, pod and subject from `diff_events` without delivering
    or saving the snapshot. `docket setup notify
    test <name>` MUST build one synthetic `channel.test` event (`build_test_event`) and deliver
    it once through that one channel's dialect, regardless of its `on` subscription or `enabled`
    flag, reporting success or failure (exit 1). Every periodic sweep of `docket start` (with or
    without `--dispatch`) and `docket run`, after its summary, MUST each call `flush` once;
    `docket run` prints nothing beyond one warning line naming the failure count when a delivery
    failed and, when the flush found events and nothing delivers (item 17), the text
    `unreached_warning` returns.
17. **Console alone tells nobody, and docket says so.** `SILENT_DIALECTS` MUST name every dialect
    whose `deliver` sends nothing (`console`, item 15). `Catalog.delivering()` MUST return the
    sorted names of the enabled channels with `notify` in `capabilities` whose dialect is not
    silent, and `unreached_warning(delivering)` MUST return `None` when that list is non-empty
    and otherwise the one warning text every surface prints: that only `console` is on, that
    console sends nothing, that a parked task waits unseen until `docket inbox`, and the two
    first-rung fixes `docket setup notify enable desktop` and `docket setup notify enable ntfy
    --set topic=<topic>`. These surfaces MUST consume it: the health report (`docket setup
    --fix`) prints a `Notifications:` block, counted as an issue when at least one project agent
    exists and informational otherwise (`--json` carries `checks.notifications {ok,
    delivering}`); bare `docket setup`'s report shows a `notifications` piece (`console only
    (nobody is told)`, command `docket setup notify enable desktop`); `docket start --dispatch`
    prints it once at startup; `docket init` prints it after the created summary; `docket run`
    prints it after the post-run flush when that flush found events. No surface enables a
    channel on its own. Two offers are allowed, each acting only on a yes: `docket init` on a
    TTY where desktop notifications are available asks `Enable desktop notifications now?
    [Y/n]` (yes is the default) and then enables `desktop` and delivers one `channel.test` event
    through it; bare `docket setup` on a TTY, when nothing delivers, asks `Enable desktop
    notifications?` (when desktop notifications are available) and `Set up Telegram?`, both
    `[y/N]`. Off a TTY nothing is asked. A catalog where something delivers MUST print none of
    this beyond the health report's one success line naming the delivering channels.

### 6.1 Dialects

The `ntfy`, `desktop`, `email` and `telegram` dialects. Each is one `deliver(spec, event, *,
secret, timeout) -> DeliveryResult` reached through `sink_for`, and each MUST report every
failure as a failed `DeliveryResult` without raising.

1. The `ntfy` dialect MUST POST the body from `render_text` to `<server>/<topic>`, where
   `config["server"]` defaults to `https://ntfy.sh` (trailing `/` stripped) and
   `config["topic"]` is required (also checked when the channel is enabled, area 6 item 5). The
   request MUST include `Title: <title>` from `render_text` and `Priority: high` when the event
   type ends with `input_required` or `approval.requested`, else `Priority: default`. When a
   secret is resolved, it MUST include `Authorization: Bearer <secret>`. A missing `topic`, a
   transport failure, or a non-2xx response MUST report a failed `DeliveryResult`.
2. The `desktop` dialect MUST send a native OS notification with the title and body from
   `render_text`: on macOS `osascript -e 'display notification <body> with title <title>'`
   (both JSON-quoted), elsewhere `notify-send <title> <body>`. The binary MUST be located on
   `PATH` first; a missing binary, a timeout or a non-zero exit MUST report a failed
   `DeliveryResult`. It MUST never run through a shell.
3. The `email` dialect MUST send one SMTP message. `config` MUST contain `smtpHost`, `from` and
   `to` (non-empty, the keys of the built-in document) and MAY set `port` (default `587`, which
   MUST parse as an integer) and `user`; any of these missing or malformed MUST report a failed
   `DeliveryResult`. The `Subject` MUST be `[docket] <title>`, `From` the `from`, `To` the `to`,
   and the body `<body>` unchanged, all from `render_text`. The connection MUST use STARTTLS
   when the server offers it. A secret is needed only for a channel whose `secret` names one: the
   dialect MUST log in as `user` (else `from`) with it, MUST report a failed `DeliveryResult`
   when the named secret did not resolve, and MUST NOT send it over a connection that does not
   offer STARTTLS. A channel with no `secret` sends without logging in. Any exception in the
   sequence MUST report a failed `DeliveryResult`.
4. The dialects in this area MUST use the Python standard library only (no third-party package).
5. Content privacy (area 6 item 11) MUST be enforced upstream by `render_data`/`render_text`,
   not by these dialects — they deliver only what they are given and apply no redaction of
   their own.
6. The `telegram` dialect is the outbound half of Telegram (its `notify` capability). It MUST
   send `<title>\n<body>` from `render_text` to every chat id in `spec.actors` and to no other
   chat — never to every chat bound in `fleet.json` — using the resolved secret (the built-in
   document names `TELEGRAM_BOT_TOKEN`) as the bot token. A missing secret, an empty `actors`
   list, or a failed send to any chat MUST report a failed `DeliveryResult` naming the chat ids
   that failed. It MUST NOT initiate a conversation or resolve an approval: a chat that wants
   to act on the notification does so through the inbound verbs `telegram-integration.spec.md`
   owns.

### 7. Answers

1. `answer_task(project, task_id, action, content, *, channel, actor)` MUST be the one function
   every surface (CLI, HTTP, MCP, Telegram) calls to answer a parked question. It MUST refuse
   (`AnswerError`) a task that is not found in that pod, or is not `waiting_input`, or whose
   parked question does not match its position in the pipeline the task was dispatched through
   (the task's own named `pipeline` when it has one, else the pod's pipeline); it MUST validate *content* against the
   question's `requestedSchema` (`validate_answer`, or `validate_answer_v11` for a v1.1 question
   with options) and screen every string value in *content* through the Lead's `pre_input`
   policy hook as untrusted input, where a `block` raises `AnswerRejected` naming the policy and
   writes nothing. On success it MUST append the answer to the task's `answers[]` (question id,
   step, message, action, content, channel, actor, `answeredAt`, the question's `kind` and
   `createdAt` (the answered question is cleared, so the answer is the only record of them), and
   `optionId` when given), clear the task's `question`, and audit `task.answer` (never the content).
2. Answering an `input` step MUST resolve that step's own `on:` route with the outcome label
   `answered` (accept) or `declined`: a terminal `fail`/`stop` target (or a backward route past
   its cap, or an unknown target) settles the task `failed`/`done` immediately; any other
   target, or no route, reopens it `pending` behind a synthetic `role="operator"` hop whose
   `nextStep` the resume follows. Answering a consultation (a question with `kind`
   `clarification` or `decision`) reopens the task `pending` with a `consultAnswer` for the same
   step instead (see "Consult" item 5). Mechanics: `pod-dispatch.spec.md` "Operator input steps
   and answers".
3. An unanswered `waiting_input` task past its question's `expiresAt` MUST be moved by
   `sweep_expired_questions`, run on every periodic sweep of `docket start`, to `blocked` with
   `blockedReason: "input_expired"` — never `failed`; `docket task retry` reopens it. A question
   parked without its own `expiresAt` (a consultation) carries now plus the pod's
   `inputExpiryHours`.
   For tests, `DOCKET_CLOCK_OFFSET_S` (float seconds, unset or invalid is 0) shifts the wall
   clock `now()` that stamps and compares these deadlines; it never shifts the monotonic clock,
   so measured durations stay real.
4. An `input` step whose `from:` hop carries a Lead intake brief with its own `questions[]`
   asks those questions instead of the generic single free-text `answer` property; this changes
   only what `validate_answer` checks *content* against, never how an answer resolves or
   resumes.
5. This area owns four trace event types, each written to the task's session:
   - `input_requested` — an `input` step parked the task; payload `{task, step, questionId}`.
   - `question_asked` — a `consult` call posed a question; payload `{questionId, kind, mode,
     question}` (the full `QuestionV11`). When the pod decided it alone (Consult item 7) `mode` is
     `decided` and the payload adds `decidedOptionId`.
   - `input_answered` — `answer_task` succeeded; payload `{task, step, questionId, action}`.
   - `input_expired` — the expiry sweep blocked the task; payload `{task, questionId}`.

### 8. Telegram

1. No behaviour in the operator-v1 contract is Telegram-specific. The inbound verbs (including
   `/answer <task-id> <text>`, which calls `answer_task` with `channel="telegram"`) are
   `telegram-integration.spec.md`'s; the outbound `telegram` dialect is area 6.1 item 6.

### 9. Seeing it coming, and not being interrupted twice

`forecast(project, *, caller_default="wait") -> list[Interruption]` derives, from *project*'s
own effective configuration, everything that could pause a task and wait on a human — without
running a dispatch.

1. `forecast` MUST derive its `Interruption` items (`kind`, `description`, `detail`) from
   exactly these sources:
   - each of this pod's effective policies with hook `pre_tool_call` and action
     `require_approval`, kind `"policy"`, described as `policy '<id>' asks on: <words>` naming
     the predicate kinds (`tool bash on path src/**`, `commands matching its pattern`, `any of
     several conditions`, else `a structured predicate`), never the pattern text;
   - every class in `HIGH_RISK_PATTERNS`, kind `"high_risk_class"` — the classes the command
     classifier enforces on every bash call. Shown for visibility, never counted toward
     "nothing will ask" (item 3): they are a docket-wide invariant, listed on their own by
     `docket setup sandbox classes`;
   - the resolved pipeline's (`effective_pipeline(project, None)`) `ApprovalGate` and `input`
     steps, one level into a `parallel` group, kind `"pipeline_gate"`;
   - the resolved `approvalMode` (`pod_approval_mode(project, caller_default=caller_default)`)
     and `approvalExpiryHours` (24 when the pod settings cannot be read), kind `"mode"` —
     context for how an ask would be handled, never itself something that asks;
   - every enabled `kind: channel` document whose capabilities include `notify`, kind
     `"channel"`.
2. `docket task show <ref>` MUST render the forecast under `May ask you`: the
   `"policy"`/`"pipeline_gate"` items (the ones that can pause a task) as the
   headline list, the resolved `approvalMode`/expiry as one context line, and the high-risk
   classes (`Always enforced:`) and enabled notifying channels (`Will notify:`) each in their
   own labelled section, shown regardless of whether the headline is empty. With `--json`, it
   MUST carry the same items as an `interruptions` list of `{"kind", "description", "detail"}`
   objects beside the task's other fields. The caller default is `wait` on a TTY, else `park`.
3. When the headline list is empty, the forecast MUST print `Nothing in this pod will ask you.`
   in place of that list.
4. `docket task add` MUST print one additional summary line after queuing: `Nothing in this pod
   will ask you.` when the same headline list is empty, else `May ask you: <n> <kind>, ... --
   see: docket task show <short-id>` (kinds sorted, counts grouped by kind with `_` rendered as
   a space and the noun pluralised by count: `1 policy`, `2 policies`, `2 pipeline gates`).
5. `docket task approve <ref> --for "<command>" [--tool bash]`, `POST /tasks/<id>/pregrants`
   (body `{"pod", "command", "tool"?, "actor"?}`) and MCP `task_pregrant(project, task_id,
   command, tool="bash")` MUST each call `record_pregrant(project, task_id, command, tool=tool,
   channel=<"cli"|"http"|"mcp">, actor=<...>)`, which:
   - refuses (raising `InterruptionsError`, rendered as CLI exit 1 / HTTP 404 / an MCP
     `McpToolError`) when *task_id* is not in *project*'s own task list — a pre-grant never
     crosses pods;
   - collapses internal whitespace in *command* before digesting it (`" ".join(command.split())`)
     — the honest limit ADR 0016 states: a model that rephrases the command is asked again;
   - computes `canonical_args_digest(tool, {"command": normalized})`, the identical digest the
     tool-call gate computes for a live `bash` call;
   - calls `create_pregrant(project, "implementer", tool, args_digest, task_id=task_id,
     expires_at=<now + this pod's approvalExpiryHours, ISO UTC>, channel=channel, actor=actor)`,
     then appends `{"token", "tool", "argsDigest"}` to the task's `pregrants` list — the shape a
     parked grant appends — so the task's next hop is given it, not only a re-run after a park.

   `--for` with `--task` MUST be refused (exit 2). Non-goals (ADR 0016): fuzzy command matching;
   a role override for the stored `role` (always `"implementer"`, since matching is by `(tool,
   argsDigest)` alone and never reads it).

### 10. Answer surfaces

Every surface below calls `answer_task` (area 7); none re-implements schema validation, the
`pre_input` screen, or the resume. Telegram's `/answer` is `telegram-integration.spec.md`'s.

1. `docket task answer <ref> [text...] [--option <id>] [--field name=value]... [--decline]
   [--pod <p>]` MUST resolve *ref* as a full id, short id, prefix or run id (every pod unless
   `--pod` or `DOCKET_POD` names one) and call `answer_task(channel="cli", actor=<OS user>)`. A
   task without a pending question MUST be refused (exit 1, nothing sent). Bare `text` MUST fill
   the single property of a one-property `requestedSchema`, read from the task's own parked
   `question`; against a schema with more than one property it MUST be refused (exit 1, nothing
   sent) naming `--field name=value`. `--field` MAY be repeated; one without `=` exits 2.
   `--option <id>` MUST put `optionId` in `content`. `--decline` MUST set `action="decline"` and
   ignore `text`/`--field`/`--option`.
2. With no `text`, `--field` or `--option`: on a TTY the command MUST print the question and each
   option as `<id> - <label>` (the recommended one marked, its description beneath), prompt for
   the option id when the question has options (Enter takes the recommended one), then once per
   `requestedSchema` property (a blank optional property is omitted from `content`; a blank
   required one is passed through, so the schema check reports it — never a client-side retry
   loop) and call `answer_task(action="accept")`. Off a TTY it MUST exit 1 naming `--option
   <id>` (the ids listed) when the question has options, else naming text, `--field` and
   `--option`; it never prompts. When the question has options and the answer carries no
   `optionId` (and is not a decline), the command MUST exit 1 naming the option ids instead of
   sending an answer the contract would refuse. `docket inbox`'s human view MUST print a
   `waiting_input` task's question, its option ids and labels (the recommended one marked
   `(recommended)`) and the `docket task answer <task-id>` command beneath the task line, and a
   `waiting_approval` task's held action (`asks: <approval.action>`) with the `docket task
   approve <id>` / `docket task deny <id>` commands.
2a. `docket task approve <ref>` MUST resolve the task's pending approval from the task's own
   `approvalToken` (a task not `waiting_approval` is refused, exit 1; an `apr-` token is accepted
   as given, the one the progress view prints, and its pod is read from the approval record so
   the run hint below still names it) and grant it with `channel="cli"`; `--task` MUST set the
   `approve_task` option first, and `--once` (the default) conflicts with it (exit 2).
   `docket task deny <ref> [--reason <why>]` MUST deny the same approval and pass the reason on,
   so the failed task's `reason` reads `approval denied: <reason>` (`pod-dispatch.spec.md`).
   After a grant (except a check-changed approval, which completes the task), an answer, a
   pre-grant or a retry, whichever form the ref took, the command MUST end with the run hint:
   `docket is running and will pick it up` when `docket start` is running, else the single
   `Next: docket run --pod <p>` line. A granted pending task is the `approved ready` state
   `inbox` renders.
3. `docket task add --brief FILE.json` MUST parse the file as JSON and validate it as a
   `TaskBrief`; an unreadable file or a parse or validation failure MUST exit 1 and enqueue
   nothing. A well-formed brief MUST be stored on the enqueued task as its `brief`.
4. `POST /tasks/<id>/answer` MUST require the same `Authorization: Bearer <token>` as every
   other write route, then a JSON object body naming `pod` (string, required) and `action`
   (string, required); `content` (object, optional) and `actor` (string, optional label — the
   Bearer token remains the sole authority, and the channel is always `"http"`) round out the
   elicitation-result shape. A malformed body or a missing/ill-typed field MUST answer `400`.
   It MUST call `answer_task(channel="http", actor=<body.actor or "http">)` and, on success,
   respond with the answered task's `TaskView` (`by_alias`, JSON mode). Errors MUST map: an
   `AnswerRejected` to `422` naming its policy id; an `AnswerError` whose message contains
   `"not found in pod"` to `404`; one containing `"is not waiting_input"` or `"is not parked at
   step"` to `409`; any other `AnswerError` (a schema-validation message, relayed unchanged) to
   `422`. `POST /tasks/<project>` (task creation) MUST accept an optional `brief`: a non-object
   answers `400`, one that fails `TaskBrief` validation `422`, and a valid one is stored on the
   enqueued task exactly as `--brief` above.
5. MCP `task_answer(project, task_id, action, content=None)` MUST call `answer_task(
   channel="mcp", actor="mcp")` and return `{"ok": true, "task": task_id, "project": project,
   "action": result.action}` on success; an `AnswerRejected` or `AnswerError` MUST become a
   raised `McpToolError` (the SDK's own `isError` convention), naming the policy id or the
   underlying message respectively — never an inline error field.

### Profile lines (ADR 0025 D2)

1. When a dispatchable pod's effective profile (`security-gates.spec.md` "Profiles") is
   `lights-out`, the health report (`docket setup --fix`) prints a `Profile:` section after its
   security gates with one line per pod and one line per violation with its fix, and `docket
   status` prints a `Profile` row on the pod block listing the same violations;
   `status --json` carries `profile {name, violations: [{requirement, fix}]}` and the health
   report's JSON carries `checks.securityGates.profile {<pod>: {name, violations}}`, only then.
   Both compute the violations with `project_violations` (`gather_facts` plus
   `lights_out_violations`), the function dispatch refuses with. Under the `attended` profile
   neither prints a profile line or key.

### A task that edited its own check (ADR 0029 point 3)

1. A task whose finished diff touches a protected path parks `waiting_approval` with an approval
   of context kind `check_changed` and `checkChanged` on the task (`pod-dispatch.spec.md` "A
   change that edits its own check"), under every profile: `lights-out` does not skip it,
   because a person is what a check the change defined cannot be.
2. The task is an ordinary `needsYou` item: its `TaskView.reason` and the approval's `action`
   text name the paths (at most 20, then a count of the rest), `a2aState` is `INPUT_REQUIRED`,
   and the notification is `approval.requested` through the channels that already carry one. No
   event type, schema field or channel exists for it alone.
3. The approval is answered like any other (`docket task approve|deny`, `POST /approvals/<token>`,
   MCP, Telegram); a grant completes the task (`done`) instead of returning it to `pending`, a
   denial fails it with `failureKind: "check_changed"`.

## Interface Contracts

### Module API (the operator contract)

```python
A2AState = Literal[...]                # the eight A2A 1.0.0 TaskState names, in order
EVENT_KINDS: tuple[str, ...]           # task.input_required, approval.requested,
                                        # approval.expiring, task.blocked, task.failed,
                                        # task.rejected, task.completed, channel.test

def a2a_state(
    status: str, blocked_reason: str | None = None, failure_kind: str | None = None,
) -> str: ...                          # raises ValueError outside requirement area 1's table

class TaskBrief(BaseModel): ...        # objective, acceptance/context/constraints/assumptions/
                                        # questions/resources/answers, expectedRiskyActions
def validate_requested_schema(d: dict[str, Any]) -> dict[str, Any]: ...  # raises ValueError
class QuestionSchema(BaseModel): ...   # schema-generator wrapper for requestedSchema
def new_question_id() -> str: ...      # "q-<12 hex chars>"
class Question(BaseModel): ...         # id/taskId/pod/step/message/requestedSchema/createdAt/
                                        # expiresAt
class AnswerResult(BaseModel): ...     # action: accept|decline|cancel, content
def validate_answer(question: Question, result: AnswerResult) -> AnswerResult: ...  # raises

class ApprovalView(BaseModel): ...     # token/pod/taskId/role/tool/action/policy/state/
                                        # createdAt/expiresAt/a2aState
class TaskView(BaseModel): ...         # id/pod/status/a2aState/reason/description/priority/
                                        # createdAt/updatedAt/question/approvalToken/brief
class InboxView(BaseModel): ...        # needsYou/failed/doneSince/running/next

class CloudEvent(BaseModel): ...       # CloudEvents 1.0 structured-mode envelope
def make_event(
    kind: str, pod: str, subject: str, data: dict[str, Any], *, time: str, version: str,
) -> CloudEvent: ...                   # raises ValueError if kind not in EVENT_KINDS;
                                        # type "dev.docket.<kind>", source "urn:docket:pod:<pod>"

def canonical_args_digest(tool: str, args: dict[str, Any]) -> str: ...  # 16 hex chars
```

### Generated schemas (`docs/contracts/operator-v1/`)

`scripts/gen_operator_schemas.py` renders `task.schema.json`, `question.schema.json`,
`answer.schema.json`, `approval.schema.json`, `inbox.schema.json`, `brief.schema.json` and
`event.schema.json` from `TaskView`, `Question`, `AnswerResult`, `ApprovalView`, `InboxView`,
`TaskBrief` and `CloudEvent` respectively. `question.schema.json`'s `requestedSchema` property is
rendered from `QuestionSchema`, not the generic object the Python field carries, so the published
document constrains it to the MCP elicitation subset. Every document carries `$id`
`https://docket.dev/schemas/operator-v1/<name>.schema.json` and JSON Schema 2020-12's
`$schema`. `--check` exits 1 when any file on disk is stale; there is no package copy (contrast
`config-v1`, which ships one inside the wheel).

### Contract 1.1 (`docs/contracts/operator-v1.1/`)

An additive extension in the operator contract module; the v1 models are unchanged. The
`consult` tool produces `QuestionV11`; `answer_task` validates answers to it with
`validate_answer_v11`; `TaskView.question` carries a `QuestionV11` whenever the stored question
has a `kind`.

- `QuestionKind` = `approval | clarification | decision`.
- `Option{id, label, description, risks: list[str], estimatedTokens: int | None}` and
  `Recommendation{optionId, rationale, evidenceRefs: list[str]}` (camelCase aliases on the wire).
- `QuestionV11(Question)` adds `kind` (required), `options` (default empty) and `recommendation`
  (optional). Option ids MUST be unique and a recommendation's `optionId` MUST name an option.
- `AnswerResultV11(AnswerResult)` adds `optionId`.
- `validate_answer_v11(question, answer)`: when `action` is `accept` and the question has options,
  `optionId` is required and MUST name an option; `decline`/`cancel` need none. It then applies
  `validate_answer` to `content`.
- `scripts/gen_operator_schemas.py` also renders `question.schema.json` and `answer.schema.json`
  (with `Option` and `Recommendation` as `$defs`) there, `$id`
  `https://docket.dev/schemas/operator-v1.1/<name>.schema.json`; `--check` covers both directories.

### Consult

The `consult` built-in tool (kind `read`, so it stays available to read-only roles such as the
Reviewer) lets a model put a clarification or decision to its operator.

1. **Arguments.** `kind` (`clarification` or `decision`), `message`, `options` (at least two,
   each `id`, `label`, `description`, optional `risks` and `estimatedTokens`) and
   `recommendation` (`optionId`, `rationale`, optional `evidenceRefs`). The call builds a
   `QuestionV11` (minted `q-` id, `createdAt`, `taskId` = the dispatch task id, else the session
   key, `pod` = the turn's project, `step` = the role). The tool's JSON schema lists
   `recommendation` as required, so the chokepoint refuses a call without one as an `invalid_call`
   (`missing required argument(s): recommendation`) before the handler runs. Fewer than two
   options, an unknown kind or a recommendation naming no option is an ordinary error tool
   result (`invalid consultation: <problem>`). Neither is an exception or a question event.
2. **Budget.** The pod setting `maxConsultationsPerTask` (integer `>= 0`, default 3; 0 disables)
   reaches the turn as `ToolContext.max_consultations`: the driver takes the internal
   `DOCKET_MAX_CONSULTATIONS` key from the hop's environment, else reads the agent's pod setting.
   Counting is per turn; in pod dispatch the count is task-wide (item 5). A call past the cap is
   the error result `consultation budget exhausted; decide yourself` with no `question_asked`
   event; an invalid call does not spend budget.
3. **Wait (`approvalMode` `wait`, outside pod dispatch).** Nobody can answer a turn that is not a
   dispatch hop, so the call returns `no answer; decide yourself` at once, without an event.
4. **Refuse.** The call traces `question_asked` and ends the turn with the
   `approval_unavailable` stop an unanswerable approval uses. `park` outside pod dispatch is
   treated as `refuse`; under pod dispatch `approvalMode: refuse` also keeps this behaviour.
5. **Park and re-entry (pod dispatch).** A turn run for a dispatch hop (the driver is given the
   task id) parks consultations unless its approval mode is `refuse` (`wait` included: a pod hop
   has nobody waiting in-turn). A consult from any role then traces `question_asked`, ends the
   hop with the `approval_parked` stop, and the hop is persisted `parked`. The stop's token is
   `consult:<question id>`. `park_token` persists the `QuestionV11` (`consult-parked/<id>.json`
   under `DOCKET_HOME`, mode 0600) and `parked_question` takes it once (read, then removed);
   there is no in-process registry, so a restart or another process still parks correctly, and
   the token never carries question text, so no stop error, hop record or trace field holds it
   past redaction. A `consult:` token whose question cannot be read fails the task with
   `consult_question_missing`; it never waits as an approval. The task becomes `waiting_input`
   with `question` set to the consult's `QuestionV11` (`taskId` = the task id, `step` = the
   hop's step id), so the inbox lists it under `needsYou` and `docket task answer`, HTTP and MCP
   answers reach it through `answer_task` unchanged; `optionId` travels in the answer
   `content`. `answer_task` validates it with `validate_answer_v11` (accept needs a valid
   `optionId`; a refused answer leaves the task `waiting_input`), records `answers[]`, and
   reopens the task `pending` with a `consultAnswer` for the same step; the parked hop replays
   at its own index and its next message ends with `Operator answered your consultation <id>:
   option <id> (<label>)` (plus any note) or `... declined. Decide yourself.` A decline records
   one `declined_answer` correction. Each parked consult increments the task's `consultations`;
   once it is non-zero dispatch passes `DOCKET_MAX_CONSULTATIONS` = the setting minus that count
   (never below 0) as the hop's cap, so a fourth consult after three parked ones returns the
   budget-exhausted error. Intake `input` steps are unchanged.
6. **The description tells the truth.** The `consult` description the model reads **MUST** say
   that asking ends the turn (in pod dispatch the task waits for a person and the answer arrives
   in the role's next message; outside it the call returns `no answer; decide yourself` at once),
   that the model should decide and state its assumption instead of asking when the repository
   lets it recommend one option, that at least two options and a marked recommendation are
   required, and how many consultations remain on the task. Each hop renders that number from
   the hop's own cap (item 5), so it never exceeds what the handler will accept. The sentence
   about the effect is derived from what the handler will do, never fixed: it is the parking
   sentence above when the hop parks, the immediate `no answer; decide yourself` sentence when it
   cannot park, and, when the pod decides (item 7), that asking returns at once with the model's
   own recommendation applied and that it should prefer deciding in its reply without the tool.
7. **Decide (`consultMode`).** The pod setting `consultMode` (`park`, the default, or `decide`;
   `docket pod set consultMode decide`) reaches the turn as `ToolContext.consult_mode`, read by the
   driver from the agent's pod settings (an unreadable store is `park`). In pod dispatch (item 5)
   with `decide`, a valid consult whose budget allows it does not park: it traces `question_asked`
   with `mode` `decided` and `decidedOptionId` (the recommendation's option), audits
   `consult.decided` (`project`, `task`, `role`, `questionId`, `optionId`; never the message or the
   options), and returns the ordinary tool result `no operator on duty; your recommendation stands:
   option <id> (<label>). Continue.`, so the turn continues. The call spends budget like any
   consult and the task never becomes `waiting_input`, so the inbox lists nothing for it. The
   recommendation is always present (item 1); a call that fails validation is still the item 1
   error. `decide` changes nothing outside pod dispatch (items 3 and 4); inside it, it applies
   whatever the approval mode. The `lights-out` profile requires `decide` (security-gates.spec.md
   "Profiles").

## Examples

### The A2A mapping

```python
a2a_state("waiting_approval")                       # "INPUT_REQUIRED"
a2a_state("blocked", blocked_reason="resources")     # "AUTH_REQUIRED"
a2a_state("blocked", blocked_reason="budget")        # "INPUT_REQUIRED"
a2a_state("failed", failure_kind="rejected")         # "REJECTED"
a2a_state("failed")                                  # "FAILED"
```

### A question and a validated answer

```python
q = Question(
    id="q-0123456789ab", task_id="t-1", pod="alpha", step="ask",
    message="Which environment?",
    requested_schema={
        "type": "object",
        "properties": {"env": {"type": "string", "enum": ["staging", "prod"]}},
        "required": ["env"],
    },
    created_at="2026-09-28T00:00:00Z",
)
validate_answer(q, AnswerResult(action="accept", content={"env": "staging"}))  # ok
validate_answer(q, AnswerResult(action="accept", content={"env": "nope"}))     # raises ValueError
validate_answer(q, AnswerResult(action="decline"))                             # ok, content ignored
```

### An event's stable id

```python
first = make_event("approval.requested", "alpha", "apr-1", {}, time="t0", version="v1")
again = make_event("approval.requested", "alpha", "apr-1", {}, time="t1", version="v1")
first.id == again.id  # True: redelivering the same transition never mints a new id
```

### Matching a pre-grant

```python
a = canonical_args_digest("bash", {"command": "git push origin main"})
b = canonical_args_digest("bash", {"command": "git push origin main"})
a == b  # True regardless of argument dict key order
```

## Validation

### Pre-conditions

- Every model in the operator contract module with a camelCase wire field uses
  `populate_by_name=True` with `alias=...`, so a caller may construct it by either the Python
  name or the wire alias.
- Every model in that module uses `extra="forbid"`: an unknown key is rejected, never silently
  carried.

### Post-conditions

- `a2a_state` MUST return an `A2AState` for every status/reason/kind combination
  requirement area 1's table lists, and MUST raise for every other status.
- `validate_requested_schema` MUST return its input unchanged on success and MUST raise
  `ValueError` naming the offending key on failure; it MUST NOT mutate its argument.
- `validate_answer` MUST leave `decline`/`cancel` results unvalidated against `content`, and MUST
  raise `ValueError` naming the first missing or mismatched property for a rejected `accept`.
- `make_event` MUST raise `ValueError` for a `kind` outside `EVENT_KINDS` and MUST NOT construct
  a `CloudEvent` in that case.
- `canonical_args_digest` MUST return the same digest for the same tool name and the same
  arguments regardless of the arguments dict's key order, and MUST return a different digest for
  a different tool name given the same arguments.

### Invariants

- `EVENT_KINDS` MUST remain the only place a `dev.docket.<noun>.<verb>` event kind is
  enumerated; adding a kind edits `EVENT_KINDS`, and the channel `on:` vocabulary extends it
  with `needs_you` rather than redeclaring it.
- No value this module rejects (an unknown A2A status, a malformed `requestedSchema`, an
  out-of-vocabulary event kind) MUST ever reach a schema document, an HTTP response or a channel
  delivery — every producer of an operator-v1 value on those surfaces MUST construct it through
  this module's models and functions, never by hand-building an equivalent dict.

## Corrections

Deny reasons, REQUEST-CHANGES review texts, and declined answers are appended to a per-pod
append-only corrections ledger (`corrections/<project>.jsonl` under `DOCKET_HOME`) as a source of
truth for operator decisions and rejections. `docket task show <ref>` lists the corrections
recorded for that task (`corrections` under `--json`).

### Schema

Each JSONL line is a JSON object with these fields:

- `ts` (string, ISO 8601): when the correction was recorded
- `project` (string): the pod name
- `kind` (string): one of `deny_reason`, `request_changes`, `declined_answer`
- `taskId` (string): the task this correction applies to
- `role` (string): the role making the decision (`reviewer`, `operator`, etc.)
- `text` (string): the decision text, redacted (secret-shaped values replaced with
  `[REDACTED]`) and tail-bounded to 4000 characters
- `source` (string): where this came from (`cli`, `reviewer`, `answer`, etc.)

### Writers

1. **deny_reason**: recorded when an approval is denied with a non-empty reason in a project
   other than `operator` (source: the approval's channel); `taskId` is the task the approval
   record names (`taskId`, else `context.taskId` — set by dispatch's pre-hop and pipeline-step
   gates and by a parked in-turn call that serves a task), so `task show` lists it under its
   task. An approval that names no task is keyed empty.
2. **request_changes**: recorded when a Reviewer hop's verdict is `REQUEST-CHANGES` and a rework
   is triggered (source: `"reviewer"`, text: the hop output)
3. **declined_answer**: recorded when an answer to a parked question has `action == "decline"`
   (source: `"answer"`, role `"operator"`, text: always `"(declined)"`)

### Guarantees

- Write failures (OSError) are caught and logged, never fail the caller.
- File mode is 0600 on creation.
- Text is redacted with the same function as trace payloads.
- Read back in append order, optionally from a cursor: the ledger's `read(project, since=)`
  keeps records with `ts > since` (string compare on the ledger's UTC `isoformat()` form,
  `+00:00`; the caller normalises `since` into that form), and
  `GET /pods/<p>/corrections?since=` serves it (`operator-api.spec.md`).

## Implementation

- `src/docket/kernel/operator_contract.py`: `A2AState`, `EVENT_KINDS`, `a2a_state`, `TaskBrief`,
  `validate_requested_schema`, `QuestionSchema`, `new_question_id`, `Question`, `AnswerResult`,
  `QuestionKind`, `Option`, `Recommendation`, `QuestionV11`, `AnswerResultV11`,
  `validate_answer`, `validate_answer_v11`, `ApprovalView`, `TaskView`, `InboxView`,
  `CloudEvent`, `make_event`, `canonical_args_digest`
- `src/docket/operator/inbox.py`: `build_inbox`, `task_view`, `pending_memory`, `MemoryItem`
- `src/docket/operator/notify.py`: `diff_events`, `render_data`, `render_text`, `flush`,
  `FlushReport`, `NotifyEvent`, `build_test_event`, `read_state`, `resolve_secret`
- `src/docket/operator/channel.py`: `ChannelSpec`, `DIALECT_MAX`, `SILENT_DIALECTS`, `ON_KINDS`,
  `Catalog`, `load_catalog`, `load_channel_document`, `enable_channel`, `disable_channel`,
  `set_content`, `is_widening`, `export_channel`, `unreached_warning`
- `src/docket/operator/adapters/__init__.py`: `sink_for`
- `src/docket/operator/adapters/webhook.py`: `deliver`, `DeliveryResult`
- `src/docket/operator/adapters/{console,command,ntfy,desktop,email,telegram}.py`: each
  dialect's `deliver`
- `src/docket/templates/channels/01-console.yaml` … `07-telegram.yaml`: the seven built-in
  channel documents
- `src/docket/hops/application/answers.py`: `answer_task`, `AnswerError`, `AnswerRejected`,
  `sweep_expired_questions`
- `src/docket/hops/application/interruptions.py`: `forecast`, `Interruption`, `ASK_KINDS`,
  `NOTHING_WILL_ASK`, `record_pregrant`, `InterruptionsError`
- `src/docket/tasks/application/consult.py`: the `consult` handler, `park_token`, `parked_question`,
  `ConsultParked`, `ConsultUnavailable`, `DEFAULT_MAX_CONSULTATIONS`
- `src/docket/tasks/application/corrections.py`: `record`, `read`, `utc_cursor`
- `src/docket/agent/tools/registry.py`: `ToolContext` (`approval_mode`, `max_consultations`,
  `consult_park`, `consult_mode`, `pregrants`); `src/docket/governance/gate.py`: the park path (`_park`,
  `context.taskId`), the pre-grant matcher, the `approve_task` in-turn pre-grant
- `src/docket/teams/settings.py`: `pod_approval_mode`
- `src/docket/hops/application/steps.py`: `effective_pipeline`, `_run_input_step`
  (`input_requested`)
- `src/docket/tasks/application/repository.py`: `TaskRepository.list`, read by the operator
  through the `TaskReader` port (bound in `src/docket/bootstrap.py`)
- `src/docket/tasks/application/actions.py`: `resolve_waiting_approval`, `TASK_GRANT_CAP`
- `src/docket/hops/application/compose.py`: task-grant minting in `_compose_hop`
- `src/docket/tasks/application/record.py`: consult park conversion
- `src/docket/hops/gates/pre_hop.py`: `_park_if_check_changed`
- `src/docket/governance/approval.py`: `create_pregrant`, `consume_pregrant`, `approval_set_option`,
  `approval_sweep_expired`, the `deny_reason` correction
- `src/docket/hops/gates/profile.py`: `project_violations`, `gather_facts`, `lights_out_violations`,
  `lights_out_report`, `as_json`
- `src/docket/interfaces/telegram/bot.py`: `/status` rendering from `build_inbox`
- `src/docket/kernel/home.py`: the `Home` members `inbox_cursor_file`, `channels_file`,
  `notify_state_file`, `channels_health_file`, `consult_parked_dir`, `corrections_dir`
- `src/docket/kernel/templates.py`: `CHANNEL_TEMPLATES_DIR`
- `src/docket/models/document_fields.py`: `check_name`, `check_http_url`, `check_credential_name`, `reject_reserved_headers`
- `src/docket/interfaces/cli/commands/inbox.py`: `docket inbox`
- `src/docket/interfaces/cli/commands/setup_notify.py`: `docket setup notify`, `send_test`
- `src/docket/interfaces/cli/commands/task.py`: `docket task add|show|approve|deny|answer|retry`
- `src/docket/interfaces/cli/commands/setup.py`, `src/docket/interfaces/cli/commands/setup_check.py`: the `notifications` piece, the
  desktop/Telegram offers, the health report's `Notifications:` and `Profile:` blocks
- `src/docket/interfaces/cli/commands/agents.py`: `docket init`'s warning and desktop offer
- `src/docket/interfaces/cli/commands/run.py`: the post-run flush and the TTY approval default
- `src/docket/interfaces/cli/commands/status.py`: the `Profile` row
- `src/docket/interfaces/cli/commands/mcp.py`: MCP `inbox`, `task_answer`, `task_pregrant`
- `src/docket/interfaces/http/routes/inbox.py`: `GET /inbox`
- `src/docket/interfaces/http/routes/metrics.py`: `GET /metrics`
- `src/docket/interfaces/http/routes/task_control.py`: `POST /tasks/<id>/answer`,
  `POST /tasks/<id>/pregrants`
- `src/docket/interfaces/http/routes/task_create.py`: `POST /tasks/<project>` `brief`
- `src/docket/interfaces/http/server.py`: the periodic sweep
  (`sweep_expired_questions`, `flush`), the startup warning
- `scripts/gen_operator_schemas.py`, `scripts/gen_config_schemas.py`: the generated schemas
