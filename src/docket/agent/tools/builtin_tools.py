from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from typing import Any

from docket.agent import skills as _skills
from docket.agent.tools.builtins import toolbox
from docket.agent.tools.builtins.toolbox import ToolOutcome as ToolOutcome
from docket.agent.tools.registry import (
    _CONSULT_TOOL,
    Tool,
    ToolContext,
    ToolRegistry,
    _str_arg,
    screen_tool_result,
)
from docket.kernel.home import current_home
from docket.platform import fetch as _fetch
from docket.tasks.application import consult as _consult


def _int_arg(args: dict[str, Any], name: str, default: int = 0) -> int:
    value = args.get(name, default)
    return int(value) if isinstance(value, int | float | str) and str(value).isdigit() else default


def _tag_bash_process_events(
    on_process: Callable[[str, dict[str, Any]], None] | None,
) -> Callable[[str, dict[str, Any]], None] | None:
    """Tag a process-lifecycle event with the tool that spawned it. No ``callId``: this
    handler lambda receives only ``(args, ctx)``, with no call id in scope, unlike
    ``dispatch_tool``."""
    if on_process is None:
        return None

    def _tagged(kind: str, data: dict[str, Any]) -> None:
        on_process(kind, {**data, "tool": "bash"})

    return _tagged


def _skill_read(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    """Handler for the ``skill`` built-in: resolve ``name`` and read ``path`` (default
    ``SKILL.md``) from within that skill's own directory. An unknown name is a failed call
    naming the known names, never a raise."""

    name = _str_arg(args, "name")
    discovered = _skills.discover_skills(ctx.project, ctx.roots[0] if ctx.roots else None)
    skill = discovered.get(name)
    if skill is None:
        known = ", ".join(sorted(discovered)) or "(none)"
        return ToolOutcome(False, error=f"unknown skill {name!r}; known skills: {known}")
    skill_path = _str_arg(args, "path", "SKILL.md")
    if skill.view is not None:
        parts = skill_path.split("/")
        if skill_path.startswith("/") or any(p in ("", ".", "..") for p in parts):
            outcome = ToolOutcome(False, error=f"not a file: {skill_path}", refusal="path_escape")
        else:
            text = skill.view.read_text(f"{_skills.CODEBASE_SKILLS_REL}/{name}/{skill_path}")
            outcome = (
                ToolOutcome(False, error=f"not a file: {skill_path}")
                if text is None
                else toolbox.text_outcome(text)
            )
    else:
        outcome = toolbox.read_file((skill.directory,), skill_path)
    # A skill body is repository prose, the same trust class as a fetched page or an MCP
    # result: screened as untrusted input before the model reads it.
    return screen_tool_result(
        ctx.role,
        outcome,
        source=f"skill {name!r}",
        detail=f"skill={name!r}",
        blocked_action="skills.body_blocked",
        warn_action="skills.body_warn",
        project=ctx.project,
    )


def _skill_tool() -> Tool:
    """The `skill` built-in: a discovered skill's body or one of its files, read on demand."""
    return Tool(
        name="skill",
        description=(
            "Read a discovered skill's full instructions (SKILL.md, or a file inside its "
            "own directory named by path). See the '# Skills' section of the system "
            "prompt for the names and one-line descriptions available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name, e.g. 'security-review'.",
                },
                "path": {
                    "type": "string",
                    "description": "File inside the skill's own directory; default SKILL.md.",
                },
            },
            "required": ["name"],
        },
        handler=_skill_read,
        kind="read",
    )


def _consult_handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    """Handler for the ``consult`` built-in (``ConsultUnavailable`` propagates to dispatch)."""
    outcome = _consult.run(args, ctx)
    return ToolOutcome(outcome.ok, outcome.content, outcome.error)


def _consult_tool() -> Tool:
    """The `consult` built-in: ask the operator a clarification or decision question."""
    option = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "label": {"type": "string"},
            "description": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "estimatedTokens": {"type": "integer"},
        },
        "required": ["id", "label", "description"],
    }
    return Tool(
        name=_CONSULT_TOOL,
        description=(
            "Ask the operator a question when the task cannot be decided from the "
            "repository alone. Give at least two options and your recommendation. The "
            "result is the operator's chosen optionId and content, or 'no answer; decide "
            "yourself'. The number of consultations per task is capped; use it sparingly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["clarification", "decision"]},
                "message": {"type": "string", "description": "The question, plainly."},
                "options": {"type": "array", "items": option, "minItems": 2},
                "recommendation": {
                    "type": "object",
                    "properties": {
                        "optionId": {"type": "string"},
                        "rationale": {"type": "string"},
                        "evidenceRefs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["optionId", "rationale"],
                },
            },
            "required": ["kind", "message", "options"],
        },
        handler=_consult_handler,
        kind="read",
    )


def _fetch_tool(fetch_url: Any) -> Tool:
    """The `fetch` built-in over *fetch_url*, the edges adapter the registry hands in."""

    def _fetch_handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        url = _str_arg(args, "url")
        outcome: ToolOutcome = fetch_url(url, _int_arg(args, "timeout"))
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        return screen_tool_result(
            ctx.role,
            outcome,
            source=f"host {host!r}",
            detail=f"host={host!r} url={url!r}",
            blocked_action="fetch.result_blocked",
            warn_action="fetch.result_warn",
            project=ctx.project,
        )

    return Tool(
        name="fetch",
        description=(
            "Fetch a URL over HTTP(S). Only domains on the fetch allowlist "
            "(FETCH_ALLOWED_DOMAINS) may be reached; the response is size-capped, time-limited "
            "and truncated like any tool result when long. Network egress is otherwise open for "
            "this fleet (see "
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
        handler=_fetch_handler,
        kind="read",
    )


def _register_all(registry: ToolRegistry, *tools: Tool) -> None:
    for tool in tools:
        registry.register(tool)


def _bash_handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    return toolbox.run_bash(
        ctx.roots,
        _str_arg(args, "command"),
        _int_arg(args, "timeout", ctx.timeout) or ctx.timeout,
        ctx.env,
        ctx.sandbox,
        ctx.cancellation_check,
        _tag_bash_process_events(ctx.on_process),
        ctx.network,
        ctx.cache_dir,
        ctx.read_only,
    )


_READ_DESCRIPTION = (
    "Read a text file as numbered lines, 400 at a time. Paths are relative to the workspace. "
    "For a larger file pass offset (1-indexed line) and limit, or follow the footer's offset "
    "to continue. Copy text from the window without the numbers when editing."
)
_GLOB_DESCRIPTION = (
    "List files matching a glob pattern, as paths relative to the workspace, sorted. Vendored and "
    "generated directories (node_modules, .git, .venv, build output) are skipped. Search with grep "
    "or a narrow pattern before listing a whole tree."
)
_GREP_DESCRIPTION = (
    "Search file contents for a regular expression. Hits print as paths relative to the "
    "workspace, sorted by path; vendored and generated directories are skipped. Search for a "
    "symbol here before listing files with glob."
)


def _offered_fetch() -> list[Tool]:
    """Offer `fetch` only while `FETCH_ALLOWED_DOMAINS` is non-empty (agent-loop requirement 83)."""

    return [_fetch_tool(_fetch.fetch_url)] if current_home().fetch_allowed_domains else []


def builtin_registry() -> ToolRegistry:
    """The default tool set: read, write, edit, glob, grep, bash, skill, consult, and fetch (only
    with an allowlist). Handlers are imported here, not at module scope, so this module stays
    importable without the filesystem/subprocess layer. Core reaches out to edges for I/O here.
    """

    registry = ToolRegistry()

    registry.register(
        Tool(
            name="read",
            description=_READ_DESCRIPTION,
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
            description=_GLOB_DESCRIPTION,
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
            description=_GREP_DESCRIPTION,
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
                "approved command additionally runs inside the strongest exec jail (landlock, "
                "seatbelt or docker) available on the host; otherwise it runs directly in "
                "the workspace. Create or change files with `write`/`edit`, not `cat >`, "
                "heredocs or `sed -i`; inspect with `read`/`grep`/`glob`; use `bash` to run things."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                    "timeout": {"type": "integer", "description": "Seconds before it is killed."},
                },
                "required": ["command"],
            },
            handler=_bash_handler,
            kind="exec",
        )
    )
    _register_all(registry, _skill_tool(), _consult_tool(), *_offered_fetch())

    return registry
