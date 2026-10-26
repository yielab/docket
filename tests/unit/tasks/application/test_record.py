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

from docket.tasks.application import record as _record

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
