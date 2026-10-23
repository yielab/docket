"""`docket init` parses its arguments as Typer options and hands `run_init` one request."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.interfaces.cli.commands import agents as _agents
from docket.interfaces.cli.commands import contract as _contract
from docket.kernel.home import Home, current_home, use_home
from docket.platform import process as _process

SUBJECT = "docket.interfaces.cli.commands.agents"

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

    def test_a_fresh_home_gets_the_shipped_policies(self, tmp_path: Path) -> None:

        home = tmp_path / "home"
        with use_home(Home(home)):
            code = tmp_path / "code"
            code.mkdir()
            (code / "README.md").write_text("# x\n")
            rc = _agents.run_init(_agents.InitRequest(name="demo", location=str(code)))
            assert rc == 0
            installed = sorted(p.name for p in current_home().policies_dir.glob("*.yaml"))
            assert "prompt-injection.yaml" in installed
            assert "block-destructive.yaml" in installed or "block-destructive.json" in installed


def test_init_closes_with_the_sandbox_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The output ends with a `This machine` block naming the sandbox posture."""

    with use_home(Home(tmp_path / "home")):
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        code = tmp_path / "code"
        code.mkdir()
        assert _agents.run_init(_agents.InitRequest(name="demo", location=str(code))) == 0
        out = capsys.readouterr().out
        tail = out[out.index("This machine") :]
        assert "Sandbox   off. The agent's commands run with your user's permissions." in tail
        assert "Turn it on: docket setup sandbox on" in tail


def _repo(tmp_path: Path, step: str = "sh scripts/migrate.sh") -> Path:
    code = tmp_path / "code"
    (code / ".docket").mkdir(parents=True)
    (code / ".docket" / "pipeline.yaml").write_text(
        f"name: p\nsteps:\n  - id: migrate\n    run: {step}\n"
    )
    return code


def _pod_exists() -> bool:
    return (current_home().projects_dir / "demo-lead").is_dir()


class TestInitAsksBeforeApplyingRepositoryCommands:
    """A repository's run-on-this-machine items need the operator's OK before init applies them."""

    @pytest.fixture(autouse=True)
    def _tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_contract, "is_tty", lambda: False)

    def test_no_terminal_creates_nothing_and_prints_the_code(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "demo", str(_repo(tmp_path))])
        assert result.exit_code == 2
        assert not _pod_exists()
        assert "sh scripts/migrate.sh" in result.output
        assert "docket init --accept " in result.output

    @pytest.mark.parametrize(
        ("gate", "label"),
        [
            ("verify: make check", 'verify command "build"'),
            ("gate: {external: ./ci.sh}", 'external gate "build"'),
        ],
    )
    def test_a_gate_command_alone_needs_the_code(
        self, tmp_path: Path, gate: str, label: str
    ) -> None:
        code = tmp_path / "code"
        (code / ".docket").mkdir(parents=True)
        (code / ".docket" / "pipeline.yaml").write_text(
            f"name: p\nsteps:\n  - build: implementer\n    {gate}\n"
        )
        result = runner.invoke(app, ["init", "demo", str(code)])
        assert result.exit_code == 2 and not _pod_exists()
        assert label in result.output and "docket init --accept " in result.output

    def test_accept_with_the_printed_code_creates_the_pod_and_audits(self, tmp_path: Path) -> None:
        from docket.governance.audit import read_audit

        code = _repo(tmp_path)
        out = runner.invoke(app, ["init", "demo", str(code), "--json"])
        review = __import__("json").loads(out.output)
        assert out.exit_code == 2 and review["status"] == "needs_review"
        ok = runner.invoke(app, ["init", "demo", str(code), "--accept", review["reviewCode"]])
        assert ok.exit_code == 0 and _pod_exists()
        assert any(e.get("action") == "repo.allow" for e in read_audit())

    def test_a_wrong_code_exits_2_without_printing_the_current_code(self, tmp_path: Path) -> None:
        code = _repo(tmp_path)
        first = __import__("json").loads(
            runner.invoke(app, ["init", "demo", str(code), "--json"]).output
        )
        result = runner.invoke(app, ["init", "demo", str(code), "--accept", "000000"])
        assert result.exit_code == 2 and not _pod_exists()
        assert first["reviewCode"] not in result.output
        assert "since review code 000000" in result.output

    def test_a_terminal_y_creates_the_pod_and_is_remembered_per_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_contract, "is_tty", lambda: True)
        monkeypatch.setattr(_process, "desktop_notifications_available", lambda: False)
        code = _repo(tmp_path)
        yes = runner.invoke(app, ["init", "demo", str(code)], input="y\n")
        assert yes.exit_code == 0 and _pod_exists()
        assert "Runs on this machine" in yes.output and "Adds to the team" in yes.output
        monkeypatch.setattr(_contract, "is_tty", lambda: False)
        import shutil

        shutil.rmtree(current_home().projects_dir / "demo-lead")
        shutil.rmtree(current_home().projects_dir / "demo-implementer", ignore_errors=True)
        current_home().fleet_file.unlink(missing_ok=True)
        again = runner.invoke(app, ["init", "demo", str(code)])
        assert again.exit_code == 0

        with use_home(Home(tmp_path / "second-home")):
            assert runner.invoke(app, ["init", "demo", str(code)]).exit_code == 2

    def test_a_terminal_n_creates_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_contract, "is_tty", lambda: True)
        result = runner.invoke(app, ["init", "demo", str(_repo(tmp_path))], input="n\n")
        assert result.exit_code == 2 and not _pod_exists()

    def test_a_shell_in_allow_commands_exits_2(self, tmp_path: Path) -> None:
        code = tmp_path / "code"
        (code / ".docket").mkdir(parents=True)
        (code / ".docket" / "pod.yaml").write_text(
            "kind: pod\nname: x\nsettings:\n  allowCommands: [bash]\n"
        )
        result = runner.invoke(app, ["init", "demo", str(code)])
        assert result.exit_code == 2 and not _pod_exists()
        assert "bash" in result.output and "make, npm" in result.output

    def test_a_shipped_recipe_by_name_never_asks(self, tmp_path: Path) -> None:
        code = tmp_path / "code"
        code.mkdir()
        result = runner.invoke(app, ["init", "demo", str(code), "--recipe", "tdd"])
        assert result.exit_code == 0 and _pod_exists()


def _teams_repo(tmp_path: Path) -> Path:
    code = tmp_path / "code"
    for team in ("a", "b"):
        (code / ".docket" / "teams" / team).mkdir(parents=True)
        (code / ".docket" / "teams" / team / "pod.yaml").write_text(
            f"kind: pod\nname: {team}\ndescription: team {team}\n"
        )
    return code


class TestInitInARepositoryWithTeams:
    """`.docket/teams/<pod>/` holds one team per pod; `init` picks one by name."""

    def test_the_named_team_is_applied_and_recorded(self, tmp_path: Path) -> None:
        from docket.teams import fleet as _fleet

        code = _teams_repo(tmp_path)
        result = runner.invoke(app, ["init", "--name", "a", "--codebase", str(code)])
        assert result.exit_code == 0, result.output
        source = _fleet.meta_get("a-lead", "configSource", "")
        assert source.endswith("teams/a")

    def test_no_name_exits_2_naming_the_teams(self, tmp_path: Path) -> None:
        code = _teams_repo(tmp_path)
        result = runner.invoke(app, ["init", "--codebase", str(code)])
        assert result.exit_code == 2
        assert "a, b" in result.output
        assert not (current_home().projects_dir / "code-lead").exists()
