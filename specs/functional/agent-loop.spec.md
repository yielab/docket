# Agent Loop Specification

**Version**: 1.15.0
**Status**: Implemented and **live in production**. `core/agent_loop.py` owns the turn and
`edges/adapters/docket_runtime.py::default_driver()` is the production `RuntimeDriver` resolution
point for dispatch, trace ingestion, usage aggregation, and distillation. The loop narrows the tool
registry by role (`core.archetypes.registry_for_role`) and composes a system prompt from this
agent's SOUL.md/persona and one runtime-safe projection of its startup contract
(`core.identity.system_prompt_for_agent`) — see the
"Per-role tool narrowing" and "System prompt composition" requirements below. **Wave 17** gave
`DocketDriver` an `mcp_loader` seam, called before this loop's registry-narrowing step, so a
configured MCP server's tools are reachable from a live turn and correctly narrowed by role — see
`mcp-client.spec.md` for the wiring and `role-archetypes.spec.md`'s requirement 6 for the
kind-based narrowing this depended on. **Wave 20 card W20-C2** made session compaction part of
this same live path before each task-completion call. **Wave 20 card W20-C4** separates the durable
history coordinate from the trace coordinate so pod steps do not replay another role's raw turns.
Every prospective task or compaction request is preflighted against the selected endpoint's
registered context window when that endpoint advertises one; same-turn tool growth is compacted
through the durable atomic path before transport rather than relying only on pre-turn history size.
When the endpoint also advertises a positive output limit, the loop reserves one bounded,
tool-free terminal response before another ordinary round can exhaust the cumulative measured
turn budget.
**Last Updated**: 2026-08-26

## Purpose

Decision D-19 has docket own the agent turn loop. Every governance primitive docket had built — the gated tool
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
- The live trigger and adapter for `core.session.compact_session`: ordering, non-recursion,
  measured usage accounting, failure behavior, and privacy-safe trace payloads (W20-C2)
- The optional trace-session coordinate used when one task-wide audit stream spans multiple
  independently persisted step histories (W20-C4)
- The cumulative measured-token preflight and one-shot, tool-free terminal-response reservation
  that prevent an optional tool round from consuming the last usable turn budget (W25-C3)
- Request-fit convergence that prevents a durable suffix or prefix from being summarized repeatedly
  without any intervening task/tool growth (W25-C6)
- Typed consecutive tool-denial recovery that stops a non-converging turn after three denied,
  non-executed results by default while preserving the completed atomic units (W25-C10)

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
- Durable session storage and compaction planning internals (`core/session.py`, ROADMAP Phase 19
  P19-4, `session-history.spec.md`) — this spec owns only their live-loop integration
- The docket-native fleet registry; see `agent-lifecycle.spec.md`
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

13. The incoming user message **MUST** be persisted after the pre-turn compaction check and before
    the first task-completion model call. The compaction summarizer is the sole model call allowed
    before that append; if it fails, the incoming message is not accepted into durable history.
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
    on disk), and one authoritative runtime projection of Docket's generated startup contract.
    The live projection **MUST NOT** send raw `WORKFLOW_AUTO.md` startup prose that tells a model
    to open or update `HEARTBEAT.md`, `MEMORY.md`, or `memory/`: those instructions are for a
    manual/external reset path, while the live runtime has already read the state itself. Instead,
    it **MUST** carry the exact project roots already resolved into `ToolContext.roots`, state once
    that private control files are already loaded/read-only and are never project-tool targets
    (explicitly including shell execution), and state that returning the completed result is
    sufficient because Docket owns turn durability. The same fresh composition **MUST** append
    current private-workspace state in this priority order: the runtime-safe projections of
    `HEARTBEAT.md` and `AGENTS.md`, optional `TOOLS.md`, then `MEMORY.md`. The HEARTBEAT projection
    **MUST** retain its H2 state sections while omitting the generated preamble and HTML authoring
    template that tell the model to maintain that file. A custom HEARTBEAT without H2 state remains
    intact. The AGENTS projection **MUST** structurally omit the generated `## Session Startup`
    section, whose private-file reads duplicate the runtime, while preserving the title,
    `## Red Lines`, and other custom sections byte-for-byte; a custom AGENTS file without that
    heading remains intact. Prompt composition **MUST NOT** rewrite any source workspace file or
    regex-filter arbitrary prose.
    The projected contract plus appended state **MUST** fit the existing
    `CONTEXT_TOKEN_BUDGET` estimate, preserve higher priorities first, and mark any
    truncation/omission visibly rather than silently growing an endpoint's context or dropping
    state. An agent with no identity/startup/private files still composes no system message.
31. The composed system prompt **MUST NOT** be persisted to session history through
    `core.session.append_messages` — it is recomposed fresh on every call to `run_agent_turn`,
    so a persona change or a re-seeded `WORKFLOW_AUTO.md` is reflected on the very next turn
    rather than frozen into a stored message.

### Live session compaction (Wave 20 W20-C2)

32. Before loading replay history or appending the incoming message, `run_agent_turn` **MUST** call
    `compact_session` with the role's history budget (or the explicit test/operator override).
    The compaction check and any required summary completion **MUST** finish before the first
    task-completion `ChatBackend.complete` call.
33. The live summarizer **MUST** be one direct, tool-free call through the `ChatBackend` instance
    already supplied to `run_agent_turn`. It **MUST NOT** call `run_agent_turn`, advertise tools,
    resolve another backend, or persist its prompt/output as a conversation. This structural path,
    together with `compact_session`'s re-entry guard, is the explicit recursion barrier.
34. The summarizer runner **MUST** receive a deterministic session key distinct from the target
    key. No summarizer messages are persisted under that isolated key or the target key; only the
    resulting compacted summary is written to the target on success.
35. The summarizer response's endpoint-reported `TokenUsage` **MUST** be added to both the returned
    turn usage and the target session's measured usage. These measured values **MUST NOT** drive
    compaction; before/after window sizes remain named estimates from
    `core.context.estimate_tokens`.
36. A not-ok/timeout, truncated, empty, or tool-requesting summarizer response **MUST** abort the
    turn with `stop_reason="compaction_failed"`, preserve the prior message history byte-for-byte,
    and make no task-completion backend call. This invalid-summary classification **MUST** take
    precedence when that same response's measured usage also crosses the cumulative turn budget;
    endpoint-reported usage, when non-zero, is still recorded as usage metadata and does not alter
    the preserved messages. A truncated partial summary **MUST NEVER** become durable history.
37. Every pre-turn compaction check **MUST** emit one `session_compaction` trace event with status
    `no_op`, `succeeded`, or `failed`; before/after message counts; before/after estimated tokens;
    and groups summarized. The payload **MUST NOT** contain raw history, prompts, summaries, or
    measured token counts mislabeled as estimates.
38. A live compaction **MAY** make multiple bounded summary completions. Every completion **MUST**
    stay on the same non-recursive, tool-free adapter; its endpoint-reported usage **MUST** be
    accumulated into turn/session measured usage, and its timeout **MUST** be capped by the turn's
    remaining wall-clock budget at call time.
39. The compaction trace payload **MUST** additionally report summary-round count and the maximum
    estimated prompt tokens sent in any round. It **MUST NOT** include any prompt or summary text.

### History and trace identity (Wave 20 W20-C4)

40. `run_agent_turn`'s `session_key` **MUST** remain the sole coordinate for durable history,
    compaction, summarizer-key derivation, and measured session usage. Optional `trace_project`
    and `trace_session_key` values **MUST** select only the trace directory/stream; when omitted
    they **MUST** default to `ctx.project`/`session_key` so every existing non-dispatch caller
    remains behaviorally unchanged.
41. Every `session_compaction`, `request_fit`, `budget_warning`, `tool_call`, and `tool_result`
    event produced inside the loop **MUST** use the resolved trace coordinate. No trace helper may
    cause messages or usage to be loaded from or appended to that trace coordinate.
42. `DocketDriver.run_turn` **MUST** pass its `session_key` to `ToolContext` and the loop as the
    durable-history identity, and **MUST** forward optional keyword-only `trace_project` and
    `trace_session_key` values to the loop. The `RuntimeDriver` port and its canonical fake
    **MUST** accept the same additive keywords; callers that omit them preserve the prior
    five-argument behavior.
43. `DocketDriver.list_sessions(agent_id)` **MUST** continue enumerating every durable key with the
    `agent:<agent-id>:` prefix, including base scoped sessions and W20-C4 step-scoped dispatch
    histories. A trace-only task key is not a durable session and **MUST NOT** be fabricated by
    session enumeration.

### Per-request endpoint fit (Wave 25 W25-C2)

44. The stored provider's model entry **MUST** reach the live client with its positive
    `contextWindow` and `maxTokens` values. Selection **MUST** match the exact model id, not merely
    the provider. A process-wide `DOCKET_LLM_BASE_URL` override **MUST NOT** inherit stored limits
    from the provider it replaces; without independently advertised override limits its window is
    explicitly unknown and existing hosted/override behavior remains available without a false fit
    guarantee.
45. Before every task or compaction `ChatBackend.complete` call whose context window is known, the
    loop **MUST** estimate the complete prospective input—messages, tool-call metadata, advertised
    tool schemas, model/protocol framing—and add the configured maximum-output reserve. The shipped
    OpenAI-compatible backend **MUST** estimate from the same payload builder used for transport.
    This bytes/`CONTEXT_BYTES_PER_TOKEN` figure **MUST** be labelled an estimate and **MUST NOT** be
    folded into measured `TokenUsage`.
46. A known-window request with no positive maximum-output reserve **MUST** fail locally rather than
    claim it fits. When the window is unknown, the loop **MUST** preserve existing behavior and
    expose that no registered-window guarantee was applied; it **MUST NOT** invent a model/window
    table.
47. When a task request is estimated over-window, the loop **MUST** invoke the existing durable,
    fail-closed session compactor with a smaller target, preserve complete assistant-tool/result
    atomic units, reload the accepted messages, and retry the estimate before transport. Every
    compactor completion is subject to the same request preflight with tools disabled.
48. If every eligible range is locally irreducible or the accepted summary plus output reserve
    still exceeds the registered window, the loop **MUST**
    make no task HTTP call and return `stop_reason="context_fit"`,
    `failure_kind="invalid_output"`, and an actionable error containing the estimated request,
    registered window, and output reserve. A failed, timed-out, truncated, empty, or tool-requesting
    summarizer instead **MUST** retain requirement 36's `compaction_failed` outcome and original
    failure kind, abort immediately, and never try another range. Already-durable history remains
    valid and no tool call/result unit is split.
49. Every prospective completion **MUST** emit a privacy-safe `request_fit` trace containing its
    purpose (`task` or `compaction`), status (`fits`, `failed`, or `unknown_window`), estimated
    input, output reserve, registered window (or null), and an explicit estimate marker. It **MUST
    NOT** contain messages, prompts, tool arguments/results, or measured usage.

### Terminal response reservation (Wave 25 W25-C3)

50. When the selected endpoint supplies a positive maximum-output reserve, every task and
    compaction completion **MUST** be preflighted against the cumulative turn budget before
    transport. The comparison **MUST** add measured usage from prior completions to the prospective
    request-input estimate and the same output reserve used by requirement 45. Estimates **MUST
    NOT** be added to `TokenUsage`; an endpoint with no positive output reserve preserves the
    existing measured post-response guard because Docket cannot truthfully promise an output bound.
51. When a normal tool-enabled task request would exceed that prospective cumulative bound, the
    loop **MUST** make at most one finalization attempt. That request **MUST** explicitly ask for a
    truthful terminal response from work already completed, advertise no tools, preserve the
    current durable representation of the complete task and whole assistant/tool-result atomic
    units, and itself pass both the per-request context-window check and the cumulative turn-budget
    check before transport. This cumulative decision **MUST** be made on the complete current
    request before request-fit compaction; when it selects finalization, no raw current-turn unit may
    first be replaced by a summary merely to fit an ordinary round that the remaining turn budget
    cannot fund. If the complete request initially fits the cumulative budget and requirement 47
    legitimately accepts a whole-unit durable summary to satisfy the endpoint window, later summary
    usage may still select finalization; that request **MUST** use the exact reloaded durable summary,
    never a stale pre-compaction snapshot. In both branches Docket preserves atomic units: raw units
    when budget selects finalization first, or the accepted durable replacement when window-fit
    compaction was selected first.
52. If the tool-free finalization request fails the endpoint-window check, it **MUST** retain
    W25-C2's `stop_reason="context_fit"`; this card does not reinterpret a context-window failure as
    cumulative spend. If the request fits that window but cannot fit the cumulative turn budget,
    the loop **MUST** return `stop_reason="token_budget"` and `failure_kind="invalid_output"`
    without another backend call. Its error **MUST** report the configured budget, measured usage,
    prospective input estimate, output reserve, and remaining measured budget without exposing
    message content.
53. A finalization response carrying any tool call **MUST NOT** dispatch or persist that call and
    **MUST** terminate with `stop_reason="token_budget"` and `failure_kind="invalid_output"`.
    A tool-free, non-truncated response is persisted normally and remains the sole successful
    `final_message` outcome. Backend failure, truncation, and timeout retain their existing
    fail-closed outcomes; none causes a second finalization attempt. A truncated ordinary or
    finalization response persists only its non-zero endpoint-reported usage metadata—never its
    assistant content or tool calls.
54. Entering or refusing finalization **MUST** emit one privacy-safe `budget_warning` event on the
    resolved trace coordinate. Its payload **MUST** distinguish the action/status and include the
    configured budget, prior measured usage, remaining measured tokens, normal/finalization input
    estimates, output reserve, and an explicit estimate marker. It **MUST NOT** contain messages,
    prompts, tool arguments, tool results, or model output.
55. After the existing backend-error and truncation checks retain their more specific outcomes, a
    successful, non-truncated response whose measured usage crosses the hard cumulative limit
    **MUST NOT** dispatch or persist tool calls from that response and **MUST** return the existing
    `token_budget` failure. Previous complete durable units remain intact.
56. Within one task request-fit evaluation, an accepted compaction of the current-turn suffix or
    historical prefix **MUST** be followed by exactly one reload and task-fit recheck, and that same
    logical segment revision **MUST NOT** be selected for compaction again. Segment revision identity
    **MUST** be private and content-derived: if a concurrent durable append changes a suffix between
    selection, locked compaction, reload, and the next fit check, the new revision remains eligible
    rather than being falsely marked irreducible. Only the newly appended, unprotected tail may be
    selected next; the already-accepted summary prefix **MUST NOT** re-enter its prompt. The other,
    still-untried segment remains eligible, and `compact_session` retains its bounded internal
    hierarchical rounds. The outer convergence-attempt cap **MUST** be fixed when the evaluation
    starts so continuous appends cannot move it indefinitely. Before accepting either a fit result
    or a prospective cumulative-budget decision, the loop **MUST** compare the durable revision
    immediately after that preflight with the revision whose messages were estimated; a changed
    revision **MUST** be reloaded and preflighted under the same fixed cap, never transported stale.
    The current task anchor **MUST** retain its durable identity across those reloads rather than be
    rediscovered by matching text, so an appended user message with identical content remains part
    of the new suffix and cannot turn the original task or an accepted summary into historical prefix.
    The guarantee ends at that post-preflight revision check: an append completed afterward remains
    durable for a later turn but is not promised into the already-validated in-flight request. If no
    untried segment can reduce an oversized request, the loop **MUST** return `context_fit` locally
    without another summarizer or task transport. A later completed tool result starts a new
    request-fit evaluation. A failed compaction is not accepted progress and **MUST** abort under
    requirements 36 and 48 before another segment is attempted. This convergence guard **MUST NOT**
    add public fields to `request_fit` or expose revision fingerprints in traces.
57. A denied, non-executed tool result **MUST** increment one per-turn consecutive-denial counter;
    an allowed, executed tool result (including an executed handler failure) **MUST** reset it.
    Other results neither increment nor reset it.
58. The default `max_consecutive_tool_denials` **MUST** be three, sourced from
    `config.AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS`, independently of `max_tool_calls`.
59. A model response's tool-call batch **MUST** retain the existing all-dispatched-or-none preflight.
    After dispatch, the complete assistant message and every answering tool result plus measured
    usage **MUST** be appended atomically before evaluating the consecutive-denial stop.
60. Once the configured consecutive-denial limit is reached, the loop **MUST** stop locally with
    `stop_reason="tool_denials"`, `failure_kind="invalid_output"`, and no further backend call. Its
    bounded actionable error **MUST** contain only the consecutive count and ordered denial kinds,
    never tool arguments, approval tokens, refusal reasons, or private values.
61. Each denied `tool_result` trace **MUST** include its stable `denialKind`; allowed/executed trace
    payloads retain their existing fields and **MUST NOT** invent a denial kind.

## Interface Contracts

### Module API (`docket.core.agent_loop`)

```python
StopReason = Literal[
    "final_message", "max_iterations", "max_tool_calls",
    "timeout", "token_budget", "truncated", "backend_error", "compaction_failed", "context_fit",
    "tool_denials",
]

class LoopConfig:                              # frozen
    max_iterations: int         # default config.AGENT_LOOP_MAX_ITERATIONS
    max_tool_calls: int         # default config.AGENT_LOOP_MAX_TOOL_CALLS
    max_consecutive_tool_denials: int # default config.AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS
    wall_clock_timeout_s: float # default config.AGENT_LOOP_WALL_CLOCK_TIMEOUT_S
    token_budget: int           # default config.AGENT_LOOP_TOKEN_BUDGET
    request_timeout_s: int      # default config.AGENT_LOOP_REQUEST_TIMEOUT_S
    max_tokens: int | None = None
    temperature: float | None = None
    history_budget_tokens: int | None = None # None resolves through context.budget_for_role
    summary_input_budget_tokens: int | None = None # None follows resolved history budget
    context_window_tokens: int | None = None # selected endpoint's registered input+output window

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
    trace_project: str | None = None,     # defaults to ctx.project; traces only
    trace_session_key: str | None = None, # defaults to session_key; traces only
) -> AgentLoopResult: ...
```

### Module API (`docket.edges.adapters.docket_runtime`)

```python
class DocketDriver:                            # implements core.runtime_driver.RuntimeDriver
    backend_factory: Callable[[str], ChatBackend | None]   # default: edges.adapters.llm.client_for
    registry_factory: Callable[[], ToolRegistry]            # default: core.tools.builtin_registry
    mcp_loader: Callable[[ToolRegistry, str], list[Any]]    # default: wraps core.mcp_tools.load_mcp_tools
                                                             # (ROADMAP Phase 19/wave 17 -- see mcp-client.spec.md)

    def run_turn(
        self, agent_id, session_key, message, timeout=300, env=None, *, on_spawn=None,
        trace_project=None, trace_session_key=None,
    ) -> TurnResult: ...
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
AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS default 3
AGENT_LOOP_WALL_CLOCK_TIMEOUT_S  default 300
AGENT_LOOP_TOKEN_BUDGET          default 100000
AGENT_LOOP_REQUEST_TIMEOUT_S     default 120
```

All six are environment-overridable, matching every other tunable in `config.py`.
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
- When trace coordinates differ from the history coordinate, messages and measured usage **MUST**
  exist only under `session_key`, while loop trace events **MUST** exist only under
  `<trace_project>/<trace_session_key>`.

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

### Version 1.15.0 (2026-08-26)

- W25-C10 stops after three consecutive typed, non-executed tool denials by default, only after
  persisting the complete atomic unit and usage. An allowed executed call resets the counter;
  `tool_denials` exposes only the count and ordered denial kinds and makes no further model request.

### Version 1.14.0 (2026-08-26)

- W25-C8 replaces the contradictory raw live `WORKFLOW_AUTO.md`/AGENTS startup prose with one
  runtime projection keyed to the already-resolved project roots. Private state remains freshly
  injected under the same visible budget and priority, actual HEARTBEAT state and custom AGENTS
  rules remain available, and the Docket-owned source files stay byte-identical; generated
  HEARTBEAT authoring instructions and the AGENTS `Session Startup` block are omitted because the
  live runtime has already performed those reads and owns turn durability.

### Version 1.13.0 (2026-08-25)

- W25-C6 marks accepted current-turn suffix and historical-prefix reductions within one request-fit
  evaluation, gives each accepted summary one reload/recheck, and fails locally instead of
  repeatedly summarizing the replacement. Distinct segments and bounded internal hierarchical
  summary rounds remain available; a summarizer failure aborts with its original compact-failure
  classification rather than falling through to another segment; a protected-span fingerprint keeps
  an accepted summary out of a later appended-tail prompt, a post-preflight revision check prevents
  stale transport, and a fixed outer cap bounds continuous revision growth without changing the
  privacy-safe `request_fit` shape.

### Version 1.12.0 (2026-08-25)

- W25-C3 preflights prior measured usage plus the prospective request/output reserve, then makes at
  most one explicit, tool-free terminal-response request when another ordinary round cannot fit.
  Irreducible requests fail before transport, finalization tool calls and measured overruns are
  never dispatched or persisted, successive compaction rounds see earlier summary usage, and one
  content-free `budget_warning` records the decision. Invalid/truncated summary outcomes retain
  `compaction_failed` precedence over simultaneous measured overrun or colliding backend-error
  text, and truncated task responses retain only usage metadata. The budget-first branch precedes
  request-fit compaction and retains raw current-turn units; when a window-first compaction was
  already valid, finalization instead uses its exact reloaded durable whole-unit summary.

### Version 1.11.0 (2026-08-22)

- W25-C2 carries the exact stored model's context/output limits into the live loop, estimates the
  real wire components plus output reserve before every task and summary call, compacts/reloads
  same-turn history by whole atomic units, and fails locally with `context_fit` when the minimum
  request cannot fit. Unknown hosted or URL-overridden windows remain explicitly unguaranteed.

### Version 1.10.0 (2026-08-20)

- Recorded the live per-request context-fit gap exposed by a 17,643-token request to a registered
  16,384-token endpoint. Distinguished endpoint-window fit from cumulative measured turn usage,
  static startup context, tool-result ceilings, and pre-turn durable-history compaction. W25-C2
  owns implementation; this version intentionally marks the spec partial.

### Version 1.9.0 (2026-08-19)

- W24-C2 closes the completion loop exposed by a realistic canary: runtime-loaded private state is
  explicitly read-only through every project tool, including bash, and task completion no longer
  implies that the model must locate or update private HEARTBEAT/memory files itself.

### Version 1.8.0 (2026-08-19)

- W23-C2 makes the private startup state promised by the workspace contract reach the live model:
  HEARTBEAT/AGENTS/TOOLS/MEMORY are freshly injected under the existing static context budget,
  visibly degraded by priority when needed, and never exposed as a second writable tool root.

### Version 1.7.0 (2026-08-19)

- W21-C1 daemon-free truth pass: collapsed the transitional P19-5/P19-7 status narrative into the
  current Docket-owned runtime contract and removed a stale non-goal for work that already shipped.
  Turn-loop behavior is unchanged.

### Version 1.6.0 (2026-08-19)

- **Wave 20, card W20-C4.** Split durable-history and trace coordinates with additive optional
  `trace_project`/`trace_session_key` values. Existing callers default to one shared coordinate;
  pod dispatch can now keep one task audit stream while each pipeline step owns its replay history.

### Version 1.5.0 (2026-08-19)

- **Wave 20, card W20-C2b.** The live adapter now supports bounded multi-round hierarchical
  compaction, aggregates every summary response's measured usage, and recomputes remaining timeout
  before each backend call. Compaction traces expose only round/max-prompt estimates.

### Version 1.4.0 (2026-08-19)

- **Wave 20, card W20-C2 (live session compaction).** Added the pre-turn compaction trigger, a
  direct non-recursive `ChatBackend` summarizer adapter with no conversation persistence, honest
  measured-usage accounting, fail-closed turn behavior, and privacy-safe compaction traces.

### Version 1.3.0 (2026-08-05)

- **ROADMAP Phase 19/wave 17, card W17-1 (MCP tools reachable in a live turn).** `DocketDriver`
  gained an `mcp_loader` field (Module API above), called from `run_turn` before the registry is
  handed to `run_agent_turn` — so this loop's existing once-per-turn `registry_for_role` call now
  also narrows whatever a configured MCP server contributed, not only built-ins. No change to
  `run_agent_turn`'s own signature or contract: it still takes an already-built `ToolRegistry` as a
  caller-supplied argument (that part of the P19-5 Status note above remains literally true) — the
  change is entirely in what `DocketDriver` builds before calling it. Full requirements and the
  role-narrowing safety argument live in `mcp-client.spec.md` (Requirements 25-29) and
  `role-archetypes.spec.md` (requirement 6), not duplicated here.

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
