"""Shipped recipe bundles (``templates/recipes/<name>/``) are real, tested and configurable.

Each recipe is data only: role YAML(s), a pipeline YAML, a small `pod.yaml`, and an optional
policy pack, applied in one command (`docket pod <p> apply`, `core.pod_apply`). The tests below
read exactly what the wheel ships (`docket.config.recipes_dir()`), so a recipe that fails to
validate, resolve against a real roster, or actually dispatch fails here first, never only in an
operator's hands. See pipeline-format.spec.md, role-archetypes.spec.md and
pod-blueprints.spec.md ("Pod manifests: apply").
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _config, _pod
from docket.core import archetypes as _arch
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import pod_apply as _pod_apply
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


def _policy_yaml_files(recipe_dir: Path) -> list[Path]:
    policies_dir = recipe_dir / "policies"
    return sorted(policies_dir.glob("*.yaml")) if policies_dir.is_dir() else []


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
def test_recipe_applies_cleanly_to_a_fixture_pod(
    recipe_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``docket pod <p> apply <recipe_dir>`` leaves every pipeline step resolvable."""
    project = "fixture"
    _seed_fixture_pod(tmp_path, monkeypatch, project)

    _pod_apply.apply(_pod_apply.plan_apply(project, recipe_dir))

    result = _pipeline.load_pipeline((recipe_dir / "pipeline.yaml").read_text(encoding="utf-8"))
    assert result.spec is not None, result.errors

    roster = _dispatch.pod_full_roster(project)
    registry = _arch.load_registry(project)
    plan = _orch.resolve_plan(result.spec, roster, registry=registry)

    skipped: list[str] = []
    for node in plan.nodes:
        units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
        skipped.extend(u.step_id for u in units if u.skipped)
    assert skipped == [], f"recipe {recipe_dir.name!r} leaves steps unresolvable: {skipped}"


def test_pod_apply_resolves_a_shipped_recipe_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``docket pod <p> apply secure-build`` applies the shipped recipe, as ``init --recipe``
    does -- a README can print a command that needs no path into the installed package."""
    from docket.cli import _pod as _cli_pod

    project = "byname"
    _seed_fixture_pod(tmp_path, monkeypatch, project)

    _cli_pod.dispatch(project, "apply", ["secure-build"])

    assert "security-vetter" in _dispatch.pod_full_roster(project)


def test_apply_with_an_invalid_setting_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad ``pod.yaml`` setting refuses before any pod-scoped file is written."""
    project = "guarded"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    bad_dir = tmp_path / "bad-recipe"
    bad_dir.mkdir()
    (bad_dir / "pod.yaml").write_text("settings:\n  mcpServers: [zzz]\n", encoding="utf-8")

    with pytest.raises(_pod_apply.PodApplyError, match="zzz"):
        _pod_apply.plan_apply(project, bad_dir)

    assert not _cfg.pod_config_dir(project).exists()


def test_apply_with_an_invalid_policy_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A policy file that fails ``validate_policy`` (an uncompilable regex) refuses before any
    pod-scoped file is written, naming the offending file."""
    project = "badpolicy"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    bad_dir = tmp_path / "bad-recipe"
    (bad_dir / "policies").mkdir(parents=True)
    (bad_dir / "policies" / "broken.json").write_text(
        json.dumps(
            {
                "id": "broken",
                "applies_to": ["implementer"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "(unclosed"},
                "action": "block",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(_pod_apply.PodApplyError, match=r"broken\.json"):
        _pod_apply.plan_apply(project, bad_dir)

    assert not _cfg.pod_config_dir(project).exists()


def test_apply_writes_a_recipes_policy_pack_into_the_pods_own_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``secure-build``'s policy pack lands in the pod's own directory, never the fleet-wide
    one; a second apply plans it ``skip`` and writes no second audit entry."""
    project = "policied"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    recipe_dir = RECIPES_DIR / "secure-build"
    src = recipe_dir / "policies" / "require-approval-secret-writes.yaml"

    plan = _pod_apply.plan_apply(project, recipe_dir)
    policy_items = [i for i in plan.items if i.kind == "policy"]
    assert [(i.name, i.action) for i in policy_items] == [(src.name, "add")]
    _pod_apply.apply(plan)

    dest = _cfg.pod_config_dir(project) / "policies" / src.name
    assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    assert not (_cfg.POLICIES_DIR / src.name).exists()
    assert dest in _policy.policy_files(project)

    entries_before = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
    second_plan = _pod_apply.plan_apply(project, recipe_dir)
    second_policy_items = [i for i in second_plan.items if i.kind == "policy"]
    assert [(i.name, i.action) for i in second_policy_items] == [(src.name, "skip")]
    _pod_apply.apply(second_plan)
    entries_after = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
    assert entries_after == entries_before


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

    _pod_apply.apply(_pod_apply.plan_apply(project, recipe_dir))
    assert pod.pod_of(f"{project}-security-vetter") == project
    assert _arch.load_registry(project).source_of("security-vetter") == f"pod:{project}"
    assert "security-vetter" not in _arch.load_registry().archetypes

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


# ── export_pod: the round trip is the proof ──────────────────────────────────


def _explain_json(agent_id: str, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    _config.dispatch("explain", [agent_id, "--json"])
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def _normalized(report: dict[str, object], project: str) -> dict[str, object]:
    """Drop *project*'s own name plus each pod's own `configSource`/`configDigest` (a
    different applied directory per pod, asserted separately by the caller) -- an
    equal-length pod's report should then match exactly."""
    text = json.dumps(report).replace(project, "PROJECT")
    normalized: dict[str, object] = json.loads(text)
    normalized.pop("configSource", None)
    normalized.pop("configDigest", None)
    return normalized


def test_export_then_apply_round_trip_matches_config_explain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Export -> apply into a fresh pod -> `config explain --json` agrees once normalized;
    also covers the CLI's non-empty-directory refusal and its `--force` override."""
    source_project = "podsrc"
    target_project = "poddst"  # same length as source_project -- see `_normalized`
    _seed_fixture_pod(tmp_path / "source", monkeypatch, source_project)

    recipe_dir = RECIPES_DIR / "secure-build"
    _pod_apply.apply(_pod_apply.plan_apply(source_project, recipe_dir))
    _pod.dispatch(source_project, "config", ["set", "approvalMode", "refuse"])

    export_dir = tmp_path / "exported"
    _pod.dispatch(source_project, "export", [str(export_dir)])
    assert (export_dir / "roles" / "security-vetter.yaml").is_file()
    assert (export_dir / "roles" / "security-vetter.md").is_file()
    assert (export_dir / "pipeline.yaml").is_file()
    assert (export_dir / "pod.yaml").is_file()
    # The export regenerates the policy as short-form YAML (not a byte copy of the recipe's
    # own file), so the two are compared by parsed content, not bytes.
    assert _policy.read_policy(
        export_dir / "policies" / "require-approval-secret-writes.yaml"
    ) == _policy.read_policy(recipe_dir / "policies" / "require-approval-secret-writes.yaml")

    with pytest.raises(typer.Exit) as exc:
        _pod.dispatch(source_project, "export", [str(export_dir)])
    assert exc.value.exit_code == 1
    _pod.dispatch(source_project, "export", [str(export_dir), "--force"])  # overwrites cleanly

    # Round trip: re-planning this pod's own export against itself plans every item `skip` --
    # the schema-header/regenerated-short-form export is still recognized as unchanged.
    reapply_plan = _pod_apply.plan_apply(source_project, export_dir)
    assert [item.action for item in reapply_plan.items] == ["skip"] * len(reapply_plan.items)

    source_report = _explain_json(f"{source_project}-security-vetter", capsys)

    _seed_fixture_pod(tmp_path / "target", monkeypatch, target_project)
    _pod_apply.apply(_pod_apply.plan_apply(target_project, export_dir))

    target_report = _explain_json(f"{target_project}-security-vetter", capsys)

    # Each pod's own configuration-of-record: the source pod was applied from `recipe_dir`,
    # the target pod from `export_dir` -- different directories, each still `drift: no`
    # since neither was edited after its own `apply`.
    assert source_report["configSource"] == str(recipe_dir.resolve())
    assert source_report["configDigest"] == _pod_apply.directory_digest(recipe_dir)
    assert source_report["drift"] == "no"
    assert target_report["configSource"] == str(export_dir.resolve())
    assert target_report["configDigest"] == _pod_apply.directory_digest(export_dir)
    assert target_report["drift"] == "no"

    assert _normalized(source_report, source_project) == _normalized(target_report, target_project)


def test_export_writes_only_this_pods_own_scope_never_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A global role and a fleet-wide policy, installed alongside this pod's own pod-scoped
    role/policy, must never appear in an export."""
    project = "guardedexp"
    _seed_fixture_pod(tmp_path, monkeypatch, project)

    _arch.add_user_archetype(
        {
            "name": "global-role",
            "scope": "org",
            "modelClass": "cheap",
            "editRights": "write",
            "toolProfile": "full",
            "tokenBudget": 4000,
            "soulTemplate": "# SOUL\n",
            "agentsTemplate": "# AGENTS\n",
            "gateContract": {"kind": "none"},
        }
    )  # global overlay -- no `project` given
    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    (_cfg.POLICIES_DIR / "global-policy.json").write_text(
        json.dumps(
            {
                "id": "global-policy",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "x"},
                "action": "require_approval",
            }
        ),
        encoding="utf-8",
    )

    _pod_apply.apply(_pod_apply.plan_apply(project, RECIPES_DIR / "secure-build"))
    pod_policies_dir = _cfg.pod_config_dir(project) / "policies"
    pod_policies_dir.mkdir(parents=True, exist_ok=True)
    policy_text = (
        RECIPES_DIR / "secure-build" / "policies" / "require-approval-secret-writes.yaml"
    ).read_text(encoding="utf-8")
    (pod_policies_dir / "require-approval-secret-writes.yaml").write_text(
        policy_text, encoding="utf-8"
    )
    _pod.dispatch(project, "config", ["set", "approvalMode", "refuse"])

    export_dir = tmp_path / "export-out"
    _pod_apply.export_pod(project, export_dir)

    assert sorted(p.name for p in (export_dir / "roles").iterdir()) == [
        "security-vetter.md",
        "security-vetter.yaml",
    ]
    assert sorted(p.name for p in (export_dir / "policies").iterdir()) == [
        "require-approval-secret-writes.yaml"
    ]
    # The export regenerates the policy as short-form YAML, so it is compared by parsed
    # content, not bytes.
    assert _policy.read_policy(
        export_dir / "policies" / "require-approval-secret-writes.yaml"
    ) == _policy.read_policy(Path(pod_policies_dir / "require-approval-secret-writes.yaml"))
    assert (export_dir / "pipeline.yaml").is_file()

    import yaml as _yaml

    manifest = _yaml.safe_load((export_dir / "pod.yaml").read_text(encoding="utf-8"))
    assert manifest == {
        "kind": "pod",
        "name": project,
        "members": ["implementer", "security-vetter"],
        "settings": {"approvalMode": "refuse"},
    }


# ── configSource/configDigest: the pod's configuration of record (ADR 0012 §2 rule 5) ──


def test_apply_records_config_source_and_digest_and_explain_reports_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`apply` records `configSource`/`configDigest`; editing the applied directory afterward
    makes `config explain --json` report `drift: yes` against the unchanged recorded digest."""
    project = "recorded"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    recipe_copy = tmp_path / "recipe-copy"
    shutil.copytree(RECIPES_DIR / "secure-build", recipe_copy)

    _pod_apply.apply(_pod_apply.plan_apply(project, recipe_copy))

    settings = pod.PodSettings.load_for(project)
    assert settings.config_source == str(recipe_copy.resolve())
    assert settings.config_digest == _pod_apply.directory_digest(recipe_copy)

    lead_id = pod.member_id(project, "lead")
    report = _explain_json(lead_id, capsys)
    assert report["configSource"] == str(recipe_copy.resolve())
    assert report["configDigest"] == settings.config_digest
    assert report["drift"] == "no"

    policy_file = recipe_copy / "policies" / "require-approval-secret-writes.yaml"
    policy_file.write_text(policy_file.read_text(encoding="utf-8") + "\n# edited\n", "utf-8")

    drifted_report = _explain_json(lead_id, capsys)
    assert drifted_report["configDigest"] == settings.config_digest  # recorded value unchanged
    assert drifted_report["drift"] == "yes"

    # Written only by `apply` -- `config set` refuses both by name, naming `apply` as the
    # writer (not the generic "unknown pod setting" message every other unknown key gets).
    capsys.readouterr()
    with pytest.raises(typer.Exit) as exc:
        _pod.dispatch(project, "config", ["set", "configSource", "/tmp/whatever"])
    assert exc.value.exit_code == 1
    assert "written by apply" in capsys.readouterr().err

    # A `pod.yaml` `settings` mapping cannot carry them either -- refused the same way any
    # unknown setting already is, since both are deliberately outside `PodSettings.KEYS`.
    bad_dir = tmp_path / "bad-recipe"
    bad_dir.mkdir()
    (bad_dir / "pod.yaml").write_text(
        "settings:\n  configDigest: " + "0" * 64 + "\n", encoding="utf-8"
    )
    with pytest.raises(_pod_apply.PodApplyError, match="configDigest"):
        _pod_apply.plan_apply(project, bad_dir)


def test_apply_records_config_source_from_every_validated_apply_all_skip_included(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second, byte-identical directory at another path still moves the recorded
    `configSource`/`configDigest` even though every item plans `skip` -- the record must not
    stay pointing at the first directory once a second one is applied (ADR 0013 §1 rule 3)."""
    project = "reconfigured"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    dir_a = tmp_path / "recipe-a"
    shutil.copytree(RECIPES_DIR / "secure-build", dir_a)
    _pod_apply.apply(_pod_apply.plan_apply(project, dir_a))

    dir_b = tmp_path / "recipe-b"
    shutil.copytree(RECIPES_DIR / "secure-build", dir_b)

    entries_before = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
    second_plan = _pod_apply.plan_apply(project, dir_b)
    assert [item.action for item in second_plan.items] == ["skip"] * len(second_plan.items)
    _pod_apply.apply(second_plan)
    entries_after = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
    assert entries_after == entries_before  # all-skip: no new audit entry

    settings = pod.PodSettings.load_for(project)
    assert settings.config_source == str(dir_b.resolve())
    assert settings.config_digest == _pod_apply.directory_digest(dir_b)


def test_export_default_dir_refuses_a_non_empty_codebase_docket_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docket pod <p> export` with no argument defaults to `<codebase>/.docket` (ADR 0012 §2
    rule 5); a non-empty one there still refuses without `--force`."""
    project = "exportdefault"
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    home = tmp_path / "home" / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
    _pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=str(codebase))

    default_dir = codebase / ".docket"
    default_dir.mkdir()
    (default_dir / "marker.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(typer.Exit) as exc:
        _pod.dispatch(project, "export", [])
    assert exc.value.exit_code == 1
    assert not (default_dir / "pod.yaml").exists()

    _pod.dispatch(project, "export", ["--force"])
    assert (default_dir / "pod.yaml").is_file()

    # The exported default directory re-applies as a no-op.
    reapply_plan = _pod_apply.plan_apply(project, default_dir)
    assert [item.action for item in reapply_plan.items] == ["skip"] * len(reapply_plan.items)


def test_recipe_member_follows_the_fleets_rank_anchors_not_the_compiled_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recipe's own role, applied into the pod, gets the fleet's model, never the literal."""
    project = "fixture"
    _seed_fixture_pod(tmp_path, monkeypatch, project)
    _cfg.MODEL_REGISTRY_FILE.write_text(
        json.dumps(
            {
                "default": "local/x",
                "rankAnchors": {"economy": "local/x", "standard": "local/x", "premium": "local/x"},
                "roles": {},
            }
        ),
        encoding="utf-8",
    )

    _pod_apply.apply(_pod_apply.plan_apply(project, _cfg.recipes_dir() / "secure-build"))

    from docket.core import fleet as _fleet

    assert _fleet.meta_get(pod.member_id(project, "security-vetter"), "model", "") == "local/x"
