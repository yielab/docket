"""A custom, verdict-gated role's hop message carries its own instruction, and a
pipeline step's `instructions` (with `${var}` interpolation from the run's resolved
variables) overrides it. See specs/functional/role-archetypes.spec.md ("Hop
instructions") and specs/functional/pipeline-format.spec.md ("Variables").

Before this card, `core/dispatch.py`'s hop-message builder gave any role outside
lead/implementer/reviewer/tester an empty instruction (dispatch.py:571-572,639) --
a custom verdict-gated role depended entirely on its SOUL template to know its own
marker convention, and a pipeline's declared `variables` were validated and stored on
the run record (`tasks/application/runs.py`) but never reached a hop's prompt.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.agent import ports as _rd
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod_members as _pod_members
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import queue as _queue
from docket.tasks.domain import task as _task
from docket.teams import pod
from docket.teams import roles as _arch

SUBJECT = "docket.tasks.application.queue"


def _register_security_reviewer() -> None:
    _arch.add_user_archetype(
        {
            "name": "security-reviewer",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "You review ${project} for security issues.",
            "agentsTemplate": "Report APPROVE or REQUEST-CHANGES.",
            "gateContract": {"kind": "verdict", "regexes": ["APPROVE", "REQUEST-CHANGES"]},
            "toolProfile": "read-only",
        },
        "proj",
    )


def _review_pipeline(instructions: str | None = None) -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="security-review",
        steps=[
            _step.Step(id="lead", role="lead"),
            _step.Step(
                id="review",
                role="security-reviewer",
                instructions=instructions,
                gate=_gates.VerdictGate(
                    pattern=r"^\s*(APPROVE|REQUEST-CHANGES)\b",
                    pass_values=["approve"],
                ),
            ),
        ],
    )


@contextmanager
def _prep_pod(
    tmp_path: Path,
) -> Iterator[None]:
    with _seed(tmp_path):
        _register_security_reviewer()
        build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
        _pod_members.add_members("proj", "security-reviewer")
        _queue.enqueue_task_once("proj", "ship the security review", channel="cli")
        yield


class TestCustomRoleGeneratedHopInstruction:
    def test_custom_verdict_role_gets_a_generated_marker_instruction(self, tmp_path: Path) -> None:
        with _prep_pod(tmp_path):
            seen: dict[str, str] = {}
            driver = FakeDriver()

            def _runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                if agent_id.endswith("security-reviewer"):
                    seen["review"] = message
                    return _rd.TurnResult(True, "APPROVE - clean", 0.0, {"output": "x"})
                return driver(agent_id, session_key, message, timeout, env)

            results = _sweep.dispatch_pod("proj", runner=_runner, spec=_review_pipeline())

            assert results[0].status == "done", results[0].reason
            assert "exactly `APPROVE` or `REQUEST-CHANGES`" in seen["review"]
            assert "LAST line of your FINAL message" in seen["review"]


class TestStepInstructionsOverrideAndInterpolation:
    def test_step_instructions_override_the_role_and_interpolate_a_variable(
        self, tmp_path: Path
    ) -> None:
        with _prep_pod(tmp_path):
            seen: dict[str, str] = {}
            driver = FakeDriver()

            def _runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                if agent_id.endswith("security-reviewer"):
                    seen["review"] = message
                    return _rd.TurnResult(True, "APPROVE - clean", 0.0, {"output": "x"})
                return driver(agent_id, session_key, message, timeout, env)

            spec = _review_pipeline(instructions="Focus on ${area}")
            results = _sweep.dispatch_pod(
                "proj", runner=_runner, spec=spec, variables={"area": "auth"}
            )

            assert results[0].status == "done", results[0].reason
            assert "Focus on auth" in seen["review"]
            assert "APPROVE or REQUEST-CHANGES" not in seen["review"]


class TestUnresolvedVariableRefusesBeforeAnyHop:
    def test_missing_variable_refuses_the_run_before_any_hop_runs(self, tmp_path: Path) -> None:
        with _prep_pod(tmp_path):
            calls: list[str] = []

            def _runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                calls.append(agent_id)
                return _rd.TurnResult(True, "APPROVE", 0.0, {"output": "x"})

            spec = _review_pipeline(instructions="Focus on ${area}")
            with pytest.raises(_task.DispatchError, match="area"):
                _sweep.dispatch_pod("proj", runner=_runner, spec=spec)

            assert calls == []
