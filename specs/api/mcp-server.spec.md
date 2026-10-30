# MCP Server Contract Specification

**Version**: 2.0.1
**Status**: Implemented
**Last Updated**: 2026-10-25

## Purpose

This specification defines `docket start --mcp` — an MCP (Model Context Protocol) stdio server
that exposes docket's control plane (pods, task queue, dispatch, the run registry, the
escalations that wait on a person, and recorded cost) as MCP tools, so any MCP client (Claude Code, Codex, or any other
compliant client) can drive docket *through* the same governance spine a CLI invocation goes
through, never around it.

## Scope

This specification covers:

- The `docket start --mcp` command's syntax, transport, and process lifecycle
- Every exposed tool's name, arguments, return shape, and failure behavior
- The audit, approval, and dispatch-gating guarantees every tool call MUST uphold
- The optional-dependency (`docket[mcp]`) degrade path when the SDK is not installed
- What this server explicitly does NOT do (the host/server boundary)

It does NOT cover:

- The pod dispatch state machine (hop order, budget gating, retries, the Reviewer verdict
  gate) — see `pod-dispatch.spec.md`
- The run registry's own schema and lifecycle — see `serve-read-api.spec.md`'s `/runs` section
- The approval lifecycle itself (`pending → granted/denied/expired`) — see
  `security-gates.spec.md`; and what resolving an escalation does — `operator-loop.spec.md` area 10
- The audit log's format and tamper-evidence chain — see `audit.spec.md`
- Agent-side MCP *client* configuration (docket consuming MCP tools inside a turn); see `mcp-client.spec.md`.

## Design constraint: a server, never a host

`docket start --mcp` exposes docket's own control plane as MCP tools for an external client to
call. It MUST NOT become an MCP *host*: this server has no notion of an upstream MCP server to
call; it only ever answers requests. Docket consuming external MCP servers' tools inside an agent
turn is a separate feature that lives in the turn path (`DocketDriver.run_turn`; see
`mcp-client.spec.md`), never in this server.

## Design constraint: through the governance spine, not around it

Every tool call MUST go through the same paths a CLI invocation (or, where one exists, a
`docket start` HTTP call) would:

1. **Audited.** Every tool call — including the seven read-only ones (`status`, `pods`, `queue`
   without `retry_task_id`, `runs`, `inbox`, `escalations`, `cost`), which have no other audited
   surface anywhere in this project — writes an audit-log entry (action
   `mcp.<tool>`) that participates in the same `seq`/`prev_hash` tamper-evidence chain as every
   other audit entry (see `audit.spec.md`). This entry is written unconditionally, before the
   underlying operation runs, so a call is recorded even if that operation goes on to fail.
2. **No parallel logic.** `dispatch`, `delegate` and `resolve` call the
   *exact same* functions the CLI and `docket start`'s HTTP API already call
   (`dispatch_pod`/`enqueue_task_once`, `resolve`).
   There is no MCP-specific dispatch path, no auto-approve, and no shortcut around a budget or
   approval gate. The only MCP-specific behavior is tagging the approval channel as `"mcp"` and
   the run source as `"mcp"` — the same convention `"cli"`/`"http"`/`"webhook"` already establish.
3. **Transport only.** The MCP server is a transport/presentation layer, like the CLI and the HTTP
   API — it reuses the domain services directly and never duplicates their business logic. The
   domain has no knowledge that MCP exists: the run source `"mcp"` and the approval channel `"mcp"`
   are generic string tags identical in kind to `"cli"`/`"webhook"`/`"http"`, not an MCP-specific
   dependency.

## Syntax

```
docket start --mcp
```

`docket start --mcp` combined with `--dispatch`, `--telegram` or `--token-file` prints a usage error
(to stderr — see stdio discipline below) and exits `2`. `--mcp` runs only the MCP server: no HTTP
listener, no sweeps, no dispatch loop. The MCP client configuration commands
(`docket setup mcp list|add|remove`, see `mcp-client.spec.md`) are a separate group.

## Transport

stdio only. `docket start --mcp` speaks newline-delimited JSON-RPC 2.0 (the MCP protocol) on
stdout/stdin — there is no HTTP/SSE mode, no bind address, and no bearer token, unlike
`docket start`. The process's trust boundary is *whoever can spawn it* (the same boundary the CLI
itself already has) — there is no separate network exposure to reason about, because there is no
network listener at all. An MCP client (e.g. Claude Code) launches `docket start --mcp` as a child
process and speaks the protocol over its stdin/stdout pipes.

### stdio discipline

An MCP stdio server's stdout **IS** the protocol channel — any stray non-protocol byte on stdout
corrupts the stream. The MCP tool functions MUST NOT import or call `docket.interfaces.cli.render.ui` (which
prints Rich-formatted output to stdout for every other command) and MUST return plain data, never
print. The one human-readable line `docket start --mcp` itself prints (confirming the tool count at
startup) MUST go to stderr, never stdout.

## Optional dependency

The official `mcp` Python SDK is **not** a base dependency — it is an optional extra
(`docket[mcp]`, pinned `mcp>=2.0.0`, no upper bound) so a base `pip install docket` stays
dependency-light. `docket start --mcp` imports the SDK lazily, only when it starts serving,
guarded by `try`/`except ImportError`, so importing docket never requires it. When the SDK is
missing, `docket start --mcp` prints
an actionable install hint to stderr and exits `1` instead of raising a bare traceback:

```
The 'mcp' package is not installed — `docket start --mcp` needs the optional MCP extra.
Install it with:  pip install 'docket[mcp]'
(uv projects:      uv sync --extra mcp   or   uv pip install 'docket[mcp]')
```

The server is built on `mcp.server.MCPServer` (`add_tool(fn, name=...)`,
`server.run(transport="stdio")`); the extra's floor is `2.0.0` and it has no upper bound.

## Tools

Eleven tools, grouped by the control-plane surface they expose. Every response shape below is a bare
JSON value (object, per this project's "no envelope wrapper" convention — see
`cli-interface.spec.md`'s Output Formats section) — there is no generic `{ok, data, error}`
wrapper on the successful path. A tool that cannot complete (bad input, an unknown id, an invalid
state transition) raises instead of returning an inline error field; the MCP SDK turns any raised
exception from a tool call into a `CallToolResult` with `isError: true` carrying the message —
this is the MCP-native way to signal "this call failed," so a successful response's shape never
has to reserve a field for an error case that didn't happen. Three tools' *successful* response
shapes do carry an `"ok": true` field — `dispatch`, `resolve` and `task_pregrant` — because
`dispatch` is a deliberate byte-for-byte match with `docket start`'s existing
`POST /dispatch/<project>` response body (see `serve-read-api.spec.md`), and the other two follow
the same convention; none is a generic envelope.

### `status`

**Purpose**: Fleet-wide status snapshot — enabled channels, every agent's
model/registration/cost, and total recorded spend.
**Arguments**: none.
**Output**: identical shape to `docket start`'s `GET /status.json` (see `serve-read-api.spec.md`),
including its `apiVersion`.
**Failure modes**: none expected in normal operation.

### `pods`

**Purpose**: List every provisioned pod (project) and its member roster.
**Arguments**: none.
**Output**:

```json
{"pods": [{"project": "myapp", "members": [{"id": "myapp-lead", "role": "lead", "model": "..."}]}]}
```

Members are ordered Lead-first, matching `docket pod show`'s own member ordering.

### `queue`

**Purpose**: Show a pod's task queue (all statuses, not just pending); optionally re-queue one
`blocked` or `failed` task first.
**Arguments**:

- `project` (string, required)
- `retry_task_id` (string, optional) — mirrors `docket task retry <task-id>`: a `blocked` or
  `failed` task goes back to `pending`, keeping its hops and clearing its block/failure fields,
  and the retry is audited as `task.retry` in addition to `mcp.queue`

**Output**: `{"project": "myapp", "tasks": [...]}` — the pod's task records as stored (see
`pod-dispatch.spec.md`); the retry, when given, is applied before the queue is read.
**Failure modes**: raises if `retry_task_id` is given but does not name a `blocked` or `failed`
task in that project's queue (the message says "not a failed or blocked task").

### `delegate`

**Purpose**: Queue a new task for a pod's Lead to work through.
**Arguments**:

- `project` (string, required)
- `description` (string, required) — 1–500 chars
- `priority` (string, optional, default `"normal"`) — `high` | `normal` | `low`

The task is recorded with channel `mcp`. The tool takes only these three arguments: the other
`docket task add` inputs (`--brief`, `--external-ref`, `--idempotency-key`, `--base-ref`,
`--pipeline`, `--gate`, `--max-tokens`, ...) and the matching `POST /tasks/<project>` fields are not
available over MCP.
**Output**: the created task record (the task of the `(task, created)` pair `enqueue_task_once` returns, bare).
**Failure modes**: raises on an empty or >500-char description, an invalid `priority`, or a
`project` with no provisioned pod — the same validation `docket task add` applies.

### `dispatch`

**Purpose**: Trigger a pod's real dispatch pipeline — one real, costed agent turn per hop
(Lead → Implementer → optional Reviewer).
**Arguments**:

- `project` (string, required)
- `resume` (boolean, optional, default `false`) — reclaim a task left `failed` with a stale claim
- `timeout` (integer, optional) — overrides both the agent-turn and `verifyCmd` timeout for this
  run only; MUST be a positive integer if given

**Gating**: calls `dispatch_pod` directly — the pod budget cap, the Implementer's
`verifyCmd` gate, and the Reviewer verdict gate all apply exactly as
they do for the CLI and the `docket start` webhook. There is no MCP-specific dispatch path.
**Output**: `{"ok": true, "run": "run-...", "project": "myapp", "status": "dispatched"}` —
byte-for-byte the same shape as `POST /dispatch/<project>`'s response body. A run record (source
`"mcp"`) is created and its id returned **before** any dispatch work starts; the pipeline itself
runs in a background thread (this call MUST NOT block on a real agent turn) — poll the `runs` tool
with the returned id for the outcome, exactly as a `docket start` webhook caller polls `GET
/runs/<id>`.
**Failure modes**: raises if `timeout` is given and not a positive integer. An invalid `project`
or a dispatch-pipeline exception does NOT raise from this call — it surfaces asynchronously as a
`failed` run record (matching the webhook's contract precisely — see `serve-read-api.spec.md`).

### `runs`

**Purpose**: List dispatch run records, or fetch one by id.
**Arguments**:

- `project` (string, optional) — filter to one pod
- `run_id` (string, optional) — fetch a single record

**Output**: `{"runs": [...]}` (newest-first) when no `run_id` is given, identical to
`docket start`'s `GET /runs` (with `?project=`); the bare run record, identical to `GET /runs/<id>`,
when `run_id` is given (`run_id` wins over `project`).
**Failure modes**: raises if `run_id` is given but unknown.

### `resolve`

**Purpose**: Settle one escalation: choose one of its options, give content. The one tool that
answers an approval, a gate, a changed check, a consult and an `input` step alike — identical to
`POST /escalations/<id>` (`operator-api.spec.md`).
**Arguments**: `escalation_id` (string, required: the `id` an `escalations` entry or an `inbox`
`escalations[]` entry carries), `option_id` (string, optional: one of the entry's
`affordances.options`; `cancel` is an alias of `decline`; omitted only for a question whose options
are just `decline`), `content` (object, optional: the answer against `requestedSchema`, or
`{"reason": "<text>"}` for an approval).
**Gating**: calls `resolve(escalation_id, option_id, content, by="mcp", channel="mcp")`
(`operator-loop.spec.md` area 10) — the exact function every other surface calls, so the option
check, the schema check, the `pre_input` screen and the continuation (grant and resume, deny and
fail, answer and resume) are the same whichever surface settles the pause.
**Output**: `{"ok": true, "escalation": "esc-...", "state": "resolved"}`, plus `"note"` only when a
task-wide grant was refused.
**Failure modes**: raises `McpToolError` for an unknown id, an escalation already settled or
whose approval or question is no longer waiting (a repeat raises, it never reports success), an
unknown option, content that fails the schema, or content a `pre_input` policy blocks. A refusal
never carries an approval token.
**Not tools**: `approvals_list`, `approvals_grant`, `approvals_deny` and `task_answer` do not
exist; `escalations` lists the pauses and `resolve` settles them (`approve_once`, `approve_task`
and `deny` for an approval, an option id or `decline` for a question).

### `task_pregrant`

**Purpose**: Record a single-use pre-grant for one exact command on one task, ahead of dispatch
(ADR 0016) — identical to `docket task pregrant <task-id> "<command>"` / `docket
start`'s `POST /tasks/<task_id>/pregrants`.
**Arguments**: `project` (string, required), `task_id` (string, required), `command` (string,
required — the exact command line to pre-approve), `tool` (string, optional, default `"bash"`).
**Gating**: calls `record_pregrant(project, task_id, command, tool=tool, channel="mcp",
actor="mcp")`, which creates the pre-grant exactly as an in-turn park does and names the task in
the record, which is what the task's hops read. When the pipeline
later reaches that exact call (matched by the canonical arguments digest), it passes once without
asking again.
**Output**: `{"ok": true, "token": "apr-...", "task": "<task_id>", "project": "<project>"}`.
**Failure modes**: raises if *task_id* is not in *project*'s own task queue.

### `inbox`

**Purpose**: The derived operator inbox — every pod's tasks needing a human, plus pending
escalations, failed/done/running context — identical to `docket start`'s `GET /inbox`.
**Arguments**: `since` (string, optional) — an ISO timestamp; restricts `doneSince` to tasks that
completed after it. Omitted, `doneSince` lists every terminal task.
**Output**: the `InboxView` document with its camelCase aliases — `{"needsYou": [...], "failed":
[...], "doneSince": [...], "running": [...], "next": "..." | null}`, matching `docket inbox
--json` for the same state.
**Failure modes**: none beyond the SDK's own argument-shape validation.

`needsYou` holds `TaskView`s and the `EscalationView`s no waiting task carries; `escalations` holds every pending `EscalationView`.

### `escalations`

**Purpose**: The escalation records after a cursor, each joined with the pause it names —
identical to `GET /escalations`.
**Arguments**: `since` (integer, optional) — only records with a greater `seq`; omitted, all.
**Output**: `{"escalations": [EscalationView...], "next": <seq>}` (`operator-api.spec.md`).
**Failure modes**: none beyond the SDK's own argument-shape validation. Audited as
`mcp.escalations`.

### `cost`

**Purpose**: **Recorded** USD spend — one agent or the whole fleet.
**Arguments**: `agent_id` (string, optional) — one agent's totals; omitted for the whole fleet.
**Output**: `{"agents": [...], "totalUsd": ...}` when `agent_id` is omitted, where each agent row is
`{"id", "model", "input", "output", "costUsd", "pricingKnown", "turns", "budgetUsd"}`; a single
agent's row when given. Rows cover project agents (pod members) only.
**Failure modes**: raises ("Project '<id>' not found.") if `agent_id` is given but is not a known
project agent.
**Cost-reporting discipline**: this figure is recorded spend from session data, which is always
`0.0` today because `DocketDriver` records measured tokens but no dollar figure; the
token-price estimate `docket status` shows is not returned here. It is never a
projected/estimated figure, and never presented as a dollar *savings* claim (a standing
product discipline across every docket status surface — see `cost-tracking.spec.md`).

## Arguments

Per-tool arguments are listed above; there are no global arguments beyond each tool's own. Every
argument is passed as a named JSON property in the MCP `CallToolRequest`'s `arguments` object (the
SDK derives each tool's JSON Schema from its Python function signature and validates a call's
arguments against it before invoking the function — an argument of the wrong type is rejected by
the SDK itself, before docket's tool code runs at all).

## Options

`docket start --mcp` takes no command-line options or flags today.

## Output

See Tools above for each tool's response shape. There is no top-level output for `docket start --mcp`
itself beyond the one stderr startup line (tool count + names) — the process then blocks,
serving the protocol, until its stdin closes or it is interrupted.

## Return

| Code | Meaning |
|------|---------|
| 0 | `docket start --mcp` shut down cleanly (stdin closed, or Ctrl-C) |
| 1 | The optional `mcp` SDK is not installed |
| 2 | `docket start --mcp` combined with `--dispatch`, `--telegram` or `--token-file` (usage error) |

A tool call's own success/failure is expressed inside the MCP protocol (`CallToolResult.isError`),
not as a process exit code — the server process itself only exits when the transport session ends.

## Validation

- Every tool call MUST write exactly one `mcp.<tool>` audit-log entry, written
  unconditionally before the underlying operation runs.
- `dispatch`, `delegate` and `resolve` MUST call the same
  functions the CLI and `docket start` call — no duplicated or parallel implementation.
- `dispatch` MUST create a run record (source `"mcp"`) and return its id before the dispatch
  pipeline itself has necessarily finished (or even started) running.
- `resolve` MUST tag the resolution with `channel="mcp"` and `by="mcp"`.
- The tool list MUST be exactly the eleven below; a pause is listed by `escalations` and settled by
  `resolve` whatever its kind, and no tool takes an approval token or a task id and an `action`.
- `resolve` MUST call the function every other surface calls (`operator-loop.spec.md` area 10): a
  second call on the same escalation raises `McpToolError`.
- No tool function may import or call `docket.interfaces.cli.render.ui`, or otherwise print to stdout.
- A missing `mcp` SDK MUST produce the actionable hint above (stderr) and exit `1`, not a bare
  `ImportError` traceback.

## Examples

### Installing the optional extra

```bash
pip install 'docket[mcp]'
# or, in a uv-managed checkout:
uv sync --extra mcp
```

### Starting the server (from an MCP client's perspective)

An MCP client is configured to launch `docket start --mcp` as a stdio subprocess — see that
client's own documentation for how it registers a local MCP server (docket does not provide or
require any client-side configuration file of its own; this is intentionally the client's
concern, not docket's — see Scope above).

### A representative tool call/response (status)

```json
// → CallToolRequest {"name": "status", "arguments": {}}
// ← CallToolResult (structuredContent)
{
  "apiVersion": "6",
  "timestamp": "2026-07-30T12:00:00Z",
  "channels": ["telegram"],
  "agents": [ /* ... */ ],
  "totalCostUsd": 0.0
}
```

### Dispatch + poll (mirrors the `docket start` webhook's curl example)

```json
// → {"name": "dispatch", "arguments": {"project": "myapp"}}
// ← {"ok": true, "run": "run-3f2a1c9e-...", "project": "myapp", "status": "dispatched"}

// → {"name": "runs", "arguments": {"run_id": "run-3f2a1c9e-..."}}
// ← {"id": "run-3f2a1c9e-...", "source": "mcp", "project": "myapp", "state": "succeeded", ...}
```

## Implementation

- `src/docket/interfaces/cli/commands/mcp.py`: the eleven tool functions (`tool_status` ... `tool_task_pregrant`, `tool_resolve`),
  `_TOOL_NAMES`, `MISSING_SDK_HINT`, `McpToolError`, `serve_stdio`
- `src/docket/interfaces/cli/commands/service.py`: the `docket start` command and its `--mcp` flag handling
- `src/docket/hops/application/sweep.py`: `dispatch_pod`
- `src/docket/tasks/application/queue.py`: `enqueue_task_once`, `pod_roster`
- `src/docket/tasks/application/lifecycle.py`: `retry_task`
- `src/docket/tasks/application/escalations.py`: `resolve`
- `src/docket/hops/application/interruptions.py`: `record_pregrant`
- `src/docket/operator/inbox.py`, `src/docket/kernel/operator_contract.py`: `build_inbox`, `escalation_views`, `InboxView`
- `src/docket/tasks/application/runs.py`: `create_run`, `execute`, `get_run`, `list_runs`, `RunSource`
- `src/docket/interfaces/http/routes/health.py`: `build_status`, `SERVE_API_VERSION`
- `pyproject.toml`: the `mcp` extra
