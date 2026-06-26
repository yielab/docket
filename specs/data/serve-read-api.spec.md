# serve read API — contract spec

**Version**: 1.0.0
**Status**: Stable
**Last Updated**: 2026-06-26

## Purpose

This specification defines the read API exposed by `docket serve` — a lightweight HTTP server
that gives dashboards, CI pipelines, and external tools a stable, versioned window into fleet
state. The API is intentionally read-only at the unauthenticated layer; all mutation flows
through the CLI (`docket approve/deny`, etc.) or token-guarded write endpoints.

## Scope

This specification covers:

- The three stable read endpoints (`/status.json`, `/metrics`, `/health`)
- The JSON schema for each response
- The Prometheus metric names and semantics
- The versioning policy (what constitutes a breaking change)
- The security model (auth requirements per endpoint)

It does NOT cover write endpoints (`POST /approvals/<token>`, `POST /dispatch/<project>`), which
are implementation details gated by `Authorization: Bearer <token>` and documented in
`src/docket/serve.py`.

**API version:** `1`  (see `SERVE_API_VERSION` in `src/docket/serve.py`)
The server binds to `127.0.0.1` by default. The read endpoints (`/status.json`, `/metrics`,
`/health`) require no auth.

## Structure

The server exposes three stable read endpoints:

| Endpoint | Content-Type | Auth required |
|---|---|---|
| `GET /status.json` | `application/json` | No |
| `GET /metrics` | `text/plain; version=0.0.4` | No |
| `GET /health` | `application/json` | No |

All responses are served from `127.0.0.1` (localhost only). Responses include
`Cache-Control: no-store` — consumers must not cache.

## Schema

### GET /status.json

Full fleet snapshot. Keys are **stable**; additional keys may be added in minor versions.

```json
{
  "apiVersion": "1",
  "timestamp":  "2026-06-25T10:00:00Z",
  "gateway":    "active | inactive",
  "channels":   ["telegram"],
  "agents": [
    {
      "id":           "myapp-lead",
      "name":         "My App Lead",
      "type":         "lead | implementer | reviewer | tester | specialist",
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
| `apiVersion` | string | Always `"1"` in this version of the spec. |
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

## Validation

- `apiVersion` MUST be a string matching `SERVE_API_VERSION` in `src/docket/serve.py`.
- `gateway` MUST be exactly `"active"` or `"inactive"`.
- `agents[*].scope` MUST be `"project"` or `"org"`.
- `agents[*].budgetUsd` MUST be a float or `null`.
- `agents[*].lastActivity` MUST be an ISO date string (`YYYY-MM-DD`) or `"never"`.
- `/metrics` MUST conform to Prometheus text format 0.0.4.
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

## Changelog

### 1.0.0 — 2026-06-26

- Initial stable specification extracted from implementation docs.
- Documents `/status.json`, `/metrics`, `/health` endpoints with field-level notes.
- Defines versioning policy: minor additions do not bump `apiVersion`; breaking changes do.
