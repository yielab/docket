"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``execute_unit``
and two extracted phases, called directly with a hand-built
``UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

from typing import Any

from docket.agent.ports import BudgetStop, TurnResult
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import record as _record
from docket.tasks.domain.task import HopResult

SUBJECT = "docket.tasks.application.record"


class TestParkedApprovalToken:
    """``_parked_approval_token`` parses the ``approval_parked`` stop's ``key=value`` error
    string -- driven through the real producer so the two are proven against each other."""

    def test_round_trips_the_real_producer(self) -> None:
        from docket.agent.loop import approval_parked_error
        from docket.agent.tools.registry import ToolResult

        result = ToolResult(
            ok=False,
            decision="deny",
            tool="bash",
            call_id="c1",
            denial_kind="approval_parked",
            policy_id="prod-approval",
            reason="policy requires approval",
            approval_token="apr-abc123",
        )
        error = approval_parked_error(result)

        assert _record._parked_approval_token(error) == "apr-abc123"

    def test_none_for_an_ordinary_failure(self) -> None:
        assert _record._parked_approval_token("boom: connection reset") is None

    def test_none_when_the_prefix_matches_but_no_token_field_is_present(self) -> None:
        assert _record._parked_approval_token("approval_parked: tool='bash'") is None


def _unit(step_id: str, gate: _gates.Gate | None = None) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role=step_id,
        agent=None,
        archetype=None,
        member_id=f"pod-{step_id}",
        gate=gate,
        retries=None,
        timeout=None,
    )


def _hop(step_id: str, *, ok: bool = True, verdict: str | None = None) -> HopResult:
    output = verdict.upper() if verdict else "done"
    return HopResult(role=step_id, step_id=step_id, ok=ok, output=output)


_REVIEW_GATE = _gates.VerdictGate(
    pattern=r"^(APPROVE|REQUEST-CHANGES)\b",
    passValues=["approve"],
    rework=_gates.ReworkEdge(to="implementer", when=["request-changes"], maxCycles=2),
)


class TestReplayPipelinePosition:
    """A failed hop replays to its own index, like a parked one, and consumes no cycle."""

    def _steps(self) -> tuple[_orch.PlannedUnit, ...]:
        return (_unit("lead"), _unit("implementer"), _unit("reviewer", _REVIEW_GATE))

    def test_a_failed_hop_runs_again_instead_of_the_next_step(self) -> None:
        pos = _record.replay_pipeline_position(
            self._steps(), [_hop("lead"), _hop("implementer", ok=False)]
        )
        assert pos.pipeline_index == 1

    def test_a_failed_hop_after_a_rework_keeps_the_rework_state(self) -> None:
        review = _hop("reviewer", verdict="request-changes")
        pos = _record.replay_pipeline_position(
            self._steps(),
            [_hop("lead"), _hop("implementer"), review, _hop("implementer", ok=False)],
        )
        assert pos.pipeline_index == 1
        assert pos.rework_hop is review
        assert pos.rework_counts == {"reviewer": 1}

    def test_the_run_after_a_failed_hop_moves_on_once_it_succeeds(self) -> None:
        pos = _record.replay_pipeline_position(
            self._steps(),
            [_hop("lead"), _hop("implementer", ok=False), _hop("implementer")],
        )
        assert pos.pipeline_index == 2


class TestBudgetOutcomeRaise:
    """A hop's ``budget.raise`` names what raises the limit that stopped it, task tokens included."""

    @staticmethod
    def _outcome(stop: BudgetStop) -> dict[str, Any]:
        run = TurnResult(False, "", 0.0, {}, budget_stop=stop)
        outcome = _record._budget_outcome(run, tree_changed=False)
        assert outcome is not None
        return outcome.model_dump(by_alias=True)

    def test_a_task_max_tokens_stop_reads_max_tokens(self) -> None:
        got = self._outcome(BudgetStop("tokens", 500, 501, "task"))
        assert (got["source"], got["raise"]) == ("task", "maxTokens")

    def test_a_pod_budget_stop_reads_budget_tokens(self) -> None:
        got = self._outcome(BudgetStop("tokens", 500, 501, "pod_budget"))
        assert (got["source"], got["raise"]) == ("pod_budget", "budgetTokens")

    def test_a_machine_token_stop_reads_the_machine_variable(self) -> None:
        got = self._outcome(BudgetStop("tokens", 100000, 100001, "default"))
        assert (got["source"], got["raise"]) == ("default", "AGENT_LOOP_TOKEN_BUDGET")

    def test_a_step_clock_stop_reads_timeout(self) -> None:
        got = self._outcome(BudgetStop("time", 30, 31, "step"))
        assert got["raise"] == "timeout"
