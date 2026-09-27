"""Unit coverage for ``core.pod_apply``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import orchestrator as _orch
from docket.core import pod
from docket.core import pod_apply as _pod_apply

SUBJECT = "docket.core.pod_apply"


def _seed_fixture_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str) -> None:
    """A minimal two-role pod (lead + implementer) in an isolated ``DOCKET_HOME`` --
    ``plan_apply``'s existing-pod lookup (``_dispatch.pod_pipeline``) needs one to resolve
    against, even for a manifest that never reaches roles/policies/settings."""
    from docket.cli import _pod as _cli_pod

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
    _cli_pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


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

        summary = _pod_apply.summarize_recipe(tmp_path)

        assert summary.roles == 0
        assert summary.policies == 1
        assert summary.plugins == 0
        assert summary.skills == 0
        assert summary.members == 0
        assert summary.settings == 0
        assert summary.pipeline == ""
        assert summary.description == ""
        assert summary.render() == (
            "roles 0 · policies 1 · members 0 · pipeline  · plugins 0 · skills 0 · settings 0"
        )

    def test_plan_apply_rejects_a_declared_scope_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "scoped"
        _seed_fixture_pod(tmp_path, monkeypatch, project)
        recipe_dir = tmp_path / "recipe"
        recipe_dir.mkdir()
        (recipe_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nscope: policies\n", encoding="utf-8"
        )

        with pytest.raises(_pod_apply.PodApplyError, match="scope"):
            _pod_apply.plan_apply(project, recipe_dir)

        assert not _cfg.pod_config_dir(project).exists()
