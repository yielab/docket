# MCP Server Contract Specification

**Version**: 1.8.0
**Status**: Implemented
**Last Updated**: 2026-10-03

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
- Agent-side MCP *client* configuration (Docket consuming MCP tools inside a turn); see `mcp-client.spec.md`. The retired external-runtime feasibility spike is historical and lives in this spec’s changelog, ROADMAP, and Git history.

## Design constraint: a server, never a host

`docket mcp serve` exposes docket's own control plane as MCP tools for an external client to
call. It MUST NOT become an MCP *host*: this server has no notion of an upstream MCP server to
call; it only ever answers requests. Docket consuming external MCP servers' tools inside an agent
turn does exist since decision D-19 (docket owns the loop), but it lives in `core/mcp_tools.py`
and `DocketDriver.run_turn` (see `mcp-client.spec.md`), never in this server.

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

`docket mcp` with no subcommand, or any subcommand other than `serve` or `servers` (the MCP
client configuration commands, see `mcp-client.spec.md`), prints usage (to stderr — see stdio
discipline below) and exits: `0` for no subcommand, `1` for an unrecognized one.

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

Thirteen tools, grouped by the control-plane surface they expose. Every response shape below is a bare
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

**Purpose**: Fleet-wide status snapshot — enabled channels, every agent's
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
MCP-side bypass, auto-approve, or alternate transition path of any kind. If *token* gates a
pod-dispatch task waiting on it (`waiting_approval`), the same `core.dispatch.resolve_waiting_approval`
call the CLI/HTTP/Telegram channels make resumes it: the task returns to `pending` with the exact
hop it stopped on handed to the next dispatch run as a single-use gate override (see
pod-dispatch.spec.md, "require_approval gate and waiting_approval"). This resolution runs even on
an already-granted token (see Failure modes) — it is not skipped just because the call raises.
**Output**: `{"ok": true, "token": "apr-...", "state": "granted"}`.
**Failure modes**: raises if the token is unknown, or if it is not currently `pending` (already
granted, denied, or expired) — an already-granted token raises rather than silently reporting
success, a deliberate difference from `docket approve`'s CLI behavior (which treats a repeat grant
as a benign warning, exit 0): an automated MCP caller should learn explicitly that its call did
not perform a fresh state transition, rather than receiving an ambiguous `"ok": true` for a call
that changed nothing. The `resolve_waiting_approval` follow-up still runs before this raise, so a
dispatch task stuck `waiting_approval` from an earlier grant that never reached it is still freed.

### `approvals_deny`

**Purpose**: Deny a pending approval token — identical to `docket deny <token>` / `docket serve`'s
`POST /approvals/<token>` with `{"action": "deny"}`.
**Arguments**: `token` (string, required).
**Gating**: calls `core.approval.approval_deny(token, channel="mcp")`, mirroring
`approvals_grant`. If *token* gates a pod-dispatch task waiting on it, the same
`core.dispatch.resolve_waiting_approval` follow-up fails that task immediately
(`failureKind: "approval_denied"`) — never auto-retried by a later dispatch, even with `--resume`.
**Output**: `{"ok": true, "token": "apr-...", "state": "denied"}`.
**Failure modes**: same as `approvals_grant`, including that the `resolve_waiting_approval`
follow-up still runs before the raise.

### `task_answer`

**Purpose**: Answer a task's parked `input` question — identical to `docket pod <project>
answer <task-id>` / `docket serve`'s `POST /tasks/<task-id>/answer`.
**Arguments**: `project` (string, required), `task_id` (string, required), `action` (string,
required — `"accept"`, `"decline"` or `"cancel"`), `content` (object, optional).
**Gating**: calls `core.answers.answer_task(channel="mcp", actor="mcp")` — the exact function
every other surface calls, so the schema/`pre_input` screen and the resume onto the step's own
route are byte-for-byte the same as `docket pod <p> answer`/`docket chat`/the HTTP route.
**Output**: `{"ok": true, "task": "<task_id>", "project": "<project>", "action": "accept"}`.
**Failure modes**: raises (`McpToolError`) naming the policy id if the answer's `content` matched
a `pre_input` `block` policy; raises naming the underlying reason for an unknown task, a task not
currently `waiting_input`, or `content` failing the question's own `requestedSchema`.

### `task_pregrant`

**Purpose**: Record a single-use pre-grant for one exact command on one task, ahead of dispatch
(ADR 0016 §10) — identical to `docket pod <project> pregrant <task-id> "<command>"` / `docket
serve`'s `POST /tasks/<task_id>/pregrants`.
**Arguments**: `project` (string, required), `task_id` (string, required), `command` (string,
required — the exact command line to pre-approve), `tool` (string, optional, default `"bash"`).
**Gating**: calls `core.interruptions.record_pregrant(project, task_id, command, tool=tool,
channel="mcp", actor="mcp")`, which calls `core.approval.create_pregrant` exactly as an in-turn
park does, then appends the grant to the task's own `pregrants` list — the same shape a live park
already produces. When the pipeline later reaches that exact call (matched by
`core.operator_contract.canonical_args_digest`), it passes once without asking again.
**Output**: `{"ok": true, "token": "apr-...", "task": "<task_id>", "project": "<project>"}`.
**Failure modes**: raises (`McpToolError`) if *task_id* is not in *project*'s own task queue.

### `inbox`

**Purpose**: The derived operator inbox — every pod's tasks needing a human, plus pending
approvals, failed/done/running context — identical to `docket serve`'s `GET /inbox`.
**Arguments**: `since` (string, optional) — an ISO timestamp; restricts `doneSince` to tasks that
completed after it. Omitted, `doneSince` lists every terminal task.
**Output**: `InboxView` (`core/operator_contract.py`), `by_alias` — `{"needsYou": [...], "failed":
[...], "doneSince": [...], "running": [...], "next": "..." | null}`, matching `docket inbox
--json` for the same state.
**Failure modes**: none beyond the SDK's own argument-shape validation.

### `cost`

**Purpose**: **Recorded** USD spend — one agent or the whole fleet.
**Arguments**: `agent_id` (string, optional) — one agent's totals; omitted for the whole fleet.
**Output**: `{"agents": [...], "totalUsd": ...}` (matches `docket cost --json`) when `agent_id` is
omitted; a single agent's cost record when given.
**Failure modes**: raises if `agent_id` is given but not a known project agent.
**Cost-reporting discipline**: this figure is recorded spend from session data, which is always
`0.0` today because `DocketDriver` records measured tokens but no dollar figure; the
`MODEL_PRICING` estimate `docket cost` shows is not returned here. It is never a
projected/estimated figure, and never presented as a dollar *savings* claim (a standing
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
concern, not docket's — see Scope above).

### A representative tool call/response (status)

```json
// → CallToolRequest {"name": "status", "arguments": {}}
// ← CallToolResult (structuredContent)
{
  "apiVersion": "3",
  "timestamp": "2026-07-30T12:00:00Z",
  "channels": ["telegram"],
  "agents": [ /* ... */ ],
  "totalCostUsd": 0.0
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

### Version 1.8.0 (2026-10-03)

- **`status` follows `/status.json` to API version 3 (legacy purge).** The always-`"inactive"`
  `gateway` key is gone from the `status` tool's output (it is `serve.build_status()`, the same
  payload); the purpose line and the representative example drop it and show `apiVersion` `"3"`.

### Version 1.7.0 (2026-09-29)

- **One more tool this close missed, thirteen total.** `task_pregrant(project, task_id, command,
  tool="bash")` — identical to `docket pod <project> pregrant` / `POST /tasks/<id>/pregrants`
  (both shipped by P34-15, ADR 0016 §10) — was registered in `_TOOL_NAMES` and audited from the
  start but never documented here. `docket mcp serve --help`'s own tool list and count
  (`cli/__init__.py`) were also stale at the old twelve and did not name `task_pregrant`; both
  corrected.

### Version 1.6.0 (2026-09-29)

- **Two new tools (Phase 34, D-50, ADR 0016), twelve total.** `task_answer(project, task_id,
  action, content=None)` calls `answer_task(channel="mcp", actor="mcp")`, raising
  `McpToolError` on rejection; `inbox(since=None)` returns the same derived `InboxView` shape
  `GET /inbox` and `docket inbox --json` return. `docket mcp serve --help` and
  `docs/commands.md`'s generated tool count and list corrected from a stale ten to the current
  twelve.

### Version 1.5.0 (2026-09-21)

- `approvals_grant`/`approvals_deny` now resolve any dispatch task they gated, including on an `ApprovalNoop` (W36-C4). Previously a task decided over MCP stayed `waiting_approval`.

### Version 1.4.1 (2026-09-18)

- Alignment pass, no tool contract change. "A server, never a host" no longer says docket refuses
  to execute other MCP servers' tools in a turn: since D-19 it does, through `core/mcp_tools.py`,
  and this server still never calls upstream. Syntax now names `servers` as a recognized
  subcommand beside `serve`. `cost` no longer says "daemon-recorded": the recorded figure is
  always `0.0` (`DocketDriver`). The `status` example now shows `"gateway": "inactive"` and
  `totalCostUsd: 0.0`, the only values the code can return. Dropped a pointer to the removed
  L-4 scope note.

### Version 1.4.0 (2026-08-19)

- W21-C1 daemon-free truth pass: removed the superseded daemon-side MCP registry spike from the
  current contract. Docket's MCP server and client boundaries now point only at their owning specs;
  the dated investigation remains in ROADMAP and Git history.

### Version 1.3.0 (2026-07-31)

- Corrected the "Scope" section's agent-side MCP client cross-reference. It previously pointed at
  L-4 (a daemon-gated, unbuilt card) as the place agent-side MCP consumption would eventually
  live; decision D-19 has since had docket own the turn loop directly, and ROADMAP Phase 19
  P19-10 built docket's own MCP client straight into `core/tools.py`'s gated registry — no daemon
  involved at all. The scope note now points at the real spec, `mcp-client.spec.md`, and states
  plainly that it supersedes the L-4 framing. No change to this server's own contract (tools,
  transport, audit/no-bypass guarantees) — documentation accuracy only.

### Version 1.2.0 (2026-07-30)

- **ROADMAP Phase 18 L-4 spike concluded: the daemon-side MCP registry is real upstream, not
  present in this fleet's targeted daemon.** Investigated whether docket can manage the OpenClaw
  daemon's own MCP client configuration (the *other* direction from this server) through the ACL.
  Verdict: **yes, the capability exists** — a genuine `mcp.servers` config surface plus a full
  `openclaw mcp add|set|list|show|status|doctor|probe|configure|tools|login|logout|reload|unset`
  CLI family, confirmed live against an isolated run of the current stable `openclaw@2026.7.1`
  (a real `add`/`list`/`show`/`status`/`unset` roundtrip succeeded exactly as documented, all
  reachable via the same subprocess-CLI pattern the ACL already uses everywhere) — but **not
  present** in the daemon version this project actually targets and has verified everywhere else
  in the codebase, `openclaw 2026.2.23` (confirmed directly: no `mcp` subcommand, `config get
  mcp.servers` reports the path unknown). Per the card's own instructions, this is a "yes, but the
  capability doesn't exist yet [in the deployed fleet]" outcome: no code was written. See "L-4
  spike findings" above for the full dated evidence trail, including a methodology note on
  sandboxing a newer CLI probe safely.

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
