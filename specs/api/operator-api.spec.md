# Operator API (HTTP, version 5) -- contract spec

**Version**: 5.0.1
**Status**: Planned (Phase 43, ADR 0027). Nothing below is implemented until the card that owns
each route closes; the cards are on the active board, Phase 43. `SERVE_API_VERSION` stays `"4"` until
Wave 111 closes.
**Last Updated**: 2026-10-14

## Purpose

This specification defines the routes an external plan of record (a project manager, a CI job,
an operator's script) uses to run work on a long-lived pod through `docket start --dispatch`:
enqueue an addressable task, follow its hops, cancel, retry and diff it, read and apply a pod's
configuration, and read the corrections ledger. It is the one door for a program; the CLI is
the door for a person, and both call the same `core/` functions (the Phase 22 rule: expose what
`core/` already does, add no new behaviour).

Version 5 is negotiated, not pinned: a consumer reads `apiVersion` from `GET /status.json`
(`serve-read-api.spec.md`) and names the version it needs. There is no interim version.

## Scope

This specification covers:

- The task body fields added to `POST /tasks/<pod>` and the idempotent answer
- `GET /tasks/<pod>` filtering, `GET /tasks/<pod>/<id>`, `POST .../cancel`, `POST .../retry`,
  `GET .../diff`
- The `hop_started` / `hop_finished` trace events a consumer reads from `GET /traces/<pod>`
- `GET /pods`, `GET /pods/<p>`, `POST /pods` with `ensure`, `POST /pods/<p>/apply`,
  `GET /pods/<p>/corrections`
- `/health` under dispatch, `--bind`, the stop and resume rules of the daemon
- Status codes and error bodies

It does NOT cover:

- The unchanged read routes (`/status.json`, `/metrics`, `/approvals`, `/runs`, `/inbox`,
  `GET /traces/<pod>`'s cursor, `GET .../evidence`) -- `serve-read-api.spec.md`
- `POST /approvals/<token>`, `POST /tasks/<id>/answer`, `POST /tasks/<id>/pregrants`,
  `POST /dispatch/<pod>` -- unchanged, `serve-read-api.spec.md` and `operator-loop.spec.md`
- The task record's persisted shape -- `pod-dispatch.spec.md`; the trace record --
  `trace-store.spec.md`; the `.docket/teams/<pod>/` layout -- `pod-blueprints.spec.md`
- Multi-tenancy, external authentication, push, streaming, quotas (ADR 0027 "What this does
  not buy")

## Syntax

Every route below requires `Authorization: Bearer <token>` (the token `docket start` prints or
writes with `--token-file`); `401` comes before any other check. `<pod>` is a project id and is
validated as today (`_reject_bad_project_id`). Bodies are JSON objects; a malformed body is `400`.

| Route | Owner in `core/` | Card |
|---|---|---|
| `POST /tasks/<pod>` | `dispatch.enqueue_task` | P43-1 |
| `GET /tasks/<pod>?externalRef=&status=` | `dispatch.read_tasks` | P43-1 |
| `GET /tasks/<pod>/<id>` | `dispatch.read_tasks` | P43-1 |
| `POST /tasks/<pod>/<id>/cancel` | `dispatch.cancel_task` (new, moved from `cli/_task.py`) | P43-10 |
| `POST /tasks/<pod>/<id>/retry` | `dispatch.retry_task` | P43-10 |
| `GET /tasks/<pod>/<id>/diff` | `dispatch.task_diff` (new) over `edges/adapters/system.py` | P43-10 |
| `GET /pods` | `dispatch.dispatchable_pods` | P43-6 |
| `GET /pods/<p>` | `pod_report.pod_report` (moved from `cli/_pod_show.py`) + `profile` | P43-6 |
| `POST /pods` (`ensure`) | `pod_provisioning.provision_pod` | P43-6 |
| `POST /pods/<p>/apply` | `pod_apply.plan_apply` / `classify_directory` / `apply` | P43-8 |
| `GET /pods/<p>/corrections?since=` | `corrections.read` | P43-9 |
| `GET /health` (dispatch block) | `serve.render_health` | P43-11 |

The CLI keeps symmetry: `docket task add` gains `--external-ref`, `--idempotency-key`,
`--base-ref`, `--pipeline`, `--gate`, `--max-tokens` (P43-1); `docket task cancel|retry|diff`
call the same core functions (P43-10); `docket start` gains `--bind` (P43-11).

## Arguments

### `POST /tasks/<pod>` -- the task body

| Field | Type | Rule |
|---|---|---|
| `description` | string | required, as today |
| `priority` | `high` / `normal` / `low` | as today |
| `trusted` | bool | as today |
| `brief` | object | as today (`TaskBrief`) |
| `externalRef` | string, 1-200 chars | a caller label, stored verbatim, never interpreted; filterable |
| `idempotencyKey` | string, 1-200 chars | when a task in this pod's queue already carries it, nothing is enqueued and that task is returned with `200`; a new task answers `201` |
| `baseRef` | string | a branch name or commit the task worktree starts from (`git worktree add -b <task-branch> <dir> <baseRef>`); unset means the codebase's HEAD as today. Validated at claim, not at enqueue: an unresolvable ref fails the task before any hop with `failureKind: "base_ref"` |
| `pipeline` | string | the name of a pod-local pipeline (`<pod config dir>/pipelines/<name>.yaml`) or a shipped methodology recipe (`docket pod recipes`); unset means the pod's effective pipeline. Resolved at claim; an unknown name fails the task before any hop with `failureKind: "pipeline"` |
| `gate` | object | `{"command": string, "timeoutS"?: int, "map"?: {exit code: label}}` -- an `ExternalGate` (ADR 0025) added **after** the last implementer step's own gate, with the same labels and `on:` routing. It never replaces a gate the pipeline declares |
| `maxTokens` | int > 0 | a budget over the task's measured usage (`input + output` summed over hops); each hop runs with `token_budget = maxTokens - used so far`; a hop that would start with nothing left fails the task with `failureKind: "budget"` |
| `restrictions` | object | see below. Anything that would widen is `422` |

`restrictions`:

| Field | Type | Rule |
|---|---|---|
| `deniedTools` | list of tool names | unioned with the role's `denied_tools` and the pod's `deniedTools` when the hop's registry is narrowed; an unknown name is `422` (same universe as `pod set deniedTools`) |
| `network` | `"none"` | the hop's jail network is `none` whatever the pod records; the only accepted value, since `"open"` would widen |
| `policies` | list of policy documents | each a `kind: policy` short or canonical form; every rule's action MUST be `block`, any other action is `422`; loaded for the task's session after the pod's policies, never persisted to the pod |

### `POST /tasks/<pod>/<id>/cancel`

Body optional: `{"reason"?: string}`. Cancels a `running` task (kills the hop's process group
through `runs.cancel_run`, as `docket task cancel` does) or a parked one
(`cancel_parked_task`). Audited with channel `http`.

### `POST /tasks/<pod>/<id>/retry`

No body. A `blocked` or `failed` task flips to `pending` keeping its hops (`retry_task`). A
rework that must start from the previous attempt's branch is a new `POST /tasks/<pod>` with
`baseRef` set to that branch, not a retry.

### `POST /pods`

As today (`name`, `location`, `blueprint`, `pod`, `budget`, `verifyCmd`), plus `ensure: true`:
when the pod exists the answer is `200` with `"created": false` and nothing is changed or
re-applied. Without `ensure` an existing pod stays `409`.

### `POST /pods/<p>/apply`

| Field | Type | Rule |
|---|---|---|
| `directory` | string | absolute path, or unset for the repository's own directory (`.docket/teams/<p>/` when present, else `.docket/`) |
| `dryRun` | bool | plan only, nothing written |
| `accept` | string | the review code for a directory that runs things on this machine (ADR 0024 §6). HTTP is off a terminal: without the matching code such a directory is `409` with the code in the body and nothing is created |

## Options

Query parameters:

| Route | Parameter | Rule |
|---|---|---|
| `GET /tasks/<pod>` | `externalRef` | exact match |
| `GET /tasks/<pod>` | `status` | one task status, the enum of `cli-json-shapes.spec.md` |
| `GET /pods/<p>/corrections` | `since` | ISO timestamp; records with `ts > since`, append order |

## Output

### Task answers

`POST /tasks/<pod>` (new task, `201`):

```json
{"ok": true, "created": true, "task": "task-5d0c...", "project": "fab-dev", "status": "pending"}
```

The same body with an `idempotencyKey` already in the queue (`200`):

```json
{"ok": true, "created": false, "task": "task-5d0c...", "project": "fab-dev", "status": "running"}
```

`GET /tasks/<pod>/<id>` returns the full task record of `pod-dispatch.spec.md` (the same object
`GET /tasks/<pod>` lists), with the fields this version adds:

```json
{
  "id": "task-5d0c...", "status": "done", "priority": "normal",
  "externalRef": "TACK-412/attempt-2", "idempotencyKey": "TACK-412:2",
  "baseRef": "docket/fab-dev/task-91aa...", "pipeline": "tdd",
  "gate": {"command": "npm test -- --ci", "timeoutS": 600},
  "maxTokens": 400000,
  "restrictions": {"deniedTools": ["fetch"], "network": "none", "policies": []},
  "worktree": {"dir": "...", "branch": "docket/fab-dev/task-5d0c...", "baseCommit": "a1b2c3d"},
  "usage": {"input": 61230, "output": 4120,
            "byModel": {"local/local-model": {"input": 48000, "output": 3000},
                        "anthropic/claude-sonnet-4-6": {"input": 13230, "output": 1120}}},
  "hops": [{"role": "implementer", "stepId": "implementer", "model": "local/local-model",
            "provider": "local", "usage": {"input": 40950, "output": 1425}, "ok": true, "...": "..."}]
}
```

`POST .../cancel` (`200`): `{"ok": true, "task": "...", "status": "cancelled"}`.
`POST .../retry` (`200`): `{"ok": true, "task": "...", "status": "pending"}`.

`GET .../diff` (`200`, `application/json`):

```json
{
  "task": "task-5d0c...", "branch": "docket/fab-dev/task-5d0c...", "baseCommit": "a1b2c3d",
  "head": "f00ba4", "patch": "diff --git a/src/app.ts b/src/app.ts\n...",
  "untracked": ["out/report.md"], "worktreePresent": true
}
```

`patch` is `git diff <baseCommit>..<branch>` run in the codebase repository (the branch outlives
the worktree); `untracked` is `git status --porcelain` of the worktree while it exists and `[]`
with `"worktreePresent": false` afterwards. A task that ran in place (no worktree) answers `409`
with `"reason": "task ran in place"`.

### Trace events

Two typed records join `trace-store.spec.md`'s `EVENT_TYPES`, written in the task's session
(`agent:<pod>:<task-id>`) and read through `GET /traces/<pod>?since=`:

```json
{"ts": "...", "project": "fab-dev", "session_id": "agent:fab-dev:task-5d0c...",
 "agent_role": "implementer", "event_type": "hop_started",
 "payload": {"task": "task-5d0c...", "step": "implementer", "role": "implementer",
             "member": "fab-dev-implementer", "model": "local/local-model",
             "provider": "local", "cycle": 0, "attempt": 1}}
{"ts": "...", "project": "fab-dev", "session_id": "agent:fab-dev:task-5d0c...",
 "agent_role": "implementer", "event_type": "hop_finished",
 "payload": {"task": "task-5d0c...", "step": "implementer", "role": "implementer",
             "member": "fab-dev-implementer", "model": "local/local-model",
             "provider": "local", "cycle": 0, "attempt": 1, "ok": true,
             "verdict": null, "gate": "pass", "usage": {"input": 40950, "output": 1425},
             "durationMs": 94012, "error": ""}}
```

`cycle` is the rework cycle (0 before any `REQUEST-CHANGES`); `verdict` is the Reviewer's or
Tester's label or `null`; `gate` is the step's gate label or `null`. `hop_started` names the
*planned* model (the step's `model` override, else the member's configured model), and
`hop_finished` names the *served* model the turn reported. The existing `tool_call`
hop marker and the `tool_result`/`error` closing record stay as they are.

### Pod answers

`GET /pods` (`200`): `{"pods": [{"name": "fab-dev", "codebase": "/srv/fabulada", "members": 2,
"profile": "lights-out", "queue": {"pending": 1, "running": 1}}]}`.

`GET /pods/<p>` (`200`): the object `docket pod show --json` prints (`cli-json-shapes.spec.md`,
unchanged keys: `members` with `role`, `model`, `modelSource`; `settings`; `pipeline`;
`configOfRecord`; `mcpServers`; `skills`; `exporters`) plus:

```json
{"profile": {"name": "lights-out", "violations": [{"requirement": "network", "fix": "docket pod set network none"}]},
 "pipelineSource": "pod",
 "repoConfigDir": "/srv/fabulada/.docket/teams/fab-dev"}
```

`POST /pods` with `ensure` on an existing pod (`200`): `{"ok": true, "created": false,
"project": "fab-dev"}`; a new pod answers as today with `"created": true`.

`POST /pods/<p>/apply` (`200`): the `ApplyResult` `docket pod update --json` prints
(`cli-json-shapes.spec.md`), with `"dryRun": true|false`. A directory that runs things without
a matching `accept` (`409`):

```json
{"error": "this directory runs commands on this machine; pass accept",
 "reviewCode": "7f3a2c", "runs": [{"kind": "run", "detail": "npm ci"}]}
```

`GET /pods/<p>/corrections?since=2026-10-01T00:00:00Z` (`200`):

```json
{"corrections": [{"ts": "2026-10-03T10:12:00Z", "project": "fab-dev", "kind": "review_rejected",
                  "taskId": "task-91aa...", "role": "reviewer", "text": "...", "source": "pipeline"}],
 "next": "2026-10-03T10:12:00Z"}
```

### `/health` under dispatch

Unchanged keys plus, when `docket start` runs with `--dispatch`:

```json
{"ok": true, "apiVersion": "5",
 "dispatch": {"on": true, "inflight": ["fab-dev"], "stopping": false, "workers": 4}}
```

## Return

| Code | When |
|---|---|
| `200` | a read; an idempotent re-post; cancel/retry/apply/ensure done |
| `201` | a new task or a new pod |
| `400` | malformed JSON, missing `description`, an unknown field type, a `baseRef`/`pipeline`/`gate` of the wrong shape |
| `401` | missing or wrong Bearer token, always first |
| `404` | no pod, no task, no such route |
| `409` | pod exists without `ensure`; `retry` on a task that is not `blocked`/`failed`; `cancel` on a terminal task; `diff` on an in-place task; `apply` without the review code |
| `422` | a `restrictions` entry that would widen (`network: open`, a non-`block` policy rule, an unknown tool name); an invalid `brief` as today |

Error bodies are `{"error": "<sentence>"}` as today, with the extra keys the examples show.

## Validation

- `tests/integration/test_serve_tasks_endpoint.py` (extended) and new
  `tests/integration/test_serve_task_lifecycle.py`, `test_serve_pods_config.py`: the real
  `_DocketHandler` on a loopback `ThreadingHTTPServer`, a pod seeded in a temporary
  `DOCKET_HOME`, a stub OpenAI-compatible server on loopback for the routes that run a hop
  (the stub `tests/integration/test_harness_cli.py` carries today moves to
  `tests/integration/conftest.py` in P43-12 before that file is deleted).
- Each example body above is asserted key-for-key by the route's test (the oracle is the key
  set and the status code, not the prose).
- `tests/unit/core/test_dispatch.py`: `enqueue_task` idempotency, `restrictions` validation,
  `maxTokens` arithmetic; `tests/unit/core/test_trace.py`: the two event types;
  `tests/unit/core/test_pod_report.py` after the move.
- The security condition of `restrictions` is pinned by an escape-style test: a pod whose
  implementer may `write` runs a task with `deniedTools: ["write"]` against the stub server and
  the `write` call is refused with `policy_id == "task-restriction"` in the audit log.
- `bash tests/golden/run.sh verify-all`: `task add --help`, `start --help` and
  `task cancel|retry|diff --help` goldens change deliberately in P43-1, P43-10 and P43-11.
- `serve-read-api.spec.md` bumps its `API version` line to `5` in P43-12 and records the
  routes this spec owns.

## Changelog

### Version 5.0.1 (2026-10-14)

- Trace events: `hop_started` names the planned model and `hop_finished` the served one (P43-5).

### Version 5.0.0 (2026-10-14)

- First version: the Phase 43 contract (ADR 0027). Planned; implemented route by route by
  P43-1, P43-5, P43-6, P43-8, P43-9, P43-10, P43-11; version negotiation and the harness
  deletion in P43-12.
