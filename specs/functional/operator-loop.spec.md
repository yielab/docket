# Operator Loop Specification

**Version**: 0.1.0
**Status**: Draft — contract only; behaviour ships across Phase 34.
**Last Updated**: 2026-09-28

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
  surface (`core/inbox.py`, `cli/_inbox.py`, `docket serve`'s `GET /inbox`, `docket mcp serve`'s
  `inbox` tool, and Telegram's `/status`)

This specification does NOT cover (each is a distinct future requirement area below, owned by
its own card):

- How `POST /tasks` and `docket pod <p> delegate` accept a pre-brief end-to-end (the CLI/HTTP/MCP
  surfaces); `core.dispatch.enqueue_task` itself gaining a `brief=` parameter is covered by
  `pod-dispatch.spec.md`'s "Task brief" section, requirement area 3 above
- The `ntfy`, `desktop`, `email` and `telegram` dialects' own wire formats — requirement area 6
  below covers the diff/render/delivery framework and the `console`/`webhook`/`command`
  dialects; the remaining four each add one more `edges/adapters/channels/` module and one more
  `sink_for` entry in a later requirement area
- How an answer actually resumes a parked `input` pipeline step (`core/answers.py`)
- The Telegram channel amendment (`core/telegram.py`, `telegram-integration.spec.md`)
- The interruption forecast and CLI/HTTP pre-grant surface (`core/interruptions.py`)

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
   call's record, a `resolve_waiting_approval` pre-grant, and `docket pod <p> pregrant`'s
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

**Status: Planned — owned by P34-13.** `TaskBrief` is the pre-brief shape `POST /tasks` and
`docket pod <p> delegate` will accept; nothing yet parses it at either surface.

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
   one `ApprovalView` to `needsYou` for each **unless** its `context.taskId` is present — an
   approval already surfaced through its task's `approvalToken` MUST NOT also appear standalone,
   so nothing needing a decision is ever shown twice.
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
   sections, `needsYou` first. Without `--peek` and without an explicit `--since`, it MUST
   advance a durable cursor (`config.INBOX_CURSOR_FILE`, written through `edges/store.py`) to
   `InboxView.next` after rendering, so a later plain call's `doneSince` only shows tasks that
   completed after the previous call. `--peek` and an explicit `--since` MUST NOT write the
   cursor. `--json` MUST emit `InboxView.model_dump(by_alias=True, mode="json")`.
7. `GET /inbox?since=<iso>` (`serve.py`) MUST require the same `Authorization: Bearer <token>`
   as `GET /approvals` and return the identical JSON shape `docket inbox --json` prints for the
   same state.
8. `docket mcp serve`'s `inbox(since=None)` tool MUST return the same shape as `GET /inbox`.
9. `GET /metrics` MUST expose `docket_inbox_items{section="needsYou"|"failed"|"doneSince"|
   "running"}` as a gauge, one line per section, computed from `build_inbox(now=..., since=None)`.
10. Telegram's `/status` (`core/telegram.py`) MUST render from `build_inbox`, filtered to the
    bound agent's own scope (`_approval_scope`, unchanged from `telegram-integration.spec.md`
    requirement 3) by each item's `pod` field, `needsYou` first, then `failed`; it MUST NOT
    change the channel's inbound-only or plain-text constraints.

### 6. Notifications

**Status: Implemented for `console`/`webhook`/`command` — items 1-8 are the `kind: channel`
document, catalog and CLI (shipped earlier); items 9-16 are the diff/render/delivery framework
and its three simplest dialects. `ntfy`, `desktop`, `email` and `telegram` remain planned
(their own requirement area).** `CloudEvent`, `make_event` and the closed `EVENT_KINDS`
vocabulary are defined (requirement area 1's module) and satisfy the CloudEvents 1.0
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
   ship enabled.
5. `enable_channel(name, overrides)` MUST refuse, without writing, a channel whose resulting
   document fails a dialect-specific precondition: `ntfy` requires a non-empty
   `config["topic"]`; `telegram` requires a non-empty `actors`. Every other built-in has no
   such precondition in this area.
6. `set_content(name, level)` MUST accept only `minimal`, `actions` or `conversation`, on the
   closed order `minimal < actions < conversation`; `core.channel.is_widening(old, new)` MUST
   return `True` exactly when `new` is strictly richer than `old`. The CLI (`docket channels
   content <name> <level>`) MUST treat a widening change as a confirmed, audited command,
   exactly as `docket exporters privacy` does: `--yes` proceeds immediately, a TTY is asked
   `y/N`, and a non-TTY refuses naming `--yes` without asking. Narrowing never asks.
7. `docket channels list|show|enable [--set k=v]|disable|add <file>|remove|export|content
   <name> [<level>] [--yes]` (`cli/_channels.py`) MUST cover exactly this document's fields;
   it MUST NOT send anything to a dialect's actual destination — that is P34-11's `channels
   test` and delivery adapters.
8. `docket validate` MUST accept `kind: channel` (`core.config_docs.KINDS` gains `channel`;
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
16. `docket notify flush [--dry-run]` MUST call `core.notify.flush` over the full channel
    catalog and print the delivered/failed/skipped counts; `--dry-run` MUST print the pending
    events from `diff_events` without delivering or advancing the persisted snapshot. `docket
    channels test <name>` MUST build one synthetic `channel.test` event
    (`core.notify.build_test_event`) and deliver it once through that one channel's dialect,
    regardless of the channel's `on` subscription, reporting success or failure — this and
    `docket notify flush` are the only things in this specification's CLI surface that ever
    send anything to a real destination. `serve.py`'s periodic sweep and `docket pod <p>
    dispatch`'s foreground summary MUST each call `core.notify.flush` once, after their own
    work, with the CLI dispatch path printing nothing beyond one warning line naming the
    failure count when a delivery failed.

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

**Status: Planned — owned by P34-16.** No behaviour in this module is Telegram-specific; the
amendment to `telegram-integration.spec.md` Command grammar 7 and the `/answer` verb are out of
scope here.

### 9. Seeing it coming, and not being interrupted twice

**Status: Planned — owned by P34-15.** `canonical_args_digest` is the digest this area's
pre-grant matcher will use (the same function `core/tools.py`'s `park` branch uses, so a
CLI-issued pre-grant and an in-turn parked approval are matched identically); the forecast
function and CLI/HTTP surface do not exist yet.

### 10. Answer surfaces

**Status: Implemented (CLI, `docket chat`, HTTP, MCP; Telegram is area 8's own card).** Every
surface below calls `core.answers.answer_task` directly (area 7) -- none re-implements schema
validation, the `pre_input` screen, or the resume. ADR 0016 §8 names these as "two core
functions, every surface is transport"; this area is that transport.

1. `docket pod <p> answer <task-id> [text] [--field name=value]... [--decline]`
   (`cli/_pod.py::_pod_answer`) MUST call `answer_task(channel="cli", actor=<OS user via
   getpass.getuser()>)`. A bare `text` argument MUST fill the single property of a
   one-property `requestedSchema`, read from the task's own parked `question`; against a
   schema with more than one property, a bare `text` MUST be refused (exit 1, nothing sent)
   naming `--field name=value` as the alternative. `--field` MAY be repeated to set named
   properties explicitly. `--decline` MUST set `action="decline"` and ignore any `text`/
   `--field` values, matching `validate_answer`'s own decline/cancel short-circuit. Neither
   `text` nor a `--field` nor `--decline` is a usage error (exit 1, nothing sent).
2. `docket chat <task-id> [--pod <project>]` (`cli/_chat.py::run_chat`) MUST locate *task-id*
   across every `core.dispatch.dispatchable_pods()` pod when `--pod` is omitted, else within
   just that one pod; an unresolved task-id MUST exit 1. It MUST render the task's brief (when
   present), its `answers[]` (when present) and its pending `question`'s message (when
   `waiting_input`). On a TTY with a pending question, it MUST prompt once per
   `requestedSchema` property (a blank optional property is omitted from `content`; a blank
   required one is passed through unchanged, so the schema check itself reports it -- never a
   client-side retry loop) and then call `answer_task(action="accept", channel="cli",
   actor=<OS user>)`. Off a TTY, or with no pending question, it MUST only display -- never
   call `answer_task`.
3. `docket pod <p> delegate --brief FILE.json` (`cli/_pod.py::_pod_delegate`) MUST parse the
   file as JSON and validate it as a `TaskBrief`; a parse or validation failure MUST exit 1
   and enqueue nothing. `core.dispatch.enqueue_task` has no `brief` parameter as of this
   requirement's own card (P34-13) -- a **well-formed** brief MUST also exit 1 and enqueue
   nothing, naming the missing parameter, rather than silently dropping the document or
   guessing how to pass it through. `_pod._ENQUEUE_ACCEPTS_BRIEF` (checked once via
   `inspect.signature`) exists so this refusal turns itself off, without further code, the
   moment a later card adds the parameter.
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
   field, validated the same way as `--brief` above and refused the same way when
   `enqueue_task` cannot yet accept it -- the identical contention, not a second guess at its
   shape.
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

## Changelog

### Version 0.1.0 (2026-09-28)

- Initial specification: the `operator-v1` contract module (`core/operator_contract.py`), its
  generated JSON Schema documents, and the nine requirement areas the rest of the operator loop
  fills in. Only requirement area 1 (task status and its A2A mapping) is implemented; the other
  eight are stubbed pending their owning cards.
