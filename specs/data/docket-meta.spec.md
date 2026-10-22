# Agent Metadata (.docket-meta.json) Specification

**Version**: 3.6.3
**Status**: Complete
**Last Updated**: 2026-10-19

## Purpose

This specification defines the schema for `.docket-meta.json`, the per-agent metadata file
that docket treats as its source of truth for an agent's identity and configuration. One file
exists per agent at `~/.docket/workspaces/projects/<agent-id>/.docket-meta.json` (pod members), and is read and written
through `core/fleet.py`'s typed `meta_get` / `meta_set` / `meta_read` helpers over the atomic JSON
store in `edges/store.py`.

## Scope

This specification covers:

- The fields stored in `.docket-meta.json`, their types, and their meaning
- Which fields are required versus optional
- Validation rules applied on write by `meta_set`

It does NOT cover docket's fleet registry (`fleet.json`, `core/fleet.py`) — agent registration,
channel bindings, gates/isolation flags, and the org-wide default model (see
agent-lifecycle.spec.md and security-gates.spec.md). **No field in this
file is mirrored anywhere else.** Every field here, including `model` and `sessionKey`, is
docket's single source of truth for that value.

## Structure

`.docket-meta.json` is a single **flat JSON object** stored at the root of each agent's workspace:

- Project / pod agents: `~/.docket/workspaces/projects/<agent-id>/.docket-meta.json`
  (pod members use the compound id `<project>-<role>`, e.g. `myapp-implementer`).

Every value is a JSON scalar (string, number, or boolean) — there are no nested objects or
arrays. The documented field set below
is the one every writer in `src/docket/` targets, backed by the `AgentMeta` Pydantic model in
`src/docket/core/models.py` — but the model is **not closed**: it declares
`extra="allow"` (deliberately, for forward-compat round-tripping — see "Validation" below), so
`meta_set` does not reject an undeclared field name. `maxReworkCycles` and `requireApprovalRoles`
(see their rows) are the shipped fields that rely on this: neither has a dedicated `AgentMeta`
attribute yet, and both survive only because unknown keys are allowed through, not rejected. The
file is docket's **single** source of truth for an agent's model, session key, and every other
field below — none of them are mirrored anywhere else (ROADMAP Phase 19 P19-6; see "Sync
contract (retired)").

## Schema

The field table below is the authoritative source. The same set is declared as the `AgentMeta`
model in `src/docket/core/models.py`; the model validates every write, so a field that drifts from
this table fails type-checking or the test suite.

**Storage ownership:** every row below is `local`. `fleet.json` (see agent-lifecycle.spec.md) does
not duplicate `model`/`sessionKey`; this file is their one home. The `Sync` column remains for
schema continuity, but every value is `local` and there is no cross-file drift check.

| Field | Type | Enum / constraints | Sync | Required | Written by | Description |
|-------|------|--------------------|------|----------|------------|-------------|
| `kind` | enum | `project` | local | Yes | `add` | Always `project` |
| `scope` | enum | `project` | local | No (defaults to `project`) | pod provisioning | Whose data the agent may see: `project` = pod-scoped, never shared across projects. Absent → `project` (the `AgentMeta` field default); nothing derives it from `kind`/`role` on read |
| `role` | string | — | local | pod members | `add`, `pod add` | Pod-member role (`lead`/`implementer`/`reviewer`/`tester`) |
| `pod` | string | pod id | local | No (pod members) | `add`, `pod add` | The pod (project id) this member belongs to; read by `docket status`, which fall back to the `<project>-<role>` id convention when absent. **Not a field on the `AgentMeta` Pydantic model** — round-trips through `extra="allow"` |
| `name` | string | — | local | Yes | `add` | Human-readable display name |
| `codebase` | string | absolute path | local | `codebase`-kind project agents | `add` | Absolute path to the project (`workdir`-kind pod members have none) |
| `workspaceKind` | enum | `codebase` or `workdir` | local | No (defaulted) | `add` (pod blueprints only, ROADMAP Phase 16 W-7) | Whether this agent's workspace is anchored to a codebase or a plain working directory. Absent on every record written before W-7 (and every `codebase`-kind pod member since — see pod-blueprints.spec.md) → implicitly `codebase`, which is what it already is; only ever written as the literal `workdir` |
| `workDir` | string | absolute path | local | `workdir`-kind pod members | `add` (pod blueprints only) | The pod's shared working directory (ROADMAP Phase 16 W-7). Mutually exclusive with `codebase` — present only when `workspaceKind: workdir` |
| `blueprint` | string | — | local | No | `add` (pod blueprints only) | Name of the pod blueprint that provisioned this agent (`software`, `research`, `content`, `ops`, …) — see pod-blueprints.spec.md. Absent for any agent not provisioned through a blueprint |
| `stack` | string | — | local | No | `add` | Comma-separated detected stack (e.g. `Docker,git`); not auto-detected for a `workdir`-kind agent (no codebase to inspect) |
| `model` | string | `provider/model-id` | local | Yes | `add`, `setup model` | Provider-qualified model id. Not mirrored anywhere (P19-6) — this is its one home |
| `description` | string | — | local | No | `add` | Free-text purpose |
| `created` | string | ISO-8601 | local | Yes | `add` | Creation timestamp |
| `sessionKey` | string | `agent:<id>:<project>` | local | Yes | `add`, `scope` | Isolation key. Not mirrored anywhere (P19-6) — this is its one home |
| `projectKey` | string | — | local | Yes | `add`, `scope` | Project component of `sessionKey` (default `default`) |
| `budgetUsd` | number | ≥ 0 | local | No | `pod set/unset budgetUsd` (Lead only, via `core.pod.PodSettings`) | Per-agent spend cap in USD, persisted on disk as a real JSON number (a numeric string from an older install still reads back fine — `PodSettings` accepts either). `docket pod show --json` emits it as a JSON number, or `null` when unset — see cli-json-shapes.spec.md |
| `paused` | bool | — | local | No | `core/dispatch.py`'s budget gate (set); `pod set budgetUsd`, `run --resume` (clear) | Whether the agent is paused. Set to `true` on a pod's Lead when its usage-derived cost estimate reaches `budgetUsd` (ROADMAP Phase 14 R-5); dispatch then refuses every further claim for that pod at claim time. Read through `AgentMeta.is_paused()`/`AgentMeta.coerce_paused()` (a real `bool`, tolerant of a stringified `"true"`/`"false"`) — never a raw string compare |
| `pausedReason` | string | — | local | No | `core/dispatch.py`'s budget gate (set to `"budget"`); `pod set budgetUsd`, `run --resume` (clear) | Human-readable pause reason. Currently always the literal `"budget"` — the only writer today is the budget-cap gate |
| `turnTimeoutS` | number | integer > 0 | local | No (Lead only) | `pod set/unset`, `meta_set` (`core.pod.PodSettings`) | Pod-wide agent-turn timeout override in seconds (ROADMAP Phase 14 R-2), read the same way `budgetUsd` is: only the Lead's value is consulted (`core/dispatch.py`'s `pod_turn_timeout`). Falls back to `DEFAULT_TIMEOUT` (or a serve-wide config knob) when unset; a per-invocation `docket run --timeout` overrides both this and `verifyTimeoutS`. A stored value that fails validation (non-integer, ≤ 0) refuses dispatch naming the key, rather than falling back |
| `verifyTimeoutS` | number | integer > 0 | local | No (Lead only) | `pod set/unset`, `meta_set` (`core.pod.PodSettings`) | Pod-wide `verifyCmd` timeout override in seconds (R-2), independent of `turnTimeoutS` — a hung test suite and a hung LLM turn no longer share one budget. Same Lead-only read convention, fallback chain, and invalid-value refusal as `turnTimeoutS` |
| `maxReworkCycles` | number | integer ≥ 0 | local | No (Lead only) | `pod set/unset`, `meta_set` (`core.pod.PodSettings`) | Bounded rework budget for a Reviewer's REQUEST-CHANGES verdict (R-4), read from the Lead only (`core/dispatch.py`'s `pod_max_rework_cycles`). Default `1` when unset (exactly one rework cycle before a second REQUEST-CHANGES fails the task); `0` disables rework entirely. Still not a field on the `AgentMeta` Pydantic model — it round-trips because `AgentMeta` allows extra keys (see "Validation" below) — but `core.pod.PodSettings` now validates it on every read and write regardless, and `docket pod show` is its dedicated CLI setter |
| `requireApprovalRoles` | string | comma-separated pod role list | local | No (Lead only) | `meta_set` (no dedicated CLI setter) | ROADMAP Phase 15 G-1: pod-level require_approval gate source — a comma-separated, case-insensitive list of pod roles (e.g. `"implementer,reviewer"`) whose hop must wait for a granted approval before it runs (`core/dispatch.py`'s `_pod_requires_approval`, read the same Lead-only way as `maxReworkCycles`/`budgetUsd`). Blank or missing = no pod-level gate for any role. **Not yet a field on the `AgentMeta` Pydantic model** — same `extra="allow"` round-trip as `maxReworkCycles`; no dedicated CLI setter yet, only the internal `meta-set` debug path. See `pod-dispatch.spec.md` for the full gate/`waiting_approval` state-machine contract this field feeds, including the two other (currently inert seam) gate sources |
| `portRangeStart` | number | integer ≥ 0 | local | No (implementer only) | `add`, `pod add` | First port of the pod's reserved range (CD-1). Absent on non-implementers. A shared locked allocation transition gives concurrently successful pods distinct ranges; a failed attempt may remove this field's range only when it created that ownership. When set, injected into the Implementer's real dispatch subprocess environment as `DOCKET_PORT_BASE` (FD-0) — not only documented as TOOLS.md prose |
| `portRangeCount` | number | integer > 0 | local | No (implementer only) | `add`, `pod add` | Number of ports in the same attempt-owned allocation as `portRangeStart`. Injected as `DOCKET_PORT_COUNT` alongside `portRangeStart` (FD-0) |
| `scratchDir` | string | absolute path | local | No (implementer only) | `add`, `pod add` | Pod-isolated scratch data directory path (CD-1). Absent on non-implementers. Its lifecycle is coupled to attempt-owned provisioning: rollback removes a scratch/workdir path only when that attempt created it, preserving pre-existing runtime contents and a successful same-project pod's directory. Injected as `DOCKET_SCRATCH_DIR` alongside the port-range vars (FD-0) |
| `verifyCmd` | string | shell command | local | No (implementer only) | `pod add --verify`, `pod set verify --member`, `pod unset verify --member` (removes the key), `meta_set` | Shell command run mechanically after each Implementer hop (CD-2). Non-zero exit blocks done and emits a `verification_failed` trace event. Absent/empty = skip (logged). Settable via the public `docket pod add --verify "<cmd>"` flag or `docket pod set verify "<cmd>" --member <member-id>` for an existing member (FD-1) — `meta_set` remains the internal fallback |
| `templateVersion` | string | — | local | No | `add` | Template schema version used at agent creation |

In the **Written by** column, `add` means project/pod provisioning, which since 21abc85 is
`docket init` (including `docket init --from`); `docket pod add`
writes the same member fields when a role joins an existing pod. `install` means the internal
workstation bootstrap the first `docket init` runs; there is no `install` command.

## Single-source contract

Before the Docket-owned registry shipped, **`model`** and **`sessionKey`** were mirrored to a
second, external registry:

- `model` — written to a second `agents.list[id].model` by `set_agent_model()`.
- `sessionKey` — written to `agents.list[id].metadata.sessionKey` by `sync_session_key()` (via
  a scope command); `projectKey` was written alongside it to `metadata.projectKey`.
- `docket setup` compared every `synced` field between the two registries
  and reported drift; `--fix` re-synced from `.docket-meta.json`.

**None of this exists anymore.** `set_agent_model`, `sync_session_key`, `core/sync.py`
(`check_agent`/`check_all`/`Drift`), and `docket setup`'s config-drift check are all deleted, not
ported. Agent registration moved to docket's own `fleet.json` (`core/fleet.py`), and — this is
the part worth stating plainly — **`fleet.json` does not track `model` or `sessionKey` at all**.
It was never a design goal to give them a *new* second home; the goal was one home. `.docket-meta.json`
is that home for every field in the schema table above, unconditionally. See
agent-lifecycle.spec.md's registration requirements and `core/fleet.py`'s module docstring for the
full rationale (a second writer was the actual source of the drift this section used to describe;
a single-writer JSON file
docket alone touches cannot drift from itself).

## Runtime environment injection (FD-0)

`portRangeStart`/`portRangeCount`/`scratchDir` are local metadata fields, but they are not passive
bookkeeping: `core/dispatch.py` reads
them for every Implementer hop and, when `portRangeStart` is set, passes
`DOCKET_PORT_BASE`/`DOCKET_PORT_COUNT`/`DOCKET_SCRATCH_DIR` into that hop's real subprocess
environment via `agent_run`'s `env` parameter (layered on top of the parent process's own
environment, which is never mutated). An Implementer with no allocated resources, and every
non-Implementer hop, receives no override. This is enforced binding, not advisory prose — the
same values are still written into the Implementer's `TOOLS.md` for human/agent-readable
context, but the subprocess environment is what an implementer can actually rely on
programmatically. See `pod-dispatch.spec.md` for the full per-hop behavioral contract.

## Validation

`meta_set` validates every write against the `AgentMeta` model in `src/docket/core/models.py`
(`AgentMeta.model_validate(raw)`, called after the new field is merged into the record but
before it's written):

- **Unknown field** → **accepted, not rejected.** `AgentMeta`'s `model_config` sets
  `extra="allow"` for forward-compat round-tripping, so `model_validate` does not raise on a
  field name it doesn't declare — a typo in a field name is silently written, not caught. (This
  predates ROADMAP Phase 14 and is a real, standing gap — not a claim this version invented —
  but it is corrected here because R-4's `maxReworkCycles` is the first shipped field that
  actively depends on this permissiveness to be settable at all. There is no test pinning
  stricter behavior.)
- **Type mismatch on a declared field**: e.g. `budgetUsd` given a non-numeric string, or
  `paused` given a non-boolean — → `error` for fields whose Pydantic type can't coerce the value.
- **Enum violation**: `kind` not in its enum → `error`.
- Valid writes pass through unchanged to the existing atomic-write/lock path.

On read, a missing file is treated as "agent not found" (exit code 1, docket's flat CLI
convention — see agent-lifecycle.spec.md's Return Codes), not an empty object.

`sessionKey` and `projectKey` MUST stay consistent; provisioning writes both in this one file
(there is no second file to mirror either into).

## Field rules

- `kind` MUST be `project`; `scope`, when present, MUST be `project`. No shared (`org`) agent
  exists.
- `workspaceKind`, when present, MUST be `codebase` or `workdir` (ROADMAP Phase 16 W-7); absent
  means `codebase` (the field default).
- `codebase` MUST be a readable absolute path for a `codebase`-kind agent; MUST be empty for a
  `workdir`-kind agent (its location lives in `workDir` instead).
- `workDir`, when present, MUST be an absolute path and implies `workspaceKind: workdir`.
- `model` MUST be a provider-qualified id (e.g. `anthropic/claude-sonnet-4-6`).
- `sessionKey` MUST match the pattern `agent:<id>:<project>` and its `<project>` component MUST
  equal `projectKey`.
- `budgetUsd`, when present, MUST be a non-negative number.

## Examples

The Lead of a project pod created by `docket init myshop ~/Sites/myshop` (the `software`
blueprint, the default — `codebase`-kind, so `workspaceKind`/`workDir` are absent):

```json
{
  "kind": "project",
  "scope": "project",
  "role": "lead",
  "pod": "myshop",
  "name": "myshop lead",
  "codebase": "/home/user/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-sonnet-4-6",
  "description": "work",
  "created": "2026-03-05T12:08:17-03:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "blueprint": "software",
  "templateVersion": "2"
}
```

The same agent after `docket pod set budgetUsd 5` and being paused:

```json
{
  "kind": "project",
  "scope": "project",
  "role": "lead",
  "pod": "myshop",
  "name": "myshop lead",
  "codebase": "/home/user/Sites/myshop",
  "stack": "Docker,git",
  "model": "anthropic/claude-sonnet-4-6",
  "description": "work",
  "created": "2026-03-05T12:08:17-03:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "budgetUsd": 5,
  "paused": true,
  "pausedReason": "budget",
  "blueprint": "software",
  "templateVersion": "2"
}
```

A `research`-blueprint pod member (`workdir`-kind — see pod-blueprints.spec.md) created by
`docket init my-market-scan --blueprint research`:

```json
{
  "kind": "project",
  "scope": "project",
  "role": "researcher",
  "pod": "my-market-scan",
  "name": "my-market-scan researcher",
  "codebase": "",
  "workspaceKind": "workdir",
  "workDir": "/home/user/.docket/workspaces/pods/my-market-scan/workdir",
  "stack": "",
  "model": "anthropic/claude-sonnet-4-6",
  "description": "quarterly competitive landscape scan",
  "created": "2026-07-30T12:08:17-03:00",
  "sessionKey": "agent:my-market-scan:default",
  "projectKey": "default",
  "blueprint": "research",
  "templateVersion": "2"
}
```
