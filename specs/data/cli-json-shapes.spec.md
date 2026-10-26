# CLI JSON Output Shapes

**Version**: 4.4.0
**Status**: Complete. The shapes were checked against the commands run with `--json` in a throwaway `DOCKET_HOME` and against their code; shapes that need a live run or a hand-built state (run records, pending approvals) were checked against the code alone.
**Last Updated**: 2026-10-25

## Purpose

Define the JSON docket prints when a command is run with `--json`, so that scripts and dashboards
can consume it as a stable contract. The HTTP routes of `docket start` are not defined here; their
shapes live in `serve-read-api.spec.md` and `operator-api.spec.md`.

## Scope

Covers every command that has a `--json` flag:

- `init` (only its refused-review answer), `status` (also `--all` and `--history`), `inbox`.
- `task list`, `task show <ref>`, `task diff <ref>`, `task trace <ref>`.
- `pod show`, `pod show <member>`, `pod memory list`, `pod update`, `pod roles`, `pod policies`,
  `pod recipes`.
- `setup` (readiness), `setup --fix` (health checks), `setup sandbox [status]`,
  `setup model [list]`, `setup provider list|show`, `setup notify list|show`,
  `setup export list|show|preview`, `setup mcp list`.

`docket log --json` prints the audit file verbatim as JSONL and is owned by `audit.spec.md`. The
spec does not cover human-readable (Rich) output, except where a section says so, or third-party
protocol payloads.

## Structure

All `--json` output is a **bare JSON object or array, with no envelope wrapper.** There is no
`{success, data, error, version}` outer object; consumers parse the returned value directly.
Output is JSON on stdout.

- **Bare values.** A command returns its object or array directly (for example
  `{"agents": [...]}`), never wrapped in a status envelope.
- **camelCase keys.** The keys docket builds are camelCase (`costUsd`, not `cost_usd`); see
  Validation for the documents that keep their own key style.
- **Errors.** A failure prints a message to stderr, leaves stdout empty and exits non-zero, except
  where a section below shows a JSON answer with a non-zero exit.

## Schema

### `docket setup --json`

The first-run readiness report. The exit status is 0 when the model endpoint is usable, else 1.

```json
{
  "ready":  "boolean (the model endpoint piece is ok)",
  "pieces": "array of { name, ok, reason, command }"
}
```

`pieces` is always five entries, in this order: `model endpoint`, `notifications`, `sandbox`,
`shell completion`, `background service`. `reason` explains a piece that is not ok and `command` is
the one command that fixes it; both are strings.

### `docket setup --fix --json`

The health report. The exit status is 0 when `healthy` is true, else 1. `--fix` first tightens
the modes of `fleet.json` and the secrets files and installs the missing baseline policies, then
reports; the report itself repairs nothing (the dispatch-ledger re-sync and the `WORKFLOW_AUTO.md`
re-seed belong to the text report). Each repair line, such as the run that installs the baseline
policies printing `ok Installed <n> baseline policies`, goes to stderr, so stdout is only the
JSON.

```json
{
  "healthy": "boolean (issues == 0)",
  "issues":  "number",
  "checks": {
    "python3":     { "ok": "boolean", "path": "string | null" },
    "fleet":       "{ ok: true, path, agents, bindings } | { ok: false, path, error }",
    "agents":      "array of { id, ok, tg (the bound Telegram peer or \"\"), issues: array of strings }",
    "dispatchLedger": "array of { project, ok, missingFromLedger, staleInLedger } (task ids)",
    "budget":      "array of { id, costUsd, budgetUsd: number | null, pct (only with a budget), ok }",
    "runaway":     "array of { id, turns, costUsd, ok }",
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
      "sandboxBackend": "string ('landlock' | 'seatbelt' | 'docker' | 'none')",
      "sandboxUsable": "boolean (false when the backend is 'none'; with at least one project agent it adds one to `issues`)",
      "dockerImageHasGit": "boolean | null (null unless the backend is docker and isolation is on; false when the DOCKET_SANDBOX_IMAGE probe finds no git or no local image)",
      "network": "string ('open' | 'none'; the global mode)",
      "networkEnforced": "boolean (true only when isolation is on and the mode is 'none'; false means egress is open)",
      "profile": "object keyed by pod: { name: 'lights-out', violations: array of { requirement, fix } } (only when a pod runs the lights-out profile)"
    },
    "templateDrift": "array of { id, agentVersion: number | null, currentVersion, ok } (advisory; pod members are not listed)",
    "modelRegistry":     "{ ok, problems: array of { key, reason } } (malformed docket-models.json entries)",
    "schedules":         "{ ok, problems: array of { key, reason } } (entries that would never fire)",
    "exporters":         "{ ok, enabled: array of { name, failed, sharesContentWith: string | null } } (advisory: a failing exporter sets ok false and never adds to `issues`)",
    "guardrailPolicies": "{ ok, problems: array of { file, reason } } (policy files that fail closed)",
    "podConfigOverlays": "{ ok, problems: array of { pod, kind: 'role' | 'policy', name, reason } }",
    "podSync":           "{ ok, stale: array of { id, storedVersion: number | null, currentVersion } } (a stale member adds one to `issues`)",
    "runtimeContract":   "{ ok, missing: array of agent ids with no current WORKFLOW_AUTO.md } (advisory, read-only here; the text report re-seeds it)"
  }
}
```

`issues` is the sum of: a missing `python3`; a fleet that fails to load; each agent with a non-empty
`issues`; each pod whose ledger disagrees with its running tasks; each budget at or over 100% and
each runaway agent; each entry of `keyHygiene.missingForAgents`; each `providerCatalog` problem;
one for `notifications` when it is not ok; one for `sandboxUsable: false` with at least one
project agent; and the problem count of each of `modelRegistry`, `schedules`,
`guardrailPolicies`, `podConfigOverlays` and `podSync`. `templateDrift`, `exporters` and
`runtimeContract` never add to it. `keyHygiene.missingForAgents` uses the agent's resolved model
(the default when the metadata names none), the same reader the text report uses.

### `docket status --json` / `docket status --all --json`

`docket status --json` (run inside a pod, or with `--pod`) emits one pod object;
`--all --json` emits `{"projects": [<pod object>, ...]}` plus the fleet inventory:

```json
{
  "id":          "string (pod id)",
  "path":        "string (codebase or workDir; may be empty)",
  "status":      "ready | active | waiting | attention | degraded (degraded: a member's workspace is missing or the pod has no members; waiting: a task is waiting_approval or waiting_input; active: a task is running; attention: a task failed)",
  "paused":      "boolean (the pod's Lead is paused, as the budget gate does)",
  "pausedReason": "string (why: 'budget'; \"\" when not paused)",
  "memberCount": "number",
  "isolation":   "string (the sandbox posture: 'on (<backend>, network <open|none>)' or '<off (default)|off>; <backend|no backend> found, network <open|none>', where isolation off and mode none reads 'network none (not enforced: isolation off)')",
  "members":     "array of { id, role, status: ready | missing }",
  "tasks": {
    "pending": "number", "running": "number", "waitingApproval": "number",
    "waitingInput": "number (parked consult or input-step questions)",
    "blocked": "number", "failed": "number", "done": "number", "cancelled": "number (one count per task status, each task counted once)",
    "approvedReady": "number (pending tasks whose approval was granted)"
  },
  "usage":       "{ input, output (measured tokens), estimateUsd (a labelled estimate) }",
  "outcomes":    "{ success, failure, aborted, meanMs | null, p95Ms | null }",
  "lastRun":     "{ id, state, finishedAt } | null",
  "running":     "boolean (docket start is running)",
  "commands":    "{ allowed, date, code, changed } (only when the operator allowed the repository's commands)",
  "profile":     "{ name: 'lights-out', violations: array of { requirement, fix } } (only when the pod's effective profile is lights-out)",
  "budgetUnpriced": "[string] (only when the pod has budgetUsd and runs a model with no price)"
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

Each agent object (every pod member is one):

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

`status --history --json` (also with `--all`, and with `--days N` to keep the last N days) emits
`{"history": [{date, turns, input, output, costUsd}, ...]}`. The list is empty against the
production driver, which keeps one running total per session rather than per-day usage
(cost-tracking.spec.md, "Known gap").

### `docket inbox --json`

The `InboxView` shape `GET /inbox` returns (`needsYou`, `failed`, `doneSince`, `running`,
`next`, `escalations`), except that every item also carries `state`
(`needs_approval | needs_answer | blocked | failed | done | running | approved_ready`) and
`command` (the one `docket ...` command that moves it forward). `next` is the cursor a plain call
stores; `--peek` and `--since` leave it alone. A pending task whose approval was granted is listed
in `needsYou` with `state: "approved_ready"` and `command: "docket run --pod <pod>"`. A pending
pod-memory entry is listed in `needsYou` as `{"kind": "memory", "pod", "id", "entryKind",
"subject", "note", "reason", "task", "state": "needs_memory_approval", "command": "docket pod
memory approve <id> --pod <pod>"}`; `GET /inbox` does not carry it. Each `escalations` entry is
an `EscalationView` (`operator-loop.spec.md` area 11) with the CLI's own `command` added
(`docket task answer <task>` for a `consult` or `input`, `docket task answer <esc-id> --option
approve_once` otherwise).
`decided` (an array of `EscalationView`, state `decided`) is present only while the pod has settled
a pause alone, newest first, at most twenty (`operator-loop.spec.md` "Escalations" item 14).

### `docket init --json`

`init` prints JSON only when it refuses to continue because the repository's `.docket/`
directory (or a recipe directory that is not shipped) brings commands that need the operator's OK and there is no terminal to ask
on. Nothing is created, the exit status is 2, and stdout is:

```json
{
  "status":     "needs_review",
  "reviewCode": "string (pass it back as --accept)",
  "items":      "array of { kind, name, runs } (runs: the exact command or change to allow)"
}
```

`pod update <directory> --json` answers the same way, with exit 2, when it needs that OK. Every
other refusal, and a successful `init`, prints text.

### `docket task list --json`

```json
{
  "pod": "string",
  "tasks": [
    {
      "id":          "string (task id)",
      "priority":    "high | normal | low",
      "status":      "string (pending | running | waiting_input | waiting_approval | blocked | failed | done | cancelled)",
      "costUsd":     "number | null (null when nothing is recorded)",
      "description": "string",
      "worktree":    "string (absolute path) | null"
    }
  ]
}
```

`worktree` is the recorded task worktree directory, or `null` for a task that has none (ran in
place, not yet claimed, or pruned). Queue order.

### Task options on the queue record

`GET /tasks/<pod>` and `GET /tasks/<pod>/<id>` return the queue record. A task enqueued with
the addressing flags of `task add` (`cli-interface.spec.md`) or a `POST /tasks/<pod>` body carries
each of these keys that was set and omits the rest: `externalRef`, `idempotencyKey`, `baseRef`,
`pipeline`, `gate` (`{command, timeoutS?, map?}`), `maxTokens`, `prepare`, `restrictions`
(`{deniedTools?, network?, policies?}`) and `autonomy` (`L3`, `L4` or `L5`). Their types and rules are defined by `operator-api.spec.md`
("Arguments").

### `docket task show <ref> --json`

```json
{
  "pod":      "string",
  "task":     "one task list item, with worktree replaced by the object below or null",
  "evidence": "the evidence-v1.1 document of docs/contracts/evidence-v1.1/schema.json",
  "runs":     "array of run records (below)",
  "corrections": "array of corrections-ledger records for this task",
  "interruptions": [{ "kind": "string", "description": "string", "detail": "string" }],
  "escalations": "array of the task's pending EscalationView (operator-loop.spec.md area 11), [] when none",
  "decided":     "array of the task's EscalationView settled by the pod alone; the key is absent when there is none"
}
```

`task.worktree` is `{ "path", "branch", "baseCommit", "diff", "merge" }` (`diff` and `merge` are
the exact shell commands) or `null`. `interruptions` is the forecast of what could pause the task;
`kind` is one of `policy`, `pipeline_gate`, `high_risk_class`, `mode` or `channel`.
A `<ref>` that is a run id whose run failed exits 1 after printing the document.

Each run record carries the run registry fields (the same record `GET /runs` returns):

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
  "pids":       "array of integers (process groups of hops in flight)",
  "variables":  "object",
  "cancellation": "{ requestedAt, observedAt, stoppedAt: string | null, reason, source: string } (always present; the timestamps are null until a cancel is requested)"
}
```

### `docket task diff <ref> --json`

The diff object of `GET /tasks/<pod>/<id>/diff` (`task`, `branch`, `baseCommit`, `head`, `patch`,
`untracked`, `worktreePresent`), defined in `operator-api.spec.md`. A task that ran in place, or
whose branch is gone, prints an error to stderr and exits 1. Without `--json` the command prints
the patch alone.

### `docket task trace <ref> --json`

`{ "pod": "string", "events": [ <trace record>, ... ] }` in file order; the records are the
trace-store records (`trace-store.spec.md`) with their own key names. A task with no trace file
exits 1. `--export` prints the raw JSONL instead.

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
    "<pod setting key>": { "value": "the effective value", "source": "\"set\" | \"default\" (maxReworkCycles with a bound pipeline: \"pipeline\", value \"<step>:<max>,...\" or \"none\")" }
  },
  "approvalMode": {
    "effective": "wait | park | refuse (what dispatch uses for this caller)",
    "source":    "set | unset"
  },
  "pipeline":     { "source": "string" },
  "network":      { "mode": "open | none", "scope": "default | global | pod" },
  "budgetUnpriced": ["string (a model the budget cannot price; empty without budgetUsd)"],
  "configSource": "string (absolute directory the pod was last applied from; empty when never applied)",
  "configDigest": "string (sha256 hex of that directory's applied files; empty when never applied)",
  "drift":        "yes | no | \"\" (empty when there is no recorded source or the directory is gone)"
}
```

`settings` has one entry per pod setting: `budgetUsd`, `maxReworkCycles`, `turnTimeoutS`,
`verifyTimeoutS`, `approvalMode`, `approvalExpiryHours`, `inputExpiryHours`, `allowCommands`,
`pipeline`, `schedule`, `projectInstructions`, `mcpServers`, `deniedTools`, `requireVerify`,
`maxConsultationsPerTask`, `consultMode`, `network`, `profile`, `readOnly`, `prepare` and `protects`.

An unset `approvalMode` resolves per caller: `wait` on a terminal, `park` without one. A stored
value that fails validation (e.g. a hand-edited `.docket-meta.json`) prints an error to stderr
naming the offending key and exits 1, with nothing on stdout, instead of showing that key's
default. A pod that does not exist exits 1.

### `docket pod show <member> --json`

A bare object: the effective configuration a real dispatch turn would use for
*member*, with the source that set each value. Composes existing resolvers only
(model policy, the prompt composer, role/tool denial, the guardrail policy engine,
the pod settings, and the pipeline resolver) — it writes nothing and adds no new
configuration surface.

Four resolved values — the role archetype (`roleScope`), each applicable policy, each loaded MCP
server, and each denied tool — carry a `scope`: `"built-in"` (a shipped
archetype/starter role), `"global"` (the operator's `~/.docket` overlay), or `"pod"`
(this pod's own `config/` overlay or pod setting). A tool denied by
both this pod's `deniedTools` setting and its role's own archetype reports `"pod"`
(the more specific override). `tools.mcpServers`/`tools.denied` list only the
servers/names a live turn would actually see — a pod's own `mcpServers` selection
excludes every other configured server, never merely relabels it.

`skills` carries its own, three-value scope vocabulary — `"codebase"` (this agent's own
codebase root's `.docket/skills/`), `"pod"` (this pod's own `config/skills/`), or
`"global"` (the operator's `~/.docket/skills/`) — nearest wins by name, and only the
winning scope's skill is listed (ADR 0013).

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
    "model":      { "id": "string", "contextWindow": "number | null", "maxTokens": "number | null", "contextWindowSource": "declared | observed | unknown", "maxTokensSource": "declared | observed | unknown", "source": "declared | observed | unknown", "observedAt": "YYYY-MM-DD | \"\"" }
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
    "denied":  [ { "name": "string", "scope": "built-in | global | pod | \"\"" } ],
    "mcpServers": [
      { "name": "string", "kind": "read | write", "scope": "global | pod" }
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
    "source": "set | default | \"\" (default: the codebase root's own AGENTS.md, unset and present; set: an explicit projectInstructions pod setting, which replaces the default entirely; \"\": neither)"
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
        "classes": "array of the privacy content classes this exporter shares"
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

`exporters` lists every catalog exporter, not only the enabled ones; the list is global, not
per member.

A name that is not a member of the pod prints an error to stderr and exits 1, with nothing on stdout.
A pod member with an invalid stored pod setting (e.g. a hand-edited
`.docket-meta.json`) refuses the same way `docket pod show` does — an
error naming the offending key, exit 1, nothing on stdout — rather than reporting a
guessed default.

The human-readable (non-`--json`) rendering keeps the `tools`/`policies` names/columns and
order and prints `scope` only in the `Provider:` line and the `Exporters:` lines. It adds one
`Provider:` line under the model, one `Project instr.:` line reporting `projectInstructions`
(`AGENTS.md (default)` / `<files> (set)` / `none`), one `Skills:` line listing each
`name (scope)` (or `none`), one `Exporters:` block listing each
`name dialect state (scope, privacy: label)` (or `none enabled` when the catalog is empty), and,
when a source is recorded, one `Config source:` line carrying the digest prefix and `drift`.

### `docket pod memory list --json`

An array, oldest first, of `{id, kind, path | command, note, status, reason, provenance}` (and
`exit` on a `command` entry) exactly as `memory.json` stores them (workspace-structure.spec.md
"Pod memory"); `[]` when the pod has none. `--status accepted|pending|refused` filters it.

### `docket pod update --json` / `pod roles --json` / `pod policies --json` / `pod recipes --json`

```json
{
  "pod update": {"items": [{"kind": "role|policy|plugin|skill|mcp-server|member|pipeline|setting", "name": "string", "action": "add|replace|skip", "note": "string"}]},
  "pod roles": "array of {name, source (built-in | starter | pod:<pod>), scope (the archetype's own scope: pod), modelClass, gate, description}; with a NAME, the archetype's wire object plus \"source\"",
  "pod policies": "array of {id, hook, action, description}; with --plugins, {\"policies\": that array, \"plugins\": array of {name, scope, file, sha256}}; with an ID, the policy's own JSON document (printed as JSON with or without --json)",
  "pod recipes": "array of {name, scope (operator | shipped), brings, directory, description, roles, policies, members, pipeline, plugins, skills, settings, mcp_servers: array of server names, exporters: array of exporter names}; with a NAME, one such object plus \"readme\""
}
```

`pod update --dry-run --json` prints the plan and writes nothing; `pod update --json` with no argument
exits 1. Output is Rich-free on stdout.

### `docket setup sandbox [status] --json`

Bare `setup sandbox` and `setup sandbox status` print the same object. It writes nothing.

```json
{
  "gate":             "always active",
  "isolation":        "string ('off (default)' | 'on' | 'off')",
  "isolationEnabled": "boolean (true when isolation is on)",
  "network":          "open | none (the global mode)",
  "networkEnforced":  "boolean (true only when isolation is on and the mode is 'none')",
  "backend":          "landlock | seatbelt | docker | none (the backend a turn would use)",
  "platform":         "string",
  "kernel":           "string | null (the kernel version when landlock is available)",
  "available":        "array of usable backends",
  "missing":          "string | null (what to install when no backend is usable)",
  "readOnly":         "array of absolute paths the jail grants read-only",
  "line":             "string (the one-line posture the text commands print)",
  "hint":             "string | null (the `Turn it on: docket setup sandbox on` line, when isolation is off and a backend is usable)"
}
```

### `docket setup model [list] --json`

Bare `setup model` and `setup model list` print the same object:

```json
{
  "roles": "array of { role, model (provider/model-id), price (a snapshot estimate such as \"$0.80/$4.00\"), source: builtin | user, why }",
  "default": "string (provider/model-id)"
}
```

### `docket setup provider list|show --json`

`list` prints a JSON array, sorted by name, of `{name, scope (built-in | global), dialect, baseUrl,
credential (the credential names joined by \", \")}`. `show <name>` prints the provider's
document with `scope` added: the document's camelCase keys (`name`, `dialect`, `baseUrl`, `auth`,
`local`, `models`, ...), where each `models` entry also carries `contextWindow`, `maxTokens`,
`limitsSource`, `contextWindowSource`, `maxTokensSource` and `observedAt` (a limit that is not
known is `null`, never a default). An unknown name exits 1.

### `docket setup notify list|show --json`

`list` prints a JSON array, sorted by name, of `{name, dialect, enabled, capabilities, content,
scope}`. `show <name>` prints the channel's effective document with `scope` added (`kind`, `name`,
`description`, `dialect`, `enabled`, `capabilities`, `on`, `content`, `actors`, `config`,
`secret`). An unknown name exits 1.

### `docket setup export list --json`

A JSON array, one object per catalog exporter (built-in + global, nearest-wins by name),
sorted by name. `state` is the exporter's activation state, a pure classification; a present
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

### `docket setup export show|preview --json`

`show <name>` prints the exporter's document with `scope`, `state`, `missingCredentials` (credential
names) and `health` (the exporter's counters, `{}` when it has none) added before the document's
own keys (`kind`, `name`, `dialect`, `endpoint`, `auth`, `headers`, `resource`, `aliases`,
`events`, `privacy`, `share`, `contentMaxChars`, `enabled`, `note`). `preview <name> --json` prints,
on one line, the OTLP/HTTP JSON document the exporter would send for a local session (newest, or
`--session`) at the exporter's privacy level (or `--level` / `--share`); it makes no network call and
writes nothing. An unknown exporter, or no local session, exits 1.

### `docket setup mcp list --json`

A JSON array of the configured MCP servers: `{name, command, args, env, timeout, kind (read |
write), tools}`. Every `env` value is masked as `"****"`; `[]` when none is configured.

## Validation

The keys docket builds are **camelCase**:

- `costUsd` (not `cost_usd`)
- `totalCostUsd` (not `total_cost_usd`)
- `budgetUsd` (not `budget_usd`)
- `lastActivity` (not `last_activity`)
- `waitingApproval` (not `waiting_approval`)

Three places keep other key styles: the trace records of `task trace` (`event_type`, `agent_role`,
`cost_usd`, ... , owned by `trace-store.spec.md`), a policy document printed by
`pod policies <id>` (`applies_to`, ...), and the `mcp_servers` key of `pod recipes --json`, which is
snake_case.

## Examples

`docket task list --json` on a pod with one queued task:

```json
{
  "pod": "repo",
  "tasks": [
    {
      "id": "task-061c8711-a1c5-40e6-8562-5a5c0ef276cf",
      "priority": "normal",
      "status": "pending",
      "costUsd": null,
      "description": "do a thing",
      "worktree": null
    }
  ]
}
```

`docket init --json` in a repository whose `.docket/` pipeline runs a command, with no terminal
(exit 2):

```json
{
  "status": "needs_review",
  "reviewCode": "c8ce5ddc7dee5024",
  "items": [
    { "kind": "pipeline-step", "name": "check-red", "runs": "python3 -m pytest -q" }
  ]
}
```

## Implementation

- `src/docket/interfaces/cli/commands/contract.py`: `emit_json`
- `src/docket/interfaces/cli/commands/status.py`: `cmd_status`, the pod summary, `_inventory`, `_history`
- `src/docket/interfaces/cli/commands/inbox.py`: `cmd_inbox`
- `src/docket/interfaces/cli/commands/task.py`: `cmd_list`, `cmd_show`, `cmd_diff`, `cmd_trace`
- `src/docket/interfaces/cli/commands/agents.py`: `init`, the refused-review answer
- `src/docket/interfaces/cli/commands/pod.py`, `src/docket/interfaces/cli/commands/pod_show.py`: `pod show`, `pod memory list`, the text rendering
- `src/docket/interfaces/cli/commands/pod_config.py`: `pod update`, `pod roles`, `pod policies`, `pod recipes`
- `src/docket/interfaces/cli/commands/setup.py`: `setup --json`
- `src/docket/interfaces/cli/commands/setup_check.py`: `setup --fix --json`
- `src/docket/interfaces/cli/commands/setup_sandbox.py`: `sandbox_state`
- `src/docket/interfaces/cli/commands/setup_model.py`: `setup model`, `setup provider`
- `src/docket/interfaces/cli/commands/setup_notify.py`, `src/docket/interfaces/cli/commands/setup_export.py`, `src/docket/interfaces/cli/commands/setup_mcp.py`: the `list` / `show` / `preview` commands
- `src/docket/hops/application/report.py`: `pod_report`, `member_report`
- `src/docket/teams/pod.py`: `PodSettings.KEYS`
- `src/docket/tasks/domain/options.py`: `TASK_STATUSES`, `TaskOptions`
- `src/docket/hops/application/interruptions.py`: `forecast`
- `src/docket/tasks/application/runs.py`: `create_run`, the run record
- `src/docket/hops/gates/profile.py`: `as_json`
- `src/docket/kernel/operator_contract.py`: `InboxView`
- `src/docket/tasks/application/repository.py`: `TaskRepository.list`
- `src/docket/tasks/application/lifecycle.py`: `task_diff`
