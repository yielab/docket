"""The turn loop's public value types: ``StopReason``, ``LoopConfig`` and ``AgentLoopResult``.

Split from ``agent/loop.py`` so the turn's collaborators (``loop_state``, ``loop_budget``,
``loop_compaction``, ``loop_steps``) can name them without importing the loop itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from docket.agent.llm import TokenUsage
from docket.agent.ports import FailureKind
from docket.kernel.home import current_home

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
    "run_cancelled",
    "approval_unavailable",
    "approval_parked",
    "no_progress",
]


@dataclass(frozen=True)
class LoopConfig:
    """Bounds for one ``run_agent_turn`` call. See the module docstring for
    what each one guards against; defaults come from the current ``Home``'s
    ``agent_loop_*`` fields, read when the config is built, so every tunable here
    is env-overridable the same way every other docket tunable is.

    ``max_tokens``/``temperature`` are passed straight through to
    ``ChatBackend.complete`` — ``None`` (the default for both) means "let the
    endpoint decide," never a docket-side guess at a model's defaults. A
    positive ``max_tokens`` also supplies the output reserve for cumulative
    request preflight; without one the loop keeps its measured-response guard
    rather than inventing an output bound.
    """

    max_iterations: int = field(default_factory=lambda: current_home().agent_loop_max_iterations)
    max_tool_calls: int = field(default_factory=lambda: current_home().agent_loop_max_tool_calls)
    max_consecutive_tool_denials: int = field(
        default_factory=lambda: current_home().agent_loop_max_consecutive_tool_denials
    )
    no_progress_rounds: int = field(
        default_factory=lambda: current_home().agent_loop_no_progress_rounds
    )
    wall_clock_timeout_s: float = field(
        default_factory=lambda: current_home().agent_loop_wall_clock_timeout_s
    )
    token_budget: int = field(default_factory=lambda: current_home().agent_loop_token_budget)
    request_timeout_s: int = field(
        default_factory=lambda: current_home().agent_loop_request_timeout_s
    )
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
    ``agent/driver.py``'s translation to ``TurnResult`` is a
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
    retry_after_s: float | None = None
    model: str = ""
    provider: str = ""
