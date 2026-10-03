"""The five methodology recipes (`templates/recipes/{tdd,spec-first,reflexion,dual-review,
frugal}/`) are real, validated pipelines -- the smallest shape that is the named practice
(ADR 0013 section 2, "The recipe library"). See pipeline-format.spec.md ("Short form", "Outcome
routing", "Parallel groups", "Conditional steps and command steps") and pod-blueprints.spec.md
("The recipe library").
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _pod as _cli_pod
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import pod_apply as _pod_apply
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace

SUBJECT = "docket.config"

RECIPES_DIR = _cfg.recipes_dir()
RECIPE_NAMES = ("tdd", "spec-first", "reflexion", "dual-review", "frugal")


def _recipe_dir(name: str) -> Path:
    return RECIPES_DIR / name


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_fixture_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str) -> None:
    """Same fixture-pod shape as ``tests/integration/test_recipes.py``'s own helper, kept as
    a local copy here since this module owns its own fixtures independent of that file."""
    import json

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
    _cli_pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


def _trace_events(project: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


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
    assert _pipeline.load_pipeline(text).errors == []


def test_tdd_check_red_routes_pass_to_fail_and_fail_to_green() -> None:
    """``check-red``'s ``on:`` map inverts ordinary pass/fail handling: an unexpectedly passing
    test fails the task outright; a failing one (the expected "red" state) continues to
    ``green``. Written in canonical form, since the short form drops a command step's ``on``."""
    text = (_recipe_dir("tdd") / "pipeline.yaml").read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    assert result.spec is not None, result.errors
    steps_by_id = {s.id: s for s in result.spec.steps}
    check_red = steps_by_id.get("check-red")
    assert check_red is not None, "the tdd README describes a 'check-red' step; none found"
    assert check_red.run == "python3 -m pytest -q"
    assert check_red.on == {"pass": "fail", "fail": "green"}


# ── plan_apply + apply on a lean fixture pod ──────────────────────────────────────


@pytest.mark.parametrize("name", RECIPE_NAMES)
def test_recipe_applies_cleanly_to_a_fixture_pod(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``docket pod <p> apply <recipe>`` leaves every pipeline step resolvable on a lean pod
    (only the base ``lead``/``implementer`` roles)."""
    project = f"fixture-{name.replace('-', '_')}"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    recipe_dir = _recipe_dir(name)

    plan = _pod_apply.plan_apply(project, recipe_dir)
    _pod_apply.apply(plan)

    result = _pipeline.load_pipeline((recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"))
    assert result.spec is not None, result.errors

    roster = _dispatch.pod_full_roster(project)
    registry = _arch.load_registry(project)
    exec_plan = _orch.resolve_plan(result.spec, roster, registry=registry)

    skipped: list[str] = []
    for node in exec_plan.nodes:
        units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
        skipped.extend(u.step_id for u in units if u.skipped)
    assert skipped == [], f"recipe {name!r} leaves steps unresolvable: {skipped}"

    if name == "dual-review":
        groups = [n for n in exec_plan.nodes if isinstance(n, _orch.PlannedGroup)]
        assert len(groups) == 1, "dual-review's plan should carry exactly one PlannedGroup"
        assert [c.step_id for c in groups[0].children] == ["review-code", "review-risk"]

    if name == "frugal":
        setting_items = [i for i in plan.items if i.kind == "setting"]
        assert len(setting_items) == 3, "frugal's plan should carry three setting items"
        assert {i.name for i in setting_items} == {
            "budgetUsd",
            "maxReworkCycles",
            "turnTimeoutS",
        }


# ── dual-review / frugal: the two named shapes, checked without `plan_apply` ─────
#
# Both assertions are also covered inside the parametrized test above; these two build the
# roster/settings input directly rather than through `plan_apply`.


def test_dual_review_plan_has_one_planned_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = "dualcheck"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    _cli_pod.dispatch(project, "add", ["reviewer"])
    _cli_pod.dispatch(project, "add", ["critic"])

    text = (_recipe_dir("dual-review") / "pipeline.yaml").read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    assert result.spec is not None, result.errors

    roster = _dispatch.pod_full_roster(project)
    registry = _arch.load_registry(project)
    exec_plan = _orch.resolve_plan(result.spec, roster, registry=registry)

    groups = [n for n in exec_plan.nodes if isinstance(n, _orch.PlannedGroup)]
    assert len(groups) == 1
    assert [c.step_id for c in groups[0].children] == ["review-code", "review-risk"]
    assert not any(c.skipped for c in groups[0].children)


def test_frugal_plan_carries_three_setting_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    project = "frugalcheck"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    manifest = yaml.safe_load((_recipe_dir("frugal") / "pod.yaml").read_text(encoding="utf-8"))
    settings = manifest["settings"]

    items, _writes = _pod_apply._plan_settings(project, settings)
    assert len(items) == 3
    assert {i.name for i in items} == {"budgetUsd", "maxReworkCycles", "turnTimeoutS"}


# ── reflexion: one full dispatch on the fake driver, rework counted ─────────────


class _ReflexionRunner:
    """REQUEST-CHANGES the critic's first pass, then APPROVE, then PASS the tester -- exercises
    the recipe's own bounded rework edge, not just its happy path."""

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
        if role == "critic":
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
        if role == "tester":
            return _rd.TurnResult(ok=True, output="PASS - behavior verified", cost_usd=0.01, raw={})
        return FakeDriver()(member_id, session_id, message, timeout, env)


def test_reflexion_recipe_dispatches_to_done_with_rework_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = "reflex"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    recipe_dir = _recipe_dir("reflexion")

    # Add this recipe's extra roster members through the ordinary `docket pod <p> add <role>`
    # path; the recipe's own `pipeline.yaml` is exercised unmodified.
    _cli_pod.dispatch(project, "add", ["critic"])
    _cli_pod.dispatch(project, "add", ["tester"])

    result = _pipeline.load_pipeline((recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"))
    assert result.spec is not None, result.errors

    _dispatch.enqueue_task(project, "harden the login handler")
    runner = _ReflexionRunner(project)
    results = _dispatch.dispatch_pod(project, runner=runner, spec=result.spec)

    assert len(results) == 1
    outcome = results[0]
    assert outcome.status == "done", outcome.reason
    assert [h.role for h in outcome.hops] == [
        "implementer",
        "critic",
        "implementer",
        "critic",
        "tester",
    ]

    events = _trace_events(project)
    critic_events = [e for e in events if e.get("agent_role") == "critic"]
    rework = [e for e in critic_events if e.get("event_type") == "verdict_rework_started"]
    assert rework, "the critic's REQUEST-CHANGES rework was not traced"
    assert "REQUEST-CHANGES" in rework[0]["payload"].get("output", "")  # type: ignore[union-attr]
