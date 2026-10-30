"""Unit coverage for ``teams.apply.plan``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.kernel.home import current_home
from docket.pipeline.domain import plan as _orch
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import recipes as _recipes

SUBJECT = "docket.teams.apply.recipes"


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
    """The shared helper ``docket pod set pipeline`` and ``apply`` both use."""

    def test_no_problems_for_a_fully_resolved_plan(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("build", role="implementer", agent=None, skipped=False),),
        )
        assert _recipes.unresolvable_pipeline_steps(plan, "proj") == []

    def test_reports_a_skipped_role_step(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("vet", role="security-vetter", agent=None, skipped=True),),
        )
        problems = _recipes.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'vet': role 'security-vetter' not in pod 'proj'"]

    def test_reports_an_agent_step_targeting_a_foreign_pod(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("build", role=None, agent="other-implementer", skipped=False),),
        )
        problems = _recipes.unresolvable_pipeline_steps(plan, "proj")
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
        problems = _recipes.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'b': role 'missing-role' not in pod 'proj'"]


class TestSummarizeRecipe:
    """``summarize_recipe`` derives what a directory brings from its contents, never a
    declared field (ADR 0013 §1 rule 1) -- ``plan_apply`` refuses a declared ``scope:`` the
    same way it refuses any other unrecognized top-level key."""

    def test_a_policies_only_directory(self, tmp_path: Path) -> None:
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        (policies_dir / "one.yaml").write_text(
            "kind: policy\nname: one\nthen: allow\n", encoding="utf-8"
        )

        summary = _recipes.summarize_recipe(tmp_path)

        assert summary.roles == 0
        assert summary.policies == 1
        assert summary.plugins == 0
        assert summary.skills == 0
        assert summary.members == 0
        assert summary.settings == 0
        assert summary.pipeline == ""
        assert summary.description == ""
        assert summary.render() == (
            "roles 0 · policies 1 · members 0 · pipeline none · plugins 0 · skills 0 · settings 0"
        )

    def test_records_routines_and_named_pipelines_are_counted(self, tmp_path: Path) -> None:
        for folder, name in (
            ("records", "entries"),
            ("routines", "weekly-report"),
            ("pipelines", "capture"),
        ):
            (tmp_path / folder).mkdir()
            (tmp_path / folder / f"{name}.yaml").write_text("kind: x\n", encoding="utf-8")
        (tmp_path / "records" / "notes.txt").write_text("not a document", encoding="utf-8")

        summary = _recipes.summarize_recipe(tmp_path)

        assert summary.records == ("entries",)
        assert summary.routines == ("weekly-report",)
        assert summary.pipelines == ("capture",)
        assert summary.render().endswith(
            "pipelines capture · records entries · routines weekly-report"
        )

    def test_plan_apply_rejects_a_declared_scope_key(self, tmp_path: Path) -> None:
        project = "scoped"
        with _seed_fixture_pod(tmp_path, project):
            recipe_dir = tmp_path / "recipe"
            recipe_dir.mkdir()
            (recipe_dir / "pod.yaml").write_text(
                "kind: pod\nname: x\nscope: policies\n", encoding="utf-8"
            )

            with pytest.raises(_model.PodApplyError, match="scope"):
                _pod_apply.plan_apply(project, recipe_dir)

            assert not current_home().pod_config_dir(project).exists()
