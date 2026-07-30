# MCP Server Contract Specification

**Version**: 1.1.0
**Status**: Implemented
**Last Updated**: 2026-07-30

## Purpose

This specification defines `docket mcp serve` — an MCP (Model Context Protocol) stdio server
that exposes docket's control plane (pods, task queue, dispatch, the run registry, HITL
approvals, and recorded cost) as MCP tools, so any MCP client (Claude Code, Codex, or any other
compliant client) can drive docket *through* the same governance spine a CLI invocation goes
through, never around it (ROADMAP Phase 18 L-3).

## Scope

This specification covers:

- The `docket mcp serve` command's syntax, transport, and process lifecycle
- Every exposed tool's name, arguments, return shape, and failure behavior
- The audit, approval, and dispatch-gating guarantees every tool call MUST uphold
- The optional-dependency (`docket[mcp]`) degrade path when the SDK is not installed
- What this server explicitly does NOT do (the host/server boundary)

It does NOT cover:

- The underlying `core/dispatch.py` state machine (hop order, budget gating, retries, the
  Reviewer/Tester verdict gates) — see `pod-dispatch.spec.md`
- The run registry's own schema and lifecycle — see `serve-read-api.spec.md`'s `/runs` section
  and `cli-json-shapes.spec.md`
- The approval token lifecycle itself (`pending → granted/denied/expired`) — see
  `security-gates.spec.md`
- The audit log's format and tamper-evidence chain — see `audit.spec.md`
- Agent-side MCP *client* configuration (docket's daemon consuming other MCP servers' tools
  inside an agent turn) — that is a deliberately separate, unbuilt card (ROADMAP Phase 18 L-4,
  daemon-gated) and is explicitly out of scope for this server

## Design constraint: a server, never a host

`docket mcp serve` exposes docket's own control plane as MCP tools for an external client to
call. It MUST NOT become an MCP *host* — docket executing other MCP servers' tools inside an
agent turn is the "standalone-runtime trap" the ROADMAP's Phase 18 program explicitly refuses.
This server has no notion of an upstream MCP server to call; it only ever answers requests.

## Design constraint: through the governance spine, not around it

Every tool call MUST go through the same paths a CLI invocation (or, where one exists, a
`docket serve` HTTP call) would:

1. **Audited.** Every tool call — including the six read-only ones, which have no other audited
   surface anywhere in this project — writes an audit-log entry (`core/audit.py`, action
   `mcp.<tool>`) that participates in the same `seq`/`prev_hash` tamper-evidence chain as every
   other audit entry (see `audit.spec.md`). This entry is written unconditionally, before the
   underlying operation runs, so a call is recorded even if that operation goes on to fail.
2. **No parallel logic.** `dispatch`, `delegate`, `approvals_grant`, and `approvals_deny` call the
   *exact same* `core/` functions the CLI and `docket serve`'s HTTP API already call
   (`core.dispatch.dispatch_pod`/`enqueue_task`, `core.approval.approval_grant`/`approval_deny`).
   There is no MCP-specific dispatch path, no auto-approve, and no shortcut around a budget or
   approval gate. The only MCP-specific behavior is tagging the approval channel as `"mcp"` and
   the run source as `"mcp"` — the same convention `"cli"`/`"http"`/`"webhook"` already establish.
3. **Presentation-tier only.** `cli/_mcp.py` is a transport/presentation module, like `cli/_pod.py`
   or `serve.py` — it reuses `core/` services directly and never duplicates their business logic.
   `core/` has no knowledge that MCP exists (the one addition, `RunSource`'s `"mcp"` literal in
   `core/runs.py`, is a generic string tag identical in kind to `"cli"`/`"webhook"`, not an
   MCP-specific dependency).

## Syntax

```
docket mcp serve
```

`docket mcp` with no subcommand, or any subcommand other than `serve`, prints usage (to stderr —
see stdio discipline below) and exits: `0` for no subcommand, `1` for an unrecognized one.

## Transport

stdio only. `docket mcp serve` speaks newline-delimited JSON-RPC 2.0 (the MCP protocol) on
stdout/stdin — there is no HTTP/SSE mode, no bind address, and no bearer token, unlike
`docket serve`. The process's trust boundary is *whoever can spawn it* (the same boundary the CLI
itself already has) — there is no separate network exposure to reason about, because there is no
network listener at all. An MCP client (e.g. Claude Code) launches `docket mcp serve` as a child
process and speaks the protocol over its stdin/stdout pipes.

### stdio discipline

An MCP stdio server's stdout **IS** the protocol channel — any stray non-protocol byte on stdout
corrupts the stream. `cli/_mcp.py`'s tool functions MUST NOT import or call `docket.ui` (which
prints Rich-formatted output to stdout for every other command) and MUST return plain data, never
print. The one human-readable line `docket mcp serve` itself prints (confirming the tool count at
startup) MUST go to stderr, never stdout.

## Optional dependency

The official `mcp` Python SDK is **not** a base dependency — it is an optional extra
(`docket[mcp]`, pinned `mcp>=2.0.0`, no upper bound) so a base `pip install docket` stays
dependency-light (the SDK pulls in starlette, uvicorn, cryptography, jsonschema, and more).
`docket mcp serve` imports the SDK lazily, inside its own function, guarded by
`try`/`except ImportError` — the same pattern this project already uses for the optional PyYAML
dependency (`core/pipeline.py`/`cli/_agents.py`). When the SDK is missing, `docket mcp serve` prints
an actionable install hint to stderr and exits `1` instead of raising a bare traceback:

```
The 'mcp' package is not installed — `docket mcp serve` needs the optional MCP extra.
Install it with:  pip install 'docket[mcp]'
(uv projects:      uv sync --extra mcp   or   uv pip install 'docket[mcp]')
```

This integration targets `mcp`'s 2.x line's `mcp.server.MCPServer` — a high-level,
decorator/`add_tool`-based server that is the direct successor of the 1.x line's
`mcp.server.fastmcp.FastMCP` (same registration ergonomics: `add_tool(fn, name=...)`,
`server.run(transport="stdio")`), just renamed and relocated as part of the SDK's 2.0 rework.
`mcp.server.fastmcp` was removed outright in 2.0 (not deprecated in place), which is why the
extra's floor moved to `2.0.0`; there is no reason to keep an upper bound once the integration
targets the module that actually ships.

## Tools

Ten tools, grouped by the control-plane surface they expose. Every response shape below is a bare
JSON value (object, per this project's "no envelope wrapper" convention — see
`cli-interface.spec.md`'s Output Formats section) — there is no generic `{ok, data, error}`
wrapper on the successful path. A tool that cannot complete (bad input, an unknown id, an invalid
state transition) raises instead of returning an inline error field; the MCP SDK turns any raised
exception from a tool call into a `CallToolResult` with `isError: true` carrying the message —
this is the MCP-native way to signal "this call failed," so a successful response's shape never
has to reserve a field for an error case that didn't happen. Two tools' *successful* response
shapes do carry an `"ok": true` field — `dispatch` and `approvals_grant`/`approvals_deny` — because
those shapes are a deliberate byte-for-byte match with `docket serve`'s existing
`POST /dispatch/<project>` and `POST /approvals/<token>` response bodies (see
`serve-read-api.spec.md`), not a new generic envelope convention.

### `status`

**Purpose**: Fleet-wide status snapshot — gateway state, enabled channels, every agent's
model/registration/cost, and total recorded spend.
**Arguments**: none.
**Output**: identical shape to `docket serve`'s `GET /status.json` (see `serve-read-api.spec.md`).
**Failure modes**: none expected in normal operation.

### `pods`

**Purpose**: List every provisioned pod (project) and its member roster.
**Arguments**: none.
**Output**:

```json
{"pods": [{"project": "myapp", "members": [{"id": "myapp-lead", "role": "lead", "model": "..."}]}]}
```

Members are ordered Lead-first, matching `docket pod <project>`'s own member ordering.

### `queue`

**Purpose**: Show a pod's task queue (all statuses, not just pending); optionally un-block one
`blocked` task first.
**Arguments**:

- `project` (string, required)
- `retry_task_id` (string, optional) — mirrors `docket pod <project> queue --retry <task-id>`

**Output**: `{"project": "myapp", "tasks": [...]}` — the task shape matches `docket pod <project>
queue`'s underlying records (see `pod-dispatch.spec.md`).
**Failure modes**: raises if `retry_task_id` is given but does not name a currently-`blocked` task
in that project's queue.

### `delegate`

**Purpose**: Queue a new task for a pod's Lead to work through.
**Arguments**:

- `project` (string, required)
- `description` (string, required) — 1–500 chars
- `priority` (string, optional, default `"normal"`) — `high` | `normal` | `low`

**Output**: the created task record (bare, matching `core.dispatch.enqueue_task`'s return value).
**Failure modes**: raises on an empty or >500-char description, an invalid `priority`, or a
`project` with no provisioned pod — the same validation `docket pod <project> delegate` applies.

### `dispatch`

**Purpose**: Trigger a pod's real dispatch pipeline — one real, costed agent turn per hop
(Lead → Implementer → optional Reviewer/Tester).
**Arguments**:

- `project` (string, required)
- `resume` (boolean, optional, default `false`) — reclaim a task left `failed` with a stale claim
- `timeout` (integer, optional) — overrides both the agent-turn and `verifyCmd` timeout for this
  run only; MUST be a positive integer if given

**Gating**: calls `core.dispatch.dispatch_pod` directly — the pod budget cap, the Implementer's
`verifyCmd` gate, the Reviewer verdict gate, and the Tester PASS/FAIL gate all apply exactly as
they do for the CLI and the `docket serve` webhook. There is no MCP-specific dispatch path.
**Output**: `{"ok": true, "run": "run-...", "project": "myapp", "status": "dispatched"}` —
byte-for-byte the same shape as `POST /dispatch/<project>`'s response body. A run record (source
`"mcp"`) is created and its id returned **before** any dispatch work starts; the pipeline itself
runs in a background thread (this call MUST NOT block on a real agent turn) — poll the `runs` tool
with the returned id for the outcome, exactly as a `docket serve` webhook caller polls `GET
/runs/<id>`.
**Failure modes**: raises if `timeout` is given and not a positive integer. An invalid `project`
or a dispatch-pipeline exception does NOT raise from this call — it surfaces asynchronously as a
`failed` run record (matching the webhook's contract precisely — see `serve-read-api.spec.md`).

### `runs`

**Purpose**: List dispatch run records, or fetch one by id.
**Arguments**:

- `project` (string, optional) — filter to one pod
- `run_id` (string, optional) — fetch a single record

**Output**: `{"runs": [...]}` (newest-first) when no `run_id` is given, matching `docket runs list
--json`; the bare record (matching `docket runs show <id> --json`) when `run_id` is given.
**Failure modes**: raises if `run_id` is given but unknown.

### `approvals_list`

**Purpose**: List pending HITL approvals awaiting a grant/deny decision.
**Arguments**: none.
**Output**: `{"pending": [...]}` — identical shape to `docket serve`'s `GET /approvals`.

### `approvals_grant`

**Purpose**: Grant a pending approval token — identical to `docket approve <token>` / `docket
serve`'s `POST /approvals/<token>` with `{"action": "grant"}`.
**Arguments**: `token` (string, required).
**Gating**: calls `core.approval.approval_grant(token, channel="mcp")` — the exact function every
other channel calls, tagged so the audit trail records which surface performed the grant. No
MCP-side bypass, auto-approve, or alternate transition path of any kind.
**Output**: `{"ok": true, "token": "apr-...", "state": "granted"}`.
**Failure modes**: raises if the token is unknown, or if it is not currently `pending` (already
granted, denied, or expired) — an already-granted token raises rather than silently reporting
success, a deliberate difference from `docket approve`'s CLI behavior (which treats a repeat grant
as a benign warning, exit 0): an automated MCP caller should learn explicitly that its call did
not perform a fresh state transition, rather than receiving an ambiguous `"ok": true` for a call
that changed nothing.

### `approvals_deny`

**Purpose**: Deny a pending approval token — identical to `docket deny <token>` / `docket serve`'s
`POST /approvals/<token>` with `{"action": "deny"}`.
**Arguments**: `token` (string, required).
**Gating**: calls `core.approval.approval_deny(token, channel="mcp")`, mirroring
`approvals_grant`.
**Output**: `{"ok": true, "token": "apr-...", "state": "denied"}`.
**Failure modes**: same as `approvals_grant`.

### `cost`

**Purpose**: Daemon-**recorded** USD spend — one agent or the whole fleet.
**Arguments**: `agent_id` (string, optional) — one agent's totals; omitted for the whole fleet.
**Output**: `{"agents": [...], "totalUsd": ...}` (matches `docket cost --json`) when `agent_id` is
omitted; a single agent's cost record when given.
**Failure modes**: raises if `agent_id` is given but not a known project agent.
**Cost-reporting discipline**: this figure is the daemon's recorded spend from session data —
never a projected/estimated figure, and never presented as a dollar *savings* claim (a standing
product discipline across every docket cost surface — see `cost-tracking.spec.md`).

## Arguments

Per-tool arguments are listed above; there are no global arguments beyond each tool's own. Every
argument is passed as a named JSON property in the MCP `CallToolRequest`'s `arguments` object (the
SDK derives each tool's JSON Schema from its Python function signature and validates a call's
arguments against it before invoking the function — an argument of the wrong type is rejected by
the SDK itself, before `cli/_mcp.py`'s code runs at all).

## Options

`docket mcp serve` takes no command-line options or flags today.

## Output

See Tools above for each tool's response shape. There is no top-level output for `docket mcp
serve` itself beyond the one stderr startup line (tool count + names) — the process then blocks,
serving the protocol, until its stdin closes or it is interrupted.

## Return

| Code | Meaning |
|------|---------|
| 0 | `docket mcp serve` shut down cleanly (stdin closed, or Ctrl-C) |
| 1 | The optional `mcp` SDK is not installed |
| 0 | `docket mcp` with no subcommand (prints usage) |
| 1 | `docket mcp <unrecognized-subcommand>` |

A tool call's own success/failure is expressed inside the MCP protocol (`CallToolResult.isError`),
not as a process exit code — the server process itself only exits when the transport session ends.

## Validation

- Every tool call MUST write exactly one `mcp.<tool>` audit-log entry (`core/audit.py`), written
  unconditionally before the underlying operation runs.
- `dispatch`, `delegate`, `approvals_grant`, and `approvals_deny` MUST call the same `core/`
  functions the CLI and `docket serve` call — no duplicated or parallel implementation.
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

An MCP client is configured to launch `docket mcp serve` as a stdio subprocess — see that
client's own documentation for how it registers a local MCP server (docket does not provide or
require any client-side configuration file of its own; this is intentionally the client's
concern, not docket's — see the Phase 18 L-4 scope note above).

### A representative tool call/response (status)

```json
// → CallToolRequest {"name": "status", "arguments": {}}
// ← CallToolResult (structuredContent)
{
  "apiVersion": "2",
  "timestamp": "2026-07-30T12:00:00Z",
  "gateway": "active",
  "channels": ["telegram"],
  "agents": [ /* ... */ ],
  "totalCostUsd": 0.4213
}
```

### Dispatch + poll (mirrors the `docket serve` webhook's curl example)

```json
// → {"name": "dispatch", "arguments": {"project": "myapp"}}
// ← {"ok": true, "run": "run-3f2a1c9e-...", "project": "myapp", "status": "dispatched"}

// → {"name": "runs", "arguments": {"run_id": "run-3f2a1c9e-..."}}
// ← {"id": "run-3f2a1c9e-...", "source": "mcp", "project": "myapp", "state": "succeeded", ...}
```

## Changelog

### Version 1.1.0 (2026-07-30)

- ROADMAP Phase 18 L-6: migrated the transport/registration layer from the `mcp` SDK's 1.x line
  (`mcp.server.fastmcp.FastMCP`) to its 2.x line (`mcp.server.MCPServer`) — the `docket[mcp]` pin
  widened from `mcp>=1.2.0,<2.0.0` to `mcp>=2.0.0` (no ceiling). This was verified by installing
  `mcp==2.0.0` and reading the shipped package directly, not assumed: `MCPServer` is a straight
  rename/relocation of `FastMCP`, keeping identical registration ergonomics (`add_tool(fn,
  name=...)`, `server.run(transport="stdio")`); `mcp.server.fastmcp` no longer exists as an import
  target in 2.0. **No contract change** — all ten tool names, arguments, return shapes, the
  audit-before-work guarantee, and the no-bypass guarantee (mutating tools still call the exact
  same `core/` functions) are unchanged; this is a transport-layer migration only. One
  SDK-integration-test-only difference: `MCPServer.call_tool` now returns a `CallToolResult` object
  (`.structured_content`/`.is_error`) rather than 1.x's `(content, structured_dict)` tuple — this
  affects only test code that calls the SDK's `call_tool` directly, not any tool's documented
  return shape (which was always the bare dict now found at `.structured_content`).

### Version 1.0.1 (2026-07-30)

- Retargeted the optional-dependency cross-reference at `core/pipeline.py` — `core/lobster.py`
  (the module it named) was deleted when `docket workflow`/Lobster was retired (ROADMAP D-16,
  Phase 16 W-3).

### Version 1.0.0 (2026-07-30)

- Initial specification for ROADMAP Phase 18 L-3: `docket mcp serve`, ten tools (`status`, `pods`,
  `queue`, `delegate`, `dispatch`, `runs`, `approvals_list`, `approvals_grant`, `approvals_deny`,
  `cost`), the audit/no-bypass/no-host design constraints, and the optional-dependency degrade
  path.
