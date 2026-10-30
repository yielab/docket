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

import dataclasses
from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import planned_unit as _planned_unit
from tests.support.pods import seed_lean_pod as _seed_lean_pod
from tests.support.pods import unit_context as _unit_context

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import TaskRecord

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

        task = TaskRecord(id="task-1", description="x", status=Status.running)

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

        task = TaskRecord(id="task-1", description="x", status=Status.running)

        with pytest.raises(RuntimeError, match="simulated crash"):
            _executor.dispatch_task("myapp", task, runner=_crasher)


class TestWhenVarComparesAsText:
    """``when.var`` / ``is`` compare the variable's text (pod-dispatch.spec.md, "Conditional steps
    and command steps"), whatever type a webhook body or a task gave the value."""

    @staticmethod
    def _skipped(value: object, is_: object) -> bool:
        ctx = _unit_context()
        ctx.variables = {"n": value}  # type: ignore[dict-item]
        node = dataclasses.replace(_planned_unit("x"), when={"var": "n", "is": is_})
        return _executor._step_skipped(ctx, node, [])

    def test_an_integer_value_matches_its_text(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        assert self._skipped(3, "3") is False

    def test_a_different_text_skips(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        assert self._skipped(4, "3") is True

    def test_a_boolean_value_compares_as_its_text(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        assert self._skipped(True, "True") is False
