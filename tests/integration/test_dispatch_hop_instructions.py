"""A custom, verdict-gated role's hop message carries its own instruction, and a
pipeline step's `instructions` (with `${var}` interpolation from the run's resolved
variables) overrides it. See specs/functional/role-archetypes.spec.md ("Hop
instructions") and specs/functional/pipeline-format.spec.md ("Variables").

Before this card, `core/dispatch.py`'s hop-message builder gave any role outside
lead/implementer/reviewer/tester an empty instruction (dispatch.py:571-572,639) --
a custom verdict-gated role depended entirely on its SOUL template to know its own
marker convention, and a pipeline's declared `variables` were validated and stored on
the run record (`core/runs.py`) but never reached a hop's prompt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _pod
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import runtime_driver as _rd

SUBJECT = "docket.core.dispatch"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")


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
            "editRights": "read-only",
            "toolProfile": "read-only",
        }
    )


def _review_pipeline(instructions: str | None = None) -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="security-review",
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(
                id="review",
                role="security-reviewer",
                instructions=instructions,
                gate=_pipeline.VerdictGate(
                    pattern=r"^\s*(APPROVE|REQUEST-CHANGES)\b",
                    pass_values=["approve"],
                ),
            ),
        ],
    )


def _prep_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path, monkeypatch)
    _register_security_reviewer()
    _pod.build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
    _pod.dispatch("proj", "add", ["security-reviewer"])
    _dispatch.enqueue_task("proj", "ship the security review")


class TestCustomRoleGeneratedHopInstruction:
    def test_custom_verdict_role_gets_a_generated_marker_instruction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _prep_pod(tmp_path, monkeypatch)
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

        results = _dispatch.dispatch_pod("proj", runner=_runner, spec=_review_pipeline())

        assert results[0].status == "done", results[0].reason
        assert "APPROVE or REQUEST-CHANGES" in seen["review"]
        assert "one output line" in seen["review"]


class TestStepInstructionsOverrideAndInterpolation:
    def test_step_instructions_override_the_role_and_interpolate_a_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _prep_pod(tmp_path, monkeypatch)
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
        results = _dispatch.dispatch_pod(
            "proj", runner=_runner, spec=spec, variables={"area": "auth"}
        )

        assert results[0].status == "done", results[0].reason
        assert "Focus on auth" in seen["review"]
        assert "APPROVE or REQUEST-CHANGES" not in seen["review"]


class TestUnresolvedVariableRefusesBeforeAnyHop:
    def test_missing_variable_refuses_the_run_before_any_hop_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _prep_pod(tmp_path, monkeypatch)
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
        with pytest.raises(_dispatch.DispatchError, match="area"):
            _dispatch.dispatch_pod("proj", runner=_runner, spec=spec)

        assert calls == []
