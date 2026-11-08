"""Shipped recipe bundles (``templates/recipes/<name>/``) are real, tested and configurable.

Each recipe is data only: role YAML(s), a pipeline YAML, a small `pod.yaml`, and an optional
policy pack, applied in one command (`docket pod update`, `teams.apply.plan`). The tests below
read exactly what the wheel ships (`kernel.templates.RECIPES_DIR`), so a recipe that fails to
validate, resolve against a real roster, or actually dispatch fails here first, never only in an
operator's hands. See pipeline-format.spec.md, role-archetypes.spec.md and
pod-blueprints.spec.md ("Pod manifests: apply").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.cli import invoke_pod
from tests.support.cli import pod_cli as _pod_cli
from tests.support.fakes import FakeDriver
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod
from tests.support.roles import ROLE_NAMES
from tests.support.trace import trace_events as _trace_events

import docket.kernel.templates as _templates
from docket.agent import ports as _rd
from docket.governance import audit as _audit
from docket.governance import gate as _gate
from docket.governance import policy as _policy
from docket.hops.application import compose as _compose
from docket.hops.application import sweep as _sweep
from docket.kernel.home import Home, current_home, use_home
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import queue as _queue
from docket.tasks.domain.task import TaskRecord
from docket.teams import pod
from docket.teams import roles as _arch
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import recipes as _recipes
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"

RECIPES_DIR = _templates.RECIPES_DIR


REQUIRED_RECIPES = (
    "secure-build",
    "research-review",
    "explore-then-edit",
    "strong-plan-cheap-edit",
    "parallel-explore",
    "web-research",
    "outward",
)


def _recipe_dirs() -> list[Path]:
    return sorted(p for p in RECIPES_DIR.iterdir() if p.is_dir())


def _role_yaml_files(recipe_dir: Path) -> list[Path]:
    roles_dir = recipe_dir / "roles"
    return sorted(roles_dir.glob("*.yaml")) if roles_dir.is_dir() else []


def _policy_yaml_files(recipe_dir: Path) -> list[Path]:
    policies_dir = recipe_dir / "policies"
    return sorted(policies_dir.glob("*.yaml")) if policies_dir.is_dir() else []


def _pod_manifest_members(recipe_dir: Path) -> list[str]:
    """This recipe's own ``pod.yaml`` ``members``, read with plain YAML rather than
    ``teams.config_docs`` -- a policy pack's manifest carries a ``description`` key the
    short-form pod model on this branch does not yet accept."""
    manifest = recipe_dir / "pod.yaml"
    if not manifest.is_file():
        return []
    import yaml as _yaml

    doc = _yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    members = doc.get("members") or []
    return [str(m) for m in members] if isinstance(members, list) else []


def test_at_least_three_recipes_are_shipped() -> None:
    names = {p.name for p in _recipe_dirs()}
    assert set(REQUIRED_RECIPES) <= names


def test_every_recipe_has_a_readme_and_some_content() -> None:
    """A policy pack ships no pipeline or roles, so every recipe needs a README and some content: a
    pipeline, roles, policies, members, or an mcp-servers / records / pipelines / routines file."""
    for recipe_dir in _recipe_dirs():
        assert (recipe_dir / "README.md").is_file(), recipe_dir
        has_pipeline = (recipe_dir / "pipeline.yaml").is_file()
        has_roles = bool(_role_yaml_files(recipe_dir) or _policy_yaml_files(recipe_dir))
        has_members = bool(_pod_manifest_members(recipe_dir))
        has_servers = any(
            any((recipe_dir / d).glob("*.yaml"))
            for d in ("mcp-servers", "records", "pipelines", "routines")
        )
        assert has_pipeline or has_roles or has_members or has_servers, recipe_dir


def _loaded(path: Path) -> _pipeline.PipelineLoadResult:
    return _pipeline.load_pipeline(path.read_text(encoding="utf-8"), roles=ROLE_NAMES)


@pytest.mark.parametrize("recipe_dir", _recipe_dirs(), ids=lambda p: p.name)
def test_recipe_pipeline_validates(recipe_dir: Path) -> None:
    pipeline_file = recipe_dir / "pipeline.yaml"
    if not pipeline_file.is_file():
        pytest.skip(f"{recipe_dir.name} is a policy pack: no pipeline.yaml")
    text = pipeline_file.read_text(encoding="utf-8")
    assert _pipeline.load_pipeline(text, roles=ROLE_NAMES).errors == []


@pytest.mark.parametrize(
    "role_file",
    [f for d in _recipe_dirs() for f in _role_yaml_files(d)],
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_recipe_role_validates(role_file: Path) -> None:
    doc = _arch.load_role_file(str(role_file))
    name = str(doc.get("name", "")).strip()
    assert name, f"{role_file} has no top-level 'name'"
    assert _arch.validate_archetype_dict(name, doc) == []


@pytest.mark.parametrize(
    "policy_file",
    [f for d in _recipe_dirs() for f in _policy_yaml_files(d)],
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_recipe_policy_validates(policy_file: Path) -> None:
    assert _policy.validate_policy(policy_file) == ""


@pytest.mark.parametrize("recipe_dir", _recipe_dirs(), ids=lambda p: p.name)
def test_recipe_applies_cleanly_to_a_fixture_pod(recipe_dir: Path, tmp_path: Path) -> None:
    """``docket pod update <recipe_dir>`` leaves every pipeline step resolvable -- a policy
    pack has no pipeline to resolve, so applying it cleanly is the whole assertion."""
    project = "fixture"
    with _seed_fixture_pod(tmp_path, project):
        _write.apply(_pod_apply.plan_apply(project, recipe_dir))

        pipeline_file = recipe_dir / "pipeline.yaml"
        if not pipeline_file.is_file():
            return
        result = _loaded(pipeline_file)
        assert result.spec is not None, result.errors

        roster = pod.pod_full_roster(project)
        registry = _arch.load_registry(project)
        plan = _orch.resolve_plan(result.spec, roster, registry=registry)

        skipped: list[str] = []
        for node in plan.nodes:
            units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
            skipped.extend(u.step_id for u in units if u.skipped)
        assert skipped == [], f"recipe {recipe_dir.name!r} leaves steps unresolvable: {skipped}"


def test_web_research_validates_and_its_lead_is_not_told_to_plan_for_the_implementer() -> None:
    """The recipe's Lead step declares its own instructions, so its request names no Implementer."""
    recipe_dir = RECIPES_DIR / "web-research"
    validated = invoke_pod(["validate", str(recipe_dir)])
    assert validated.exit_code == 0, validated.output

    spec = _loaded(recipe_dir / "pipeline.yaml").spec
    assert spec is not None
    lead = next(step for step in spec.steps if step.role == "lead")
    assert lead.instructions
    message, _ = _compose._hop_message(
        TaskRecord(description="what is new in X"), "lead", [], step_instructions=lead.instructions
    )
    assert "Implementer" not in message
    assert message.endswith("\n\nwhat is new in X")


def test_pod_apply_resolves_a_shipped_recipe_by_name(tmp_path: Path) -> None:
    """``docket pod update secure-build`` applies the shipped recipe, as ``init --recipe``
    does -- a README can print a command that needs no path into the installed package."""
    project = "byname"
    with _seed_fixture_pod(tmp_path, project):
        assert _pod_cli("update", "secure-build", "--pod", project).exit_code == 0

        assert "security-vetter" in pod.pod_full_roster(project)


def test_apply_with_an_invalid_setting_writes_nothing(tmp_path: Path) -> None:
    """A bad ``pod.yaml`` setting refuses before any pod-scoped file is written."""
    project = "guarded"
    with _seed_fixture_pod(tmp_path, project):
        bad_dir = tmp_path / "bad-recipe"
        bad_dir.mkdir()
        (bad_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nsettings:\n  mcpServers: [zzz]\n", encoding="utf-8"
        )

        with pytest.raises(_model.PodApplyError, match="zzz"):
            _pod_apply.plan_apply(project, bad_dir)

        assert not current_home().pod_config_dir(project).exists()


def test_apply_with_an_invalid_policy_writes_nothing(tmp_path: Path) -> None:
    """A policy file that fails ``validate_policy`` (an uncompilable regex) refuses before any
    pod-scoped file is written, naming the offending file."""
    project = "badpolicy"
    with _seed_fixture_pod(tmp_path, project):
        bad_dir = tmp_path / "bad-recipe"
        (bad_dir / "policies").mkdir(parents=True)
        (bad_dir / "policies" / "broken.json").write_text(
            json.dumps(
                {
                    "kind": "policy",
                    "name": "broken",
                    "appliesTo": ["implementer"],
                    "on": "toolCall",
                    "when": {"matches": "(unclosed"},
                    "then": "block",
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(_model.PodApplyError, match=r"broken\.json"):
            _pod_apply.plan_apply(project, bad_dir)

        assert not current_home().pod_config_dir(project).exists()


def test_apply_writes_a_recipes_policy_pack_into_the_pods_own_directory(tmp_path: Path) -> None:
    """``secure-build``'s policy pack lands in the pod's own directory, never the fleet-wide
    one; a second apply plans it ``skip`` and writes no second audit entry."""
    project = "policied"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = RECIPES_DIR / "secure-build"
        src = recipe_dir / "policies" / "require-approval-secret-writes.yaml"

        plan = _pod_apply.plan_apply(project, recipe_dir)
        policy_items = [i for i in plan.items if i.kind == "policy"]
        assert [(i.name, i.action) for i in policy_items] == [(src.name, "add")]
        _write.apply(plan)

        dest = current_home().pod_config_dir(project) / "policies" / src.name
        assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
        assert not (current_home().policies_dir / src.name).exists()
        assert dest in _policy.policy_files(project)

        entries_before = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
        second_plan = _pod_apply.plan_apply(project, recipe_dir)
        second_policy_items = [i for i in second_plan.items if i.kind == "policy"]
        assert [(i.name, i.action) for i in second_policy_items] == [(src.name, "skip")]
        _write.apply(second_plan)
        entries_after = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
        assert entries_after == entries_before


# ── skills: the Agent Skills shape, applied/exported like any other pod scope ─────────────────


def test_secure_build_plans_applies_and_round_trips_its_skill(tmp_path: Path) -> None:
    """``secure-build``'s ``skills/security-review/`` plans ``add``, lands whole in the pod's
    own ``config/skills/``, exports back byte-for-byte, and re-applying the export plans
    ``skip`` -- the same additive/idempotent contract every other recipe part already has."""
    project = "skilled"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = RECIPES_DIR / "secure-build"

        plan = _pod_apply.plan_apply(project, recipe_dir)
        skill_items = [i for i in plan.items if i.kind == "skill"]
        assert [(i.name, i.action) for i in skill_items] == [("security-review", "add")]
        _write.apply(plan)

        dest = current_home().pod_config_dir(project) / "skills" / "security-review" / "SKILL.md"
        assert dest.is_file()
        assert dest.read_text(encoding="utf-8") == (
            recipe_dir / "skills" / "security-review" / "SKILL.md"
        ).read_text(encoding="utf-8")

        entries_before = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
        second_plan = _pod_apply.plan_apply(project, recipe_dir)
        second_skill_items = [i for i in second_plan.items if i.kind == "skill"]
        assert [(i.name, i.action) for i in second_skill_items] == [("security-review", "skip")]
        _write.apply(second_plan)
        entries_after = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
        assert entries_after == entries_before

        export_dir = tmp_path / "export-skill"
        _write.export_pod(project, export_dir)
        assert (export_dir / "skills" / "security-review" / "SKILL.md").is_file()

        reapply_plan = _pod_apply.plan_apply(project, export_dir)
        reapply_skill_items = [i for i in reapply_plan.items if i.kind == "skill"]
        assert [(i.name, i.action) for i in reapply_skill_items] == [("security-review", "skip")]

        summary = _recipes.summarize_recipe(recipe_dir)
        assert summary.skills == 1


# ── policy-pack recipes: structured predicates over the call, not text ───────────────────────


def test_git_safety_recipe_plans_policy_items_only(tmp_path: Path) -> None:
    """A policy pack has no role, member or pipeline to add -- applying it onto a lean fixture
    pod plans ``policy`` items only (ADR 0013 SS2, "Policy pack")."""
    project = "leangit"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = RECIPES_DIR / "git-safety"

        plan = _pod_apply.plan_apply(project, recipe_dir)

        assert plan.items, "git-safety should plan at least one item"
        assert all(item.kind == "policy" for item in plan.items), plan.items


def test_git_safety_blocks_force_push_after_apply(tmp_path: Path) -> None:
    """After ``apply``, a force-push is blocked for the implementer regardless of the exec
    allowlist -- ``git`` is allowlisted, so only the recipe's structured ``tool``/``matches``
    predicate over the call catches this, never the command classifier alone."""
    project = "leangit2"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = RECIPES_DIR / "git-safety"
        _write.apply(_pod_apply.plan_apply(project, recipe_dir))

        command = "git push --force origin main"
        text = _gate.render_tool_call("bash", {"command": command})
        call = _policy.ToolCallFacts(tool="bash", args={"command": command}, branch_of=lambda: "")

        action = _policy.policy_test(
            "pre_tool_call", "implementer", text, project=project, call=call
        )
        assert action == "block"


def test_secrets_guard_blocks_env_write_and_allows_a_plain_write(tmp_path: Path) -> None:
    """The path-shaped ``anyOf`` fires on a ``.env`` write regardless of content, and never on
    an ordinary file -- the negative case a fail-closed pack must not also over-trigger on."""
    project = "leansecrets"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = RECIPES_DIR / "secrets-guard"
        _write.apply(_pod_apply.plan_apply(project, recipe_dir))

        env_call = _policy.ToolCallFacts(
            tool="write", args={"path": "config/.env"}, branch_of=lambda: ""
        )
        env_text = _gate.render_tool_call("write", {"path": "config/.env", "content": "SECRET=1"})
        env_action = _policy.policy_test(
            "pre_tool_call", "implementer", env_text, project=project, call=env_call
        )
        assert env_action == "block"

        doc_call = _policy.ToolCallFacts(
            tool="write", args={"path": "README.md"}, branch_of=lambda: ""
        )
        doc_text = _gate.render_tool_call("write", {"path": "README.md", "content": "hello"})
        doc_action = _policy.policy_test(
            "pre_tool_call", "implementer", doc_text, project=project, call=doc_call
        )
        assert doc_action == "allow"


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
                    raw={},
                )
            return _rd.TurnResult(ok=True, output="APPROVE - injection risk fixed", raw={})
        return FakeDriver()(member_id, session_id, message, timeout, env)


def test_secure_build_recipe_dispatches_to_done_with_the_verdict_gate_observed_in_trace(
    tmp_path: Path,
) -> None:
    project = "webapp"
    with _seed_fixture_pod(tmp_path, project):
        recipe_dir = RECIPES_DIR / "secure-build"

        _write.apply(_pod_apply.plan_apply(project, recipe_dir))
        assert pod.pod_of(f"{project}-security-vetter") == project
        assert _arch.load_registry(project).source_of("security-vetter") == f"pod:{project}"
        assert "security-vetter" not in _arch.load_registry().archetypes

        result = _loaded(recipe_dir / "pipeline.yaml")
        assert result.spec is not None, result.errors

        _queue.enqueue_task_once(project, "add a login endpoint", channel="cli")
        runner = _SecureBuildRunner(project)
        results = _sweep.dispatch_pod(project, runner=runner, spec=result.spec)

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


def test_recipe_member_follows_the_fleets_rank_anchors_not_the_compiled_default(
    tmp_path: Path,
) -> None:
    """A recipe's own role, applied into the pod, gets the fleet's model, never the literal."""
    project = "fixture"
    with _seed_fixture_pod(tmp_path, project):
        current_home().model_registry_file.parent.mkdir(parents=True, exist_ok=True)
        current_home().model_registry_file.write_text(
            json.dumps(
                {
                    "default": "local/x",
                    "rankAnchors": {
                        "economy": "local/x",
                        "standard": "local/x",
                        "premium": "local/x",
                    },
                    "roles": {},
                }
            ),
            encoding="utf-8",
        )

        _write.apply(_pod_apply.plan_apply(project, _templates.RECIPES_DIR / "secure-build"))

        from docket.teams import fleet as _fleet

        assert _fleet.meta_get(pod.member_id(project, "security-vetter"), "model", "") == "local/x"


# ── docket pod recipes: the operator's own recipes directory (ADR 0013 SS1 rule 4-5) ─────────────


def test_operator_recipe_is_listed_and_applies_via_pod_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A recipe under the operator's own ``recipes/`` directory is listed with scope
    ``operator`` alongside every shipped recipe, and resolves by name for
    ``docket pod update`` exactly as a shipped one does."""
    project = "recipefixture"
    with _seed_fixture_pod(tmp_path, project):
        mine_dir = current_home().user_recipes_dir / "mine"
        (mine_dir / "policies").mkdir(parents=True)
        (mine_dir / "policies" / "x.yaml").write_text(
            "kind: policy\n"
            "name: x\n"
            "appliesTo: [implementer]\n"
            "when: {matches: 'nope'}\n"
            "then: block\n",
            encoding="utf-8",
        )

        infos = {info.name: info for info in _recipes.list_recipes()}
        assert infos["mine"].scope == "operator"
        assert infos["mine"].summary.policies == 1
        for shipped_name in REQUIRED_RECIPES:
            assert infos[shipped_name].scope == "shipped"

        plan = json.loads(
            _pod_cli("update", "mine", "--pod", project, "--dry-run", "--json").output
        )
        assert [(item["kind"], item["name"], item["action"]) for item in plan["items"]] == [
            ("policy", "x.yaml", "add")
        ]


def test_recipes_show_unknown_name_exits_1_naming_both_scopes(tmp_path: Path) -> None:
    """``docket pod recipes <unknown>`` exits 1, with a message naming both ``operator:``
    and ``shipped:`` recipe lists -- the same fail-closed error ``docket pod update``/
    ``docket init --recipe`` raise."""
    home = tmp_path / ".docket"
    with use_home(Home(home)):
        result = _pod_cli("recipes", "nope")

        assert result.exit_code == 1
        assert "operator:" in result.output
        assert "shipped:" in result.output


def test_a_recipe_step_env_survives_apply_and_export(tmp_path: Path) -> None:
    project = "envpod"
    with _seed_fixture_pod(tmp_path / "source", project):
        _write.apply(_pod_apply.plan_apply(project, RECIPES_DIR / "mutation"))
        export_dir = tmp_path / "exported"
        assert _pod_cli("export", str(export_dir), "--pod", project).exit_code == 0
        result = _loaded(export_dir / "pipeline.yaml")
        assert result.spec is not None, result.errors
        step = next(s for s in result.spec.steps if s.id == "check-mutation-score")
        assert step.env == {"MUTATION_THRESHOLD": "80", "MUTATION_CMD": "mutmut"}
