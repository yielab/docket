# MCP Server Contract Specification

**Version**: 1.9.5
**Status**: Implemented
**Last Updated**: 2026-10-23

## Purpose

This specification defines `docket start --mcp` — an MCP (Model Context Protocol) stdio server
that exposes docket's control plane (pods, task queue, dispatch, the run registry, HITL
approvals, and recorded cost) as MCP tools, so any MCP client (Claude Code, Codex, or any other
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

- The pod dispatch state machine (hop order, budget gating, retries, the Reviewer/Tester verdict
  gates) — see `pod-dispatch.spec.md`
- The run registry's own schema and lifecycle — see `serve-read-api.spec.md`'s `/runs` section
- The approval token lifecycle itself (`pending → granted/denied/expired`) — see
  `security-gates.spec.md`
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
   without `retry_task_id`, `runs`, `approvals_list`, `inbox`, `cost`), which have no other audited
   surface anywhere in this project — writes an audit-log entry (action
   `mcp.<tool>`) that participates in the same `seq`/`prev_hash` tamper-evidence chain as every
   other audit entry (see `audit.spec.md`). This entry is written unconditionally, before the
   underlying operation runs, so a call is recorded even if that operation goes on to fail.
2. **No parallel logic.** `dispatch`, `delegate`, `approvals_grant`, and `approvals_deny` call the
   *exact same* functions the CLI and `docket start`'s HTTP API already call
   (`dispatch_pod`/`enqueue_task_once`, `approval_grant`/`approval_deny`).
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
corrupts the stream. The MCP tool functions MUST NOT import or call `docket.ui` (which
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

Thirteen tools, grouped by the control-plane surface they expose. Every response shape below is a bare
JSON value (object, per this project's "no envelope wrapper" convention — see
`cli-interface.spec.md`'s Output Formats section) — there is no generic `{ok, data, error}`
wrapper on the successful path. A tool that cannot complete (bad input, an unknown id, an invalid
state transition) raises instead of returning an inline error field; the MCP SDK turns any raised
exception from a tool call into a `CallToolResult` with `isError: true` carrying the message —
this is the MCP-native way to signal "this call failed," so a successful response's shape never
has to reserve a field for an error case that didn't happen. Four tools' *successful* response
shapes do carry an `"ok": true` field — `dispatch`, `approvals_grant`/`approvals_deny`, and
`task_answer`/`task_pregrant` — because `dispatch` and the approvals shapes are a deliberate byte-for-byte match with `docket start`'s existing
`POST /dispatch/<project>` and `POST /approvals/<token>` response bodies (see
`serve-read-api.spec.md`), and the other two follow the same convention; none is a generic
envelope.

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
task in that project's queue (the message says "not a blocked task").

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
(Lead → Implementer → optional Reviewer/Tester).
**Arguments**:

- `project` (string, required)
- `resume` (boolean, optional, default `false`) — reclaim a task left `failed` with a stale claim
- `timeout` (integer, optional) — overrides both the agent-turn and `verifyCmd` timeout for this
  run only; MUST be a positive integer if given

**Gating**: calls `dispatch_pod` directly — the pod budget cap, the Implementer's
`verifyCmd` gate, the Reviewer verdict gate, and the Tester PASS/FAIL gate all apply exactly as
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

### `approvals_list`

**Purpose**: List pending HITL approvals awaiting a grant/deny decision.
**Arguments**: none.
**Output**: `{"pending": [...]}` — identical shape to `docket start`'s `GET /approvals`.

### `approvals_grant`

**Purpose**: Grant a pending approval token — the same grant `docket task approve <id>` records / `docket
start`'s `POST /approvals/<token>` with `{"action": "grant"}`.
**Arguments**: `token` (string, required); `option` (string, optional: `approve_once` or
`approve_task`; anything else raises before any change). `approve_task` is recorded on
the approval before the grant, so a parked pod task gains the task-wide grant of
`operator-loop.spec.md` requirement 5a (channel `mcp`); a task-wide grant refused because the task already holds
20 adds a `note` to the output.
**Gating**: calls `approval_grant(token, channel="mcp")` — the exact function every
other channel calls, tagged so the audit trail records which surface performed the grant. No
MCP-side bypass, auto-approve, or alternate transition path of any kind. If *token* gates a
pod-dispatch task waiting on it (`waiting_approval`), the same `resolve_waiting_approval`
call the CLI/HTTP/Telegram channels make resumes it: the task returns to `pending` with the exact
hop it stopped on handed to the next dispatch run as a single-use gate override (see
pod-dispatch.spec.md, "require_approval gate and waiting_approval"). This resolution runs even on
an already-granted token (see Failure modes) — it is not skipped just because the call raises.
**Output**: `{"ok": true, "token": "apr-...", "state": "granted"}`, plus `"note"` only when a
task-wide grant was refused.
**Failure modes**: raises if the token is unknown, or if it is not currently `pending` (already
granted, denied, or expired) — an already-granted token raises rather than silently reporting
success, a deliberate difference from `docket task approve`'s CLI behavior (which treats a repeat grant
as a benign warning, exit 0): an automated MCP caller should learn explicitly that its call did
not perform a fresh state transition, rather than receiving an ambiguous `"ok": true` for a call
that changed nothing. The `resolve_waiting_approval` follow-up still runs before this raise, so a
dispatch task stuck `waiting_approval` from an earlier grant that never reached it is still freed.

### `approvals_deny`

**Purpose**: Deny a pending approval token — the same denial `docket task deny <id>` records / `docket start`'s
`POST /approvals/<token>` with `{"action": "deny"}`.
**Arguments**: `token` (string, required).
**Gating**: calls `approval_deny(token, channel="mcp")`, mirroring
`approvals_grant`. If *token* gates a pod-dispatch task waiting on it, the same
`resolve_waiting_approval` follow-up fails that task immediately
(`failureKind: "approval_denied"`) — never auto-retried by a later dispatch, even with `--resume`.
**Output**: `{"ok": true, "token": "apr-...", "state": "denied"}`.
**Failure modes**: same as `approvals_grant`, including that the `resolve_waiting_approval`
follow-up still runs before the raise.

### `task_answer`

**Purpose**: Answer a task's parked `input` question — identical to `docket task answer
<task-id>` / `docket start`'s `POST /tasks/<task-id>/answer`.
**Arguments**: `project` (string, required), `task_id` (string, required), `action` (string,
required — `"accept"`, `"decline"` or `"cancel"`), `content` (object, optional).
**Gating**: calls `answer_task(channel="mcp", actor="mcp")` — the exact function
every other surface calls, so the schema/`pre_input` screen and the resume onto the step's own
route are byte-for-byte the same as `docket task answer`/the HTTP route.
**Output**: `{"ok": true, "task": "<task_id>", "project": "<project>", "action": "accept"}`.
**Failure modes**: raises naming the policy id if the answer's `content` matched
a `pre_input` `block` policy; raises naming the underlying reason for an unknown task, a task not
currently `waiting_input`, or `content` failing the question's own `requestedSchema`.

### `task_pregrant`

**Purpose**: Record a single-use pre-grant for one exact command on one task, ahead of dispatch
(ADR 0016) — identical to `docket task approve <task-id> --for "<command>"` / `docket
start`'s `POST /tasks/<task_id>/pregrants`.
**Arguments**: `project` (string, required), `task_id` (string, required), `command` (string,
required — the exact command line to pre-approve), `tool` (string, optional, default `"bash"`).
**Gating**: calls `record_pregrant(project, task_id, command, tool=tool, channel="mcp",
actor="mcp")`, which creates the pre-grant exactly as an in-turn park does, then appends the grant
to the task's own `pregrants` list — the same shape a live park already produces. When the pipeline
later reaches that exact call (matched by the canonical arguments digest), it passes once without
asking again.
**Output**: `{"ok": true, "token": "apr-...", "task": "<task_id>", "project": "<project>"}`.
**Failure modes**: raises if *task_id* is not in *project*'s own task queue.

### `inbox`

**Purpose**: The derived operator inbox — every pod's tasks needing a human, plus pending
approvals, failed/done/running context — identical to `docket start`'s `GET /inbox`.
**Arguments**: `since` (string, optional) — an ISO timestamp; restricts `doneSince` to tasks that
completed after it. Omitted, `doneSince` lists every terminal task.
**Output**: the `InboxView` document with its camelCase aliases — `{"needsYou": [...], "failed":
[...], "doneSince": [...], "running": [...], "next": "..." | null}`, matching `docket inbox
--json` for the same state.
**Failure modes**: none beyond the SDK's own argument-shape validation.

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
- `dispatch`, `delegate`, `approvals_grant`, and `approvals_deny` MUST call the same
  functions the CLI and `docket start` call — no duplicated or parallel implementation.
- `dispatch` MUST create a run record (source `"mcp"`) and return its id before the dispatch
  pipeline itself has necessarily finished (or even started) running.
- `approvals_grant`/`approvals_deny` MUST tag the approval's audit entry with `channel="mcp"`.
- No tool function may import or call `docket.ui`, or otherwise print to stdout.
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

- `src/docket/cli/_mcp.py`: the thirteen tool functions (`tool_status` ... `tool_task_pregrant`),
  `_TOOL_NAMES`, `MISSING_SDK_HINT`, `McpToolError`, `serve_stdio`
- `src/docket/cli/_service.py`: the `docket start` command and its `--mcp` flag handling
- `src/docket/core/dispatch.py`: `dispatch_pod`, `enqueue_task_once`, `retry_task`, `read_tasks`,
  `pod_roster`, `resolve_waiting_approval`, `resolve_waiting_approval_detail`
- `src/docket/core/approval.py`: `approval_grant`, `approval_deny`, `approval_set_option`,
  `list_pending`
- `src/docket/core/answers.py`: `answer_task`
- `src/docket/core/interruptions.py`: `record_pregrant`
- `src/docket/core/inbox.py`, `src/docket/core/operator_contract.py`: `build_inbox`, `InboxView`
- `src/docket/core/runs.py`: `create_run`, `execute`, `get_run`, `list_runs`, `RunSource`
- `src/docket/serve.py`: `build_status`, `SERVE_API_VERSION`
- `pyproject.toml`: the `mcp` extra
