# serve read API — contract spec (v1)

**API version:** `1`  (see `SERVE_API_VERSION` in `src/docket/serve.py`)  
**Status:** Stable — breaking changes bump `SERVE_API_VERSION` and update this document.  
**Scope:** Read-only. All mutation stays in the CLI (`docket approve/deny`, etc.) or the
token-guarded write endpoints (`POST /approvals/<token>`, `POST /dispatch/<project>`).

The server binds to `127.0.0.1` by default. The read endpoints (`/status.json`,
`/metrics`, `/health`) require no auth. Write endpoints require `Authorization: Bearer
<token>` (see `serve.py` security-model note for token sourcing).

---

## Endpoints

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

---

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

---

### GET /health

Liveness check. Always returns HTTP 200 while the process is alive.

```json
{"status": "ok", "gateway": 1}
```

`gateway` is `1` (active) or `0` (inactive).

---

## Versioning policy

- **Minor additions** (new top-level or agent fields, new metric names) do not bump
  `apiVersion`. Dashboard consumers should ignore unknown keys.
- **Breaking changes** (removed/renamed fields, changed semantics) bump `apiVersion`
  and are documented here.
- The contract is pinned by `tests/python/test_cd8_read_api.py` (class `TestApiContract`).
  Any change that breaks that test is a breaking API change and must bump `apiVersion`.
