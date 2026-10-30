"""The four methodology recipes (`templates/recipes/{tdd,spec-first,reflexion,frugal}/`) are real, validated pipelines -- the smallest shape that is the named practice
(ADR 0013 section 2, "The recipe library"). See pipeline-format.spec.md ("Short form", "Outcome
routing", "Parallel groups", "Conditional steps and command steps") and pod-blueprints.spec.md
("The recipe library").
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.pods import build_pod
from tests.support.roles import ROLE_NAMES
from tests.support.trace import trace_events as _trace_events

import docket.kernel.templates as _templates
from docket.agent import ports as _rd
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod_members as _pod_members
from docket.kernel.home import Home, use_home
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import queue as _queue
from docket.teams import pod
from docket.teams import roles as _arch
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"

RECIPES_DIR = _templates.RECIPES_DIR
RECIPE_NAMES = ("tdd", "spec-first", "reflexion", "frugal")


def _recipe_dir(name: str) -> Path:
    return RECIPES_DIR / name


@contextmanager
def _seed_fixture_pod(tmp_path: Path, project: str) -> Iterator[None]:
    """Same fixture-pod shape as ``tests/integration/test_recipes.py``'s own helper, kept as
    a local copy here since this module owns its own fixtures independent of that file."""
    import json

    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield


# ── Structural: every recipe validates on its own ────────────────────────────────


def test_every_methodology_recipe_has_its_three_files() -> None:
    for name in RECIPE_NAMES:
        d = _recipe_dir(name)
        assert (d / "pod.yaml").is_file(), d
        assert (d / "pipeline.yaml").is_file(), d
        assert (d / "README.md").is_file(), d


@pytest.mark.parametrize("name", RECIPE_NAMES)
def test_recipe_pipeline_validates(name: str) -> None:
    text = (_recipe_dir(name) / "pipeline.yaml").read_text(encoding="utf-8")
    assert _pipeline.load_pipeline(text, roles=ROLE_NAMES).errors == []


def test_tdd_check_red_routes_pass_to_fail_and_fail_to_green() -> None:
    """``check-red``'s ``on:`` map inverts ordinary pass/fail handling: an unexpectedly passing
    test fails the task outright; a failing one (the expected "red" state) continues to
    ``green``. Written in canonical form, since the short form drops a command step's ``on``."""
    text = (_recipe_dir("tdd") / "pipeline.yaml").read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text, roles=ROLE_NAMES)
    assert result.spec is not None, result.errors
    steps_by_id = {s.id: s for s in result.spec.steps}
    check_red = steps_by_id.get("check-red")
    assert check_red is not None, "the tdd README describes a 'check-red' step; none found"
    assert check_red.run == "python3 -m pytest -q"
    assert check_red.on == {"pass": "fail", "fail": "green"}


# ── plan_apply + apply on a lean fixture pod ──────────────────────────────────────


@pytest.mark.parametrize("name", RECIPE_NAMES)
def test_recipe_applies_cleanly_to_a_fixture_pod(name: str, tmp_path: Path) -> None:
    """``docket pod update <recipe>`` leaves every pipeline step resolvable on a lean pod
    (only the base ``lead``/``implementer`` roles)."""
    project = f"fixture-{name.replace('-', '_')}"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = _recipe_dir(name)

        plan = _pod_apply.plan_apply(project, recipe_dir)
        _write.apply(plan)

        result = _pipeline.load_pipeline(
            (recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"), roles=ROLE_NAMES
        )
        assert result.spec is not None, result.errors

        roster = pod.pod_full_roster(project)
        registry = _arch.load_registry(project)
        exec_plan = _orch.resolve_plan(result.spec, roster, registry=registry)

        skipped: list[str] = []
        for node in exec_plan.nodes:
            units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
            skipped.extend(u.step_id for u in units if u.skipped)
        assert skipped == [], f"recipe {name!r} leaves steps unresolvable: {skipped}"

        if name == "frugal":
            setting_items = [i for i in plan.items if i.kind == "setting"]
            assert len(setting_items) == 2, "frugal's plan should carry two setting items"
            assert {i.name for i in setting_items} == {"budgetUsd", "turnTimeoutS"}


# ── frugal: the named shape, checked without `plan_apply` ────────────────────────


def test_frugal_plan_carries_two_setting_items(tmp_path: Path) -> None:
    import yaml

    project = "frugalcheck"
    with _seed_fixture_pod(tmp_path, project):
        manifest = yaml.safe_load((_recipe_dir("frugal") / "pod.yaml").read_text(encoding="utf-8"))
        settings = manifest["settings"]

        items, _writes = _pod_apply._plan_settings(project, settings)
        assert len(items) == 2
        assert {i.name for i in items} == {"budgetUsd", "turnTimeoutS"}


# ── reflexion: one full dispatch on the fake driver, rework counted ─────────────


class _ReflexionRunner:
    """REQUEST-CHANGES the reviewer's first pass, then APPROVE -- exercises the recipe's own
    bounded rework edge, not just its happy path."""

    def __init__(self, project: str) -> None:
        self._project = project
        self._critique_calls = 0

    def _role_of(self, member_id: str) -> str:
        prefix = f"{self._project}-"
        assert member_id.startswith(prefix)
        return member_id[len(prefix) :]

    def __call__(
        self,
        member_id: str,
        session_id: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = self._role_of(member_id)
        if role == "reviewer":
            self._critique_calls += 1
            if self._critique_calls == 1:
                return _rd.TurnResult(
                    ok=True,
                    output="REQUEST-CHANGES\nTighten the input validation.",
                    cost_usd=0.01,
                    raw={},
                )
            return _rd.TurnResult(
                ok=True, output="APPROVE - looks solid now", cost_usd=0.01, raw={}
            )
        return FakeDriver()(member_id, session_id, message, timeout, env)


def test_reflexion_recipe_dispatches_to_done_with_rework_counted(tmp_path: Path) -> None:
    project = "reflex"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = _recipe_dir("reflexion")

        # Add this recipe's extra roster members through the ordinary `docket pod add <role>`
        # path; the recipe's own `pipeline.yaml` is exercised unmodified.
        _pod_members.add_members(project, "reviewer")

        result = _pipeline.load_pipeline(
            (recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"), roles=ROLE_NAMES
        )
        assert result.spec is not None, result.errors

        _queue.enqueue_task_once(project, "harden the login handler", channel="cli")
        runner = _ReflexionRunner(project)
        results = _sweep.dispatch_pod(project, runner=runner, spec=result.spec)

        assert len(results) == 1
        outcome = results[0]
        assert outcome.status == "done", outcome.reason
        assert [h.role for h in outcome.hops] == [
            "implementer",
            "reviewer",
            "implementer",
            "reviewer",
        ]

        events = _trace_events(project)
        reviewer_events = [e for e in events if e.get("agent_role") == "reviewer"]
        rework = [e for e in reviewer_events if e.get("event_type") == "rework_started"]
        assert rework, "the reviewer's REQUEST-CHANGES rework was not traced"
        assert "REQUEST-CHANGES" in rework[0]["payload"].get("output", "")  # type: ignore[union-attr]
