# Agent Metadata (.docket-meta.json) Specification

**Version**: 2.4.0
**Status**: Complete
**Last Updated**: 2026-07-30

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
| `schemaVersion` | number | integer ≥ 1 | local | Yes (defaulted) | `add`, `install` | Meta schema version stamp; lets future migrations detect old records |
| `kind` | enum | `project` or `specialist` | local | Yes | `add`, `install` | Whether this is a project or specialist agent |
| `scope` | enum | `org` or `project` | local | No (backfilled) | `add`, `install`, `doctor` | Whose data the agent may see (Phase 10): `org` = shared/cross-cutting; `project` = pod-scoped, never shared across projects. Orthogonal to `kind`/`role`. Absent on legacy records → derived from `kind`+`role` on read |
| `role` | string | — | local | specialists + pod members | `install`, `add`, `pod add` | Role name: org-specialist role (e.g. `security`) or pod-member role (`lead`/`implementer`/`reviewer`/`tester`) |
| `name` | string | — | local | Yes | `add` | Human-readable display name |
| `codebase` | string | absolute path | local | project agents | `add` | Absolute path to the project (specialists have none) |
| `stack` | string | — | local | No | `add` | Comma-separated detected stack (e.g. `Docker,git`) |
| `model` | string | `provider/model-id` | **synced** | Yes | `add`, `profile` | Provider-qualified model id mirrored to `openclaw.json` |
| `modelSource` | enum | `policy` or `pinned` | local | Yes | `add`, `profile` | Whether the model follows the role policy or is pinned |
| `description` | string | — | local | No | `add` | Free-text purpose |
| `created` | string | ISO-8601 | local | Yes | `add` | Creation timestamp |
| `sessionKey` | string | `agent:<id>:<project>` | **synced** | Yes | `add`, `scope` | Isolation key; mirrored to `openclaw.json` agent metadata |
| `projectKey` | string | — | local | Yes | `add`, `scope` | Project component of `sessionKey` (default `default`) |
| `budgetUsd` | number | ≥ 0 | local | No | `profile --budget` | Per-agent spend cap in USD |
| `paused` | bool | — | local | No | `core/dispatch.py`'s budget gate (set); `profile --budget`/`profile --resume` (clear) | Whether the agent is paused. Set to `true` on a pod's Lead when the pod's spend (recorded, or estimated when the daemon recorded none) reaches its `budgetUsd` cap (ROADMAP Phase 14 R-5); dispatch then refuses every further claim for that pod at claim time. Read through `AgentMeta.is_paused()`/`AgentMeta.coerce_paused()` (a real `bool`, tolerant of a legacy `"true"`/`"false"` string) — never a raw string compare |
| `pausedReason` | string | — | local | No | `core/dispatch.py`'s budget gate (set to `"budget"`); `profile --budget`/`profile --resume` (clear) | Human-readable pause reason. Currently always the literal `"budget"` — the only writer today is the budget-cap gate |
| `portRangeStart` | number | integer ≥ 0 | local | No (implementer only) | `add`, `pod add` | First port of the pod's reserved range (CD-1). Absent on non-implementers. When set, injected into the Implementer's real dispatch subprocess environment as `DOCKET_PORT_BASE` (FD-0) — not only documented as TOOLS.md prose |
| `portRangeCount` | number | integer > 0 | local | No (implementer only) | `add`, `pod add` | Number of ports in the pod's reserved range (CD-1). Injected as `DOCKET_PORT_COUNT` alongside `portRangeStart` (FD-0) |
| `scratchDir` | string | absolute path | local | No (implementer only) | `add`, `pod add` | Pod-isolated scratch data directory path (CD-1). Absent on non-implementers. Injected as `DOCKET_SCRATCH_DIR` alongside the port-range vars (FD-0) |
| `verifyCmd` | string | shell command | local | No (implementer only) | `pod add --verify`, `pod set-verify`, `meta_set` | Shell command run mechanically after each Implementer hop (CD-2). Non-zero exit blocks done and emits a `verification_failed` trace event. Absent/empty = skip (logged). Settable via the public `docket pod <project> add --verify "<cmd>"` flag or `docket pod <project> set-verify <member-id> "<cmd>"` for an existing member (FD-1) — `meta_set` remains the internal fallback |
| `templateVersion` | string | — | local | No | `add` | Template schema version used at agent creation |
| `persona` | object | `{name, emoji}` | local | No | `docket persona set/clear` | Optional docket-owned cosmetic identity, rendered into `SOUL.md` between persona markers and re-applied on `maintain rebuild`. Display only — the agent's structural identity is its role (never read from a self-authored `IDENTITY.md`) |

## Sync contract

Only **`model`** and **`sessionKey`** are mirrored to `openclaw.json`:

- `model` — written to `agents.list[id].model` by `set_agent_model()` (via `docket profile`).
- `sessionKey` — written to `agents.list[id].metadata.sessionKey` by `sync_session_key()` (via
  `docket scope`); `projectKey` is written alongside it to `metadata.projectKey` for convenience.

All other fields are **local** to docket. Do not expect them in `openclaw.json`.

`docket doctor` compares every `synced` field between `.docket-meta.json` and `openclaw.json`
and reports drift. `--fix` re-syncs from `.docket-meta.json` (the source of truth).

## Runtime environment injection (FD-0)

`portRangeStart`/`portRangeCount`/`scratchDir` are **local** fields (never synced to
`openclaw.json`), but they are not docket-only bookkeeping either: `core/dispatch.py` reads
them for every Implementer hop and, when `portRangeStart` is set, passes
`DOCKET_PORT_BASE`/`DOCKET_PORT_COUNT`/`DOCKET_SCRATCH_DIR` into that hop's real subprocess
environment via `agent_run`'s `env` parameter (layered on top of the parent process's own
environment, which is never mutated). An Implementer with no allocated resources, and every
non-Implementer hop, receives no override. This is enforced binding, not advisory prose — the
same values are still written into the Implementer's `TOOLS.md` for human/agent-readable
context, but the subprocess environment is what an implementer can actually rely on
programmatically. See `pod-dispatch.spec.md` for the full per-hop behavioral contract.

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

A project agent created by `docket add myshop ~/Sites/myshop`:

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
  "pausedReason": "budget",
  "templateVersion": "3"
}
```

## Changelog

### Version 2.4.0 (2026-07-30)

- ROADMAP Phase 14 R-5: `paused`/`pausedReason` are no longer clear-only fields — the
  pod-dispatch budget gate (`core/dispatch.py`'s `_pause_lead_for_budget`) now sets them for
  real the first time a pod's Lead reaches its `budgetUsd` cap, and the new `docket profile <id>
  --resume` flag clears them (with an audit entry). Removed the prior "Known gap: nothing sets
  this to `true` yet" note (now resolved) and corrected the `pausedReason` example value to the
  literal `"budget"` string the code actually writes, replacing the illustrative full-sentence
  placeholder. Documented the typed `AgentMeta.is_paused()`/`coerce_paused()` accessor as the
  one correct way to read `paused` (fixing a prior display-code bug where the flag was compared
  against the string `"true"` instead of read as the `bool` it's typed and stored as).

### Version 2.3.0 (2026-07-30)

- Truth pass (Platformization baseline): removed the `type` (`repo`|`task`) row — the field
  was deleted from `AgentMeta` when the dual-type model was retired ("every project agent is
  a repo agent"); added the missing `schemaVersion` and `persona` rows (both shipped fields
  absent from the closed set); corrected `role` (pod members carry it too, not only
  specialists) and `codebase` (no more task agents); flagged the `paused`/`pausedReason`
  writer gap (auto-pause is Phase 14 R-5 — today only a clearing write exists).

### Version 2.2.0 (2026-07-02)

- FD-6 spec truth pass for Phase 13's FD-0/FD-1 cards:
  - Documented that `portRangeStart`/`portRangeCount`/`scratchDir` now reach the Implementer's
    real dispatch subprocess environment as `DOCKET_PORT_BASE`/`DOCKET_PORT_COUNT`/
    `DOCKET_SCRATCH_DIR` (FD-0) — previously only TOOLS.md prose, now an enforced binding. Added
    a "Runtime environment injection" section and cross-referenced the new `pod-dispatch.spec.md`.
  - Corrected `verifyCmd`'s "Written by" column to include `pod set-verify` (FD-1's public
    setter for an existing member); the pre-existing `pod add --verify` claim was verified
    accurate against the now-shipped flag.

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
