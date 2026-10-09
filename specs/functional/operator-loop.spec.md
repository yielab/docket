# Operator Loop Specification

**Version**: 1.5.3
**Status**: Implemented — every requirement area shipped across Phase 34's Waves 64-69.
**Last Updated**: 2026-10-08

## Purpose

A docket operator who assigns work to a pod's Lead and walks away needs a way to learn that
something needs them, be asked a question rather than only a permission, and trust that
answering late never loses the work. This specification defines the shared `operator-v1`
contract every later Phase-34 requirement, surface and channel builds through:
`core/operator_contract.py`. It adopts existing standards rather than inventing docket-only
vocabulary — A2A 1.0.0 task states, an MCP-elicitation-shaped question/answer, CloudEvents 1.0
event envelopes — so any client that already understands one of those standards understands the
matching part of docket's operator loop unchanged.

## Scope

This specification covers:

- The task lifecycle vocabulary and its mapping onto the A2A 1.0.0 `TaskState` enumeration
- The typed intake brief a pod's Lead produces (`TaskBrief`)
- A question posed to a human and its answer, shaped as an MCP elicitation request/result
  (`Question`, `QuestionSchema`, `AnswerResult`, `validate_requested_schema`, `validate_answer`)
- The read views every surface (HTTP, CLI, MCP, channels) renders (`ApprovalView`, `TaskView`,
  `InboxView`)
- The CloudEvents 1.0 envelope every notification uses (`CloudEvent`, `make_event`,
  `EVENT_KINDS`)
- The stable digest that matches a tool call to a single-use pre-grant
  (`canonical_args_digest`)
- The generated JSON Schema documents under `docs/contracts/operator-v1/`
- How the derived inbox is assembled from live pod/approval state and exposed through every
  surface (`core/inbox.py`, `cli/_inbox.py`, `docket start`'s `GET /inbox`, `docket start --mcp`'s
  `inbox` tool, and Telegram's `/status`)
- The interruption forecast and the CLI/HTTP/MCP pre-grant surface (`core/interruptions.py`,
  `docket task show`'s forecast, `docket task approve --for`)

This specification does NOT cover (each is a distinct future requirement area below, owned by
its own card):

- How `POST /tasks` and `docket task add` accept a pre-brief end-to-end (the CLI/HTTP/MCP
  surfaces); `core.dispatch.enqueue_task` itself gaining a `brief=` parameter is covered by
  `pod-dispatch.spec.md`'s "Task brief" section, requirement area 3 above
- The `ntfy`, `desktop`, `email` and `telegram` dialects' own wire formats — requirement area 6
  below covers the diff/render/delivery framework and the `console`/`webhook`/`command`
  dialects; the remaining four each add one more `edges/adapters/channels/` module and one more
  `sink_for` entry in a later requirement area
- How an answer actually resumes a parked `input` pipeline step (`core/answers.py`)
- The Telegram channel amendment (`core/telegram.py`, `telegram-integration.spec.md`)

## Requirements

### 1. Task status and its A2A mapping

1. `a2a_state(status, blocked_reason=None, failure_kind=None)` MUST return exactly one of the
   eight `A2A_STATES` names for every docket task `status` this specification enumerates:

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
3. `A2A_STATES` MUST list exactly the eight names above, in A2A 1.0.0's own order, and MUST be
   the only place that vocabulary is enumerated (later requirement areas reference it, never
   redeclare it).

### 2. Park, don't block

**Status: Implemented.** The chokepoint half (`ToolContext.approval_mode: "park"`,
`core/tools.py`'s `_park_call`, the `approval_parked` denial kind and stop reason) and the
dispatch re-entry half (`core/dispatch.py`, `core/pod.py`) together answer requirement area 2's
question with no live wait: an unattended pod's in-turn `ask` records the call and durably
parks the task for a human, instead of blocking a thread for up to `TOOL_APPROVAL_TIMEOUT` or
losing the call outright under `"refuse"`. Full dispatch-side mechanics (resume position,
pre-grant matching, expiry) are `pod-dispatch.spec.md`'s "Parked approvals"; this area states the
operator-loop-level contract that section's behaviour must satisfy.

1. A parked task's docket `status` MUST be `waiting_approval`, mapping to `INPUT_REQUIRED` via
   requirement area 1's table — the same `a2aState` a pre-hop `require_approval` gate's
   `waiting_approval` already carries. A client reading `a2aState` alone cannot distinguish the
   two triggers, and MUST NOT need to: both mean "nothing runs until a human decides."
2. `core.operator_contract.canonical_args_digest(tool, args)` MUST be the one digest a parked
   call's record, a `resolve_waiting_approval` pre-grant, and `docket task approve --for`'s
   CLI-issued pre-grant (requirement area 9, deferred) all key against — so a CLI-issued
   pre-grant and an in-turn parked approval are matched identically by `core/tools.py`'s single
   matcher, never two independent digest implementations that could silently disagree.
3. An unset pod `approvalMode` MUST NOT resolve to a single fixed posture across every caller.
   `serve --dispatch`'s sweep and a non-interactive foreground dispatch MUST resolve it to
   `"park"`; an interactive foreground dispatch (a real TTY) MUST resolve it to `"wait"`. An
   explicit stored `approvalMode` always overrides the caller's own default.
4. A parked approval's own `expiresAt` MUST be honoured by the same fail-closed sweep that
   already expires a pre-hop gate's pending approval, resolving to **denied** past deadline —
   never a silent indefinite wait, and never a second expiry mechanism.
5. Granting a parked approval MUST NOT reuse the pre-hop gate's `gateOverridePipelineIndex`
   single-use override: that field exists to skip a gate at a position no hop ever ran, which
   does not describe an already-attempted, parked hop. The re-entry MUST instead re-run that
   exact hop, carrying a single-use pre-grant matched by `canonical_args_digest`, so the model's
   identical next call passes once without asking again.
5a. Granting a parked approval with the `approve_task` option (`docket task approve <task> --task`,
   Telegram `/approve <token> task`; the option is recorded with
   `approval_set_option` before the grant) MUST also record a task-wide grant
   `{tool, argsDigest, role, token, grantedAt, actor, channel}` in the task's `taskGrants`, where
   `role` is the parked approval's role, distinct from the single-use `pregrants`. `_compose_hop`
   MUST mint one fresh single-use pre-grant per entry whose `role` is the hop's role
   (`create_pregrant`, bound to the project and that role, task-scoped, expiring with the pod's
   approval window) for every later hop of that role, so each use is consumed and audited as any
   pre-grant; a hop of another role gets none. The match is exact on `(tool, argsDigest)`; the grant exists only on the `ask`
   path (a `deny` or policy block never creates an approval, so is never widened); a task holds
   at most 20 (the 21st is approved once only, audited as `approval.task_grant_refused` and
   reported to the operator); `taskGrants` is dropped when the task reaches a terminal status
   (done, failed, cancelled, or approval denied) and is never read by another task.
6. Non-goal (deliberately out of scope, ADR 0016): resuming the live model-turn session with the
   granted call's result injected in place of a hop re-run — deferred with a named trigger in
   the ADR (a measured rate of the re-run hop not re-issuing the granted call).

### 3. The Lead's intake

**Status: Implemented.** `TaskBrief`, its field validation (a non-empty `objective`, and every
`resources[]` entry prefixed `secret:`, `path:` or equal to `verify`) and the
`expectedRiskyActions` alias exist in this module, unchanged by this area. `core.handoff
.parse_brief`/`render_brief`, `HandoffArtifact.brief`, the recipe that produces a brief from a
Lead's reply (`templates/recipes/intake/`), the deterministic resource pre-check
(`core.dispatch._check_brief_resources`), the richer per-question schema derived from
`TaskBrief.questions[]`, and the Implementer's `## Brief` view are all `pod-dispatch.spec.md`'s
"Task brief" section — this area states the operator-loop-level contract that section's
behaviour must satisfy, the same split "Park, don't block" (area 2) has with "Parked approvals".

### 4. Task assignment in a standard shape

**Status: Implemented.** `TaskBrief` is the pre-brief shape `POST /tasks/<project>` and
`docket task add --brief FILE.json` accept, validate, and pass through to
`core.dispatch.enqueue_task`'s own `brief=` parameter — see area 10, "Answer surfaces",
requirements 3-4 for the exact CLI/HTTP contract.

### 5. One inbox, derived

**Status: Implemented.** `core/inbox.py::build_inbox(*, now, since=None) -> InboxView` is pure:
it takes the caller's current time and cursor as data and performs no writes and no clock reads
of its own.

1. `build_inbox` MUST enumerate every project that has at least one registered pod member —
   every provisioned pod, paused included — not the narrower set `core.dispatch.dispatchable_pods`
   exposes for dispatch eligibility.
2. For every pod, `build_inbox` MUST read its task list through `core.dispatch.read_tasks` and
   sort each task into exactly one of `needsYou`, `failed`, `doneSince` or `running` by its
   `status`, or omit it (`pending`, `cancelled`):
   - `needsYou`: any status starting `waiting_` (future-proof beyond today's `waiting_approval`),
     plus `blocked`.
   - `failed`: `status == "failed"`.
   - `doneSince`: `status == "done"` and, when `since` is given, only a task whose timestamp
     (below) is strictly later than `since`; every `done` task when `since` is omitted.
   - `running`: `status == "running"`.
3. `build_inbox` MUST read every pending approval through `core.approval.list_pending` and add
   one `ApprovalView` to `needsYou` for each **unless** its `context.taskId` is present or a
   task in `needsYou` holds its token as `approvalToken` — an approval already surfaced through
   its task MUST NOT also appear standalone, so nothing needing a decision is ever shown (or
   notified) twice. `core/tools.py::_park_call` MUST record `context.taskId` from
   `ToolContext.task_id` when the turn serves a task, so a parked call's record names it too.
4. Each item's `TaskView`/`ApprovalView` MUST carry its `a2aState` via
   `operator_contract.a2a_state`, passing `blocked_reason`/`failure_kind` from the task's own
   `blockedReason`/`failureKind` fields.
5. A task's timestamp, for sorting into `doneSince` and for `InboxView.next`, MUST be
   `completedAt`, else `startedAt`, else `created` (the caller's `now` only as a last-resort
   fallback when none is set). An approval's timestamp is its `created` field. `next` MUST be the
   maximum timestamp seen across every item considered (by parsed instant, not string order,
   since a task's ISO-with-offset timestamp and an approval's `Z`-suffixed one are not
   lexicographically comparable), or `None` when nothing was seen.
6. `docket inbox [--json] [--since <iso>] [--peek]` (`cli/_inbox.py`) MUST render the four
   sections (`Needs you`, `Failed`, `Done`, `Running`), `Needs you` first. Without `--peek` and
   without an explicit `--since`, it MUST advance a durable cursor (`config.INBOX_CURSOR_FILE`,
   written through `edges/store.py`) to `InboxView.next` after rendering, so a later plain
   call's `doneSince` only shows tasks that completed after the previous call. `--peek` and an
   explicit `--since` MUST NOT write the cursor. An undeclared flag MUST exit 2. Every item MUST
   print the exact command that moves it forward (`docket task approve|deny|answer <id>`,
   `docket task retry <id>`, `docket run --pod <pod>`), a held command or question in full, never
   truncated. A pending task whose approval was granted MUST appear under `Needs you` as
   "approved, ready" (`state: "approved_ready"`) with the `docket run` command. `--json` MUST emit
   `InboxView.model_dump(by_alias=True, mode="json")` with `state` and `command` added to each
   item, and no escape codes.
7. `GET /inbox?since=<iso>` (`serve.py`) MUST require the same `Authorization: Bearer <token>`
   as `GET /approvals` and return the identical JSON shape `docket inbox --json` prints for the
   same state.
8. `docket start --mcp`'s `inbox(since=None)` tool MUST return the same shape as `GET /inbox`.
9. `GET /metrics` MUST expose `docket_inbox_items{section="needsYou"|"failed"|"doneSince"|
   "running"}` as a gauge, one line per section, computed from `build_inbox(now=..., since=None)`.
10. Telegram's `/status` (`core/telegram.py`) MUST render from `build_inbox`, filtered to the
    bound agent's own scope (`_approval_scope`, unchanged from `telegram-integration.spec.md`
    requirement 3) by each item's `pod` field, `needsYou` first, then `failed`; it MUST NOT
    change the channel's inbound-only or plain-text constraints.

### 6. Notifications

**Status: Implemented.** Items 1-8 are the `kind: channel` document, catalog and CLI; items
9-16 are the diff/render/delivery framework and every v1 dialect, `console`/`webhook`/`command`
here and `ntfy`/`desktop`/`email`/`telegram` in area 6.1. `CloudEvent`, `make_event` and the
closed `EVENT_KINDS` vocabulary are defined (requirement area 1's module) and satisfy the CloudEvents 1.0
structured-mode shape. This area adds the destination side: what a channel document declares
about itself, what docket refuses to write or activate, and — from item 9 — how a transition
in the derived inbox becomes an event on the wire.

1. `core.channel.ChannelSpec` (`kind: channel`) MUST declare `dialect` (one of `console`,
   `desktop`, `webhook`, `command`, `ntfy`, `email`, `telegram`), `capabilities` (a subset of
   `{notify, converse, decide}`), `on` (event types this channel receives, from `EVENT_KINDS`
   plus the `needs_you` shorthand), `content` (`minimal | actions | conversation`, default
   `minimal` — never the export-only `full`; ADR 0016 §7), `actors` (identities allowed to
   converse or decide through it), `config` (dialect-specific settings), and `secret` (a
   credential **name**, never a value).
2. Each dialect MUST have a closed maximum capability set (`core.channel.DIALECT_MAX`):
   `console` and `telegram` may include `decide`; every other v1 dialect may only `notify`. A
   document declaring a capability past its dialect's maximum MUST be refused, naming the
   maximum, at parse time (unconditional — this is a structural property of the dialect, not
   of whether the document is enabled).
3. A document whose `capabilities` include `decide` or `converse` and whose `actors` is empty
   MUST be refused only once `enabled` is true, and never for `dialect: console` (the
   operator's own terminal, trusted without an allow-list). A *dormant* document (`enabled:
   false`, the default) MAY declare `decide`/`converse` with empty `actors` — this is the
   shape the built-in `telegram` template ships, so it can be catalogued before an operator
   names who may use it.
4. The channel catalog (`core.channel.load_catalog`) MUST merge two scopes nearest-wins by
   name: built-in documents under `config.CHANNEL_TEMPLATES_DIR` (seven shipped:
   `console`, `desktop`, `webhook`, `command`, `ntfy`, `email`, `telegram`) and the operator's
   own global entries in `config.CHANNELS_FILE`, through `edges/store.py`. Only `console` MUST
   ship enabled. Every built-in subscribes to `needs_you`; `desktop` and `ntfy`, the two
   dialects that reach an operator who walked away, MUST also subscribe to `task.failed`.
   None subscribes to `task.completed` by default (the inbox's `doneSince` carries it).
5. `enable_channel(name, overrides)` MUST refuse, without writing, a channel whose resulting
   document fails a dialect-specific precondition: `ntfy` requires a non-empty
   `config["topic"]`; `telegram` requires a non-empty `actors`. Every other built-in has no
   such precondition in this area.
6. `set_content(name, level)` MUST accept only `minimal`, `actions` or `conversation`, on the
   closed order `minimal < actions < conversation`; `core.channel.is_widening(old, new)` MUST
   return `True` exactly when `new` is strictly richer than `old`. The CLI (`docket setup notify
   privacy <name> <level>`) MUST treat a widening change as a confirmed, audited command,
   exactly as `docket setup export privacy` does: `--yes` proceeds immediately, a TTY is asked
   `y/N`, and a non-TTY refuses naming `--yes` without asking. Narrowing never asks.
7. `docket setup notify list|show|enable [--set k=v]|disable|add <file>|remove|export|privacy
   <name> [<level>] [--yes]` (`cli/_setup_notify.py`) MUST cover exactly this document's fields;
   it MUST NOT send anything to a dialect's actual destination — that is P34-11's `notify
   test`, `enable --test` and the delivery adapters.
8. `docket pod validate` MUST accept `kind: channel` (`core.config_docs.KINDS` gains `channel`;
   `core.config_docs._MODEL_FOR_KIND["channel"] = core.channel.ChannelSpec`), and
   `scripts/gen_config_schemas.py` MUST render `docs/contracts/config-v1/channel.schema.json`
   (and its package copy) directly from `ChannelSpec`, the same shape as `exporter`.
9. `core.notify.diff_events(prev, inbox, now) -> (events, snapshot)` MUST be pure (no clock, no
   I/O) and MUST emit one `NotifyEvent` per item in `inbox.needsYou`/`failed`/`doneSince` whose
   dedupe key is new, or whose version has changed, since `prev`. The dedupe key MUST be
   `task:<pod>:<id>` for a `TaskView` or `approval:<token>` for an `ApprovalView`; the version
   MUST be the item's status (or state) plus its question id or approval token, so a task
   re-asking a different question is treated as changed even when `status` itself repeats. The
   event kind MUST be `task.input_required` (`waiting_input`), `approval.requested`
   (`waiting_approval` or a standalone `ApprovalView`), `task.blocked`, `task.rejected` (a
   failed task whose `a2aState` is `REJECTED`), `task.failed` (any other failed task), or
   `task.completed`.
10. `diff_events` MUST additionally emit `approval.expiring` at most once per approval token,
    the first time 80% or more of the interval between its `createdAt` and `expiresAt` has
    elapsed; a token already recorded in the returned `snapshot`'s `expiring` list MUST NOT
    fire again.
11. `core.notify.render_data(item, level)` MUST enforce the three content levels on the
    `CloudEvent.data` it builds: `minimal` MUST NOT include an approval's rendered `action` or
    a task's `question`/`brief`; `actions` MUST add `action` (approvals only); `conversation`
    MUST add `question` and, when present, `brief` (tasks only). `core.notify.render_text(event)`
    MUST derive `(title, body)` only from *event*'s own already-leveled `data`, never from the
    source item, so a `minimal` event's text carries nothing a `minimal` event's data omitted.
    When a task's question is a `QuestionV11` with options, `conversation` MUST also add
    `options` (`[{id, label}]`, labels stripped of control characters and capped at 80
    characters) and, when recommended, `recommendation` (`{optionId}` only -- never the rationale
    or evidence); `minimal` and `actions` MUST carry neither. `render_text` MUST then add one
    `<id> - <label>` line per option, `(recommended)` on the recommended one, and a final
    `reply: /answer <task> <id>` line. The `TaskView` these read **MUST** carry the task's stored
    `question` and `brief`: `core.inbox.task_view` (the one builder, used by the inbox and by
    `POST /tasks/<id>/answer`) validates a stored question with `kind` as `QuestionV11`, so its
    options reach `render_data`; the JSON view still serializes the operator-v1 `question` shape.
12. `core.notify.flush(specs, sink_for, *, now) -> FlushReport` MUST load the persisted dedupe
    snapshot (`config.NOTIFY_STATE_FILE`), compute `diff_events`, and save the new snapshot
    **before** delivering anything, so a crash mid-delivery never re-emits an event on the next
    flush — delivery in this module is at-most-once, not at-least-once, by construction. For
    every event, `flush` MUST call `sink_for` once per enabled channel with `notify` in
    `capabilities` whose `on` matches the event's kind (directly, or via the `needs_you`
    shorthand for `task.input_required`/`approval.requested`/`task.blocked`/
    `approval.expiring`), retry a failing delivery up to two further times within the same
    call, and record the outcome in `config.CHANNELS_HEALTH_FILE` (`delivered`/`failed`
    counters, `lastOk`/`lastError`/`lastErrorAt`). `flush` MUST NOT import
    `edges/adapters/channels` itself — `sink_for` is supplied by its caller, the same seam
    `core/telemetry.py::start(specs, sink_for)` uses. `flush` MUST NOT raise.
13. The `webhook` dialect (`edges/adapters/channels/webhook.py::deliver`) MUST POST the
    `CloudEvent` as `application/cloudevents+json` to `spec.config["url"]` with the Standard
    Webhooks headers: `webhook-id` (the event's `id`), `webhook-timestamp` (Unix seconds), and,
    when a secret is resolved, `webhook-signature: v1,<base64>` over
    `hmac-sha256(base64-decode(secret.removeprefix("whsec_")), f"{id}.{ts}.{body}")`. A missing
    `config.url`, a transport failure, or a non-2xx response MUST all report a failed
    `DeliveryResult` without raising.
14. The `command` dialect (`edges/adapters/channels/command.py::deliver`) MUST run
    `spec.config["argv"]` (a JSON-encoded list of strings, since `config` is `dict[str, str]`)
    — or, when `argv` is absent, a single-element argv built from `spec.config["command"]` (the
    already-shipped built-in document's shape) — as `subprocess.run(argv, input=<event JSON>,
    timeout=min(timeout, 10), check=False)`, never `shell=True`. A non-zero exit, a missing
    binary, or a missing `argv`/`command` MUST all report a failed `DeliveryResult` without
    raising.
15. The `console` dialect (`edges/adapters/channels/console.py::deliver`) MUST always succeed
    without sending anything — the console is already the inbox.
16. Bare `docket setup notify` (and any action other than a declared one) MUST print usage or
    exit 2 without calling `core.notify.flush`. `docket setup notify flush [--dry-run]` MUST call `core.notify.flush` over the full channel
    catalog and print the delivered/failed/skipped counts; `--dry-run` MUST print the pending
    events from `diff_events` without delivering or advancing the persisted snapshot. `docket
    setup notify test <name>` MUST build one synthetic `channel.test` event
    (`core.notify.build_test_event`) and deliver it once through that one channel's dialect,
    regardless of the channel's `on` subscription, reporting success or failure — this and
    `docket setup notify flush` and `enable --test` are the only things in this specification's CLI surface that ever
    send anything to a real destination. `serve.py`'s periodic sweep and `docket run`'s
    foreground summary MUST each call `core.notify.flush` once, after their own
    work, with the CLI dispatch path printing nothing beyond one warning line naming the
    failure count when a delivery failed and, when the flush found events and nothing
    delivers (item 17), the one line `unreached_warning` renders.
17. **Console alone tells nobody, and docket says so.** `core.channel.SILENT_DIALECTS` MUST
    name every dialect whose `deliver` sends nothing (`console`, item 15).
    `Catalog.delivering()` MUST return the sorted names of the enabled channels with `notify`
    in `capabilities` whose dialect is not silent, and `core.channel.unreached_warning(
    delivering)` MUST return `None` when that list is non-empty and otherwise the one warning
    text every surface prints: that only `console` is on, that console sends nothing, that a
    parked task waits unseen until `docket inbox`, and the two first-rung fixes `docket setup notify
    enable desktop` and `docket setup notify enable ntfy --set topic=<topic>`. Four surfaces MUST
    consume it, none MAY enable a channel on its own: `docket setup`'s `Notifications:` block
    (counted as an issue when at least one project agent exists, informational otherwise;
    `--json` carries `checks.notifications {ok, delivering}`), `docket start --dispatch` once
    at startup, `docket init` after the created summary, and `docket run`'s
    post-run flush when that flush found events. One offer is allowed: `docket init` on a
    TTY where `edges.adapters.system.desktop_notifications_available()` holds MAY ask
    `Enable desktop notifications now? [Y/n]` and, only on a yes (the default), enable `desktop`
    and deliver one `channel.test` event through it so the operator sees it work; off a TTY
    nothing is asked. A catalog where something delivers MUST print none of this beyond
    `doctor`'s one success line naming the delivering channels.

### 6.1 Dialects

**Status: Implemented.** The `console`, `webhook`, and `command` dialects are delivered via
requirement area 6 items 1-16. The three dialects described here, plus the `telegram` dialect
area 8 owns, each add one more module under `edges/adapters/channels/` and one more entry to
`sink_for`.

1. The `ntfy` dialect (`edges/adapters/channels/ntfy.py::deliver`) MUST POST the event title and
   body to an ntfy.sh server via HTTP. `spec.config["server"]` (default `https://ntfy.sh`,
   `rstrip("/")` to normalize) and `spec.config["topic"]` are required; `config.topic` MUST be
   validated non-empty at parse time (requirement area 6 item 5). The request MUST include
   `Title` and `Priority` headers: `Title: <title>` from `render_text`, and
   `Priority: high` if the event kind ends with `input_required` or `approval.requested`, else
   `Priority: default`. When a secret is resolved, the request MUST include
   `Authorization: Bearer <secret>`. A missing `topic`, a transport failure, or a non-2xx
   response MUST all report a failed `DeliveryResult` without raising.

2. The `desktop` dialect (`edges/adapters/channels/desktop.py::deliver`) MUST send a native OS
   notification. On macOS, execute `osascript -e display\ notification …` with the title and
   body from `render_text`; on all other platforms, execute `notify-send title body`. The binary
   MUST be located via `shutil.which` first; if missing, return a failed `DeliveryResult` without
   raising. Execution MUST use `subprocess.run`, never `shell=True`, and a non-zero exit MUST
   report a failed `DeliveryResult` without raising.

3. The `email` dialect (`edges/adapters/channels/email.py::deliver`) MUST send an SMTP email.
   `spec.config` MUST contain `host` (non-empty), `port` (default `587`, parsed as integer),
   `user`, and `to`; a missing field MUST report a failed `DeliveryResult`. The email `Subject`
   MUST be `[docket] <title>` from `render_text`, and the body MUST be `<body>` unchanged. The
   connection MUST call `smtplib.SMTP(host, int(port), timeout=timeout)`, followed by
   `starttls()`, `login(user, secret)`, `send_message(msg)`, and `quit()`. Any exception in
   this sequence MUST be caught and reported as a failed `DeliveryResult` without raising.

4. All three new dialects MUST use stdlib only — `urllib.request`, `subprocess`, `shutil`,
   `smtplib`, `email.message`, `json`, `sys`.

5. Content privacy (requirement area 6 item 11) MUST be enforced upstream by `render_text`, not
   by these modules themselves — they deliver only what they are given, applying no redaction of
   their own.

### 7. Answers

**Status: Implemented.** `core/answers.py::answer_task(project,
task_id, action, content, channel=, actor=)` resumes a parked `input` step: it builds an
`AnswerResult`, validates *content* against the question's `requestedSchema` via
`validate_answer`, screens every string value in *content* through
`core.policy.policy_eval_detail("lead", "pre_input", value, trusted=False)` (a `block` raises
`AnswerRejected` and writes nothing), appends the answer to the task's `answers[]`, and resolves
the step's own `on:` route -- a terminal `fail`/`stop` target settles the task `failed`/`done`
right here; any other target (or none) reopens it `pending`, carrying a synthetic
`role="operator"` hop whose `nextStep` the resume builder follows on the next claim, with
`route_counts` rebuilt from that same persisted field exactly as any other routed hop's.
`core.answers.sweep_expired_questions`, run from every `serve --dispatch` sweep, moves an
unanswered `waiting_input` task past its question's `expiresAt` to `blocked`/
`blockedReason: "input_expired"` -- never `failed`. Full mechanics: pod-dispatch.spec.md,
"Operator input steps and answers". An `input` step whose `from:` hop carries a Lead intake
brief with its own `questions[]` asks those specific questions instead of the generic single
free-text `answer` property (area 3, "The Lead's intake"); `answer_task` and this area's own
mechanics are otherwise unchanged either way -- the richer schema only changes what
`validate_answer` checks *content* against, never how an answer resolves or resumes.

### 8. Telegram (the one amended boundary)

**Status: Implemented.** No behaviour in this module is Telegram-specific; the amendment to
`telegram-integration.spec.md` Command grammar 7, the fifth `/answer <task-id> <text>` verb
(`core/telegram.py`), and the outbound `telegram` channel dialect
(`edges/adapters/channels/telegram.py`) are that spec's own requirements.

### 9. Seeing it coming, and not being interrupted twice

**Status: Implemented.** `core/interruptions.py::forecast(project, *, caller_default="wait") ->
list[Interruption]` derives, from *project*'s own effective configuration, everything that could
pause a task and wait on a human -- without ever running a live dispatch.

1. `forecast` MUST derive its `Interruption` items from exactly these sources, matching what a
   live dispatch would actually evaluate:
   - this pod's own effective `require_approval` policies (`core.policy.policy_files(project)` +
     `core.policy.read_policy` -- the identical loader `docket pod check --pod` uses), kind
     `"policy"`, naming the policy id and its pattern (`match.pattern`, or `when.matches` when the
     canonical document carries no top-level `match`);
   - `core.security.HIGH_RISK_PATTERNS`, kind `"high_risk_class"` -- the same classes
     `classify_command` enforces unconditionally on every bash call. Shown for visibility, never
     counted toward "nothing will ask" (item 3 below): they are a docket-wide invariant, not this
     pod's own configuration, and already have their own listing (`docket setup sandbox classes`);
   - the resolved pipeline's (`core.dispatch.effective_pipeline(project, None)`) own
     `ApprovalGate` and `input` steps, one level into a `parallel` group, kind `"pipeline_gate"`;
   - the pod's `requireApprovalRoles` (Lead meta, comma-split, lower-cased), kind `"role_gate"`;
   - the resolved `approvalMode` (`core.dispatch.pod_approval_mode(project,
     caller_default=caller_default)`) and `approvalExpiryHours`
     (`core.pod.PodSettings.load_for(project)`), kind `"mode"` -- context for how an ask would be
     handled, never itself something that asks;
   - every enabled `kind: channel` document (`core.channel.load_catalog()`) whose capabilities
     include `notify`, kind `"channel"`.
2. `docket task show <ref>` MUST render the forecast: the
   `"policy"`/`"pipeline_gate"`/`"role_gate"` items (the ones that can actually pause a task) as
   the headline list, the resolved `approvalMode`/expiry as one context line, and the high-risk
   classes and enabled notifying channels each in their own labelled section, shown regardless of
   whether the headline is empty. With `--json`, it MUST carry the same items as an `interruptions` list of
   `{"kind", "description", "detail"}` objects beside the task's other fields.
3. When the headline list (`"policy"`/`"pipeline_gate"`/`"role_gate"`) is empty, the forecast MUST print `Nothing in this pod will ask you.` in place of that list.
4. `docket task add` MUST print one additional summary line after queuing:
   `Nothing in this pod will ask you.` when the same headline list is empty, else `May ask you:
   <n> <kind>, ... — see: docket task show <ref>` (kinds sorted, counts
   grouped by kind with `_` rendered as a space and the noun pluralised by count: `1 policy`,
   `2 policies`, `2 pipeline gates`). A `policy` interruption's description is
   `policy '<id>' asks on: <words>`, naming the predicate kinds (`tool bash on path src/**`,
   `commands matching its pattern`), never the pattern text.
5. `docket task approve <ref> --for "<command>" [--tool bash]`, `POST /tasks/<id>/pregrants`
   (body `{"pod", "command", "tool"?, "actor"?}`) and MCP `task_pregrant(project, task_id,
   command, tool="bash")` MUST each call `core.interruptions.record_pregrant(project, task_id,
   command, tool=tool, channel=<"cli"|"http"|"mcp">, actor=<...>)`, which:
   - refuses (raising `InterruptionsError`, rendered as CLI exit 1 / HTTP 404 / an MCP
     `McpToolError`) when *task_id* is not present in *project*'s own `read_tasks` -- a pre-grant
     never crosses pods;
   - collapses internal whitespace in *command* before digesting it (`" ".join(command.split())`)
     -- the honest limit ADR 0016 §10 states: a model that rephrases the command is asked again
     regardless;
   - computes `args_digest = core.operator_contract.canonical_args_digest(tool, {"command":
     normalized})` -- the identical digest `core/tools.py`'s park/consume matcher computes for a
     live `bash` call, so a CLI-issued pre-grant and an in-turn parked approval are matched
     identically;
   - calls `core.approval.create_pregrant(project, "implementer", tool, args_digest,
     task_id=task_id, expires_at=<now + this pod's approvalExpiryHours, ISO UTC>,
     channel=channel, actor=actor)` unchanged, then appends `{"token", "tool", "argsDigest":
     args_digest}` to the task's own `pregrants` list (`edges.store.read_modify_write` on
     `core.dispatch.pod_task_list_path(project)`) -- the exact shape
     `resolve_waiting_approval`'s own parked-grant append already produces, so `_compose_hop`
     serialises it into `DOCKET_PREGRANTS` on the task's very next hop, not only a re-run after a
     park.
Non-goals (ADR 0016 §10): fuzzy command matching -- the exact-after-whitespace-collapse limit in
item 5 is the only normalisation applied, and a rephrased command is asked again regardless; a
`--role` override for `create_pregrant`'s stored `role` field (fixed to `"implementer"`, since
matching is by `(tool, argsDigest)` alone and never reads it).

### 10. Answer surfaces

**Status: Implemented (CLI, HTTP, MCP; Telegram is area 8's own card).** Every
surface below calls `core.answers.answer_task` directly (area 7) -- none re-implements schema
validation, the `pre_input` screen, or the resume. ADR 0016 §8 names these as "two core
functions, every surface is transport"; this area is that transport.

1. `docket task answer <ref> [text...] [--option <id>] [--field name=value]... [--decline]
   [--pod <p>]` (`cli/_task.py::_task_answer`) MUST resolve *ref* through
   `core.task_ref.resolve_task` (full id, short id, prefix or run id; every pod unless `--pod`)
   and call `answer_task(channel="cli", actor=<OS user via getpass.getuser()>)`. A task without a
   pending question MUST be refused (exit 1, nothing sent). Bare `text` MUST fill the single
   property of a one-property `requestedSchema`, read from the task's own parked `question`;
   against a schema with more than one property it MUST be refused (exit 1, nothing sent)
   naming `--field name=value`. `--field` MAY be repeated. `--option <id>` MUST put `optionId`
   in `content`. `--decline` MUST set `action="decline"` and ignore `text`/`--field`/`--option`.
2. With no `text`, `--field` or `--option`: on a TTY the command MUST print the question and each
   option as `<id> - <label>` (the recommended one marked, its description beneath), prompt for
   the option id when the question has options (Enter takes the recommended one), then once per
   `requestedSchema` property (a blank optional property is omitted from `content`; a blank
   required one is passed through unchanged, so the schema check reports it -- never a
   client-side retry loop) and call `answer_task(action="accept")`. Off a TTY it MUST exit 1
   naming `--option <id>` (the ids listed) when the question has options, else the three
   flags; it never prompts. When the question has options and the answer carries no `optionId`
   (and is not a decline), the command MUST exit 1 naming the option ids instead of sending an
   answer the contract would refuse. `docket inbox`'s human view MUST print a `waiting_input`
   task's question, its option ids and labels (the recommended one marked `(recommended)`) and
   the `docket task answer <task-id>` command beneath the task line, and a `waiting_approval`
   task's held action (`asks: <approval.action>`) with the `docket task approve <id>` /
   `docket task deny <id>` commands -- what the standalone approval line carried before inbox
   item 3 folded it into its task.
2a. `docket task approve <ref>` MUST resolve the task's pending approval from the task's own
   `approvalToken` (a task not `waiting_approval` is refused, exit 1; an `apr-` token is accepted
   as given, the one the progress view prints, and its pod is read from the approval record so
   the run hint below still names it) and grant it with `channel="cli"`; `--task` MUST
   set the `approve_task` option first, and `--once` (the default) conflicts with it (exit 2).
   `docket task deny <ref>` MUST deny the same approval and hand `--reason` to
   `resolve_waiting_approval` so the failed task's `reason` reads `approval denied: <reason>`
   (pod-dispatch.spec.md). After a grant, an answer, a pre-grant or a retry, whichever form the
   ref took, the command MUST end with the run hint: `docket is running and will pick it up` when
   the service's pid check says `docket start` is running, else the single `Next: docket run
   --pod <p>` line. A granted pending task is the "approved, ready" state `inbox` and `status`
   render.
3. `docket task add --brief FILE.json` (`cli/_task.py`) MUST parse the
   file as JSON and validate it as a `TaskBrief`; a parse or validation failure MUST exit 1
   and enqueue nothing. A well-formed brief MUST be passed through to
   `core.dispatch.enqueue_task`'s own `brief=` parameter and actually enqueue.
   `_pod._ENQUEUE_ACCEPTS_BRIEF` (checked once via `inspect.signature`) is a self-correcting
   guard against a stale build whose `enqueue_task` predates the parameter -- present, but
   never triggered against this module's own `core.dispatch`.
4. `POST /tasks/<id>/answer` (`serve.py::_handle_post_task_answer`) MUST require the same
   `Authorization: Bearer <token>` as every other write route, then a JSON object body naming
   `pod` (string, required) and `action` (string, required); `content` (object, optional) and
   `actor` (string, optional label -- the Bearer token remains the sole authority, and the
   channel is always `"http"`) round out the elicitation-result shape. It MUST call
   `answer_task(channel="http", actor=<body.actor or "http">)` and, on success, respond with
   the answered task's `TaskView` (`by_alias`, `mode="json"`). Errors MUST map: an
   `AnswerRejected` to `422` naming its `policy_id`; an `AnswerError` whose message contains
   `"not found in pod"` to `404`; one containing `"is not waiting_input"` or `"is not parked at
   step"` to `409`; any other `AnswerError` (a schema-validation `ValueError`, relayed
   unchanged) to `422`. `POST /tasks/<project>` (task creation) gained an optional `brief`
   field, validated the same way as `--brief` above and, once valid, passed through to
   `enqueue_task`'s `brief=` parameter the identical way -- not a second guess at its shape.
5. MCP `task_answer(project, task_id, action, content=None)` (`cli/_mcp.py::tool_task_answer`)
   MUST call `answer_task(channel="mcp", actor="mcp")` and return `{"ok": true, "task":
   task_id, "project": project, "action": result.action}` on success; an `AnswerRejected` or
   `AnswerError` MUST become a raised `McpToolError` (the SDK's own `isError` convention),
   naming the policy id or the underlying message respectively -- never an inline error field.

## Interface Contracts

### Module API (`docket.core.operator_contract`)

```python
A2A_STATES: tuple[str, ...]            # the eight A2A 1.0.0 TaskState names, in order
EVENT_KINDS: tuple[str, ...]           # the closed vocabulary of dev.docket.<noun>.<verb> kinds

def a2a_state(
    status: str, blocked_reason: str | None = None, failure_kind: str | None = None,
) -> str: ...                          # raises ValueError outside requirement area 1's table

class TaskBrief(BaseModel): ...        # objective, acceptance/context/constraints/assumptions/
                                        # questions/resources/answers, expectedRiskyActions
def validate_requested_schema(d: dict[str, Any]) -> dict[str, Any]: ...  # raises ValueError
class QuestionSchema(BaseModel): ...   # schema-generator wrapper for requestedSchema
def new_question_id() -> str: ...      # "q-<12 hex chars>"
class Question(BaseModel): ...         # id/taskId/pod/step/message/requestedSchema/created/expires
class AnswerResult(BaseModel): ...     # action: accept|decline|cancel, content
def validate_answer(question: Question, result: AnswerResult) -> AnswerResult: ...  # raises

class ApprovalView(BaseModel): ...     # token/pod/taskId/role/tool/action/policy/state/…/a2aState
class TaskView(BaseModel): ...         # id/pod/status/a2aState/…/question/approvalToken/brief
class InboxView(BaseModel): ...        # needsYou/failed/doneSince/running/next

class CloudEvent(BaseModel): ...       # CloudEvents 1.0 structured-mode envelope
def make_event(
    kind: str, pod: str, subject: str, data: dict[str, Any], *, time: str, version: str,
) -> CloudEvent: ...                   # raises ValueError if kind not in EVENT_KINDS

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

An additive extension in `docket.core.operator_contract`; v1 models and schemas are unchanged.

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
  No producer or consumer of these models exists yet.

### Consult (P36-7)

The `consult` built-in (`core/consult.py`, registered in `core/tools.py`, kind `read`, so
`BUILTIN_TOOL_KINDS` keeps it for read-only roles such as the Reviewer) lets a model put a
clarification or decision to its operator.

1. **Arguments.** `kind` (`clarification` or `decision`), `message`, `options` (at least two,
   each `id`, `label`, `description`, optional `risks` and `estimatedTokens`) and
   `recommendation` (`optionId`, `rationale`, optional `evidenceRefs`). The call builds a
   `QuestionV11` (minted `q-` id, `createdAt`, `taskId` = the session key, `pod` = the turn's
   project, `step` = the role). A missing recommendation, fewer than two options, an unknown kind
   or a recommendation naming no option is an ordinary error tool result naming the problem, never
   an exception and never a question event.
2. **Budget.** The pod setting `maxConsultationsPerTask` (integer `>= 0`, default 3; 0 disables)
   reaches the turn as `ToolContext.max_consultations`: the driver pops the internal
   `DOCKET_MAX_CONSULTATIONS` env key, else reads the agent's pod setting. Counting is per
   `ToolContext`, i.e. per turn; in harness single-turn mode that is per task. In pod dispatch
   the count is task-wide (item 5). A call past the cap is an error result "consultation budget exhausted; decide yourself" with no
   `question_asked` event; an invalid call does not spend budget.
3. **Wait (`approvalMode` `wait` with an answer reader).** The call traces `question_asked`
   (`{questionId, kind, mode, question}`; telemetry exports only `questionId`, `kind`, `mode`)
   and blocks until `core.consult.submit` delivers an answer, polling cancellation, for at most
   `TOOL_APPROVAL_TIMEOUT` (`--answer-timeout` under the harness). The answer is validated with
   `validate_answer_v11` against the question; the tool result is the JSON `{action, optionId,
   content}`. No answer in time returns "no answer; decide yourself". The only answer reader is
   the harness stdin reader (harness-mode spec Section 5 item 9); with none open, the call
   returns the same "no answer" result at once without an event.
4. **Refuse.** The call traces `question_asked` and ends the turn with the
   `approval_unavailable` stop an unanswerable approval uses, so a harness run is `blocked` and
   its 1.1 result carries the `question`. `park` outside pod dispatch (no `consult_park`) is
   treated as `refuse`; under pod dispatch `approvalMode: refuse` also keeps this behaviour.
5. **Park and re-entry (pod dispatch, P36-8).** A turn run for a dispatch hop (the driver is
   given the task id) sets `ToolContext.consult_park` unless its approval mode is `refuse`
   (`wait` included: a pod hop has no stdin reader). A consult from any role then traces `question_asked`, ends the hop
   with the `approval_parked` stop and the hop is persisted `parked`. The stop's token is
   `consult:<question id>`. `consult.park_token` persists the `QuestionV11` through
   `edges/store.py` (`config.CONSULT_PARKED_DIR/<id>.json`, 0600) and `consult.parked_question`
   takes it once (read, then removed); there is no in-process registry, so a restart or another
   process still parks correctly, and the token never carries question text, so no stop error,
   hop record or trace field holds it past redaction. A `consult:` token whose question
   cannot be read fails the task with `consult_question_missing`; it never waits as an
   approval. A question's `taskId` is `ToolContext.task_id` (the dispatch task id; the harness
   run token), falling back to the session key only when empty. The task becomes `waiting_input` with `question` set to the consult's `QuestionV11`
   (`taskId` = the real task id, `step` = the hop's step id), so the inbox lists it under
   `needsYou` and `docket task answer`, HTTP, MCP and recipe-harness answers reach it through
   `answer_task` unchanged; `optionId` travels in the answer `content`. `answer_task` validates a
   v1.1 question with `validate_answer_v11` (accept needs a valid `optionId`; a refused answer
   leaves the task `waiting_input`), records `answers[]`, and reopens the task `pending` with a
   `consultAnswer` for the same step; the parked hop replays at its own index and its next
   message ends with "Operator answered your consultation <id>: option <id> (<label>)" or
   "... declined. Decide yourself." A decline records one `declined_answer` correction.
   `maxConsultationsPerTask` counts task-wide: each parked consult increments the task's
   `consultations`, and once it is non-zero dispatch passes `DOCKET_MAX_CONSULTATIONS` = the
   setting minus that count as the hop's cap (a fourth consult after
   three parked ones returns the budget-exhausted error). Intake `input` steps are unchanged.

## Examples

### The A2A mapping

```python
from docket.core.operator_contract import a2a_state

a2a_state("waiting_approval")                       # "INPUT_REQUIRED"
a2a_state("blocked", blocked_reason="resources")     # "AUTH_REQUIRED"
a2a_state("blocked", blocked_reason="budget")        # "INPUT_REQUIRED"
a2a_state("failed", failure_kind="rejected")         # "REJECTED"
a2a_state("failed")                                  # "FAILED"
```

### A question and a validated answer

```python
from docket.core.operator_contract import AnswerResult, Question, validate_answer

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
from docket.core.operator_contract import make_event

first = make_event("approval.requested", "alpha", "apr-1", {}, time="t0", version="v1")
again = make_event("approval.requested", "alpha", "apr-1", {}, time="t1", version="v1")
first.id == again.id  # True: redelivering the same transition never mints a new id
```

### Matching a pre-grant

```python
from docket.core.operator_contract import canonical_args_digest

a = canonical_args_digest("bash", {"command": "git push origin main"})
b = canonical_args_digest("bash", {"command": "git push origin main"})
a == b  # True regardless of argument dict key order
```

## Validation

### Pre-conditions

- Every model in this module uses `populate_by_name=True` with `alias=...` for its `camelCase`
  wire fields, mirroring `core/conversations.py`, so a caller may construct one by either the
  Python name or the wire alias.
- Every model uses `extra="forbid"`: an unknown key is rejected, never silently carried.

### Post-conditions

- `a2a_state` MUST return a value from `A2A_STATES` for every status/reason/kind combination
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
  enumerated; a future card adding a kind edits this module, never redeclares one elsewhere.
- No value this module rejects (an unknown A2A status, a malformed `requestedSchema`, an
  out-of-vocabulary event kind) MUST ever reach a schema document, an HTTP response or a channel
  delivery — every producer of those surfaces MUST construct its value through this module's
  functions, never by hand-building an equivalent dict.

## Corrections

Deny reasons, REQUEST-CHANGES review texts, and declined answers are appended to a per-pod
append-only corrections ledger (`~/.docket/corrections/<project>.jsonl`) as a source of truth
for operator decisions and rejections. The ledger is read back through `docket task show <ref>`, which lists
the corrections recorded for that task (`corrections` under `--json`).

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

1. **deny_reason**: recorded when `approval_deny()` is called with a non-empty `reason`
   parameter (source: the approval's `channel`); `taskId` is the id the gate stored in the
   record's `context` (dispatch's pre-hop and pipeline-step gates), so `task show` lists it under
   its task. A parked in-turn call's record names no task and its correction is keyed empty
2. **request_changes**: recorded when a Reviewer hop's verdict is `REQUEST-CHANGES` and a rework
   is triggered (source: `"reviewer"`, text: the hop output)
3. **declined_answer**: recorded when an answer to a parked input step has `action == "decline"`
   (source: `"answer"`, text: always `"(declined)"`)

### Guarantees

- Write failures (OSError) are caught and logged, never fail the caller.
- File mode is 0600 on creation.
- Text is redacted with the same function as trace payloads.

## Changelog

### Version 1.5.3 (2026-10-08)

- The `task add` summary pluralises its counts, and a policy interruption is described in words
  (its predicate kinds) instead of its raw regex. Requirement 4 says what now holds.

### Version 1.5.2 (2026-10-08)

- Found by the Phase 39 live run: `task approve <apr-token>` printed no run hint (the record's
  `project` now supplies the pod), and a deny's reason never reached its task (`approval_deny`
  keyed the `deny_reason` correction by a top-level `taskId` the record stores under `context`,
  so `task show` never matched it; the task's own `reason` was the fixed `approval denied`).
  Requirement 2a and the corrections writer say what now holds.

### Version 1.5.1 (2026-10-08)

- Command names follow ADR 0022.

### Version 1.5.0 (2026-10-08)

- Phase 39 (P39-9): `docket task answer <ref>` absorbs `docket chat` and `docket pod <p> answer`; the pre-grant is `docket task approve <ref> --for "<command>"`; `docket task approve|deny <ref>` resolve the task's own pending approval and end with the run hint. The standalone `approve`, `deny`, `chat` and `pod <p> pregrant` commands, and `chat`'s `Pre-grant:` line under a brief's risky actions, are removed.

### Version 1.4.0 (2026-10-07)

- Phase 39 (P39-13): the channel and flush commands live under `docket setup notify` (`channels`
  and `notify` are removed; `content` is `privacy`): `docket setup notify flush [--dry-run]` is the
  manual flush, and `enable telegram`/`enable --test` join `test` as the only senders.
- `inbox` prints the `docket task approve|deny|answer <id>` line on every item, never truncates a held command, exits 2 on an unknown flag and lists a granted pending task as "approved, ready" (`state: "approved_ready"`); `--json` items carry `state` and `command`.

### Version 1.3.1 (2026-10-07)

- Bare `docket notify` is usage (exit 2); only `flush` delivers.

### Version 1.3.0 (2026-10-06)

- Notifications item 17: `console` is a silent dialect (`SILENT_DIALECTS`), `Catalog.delivering()`
  names the enabled channels that reach an operator away from the terminal, and
  `unreached_warning` owns the one text `doctor`, `serve --dispatch`, `init` and the
  post-dispatch flush print when that list is empty. Measured need: a fresh home runs
  `serve --dispatch`, a task parks, and nothing anywhere said that only `console` was on.
- Notifications item 16: the CLI dispatch flush may print that one line too.
- Answer surfaces item 2: the CLI can pick a consult option (`pod answer --option <id>`,
  `chat`'s option prompt with the recommended default) and `docket inbox` shows the question.
  Found live: a Lead consult with two options could be answered from Telegram and HTTP but
  not from the CLI, and the inbox showed only the task's description.
- Notifications item 4: the built-in `desktop` document subscribes to `task.failed` like
  `ntfy`; the default `on:` of every built-in is now stated.
- Inbox item 3: a parked call's approval record carries `context.taskId`, and `build_inbox`
  also folds an approval whose token a `needsYou` task holds. Found by the first real
  park -> flush run: the same approval reached `desktop` and `ntfy` twice, once as the task
  and once standalone.

### Version 1.2.0 (2026-10-05)

Waves 89-90 close (W89-10): the entries below were Unreleased and are now this version.

- `approve_task` on a parked pod approval grants the same call for the rest of the task, through `taskGrants` (requirement 5a).
- A parked consult's question is persisted under `CONSULT_PARKED_DIR` and named by the `consult:<id>` token (`consult.park_token`/`parked_question`); the in-process `_PARKED` registry and `take_parked` are deleted, and a consult token with no question fails the task `consult_question_missing` instead of waiting as an approval (Consult 5).
- `core.inbox.task_view` populates `question` and `brief`; before, no inbox view or notification ever carried them (Notifications 11).
- Notifications item 11: `conversation`-level events carry a consult question's `options` and
  `recommendation.optionId`, and `render_text` lists them with a `/answer` reply hint.

### Version 1.1.0 (2026-10-04)

Phase 36 close (P36-10): the entries below were Unreleased and are now this version.

- **P36-8.** Consult: park and re-entry in pod dispatch, task-wide `maxConsultationsPerTask` count
  (requirement section "Consult", items 4-5).
- **P36-7.** Consult: the `consult` built-in, `maxConsultationsPerTask`, the `question_asked` trace event
  and its harness routing (requirement section "Consult").
- **P36-5.** Corrections ledger: deny reasons, REQUEST-CHANGES texts and declined answers are appended
  to a per-pod JSONL ledger under the D-12 exemption, accessible via `docket pod <p>
  corrections [--json]`. Text is redacted and tail-bounded; write failures are logged, never
  fail the caller.
- **P36-1.** Contract 1.1: `QuestionV11`, `AnswerResultV11`, `Option`, `Recommendation`,
  `validate_answer_v11` and the generated `operator-v1.1` schemas.

### Version 1.0.0 (2026-09-29)

- Every requirement area's stub replaced with its owning card's shipped behaviour (Waves
  65-69): park/pre-grant (area 2), the Lead's intake (area 3), pre-brief task assignment
  (area 4, corrected below), the derived inbox (area 5), notifications and every v1 channel
  dialect including `telegram` (areas 6, 6.1), answers (area 7), the Telegram amendment
  (area 8), interruption forecasting and pre-grants from intake (area 9), and every answer
  surface (area 10) — closing Phase 34 (D-50, ADR 0016).
- Corrected areas 4 and 10 (items 3-4): a post-close integration fix
  (`Fix: delegate --brief and POST /tasks brief now actually enqueue`) wired
  `core.dispatch.enqueue_task`'s `brief=` parameter through both surfaces in the same wave
  they were built, so the refusal these areas originally documented never actually shipped to
  an operator; the requirement text now describes the shipped, enqueuing behaviour.
- **Two integration-pass regressions found by running the live product, not by reading it,
  and fixed as part of this close**, unrelated to any single requirement area above but worth
  recording here since both surfaced through this spec's own machinery:
  - `scripts/smoke_workflow.py`'s own `--scenario operator-loop` measured `eventsDelivered` by
    reading a `deliveries` key `core.notify.flush`'s health-file shape never had (the real
    shape is one entry per channel name with its own `delivered` counter) — the counter had
    silently read `0` since it was written.
  - The same scenario's `--live-model` path registered the live provider *after* `docket
    init`, the reverse of the working order the basic/memory scenarios use — `init`'s own
    readiness check resolved the packaged Anthropic default and failed on a missing
    `ANTHROPIC_API_KEY` before the live provider was ever registered, so `--live-model` had
    never actually completed `init` for this scenario.

### Version 0.1.0 (2026-09-28)

- Initial specification: the `operator-v1` contract module (`core/operator_contract.py`), its
  generated JSON Schema documents, and the nine requirement areas the rest of the operator loop
  fills in. Only requirement area 1 (task status and its A2A mapping) is implemented; the other
  eight are stubbed pending their owning cards.
