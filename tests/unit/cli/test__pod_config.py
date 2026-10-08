"""`docket pod apply|export|validate|plan|check|recipes|roles|policies`: the configuration half."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _pod, _pod_config, app
from docket.core import archetypes as _arch
from docket.core import pod_apply as _pod_apply
from docket.core import policy as _policy

SUBJECT = "docket.cli._pod_config"

_runner = CliRunner()

_ROLE = (
    "kind: role\n"
    "name: vetter\n"
    "scope: org\n"
    "modelClass: cheap\n"
    "soulTemplate: You vet things.\n"
    "agentsTemplate: Vetting protocol.\n"
)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=str(tmp_path / "code"))
    return home


def _pod_run(*args: str):  # type: ignore[no-untyped-def]
    return _runner.invoke(_pod.pod_app, list(args))


def _summary(**overrides: object) -> _pod_apply.RecipeSummary:
    fields: dict[str, object] = {
        "roles": 0,
        "policies": 0,
        "plugins": 0,
        "skills": 0,
        "members": 0,
        "settings": 0,
        "pipeline": "",
        "description": "",
    }
    fields.update(overrides)
    return _pod_apply.RecipeSummary(**fields)  # type: ignore[arg-type]


class TestPodCheck:
    def test_a_push_to_production_is_not_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _pod_run(
            "check", "git push origin production", "--role", "implementer", "--pod", "demo"
        )
        assert result.exit_code == 0
        assert "Result:" in result.output
        assert "Result: allow" not in result.output

    def test_a_read_only_command_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _pod_run("check", "git status", "--role", "implementer", "--pod", "demo")
        assert result.exit_code == 0
        assert "allow" in result.output

    def test_an_unknown_hook_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _pod_run("check", "x", "--role", "implementer", "--hook", "bogus", "--pod", "demo")
        assert result.exit_code == 2

    def test_the_role_is_required(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _pod_run("check", "ls", "--pod", "demo").exit_code == 2


class TestPodApply:
    def test_a_role_file_lands_in_the_pods_roles_overlay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        role = tmp_path / "vetter.yaml"
        role.write_text(_ROLE, encoding="utf-8")
        result = _pod_run("apply", str(role), "--pod", "demo")
        assert result.exit_code == 0
        stored = json.loads((_cfg.pod_config_dir("demo") / "roles.json").read_text())
        assert "vetter" in stored["roles"]
        assert _arch.load_registry("demo").get("vetter") is not None

    def test_dry_run_writes_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        role = tmp_path / "vetter.yaml"
        role.write_text(_ROLE, encoding="utf-8")
        result = _pod_run("apply", str(role), "--pod", "demo", "--dry-run", "--json")
        assert json.loads(result.output)["items"][0]["action"] == "add"
        assert not (_cfg.pod_config_dir("demo") / "roles.json").exists()

    def test_a_document_that_is_not_a_role_or_policy_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text("kind: pipeline\nname: p\nsteps:\n  - id: a\n    role: lead\n")
        assert _pod_run("apply", str(pipeline), "--pod", "demo").exit_code == 1

    def test_a_policy_file_is_copied_into_the_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        source = sorted(_cfg.policy_templates_dir().glob("*.yaml"))[0]
        result = _pod_run("apply", str(source), "--pod", "demo")
        assert result.exit_code == 0
        assert (_cfg.pod_config_dir("demo") / "policies" / source.name).is_file()

    def test_a_directory_is_planned_and_json_names_the_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        directory = tmp_path / "recipe"
        (directory / "roles").mkdir(parents=True)
        (directory / "roles" / "vetter.yaml").write_text(_ROLE, encoding="utf-8")
        result = _pod_run("apply", str(directory), "--pod", "demo", "--dry-run", "--json")
        assert result.exit_code == 0
        assert [i["kind"] for i in json.loads(result.output)["items"]] == ["role"]

    def test_no_argument_resyncs_and_an_in_sync_pod_is_a_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _pod_run("apply", "--pod", "demo")
        assert result.exit_code == 0
        assert "in sync" in result.output

    def test_json_needs_something_to_apply(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _pod_run("apply", "--pod", "demo", "--json").exit_code == 1


class TestPodExport:
    def test_export_writes_the_pods_scope_and_refuses_a_non_empty_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        target = tmp_path / "out"
        assert _pod_run("export", str(target), "--pod", "demo").exit_code == 0
        assert (target / "pod.yaml").is_file()
        assert _pod_run("export", str(target), "--pod", "demo").exit_code == 1
        assert _pod_run("export", str(target), "--pod", "demo", "--force").exit_code == 0

    def test_a_pod_is_required_off_a_registered_codebase(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DOCKET_POD", raising=False)
        assert _pod_run("export", str(tmp_path / "o")).exit_code == 1


class TestPodValidate:
    def test_an_invalid_role_exits_one_and_prints_the_message(self, tmp_path: Path) -> None:
        (tmp_path / "roles").mkdir()
        (tmp_path / "roles" / "bad.yaml").write_text("kind: banana\nname: x\n", encoding="utf-8")
        (tmp_path / "roles" / "good.yaml").write_text(_ROLE, encoding="utf-8")
        result = _pod_run("validate", str(tmp_path))
        assert result.exit_code == 1
        assert "bad.yaml" in result.output
        assert result.output.index("bad.yaml") < result.output.index("good.yaml")

    def test_one_file_is_validated_by_its_own_kind(self, tmp_path: Path) -> None:
        good = tmp_path / "role.yaml"
        good.write_text(_ROLE, encoding="utf-8")
        assert _pod_run("validate", str(good)).exit_code == 0

    def test_a_pipeline_step_naming_an_unknown_provider_is_invalid(self, tmp_path: Path) -> None:
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "kind: pipeline\nname: p\nsteps:\n  - id: a\n    role: lead\n    model: nope/x\n"
        )
        assert _pod_run("validate", str(pipeline)).exit_code == 1

    def test_a_missing_path_is_a_failure(self, tmp_path: Path) -> None:
        assert _pod_run("validate", str(tmp_path / "nope")).exit_code == 1


class TestPodPlan:
    def test_the_default_plan_lists_the_pods_hops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _pod_run("plan", "--pod", "demo")
        assert result.exit_code == 0
        assert "implementer" in result.output

    def test_an_invalid_pipeline_file_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        bad = tmp_path / "p.yaml"
        bad.write_text("kind: pipeline\nname: p\nsteps: []\n")
        assert _pod_run("plan", "--pod", "demo", "--pipeline", str(bad)).exit_code == 1


class TestLibraries:
    def test_recipes_lists_and_shows_json(self) -> None:
        listed = json.loads(_pod_run("recipes", "--json").output)
        assert any(r["name"] == "code-intel" for r in listed)
        shown = json.loads(_pod_run("recipes", "code-intel", "--json").output)
        assert shown["unjailed_mcp_servers"] == ["ast-grep"]

    def test_an_unknown_recipe_fails(self) -> None:
        assert _pod_run("recipes", "no-such-recipe").exit_code == 1

    def test_roles_list_and_show(self) -> None:
        rows = json.loads(_pod_run("roles", "--json").output)
        assert {"lead", "implementer"} <= {r["name"] for r in rows}
        shown = json.loads(_pod_run("roles", "tester", "--json").output)
        assert shown["source"] and shown["name"] == "tester"
        assert _pod_run("roles", "nonexistent").exit_code == 1

    def test_policies_list_show_and_plugins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _policy.install_policies()
        rows = json.loads(_pod_run("policies", "--json", "--pod", "demo").output)
        assert "block-destructive" in {r["id"] for r in rows}
        shown = json.loads(_pod_run("policies", "block-destructive").output)
        assert shown["id"] == "block-destructive"
        both = json.loads(_pod_run("policies", "--json", "--plugins").output)
        assert set(both) == {"policies", "plugins"}
        assert _pod_run("policies", "nope").exit_code == 1
        assert _pod_run("policies", "block-destructive", "--plugins").exit_code == 2


class TestRemovedNames:
    @pytest.mark.parametrize("name", ["validate", "pipeline", "roles", "policies", "plugins"])
    def test_a_removed_top_level_name_is_an_unknown_command(self, name: str) -> None:
        assert _runner.invoke(app, [name]).exit_code == 2

    def test_recipes_is_not_a_top_level_command(self) -> None:
        assert _runner.invoke(app, ["recipes"]).exit_code == 2


class TestRecipeRows:
    def test_brings_joins_only_the_parts_present(self) -> None:
        assert _pod_config._brings(_summary()) == "nothing"
        assert _pod_config._brings(_summary(roles=2, mcp_servers=("a",))) == "roles+mcp-servers"

    def test_the_json_row_names_the_servers_that_run_unjailed(self) -> None:
        row = _pod_config._info_dict(
            "code-intel",
            "shipped",
            "/r",
            _summary(mcp_servers=("ast-grep", "lsp"), unjailed_mcp_servers=("ast-grep",)),
        )
        assert row["mcp_servers"] == ["ast-grep", "lsp"]
        assert row["unjailed_mcp_servers"] == ["ast-grep"]

    def test_the_shipped_code_intel_recipe_declares_ast_grep_unjailed(self) -> None:
        summary = _pod_apply.summarize_recipe(_pod_apply.resolve_recipe("code-intel"))
        row = _pod_config._info_dict("code-intel", "shipped", "", summary)
        assert row["unjailed_mcp_servers"] == ["ast-grep"]
