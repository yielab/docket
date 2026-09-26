"""Shipped recipe bundles (``templates/recipes/<name>/``) are real, tested and configurable.

Each recipe is data only: role YAML(s), a pipeline YAML, and an optional policy pack, applied
with existing `docket roles`/`docket pod`/`docket policies` commands (no new CLI surface). The
tests below read exactly what the wheel ships (`docket.config.recipes_dir()`), so a recipe that
fails to validate, resolve against a real roster, or actually dispatch fails here first, never
only in an operator's hands. See pipeline-format.spec.md, role-archetypes.spec.md and
workspace-structure.spec.md ("shipped recipes").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _pod
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import policy as _policy
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace

SUBJECT = "docket.config"

RECIPES_DIR = _cfg.recipes_dir()
REQUIRED_RECIPES = ("secure-build", "research-review", "ops-approval")


def _recipe_dirs() -> list[Path]:
    return sorted(p for p in RECIPES_DIR.iterdir() if p.is_dir())


def _role_yaml_files(recipe_dir: Path) -> list[Path]:
    roles_dir = recipe_dir / "roles"
    return sorted(roles_dir.glob("*.yaml")) if roles_dir.is_dir() else []


def _policy_json_files(recipe_dir: Path) -> list[Path]:
    policies_dir = recipe_dir / "policies"
    return sorted(policies_dir.glob("*.json")) if policies_dir.is_dir() else []


def _pipeline_roles(spec: _pipeline.PipelineSpec) -> list[str]:
    """Every ``role`` a step (or parallel child) targets, in first-seen order."""
    roles: list[str] = []
    for step in spec.steps:
        for unit in step.parallel or [step]:
            if unit.role and unit.role not in roles:
                roles.append(unit.role)
    return roles


def test_at_least_three_recipes_are_shipped() -> None:
    names = {p.name for p in _recipe_dirs()}
    assert set(REQUIRED_RECIPES) <= names


def test_every_recipe_has_a_pipeline_and_a_readme() -> None:
    for recipe_dir in _recipe_dirs():
        assert (recipe_dir / "pipeline.yaml").is_file(), recipe_dir
        assert (recipe_dir / "README.md").is_file(), recipe_dir


@pytest.mark.parametrize("recipe_dir", _recipe_dirs(), ids=lambda p: p.name)
def test_recipe_pipeline_validates(recipe_dir: Path) -> None:
    text = (recipe_dir / "pipeline.yaml").read_text(encoding="utf-8")
    assert _pipeline.validate_pipeline(text) == []


@pytest.mark.parametrize(
    "role_file",
    [f for d in _recipe_dirs() for f in _role_yaml_files(d)],
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_recipe_role_validates(role_file: Path) -> None:
    doc = _arch.parse_yaml_file(str(role_file))
    name = str(doc.get("name", "")).strip()
    assert name, f"{role_file} has no top-level 'name'"
    assert _arch.validate_archetype_dict(name, doc) == []


@pytest.mark.parametrize(
    "policy_file",
    [f for d in _recipe_dirs() for f in _policy_json_files(d)],
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_recipe_policy_validates(policy_file: Path) -> None:
    assert _policy.validate_policy(policy_file) == ""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_fixture_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str) -> None:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
    _pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


@pytest.mark.parametrize("recipe_dir", _recipe_dirs(), ids=lambda p: p.name)
def test_recipe_pipeline_plans_cleanly_against_a_fixture_pod(
    recipe_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Applying each recipe with only its own documented commands leaves every step
    resolvable -- the same check ``docket pipeline plan``/``pod config set pipeline`` run."""
    project = "fixture"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    for role_file in _role_yaml_files(recipe_dir):
        _arch.add_user_archetype(_arch.parse_yaml_file(str(role_file)))

    result = _pipeline.load_pipeline((recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"))
    assert result.spec is not None, result.errors
    spec = result.spec

    for role in _pipeline_roles(spec):
        if role in pod.DEFAULT_POD_ROLES:
            continue
        _pod.dispatch(project, "add", [role])

    roster = _dispatch.pod_full_roster(project)
    registry = _arch.load_registry()
    plan = _orch.resolve_plan(spec, roster, registry=registry)

    skipped: list[str] = []
    for node in plan.nodes:
        units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
        skipped.extend(u.step_id for u in units if u.skipped)
    assert skipped == [], f"recipe {recipe_dir.name!r} leaves steps unresolvable: {skipped}"


# ── secure-build: one full dispatch on the fake driver ──────────────────────────


class _SecureBuildRunner:
    """REQUEST-CHANGES the vetter's first pass, then APPROVE -- exercises the recipe's own
    one-cycle rework edge, not just its happy path."""

    def __init__(self, project: str) -> None:
        self._project = project
        self.calls: list[tuple[str, str]] = []
        self._vet_calls = 0

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
        self.calls.append((role, message))
        if role == "security-vetter":
            self._vet_calls += 1
            if self._vet_calls == 1:
                return _rd.TurnResult(
                    ok=True,
                    output="REQUEST-CHANGES\nSanitize the raw SQL string in query.py.",
                    cost_usd=0.01,
                    raw={},
                )
            return _rd.TurnResult(
                ok=True, output="APPROVE - injection risk fixed", cost_usd=0.01, raw={}
            )
        return FakeDriver()(member_id, session_id, message, timeout, env)


def _trace_events(project: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


def test_secure_build_recipe_dispatches_to_done_with_the_verdict_gate_observed_in_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = "webapp"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    recipe_dir = RECIPES_DIR / "secure-build"

    role_doc = _arch.parse_yaml_file(str(recipe_dir / "roles" / "security-vetter.yaml"))
    _arch.add_user_archetype(role_doc)
    _pod.dispatch(project, "add", ["security-vetter"])
    assert pod.pod_of(f"{project}-security-vetter") == project

    result = _pipeline.load_pipeline((recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"))
    assert result.spec is not None, result.errors

    _dispatch.enqueue_task(project, "add a login endpoint")
    runner = _SecureBuildRunner(project)
    results = _dispatch.dispatch_pod(project, runner=runner, spec=result.spec)

    assert len(results) == 1
    outcome = results[0]
    assert outcome.status == "done", outcome.reason
    assert [h.role for h in outcome.hops] == [
        "lead",
        "implementer",
        "security-vetter",
        "implementer",
        "security-vetter",
    ]

    events = _trace_events(project)
    vetter_events = [e for e in events if e.get("agent_role") == "security-vetter"]
    rework = [e for e in vetter_events if e.get("event_type") == "verdict_rework_started"]
    assert rework, "the vetter's REQUEST-CHANGES rework was not traced"
    assert "REQUEST-CHANGES" in rework[0]["payload"].get("output", "")  # type: ignore[union-attr]

    approvals = [
        e
        for e in vetter_events
        if e.get("event_type") == "tool_result"
        and "APPROVE" in (e.get("payload") or {}).get("text", "")  # type: ignore[union-attr]
    ]
    assert approvals, "the vetter's APPROVE verdict was not traced"
