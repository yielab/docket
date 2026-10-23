# serve read API — contract spec

**Version**: 4.1.0
**Status**: Stable
**Last Updated**: 2026-10-23

## Purpose

This specification defines the HTTP API exposed by `docket start`: a small, versioned window
into fleet state for dashboards, CI pipelines and external tools. Three endpoints
(`/status.json`, `/metrics`, `/health`) are read-only and unauthenticated. Every other route,
read or write, requires the server's Bearer token, because it exposes per-task and per-dispatch
detail or changes state. All mutation flows through the CLI or these token-guarded routes.

## Scope

This specification covers:

- The three unauthenticated read endpoints (`/status.json`, `/metrics`, `/health`)
- The authenticated reads `GET /approvals`, `GET /runs`, `GET /runs/<id>`, `GET /inbox`,
  `GET /tasks/<project>`, `GET /tasks/<project>/<id>/evidence` and `GET /traces/<project>`
- The run lifecycle behind `GET /runs` and `POST /dispatch/<project>`
- The write routes `POST /dispatch/<project>`, `POST /tasks/<project>`, `POST /tasks/<id>/answer`,
  `POST /tasks/<id>/pregrants`, `POST /pods` and `POST /approvals/<token>`
- The JSON schema for each response, the Prometheus metric names and semantics, the versioning
  policy (what is a breaking change) and the auth requirement per endpoint

The addressable-task fields of `POST /tasks/<project>`, the `GET /tasks/<project>` filters and
`tokenBudget`, `GET /tasks/<project>/<id>`, `GET /tasks/<project>/<id>/diff`,
`POST /tasks/<project>/<id>/cancel|retry`, `GET /pods`, `GET /pods/<p>`,
`GET /pods/<p>/corrections` and `POST /pods/<p>/apply` are specified by
`operator-api.spec.md`.

**API version:** `6` (`SERVE_API_VERSION`, reported as `apiVersion` by `/status.json` and
`/health`).

The server binds to `127.0.0.1` by default; `docket start --bind <addr>` sets the listen
address and the startup banner warns when it is not loopback. Every request thread, and every
thread the server starts (sweeps, scheduled and webhook dispatches, the Telegram poll), serves the
`DOCKET_HOME` the server was started with. `/status.json`, `/metrics` and
`/health` require no auth. Every other route requires `Authorization: Bearer <token>`, compared in
constant time; the token is `DOCKET_SERVE_TOKEN` when set, otherwise a random one printed at
startup (or written 0600 to `docket start --token-file <path>`). A server with no token refuses
every authenticated request.

## Structure

Unauthenticated read endpoints:

| Endpoint | Content-Type | Auth required |
|---|---|---|
| `GET /status.json` | `application/json` | No |
| `GET /metrics` | `text/plain; version=0.0.4` | No |
| `GET /health` | `application/json` | No |

Authenticated read endpoints:

| Endpoint | Content-Type | Auth required |
|---|---|---|
| `GET /approvals` | `application/json` | Yes |
| `GET /runs` | `application/json` | Yes |
| `GET /runs/<id>` | `application/json` | Yes |
| `GET /inbox` | `application/json` | Yes |
| `GET /tasks/<project>` | `application/json` | Yes |
| `GET /tasks/<project>/<id>/evidence` | `application/json` | Yes |
| `GET /traces/<project>` | `application/json` | Yes |

Every response carries `Cache-Control: no-store`; consumers must not cache. An unknown `GET`
path is `404` (`text/plain`); an unknown `POST` path is `404 {"ok": false, "error": "not found"}`.
Errors from the JSON routes carry `{"ok": false, "error": <message>}`. A bare route prefix
(`GET /tasks`, `GET /traces`, `POST /tasks`, `POST /dispatch`, `POST /approvals`, with or without
a trailing `/`) checks auth first (`401`) and then answers `400` naming the missing segment. A `POST` body larger than 1 MiB is refused with `413`
without being read; an absent body reads as `{}`. Every socket read is bounded by a 30-second
timeout.

## Schema

### GET /status.json

Full fleet snapshot, served at `/status.json` only. Keys are **stable**; additional keys may be
added in minor versions.

```json
{
  "apiVersion": "6",
  "timestamp":  "2026-06-25T10:00:00Z",
  "channels":   ["telegram"],
  "agents": [
    {
      "id":           "myapp-lead",
      "name":         "My App Lead",
      "kind":         "project",
      "scope":        "project",
      "model":        "anthropic/claude-haiku-4-5-20251001",
      "registered":   true,
      "bindings":     [{"channel": "telegram"}],
      "lastActivity": "2026-06-25",
      "costUsd":      0.0,
      "budgetUsd":    10.0
    }
  ],
  "totalCostUsd": 0.0
}
```

**Field notes**

| Field | Type | Notes |
|---|---|---|
| `apiVersion` | string | Always `SERVE_API_VERSION`, currently `"6"`. |
| `channels` | string[] | Distinct channel names present in `fleet.json` bindings (e.g. `["telegram"]`). |
| `agents[*].bindings` | `{channel}[]` | The channel names the agent is bound to. **No peer id is published here**: a Telegram `peerId` is the chat id that is the whole Telegram authorization boundary, and this endpoint is unauthenticated. |
| `agents[*].scope` | `"project"` | Always `project`; `agents` lists pod members only. |
| `agents[*].budgetUsd` | float \| null | `null` when no budget cap is set for the agent. |
| `agents[*].lastActivity` | date string \| `"never"` | Date (`YYYY-MM-DD`) of the agent's most recently updated session, or `"never"`. |
| `agents[*].costUsd` | float | The runtime driver's reported dollar cost for the agent. The shipped driver measures tokens and records no dollar spend, so this is `0.0`. |
| `totalCostUsd` | float | Sum of `agents[*].costUsd`. |

### GET /metrics

Prometheus text format (content-type `text/plain; version=0.0.4`).

**Metric names (stable)**

| Metric | Type | Description |
|---|---|---|
| `docket_agents_total` | gauge | Number of project agents. |
| `docket_agent_cost_usd{agent,model}` | gauge | Per-agent dollar cost as the runtime driver reports it (`0` with the shipped driver; see `costUsd` above). |
| `docket_agent_turns_total{agent}` | gauge | Total turns per agent. Its samples follow all of `docket_agent_cost_usd`'s, under their own `# HELP`/`# TYPE`. |
| `docket_cost_usd_total` | gauge | Sum of `docket_agent_cost_usd`. |
| `docket_approvals_pending_total` | gauge | Pending approvals awaiting a human decision. |
| `docket_inbox_items{section}` | gauge | Items in the derived operator inbox (`GET /inbox`), by section (`needsYou`\|`failed`\|`doneSince`\|`running`). Computed fresh on every scrape with no `since`, so `doneSince` here is every terminal task, not scoped to any consumer's cursor. |
| `docket_tool_calls_total{decision}` | counter | Tool calls dispatched through the gated tool registry (`dispatch_tool`), by gate decision (`allow`\|`ask`\|`deny`), from `tool_result` trace events. Sum gives tool-call rate; the `deny` bucket over the sum gives denial rate. |
| `docket_policy_hits_total{policy_id,hook,action}` | counter | Guardrail policy hits, by policy id, hook (`pre_input`\|`pre_tool_call`\|`pre_output`) and the policy's own action (`warn`\|`redact`\|`require_approval`\|`block`). The `pre_input`/`pre_output` slice comes from `guardrail_check` trace events; the `pre_tool_call` slice comes from the audit log's `tool.deny`/`tool.ask`/`tool.warn`/`tool.redact` entries that name a policy, and is subject to the rotation caveat below. |
| `docket_approvals_total{channel,outcome}` | counter | Resolved approvals from the audit log's `approval.grant`/`approval.deny` entries, by channel (`cli`\|`http`\|`mcp`\|`telegram`\|`timeout`\|`tack`, or `unknown` for an entry that names none) and outcome (`granted`\|`denied`). `channel="timeout"` is the fail-closed expiry path, never a human channel, and only ever pairs with `outcome="denied"`. `channel="tack"` is a decision made from Tack's board. Subject to the rotation caveat below. |
| `docket_turn_duration_seconds` | summary (`_sum`/`_count`, no quantiles) | Session wall-clock (`session_start` → `session_end`), fleet-wide, one sample per trace file that has both. `_sum`/`_count` gives the mean; no percentiles are invented. |
| `docket_tasks_started_total` | counter | Dispatch task claims, counted from dispatch-sourced `session_start` trace events; a resumed task's second `session_start` (`"resumed": true`) is not counted. Trace-derived. |
| `docket_questions_total{kind,outcome}` | counter | Operator questions by kind and outcome. An answered question counts under its task's `question.kind` (default `clarification`) and the answer's action (`accept`\|`decline`\|`cancel`); approvals count under `kind="approval"` with outcome `granted`\|`denied` (from the audit log's `approval.grant`/`approval.deny` entries) or `pending` (the pending approvals). |
| `docket_decision_latency_seconds` | summary (`_sum`/`_count`, no quantiles) | Seconds from a task's `question.createdAt` to an answer's `answeredAt`, answered questions only, negative intervals skipped. |

Additional metrics may be added in minor versions. Every metric is computed fresh, on every
scrape, from durable state already on disk (trace JSONL under `traces/`, `audit.log`, the task
lists, the approval records), never from a second in-process counter store, so a `docket start`
restart loses nothing and every number traces back to a record `docket task trace` or
`docket log` can also show. The metrics only *read* those stores; they never write through them.

**Durability caveat — every counter here is a lifetime-of-current-storage count, NOT a monotonic
total.** The sources lose history, for different reasons:

1. **Audit-derived** — `docket_approvals_total`, the `pre_tool_call` slice of
   `docket_policy_hits_total` and the approval part of `docket_questions_total` — see only
   `audit.log`'s *current* generation. The audit log rotates to a single-generation backup
   (`audit.log.1`, itself overwritten by the next rotation) once it exceeds
   `AUDIT_LOG_MAX_BYTES` (5MB by default), and only the current file is read, so a rotation
   drops whatever history was in the backup.
2. **Trace-derived** — the rest of the trace-sourced counters — drop when trace retention
   (`expire_old_traces`, run by `docket task prune` and by `start`'s periodic sweep) deletes
   *terminated* traces past `TRACE_RETENTION_S`.
3. **Task-derived** — the answer part of `docket_questions_total` and
   `docket_decision_latency_seconds` — drop when task records are pruned.

A Prometheus `rate()` reading a counter that drops to a **smaller-but-nonzero** value misreads
that as a reset followed by real (under-counted) traffic, not as missing history. **Consumers
MUST NOT build alerting that assumes these counters are monotonic.**

Retention is measured from when a session *ended*, not from when it was last active: a trace
with no `session_end` is never expired by age, and the sweep's synthetic `session_end` carries a
fresh timestamp, so an abandoned session's trace survives a full window after the sweep first
terminates it.

**Scrape cost.** Every `/metrics` request re-parses every trace JSONL file plus the whole current
audit log; there is no cache. The cost is `O(total trace + audit bytes)` per scrape, on a server
thread shared with `/health`.

### GET /health

Liveness check. Always returns HTTP 200 while the process is alive.

```json
{"status":"ok","apiVersion":"6","dispatch":{"on":false,"inflight":[],"stopping":false,"workers":4}}
```

`apiVersion` is `SERVE_API_VERSION`. `dispatch.on` is whether the server runs with `--dispatch`,
`inflight` the pods with a sweep running, `stopping` whether the first stop signal has arrived and
`workers` the sweep pool size (`DISPATCH_SWEEP_WORKERS`). Liveness is the HTTP 200 and
`status="ok"`.

With dispatch on, a `POST /tasks/<pod>` that creates a task that is not gated on approval starts
that pod's sweep at once instead of waiting for the next refresh; it is a no-op while a sweep of
that pod is in flight.

### GET /approvals

Requires `Authorization: Bearer <token>`. Returns every pending approval record, in record
filename order; a record that fails to parse is skipped.

```json
{
  "pending": [
    {"token": "apr-3f2a...", "project": "myapp", "role": "lead", "action": "...",
     "state": "pending", "created": "...", "context": {"taskId": "task-91a2..."}}
  ]
}
```

Each element is the approval record as stored under `approvals/` in `DOCKET_HOME`.

### GET /runs

Requires `Authorization: Bearer <token>`. Returns every persisted dispatch-run record (one per
invocation of the pod pipeline: the CLI, the webhook, a due schedule, the sweep loop, or the MCP
`dispatch` tool), newest first by `created`. An optional `?project=<name>` query parameter
filters to one pod.

```json
{
  "runs": [
    {
      "id":         "run-3f2a1c9e-...",
      "source":     "cli | webhook | schedule | sweep | mcp",
      "project":    "myapp",
      "state":      "queued | running | waiting_input | waiting_approval | succeeded | failed | cancelled",
      "taskIds":    ["task-91a2..."],
      "error":      "",
      "created":    "2026-07-30T02:10:00.123456+00:00",
      "startedAt":  "2026-07-30T02:10:00.200000+00:00",
      "finishedAt": "2026-07-30T02:10:04.500000+00:00",
      "pids":       [],
      "variables":  {"env": "staging"},
      "cancellation": {
        "requestedAt": "2026-07-30T02:10:02.000000+00:00",
        "observedAt":  "2026-07-30T02:10:04.400000+00:00",
        "stoppedAt":   "2026-07-30T02:10:04.500000+00:00",
        "reason":      "operator request",
        "source":      "cli"
      }
    }
  ]
}
```

`variables` is the pipeline variable namespace this run was resolved against: `{}` for every
source except `webhook` (see `POST /dispatch/<project>` below). `pids` are the process groups of
any hop in flight for the run. `cancelled` is a run `docket task cancel <id>` (or the server's
second stop signal) stopped.

`cancellation` is the persisted cross-process cancellation signal. Its nullable `requestedAt`,
`observedAt`, and `stoppedAt` timestamps distinguish an operator request from execution observing
that request and from execution fully stopping. `reason` and `source` are bounded, non-secret
context; the lifecycle does not persist a redundant derived phase. Every run record is created
with a `cancellation` object whose timestamps are all `null` (no request); a record whose
`cancellation` is missing or not an object is malformed and fails closed like any other malformed
lifecycle (see Validation). A queued request writes all three timestamps and terminal `cancelled`
(with `error` `"cancelled by operator"`) in one atomic transition because no body started. A
running request writes `requestedAt` once and remains nonterminal until its owning `execute` call
observes and stops; observation and stop are monotonic and idempotent.

The terminal state reflects the returned dispatch result, not merely whether the dispatcher
raised. After one ordered fold over the returned result list: any item whose `status` is
`cancelled` makes the run `cancelled` (`error` `"cancelled by operator"`); otherwise any item whose
`status` is `failed` makes the run `failed`; otherwise any item whose `status` is `waiting_input`
or `waiting_approval` makes the run that state (the first parked item's); otherwise the run is
`succeeded`, which covers an empty list and a list of only `done` and/or `blocked` items.
`taskIds` preserves every returned task id in result order in every case. A returned-task failure
writes a deterministic, actionable `error` summary of at most 1024 characters, derived only from
failing task ids and their `reason` fields; it MUST NOT serialize the raw result, hop artifacts,
model output, or tool output. The summary names the total failure count, details at most three
failures with bounded ids and reasons, and reports how many failures were omitted. An exception
produces a `failed` run whose `error` is the exception class and message. The queued-to-running
claim and the terminal write are atomic: `execute` does not invoke dispatch for a run already
cancelled while queued, and a concurrent cancellation that wins before the terminal write remains
`cancelled` rather than being overwritten.

A second SIGINT/SIGTERM to `docket start` requests cancellation of every in-flight sweep run
through this same lifecycle (see pod-dispatch "Sweep workers" 4-5), recording `source: "serve"`
(a cancel from `docket task cancel` records `"cli"`): `requestedAt` is persisted
at once, and the run reaches `cancelled` only when its body observes the request.

### GET /runs/&lt;id&gt;

Requires `Authorization: Bearer <token>`. Returns one run record (the same shape as one element of
`/runs`' array, unwrapped). `404` if the id is unknown.

### GET /inbox

Requires `Authorization: Bearer <token>`. Returns the derived operator inbox — everything across
every provisioned pod that needs a human, plus recent context — built by `build_inbox`. An
optional `?since=<iso>` query parameter restricts `doneSince` to tasks that completed after that
timestamp; omitted, `doneSince` lists every terminal task. The body is `InboxView` exactly,
`by_alias`; an item's `question` includes the operator-v1.1 fields (`kind`, `options`,
`recommendation`) when the task parked a consultation:

```json
{
  "needsYou": [
    {"id": "task-1", "pod": "demo", "status": "blocked", "a2aState": "INPUT_REQUIRED", "...": "..."},
    {"token": "apr-2", "pod": "demo", "role": "lead", "a2aState": "INPUT_REQUIRED", "...": "..."}
  ],
  "failed":    [ {"id": "task-3", "pod": "demo", "status": "failed", "a2aState": "FAILED"} ],
  "doneSince": [ {"id": "task-4", "pod": "demo", "status": "done", "a2aState": "COMPLETED"} ],
  "running":   [],
  "next": "2026-09-28T00:00:05+00:00"
}
```

`needsYou` mixes `TaskView` (a `waiting_*`/`blocked` task) and `ApprovalView` (a pending approval
not already carried by a task's `approvalToken`) items; a client distinguishes them by the
presence of `token` vs. `id`. Identical shape to `docket inbox --json` and `docket start --mcp`'s
`inbox` tool for the same state — one assembly function, three surfaces.

### GET /tasks/&lt;project&gt;/&lt;id&gt;/evidence

Requires `Authorization: Bearer <token>` exactly like `GET /tasks/<project>` (`401` first, then
the project-id check). Body is `task_evidence(project, id, "1.1.0")` serialized `by_alias`, the
evidence document at version 1.1.0, the same `evidence` object `docket task show <id> --json`
prints. An unknown task is `404 {"ok": false, "error": ...}`.

### GET /tasks/&lt;project&gt;

Requires `Authorization: Bearer <token>`. Returns the pod's task records as `read_tasks(project)`
normalizes them, each with a `tokenBudget` key added (the measured-token ceiling its next hop
runs under). The optional `?status=` and `?externalRef=` filters, the `400` for an unknown
`status`, and `tokenBudget` are specified by `operator-api.spec.md`. A project with no pod is
`read_tasks`' own `[]`, not an error.

```json
{
  "tasks": [
    {
      "id": "task-91a2...",
      "description": "Fix the bug",
      "priority": "normal",
      "status": "pending",
      "source": "operator",
      "channel": "http",
      "created": "2026-08-04T12:00:00Z",
      "hops": [],
      "tokenBudget": 100000
    }
  ]
}
```

The field set of a task record is the one `read_tasks` normalizes onto it (owned by
`pod-dispatch.spec.md` and `operator-api.spec.md`); this spec does not re-enumerate it.

- The project segment must be non-empty — `GET /tasks` and `GET /tasks/` both reject with `400`.
- The project segment must also pass `validate_project_id` (`input-validation.spec.md` §1) — a
  segment containing e.g. `/` or `..` rejects with `400 {"error": ...}`, checked after the auth
  check so an unauthenticated caller still gets `401` first.
- A project with a pod but an empty queue, and a project with no pod at all, both return `200` with
  `{"tasks": []}` — indistinguishable at this endpoint, matching `read_tasks`' own contract (it has
  no notion of "pod exists but is empty" vs. "no pod").

### GET /traces/&lt;project&gt;

Requires `Authorization: Bearer <token>`. Returns raw trace JSONL for one project, cursor'd by an
optional `?since=<cursor>` query parameter so a polling consumer (e.g. Tack) can resume without
re-reading everything each time. One project, one cursor, no filtering by event type, role or
session; a caller that wants a fleet-wide view aggregates client-side across calls.

```json
{
  "events": [
    "{\"ts\": \"2026-08-04T12:00:00Z\", \"project\": \"myapp\", \"session_id\": \"...\", \"agent_role\": \"lead\", \"event_type\": \"tool_call\", \"payload\": {...}}"
  ],
  "next": "2026-08-04T12:00:00Z:1"
}
```

- Each element of `events` is the **verbatim JSONL line** (a JSON string, not a re-parsed/re-keyed
  object) exactly as `export_lines` returned it — no field is added, removed or renamed. A page is
  ordered by `ts` across the project's session files (stable, so same-second lines keep their file
  order).
- **`task_id`.** A pod-dispatch hop's line may carry a `task_id` key (`trace-store.spec.md`
  requirement 19), identifying which claimed task the record belongs to. A line is delivered
  verbatim, so it flows through unchanged; a caller that does not recognize the key **MUST**
  ignore it, exactly as any other unrecognized payload field.
- A project with no trace files returns `200` with `{"events": []}` and `next` equal to the
  incoming `since` (`""` when none) — not an error.
- The project segment must be non-empty — `GET /traces` and `GET /traces/` both reject with `400`.
- The project segment must also pass `validate_project_id` (`input-validation.spec.md` §1) — an
  invalid segment rejects with `400 {"error": ...}`, checked after the auth check so an
  unauthenticated caller still gets `401` first.
- **Cursor semantics.** `export_lines`' own `since` filter is `ts >= since` — inclusive — and `ts`
  is second-granularity (`%Y-%m-%dT%H:%M:%SZ`). Several trace events sharing one timestamp is
  routine (one dispatch hop can emit several events inside the same wall-clock second), so neither
  "next cursor = last event's raw ts" (redelivers that whole second on the next poll) nor a naive
  exclusive reinterpretation of it (drops a same-second event that arrives after the poll that
  first saw that second) is correct. The `next` value is instead a compound `"<ts>:<n>"` token —
  `n` is how many lines carrying that exact `ts` have already been delivered — so a poll loop that
  always passes back the previous response's `next` as its `since` ingests every event exactly
  once, even across a same-second boundary. A bare timestamp (no `:<n>` suffix) is also accepted
  as `since`, with `n` treated as 0; a `:<n>` suffix is read as a count only when the part before
  it ends in `Z`.
- **Hold-back.** The compound cursor alone is not sufficient: `export_lines` reads a project's
  session files in *filename* order, and a brand-new file can sort earlier than one already on
  disk, so the "skip the first `n` lines at this `ts`" bookkeeping is only stable within one poll,
  not across two. A page therefore never includes a line whose `ts` is within one second of the
  current time (`ts >= now - 1s` is withheld, not dropped) — by the time any line at a given `ts`
  is handed out, that second is closed, so no later write from any session file can land at that
  `ts` again and invalidate an already-minted cursor. A withheld line is delivered, in full, on a
  later poll once it has aged past the hold-back window; the cursor is left unadvanced past it in
  the meantime, and a poll that returns nothing because everything new is still within the
  hold-back window returns its unchanged incoming cursor as `next`.
- A line that is not valid JSON has no `ts` to key on: whenever a `since` filter is active it is
  always re-included, regardless of cursor value, and the cursor anchors on the last line that has
  a `ts` (never on `""`, which would replay the whole project). A valid JSON line with no `ts` is
  dropped by any `since` filter. Neither occurs under normal operation, since `trace_event` always
  writes a valid `ts`.

### POST /dispatch/&lt;project&gt;

Requires `Authorization: Bearer <token>`. Creates a run record (source `webhook`) *before*
returning, writes one `run.dispatch` audit entry, and answers `200` with the run id:

```json
{"ok": true, "run": "run-3f2a1c9e-...", "project": "myapp", "status": "dispatched"}
```

The dispatch pipeline itself runs asynchronously (this endpoint does not block on a real agent
turn) — poll `GET /runs/<id>` (or `docket task show <id>`) for the outcome.

**Request body.** The request body — a plain `{name: value}` JSON object, `{}` if omitted — is the
webhook's params, resolved against the pod's *effective* pipeline's declared `variables`
(`resolve_variables`; see `pipeline-format.spec.md`) before the run record is created:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"env": "staging"}' http://127.0.0.1:7331/dispatch/myapp
```

- The project segment must be non-empty and must pass `validate_project_id`
  (`input-validation.spec.md` §1); either failure rejects with `400 {"error": ...}`, checked after
  the auth check and before the request body is read.
- A body that is not a JSON object (malformed JSON, or valid JSON that isn't an object) is
  rejected with `400` before any pipeline is resolved.
- A pod whose effective pipeline cannot be resolved (`DispatchError` from the pod's settings or its
  bound pipeline: copy missing, unreadable or hash-mismatched) is answered like
  `POST /tasks/<project>`: `404` when there is no pod for the project, otherwise
  `400 {"error": <the error text>}`; no run record is created and the connection is never dropped.
- A missing `required` pipeline variable (one absent from the body; a required variable never has
  a default) is rejected with `400` naming every missing variable, and — like the auth and
  malformed-project rejections above it — **no run record is created** for a rejected request.
- On success, the resolved namespace (payload values winning over any declared default; a key the
  pipeline never declared passes through unchanged) is persisted on the created run record's
  `variables` field (see `GET /runs` above).
- The effective pipeline resolved here is always the pod's own configured/default one (whatever
  `docket run` would use without `--pipeline`) — the webhook cannot supply a pipeline file of its
  own; only its *variable values* are payload-driven.

### POST /tasks/&lt;project&gt;

Requires `Authorization: Bearer <token>`. Enqueues one task onto the pod's queue — the HTTP
counterpart of `docket task add` and the MCP `delegate` tool. It calls the same enqueue path those
callers use, so the `pre_input` guardrail gate, priority normalization and persisted task shape
are identical to the CLI path; the task's `channel` is `http` and a `task.enqueue` audit entry is
written.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"description": "Fix the flaky test", "priority": "high"}' \
  http://127.0.0.1:7331/tasks/myapp
```

Request body (the addressable-task fields `externalRef`, `idempotencyKey`, `baseRef`,
`pipeline`, `gate`, `maxTokens`, `prepare` and `restrictions` are specified by
`operator-api.spec.md`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `description` | string | Yes | `400` if absent, empty or not a string. |
| `priority` | `"high"\|"normal"\|"low"` | No | Defaults to `"normal"`; an unrecognized value falls back to `"normal"` — the same normalization the CLI/MCP callers get. |
| `trusted` | boolean | No | Overrides the `pre_input` policy check's trust flag for this one enqueue. Omitted, it keeps the CLI/MCP default (trusted, because the task's `source` is `operator`). It does **not** change the persisted task's `source` field or introduce a new trust/source vocabulary — the only thing it touches is which `pre_input` policies are eligible to fire (whether the `prompt-injection` policy id is skipped). |
| `brief` | object | No | A `TaskBrief` document (operator-v1, `operator-loop.spec.md`), the HTTP counterpart of `docket task add --brief`. A non-object value is `400`; an invalid one is `422` before anything is enqueued. A valid one is appended to the task description as a `## Pre-brief` section and persisted on the task's `brief` field. |

Success response: a new task answers `201` with `"created": true`; a repeated `idempotencyKey`
that matches a queued task answers `200` with `"created": false` and that task:

```json
{"ok": true, "created": true, "task": "task-91a2...", "project": "myapp", "status": "pending"}
```

- The project segment must be non-empty and must pass `validate_project_id`
  (`input-validation.spec.md` §1); either failure rejects with `400 {"error": ...}`, checked after
  the auth check and before the request body is read.
- A malformed JSON body, or a body that is valid JSON but not an object, is rejected with `400`
  before anything is enqueued.
- A project with no pod (`docket init` never run for it) is rejected with `404`, naming the
  project — a real "nothing to enqueue against" condition, not a server error.
- A `pre_input` guardrail policy matching the description with a `block` verdict is rejected with
  `400` naming the policy id (the same message `docket task add` prints); a wrongly shaped
  addressable field is also `400`, and a refused `restrictions` document is `422`. Nothing is
  persisted in any of these cases.
- A `pre_input` policy matching with a `require_approval` verdict is **not** an error: the task is
  created (visible on `GET /tasks/<project>`, `docket task list`, etc.) but gated, so the response
  is `201` reporting the real state and the approval token instead of one that implies the task
  is queued to run:

  ```json
  {
    "ok": true,
    "created": true,
    "task": "task-91a2...",
    "project": "myapp",
    "status": "waiting_approval",
    "approvalToken": "apr-3f2a1c9e-..."
  }
  ```

  `approvalToken` resolves through the same `POST /approvals/<token>` endpoint documented below —
  granting it resumes the task, denying it fails the task terminally, exactly like any other
  approval-gated task.

### POST /tasks/&lt;id&gt;/answer

Requires `Authorization: Bearer <token>`. Resolves one task's parked `input` question — the HTTP
counterpart of `docket task answer` and the MCP `task_answer` tool. It calls the same
`answer_task` those two callers use, so the schema/`pre_input` screen and the resume onto the
step's own route are identical; this route adds no new semantics (`operator-loop.spec.md`,
"Answer surfaces").

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"pod": "myapp", "action": "accept", "content": {"answer": "ship it"}}' \
  http://127.0.0.1:7331/tasks/task-91a2.../answer
```

Request body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `pod` | string | Yes | The project the task belongs to (task ids are not globally unique across pods). `400` if absent, empty, or fails `validate_project_id`. |
| `action` | string | Yes | `"accept"`, `"decline"` or `"cancel"` (the MCP elicitation result vocabulary). `400` if absent or empty; an unrecognized value is `422` from `answer_task`'s own validation. |
| `content` | object | No | Required properties for `"accept"` (validated against the parked question's `requestedSchema`); ignored for `"decline"`/`"cancel"`. `400` if present but not an object. |
| `actor` | string | No | A label only — the Bearer token remains the sole authority over who may answer. Defaults to `"http"`. The channel recorded on the answer and its audit entry is always `"http"`, regardless of `actor`. |

Success response (`200`) — the answered task's `TaskView` (operator-v1, `by_alias`, `mode="json"`):

```json
{
  "id": "task-91a2...",
  "pod": "myapp",
  "status": "pending",
  "a2aState": "SUBMITTED",
  "description": "needs a decision",
  "priority": "normal",
  "createdAt": "...",
  "updatedAt": "..."
}
```

- A missing task id, a malformed JSON body, a body that is valid JSON but not an object, a
  missing/empty `pod` or `action`, or a non-object `content` is rejected with `400` before
  `answer_task` is called.
- An answer whose `content` matches a `pre_input` `block` policy is `422`, naming the policy id
  in the error message — nothing is written.
- An answer naming an unknown task (`"not found in pod"`) is `404`; one naming a task not
  currently `waiting_input`, or parked at a different step than the answer targets
  (`"is not waiting_input"` / `"is not parked at step"`), is `409`; any other answer error — a
  schema-validation failure, relayed unchanged — is `422`.

### POST /tasks/&lt;id&gt;/pregrants

Requires `Authorization: Bearer <token>`. Records a single-use pre-grant for one exact command on
one task, ahead of dispatch — the HTTP counterpart of `docket task approve --for` and the MCP
`task_pregrant` tool. It calls `record_pregrant`, which mints the approval exactly as an in-turn
park does and appends the grant to the task's own `pregrants` list. When the pipeline later
reaches that exact call (matched by its canonical arguments digest), it passes once without
asking again (`operator-loop.spec.md`, "Interruption forecast and pre-grants").

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"pod": "myapp", "command": "git push origin main"}' \
  http://127.0.0.1:7331/tasks/task-91a2.../pregrants
```

Request body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `pod` | string | Yes | The project the task belongs to. `400` if absent, empty, or fails `validate_project_id`. |
| `command` | string | Yes | The exact command line to pre-approve. `400` if absent, empty, or whitespace-only. |
| `tool` | string | No | The tool name the pre-grant is keyed under. Defaults to `"bash"`. |
| `actor` | string | No | A label only — the Bearer token remains the sole authority. Defaults to `"http"`. The channel recorded on the pre-grant and its audit entry is always `"http"`, regardless of `actor`. |

Success response (`200`):

```json
{"ok": true, "token": "apr-...", "task": "task-91a2...", "pod": "myapp"}
```

- A missing task id, a malformed JSON body, a body that is valid JSON but not an object, or a
  missing/empty `pod`/`command`, is rejected with `400` before `record_pregrant` is called.
- A task that is not in that pod's own queue is `404`.

### POST /pods

Requires `Authorization: Bearer <token>`. Provisions a fresh pod from a blueprint — the HTTP
counterpart of `docket init`. `provision_pod` holds the provisioning decisions and effects with no
terminal output; `docket init`'s default and `--from` pod paths call the same function, so this
route and the CLI cannot drift apart.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "myapp", "location": "/srv/repos/myapp", "blueprint": "software"}' \
  http://127.0.0.1:7331/pods
```

Request body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | The pod id (`docket init`'s project id, not a display name — a blueprint pod has no separate display-name field). `400` if absent, empty, not a string, or fails `validate_project_id` (`input-validation.spec.md` §1). |
| `location` | string | No | The blueprint's `codebase` (a `codebase`-kind blueprint, e.g. `software`) or `workDir` (a `workdir`-kind blueprint, e.g. `research`/`content`/`ops`) — `provision_pod` picks which one it means from the blueprint's own workspace kind. Defaults to `""`: a `workdir`-kind blueprint then auto-provisions `workspaces/pods/<name>/workdir` under `DOCKET_HOME`, exactly as `docket init` with no path does. A non-string is `400`. |
| `blueprint` | string | No | A blueprint registry name. Defaults to `"software"` (`DEFAULT_BLUEPRINT`, `docket init`'s own default). An empty or non-string value is `400`; an unknown name is `400` naming the invalid blueprint. |
| `pod` | `"full"` | No | Mirrors `docket init --pod full` (case-insensitive) — the CLI's roster override, itself restricted to the `software` blueprint (a non-`software` blueprint provisions its own fixed roster; `pod` is ignored for one, as the CLI warns and ignores rather than erroring). Any other value is `400`. |
| `budget` | number \| numeric string | No | Overrides the blueprint's own default budget cap (applied to the Lead member only). `0`, omitted, or a non-positive value means no override (falls back to the blueprint default). A boolean or non-numeric value is `400`. |
| `verifyCmd` | string | No | Applied to Implementer member(s) only, at creation time — the same verify command `docket pod add --verify` and `docket pod set verify --member` set after creation. Validated the same way (no NUL byte, no newline, length-capped); a non-string or failing value is `400`. |
| `ensure` | boolean | No | Default `false`. On an existing pod the request **MUST** answer `200` `{"ok": true, "created": false, "project": p}` and change nothing; without `ensure` an existing pod is `409`. A non-boolean is `400`. |

Success response (`201`) — the created pod roster:

```json
{
  "ok": true,
  "created": true,
  "project": "myapp",
  "blueprint": "software",
  "members": [
    {"id": "myapp-lead", "role": "lead", "model": "anthropic/claude-haiku-4-5-20251001"},
    {"id": "myapp-implementer", "role": "implementer", "model": "anthropic/claude-sonnet-4-6"}
  ]
}
```

- A malformed JSON body, or a body that is valid JSON but not an object, is rejected with `400`
  before `provision_pod` is called.
- A missing or empty `name` is `400` (`name is required`).
- A `name` that fails `validate_project_id` — e.g. contains `/` or `..` — is rejected with `400`
  (the validator's own message), checked inside `provision_pod` as its first statement, before the
  per-project lock and before any workspace path is built.
- A `name` that already has a registered pod member is rejected with `409` (unless `ensure`) —
  matching `docket init --from`'s own idempotence (an existing pod is skipped): the existing pod is
  left untouched, not re-provisioned or clobbered. Concurrent requests for one project are
  serialized from that check through commit or rollback, so a losing request cannot remove the
  successful request's members, runtime directory, scratch directory, or port allocation.
- **A partial failure leaves nothing behind.** If any member after the first fails to provision,
  every member `provision_pod` already created during that one call — its workspace directory and
  its fleet registration — is torn down, and only pod-level resources (port range, scratch dir,
  and an auto-provisioned workdir) created by that attempt are freed; pre-existing pod runtime
  contents are preserved, before the request fails. Port allocation itself is one shared locked
  registry transition, so concurrently successful *different* projects receive disjoint
  deterministic ranges without taking each other's project lock. The consumer (Tack) rolls back
  its own project record on a non-2xx response and has no way to roll back a half-created pod on
  docket's side. Such a failure is reported as `500` — the request itself was well-formed; the
  failure is an operational one (e.g. a filesystem error), not a validation error.
- This route adds no field `docket init` does not already have a corresponding capability for —
  see the request-body table above for which CLI capability each field reuses.

### POST /approvals/&lt;token&gt;

Requires `Authorization: Bearer <token>`. Resolves one approval — the HTTP counterpart of
`docket task approve`/`deny`. If the token gates a pod task, the task is resumed (grant) or
failed (deny) in the same request.

Request body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `action` | `"grant"\|"deny"` | Yes | Anything else is `400`. |
| `channel` | `"http"\|"tack"` | No | Defaults to `"http"`. Tagged onto the `approval.grant`/`approval.deny` audit entry. |
| `option` | `"approve_once"\|"approve_task"` | No | Grant only. |
| `reason` | string | No | Recorded with the decision; a non-string is ignored. |

Success response (`200`): `{"ok": true, "token": <token>, "state": <resulting state>}`, plus a
`note` when the grant was recorded but its task-wide grant was refused.

`channel` is validated against `http`\|`tack` — the subset of `APPROVAL_CHANNELS` the HTTP
transport itself may claim — rather than the full closed vocabulary: `cli`, `mcp` and `telegram`
are audit-logged only by their own surfaces (the CLI, an MCP tool call, the Telegram channel), and
`timeout` is the fail-closed expiry path, never a caller-supplied value. An HTTP Bearer holder
asking for any of those, or any other unrecognized value, is rejected with `400` before the
approval's state changes, so a caller cannot forge which surface a decision came through in the
hash-chained audit log. `tack` distinguishes a decision made from Tack's board from one made
through any other surface.

## Validation

- `apiVersion` MUST be a string equal to `SERVE_API_VERSION`.
- `agents[*].scope` MUST be `"project"`; `agents[*].kind` MUST be `"project"`.
- `agents[*].budgetUsd` MUST be a float or `null`.
- `agents[*].lastActivity` MUST be an ISO date string (`YYYY-MM-DD`) or `"never"`.
- `/metrics` MUST conform to Prometheus text format 0.0.4: each metric family appears once, its
  `# HELP` then `# TYPE` line before its first sample, and all of its samples together, with
  every agent's `docket_agent_turns_total` sample under that one header.
- `/approvals`, `/runs` and `/runs/<id>` MUST reject a request with no (or an invalid) Bearer
  token with `401`, before touching the approval records or the run registry.
- `/inbox` MUST reject a request with no (or an invalid) Bearer token with `401` before building
  the inbox, and MUST return the byte-identical shape `docket inbox --json` prints for the same
  pod/approval state (`operator-loop.spec.md` requirement area 5).
- `GET /tasks/<project>`, `GET /tasks/<project>/<id>/evidence`, `GET /traces/<project>`,
  `POST /tasks/<project>` and `POST /dispatch/<project>` MUST reject a request with no (or an
  invalid) Bearer token with `401`, and MUST reject an empty project segment or one that fails
  `validate_project_id` with `400`, before touching any project state.
- `/traces/<project>`'s `next` cursor MUST be safe to feed back as the next request's `since`
  without either re-delivering an event already returned or skipping one written after the
  previous response — including when several events share one `ts` (see the cursor semantics
  paragraph above).
- A run record's `state` MUST be one of `queued | running | waiting_input | waiting_approval | succeeded | failed | cancelled`;
  `source` MUST be one of `cli | webhook | schedule | sweep | mcp` (`mcp` is `docket start --mcp`'s
  `dispatch` tool).
- A cancellation request and a competing terminal transition MUST choose one winner in one
  conditional registry read-modify-write. A queued winner is immediately `cancelled`; a running
  winner remains `running` with only `cancellation.requestedAt` populated until `execute` records
  observation and stop. Repeated requests MUST NOT re-signal or re-audit. Records in any terminal
  state (`succeeded`, `failed`, `cancelled`, `waiting_input`, `waiting_approval`) are stable
  no-ops. Malformed cancellation lifecycle data MUST fail closed without fabricating `observedAt`,
  `stoppedAt`, or a terminal state, and unrelated run fields MUST survive every lifecycle
  transition.
- A normally returned dispatch result MUST make the run `cancelled` if any returned task has
  `status="cancelled"`, else `failed` if any has `status="failed"` (writing the bounded safe
  summary described under `GET /runs`), else `waiting_input`/`waiting_approval` if any task
  parked, else `succeeded`; it MUST preserve every returned task id in order. `done` and `blocked`
  MUST NOT fail the run, and a concurrent `cancelled` state MUST win.
- `POST /dispatch/<project>`'s response MUST carry a `run` id matching a record retrievable via
  `GET /runs/<id>` immediately after the response is sent (the record exists before the HTTP
  response is written, even though the dispatch itself is still in flight).
- `POST /tasks/<project>` MUST reject a request with no (or an invalid) Bearer token with `401`
  before touching the pod's queue; MUST reject an absent/empty `description` and a malformed or
  non-object body with `400` before enqueueing; MUST return `404` (not `500`) for a project with
  no pod; MUST return `400` naming the policy id for a `block` `pre_input` verdict; and MUST return
  `201` with `status: "waiting_approval"` plus a non-empty `approvalToken` for a
  `require_approval` verdict, never a response implying the task is queued to run.
- `POST /approvals/<token>` MUST return `401` before touching the record for a missing/invalid
  Bearer token; `400` for a missing token, a malformed body or an `action` other than
  `grant`/`deny`; `200` with the resulting `state` on a successful transition; `404` for a token
  that does not exist; and `409` for a token that already resolved — whether to the *same* action
  or the *opposite* one (deny-after-grant or grant-after-deny) — naming the winning state in the
  error message either way, never the missing-token `404` (`security-gates.spec.md`'s
  approval-resolution section).
- `POST /approvals/<token>`'s optional `channel` field MUST be one of `http | tack` — the subset of
  `APPROVAL_CHANNELS` the HTTP transport may claim; `cli`, `mcp`, `telegram` and `timeout` belong
  to other surfaces or to the fail-closed expiry path and MUST be rejected the same as any other
  unrecognized value, with `400` and no change to the approval's state or the audit log. Omitted,
  it MUST default to `"http"`.
- `POST /approvals/<token>`'s optional `option` field MUST be `approve_once` or `approve_task`, and
  only with `"action": "grant"`; any other value, or an option on a deny, MUST be rejected with
  `400` and no change. `approve_task` is recorded with `approval_set_option` before the grant, so a
  parked pod task gains the task-wide grant of operator-loop 5a (channel `http`); a refused grant
  past the task's cap of 20 adds a `note` to the `200` body.
- `POST /pods` MUST reject a request with no (or an invalid) Bearer token with `401` before touching
  any project state; MUST reject a malformed/non-object body, a missing/empty `name`, a `pod`
  value other than `"full"`, a non-numeric `budget`, or a wrongly typed `blueprint`, `location`,
  `verifyCmd` or `ensure` with `400` before `provision_pod` is called, and a `name` failing
  `validate_project_id`, an unknown `blueprint`, or an invalid `verifyCmd` with `400` from
  `provision_pod`'s own validation (id check first, before its exists-check, before any side
  effect); MUST reject an already-provisioned `name` with `409` without touching the existing pod,
  unless the body carries `"ensure": true`, which answers `200` with `"created": false` and touches
  nothing; and on a genuine mid-provisioning failure MUST leave no member workspace, no fleet
  registration and no orphaned port/scratch allocation created by that request behind (full
  rollback) before responding `500`; concurrent same-project attempts MUST leave the successful
  attempt's members, metadata, allocation, and runtime directory untouched. Concurrent successful
  different-project requests MUST retain distinct port ranges. `docket init`'s pod-provisioning
  path (default and `--from`) and this route MUST call the same `provision_pod` function — there
  is no second provisioning implementation.
- Any change that breaks the contract tests listed under Implementation is a breaking API change
  and MUST bump `apiVersion`.

## Examples

### Status endpoint (curl)

```bash
curl -s http://127.0.0.1:7331/status.json | jq .
```

### Metrics endpoint (curl)

```bash
curl -s http://127.0.0.1:7331/metrics
# docket_agents_total 3
# docket_cost_usd_total 0
```

### Health check

```bash
curl -s http://127.0.0.1:7331/health
# {"status":"ok","apiVersion":"6","dispatch":{"on":false,"inflight":[],"stopping":false,"workers":4}}
```

### Trigger a dispatch and poll its run (curl)

```bash
TOKEN=... # printed at `docket start` startup, or $DOCKET_SERVE_TOKEN

run_id=$(curl -s -H "Authorization: Bearer $TOKEN" -X POST \
  http://127.0.0.1:7331/dispatch/myapp | jq -r .run)

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7331/runs/$run_id | jq .
```

### List runs for one project (curl)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:7331/runs?project=myapp" | jq .
```

## Implementation

- `src/docket/serve.py`: `SERVE_API_VERSION`, `build_status`, `render_metrics`, `render_health`,
  `LoopMetrics`, the request handler (every route above, the Bearer check, the body cap
  `MAX_POST_BODY_BYTES`, the `/traces` cursor and hold-back), the sweep pool started by
  `POST /tasks` under dispatch, `run_serve`
- `src/docket/kernel/threads.py`: `ContextHTTPServer`, `new_thread`, `start_thread`, `submit`
- `src/docket/core/escalation.py`: `count_escalation_metrics` (`docket_tasks_started_total`,
  `docket_questions_total`, `docket_decision_latency_seconds`)
- `src/docket/core/inbox.py`: `build_inbox`, `task_view`
- `src/docket/core/operator_contract.py`: `InboxView`, `TaskView`, `ApprovalView`, `TaskBrief`
- `src/docket/core/runs.py`: `create_run`, `list_runs`, `get_run`, `execute`, `cancel_run`, the
  run record and its `cancellation` lifecycle
- `src/docket/core/dispatch.py`: `read_tasks` (task-record normalization, `_TASK_SCALAR_DEFAULTS`),
  `enqueue_task_once`, `effective_pipeline`, `dispatch_pod`, `resolve_waiting_approval_detail`,
  `TASK_GRANT_CAP`
- `src/docket/core/evidence.py`: `task_evidence`
- `src/docket/core/trace.py`: `export_lines`, `trace_event`, `expire_old_traces`, `sweep_all`
- `src/docket/core/audit.py`: `read_audit`, rotation at `AUDIT_LOG_MAX_BYTES`
- `src/docket/core/approval.py`: `APPROVAL_CHANNELS`, `list_pending`, `approval_grant`,
  `approval_deny`, `approval_set_option`
- `src/docket/core/answers.py`: `answer_task`
- `src/docket/core/interruptions.py`: `record_pregrant`
- `src/docket/core/pipeline.py`: `resolve_variables`
- `src/docket/core/provisioning.py`: `validate_project_id`
- `src/docket/core/pod_provisioning.py`: `provision_pod`, `validate_verify_cmd`
- `src/docket/core/blueprints.py`: `DEFAULT_BLUEPRINT`, the blueprint registry
- `src/docket/config.py`: `DISPATCH_SWEEP_WORKERS`, `TRACE_RETENTION_S`, `pod_work_dir`
- Contract tests: `tests/unit/test_serve__read_api.py` (class `TestApiContract`),
  `tests/unit/test_serve.py`, `tests/unit/test_serve__traces_cursor.py`,
  `tests/unit/test_serve__contract_gaps.py`, `tests/unit/core/test_dispatch.py`,
  `tests/unit/core/test_runs.py`, `tests/unit/core/test_approval.py` (class
  `TestApprovalChannel`), `tests/integration/test_serve_pods_endpoint.py`,
  `tests/integration/test_serve_tasks_endpoint.py`
