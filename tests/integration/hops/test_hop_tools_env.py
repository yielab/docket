"""A step's ``tools`` and ``maxToolCalls`` reach the turn as the driver's hop coordinates
(pipeline-format.spec.md "Steps" requirement 11, agent-loop.spec.md requirements 103 and 104).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support import pods as _support_pods
from tests.support.pods import seed_lean_pod as _seed_lean_pod

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import TaskRecord

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.hops.application.compose"

_PROJECT = "myapp"


def _envs(*steps: _step.Step) -> dict[str, dict[str, str]]:
    """The environment each step's role received, by role."""
    seen: dict[str, dict[str, str]] = {}

    def _runner(
        agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
    ) -> _rd.TurnResult:
        seen[agent_id.rsplit("-", 1)[-1]] = dict(env or {})
        return _rd.TurnResult(True, "done", 0.0, {})

    spec = _pipeline.PipelineSpec(name="solo", steps=list(steps))
    task = TaskRecord(id="task-1", description="x", status=Status.running)
    _executor.dispatch_task(_PROJECT, task, runner=_runner, spec=spec)
    return seen


def test_a_step_with_tools_and_a_cap_hands_both_to_the_turn(pod_home: Path) -> None:
    _seed_lean_pod(_PROJECT)

    seen = _envs(_step.Step(id="lead", role="lead", tools=["read", "grep"], max_tool_calls=3))

    env = seen["lead"]
    assert json.loads(env[_rd.DOCKET_HOP_TOOLS]) == ["read", "grep"]
    assert env[_rd.DOCKET_HOP_MAX_TOOL_CALLS] == "3"


def test_a_step_with_neither_hands_the_turn_nothing(pod_home: Path) -> None:
    _seed_lean_pod(_PROJECT)

    seen = _envs(_step.Step(id="lead", role="lead"))

    assert _rd.DOCKET_HOP_TOOLS not in seen["lead"]
    assert _rd.DOCKET_HOP_MAX_TOOL_CALLS not in seen["lead"]


def test_every_step_hands_the_turn_its_own_id(pod_home: Path) -> None:
    _seed_lean_pod(_PROJECT)

    seen = _envs(_step.Step(id="intake", role="lead"))

    assert seen["lead"][_rd.DOCKET_HOP_STEP] == "intake"
