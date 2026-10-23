"""`docket init` and provisioning leave alone what they did not create, and refuse input they
cannot store faithfully (agent-lifecycle, cli-interface, input-validation)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.pods import build_pod
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import pod_members as _pod_members
from docket.kernel.home import Home, current_home, use_home
from docket.teams import fleet as _fleet
from docket.teams import pod_provisioning as _pp

SUBJECT = "docket.interfaces.cli.commands.agents"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setattr(_contract, "is_tty", lambda: False)
    home = tmp_path / "home"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        yield home


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _members() -> list[str]:
    return sorted(p.name for p in current_home().projects_dir.iterdir())


class TestProvisioningLeavesAWorkdirItDidNotCreate:
    def test_defect_60_87_a_preexisting_workdir_keeps_its_mode(self, tmp_path: Path) -> None:
        workdir = tmp_path / "existing"
        workdir.mkdir()
        workdir.chmod(0o755)

        _pp.provision_pod("demo", "research", location=str(workdir))

        assert _mode(workdir) == 0o755

    def test_defect_60_87_init_from_a_directory_keeps_that_directory_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cwd = tmp_path / "repo"
        cwd.mkdir()
        cwd.chmod(0o755)
        monkeypatch.chdir(cwd)

        result = runner.invoke(app, ["init", "demo", "--blueprint", "research"])

        assert result.exit_code == 0, result.output
        assert _mode(cwd) == 0o755

    def test_a_workdir_provisioning_creates_is_owner_only(self, tmp_path: Path) -> None:
        workdir = tmp_path / "made-here"

        _pp.provision_pod("demo", "research", location=str(workdir))

        assert _mode(workdir) == 0o700


class TestRemovingTheLastImplementerKeepsThePodsOwnData:
    def test_defect_82_memory_config_and_the_work_dir_survive(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        memory = current_home().pod_memory_path("demo")
        memory.write_text("{}")
        config = current_home().pod_config_dir("demo")
        config.mkdir(parents=True)
        (config / "roles.json").write_text("{}")
        scratch = current_home().pod_scratch_dir("demo")
        assert scratch.is_dir()

        _pod_members.remove_member("demo", "demo-implementer", yes=True)

        assert memory.is_file()
        assert (config / "roles.json").is_file()
        assert not scratch.exists()
        assert not current_home().pod_cache_dir("demo").exists()

    def test_defect_82_the_port_range_is_released_and_a_new_implementer_gets_one(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod_members.remove_member("demo", "demo-implementer", yes=True)

        assert _pod_members.add_members("demo", "implementer") == ["demo-implementer"]
        assert current_home().pod_scratch_dir("demo").is_dir()


class TestFromRefusesAnEntryWithoutABlueprint:
    def _spec(self, tmp_path: Path, entries: list[dict[str, object]]) -> str:
        path = tmp_path / "spec.json"
        path.write_text(json.dumps(entries))
        return str(path)

    def test_q5_an_entry_without_a_blueprint_is_refused_with_exit_2(self, tmp_path: Path) -> None:
        spec = self._spec(tmp_path, [{"id": "legacy", "codebase": str(tmp_path)}])

        result = runner.invoke(app, ["init", "--from", spec])

        assert result.exit_code == 2, result.output
        assert "blueprint" in result.output
        assert _members() == []

    def test_defect_36_a_traversal_id_without_a_blueprint_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        spec = self._spec(tmp_path, [{"id": "../escaped"}])

        result = runner.invoke(app, ["init", "--from", spec])

        assert result.exit_code == 2
        assert not (current_home().projects_dir.parent / "escaped").exists()
        assert _members() == []

    def test_q5_the_other_entries_of_the_file_still_provision(self, tmp_path: Path) -> None:
        code = tmp_path / "code"
        code.mkdir()
        spec = self._spec(
            tmp_path,
            [{"id": "legacy"}, {"id": "demo", "blueprint": "software", "codebase": str(code)}],
        )

        result = runner.invoke(app, ["init", "--from", spec])

        assert result.exit_code == 2
        assert _members() == ["demo-implementer", "demo-lead"]


class TestInitFromTheDirectoryHoldingTheHome:
    def test_defect_70_a_cwd_whose_dot_docket_is_the_home_applies_nothing(
        self, tmp_path: Path
    ) -> None:
        code = tmp_path / "code"
        home = code / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        (home / "pod.yaml").write_text("kind: pod\nname: demo\ndescription: from the home\n")
        with use_home(Home(home)):
            result = runner.invoke(app, ["init", "demo", str(code)])

            assert result.exit_code == 0, result.output
            assert _fleet.meta_get("demo-lead", "configSource", "") == ""
            assert "from the home" not in _fleet.meta_get("demo-lead", "description", "")
