"""What the turn engine owns and shows its neighbours: the ports and the vocabulary they speak.

Three ports and their types live here, because other contexts may import ``agent.ports`` and
nothing else of the engine's inside:

- ``RuntimeDriver`` (below): how a pod's pipeline runs one agent turn.
- ``ChatBackend`` and the chat vocabulary (``ChatMessage``, ``ToolCall``, ``TokenUsage``, ...):
  how the loop speaks to inference. ``models/adapters/openai_http.py`` is the shipped adapter; the
  shapes are docket's own, and the adapter translates in both directions, so no wire field leaks
  into the loop. Deliberately absent: streaming, and any notion of "an agent" -- a backend performs
  one request/response exchange; feeding tool results back and deciding when a turn is over belong
  to ``agent/loop.py``.
- ``RoleComposer`` and ``ToolGate``: what the engine asks of the teams (roles, the system prompt)
  and of governance (policy, approvals, audit). Both are bound once per entry point.

Execution-related state (session records, turn results, cost/usage) tends to leak its
on-disk/wire shape into every caller that reads it. ``RuntimeDriver`` is the fix: a single typed
``Protocol`` that application code and ``interfaces/cli`` program against, so no module outside
``models/adapters/`` needs to know what a session record, a driver invocation, or a cost figure
looks like on disk.

ROADMAP §4.5 bans an ``AbstractBackend``; this module revises that ban, not repeals
it: **one typed port, one shipped driver** (``hops.application.driver.DocketDriver``), plus a
``FakeDriver`` test double. This is containment of coupling, not speculative plugin-framework
generality -- a second real driver still needs a §4.5 trigger (upstream stall/breakage) or a
paying user.

The required members of ``RuntimeDriver`` mirror an agent's whole lifecycle: ``run_turn`` (one
costed agent turn, the hot path -- ``hops/application/runner.py``'s pipeline and docket's own
self-originated LLM calls go through this); ``list_sessions``/``usage`` (durable-session
enumeration and token/cost aggregation, keeping on-disk format knowledge out of application
code); ``capabilities`` (what this driver instance can actually promise, e.g. whether it reports
real USD cost, so callers never hardcode an assumption about the shipped driver's quirks).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from docket.kernel.errors import InvalidInput
from docket.kernel.gate import GateCall, GateContext, GateDecision, Screened
from docket.kernel.home import current_home
from docket.kernel.ports import Binding

if TYPE_CHECKING:
    from pathlib import Path

    from docket.agent.tools.registry import ToolRegistry

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

# Same route again: the JSON plan of the `verify` tool (command, directory, timeout) a hop whose
# step has a verify command is offered. Popped by DocketDriver, which registers the tool from it.
DOCKET_VERIFY_PLAN = "DOCKET_VERIFY_PLAN"

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


#: Where a resolved budget's value came from — named consistently wherever a
#: budget is reported (the ``prompt_composed`` trace event, ``docket pod
#: show``): an explicit ``CONTEXT_TOKEN_BUDGET`` env override, an archetype's
#: own declared ``tokenBudget``, a computed share of the resolved model
#: window, or today's plain constant (no override, no usable window).
BudgetSource = Literal["env", "archetype", "window", "default"]


#: A composed prompt section's fit outcome, for the ``prompt_composed`` trace event
#: `agent/loop.py` emits -- this module stays trace-free and only reports data.
PromptSectionStatus = Literal["full", "truncated", "omitted"]


@dataclass(frozen=True)
class PromptSectionReport:
    """One section's byte accounting in a composed prompt."""

    name: str
    bytes: int
    status: PromptSectionStatus


@dataclass(frozen=True)
class PromptComposition:
    """A composed system prompt plus its per-section fit accounting."""

    text: str
    sections: tuple[PromptSectionReport, ...] = ()
    # The static-context budget this composition was fit to, and where that number
    # came from (see resolve_static_context_budget) -- reported even for an empty
    # composition (no prompt material), describing what would have applied.
    budget_tokens: int = field(default_factory=lambda: current_home().context_token_budget_default)
    budget_source: BudgetSource = "default"


# ── the role composer: what a turn needs from the team that owns the role ──────


class RoleComposer(Protocol):
    """What the turn engine asks of the context that knows roles and identity files.

    The engine owns the loop; which tools a role may see, what budget its archetype declares
    and the system prompt its workspace composes are the team's data, bound once at the entry
    point (``bootstrap.bind_adapters``) and swapped in a test with ``role_composer_port.use``."""

    def narrow_registry(self, registry: ToolRegistry, role: str, project: str) -> ToolRegistry:
        """*registry* without the tools *role* may never call."""
        ...

    def declared_token_budget(self, role: str, project: str) -> int | None:
        """The context budget *role*'s archetype declares, or ``None`` when it declares none."""
        ...

    def compose_prompt(
        self,
        agent_id: str,
        *,
        project_roots: tuple[Path, ...],
        context_window_tokens: int | None,
        max_output_tokens: int | None,
    ) -> PromptComposition:
        """*agent_id*'s system prompt, fit to this turn's resolved model bounds."""
        ...


role_composer_port: Binding[RoleComposer] = Binding("role_composer")
role_composer: RoleComposer = role_composer_port.proxy()


def bind_role_composer(adapter: RoleComposer) -> None:
    role_composer_port.bind(adapter)


# ── the tool gate: what the chokepoint asks of governance ──────────────────────


class ToolGate(Protocol):
    """What ``dispatch_tool`` asks of the context that owns policy, approvals and audit.

    ``dispatch_tool`` stays the only way a tool call runs; it decides nothing itself. Bound once
    per entry (``bootstrap.bind_adapters``, the runtime package's ``_bind``) to ``governance.gate``
    and swapped in a test with ``tool_gate_port.use``."""

    def govern(self, call: GateCall, ctx: GateContext) -> GateDecision:
        """Whether *call* may run: policy and the command classifier, then any approval it needs."""
        ...

    def audit_refusal(self, call: GateCall, ctx: GateContext, kind: str) -> None:
        """Audit a refusal a tool handler made itself (``kind`` names the rule)."""
        ...

    def audit_event(self, action: str, detail: str) -> None:
        """Append *detail* to the audit log under *action* (a tool adapter's own event)."""
        ...

    def screen_untrusted(
        self,
        role: str,
        text: str,
        *,
        project: str,
        detail: str,
        blocked_action: str,
        warn_action: str,
    ) -> Screened:
        """Judge text from outside docket as untrusted input and audit a non-allow hit."""
        ...


tool_gate_port: Binding[ToolGate] = Binding("tool_gate")
tool_gate: ToolGate = tool_gate_port.proxy()


def bind_tool_gate(adapter: ToolGate) -> None:
    tool_gate_port.bind(adapter)


Role = Literal["system", "user", "assistant", "tool"]


class ToolCallArgumentsError(InvalidInput):
    """A model emitted tool-call arguments that are not a JSON object. Raised by
    ``ToolCall.parsed_arguments`` since arguments are what ``pre_tool_call`` inspects;
    ``dispatch_tool`` fail-closes to denial rather than executing an unreadable call."""


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation requested by the model. ``arguments`` stays the raw string the model
    emitted, not a parsed dict: the audit/trace record shows what was truly asked for (even
    malformed JSON), and a parse failure is one the gate must see, not inherit as empty."""

    id: str
    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        """Decode ``arguments`` as a JSON object. Raises ``ToolCallArgumentsError`` for anything
        that is not a JSON object (invalid JSON, or a bare list/string/number); an empty/blank
        string decodes to ``{}`` since some models emit that for a zero-argument tool."""
        raw = self.arguments.strip()
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as ex:
            raise ToolCallArgumentsError(
                f"tool call {self.name!r} sent unparseable arguments: {ex}"
            ) from ex
        if not isinstance(decoded, dict):
            raise ToolCallArgumentsError(
                f"tool call {self.name!r} sent {type(decoded).__name__} arguments, expected object"
            )
        return dict(decoded)


@dataclass(frozen=True)
class ToolSpec:
    """A tool advertised to the model. ``parameters`` (a JSON Schema object) is a plain dict,
    not a modelled type, because it passes through to the endpoint verbatim and docket never
    reasons about its internals; ``agent/tools/registry.py`` owns what a valid tool looks like."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """One message in a conversation. ``tool_calls`` populates only on an ``assistant`` message;
    ``tool_call_id``/``name`` only on a ``tool`` message — unenforced by the dataclass, so prefer
    the ``system``/``user``/``assistant``/``tool_result`` helpers below to a bare constructor."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""


def system(content: str) -> ChatMessage:
    """A system/instruction message."""
    return ChatMessage(role="system", content=content)


def user(content: str) -> ChatMessage:
    """A user-turn message."""
    return ChatMessage(role="user", content=content)


def assistant(content: str = "", tool_calls: Sequence[ToolCall] = ()) -> ChatMessage:
    """An assistant message, optionally requesting tool calls."""
    return ChatMessage(role="assistant", content=content, tool_calls=list(tool_calls))


def tool_result(call: ToolCall, content: str) -> ChatMessage:
    """The result of executing *call*, addressed back to the model. Takes the ``ToolCall``
    rather than a loose id/name pair so a result can never be attributed to the wrong call:
    an endpoint that receives a ``tool_call_id`` it did not issue rejects the whole request."""
    return ChatMessage(role="tool", content=content, tool_call_id=call.id, name=call.name)


@dataclass(frozen=True)
class TokenUsage:
    """Token counts **as reported by the endpoint** for one exchange — real counts off the
    response body, unlike the ``Home.context_bytes_per_token`` estimates used elsewhere
    (``agent/context.py``'s budgets). Keep this distinction in any
    user-facing wording: never call an estimate a measurement. ``cached_tokens`` is a subset of
    ``input_tokens`` where the endpoint reports one, and 0 where it does not — meaning "not
    reported", never "definitely no cache hit"; ``cache_write_tokens`` is a subset too."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Input plus output, for display and truthiness only; budgets use ``counted_tokens``."""
        return self.input_tokens + self.output_tokens

    @property
    def counted_tokens(self) -> int:
        """New tokens: input minus cache reads, plus output. What every budget compares."""
        return max(0, self.input_tokens - self.cached_tokens) + self.output_tokens


@dataclass
class ChatResponse:
    """Outcome of one exchange, never an exception for ordinary failures. Mirrors ``TurnResult``'s
    contract deliberately (reusing ``FailureKind`` so ``agent/loop.py``'s driver slots under
    ``hops/application/runner.py``'s retry policy); ``failure_kind`` is ``None`` iff ``ok`` is True."""

    ok: bool
    message: ChatMessage = field(default_factory=lambda: ChatMessage(role="assistant"))
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    failure_kind: FailureKind | None = None
    retry_after_s: float | None = None
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    #: Bytes of each request part as the adapter encoded them (system, tools, toolResults,
    #: assistant, user); empty when the backend does not measure its request.
    request_bytes: dict[str, int] = field(default_factory=dict)

    @property
    def tool_calls(self) -> list[ToolCall]:
        """Tool calls the model requested, if any (convenience for the loop)."""
        return self.message.tool_calls

    @property
    def truncated(self) -> bool:
        """True when the endpoint stopped for length, not because it was done; worth checking
        explicitly since a length-truncated reply can carry a *partial* tool call, exactly the
        malformed input the gate must not wave through."""
        return self.finish_reason == "length"


@dataclass(frozen=True)
class ModelLimits:
    """One model's context window and output cap as a provider published them; ``None`` is
    unknown, never zero."""

    context_window: int | None = None
    max_output: int | None = None


@dataclass(frozen=True)
class Endpoint:
    """Where to send an exchange, and as whom. ``api_key`` is never logged. ``auth_type``/
    ``auth_header`` say how it rides the wire (bearer, a named header, or none); ``headers``
    are additional static headers sent verbatim, as a tuple of pairs to stay hashable."""

    base_url: str
    model_id: str
    api_key: str = ""
    provider: str = ""
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    auth_type: Literal["bearer", "header", "none"] = "bearer"
    auth_header: str = ""
    headers: tuple[tuple[str, str], ...] = ()


@runtime_checkable
class ChatBackend(Protocol):
    """The port ``agent/loop.py`` programs against: one method, one exchange. Implementations
    must not raise for transport, protocol, or endpoint errors, returning ``ChatResponse(ok=False,
    failure_kind=...)`` instead so the caller's retry policy decides what happens next."""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        """Send *messages* (plus any advertised *tools*) and return the reply."""
        ...


def estimate_tokens(text: str) -> int:
    """Approximate *text*'s token count.

    ``len(text.encode("utf-8")) // Home.context_bytes_per_token`` — the
    same bytes-per-token approximation (default 4) ``teams/identity.py``'s
    prompt budget already uses for its own context-size guards. This is honestly an approximation, not a real count
    from the model's own tokenizer — good enough to bound a prompt
    deterministically, never a basis for billing.
    """
    return len(text.encode("utf-8")) // current_home().context_bytes_per_token
