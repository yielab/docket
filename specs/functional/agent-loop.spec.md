# Agent Loop Specification

**Version**: 1.2.0
**Status**: Implemented and **live in production**. `core/agent_loop.py` and
`edges/adapters/docket_runtime.py` (ROADMAP Phase 19 P19-5) are the first live callers of
`core/llm.py` (P19-1), `core/tools.py` (P19-2/P19-3) and `core/session.py` (P19-4).
`DocketDriver` was a complete, independently-tested `RuntimeDriver` implementation as of P19-5,
but not yet wired as any caller's default driver. **ROADMAP Phase 19 P19-7a (the runtime
cutover, 2026-08-03) is what wires it**: `edges.adapters.docket_runtime.default_driver()` (new
in that card) is now the resolution point `core/dispatch.py`'s hop execution, `core/trace.py`'s
`trace_ingest`, `core/utils.py`'s cost aggregation, and `cli/_agents.py`'s distillation turn all
call — this is the card that makes the OpenClaw daemon *unused* by production traffic, not yet
uninstalled (P19-7b removes it). See `pod-dispatch.spec.md`'s "Runtime driver resolution
(P19-7a)" for the dispatch-side contract this made real. ROADMAP Phase 19's P19-12 closed two
omissions P19-5 recorded honestly rather than papering over: the loop now narrows the tool
registry by role (`core.archetypes.registry_for_role`) and composes a system prompt from this
agent's SOUL.md/persona/WORKFLOW_AUTO.md (`core.identity.system_prompt_for_agent`) — see the new
"Per-role tool narrowing" and "System prompt composition" requirements below.
**Last Updated**: 2026-08-03

## Purpose

Decision D-19 has docket take ownership of the agent turn loop instead of delegating it to
the OpenClaw daemon. Every governance primitive docket had already built — the gated tool
registry, the `pre_tool_call` policy hook, the approval store, the argument-aware command
classifier, hash-chained audit, durable session history — could previously only act *between*
turns, because the daemon owned what happened *inside* one. This specification defines the
loop that finally closes that gap: compose context, call the model, gate and execute every
requested tool call through the existing chokepoint, feed results back, and repeat until one
of a fixed set of deliberate stop conditions fires.

## Scope

This specification covers:

- `core/agent_loop.py`'s `run_agent_turn`: message composition, the single tool-execution
  path, the stop-condition contract, truncation handling, and per-iteration session
  durability
- `edges/adapters/docket_runtime.py`'s `DocketDriver`: how the 7-method `RuntimeDriver`
  Protocol is implemented on top of the loop with no daemon underneath, including the
  driver's tool-containment root resolution and its `capabilities()` honesty contract
- That `run_agent_turn` narrows its tool registry by role (via
  `core.archetypes.registry_for_role`) and composes a system prompt (via
  `core.identity.system_prompt_for_agent`), once per turn, and what effect each has on the
  messages sent to the backend and persisted to session history (ROADMAP Phase 19 P19-12)

This specification does NOT cover:

- The chat-completion wire protocol or the `ChatBackend` port (`core/llm.py`,
  `edges/adapters/llm.py`, ROADMAP Phase 19 P19-1)
- The tool registry, the gate, or the chokepoint itself (`core/tools.py`, ROADMAP Phase 19
  P19-2/P19-3) — this spec only depends on `dispatch_tool`'s documented contract
- The archetype schema, `deniedTools` data, and `registry_for_role`'s own contract — see
  `role-archetypes.spec.md`'s "Per-role tool sets"; this spec only covers that `run_agent_turn`
  calls it and what that does to a turn
- The persona rendering/upsert primitives (`render_persona_block`, `upsert_persona_block`) or
  the identity file layout itself (`SOUL.md`, `WORKFLOW_AUTO.md`) — see `workspace-structure.spec.md`
  and `core/identity.py`'s own docstring; this spec only covers that `run_agent_turn` composes
  and injects the result
- Durable session storage or compaction (`core/session.py`, ROADMAP Phase 19 P19-4,
  `session-history.spec.md`) — this spec only depends on `load_messages`/`append_messages`'s
  documented contract
- Repointing any existing caller's default driver, deleting the OpenClaw ACL, or the
  docket-native fleet registry (ROADMAP Phase 19 P19-6/P19-7) — those are separate cards with
  their own specs when they land
- Turning measured token usage into a dollar figure — `cost_usd` is `0.0` on every result this
  driver produces; see the Requirements section below and `cost-tracking.spec.md`

## Requirements

### Single execution path

1. Every tool call a turn's model response requests **MUST** be dispatched exclusively
   through `core.tools.dispatch_tool`. `core/agent_loop.py` **MUST NOT** import
   `edges/adapters/toolbox.py` or invoke a `Tool.handler` directly.
2. A tool call that cannot be evaluated (unknown tool, unparseable arguments, missing
   required arguments) **MUST** be refused via the same `dispatch_tool` path, never silently
   dropped or executed anyway.

### Truncation safety

3. A response whose `finish_reason` indicates truncation (`ChatResponse.truncated`) **MUST
   NOT** have any of its tool calls dispatched, regardless of whether the truncation happened
   mid-argument or mid-prose.
4. A truncated response's assistant message **MUST NOT** be persisted to session history —
   persisting it would risk storing an assistant `tool_calls` entry with no answering `tool`
   message, which `core/session.py`'s atomic-unit contract forbids.
5. A turn that stops due to truncation **MUST** report `stop_reason="truncated"` and
   `ok=False`.

### Stop conditions

6. The loop **MUST** stop with `stop_reason="final_message"` and `ok=True` when a response
   carries no tool calls. This **MUST** be the only stop reason for which `ok` is `True`.
7. The loop **MUST** stop with `stop_reason="max_iterations"` once the configured maximum
   number of model round-trips would be exceeded, without making a further model call.
8. The loop **MUST** stop with `stop_reason="max_tool_calls"` once the configured maximum
   number of dispatched tool calls would be exceeded. A single response's tool-call batch
   **MUST** be dispatched wholly or not at all — never partially — so a batch that would push
   the total over the cap is refused in full before any call in it runs.
9. The loop **MUST** stop with `stop_reason="timeout"` once the configured wall-clock budget
   for the whole turn has elapsed, checked between iterations.
10. The loop **MUST** stop with `stop_reason="token_budget"` once the turn's cumulative
    *measured* token usage (`core.llm.TokenUsage`, real counts) exceeds the configured budget.
    This **MUST NOT** be computed from the bytes/divisor estimate `core/context.py`/
    `core/session.py` use for compaction.
11. A backend failure (`ChatResponse.ok=False`) **MUST** stop the loop with
    `stop_reason="backend_error"` and the backend's own `failure_kind`, without raising.
12. `AgentLoopResult.failure_kind` **MUST** be `None` if and only if `ok` is `True`.

### Durability

13. The incoming user message **MUST** be persisted to the session before any model call is
    made for that turn.
14. Each iteration that dispatches tool calls **MUST** persist the assistant message and every
    tool result answering it in one call to `core.session.append_messages` — never split
    across two separate calls, which could leave an orphaned `tool_calls` entry durable if
    the process died between them.
15. A turn **MUST NOT** write session history through any path other than
    `core.session.append_messages`/`load_messages`.

### Tracing

16. Every tool call actually dispatched **MUST** emit a `tool_call` trace event
    (`core/trace.py`) before it runs and a `tool_result` trace event after, using the same two
    event types `core/trace.py`'s `trace_ingest` already projects from daemon session logs.
17. A turn that dispatches no tool calls **MUST NOT** emit either event type.

### `DocketDriver` (`RuntimeDriver` conformance)

18. `run_turn` **MUST** map the loop's result onto `TurnResult` using the existing
    `FailureKind` vocabulary, and **MUST NOT** raise for an ordinary failure (missing agent
    metadata, an unresolvable model endpoint) — each **MUST** come back as
    `TurnResult(ok=False, ...)`.
19. `run_turn`'s `cost_usd` **MUST** always be `0.0`. Real token counts are recorded (folded
    into the session's `MeasuredUsage` by `core/session.py`), but this driver **MUST NOT**
    convert them into a dollar figure.
20. `run_turn`'s tool-containment root **MUST** be resolved with the precedence: an explicit
    worktree directory, then the agent's codebase, then its work directory, then its bare
    docket workspace directory.
21. `provision`/`teardown` **MUST** return `ok=True` without performing any daemon
    registration side effect (there is no daemon), and **MUST** say so in their `message`.
22. `capabilities().supports_provisioning` **MUST** be `False`, so a caller cannot mistake
    `provision`/`teardown`'s no-op for a real registration step.
23. `capabilities().reports_cost_usd` **MUST** be `False`.
24. `capabilities().supports_sessions` **MUST** be `True`, and `list_sessions`/
    `read_new_turns`/`usage` **MUST** read `core/session.py`'s durable storage, never a daemon
    session log.
25. `list_sessions` **MUST** scope its results to sessions whose key belongs to the requested
    agent id, even when that agent has been re-scoped to more than one project over its
    lifetime (`docket scope ... set`).

### Per-role tool narrowing (ROADMAP Phase 19 P19-12)

26. `run_agent_turn` **MUST** narrow the *registry* it was given via
    `core.archetypes.registry_for_role(registry, ctx.role)` exactly once per turn, before the
    first `backend.complete` call — not per iteration, since a role's tool set does not change
    mid-turn. Every use of the registry for the rest of the turn (advertising tool specs to the
    model, `dispatch_tool`) **MUST** use the narrowed result.
27. A tool call requesting a name the role's archetype denies **MUST** be refused by
    `dispatch_tool` as an unknown tool — the same refusal path an unrelated hallucinated tool
    name takes — never a distinct "forbidden for your role" code path. This is what makes the
    guarantee real: the model is not even advertised the tool, and if a call for it arrives
    anyway, the registry genuinely does not contain it.
28. `run_agent_turn` **MUST NOT** contain a branch on a specific role's name (e.g.
    `if ctx.role == "reviewer"`) to decide what to narrow — the denylist is data on the
    archetype (see `role-archetypes.spec.md`'s "Per-role tool sets"), and `registry_for_role` is
    the single, generic function consuming it.

### System prompt composition (ROADMAP Phase 19 P19-12)

29. `run_agent_turn` **MUST** compose a system prompt via
    `core.identity.system_prompt_for_agent(ctx.agent_id)` once per turn and, when non-empty,
    prepend it as a `system`-role message ahead of the turn's history and incoming user message.
    An empty result (no workspace, no identity files, no `agent_id`) **MUST NOT** add an empty
    `system` message.
30. The composed system prompt **MUST** fold together this agent's `SOUL.md` (if present), its
    live persona (read fresh from `.docket-meta.json`, not trusted from whatever `SOUL.md` has
    on disk), and its `WORKFLOW_AUTO.md` (the resume/durability contract; `core/memory.py`,
    `CONTRACT_VERSION`) — see `core/identity.py`'s `compose_system_prompt` for the exact
    composition rule.
31. The composed system prompt **MUST NOT** be persisted to session history through
    `core.session.append_messages` — it is recomposed fresh on every call to `run_agent_turn`,
    so a persona change or a re-seeded `WORKFLOW_AUTO.md` is reflected on the very next turn
    rather than frozen into a stored message.

## Interface Contracts

### Module API (`docket.core.agent_loop`)

```python
StopReason = Literal[
    "final_message", "max_iterations", "max_tool_calls",
    "timeout", "token_budget", "truncated", "backend_error",
]

class LoopConfig:                              # frozen
    max_iterations: int         # default config.AGENT_LOOP_MAX_ITERATIONS
    max_tool_calls: int         # default config.AGENT_LOOP_MAX_TOOL_CALLS
    wall_clock_timeout_s: float # default config.AGENT_LOOP_WALL_CLOCK_TIMEOUT_S
    token_budget: int           # default config.AGENT_LOOP_TOKEN_BUDGET
    request_timeout_s: int      # default config.AGENT_LOOP_REQUEST_TIMEOUT_S
    max_tokens: int | None = None
    temperature: float | None = None

class AgentLoopResult:
    ok: bool
    output: str
    stop_reason: StopReason
    iterations: int
    tool_calls_executed: int
    usage: TokenUsage
    error: str
    failure_kind: FailureKind | None
    raw: dict[str, Any]

def run_agent_turn(
    backend: ChatBackend,
    registry: ToolRegistry,
    ctx: ToolContext,
    session_key: str,
    message: str,
    *,
    config: LoopConfig | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AgentLoopResult: ...
```

### Module API (`docket.edges.adapters.docket_runtime`)

```python
class DocketDriver:                            # implements core.runtime_driver.RuntimeDriver
    backend_factory: Callable[[str], ChatBackend | None]   # default: edges.adapters.llm.client_for
    registry_factory: Callable[[], ToolRegistry]            # default: core.tools.builtin_registry

    def run_turn(self, agent_id, session_key, message, timeout=300, env=None, *, on_spawn=None) -> TurnResult: ...
    def provision(self, agent_id, workspace, model) -> ProvisionResult: ...
    def teardown(self, agent_id) -> TeardownResult: ...
    def list_sessions(self, agent_id) -> list[SessionSummary]: ...
    def read_new_turns(self, agent_id, session_id, offset) -> SessionSlice: ...
    def usage(self, agent_id) -> UsageReport: ...
    def capabilities(self) -> DriverCapabilities: ...
```

### Config (`docket.config`)

```text
AGENT_LOOP_MAX_ITERATIONS        default 20
AGENT_LOOP_MAX_TOOL_CALLS        default 40
AGENT_LOOP_WALL_CLOCK_TIMEOUT_S  default 300
AGENT_LOOP_TOKEN_BUDGET          default 100000
AGENT_LOOP_REQUEST_TIMEOUT_S     default 120
```

All five are environment-overridable, matching every other tunable in `config.py`.
`DocketDriver.run_turn`'s own `timeout` argument overrides `wall_clock_timeout_s` directly —
it is the same per-hop budget figure `core/dispatch.py` already resolves, not a second,
independently-tuned number.

### Return values

- `AgentLoopResult.ok is True` **MUST** imply `stop_reason == "final_message"` and
  `failure_kind is None`.
- `TurnResult.cost_usd` from `DocketDriver.run_turn` **MUST** always equal `0.0`.

## Examples

### A turn with one tool call

```python
from docket.core import agent_loop
from docket.core.tools import ToolContext, builtin_registry

ctx = ToolContext(agent_id="demo", role="implementer", project="demo", roots=(workspace,))
result = agent_loop.run_agent_turn(backend, builtin_registry(), ctx, "agent:demo:default", "read notes.md")
# result.ok, result.output, result.usage.total_tokens, result.tool_calls_executed
```

### A confused model that never stops requesting tools

Given a backend that always replies with another tool call, `run_agent_turn` with
`LoopConfig(max_iterations=20)` (the default) makes at most 20 model calls total, then
returns `AgentLoopResult(ok=False, stop_reason="max_iterations", failure_kind="invalid_output")`
— never an unbounded loop.

### A truncated reply carrying a tool call

```python
# response.truncated is True and response.message.tool_calls is non-empty
result = agent_loop.run_agent_turn(backend, registry, ctx, session_key, "go")
# result.ok is False; result.stop_reason == "truncated"; result.tool_calls_executed == 0
# core.session.load_messages(session_key) contains no trace of the truncated reply
```

### `DocketDriver` root resolution

Given an agent whose metadata sets both `codebase` and a raw `worktreeDir` field, a `read`
tool call resolves against the worktree directory, not the codebase — worktree wins.

### A Reviewer cannot dispatch a write

```python
ctx = ToolContext(agent_id="rev-1", role="reviewer", project="demo", roots=(workspace,))
result = agent_loop.run_agent_turn(backend, builtin_registry(), ctx, "agent:rev-1:default", "edit it")
# the model was never advertised "write"/"edit"/"bash" (registry_for_role narrowed them out);
# if it requests one anyway, dispatch_tool's tool_result answers "REFUSED: unknown tool ..."
# result.ok can still be True — the turn completes normally, just without that call executing
```

### The system prompt reaches the model

```python
# ws/SOUL.md exists, ws/WORKFLOW_AUTO.md exists, agent has a persona set
result = agent_loop.run_agent_turn(backend, registry, ctx, session_key, "hello")
# backend.complete's first call's messages[0].role == "system"
# that message's content folds in SOUL.md, the live persona, and WORKFLOW_AUTO.md
# core.session.load_messages(session_key) contains no "system"-role message afterward
```

## Validation

### Pre-conditions

- `run_agent_turn` **MUST** be given a `ToolContext` whose `roots` already reflects the
  correct containment boundary for this call — the loop itself never inspects or widens it.
- `DocketDriver.run_turn` **MUST** be given an `agent_id` with a readable `.docket-meta.json`
  to succeed; a missing or malformed one is a defined failure (`failure_kind="invalid_output"`),
  not a precondition violation that raises.

### Post-conditions

- After a turn that stops with `stop_reason="final_message"`, `core.session.load_messages`
  for that session key **MUST** end with the final assistant message.
- After a turn that stops with `stop_reason="truncated"` or `stop_reason="max_tool_calls"`
  (batch-rejected case), `core.session.load_messages` **MUST NOT** contain any message from
  the rejected exchange.
- After any turn that dispatches at least one tool call, the session's trace file **MUST**
  contain exactly one `tool_call` and one `tool_result` event per dispatched call, in that
  order.

### Invariants

- No module other than `core/tools.py`'s own internals **MUST** ever call a `Tool.handler`
  directly; `core/agent_loop.py` in particular never does.
- `DocketDriver.run_turn`'s `cost_usd` **MUST** be `0.0` on every call, regardless of how much
  token usage the turn recorded.
- Two agents **MUST NOT** be able to see each other's sessions through
  `DocketDriver.list_sessions`.
- A role's denied tool names **MUST NOT** be reachable through `dispatch_tool` for that role's
  turn — proven at the dispatch level (an "unknown tool" refusal), never merely by inspecting
  `RoleArchetype.denied_tools` or a `ToolRegistry`'s name set.
- The system prompt `run_agent_turn` composes **MUST NOT** appear in
  `core.session.load_messages`'s stored history for that session.

## Changelog

### Version 1.2.0 (2026-08-03)

- **ROADMAP Phase 19, card P19-7a (the runtime cutover).** `edges.adapters.docket_runtime.py`
  gained its own `default_driver()` singleton resolver (mirroring
  `edges.adapters.openclaw.default_driver()`'s pattern), and every production caller that used to
  resolve the ACL's version now resolves this one instead: `core/dispatch.py`'s two hop-execution
  call sites, `core/trace.py`'s `trace_ingest`, `core/utils.py`'s `aggregate_cost`/`cost_history`,
  and `cli/_agents.py`'s `_run_distillation` (D-18's first self-originated LLM call). No change to
  `DocketDriver`'s own implementation or public signature — this version documents that the loop
  this spec describes is now the one real turns actually run on, not just a tested-but-unused
  parallel path. See `pod-dispatch.spec.md` v6.0.0 for the dispatch-side behavior changes this
  causes (cost_usd always 0.0 in production, `docket runs cancel` cannot interrupt an in-flight
  turn). No new trace event types, no new CLI flags, no golden diff (no new CLI surface).

### Version 1.1.0 (2026-08-02)

- **ROADMAP Phase 19, card P19-12 (per-role tool sets + identity composition).** Closed two
  omissions this spec's own Version 1.0.0 recorded as out of scope for P19-5: `run_agent_turn`
  now narrows its tool registry by role once per turn (`core.archetypes.registry_for_role`,
  new requirements 26–28) and composes a system prompt from `SOUL.md`/the live persona/
  `WORKFLOW_AUTO.md` (`core.identity.system_prompt_for_agent`, new requirements 29–31). Both are
  resolved once per turn, not per iteration; the system prompt is never persisted to session
  history. No change to `run_agent_turn`'s or `DocketDriver`'s public signatures — this is a
  behavior change inside an unchanged interface. No CLI surface added; the 18 golden cases are
  unaffected.

### Version 1.0.0 (2026-07-31)

- Initial specification: the turn loop (`core/agent_loop.py`) and the daemon-free
  `RuntimeDriver` built on top of it (`edges/adapters/docket_runtime.py`), covering single
  tool-execution-path enforcement, truncation safety, all stop conditions, per-iteration
  session durability, tool-call tracing, and `DocketDriver`'s root-resolution and honesty
  contracts (ROADMAP Phase 19 P19-5, decision D-19).
