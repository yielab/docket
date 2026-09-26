"""The gated tool registry.

**One chokepoint.** Every tool call passes through ``dispatch_tool`` and nowhere else -- the
policy engine, approval store, command classifier and audit log only work if there is exactly one
place a tool call can run from. A second path is not a convenience, it is a hole.

This module *decides*; ``edges/adapters/toolbox.py`` *acts* and consults no policy, keeping
filesystem/subprocess work out of ``core/``. Every non-allow decision is audited here, not by
callers. ``dispatch_tool``'s full order of operations is the pinned contract in
``specs/functional/security-gates.spec.md``'s "in-turn tool-call gate" section.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docket.core import approval as _approval
from docket.core import policy as _policy
from docket.core.audit import audit_log
from docket.core.llm import ToolCall, ToolCallArgumentsError, ToolSpec
from docket.core.security import classify_command
from docket.core.trace import redact as _redact
from docket.edges.adapters.toolbox import SandboxMode, ToolOutcome

ToolKind = Literal["read", "write", "exec"]
Decision = Literal["allow", "ask", "deny"]
ToolDenialKind = Literal[
    "invalid_call",
    "gate_denied",
    "approval_denied",
    "approval_timeout",
    "run_cancelled",
    "approval_unavailable",
]


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
    cancellation_check: Callable[[], bool] | None = None
    approval_mode: Literal["wait", "refuse"] = "wait"
    allow_commands: tuple[str, ...] = ()


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

    def without_kind(self, *kinds: ToolKind) -> ToolRegistry:
        """A copy with every tool whose ``kind`` is in *kinds* removed. Keyed on
        capability, not name, so a namespaced MCP-adapted tool still gets excluded from a
        role that denies that capability. See specs/functional/role-archetypes.spec.md
        and the sole caller, ``core.archetypes.registry_for_role``."""
        clone = ToolRegistry()
        for tool in self._tools.values():
            if tool.kind not in kinds:
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


# Most-restrictive-wins ranking, mirroring core/policy.py's _RANK philosophy
# but over the three-valued tool Decision rather than five policy actions.
_DECISION_RANK: dict[str, int] = {"deny": 2, "ask": 1, "allow": 0}

# core/policy.py action -> tool Decision. `warn`/`redact` do not block
# execution — they are recorded (see dispatch_tool) but never change what a
# tool call is allowed to do, since neither implies a human must decide first.
_POLICY_ACTION_TO_DECISION: dict[str, Decision] = {
    "block": "deny",
    "require_approval": "ask",
    "warn": "allow",
    "redact": "allow",
    "allow": "allow",
}


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
        cmd_verdict = classify_command(command, extra_bins=frozenset(ctx.allow_commands))
        if cmd_verdict.action != "allow":
            command_decision = "ask" if cmd_verdict.action == "ask" else "deny"
            command_reason = cmd_verdict.reason

    rendered = render_tool_call(tool.name, args)
    hit = _policy.policy_eval_detail(ctx.role, "pre_tool_call", rendered)
    policy_decision = _POLICY_ACTION_TO_DECISION.get(hit.action, "allow")
    policy_reason = f"policy {hit.policy_id!r}: {hit.message}" if hit.policy_id else ""

    if _DECISION_RANK[command_decision] >= _DECISION_RANK[policy_decision]:
        decision, reason = command_decision, command_reason
    else:
        decision, reason = policy_decision, policy_reason

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

    if verdict.decision == "ask":
        _audit_tool_decision(
            "tool.ask",
            tool.name,
            ctx,
            f"{verdict.reason} call={render_tool_call(tool.name, args)}",
            policy_id=verdict.policy_id,
            policy_action=verdict.policy_action,
        )
        if ctx.approval_mode == "refuse":
            # No approval record, no wait: there is nobody on the other end of
            # this call who could ever answer it. Reported distinctly from a
            # timeout or an explicit denial so a caller can tell "nobody was
            # asked" apart from "someone was asked and said no" or "asked and
            # nobody answered in time" -- see docs/adr/0001-harness-mode.md
            # decision 11.
            result.decision = "deny"
            result.denial_kind = "approval_unavailable"
            result.error = result.reason
            return result
        token = _approval.approval_create(
            ctx.project or "operator",
            ctx.role or "tool",
            (
                f"tool call {tool.name!r}: {verdict.reason}; "
                f"call={render_tool_call(tool.name, args)}"
            )[:1000],
            context={"tool": tool.name, "callId": call.id},
        )
        if ctx.cancellation_check is None:
            # Preserve the public embeddable runtime's one-argument approval
            # stub when this call is not owned by a cancellable run.
            wait_outcome = _approval.wait_for_approval(token)
        else:
            wait_outcome = _approval.wait_for_approval(
                token,
                cancellation_check=ctx.cancellation_check,
            )
        if cancel_before_execution():
            return result
        if wait_outcome.state != "granted":
            result.decision = "deny"
            if wait_outcome.cancelled:
                result.denial_kind = "run_cancelled"
                result.reason = "run cancellation requested before execution"
            else:
                result.denial_kind = (
                    "approval_timeout" if wait_outcome.timed_out else "approval_denied"
                )
                result.reason = (
                    "approval timed out and was denied"
                    if wait_outcome.timed_out
                    else "approval denied"
                )
            result.error = result.reason
            return result
        # Granted: the call is now allowed, and falls through to execute.
        result.decision = "allow"
        result.reason = f"approved (token={token})"

    if cancel_before_execution():
        return result

    try:
        outcome = tool.handler(args, ctx)
    except Exception as ex:  # a broken tool must not unwind the whole turn
        result.executed = True
        result.error = f"{type(ex).__name__}: {ex}"
        return result

    result.executed = True
    result.ok = outcome.ok
    result.content = outcome.content
    result.error = outcome.error
    return result


# ── built-in tools ────────────────────────────────────────────────────────────


def _str_arg(args: dict[str, Any], name: str, default: str = "") -> str:
    value = args.get(name, default)
    return value if isinstance(value, str) else str(value)


def _int_arg(args: dict[str, Any], name: str, default: int = 0) -> int:
    value = args.get(name, default)
    return int(value) if isinstance(value, int | float | str) and str(value).isdigit() else default


def builtin_registry() -> ToolRegistry:
    """The default tool set: read, write, edit, glob, grep, bash, fetch. Handlers are
    imported here (not at module scope) so this module stays importable without the
    filesystem/subprocess layer, keeping "core reaches out to edges for I/O" at one
    point."""
    from docket.edges.adapters import fetch as _fetch
    from docket.edges.adapters import toolbox

    registry = ToolRegistry()

    registry.register(
        Tool(
            name="read",
            description="Read a text file. Use offset/limit to read a window of a large file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read."},
                    "offset": {"type": "integer", "description": "First line (1-indexed)."},
                    "limit": {"type": "integer", "description": "Number of lines to read."},
                },
                "required": ["path"],
            },
            handler=lambda args, ctx: toolbox.read_file(
                ctx.roots,
                _str_arg(args, "path"),
                _int_arg(args, "offset"),
                _int_arg(args, "limit"),
            ),
            kind="read",
        )
    )

    registry.register(
        Tool(
            name="write",
            description="Create or overwrite a text file with the given content.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
            handler=lambda args, ctx: toolbox.write_file(
                ctx.roots, _str_arg(args, "path"), _str_arg(args, "content")
            ),
            kind="write",
        )
    )

    registry.register(
        Tool(
            name="edit",
            description=(
                "Replace an exact string in a file. Fails if the string is not unique "
                "unless replace_all is set."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit."},
                    "old_string": {"type": "string", "description": "Exact text to replace."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
                },
                "required": ["path", "old_string", "new_string"],
            },
            handler=lambda args, ctx: toolbox.edit_file(
                ctx.roots,
                _str_arg(args, "path"),
                _str_arg(args, "old_string"),
                _str_arg(args, "new_string"),
                bool(args.get("replace_all")),
            ),
            kind="write",
        )
    )

    registry.register(
        Tool(
            name="glob",
            description="List files matching a glob pattern, most recently modified first.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob, e.g. '**/*.py'."},
                    "path": {"type": "string", "description": "Directory to search from."},
                },
                "required": ["pattern"],
            },
            handler=lambda args, ctx: toolbox.glob_files(
                ctx.roots, _str_arg(args, "pattern"), _str_arg(args, "path")
            ),
            kind="read",
        )
    )

    registry.register(
        Tool(
            name="grep",
            description="Search file contents for a regular expression.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression."},
                    "path": {"type": "string", "description": "Directory to search from."},
                    "glob": {"type": "string", "description": "File filter, e.g. '**/*.py'."},
                },
                "required": ["pattern"],
            },
            handler=lambda args, ctx: toolbox.grep_files(
                ctx.roots,
                _str_arg(args, "pattern"),
                _str_arg(args, "path"),
                _str_arg(args, "glob", "**/*"),
            ),
            kind="read",
        )
    )

    registry.register(
        Tool(
            name="bash",
            description=(
                "Run a shell command in the workspace. Commands are classified before they "
                "run; anything off the allowlist or matching a high-risk action class "
                "requires human approval. If sandboxing is enabled for this agent, an "
                "approved command additionally runs inside the strongest exec jail (a "
                "container or bwrap) available on the host; otherwise it runs directly in "
                "the workspace."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                    "timeout": {"type": "integer", "description": "Seconds before it is killed."},
                },
                "required": ["command"],
            },
            handler=lambda args, ctx: toolbox.run_bash(
                ctx.roots,
                _str_arg(args, "command"),
                _int_arg(args, "timeout", ctx.timeout) or ctx.timeout,
                ctx.env,
                ctx.sandbox,
                ctx.cancellation_check,
            ),
            kind="exec",
        )
    )

    registry.register(
        Tool(
            name="fetch",
            description=(
                "Fetch a URL over HTTP(S). Only domains on the fetch allowlist "
                "(FETCH_ALLOWED_DOMAINS) may be reached; the response is size-capped and "
                "time-limited. Network egress is otherwise open for this fleet (see "
                "security-gates.spec.md) -- this tool exists so reaching the network never "
                "has to mean reaching for bash + curl/python3/node instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http:// or https:// URL to fetch."},
                    "timeout": {"type": "integer", "description": "Seconds before it is killed."},
                },
                "required": ["url"],
            },
            handler=lambda args, ctx: _fetch.fetch_url(
                _str_arg(args, "url"), _int_arg(args, "timeout")
            ),
            kind="read",
        )
    )

    return registry
