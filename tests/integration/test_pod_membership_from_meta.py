"""Pod membership resolution reads recorded meta, never guesses from the id string.

A custom role named `security-reviewer` (registered via the archetype user-overlay) is
provisionable via `docket pod add`, but its member id (`<project>-security-reviewer`) can
make `teams/pod.py::pod_of` mis-parse the tail `reviewer` as the role, answering the wrong
(nonexistent) project and tripping the cross-pod dispatch refusal in
`hops/application/runner.py::_execute_unit`. See pod-dispatch.spec.md ("Pipeline order and participation",
requirement 3) and role-archetypes.spec.md ("Built-in archetypes and legacy fidelity",
requirement 5).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.fakes import FakeDriver
from tests.pods import build_pod

from docket.agent import ports as _rd
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.teams import pod
from docket.teams import roles as _arch

SUBJECT = "docket.teams.pod"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed(
    tmp_path: Path,
) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        yield


def _register_security_reviewer() -> None:
    _arch.add_user_archetype(
        {
            "name": "security-reviewer",
            "version": 1,
            "scope": "pod",
            "modelClass": "cheap",
            "soulTemplate": "You review ${project} for security issues.",
            "agentsTemplate": "Report APPROVE or REQUEST-CHANGES.",
            "gateContract": {"kind": "none"},
            "toolProfile": "read-only",
        },
        "proj",
    )


def _security_review_pipeline() -> _pipeline.PipelineSpec:
    """A minimal custom pipeline: Lead, then the custom verdict-gated role -- the step's own
    gate always wins over the archetype's, so the registered `gateContract: none` above is
    irrelevant here (mirrors how `default_pipeline()` gates its Reviewer step)."""
    return _pipeline.PipelineSpec(
        name="security-review",
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(
                id="review",
                role="security-reviewer",
                gate=_pipeline.VerdictGate(
                    pattern=r"^\s*(APPROVE|REQUEST-CHANGES)\b",
                    pass_values=["approve"],
                ),
            ),
        ],
    )


class TestCustomRoleEndingInRegisteredRoleName:
    def test_dispatch_reaches_done(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            _register_security_reviewer()
            build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
            _pod.add_members("proj", "security-reviewer")

            # The provisioned member's own meta is what makes pod_of resolvable -- confirm the
            # fixture actually reproduces the trigger's precondition before dispatching.
            assert pod.pod_of("proj-security-reviewer") == "proj"

            _queue.enqueue_task_once("proj", "ship the security review", channel="cli")

            driver = FakeDriver()

            def _runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                result = driver(agent_id, session_key, message, timeout, env)
                if agent_id.endswith("security-reviewer"):
                    return _rd.TurnResult(True, "APPROVE - clean", result.cost_usd, {"output": "x"})
                return result

            results = _sweep.dispatch_pod("proj", runner=_runner, spec=_security_review_pipeline())

            assert len(results) == 1
            assert results[0].status == "done", results[0].reason
            assert [h.role for h in results[0].hops] == ["lead", "security-reviewer"]

    def test_a_genuinely_cross_pod_member_id_is_still_refused(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
            build_pod("other", pod.DEFAULT_POD_ROLES, codebase="/src/other")

            assert pod.pod_of("other-lead") == "other"
            assert pod.pod_of("other-lead") != "proj"
