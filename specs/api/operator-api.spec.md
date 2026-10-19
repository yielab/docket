# Operator API (HTTP, version 6) -- contract spec

**Version**: 6.1.0
**Status**: Implemented (Phase 43, ADR 0027; Phase 45, ADR 0029). `SERVE_API_VERSION` is `"6"`.
**Last Updated**: 2026-10-19

## Purpose

This specification defines the routes an external plan of record (a project manager, a CI job,
an operator's script) uses to run work on a long-lived pod through `docket start --dispatch`:
enqueue an addressable task, follow its hops, cancel, retry and diff it, read and apply a pod's
configuration, and read the corrections ledger. It is the one door for a program; the CLI is
the door for a person, and both call the same `core/` functions (the Phase 22 rule: expose what
`core/` already does, add no new behaviour).

Version 6 is negotiated, not pinned: a consumer reads `apiVersion` from `GET /status.json`
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

| Route | Owner in `core/` | Card | Status |
|---|---|---|---|
| `POST /tasks/<pod>` | `dispatch.enqueue_task` | P43-1 | Implemented (Wave 109) |
| `GET /tasks/<pod>?externalRef=&status=` | `dispatch.read_tasks` | P43-1 | Implemented (Wave 109) |
| `GET /tasks/<pod>/<id>` | `dispatch.read_tasks` | P43-1 | Implemented (Wave 109) |
| `POST /tasks/<pod>/<id>/cancel` | `dispatch.cancel_task` (moved from `cli/_task.py`) | P43-10 | Implemented (Wave 111) |
| `POST /tasks/<pod>/<id>/retry` | `dispatch.retry_task` | P43-10 | Implemented (Wave 111) |
| `GET /tasks/<pod>/<id>/diff` | `dispatch.task_diff` over `edges/adapters/system.py` | P43-10 | Implemented (Wave 111) |
| `GET /pods` | `dispatch.dispatchable_pods` | P43-6 | Implemented (Wave 110) |
| `GET /pods/<p>` | `pod_report.pod_report` (moved from `cli/_pod_show.py`) + `profile` | P43-6 | Implemented (Wave 110) |
| `POST /pods` (`ensure`) | `pod_provisioning.provision_pod` | P43-6 | Implemented (Wave 110) |
| `POST /pods/<p>/apply` | `pod_apply.apply_directory` (plan, `review_decision`, apply) | P43-8 | Implemented (Wave 110) |
| `GET /pods/<p>/corrections?since=` | `corrections.read` | P43-9 | Implemented (Wave 110) |
| `GET /health` (dispatch block) | `serve.render_health` | P43-11 | Implemented (Wave 111) |

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
| `maxTokens` | int > 0 | a budget over the task's counted usage (`input - cached + output` summed over hops; a cache read is not counted); each hop runs with `token_budget = maxTokens - used so far`; a hop that would start with nothing left fails the task with `failureKind: "budget"` |
| `prepare` | string | the install command run in this task's worktree before its first hop; `""` or `none` runs nothing and wins over the pod's `prepare` and the lockfile. Unset means the pod's `prepare` setting, else the command for the worktree's lockfile (`pod-dispatch.spec.md` "Task preparation"). Stored on the task record before it runs and shown by `GET /tasks/<pod>/<id>`; an install that fails settles the task before any hop with `failureKind: "prepare"` and the output tail as `reason`. A newline or NUL, or more than 1,000 characters, is `400` |
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
(`cancel_parked_task`). Both halves are `dispatch.cancel_task`. Audited `task.cancel` with channel
`http` and the reason. `404` for an unknown pod or task; `409` when nothing is in flight to cancel
(a terminal task). The answer's `status` is `cancelled` when a run was stopped or a parked task
cancelled, else the task's own status after a stale claim was settled (`failed`).

### `POST /tasks/<pod>/<id>/retry`

No body. A `blocked` or `failed` task flips to `pending` keeping its hops (`retry_task`). A
rework that must start from the previous attempt's branch is a new `POST /tasks/<pod>` with
`baseRef` set to that branch, not a retry.

### `POST /pods`

`name`, `location`, `blueprint`, `pod`, `budget`, `verifyCmd` (`serve-read-api.spec.md`
§POST /pods), plus `ensure: true`:
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
| `GET /pods/<p>/corrections` | `since` | ISO-8601 timestamp with an offset (normalised to UTC; naive is `400`); records with `ts > since`, append order |

## Output

### Task answers

`POST /tasks/<pod>` (new task, `201`):

```json
{"ok": true, "created": true, "task": "task-5d0c...", "project": "web-dev", "status": "pending"}
```

The same body with an `idempotencyKey` already in the queue (`200`):

```json
{"ok": true, "created": false, "task": "task-5d0c...", "project": "web-dev", "status": "running"}
```

`GET /tasks/<pod>/<id>` returns the full task record of `pod-dispatch.spec.md` (the same object
`GET /tasks/<pod>` lists), with the fields this version adds:

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
usage), never below 0. It is computed on read, from the same values `core/dispatch.py` applies, and
is present on every task object the `GET /tasks/<pod>` list and `GET /tasks/<pod>/<id>` return.

The task's `usage` and each `byModel` entry sum their hops' `input`, `cached`, `cacheWrite` and
`output`. `input` includes the cache reads and writes, so a consumer counting new tokens computes
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

`patch` is `git diff <baseCommit>..<branch>` run in the codebase repository (the branch outlives
the worktree); `untracked` is `git status --porcelain` of the worktree while it exists and `[]`
with `"worktreePresent": false` afterwards. A task that ran in place (no worktree) answers `409`
with `"reason": "task ran in place"`. `patch` is capped at 500000 characters
(`system.DIFF_MAX_CHARS`); a longer one is cut and ends with a `[diff truncated ...]` line. A task
whose branch no longer exists answers `404` with a sentence.

### Trace events

Two typed records join `trace-store.spec.md`'s `EVENT_TYPES`, written in the task's session
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
`hop_finished` names the *served* model the turn reported. The existing `tool_call`
hop marker and the `tool_result`/`error` closing record stay as they are.

### Pod answers

`GET /pods` (`200`): `{"pods": [{"name": "web-dev", "codebase": "/srv/webapp", "members": 2,
"profile": "lights-out", "queue": {"pending": 1, "running": 1, "waitingApproval": 0,
"waitingInput": 0, "failed": 0, "completed": 4}}]}`; `queue` carries the counts `status --json` prints
under `tasks`.

`GET /pods/<p>` (`200`): the object `docket pod show --json` prints (`cli-json-shapes.spec.md`,
unchanged keys: `members` with `role`, `model`, `modelSource`; `settings`; `pipeline`;
`configOfRecord`; `mcpServers`; `skills`; `exporters`) plus:

```json
{"profile": {"name": "lights-out", "violations": [{"requirement": "network", "fix": "docket pod set network none"}]},
 "pipelineSource": "pod",
 "repoConfigDir": "/srv/webapp/.docket/teams/web-dev",
 "readOnly": ["/opt/node-22"]}
```

`readOnly` is the read-only jail grants a turn of this pod gets: the machine's
(`docket setup sandbox read add`), kept only where the pod's `settings.readOnly` names them
(`security-gates.spec.md` Exec sandbox requirement 14); `[]` when there are none.

`POST /pods` with `ensure` on an existing pod (`200`): `{"ok": true, "created": false,
"project": "web-dev"}`; a new pod answers as today with `"created": true`.

`POST /pods/<p>/apply` (`200`): `{"ok": true, "project", "items", "dryRun": true|false}`, `items`
being the `docket pod update --json` list (`cli-json-shapes.spec.md`); a dry run writes nothing.
A directory that runs things without a matching `accept` (`409`; a wrong `accept` is the same
`409`, listing only the items that changed since the code was issued, and never the current code):

```json
{"ok": false, "error": "this directory runs commands on this machine; pass accept",
 "reviewCode": "7f3a2c...", "runs": [{"kind": "pipeline-step", "name": "build", "runs": "npm ci"}]}
```

A directory that names a refused `allowCommands` shell is `409` with no `reviewCode`. A
nonexistent or relative `directory` is `400`, an unknown pod `404`. A pod with no recorded
codebase (its Lead has no `codebase` meta) is `400` with a message naming `docket pod update`
and a codebase; it is never reviewed against the directory's parent. The apply is audited as
`pod.apply` with `channel=http`; an accepted code is remembered as the CLI does (`repo.allow`).

`GET /pods/<p>/corrections?since=2026-10-01T00:00:00Z` (`200`):

```json
{"corrections": [{"ts": "2026-10-03T10:12:00Z", "project": "web-dev", "kind": "review_rejected",
                  "taskId": "task-91aa...", "role": "reviewer", "text": "...", "source": "pipeline"}],
 "next": "2026-10-03T10:12:00Z"}
```

### `/health` under dispatch

Unchanged keys plus, when `docket start` runs with `--dispatch`:

```json
{"ok": true, "apiVersion": "6",
 "dispatch": {"on": true, "inflight": ["web-dev"], "stopping": false, "workers": 4}}
```

### Re-attaching after a restart

A client whose runner, or docket itself, restarted re-attaches from durable state alone. Every
rule below holds because the task list (`TASK_LIST.json`) and the approval records are the only
state; a server instance holds none.

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
   (30 s under `--dispatch`) or `POST /dispatch/<pod>` resumes it at the hop it stopped on; a
   completed hop is never re-run.
4. Use one `idempotencyKey` per attempt. The key binds to the task for as long as the task is in
   the pod's queue, whatever its status: a retry that reuses the key after a failure answers
   `200` with `"created": false` and the failed task, and enqueues nothing. A new attempt takes a
   new key, or `POST .../retry` on the failed task.
5. Expiry and its final states are not restated here: an approval past its `expiresAt` resolves
   to denied (`security-gates.spec.md` 0.63.0, "Approval tokens and approval packs"); a question past its
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
   /approvals` lists the approval with context kind `check_changed`.
2. `POST /approvals/<token>` with a grant ends the task `done`; a deny (or an approval past its
   `expiresAt`) ends it `failed` with `failureKind: "check_changed"`, which is final until
   `POST .../retry`. `checkChanged` stays on the record either way.
3. `apiVersion` stays `"6"`: `checkChanged` and the new `failureKind` are additive to it, and the
   Phase 45 version has not been released.

## Return

| Code | When |
|---|---|
| `200` | a read; an idempotent re-post; cancel/retry/apply/ensure done |
| `201` | a new task or a new pod |
| `400` | malformed JSON, missing `description`, an unknown field type, a `baseRef`/`pipeline`/`gate`/`prepare` of the wrong shape |
| `401` | missing or wrong Bearer token, always first |
| `404` | no pod, no task, no such route |
| `409` | pod exists without `ensure`; `retry` on a task that is not `blocked`/`failed`; `cancel` on a terminal task; `diff` on an in-place task; `apply` without the review code |
| `422` | a `restrictions` entry that would widen (`network: open`, a non-`block` policy rule, an unknown tool name); an invalid `brief` as today |

Error bodies are `{"error": "<sentence>"}` as today, with the extra keys the examples show.

## Validation

- `tests/integration/test_serve_reattach.py`: one test per rule of "Re-attaching after a
  restart"; a restart is a first `ThreadingHTTPServer` shut down and a second one started over
  the same temporary `DOCKET_HOME`. The oracles are the HTTP bodies and `TASK_LIST.json`.
- `tests/integration/test_serve_tasks_endpoint.py` (extended) and new
  `tests/integration/test_serve_task_lifecycle.py`, `test_serve_pods_config.py`: the real
  `_DocketHandler` on a loopback `ThreadingHTTPServer`, a pod seeded in a temporary
  `DOCKET_HOME`, a stub OpenAI-compatible server on loopback for the routes that run a hop
  (the stub in `tests/integration/llm_stub.py`, fixture `llm_server`).
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

### Version 6.1.0 (2026-10-19)

- New "Check changed" section (P45-3, ADR 0029 point 3): a task whose diff touches a protected
  path is `waiting_approval` with `checkChanged: [paths]` under every profile; a grant ends it
  `done`, a deny `failed` with `failureKind: "check_changed"` (final). `apiVersion` stays `"6"`.

### Version 6.0.0 (2026-10-19)

- `apiVersion` `"6"` (P45-1, ADR 0029 point 1): `POST /tasks/<pod>` accepts `prepare`, the task
  record carries it and `prepared`, and `failureKind: "prepare"` is a new final failure (the sweep
  does not resume it). A consumer that needs docket to install a task's dependencies reads
  `apiVersion >= 6`; one that sends no `prepare` gets the pod's setting or the lockfile's command.

### Version 5.10.0 (2026-10-19)

- `POST /pods/<p>/apply` (P45-4): a pod with no recorded codebase is `400` instead of being reviewed
  against the directory's parent; the remembered review is per codebase and pod, so an approval
  for one pod never replaces another's (pod-blueprints 1.34.0 requirement 12).

### Version 5.9.0 (2026-10-19)

- New section "Re-attaching after a restart": six rules a client may rely on after its runner or
  docket restarts (tasks served from disk, tokens and questions answerable across restarts,
  answers start no sweep, one `idempotencyKey` per attempt, expiry by cross-reference,
  `stale_claim` resumed by the next sweep). Documents existing behaviour; pinned by
  `tests/integration/test_serve_reattach.py`.

### Version 5.8.0 (2026-10-18)

- `GET /pods/<p>` carries `readOnly`, the pod's effective read-only jail grants (the machine's
  list narrowed by the pod's `readOnly` setting). Additive: no existing key changes.

### Version 5.7.0 (2026-10-18)

- The task's top-level `usage` carries `cached` and `cacheWrite` beside `input` and `output`,
  summed over its hops like each `byModel` entry. Additive: no existing key changes.

### Version 5.6.0 (2026-10-18)

- Every task object the `GET /tasks/<pod>` list and `GET /tasks/<pod>/<id>` return carries
  `tokenBudget` (the per-turn ceiling, or what a task's `maxTokens` has left; see "Task answers").
  Additive: no existing key changes.
- A `byModel` entry carries `cached` and `cacheWrite` summed from its hops, beside `input` and
  `output`. Additive; the top-level `usage` keys are unchanged.

### Version 5.5.0 (2026-10-18)

- A hop's `usage` carries `cached` (the part of `input` served from a cache) and `cacheWrite` (the
  part of `input` written to one; 0 where the endpoint does not report it) beside `input` and
  `output`. Additive: a consumer that reads `input` and `output` is unaffected. A task's
  `maxTokens` counts `input - cached + output` over its hops; the task's own `usage` keys are
  unchanged.

### Version 5.4.1 (2026-10-18)

- `POST /pods` now reads `name` and `location` as this spec has said since 5.0.0; until
  0.2.0-beta.6's fix the route read `project` and `path` (found by Tack's first run against a real
  docket). A test sends the ADR 0027 body literally.

### Version 5.4.0 (2026-10-17)

- Status: implemented. The `exec` command and the harness are deleted; this spec is the one door
  for a program. `GET /status.json` answers
  `apiVersion` `"5"`.

### Version 5.3.0 (2026-10-17)

- `POST /tasks/<pod>/<id>/cancel`, `POST .../retry` and `GET .../diff` implemented (P43-10).
  `docket task diff` prints the same `patch` (`--json` the whole object).

### Version 5.2.0 (2026-10-17)

- `GET /pods`, `GET /pods/<p>` and `POST /pods` with `ensure` implemented (P43-6). The pod report
  is `core/pod_report.py`, shared with `docket pod show --json`. `repoConfigDir` is
  `pod_apply.repo_config_dir` (`<codebase>/.docket/teams/<pod>` when it exists, else `<codebase>/.docket`).
- `POST /pods/<p>/apply` implemented (P43-8): the review rule off a terminal, `reviewCode` and
  `runs` on `409`, `dryRun`, `pod.apply` audited with `channel=http`.
- `GET /pods/<p>/corrections?since=` reads the corrections
  ledger (P43-9) in append order, keeping records with `ts > since` (`corrections.read(project,
  since=)`). `since` is any ISO-8601 timestamp with an offset, normalised to UTC before the
  comparison; a naive `since` (no offset) is `400`, as is one that does not parse. `next` is
  the last returned record's `ts` in UTC with a `Z` suffix, else the normalised `since` in
  UTC `Z`, else `""`. The route answers `404` for a pod with no Lead and `401` without the
  bearer token.

### Version 5.1.0 (2026-10-14)

- Status: partially implemented. Wave 109 closed P43-1..5: the task fields and their claim-time
  and hop-time effects, the three P43-1 task routes, the hop events. The route table gains a
  Status column.

### Version 5.0.1 (2026-10-14)

- Trace events: `hop_started` names the planned model and `hop_finished` the served one (P43-5).

### Version 5.0.0 (2026-10-14)

- First version: the Phase 43 contract (ADR 0027). Planned; implemented route by route by
  P43-1, P43-5, P43-6, P43-8, P43-9, P43-10, P43-11; version negotiation and the harness
  deletion in P43-12.
