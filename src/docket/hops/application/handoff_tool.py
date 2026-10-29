"""The ``handoff`` tool: how a hop records its outcome and finishes.

A hop whose prompt declares ``output: handoff/v1`` (and every verdict-gated hop) is offered one
tool, ``handoff``, shaped by the published schema (``kernel/handoff.py``: ``summary``,
``filesChanged``, ``verdict``, ``assumptions``, ``questions``). On a gated step ``verdict`` is
required and an enum of the gate's allowed values. A successful call ends the turn; the turn's
closing arguments reach the hop's record (``tasks/application/record.py``). A hop that never calls
it is read from its reply text as before.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.kernel.handoff import (
    HANDOFF_DESCRIPTION,
    HANDOFF_TOOL,
    HANDOFF_V1_PARAMETERS,
    parse_handoff_call,
)
from docket.kernel.tool_outcome import ToolOutcome


def handoff_tool(values: tuple[str, ...] = (), case_sensitive: bool = False) -> Tool:
    """The ``handoff`` tool; *values*, a gate's allowed verdicts, make ``verdict`` required. A
    value is matched ignoring case unless *case_sensitive*, and recorded as the enum spells it."""

    def _record(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        call = parse_handoff_call(args)
        if call is None:
            return ToolOutcome(False, error="arguments do not match the handoff schema")
        verdict = call.verdict.strip() if call.verdict is not None else ""
        if values:
            for value in values:
                if verdict == value or (not case_sensitive and verdict.lower() == value.lower()):
                    verdict = value
                    break
            else:
                return ToolOutcome(False, error=f"verdict must be one of: {', '.join(values)}")
        return ToolOutcome(True, content=verdict or call.summary)

    parameters = copy.deepcopy(HANDOFF_V1_PARAMETERS)
    if values:
        parameters["properties"]["verdict"] = {
            "type": "string",
            "enum": list(values),
            "description": "Your verdict. Write your reasons in the summary.",
        }
        parameters["required"] = ["verdict"]
    return Tool(
        name=HANDOFF_TOOL,
        description=HANDOFF_DESCRIPTION,
        parameters=parameters,
        handler=_record,
        kind="read",
        ends_turn=True,
    )


def register_closing_tool(
    registry: ToolRegistry, gate: tuple[tuple[str, ...], bool] | None, offer: str | None
) -> None:
    """Offer the turn the ``handoff`` tool: gated when it has a verdict *gate*, plain when its
    environment carries the *offer* (``DOCKET_HANDOFF``), else not at all."""
    if gate is not None or offer == "1":
        registry.register(handoff_tool(*(gate or ())))


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
