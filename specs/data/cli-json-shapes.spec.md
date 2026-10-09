# CLI JSON Output Shapes

**Version**: 1.27.0
**Status**: Complete
**Last Updated**: 2026-10-08

## Purpose

Define the exact JSON shapes docket emits when a read command is run with `--json`, so that
scripts and dashboards can consume docket output as a stable contract. The shapes are produced by
the CLI layer (`src/docket/cli/`) and the serve loop (`src/docket/serve.py`) and are verified
against that code.

## Scope

Covers every command that supports `--json` output: `list`, `status` (and
`status --history`), `doctor`, `inbox`, `task list`/`task show <ref>`/`task trace <ref>`,
`pod show`, `pod show <member>`, and the `serve` HTTP endpoints. `docket
audit --json` is a raw JSONL passthrough, owned by audit.spec.md. It does **not** cover
human-readable (Rich) output or third-party protocol payloads.

## Structure

All `--json` output is a **bare JSON object or array — there is no envelope wrapper.** There is no
`{success, data, error, version}` outer object; consumers parse the returned object directly. Two
structural rules hold everywhere:

- **Bare values.** A command returns its object/array directly (e.g. `{"agents": [...]}`), never
  wrapped in a status envelope.
- **camelCase keys.** Every key is camelCase (`costUsd`, not `cost_usd`) — see Validation.

## Schema

### `docket setup --fix --json`

```json
{
  "healthy": "boolean",
  "issues":  "number",
  "checks": {
    "python3":     { "ok": "boolean", "path": "string | null" },
    "fleet":       "{ ok: true, path, agents, bindings } | { ok: false, path, error }",
    "agents":      "array of { id, ok, tg, issues }",
    "dispatchLedger": "array of { project, ok, missingFromLedger, staleInLedger }",
    "budget":      "array of agent budget status objects",
    "runaway":     "array of agent runaway detection objects",
    "keyHygiene":  {
      "keys": "array of { name, state, detail }",
      "missingForAgents": "array of { agent, model, needsKey }"
    },
    "providerCatalog": {
      "ok": "boolean",
      "problems": "array of { name, reason } (malformed global provider documents)"
    },
    "notifications": {
      "ok": "boolean (false when at least one project agent exists and `delivering` is empty)",
      "delivering": "array of channel names: enabled, `notify`-capable, dialect not `console`"
    },
    "securityGates": {
      "toolCallGate": "always-on",
      "isolation": "string ('off (default)' | 'on' | 'off')",
      "sandboxBackend": "string ('bwrap' | 'docker' | 'none')",
      "dockerImageHasGit": "boolean | null (null unless the backend is docker and isolation is on; false when the DOCKET_SANDBOX_IMAGE probe finds no git or no local image)",
      "network": "string ('open' | 'none'; the global mode)",
      "unjailedMcpServers": "array of { name, pod } (empty array if none)"
    },
    "templateDrift": "array of { id, agentVersion, currentVersion, ok }"
  }
}
```

### `docket status --json` / `docket status --all --json`

`docket status --json` (run inside a pod, or with `--pod`) emits one pod object;
`--all --json` emits `{"projects": [<pod object>, ...]}` plus the fleet inventory:

```json
{
  "id":          "string (pod id)",
  "path":        "string (codebase or workDir; may be empty)",
  "status":      "ready | active | waiting | attention | degraded (waiting: a task is waiting_approval or waiting_input)",
  "memberCount": "number",
  "isolation":   "string (the sandbox posture: 'on (<backend>, network <open|none>)' or '<off (default)|off>; <backend|no backend> found, network <open|none>')",
  "members":     "array of { id, role, status: ready | missing }",
  "tasks": {
    "pending": "number", "running": "number", "waitingApproval": "number",
    "waitingInput": "number (parked consult or input-step questions)",
    "failed": "number", "completed": "number", "approvedReady": "number"
  },
  "usage":       "{ input, output (measured tokens), estimateUsd (a labelled estimate) }",
  "outcomes":    "{ success, failure, aborted, meanMs | null, p95Ms | null }",
  "lastRun":     "{ id, state, finishedAt } | null",
  "running":     "boolean (docket start is running)"
}
```

`--all --json` also carries these top-level fields beside `projects`:

```json
{
  "timestamp":    "string (ISO-8601 UTC, e.g. 2026-07-30T12:00:00Z)",
  "channels":     "array of strings (channels present in Docket fleet bindings)",
  "agents":       "array of agent objects (below)",
  "totalCostUsd": "number"
}
```

Each agent object:

```json
{
  "id":           "string",
  "name":         "string",
  "kind":         "project",
  "model":        "string",
  "registered":   "boolean",
  "bindings":     "array of {channel, peerId}",
  "lastActivity": "string (YYYY-MM-DD) | \"never\"",
  "costUsd":      "number"
}
```

`status --history --json` emits `{"history": [{date, turns, input, output, costUsd}, ...]}`;
the list is empty against the production driver (cost-tracking.spec.md, "Known gap").

### `docket inbox --json`

The `InboxView` shape `GET /inbox` returns (`needsYou`, `failed`, `doneSince`, `running`,
`next`), except that every item also carries `state`
(`needs_approval | needs_answer | blocked | failed | done | running | approved_ready`) and
`command` (the one `docket ...` command that moves it forward). A pending task whose approval
was granted is listed in `needsYou` with `state: "approved_ready"` and `command: "docket run
--pod <pod>"`. The output is plain JSON with no escape codes.

### `docket task list --json`

```json
{
  "pod": "string",
  "tasks": [
    {
      "id":          "string (task id)",
      "priority":    "high | normal | low",
      "status":      "string (pending | in_progress | waiting_input | waiting_approval | blocked | failed | done | cancelled)",
      "costUsd":     "number | null",
      "description": "string",
      "worktree":    "string (absolute path) | null"
    }
  ]
}
```

`worktree` is the recorded task worktree directory, or `null` for a task that has none (ran in
place, not yet claimed, or pruned). Queue order.

### `docket task show <ref> --json`

```json
{
  "pod":      "string",
  "task":     "one task list item, with worktree replaced by the object below or null",
  "evidence": "the evidence-v1 document of docs/contracts/evidence-v1/schema.json",
  "runs":     "array of run records (below)",
  "corrections": "array of corrections-ledger records for this task",
  "interruptions": [{ "kind": "string", "description": "string", "detail": "object" }]
}
```

`task.worktree` is `{ "path", "branch", "baseCommit", "diff", "merge" }` (`diff` and `merge` are
the exact shell commands) or `null`. Each run record carries the run registry fields:

```json
{
  "id":         "string (run-<uuid4>)",
  "source":     "cli | webhook | schedule | sweep | mcp",
  "project":    "string",
  "state":      "queued | running | waiting_input | waiting_approval | succeeded | failed | cancelled",
  "taskIds":    "array of strings",
  "error":      "string",
  "created":    "string (ISO-8601)",
  "startedAt":  "string (ISO-8601) | null",
  "finishedAt": "string (ISO-8601) | null",
  "variables":  "object",
  "cancellation": "{ requestedAt, observedAt, stoppedAt, reason, source } | null"
}
```

### `docket task trace <ref> --json`

`{ "pod": "string", "events": [ <trace record>, ... ] }` in file order; the records are the
trace-store records (`trace-store.spec.md`).

### `docket pod show --json`

A bare object: the pod as it will run. Composes existing resolvers only and writes nothing.

```json
{
  "pod":     "string",
  "members": [
    {
      "id":        "string",
      "role":      "string",
      "model":     { "value": "string (provider/model-id)", "source": "policy | pod overlay" },
      "workspace": "string (absolute path)",
      "verifyCmd": "string (empty when none; only an implementer has one)"
    }
  ],
  "settings": {
    "<key in core.pod.PodSettings.KEYS>": { "value": "the effective value", "source": "\"set\" | \"default\"" }
  },
  "approvalMode": {
    "effective": "wait | park | refuse (core.dispatch.pod_approval_mode for this caller)",
    "source":    "set | unset"
  },
  "pipeline":     { "source": "string" },
  "network":      { "mode": "open | none", "scope": "default | global | pod" },
  "configSource": "string (absolute directory the pod was last applied from; empty when never applied)",
  "configDigest": "string (sha256 hex of that directory's applied files; empty when never applied)",
  "drift":        "yes | no | \"\" (empty when there is no recorded source or the directory is gone)"
}
```

An unset `approvalMode` resolves per caller: `wait` on a terminal, `park` without one. A stored
value that fails validation (e.g. a hand-edited `.docket-meta.json`) prints an error to stderr
naming the offending key and exits 1, with nothing on stdout, instead of showing that key's
default. A pod that does not exist exits 1.

### `docket setup export list --json`

A JSON array, one object per catalog exporter (built-in + global, nearest-wins by name),
sorted by name. `state` is `core.exporter.activation_state`'s pure classification; a present
credential never flips it to `"enabled"` by itself -- `enabled` in the underlying document
must also be `true`.

```json
[
  {
    "name":        "string",
    "dialect":     "otlp-http",
    "state":       "enabled | needs credential | disabled | unreachable",
    "credentials": "array of credential names this exporter's auth declares (may be empty)",
    "scope":       "built-in | global"
  }
]
```

### `docket pod show <member> --json`

A bare object: the effective configuration a real dispatch turn would use for
*member*, with the source that set each value. Composes existing resolvers only
(model policy, the prompt composer, role/tool denial, the guardrail policy engine,
`PodSettings`, and the pipeline resolver) — it writes nothing and adds no new
configuration surface.

Three resolved values — the role archetype, each applicable policy, each loaded MCP
server, and each denied tool — additionally carry a `scope`: `"built-in"` (a shipped
archetype/starter role), `"global"` (the operator's `~/.docket` overlay), or `"pod"`
(this pod's own `config/` overlay or `.docket-meta.json` setting). A tool denied by
both this pod's `deniedTools` setting and its role's own archetype reports `"pod"`
(the more specific override). `tools.mcpServers`/`tools.denied` list only the
servers/names a live turn would actually see — a pod's own `mcpServers` selection
excludes every other configured server, never merely relabels it.

`skills` carries its own, three-value scope vocabulary — `"codebase"` (this agent's own
codebase root's `.docket/skills/`), `"pod"` (this pod's own `config/skills/`), or
`"global"` (the operator's `~/.docket/skills/`) — nearest wins by name, and only the
winning scope's skill is listed (P31-6, ADR 0013 §3 rule 8).

```json
{
  "id":        "string",
  "workspace": "string (absolute path of the member's workspace)",
  "role":      "string (pod role; may be empty)",
  "roleScope": "built-in | global | pod | \"\" (role not found in the live registry)",
  "pod":       "string (project this agent belongs to; empty for a non-pod agent)",
  "model":     { "value": "string (provider/model-id)", "source": "policy | pod overlay" },
  "endpoint": {
    "baseUrl":            "string (may be empty if unresolved)",
    "ready":              "boolean",
    "contextWindowTokens": "number | null",
    "maxOutputTokens":    "number | null",
    "issue":              "string (empty when ready)"
  },
  "provider": {
    "name":       "string (catalog entry; the bare prefix when absent from the catalog)",
    "scope":      "built-in | global | \"\" (absent from the catalog)",
    "dialect":    "string (openai-chat)",
    "baseUrl":    "string | null",
    "credential": { "name": "string (may be empty)", "source": "override | env | store | none" },
    "model":      { "id": "string", "contextWindow": "number | null", "maxTokens": "number | null", "source": "row | none" }
  },
  "network":   { "mode": "open | none", "scope": "default | global | pod" },
  "prompt": {
    "budgetTokens": "number",
    "budgetSource": "env | window | default",
    "sections": [
      { "name": "string", "bytes": "number", "status": "full | truncated | omitted" }
    ]
  },
  "tools": {
    "allowed": "array of built-in tool names, after role and pod denial",
    "denied":  [ { "name": "string", "scope": "built-in | global | pod" } ],
    "mcpServers": [
      { "name": "string", "kind": "read | write", "scope": "global | pod", "isolate": "boolean (true = jailed, false = unjailed)" }
    ]
  },
  "policies": [
    {
      "id": "string", "hook": "pre_input | pre_tool_call | pre_output", "action": "string",
      "scope": "global | pod"
    }
  ],
  "pipeline":    "{ source: string } | null (null for a non-pod agent)",
  "podSettings": "same shape as `docket pod show --json`'s `settings` object | null (null for a non-pod agent)",
  "projectInstructions": {
    "files":  "array of relative paths (empty when there is nothing to compose)",
    "source": "set | default | \"\" (default: the codebase root's own AGENTS.md, unset and present; set: an explicit PodSettings.projectInstructions list, which replaces the default entirely; \"\": neither)"
  },
  "skills": [
    { "name": "string", "scope": "codebase | pod | global" }
  ],
  "exporters": [
    {
      "name":             "string",
      "dialect":          "otlp-http",
      "state":            "enabled | needs credential | disabled | unreachable",
      "scope":            "built-in | global",
      "credentialSource": "env | store | mixed | none",
      "privacy": {
        "label":   "minimal | actions | conversation | full | custom",
        "classes": "array of core.privacy.CONTENT_CLASSES names this exporter shares"
      },
      "exported":         "number", "dropped": "number", "failed": "number",
      "lastError":        "string (empty when there has been none)"
    }
  ],
  "configSource": "string (absolute directory the pod was last applied from; empty when never applied)",
  "configDigest": "string (sha256 hex of that directory's applied files; empty when never applied)",
  "drift":        "yes | no | \"\" (empty when there is no recorded source or the directory is gone)"
}
```

A name that is not a member of the pod prints an error to stderr and exits 1, with nothing on stdout.
A pod member with an invalid stored `PodSettings` value (e.g. a hand-edited
`.docket-meta.json`) refuses the same way `docket pod show` does — an
error naming the offending key, exit 1, nothing on stdout — rather than reporting a
guessed default.

The human-readable (non-`--json`) rendering prints `scope` nowhere (JSON-only) and keeps the
`tools`/`policies` names/columns and order; it adds one `Provider:` line under the model,
one `Project instr.:` line reporting `projectInstructions` (`AGENTS.md (default)` /
`<files> (set)` / `none`), one `Skills:` line listing each `name (scope)` (or `none`), one
`Exporters:` block listing each `name dialect state (scope)` (or `none enabled`), and,
when a source is recorded, one `Config source:` line carrying the digest prefix and `drift`.

### `docket pod apply --json` / `pod roles --json` / `pod policies --json` / `pod recipes --json`

```json
{
  "pod apply": {"items": [{"kind": "role|policy|plugin|skill|mcp-server|member|pipeline|setting", "name": "string", "action": "add|replace|skip", "note": "string"}]},
  "pod roles": "array of {name, source, scope, modelClass, gate, description}; with a NAME, the archetype's wire object plus \"source\"",
  "pod policies": "array of {id, hook, action, description}; with --plugins, {\"policies\": that array, \"plugins\": array of {name, scope, file, sha256}}; with an ID, the policy's own JSON",
  "pod recipes": "array of {name, scope, brings, directory, description, roles, policies, members, pipeline, plugins, skills, settings, mcp_servers, unjailed_mcp_servers}; with a NAME, one such object plus \"readme\""
}
```

`pod apply --dry-run --json` prints the plan and writes nothing; `pod apply --json` with no argument
exits 1. Output is Rich-free on stdout.

### `docket start` HTTP endpoints

| Endpoint | Content-Type | Shape |
|----------|-------------|-------|
| `/status.json` | `application/json` | the `status --all --json` inventory shape plus a top-level `apiVersion` and per-agent `scope`/`budgetUsd` (full schema: `specs/data/serve-read-api.spec.md`) |
| `/health` | `application/json` | `{"status":"ok"}` |
| `/metrics` | `text/plain` | Prometheus text format (see below) |
| `/runs` | `application/json` | One run record per entry, as in `task show --json` (auth required; see `specs/data/serve-read-api.spec.md`) |
| `/runs/<id>` | `application/json` | One run record, as in `task show --json` (auth required) |

Prometheus metrics emitted by `/metrics`:

```
docket_agents_total <N>
docket_agent_cost_usd{agent="<id>",model="<model>"} <F>
docket_agent_turns_total{agent="<id>"} <N>
docket_cost_usd_total <F>
docket_approvals_pending_total <N>
docket_tool_calls_total{decision="<allow|ask|deny>"} <N>
docket_policy_hits_total{policy_id="<id>",hook="<hook>",action="<action>"} <N>
docket_approvals_total{channel="<channel>",outcome="<granted|denied>"} <N>
docket_turn_duration_seconds_sum <F>
docket_turn_duration_seconds_count <N>
```

The last five are the guardrail/loop metrics; their semantics and durability caveats are owned by
`specs/data/serve-read-api.spec.md`.

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

The Python suite (e.g. `tests/integration/test_list_info_cost_commands.py`,
`tests/unit/test_serve.py`) asserts each shape field-by-field, so a shape change here that isn't
reflected in code fails CI.

## Examples

Every schema block above is a complete example of its command's output.

## Changelog

### Version 1.27.0 (2026-10-08)

- `docket status --json` `tasks.waitingInput` counts parked `waiting_input` tasks and a pod holding one is `waiting`; `isolation` reports the sandbox posture `setup sandbox status` reads instead of a static string.

### Version 1.26.1 (2026-10-08)

- Command names follow ADR 0022.

### Version 1.26.0 (2026-10-08)

- `docket pod roles`, `pod policies` and `pod recipes` print JSON with `--json`; `pod apply --json` prints the plan's items. `pod recipes` keeps the shape `recipes list|show --json` had.
### Version 1.25.0 (2026-10-08)

- Phase 39 (P39-10): `docket info --json` and `docket pod <p> config get --json` are removed.
  `docket pod show --json` is new (members with model source and `verifyCmd`, every setting with
  its source, the resolved `approvalMode`, `pipeline`, `network` and the config-of-record
  fields). `docket config explain <agent> --json` becomes `docket pod show <member> --json`:
  same object, plus `workspace`, with `model.source` now `policy | pod overlay` (the per-agent
  pin is gone).
### Version 1.24.0 (2026-10-08)

- `docket task list --json` and `docket task show <ref> --json` replace `runs list --json` and
  `runs show <id> --json`; each task carries `worktree` (a path or `null` in the list, an object
  with the diff and merge commands in `show`). `task trace --json` is `{pod, events}`.

### Version 1.23.0 (2026-10-07)

- `status --all --json` carries the inventory `snapshot` printed (`timestamp`, `channels`, `agents`, `totalCostUsd`); pod objects gain `usage`, `outcomes`, `lastRun`, `running` and `tasks.approvedReady`; `status --history --json` replaces `cost --history --json`; `inbox --json` items carry `state` and `command`. `cost --json`, `cost --history --json` and `snapshot` are removed.
- Removed the `docket list --json` shape and its example with the command; the member inventory
  is read from `status --all --json`. `docket info <id> --json` is unchanged.

### Version 1.22.2 (2026-10-07)

- `runs list|show --json` `state` also admits `waiting_input | waiting_approval` (a parked
  dispatch is never `succeeded`, pod-dispatch.spec.md 6.33.0).

### Version 1.22.1 (2026-10-07)

- The role→model policy keys named by `docket models` (and the `role` an agent's model resolves
  through) are archetype names (`lead`, `implementer`, ...), per model-profiles.spec.md 3.0.0; no
  JSON shape changes.

### Version 1.22.0 (2026-10-06)

- `doctor --json` `securityGates.isolation` reads `off (default)` with no recorded choice
  (isolation is opt-in, ADR 0021); `dockerImageHasGit` is probed only while isolation is on.

### Version 1.21.0 (2026-10-06)

- `doctor --json` gains `checks.notifications {ok, delivering}`: the enabled channels that
  deliver somewhere other than the console, `ok: false` when a project agent exists and none
  does (operator-loop.spec.md Notifications 17).

### Version 1.19.0 (2026-10-05)

Waves 89-90 close (W89-10): the entries below were Unreleased and are now this version.

- `doctor --json` `securityGates.dockerImageHasGit`: boolean or null, the docker jail image's `git` probe.
- `doctor --json` `securityGates.unjailedMcpServers`: array of {name, pod} for servers with isolate: false.
- `config explain --json` `tools.mcpServers[].isolate`: boolean field added to each server.
- `recipes show --json` and `recipes list --json` gain `unjailed_mcp_servers` field.

### Version 1.18.0 (2026-10-05)

Phase 38 close (P38-9, ADR 0020): the entries below were Unreleased and are now this version.

- `doctor --json` `securityGates.network`; `config explain --json` `network {mode, scope}`;
  `podSettings` gains the `network` key.

### Version 1.17.0 (2026-10-03)

- **Legacy purge.** `doctor --json` drops `checks.fzf`, `checks.modelConfig`,
  `checks.modelRegistry` and `securityGates.approvalRouting`/`routingMode` (the checks behind
  them are deleted); `checks.providerCatalog` (`{ok, problems}`), already emitted but never listed
  here, is added. `snapshot` drops `gateway`; the `/health` row is `{"status":"ok"}` and
  `docket_gateway_up` is gone from the metrics list (serve API version 3). `docket cost --json`
  is unchanged.

### Version 1.16.0 (2026-09-28)

- **`config explain --json` exporters entries.** `privacy` is now `{label, classes}` in place
  of a bare label string.

### Version 1.15.0 (2026-09-27)

- Added `docket exporters list --json`: an array of `{name, dialect, state, credentials,
  scope}`, state from `core.exporter.activation_state`. `docket config explain <agent> --json`
  gains `exporters`: one object per catalog exporter (name, dialect, state, scope, credential
  source, payload mode, and today's health counters) -- global, not per-agent, since an
  exporter has no per-pod scope. The human view gains a matching `Exporters:` block.

### Version 1.14.0 (2026-09-27)

- `docket config explain <agent> --json` gains `skills`: `[{"name": "...", "scope": "codebase" |
  "pod" | "global"}]`, every skill a live turn's `# Skills` prompt section would list, in its own
  three-value scope vocabulary (distinct from the `built-in | global | pod` vocabulary the three
  resolved-value fields above it use). The human view gains a matching `Skills:` line. See
  `agent-loop.spec.md` 1.24.0 for the composition-side discovery (P31-6, ADR 0013 §3 rule 8).

### Version 1.13.0 (2026-09-27)

- `docket config explain <agent> --json` gains `projectInstructions`: `{"files": [...], "source":
  "set" | "default" | ""}`, the effective project-instructions files this pod's turns compose and
  where they came from (P31-5, ADR 0013 §3 rule 7) — `"default"` when `PodSettings.
  projectInstructions` is unset and the codebase root's own `AGENTS.md` exists, `"set"` for an
  explicit list (which replaces the default entirely), `""` for neither. The human view gains a
  matching `Project instr.:` line. See `agent-loop.spec.md` 1.23.0 for the composition-side default.

### Version 1.12.0 (2026-09-27)

- `docket config explain <agent> --json` documents the `provider` block that Phase 29 (P29-6)
  added — catalog name and scope, dialect, base URL, the credential's name and source, and the
  exact model row's limits — and gains `configSource`, `configDigest` and `drift` (Phase 30,
  P30-2, ADR 0012): the directory a pod's team was last applied from, the digest of what was
  applied, and whether that directory has changed since. The human view gains the matching
  `Provider:` and `Config source:` lines.

### Version 1.11.0 (2026-09-26)

- `docket config explain <agent> --json` gains a `roleScope` field and a `scope`
  (`built-in | global | pod`) per policy, per denied tool and per MCP server, naming
  which of the three layers (a shipped archetype, the operator's global overlay, or
  this pod's own `config/`) resolved that value. `tools.denied`/`tools.mcpServers`
  change shape from a bare array of names to an array of objects carrying `scope`
  (and, for `mcpServers`, the server's declared `kind`); `tools.mcpServers` now lists
  only the servers a live turn would actually load for this pod, not every configured
  server, when the pod's own `mcpServers` setting narrows the shared catalog. The
  human-readable rendering is unchanged (P27-8).

### Version 1.10.0 (2026-09-26)

- New `docket config explain <agent> --json` shape (P26-11): a bare object reporting the
  configuration a real dispatch turn actually uses for one agent, with the source that
  set each value — resolved model (`policy`/`pinned`) and endpoint readiness; the
  composed system prompt's per-section byte/fit accounting and static-context budget
  source; built-in tools after role denial plus configured MCP server names; the
  guardrail policies whose `applies_to` covers this role; the effective pipeline and its
  source; and, for a pod member, the same `podSettings` object as `pod <p> config get
  --json` (`null` for a non-pod agent). Read-only — composes existing resolvers, adds no
  configuration surface. An unknown agent id or an invalid stored `PodSettings` value
  refuses (stderr + exit 1) the same way `pod <p> config get` does.

### Version 1.9.0 (2026-09-25)

- New `docket pod <p> config get --json` shape: a bare object keyed by the four pod settings
  (`budgetUsd`/`maxReworkCycles`/`turnTimeoutS`/`verifyTimeoutS`), each an object with its
  effective `value` and `source` (`set` or `default`). An invalid stored value refuses instead
  of showing a default (P26-4).

### Version 1.8.0 (2026-09-25)

- `docket cost <id> --json` is a bare single-agent object in the shape of one `agents` element; an unknown id writes an error to stderr, nothing to stdout, and exits 1 (W37-C6).

### Version 1.7.0 (2026-09-21)

- `docket list --json` / `docket info --json` `budgetUsd` corrected to `number | null` (was emitted as the stored string, or `""`); examples updated to `null`. `docket snapshot` emits `lastActivity: "never"` like `/status.json` (W36-C8).

### Version 1.6.1 (2026-09-18)

- Truth pass against the code: added the undocumented `docket status [--all] --json` shape;
  `info --json` `lastActive` is a date or `"—"`, never relative time or `null`; `cost --json`
  carries `pricingKnown` and `costUsd` is never `null`; `cost --history` scope reads `all agents`;
  `doctor --json` `keyHygiene`, `securityGates` (`approvalRouting`/`routingMode`), `fleet` error
  shape and nullable `modelRegistry.migrated` spelled out per the `_doctor_json_*` helpers;
  snapshot `gateway` is always `inactive`; `/status.json` and `/health` rows and the `/metrics`
  list corrected to what `serve.py` emits. Documentation corrections, not shape changes.

### Version 1.6.0 (2026-08-31)

- W26-C10c records the already-additive cancelled run state and persisted cancellation lifecycle
  in the stable `runs list`/`runs show` JSON shapes, including the `mcp` source and variables field.

### Version 1.5.0 (2026-08-19)

- W21-C1 daemon-free truth pass: corrected `doctor --json` to its Docket-owned `fleet`,
  `modelRegistry`, and `dispatchLedger` checks; removed deleted daemon/config/gateway/drift keys;
  and described snapshot channels as fleet-binding channels. These are documentation corrections
  to the existing output, not shape changes.

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
