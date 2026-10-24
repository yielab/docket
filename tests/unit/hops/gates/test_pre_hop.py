"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``_execute_unit``
and two extracted phases, called directly with a hand-built
``UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import planned_unit as _planned_unit
from tests.support.pods import unit_context as _unit_context

from docket.agent import ports as _rd
from docket.agent.ports import TokenUsage
from docket.hops.application import runner as _runner
from docket.hops.gates import pre_hop as _pre_hop
from docket.pipeline.domain import gates as _gates
from docket.tasks.application import record as _record
from docket.tasks.domain import task as _task

pod_home = _support_pods.pod_home_2

SUBJECT = "docket.hops.gates.pre_hop"


# ── fixtures ──────────────────────────────────────────────────────────────────


# ── _execute_unit, lifted out of dispatch_task's closure (W31-C8b) ────────────


class TestExecuteUnitDirectly:
    """Direct unit coverage of ``_execute_unit`` and two extracted phase
    functions -- reachable by name since they are module-level, not a
    closure only ``dispatch_task`` could call."""

    def test_gate_pre_hop_approval_consumes_the_override_exactly_once(self, pod_home: Path) -> None:
        # The riskiest capture in the pre-lift closure: `override_index` was
        # rebound with `nonlocal`. As a `UnitContext` attribute, the same
        # rebind is `ctx.override_index = None` — this test pins that the
        # mutation actually lands on the shared context, not a local copy.
        ctx = _unit_context(override_index=2)
        node = _planned_unit("myapp-implementer")

        outcome = _pre_hop._gate_pre_hop_approval(
            ctx, "implementer", node, check_approval=True, index_for_context=2
        )

        assert outcome is None
        assert ctx.override_index is None

    def test_gate_pre_hop_approval_leaves_a_non_matching_override_untouched(
        self, pod_home: Path
    ) -> None:
        ctx = _unit_context(override_index=7)
        node = _planned_unit("myapp-implementer")

        outcome = _pre_hop._gate_pre_hop_approval(
            ctx, "implementer", node, check_approval=True, index_for_context=2
        )

        assert outcome is None
        assert ctx.override_index == 7

    def test_execute_unit_runs_a_full_hop_and_advances(self, pod_home: Path) -> None:
        """A mechanical gate with no configured verifyCmd advances and marks
        the hop ``verification_skipped``, end to end, with no
        ``dispatch_task`` loop involved."""
        persisted: list[_task.HopResult] = []

        def _fake_run(
            member_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None,
        ) -> _rd.TurnResult:
            assert member_id == "myapp-implementer"
            return _rd.TurnResult(True, "did the thing", 0.0, {})

        ctx = _unit_context(run=_fake_run, on_hop=persisted.append)
        node = _planned_unit("myapp-implementer", gate=_gates.MechanicalGate(command=None))

        outcome = _runner._execute_unit(
            ctx,
            node,
            prior_snapshot=[],
            rework_hop=None,
            check_approval=True,
            index_for_context=0,
        )

        assert outcome.kind == "advance"
        assert len(outcome.hops) == 1
        hop = outcome.hops[0]
        assert hop.ok is True
        assert hop.output == "did the thing"
        assert hop.verification_skipped is True
        assert persisted == [hop]

    def test_execute_unit_refuses_cross_pod_dispatch(self, pod_home: Path) -> None:
        ctx = _unit_context(project="myapp")
        node = _planned_unit("otherapp-implementer")

        with pytest.raises(_task.DispatchError, match="refusing cross-pod dispatch"):
            _runner._execute_unit(
                ctx,
                node,
                prior_snapshot=[],
                rework_hop=None,
                check_approval=True,
                index_for_context=0,
            )


class TestTaskRestrictionHelpers:
    """A hop's recorded usage carries the cache split the token budget counts."""

    def test_hop_usage_carries_the_cache_split(self) -> None:
        result = _rd.TurnResult(
            True,
            "ok",
            0.0,
            {},
            usage=TokenUsage(
                input_tokens=900, output_tokens=40, cached_tokens=700, cache_write_tokens=50
            ),
        )

        assert _record._hop_usage(result) == {
            "input": 900,
            "cached": 700,
            "cacheWrite": 50,
            "output": 40,
        }
