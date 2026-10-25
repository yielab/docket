"""The ``verdict`` tool: how a verdict-gated hop records its verdict and finishes.

A hop whose step carries a verdict gate is offered one tool, ``verdict``, whose single ``value``
parameter is an enum of the gate's allowed values. A successful call ends the turn and its result
is the recorded value, so the hop's output closes with exactly that line and the ordinary verdict
parser reads it; a hop that writes the marker in text instead is read as before.
"""

from __future__ import annotations

import json
from typing import Any

from docket.agent.tools.registry import Tool, ToolContext
from docket.kernel.tool_outcome import ToolOutcome

VERDICT_TOOL = "verdict"
_DESCRIPTION = "Record your verdict and finish. Call this once, as your last action."


def verdict_tool(values: tuple[str, ...], case_sensitive: bool = False) -> Tool:
    """The ``verdict`` tool for a gate accepting *values*; a value is matched ignoring case
    unless *case_sensitive*, and recorded as the enum spells it."""

    def _record(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        given = str(args.get("value", "")).strip()
        for value in values:
            if given == value or (not case_sensitive and given.lower() == value.lower()):
                return ToolOutcome(True, content=value)
        return ToolOutcome(False, error=f"value must be one of: {', '.join(values)}")

    return Tool(
        name=VERDICT_TOOL,
        description=_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "enum": list(values),
                    "description": "Your verdict. Write your reasons in the same message, above this call.",
                }
            },
            "required": ["value"],
        },
        handler=_record,
        kind="read",
        ends_turn=True,
    )


def encode_values(values: tuple[str, ...], case_sensitive: bool) -> str:
    """The hop environment coordinate carrying a gate's allowed values to the driver."""
    return json.dumps({"values": list(values), "caseSensitive": case_sensitive})


def parse_values(raw: str | None) -> tuple[tuple[str, ...], bool] | None:
    """The values and case rule *raw* names, or ``None`` when it is absent or unusable."""
    try:
        data = json.loads(raw or "")
    except ValueError:
        return None
    values = data.get("values") if isinstance(data, dict) else None
    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
        return None
    return tuple(values), bool(data.get("caseSensitive"))
