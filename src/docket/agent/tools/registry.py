"""The gated tool registry.

**One chokepoint.** Every tool call passes through ``dispatch_tool`` and nowhere else -- the
policy engine, approval store, command classifier and audit log only work if there is exactly one
place a tool call can run from. A second path is not a convenience, it is a hole.

This module *decides*; ``agent/tools/builtins/toolbox.py`` *acts* and consults no policy, keeping
filesystem/subprocess work out of the decision path. Every non-allow decision is audited here, not by
callers. ``dispatch_tool``'s full order of operations is the pinned contract in
``specs/functional/security-gates.spec.md``'s "in-turn tool-call gate" section.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docket.agent.ports import ToolCall, ToolCallArgumentsError, ToolSpec, tool_gate

# ToolOutcome is re-exported: callers outside the chokepoint build one without importing the
# handler module, which only this module may import.
from docket.agent.tools.builtins.toolbox import SandboxMode
from docket.kernel.gate import (
    DEFAULT_MAX_CONSULTATIONS,
    Decision,
    GateCall,
    HandlerParked,
    HandlerUnavailable,
    ToolDenialKind,
)
from docket.kernel.tool_outcome import ToolOutcome as ToolOutcome

ToolKind = Literal["read", "write", "exec"]


@dataclass(frozen=True)
class Pregrant:
    """One single-use pre-grant carried into a turn: a human already approved this exact
    tool call, ahead of time, identified by its canonical argument digest."""

    token: str
    tool: str
    args_digest: str


@dataclass
class ToolContext:
    """Everything a tool call needs to know about who is making it. ``roots`` is the
    containment boundary for paths and the bash cwd; empty ``roots`` deliberately fails
    every path-taking tool rather than defaulting to the whole filesystem (see
    specs/functional/security-gates.spec.md items 4, 11)."""

    agent_id: str = ""
    session_key: str = ""
    roots: tuple[Path, ...] = ()
    timeout: int = 120
    env: dict[str, str] = field(default_factory=dict)
    role: str = ""
    project: str = ""
    sandbox: SandboxMode = "off"
    # False cuts the jail's network; only meaningful with a sandbox (the turn refuses otherwise).
    network: bool = True
    cancellation_check: Callable[[], bool] | None = None
    approval_mode: Literal["wait", "park", "refuse"] = "wait"
    allow_commands: tuple[str, ...] = ()
    pregrants: tuple[Pregrant, ...] = ()
    approval_expires_at: str | None = None
    # Seconds an in-turn approval or consult wait may last; None keeps Home.tool_approval_timeout.
    approval_timeout: int | None = None
    # The pod's cache dir: a jailed bash gets it as its home and an extra read-write root.
    cache_dir: Path | None = None
    # The operator's read-only jail grants (the toolchain); only a jailed bash reads them.
    read_only: tuple[Path, ...] = ()
    on_process: Callable[[str, dict[str, Any]], None] | None = None
    # The assistant text of the message making the current call(s); the agent loop sets it
    # per batch. Raw: ``_approval.screen_rationale`` screens it when an approval is made.
    rationale: str = ""
    # `consult` budget for this context (one turn); `consult_count` is what it has spent.
    max_consultations: int = DEFAULT_MAX_CONSULTATIONS
    consult_count: int = 0
    # Pod dispatch sets it: a consult parks the task (``waiting_input``) rather than waiting.
    consult_park: bool = False
    # The task this turn serves (a pod task id); stamps a consult's question.
    task_id: str = ""


@dataclass
class ToolResult:
    """Outcome of one call: what was decided, and what happened if it ran. ``executed``
    is separate from ``ok``: a denied call and a call that ran and failed are different
    events (a guardrail working vs. a task problem), and audit needs to tell them apart.
    ``policy_id`` is the ``pre_tool_call`` policy that (co-)decided a non-``allow`` verdict
    -- see specs/functional/security-gates.spec.md item 11 for when it is populated."""

    ok: bool
    content: str = ""
    error: str = ""
    decision: Decision = "allow"
    reason: str = ""
    tool: str = ""
    call_id: str = ""
    executed: bool = False
    denial_kind: ToolDenialKind | None = None
    policy_id: str = ""
    approval_token: str = ""

    @property
    def denied(self) -> bool:
        return self.decision == "deny"

    def as_tool_output(self) -> str:
        """The text fed back to the model: a refusal is reported in words, not silence, so the
        model can adapt instead of blindly retrying the same call."""
        if self.decision == "deny":
            kind = self.denial_kind or "invalid_call"
            return f"REFUSED [{kind}]: {self.reason}"
        if self.decision == "ask":
            return f"AWAITING APPROVAL: {self.reason}"
        if not self.ok:
            return f"ERROR: {self.error}\n{self.content}".strip()
        return self.content


@dataclass(frozen=True)
class Tool:
    """One callable tool: its schema for the model, its handler for docket. ``kind`` drives gating:
    ``exec`` goes through the classifier, ``write`` is a mutating record, ``read`` is the cheap case.
    ``ends_turn`` marks a tool whose successful call closes the turn (the agent loop's own rule)."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], ToolOutcome]
    kind: ToolKind = "read"
    ends_turn: bool = False

    @property
    def required_args(self) -> tuple[str, ...]:
        required = self.parameters.get("required")
        return tuple(str(r) for r in required) if isinstance(required, list) else ()

    def mistyped_strings(self, args: dict[str, Any]) -> tuple[str, ...]:
        """Required arguments the schema declares as strings that arrived as another JSON type."""
        properties = self.parameters.get("properties")
        declared = properties if isinstance(properties, dict) else {}
        return tuple(
            name
            for name in self.required_args
            if isinstance(declared.get(name), dict)
            and declared[name].get("type") == "string"
            and not isinstance(args[name], str)
        )

    def spec(self) -> ToolSpec:
        """The advertisement sent to the model."""
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)


class ToolRegistry:
    """The set of tools one agent may call, scoped per-agent (not global) so a role can be given a
    narrower set -- a Reviewer with no ``write`` tool cannot edit code by accident, a stronger
    guarantee than instructing it not to."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add *tool*, replacing any same-named entry."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        """Advertisements for every registered tool, in a stable order."""
        return [self._tools[name].spec() for name in self.names()]

    def without(self, *names: str) -> ToolRegistry:
        """A copy with *names* removed (e.g. a read-only Reviewer registry)."""
        clone = ToolRegistry()
        for name, tool in self._tools.items():
            if name not in names:
                clone.register(tool)
        return clone

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


# ── the chokepoint ────────────────────────────────────────────────────────────


def dispatch_tool(call: ToolCall, ctx: ToolContext, registry: ToolRegistry) -> ToolResult:
    """Run one tool call, or refuse it. The only path to tool execution."""
    result = ToolResult(ok=False, tool=call.name, call_id=call.id)

    def cancel_before_execution() -> bool:
        if ctx.cancellation_check is None or not ctx.cancellation_check():
            return False
        result.decision = "deny"
        result.denial_kind = "run_cancelled"
        result.reason = "run cancellation requested before execution"
        result.error = result.reason
        return True

    if cancel_before_execution():
        return result

    tool = registry.get(call.name)
    if tool is None:
        result.decision = "deny"
        result.denial_kind = "invalid_call"
        result.reason = f"unknown tool {call.name!r}; available: {', '.join(registry.names())}"
        result.error = result.reason
        return result

    try:
        args = call.parsed_arguments()
    except ToolCallArgumentsError as ex:
        # Fail closed. Arguments are what the gate inspects, so a call whose
        # arguments cannot be read cannot be evaluated, and an unevaluated call
        # must not run.
        result.decision = "deny"
        result.denial_kind = "invalid_call"
        result.reason = str(ex)
        result.error = result.reason
        return result

    missing = [name for name in tool.required_args if name not in args]
    if missing:
        result.decision = "deny"
        result.denial_kind = "invalid_call"
        result.reason = f"missing required argument(s): {', '.join(missing)}"
        result.error = result.reason
        return result

    mistyped = tool.mistyped_strings(args)
    if mistyped:
        result.decision = "deny"
        result.denial_kind = "invalid_call"
        result.reason = f"argument(s) must be text: {', '.join(mistyped)}"
        result.error = result.reason
        return result

    gate_call = GateCall(tool, call.id, args)
    decision = tool_gate.govern(gate_call, ctx)
    result.decision = decision.decision
    result.reason = decision.reason
    result.policy_id = decision.policy_id
    result.denial_kind = decision.denial_kind
    result.error = decision.error
    result.approval_token = decision.approval_token
    if decision.granted is not None:
        ctx.pregrants = (*ctx.pregrants, Pregrant(*decision.granted))
    if decision.decision == "deny":
        return result

    if cancel_before_execution():
        return result

    try:
        outcome = tool.handler(args, ctx)
    except HandlerParked as ex:
        result.decision = "deny"
        result.denial_kind = "approval_parked"
        result.policy_id = "consult"
        result.reason = str(ex)
        result.error = result.reason
        result.approval_token = ex.token
        return result
    except HandlerUnavailable as ex:
        # Same terminal stop as an approval nobody can give (refuse mode).
        result.decision = "deny"
        result.denial_kind = "approval_unavailable"
        result.reason = str(ex)
        result.error = result.reason
        return result
    except Exception as ex:  # a broken tool must not unwind the whole turn
        result.executed = True
        result.error = f"{type(ex).__name__}: {ex}"
        return result

    if outcome.refusal:
        tool_gate.audit_refusal(gate_call, ctx, outcome.refusal)
    result.executed = True
    result.ok = outcome.ok
    result.content = outcome.content
    result.error = outcome.error
    return result


# ── built-in tools ────────────────────────────────────────────────────────────


def str_arg(args: dict[str, Any], name: str, default: str = "") -> str:
    value = args.get(name, default)
    return value if isinstance(value, str) else str(value)
