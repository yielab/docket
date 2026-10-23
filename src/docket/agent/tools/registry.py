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

import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docket.agent.llm import ToolCall, ToolCallArgumentsError, ToolSpec

# ToolOutcome is re-exported: callers outside the chokepoint build one without importing the
# handler module, which only this module may import.
from docket.agent.tools.builtins.toolbox import SandboxMode
from docket.agent.tools.builtins.toolbox import ToolOutcome as ToolOutcome
from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _approval_pregrant
from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.governance.security import classify_command
from docket.observability.trace import redact as _redact
from docket.operator.contract import canonical_args_digest
from docket.platform import git as _git
from docket.tasks.application import consult as _consult

ToolKind = Literal["read", "write", "exec"]
Decision = Literal["allow", "ask", "deny"]
ToolDenialKind = Literal[
    "invalid_call",
    "gate_denied",
    "approval_denied",
    "approval_timeout",
    "run_cancelled",
    "approval_unavailable",
    "approval_parked",
]


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
    max_consultations: int = _consult.DEFAULT_MAX_CONSULTATIONS
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
    ``exec`` goes through the classifier, ``write`` is a mutating record, ``read`` is the cheap case."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], ToolOutcome]
    kind: ToolKind = "read"

    @property
    def required_args(self) -> tuple[str, ...]:
        required = self.parameters.get("required")
        return tuple(str(r) for r in required) if isinstance(required, list) else ()

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


# ── rendering a call for the policy engine ──────────────────────────────────


def render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Render one tool call as the text a ``pre_tool_call`` regex policy matches.
    Pinned contract: ``"<name> <key>=<json-value> ..."``, keys in ``args``' own order,
    each value ``json.dumps``-encoded; a no-argument call renders as just ``name``.
    Putting the name first keeps a command-shaped regex (``rm\\s+-[rf]``) matching
    this render the same way it matches the bare command -- it is *not* symmetric, so
    a pattern assuming an argument appears *before* its verb will not match. See
    specs/functional/security-gates.spec.md item 1."""
    parts = [name]
    for key, value in args.items():
        parts.append(f"{key}={json.dumps(value)}")
    return " ".join(parts)


# ── the gate ──────────────────────────────────────────────────────────────────


# Most-restrictive-wins ranking, mirroring governance/policy.py's _RANK philosophy
# but over the three-valued tool Decision rather than five policy actions.
_DECISION_RANK: dict[str, int] = {"deny": 2, "ask": 1, "allow": 0}

# governance/policy.py action -> tool Decision. `warn`/`redact` do not block
# execution — they are recorded (see dispatch_tool) but never change what a
# tool call is allowed to do, since neither implies a human must decide first.
_POLICY_ACTION_TO_DECISION: dict[str, Decision] = {
    "block": "deny",
    "require_approval": "ask",
    "warn": "allow",
    "redact": "allow",
    "allow": "allow",
}


_CONSULT_TOOL = "consult"


@dataclass(frozen=True)
class ToolVerdict:
    """The gate's answer for one call. ``policy_action``/``policy_id`` carry the *raw*
    ``pre_tool_call`` hit, independent of what decided ``decision`` -- so a caller can
    see a ``warn``/``redact`` fired even when the overall decision is ``allow``.
    ``policy_action`` is ``""`` when no policy matched, ``"allow"`` when one matched
    but allowed."""

    decision: Decision
    reason: str = ""
    policy_id: str = ""
    policy_action: str = ""


def evaluate_tool_call(tool: Tool, args: dict[str, Any], ctx: ToolContext) -> ToolVerdict:
    """Decide whether this call may proceed. **The** decision point: combines the
    argument-aware command classifier (``exec`` tools only) and the ``pre_tool_call``
    policy hook in this one function so "what gates a call" has a single answer,
    most-restrictive-wins (deny beats ask beats allow) -- see
    specs/functional/security-gates.spec.md items 1-3 for why argument-awareness
    matters (``git`` is allowlisted, ``git push origin production`` is not). Pure:
    never audits or traces, that is ``dispatch_tool``'s job."""
    command_decision: Decision = "allow"
    command_reason = ""
    if tool.kind == "exec":
        command = str(args.get("command") or "")
        cmd_verdict = classify_command(
            command,
            extra_bins=frozenset(ctx.allow_commands),
            roots=tuple(ctx.roots),
            jailed=ctx.sandbox == "auto",
        )
        if cmd_verdict.action != "allow":
            command_decision = "ask" if cmd_verdict.action == "ask" else "deny"
            command_reason = cmd_verdict.reason

    rendered = render_tool_call(tool.name, args)
    call = _policy.ToolCallFacts(
        tool=tool.name,
        args=args,
        branch_of=lambda: _git.git_current_branch(str(ctx.roots[0])) if ctx.roots else "",
        worktree_root=str(ctx.roots[0]) if ctx.roots else "",
    )
    hit = _policy.policy_eval_detail(
        ctx.role, "pre_tool_call", rendered, project=ctx.project, call=call
    )
    policy_decision = _POLICY_ACTION_TO_DECISION.get(hit.action, "allow")
    policy_reason = f"policy {hit.policy_id!r}: {hit.message}" if hit.policy_id else ""

    if _DECISION_RANK[command_decision] >= _DECISION_RANK[policy_decision]:
        decision, reason = command_decision, command_reason
    else:
        decision, reason = policy_decision, policy_reason
    if tool.name == _CONSULT_TOOL and decision == "ask":
        # The consultation is the human's decision: asking approval to ask would put the same
        # question to the operator twice. The raw hit stays on the verdict; deny still denies.
        decision = "allow"

    return ToolVerdict(decision, reason, policy_id=hit.policy_id, policy_action=hit.action)


# ── the chokepoint ────────────────────────────────────────────────────────────


def _audit_tool_decision(
    action: str,
    tool_name: str,
    ctx: ToolContext,
    detail: str,
    *,
    policy_id: str = "",
    policy_action: str = "",
) -> None:
    """Write one audit entry for a non-``allow`` (or ``warn``/``redact``) gate decision.
    Centralized so every gated call is recorded exactly once regardless of which check
    decided it; arguments are redacted first since they can carry a secret (a token in a
    ``write`` call, a credential in a ``bash`` command). Records ``policy_id``/
    ``policy_action`` as a fixed, ``repr``-quoted pair so a reader can attribute a hit
    without parsing free-text ``detail``."""
    audit_log(
        action,
        f"tool={tool_name} agent={ctx.agent_id or '?'} role={ctx.role or '?'} "
        f"project={ctx.project or '?'} policy_id={policy_id!r} policy_action={policy_action!r}: "
        f"{_redact(detail)}",
    )


def _audit_refusal(tool: Tool, args: dict[str, Any], ctx: ToolContext, kind: str) -> None:
    """Audit a refusal a handler made itself: tool, kind and the attempted path or host only."""
    if kind == "fetch_not_allowed":
        host = urllib.parse.urlsplit(_str_arg(args, "url")).hostname or "?"
        target = f"host={host.lower()!r}"
    else:
        target = f"path={_str_arg(args, 'path')!r}"
    _audit_tool_decision("tool.refused", tool.name, ctx, f"kind={kind} {target}")


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

    verdict = evaluate_tool_call(tool, args, ctx)
    result.decision = verdict.decision
    result.reason = verdict.reason
    if verdict.decision != "allow":
        result.policy_id = verdict.policy_id

    if verdict.policy_action in ("warn", "redact"):
        # Allowed to proceed, but a policy still flagged it -- silently
        # letting this through would waste the policy.
        _audit_tool_decision(
            f"tool.{verdict.policy_action}",
            tool.name,
            ctx,
            f"call={render_tool_call(tool.name, args)}",
            policy_id=verdict.policy_id,
            policy_action=verdict.policy_action,
        )

    if verdict.decision == "deny":
        result.denial_kind = "gate_denied"
        _audit_tool_decision(
            "tool.deny",
            tool.name,
            ctx,
            f"{verdict.reason} call={render_tool_call(tool.name, args)}",
            policy_id=verdict.policy_id,
            policy_action=verdict.policy_action,
        )
        result.error = verdict.reason
        return result

    if verdict.decision == "ask" and _resolve_ask_verdict(call, tool, args, ctx, verdict, result):
        return result

    if cancel_before_execution():
        return result

    try:
        outcome = tool.handler(args, ctx)
    except _consult.ConsultParked as ex:
        result.decision = "deny"
        result.denial_kind = "approval_parked"
        result.policy_id = "consult"
        result.reason = str(ex)
        result.error = result.reason
        result.approval_token = ex.token
        return result
    except _consult.ConsultUnavailable as ex:
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
        _audit_refusal(tool, args, ctx, outcome.refusal)
    result.executed = True
    result.ok = outcome.ok
    result.content = outcome.content
    result.error = outcome.error
    return result


def _resolve_ask_verdict(
    call: ToolCall,
    tool: Tool,
    args: dict[str, Any],
    ctx: ToolContext,
    verdict: ToolVerdict,
    result: ToolResult,
) -> bool:
    """Handle an ``ask`` verdict: a matching pre-grant, ``refuse``, ``park``, or
    ``wait``. Mutates *result* in place; returns ``True`` when it is already
    terminal, so ``dispatch_tool`` should return it without running the handler."""
    _audit_tool_decision(
        "tool.ask",
        tool.name,
        ctx,
        f"{verdict.reason} call={render_tool_call(tool.name, args)}",
        policy_id=verdict.policy_id,
        policy_action=verdict.policy_action,
    )
    digest = canonical_args_digest(tool.name, args)
    pregrant_token = _consume_matching_pregrant(ctx, tool.name, digest)
    if pregrant_token is not None:
        # A human already approved this exact call, ahead of time, by its
        # canonical argument digest -- consumed once, above, so it falls
        # straight through to execution without asking again.
        result.decision = "allow"
        result.reason = f"pre-granted (token={pregrant_token})"
        result.approval_token = pregrant_token
        return False

    if ctx.approval_mode == "refuse":
        # No approval record, no wait: the pod's posture says nobody will answer. Reported
        # distinctly from a timeout or an explicit denial ("nobody was asked").
        result.decision = "deny"
        result.denial_kind = "approval_unavailable"
        result.error = result.reason
        return True

    if ctx.approval_mode == "park":
        _park_call(call, tool, args, ctx, verdict, digest, result)
        return True

    rationale, blocked = _approval.screen_rationale(ctx.rationale, ctx.project)
    token = _approval.approval_create(
        ctx.project or "operator",
        ctx.role or "tool",
        (f"tool call {tool.name!r}: {verdict.reason}; call={render_tool_call(tool.name, args)}")[
            :1000
        ],
        context={"tool": tool.name, "callId": call.id, "argsDigest": digest},
        rationale=rationale,
        rationale_blocked=blocked,
    )
    _wait_for_ask_approval(token, ctx, result, tool.name, digest)
    return result.decision == "deny"


def _park_call(
    call: ToolCall,
    tool: Tool,
    args: dict[str, Any],
    ctx: ToolContext,
    verdict: ToolVerdict,
    digest: str,
    result: ToolResult,
) -> None:
    """Record the exact call and end the turn without waiting -- a later grant
    re-enters the pipeline with a single-use pre-grant for it (tasks/application/actions.py's
    resume path). Mutates *result* into its terminal ``approval_parked`` denial."""
    park_context: dict[str, Any] = {
        "tool": tool.name,
        "callId": call.id,
        "argsDigest": digest,
        "parked": True,
    }
    if ctx.project:
        park_context["project"] = ctx.project
    if ctx.role:
        park_context["role"] = ctx.role
    if ctx.task_id:
        park_context["taskId"] = ctx.task_id  # lets the inbox fold this approval into its task
    rationale, blocked = _approval.screen_rationale(ctx.rationale, ctx.project)
    token = _approval.approval_create(
        ctx.project or "operator",
        ctx.role or "tool",
        (f"tool call {tool.name!r}: {verdict.reason}; call={render_tool_call(tool.name, args)}")[
            :1000
        ],
        context=park_context,
        expires_at=ctx.approval_expires_at,
        rationale=rationale,
        rationale_blocked=blocked,
    )
    result.decision = "deny"
    result.denial_kind = "approval_parked"
    result.approval_token = token
    result.reason = f"parked for approval (token={token})"
    result.error = result.reason


def _consume_matching_pregrant(ctx: ToolContext, tool_name: str, digest: str) -> str | None:
    """Return the token of the first pre-grant whose ``(tool, args_digest)`` matches and
    that consumed cleanly, or ``None``. A pre-grant past its own expiry, or already
    consumed by a concurrent caller, does not match."""
    for pregrant in ctx.pregrants:
        if (
            pregrant.tool == tool_name
            and pregrant.args_digest == digest
            and _approval_pregrant.consume_pregrant(pregrant.token)
        ):
            return pregrant.token
    return None


def _wait_for_ask_approval(
    token: str, ctx: ToolContext, result: ToolResult, tool_name: str = "", digest: str = ""
) -> None:
    """Block on *token* (the ``wait`` posture, the pre-existing in-turn gate) and fill
    *result* with the outcome, mutating it in place."""
    kwargs: dict[str, Any] = {}
    if ctx.approval_timeout is not None:
        kwargs["timeout"] = ctx.approval_timeout
    if ctx.cancellation_check is not None:
        kwargs["cancellation_check"] = ctx.cancellation_check
    # A run without cancellation or a bound keeps the embeddable runtime's one-argument stub.
    wait_outcome = _approval.wait_for_approval(token, **kwargs)
    if ctx.cancellation_check is not None and ctx.cancellation_check():
        result.decision = "deny"
        result.denial_kind = "run_cancelled"
        result.reason = "run cancellation requested before execution"
        result.error = result.reason
        return
    if wait_outcome.state != "granted":
        result.decision = "deny"
        if wait_outcome.cancelled:
            result.denial_kind = "run_cancelled"
            result.reason = "run cancellation requested before execution"
        else:
            result.denial_kind = "approval_timeout" if wait_outcome.timed_out else "approval_denied"
            result.reason = (
                "approval timed out and was denied" if wait_outcome.timed_out else "approval denied"
            )
        result.error = result.reason
        return
    # Granted: the call is now allowed, and falls through to execute.
    result.decision = "allow"
    result.reason = f"approved (token={token})"
    _record_task_pregrant(token, ctx, tool_name, digest)


def _record_task_pregrant(token: str, ctx: ToolContext, tool_name: str, digest: str) -> None:
    """``approve_task``: a grant that chose that option also pre-grants one identical call
    for the rest of this turn's context, through the existing ``create_pregrant`` path."""
    if not tool_name or not digest:
        return
    try:
        record = _approval.approval_get(token)
        if (record.get("context") or {}).get("optionId") != "approve_task":
            return
        pre = _approval_pregrant.create_pregrant(
            ctx.project or "operator",
            ctx.role or "tool",
            tool_name,
            digest,
            channel="cli",
            actor="approve_task",
        )
    except _approval.ApprovalError:
        return
    ctx.pregrants = (*ctx.pregrants, Pregrant(pre, tool_name, digest))


# ── built-in tools ────────────────────────────────────────────────────────────


def _str_arg(args: dict[str, Any], name: str, default: str = "") -> str:
    value = args.get(name, default)
    return value if isinstance(value, str) else str(value)


def screen_tool_result(
    role: str,
    outcome: ToolOutcome,
    *,
    source: str,
    detail: str,
    blocked_action: str,
    warn_action: str,
    project: str = "",
) -> ToolOutcome:
    """Screen a remote tool result as untrusted `pre_input` (the calling pod's policies
    included): block refuses, redact strips, warn passes; each non-allow hit is audited under
    the caller's action names; *source* names the origin, *detail* prefixes the audit."""
    text = outcome.content if outcome.ok else outcome.error
    if not text:
        return outcome
    hit = _policy.policy_eval_detail(role, "pre_input", text, trusted=False, project=project)
    audit_detail = f"{detail} policy={hit.policy_id!r} action={hit.action}"
    if hit.action in ("block", "require_approval"):
        audit_log(blocked_action, audit_detail)
        return ToolOutcome(
            False,
            error=f"result from {source} blocked by policy {hit.policy_id!r} (action={hit.action})",
            refusal=outcome.refusal,
        )
    if hit.action in ("warn", "redact"):
        audit_log(warn_action, audit_detail)
    if hit.action == "redact":
        if outcome.ok:
            return ToolOutcome(True, content=_redact(text))
        return ToolOutcome(False, error=_redact(text), refusal=outcome.refusal)
    return outcome
