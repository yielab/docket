"""The ``verify`` tool: the step's own verify command, run on demand by the hop that must pass it.

Dispatch decides the plan (command, directory, timeout) when it composes the hop and hands it to
the driver as one env coordinate; the driver registers the tool from it. The tool takes no
arguments and runs the gate's own runner, so what the model sees is what the gate will see. It is
``pregranted``: the pipeline already authorises the command, so the command classifier is skipped,
but the call still passes ``dispatch_tool``, the policies and the trace.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from docket.agent.tools.registry import Tool, ToolContext
from docket.hops.gates.post_hop import (
    _gate_cwd,
    gate_timeout,
    run_verify_command,
    step_verify_command,
)
from docket.kernel import text as _text
from docket.kernel.tool_outcome import VERDICT_TAIL, ToolOutcome, bounded_text
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application.record import UnitContext

VERIFY_TOOL = "verify"


@dataclass(frozen=True)
class VerifyPlan:
    """What the ``verify`` tool runs: the command, where, and for how long."""

    command: str
    cwd: str
    timeout: int


def plan_for_hop(ctx: UnitContext, node: _orch.PlannedUnit, member_id: str) -> VerifyPlan | None:
    """The plan for *node*'s hop, or ``None`` when its step has no verify command."""
    command = step_verify_command(node.gate, member_id)
    if not command or not isinstance(node.gate, _gates.MechanicalGate):
        return None
    return VerifyPlan(command, _gate_cwd(ctx, member_id), gate_timeout(ctx, node.gate))


def plan_env_value(plan: VerifyPlan) -> str:
    """*plan* as the text of its env coordinate."""
    return json.dumps(asdict(plan))


def parse_plan(raw: str | None) -> VerifyPlan | None:
    """The plan in an env coordinate; ``None`` for absent or malformed text (no tool, fail closed)."""
    if not raw:
        return None
    try:
        data: Any = json.loads(raw)
        plan = VerifyPlan(str(data["command"]), str(data["cwd"]), int(data["timeout"]))
    except (ValueError, KeyError, TypeError):
        return None
    return plan if plan.command.strip() and plan.timeout > 0 else None


def verify_tool(plan: VerifyPlan, project: str) -> Tool:
    """The ``verify`` tool for *plan*, run in *project*'s envelope."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        run = run_verify_command(project, plan.command, plan.cwd, plan.timeout)
        status = "none" if run.code is None else str(run.code)
        output = bounded_text(_text.normalize_output(run.redacted.strip()), VERDICT_TAIL)
        return ToolOutcome(True, content=f"exit {status}\n{output}" if output else f"exit {status}")

    return Tool(
        name=VERIFY_TOOL,
        description=(
            "Run this step's verify command, the check that decides whether your work is "
            "accepted, and report `exit N` and its output. Takes no arguments. Run it before you "
            "finish and fix what it reports."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_handler,
        kind="exec",
        pregranted=True,
    )
