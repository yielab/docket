"""RuntimeDriver port.

Execution-related state (session records, turn results, cost/usage) tends to leak
its on-disk/wire shape into every caller that reads it. This module is the fix: a
single typed ``Protocol`` that application code and ``interfaces/cli`` program against, so no module
outside ``models/adapters/`` needs to know what a session record, a driver
invocation, or a cost figure actually looks like on disk.

ROADMAP §4.5 bans an ``AbstractBackend``; this module revises that ban, not repeals
it: **one typed port, one shipped driver** (``agent.driver.
DocketDriver``), plus a ``FakeDriver`` test double. This is containment of
coupling, not speculative plugin-framework generality — a second real driver still
needs a §4.5 trigger (upstream stall/breakage) or a paying user.

The required members mirror an agent's whole lifecycle: ``run_turn`` (one
costed agent turn, the hot path -- ``hops/application/runner.py``'s pipeline and docket's own
self-originated LLM calls go through this); ``list_sessions``/``usage`` (durable-session
enumeration and token/cost aggregation, keeping on-disk format knowledge out of
application code); ``capabilities`` (what this driver instance can actually promise, e.g.
whether it reports real USD cost, so callers never hardcode an assumption about the
shipped driver's quirks).

Nothing in this module touches a filesystem or a subprocess — it is pure typing,
describing only the shape a driver's return values must have.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from docket.agent.llm import TokenUsage

# ── run_turn ──────────────────────────────────────────────────────────────────

# Only "timeout"/"daemon_error" are retryable (a transient hiccup talking to the
# model backend, not a real answer) — see hops/application/runner.py's _RETRYABLE_FAILURE_KINDS.
FailureKind = Literal[
    "timeout",
    "daemon_error",
    "nonzero_exit",
    "invalid_output",
    "run_cancelled",
]

# Internal dispatch→driver coordinate for a downstream hop that must inspect
# the worktree which produced its handoff. The shipped driver validates it
# against same-pod Implementer metadata before using it as a tool root.
PIPELINE_WORKTREE_ENV = "DOCKET_PIPELINE_WORKTREE"

# Internal caller→driver coordinate for a turn that has nobody to ask for approval
# (a pod's `approvalMode`). Travels the same route
# as PIPELINE_WORKTREE_ENV: set in run_turn's env, popped by DocketDriver
# before the tool env is built, and mapped onto ToolContext.approval_mode.
DOCKET_APPROVAL_MODE = "DOCKET_APPROVAL_MODE"

# Same route as DOCKET_APPROVAL_MODE: a JSON list of single-use pre-grants
# (``[{"token", "tool", "argsDigest"}, ...]``) a resumed hop carries for the
# exact calls a human already granted. Popped by DocketDriver into
# ToolContext.pregrants.
DOCKET_PREGRANTS = "DOCKET_PREGRANTS"

# Same route again: the seconds an in-turn approval or consult wait may last for this one run,
# popped by DocketDriver into ToolContext.approval_timeout.
DOCKET_APPROVAL_TIMEOUT = "DOCKET_APPROVAL_TIMEOUT"

# Same route again: the ISO UTC deadline a ``park``-mode call's approval
# record should carry as its own ``expiresAt``. Popped by DocketDriver into
# ToolContext.approval_expires_at.
DOCKET_APPROVAL_EXPIRES_AT = "DOCKET_APPROVAL_EXPIRES_AT"

# Same route again: a caller's measured-token ceiling for this one turn (a positive
# integer, as text). Popped by DocketDriver into LoopConfig.token_budget, so an
# unset value keeps the configured AGENT_LOOP_TOKEN_BUDGET default.
DOCKET_TURN_TOKEN_BUDGET = "DOCKET_TURN_TOKEN_BUDGET"

# Same route again, one per task restriction (security-gates.spec.md "Task restrictions"), popped by
# DocketDriver: a JSON list of tool names to block, the literal "none" to cut the jail's network,
# and a JSON list of block-only policy documents evaluated after the pod's.
DOCKET_TASK_DENIED_TOOLS = "DOCKET_TASK_DENIED_TOOLS"
DOCKET_TASK_NETWORK = "DOCKET_TASK_NETWORK"
DOCKET_TASK_POLICIES = "DOCKET_TASK_POLICIES"

# Same route again: this turn's `consult` budget (a non-negative integer, as text). Popped by
# DocketDriver into ToolContext.max_consultations; unset, the driver reads the pod's
# `maxConsultationsPerTask` setting (default 3).
DOCKET_MAX_CONSULTATIONS = "DOCKET_MAX_CONSULTATIONS"


@dataclass
class TurnResult:
    """Outcome of one agent turn, however the driver executed it. Field order is
    load-bearing: dozens of existing tests construct this positionally
    (``TurnResult(False, "", 0.0, {}, "boom")``) — do not reorder or insert a field
    before ``failure_kind`` without a matching sweep of those call sites."""

    ok: bool
    output: str
    cost_usd: float  # 0.0 when the driver doesn't report a USD cost
    raw: dict[str, Any]  # full parsed backend response (empty when unparseable)
    error: str = ""
    failure_kind: FailureKind | None = None
    # kw_only: dataclasses moves kw_only fields out of the positional __init__
    # signature regardless of declaration order, so this stays addable without
    # breaking the positional call sites the class docstring warns about.
    retry_after_s: float | None = field(default=None, kw_only=True)
    # Measured endpoint token counts for this turn (never an estimate); ``None`` when the
    # driver reports none (evidence-v1 then records null usage for the hop).
    usage: TokenUsage | None = field(default=None, kw_only=True)
    # The turn loop's own stop reason (``agent.loop.StopReason``: ``approval_unavailable``,
    # ``max_iterations``, ...), finer than ``failure_kind``; ``""`` when the driver gave none.
    stop_reason: str = field(default="", kw_only=True)
    # Repository files this turn's prompt and skill reads were served from the task's base commit:
    # repository-relative path -> sha256 of the bytes served. Empty when the turn read the
    # filesystem (no task worktree).
    repo_files: dict[str, str] = field(default_factory=dict, kw_only=True)
    # The served model (bare endpoint id) and its provider, as the last response reported them;
    # "" when no response arrived. See pod-dispatch.spec.md, "Hop events and task usage".
    model: str = field(default="", kw_only=True)
    provider: str = field(default="", kw_only=True)


# ── list_sessions ─────────────────────────────────────────────────────────────


@dataclass
class SessionSummary:
    """One durable session the driver knows about for an agent. ``session_id`` is the
    only field callers may treat as stable identity — everything else is best-effort
    metadata for display/ingestion, not a contract other modules should branch on."""

    session_id: str
    turns: int = 0
    last_active: str = ""  # ISO-ish timestamp string, '' if unknown


# ── usage ─────────────────────────────────────────────────────────────────────


@dataclass
class UsageTotals:
    """Aggregated token/cost totals for one agent across all its sessions."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    turns: int = 0


@dataclass
class UsageDay:
    """Token/cost totals for a single calendar day."""

    date: str
    turns: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class UsageReport:
    """``usage()``'s full return: running totals plus a per-day breakdown."""

    totals: UsageTotals
    by_day: list[UsageDay] = field(default_factory=list)


# ── capabilities ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DriverCapabilities:
    """What one driver instance can actually promise. Exists so a caller never has to
    hardcode an assumption about the shipped driver's quirks — ``DocketDriver``
    reports only measured token counts, never a USD cost field, so
    ``reports_cost_usd`` is False even though ``run_turn`` always returns a (zero)
    ``cost_usd``."""

    driver_name: str
    reports_cost_usd: bool
    supports_sessions: bool


# ── the port itself ────────────────────────────────────────────────────────────


@runtime_checkable
class RuntimeDriver(Protocol):
    """The typed boundary between docket's domain logic and an agent runtime.
    Application code and ``interfaces/cli`` depend on this Protocol, never on a concrete driver's
    on-disk format knowledge. ``DocketDriver`` is the one shipped implementation --
    one typed port, one driver, not a plugin framework (see module docstring);
    ``tests/fakes.py``'s ``FakeDriver`` is the one test double."""

    def run_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
        *,
        on_spawn: Callable[[int], None] | None = None,
        trace_project: str | None = None,
        trace_session_key: str | None = None,
        trace_task_id: str | None = None,
        model: str | None = None,
    ) -> TurnResult:
        """Run one real, costed agent turn. Never raises for ordinary failure modes.
        ``on_spawn`` fires with the process pid immediately after it starts, before
        this call blocks on its result -- a driver with no real process (or a test
        double) may ignore it, so this is purely additive. ``trace_project``/
        ``trace_session_key`` optionally keep an audit stream separate from the
        durable ``session_key``; drivers without an internal trace producer may
        ignore them. ``trace_task_id`` names the pod task a dispatch hop serves: a non-empty
        value stamps the turn's trace events and lets a consult park that task; ``None`` or
        ``""`` is a turn with no task. ``model``, when given, wins over *agent_id*'s own
        configured model for this one call only -- a pipeline step's own override (pipeline-format.spec.md
        "Steps" Req. 10) -- and is never persisted."""
        ...

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        """Enumerate the durable sessions the driver knows about for *agent_id*."""
        ...

    def usage(self, agent_id: str) -> UsageReport:
        """Aggregate token/cost usage for *agent_id* across all its sessions."""
        ...

    def capabilities(self) -> DriverCapabilities:
        """Describe what this driver instance can actually promise."""
        ...
