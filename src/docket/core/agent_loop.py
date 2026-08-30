"""The turn loop docket owns.

``run_agent_turn`` composes three pieces:

- ``core/llm.py`` — the ``ChatBackend`` port: one request/response
  exchange, nothing more.
- ``core/tools.py`` — ``ToolRegistry``/``dispatch_tool``, the
  **single** chokepoint where the command classifier, the ``pre_tool_call``
  policy hook, approval routing and audit live.
- ``core/session.py`` — durable per-session turn history, with
  compaction that never splits a tool-call/tool-result atomic unit.

``run_agent_turn`` composes these three: load history -> call the backend ->
receive ``tool_calls`` -> dispatch every one through ``core.tools.dispatch_tool``
-> append results -> repeat until a stop condition. **Non-negotiable: there is
no second path to tool execution here.** This module never imports
``edges/adapters/toolbox.py`` and never touches a ``Tool.handler`` directly —
a tool call that bypassed ``dispatch_tool`` would bypass every guardrail
built into it.

## Stop conditions — every exit is deliberate, and the result says which fired

An unbounded loop burning money on a confused model is the failure mode this
card exists to prevent, so every one of these is checked explicitly and
reported as ``AgentLoopResult.stop_reason``:

- ``final_message`` — the model replied with no further tool calls. The only
  *successful* stop reason; every other one leaves ``ok=False``.
- ``max_iterations`` — too many model round-trips (``LoopConfig.max_iterations``).
- ``max_tool_calls`` — too many tool calls dispatched, whether spread across
  many iterations or requested all at once in a single response
  (``LoopConfig.max_tool_calls``). Checked *before* dispatching a batch that
  would exceed it, so a batch is either wholly dispatched or not dispatched
  at all — never partially, which would leave an assistant message with some
  tool calls answered and others orphaned (exactly what ``core/session.py``'s
  atomic-unit contract forbids storing).
- ``tool_denials`` — too many consecutive denied, non-executed tool results
  (``LoopConfig.max_consecutive_tool_denials``). The model may recover after
  an isolated refusal, and an allowed executed result resets the count; the
  default third consecutive denial stops locally after its complete atomic
  assistant/tool-result unit and usage are persisted.
- ``timeout`` — wall-clock budget exceeded, checked between iterations
  (``LoopConfig.wall_clock_timeout_s``). This does not interrupt an in-flight
  HTTP call already underway; ``ChatBackend.complete``'s own per-request
  timeout is the last-resort safety net for a single hung call.
- ``token_budget`` — cumulative *measured* usage (``core.llm.TokenUsage``,
  real counts) exceeded ``LoopConfig.token_budget``. Never the bytes/divisor
  estimate ``core/context.py``/``core/session.py`` use for compaction — see
  ``core/session.py``'s "Budgeting honesty" section, which this mirrors. When
  the endpoint supplies a positive maximum-output reserve, the loop combines
  prior measured usage with the next request estimate and that reserve before
  transport. If an ordinary tool-enabled round no longer fits, it offers at
  most one explicit tool-free terminal response that itself must fit.
- ``truncated`` — the endpoint stopped for length, not because it was done
  (``ChatResponse.truncated``). A length-truncated reply can carry a
  *partial* tool call, and partial arguments are exactly what a gate cannot
  evaluate, so this response's tool calls (if any) are never dispatched and
  the response is never persisted to the session — see below.
- ``backend_error`` — not one of the four stop conditions the card's design
  is built around, but a real-world failure path that cannot be dropped: the
  backend itself returned ``ChatResponse(ok=False, ...)`` (a transport,
  protocol, or endpoint failure). Reported with the backend's own
  ``failure_kind``.

``AgentLoopResult.failure_kind`` is ``None`` exactly when ``ok`` is True —
the same invariant ``ChatResponse``/``TurnResult`` already keep.

## Truncation is handled explicitly, not incidentally

A truncated response's assistant message is **never appended to session
history and its tool calls, if any, are never dispatched.** Persisting a
truncated assistant message that requested tool calls would create an
orphaned-tool-call state in the very history ``core/session.py``'s
compaction post-conditions exist to forbid; discarding it instead means the
turn simply reports ``truncated`` and the caller decides whether to retry —
the same fail-closed posture ``core/session.py``'s compaction and
``core/memory.py``'s distillation already take on their own failure paths.

## Durability: persisted per iteration, not only at the end

The incoming user message is appended to the session immediately, before any
model call is made. Each iteration that produces tool calls appends the
assistant message *and every tool result answering it* in one
``core.session.append_messages`` call — one atomic unit, matching
``core/session.py``'s own atomicity contract, and never split across two
appends. A crash mid-loop therefore loses at most the in-flight iteration,
never the ones already completed — the durability contract that is the
reason docket owns session state at all.

## Tracing

Every dispatched tool call emits a ``tool_call`` trace event before it runs
and a ``tool_result`` trace event after (``core/trace.py``'s existing event
vocabulary — the same two event types ``core/trace.py``'s ``trace_ingest``
already projects from a driver's decoded session records, reused here for a
live-emitted equivalent rather than an ingested one). ``docket trace`` shows
what an agent actually did inside a turn. Entering or refusing the terminal
response reservation emits the existing ``budget_warning`` event with numeric
budget/estimate evidence only, never messages or model/tool content.

## Per-role tool sets and the system prompt

- **The tool registry handed to the model is narrowed by role.**
  ``core.archetypes.registry_for_role`` is called once per turn, before the
  first ``backend.complete``, so a Reviewer is never even *advertised*
  ``write``/``edit``, and if a call for either arrives anyway (a stale
  client, a hallucination), ``dispatch_tool`` refuses it as an unknown tool
  against the narrowed registry — a strictly stronger guarantee than a
  SOUL.md instruction. This function never branches on a role's name; the
  denylist is data on the role's archetype (see ``core/archetypes.py``).
- **The system prompt is composed fresh every turn.**
  ``core.identity.system_prompt_for_agent`` reads this agent's ``SOUL.md``,
  live persona, the driver's resolved project roots, and bounded private
  workspace state. It projects one live-safe startup contract instead of
  replaying ``WORKFLOW_AUTO.md``'s manual private-file instructions, then
  prepends the result as a ``system`` message. It is never persisted to
  session history, so refreshed persona/state is visible on the next turn
  rather than frozen into a stored message.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import docket.config as _cfg
from docket.core import archetypes as _archetypes
from docket.core import context as _context
from docket.core import identity as _identity
from docket.core.llm import (
    ChatBackend,
    ChatMessage,
    TokenUsage,
    ToolSpec,
    system,
    tool_result,
    user,
)
from docket.core.runtime_driver import FailureKind, TurnResult
from docket.core.session import CompactionResult, append_messages, compact_session, load_messages
from docket.core.tools import ToolContext, ToolDenialKind, ToolRegistry, dispatch_tool
from docket.core.trace import trace_event

__all__ = [
    "AgentLoopResult",
    "LoopConfig",
    "StopReason",
    "run_agent_turn",
]

StopReason = Literal[
    "final_message",
    "max_iterations",
    "max_tool_calls",
    "timeout",
    "token_budget",
    "truncated",
    "backend_error",
    "compaction_failed",
    "context_fit",
    "tool_denials",
]

_FINALIZATION_INSTRUCTION = (
    "The remaining cumulative turn budget cannot safely fund another tool-enabled round. "
    "Return the truthful terminal response now using only the work already completed and the "
    "tool results above. Do not request any tools. If the task is incomplete, say so explicitly."
)
_TOKEN_BUDGET_ERROR_PREFIX = "token budget:"


@dataclass(frozen=True)
class LoopConfig:
    """Bounds for one ``run_agent_turn`` call. See the module docstring for
    what each one guards against; defaults come from ``config.py``'s
    ``AGENT_LOOP_*`` constants so every tunable here is env-overridable the
    same way every other docket tunable is.

    ``max_tokens``/``temperature`` are passed straight through to
    ``ChatBackend.complete`` — ``None`` (the default for both) means "let the
    endpoint decide," never a docket-side guess at a model's defaults. A
    positive ``max_tokens`` also supplies the output reserve for cumulative
    request preflight; without one the loop keeps its measured-response guard
    rather than inventing an output bound.
    """

    max_iterations: int = _cfg.AGENT_LOOP_MAX_ITERATIONS
    max_tool_calls: int = _cfg.AGENT_LOOP_MAX_TOOL_CALLS
    max_consecutive_tool_denials: int = _cfg.AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS
    wall_clock_timeout_s: float = _cfg.AGENT_LOOP_WALL_CLOCK_TIMEOUT_S
    token_budget: int = _cfg.AGENT_LOOP_TOKEN_BUDGET
    request_timeout_s: int = _cfg.AGENT_LOOP_REQUEST_TIMEOUT_S
    max_tokens: int | None = None
    temperature: float | None = None
    history_budget_tokens: int | None = None
    summary_input_budget_tokens: int | None = None
    context_window_tokens: int | None = None


@dataclass
class AgentLoopResult:
    """Outcome of one ``run_agent_turn`` call.

    ``failure_kind`` is ``None`` exactly when ``ok`` is True, and
    ``stop_reason == "final_message"`` exactly when ``ok`` is True — the only
    stop reason that represents a completed, usable turn. Mirrors
    ``ChatResponse``/``TurnResult``'s identical invariant deliberately, so
    ``edges/adapters/docket_runtime.py``'s translation to ``TurnResult`` is a
    field-for-field copy, not a re-interpretation.
    """

    ok: bool
    output: str = ""
    stop_reason: StopReason = "final_message"
    iterations: int = 0
    tool_calls_executed: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    error: str = ""
    failure_kind: FailureKind | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _accumulate(current: TokenUsage, delta: TokenUsage) -> TokenUsage:
    """Fold one exchange's real ``TokenUsage`` into the turn's running total.

    Mirrors ``core.session._add_usage``'s shape exactly (a separate function,
    not an import of that private helper, since the two accumulate into
    different record types — a session's lifetime total vs. one turn's).
    """
    return TokenUsage(
        input_tokens=current.input_tokens + delta.input_tokens,
        output_tokens=current.output_tokens + delta.output_tokens,
        cached_tokens=current.cached_tokens + delta.cached_tokens,
    )


def _usage_delta(current: TokenUsage, previous: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=current.input_tokens - previous.input_tokens,
        output_tokens=current.output_tokens - previous.output_tokens,
        cached_tokens=current.cached_tokens - previous.cached_tokens,
    )


def _fallback_input_estimate(
    messages: list[ChatMessage],
    tools: list[ToolSpec],
    max_tokens: int | None,
    temperature: float | None,
) -> int:
    """Estimate all model-visible components for a non-wire-aware backend."""
    payload = {
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in message.tool_calls
                ],
                "tool_call_id": message.tool_call_id,
                "name": message.name,
            }
            for message in messages
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return max(1, _context.estimate_tokens(json.dumps(payload, ensure_ascii=False))) + 16


def _estimate_input_tokens(
    backend: ChatBackend,
    messages: list[ChatMessage],
    tools: list[ToolSpec],
    max_tokens: int | None,
    temperature: float | None,
) -> int:
    estimator = getattr(backend, "estimate_input_tokens", None)
    if callable(estimator):
        estimated = estimator(
            messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return max(1, int(estimated))
    return _fallback_input_estimate(messages, tools, max_tokens, temperature)


def _trace_request_fit(
    project: str,
    session_key: str,
    role: str,
    *,
    purpose: str,
    status: str,
    estimated_input_tokens: int,
    output_reserve_tokens: int,
    context_window_tokens: int | None,
) -> None:
    trace_event(
        project,
        session_key,
        role,
        "request_fit",
        json.dumps(
            {
                "purpose": purpose,
                "status": status,
                "estimatedInputTokens": estimated_input_tokens,
                "outputReserveTokens": output_reserve_tokens,
                "contextWindowTokens": context_window_tokens,
                "estimate": True,
            }
        ),
    )


def _trace_tool_call(
    project: str, session_key: str, role: str, tool: str, call_id: str, arguments: str
) -> None:
    trace_event(
        project,
        session_key,
        role,
        "tool_call",
        json.dumps({"tool": tool, "callId": call_id, "arguments": arguments}),
    )


def _trace_tool_result(
    project: str,
    session_key: str,
    role: str,
    tool: str,
    call_id: str,
    decision: str,
    ok: bool,
    executed: bool,
    denial_kind: ToolDenialKind | None,
) -> None:
    payload: dict[str, Any] = {
        "tool": tool,
        "callId": call_id,
        "decision": decision,
        "ok": ok,
        "executed": executed,
    }
    if denial_kind is not None:
        payload["denialKind"] = denial_kind
    trace_event(
        project,
        session_key,
        role,
        "tool_result",
        json.dumps(payload),
    )


def _trace_compaction(
    project: str,
    session_key: str,
    role: str,
    result: CompactionResult,
) -> None:
    status = "failed" if not result.ok else "succeeded" if result.compacted else "no_op"
    trace_event(
        project,
        session_key,
        role,
        "session_compaction",
        json.dumps(
            {
                "status": status,
                "beforeMessageCount": result.before_message_count,
                "afterMessageCount": result.after_message_count,
                "beforeEstimatedTokens": result.before_estimated_tokens,
                "afterEstimatedTokens": result.after_estimated_tokens,
                "groupsSummarized": result.groups_summarized,
                "summaryRounds": result.summary_rounds,
                "maxSummaryPromptEstimatedTokens": (result.max_summary_prompt_estimated_tokens),
            }
        ),
    )


def _trace_terminal_finalization(
    project: str,
    session_key: str,
    role: str,
    *,
    status: str,
    reason: str,
    token_budget: int,
    measured_tokens_used: int,
    normal_estimated_input_tokens: int,
    finalization_estimated_input_tokens: int,
    output_reserve_tokens: int,
) -> None:
    remaining = max(0, token_budget - measured_tokens_used)
    trace_event(
        project,
        session_key,
        role,
        "budget_warning",
        json.dumps(
            {
                "action": "terminal_finalization",
                "status": status,
                "reason": reason,
                "tokenBudget": token_budget,
                "measuredTokensUsed": measured_tokens_used,
                "remainingMeasuredTokens": remaining,
                "normalEstimatedInputTokens": normal_estimated_input_tokens,
                "finalizationEstimatedInputTokens": finalization_estimated_input_tokens,
                "outputReserveTokens": output_reserve_tokens,
                "normalProspectiveTokens": normal_estimated_input_tokens + output_reserve_tokens,
                "finalizationProspectiveTokens": finalization_estimated_input_tokens
                + output_reserve_tokens,
                "estimate": True,
            }
        ),
    )


def run_agent_turn(
    backend: ChatBackend,
    registry: ToolRegistry,
    ctx: ToolContext,
    session_key: str,
    message: str,
    *,
    config: LoopConfig | None = None,
    clock: Callable[[], float] = time.monotonic,
    trace_project: str | None = None,
    trace_session_key: str | None = None,
) -> AgentLoopResult:
    """Run one full turn: compose -> call -> gate-and-execute -> feed back -> repeat.

    ``session_key`` is the durable-history key (``core/session.py``). The
    optional trace coordinates select only where events are written and default
    to ``ctx.project``/``session_key`` for backward compatibility. ``ctx`` also
    carries the tool containment boundary (``ctx.roots``) that
    ``dispatch_tool`` enforces — this function never inspects or widens it.

    Never raises for an ordinary failure mode: every stop condition, and
    every backend failure, comes back as a populated ``AgentLoopResult``.
    """
    cfg = config or LoopConfig()
    backend_window = getattr(backend, "context_window_tokens", None)
    context_window = cfg.context_window_tokens
    if context_window is None and isinstance(backend_window, int) and backend_window > 0:
        context_window = backend_window
    backend_output = getattr(backend, "max_output_tokens", None)
    request_max_tokens = cfg.max_tokens
    if request_max_tokens is None and isinstance(backend_output, int) and backend_output > 0:
        request_max_tokens = backend_output
    output_reserve = request_max_tokens if request_max_tokens is not None else 0
    started = clock()
    project = trace_project or ctx.project or ctx.agent_id or "unknown"
    trace_key = trace_session_key or session_key
    total_usage = TokenUsage()
    tool_calls_executed = 0
    iteration = 0
    last_raw: dict[str, Any] = {}

    def _done(
        *,
        ok: bool,
        stop_reason: StopReason,
        output: str = "",
        error: str = "",
        failure_kind: FailureKind | None = None,
    ) -> AgentLoopResult:
        return AgentLoopResult(
            ok=ok,
            output=output,
            stop_reason=stop_reason,
            iterations=iteration,
            tool_calls_executed=tool_calls_executed,
            usage=total_usage,
            error=error,
            failure_kind=failure_kind,
            raw=last_raw,
        )

    # Resolved once per turn, not per iteration -- neither the role's
    # toolset nor this agent's identity files change mid-turn.
    registry = _archetypes.registry_for_role(registry, ctx.role)
    system_prompt = _identity.system_prompt_for_agent(
        ctx.agent_id,
        project_roots=ctx.roots,
    )
    tool_specs = registry.specs()

    def _preflight_request(
        request_messages: list[ChatMessage],
        request_tools: list[ToolSpec],
        *,
        purpose: str,
    ) -> tuple[int, str]:
        estimated_input = _estimate_input_tokens(
            backend,
            request_messages,
            request_tools,
            request_max_tokens,
            cfg.temperature,
        )
        if context_window is None:
            _trace_request_fit(
                project,
                trace_key,
                ctx.role,
                purpose=purpose,
                status="unknown_window",
                estimated_input_tokens=estimated_input,
                output_reserve_tokens=output_reserve,
                context_window_tokens=None,
            )
            return estimated_input, ""
        if output_reserve <= 0:
            error = (
                "context fit: selected endpoint has registered context window "
                f"{context_window} but no positive maximum-output reserve"
            )
        elif estimated_input + output_reserve > context_window:
            error = (
                "context fit: estimated request "
                f"{estimated_input + output_reserve} tokens (input {estimated_input} + output "
                f"reserve {output_reserve}) exceeds registered context window {context_window}"
            )
        else:
            error = ""
        _trace_request_fit(
            project,
            trace_key,
            ctx.role,
            purpose=purpose,
            status="failed" if error else "fits",
            estimated_input_tokens=estimated_input,
            output_reserve_tokens=output_reserve,
            context_window_tokens=context_window,
        )
        return estimated_input, error

    def _context_fit_convergence_error(reason: str, estimated_input: int) -> str:
        registered_window = str(context_window) if context_window is not None else "unknown"
        return (
            "context fit: estimated request "
            f"{estimated_input + output_reserve} tokens (input {estimated_input} + output reserve "
            f"{output_reserve}) could not be validated against registered context window "
            f"{registered_window}: {reason}"
        )

    summary_usage = TokenUsage()
    accounted_summary_usage = TokenUsage()
    compaction_failure_stop_reason: StopReason | None = None

    def _effective_measured_tokens() -> int:
        pending = _usage_delta(summary_usage, accounted_summary_usage)
        return total_usage.total_tokens + pending.total_tokens

    def _prospective_budget_error(estimated_input: int, *, purpose: str) -> str:
        # Without an endpoint/config output bound, Docket cannot honestly
        # reserve a completion. Preserve the existing measured post-response
        # guard instead of inventing a model-specific output allowance.
        if output_reserve <= 0:
            return ""
        measured_tokens = _effective_measured_tokens()
        remaining = cfg.token_budget - measured_tokens
        prospective = estimated_input + output_reserve
        if prospective <= remaining:
            return ""
        return (
            f"{_TOKEN_BUDGET_ERROR_PREFIX} cannot start {purpose} completion within "
            f"token_budget={cfg.token_budget} (used {measured_tokens}, estimated input "
            f"{estimated_input} + output reserve {output_reserve}, remaining {max(0, remaining)}); "
            "no backend call made"
        )

    def _finalization_messages(current: list[ChatMessage]) -> list[ChatMessage]:
        # Keep the instruction in the leading system slot for adapters/models
        # that require system messages before conversation history. This copy
        # is request-only and is never written to durable history.
        if current and current[0].role == "system":
            terminal_system = system(f"{current[0].content}\n\n{_FINALIZATION_INSTRUCTION}")
            return [terminal_system, *current[1:]]
        return [system(_FINALIZATION_INSTRUCTION), *current]

    def _summarize_without_reentry(
        agent_id: str,
        summary_session_key: str,
        prompt: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        """One tool-free backend call: no loop recursion and no session writes."""
        nonlocal compaction_failure_stop_reason, last_raw, summary_usage
        if summary_session_key == session_key:
            compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                {},
                "compaction summarizer key matched the target session",
                "invalid_output",
            )
        elapsed = clock() - started
        remaining = int(cfg.wall_clock_timeout_s - elapsed)
        if remaining <= 0:
            compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                {},
                "compaction exhausted the turn wall-clock budget",
                "timeout",
            )
        summary_messages = [user(prompt)]
        estimated_input, fit_error = _preflight_request(
            summary_messages,
            [],
            purpose="compaction",
        )
        if fit_error:
            compaction_failure_stop_reason = "context_fit"
            return TurnResult(False, "", 0.0, {}, fit_error, "invalid_output")
        budget_error = _prospective_budget_error(estimated_input, purpose="compaction")
        if budget_error:
            compaction_failure_stop_reason = "token_budget"
            return TurnResult(False, "", 0.0, {}, budget_error, "invalid_output")
        response = backend.complete(
            summary_messages,
            tools=(),
            max_tokens=request_max_tokens,
            temperature=cfg.temperature,
            timeout=min(timeout, remaining),
        )
        last_raw = response.raw
        summary_usage = _accumulate(summary_usage, response.usage)
        if not response.ok:
            compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                response.error,
                response.failure_kind or "daemon_error",
            )
        if response.truncated:
            compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "compaction summarizer response was truncated; partial summary was not accepted",
                "invalid_output",
            )
        if response.tool_calls:
            compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "compaction summarizer requested tools on a tool-free call",
                "invalid_output",
            )
        if not response.message.content.strip():
            compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "compaction summarisation turn returned an empty summary",
                "invalid_output",
            )
        measured_tokens = _effective_measured_tokens()
        if measured_tokens > cfg.token_budget:
            compaction_failure_stop_reason = "token_budget"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                (
                    f"{_TOKEN_BUDGET_ERROR_PREFIX} compaction completion exceeded "
                    f"token_budget={cfg.token_budget} (used {measured_tokens}); summary was not "
                    "accepted"
                ),
                "invalid_output",
            )
        return TurnResult(True, response.message.content, 0.0, response.raw)

    def _run_compaction(
        *,
        budget_tokens: int | None,
        compact_range: tuple[int, int] | None = None,
        keep_latest_unit: bool = True,
    ) -> tuple[CompactionResult, StopReason | None]:
        nonlocal accounted_summary_usage, compaction_failure_stop_reason, total_usage
        compaction_failure_stop_reason = None
        elapsed_now = clock() - started
        remaining_now = max(1, int(cfg.wall_clock_timeout_s - elapsed_now))
        result = compact_session(
            session_key,
            role=ctx.role,
            agent_id=ctx.agent_id,
            summarizer=_summarize_without_reentry,
            summarizer_session_key=f"{session_key}:compaction",
            budget_tokens=budget_tokens,
            summary_input_budget_tokens=cfg.summary_input_budget_tokens,
            compact_range=compact_range,
            keep_latest_unit=keep_latest_unit,
            timeout=min(cfg.request_timeout_s, remaining_now),
            label=f"{ctx.role} session",
        )
        usage_delta = _usage_delta(summary_usage, accounted_summary_usage)
        total_usage = _accumulate(total_usage, usage_delta)
        accounted_summary_usage = summary_usage
        if usage_delta.total_tokens or usage_delta.cached_tokens:
            append_messages(session_key, [], usage=usage_delta)
        _trace_compaction(project, trace_key, ctx.role, result)
        return result, compaction_failure_stop_reason

    compaction, compaction_stop_reason = _run_compaction(budget_tokens=cfg.history_budget_tokens)
    if not compaction.ok:
        return _done(
            ok=False,
            stop_reason=compaction_stop_reason or "compaction_failed",
            error=compaction.error,
            failure_kind=compaction.failure_kind or "invalid_output",
        )

    incoming = user(message)
    appended = append_messages(session_key, [incoming])
    task_message_index = len(appended.messages) - 1

    def _selected_estimate(selected: list[ChatMessage]) -> int:
        return max(1, _fallback_input_estimate(selected, [], None, None) - 16)

    def _segment_revision(selected: list[ChatMessage]) -> str:
        encoded = json.dumps(
            [asdict(message) for message in selected],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _messages_for_durable(durable: list[ChatMessage]) -> list[ChatMessage]:
        return [*([system(system_prompt)] if system_prompt else []), *durable]

    def _fit_task_request() -> tuple[
        list[ChatMessage], int, str, StopReason | None, FailureKind | None
    ]:
        nonlocal task_message_index
        durable_revision = load_messages(session_key)
        current_messages = _messages_for_durable(durable_revision)
        current_revision = _segment_revision(durable_revision)
        attempts = 0
        attempt_cap = max(2, len(durable_revision) + 1)
        protected_segments: dict[str, tuple[int, str]] = {}
        while True:
            estimated_input, fit_error = _preflight_request(
                current_messages,
                tool_specs,
                purpose="task",
            )
            latest_durable = load_messages(session_key)
            latest_revision = _segment_revision(latest_durable)
            if latest_revision != current_revision:
                if attempts >= attempt_cap:
                    return (
                        current_messages,
                        estimated_input,
                        _context_fit_convergence_error(
                            "durable history changed during request preflight and did not "
                            f"stabilize within attempt cap {attempt_cap}; no backend call made",
                            estimated_input,
                        ),
                        "context_fit",
                        "invalid_output",
                    )
                attempts += 1
                durable_revision = latest_durable
                current_revision = latest_revision
                current_messages = _messages_for_durable(durable_revision)
                continue
            if _prospective_budget_error(estimated_input, purpose="tool-enabled task"):
                return current_messages, estimated_input, "", None, None
            if not fit_error:
                return current_messages, estimated_input, "", None, None
            if context_window is None or output_reserve <= 0:
                return current_messages, estimated_input, fit_error, "context_fit", "invalid_output"
            if attempts >= attempt_cap:
                return (
                    current_messages,
                    estimated_input,
                    f"{fit_error}; request-fit compaction did not converge",
                    "context_fit",
                    "invalid_output",
                )

            durable = load_messages(session_key)
            task_index = task_message_index
            if task_index < 0 or task_index >= len(durable) or durable[task_index] != incoming:
                return (
                    current_messages,
                    estimated_input,
                    f"{fit_error}; current task was not found in durable history",
                    "context_fit",
                    "invalid_output",
                )
            overflow = estimated_input + output_reserve - context_window
            candidate_ranges: list[tuple[str, tuple[int, int], bool, int]] = []
            if task_index + 1 < len(durable):
                suffix_start = task_index + 1
                prior_protected_count = 0
                checkpoint = protected_segments.get("suffix")
                if checkpoint is not None:
                    protected_count, protected_revision = checkpoint
                    suffix = durable[suffix_start:]
                    protected = suffix[:protected_count]
                    if (
                        len(protected) == protected_count
                        and _segment_revision(protected) == protected_revision
                    ):
                        suffix_start += protected_count
                        prior_protected_count = protected_count
                    else:
                        protected_segments.pop("suffix", None)
                if suffix_start < len(durable):
                    candidate_ranges.append(
                        (
                            "suffix",
                            (suffix_start, len(durable)),
                            False,
                            prior_protected_count,
                        )
                    )
            if task_index > 0:
                prefix = durable[:task_index]
                checkpoint = protected_segments.get("prefix")
                if checkpoint is None or checkpoint != (
                    len(prefix),
                    _segment_revision(prefix),
                ):
                    candidate_ranges.append(("prefix", (0, task_index), True, 0))

            progressed = False
            accepted_segment = ""
            accepted_prior_protected_count = 0
            accepted_replacement_count = 0
            for segment, selected_range, keep_latest, prior_protected_count in candidate_ranges:
                selected = durable[selected_range[0] : selected_range[1]]
                selected_tokens = _selected_estimate(selected)
                target = max(1, selected_tokens - overflow - 32)
                if target >= selected_tokens:
                    continue
                fit_compaction, fit_compaction_stop_reason = _run_compaction(
                    budget_tokens=target,
                    compact_range=selected_range,
                    keep_latest_unit=keep_latest,
                )
                if not fit_compaction.ok:
                    failure_stop_reason = fit_compaction_stop_reason or "compaction_failed"
                    return (
                        current_messages,
                        estimated_input,
                        fit_compaction.error or "request-fit compaction failed",
                        failure_stop_reason,
                        (
                            fit_compaction.failure_kind
                            if failure_stop_reason == "compaction_failed"
                            else "invalid_output"
                        )
                        or "invalid_output",
                    )
                if fit_compaction.compacted:
                    accepted_segment = segment
                    accepted_prior_protected_count = prior_protected_count
                    accepted_replacement_count = (
                        fit_compaction.after_message_count
                        - fit_compaction.before_message_count
                        + selected_range[1]
                        - selected_range[0]
                    )
                    progressed = True
                    break

            if not progressed:
                return (
                    current_messages,
                    estimated_input,
                    f"{fit_error}; irreducible durable request",
                    "context_fit",
                    "invalid_output",
                )

            durable = load_messages(session_key)
            reloaded_task_index = (
                accepted_replacement_count if accepted_segment == "prefix" else task_index
            )
            if (
                reloaded_task_index < 0
                or reloaded_task_index >= len(durable)
                or durable[reloaded_task_index] != incoming
            ):
                return (
                    current_messages,
                    estimated_input,
                    _context_fit_convergence_error(
                        "current task durable identity changed during request-fit compaction",
                        estimated_input,
                    ),
                    "context_fit",
                    "invalid_output",
                )
            task_message_index = reloaded_task_index
            if accepted_segment and accepted_replacement_count > 0:
                if accepted_segment == "suffix":
                    suffix = durable[reloaded_task_index + 1 :]
                    protected_count = accepted_prior_protected_count + accepted_replacement_count
                    accepted_messages = suffix[:protected_count]
                else:
                    protected_count = accepted_replacement_count
                    accepted_messages = durable[:protected_count]
                if len(accepted_messages) == protected_count:
                    protected_segments[accepted_segment] = (
                        protected_count,
                        _segment_revision(accepted_messages),
                    )
            durable_revision = durable
            current_revision = _segment_revision(durable_revision)
            current_messages = _messages_for_durable(durable_revision)
            attempts += 1

    finalization_attempted = False
    consecutive_denial_kinds: list[ToolDenialKind] = []
    while True:
        iteration += 1
        if iteration > cfg.max_iterations:
            return _done(
                ok=False,
                stop_reason="max_iterations",
                error=f"exceeded max_iterations={cfg.max_iterations}",
                failure_kind="invalid_output",
            )
        elapsed = clock() - started
        if elapsed > cfg.wall_clock_timeout_s:
            return _done(
                ok=False,
                stop_reason="timeout",
                error=f"exceeded wall_clock_timeout_s={cfg.wall_clock_timeout_s}",
                failure_kind="timeout",
            )
        if total_usage.total_tokens > cfg.token_budget:
            return _done(
                ok=False,
                stop_reason="token_budget",
                error=(
                    f"exceeded token_budget={cfg.token_budget} (used {total_usage.total_tokens})"
                ),
                failure_kind="invalid_output",
            )
        if tool_calls_executed >= cfg.max_tool_calls:
            return _done(
                ok=False,
                stop_reason="max_tool_calls",
                error=f"exceeded max_tool_calls={cfg.max_tool_calls}",
                failure_kind="invalid_output",
            )

        remaining = max(1, int(cfg.wall_clock_timeout_s - elapsed))
        request_timeout = min(cfg.request_timeout_s, remaining)
        (
            messages,
            normal_estimated_input,
            fit_error,
            fit_stop_reason,
            fit_failure_kind,
        ) = _fit_task_request()
        if fit_error:
            return _done(
                ok=False,
                stop_reason=fit_stop_reason or "context_fit",
                error=fit_error,
                failure_kind=fit_failure_kind or "invalid_output",
            )

        finalizing = False
        request_tools = tool_specs
        normal_budget_error = _prospective_budget_error(
            normal_estimated_input, purpose="tool-enabled task"
        )
        if normal_budget_error:
            if finalization_attempted:
                return _done(
                    ok=False,
                    stop_reason="token_budget",
                    error=normal_budget_error,
                    failure_kind="invalid_output",
                )
            finalization_attempted = True
            terminal_messages = _finalization_messages(messages)
            final_estimated_input, final_fit_error = _preflight_request(
                terminal_messages,
                [],
                purpose="task",
            )
            final_budget_error = _prospective_budget_error(
                final_estimated_input, purpose="terminal finalization"
            )
            if final_fit_error:
                final_status = "refused"
                final_reason = "finalization_context_fit_failed"
            elif final_budget_error:
                final_status = "refused"
                final_reason = "finalization_exceeds_remaining_turn_budget"
            else:
                final_status = "entered"
                final_reason = "normal_request_exceeds_remaining_turn_budget"
            _trace_terminal_finalization(
                project,
                trace_key,
                ctx.role,
                status=final_status,
                reason=final_reason,
                token_budget=cfg.token_budget,
                measured_tokens_used=total_usage.total_tokens,
                normal_estimated_input_tokens=normal_estimated_input,
                finalization_estimated_input_tokens=final_estimated_input,
                output_reserve_tokens=output_reserve,
            )
            if final_fit_error:
                return _done(
                    ok=False,
                    stop_reason="context_fit",
                    error=final_fit_error,
                    failure_kind="invalid_output",
                )
            if final_budget_error:
                return _done(
                    ok=False,
                    stop_reason="token_budget",
                    error=final_budget_error,
                    failure_kind="invalid_output",
                )
            messages = terminal_messages
            request_tools = []
            finalizing = True

        response = backend.complete(
            messages,
            tools=request_tools,
            max_tokens=request_max_tokens,
            temperature=cfg.temperature,
            timeout=request_timeout,
        )
        last_raw = response.raw
        if not response.ok:
            return _done(
                ok=False,
                stop_reason="backend_error",
                error=response.error,
                failure_kind=response.failure_kind or "daemon_error",
            )

        total_usage = _accumulate(total_usage, response.usage)

        if response.truncated:
            # A length-truncated reply can carry a partial tool call — never
            # dispatched, and neither it nor the partial assistant content is
            # persisted (see module docstring). Endpoint-reported usage remains
            # durable even though the response itself is rejected.
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(session_key, [], usage=response.usage)
            return _done(
                ok=False,
                stop_reason="truncated",
                output=response.message.content,
                error="model response was truncated (finish_reason=length); no tool calls were executed",
                failure_kind="invalid_output",
            )

        if total_usage.total_tokens > cfg.token_budget:
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(session_key, [], usage=response.usage)
            return _done(
                ok=False,
                stop_reason="token_budget",
                error=(
                    f"exceeded token_budget={cfg.token_budget} "
                    f"(used {total_usage.total_tokens}); response was not persisted and its "
                    "tool calls were not dispatched"
                ),
                failure_kind="invalid_output",
            )

        assistant_msg = response.message
        if finalizing and assistant_msg.tool_calls:
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(session_key, [], usage=response.usage)
            return _done(
                ok=False,
                stop_reason="token_budget",
                error=(
                    "terminal finalization requested tool calls even though no tools were "
                    "advertised; none were dispatched or persisted"
                ),
                failure_kind="invalid_output",
            )
        if not assistant_msg.tool_calls:
            append_messages(session_key, [assistant_msg], usage=response.usage)
            return _done(ok=True, stop_reason="final_message", output=assistant_msg.content)

        if tool_calls_executed + len(assistant_msg.tool_calls) > cfg.max_tool_calls:
            return _done(
                ok=False,
                stop_reason="max_tool_calls",
                error=(
                    f"model requested {len(assistant_msg.tool_calls)} tool call(s), which would "
                    f"exceed max_tool_calls={cfg.max_tool_calls} (already used "
                    f"{tool_calls_executed}); none of this batch was executed"
                ),
                failure_kind="invalid_output",
            )

        tool_msgs: list[ChatMessage] = []
        for call in assistant_msg.tool_calls:
            _trace_tool_call(project, trace_key, ctx.role, call.name, call.id, call.arguments)
            result = dispatch_tool(call, ctx, registry)
            tool_calls_executed += 1
            _trace_tool_result(
                project,
                trace_key,
                ctx.role,
                call.name,
                call.id,
                result.decision,
                result.ok,
                result.executed,
                result.denial_kind,
            )
            if result.denial_kind is not None and not result.executed:
                consecutive_denial_kinds.append(result.denial_kind)
            elif result.decision == "allow" and result.executed:
                consecutive_denial_kinds.clear()
            tool_msgs.append(tool_result(call, result.as_tool_output()))

        messages.append(assistant_msg)
        messages.extend(tool_msgs)
        # One append per iteration, the whole atomic unit at once — never the
        # assistant message and its tool results in separate calls, which
        # would let a crash between them persist an orphaned tool_calls entry.
        append_messages(session_key, [assistant_msg, *tool_msgs], usage=response.usage)
        denial_limit = cfg.max_consecutive_tool_denials
        if denial_limit > 0 and len(consecutive_denial_kinds) >= denial_limit:
            reported_kinds = consecutive_denial_kinds[-denial_limit:]
            return _done(
                ok=False,
                stop_reason="tool_denials",
                error=(
                    "consecutive tool denials reached configured limit: "
                    f"count={len(consecutive_denial_kinds)}; "
                    f"kinds={','.join(reported_kinds)}; no further model request was made"
                ),
                failure_kind="invalid_output",
            )
