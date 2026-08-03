"""The gated tool registry (ROADMAP Phase 19 P19-2 / D-19).

**One chokepoint.** Every tool call an agent makes passes through
``dispatch_tool`` and nowhere else. That is the entire point of this module:
docket's governance stack — the policy engine, the approval store, the
high-risk classifier, the audit log — is only worth anything if there is
exactly one place a tool can be executed from. A second path is not a
convenience, it is a hole.

Layering. This module *decides*; ``edges/adapters/toolbox.py`` *acts*. The
handlers there consult no policy and know nothing about approvals, so nothing
can execute without first having come through here. The split also keeps the
filesystem and subprocess work out of ``core/``.

Order of operations in ``dispatch_tool``, and why each step precedes the next:

1. **Resolve the tool.** An unknown name is refused, not ignored — a model
   hallucinating a tool must get a refusal it can read, and the attempt is
   worth recording.
2. **Parse the arguments.** Unparseable arguments are a *denial*, never an
   empty dict, because arguments are what the gate inspects.
3. **Validate required arguments**, so a half-specified call fails before any
   side effect rather than partway through one.
4. **Gate.** ``evaluate_tool_call`` is the single decision point. P19-3 adds
   the ``pre_tool_call`` policy hook here — the hook docket has shipped
   templates for since Phase 11 and never once evaluated.
5. **Route ``ask``.** A gate verdict of ``ask`` blocks the call on the real
   approval store (``core/approval.py``'s ``wait_for_approval``) rather than
   just reporting the requirement — the daemon is gone, so nothing else will
   ever resolve this call if docket does not wait for it here.
6. **Execute**, catching everything, so a broken handler returns a result the
   loop can feed back rather than unwinding the turn.

Every gate/approval decision that is not a bare ``allow`` is audited
(``core/audit.py``'s ``audit_log``) from this module, not from callers —
the same "the chokepoint records, so nobody downstream has to remember to"
reasoning that makes ``dispatch_tool`` the single execution path.
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


@dataclass
class ToolContext:
    """Everything a tool call needs to know about who is making it.

    ``roots`` is the containment boundary: every path argument must resolve
    inside one of these, and the first is the working directory for shell
    commands. An empty ``roots`` makes every path-taking tool fail — deliberate,
    since defaulting to the whole filesystem is the failure this guards.

    ``role``/``project`` (P19-3) feed ``policy.policy_eval_detail``'s
    ``applies_to`` matching and ``approval.approval_create``'s record. Both
    default to ``""`` rather than being required: every shipped policy
    template uses ``applies_to: ["*"]``, which matches an empty role, and an
    approval record with no project still needs to be created and shown
    somewhere — ``dispatch_tool`` falls back to ``"operator"`` for that case
    rather than refusing to gate at all.

    ``sandbox`` (P19-9) is a **mechanism** choice, not a gate decision — it is
    consulted only by the ``bash`` tool's handler, after ``evaluate_tool_call``
    has already allowed the call, and only changes what an already-permitted
    command can reach while it runs, never whether it runs. Defaults to
    ``"off"`` (today's plain, unsandboxed exec, unchanged) rather than
    ``"auto"``: a docker/bwrap jail is real, opt-in hardening, not something a
    bare ``ToolContext()`` should silently start relying on — see
    ``edges.adapters.toolbox.run_bash`` and `specs/functional/security-gates.spec.md`
    for the on-by-default-vs-opt-in rationale.
    """

    agent_id: str = ""
    session_key: str = ""
    roots: tuple[Path, ...] = ()
    timeout: int = 120
    env: dict[str, str] = field(default_factory=dict)
    role: str = ""
    project: str = ""
    sandbox: SandboxMode = "off"


@dataclass
class ToolResult:
    """Outcome of one call: what was decided, and what happened if it ran.

    ``executed`` is separate from ``ok`` on purpose. A denied call and a call
    that ran and failed are different events — the first is a guardrail doing
    its job, the second is a task problem — and collapsing them would make the
    audit log unable to tell them apart.
    """

    ok: bool
    content: str = ""
    error: str = ""
    decision: Decision = "allow"
    reason: str = ""
    tool: str = ""
    call_id: str = ""
    executed: bool = False

    @property
    def denied(self) -> bool:
        return self.decision == "deny"

    @property
    def needs_approval(self) -> bool:
        """True when a human has to answer before this call may run.

        P19-2 stops here and reports the requirement. P19-3 routes it to
        ``core/approval.py``, which fails closed on timeout.
        """
        return self.decision == "ask"

    def as_tool_output(self) -> str:
        """The text fed back to the model as this call's result.

        A refusal is reported *to the model*, in words, rather than being
        dropped: an agent that receives silence retries the same call, while an
        agent told "denied, because X" can choose a different approach.
        """
        if self.decision == "deny":
            return f"REFUSED: {self.reason}"
        if self.decision == "ask":
            return f"AWAITING APPROVAL: {self.reason}"
        if not self.ok:
            return f"ERROR: {self.error}\n{self.content}".strip()
        return self.content


@dataclass(frozen=True)
class Tool:
    """One callable tool: its schema for the model, its handler for docket.

    ``kind`` drives gating, not behaviour: ``exec`` tools go through the
    argument-aware command classifier, ``write`` tools are recorded as
    mutating, ``read`` tools are the cheap case.
    """

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
    """The set of tools one agent may call.

    Per-agent rather than global so a role can be given a narrower set — a
    Reviewer with no ``write`` tool cannot edit code by accident, which is a
    stronger guarantee than instructing it not to.
    """

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

    **Contract — pinned by ``tests/python/test_p19_3_pre_tool_call.py`` and load
    bearing for every shipped policy template, not an implementation detail:**

        "<name> <key>=<json-value> <key>=<json-value> ..."

    Keys appear in ``args``' own iteration order (the order the model's JSON
    arguments decoded in); each value is rendered via ``json.dumps`` so a
    string is quoted, a number/bool/``null`` renders as its JSON literal, and
    a nested object/list renders inline. A call with no arguments renders as
    just ``name``. No trailing whitespace, no line breaks inserted.

    Why this shape: every shipped policy pattern (``rm\\s+-[rf]``,
    ``git\\s+push\\s+.*\\bmain\\b``) was written to read like the raw shell
    command it matches, and a tool's most policy-relevant argument is usually
    that exact string (``bash``'s ``command``, a path). Putting the tool name
    first and the arguments after, verbatim and quoted, keeps a command-shaped
    regex matching a rendered call the same way it would match the bare
    command. It is *not* symmetric — a pattern written assuming an argument's
    text appears *before* the verb that acts on it (e.g. a path before the
    word "write") will not match this render; see block-destructive.json's
    changelog note for the two patterns P19-3 found and fixed for exactly
    that reason.
    """
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
    """The gate's answer for one call.

    ``policy_action``/``policy_id`` carry the *raw* ``pre_tool_call`` hit
    (P19-3), independent of which check ended up deciding ``decision`` — so a
    caller can tell a policy actually fired a ``warn``/``redact`` even on a
    call whose overall decision is ``allow`` (e.g. the command classifier
    already said allow, but a policy still wants a record). ``policy_action``
    is ``""`` when no policy file matched at all, and ``"allow"`` when one
    matched but explicitly allowed.
    """

    decision: Decision
    reason: str = ""
    policy_id: str = ""
    policy_action: str = ""


def evaluate_tool_call(tool: Tool, args: dict[str, Any], ctx: ToolContext) -> ToolVerdict:
    """Decide whether this call may proceed. **The** decision point.

    P19-2 implements the exec gate: a shell command is classified by
    ``core/security.classify_command``, which reads the whole command line
    including every segment behind a ``;``/``&&``/pipe. This is the
    argument-aware enforcement the daemon's binary-path allowlist structurally
    could not do — ``git`` is allowlisted, ``git push origin production`` is a
    production deploy, and only a classifier that sees the arguments can tell
    them apart.

    P19-3 adds the ``pre_tool_call`` policy hook to this function, so a
    deny/require_approval rule from a shipped template applies to every tool,
    not just ``bash``. Both checks land in this one function rather than at
    their call sites, so "what gates a tool call" has a single answer. The two
    gates can disagree — one call is combined via most-restrictive-wins
    (``_DECISION_RANK``, the same philosophy as ``core/policy.py``'s own
    ``_RANK``): deny beats ask beats allow.

    Pure decision function — it never audits or traces. That is
    ``dispatch_tool``'s job (matching ``core/dispatch.py``'s own
    ``policy_eval_detail`` callers, which decide what to do with a
    :class:`~docket.core.policy.PolicyHit` themselves rather than having the
    evaluator emit records).
    """
    command_decision: Decision = "allow"
    command_reason = ""
    if tool.kind == "exec":
        command = str(args.get("command") or "")
        cmd_verdict = classify_command(command)
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


def _audit_tool_decision(action: str, tool_name: str, ctx: ToolContext, detail: str) -> None:
    """Write one audit entry for a non-``allow`` (or ``warn``/``redact``) gate
    decision. Centralized here so every gated tool call is recorded exactly
    once, regardless of which check (command classifier or policy engine)
    produced it — the arguments are rendered and passed through
    ``core.trace.redact`` first, since a tool call's arguments can carry a
    secret (a token in a ``write`` call, a credential in a ``bash`` command).
    """
    audit_log(
        action,
        f"tool={tool_name} agent={ctx.agent_id or '?'} role={ctx.role or '?'} "
        f"project={ctx.project or '?'}: {_redact(detail)}",
    )


def dispatch_tool(call: ToolCall, ctx: ToolContext, registry: ToolRegistry) -> ToolResult:
    """Run one tool call, or refuse it. The only path to tool execution."""
    result = ToolResult(ok=False, tool=call.name, call_id=call.id)

    tool = registry.get(call.name)
    if tool is None:
        result.decision = "deny"
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
        result.reason = str(ex)
        result.error = result.reason
        return result

    missing = [name for name in tool.required_args if name not in args]
    if missing:
        result.decision = "deny"
        result.reason = f"missing required argument(s): {', '.join(missing)}"
        result.error = result.reason
        return result

    verdict = evaluate_tool_call(tool, args, ctx)
    result.decision = verdict.decision
    result.reason = verdict.reason

    if verdict.policy_action in ("warn", "redact"):
        # Allowed to proceed, but a policy still flagged it -- silently
        # letting this through would waste the policy (P19-3 requirement).
        _audit_tool_decision(
            f"tool.{verdict.policy_action}",
            tool.name,
            ctx,
            f"policy={verdict.policy_id!r} call={render_tool_call(tool.name, args)}",
        )

    if verdict.decision == "deny":
        _audit_tool_decision(
            "tool.deny",
            tool.name,
            ctx,
            f"{verdict.reason} call={render_tool_call(tool.name, args)}",
        )
        result.error = verdict.reason
        return result

    if verdict.decision == "ask":
        _audit_tool_decision(
            "tool.ask", tool.name, ctx, f"{verdict.reason} call={render_tool_call(tool.name, args)}"
        )
        token = _approval.approval_create(
            ctx.project or "operator",
            ctx.role or "tool",
            f"tool call {tool.name!r}: {verdict.reason}"[:1000],
            context={"tool": tool.name, "callId": call.id},
        )
        wait_outcome = _approval.wait_for_approval(token)
        if wait_outcome.state != "granted":
            result.decision = "deny"
            result.reason = (
                f"approval {'timed out and was denied' if wait_outcome.timed_out else 'denied'} "
                f"(token={token})"
            )
            result.error = result.reason
            return result
        # Granted: the call is now allowed, and falls through to execute.
        result.decision = "allow"
        result.reason = f"approved (token={token})"

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
    """The default tool set: read, write, edit, glob, grep, bash.

    Handlers are imported here rather than at module scope so ``core/tools.py``
    stays importable without dragging in the filesystem/subprocess layer, and
    so the dependency direction reads as "core reaches out to edges for I/O"
    at exactly one point.
    """
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
