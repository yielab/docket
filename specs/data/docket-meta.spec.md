# Agent Metadata (.docket-meta.json) Specification

**Version**: 2.1.0
**Status**: Complete
**Last Updated**: 2026-06-25

## Purpose

This specification defines the schema for `.docket-meta.json`, the per-agent metadata file
that docket treats as its source of truth for an agent's identity and configuration. One file
exists per agent at `~/.openclaw/workspaces/projects/<agent-id>/.docket-meta.json` (project
agents) or `~/.openclaw/workspaces/<role>/.docket-meta.json` (specialist agents), and is read
and written exclusively through the typed ACL helpers (`meta_get` / `meta_set` / `meta_read`) in
`src/docket/edges/adapters/openclaw.py`, over the atomic JSON store in `src/docket/edges/store.py`.

## Scope

This specification covers:

- The fields stored in `.docket-meta.json`, their types, and their meaning
- Which fields are required versus optional
- The sync class of each field (`synced` vs `local`) and what that means
- Validation rules applied on write by `meta_set`

It does NOT cover the OpenClaw daemon's own configuration schema (`openclaw.json`), which is
owned by the daemon; docket mirrors only `synced` fields into it.

## Structure

`.docket-meta.json` is a single **flat JSON object** stored at the root of each agent's workspace:

- Project / pod agents: `~/.openclaw/workspaces/projects/<agent-id>/.docket-meta.json`
  (pod members use the compound id `<project>-<role>`, e.g. `myapp-implementer`).
- Org specialists: `~/.openclaw/workspaces/<role>/.docket-meta.json`.

Every value is a JSON scalar (string, number, or boolean) — there are no nested objects or
arrays. The field set is **closed**: it is the `AgentMeta` Pydantic model in
`src/docket/core/models.py`, which validates the whole record on every write through
`edges/store.py`. The file is docket's source of truth for an agent; the daemon's `openclaw.json`
mirrors only the `synced` fields (see Sync contract).

## Schema

The field table below is the authoritative source. The same set is declared as the `AgentMeta`
model in `src/docket/core/models.py`; the model validates every write, so a field that drifts from
this table fails type-checking or the test suite.

**Sync classes:**

- `synced` — docket mirrors this field into `openclaw.json`; `docket doctor` detects drift.
- `local` — docket-only state; never expected in `openclaw.json`; not checked for drift.

| Field | Type | Enum / constraints | Sync | Required | Written by | Description |
|-------|------|--------------------|------|----------|------------|-------------|
| `kind` | enum | `project` or `specialist` | local | Yes | `add`, `install` | Whether this is a project or specialist agent |
| `scope` | enum | `org` or `project` | local | No (backfilled) | `add`, `install`, `doctor` | Whose data the agent may see (Phase 10): `org` = shared/cross-cutting; `project` = pod-scoped, never shared across projects. Orthogonal to `kind`/`role`. Absent on legacy records → derived from `kind`+`role` on read |
| `role` | string | — | local | specialist only | `install` | Specialist role name (e.g. `programmer`) |
| `type` | enum | `repo` or `task` | local | Yes | `add` | Agent sub-type: codebase-bound or free-roaming |
| `name` | string | — | local | Yes | `add` | Human-readable display name |
| `codebase` | string | absolute path | local | repo only | `add` | Absolute path to the project; empty for `task` agents |
| `stack` | string | — | local | No | `add` | Comma-separated detected stack (e.g. `Docker,git`) |
| `model` | string | `provider/model-id` | **synced** | Yes | `add`, `profile` | Provider-qualified model id mirrored to `openclaw.json` |
| `modelSource` | enum | `policy` or `pinned` | local | Yes | `add`, `profile` | Whether the model follows the role policy or is pinned |
| `description` | string | — | local | No | `add` | Free-text purpose |
| `created` | string | ISO-8601 | local | Yes | `add` | Creation timestamp |
| `sessionKey` | string | `agent:<id>:<project>` | **synced** | Yes | `add`, `scope` | Isolation key; mirrored to `openclaw.json` agent metadata |
| `projectKey` | string | — | local | Yes | `add`, `scope` | Project component of `sessionKey` (default `default`) |
| `budgetUsd` | number | ≥ 0 | local | No | `profile --budget` | Per-agent spend cap in USD |
| `paused` | bool | — | local | No | `doctor`, `profile` | Whether the agent is paused (e.g. budget exceeded) |
| `pausedReason` | string | — | local | No | `doctor`, `profile` | Human-readable pause reason |
| `portRangeStart` | number | integer ≥ 0 | local | No (implementer only) | `add`, `pod add` | First port of the pod's reserved range (CD-1). Absent on non-implementers |
| `portRangeCount` | number | integer > 0 | local | No (implementer only) | `add`, `pod add` | Number of ports in the pod's reserved range (CD-1) |
| `scratchDir` | string | absolute path | local | No (implementer only) | `add`, `pod add` | Pod-isolated scratch data directory path (CD-1). Absent on non-implementers |
| `templateVersion` | string | — | local | No | `add` | Template schema version used at agent creation |

## Sync contract

Only **`model`** and **`sessionKey`** are mirrored to `openclaw.json`:

- `model` — written to `agents.list[id].model` by `set_agent_model()` (via `docket profile`).
- `sessionKey` — written to `agents.list[id].metadata.sessionKey` by `sync_session_key()` (via
  `docket scope`); `projectKey` is written alongside it to `metadata.projectKey` for convenience.

All other fields are **local** to docket. Do not expect them in `openclaw.json`.

`docket doctor` compares every `synced` field between `.docket-meta.json` and `openclaw.json`
and reports drift. `--fix` re-syncs from `.docket-meta.json` (the source of truth).

## Validation

`meta_set` validates every write against the `AgentMeta` model in `src/docket/core/models.py`:

- **Unknown field** → `error` (typo guard; exits non-zero without writing).
- **Type mismatch**: `budgetUsd` non-numeric or negative → `error`; `paused` non-boolean → `error`.
- **Enum violation**: `kind`, `type`, `modelSource` not in their enum → `error`.
- Valid writes pass through unchanged to the existing atomic-write/lock path.

On read, a missing file is treated as "agent not found" (return code 2), not an empty object.

`sessionKey` and `projectKey` MUST stay consistent; `docket scope` updates both atomically and
calls `sync_session_key()` to mirror the value into `openclaw.json`.

## Field rules

- `kind` MUST be `project` (for `docket add` agents) or `specialist` (for `docket install` agents).
- `type` MUST be `repo` or `task` for project agents.
- `codebase` MUST be a readable absolute path when `type` is `repo`; MAY be empty for `task`.
- `model` MUST be a provider-qualified id (e.g. `anthropic/claude-sonnet-4-6`).
- `modelSource` MUST be `policy` (follows the role→model table) or `pinned` (explicit choice).
- `sessionKey` MUST match the pattern `agent:<id>:<project>` and its `<project>` component MUST
  equal `projectKey`.
- `budgetUsd`, when present, MUST be a non-negative number.

## Examples

A repo agent created by `docket add myshop ~/Sites/myshop`:

```json
{
  "kind": "project",
  "type": "repo",
  "name": "My Shop",
  "codebase": "/home/user/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-sonnet-4-6",
  "modelSource": "policy",
  "description": "work",
  "created": "2026-03-05T12:08:17-03:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "templateVersion": "3"
}
```

The same agent after `docket profile myshop anthropic/claude-haiku-4-5 --budget 5` and being paused:

```json
{
  "kind": "project",
  "type": "repo",
  "name": "My Shop",
  "codebase": "/home/user/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-haiku-4-5",
  "modelSource": "pinned",
  "description": "work",
  "created": "2026-03-05T12:08:17-03:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "budgetUsd": 5,
  "paused": true,
  "pausedReason": "Budget cap of $5 reached",
  "templateVersion": "3"
}
```

## Changelog

### Version 2.1.0 (2026-06-25)

- CD-1: Added `portRangeStart`, `portRangeCount`, `scratchDir` fields (Implementer only; local)
- These are pod-level runtime-resource fields allocated at provisioning and freed on teardown.
  They are never synced to `openclaw.json`.

### Version 2.0.0 (2026-06-22)

- CDD-1: Added `kind`, `role`, `modelSource`, `templateVersion` fields (all present in code since
  Phase 6b; spec was behind)
- CDD-1: Added `sync` column; declared `model` and `sessionKey` as `synced`, all others as `local`
- CDD-2: Documented `meta_set` validation contract (unknown-field guard, type/enum checks)
- Updated examples to include `kind`, `modelSource`, `templateVersion`
- Corrected `docket profile` syntax in examples (model-id, not tier name)

### Version 1.0.0 (2026-06-09)

- Initial `.docket-meta.json` schema specification
- Documented core identity and configuration fields
- Defined required/optional fields and the openclaw.json sync contract
- Linked field-level validation to input-validation.spec.md
