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
5. **Execute**, catching everything, so a broken handler returns a result the
   loop can feed back rather than unwinding the turn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docket.core.llm import ToolCall, ToolCallArgumentsError, ToolSpec
from docket.core.security import classify_command
from docket.edges.adapters.toolbox import ToolOutcome

ToolKind = Literal["read", "write", "exec"]
Decision = Literal["allow", "ask", "deny"]


@dataclass
class ToolContext:
    """Everything a tool call needs to know about who is making it.

    ``roots`` is the containment boundary: every path argument must resolve
    inside one of these, and the first is the working directory for shell
    commands. An empty ``roots`` makes every path-taking tool fail — deliberate,
    since defaulting to the whole filesystem is the failure this guards.
    """

    agent_id: str = ""
    session_key: str = ""
    roots: tuple[Path, ...] = ()
    timeout: int = 120
    env: dict[str, str] = field(default_factory=dict)


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


# ── the gate ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolVerdict:
    """The gate's answer for one call."""

    decision: Decision
    reason: str = ""


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
    their call sites, so "what gates a tool call" has a single answer.
    """
    if tool.kind == "exec":
        command = str(args.get("command") or "")
        verdict = classify_command(command)
        if verdict.action != "allow":
            return ToolVerdict(
                "ask" if verdict.action == "ask" else "deny",
                verdict.reason,
            )
    return ToolVerdict("allow")


# ── the chokepoint ────────────────────────────────────────────────────────────


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
    if verdict.decision != "allow":
        result.error = verdict.reason
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
    """The default tool set: read, write, edit, glob, grep, bash.

    Handlers are imported here rather than at module scope so ``core/tools.py``
    stays importable without dragging in the filesystem/subprocess layer, and
    so the dependency direction reads as "core reaches out to edges for I/O"
    at exactly one point.
    """
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
                "requires human approval."
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
            ),
            kind="exec",
        )
    )

    return registry
