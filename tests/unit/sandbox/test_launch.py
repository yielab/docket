"""The real jail adapter (`Launcher`): which backend a host can use, the argv and environment a
jailed command gets, and the verification command run under it. The backend probes answer as
`launcher_with` says; no jail is ever entered here."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from tests.support.fakes import FakeGit, launcher_with

from docket.kernel.home import Home, use_home
from docket.kernel.jail import JailPolicy
from docket.sandbox import landlock as _landlock
from docket.sandbox import seatbelt as _seatbelt
from docket.sandbox.launch import Launcher
from docket.teams import fleet

SUBJECT = "docket.sandbox.launch"


class TestChosenBackend:
    def _hosts(self, monkeypatch: pytest.MonkeyPatch, *, landlock: bool, docker: bool) -> Launcher:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        return launcher_with(landlock=landlock, seatbelt=False, docker=docker)

    def test_auto_never_picks_docker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        launcher = self._hosts(monkeypatch, landlock=False, docker=True)
        availability = launcher.sandbox_availability("auto")
        assert availability.backend == "none"
        assert availability.docker is False

    def test_docker_choice_uses_docker_even_where_landlock_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launcher = self._hosts(monkeypatch, landlock=True, docker=True)
        assert launcher.sandbox_availability("docker").backend == "docker"

    def test_docker_choice_with_no_daemon_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        launcher = self._hosts(monkeypatch, landlock=True, docker=False)
        assert launcher.sandbox_availability("docker").backend == "none"

    def test_the_recorded_fleet_choice_is_read_when_none_is_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launcher = self._hosts(monkeypatch, landlock=True, docker=True)
        assert launcher.sandbox_availability().backend == "landlock"
        fleet.set_sandbox_backend("docker")
        assert launcher.sandbox_availability().backend == "docker"

    def test_the_env_override_still_forces_a_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        launcher = self._hosts(monkeypatch, landlock=False, docker=False)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        assert launcher.sandbox_availability("auto").backend == "landlock"


class TestTaskEnvironmentCacheDir:
    def test_cache_dir_sets_the_six_variables(self, tmp_path: Path) -> None:
        env = launcher_with().task_environment({"A": "1"}, cache_dir=tmp_path)

        for name in (
            "HOME",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "UV_CACHE_DIR",
            "PIP_CACHE_DIR",
            "npm_config_cache",
        ):
            assert env[name] == str(tmp_path)
        assert env["A"] == "1"

    def test_the_overlay_still_wins_over_the_cache_variables(self, tmp_path: Path) -> None:
        env = launcher_with().task_environment({"HOME": "/elsewhere"}, cache_dir=tmp_path)

        assert env["HOME"] == "/elsewhere"

    def test_without_cache_dir_home_is_inherited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/inherited")

        assert launcher_with().task_environment()["HOME"] == "/inherited"


# ── jail_launch / run_command under a jail ─────────────────────────────────


class TestJailLaunch:
    @pytest.fixture(autouse=True)
    def _no_identity(self, fake_git: FakeGit) -> None:
        """``FakeGit`` has no git identity to add to the jail's environment."""

    def test_landlock_argv_roots_extra_rw_and_minimal_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("SOME_SECRET", "x")
        # /usr/bin/git is the Xcode shim on macOS, whose first run alone can pass 2s.
        monkeypatch.setattr(_landlock, "git_dirs", lambda root: [])
        cache = tmp_path / "cache"
        launch = launcher_with().jail_launch(
            (tmp_path,), "echo hi", "landlock", network=False, env={"A": "1"}, extra_rw=(cache,)
        )
        assert launch.argv[:3] == [sys.executable, "-m", "docket.sandbox.jail"]
        rw = [launch.argv[i + 1] for i, a in enumerate(launch.argv) if a == "--rw"]
        assert rw[:2] == [str(tmp_path.resolve()), str(cache.resolve())]
        assert launch.argv[launch.argv.index("--net") + 1] == "none"
        assert launch.argv[-3:] == ["/bin/sh", "-c", "echo hi"]
        assert launch.env is not None and "SOME_SECRET" not in launch.env
        assert launch.env["PATH"] == "/usr/bin" and launch.env["A"] == "1"
        assert launch.env["TMPDIR"] == rw[2]

    def test_cache_dir_is_a_rw_root_and_sets_home_under_the_overlay(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        launch = launcher_with().jail_launch(
            (tmp_path,), "true", "landlock", env={"HOME": "/kept"}, cache_dir=cache
        )
        rw = [launch.argv[i + 1] for i, a in enumerate(launch.argv) if a == "--rw"]
        assert rw[:2] == [str(tmp_path.resolve()), str(cache.resolve())]
        assert launch.env is not None
        assert launch.env["HOME"] == "/kept"
        assert launch.env["UV_CACHE_DIR"] == str(cache)

    def test_seatbelt_runs_the_shell_under_sandbox_exec(self, tmp_path: Path) -> None:
        launch = launcher_with().jail_launch((tmp_path,), "echo hi", "seatbelt", network=False)
        assert launch.argv[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert "(deny network*)" in launch.argv[2]
        assert launch.argv[-3:] == ["/bin/sh", "-c", "echo hi"]

    def test_seatbelt_command_argv_runs_the_server_without_a_shell(self, tmp_path: Path) -> None:
        argv = _seatbelt.seatbelt_command_argv((tmp_path,), ["srv", "--x"], network=True)
        assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert argv[3:] == ["srv", "--x"]

    def test_docker_names_a_container_and_leaves_the_process_env_to_the_cli(
        self, tmp_path: Path
    ) -> None:
        launch = launcher_with().jail_launch((tmp_path,), "true", "docker", env={"A": "1"})
        assert launch.env is None
        assert launch.container.startswith("docket-sbx-")
        assert launch.argv[:2] == ["docker", "run"]
        assert "A=1" in launch.argv

    def test_no_backend_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            launcher_with().jail_launch((tmp_path,), "true", "none")

    def test_a_read_only_grant_is_ro_for_landlock_never_rw(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_landlock, "git_dirs", lambda root: [])
        tool = tmp_path / "toolchain"
        tool.mkdir()
        launch = launcher_with().jail_launch(
            (tmp_path / "w",), "true", "landlock", read_only=(tool,)
        )
        ro = [launch.argv[i + 1] for i, a in enumerate(launch.argv) if a == "--ro"]
        rw = [launch.argv[i + 1] for i, a in enumerate(launch.argv) if a == "--rw"]
        assert str(tool.resolve()) in ro
        assert str(tool.resolve()) not in rw

    def test_a_read_only_grant_is_a_ro_bind_mount_for_docker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_landlock, "git_dirs", lambda root: [])
        tool, gone = tmp_path / "toolchain", tmp_path / "gone"
        tool.mkdir()
        launch = launcher_with().jail_launch((tmp_path,), "true", "docker", read_only=(tool, gone))
        assert f"{tool.resolve()}:{tool.resolve()}:ro" in launch.argv
        assert not any(str(gone) in a for a in launch.argv)


class TestVerifyUnderJail:
    def test_no_usable_backend_runs_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        marker = tmp_path / "ran"
        code, output = launcher_with().run_command(
            f"touch {marker}", str(tmp_path), jail=JailPolicy()
        )
        assert code is None
        assert "verify not run" in output
        assert not marker.exists()

    def test_high_risk_refusal_comes_before_the_jail(self, tmp_path: Path) -> None:
        code, output = launcher_with().run_command(
            "git push origin production", str(tmp_path), jail=JailPolicy()
        )
        assert code is None
        assert "refused" in output


class TestPrivateJailTmp:
    def test_the_dir_lives_under_the_cache_dir_and_is_private(self, tmp_path: Path) -> None:
        tmp = launcher_with().jail_tmp_dir((tmp_path / "w",), tmp_path / "cache")
        assert tmp == tmp_path / "cache" / "tmp"
        assert tmp.stat().st_mode & 0o777 == 0o700

    def test_without_a_cache_dir_it_lives_under_docket_home_keyed_by_the_root(
        self, tmp_path: Path
    ) -> None:
        with use_home(Home(tmp_path / "home")):
            a = launcher_with().jail_tmp_dir((tmp_path / "a",), None)
            b = launcher_with().jail_tmp_dir((tmp_path / "b",), None)
            assert a != b and a.parent == tmp_path / "home" / "jail-tmp"
            assert a.stat().st_mode & 0o777 == 0o700
            assert launcher_with().jail_tmp_dir((tmp_path / "a",), None) == a

    @pytest.mark.parametrize("backend", ["landlock", "seatbelt"])
    def test_launch_exports_and_grants_the_private_dir(self, backend: str, tmp_path: Path) -> None:
        root = tmp_path / "w"
        root.mkdir()
        launch = launcher_with().jail_launch((root,), "true", backend)  # type: ignore[arg-type]
        assert launch.env is not None
        tmp = launch.env["TMPDIR"]
        assert launch.env["TMP"] == launch.env["TEMP"] == tmp
        assert Path(tmp).is_dir() and Path(tmp).stat().st_mode & 0o777 == 0o700
        assert any(tmp in part for part in launch.argv)

    def test_docker_keeps_the_container_tmp(self, tmp_path: Path) -> None:
        root = tmp_path / "w"
        root.mkdir()
        launch = launcher_with().jail_launch((root,), "true", "docker")
        assert "TMPDIR" not in " ".join(launch.argv)
