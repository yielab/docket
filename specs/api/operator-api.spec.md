# Operator API (HTTP, version 6) -- contract spec

**Version**: 7.30.0
**Status**: Implemented (ADR 0027, ADR 0029). The server reports `apiVersion` `"6"`.
**Last Updated**: 2026-11-05

## Purpose

This specification defines the routes an external plan of record (a project manager, a CI job,
an operator's script) uses to run work on a long-lived pod through `docket start --dispatch`:
enqueue an addressable task, follow its hops, cancel, retry and diff it, read and apply a pod's
configuration, and read the corrections ledger. It is the one door for a program; the CLI is
the door for a person, and both run the same domain functions: a route exposes what the CLI
already does and adds no behaviour of its own.

Version 6 is negotiated, not pinned: a consumer reads `apiVersion` from `GET /status.json`
(`serve-read-api.spec.md`) and names the version it needs.

## Scope

This specification covers:

- The task body fields added to `POST /tasks/<pod>` and the idempotent answer
- `GET /tasks/<pod>` filtering, `GET /tasks/<pod>/<id>`, `POST .../cancel`, `POST .../retry`,
  `GET .../diff`
- The `hop_started` / `hop_finished` trace events a consumer reads from `GET /traces/<pod>`
- `GET /escalations`, the pauses a task waits on, one record each (`operator-loop.spec.md` area 11)
- `GET /pods`, `GET /pods/<p>`, `POST /pods` with `ensure`, `POST /pods/<p>/apply`,
  `POST /pods/<p>/resume`, `GET /pods/<p>/corrections`, `GET /pods/<p>/memory`,
  `POST /pods/<p>/memory/<id>`, `GET /pods/<p>/records`, `GET /pods/<p>/records/<set>`
- The `dispatch` block of `GET /health` under `--dispatch`
- Re-attaching a client after a restart, and the `check_changed` approval a consumer sees
- Status codes and error bodies

It does NOT cover:

- The other read routes (`/status.json`, `/metrics`, `/runs`, `/inbox`,
  `GET /traces/<pod>`'s cursor, `GET .../evidence`) -- `serve-read-api.spec.md`
- `POST /tasks/<id>/pregrants` and `POST /dispatch/<pod>` -- `serve-read-api.spec.md` and
  `operator-loop.spec.md`
- The task record's persisted shape -- `pod-dispatch.spec.md`; the trace record --
  `trace-store.spec.md`; the `.docket/teams/<pod>/` layout -- `pod-blueprints.spec.md`
- The `/health` body itself -- `serve-read-api.spec.md`
- `--bind`, the Bearer token and the stop signals of `docket start` --
  `serve-read-api.spec.md` and `pod-dispatch.spec.md`
- The A2A JSON-RPC binding (`POST /a2a`, `GET /.well-known/agent.json`) -- `a2a-binding.spec.md`;
  it is a second door over the same task and escalation records and `resolve`, and adds no route
  to this table
- Multi-tenancy, external authentication, streaming, quotas (ADR 0027 "What this does
  not buy")

## Syntax

Every route below requires `Authorization: Bearer <token>` (the token `docket start` prints or
writes with `--token-file`); `401` comes before any other check. `DOCKET_SERVE_READ_TOKEN`, when set,
is a second Bearer token that may only read: it is allowed on every `GET` and `HEAD` route the serve
token is allowed on, and on a `POST` route it is answered `403` with `code: read_scope` before the
handler runs, so nothing is written. The read token has no file and is never printed; `docket start`
refuses to start when it equals the serve token. `/status.json`, `/metrics` and `/health` stay open.
`<pod>` is a project id, validated
as a project id (a bad one is `400`). Bodies are JSON objects; a malformed body is `400`, a body
over 1 MiB is `413`.

| Route | Does |
|---|---|
| `POST /tasks/<pod>` | enqueue a task, optionally idempotent and addressable |
| `GET /tasks/<pod>?externalRef=&status=` | list the pod's tasks, filtered |
| `GET /tasks/<pod>?updatedSince=<n>` | the tasks changed since a cursor, with the next cursor |
| `GET /tasks/<pod>/<id>` | one task record |
| `POST /tasks/<pod>/<id>/cancel` | cancel a task that is not over |
| `POST /tasks/<pod>/<id>/retry` | put a `blocked` or `failed` task back on the queue |
| `GET /tasks/<pod>/<id>/diff` | what the task's branch changed |
| `GET /escalations?since=<seq>&pod=&task=` | the escalation records after a cursor, each joined with its pause |
| `GET /escalations/<id>` | one escalation joined with its pause; a pending `send` approval also carries its `call` |
| `POST /escalations/<id>` | resolve one escalation: choose an option, give content |
| `GET /pods` | every dispatchable pod with its queue counts |
| `GET /pods/<p>` | one pod's report |
| `POST /pods` (`ensure`) | provision a pod, or find it |
| `POST /pods/<p>/apply` | apply a directory of configuration to a pod |
| `POST /pods/<p>/resume` | clear a pod's pause and re-queue its blocked tasks |
| `GET /pods/<p>/corrections?since=` | the corrections ledger, from a cursor |
| `GET /pods/<p>/memory?status=` | the pod's memory entries in one status (default `accepted`), oldest first |
| `POST /pods/<p>/memory/<id>` | approve or refuse a pending memory entry, as `docket pod memory approve` and `refuse` do |
| `GET /pods/<p>/records` | the pod's record sets with their columns and row counts |
| `GET /pods/<p>/records/<set>?limit=&sql=` | a set's rows, or a read-only `SELECT`'s |
| `GET /health` (dispatch block) | whether the sweep is on and what is in flight |

The CLI keeps symmetry: `docket task add` takes `--external-ref`, `--idempotency-key`,
`--base-ref`, `--pipeline`, `--gate`, `--max-tokens` and `--autonomy`; `docket task cancel|retry|diff` run the
same functions as their routes; `docket start` takes `--bind`. `prepare`, `restrictions` and
`trusted` are body fields with no `docket task add` flag.

## Arguments

### `POST /tasks/<pod>` -- the task body

| Field | Type | Rule |
|---|---|---|
| `description` | string | required, non-empty |
| `priority` | `high` / `normal` / `low` | default `normal` |
| `trusted` | bool | overrides the `pre_input` trust flag for this enqueue only |
| `brief` | object | a `TaskBrief`; an invalid one is `422` and nothing is enqueued |
| `task` | object | optional structured fields beside `description`, additive to API 6 (no version change): `objective`, `doneWhen`, `risk`, `verify`, `kind` (strings), `acceptance`, `constraints`, `paths` (lists of strings) and `answers` (a list of objects), each optional. An unknown key or a field of the wrong type is `400` naming it, and nothing is enqueued. The record keeps it as `task`; with both present `description` is the title. The first non-Lead hop's `## Task` section renders it after the description in the fixed order objective, done when, acceptance, constraints, risk, answers, verify, kind, paths, and `paths` bound that hop's repository map to the entries beside them (`pod-dispatch.spec.md` "Bounded hop prompts"). The text is screened by `pre_input` with the description. Not exposed by the CLI, MCP or the operator view |
| `externalRef` | string, 1-200 chars | a caller label, stored verbatim, never interpreted; filterable |
| `idempotencyKey` | string, 1-200 chars | when a task in this pod's queue already carries it, nothing is enqueued and that task is returned with `200`; a new task answers `201` |
| `baseRef` | string | a branch name or commit the task worktree starts from (`git worktree add -b <task-branch> <dir> <baseRef>`); unset means the codebase's HEAD. Validated at claim, not at enqueue: an unresolvable ref, a `workdir` pod, or a pod with no Implementer codebase to make the worktree from, fails the task before any hop with `failureKind: "base_ref"` (see "A task on a `workdir` pod") |
| `pipeline` | string | the name of a pod-local pipeline (`<pod config dir>/pipelines/<name>.yaml`) or of a recipe that carries a `pipeline.yaml`, the operator's own (`~/.docket/recipes/`) before the shipped ones (`docket pod recipes`); unset means the pod's effective pipeline. Resolved at claim; a name that resolves to nothing valid, a pipeline with a step whose role the pod lacks (`pipeline 'tdd' (recipe:tdd) names roles this pod does not have: reviewer (step review)`; `docket task retry` re-queues it once the pod has the role), or a `gate` that cannot be honoured, fails the task before any hop with `failureKind: "pipeline"` |
| `gate` | object | `{"command": string, "timeoutS"?: int, "map"?: {exit code: label}}` -- an `ExternalGate` (ADR 0025) added **after** the last implementer step's own gate, with the same labels and `on:` routing. It never replaces a gate the pipeline declares |
| `maxTokens` | int > 0 | a budget over the task's counted usage (`input - cached + output` summed over hops; a cache read is not counted); each hop runs with a turn token budget of `maxTokens - used so far`; a hop that would start with nothing left, or a turn that stops on that budget, fails the task with `failureKind: "budget"` |
| `prepare` | string | the install command run in this task's worktree before its first hop; `""` or `none` runs nothing and wins over the pod's `prepare` and the lockfile. Unset means the pod's `prepare` setting, else the command for the worktree's lockfile (`pod-dispatch.spec.md` "Task preparation"). Stored on the task record and shown by `GET /tasks/<pod>/<id>`; an install that fails settles the task before any hop with `failureKind: "prepare"` and the output tail as `reason`. A newline or NUL, or more than 1,000 characters, is `400`. On a `workdir` pod a command fails the task at claim with `failureKind: "prepare"`; `""` or `none` is accepted (see "A task on a `workdir` pod") |
| `variables` | object of strings | optional, additive to API 6 (no version change): pipeline variables that belong to this task, name to string value. A value that is not a string, or a body that is not an object, is `400` naming the field and nothing is enqueued. Stored on the task record as `variables` (absent when none were sent, and absent on a record written before the field) and shown by `GET /tasks/<pod>/<id>`. At claim they are merged over the run's variables (a webhook body or `docket run --var`), the task's winning, so a step's `when: {var: ..., is: ...}` and `${var}` instructions see them for this task only. `when.var` compares the variable's text with `is`, so an integer from a webhook body matches `is: "3"` |
| `conversation` | object | `{"maxTurns": int}` -- the task continues turn by turn: after each turn short of `maxTurns` it waits on an escalation of kind `turn` (`operator-loop.spec.md` area 11 item 17). `maxTurns` is required, a strict integer from 1 to 20 (`MAX_CONVERSATION_TURNS`); a string, a bool, 0 or 21 is `400` naming the field. The task's pipeline must have exactly one step (the pod's effective pipeline, or the named `pipeline`): more is `400` with `code: conversation_needs_one_step`, and nothing is enqueued. Stored on the task record and shown as `conversation: {maxTurns, turns}` by `GET /tasks/<pod>` and `GET /tasks/<pod>/<id>` (absent when none was sent); `turns` is computed on read, the count of the task's finished hops, never stored as input. Additive to API 6 (no version change); a client probes for it with the `conversation` feature |
| `restrictions` | object | see below. Anything that would widen is `422` |
| `autonomy` | `L3` / `L4` / `L5` | the level the task's pauses are decided at (`security-gates.spec.md` "Autonomy levels"). It only narrows: the pod's profile is the ceiling, `attended` admits up to `L3` and `lights-out` up to `L5`, and a level above it is `422` with the ceiling named. Unset takes the profile's default (`L3` attended, `L4` lights-out), so `L5` is always asked for. Any other value is `400`. Stored on the task record and shown by `GET /tasks/<pod>/<id>` |

`restrictions`:

| Field | Type | Rule |
|---|---|---|
| `deniedTools` | list of tool names | unioned with the role's denied tools and the pod's `deniedTools` when the hop's registry is narrowed; an unknown name is `422` (the built-in tool names, as for `pod set deniedTools`) |
| `network` | `"none"` | the hop's jail network is `none` whatever the pod records; the only accepted value, since `"open"` would widen |
| `policies` | list of policy documents | each a `kind: policy` short or canonical form; every rule's action MUST be `block`, any other action is `422`; loaded for the task's session after the pod's policies, never persisted to the pod |

### A task on a `workdir` pod

A pod's `workspaceKind` (`GET /pods`) says where its tasks run. A `codebase` pod gives each task a
worktree of its own; a `workdir` pod (the `respond`, `operate` and `routine` blueprints) runs every
task in its one working directory, with no repository and no worktree, and never makes one.
`baseRef` and `prepare` both act on a task's worktree, so on a `workdir` pod:

- `baseRef` **MUST** fail the task at claim, before any hop, with `failureKind: "base_ref"` and
  the reason `pod '<pod>' works in a folder (workspaceKind workdir); baseRef '<ref>' applies only
  to a pod with a codebase`. A caller that names a base revision expects the work on a branch from
  it; running elsewhere would hide that the request was not met.
- A `prepare` command **MUST** fail the task at claim the same way, with `failureKind: "prepare"`
  and the reason `pod '<pod>' works in a folder (workspaceKind workdir); prepare '<command>'
  applies only to a pod with a codebase`. It is refused rather than ignored for the same reason: a
  caller that asks for an install expects the hops to run with it, and nothing would install it.
  `""` and `none` ask for nothing to run, so they are accepted.
- A pod's own `prepare` is never derived for a `workdir` pod and cannot be set on one
  (`pod-blueprints.spec.md` "Pod manifests: apply" requirement 13).

On a `codebase` pod whose Implementer records no codebase (the member was removed, or never had
one), a `baseRef` fails with `failureKind: "base_ref"` and the reason `pod '<pod>' has no
Implementer with a codebase to make a task worktree from; baseRef '<ref>' was not used`, and a task
without one runs in place unprepared (`pod-dispatch.spec.md` "Task worktrees" requirement 4).

### `POST /tasks/<pod>/<id>/cancel`

Body optional: `{"reason"?: string, "actor"?: string}`; `actor` is a label for the audit entry,
default `http`. Cancels a task in any state that is not over: a `running` one (kills the hop's
process group, as `docket task cancel` does), a parked one (`waiting_input` or `waiting_approval`)
and one no run holds yet (`pending`, or `blocked`), which ends `cancelled` under the lock a claim
takes, so it is never claimed after; the CLI runs the same function. Audited `task.cancel` with
channel `http` and the reason. `404` for an unknown pod or task; `409` when nothing could be
cancelled, and its body carries a stable `code` beside `error`: `already_terminal` for a task that
is `done`, `failed` or `cancelled`, `not_cancellable` for any other task that nothing could stop (a
run that refused). The answer's `status` is `cancelled` when a run was stopped or a parked or
unclaimed task cancelled, else the task's own status after a stale claim was settled (`failed`).

### `POST /tasks/<pod>/<id>/retry`

No body. A `blocked` or `failed` task flips to `pending` keeping its hops, with `blockedReason`,
`failureKind` and `reason` cleared; audited `task.retry`. A task in any other status is `409`, an
unknown task `404`. The next run starts at the step whose hop failed, not after it, and that step
continues its session: its turn receives a message saying the previous turn stopped before it
finished, with the error, the hop's summary, up to 20 changed paths and the instruction to continue
rather than start over (`pod-dispatch.spec.md`, "Retries and the failure-kind taxonomy"). A client
probes for this with the `retryContinues` feature. A rework that must start from the previous
attempt's branch is a new `POST /tasks/<pod>` with `baseRef` set to that branch, not a retry.

### `POST /pods`

The body, the `201` answer for a new pod and the `ensure` flag are owned by
`serve-read-api.spec.md` (POST /pods). With `ensure: true` and an existing pod the answer is `200`
with `"created": false` and nothing is changed or re-applied; without it an existing pod is `409`.

### `POST /pods/<p>/resume`

No body (a body is ignored). A pod whose Lead is paused has `paused` and `pausedReason` cleared, its
blocked tasks re-queued (`unblock_pod`) and a `run.resume` audit entry written with `channel=http`;
the answer is `200` with the `GET /pods/<p>` object plus `resumed: true`. A pod that is not paused
answers `200` with the same object and `resumed: false`; nothing is written and nothing is audited.
An unknown pod is `404`. It resumes the pod, never one task (`POST /tasks/<pod>/<id>/retry` does
that) and changes no budget. A client probes for it with the `podResume` feature.

### `POST /pods/<p>/apply`

| Field | Type | Rule |
|---|---|---|
| `directory` | string | absolute path to an existing directory, or unset for the repository's own directory (`.docket/teams/<p>/` when present, else `.docket/`). Required for a pod that works in a folder (`respond`, `operate`, `routine`): it has no repository to read `.docket/` from |
| `dryRun` | bool | plan only, nothing written; no review code is needed |
| `accept` | string | the review code for a directory that runs things on this machine (ADR 0024). HTTP is off a terminal: without the matching code such a directory is `409` with the code in the body and nothing is written |

## Options

Query parameters:

| Route | Parameter | Rule |
|---|---|---|
| `GET /tasks/<pod>` | `externalRef` | exact match; both parameters combine |
| `GET /tasks/<pod>` | `updatedSince` | a non-negative decimal integer cursor (`0` starts from the beginning); the answer is `{"tasks": [...], "next": "<n>"}` and anything that is not such an integer is `400` with `code: bad_cursor`; see "Task cursor" |
| `GET /tasks/<pod>` | `status` | one of `pending`, `running`, `waiting_input`, `waiting_approval`, `blocked`, `failed`, `done`, `cancelled`; any other value is `400` |
| `GET /pods/<p>/memory` | `status` | `accepted` (the default), `pending` or `refused`; any other value is `400` naming the three |
| `GET /pods/<p>/corrections` | `since` | ISO-8601 timestamp with an offset (normalised to UTC; naive is `400`); records with `ts > since`, append order |
| `GET /pods/<p>/records/<set>` | `limit` | integer 1 to 1000, default 50; anything else is `400` |
| `GET /pods/<p>/records/<set>` | `sql` | one read-only `SELECT`; absent reads the whole set newest first (`ORDER BY _id DESC`) |

## Output

### Features

`GET /status.json` and `GET /health` both carry `features`: the names of the features this build
answers to, so a client can probe for one before it calls the route (`podMemory`, the pod memory
route below). A name joins the list in the commit that makes the feature work, never before.

### Task answers

`POST /tasks/<pod>` (new task, `201`):

```json
{"ok": true, "created": true, "task": "task-5d0c...", "project": "web-dev", "status": "pending"}
```

A task gated by a `require_approval` `pre_input` verdict is created (`201`) with `"status":
"waiting_approval"` and an extra `"escalation"`, the id of the escalation to resolve. The same body with an `idempotencyKey` already
in the queue (`200`):

```json
{"ok": true, "created": false, "task": "task-5d0c...", "project": "web-dev", "status": "running"}
```

`GET /tasks/<pod>/<id>` returns the full task record of `pod-dispatch.spec.md` (the same object
`GET /tasks/<pod>` lists), including the addressable-task fields:

```json
{
  "id": "task-5d0c...", "status": "done", "priority": "normal",
  "externalRef": "TACK-412/attempt-2", "idempotencyKey": "TACK-412:2",
  "baseRef": "docket/web-dev/task-91aa...", "pipeline": "tdd",
  "gate": {"command": "npm test -- --ci", "timeoutS": 600},
  "maxTokens": 400000, "tokenBudget": 100000,
  "restrictions": {"deniedTools": ["fetch"], "network": "none", "policies": []},
  "worktree": {"dir": "...", "branch": "docket/web-dev/task-5d0c...", "baseCommit": "a1b2c3d"},
  "usage": {"input": 61230, "cached": 40000, "cacheWrite": 2100, "output": 4120,
            "byModel": {"local/local-model": {"input": 48000, "cached": 40000, "cacheWrite": 0, "output": 3000},
                        "anthropic/claude-sonnet-4-6": {"input": 13230, "cached": 0, "cacheWrite": 2100, "output": 1120}}},
  "hops": [{"role": "implementer", "stepId": "implementer", "model": "local/local-model",
            "provider": "local", "usage": {"input": 40950, "cached": 36000, "cacheWrite": 0, "output": 1425}, "ok": true, "...": "..."}]
}
```

Each hop of `hops` carries `promptManifest` once it has one (absent on a hop recorded before the
field existed): `{"layers": [{"layer", "name", "version", "sha256", "scope", "tokens"}, ...],
"model", "family", "class", "profile"}`. A layer's `sha256` is the hash of its prompt's text as
the prompt file holds it, so a consumer compares it with the file; `tokens` is the estimate the
context compiler budgets with, not a measurement. The field is additive: a consumer that does not
read it is unaffected. A hop's `artifact` may also carry `assumptions` and `questions` (lists of
strings, absent when empty) from the hop's `handoff` call; a question there is information for the
next hop and the operator, and never parks the task.

Each hop that ran an agent turn also carries `startedAt`, `finishedAt` and `cycle`: the two
instants (ISO 8601 UTC with microseconds and an explicit offset, the format of `current.startedAt`)
and the rework cycle (an integer, `0` on a first pass) of the hop's own `hop_started` and
`hop_finished` events. Each is stamped where its event is emitted, so it is within milliseconds of
that event's `ts_us` (the event's `ts` is the same instant cut to the second). They belong to the
hop, never copied from `current`, which has one slot and so would give a child of a parallel group
its sibling's start. A hop with no agent turn (a command or gate step, a wait, a resolution) has no
such events and carries none of the three, as does a hop recorded before the rule: the keys are
absent, never `null`. There is no duration field; a client subtracts. A client probes for them
with the `hopTimes` feature.

`tokenBudget` is the measured-token ceiling the next hop of the task would run under: the
configured per-turn budget (`AGENT_LOOP_TOKEN_BUDGET`) for a task without `maxTokens`; for a task
with one, what its cap has left after its persisted hops (`maxTokens` minus the hops' counted
usage), never below 0. It is computed on read, from the same values dispatch applies, and
is present on every task object the `GET /tasks/<pod>` list and `GET /tasks/<pod>/<id>` return.

A hop that ran out of rounds, tool calls, tokens or wall-clock time (never a request timeout) is
`ok: false` and carries `budget`: `{"bound": "rounds" | "toolCalls" | "tokens" | "time", "limit",
"used", "source", "raise", "treeChanged"}`. `limit` and `used` are counts, seconds for `time` and
counted tokens for `tokens`; `source` is who set the limit (`step`, `pod`, `default`, or `task` for
tokens under a task `maxTokens`); `raise` is the one key or machine variable that raises that limit
(`timeout` for source `step`, `turnTimeoutS` for `pod`, `maxTokens` for `task`, and for `default`
the machine variable: `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S`, `AGENT_LOOP_TOKEN_BUDGET`,
`AGENT_LOOP_MAX_ITERATIONS` or `AGENT_LOOP_MAX_TOOL_CALLS`), so a plan of record reads a field and
never parses the stop message (additive on API 6); `treeChanged` is `true` when the hop left a dirty tree that
docket committed on the task branch, so the hop's `artifact.files_changed` and the task's diff show
the work. The key is absent on every other hop and on a hop recorded before the rule. A client
probes for it with the `budgetOutcome` feature.

A hop whose turn stopped on a gap in the pod's configuration is `ok: false` and carries
`capabilityMissing`: `{"kind": "tool" | "records" | "fetch", "name", "fix"}`. `kind` says what the
turn called that the pod lacks (a tool its role does not list, a record set the pod does not
declare or the role may not use, `fetch` while the pod declares no host); `name` is that tool, set
or `fetch`; `fix` is one sentence that names the key or command that closes the gap, so a plan of
record shows it to a person without parsing the hop's `error`. The task settles `failed` with
`failureKind: "capability_missing"` and a `reason` of `<role> needs <kind> '<name>': <fix>`; no
escalation is opened, and an Implementer's work is kept as for a transport stop. The key is
absent on every other hop and on a hop recorded before the rule (additive on API 6). A client
probes for it with the `capabilityMissing` feature.

`failureKind` names why a task did not finish, and a consumer decides from it. A task that settles
`failed` **MUST** carry a non-empty one, and a `blocked` task whose pod budget tripped carries
`pod_budget`. The kinds docket itself writes are closed: `stale_claim`, `dispatch_refused`, `base_ref`,
`prepare`, `pipeline`, `budget`, `needs_human`, `approval_denied`, `approval_expired`,
`check_changed`, `rejected`, the gate kinds `gate_failed`, `gate_needs_human` and `gate_error`,
`capability_missing` (a hop's turn called what the pod's configuration lacks; the hop's
`capabilityMissing` says what and how to close it), `pod_budget` (status `blocked`: the pod's `budgetTokens` was spent before a hop; the reason text
keeps the token counts, the field never does), and `hop_failed`, the default of a failed task
whose hop or step carried no more specific kind. The default is applied once, where the task
settles `failed`, never by a producer. A claim clears the key, and so does a retry; an unblock
keeps it until the next claim, so a `pending` task can still carry the kind of the block it left.
A record written before the rule can lack it. A client probes for the rule with the
`failureKinds` feature. `pipeline` also covers a task-named pipeline the pod cannot staff: a step
whose role the pod's roster lacks refuses the task at the claim, with the roles and steps in the
`reason`, where the pod's own pipeline would skip that step. A client probes for the check with the
`pipelineChecked` feature. `budget` means the work ran out of budget, not that it failed on its merits:
the last hop's `budget` says which bound, and its pinned work is on the task branch. It covers the
task's `maxTokens` and each hop bound (rounds, tool calls, wall clock, tokens), and is never retried
in place.

`current` names the hop a `running` task is inside: `{"stepId", "role", "member", "model",
"startedAt", "cycle"}`. It is written where the hop's `hop_started` event is emitted, with the same
values (`model` is the planned model, not the one that served; `cycle` counts the backward moves taken, `0`
on a first pass), and cleared in the write that records the finished hop, so no read sees the hop recorded while `current`
still names it, or `current` gone while the hop is missing. The key is absent, never
`null`, on a task that is not inside a hop, and every move out of `running` removes it, so a task
that dies mid-hop never shows a stale `current`. A task has one slot, and only an agent hop fills it: inside a parallel group it names the child
that started last, and the key goes when that child ends even while a sibling runs, so on a
`running` task an absent `current` means no agent hop is known to be in flight. It is on both `GET /tasks/<pod>` and
`GET /tasks/<pod>/<id>`; a client probes for it with the `taskCurrent` feature.

The task's `usage` and each `byModel` entry sum their hops' `input`, `cached`, `cacheWrite` and
`output`; the task-level `usage` is written when the task settles, so a task still in flight has
only its hops' usage. `input` includes the cache reads and writes, so a consumer counting new tokens computes
`input - cached + output`, the rule docket's own budget applies.

`rev` is the task's position in its pod's change counter: an integer the store stamps, inside the
locked write, on every task whose content changed in that write (and on a new one), with consecutive
values for the tasks of one write. A task that was never written since the counter existed has no
`rev`, read as `0`. `GET /tasks/<pod>?updatedSince=<n>` (`n` a non-negative decimal integer, `0`
from the beginning) answers the tasks with `rev` greater than `n`, in `rev` order, each as in the
plain list, as `{"tasks": [...], "next": "<n>"}`. `next` is the highest `rev` returned, or `n` itself
when nothing changed. `status` and `externalRef` filter that changed set. A cursor that is not a non-negative decimal integer is
`400` with `code: bad_cursor`. Without `updatedSince` the body is the plain `{"tasks": [...]}`
(`serve-read-api.spec.md` "Task cursor").

`POST .../cancel` (`200`): `{"ok": true, "task": "...", "status": "cancelled"}`.
`POST .../retry` (`200`): `{"ok": true, "task": "...", "status": "pending"}`.

`GET .../diff` (`200`, `application/json`):

```json
{
  "task": "task-5d0c...", "branch": "docket/web-dev/task-5d0c...", "baseCommit": "a1b2c3d",
  "head": "f00ba4", "patch": "diff --git a/src/app.ts b/src/app.ts\n...",
  "untracked": ["out/report.md"], "worktreePresent": true
}
```

`patch` is `git diff <baseCommit>..<branch>` run in the Implementer's codebase repository (the
branch outlives the worktree); `untracked` is `git status --porcelain` of the worktree while it exists and `[]`
with `"worktreePresent": false` afterwards. A task that ran in place (no worktree) answers `409`
with `"ok": false`, `"error"` and `"reason"` both `"task ran in place"`. `patch` is capped at
500000 characters; a longer one is cut and ends with a `[diff truncated at 500000 characters]`
line. A task
whose branch no longer exists answers `404` with a sentence.

### Trace events

Two typed records are among the event types of `trace-store.spec.md`, written in the task's session
(`agent:<pod>:<task-id>`) and read through `GET /traces/<pod>?since=`:

```json
{"ts": "...", "project": "web-dev", "session_id": "agent:web-dev:task-5d0c...",
 "agent_role": "implementer", "event_type": "hop_started",
 "payload": {"task": "task-5d0c...", "step": "implementer", "role": "implementer",
             "member": "web-dev-implementer", "model": "local/local-model",
             "provider": "local", "cycle": 0, "attempt": 1}}
{"ts": "...", "project": "web-dev", "session_id": "agent:web-dev:task-5d0c...",
 "agent_role": "implementer", "event_type": "hop_finished",
 "payload": {"task": "task-5d0c...", "step": "implementer", "role": "implementer",
             "member": "web-dev-implementer", "model": "local/local-model",
             "provider": "local", "cycle": 0, "attempt": 1, "ok": true,
             "verdict": null, "gate": "pass", "usage": {"input": 40950, "cached": 36000, "cacheWrite": 0, "output": 1425},
             "durationMs": 94012, "error": ""}}
```

`cycle` counts the backward moves taken so far: rework cycles after a `REQUEST-CHANGES` plus `on:` routes back to an earlier step (0 before any); `verdict` is the Reviewer's
label or `null`; `gate` is the step's gate label or `null`. `hop_started` names the
*planned* model (the step's `model` override, else the member's configured model), and
`hop_finished` names the *served* model the turn reported. `attempt` on `hop_started` is always `1`.

### Pod answers

`GET /pods/<p>/memory` (`200`): `{"entries": [...]}`. The entries in the `status` the query names
(`accepted` when it names none; `pending` are the ones waiting for `docket pod memory approve`),
oldest first; each element is exactly an element of `docket pod memory list --json` (the CLI prints a bare
array; the object wrapper is the one every HTTP route uses) and is `{id, kind, subject, note,
status, reason, provenance, stale, evidence}`: `subject` for every kind, `stale` a boolean and
`evidence` `{"exit": n}`, `{"ok": bool}` or `{}`; there is no `path`, `tool`, `command` or `exit`
key. A pod that is not dispatchable is
`404`. A client probes for the `status` query with the `memoryStatus` feature.

`POST /pods/<p>/memory/<id>` (`200`): body `{"decision": "approve" | "refuse", "reason"?: string}`.
It has the effect of `docket pod memory approve <id>` or `refuse <id> --reason`, with the actor
`http`: the entry must be `pending`; it becomes `accepted` or `refused`, the change is traced and
audited as the CLI's is, and the answer is that one entry as `GET /pods/<p>/memory` lists it, in its
new status (not wrapped in `entries`). `reason` is a string and is required for `refuse`, as the CLI's
`--reason` is, and is ignored for `approve`. A pod that is not dispatchable and an entry the pod does
not have are `404`; an entry that is not `pending` is `409` and is left as it was; a body that is not a
JSON object, a `decision` other than the two, a `reason` that is not a string, or a `refuse` with no
`reason` is `400`. A client probes for it with the `memoryDecide` feature.

`GET /pods` (`200`): `{"pods": [{"name": "web-dev", "codebase": "/srv/webapp",
"workspaceKind": "codebase", "blueprint": "build", "members": 2, "profile": "lights-out", "network": {"mode": "none", "scope": "default", "enforced": true}, "queue": {"pending": 1, "running": 1, "waitingApproval": 0,
"waitingInput": 0, "blocked": 0, "failed": 0, "done": 4, "cancelled": 0}}]}`; `queue` carries the
counts `status --json` prints under `tasks`: one per task status. `workspaceKind` is the closed
enum `"codebase"` or `"workdir"`, read from the kind the pod was provisioned with (its Lead's
`workspaceKind`; a pod that records none is `"codebase"`), never inferred from an empty `codebase`:
`codebase` is `""` both for a `workdir` pod and for a `codebase` pod whose codebase is not recorded.
`blueprint` is the shape the pod was provisioned with (`build`, `respond`, `operate`, `routine`; its
Lead's `blueprint`), `""` for a pod provisioned without one.

`network` is `{mode, scope, enforced}` on every row, on the `GET /pods/<p>` object and on each of its
`members`. `enforced` is a boolean: `true` only when `mode` is `none`, isolation is on and a sandbox
backend exists on this machine (the same fact `docket status` words), so an `open` pod, a machine
with isolation off and a machine with no backend all read `false`. A client reads it instead of
inferring a cut network from `mode`. A client probes for it with the `networkEnforced` feature.
A `workdir` pod's row and its `GET /pods/<p>` object also carry `workDir`, the absolute path of the
folder its tasks run in (its Lead's `workDir`); a `codebase` pod carries no `workDir` key, and the
key is never `null`. A client probes for it with the `podWorkDir` feature.
The `GET /pods/<p>` object also carries `fetchDomains`, the list of hosts the pod itself declares for
its members' `fetch` (`host`, `*.host` for every subdomain and never the apex, or `*`, which matches any host name,
once the operator recorded the grant, `security-gates.spec.md` "Network egress and the `fetch`
tool"); `[]` when it declares none. It does not repeat the machine's `FETCH_ALLOWED_DOMAINS`, which
is every pod's. A client probes for it with the `podFetch` feature. `POST /pods/<p>/apply` and `docket
pod update` refuse a `*` entry; only `docket pod set fetchDomains '*' --widen` writes it.
The same object carries `webRead`, how the pod's members read the web, from the one function that
decides it (`teams/network_posture.py` `fetch_reach`): `{"mode": "open" | "listed" | "none",
"reason": string, "fix": string}`. `open` is a folder pod under an enforced jail with no host
declared (any public host; `security-gates.spec.md` "Network egress and the `fetch` tool"),
`listed` is a declared list (the machine's plus the pod's, or `*` once the operator recorded the
grant), and `none` is a pod whose members hold no `fetch`. `reason` is one sentence a person can read
and `fix` is the one command that opens the web when `mode` is `none` (`docket setup sandbox on` or
`docket setup sandbox backend docker` for a folder pod whose jail is not running, `docket pod set
fetchDomains <host> --pod <pod>` for a repository pod); `""` otherwise. A client quotes `reason` and
`fix` instead of spelling docket's commands. A client probes for it with the `webRead` feature.
The same object carries `search`, the pod's web search, from the one function that decides it
(`teams/apply/search_state.py`, also the source of the `search-host` need line): `{"provider":
"searxng" | "brave" | "custom" | "none", "ready": boolean, "reason": string, "fix": string,
"options": [{"provider": string, "command": string, "secret": string}]}`. `provider` is read from
the service named `search` the pod resolves (its own, else the operator's): `searxng` for the base
URL `docket setup search searxng` writes, `brave` for the Brave Search API's, `custom` for any other
and `none` when no such service is declared. `ready` is, for `searxng` and `custom`, one `GET` of
the base URL answering within two seconds (any HTTP status; the probe `search-host` uses) and, for
`brave`, only that every secret its `auth` value references is stored (`resolve_auth`): docket
makes no call to Brave to answer it, so the report never spends the operator's quota. `reason` is
one sentence and `fix` the one command that makes `ready` true (`""` when it is). `options` lists
every provider docket can set up, each with the command that sets it up on this machine and the
name of the stored secret it needs (`""` for none). The key never travels over this API: a Brave
service whose secret is missing reports the `fix` `docket setup secret set brave-search --stdin`,
to be run on the machine, and no response, trace or audit line holds the value. A client sets the
provider by applying a directory whose `services/search.yaml` is the chosen one (`POST
/pods/<p>/apply` replaces a pod's service file by bytes); one service named `search` exists at a
time. A client probes for it with the `search` feature.

Every row of `GET /pods` and the `GET /pods/<p>` object also carry `paused` (boolean, always
present). A pod is paused while its Lead's meta holds `paused: true`, which a spent budget sets
(`pausedReason: "budget"`); while it is, every claim is refused and queued work waits. When
`paused` is `true` the same object carries `pausedReason`, a non-empty string (`"budget"` when the
meta names no reason); when `paused` is `false` the key is absent, not `null` and not `""`. The
fields are read from the Lead's meta on each request, so they follow the pause as `POST
/pods/<p>/resume`, `docket run --resume` or a changed budget clears it. `docket pod show --json`
does not carry the pair.

Every row of `GET /pods` and the `GET /pods/<p>` object also carry `budget`: `{"tokens": 500000,
"used": 512340, "window": "day", "windowStart": "2026-11-04T00:00:00Z"}`. `tokens` is the Lead's
`budgetTokens`, `null` without a cap; `used` is the count the budget gate would compare now (the
pod's counted tokens over the window, `cost-tracking.spec.md` requirement 9); `window` is `none`,
`day` or `week`; `windowStart` is the ISO-8601 UTC instant the window began, `null` for `none`.
The object is present with no cap too (`{"tokens": null, "used": n, "window": "none",
"windowStart": null}`). A row whose stored settings are invalid carries `error` (the sentence
`GET /pods/<p>` answers `500` with) and no `budget`; `GET /pods` itself stays `200`.

`GET /pods/<p>` (`200`): the object `docket pod show --json` prints (`cli-json-shapes.spec.md`:
`pod`, `blueprint`, `members`, `settings`, `approvalMode`, `pipeline` with its `steps`, `network`,
`needs`, `delivers`, `methods`, `configSource`, `configDigest`, `drift`) plus the five keys below, where `profile` here is the
verdict object (a row of `GET /pods` carries the profile name as a string):

```json
{"profile": {"name": "lights-out", "violations": [{"requirement": "network", "fix": "docket pod set network none"}]},
 "pipelineSource": "pod",
 "workspaceKind": "codebase",
 "repoConfigDir": "/srv/webapp/.docket/teams/web-dev",
 "readOnly": ["/opt/node-22"]}
```

`readOnly` is the read-only jail grants a turn of this pod gets: the machine's
(`docket setup sandbox read add`), kept only where the pod's `settings.readOnly` names them
(`security-gates.spec.md` Exec sandbox requirement 14); `[]` when there are none.
`profile.violations` is empty unless the effective profile is `lights-out`, `pipelineSource` says
where the effective pipeline comes from, `workspaceKind` is the value its `GET /pods` row carries,
and `repoConfigDir` is `""` for a pod with no codebase.

The pod's contract is three keys of the same object, so a client can fit a profile to a team before
it posts a task. `delivers` is what a task hands back (`["branch"]`, `["report"]`, plus `"records"`
when the pod declares record sets). `methods` is every pipeline a task may name in `pipeline`, each
`{name, source, missingRoles, default}`, resolved by the function the claim uses so the list and the
claim cannot disagree; `missingRoles` names the roles of its steps the pod's roster cannot fill (a
task naming that method is refused at claim), `default` marks the method whose file is the pod's
bound pipeline, and a file that does not load carries an `error` string. `needs` is each need the
pod's applied recipes recorded as `{kind, name, fix, satisfied, blocking}`, recomputed on every call;
`blocking` says whether the need, when unmet, stops the work (`fetch-hosts`: the researchers read
nothing) or only degrades it (`search-host`: pages the agent knows still read; `isolation`: every
format but PDF still reads), a fact of the kind, not of the pod. `search-host` is met only by a
declared service named `search` whose base URL answers one `GET` within two seconds, so that call
includes the probe (`pod-blueprints.spec.md` requirement 16). A client probes for the three with
the `podContract` feature.
Each entry of `members` also carries `capabilities`, what its role can reach after the role's and the
pod's denials, computed by `registry_for_role` over the tools docket declares (the built-ins and the
pod's record tools):

```json
{"kinds": ["read", "record"],
 "tools": ["glob", "grep", "read", "rec__query", "rec__tack_proposals__add", "rec__tack_proposals__update"],
 "records": {"write": ["tack_proposals"], "query": true},
 "notComputed": ["mcp", "service"]}
```

When the member holds `fetch`, the object also carries `fetchDomains`, the hosts that `fetch`
reaches: the machine's `FETCH_ALLOWED_DOMAINS` plus the pod's own list (same entry forms as above);
a member whose role denies `fetch`, or a pod with no host at all that is not a folder pod under an
enforced jail, holds no `fetch` and carries no `fetchDomains` key; a folder pod under the jail with
no host declared holds `fetch` and carries `fetchDomains: ["*"]` (any public host). `tools` lists
`fetch` only in the first case.

`kinds` is the distinct tool kinds (`read`, `write`, `exec`, `send`, `record`) of `tools`, the tool names the
role holds; `records.write` names the sets it can add to and `records.query` says whether it holds
`rec__query`. A role that denies `write` still lists `record` and its sets (`pod-records.spec.md`
requirement 37). MCP and service tools are not listed: a server's tools are known only once it is
started and a service's only once its secret resolves, and a `GET` does neither. `notComputed` is
`["mcp", "service"]` on every entry, saying those parts were not worked out, so a missing `mcp__*` or
`svc__*` tool is not read as a role that has none.
A pod that is not dispatchable is `404`. A pod whose stored settings no longer validate is `500`
with the error envelope naming the setting.

`POST /pods` with `ensure` on an existing pod (`200`): `{"ok": true, "created": false,
"project": "web-dev"}`; a new pod answers `201` with `"created": true` (`serve-read-api.spec.md`).

`POST /pods/<p>/apply` looks the pod up (`404`) before it reads the body (`400` for a body that
is not a JSON object). On success (`200`): `{"ok": true, "project", "items", "dryRun": true|false}`, `items`
being the `docket pod update --json` list (`cli-json-shapes.spec.md`); a dry run writes nothing.
A directory that runs things without `accept` is `409` as below. A wrong `accept` is `409` with
`"error": "the directory changed what runs on this machine since that code"` and no `reviewCode`,
and `runs` lists only the items that changed since the code was issued:

```json
{"ok": false, "error": "this directory runs commands on this machine; pass accept",
 "reviewCode": "7f3a2c...", "runs": [{"kind": "pipeline-step", "name": "build", "runs": "npm ci"}]}
```

A directory whose `allowCommands` names a refused command is `409` with an `error` naming it and
no `reviewCode`. A
nonexistent or relative `directory` is `400`, an unknown pod `404`. A pod with a repository and no
recorded codebase is `400` with a message naming `docket pod update`
and a codebase; it is never reviewed against the directory's parent. A pod that works in a folder
reviews the directory against the Lead's `workDir` and answers `400` without a `directory`:
`directory is required: pod 'x' works in a folder and has no repository to read .docket/ from`.
A `pod.yaml` whose `shape` differs from the pod's blueprint is `400` naming both
(`pod-blueprints.spec.md` requirement 1). A plan that changes something
is audited as `pod.apply` with `channel=http`, and so is one whose every item is skipped
(`changed=0 skipped=<n>`); a dry run is not audited. An accepted code is remembered as the CLI does
(audit action `repo.allow`). A body field of the wrong type is `400`. A client probes the
folder-pod apply and the manifest `shape` with the `podShape` feature.

`GET /pods/<p>/corrections?since=2026-10-01T00:00:00Z` (`200`):

```json
{"corrections": [{"ts": "2026-10-03T10:12:00Z", "project": "web-dev", "kind": "review_rejected",
                  "taskId": "task-91aa...", "role": "reviewer", "text": "...", "source": "pipeline"}],
 "next": "2026-10-03T10:12:00Z"}
```

`GET /pods/<p>/records` (`200`), then `GET /pods/<p>/records/leads?limit=1` (`200`):

```json
{"records": [{"name": "leads", "description": "", "key": "email", "rows": 2,
              "columns": [{"name": "email", "type": "string", "required": true}]}],
 "problems": []}
{"set": "leads", "columns": ["_id", "email"], "rows": [{"_id": 2, "email": "b@x.test"}], "cut": 1}
```

Both read the pod's own records file and nothing else (`pod-records.spec.md` requirements 50-53).
A statement the store refuses is `400` with its message; a set the pod does not declare, or an
unknown pod, is `404`.

### Escalations

`GET /escalations?since=<seq>&pod=<pod>&task=<id>` answers `200` with

```json
{"escalations": [{"id": "esc-0123456789ab", "task": "task-1", "pod": "demo", "step": "implementer",
  "role": "implementer", "kind": "consult", "causedBy": "c1", "prompt": "Which store?",
  "options": [{"id": "redis", "label": "Redis", "description": "fast", "risks": []}],
  "recommendation": {"optionId": "redis", "rationale": "...", "evidenceRefs": []},
  "requestedSchema": {}, "askedAt": "...", "expiresAt": "...", "onExpiry": "block",
  "policy": "person", "level": "L3", "state": "pending", "resolution": null, "seq": 1,
  "affordances": {"options": ["redis", "decline"], "acceptsText": true,
                  "resolveUrl": "/escalations/esc-0123456789ab"}}],
 "next": 1}
```

Each entry is an `EscalationView` (`operator-loop.spec.md` area 11 item 7): the stored record
plus `affordances`, its `state` joined with the pause it names, in `seq` order.
`seq` is the record's last change: stamped when it is created and stamped again when it settles
(`resolved` or `expired`), so a record's final state comes back through `since`. Stamping
`resolution.appliedAt` is bookkeeping and does not move it.
`since` is an integer `seq` (default `0`): only records with a greater `seq` are returned, whatever
their state, so a poller never misses a record that settled between two reads. `pod` and `task`
narrow the list. `next` is the highest `seq` returned, else `since`; pass it back as `since`. A
`since` that is not a non-negative integer answers `400`. `resolveUrl` names the route that
resolves the escalation (below). A `consult` view carries `part: {"index": 1, "count": 3}` (1-based):
one `consult` call that asks several questions opens one escalation per question, each with the
same `task`, `step` and `role`, and a client groups them by `(task, step)` and orders them by
`part.index`. A single question is `{"index": 1, "count": 1}`; a view of any other kind has no
`part` key. The task stays `waiting_input` until every part is settled; answering the last one
reopens it. `part` is additive to `operator-v2` and to API 6; a client probes for it with the
`consultParts` feature. `GET /inbox` carries the pending ones as
`escalations` (and lists a pause no waiting task carries in `needsYou`) and the pauses the pod settled alone as
`decided`, newest first and at most twenty, a key that is absent while there are none.

`GET /escalations/<id>` (Bearer) answers `200` with the one `EscalationView`, as `GET /escalations`
lists it, and `404` for an id no record has. For an approval of a `send` call that is still
`pending` it adds `call`, the whole call with credentials and stored secret values removed, uncut
(`operator-loop.spec.md` area 11 item 16); every other answer, a settled approval included, has no
`call`, and no other route carries it. `outward` (`true` on the approval of a `send` call, absent
otherwise) is on every view. Both are additive to `operator-v2` and to API 6.

`POST /escalations/<id>` takes `{"optionId"?: string, "content"?: object, "actor"?: string}` and
calls `resolve` (`operator-loop.spec.md` area 10) with channel `http` and actor `actor` (default
`http`; a label only, the Bearer token is the authority). `optionId` is one of the view's
`affordances.options` (`cancel` is accepted as an alias of `decline`); it may be omitted only for a
question whose options are just `decline`, which accepts `content` against `requestedSchema`. An
approval, gate or changed-check takes `content` `{"reason": "<text>"}` at most. It answers `200`
with the resolved `EscalationView` (`state: "resolved"`, `resolution` set, `affordances.options`
empty), plus a `note` only when a task-wide grant was refused. A body that is not an object, an `optionId` that is not a string, a `content` that is not
an object or an `actor` that is not a string answers `400`; an id no record has `404`; an
escalation already settled, or whose approval or question is no longer waiting, `409` with
`"code": "escalation_not_pending"` beside `error` (a `turn` the task no longer waits on included); an
unknown option, a `content` that fails `requestedSchema` or a `content` blocked by a `pre_input`
policy `422`.

`POST /escalations/<id>` is the only route that settles a pause, whatever its kind, and
`GET /escalations` is the only list of them. A client written against the earlier per-kind
surfaces adapts as follows; the names on the left do not exist, and a request to a retired route
answers `404`:

| Retired | Use instead |
|---|---|
| `GET /approvals` | `GET /escalations?since=<seq>` (an approval is an escalation of kind `approval`, `gate` or `check_changed`) |
| `POST /approvals/<token>` | `POST /escalations/<id>` with `optionId` `approve_once`, `approve_task` or `deny`, and `content` `{"reason"}` at most; `actor` replaces the body's `channel` (the channel is always `http`) |
| `POST /tasks/<id>/answer` | `POST /escalations/<id>` with `optionId` and `content`; `optionId` `decline` declines |
| MCP `approvals_list`, `approvals_grant`, `approvals_deny`, `task_answer` | MCP `escalations`, `resolve` |
| `task approve`, `task deny` (CLI) | `docket task answer <ref> --option approve_once\|approve_task\|deny`; `docket task pregrant` for a command approved ahead |
| Telegram `/approve`, `/deny` | Telegram `/answer <esc-id> <option>` |
| task keys `approvalToken`, `question`, `answers`, `consultAnswer`, `pregrants`, `taskGrants`, `gateOverridePipelineIndex` | `escalations` on the task record; `escalation` on a task view and on the `POST /tasks/<pod>` answer of a gated enqueue |
| inbox `needsYou` approval items (`ApprovalView`, `token`) | `EscalationView` items (`id`, `kind`, `affordances`) |
| trace events `approval_requested`, `question_asked`, `input_requested`, `input_answered`, `input_expired` | `escalation_asked`, `escalation_delivered`, `escalation_resolved`, `escalation_expired`, `escalation_decided` |
| contract `operator-v1` (`docs/contracts/operator-v1/`) | `operator-v2` (`docs/contracts/operator-v2/`); `operator-v1.1` stays |

A task record lists the escalations opened for it as `escalations`, and `GET /inbox` shows the
one a task waits on as the `escalation` of its task view. An approval's `apr-` token is not an
address: no response and no request body carries it.

### `/health` under dispatch

The keys and the unauthenticated access of `GET /health` are owned by `serve-read-api.spec.md`.
Under `docket start --dispatch` its `dispatch` block reads:

```json
{"status": "ok", "apiVersion": "6",
 "dispatch": {"on": true, "inflight": ["web-dev"], "stopping": false, "workers": 4}}
```

`inflight` lists the pods whose sweep is running, `stopping` is true after the first stop signal,
and `on` is false when `--dispatch` was not given.

### Re-attaching after a restart

A client whose runner, or docket itself, restarted re-attaches from durable state alone. Every
rule below holds because the pod's task list and the approval records, on disk under
`DOCKET_HOME`, are the only state; a server instance holds none.

1. `GET /tasks/<pod>/<id>` serves any task of the pod from disk, whatever its status and
   whichever server instance started its hops. A `waiting_approval` or `waiting_input` task lists
   the escalations opened for it in `escalations`, and the one it waits on is a record of
   `GET /escalations?task=<id>` with `state` `pending`.
2. An escalation is resolvable after either process restarts: `POST /escalations/<id>` reads the
   same files, so a fresh instance over the same `DOCKET_HOME` accepts the answer a previous
   instance parked. The pause's own `expiresAt` is on its record (`GET /escalations`).
3. A resolution moves the task to `pending` and starts nothing (a grant of a `check_changed`
   escalation is the exception: it ends the task `done`, see "Check changed" below). The next sweep tick
   (every 30 s by default under `--dispatch`) or `POST /dispatch/<pod>` resumes it at the hop it stopped on; a
   completed hop is never re-run.
4. Use one `idempotencyKey` per attempt. The key binds to the task for as long as the task is in
   the pod's queue, whatever its status: a retry that reuses the key after a failure answers
   `200` with `"created": false` and the failed task, and enqueues nothing. A new attempt takes a
   new key, or `POST .../retry` on the failed task.
5. Expiry and its final states are not restated here: an approval past its `expiresAt` resolves
   to denied and fails its task with `failureKind: "approval_expired"`, never `approval_denied`,
   which only a sent `deny` produces (`security-gates.spec.md`, "Approval tokens and approval
   packs"; additive to version 6); a question past its
   `expiresAt` moves the task to `blocked` with `blockedReason: "input_expired"`
   (`operator-loop.spec.md`, `inputExpiryHours`); both are ended by the one sweep, by each
   record's `onExpiry`.
5a. A task at `L5` whose tool call needs approval fails at once with `failureKind: "needs_human"`
   (`security-gates.spec.md` "Autonomy levels" item 4) and is final until `POST .../retry`, which
   a caller uses to run it again at `L3`.
6. A `failed` task with `failureKind: "stale_claim"` is transient under `--dispatch`: the sweep
   resumes it from its last persisted hop on the next tick. A `failed` task with any other
   `failureKind` (except a settled `dispatch_refused`, which the sweep also resumes) is final
   until `POST .../retry`.

## Check changed

A task whose finished diff touches a protected path (`security-gates.spec.md` "Protected paths and
the reviewed digest") is not `done`: it is `waiting_approval` whatever the pod's profile, so a
consumer that polls for `done` does not see an unreviewed change to a check.

1. The task record (`GET /tasks/<pod>/<id>`, `GET /inbox`'s task view reason) carries
   `checkChanged`, the sorted protected paths the diff touched; `GET /escalations?task=<id>`
   lists the escalation of kind `check_changed` it waits on (`serve-read-api.spec.md`).
2. `POST /escalations/<id>` with `optionId` `approve_once` ends the task `done`; `deny` ends it
   `failed` with `failureKind: "check_changed"`, and an escalation past its `expiresAt` with
   `failureKind: "approval_expired"`; either is final until `POST .../retry`. `checkChanged` stays
   on the record either way, so a client still knows what the pause was about.
3. `checkChanged` and `failureKind: "check_changed"` are additive keys of version 6.

## Wait

A pipeline `wait` step (`pipeline-format.spec.md` "Wait steps") parks its task until a time or a
probe; the sweep ends the wait, nobody is asked.

1. The task is `waiting_input`, its view carries `escalation` and `a2aState` `WORKING`, and
   `GET /escalations?task=<id>` lists the escalation of kind `wait`, `policy` `machine`,
   `options` `resume`, `expiresAt` the due time.
2. `GET /inbox` lists the wait under `escalations` and neither it nor its task under `needsYou`
   (`operator-loop.spec.md` areas 5 and 11).
3. `POST /escalations/<id>` with `optionId` `resume` ends the wait early; the task becomes `pending`
   and the next sweep tick or `POST /dispatch/<pod>` runs the step after the wait. Any other
   `optionId` answers `422`; a wait already ended answers `409`.
4. A wait that times out with no `on.timeout` route blocks the task, `blockedReason:
   "wait_expired"`, final until `POST .../retry` or an unblock; with a route the task runs on.
5. The kind `wait` and the policy `machine` are additive values of the `operator-v2` contract
   (`docs/contracts/operator-v2/`), not a new version. A client **MUST** ignore an escalation kind it
   does not know, and **MUST NOT** answer one it does not render.

## Return

| Code | When |
|---|---|
| `200` | a read; an idempotent re-post; cancel/retry/apply/ensure/resume/memory decision done |
| `201` | a new task or a new pod |
| `400` | a `status` of `GET /pods/<p>/memory` that is not `accepted`, `pending` or `refused`, a bad `decision` or `reason` of `POST /pods/<p>/memory/<id>`, malformed JSON or a non-object body, an ill-typed `optionId`, `content` or `actor` of `POST /escalations/<id>`, a `since` of `GET /escalations` or an `updatedSince` of `GET /tasks/<pod>` (`code: bad_cursor`) that is not a non-negative integer, missing `description`, a bad project id, a `task` with an unknown key or a field of the wrong type, an unknown `status` filter, a `baseRef`/`pipeline`/`gate`/`prepare`/`externalRef`/`idempotencyKey`/`maxTokens`/`autonomy`/`variables`/`conversation` of the wrong shape, a `conversation` on a pipeline of more than one step (`code: conversation_needs_one_step`), a naive `since`, a bad `apply` body |
| `401` | missing or wrong Bearer token, always first |
| `403` | the read-scoped token (`DOCKET_SERVE_READ_TOKEN`) on a `POST` route (`code: read_scope`) |
| `404` | no pod (checked before an `apply` body is read; `resume` too), no task, no escalation (`GET` or `POST /escalations/<id>`), no memory entry (`POST /pods/<p>/memory/<id>`), no such route; a task whose branch is gone (`diff`) |
| `409` | pod exists without `ensure`; `retry` on a task that is not `blocked`/`failed`; `cancel` on a terminal task; `diff` on an in-place task; a memory decision on an entry that is not `pending`; `apply` without the review code or with a refused command; `POST /escalations/<id>` on an escalation that is already settled or whose pause is no longer waiting (the body carries `code: escalation_not_pending`) |
| `413` | a request body over 1 MiB |
| `422` | a `restrictions` entry that would widen (`network: open`, a non-`block` policy rule, an unknown tool name); an `autonomy` above the pod profile's ceiling; an invalid `brief`; `POST /escalations/<id>` with an unknown option, content that fails the schema or content a policy blocks |
| `500` | `POST /pods` could not provision (the attempt is rolled back); `GET /pods/<p>` and `POST /pods/<p>/resume` for a pod whose stored settings are invalid |

`GET /tasks/<pod>` for a pod with no queue answers `200` with an empty list. Error bodies are
`{"ok": false, "error": "<sentence>"}`, with the extra keys the examples show. A refusal that
carries a stable `code` (a `DocketError` with a `code` attribute, or a route naming one) puts it on
the wire as `"code"`, whichever route answers it.

## Validation

- One test per rule of "Re-attaching after a restart": a restart is a first server shut down and a
  second one started over the same temporary `DOCKET_HOME`. The oracles are the HTTP bodies and the
  pod's task list.
- The routes are tested against a real server on a loopback port, a pod seeded in a temporary
  `DOCKET_HOME`, and a stub OpenAI-compatible server on loopback for the routes that run a hop.
- `GET /escalations` is pinned through the real route by a contract test that parks a consult
  through dispatch and compares both it and `GET /inbox` to a recorded fixture.
- Each example body above is asserted key-for-key by the route's test (the oracle is the key
  set and the status code, not the prose).
- Unit tests cover enqueue idempotency, `restrictions` validation, `maxTokens` arithmetic, the two
  hop event types and the pod report.
- The security condition of `restrictions` is pinned by an escape-style test: a pod whose
  implementer may `write` runs a task with `deniedTools: ["write"]` against the stub server and
  the `write` call is refused with `policy_id == "task-restriction"` in the audit log.

## Implementation

- `src/docket/interfaces/http/routes/`: the handler for every route above (`table.py` is the
  route table, one module per resource).
- `src/docket/interfaces/http/routes/escalations.py`: `get_escalations`, `get_escalation`, `post_escalation`.
- `src/docket/tasks/application/escalations.py`: `resolve`.
- `src/docket/interfaces/http/server.py`: `render_health`.
- `src/docket/interfaces/http/routes/health.py`: `SERVE_API_VERSION`, the `tokenBudget`
  computation on read.
- `src/docket/interfaces/http/exchange.py`: the 1 MiB body cap.
- `src/docket/tasks/application/queue.py`: `enqueue_task_once`, `dispatchable_pods`,
  the claim-time refusals (`base_ref`, `pipeline`, `prepare`).
- `src/docket/tasks/application/lifecycle.py`: `cancel_task`, `retry_task`, `task_diff`, `resume_pod`.
- `src/docket/tasks/domain/options.py`: addressable-task and `restrictions` validation,
  `TASK_STATUSES`.
- `src/docket/hops/application/report.py`: the `GET /pods` row (`pod_summary`) and `GET /pods/<p>`
  (`pod_detail`), the `budget` object (`_budget_fields`).
- `src/docket/teams/apply/plan.py`: `apply_directory`; `src/docket/governance/review.py`: the
  review code and `repo.allow`.
- `src/docket/teams/pod_provisioning.py`: `provision_pod`.
- `src/docket/tasks/application/corrections.py`: `read` and the cursor helpers.
- `src/docket/interfaces/http/routes/pod_records.py`: `GET /pods/<p>/records[/<set>]`, over
  `teams/records.py`.
- `src/docket/observability/trace.py`: `hop_started`, `hop_finished` in `EVENT_TYPES`.
- `src/docket/platform/git.py`: `git_diff_range`, `git_untracked`, `DIFF_MAX_CHARS`.
- `tests/integration/interfaces/test_serve_reattach.py`, `test_serve_tasks_endpoint.py`,
  `test_serve_task_lifecycle.py`, `test_serve_pods_endpoint.py`, `test_serve_pods_config.py`,
  `test_serve_pods_corrections.py`, `test_pod_records_api.py`, `test_task_check_changed.py`; `tests/support/model_server.py`
  (fixture `fake_model`).
