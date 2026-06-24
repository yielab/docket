# CLI JSON Output Shapes

**Version**: 1.1.0
**Status**: Complete
**Last Updated**: 2026-06-24

## Purpose

Define the exact JSON shapes docket emits when a read command is run with `--json`, so that
scripts and dashboards can consume docket output as a stable contract. The shapes are produced by
the CLI layer (`src/docket/cli/`) and the serve loop (`src/docket/serve.py`) and are verified
against that code.

## Scope

Covers every command that supports `--json` output: `list`, `info`, `cost` (and
`cost --history`), `doctor`, `snapshot`, and the `serve` HTTP endpoints. It does **not** cover
human-readable (Rich) output, nor the OpenClaw daemon's own `openclaw.json` format (owned by the
daemon; see the Anti-Corruption Layer).

## Structure

All `--json` output is a **bare JSON object or array — there is no envelope wrapper.** There is no
`{success, data, error, version}` outer object; consumers parse the returned object directly. Two
structural rules hold everywhere:

- **Bare values.** A command returns its object/array directly (e.g. `{"agents": [...]}`), never
  wrapped in a status envelope.
- **camelCase keys.** Every key is camelCase (`costUsd`, not `cost_usd`) — see Validation.

## Schema

### `docket list --json`

```json
{
  "agents": [
    {
      "id":          "string",
      "kind":        "project | specialist",
      "scope":       "org | project",
      "role":        "string (pod role / specialist role; may be empty)",
      "pod":         "string (project this member belongs to; empty for non-pod agents)",
      "name":        "string",
      "type":        "repo | task",
      "model":       "string (provider/model-id)",
      "modelSource": "policy | pinned",
      "stack":       "string (comma-separated, may be empty)",
      "codebase":    "string (absolute path, may be empty)",
      "budgetUsd":   "number | \"\"",
      "telegram":    "string (peer id) | null",
      "registered":  true
    }
  ]
}
```

### `docket info <id> --json`

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

### `docket cost --json`

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

### `docket doctor --json`

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

### `docket snapshot` (full output)

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

### `docket serve` HTTP endpoints

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

## Validation

All JSON output from docket uses **camelCase**:

- `costUsd` (not `cost_usd`)
- `totalUsd` (not `total_usd`)
- `budgetUsd` (not `budget_usd`)
- `sessionKey` (not `session_key`)
- `modelSource` (not `model_source`)
- `lastActive` (not `last_active`)

The Python suite (`tests/python/`, e.g. `test_m3_commands.py`, `test_m5_serve.py`) asserts each
shape field-by-field, so a shape change here that isn't reflected in code fails CI.

## Examples

`docket list --json` for a project pod (lean Lead + Implementer):

```json
{
  "agents": [
    {
      "id": "myapp-lead", "kind": "project", "scope": "project", "role": "lead",
      "pod": "myapp", "name": "myapp-lead", "type": "repo",
      "model": "anthropic/claude-haiku-4-5", "modelSource": "policy",
      "stack": "", "codebase": "/code/myapp", "budgetUsd": "",
      "telegram": null, "registered": true
    },
    {
      "id": "myapp-implementer", "kind": "project", "scope": "project", "role": "implementer",
      "pod": "myapp", "name": "myapp-implementer", "type": "repo",
      "model": "anthropic/claude-sonnet-4-6", "modelSource": "policy",
      "stack": "", "codebase": "/code/myapp", "budgetUsd": "",
      "telegram": null, "registered": true
    }
  ]
}
```

## Changelog

### Version 1.1.0 (2026-06-24)

- Restructured to the canonical data-spec sections (Purpose, Scope, Structure, Schema, Validation,
  Examples, Changelog) so it validates under `scripts/validate-specs.sh`.
- Updated `list --json` to the current shape: added `scope`, `role`, `pod` (Phase 10 pods) and
  `budgetUsd`.
- Re-pointed source references from the retired Bash `lib/commands/` to the Python
  `src/docket/cli/` + `src/docket/serve.py`, and the contract test from the old shell helper to the
  pytest suite.

### Version 1.0.0 (2026-06-22)

- CDD-4: First specification of actual `--json` output shapes across all read commands.
- Replaces the phantom `{success, data, error, version}` envelope that was documented in
  `cli-interface.spec.md` but never emitted by any command (D-10: document reality).
