# Operator API (HTTP, version 6) -- contract spec

**Version**: 6.2.3
**Status**: Implemented (ADR 0027, ADR 0029). The server reports `apiVersion` `"6"`.
**Last Updated**: 2026-10-24

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
- `GET /pods`, `GET /pods/<p>`, `POST /pods` with `ensure`, `POST /pods/<p>/apply`,
  `GET /pods/<p>/corrections`
- The `dispatch` block of `GET /health` under `--dispatch`
- Re-attaching a client after a restart, and the `check_changed` approval a consumer sees
- Status codes and error bodies

It does NOT cover:

- The other read routes (`/status.json`, `/metrics`, `/runs`, `/inbox`,
  `GET /traces/<pod>`'s cursor, `GET .../evidence`) -- `serve-read-api.spec.md`
- `POST /approvals/<token>`, `POST /tasks/<id>/answer`, `POST /tasks/<id>/pregrants`,
  `POST /dispatch/<pod>` -- `serve-read-api.spec.md` and `operator-loop.spec.md`
- The task record's persisted shape -- `pod-dispatch.spec.md`; the trace record --
  `trace-store.spec.md`; the `.docket/teams/<pod>/` layout -- `pod-blueprints.spec.md`
- The `/health` body itself and `GET /approvals` -- `serve-read-api.spec.md`
- `--bind`, the Bearer token and the stop signals of `docket start` --
  `serve-read-api.spec.md` and `pod-dispatch.spec.md`
- Multi-tenancy, external authentication, push, streaming, quotas (ADR 0027 "What this does
  not buy")

## Syntax

Every route below requires `Authorization: Bearer <token>` (the token `docket start` prints or
writes with `--token-file`); `401` comes before any other check. `<pod>` is a project id, validated
as a project id (a bad one is `400`). Bodies are JSON objects; a malformed body is `400`, a body
over 1 MiB is `413`.

| Route | Does |
|---|---|
| `POST /tasks/<pod>` | enqueue a task, optionally idempotent and addressable |
| `GET /tasks/<pod>?externalRef=&status=` | list the pod's tasks, filtered |
| `GET /tasks/<pod>/<id>` | one task record |
| `POST /tasks/<pod>/<id>/cancel` | stop a running or parked task |
| `POST /tasks/<pod>/<id>/retry` | put a `blocked` or `failed` task back on the queue |
| `GET /tasks/<pod>/<id>/diff` | what the task's branch changed |
| `GET /pods` | every dispatchable pod with its queue counts |
| `GET /pods/<p>` | one pod's report |
| `POST /pods` (`ensure`) | provision a pod, or find it |
| `POST /pods/<p>/apply` | apply a directory of configuration to a pod |
| `GET /pods/<p>/corrections?since=` | the corrections ledger, from a cursor |
| `GET /health` (dispatch block) | whether the sweep is on and what is in flight |

The CLI keeps symmetry: `docket task add` takes `--external-ref`, `--idempotency-key`,
`--base-ref`, `--pipeline`, `--gate` and `--max-tokens`; `docket task cancel|retry|diff` run the
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
| `externalRef` | string, 1-200 chars | a caller label, stored verbatim, never interpreted; filterable |
| `idempotencyKey` | string, 1-200 chars | when a task in this pod's queue already carries it, nothing is enqueued and that task is returned with `200`; a new task answers `201` |
| `baseRef` | string | a branch name or commit the task worktree starts from (`git worktree add -b <task-branch> <dir> <baseRef>`); unset means the codebase's HEAD. Validated at claim, not at enqueue: an unresolvable ref, or a pod whose Implementer has no codebase, fails the task before any hop with `failureKind: "base_ref"` |
| `pipeline` | string | the name of a pod-local pipeline (`<pod config dir>/pipelines/<name>.yaml`) or of a recipe that carries a `pipeline.yaml`, the operator's own (`~/.docket/recipes/`) before the shipped ones (`docket pod recipes`); unset means the pod's effective pipeline. Resolved at claim; a name that resolves to nothing valid, or a `gate` that cannot be honoured, fails the task before any hop with `failureKind: "pipeline"` |
| `gate` | object | `{"command": string, "timeoutS"?: int, "map"?: {exit code: label}}` -- an `ExternalGate` (ADR 0025) added **after** the last implementer step's own gate, with the same labels and `on:` routing. It never replaces a gate the pipeline declares |
| `maxTokens` | int > 0 | a budget over the task's counted usage (`input - cached + output` summed over hops; a cache read is not counted); each hop runs with a turn token budget of `maxTokens - used so far`; a hop that would start with nothing left, or a turn that stops on that budget, fails the task with `failureKind: "budget"` |
| `prepare` | string | the install command run in this task's worktree before its first hop; `""` or `none` runs nothing and wins over the pod's `prepare` and the lockfile. Unset means the pod's `prepare` setting, else the command for the worktree's lockfile (`pod-dispatch.spec.md` "Task preparation"). Stored on the task record and shown by `GET /tasks/<pod>/<id>`; an install that fails settles the task before any hop with `failureKind: "prepare"` and the output tail as `reason`. A newline or NUL, or more than 1,000 characters, is `400` |
| `restrictions` | object | see below. Anything that would widen is `422` |

`restrictions`:

| Field | Type | Rule |
|---|---|---|
| `deniedTools` | list of tool names | unioned with the role's denied tools and the pod's `deniedTools` when the hop's registry is narrowed; an unknown name is `422` (the built-in tool names, as for `pod set deniedTools`) |
| `network` | `"none"` | the hop's jail network is `none` whatever the pod records; the only accepted value, since `"open"` would widen |
| `policies` | list of policy documents | each a `kind: policy` short or canonical form; every rule's action MUST be `block`, any other action is `422`; loaded for the task's session after the pod's policies, never persisted to the pod |

### `POST /tasks/<pod>/<id>/cancel`

Body optional: `{"reason"?: string, "actor"?: string}`; `actor` is a label for the audit entry,
default `http`. Cancels a `running` task (kills the hop's process group, as `docket task cancel`
does) or a parked one (`waiting_input` or `waiting_approval`); the CLI runs the same function.
Audited `task.cancel` with channel `http` and the reason. `404` for an unknown pod or task; `409`
when nothing is in flight to cancel (a terminal task). The answer's `status` is `cancelled` when a
run was stopped or a parked task cancelled, else the task's own status after a stale claim was
settled (`failed`).

### `POST /tasks/<pod>/<id>/retry`

No body. A `blocked` or `failed` task flips to `pending` keeping its hops, with `blockedReason`,
`failureKind` and `reason` cleared; audited `task.retry`. A task in any other status is `409`, an
unknown task `404`. A rework that must start from the previous attempt's branch is a new `POST /tasks/<pod>` with
`baseRef` set to that branch, not a retry.

### `POST /pods`

The body, the `201` answer for a new pod and the `ensure` flag are owned by
`serve-read-api.spec.md` (POST /pods). With `ensure: true` and an existing pod the answer is `200`
with `"created": false` and nothing is changed or re-applied; without it an existing pod is `409`.

### `POST /pods/<p>/apply`

| Field | Type | Rule |
|---|---|---|
| `directory` | string | absolute path to an existing directory, or unset for the repository's own directory (`.docket/teams/<p>/` when present, else `.docket/`) |
| `dryRun` | bool | plan only, nothing written; no review code is needed |
| `accept` | string | the review code for a directory that runs things on this machine (ADR 0024). HTTP is off a terminal: without the matching code such a directory is `409` with the code in the body and nothing is written |

## Options

Query parameters:

| Route | Parameter | Rule |
|---|---|---|
| `GET /tasks/<pod>` | `externalRef` | exact match; both parameters combine |
| `GET /tasks/<pod>` | `status` | one of `pending`, `running`, `waiting_input`, `waiting_approval`, `blocked`, `failed`, `done`, `cancelled`; any other value is `400` |
| `GET /pods/<p>/corrections` | `since` | ISO-8601 timestamp with an offset (normalised to UTC; naive is `400`); records with `ts > since`, append order |

## Output

### Task answers

`POST /tasks/<pod>` (new task, `201`):

```json
{"ok": true, "created": true, "task": "task-5d0c...", "project": "web-dev", "status": "pending"}
```

A task gated by a `require_approval` `pre_input` verdict is created (`201`) with `"status":
"waiting_approval"` and an extra `"approvalToken"`. The same body with an `idempotencyKey` already
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

`tokenBudget` is the measured-token ceiling the next hop of the task would run under: the
configured per-turn budget (`AGENT_LOOP_TOKEN_BUDGET`) for a task without `maxTokens`; for a task
with one, what its cap has left after its persisted hops (`maxTokens` minus the hops' counted
usage), never below 0. It is computed on read, from the same values dispatch applies, and
is present on every task object the `GET /tasks/<pod>` list and `GET /tasks/<pod>/<id>` return.

The task's `usage` and each `byModel` entry sum their hops' `input`, `cached`, `cacheWrite` and
`output`; the task-level `usage` is written when the task settles, so a task still in flight has
only its hops' usage. `input` includes the cache reads and writes, so a consumer counting new tokens computes
`input - cached + output`, the rule docket's own budget applies.

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

`cycle` is the rework cycle (0 before any `REQUEST-CHANGES`); `verdict` is the Reviewer's or
Tester's label or `null`; `gate` is the step's gate label or `null`. `hop_started` names the
*planned* model (the step's `model` override, else the member's configured model), and
`hop_finished` names the *served* model the turn reported. `attempt` on `hop_started` is always `1`.

### Pod answers

`GET /pods` (`200`): `{"pods": [{"name": "web-dev", "codebase": "/srv/webapp", "members": 2,
"profile": "lights-out", "queue": {"pending": 1, "running": 1, "waitingApproval": 0,
"waitingInput": 0, "blocked": 0, "failed": 0, "done": 4, "cancelled": 0}}]}`; `queue` carries the
counts `status --json` prints under `tasks`: one per task status.

`GET /pods/<p>` (`200`): the object `docket pod show --json` prints (`cli-json-shapes.spec.md`:
`pod`, `members`, `settings`, `approvalMode`, `pipeline`, `network`, `budgetUnpriced`,
`configSource`, `configDigest`, `drift`) plus the four keys below, where `profile` here is the
verdict object (a row of `GET /pods` carries the profile name as a string):

```json
{"profile": {"name": "lights-out", "violations": [{"requirement": "network", "fix": "docket pod set network none"}]},
 "pipelineSource": "pod",
 "repoConfigDir": "/srv/webapp/.docket/teams/web-dev",
 "readOnly": ["/opt/node-22"]}
```

`readOnly` is the read-only jail grants a turn of this pod gets: the machine's
(`docket setup sandbox read add`), kept only where the pod's `settings.readOnly` names them
(`security-gates.spec.md` Exec sandbox requirement 14); `[]` when there are none.
`profile.violations` is empty unless the effective profile is `lights-out`, `pipelineSource` says
where the effective pipeline comes from, and `repoConfigDir` is `""` for a pod with no codebase.
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
nonexistent or relative `directory` is `400`, an unknown pod `404`. A pod with no recorded
codebase is `400` with a message naming `docket pod update`
and a codebase; it is never reviewed against the directory's parent. A plan that changes something
is audited as `pod.apply` with `channel=http`; an accepted code is remembered as the CLI does
(audit action `repo.allow`). A body field of the wrong type is `400`.

`GET /pods/<p>/corrections?since=2026-10-01T00:00:00Z` (`200`):

```json
{"corrections": [{"ts": "2026-10-03T10:12:00Z", "project": "web-dev", "kind": "review_rejected",
                  "taskId": "task-91aa...", "role": "reviewer", "text": "...", "source": "pipeline"}],
 "next": "2026-10-03T10:12:00Z"}
```

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
   whichever server instance started its hops. A `waiting_approval` task carries its
   `approvalToken`; a `waiting_input` task carries its `question`, with `options` when the park
   was a consultation or a decision.
2. A token or a question is answerable after either process restarts: `POST /approvals/<token>`
   and `POST /tasks/<id>/answer` read the same files, so a fresh instance over the same
   `DOCKET_HOME` accepts the grant or answer a previous instance parked. The approval's own
   `expiresAt` is on its record (`GET /approvals`).
3. An answer or grant moves the task to `pending` and starts nothing (a grant of a `check_changed`
   approval is the exception: it ends the task `done`, see "Check changed" below). The next sweep tick
   (every 30 s by default under `--dispatch`) or `POST /dispatch/<pod>` resumes it at the hop it stopped on; a
   completed hop is never re-run.
4. Use one `idempotencyKey` per attempt. The key binds to the task for as long as the task is in
   the pod's queue, whatever its status: a retry that reuses the key after a failure answers
   `200` with `"created": false` and the failed task, and enqueues nothing. A new attempt takes a
   new key, or `POST .../retry` on the failed task.
5. Expiry and its final states are not restated here: an approval past its `expiresAt` resolves
   to denied (`security-gates.spec.md`, "Approval tokens and approval packs"); a question past its
   `expiresAt` moves the task to `blocked` with `blockedReason: "input_expired"`
   (`operator-loop.spec.md`, `inputExpiryHours`).
6. A `failed` task with `failureKind: "stale_claim"` is transient under `--dispatch`: the sweep
   resumes it from its last persisted hop on the next tick. A `failed` task with any other
   `failureKind` (except a settled `dispatch_refused`, which the sweep also resumes) is final
   until `POST .../retry`.

## Check changed

A task whose finished diff touches a protected path (`security-gates.spec.md` "Protected paths and
the reviewed digest") is not `done`: it is `waiting_approval` whatever the pod's profile, so a
consumer that polls for `done` does not see an unreviewed change to a check.

1. The task record (`GET /tasks/<pod>/<id>`, `GET /inbox`'s task view reason) carries
   `checkChanged`, the sorted protected paths the diff touched, with `approvalToken`; `GET
   /approvals` lists the approval with context kind `check_changed`
   (`serve-read-api.spec.md`).
2. `POST /approvals/<token>` with a grant ends the task `done`; a deny (or an approval past its
   `expiresAt`) ends it `failed` with `failureKind: "check_changed"`, which is final until
   `POST .../retry`. `checkChanged` stays on the record either way.
3. `checkChanged` and `failureKind: "check_changed"` are additive keys of version 6.

## Return

| Code | When |
|---|---|
| `200` | a read; an idempotent re-post; cancel/retry/apply/ensure done |
| `201` | a new task or a new pod |
| `400` | malformed JSON or a non-object body, missing `description`, a bad project id, an unknown `status` filter, a `baseRef`/`pipeline`/`gate`/`prepare`/`externalRef`/`idempotencyKey`/`maxTokens` of the wrong shape, a naive `since`, a bad `apply` body |
| `401` | missing or wrong Bearer token, always first |
| `404` | no pod (checked before an `apply` body is read), no task, no such route; a task whose branch is gone (`diff`) |
| `409` | pod exists without `ensure`; `retry` on a task that is not `blocked`/`failed`; `cancel` on a terminal task; `diff` on an in-place task; `apply` without the review code or with a refused command |
| `413` | a request body over 1 MiB |
| `422` | a `restrictions` entry that would widen (`network: open`, a non-`block` policy rule, an unknown tool name); an invalid `brief` |
| `500` | `POST /pods` could not provision (the attempt is rolled back); `GET /pods/<p>` for a pod whose stored settings are invalid |

`GET /tasks/<pod>` for a pod with no queue answers `200` with an empty list. Error bodies are
`{"ok": false, "error": "<sentence>"}`, with the extra keys the examples show.

## Validation

- One test per rule of "Re-attaching after a restart": a restart is a first server shut down and a
  second one started over the same temporary `DOCKET_HOME`. The oracles are the HTTP bodies and the
  pod's task list.
- The routes are tested against a real server on a loopback port, a pod seeded in a temporary
  `DOCKET_HOME`, and a stub OpenAI-compatible server on loopback for the routes that run a hop.
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
- `src/docket/interfaces/http/server.py`: `render_health`.
- `src/docket/interfaces/http/routes/health.py`: `SERVE_API_VERSION`, the `tokenBudget`
  computation on read.
- `src/docket/interfaces/http/exchange.py`: the 1 MiB body cap.
- `src/docket/tasks/application/queue.py`: `enqueue_task_once`, `dispatchable_pods`,
  the claim-time refusals (`base_ref`, `pipeline`, `prepare`).
- `src/docket/tasks/application/lifecycle.py`: `cancel_task`, `retry_task`, `task_diff`.
- `src/docket/tasks/domain/options.py`: addressable-task and `restrictions` validation,
  `TASK_STATUSES`.
- `src/docket/hops/application/report.py`: the `GET /pods` row (`pod_summary`) and `GET /pods/<p>`
  (`pod_detail`).
- `src/docket/teams/apply/plan.py`: `apply_directory`; `src/docket/governance/review.py`: the
  review code and `repo.allow`.
- `src/docket/teams/pod_provisioning.py`: `provision_pod`.
- `src/docket/tasks/application/corrections.py`: `read` and the cursor helpers.
- `src/docket/observability/trace.py`: `hop_started`, `hop_finished` in `EVENT_TYPES`.
- `src/docket/platform/git.py`: `git_diff_range`, `git_untracked`, `DIFF_MAX_CHARS`.
- `tests/integration/interfaces/test_serve_reattach.py`, `test_serve_tasks_endpoint.py`,
  `test_serve_task_lifecycle.py`, `test_serve_pods_endpoint.py`, `test_serve_pods_config.py`,
  `test_serve_pods_corrections.py`, `test_task_check_changed.py`; `tests/support/model_server.py`
  (fixture `fake_model`).
