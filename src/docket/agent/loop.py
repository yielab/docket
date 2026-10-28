"""The turn loop docket owns.

``run_agent_turn`` composes three pieces:

- ``agent/ports.py`` — the ``ChatBackend`` port: one request/response
  exchange, nothing more.
- ``agent/tools/registry.py`` — ``ToolRegistry``/``dispatch_tool``, the
  **single** chokepoint where the command classifier, the ``pre_tool_call``
  policy hook, approval routing and audit live.
- ``agent/session.py`` — durable per-session turn history, with
  compaction that never splits a tool-call/tool-result atomic unit.

``run_agent_turn`` composes these three: load history -> call the backend ->
receive ``tool_calls`` -> dispatch every one through ``agent.tools.registry.dispatch_tool``
-> append results -> repeat until a stop condition. **Non-negotiable: there is
no second path to tool execution here.** This module never imports
``agent/tools/builtins/toolbox.py`` and never touches a ``Tool.handler`` directly —
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
  tool calls answered and others orphaned (exactly what ``agent/session.py``'s
  atomic-unit contract forbids storing).
- ``tool_denials`` — too many consecutive denied, non-executed tool results
  (``LoopConfig.max_consecutive_tool_denials``). The model may recover after
  an isolated refusal, and an allowed executed result resets the count; the
  default third consecutive denial stops locally after its complete atomic
  assistant/tool-result unit and usage are persisted.
- ``approval_unavailable`` — a tool call needed a human decision
  (``governance.gate.evaluate_tool_call`` returned ``ask``) and ``ToolContext.
  approval_mode == "refuse"``, so ``dispatch_tool`` denied it immediately
  instead of creating an approval record and waiting. Unlike ``tool_denials``
  this is not a count reaching a limit — one such result ends the turn right
  after its batch is persisted, because there is nobody left to ask and no
  amount of retrying changes that. ``gate_denied`` and ``invalid_call`` are
  unaffected and remain recoverable, still bounded by
  ``max_consecutive_tool_denials`` as before — only the specific "nobody could
  answer" case is terminal on its own.
- ``approval_parked`` — a tool call needed a human decision and
  ``ToolContext.approval_mode == "park"``, so ``dispatch_tool`` recorded the
  exact call as a pending approval and ended the turn without waiting on it.
  Terminal on its own for the same reason as ``approval_unavailable``: there
  is somebody who *could* eventually answer, but not on this thread, right
  now — the task resumes elsewhere once a human resolves the token.
- ``no_progress`` — ``LoopConfig.no_progress_rounds`` consecutive tool rounds
  each repeated a round already seen earlier in the turn (same tools, same
  canonical arguments, same outcomes). ``0`` disables the check.
- ``timeout`` — wall-clock budget exceeded, checked between iterations
  (``LoopConfig.wall_clock_timeout_s``). This does not interrupt an in-flight
  HTTP call already underway; ``ChatBackend.complete``'s own per-request
  timeout is the last-resort safety net for a single hung call.
- ``token_budget`` — cumulative *counted* usage (``TokenUsage.counted_tokens``:
  real input minus cache reads, plus output) exceeded ``LoopConfig.token_budget``
  on a reply that still wants tools; a reply with none is already paid and is
  kept. Never the bytes/divisor estimate ``agent/context.py``/``agent/session.py``
  use for compaction — see ``agent/session.py``'s "Budgeting honesty" section,
  which this mirrors. The loop combines prior counted usage with the next
  request estimate (scaled by the last measured/estimated ratio, never below
  1) and the output reserve (``Home.default_max_output_tokens`` when the
  endpoint registers none) before transport. If an ordinary tool-enabled round
  no longer fits, it offers at most one explicit tool-free terminal response
  that itself must fit.
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
orphaned-tool-call state in the very history ``agent/session.py``'s
compaction post-conditions exist to forbid; discarding it instead means the
turn simply reports ``truncated`` and the caller decides whether to retry —
the same fail-closed posture ``agent/session.py``'s compaction and
``teams/agent_memory.py``'s distillation already take on their own failure paths.

## Durability: persisted per iteration, not only at the end

The incoming user message is appended to the session before the turn's own
first model call -- but ``apply_initial_history_compaction`` runs first, and
when it decides compaction is needed its summariser (``summarize_without_reentry``)
makes a model call of its own to produce the summary, so "before any model
call" is not quite true: at most one compaction-summary call can precede the
append. Each iteration that produces tool calls appends the
assistant message *and every tool result answering it* in one
``agent.session.append_messages`` call — one atomic unit, matching
``agent/session.py``'s own atomicity contract, and never split across two
appends. A crash mid-loop therefore loses at most the in-flight iteration,
never the ones already completed — the durability contract that is the
reason docket owns session state at all.

## Tracing

Every dispatched tool call emits a ``tool_call`` trace event before it runs
and a ``tool_result`` trace event after (``observability/trace.py``'s existing event
vocabulary, written through ``trace_append``). ``docket task trace`` shows
what an agent actually did inside a turn. Entering or refusing the terminal
response reservation emits the existing ``budget_warning`` event with numeric
budget/estimate evidence only, never messages or model/tool content.

## Per-role tool sets and the system prompt

- **The tool registry handed to the model is narrowed by role.**
  the role composer port (``agent.ports.role_composer``, ``teams.roles.registry_for_role``) is called once per turn, before the
  first ``backend.complete``, so a Reviewer is never even *advertised*
  ``write``/``edit``, and if a call for either arrives anyway (a stale
  client, a hallucination), ``dispatch_tool`` refuses it as an unknown tool
  against the narrowed registry — a strictly stronger guarantee than a
  SOUL.md instruction. This function never branches on a role's name; the
  denylist is data on the role's archetype (see ``teams/roles.py``).
- **The system prompt is composed fresh every turn.**
  the role composer (``teams.identity.compose_agent_prompt``) reads this agent's ``SOUL.md``,
  live persona, the driver's resolved project roots, and bounded private
  workspace state, and reports its own fit accounting (traced as
  ``prompt_composed``). It projects one live-safe startup contract instead
  of replaying ``WORKFLOW_AUTO.md``'s manual private-file instructions, then
  prepends the result as a ``system`` message. It is never persisted to
  session history, so refreshed persona/state is visible on the next turn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from docket.agent.loop_budget import MIN_OUTPUT_TOKENS, TurnBudget
from docket.agent.loop_compaction import TurnCompaction
from docket.agent.loop_request import _accumulate, _closing_messages, _finalization_messages
from docket.agent.loop_state import TurnState
from docket.agent.loop_steps import ToolStep, approval_parked_error, approval_unavailable_error
from docket.agent.loop_trace import (
    _trace_llm_call,
    _trace_prompt_composed,
    _trace_terminal_finalization,
)
from docket.agent.loop_types import AgentLoopResult, LoopConfig, StopReason
from docket.agent.ports import (
    ChatBackend,
    ChatMessage,
    PromptComposition,
    TokenUsage,
    ToolSpec,
    role_composer,
)
from docket.agent.session import append_messages
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.kernel import clock as _clock
from docket.kernel.home import current_home

__all__ = [
    "MIN_OUTPUT_TOKENS",
    "AgentLoopResult",
    "LoopConfig",
    "StopReason",
    "approval_parked_error",
    "approval_unavailable_error",
    "run_agent_turn",
]


# LoopConfig wins when set explicitly; a backend's own reported window or output
# ceiling only fills in a value the config leaves unset, so an endpoint can
# describe its own limits without every caller having to know them ahead of time.
def _resolve_context_bounds(
    backend: ChatBackend, cfg: LoopConfig
) -> tuple[int | None, int, int | None]:
    """Resolve the request's context window, max output tokens, and reserve."""
    backend_window = getattr(backend, "context_window_tokens", None)
    context_window = cfg.context_window_tokens
    if context_window is None and isinstance(backend_window, int) and backend_window > 0:
        context_window = backend_window
    backend_output = getattr(backend, "max_output_tokens", None)
    request_max_tokens = cfg.max_tokens
    if request_max_tokens is None and isinstance(backend_output, int) and backend_output > 0:
        request_max_tokens = backend_output
    output_reserve = (
        request_max_tokens
        if request_max_tokens is not None
        else current_home().default_max_output_tokens
    )
    return context_window, output_reserve, request_max_tokens


def _resolve_trace_coordinates(
    ctx: ToolContext,
    session_key: str,
    trace_project: str | None,
    trace_session_key: str | None,
) -> tuple[str, str]:
    """Pick where trace events are written; defaults keep old callers unchanged."""
    project = trace_project or ctx.project or ctx.agent_id or "unknown"
    trace_key = trace_session_key or session_key
    return project, trace_key


# Resolved once per turn, not per iteration -- neither the role's toolset nor
# this agent's identity files change mid-turn. *context_window_tokens*/
# *output_reserve_tokens* are this turn's already-resolved model bounds (see
# `_resolve_context_bounds`, called just before this in `_TurnState.create`) --
# threaded through so `compose_agent_prompt`'s static-context budget can share
# the same resolved window instead of a second, independent lookup.
def _resolve_role_registry_and_prompt(
    registry: ToolRegistry,
    ctx: ToolContext,
    *,
    context_window_tokens: int | None = None,
    output_reserve_tokens: int | None = None,
) -> tuple[ToolRegistry, PromptComposition, list[ToolSpec]]:
    """Narrow the tool registry to this role and compose today's system prompt."""
    registry = role_composer.narrow_registry(registry, ctx.role, ctx.project)
    composition = role_composer.compose_prompt(
        ctx.agent_id,
        project_roots=ctx.roots,
        context_window_tokens=context_window_tokens,
        max_output_tokens=output_reserve_tokens,
    )
    return registry, composition, registry.specs()


@dataclass
class _TurnState(TurnState):
    """The orchestrator: ``TurnState`` plus the collaborators that act on it (budget,
    compaction and request fit, the tool step), and the request/response phase between them."""

    finalization_attempted: bool = False
    close_attempted: bool = False
    close_forced: bool = False
    close_reply: str = ""
    budget: TurnBudget = field(init=False, repr=False)
    compaction: TurnCompaction = field(init=False, repr=False)
    steps: ToolStep = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.budget = TurnBudget(self)
        self.compaction = TurnCompaction(self, self.budget)
        self.steps = ToolStep(self)

    @classmethod
    def create(
        cls,
        *,
        backend: ChatBackend,
        registry: ToolRegistry,
        ctx: ToolContext,
        session_key: str,
        cfg: LoopConfig,
        clock: Callable[[], float],
        trace_project: str | None,
        trace_session_key: str | None,
        trace_task_id: str = "",
    ) -> _TurnState:
        """Resolve every per-turn constant, in the order the loop always has."""
        context_window, output_reserve, request_max_tokens = _resolve_context_bounds(backend, cfg)
        started = clock()
        project, trace_key = _resolve_trace_coordinates(
            ctx, session_key, trace_project, trace_session_key
        )
        registry, composition, tool_specs = _resolve_role_registry_and_prompt(
            registry,
            ctx,
            context_window_tokens=context_window,
            output_reserve_tokens=output_reserve,
        )
        system_prompt = composition.text
        if composition.text:
            _trace_prompt_composed(
                project,
                trace_key,
                ctx.role,
                composition.sections,
                composition.budget_tokens,
                composition.budget_source,
                task_id=trace_task_id,
                sha256=composition.sha256,
                sources=composition.sources,
            )
        return cls(
            backend=backend,
            ctx=ctx,
            session_key=session_key,
            cfg=cfg,
            clock=clock,
            started=started,
            project=project,
            trace_key=trace_key,
            context_window=context_window,
            output_reserve=output_reserve,
            request_max_tokens=request_max_tokens,
            call_max_tokens=request_max_tokens,
            registry=registry,
            system_prompt=system_prompt,
            tool_specs=tool_specs,
            trace_task_id=trace_task_id,
        )

    # Falls back to one tool-free terminal attempt when the ordinary
    # tool-enabled round no longer fits the remaining turn budget. A non-None
    # last element means stop now.
    def prepare_request_or_finalize(
        self,
    ) -> tuple[list[ChatMessage], list[ToolSpec], bool, AgentLoopResult | None]:
        """Fit the task request, or enter terminal finalization instead."""
        (
            messages,
            normal_estimated_input,
            fit_error,
            fit_stop_reason,
            fit_failure_kind,
        ) = self.compaction.fit_task_request()
        if fit_error:
            return (
                [],
                [],
                False,
                self.done(
                    ok=False,
                    stop_reason=fit_stop_reason or "context_fit",
                    error=fit_error,
                    failure_kind=fit_failure_kind or "invalid_output",
                ),
            )

        request_tools = self.tool_specs
        normal_budget_error = self.budget.prospective_budget_error(
            normal_estimated_input, purpose="tool-enabled task"
        )
        if not normal_budget_error:
            return messages, request_tools, False, None

        if self.finalization_attempted:
            return (
                [],
                [],
                False,
                self.done(
                    ok=False,
                    stop_reason="token_budget",
                    error=normal_budget_error,
                    failure_kind="invalid_output",
                ),
            )
        self.finalization_attempted = True
        terminal_messages = _finalization_messages(messages)
        final_estimated_input, final_fit_error = self.budget.preflight_request(
            terminal_messages,
            [],
            purpose="task",
        )
        final_budget_error = self.budget.prospective_budget_error(
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
            self.project,
            self.trace_key,
            self.ctx.role,
            status=final_status,
            reason=final_reason,
            token_budget=self.cfg.token_budget,
            measured_tokens_used=self.total_usage.counted_tokens,
            normal_estimated_input_tokens=normal_estimated_input,
            finalization_estimated_input_tokens=final_estimated_input,
            output_reserve_tokens=self.output_reserve,
            task_id=self.trace_task_id,
        )
        if final_fit_error:
            return (
                [],
                [],
                False,
                self.done(
                    ok=False,
                    stop_reason="context_fit",
                    error=final_fit_error,
                    failure_kind="invalid_output",
                ),
            )
        if final_budget_error:
            return (
                [],
                [],
                False,
                self.done(
                    ok=False,
                    stop_reason="token_budget",
                    error=final_budget_error,
                    failure_kind="invalid_output",
                ),
            )
        return terminal_messages, [], True, None

    # Returns the assistant message to dispatch tools for, or None with a
    # populated AgentLoopResult when the turn must stop here -- including the
    # ordinary final_message success exit, which is itself a response shape
    # (no tool calls requested), not a separate kind of ending. A None message
    # with no result means a reply that asked for no tool is to be followed by
    # the forced closing call (see closing_call_due).
    def call_backend_and_handle_response(
        self,
        messages: list[ChatMessage],
        request_tools: list[ToolSpec],
        finalizing: bool,
        request_timeout: int,
    ) -> tuple[ChatMessage | None, TokenUsage, AgentLoopResult | None]:
        """One backend exchange and every response-shaped stop condition."""
        if self.cancellation_requested():
            return None, TokenUsage(), self.cancelled()
        forced = self.cfg.closing_tool if self.close_forced else None
        carried, self.close_forced, self.close_reply = self.close_reply, False, ""
        if forced:
            messages = _closing_messages(messages, carried, forced)
        response = self.backend.complete(
            messages,
            tools=request_tools,
            max_tokens=self.call_max_tokens,
            temperature=self.cfg.temperature,
            top_p=self.cfg.top_p,
            tool_choice=forced,
            timeout=request_timeout,
        )
        _trace_llm_call(
            self.project,
            self.trace_key,
            self.ctx.role,
            response,
            self.iteration,
            task_id=self.trace_task_id,
            messages=messages,
            cfg=self.cfg,
            tool_choice=forced,
        )
        self.last_raw = response.raw
        self.last_model, self.last_provider = response.model, response.provider
        self.total_usage = _accumulate(self.total_usage, response.usage)
        self.budget.calibrate(response.usage.input_tokens)
        if self.cancellation_requested():
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(self.session_key, [], usage=response.usage)
            return None, response.usage, self.cancelled()
        if not response.ok:
            return (
                None,
                response.usage,
                self.done(
                    ok=False,
                    stop_reason="backend_error",
                    error=response.error,
                    failure_kind=response.failure_kind or "daemon_error",
                    retry_after_s=response.retry_after_s,
                ),
            )

        if response.truncated:
            # A length-truncated reply can carry a partial tool call — never
            # dispatched, and neither it nor the partial assistant content is
            # persisted (see module docstring). Endpoint-reported usage remains
            # durable even though the response itself is rejected.
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(self.session_key, [], usage=response.usage)
            return (
                None,
                response.usage,
                self.done(
                    ok=False,
                    stop_reason="truncated",
                    output=response.message.content,
                    error=(
                        "model response was truncated (finish_reason=length); no tool calls "
                        "were executed"
                    ),
                    failure_kind="invalid_output",
                ),
            )

        assistant_msg = response.message
        if assistant_msg.tool_calls and self.total_usage.counted_tokens > self.cfg.token_budget:
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(self.session_key, [], usage=response.usage)
            return (
                None,
                response.usage,
                self.done(
                    ok=False,
                    stop_reason="token_budget",
                    error=(
                        f"exceeded token_budget={self.cfg.token_budget} "
                        f"(used {self.total_usage.counted_tokens}); response was not persisted "
                        "and its tool calls were not dispatched"
                    ),
                    failure_kind="invalid_output",
                ),
            )

        if finalizing and assistant_msg.tool_calls:
            if response.usage.total_tokens or response.usage.cached_tokens:
                append_messages(self.session_key, [], usage=response.usage)
            return (
                None,
                response.usage,
                self.done(
                    ok=False,
                    stop_reason="token_budget",
                    error=(
                        "terminal finalization requested tool calls even though no tools were "
                        "advertised; none were dispatched or persisted"
                    ),
                    failure_kind="invalid_output",
                ),
            )
        if not assistant_msg.tool_calls and self.closing_call_due(finalizing):
            # The reply asks for no tool: keep its text for the closing call and persist only
            # that call's own message, so the stored history has one assistant turn.
            self.close_attempted = self.close_forced = True
            self.close_reply = assistant_msg.content
            append_messages(self.session_key, [], usage=response.usage)
            return None, response.usage, None
        if carried:
            assistant_msg = replace(
                assistant_msg,
                content="\n".join(p for p in (carried, assistant_msg.content) if p),
            )
        if not assistant_msg.tool_calls:
            append_messages(self.session_key, [assistant_msg], usage=response.usage)
            return (
                None,
                response.usage,
                self.done(ok=True, stop_reason="final_message", output=assistant_msg.content),
            )
        return assistant_msg, response.usage, None

    def closing_call_due(self, finalizing: bool) -> bool:
        """Whether a reply with no tool call is to be followed by the forced closing call: the
        profile forces it, the step's closing tool is offered, and it has not been forced yet."""
        return (
            self.cfg.tool_choice == "forced-on-close"
            and bool(self.cfg.closing_tool)
            and not self.close_attempted
            and not finalizing
            and any(spec.name == self.cfg.closing_tool for spec in self.tool_specs)
        )

    # Returns None to keep looping.
    def run_iteration(self) -> AgentLoopResult | None:
        """One full round: bounds, fit-or-finalize, model call, tool dispatch."""
        request_timeout, stop = self.budget.check_iteration_bounds()
        if stop is not None:
            return stop
        messages, request_tools, finalizing, stop = self.prepare_request_or_finalize()
        if stop is not None:
            return stop
        assistant_msg, response_usage, stop = self.call_backend_and_handle_response(
            messages, request_tools, finalizing, request_timeout
        )
        if stop is not None:
            return stop
        if assistant_msg is None:  # a reply that asked for no tool: the closing call follows
            return None
        return self.steps.dispatch_tool_batch(messages, assistant_msg, response_usage)


def run_agent_turn(
    backend: ChatBackend,
    registry: ToolRegistry,
    ctx: ToolContext,
    session_key: str,
    message: str,
    *,
    config: LoopConfig | None = None,
    clock: Callable[[], float] = _clock.monotonic,
    trace_project: str | None = None,
    trace_session_key: str | None = None,
    trace_task_id: str = "",
) -> AgentLoopResult:
    """Run one full turn: compose -> call -> gate-and-execute -> feed back -> repeat.

    ``session_key`` is the durable-history key (``agent/session.py``). The
    optional trace coordinates select only where events are written and default
    to ``ctx.project``/``session_key``. ``ctx`` also
    carries the tool containment boundary (``ctx.roots``) that
    ``dispatch_tool`` enforces — this function never inspects or widens it.

    Never raises for an ordinary failure mode: every stop condition, and
    every backend failure, comes back as a populated ``AgentLoopResult``.
    """
    cfg = config or LoopConfig()
    state = _TurnState.create(
        backend=backend,
        registry=registry,
        ctx=ctx,
        session_key=session_key,
        cfg=cfg,
        clock=clock,
        trace_project=trace_project,
        trace_session_key=trace_session_key,
        trace_task_id=trace_task_id,
    )

    initial_compaction_stop = state.compaction.apply_initial_history_compaction()
    if initial_compaction_stop is not None:
        return initial_compaction_stop

    state.compaction.seed_task_message(message)

    while True:
        outcome = state.run_iteration()
        if outcome is not None:
            return outcome
