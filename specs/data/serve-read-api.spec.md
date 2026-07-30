# serve read API — contract spec

**Version**: 2.2.0
**Status**: Stable
**Last Updated**: 2026-07-30

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
- The JSON schema for each response
- The Prometheus metric names and semantics
- The versioning policy (what constitutes a breaking change)
- The security model (auth requirements per endpoint)

It does NOT cover the write endpoints' request handling (`POST /approvals/<token>`,
`POST /dispatch/<project>`) beyond the shape of their response body — those are implementation
details gated by `Authorization: Bearer <token>` and documented in `src/docket/serve.py`.

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
| `gateway` | `"active" \| "inactive"` | Systemd is-active result for `openclaw-gateway.service`. |
| `channels` | string[] | Enabled OpenClaw channel names (e.g. `["telegram"]`). |
| `agents[*].scope` | `"project" \| "org"` | `project` for pod agents, `org` for shared specialists. |
| `agents[*].budgetUsd` | float \| null | `null` when no budget cap is set for the agent. |
| `agents[*].lastActivity` | date string \| `"never"` | Date of the newest memory log file, or `"never"`. |
| `totalCostUsd` | float | Sum of all agent `costUsd` values (daemon-recorded). |

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

Additional metrics may be added in minor versions.

### GET /health

Liveness check. Always returns HTTP 200 while the process is alive.

```json
{"status": "ok", "gateway": 1}
```

`gateway` is `1` (active) or `0` (inactive).

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

## Validation

- `apiVersion` MUST be a string matching `SERVE_API_VERSION` in `src/docket/serve.py`.
- `gateway` MUST be exactly `"active"` or `"inactive"`.
- `agents[*].scope` MUST be `"project"` or `"org"`.
- `agents[*].budgetUsd` MUST be a float or `null`.
- `agents[*].lastActivity` MUST be an ISO date string (`YYYY-MM-DD`) or `"never"`.
- `/metrics` MUST conform to Prometheus text format 0.0.4.
- `/runs` and `/runs/<id>` MUST reject a request with no (or an invalid) Bearer token with `401`,
  before touching the run registry.
- A run record's `state` MUST be one of `queued | running | succeeded | failed`; `source` MUST be
  one of `cli | webhook | schedule | sweep | mcp` (`mcp` added Phase 18 L-3 — `docket mcp serve`'s
  `dispatch` tool).
- `POST /dispatch/<project>`'s response MUST carry a `run` id matching a record retrievable via
  `GET /runs/<id>` immediately after the response is sent (the record exists before the HTTP
  response is written, even though the dispatch itself is still in flight).
- The contract is pinned by `tests/python/test_cd8_read_api.py` (class `TestApiContract`).
  Any change that breaks that test is a breaking API change and MUST bump `apiVersion`.

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
