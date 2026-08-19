# serve read API — contract spec

**Version**: 2.6.0
**Status**: Stable
**Last Updated**: 2026-08-19

## Purpose

This specification defines the read API exposed by `docket serve` — a lightweight HTTP server
that gives dashboards, CI pipelines, and external tools a stable, versioned window into fleet
state. Three endpoints (`/status.json`, `/metrics`, `/health`) are read-only and unauthenticated;
a second tier (`/approvals`, `/runs`) is also read-only but requires the same Bearer token as the
write endpoints, since it exposes per-agent/per-dispatch detail an unauthenticated caller
shouldn't see. All mutation flows through the CLI (`docket approve/deny`, `docket pod <p>
dispatch`, etc.) or these same token-guarded write endpoints.

## Scope

This specification covers:

- The three stable, unauthenticated read endpoints (`/status.json`, `/metrics`, `/health`)
- The authenticated read-registry endpoints added in R-3 (`/runs`, `/runs/<id>`) and their
  relationship to `POST /dispatch/<project>`
- The Phase 22 authenticated read endpoints (`GET /tasks/<project>`, `GET /traces/<project>`)
- `POST /pods` (Phase 22, P22-5) — provisioning a fresh pod over HTTP
- The JSON schema for each response
- The Prometheus metric names and semantics
- The versioning policy (what constitutes a breaking change)
- The security model (auth requirements per endpoint)

It does NOT cover the write endpoints' request handling (`POST /approvals/<token>`,
`POST /dispatch/<project>`, `POST /tasks/<project>`, `POST /pods`) beyond the shape of their
request/response body — those are implementation details gated by `Authorization: Bearer <token>`
and documented in `src/docket/serve.py`.

**API version:** `2`  (see `SERVE_API_VERSION` in `src/docket/serve.py`)
The server binds to `127.0.0.1` by default. The read endpoints (`/status.json`, `/metrics`,
`/health`) require no auth. `/approvals`, `/runs`, `/runs/<id>`, and the write endpoints all
require `Authorization: Bearer <token>`.

## Structure

The server exposes three stable, unauthenticated read endpoints:

| Endpoint | Content-Type | Auth required |
|---|---|---|
| `GET /status.json` | `application/json` | No |
| `GET /metrics` | `text/plain; version=0.0.4` | No |
| `GET /health` | `application/json` | No |

...and an authenticated read-registry tier (R-3 / D-17), one dispatch-run record per invocation
of the pod pipeline — the CLI, the serve webhook, a due schedule, or the sweep loop:

| Endpoint | Content-Type | Auth required |
|---|---|---|
| `GET /runs` | `application/json` | Yes |
| `GET /runs/<id>` | `application/json` | Yes |

...and two more authenticated read endpoints (Phase 22, P22-2/P22-3) — each exposes exactly what a
`core/` function already returns, no new behaviour:

| Endpoint | Content-Type | Auth required |
|---|---|---|
| `GET /tasks/<project>` | `application/json` | Yes |
| `GET /traces/<project>` | `application/json` | Yes |

All responses are served from `127.0.0.1` (localhost only). Responses include
`Cache-Control: no-store` — consumers must not cache.

## Schema

### GET /status.json

Full fleet snapshot. Keys are **stable**; additional keys may be added in minor versions.

```json
{
  "apiVersion": "2",
  "timestamp":  "2026-06-25T10:00:00Z",
  "gateway":    "active | inactive",
  "channels":   ["telegram"],
  "agents": [
    {
      "id":           "myapp-lead",
      "name":         "My App Lead",
      "kind":         "project | specialist",
      "scope":        "project | org",
      "model":        "anthropic/claude-haiku-4-5-20251001",
      "registered":   true,
      "bindings":     [{"channel": "telegram", "peerId": "-100123"}],
      "lastActivity": "2026-06-25 | never",
      "costUsd":      0.012345,
      "budgetUsd":    10.0
    }
  ],
  "totalCostUsd": 0.012345
}
```

**Field notes**

| Field | Type | Notes |
|---|---|---|
| `apiVersion` | string | Always matches `SERVE_API_VERSION` in `src/docket/serve.py` — currently `"2"`. |
| `gateway` | `"active" \| "inactive"` | Compatibility field. Docket owns its runtime, so the shipped `gateway_active()` stub returns `False` and this is always `"inactive"`. |
| `channels` | string[] | Distinct channel names present in Docket's `fleet.json` bindings (e.g. `["telegram"]`). |
| `agents[*].scope` | `"project" \| "org"` | `project` for pod agents, `org` for shared specialists. |
| `agents[*].budgetUsd` | float \| null | `null` when no budget cap is set for the agent. |
| `agents[*].lastActivity` | date string \| `"never"` | Date of the newest memory log file, or `"never"`. |
| `totalCostUsd` | float | Sum of all agents' usage-derived cost estimates. |

### GET /metrics

Prometheus text format (content-type `text/plain; version=0.0.4`).

**Metric names (stable)**

| Metric | Type | Description |
|---|---|---|
| `docket_agents_total` | gauge | Number of project agents. |
| `docket_agent_cost_usd{agent,model}` | gauge | Cumulative cost per agent (USD). |
| `docket_agent_turns_total{agent}` | gauge | Total turns per agent. |
| `docket_cost_usd_total` | gauge | Total cost across all agents (USD). |
| `docket_gateway_up` | gauge | `1` = gateway active, `0` = inactive. |
| `docket_approvals_pending_total` | gauge | Pending approvals awaiting a human decision. |
| `docket_tool_calls_total{decision}` | counter | Tool calls dispatched through the gated tool registry (`core/tools.py`'s `dispatch_tool`), by gate decision (`allow`\|`ask`\|`deny`). Sum gives tool-call rate; the `deny` bucket over the sum gives denial rate. Sourced entirely from trace JSONL (see the durability note below). |
| `docket_policy_hits_total{policy_id,hook,action}` | counter | Guardrail policy hits, by policy id, hook (`pre_input`\|`pre_tool_call`\|`pre_output`) and the policy's own action (`warn`\|`redact`\|`require_approval`\|`block`). The pre_input/pre_output slice comes from trace JSONL; the pre_tool_call slice comes from the audit log and is subject to the rotation caveat below. |
| `docket_approvals_total{channel,outcome}` | counter | Resolved approvals, by channel (`cli`\|`http`\|`mcp`\|`telegram`\|`timeout`\|`tack`) and outcome (`granted`\|`denied`). `channel="timeout"` is the fail-closed expiry path (`core/approval.py`), never a human channel, and only ever pairs with `outcome="denied"`. `channel="tack"` (added in 2.4.0) distinguishes a decision made from Tack's board from one made through any other surface. Sourced entirely from the audit log; subject to the rotation caveat below. |
| `docket_turn_duration_seconds` | summary (`_sum`/`_count`, no quantiles) | Session wall-clock (`session_start` → `session_end`), fleet-wide, across every project's trace JSONL. `_sum`/`_count` gives mean duration; deliberately no invented percentiles (see `docket.serve.LoopMetrics`'s docstring). |

Additional metrics may be added in minor versions. **P20-2 (added 2026-08-03):** the guardrail/loop
metrics above are computed fresh, on every `/metrics` scrape, from durable state already on disk —
trace JSONL (`$TRACES_DIR`) and the audit log (`$DOCKET_HOME/audit.log`) — never a second in-process
counter store, so they survive a `docket serve` restart for free and every number is traceable back
to a record `docket trace`/`docket audit` can also show. This module only *reads* those stores to
compute counters; it never writes through them, keeping telemetry and the audit log's own
tamper-evidence chain separate (ROADMAP Phase 20).

**Durability caveat, stated plainly — every counter here is a lifetime-of-current-storage count,
NOT a monotonic total.** Both sources lose history, for different reasons:

1. **Audit-derived** — all of `docket_approvals_total`, and the pre_tool_call slice of
   `docket_policy_hits_total` — see only `audit.log`'s *current* generation. `core/audit.py`
   rotates that file to a single-generation backup (`audit.log.1`, itself overwritten by the next
   rotation) once it exceeds `AUDIT_LOG_MAX_BYTES` (5MB by default), and `read_audit()` reads only
   the current file, so a rotation silently drops whatever history was in the backup.
2. **Trace-derived** — the rest of these metrics — had no such gap until 2.5.0, because traces were
   only ever appended to. They now expire: `core/trace.py`'s `expire_old_traces()` (P22-6) deletes
   *terminated* traces past `TRACE_RETENTION_S`, run by `docket trace expire` and by `serve`'s
   periodic sweep. Retention bounds the unbounded storage growth this caveat used to name as an
   open gap, at the cost of giving these counters the same drop behaviour.

A Prometheus `rate()` reading a counter that drops to a **smaller-but-nonzero** value misreads that
as a reset followed by real (under-counted) traffic, not as missing history. **Consumers MUST NOT
build alerting that assumes these counters are monotonic.**

Note that retention is measured from when a session *ended*, not from when it was last active: a
trace with no `session_end` is never expired by age, and `sweep_all()`'s synthetic `session_end`
carries a fresh timestamp, so an abandoned session's trace survives a full window after the sweep
first terminates it.

**Scrape cost, measured:** every `/metrics` request re-parses every trace JSONL file plus the whole
current audit log — there is no cache. Measured against a synthetic corpus of 50 trace files across
10 projects (200 events each, 10,000 events total, ~927KB) plus an audit log at its rotation
ceiling (`AUDIT_LOG_MAX_BYTES` = 5MB, 18,296 entries at this corpus's average entry size):
`render_metrics()` averaged **60ms** wall-clock over 5 runs (58-65ms range) on the box this was
measured on. That is fine at today's fleet size and Prometheus's typical 15s scrape interval, but
it is `O(total trace + audit bytes)` per scrape on the same thread that serves `/health`, so it
degrades linearly as either grows unbounded (see the durability caveat above) — a cache is
deliberately not added by this card; the threshold to revisit is when a scrape starts costing
enough to compete with that interval against a real fleet's actual trace/audit volume, which
should be measured against production data, not asserted here.

### GET /health

Liveness check. Always returns HTTP 200 while the process is alive.

```json
{"status": "ok", "gateway": 1}
```

`gateway` is retained for API compatibility and is always `0`: Docket has no external gateway
process. Liveness is represented by the HTTP 200 and `status="ok"`.

### GET /runs

**Added in API version 2 (R-3 / D-17).** Requires `Authorization: Bearer <token>`. Returns every
persisted dispatch-run record, newest first. An optional `?project=<name>` query parameter filters
to one pod.

```json
{
  "runs": [
    {
      "id":         "run-3f2a1c9e-...",
      "source":     "cli | webhook | schedule | sweep | mcp",
      "project":    "myapp",
      "state":      "queued | running | succeeded | failed | cancelled",
      "taskIds":    ["task-91a2..."],
      "error":      "",
      "created":    "2026-07-30T02:10:00.123456+00:00",
      "startedAt":  "2026-07-30T02:10:00.200000+00:00",
      "finishedAt": "2026-07-30T02:10:04.500000+00:00",
      "variables":  {"env": "staging"}
    }
  ]
}
```

`variables` (added Phase 16 W-4, additive) is the pipeline variable namespace this run was
resolved against — `{}` for every source except `webhook` (see `POST /dispatch/<project>` below);
`cancelled` (added Phase 16 W-2, additive) is a run `docket runs cancel <id>` killed in flight.

### GET /runs/&lt;id&gt;

**Added in API version 2 (R-3 / D-17).** Requires `Authorization: Bearer <token>`. Returns one run
record (the same shape as one element of `/runs`' array, unwrapped). `404` if the id is unknown.

### GET /tasks/&lt;project&gt;

**Added 2.4.0 (Phase 22, P22-2).** Requires `Authorization: Bearer <token>`. Wraps
`core.dispatch.read_tasks(project)` exactly — no filtering, no reshaping, no invented 404: a
project with no pod is `read_tasks`' own `[]`, not an error.

```json
{
  "tasks": [
    {
      "id": "task-91a2...",
      "description": "Fix the bug",
      "priority": "normal",
      "status": "pending",
      "source": "operator",
      "created": "2026-08-04T12:00:00Z",
      "hops": []
    }
  ]
}
```

Field set matches whatever `read_tasks` normalizes onto a task record (v2 fields backfilled for a
legacy queue) — this spec does not re-enumerate them; see `core/dispatch.py`'s
`_TASK_SCALAR_DEFAULTS` for the authoritative list, since duplicating it here would drift the
moment a field is added there.

- The project segment must be non-empty — `GET /tasks` and `GET /tasks/` both reject with `400`.
- A project with a pod but an empty queue, and a project with no pod at all, both return `200` with
  `{"tasks": []}` — indistinguishable at this endpoint, matching `read_tasks`' own contract (it has
  no notion of "pod exists but is empty" vs. "no pod").

### GET /traces/&lt;project&gt;

**Added 2.4.0 (Phase 22, P22-3 — P20-3's deferral trigger firing).** Requires
`Authorization: Bearer <token>`. Returns raw trace JSONL for one project, verbatim, cursor'd by an
optional `?since=<cursor>` query parameter so a polling consumer (e.g. Tack) can resume without
re-reading everything each time. This is deliberately **not** the fleet-wide trace query P20-3
described — one project, one cursor, no filtering by event type/role/session; a caller that wants
that aggregates client-side across calls.

```json
{
  "events": [
    "{\"ts\": \"2026-08-04T12:00:00Z\", \"project\": \"myapp\", \"session_id\": \"...\", \"agent_role\": \"lead\", \"event_type\": \"tool_call\", \"payload\": {...}}"
  ],
  "next": "2026-08-04T12:00:00Z:1"
}
```

- Each element of `events` is the **verbatim JSONL line** (a JSON string, not a re-parsed/re-keyed
  object) exactly as `core.trace.export_lines` returned it — no field is added, removed or renamed.
- A project with no trace files returns `200` with `{"events": [], "next": ""}` — not an error.
- The project segment must be non-empty — `GET /traces` and `GET /traces/` both reject with `400`.
- **Cursor semantics.** `export_lines`' own `since` filter is `ts >= since` — inclusive — and `ts`
  is second-granularity (`%Y-%m-%dT%H:%M:%SZ`). Several trace events sharing one timestamp is
  routine (one dispatch hop can emit several events inside the same wall-clock second), so neither
  "next cursor = last event's raw ts" (redelivers that whole second on the next poll) nor a naive
  exclusive reinterpretation of it (silently drops a same-second event that arrives after the poll
  that first saw that second) is correct. The `next` value is instead a compound
  `"<ts>:<n>"` token — `n` is how many lines carrying that exact `ts` have already been delivered —
  so a poll loop that always passes back the previous response's `next` as its `since` ingests every
  event exactly once, even across a same-second boundary. A bare timestamp (no `:<n>` suffix) is
  also accepted as `since`, with `n` treated as 0.
- A trace line `export_lines` cannot key on (malformed JSON, or valid JSON missing `ts`) is a
  pre-existing limitation of that function, not solved by this endpoint: such a line is always
  re-included whenever any `since` filter is active, regardless of cursor value. This endpoint never
  drops it, but also cannot make it stop reappearing — the practical impact is nil under normal
  operation, since `core.trace.trace_event` always writes a valid `ts`.

### POST /dispatch/&lt;project&gt;

**Changed in API version 2.** The webhook now creates a run record *before* returning, and the
response body carries its id:

```json
{"ok": true, "run": "run-3f2a1c9e-...", "project": "myapp", "status": "dispatched"}
```

The dispatch pipeline itself still runs asynchronously (this endpoint must not block on a real
agent turn) — poll `GET /runs/<id>` (or `docket runs show <id>`) for the outcome. Before API
version 2 this response had no `run` field and the dispatch outcome, including any exception, was
silently discarded.

**Request body (added Phase 16 W-4, additive).** The request body — a plain `{name: value}` JSON
object, `{}` if omitted — is the webhook's params, resolved against the pod's *effective*
pipeline's declared `variables` (`core.pipeline.resolve_variables`; see
`pipeline-format.spec.md`) before the run record is created:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"env": "staging"}' http://127.0.0.1:7474/dispatch/myapp
```

- A body that is not a JSON object (e.g. malformed JSON, or valid JSON that isn't an object) is
  rejected with `400` before any pipeline is even resolved.
- A missing `required` pipeline variable (one absent from both the body and the pipeline's own
  declared default — a required variable never has one) is rejected with `400` naming the missing
  variable(s), and — like the auth/malformed-project rejections above it — **no run record is
  created** for a rejected request.
- On success, the resolved namespace (payload values winning over any declared default; a key the
  pipeline never declared passes through unchanged) is persisted on the created run record's new
  `variables` field (see `GET /runs` above).
- The effective pipeline resolved here is always the pod's own configured/default one (whatever
  `docket pod <project> dispatch` would use) — the webhook has no way to supply a `--file` pipeline
  of its own; only its *variable values* are payload-driven.

### POST /tasks/&lt;project&gt;

**Added in 2.4.0.** Requires `Authorization: Bearer <token>`. Enqueues one task onto the pod's
queue — the HTTP counterpart of `docket pod <project> delegate` and the MCP `delegate` tool, closing
the one enqueue gap Phase 22 exists to close (`POST /dispatch/<project>` above only *runs* an
already-populated queue). Calls the exact same `core.dispatch.enqueue_task` those two callers use,
so the `pre_input` guardrail gate, priority normalization and persisted task shape are byte-for-byte
identical to the CLI path — this route adds no new semantics.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"description": "Fix the flaky test", "priority": "high"}' \
  http://127.0.0.1:7474/tasks/myapp
```

Request body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `description` | string | Yes | `400` if absent or empty. |
| `priority` | `"high"\|"normal"\|"low"` | No | Defaults to `"normal"`; an unrecognized value falls back to `"normal"` — the same normalization `enqueue_task` already applies to the CLI/MCP callers. |
| `trusted` | boolean | No | Overrides the `pre_input` policy check's trust flag for this one enqueue (see `core.dispatch.enqueue_task`'s `trusted` parameter). Omitted, it preserves the CLI/MCP default exactly (trusted). It does **not** change the persisted task's `source` field or introduce a new trust/source vocabulary — the only thing it touches is which `pre_input` policies are eligible to fire (today: whether the `prompt-injection` policy id is skipped). |

Success response (task queued, `pending`):

```json
{"ok": true, "task": "task-91a2...", "project": "myapp", "status": "pending"}
```

- A malformed JSON body, or a body that is valid JSON but not an object, is rejected with `400`
  before `enqueue_task` is ever called.
- A project with no pod (`docket add <project>` never run) is rejected with `404`, naming the
  project — this is a real "nothing to enqueue against" condition, not a server error.
- A `pre_input` guardrail policy matching the description with a `block` verdict is rejected with a
  `4xx` naming the policy id (the same `DispatchError` message `docket pod <p> delegate` prints) —
  nothing is persisted.
- A `pre_input` policy matching with a `require_approval` verdict is **not** an error: the task is
  genuinely created (visible on `GET /tasks/<project>`, `docket pod <p> queue`, etc.) but gated, so
  the response is an honest `200` reporting the real state instead of one that implies the task is
  queued to run:

  ```json
  {
    "ok": true,
    "task": "task-91a2...",
    "project": "myapp",
    "status": "waiting_approval",
    "approvalToken": "apr-3f2a1c9e-..."
  }
  ```

  `approvalToken` resolves through the same `POST /approvals/<token>` endpoint documented below —
  granting it resumes the task, denying it fails the task terminally, exactly like any other
  approval-gated task.

### POST /pods

**Added in 2.5.0 (Phase 22, P22-5).** Requires `Authorization: Bearer <token>`. Provisions a fresh
pod from a blueprint — the HTTP counterpart of `docket add`, closing the one provisioning gap Phase
22 exists to close (a product-factory "one click creates a product" flow has no other way to reach
pod creation). Unlike every other Phase 22 route, this one is not a thin wrapper over a
pre-existing `core/` function: the real provisioning path (`cli/_pod.py`/`cli/_agents.py`) used to
print through `ui.py` as it worked, which `serve.py` (which never imports `docket.cli`) cannot
reach. `core.pod_provisioning.provision_pod` is the P22-5 extraction of that path's decisions and
effects, UI-free; `docket add`'s interactive and `--from` pod paths call the exact same function
(via `cli/_pod.py::build_pod_from_blueprint`), so this route and the CLI cannot drift apart.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"project": "myapp", "path": "/srv/repos/myapp", "blueprint": "software"}' \
  http://127.0.0.1:7474/pods
```

Request body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `project` | string | Yes | The pod id (matches `docket add`'s agent id, not its display name — a blueprint pod has no separate display-name field). `400` if absent or empty. |
| `path` | string | No | The blueprint's `codebase` (a `codebase`-kind blueprint, e.g. `software`) or `workDir` (a `workdir`-kind blueprint, e.g. `research`/`content`/`ops`) — `provision_pod` picks which one it means from the blueprint's own `workspace_kind`. Defaults to `""` (a `workdir`-kind blueprint then auto-provisions one under `config.pod_work_dir(project)`, exactly as `docket add` with no path does). |
| `blueprint` | string | No | A `core.blueprints` registry name. Defaults to `"software"` (`core.blueprints.DEFAULT_BLUEPRINT`, `docket add`'s own default). An unknown name is `400`, naming the invalid blueprint (`core.blueprints.BlueprintError`'s own message). |
| `pod` | `"full"` | No | Mirrors `docket add --pod full` — the CLI's only roster-override, itself restricted to the `software` blueprint (a non-`software` blueprint provisions its own fixed roster; `pod` is silently ignored for one, exactly as the CLI warns-and-ignores rather than erroring). Any value other than `"full"` is `400`. |
| `budget` | number \| numeric string | No | Overrides the blueprint's own default budget cap (applied to the Lead member only). `0`, omitted, or a non-positive value means no override (falls back to the blueprint default). A non-numeric value is `400`. |
| `verifyCmd` | string | No | Applied to Implementer member(s) only, at creation time — the same `verify_cmd` parameter `docket pod <p> add --verify` / `docket pod <p> set-verify` already thread through post-hoc, just supplied at creation instead. Validated the same way (`core.pod_provisioning.VerifyCmdError` — no NUL byte, no newline, length-capped); a failing value is `400`. |

Success response (`201`) — the created pod roster:

```json
{
  "ok": true,
  "project": "myapp",
  "blueprint": "software",
  "members": [
    {"id": "myapp-lead", "role": "lead", "model": "anthropic/claude-haiku-4-5-20251001"},
    {"id": "myapp-implementer", "role": "implementer", "model": "anthropic/claude-sonnet-4-6"}
  ]
}
```

- A malformed JSON body, or a body that is valid JSON but not an object, is rejected with `400`
  before `provision_pod` is ever called.
- A missing or empty `project` is `400`.
- `project` already having a registered pod member is rejected with `409` — matching `docket add`'s
  own idempotence contract (`_provision_pod_from_spec`'s "already exists — skipping"): the existing
  pod is left completely untouched, not silently re-provisioned or clobbered.
- **A partial failure leaves nothing behind.** If any member after the first fails to provision, every
  member `provision_pod` already created during that one call — its workspace directory and its
  fleet registration — is torn down, and any pod-level resources (port range, scratch dir) allocated
  for the attempt are freed, before the request fails. This is deliberate: the consumer (Tack) rolls
  back its own project record on a non-2xx response and has no way to roll back a half-created pod
  on docket's side. Such a failure is reported as `500` — the request itself was well-formed; the
  failure is an operational one (e.g. a filesystem error), not a validation error.
- This route adds no field `docket add` does not already have a corresponding capability for — see
  the request-body table above for exactly which existing CLI capability each field reuses.

### POST /approvals/&lt;token&gt; — the `channel` field

**Added in 2.4.0.** The request body accepts an optional `channel` string, tagged onto the
`approval.grant`/`approval.deny` audit entry this endpoint already writes (`core/approval.py`).
Validated against the closed vocabulary `core.approval.APPROVAL_CHANNELS` (`cli`\|`http`\|`mcp`\|
`telegram`\|`timeout`\|`tack`) — an unrecognized value is rejected with `400` rather than let an
arbitrary caller-supplied string reach the hash-chained audit log. Omitted, it defaults to `"http"`,
so every caller that predates this field is unchanged. `tack` distinguishes a decision made from
Tack's board from one made through any other surface — the audit chain's whole value is that its
provenance is honest, so a Tack-granted approval must not be indistinguishable from a CI job's.

## Validation

- `apiVersion` MUST be a string matching `SERVE_API_VERSION` in `src/docket/serve.py`.
- `gateway` MUST be exactly `"active"` or `"inactive"`.
- `agents[*].scope` MUST be `"project"` or `"org"`.
- `agents[*].budgetUsd` MUST be a float or `null`.
- `agents[*].lastActivity` MUST be an ISO date string (`YYYY-MM-DD`) or `"never"`.
- `/metrics` MUST conform to Prometheus text format 0.0.4.
- `/runs` and `/runs/<id>` MUST reject a request with no (or an invalid) Bearer token with `401`,
  before touching the run registry.
- `/tasks/<project>` and `/traces/<project>` MUST reject a request with no (or an invalid) Bearer
  token with `401`, and MUST reject an empty project segment with `400`, before touching any
  project state.
- `/traces/<project>`'s `next` cursor MUST be safe to feed back as the next request's `since`
  without either re-delivering an event already returned or skipping one written after the
  previous response — including when several events share one `ts` (see the cursor semantics
  paragraph above).
- A run record's `state` MUST be one of `queued | running | succeeded | failed`; `source` MUST be
  one of `cli | webhook | schedule | sweep | mcp` (`mcp` added Phase 18 L-3 — `docket mcp serve`'s
  `dispatch` tool).
- `POST /dispatch/<project>`'s response MUST carry a `run` id matching a record retrievable via
  `GET /runs/<id>` immediately after the response is sent (the record exists before the HTTP
  response is written, even though the dispatch itself is still in flight).
- `POST /tasks/<project>` MUST reject a request with no (or an invalid) Bearer token with `401`
  before touching the pod's queue; MUST reject an absent/empty `description` and a malformed or
  non-object body with `400` before calling `enqueue_task`; MUST return `404` (not `500`) for a
  project with no pod; MUST return a `4xx` naming the policy id for a `block` `pre_input` verdict;
  and MUST return `200` with `status: "waiting_approval"` plus a non-empty `approvalToken` for a
  `require_approval` verdict, never a response implying the task is queued to run.
- `POST /approvals/<token>`'s optional `channel` field MUST be one of
  `core.approval.APPROVAL_CHANNELS` (`cli | http | mcp | telegram | timeout | tack`); an
  unrecognized value MUST be rejected with `400` without changing the approval's state. Omitted, it
  MUST default to `"http"`.
- `POST /pods` MUST reject a request with no (or an invalid) Bearer token with `401` before touching
  any project state; MUST reject a malformed/non-object body, a missing/empty `project`, an unknown
  `blueprint`, a `pod` value other than `"full"`, a non-numeric `budget`, or an invalid `verifyCmd`
  with `400` before `provision_pod` is ever called; MUST reject an already-provisioned `project`
  with `409` without touching the existing pod; and on a genuine mid-provisioning failure MUST leave
  no member workspace, no fleet registration and no orphaned port/scratch allocation behind (full
  rollback) before responding `500`. `docket add`'s pod-provisioning path (interactive and `--from`)
  and this route MUST call the same `core.pod_provisioning.provision_pod` function — there is no
  second, drift-prone provisioning implementation.
- The contract is pinned by `tests/python/test_serve_read_api.py` (class `TestApiContract`),
  `tests/python/test_task_enqueue_api.py`, `tests/python/test_headless_approval_api.py` (class
  `TestApprovalChannel`), and `tests/python/test_serve_pods_endpoint.py`. Any change that breaks
  these is a breaking API change and MUST bump `apiVersion`.

## Examples

### Status endpoint (curl)

```bash
curl -s http://127.0.0.1:7474/status.json | jq .
```

### Metrics endpoint (curl)

```bash
curl -s http://127.0.0.1:7474/metrics
# docket_agents_total 3.0
# docket_gateway_up 1.0
```

### Health check

```bash
curl -s http://127.0.0.1:7474/health
# {"status": "ok", "gateway": 1}
```

### Trigger a dispatch and poll its run (curl)

```bash
TOKEN=... # printed at `docket serve` startup, or $DOCKET_SERVE_TOKEN

run_id=$(curl -s -H "Authorization: Bearer $TOKEN" -X POST \
  http://127.0.0.1:7474/dispatch/myapp | jq -r .run)

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7474/runs/$run_id | jq .
```

### List runs for one project (curl)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:7474/runs?project=myapp" | jq .
```

## Changelog

### 2.6.0 — 2026-08-19

W21-C1 daemon-free truth pass: documented the versioned `gateway` field as an always-inactive
compatibility field, sourced channels from Docket's fleet bindings, and corrected cost provenance
to usage-derived estimates. No response shape or runtime behavior changed.

### 2.5.0 — 2026-08-04

**`POST /pods`** (Phase 22, P22-5): provisioning over HTTP, the HTTP counterpart of `docket add`.
Unlike the four 2.4.0 routes, this one is not a thin wrapper over a pre-existing `core/` function —
the real provisioning path used to print through `ui.py` as it worked, which `serve.py` (never
importing `docket.cli`) cannot reach. `core.pod_provisioning.provision_pod` (new module) is the
extraction of that path's decisions and effects, UI-free; `docket add`'s pod path (interactive and
`--from`) was refactored onto the same function, via `cli/_pod.py::build_pod_from_blueprint`, so the
two surfaces cannot drift apart — pinned by a test that intercepts `provision_pod` and observes both
surfaces route through it. Body: `{project, path, blueprint, pod, budget, verifyCmd}` — every field
reuses an existing `docket add`/`docket pod` capability (see the `POST /pods` schema section above
for the exact mapping); none is a new flag, field, or semantic the CLI does not already have. An
already-provisioned `project` is `409`, untouched. A genuine mid-provisioning failure rolls back
every member (and pod-level resource) created during that call before responding `500` — proven with
a real induced failure (a monkeypatched workspace write raising on the second member), not a mock
asserting a cleanup function was called. Additive (new endpoint only), so `apiVersion` is unchanged.

Also in 2.5.0: the `/metrics` **durability caveat is rewritten, because P22-6 made half of it
false.** It previously said trace-derived counters had no history gap "because `sweep_all()` never
deletes a trace file", and named unbounded trace growth as an open P20-3 gap. Trace retention
(`expire_old_traces`) closed that gap and, in doing so, gave the trace-derived counters the same
drop behaviour the audit-derived ones already had. Both halves are now stated as
lifetime-of-current-storage counts with an explicit MUST NOT on monotonic alerting. No metric
name, type or label changed — only the honesty of what they mean.

### 2.4.0 — 2026-08-04

Phase 22 closes the CLI/HTTP asymmetry: four routes that expose what `core/` already does, adding
no new behaviour. Same Bearer auth, same policy hooks, same audit entries the CLI path produces.

- **`POST /tasks/<project>`** (Phase 22): the missing HTTP way to *enqueue* a task —
  `POST /dispatch/<project>` only ever ran an already-populated queue. Calls the exact same
  `core.dispatch.enqueue_task` the CLI (`docket pod <p> delegate`) and the MCP `delegate` tool call,
  so the `pre_input` guardrail gate, priority normalization and persisted task shape are unchanged;
  this route adds no new behaviour, only a new way to reach existing behaviour. A `block` verdict is
  a `4xx` naming the policy id; a `require_approval` verdict is an honest `200` reporting
  `status: "waiting_approval"` plus the real `approvalToken`, not a response implying the task is
  queued to run. A project with no pod is `404`. Additive (new endpoint only), so `apiVersion` is
  unchanged.
- `enqueue_task` gained an optional, keyword-only `trusted` parameter, wired straight into
  `core.policy.policy_eval_detail`'s existing `trusted=` argument — it does not add a new trust
  concept, policy action, or `source` vocabulary, and does not touch the persisted task's `source`
  field. Every existing caller (the CLI, the MCP tool, Telegram's inline delegate) passes no value
  and keeps byte-for-byte identical behaviour; only `POST /tasks/<project>` threads a caller-supplied
  value through.
- **`channel="tack"` on `POST /approvals/<token>`** (Phase 22): the request body now accepts an
  optional `channel` field, validated against the closed vocabulary `core.approval.APPROVAL_CHANNELS`
  (`cli | http | mcp | telegram | timeout | tack`) rather than accepted as free text — an
  unrecognized value is rejected with `400` without touching the approval's state. Omitted, it
  defaults to `"http"`, so every caller that predates this field keeps identical behaviour. `tack` is
  new so an approval granted from Tack's board is distinguishable in the hash-chained audit log from
  one granted through any other surface. Additive, so `apiVersion` is unchanged.
- `docket_approvals_total{channel,outcome}`'s documented channel set gained `tack` to match.
- **`GET /tasks/<project>`** (Phase 22): wraps `core.dispatch.read_tasks(project)` behind the same Bearer
  auth as `/runs`. No new behaviour: no filtering, no reshaping, and no 404 invented beyond what
  `read_tasks` itself expresses (`[]` for a project with no pod). Additive (new endpoint only), so
  this does not bump `apiVersion`.
- **`GET /traces/<project>?since=<cursor>`** (Phase 22): this is P20-3's deferral trigger firing ("grep
  over JSONL is adequate" was true for a human operator, false for a programmatic consumer that
  must resume from a cursor). Built on `core.trace.export_lines(project, since)` used as-is; returns
  raw JSONL verbatim for one project, cursor'd, with no fleet-wide query and no filtering by event
  type/role/session — deliberately narrower than the fleet trace query P20-3 originally described.
  Additive, does not bump `apiVersion`.
- The `next` cursor `GET /traces/<project>` returns is a compound `"<ts>:<n>"` token, not a bare
  timestamp — `export_lines`' `since` filter is inclusive (`ts >= since`) and second-granularity, so
  a bare last-seen ts would either redeliver everything from that second or, if naively treated as
  exclusive instead, silently drop a same-second event written after the poll that first observed
  that second. `n` tracks how many lines at that exact `ts` have already gone out, so a poll loop
  ingests every event exactly once across the boundary. A caller-supplied bare timestamp is still
  accepted as `since` (treated as `n=0`).
- Both read routes are pure reads (`read_tasks` / `export_lines`), so neither adds a policy hook or
  an audit entry the CLI path would not already produce.

### 2.3.0 — 2026-08-03

- P20-2 (ROADMAP Phase 20): four new `/metrics` families — `docket_tool_calls_total{decision}`,
  `docket_policy_hits_total{policy_id,hook,action}`, `docket_approvals_total{channel,outcome}`
  (all `counter`), and `docket_turn_duration_seconds` (`summary`: `_sum`/`_count` lines, no
  quantiles — one HELP/TYPE pair on the bare name per the Prometheus text exposition format, not
  two independent counters). Additive (new metric names only, no existing name/label/type
  changed), so this does not bump `apiVersion` — the same additive rule the 2.1.0 entry below
  already establishes for this endpoint.
- All four are recomputed fresh on every scrape from durable state already on disk (trace JSONL
  under `$TRACES_DIR`, and the audit log) — no new counter store, no new endpoint, no new
  dependency. `core/tools.py`'s tool-gate audit entries (`tool.deny`/`tool.ask`/`tool.warn`/
  `tool.redact`) now also carry a structured `policy_id=`/`policy_action=` pair so the
  pre_tool_call half of the policy-hit counter can be attributed without parsing free text; this
  is additive to the audit `detail` string, not a new audit action, and does not touch
  `evaluate_tool_call`'s decision logic.
- `channel="timeout"` on `docket_approvals_total` is `core/approval.py`'s existing fail-closed
  expiry path (`_resolve_timeout_as_denied`), not a new state — it only ever pairs with
  `outcome="denied"`. `channel` covers `cli`, `http`, `mcp`, `telegram` and `timeout`, the same
  closed set of callers `core/approval.py`'s own docstring already names.
- **Durability and scrape-cost caveats documented, not solved** (retention/rotation is P20-3,
  DEFERRED by D-24) — see the two callout paragraphs above the metric table: the audit-log-derived
  counters silently lose history older than the current 5MB generation on rotation, and a `/metrics`
  scrape is `O(total trace + audit bytes)` with no cache (measured at 60ms against a 10,000-event/
  50-file trace corpus plus a 5MB audit log).
- Deliberately not shipped: a per-agent cost/token metric change, or a p50/p95 latency figure —
  see the P20-2 report for why (docket's own driver's `cost_usd` is structurally always 0.0 post
  Phase 19, and no per-turn timestamp exists to compute a percentile from; `_sum`/`_count` is the
  honest S-sized answer for the mean).

### 2.1.0 — 2026-07-30

- Phase 18 L-3: `mcp` added as a valid run `source` (`docket mcp serve`'s `dispatch` tool creates
  a run record before any dispatch work starts, exactly like this webhook does — see
  `specs/api/mcp-server.spec.md`). Additive: existing `cli | webhook | schedule | sweep` values
  are unchanged, so this does not bump `apiVersion`.

### 2.0.1 — 2026-07-30

- Doc fix (ROADMAP Phase 14 R-8): the `GET /status.json` schema's `apiVersion` example and field
  note were left at the stale `"1"` value when 2.0.0 bumped `SERVE_API_VERSION` to `2` — both now
  read `"2"`, matching the field's own validation rule below (which was already correct).

### 2.0.0 — 2026-07-30

- R-3 (D-17): added the authenticated read-registry tier — `GET /runs` (newest-first, optional
  `?project=` filter) and `GET /runs/<id>` — backed by the persisted dispatch-run registry
  (`core/runs.py`).
- `POST /dispatch/<project>`'s response body gained a `run` field (the created run's id), returned
  before the dispatch pipeline itself runs. This is a breaking change to that endpoint's response
  shape (a consumer parsing the old `{ok, project, status}` shape unchanged still works — `run` is
  additive — but the *guarantee* that a run id always accompanies a 200 response is new and the
  reason for the major bump), hence `apiVersion` → `2`.
- Documented the security-model split: `/status.json` / `/metrics` / `/health` stay unauthenticated
  read endpoints; `/approvals`, `/runs`, `/runs/<id>` join the write endpoints in requiring a
  Bearer token.

### 1.0.0 — 2026-06-26

- Initial stable specification extracted from implementation docs.
- Documents `/status.json`, `/metrics`, `/health` endpoints with field-level notes.
- Defines versioning policy: minor additions do not bump `apiVersion`; breaking changes do.
