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

- How the Lead's pipeline produces a `TaskBrief` in practice, or how `POST /tasks` and
  `docket pod <p> delegate` accept a pre-brief
- How an event is actually produced, diffed and delivered to a `kind: channel` destination
  (`core/notify.py`, `edges/adapters/channels/`)
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

**Status: Planned — owned by P34-12.** `TaskBrief`, its field validation (a non-empty
`objective`, and every `resources[]` entry prefixed `secret:`, `path:` or equal to `verify`) and
the `expectedRiskyActions` alias exist in this module. The pipeline `input` step that produces
one from a Lead's reply, and the deterministic resource pre-check, do not.

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

**Status: Planned — owned by P34-9 (the `kind: channel` document) and P34-11 (delivery).**
`CloudEvent`, `make_event` and the closed `EVENT_KINDS` vocabulary are defined and satisfy the
CloudEvents 1.0 structured-mode shape; no channel document kind, snapshot diff or delivery
adapter exists yet.

### 7. Answers

**Status: Planned — owned by P34-10.** `Question`, `QuestionSchema`,
`validate_requested_schema` and `AnswerResult`/`validate_answer` are defined and enforce the MCP
elicitation subset (a flat object of primitive properties, `accept`/`decline`/`cancel`); no
`core/answers.py::answer_task` exists yet to resume a parked `input` step with a validated
answer.

### 8. Telegram (the one amended boundary)

**Status: Planned — owned by P34-16.** No behaviour in this module is Telegram-specific; the
amendment to `telegram-integration.spec.md` Command grammar 7 and the `/answer` verb are out of
scope here.

### 9. Seeing it coming, and not being interrupted twice

**Status: Planned — owned by P34-15.** `canonical_args_digest` is the digest this area's
pre-grant matcher will use (the same function `core/tools.py`'s `park` branch uses, so a
CLI-issued pre-grant and an in-turn parked approval are matched identically); the forecast
function and CLI/HTTP surface do not exist yet.

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
