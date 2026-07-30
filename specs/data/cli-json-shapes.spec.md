# CLI JSON Output Shapes

**Version**: 1.4.0
**Status**: Complete
**Last Updated**: 2026-07-30

## Purpose

Define the exact JSON shapes docket emits when a read command is run with `--json`, so that
scripts and dashboards can consume docket output as a stable contract. The shapes are produced by
the CLI layer (`src/docket/cli/`) and the serve loop (`src/docket/serve.py`) and are verified
against that code.

## Scope

Covers every command that supports `--json` output: `list`, `info`, `cost` (and
`cost --history`), `doctor`, `snapshot`, `runs list`/`runs show <id>` (R-3), and the `serve` HTTP
endpoints. It does **not** cover human-readable (Rich) output, nor the OpenClaw daemon's own
`openclaw.json` format (owned by the daemon; see the Anti-Corruption Layer).

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

Note: there is no `type` field — every project agent has been a `repo` agent since the
task-agent type was retired; the CLI does not emit a `type` key at all (previously documented
here in error; see `docket-meta.spec.md`'s v2.3.0 changelog for the field's removal from
`AgentMeta`).

### `docket info <id> --json`

```json
{
  "id":          "string",
  "name":        "string",
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

### `docket runs list --json` (R-3)

```json
{
  "runs": [
    {
      "id":         "string (run-<uuid4>)",
      "source":     "cli | webhook | schedule | sweep | mcp",
      "project":    "string",
      "state":      "queued | running | succeeded | failed",
      "taskIds":    "array of strings",
      "error":      "string (empty unless state is failed)",
      "created":    "string (ISO-8601, local offset)",
      "startedAt":  "string (ISO-8601) | null",
      "finishedAt": "string (ISO-8601) | null"
    }
  ]
}
```

`docket runs list --project <p> --json` filters the array to one pod; newest-first ordering.

### `docket runs show <id> --json` (R-3)

Same shape as one element of `runs list`'s array, unwrapped (a bare object, not `{"runs": [...]}`):

```json
{
  "id":         "string (run-<uuid4>)",
  "source":     "cli | webhook | schedule | sweep",
  "project":    "string",
  "state":      "queued | running | succeeded | failed",
  "taskIds":    "array of strings",
  "error":      "string",
  "created":    "string (ISO-8601)",
  "startedAt":  "string (ISO-8601) | null",
  "finishedAt": "string (ISO-8601) | null"
}
```

### `docket snapshot` (full output)

The snapshot command writes to a file (or stdout). The outer shape:

```json
{
  "timestamp":    "string (ISO-8601 UTC, e.g. 2026-07-30T12:00:00Z)",
  "gateway":      "active | inactive",
  "channels":     "array of strings (enabled OpenClaw channel names)",
  "agents":       "array of agent objects (see below)",
  "totalCostUsd": "number"
}
```

There is no top-level `version` or `bindings` field (a prior version of this spec documented
both; neither is emitted — bindings, when present, are nested per-agent below, and no version
string is included).

Each agent object in the snapshot (project agents, then any specialists with a workspace):

```json
{
  "id":           "string",
  "name":         "string",
  "kind":         "project | specialist",
  "model":        "string",
  "registered":   "boolean",
  "bindings":     "array of {channel, peerId}",
  "lastActivity": "string (YYYY-MM-DD) | \"never\"",
  "costUsd":      "number"
}
```

Note: the snapshot's agent object is intentionally leaner than `docket list --json`'s — it
carries no `scope`, `role`, `pod`, `codebase`, `stack`, `budgetUsd`, or `paused`. Use `docket
list --json` / `docket info <id> --json` for those.

### `docket serve` HTTP endpoints

| Endpoint | Content-Type | Shape |
|----------|-------------|-------|
| `/status.json` | `application/json` | Same as `docket snapshot` output |
| `/health` | `application/json` | `{"status": "ok", "gateway": <0 \| 1>}` |
| `/metrics` | `text/plain` | Prometheus text format (see below) |
| `/runs` | `application/json` | Same as `docket runs list --json` (auth required; see `specs/data/serve-read-api.spec.md`) |
| `/runs/<id>` | `application/json` | Same as `docket runs show <id> --json` (auth required) |

Prometheus metrics emitted by `/metrics`:

```
docket_agents_total <N>
docket_agent_cost_usd{agent="<id>",model="<model>"} <F>
docket_agent_turns_total{agent="<id>"} <N>
docket_cost_usd_total <F>
docket_gateway_up <0|1>
docket_approvals_pending_total <N>
```

Note: there is no `docket_agents_paused_total` metric, and the per-agent cost/turns labels are
keyed `agent="<id>"`, not `id="<id>"` (a prior version of this spec documented both incorrectly).

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
      "pod": "myapp", "name": "myapp-lead",
      "model": "anthropic/claude-haiku-4-5", "modelSource": "policy",
      "stack": "", "codebase": "/code/myapp", "budgetUsd": "",
      "telegram": null, "registered": true
    },
    {
      "id": "myapp-implementer", "kind": "project", "scope": "project", "role": "implementer",
      "pod": "myapp", "name": "myapp-implementer",
      "model": "anthropic/claude-sonnet-4-6", "modelSource": "policy",
      "stack": "", "codebase": "/code/myapp", "budgetUsd": "",
      "telegram": null, "registered": true
    }
  ]
}
```

## Changelog

### Version 1.4.0 (2026-07-30)

- Phase 18 L-3: `mcp` added as a valid `runs` `source` value (`docket mcp serve`'s `dispatch`
  tool) alongside `cli | webhook | schedule | sweep` — see `specs/api/mcp-server.spec.md` for the
  MCP tool surface itself (its tool responses reuse these same JSON shapes verbatim rather than
  defining new ones).

### Version 1.3.0 (2026-07-30)

- ROADMAP Phase 14 R-8 spec truth pass: removed the `type` field from `docket list --json` and
  `docket info --json`'s documented shapes — no command has emitted it since the `type`
  (`repo`|`task`) field was dropped from `AgentMeta` (see `docket-meta.spec.md` v2.3.0); it was
  left in this spec by mistake at the time. Corrected `docket snapshot`'s outer shape (no
  `version` or top-level `bindings` field; `gateway`/`channels` were missing) and its agent
  object (the real, leaner field set the code emits — no `type`/`codebase`/`stack`/`budgetUsd`/
  `paused`, `bindings` nested per-agent). Corrected the `/metrics` Prometheus list: no
  `docket_agents_paused_total` metric exists; the per-agent labels are `agent="<id>"`, not
  `id="<id>"`; added the metrics that were missing from this list (`docket_agent_turns_total`,
  `docket_gateway_up`, `docket_approvals_pending_total`).

### Version 1.2.0 (2026-07-30)

- R-3 (D-17): documented `docket runs list --json` and `docket runs show <id> --json` (the run
  registry — one persisted record per dispatch invocation) and the corresponding
  `GET /runs` / `GET /runs/<id>` serve endpoints.

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
