"""The two built-ins that read and stop a background ``bash`` command (agent-loop 99-100)."""

from __future__ import annotations

from typing import Any

from docket.agent.tools.builtins import background
from docket.agent.tools.registry import Tool, ToolContext
from docket.kernel.home import current_home
from docket.kernel.tool_outcome import ToolOutcome

COMPACT_DESCRIPTIONS = {
    "process_output": "Read a background command's log from a byte offset; says whether it is alive.",
    "process_stop": "Kill a background command's process group.",
}


def _pgid(args: dict[str, Any]) -> int | None:
    value = args.get("pgid")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _offset(args: dict[str, Any]) -> int:
    value = args.get("offset", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _process_output(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    pgid = _pgid(args)
    if pgid is None:
        return ToolOutcome(False, error="pgid must be the integer `bash` returned")
    return background.output(
        ctx.processes, pgid, _offset(args), current_home().tool_max_output_chars, ctx.on_process
    )


def _process_stop(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    pgid = _pgid(args)
    if pgid is None:
        return ToolOutcome(False, error="pgid must be the integer `bash` returned")
    return background.stop(ctx.processes, pgid, ctx.on_process)


def process_output_tool() -> Tool:
    return Tool(
        name="process_output",
        description=(
            "Read the log of a command started with `bash` and `background: true`, from a byte "
            "offset (default 0). The result says `alive: true|false` (with `exit: <code>` once it "
            "ended) and the `offset:` to continue from."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pgid": {"type": "integer", "description": "The pgid `bash` returned."},
                "offset": {"type": "integer", "description": "Byte offset to read from."},
            },
            "required": ["pgid"],
        },
        handler=_process_output,
        kind="read",
    )


def process_stop_tool() -> Tool:
    return Tool(
        name="process_stop",
        description=(
            "Kill a command started with `bash` and `background: true`, with everything it "
            "started. Background commands are also stopped when your turn ends."
        ),
        parameters={
            "type": "object",
            "properties": {"pgid": {"type": "integer", "description": "The pgid `bash` returned."}},
            "required": ["pgid"],
        },
        handler=_process_stop,
        kind="write",
    )
