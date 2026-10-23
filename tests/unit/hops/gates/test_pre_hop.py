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
from docket.agent.llm import TokenUsage
from docket.hops.application import record as _record
from docket.hops.application import runner as _runner
from docket.hops.gates import pre_hop as _pre_hop
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.domain import task as _task

SUBJECT = "docket.hops.gates.pre_hop"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def pod_home(tmp_path: Path) -> Iterator[Path]:
    """A hermetic DOCKET_HOME with the directories enqueue_task_once touches."""
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield home


# ── _execute_unit, lifted out of dispatch_task's closure (W31-C8b) ────────────


def _unit_context(
    *,
    project: str = "myapp",
    task_id: str = "task-1",
    cap: float = 0.0,
    override_index: int | None = None,
    run: Any = None,
    on_hop: Any = None,
) -> _record._UnitContext:
    return _record._UnitContext(
        project=project,
        task={"id": task_id},
        task_id=task_id,
        session_id=f"agent:{project}:{task_id}",
        cap=cap,
        resolved_turn_timeout=60,
        resolved_verify_timeout=60,
        id_to_index={},
        rework_counts={},
        override_index=override_index,
        track_pid=False,
        run=run or (lambda *a, **k: _rd.TurnResult(True, "", 0.0, {})),
        do_sleep=lambda seconds: None,
        on_hop=on_hop,
        on_retry=None,
    )


def _planned_unit(
    member_id: str, *, gate: _pipeline.Gate | None = None, step_id: str = "implementer"
) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role="implementer",
        agent=None,
        archetype=None,
        member_id=member_id,
        gate=gate,
        retries=None,
        timeout=None,
    )


class TestExecuteUnitDirectly:
    """Direct unit coverage of ``_execute_unit`` and two extracted phase
    functions -- reachable by name since they are module-level, not a
    closure only ``dispatch_task`` could call."""

    def test_gate_budget_blocks_before_any_hop_and_traces_it(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_pre_hop, "pod_gating_cost", lambda project: (10.0, False))
        ctx = _unit_context(cap=5.0)

        outcome = _pre_hop._gate_budget(ctx, "implementer")

        assert outcome is not None
        assert outcome.kind == "blocked"
        assert "$10.00" in outcome.reason and "$5.00" in outcome.reason
        tf = current_home().traces_dir / "myapp" / "agent:myapp:task-1.jsonl"
        events = _trace.read_trace(tf)
        assert events[-1]["event_type"] == "budget_exceeded"
        assert events[-1]["agent_role"] == "implementer"

    def test_gate_budget_allows_when_under_cap(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_pre_hop, "pod_gating_cost", lambda project: (1.0, False))
        ctx = _unit_context(cap=5.0)

        assert _pre_hop._gate_budget(ctx, "implementer") is None

    def test_gate_pre_hop_approval_consumes_the_override_exactly_once(self, pod_home: Path) -> None:
        # The riskiest capture in the pre-lift closure: `override_index` was
        # rebound with `nonlocal`. As a `_UnitContext` attribute, the same
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
        node = _planned_unit("myapp-implementer", gate=_pipeline.MechanicalGate(command=None))

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
    """The hop's network is the narrower of pod and task; maxTokens counts persisted hop usage."""

    @pytest.mark.parametrize(
        ("pod_mode", "task_mode", "expected"),
        [
            ("open", None, "open"),
            ("open", "none", "none"),
            ("none", None, "none"),
            ("none", "none", "none"),
        ],
    )
    def test_hop_network_takes_the_narrower(
        self, pod_mode: str, task_mode: str | None, expected: str
    ) -> None:
        assert _pre_hop._hop_network(pod_mode, task_mode) == expected

    def test_token_budget_is_the_cap_less_persisted_usage(self) -> None:
        task = {
            "maxTokens": 1000,
            "hops": [{"usage": {"input": 300, "output": 100}}, {"usage": None}, {"role": "x"}],
        }

        assert _pre_hop._task_token_budget(task) == 600

    def test_token_budget_does_not_count_cache_reads(self) -> None:
        hop = {"usage": {"input": 30_000, "cached": 25_000, "cacheWrite": 0, "output": 100}}
        task = {"maxTokens": 10_000, "hops": [hop, hop]}

        assert _pre_hop._task_token_budget(task) == 10_000 - 2 * 5_100

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

    def test_token_budget_goes_non_positive_when_spent(self) -> None:
        task = {"maxTokens": 100, "hops": [{"usage": {"input": 90, "output": 20}}]}

        assert _pre_hop._task_token_budget(task) == -10

    @pytest.mark.parametrize("task", [{}, {"maxTokens": None}, {"maxTokens": True}])
    def test_no_cap_means_no_budget(self, task: dict[str, Any]) -> None:
        assert _pre_hop._task_token_budget(task) is None
