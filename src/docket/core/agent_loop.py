"""The turn loop docket now owns (ROADMAP Phase 19 P19-5 / decision D-19).

This is the card that makes the OpenClaw daemon unused. Everything it needs
already shipped and was, until now, unwired:

- ``core/llm.py`` (P19-1) — the ``ChatBackend`` port: one request/response
  exchange, nothing more.
- ``core/tools.py`` (P19-2/P19-3) — ``ToolRegistry``/``dispatch_tool``, the
  **single** chokepoint where the command classifier, the ``pre_tool_call``
  policy hook, approval routing and audit already live.
- ``core/session.py`` (P19-4) — durable per-session turn history, with
  compaction that never splits a tool-call/tool-result atomic unit.

``run_agent_turn`` composes these three: load history -> call the backend ->
receive ``tool_calls`` -> dispatch every one through ``core.tools.dispatch_tool``
-> append results -> repeat until a stop condition. **Non-negotiable: there is
no second path to tool execution here.** This module never imports
``edges/adapters/toolbox.py`` and never touches a ``Tool.handler`` directly —
a tool call that bypassed ``dispatch_tool`` would bypass every guardrail the
last three cards built.

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
- ``timeout`` — wall-clock budget exceeded, checked between iterations
  (``LoopConfig.wall_clock_timeout_s``). This does not interrupt an in-flight
  HTTP call already underway; ``ChatBackend.complete``'s own per-request
  timeout is the last-resort safety net for a single hung call.
- ``token_budget`` — cumulative *measured* usage (``core.llm.TokenUsage``,
  real counts) exceeded ``LoopConfig.token_budget``. Never the bytes/divisor
  estimate ``core/context.py``/``core/session.py`` use for compaction — see
  ``core/session.py``'s "Budgeting honesty" section, which this mirrors.
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

## Tracing: new visibility docket has never had

Every dispatched tool call emits a ``tool_call`` trace event before it runs
and a ``tool_result`` trace event after (``core/trace.py``'s existing event
vocabulary — the same two event types ``core/trace.py``'s ``trace_ingest``
already projects from daemon session logs, reused here for a live-emitted
equivalent rather than an ingested one). ``docket trace`` can now show what
an agent actually did inside a turn; the daemon kept this to itself.

## Per-role tool sets and the system prompt (ROADMAP Phase 19 P19-12)

Two omissions this card closes, both recorded honestly rather than papered
over when P19-5 shipped:

- **The tool registry handed to the model was never narrowed by role.**
  ``core.archetypes.registry_for_role`` is called once per turn, before the
  first ``backend.complete``, so a Reviewer is never even *advertised*
  ``write``/``edit``, and if a call for either arrives anyway (a stale
  client, a hallucination), ``dispatch_tool`` refuses it as an unknown tool
  against the narrowed registry — a strictly stronger guarantee than a
  SOUL.md instruction. This function never branches on a role's name; the
  denylist is data on the role's archetype (see ``core/archetypes.py``).
- **No system prompt was composed at all.** ``core.identity.system_prompt_for_agent``
  reads this agent's ``SOUL.md``, live persona, and ``WORKFLOW_AUTO.md`` (the
  resume/durability contract) and folds them into one prompt, prepended as a
  ``system`` message. Composed fresh every turn — never persisted to session
  history — so a persona change or a re-seeded ``WORKFLOW_AUTO.md`` is
  reflected on the very next turn rather than frozen into a stored message.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import docket.config as _cfg
from docket.core import archetypes as _archetypes
from docket.core import identity as _identity
from docket.core.llm import ChatBackend, ChatMessage, TokenUsage, system, tool_result, user
from docket.core.runtime_driver import FailureKind
from docket.core.session import append_messages, load_messages
from docket.core.tools import ToolContext, ToolRegistry, dispatch_tool
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
]


@dataclass(frozen=True)
class LoopConfig:
    """Bounds for one ``run_agent_turn`` call. See the module docstring for
    what each one guards against; defaults come from ``config.py``'s
    ``AGENT_LOOP_*`` constants so every tunable here is env-overridable the
    same way every other docket tunable is.

    ``max_tokens``/``temperature`` are passed straight through to
    ``ChatBackend.complete`` — ``None`` (the default for both) means "let the
    endpoint decide," never a docket-side guess at a model's defaults.
    """

    max_iterations: int = _cfg.AGENT_LOOP_MAX_ITERATIONS
    max_tool_calls: int = _cfg.AGENT_LOOP_MAX_TOOL_CALLS
    wall_clock_timeout_s: float = _cfg.AGENT_LOOP_WALL_CLOCK_TIMEOUT_S
    token_budget: int = _cfg.AGENT_LOOP_TOKEN_BUDGET
    request_timeout_s: int = _cfg.AGENT_LOOP_REQUEST_TIMEOUT_S
    max_tokens: int | None = None
    temperature: float | None = None


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
) -> None:
    trace_event(
        project,
        session_key,
        role,
        "tool_result",
        json.dumps(
            {"tool": tool, "callId": call_id, "decision": decision, "ok": ok, "executed": executed}
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
) -> AgentLoopResult:
    """Run one full turn: compose -> call -> gate-and-execute -> feed back -> repeat.

    ``session_key`` is both the durable-history key (``core/session.py``) and
    the trace session id (``core/trace.py``) — the same coordinate
    ``core/dispatch.py`` already uses for both purposes, so this is not a new
    convention. ``ctx.project`` (falling back to ``ctx.agent_id``) and
    ``ctx.role`` label the trace events; ``ctx`` also carries the tool
    containment boundary (``ctx.roots``) that ``dispatch_tool`` enforces —
    this function never inspects or widens it.

    Never raises for an ordinary failure mode: every stop condition, and
    every backend failure, comes back as a populated ``AgentLoopResult``.
    """
    cfg = config or LoopConfig()
    started = clock()
    project = ctx.project or ctx.agent_id or "unknown"

    # P19-12: resolved once per turn, not per iteration -- neither the
    # role's toolset nor this agent's identity files change mid-turn.
    registry = _archetypes.registry_for_role(registry, ctx.role)
    system_prompt = _identity.system_prompt_for_agent(ctx.agent_id)

    history = load_messages(session_key)
    incoming = user(message)
    append_messages(session_key, [incoming])
    messages: list[ChatMessage] = [*history, incoming]
    if system_prompt:
        # Composed fresh, never persisted -- see the module docstring's
        # "Per-role tool sets and the system prompt" section.
        messages = [system(system_prompt), *messages]

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
        response = backend.complete(
            messages,
            tools=registry.specs(),
            max_tokens=cfg.max_tokens,
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
            # dispatched, never persisted (see module docstring). The turn
            # simply reports why it stopped; nothing here is written to
            # session history.
            return _done(
                ok=False,
                stop_reason="truncated",
                output=response.message.content,
                error="model response was truncated (finish_reason=length); no tool calls were executed",
                failure_kind="invalid_output",
            )

        assistant_msg = response.message
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
            _trace_tool_call(project, session_key, ctx.role, call.name, call.id, call.arguments)
            result = dispatch_tool(call, ctx, registry)
            tool_calls_executed += 1
            _trace_tool_result(
                project,
                session_key,
                ctx.role,
                call.name,
                call.id,
                result.decision,
                result.ok,
                result.executed,
            )
            tool_msgs.append(tool_result(call, result.as_tool_output()))

        messages.append(assistant_msg)
        messages.extend(tool_msgs)
        # One append per iteration, the whole atomic unit at once — never the
        # assistant message and its tool results in separate calls, which
        # would let a crash between them persist an orphaned tool_calls entry.
        append_messages(session_key, [assistant_msg, *tool_msgs], usage=response.usage)
