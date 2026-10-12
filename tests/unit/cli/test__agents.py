"""`docket init` parses its arguments as Typer options and hands `run_init` one request."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docket.cli import _agents, app

SUBJECT = "docket.cli._agents"

runner = CliRunner()


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[_agents.InitRequest]:
    seen: list[_agents.InitRequest] = []

    def fake_run_init(req: _agents.InitRequest) -> int:
        seen.append(req)
        return 0

    monkeypatch.setattr(_agents, "run_init", fake_run_init)
    return seen


class TestParsing:
    def test_no_arguments_is_the_empty_request(self, requests: list) -> None:
        assert runner.invoke(app, ["init"]).exit_code == 0
        assert requests == [_agents.InitRequest()]

    def test_positionals_are_name_then_location(self, requests: list) -> None:
        runner.invoke(app, ["init", "myapp", "/src/myapp"])
        assert requests[0].name == "myapp"
        assert requests[0].location == "/src/myapp"

    def test_options_win_over_positionals(self, requests: list) -> None:
        runner.invoke(app, ["init", "pos", "/a", "--name", "Flag Name", "--codebase=/b"])
        assert (requests[0].name, requests[0].location) == ("Flag Name", "/b")

    def test_roster_blueprint_recipe_and_no_apply(self, requests: list) -> None:
        runner.invoke(
            app,
            ["init", "--pod", "full", "--with", "tester", "--blueprint", "ops", "--recipe", "tdd"],
        )
        req = requests[0]
        assert (req.full, req.with_roles, req.blueprint, req.recipe) == (
            True,
            "tester",
            "ops",
            "tdd",
        )
        runner.invoke(app, ["init", "--no-apply"])
        assert requests[1].no_apply is True

    def test_from_is_the_declarative_path(self, requests: list) -> None:
        runner.invoke(app, ["init", "--from", "spec.yaml"])
        assert requests[0].from_file == "spec.yaml"


class TestUsageErrors:
    def test_an_undefined_option_exits_2_before_anything_runs(self, requests: list) -> None:
        result = runner.invoke(app, ["init", "--portfolio"])
        assert result.exit_code == 2
        assert "No such option" in result.output
        assert requests == []

    def test_pod_accepts_only_full(self, requests: list) -> None:
        result = runner.invoke(app, ["init", "--pod", "half"])
        assert result.exit_code == 2
        assert requests == []

    def test_from_excludes_every_other_option(self, requests: list) -> None:
        result = runner.invoke(app, ["init", "--from", "spec.yaml", "--name", "x"])
        assert result.exit_code == 2
        assert requests == []

    def test_a_third_positional_is_a_usage_error(self, requests: list) -> None:
        assert runner.invoke(app, ["init", "a", "/b", "c"]).exit_code == 2
        assert requests == []


class TestInitInstallsTheBaselinePolicies:
    """security-gates spec: on the first run `docket init` installs the shipped policy
    templates, so the `pre_input`/`pre_tool_call` screens are not no-ops in a fresh home."""

    def test_a_fresh_home_gets_the_shipped_policies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.conftest import repoint_docket_home

        import docket.config as _cfg

        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)
        code = tmp_path / "code"
        code.mkdir()
        (code / "README.md").write_text("# x\n")
        rc = _agents.run_init(_agents.InitRequest(name="demo", location=str(code)))
        assert rc == 0
        installed = sorted(p.name for p in _cfg.POLICIES_DIR.glob("*.yaml"))
        assert "prompt-injection.yaml" in installed
        assert "block-destructive.yaml" in installed or "block-destructive.json" in installed
