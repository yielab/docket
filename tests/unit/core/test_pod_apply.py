"""Unit coverage for ``core.pod_apply``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

from docket.core import orchestrator as _orch
from docket.core import pod_apply as _pod_apply

SUBJECT = "docket.core.pod_apply"


def _unit(step_id: str, *, role: str | None, agent: str | None, skipped: bool) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role=role,
        agent=agent,
        archetype=None,
        member_id=None if skipped else "proj-implementer",
        gate=None,
        retries=None,
        timeout=None,
        skipped=skipped,
    )


class TestUnresolvablePipelineSteps:
    """The shared helper ``docket pod <p> config set pipeline`` and ``apply`` both use."""

    def test_no_problems_for_a_fully_resolved_plan(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("build", role="implementer", agent=None, skipped=False),),
        )
        assert _pod_apply.unresolvable_pipeline_steps(plan, "proj") == []

    def test_reports_a_skipped_role_step(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("vet", role="security-vetter", agent=None, skipped=True),),
        )
        problems = _pod_apply.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'vet': role 'security-vetter' not in pod 'proj'"]

    def test_reports_an_agent_step_targeting_a_foreign_pod(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("build", role=None, agent="other-implementer", skipped=False),),
        )
        problems = _pod_apply.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'build': agent 'other-implementer' is not a member of pod 'proj'"]

    def test_a_parallel_group_checks_every_child(self) -> None:
        group = _orch.PlannedGroup(
            step_id="fanout",
            children=(
                _unit("a", role="implementer", agent=None, skipped=False),
                _unit("b", role="missing-role", agent=None, skipped=True),
            ),
        )
        plan = _orch.ExecutionPlan(pipeline_name="p", nodes=(group,))
        problems = _pod_apply.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'b': role 'missing-role' not in pod 'proj'"]
