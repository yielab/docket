"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import seed_lean_pod as _seed_lean_pod

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.hops.application.executor"


# ── fixtures ──────────────────────────────────────────────────────────────────


class TestDeterministicRefusalFailsOnlyThatTask:
    """A claimed-task ``DispatchError`` (pod-dispatch.spec.md, "Deterministic refusal inside a
    claimed task") must settle as ``"failed"``, never propagate out of ``dispatch_pod``."""

    def test_dispatch_task_settles_a_cross_pod_refusal_as_failed(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="alien-step",
            steps=[
                _step.Step(id="lead", role="lead"),
                _step.Step(id="alien", agent="ghost-lead"),
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
