"""Compaction for the turn loop: the tool-free summariser and the request-fit reduction.

``TurnCompaction`` owns the compaction summariser (one tool-free backend call, no loop
recursion, no session writes), the incoming task message's durable position, and the request-fit
loop that compacts around that message until the task request fits the registered context window.
A session is compacted for that one reason; nothing compacts it at the start of a turn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from docket.agent.loop_budget import _TOKEN_BUDGET_ERROR_PREFIX, TurnBudget
from docket.agent.loop_request import (
    CUT_SUMMARY_ADVICE,
    _accumulate,
    _build_reduction_candidates,
    _cut_reply_ask,
    _fallback_input_estimate,
    _message_tokens,
    _segment_revision,
    _usage_delta,
    send_request,
)
from docket.agent.loop_state import TurnState
from docket.agent.loop_trace import _trace_compaction, _trace_llm_call
from docket.agent.loop_types import StopReason
from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    FailureKind,
    TurnResult,
    role_composer,
    system,
    user,
)
from docket.agent.session import (
    HISTORY_FULL_RESULTS_CHARS,
    append_messages,
    condense_history,
    load_messages,
    window_results_budget,
)
from docket.agent.session_compaction import CompactionResult, compact_session
from docket.agent.session_units import group_atomic_units, is_compacted_summary_unit

#: The share of the request room one reduction frees beyond the overflow: the summary it writes
#: takes room back, and a reduction that frees only the overflow is repeated by the next round.
_FIT_HEADROOM_SHARE = 4


def covering_range(
    durable: list[ChatMessage],
    projected: list[ChatMessage],
    bounds: tuple[int, int],
    need: int,
    headroom: int = 0,
    *,
    calibration: float = 1.0,
) -> tuple[int, int] | None:
    """The oldest whole atomic units of ``durable[bounds]``, sized as the preflight sizes them
    (``projected``, scaled by *calibration*), that cover *need* + *headroom*; else the whole of
    *bounds* if it covers *need*. It holds a non-summary unit, else ``None``."""
    start, end = bounds
    covered = 0
    cursor = start
    has_raw_unit = False
    for raw_unit, projected_unit in zip(
        group_atomic_units(durable[start:end]),
        group_atomic_units(projected[start:end]),
        strict=True,
    ):
        covered += math.ceil(_message_tokens(projected_unit) * calibration)
        cursor += len(raw_unit)
        has_raw_unit = has_raw_unit or not is_compacted_summary_unit(raw_unit)
        if has_raw_unit and covered >= need + headroom:
            return start, cursor
    if has_raw_unit and covered >= need:
        return start, cursor
    return None


@dataclass(frozen=True)
class RequestProjection:
    """The messages of one task request and what the projection did to its tool results."""

    messages: list[ChatMessage]
    condensed_results: int
    kept_whole_results: int
    budget_chars: int

    def figures(self) -> dict[str, int]:
        """The trace form: the ``projection`` of an ``llm_call`` event."""
        return {
            "condensedResults": self.condensed_results,
            "keptWholeResults": self.kept_whole_results,
            "budgetChars": self.budget_chars,
        }


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
        #: The latest summary request was refused for its size and the estimate learned from it.
        self.summary_refused_for_size = False
        #: The output cap a summary of this compaction was cut at; its repeat asks for less (116a).
        self.summary_cut_at = 0
        #: The projection of the request most recently built; the next task call carries its figures.
        self.projection: RequestProjection | None = None

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
                {},
                "compaction exhausted the turn wall-clock budget",
                "timeout",
            )
        if self.summary_cut_at:
            prompt = f"{prompt}\n\n{_cut_reply_ask(self.summary_cut_at, CUT_SUMMARY_ADVICE)}"
        summary_messages = [user(prompt)]
        estimated_input, fit_error = self.budget.preflight_request(
            summary_messages,
            [],
            purpose="compaction",
        )
        if fit_error:
            self.compaction_failure_stop_reason = "context_fit"
            return TurnResult(False, "", {}, fit_error, "invalid_output")
        budget_error = self.budget.prospective_budget_error(estimated_input, purpose="compaction")
        if budget_error:
            self.compaction_failure_stop_reason = "token_budget"
            return TurnResult(False, "", {}, budget_error, "invalid_output")
        if self.state.cancellation_requested():
            self.compaction_failure_stop_reason = "run_cancelled"
            return TurnResult(False, "", {}, "run cancellation requested", "run_cancelled")
        state = self.state

        def clock_left_timeout() -> int:
            # A retry after a timeout gets the request limit that timeout widened (requirement 110).
            left = int(state.cfg.wall_clock_timeout_s - (state.clock() - state.started))
            return min(max(timeout, state.request_limit_s), max(1, left))

        response, sent_timeout = send_request(
            state,
            lambda seconds: state.backend.complete(
                summary_messages,
                tools=(),
                max_tokens=state.call_max_tokens,
                temperature=state.cfg.temperature,
                top_p=state.cfg.top_p,
                timeout=seconds,
            ),
            min(timeout, remaining),
            next_timeout=clock_left_timeout,
            clock_cut=self.budget.clock_cut,
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
                response.raw,
                "run cancellation requested",
                "run_cancelled",
            )
        if not response.ok:
            if response.context_overflow:
                self.summary_refused_for_size = self.budget.learn_from_overflow(
                    response.overflow_input_tokens
                )
            on_clock = self.budget.timed_out_on_clock(response, sent_timeout)
            self.compaction_failure_stop_reason = "timeout" if on_clock else "compaction_failed"
            return TurnResult(
                False,
                "",
                response.raw,
                response.error,
                response.failure_kind or "daemon_error",
            )
        if response.truncated:
            return self.cut_summary(response)
        if response.tool_calls:
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
                response.raw,
                "compaction summarizer requested tools on a tool-free call",
                "invalid_output",
            )
        if not response.message.content.strip():
            self.compaction_failure_stop_reason = "compaction_failed"
            return TurnResult(
                False,
                "",
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
                response.raw,
                (
                    f"{_TOKEN_BUDGET_ERROR_PREFIX} compaction completion exceeded "
                    f"token_budget={self.state.cfg.token_budget} (used {measured_tokens}); summary was "
                    "not accepted"
                ),
                "invalid_output",
            )
        return TurnResult(True, response.message.content, response.raw)

    def cut_summary(self, response: ChatResponse) -> TurnResult:
        """A summary cut for length is never accepted (requirement 36). Cut because its prompt ate
        the reply room, it teaches the estimate (48a); cut at the cap, the repeat asks for less
        (116a). Either way the attempt fails, and ``run_compaction`` decides on the repeat."""
        measured = response.usage.input_tokens
        if self.state.context_window is not None and measured > self.budget.request_room():
            self.summary_refused_for_size = self.budget.learn_from_overflow(measured)
        elif not self.summary_cut_at:
            self.summary_cut_at = self.state.call_max_tokens or response.usage.output_tokens or 1
        self.compaction_failure_stop_reason = "compaction_failed"
        return TurnResult(
            False,
            "",
            response.raw,
            "compaction summarizer response was truncated; partial summary was not accepted",
            "invalid_output",
        )

    def run_compaction(
        self, compact_range: tuple[int, int]
    ) -> tuple[CompactionResult, StopReason | None]:
        """Summarize *compact_range* of the session whole, in batches the summarizer's own request
        can carry: its input is bounded by what passes the fit preflight, like any request."""
        elapsed_now = self.state.clock() - self.state.started
        remaining_now = max(1, int(self.state.cfg.wall_clock_timeout_s - elapsed_now))
        prompt_text, prompt_sha256 = role_composer.compaction_prompt(
            self.state.project, self.state.ctx.roots
        )

        def attempt() -> CompactionResult:
            # Fail-closed: a failed attempt wrote nothing, so a repeat starts from the same session.
            self.compaction_failure_stop_reason = None
            self.summary_refused_for_size = False
            return compact_session(
                self.state.session_key,
                agent_id=self.state.ctx.agent_id,
                summarizer=self.summarize_without_reentry,
                prompt_text=prompt_text,
                prompt_sha256=prompt_sha256,
                summarizer_session_key=f"{self.state.session_key}:compaction",
                budget_tokens=0,
                summary_input_budget_tokens=self.budget.request_room(),
                summary_estimate=self.budget.prompt_cost,
                compact_range=compact_range,
                keep_latest_unit=False,
                timeout=min(self.state.request_limit_s, remaining_now),
                label=f"{self.state.ctx.role} session",
            )

        result = attempt()
        if not result.ok and (self.summary_refused_for_size or self.summary_cut_at):
            # 48a: the refusal taught the scale, so the batches are smaller this time; 116a: the
            # prompt asks for a shorter summary.
            first, first_stop = result, self.compaction_failure_stop_reason
            result = attempt()
            if self.compaction_failure_stop_reason == "token_budget":
                # The repeat was refused before it was sent: the first failure stays (36).
                result, self.compaction_failure_stop_reason = first, first_stop
            elif not result.ok and self.summary_refused_for_size:
                result = replace(
                    result,
                    error=(
                        "context fit: the provider refused the summary request for its size twice, "
                        f"the second time after the estimate was recalibrated: {result.error}"
                    ),
                )
        self.summary_cut_at = 0  # the next compaction starts without the ask
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
        if result.compacted:
            self.state.compactions += 1
        return result, self.compaction_failure_stop_reason

    def seed_task_message(self, message: str) -> None:
        """Append the incoming user message and record its durable position."""
        incoming = user(message)
        appended = append_messages(self.state.session_key, [incoming])
        self.incoming = incoming
        self.task_message_index = len(appended.messages) - 1

    def whole_results_budget(self, durable: list[ChatMessage]) -> int:
        """The characters of whole tool results the window leaves once the system prompt, the tool
        specs and the history's other messages are in: the default where the window is unknown."""
        window = self.state.context_window
        if window is None:
            return HISTORY_FULL_RESULTS_CHARS
        base = [system(self.state.system_prompt)] if self.state.system_prompt else []
        others = base + [m for m in durable if m.role != "tool"]
        fixed = _fallback_input_estimate(others, self.state.tool_specs, None, None)
        return window_results_budget(window - max(0, self.state.output_reserve) - fixed)

    def projected(self, durable: list[ChatMessage]) -> tuple[list[ChatMessage], int]:
        """*durable* as the request carries it, with the whole-results budget that shaped it."""
        budget = self.whole_results_budget(durable)
        return condense_history(durable, budget=budget), budget

    def messages_for_durable(self, durable: list[ChatMessage]) -> RequestProjection:
        """The request for *durable*: the system prompt, then the history as projected. Remembered
        as ``self.projection``."""
        projected, budget = self.projected(durable)
        results = [(m, p) for m, p in zip(durable, projected, strict=True) if m.role == "tool"]
        condensed = sum(1 for m, p in results if p.content != m.content)
        self.projection = RequestProjection(
            messages=[
                *([system(self.state.system_prompt)] if self.state.system_prompt else []),
                *projected,
            ],
            condensed_results=condensed,
            kept_whole_results=len(results) - condensed,
            budget_chars=budget,
        )
        return self.projection

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
        current_messages = self.messages_for_durable(durable_revision).messages
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
                current_messages = self.messages_for_durable(durable_revision).messages
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
        headroom = self.budget.request_room() // _FIT_HEADROOM_SHARE
        projected, _budget = self.projected(durable)

        progressed = False
        accepted_segment = ""
        accepted_prior_protected_count = 0
        accepted_replacement_count = 0
        accepted_size_change = 0
        # Per candidate: the range with headroom, then (when the headroom grew it) the range that
        # covers the overflow alone, tried only if a unit of the larger one is too large to summarize.
        tries: list[tuple[str, int, tuple[int, int], bool]] = []
        for segment, candidate_range, prior_protected_count in candidate_ranges:
            wanted = covering_range(
                durable,
                projected,
                candidate_range,
                overflow,
                headroom,
                calibration=self.budget.calibration,
            )
            if wanted is None:
                continue
            bare = covering_range(
                durable, projected, candidate_range, overflow, calibration=self.budget.calibration
            )
            smaller = bare if bare is not None and bare != wanted else None
            tries.append((segment, prior_protected_count, wanted, smaller is not None))
            if smaller is not None:
                tries.append((segment, prior_protected_count, smaller, False))
        for segment, prior_protected_count, selected_range, retry in tries:
            fit_compaction, fit_compaction_stop_reason = self.run_compaction(selected_range)
            if retry and fit_compaction.unit_too_large and fit_compaction_stop_reason is None:
                continue
            if fit_compaction.refused_by_guard and fit_compaction_stop_reason is None:
                # The summary gained nothing and the history is as it was: the request is
                # irreducible, which is the fit stop, not a summarizer failure.
                return _FitOutcome(
                    stop=_FitStop(
                        current_messages,
                        estimated_input,
                        f"{fit_error}; irreducible durable request: {fit_compaction.error}",
                        "context_fit",
                        "invalid_output",
                    )
                )
            if not fit_compaction.ok:
                # The summarizer's own stop (a timeout on the clock, a cancellation, the token
                # budget) and its typed kind are the turn's; a plain failure is compaction_failed.
                return _FitOutcome(
                    stop=_FitStop(
                        current_messages,
                        estimated_input,
                        fit_compaction.error or "request-fit compaction failed",
                        fit_compaction_stop_reason or "compaction_failed",
                        fit_compaction.failure_kind or "invalid_output",
                    )
                )
            if fit_compaction.compacted:
                accepted_segment = segment
                accepted_prior_protected_count = prior_protected_count
                accepted_size_change = (
                    fit_compaction.after_message_count - fit_compaction.before_message_count
                )
                accepted_replacement_count = (
                    accepted_size_change + selected_range[1] - selected_range[0]
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
        reloaded_task_index = task_index + (
            accepted_size_change if accepted_segment == "prefix" else 0
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
        current_messages = self.messages_for_durable(durable_revision).messages
        return _FitOutcome(
            durable_revision=durable_revision,
            current_revision=current_revision,
            current_messages=current_messages,
            attempts=attempts + 1,
        )
