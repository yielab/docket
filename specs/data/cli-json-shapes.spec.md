# CLI JSON Output Shapes

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-22

## Overview

Commands that support `--json` emit bare JSON objects or arrays — **no envelope wrapper**.
There is no `{success, data, error, version}` outer object; consumers parse the returned
object directly. Key names use camelCase throughout.

All shapes in this document are verified against the code (see `lib/commands/`).

---

## `docket list --json`

File: `lib/commands/list.sh`

```json
{
  "agents": [
    {
      "id":          "string",
      "kind":        "project | specialist",
      "name":        "string",
      "type":        "repo | task",
      "model":       "string (provider/model-id)",
      "modelSource": "policy | pinned",
      "codebase":    "string (absolute path, may be empty)",
      "stack":       "string (comma-separated, may be empty)",
      "telegram":    "string (peer id) | null",
      "registered":  true
    }
  ]
}
```

---

## `docket info <id> --json`

File: `lib/commands/info.sh`

```json
{
  "id":          "string",
  "name":        "string",
  "type":        "repo | task",
  "codebase":    "string (may be empty)",
  "stack":       "string (may be empty)",
  "model":       "string (provider/model-id)",
  "budgetUsd":   "number | \"\"",
  "paused":      "boolean",
  "sessionKey":  "string (agent:<id>:<project>)",
  "projectKey":  "string",
  "registered":  "boolean",
  "telegram":    "string (peer id) | null",
  "lastActive":  "string (relative time, e.g. '3h ago') | null"
}
```

---

## `docket cost --json`

File: `lib/commands/cost.sh`

```json
{
  "agents": [
    {
      "id":        "string",
      "model":     "string",
      "input":     "number (tokens)",
      "output":    "number (tokens)",
      "costUsd":   "number | null (null when pricing unknown)",
      "turns":     "number",
      "budgetUsd": "number | null"
    }
  ],
  "totalUsd": "number"
}
```

### `docket cost --history [<id>] --json`

```json
{
  "scope": "string (agent id or 'all')",
  "history": [
    {
      "date":    "string (YYYY-MM-DD)",
      "turns":   "number",
      "input":   "number (tokens)",
      "output":  "number (tokens)",
      "costUsd": "number"
    }
  ]
}
```

---

## `docket doctor --json`

File: `lib/commands/doctor.sh`

```json
{
  "healthy": "boolean",
  "issues":  "number",
  "checks": {
    "openclaw":    { "ok": "boolean", "path": "string | null" },
    "python3":     { "ok": "boolean", "path": "string | null" },
    "fzf":         { "available": "boolean", "path": "string | null" },
    "config":      { "ok": "boolean", "path": "string", "agentCount": "number", "bindingCount": "number" },
    "gateway":     { "ok": "boolean", "status": "string" },
    "telegram":    { "enabled": "boolean" },
    "agents":      "array of { id, model, budget, cost, turns, paused }",
    "modelConfig": { "ok": "boolean", "invalid": "array of strings" },
    "drift":       "array of { id, metaModel, ocModel, synced }",
    "budget":      "array of agent budget status objects",
    "runaway":     "array of agent runaway detection objects",
    "keyHygiene":  { "keys": "array", "missingForAgents": "array of strings" },
    "securityGates": "object",
    "templateDrift": "array of { id, agentVersion, currentVersion, ok }"
  }
}
```

---

## `docket snapshot` (full output)

File: `lib/commands/snapshot.sh`

The snapshot command writes to a file (or stdout). The outer shape:

```json
{
  "timestamp":    "string (ISO-8601 UTC)",
  "version":      "string (docket version)",
  "agents":       "array of agent objects (see below)",
  "bindings":     "array of binding objects",
  "totalCostUsd": "number"
}
```

Each agent object in the snapshot:

```json
{
  "id":        "string",
  "kind":      "project | specialist",
  "name":      "string",
  "type":      "repo | task | role",
  "model":     "string",
  "codebase":  "string",
  "stack":     "string",
  "budgetUsd": "number | null",
  "paused":    "boolean",
  "costUsd":   "number"
}
```

---

## `docket serve` HTTP endpoints

File: `lib/commands/serve.sh`

| Endpoint | Content-Type | Shape |
|----------|-------------|-------|
| `/status.json` | `application/json` | Same as `docket snapshot` output |
| `/health` | `application/json` | `{"status": "ok", "gateway": <boolean>}` |
| `/metrics` | `text/plain` | Prometheus text format (see below) |

Prometheus metrics emitted by `/metrics`:

```
docket_agents_total <N>
docket_agents_paused_total <N>
docket_cost_usd_total <F>
docket_agent_cost_usd{id="<id>"} <F>
```

---

## Key naming rules

All JSON output from docket uses **camelCase**:

- `costUsd` (not `cost_usd`)
- `totalUsd` (not `total_usd`)
- `budgetUsd` (not `budget_usd`)
- `sessionKey` (not `session_key`)
- `modelSource` (not `model_source`)
- `lastActive` (not `last_active`)

A test in `tests/unit/test-helpers.sh` asserts that no `--json` output contains snake_case
keys (underscore-separated) in its top-level or agent-level fields.

---

## Changelog

### Version 1.0.0 (2026-06-22)

- CDD-4: First specification of actual `--json` output shapes across all read commands
- Replaces the phantom `{success, data, error, version}` envelope that was documented in
  `cli-interface.spec.md` but never emitted by any command (D-10: document reality)
- Verified against `lib/commands/` source
