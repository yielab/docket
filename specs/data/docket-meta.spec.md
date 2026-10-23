# Agent Metadata (.docket-meta.json) Specification

**Version**: 5.1.0
**Status**: Complete. Every field below is written by a live path and read by one; the Lead's file
also carries the pod's settings (see "Pod settings on the Lead"), which Phase 46 moves out.
**Last Updated**: 2026-10-23

## Purpose

This specification defines the schema for `.docket-meta.json`, the per-agent metadata file that
docket treats as the source of truth for an agent's identity and configuration. One file exists per
agent at `$DOCKET_HOME/workspaces/projects/<agent-id>/.docket-meta.json`. It is read and written
through the typed `meta_get` / `meta_set` helpers over docket's atomic JSON store.

## Scope

This specification covers:

- The fields stored in `.docket-meta.json`, their types, and their meaning
- Which fields are required versus optional
- Validation rules applied on write by `meta_set`
- The pod settings that are stored on the pod Lead's file today

It does NOT cover docket's fleet registry (`fleet.json`): agent registration, channel bindings,
gates and isolation flags, and the machine-wide default model (see agent-lifecycle.spec.md and
security-gates.spec.md). **No field in this file is mirrored anywhere else.** Every field here,
including `model` and `sessionKey`, is docket's single source of truth for that value;
`fleet.json` does not carry `model` or `sessionKey` at all.

## Structure

`.docket-meta.json` is a single **flat JSON object** at the root of each agent's workspace. Pod
members use the compound id `<pod>-<role>` (for example `myapp-implementer`; a second member of the
same role is `<pod>-<role>-<n>`).

Every value is a JSON scalar (string, number, boolean) or `null`: there are no nested objects or
arrays. A list-valued pod setting is stored as a comma-joined string.

The documented field set is the one every writer targets, backed by the `AgentMeta` model, but the
model is **not closed**: it declares `extra="allow"` so unknown keys round-trip. `meta_set` therefore
does not reject an undeclared key name. The pod settings (see below)
rely on this: none of them is an `AgentMeta` attribute.

Pod member files are written by provisioning (`docket init`, `docket init --from`, `docket pod
add`, `POST /pods`). They carry every row of the agent table that applies to the member's role and
blueprint.

## Schema

The tables below are the authoritative source for the field set. `AgentMeta` validates every
`meta_set` write.

### Agent fields

| Field | Type | Enum / constraints | Required | Written by | Description |
|-------|------|--------------------|----------|------------|-------------|
| `kind` | enum | `project` | Yes (the only field `AgentMeta` requires) | provisioning | Always `project` |
| `scope` | enum | `project` | No (`AgentMeta` defaults to `project`) | pod provisioning | Whose data the agent may see: `project` is pod-scoped, never shared across projects. Absent means `project`; nothing derives it from `kind` or `role` |
| `role` | string | none | pod members | provisioning | Pod-member role (`lead`, `implementer`, `reviewer`, `tester`, or a blueprint's role such as `researcher`) |
| `pod` | string | pod id | pod members | provisioning | The pod this member belongs to. Read first by `docket status`, the cwd-to-pod lookup and `pod_of`, which fall back to parsing the `<pod>-<role>` id only when it is absent. **Not an `AgentMeta` attribute**; it round-trips through `extra="allow"` |
| `name` | string | none | Yes (written always; `AgentMeta` defaults it to empty) | provisioning | Human-readable display name |
| `codebase` | string | path | pod members | provisioning | The project path with `~` expanded; empty for a `workdir`-kind member. `docket init` stores it absolute (a relative path is taken from the current directory) and refuses one that is not an existing directory; `POST /pods` stores it as given |
| `workspaceKind` | enum | `codebase` or `workdir` | No (absent means `codebase`) | provisioning (blueprints with a working directory) | Whether the workspace is anchored to a codebase or a plain working directory. Only ever written as the literal `workdir` |
| `workDir` | string | path | `workdir`-kind members | provisioning | The pod's shared working directory, stored as given. Present only with `workspaceKind: workdir`, and then `codebase` is `""` |
| `blueprint` | string | none | No | provisioning | Name of the pod blueprint that provisioned the member (`software`, `research`, `content`, `ops`, `agentic-product`). |
| `stack` | string | none | No | provisioning | Comma-separated detected stack (`Docker,git`), `unknown` when a codebase shows none, and empty for a `workdir`-kind member (nothing to inspect) |
| `model` | string | `provider/model-id` | Yes (written always; `AgentMeta` defaults it to empty) | provisioning, `docket setup model` | Provider-qualified model id. Provisioning resolves it from the role-to-model policy; re-resolving the policy rewrites it |
| `description` | string | none | No | provisioning | Free-text purpose; empty when none was given |
| `created` | string | ISO-8601 UTC | pod members | provisioning | Creation timestamp |
| `sessionKey` | string | `agent:<pod>:<projectKey>` | Yes (written always) | provisioning | Base session scope key. Pod dispatch derives its per-turn session keys itself and does not read this value |
| `projectKey` | string | none | Yes (written always) | provisioning | Last component of `sessionKey` (default `default`) |
| `budgetUsd` | number or numeric string | at least 0 | No | `docket pod set` / `unset` (Lead), provisioning (Lead, when a budget was requested) | Per-pod spend cap in USD, read from the Lead only. `pod set` writes a JSON number; provisioning with a requested budget writes it as a string (`"20.0"`). Both read back the same. `pod unset` stores `null`, which reads as the default (`0`, unlimited). See "Pod settings on the Lead" |
| `paused` | bool | none | No | dispatch budget gate (sets `true`); `docket pod set budgetUsd <n>` and `docket run --resume` (set `false`) | Whether the pod is paused. Set on the Lead when the pod's usage-derived cost estimate reaches `budgetUsd`; dispatch then refuses every further claim for that pod and traces `paused_refused`. Read through `AgentMeta.coerce_paused` (a real `bool`, tolerant of a stringified `"true"`/`"false"`), never a raw string compare |
| `pausedReason` | string | none | No | same as `paused` | Human-readable pause reason. The only writer sets the literal `"budget"`; the clearing writers set `""` |
| `portRangeStart` | number | integer at least 0 | No (implementer only) | provisioning | First port of the pod's reserved range. Absent on non-implementers. A shared locked allocation gives concurrently created pods distinct ranges |
| `portRangeCount` | number | integer above 0 | No (implementer only) | provisioning | Number of ports in the same allocation as `portRangeStart` |
| `scratchDir` | string | absolute path | No (implementer only) | provisioning | Pod-isolated scratch directory. Its lifecycle is coupled to provisioning: a failed attempt removes a scratch or working directory only when that attempt created it, preserving pre-existing contents and a successful same-pod directory |
| `verifyCmd` | string | shell command, at most 2000 characters, no NUL or newline | No (implementer only) | `docket pod add --verify`, `docket pod set verify <cmd> --member <id>`, `docket pod unset verify --member <id>` (removes the key), `POST /pods` | Shell command run mechanically after each Implementer hop. A non-zero exit blocks done and emits a `verification_failed` trace event. Absent or empty means skip, unless the pod's `requireVerify` is true (the task then fails). Per member, not a pod setting |
| `templateVersion` | string | none | Yes (written always) | provisioning | Template schema version the member was created with (`5`); `docket pod reset` restamps it when it rebuilds the member's files |

The pod-wide settings that live on the Lead (`budgetUsd`, `turnTimeoutS`, `verifyTimeoutS`,
`maxReworkCycles`, and the rest) are listed in their own table below.

### Pod settings on the Lead

The pod's Lead file carries the pod's dispatch configuration as extra keys. They are validated
by `PodSettings` on every read and by `PodSettings.coerce` on every `docket pod set`, never by
`AgentMeta`. **Only the Lead's value is consulted.** A key that is absent, `null`, or `""` reads as
its default. A *present but malformed* stored value is never replaced by the default: loading the
settings raises an error naming the key, and dispatch refuses (`docket pod show` and
`docket pod set` surface the same message).

`docket pod set <key> <value>` validates, then writes; `docket pod unset <key>` writes `null`
(the key stays, and reads as the default). A key outside this table is refused with the valid keys
listed. Each write is audited (`pod.config`).

| Key | Stored as | Default | Constraints and meaning |
|-----|-----------|---------|-------------------------|
| `budgetUsd` | number | `0` (no cap) | At least 0. A positive cap pauses the pod when the estimate reaches it (`paused`). Setting or unsetting it re-queues the pod's blocked tasks and clears `paused` and `pausedReason` |
| `maxReworkCycles` | integer | `1` | At least 0. Bounded rework for a Reviewer's REQUEST-CHANGES verdict: `1` allows exactly one rework cycle before a second REQUEST-CHANGES fails the task, `0` disables rework |
| `turnTimeoutS` | integer | none | Above 0. Pod-wide agent-turn timeout in seconds. Unset falls back to the global default (or a serve-wide knob); `docket run --timeout` overrides it |
| `verifyTimeoutS` | integer | none | Above 0. Pod-wide `verifyCmd` timeout in seconds, independent of `turnTimeoutS`; same fallback and override rules |
| `approvalMode` | string | `wait` | `wait`, `park` or `refuse`: whether an unattended hop that needs approval waits, parks durably, or is refused at once. Whether the key is present at all (not its value) decides which caller-scoped default applies |
| `approvalExpiryHours` | integer | `24` | At least 1. How long a parked approval stays live before the fail-closed sweep denies it |
| `inputExpiryHours` | integer | `72` | At least 1. How long an unanswered `input` question stays live |
| `allowCommands` | comma-joined string | none | Exact binary basenames the pod adds to the unattended allowlist. Refused: a path segment, a shell metacharacter, an opaque name (`eval`, `exec`, `source`, `.`, `export`), a high-risk-class binary. A name already on the built-in safe list is accepted and dropped |
| `pipeline` | string | none | sha256 hex digest of the bound pipeline copy docket keeps in the Lead's workspace (`PIPELINE.yaml`), never the operator's file path. Written only by `docket pod set pipeline <file>` after the file validates against the pod's roster; dispatch refuses a copy that no longer hashes to it |
| `schedule` | string | none | An `@every`, `HH:MM` or cron spec. `docket pod set schedule` also writes the pod's entry in `docket-schedules.json`, which is what the scheduler reads; this key mirrors it for display |
| `projectInstructions` | comma-joined string | none | Relative paths inside the pod's codebase composed into each turn's system prompt. Refused: absolute, `~`-relative, or containing `..` |
| `mcpServers` | comma-joined string | none (every configured server) | The exhaustive set of MCP servers this pod's turns load; each name must be in the global catalog or be this pod's own server |
| `deniedTools` | comma-joined string | none | Built-in tool names every role of the pod additionally denies; unknown names are refused |
| `requireVerify` | boolean | `false` | When true, an Implementer hop with no `verifyCmd` fails the task instead of skipping the gate |
| `maxConsultationsPerTask` | integer | `3` | At least 0. How many `consult` questions one task's turn may ask; `0` disables |
| `network` | string | `open` | `open` or `none`. `none` cuts the pod's jailed tool calls off the network; it only narrows the machine setting |
| `readOnly` | string | `""` | `""` (every machine read-only grant), `none`, or comma-joined absolute paths that must already be machine grants; it only narrows |
| `prepare` | string | `""` | The install command a task's fresh worktree runs before its first hop; `none` turns preparation off, `""` leaves the choice to the worktree's lockfile. One line, at most 1000 characters |
| `protects` | comma-joined string | none | Path globs a task may not change without a person; they add to the defaults and never remove one |
| `profile` | string | `attended` | `attended` or `lights-out`; a pod may only move toward stricter than the machine's recorded profile |

Three more keys are **recorded by `docket pod update`**, are never operator-settable (`docket pod
set` and a `pod.yaml` `settings` mapping both refuse them), and are read alongside the table above:
`configSource` (the absolute directory last applied), `configDigest` (sha256 of that directory's
contents, lowercase hex or empty), and `exporters` (comma-joined exporter names the applied recipe
named).

## Single-source contract

Each field has exactly one home: this file, written by docket alone. There is no second registry to
drift from. Registration lives in `fleet.json` (agent ids, bindings, gates), which holds neither
`model` nor `sessionKey`. A single-writer JSON file that docket alone touches cannot drift from
itself.

## Runtime environment injection

`portRangeStart`, `portRangeCount` and `scratchDir` are not passive bookkeeping. For every
Implementer hop with `portRangeStart` set, dispatch passes `DOCKET_PORT_BASE`, `DOCKET_PORT_COUNT`
and `DOCKET_SCRATCH_DIR` into that hop's subprocess environment, layered on top of the parent
process's environment, which is never mutated. An Implementer with no allocated range, and every
non-Implementer hop, receives no override. The same values are also written into the Implementer's
`TOOLS.md` as readable context, but the subprocess environment is what an agent can rely on
programmatically. See pod-dispatch.spec.md for the per-hop contract.

## Validation

`meta_set` merges the new value into the record, validates the whole record against `AgentMeta`,
and only then writes (atomically, under a lock):

- **Unknown field**: accepted, not rejected (`extra="allow"`). A typo in a key name is written
  silently. No test pins stricter behaviour.
- **Type mismatch on a declared field**: for example `budgetUsd` given a non-numeric string,
  `paused` given a non-boolean string, or `verifyCmd` given a number. A validation error is
  raised and nothing is written.
- **Enum violation**: `kind`, `scope` or `workspaceKind` outside its enum raises a validation error.
- `AgentMeta` does not range-check `budgetUsd`; the at-least-0 rule is enforced by `PodSettings`
  (so by `docket pod set` and by every dispatch read).

`meta_get` on a missing file returns the caller's default. `meta_set` on an agent
with no file fails validation (`kind` is required), so a missing agent is never read as an empty
object.

## Field rules

- `kind` MUST be `project`; `scope`, when present, MUST be `project`. No shared agent exists.
- `workspaceKind`, when present, MUST be `codebase` or `workdir`; absent means `codebase`.
- A `workdir`-kind member MUST have an empty `codebase` and a `workDir`; `workDir` is present only
  with `workspaceKind: workdir`.
- `model` is written as a provider-qualified id (for example `anthropic/claude-sonnet-4-6`).
- `sessionKey` is written as `agent:<pod>:<projectKey>`, so its last component equals `projectKey`;
  provisioning writes both in this one file.
- `budgetUsd`, when written through `docket pod set`, MUST be a non-negative number.

## Examples

The Lead of a software pod created by `docket init --pod full` in `~/Sites/myshop` (`codebase`
kind, so `workspaceKind` and `workDir` are absent):

```json
{
  "kind": "project",
  "scope": "project",
  "role": "lead",
  "pod": "myshop",
  "name": "myshop lead",
  "codebase": "/home/user/Sites/myshop",
  "stack": "unknown",
  "model": "anthropic/claude-haiku-4-5",
  "description": "",
  "created": "2026-10-22T21:34:29.210789+00:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "templateVersion": "5",
  "blueprint": "software"
}
```

The same Lead after `docket pod set budgetUsd 5`, `docket pod set allowCommands foo` and
`docket pod set maxReworkCycles 2` (the budget write also clears the pause fields), and then once
the budget gate has paused the pod (`paused` and `pausedReason` change):

```json
{
  "kind": "project",
  "scope": "project",
  "role": "lead",
  "pod": "myshop",
  "name": "myshop lead",
  "codebase": "/home/user/Sites/myshop",
  "stack": "unknown",
  "model": "anthropic/claude-haiku-4-5",
  "description": "",
  "created": "2026-10-22T21:34:29.210789+00:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "templateVersion": "5",
  "blueprint": "software",
  "budgetUsd": 5.0,
  "paused": true,
  "pausedReason": "budget",
  "allowCommands": "foo",
  "maxReworkCycles": 2
}
```

The pod's Implementer, with its port range, scratch directory and a verify command set by
`docket pod set verify true --member myshop-implementer`:

```json
{
  "kind": "project",
  "scope": "project",
  "role": "implementer",
  "pod": "myshop",
  "name": "myshop implementer",
  "codebase": "/home/user/Sites/myshop",
  "stack": "unknown",
  "model": "anthropic/claude-sonnet-4-6",
  "description": "",
  "created": "2026-10-22T21:34:29.211614+00:00",
  "sessionKey": "agent:myshop:default",
  "projectKey": "default",
  "templateVersion": "5",
  "portRangeStart": 3000,
  "portRangeCount": 100,
  "scratchDir": "/home/user/.docket/workspaces/pods/myshop/.scratch",
  "blueprint": "software",
  "verifyCmd": "true"
}
```

A `research`-blueprint Lead (`workdir` kind, see pod-blueprints.spec.md) created by
`docket init my-scan ~/work/scan --blueprint research`; the blueprint's default budget is stored as
a string:

```json
{
  "kind": "project",
  "scope": "project",
  "role": "lead",
  "pod": "my-scan",
  "name": "my-scan lead",
  "codebase": "",
  "stack": "",
  "model": "anthropic/claude-haiku-4-5",
  "description": "",
  "created": "2026-10-23T00:15:18.292472+00:00",
  "sessionKey": "agent:my-scan:default",
  "projectKey": "default",
  "templateVersion": "5",
  "blueprint": "research",
  "workspaceKind": "workdir",
  "workDir": "/home/user/work/scan",
  "budgetUsd": "20.0"
}
```

## Phase 46 amendments

Phase 46 (ADR 0030) moves the pod's settings off the Lead's file. Until then the requirements above
stand as written; these change when the cards land.

- **P46-11** (pod settings move to `pods/<pod>/settings.json`): the whole "Pod settings on the Lead"
  section (every key of the table, the "only the Lead's value is consulted" rule, the
  absent/`null`/malformed read rules, `unset` writing `null`, the recorded keys `configSource`,
  `configDigest`, `exporters`), and the pod-level rows `budgetUsd`, `paused`
  and `pausedReason` of the agent table (the budget pause is stored on the Lead). `verifyCmd` is a
  per-member field and is not part of `PodSettings`; whether it moves is that card's decision.
- **P46-1** (module layout): the "Implementation" section below is rewritten by the codemod; no
  requirement changes.

## Implementation

- `src/docket/core/models.py`: `AgentMeta` (`coerce_paused`), `AgentKind`, `AgentScope`, `WorkspaceKind`
- `src/docket/core/fleet.py`: `meta_get`, `meta_set`, `set_model_both`
- `src/docket/core/pod.py`: `PodSettings` (`KEYS`, `RECORDED_KEYS`, `load_for`, `coerce`, `value_and_source`), `PodSettingsError`, `pod_of`, `member_id`, `bound_pipeline_path`
- `src/docket/core/pod_provisioning.py`: pod-member provisioning, `POD_TEMPLATE_VERSION`, `validate_verify_cmd`, `parse_budget_usd`
- `src/docket/cli/_agents.py`: `docket init`, `docket init --from`
- `src/docket/cli/_pod.py`: `docket pod set` / `unset` / `add`, `verifyCmd` setters
- `src/docket/cli/_run.py`: `docket run --resume` (clears the pause)
- `src/docket/core/dispatch.py`: pod-settings readers, the budget gate, `hop_env` (port and scratch injection)
- `src/docket/core/models_policy.py`: model re-resolution (`docket setup model`)
- `src/docket/edges/store.py`: atomic JSON read and write
