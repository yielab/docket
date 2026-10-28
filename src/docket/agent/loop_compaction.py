"""Compaction for the turn loop: the tool-free summariser and the request-fit reduction.

``TurnCompaction`` owns the compaction summariser (one tool-free backend call, no loop
recursion, no session writes), the initial history compaction, the incoming task message's
durable position, and the request-fit loop that compacts around that message until the task
request fits the registered context window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docket.agent.loop_budget import _TOKEN_BUDGET_ERROR_PREFIX, TurnBudget
from docket.agent.loop_request import (
    _accumulate,
    _build_reduction_candidates,
    _segment_revision,
    _selected_estimate,
    _usage_delta,
)
from docket.agent.loop_state import TurnState
from docket.agent.loop_trace import _trace_compaction, _trace_llm_call
from docket.agent.loop_types import AgentLoopResult, StopReason
from docket.agent.ports import ChatMessage, FailureKind, TurnResult, system, user
from docket.agent.session import append_messages, condense_history, load_messages
from docket.agent.session_compaction import CompactionResult, compact_session


@dataclass
class _FitStop:
    """Terminal outcome of one context-fit reduction attempt, returned verbatim."""

    messages: list[ChatMessage]
    estimated_input: int
    error: str
    stop_reason: StopReason | None
    failure_kind: FailureKind | None


@dataclass
class _FitOutcome:
    """Result of one reduce_for_fit call: a stop outcome, or retry-loop state."""

    stop: _FitStop | None = None
    durable_revision: list[ChatMessage] = field(default_factory=list)
    current_revision: str = ""
    current_messages: list[ChatMessage] = field(default_factory=list)
    attempts: int = 0


class TurnCompaction:
    """Compaction and request-fit reduction around the incoming task message."""

    def __init__(self, state: TurnState, budget: TurnBudget) -> None:
        self.state = state
        self.budget = budget
        self.compaction_failure_stop_reason: StopReason | None = None
        self.incoming: ChatMessage | None = None
        self.task_message_index = -1

    def summarize_without_reentry(
        self,
        agent_id: str,
        summary_session_key: str,
        prompt: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        """One tool-free backend call: no loop recursion and no session writes."""
        if summary_session_key == self.state.session_key:
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                {},
                "compaction summarizer key matched the target session",
                "invalid_output",
            )
        elapsed = self.state.clock() - self.state.started
        remaining = int(self.state.cfg.wall_clock_timeout_s - elapsed)
        if remaining <= 0:
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                {},
                "compaction exhausted the turn wall-clock budget",
                "timeout",
            )
        summary_messages = [user(prompt)]
        estimated_input, fit_error = self.budget.preflight_request(
            summary_messages,
            [],
            purpose="compaction",
        )
        if fit_error:
            self.compaction_failure_stop_reason = "context_fit"
            return TurnResult(False, "", 0.0, {}, fit_error, "invalid_output")
        budget_error = self.budget.prospective_budget_error(estimated_input, purpose="compaction")
        if budget_error:
            self.compaction_failure_stop_reason = "token_budget"
            return TurnResult(False, "", 0.0, {}, budget_error, "invalid_output")
        if self.state.cancellation_requested():
            self.compaction_failure_stop_reason = "run_cancelled"
            return TurnResult(False, "", 0.0, {}, "run cancellation requested", "run_cancelled")
        response = self.state.backend.complete(
            summary_messages,
            tools=(),
            max_tokens=self.state.call_max_tokens,
            temperature=self.state.cfg.temperature,
            top_p=self.state.cfg.top_p,
            timeout=min(timeout, remaining),
        )
        _trace_llm_call(
            self.state.project,
            self.state.trace_key,
            self.state.ctx.role,
            response,
            purpose="compaction",
            task_id=self.state.trace_task_id,
            messages=summary_messages,
            cfg=self.state.cfg,
        )
        self.state.last_raw = response.raw
        self.state.last_model, self.state.last_provider = response.model, response.provider
        self.state.summary_usage = _accumulate(self.state.summary_usage, response.usage)
        if self.state.cancellation_requested():
            self.compaction_failure_stop_reason = "run_cancelled"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "run cancellation requested",
                "run_cancelled",
            )
        if not response.ok:
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                response.error,
                response.failure_kind or "daemon_error",
            )
        if response.truncated:
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "compaction summarizer response was truncated; partial summary was not accepted",
                "invalid_output",
            )
        if response.tool_calls:
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "compaction summarizer requested tools on a tool-free call",
                "invalid_output",
            )
        if not response.message.content.strip():
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                "compaction summarisation turn returned an empty summary",
                "invalid_output",
            )
        measured_tokens = self.budget.effective_measured_tokens()
        if measured_tokens > self.state.cfg.token_budget:
            self.compaction_failure_stop_reason = "token_budget"
            return TurnResult(
                False,
                "",
                0.0,
                response.raw,
                (
                    f"{_TOKEN_BUDGET_ERROR_PREFIX} compaction completion exceeded "
                    f"token_budget={self.state.cfg.token_budget} (used {measured_tokens}); summary was "
                    "not accepted"
                ),
                "invalid_output",
            )
        return TurnResult(True, response.message.content, 0.0, response.raw)

    def run_compaction(
        self,
        *,
        budget_tokens: int | None,
        compact_range: tuple[int, int] | None = None,
        keep_latest_unit: bool = True,
    ) -> tuple[CompactionResult, StopReason | None]:
        self.compaction_failure_stop_reason = None
        elapsed_now = self.state.clock() - self.state.started
        remaining_now = max(1, int(self.state.cfg.wall_clock_timeout_s - elapsed_now))
        result = compact_session(
            self.state.session_key,
            role=self.state.ctx.role,
            agent_id=self.state.ctx.agent_id,
            summarizer=self.summarize_without_reentry,
            summarizer_session_key=f"{self.state.session_key}:compaction",
            budget_tokens=budget_tokens,
            summary_input_budget_tokens=self.state.cfg.summary_input_budget_tokens,
            compact_range=compact_range,
            keep_latest_unit=keep_latest_unit,
            timeout=min(self.state.cfg.request_timeout_s, remaining_now),
            label=f"{self.state.ctx.role} session",
            project=self.state.project,
        )
        usage_delta = _usage_delta(self.state.summary_usage, self.state.accounted_summary_usage)
        self.state.total_usage = _accumulate(self.state.total_usage, usage_delta)
        self.state.accounted_summary_usage = self.state.summary_usage
        if usage_delta.total_tokens or usage_delta.cached_tokens:
            append_messages(self.state.session_key, [], usage=usage_delta)
        _trace_compaction(
            self.state.project,
            self.state.trace_key,
            self.state.ctx.role,
            result,
            task_id=self.state.trace_task_id,
        )
        return result, self.compaction_failure_stop_reason

    def apply_initial_history_compaction(self) -> AgentLoopResult | None:
        """Compact durable history to the turn's budget before the incoming message is seeded."""
        if self.state.cancellation_requested():
            return self.state.cancelled()
        compaction, compaction_stop_reason = self.run_compaction(
            budget_tokens=self.state.cfg.history_budget_tokens
        )
        if not compaction.ok:
            return self.state.done(
                ok=False,
                stop_reason=compaction_stop_reason or "compaction_failed",
                error=compaction.error,
                failure_kind=compaction.failure_kind or "invalid_output",
            )
        return None

    def seed_task_message(self, message: str) -> None:
        """Append the incoming user message and record its durable position."""
        incoming = user(message)
        appended = append_messages(self.state.session_key, [incoming])
        self.incoming = incoming
        self.task_message_index = len(appended.messages) - 1

    def messages_for_durable(self, durable: list[ChatMessage]) -> list[ChatMessage]:
        return [
            *([system(self.state.system_prompt)] if self.state.system_prompt else []),
            *condense_history(durable),
        ]

    def context_fit_convergence_error(self, reason: str, estimated_input: int) -> str:
        registered_window = (
            str(self.state.context_window) if self.state.context_window is not None else "unknown"
        )
        return (
            "context fit: estimated request "
            f"{estimated_input + self.state.output_reserve} tokens (input {estimated_input} + output "
            f"reserve {self.state.output_reserve}) could not be validated against registered context "
            f"window {registered_window}: {reason}"
        )

    def fit_task_request(
        self,
    ) -> tuple[list[ChatMessage], int, str, StopReason | None, FailureKind | None]:
        durable_revision = load_messages(self.state.session_key)
        current_messages = self.messages_for_durable(durable_revision)
        current_revision = _segment_revision(durable_revision)
        attempts = 0
        attempt_cap = max(2, len(durable_revision) + 1)
        protected_segments: dict[str, tuple[int, str]] = {}
        while True:
            estimated_input, fit_error = self.budget.preflight_request(
                current_messages,
                self.state.tool_specs,
                purpose="task",
            )
            latest_durable = load_messages(self.state.session_key)
            latest_revision = _segment_revision(latest_durable)
            if latest_revision != current_revision:
                if attempts >= attempt_cap:
                    return (
                        current_messages,
                        estimated_input,
                        self.context_fit_convergence_error(
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
                current_messages = self.messages_for_durable(durable_revision)
                continue
            if self.budget.prospective_budget_error(estimated_input, purpose="tool-enabled task"):
                return current_messages, estimated_input, "", None, None
            if not fit_error:
                return current_messages, estimated_input, "", None, None
            if self.state.context_window is None or self.state.output_reserve <= 0:
                return (
                    current_messages,
                    estimated_input,
                    fit_error,
                    "context_fit",
                    "invalid_output",
                )
            if attempts >= attempt_cap:
                return (
                    current_messages,
                    estimated_input,
                    f"{fit_error}; request-fit compaction did not converge",
                    "context_fit",
                    "invalid_output",
                )

            outcome = self.reduce_for_fit(
                fit_error, estimated_input, current_messages, protected_segments, attempts
            )
            if outcome.stop is not None:
                stop = outcome.stop
                return (
                    stop.messages,
                    stop.estimated_input,
                    stop.error,
                    stop.stop_reason,
                    stop.failure_kind,
                )
            durable_revision = outcome.durable_revision
            current_revision = outcome.current_revision
            current_messages = outcome.current_messages
            attempts = outcome.attempts

    def reduce_for_fit(
        self,
        fit_error: str,
        estimated_input: int,
        current_messages: list[ChatMessage],
        protected_segments: dict[str, tuple[int, str]],
        attempts: int,
    ) -> _FitOutcome:
        """One request-fit compaction attempt: try the suffix, then the prefix, around
        the task message; return a terminal ``_FitStop`` or state to retry with."""
        assert self.incoming is not None
        assert self.state.context_window is not None
        durable = load_messages(self.state.session_key)
        task_index = self.task_message_index
        if task_index < 0 or task_index >= len(durable) or durable[task_index] != self.incoming:
            return _FitOutcome(
                stop=_FitStop(
                    current_messages,
                    estimated_input,
                    f"{fit_error}; current task was not found in durable history",
                    "context_fit",
                    "invalid_output",
                )
            )
        overflow = estimated_input + self.state.output_reserve - self.state.context_window
        candidate_ranges = _build_reduction_candidates(durable, task_index, protected_segments)

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
            fit_compaction, fit_compaction_stop_reason = self.run_compaction(
                budget_tokens=target,
                compact_range=selected_range,
                keep_latest_unit=keep_latest,
            )
            if not fit_compaction.ok:
                failure_stop_reason = fit_compaction_stop_reason or "compaction_failed"
                return _FitOutcome(
                    stop=_FitStop(
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
            return _FitOutcome(
                stop=_FitStop(
                    current_messages,
                    estimated_input,
                    f"{fit_error}; irreducible durable request",
                    "context_fit",
                    "invalid_output",
                )
            )

        durable = load_messages(self.state.session_key)
        reloaded_task_index = (
            accepted_replacement_count if accepted_segment == "prefix" else task_index
        )
        if (
            reloaded_task_index < 0
            or reloaded_task_index >= len(durable)
            or durable[reloaded_task_index] != self.incoming
        ):
            return _FitOutcome(
                stop=_FitStop(
                    current_messages,
                    estimated_input,
                    self.context_fit_convergence_error(
                        "current task durable identity changed during request-fit compaction",
                        estimated_input,
                    ),
                    "context_fit",
                    "invalid_output",
                )
            )
        self.task_message_index = reloaded_task_index
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
        current_messages = self.messages_for_durable(durable_revision)
        return _FitOutcome(
            durable_revision=durable_revision,
            current_revision=current_revision,
            current_messages=current_messages,
            attempts=attempts + 1,
        )
