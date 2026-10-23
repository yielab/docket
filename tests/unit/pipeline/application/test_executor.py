"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``_execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from docket.agent import ports as _rd
from docket.kernel.home import Home, current_home, use_home
from docket.pipeline.application import executor as _executor
from docket.pipeline.domain import spec as _pipeline
from docket.teams import fleet as _fleet

SUBJECT = "docket.pipeline.application.executor"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def pod_home(tmp_path: Path) -> Iterator[Path]:
    """A hermetic DOCKET_HOME with the directories enqueue_task_once touches."""
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield home


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = current_home().projects_dir / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id)


def _seed_lean_pod(project: str = "myapp") -> None:
    _write_meta(f"{project}-lead")
    _write_meta(f"{project}-implementer")


class TestDeterministicRefusalFailsOnlyThatTask:
    """A claimed-task ``DispatchError`` (pod-dispatch.spec.md, "Deterministic refusal inside a
    claimed task") must settle as ``"failed"``, never propagate out of ``dispatch_pod``."""

    def test_dispatch_task_settles_a_cross_pod_refusal_as_failed(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="alien-step",
            steps=[
                _pipeline.Step(id="lead", role="lead"),
                _pipeline.Step(id="alien", agent="ghost-lead"),
            ],
        )
        calls: list[str] = []

        def _runner(
            agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            return _rd.TurnResult(True, "done", 0.0, {})

        task = {"id": "task-1", "description": "x", "status": "running"}

        result = _executor.dispatch_task("myapp", task, runner=_runner, spec=spec)

        assert result.status == "failed"
        assert "refusing cross-pod dispatch" in result.reason
        assert result.failure_kind == "dispatch_refused"
        # The lead step ran and its hop is preserved; the alien step never got a turn.
        assert [h.role for h in result.hops] == ["lead"]
        assert calls == ["myapp-lead"]

    def test_a_crash_is_not_caught_and_still_leaves_no_result(self, pod_home: Path) -> None:
        """A real crash (any exception other than DispatchError) must still propagate --
        catching it too would wrongly settle an orphaned claim as 'failed' instead of leaving
        it 'running' for the stale-claim sweep."""
        _seed_lean_pod("myapp")

        def _crasher(
            agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
        ) -> _rd.TurnResult:
            raise RuntimeError("simulated crash")

        task = {"id": "task-1", "description": "x", "status": "running"}

        with pytest.raises(RuntimeError, match="simulated crash"):
            _executor.dispatch_task("myapp", task, runner=_crasher)
