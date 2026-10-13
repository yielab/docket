"""Real git evidence helpers (`git_head_sha`, `git_merge_base`, `git_diff_stat`).

Each degrades to `None` rather than raising -- the same convention `git_current_branch`/
`git_changed_files` already use -- on a missing binary, a non-repository directory, or an
unresolvable ref. `subprocess.run` is monkeypatched throughout, mirroring
`tests/integration/test_system_adapter.py`'s pattern; no real git process ever runs here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docket.edges.adapters import system as _sys

SUBJECT = "docket.edges.adapters.system"


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


# ── git_head_sha ──────────────────────────────────────────────────────────────


class TestGitHeadSha:
    def test_returns_stripped_sha_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        sha = "a" * 40
        monkeypatch.setattr(
            _sys.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=sha + "\n"),
        )
        assert _sys.git_head_sha("/tmp/repo") == sha

    def test_none_when_not_a_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(_sys.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _sys.git_head_sha("/tmp/notrepo") is None

    def test_none_when_git_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise AssertionError("must not shell out without git")

        monkeypatch.setattr(_sys.subprocess, "run", boom)
        assert _sys.git_head_sha("/tmp/repo") is None

    def test_none_on_missing_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)

        def raise_fnf(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise FileNotFoundError

        monkeypatch.setattr(_sys.subprocess, "run", raise_fnf)
        assert _sys.git_head_sha("/tmp/repo") is None

    def test_none_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)

        def raise_timeout(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise _sys.subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(_sys.subprocess, "run", raise_timeout)
        assert _sys.git_head_sha("/tmp/repo") is None


# ── git_merge_base ────────────────────────────────────────────────────────────


class TestGitMergeBase:
    def test_returns_stripped_sha_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        sha = "b" * 40
        monkeypatch.setattr(
            _sys.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=sha + "\n"),
        )
        assert _sys.git_merge_base("/tmp/repo", "main") == sha

    def test_none_for_unknown_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(_sys.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _sys.git_merge_base("/tmp/repo", "no-such-branch") is None

    def test_none_when_git_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise AssertionError("must not shell out without git")

        monkeypatch.setattr(_sys.subprocess, "run", boom)
        assert _sys.git_merge_base("/tmp/repo", "main") is None


# ── git_diff_stat ─────────────────────────────────────────────────────────────


class TestGitDiffStat:
    def test_parses_files_insertions_and_deletions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        summary = " 2 files changed, 10 insertions(+), 3 deletions(-)\n"
        monkeypatch.setattr(
            _sys.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=summary),
        )
        assert _sys.git_diff_stat("/tmp/repo", "abc123") == {
            "files": 2,
            "insertions": 10,
            "deletions": 3,
        }

    def test_singular_wording_still_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        summary = " 1 file changed, 1 insertion(+)\n"
        monkeypatch.setattr(
            _sys.subprocess,
            "run",
            lambda *a, **k: _FakeCompleted(returncode=0, stdout=summary),
        )
        assert _sys.git_diff_stat("/tmp/repo", "abc123") == {
            "files": 1,
            "insertions": 1,
            "deletions": 0,
        }

    def test_empty_summary_reports_all_zero_not_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(
            _sys.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
        )
        assert _sys.git_diff_stat("/tmp/repo", "abc123") == {
            "files": 0,
            "insertions": 0,
            "deletions": 0,
        }

    def test_none_for_unresolvable_base(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(_sys.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _sys.git_diff_stat("/tmp/repo", "no-such-ref") is None

    def test_none_when_not_a_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: True)
        monkeypatch.setattr(_sys.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
        assert _sys.git_diff_stat("/tmp/notrepo", "HEAD") is None

    def test_none_when_git_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_available", lambda: False)

        def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
            raise AssertionError("must not shell out without git")

        monkeypatch.setattr(_sys.subprocess, "run", boom)
        assert _sys.git_diff_stat("/tmp/repo", "HEAD") is None


class TestDesktopNotificationsAvailable:
    def test_linux_needs_a_session_and_notify_send(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys.sys, "platform", "linux")
        monkeypatch.setattr(_sys, "_which", lambda binary: binary == "notify-send")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert _sys.desktop_notifications_available() is False
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert _sys.desktop_notifications_available() is True
        monkeypatch.setattr(_sys, "_which", lambda binary: False)
        assert _sys.desktop_notifications_available() is False

    def test_macos_needs_only_osascript(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys.sys, "platform", "darwin")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(_sys, "_which", lambda binary: binary == "osascript")
        assert _sys.desktop_notifications_available() is True


# ── landlock backend ──────────────────────────────────────────────────────────


class TestLandlockBackend:
    def test_argv_runs_the_jail_entry_with_the_roots_and_network_mode(self, tmp_path: Path) -> None:
        argv = _sys.landlock_argv((tmp_path,), "echo hi", network=False)
        assert argv[:3] == [_sys.sys.executable, "-m", "docket.jail"]
        assert argv[argv.index("--rw") + 1] == str(tmp_path.resolve())
        assert argv[argv.index("--net") + 1] == "none"
        assert argv[-4:] == ["--", "/bin/sh", "-c", "echo hi"]
        assert _sys.landlock_argv((tmp_path,), "x")[argv.index("--net") + 1] == "open"

    def test_command_argv_passes_the_argv_through(self, tmp_path: Path) -> None:
        argv = _sys.landlock_command_argv((tmp_path,), ["srv", "--x"], network=True)
        assert argv[-3:] == ["--", "srv", "--x"]

    def test_landlock_is_probed_first_and_overridable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.setattr(_sys, "landlock_available", lambda: True)
        monkeypatch.setattr(_sys, "docker_daemon_reachable", lambda: True)
        assert _sys.sandbox_availability("auto").backend == "landlock"
        monkeypatch.setattr(_sys, "landlock_available", lambda: False)
        assert _sys.sandbox_availability("auto").backend == "none"
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        assert _sys.sandbox_availability().backend == "landlock"

    def test_availability_follows_the_abi_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from docket.edges.adapters import landlock

        monkeypatch.delenv("DOCKET_SANDBOX_PROBE", raising=False)
        monkeypatch.setattr(landlock, "abi_version", lambda: 0)
        assert _sys.landlock_available() is False
        monkeypatch.setattr(landlock, "abi_version", lambda: 3)
        assert _sys.landlock_available() is True

    def test_the_probe_override_hides_the_kernel_feature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``DOCKET_SANDBOX_PROBE=none`` reports Landlock absent whatever the kernel says."""
        from docket.edges.adapters import landlock

        monkeypatch.setattr(landlock, "abi_version", lambda: 5)
        monkeypatch.setenv("DOCKET_SANDBOX_PROBE", "none")
        assert _sys.landlock_available() is False


class TestChosenBackend:
    def _hosts(self, monkeypatch: pytest.MonkeyPatch, *, landlock: bool, docker: bool) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.setattr(_sys, "landlock_available", lambda: landlock)
        monkeypatch.setattr(_sys, "seatbelt_available", lambda: False)
        monkeypatch.setattr(_sys, "docker_daemon_reachable", lambda: docker)

    def test_auto_never_picks_docker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._hosts(monkeypatch, landlock=False, docker=True)
        availability = _sys.sandbox_availability("auto")
        assert availability.backend == "none"
        assert availability.docker is False

    def test_docker_choice_uses_docker_even_where_landlock_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._hosts(monkeypatch, landlock=True, docker=True)
        assert _sys.sandbox_availability("docker").backend == "docker"

    def test_docker_choice_with_no_daemon_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._hosts(monkeypatch, landlock=True, docker=False)
        assert _sys.sandbox_availability("docker").backend == "none"

    def test_the_recorded_fleet_choice_is_read_when_none_is_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import fleet

        self._hosts(monkeypatch, landlock=True, docker=True)
        assert _sys.sandbox_availability().backend == "landlock"
        fleet.set_sandbox_backend("docker")
        assert _sys.sandbox_availability().backend == "docker"

    def test_the_env_override_still_forces_a_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._hosts(monkeypatch, landlock=False, docker=False)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        assert _sys.sandbox_availability("auto").backend == "landlock"

    def test_bwrap_is_no_longer_a_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._hosts(monkeypatch, landlock=False, docker=False)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        assert _sys.sandbox_availability("auto").backend == "none"
        assert not hasattr(_sys, "bwrap_argv")


class TestTaskEnvironmentCacheDir:
    def test_cache_dir_sets_the_six_variables(self, tmp_path: Path) -> None:
        env = _sys.task_environment({"A": "1"}, cache_dir=tmp_path)

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
        env = _sys.task_environment({"HOME": "/elsewhere"}, cache_dir=tmp_path)

        assert env["HOME"] == "/elsewhere"

    def test_without_cache_dir_home_is_inherited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/inherited")

        assert _sys.task_environment()["HOME"] == "/inherited"


# ── jail_launch / run_verify_cmd under a jail ─────────────────────────────────


class TestJailLaunch:
    @pytest.fixture(autouse=True)
    def _no_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys, "git_identity_env", lambda root: {})

    def test_landlock_argv_roots_extra_rw_and_minimal_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("SOME_SECRET", "x")
        cache = tmp_path / "cache"
        launch = _sys.jail_launch(
            (tmp_path,), "echo hi", "landlock", network=False, env={"A": "1"}, extra_rw=(cache,)
        )
        assert launch.argv[:3] == [_sys.sys.executable, "-m", "docket.jail"]
        rw = [launch.argv[i + 1] for i, a in enumerate(launch.argv) if a == "--rw"]
        assert rw == [str(tmp_path.resolve()), str(cache.resolve())]
        assert launch.argv[launch.argv.index("--net") + 1] == "none"
        assert launch.argv[-3:] == ["/bin/sh", "-c", "echo hi"]
        assert launch.env == {"PATH": "/usr/bin", "A": "1"}

    def test_cache_dir_is_a_rw_root_and_sets_home_under_the_overlay(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        launch = _sys.jail_launch(
            (tmp_path,), "true", "landlock", env={"HOME": "/kept"}, cache_dir=cache
        )
        rw = [launch.argv[i + 1] for i, a in enumerate(launch.argv) if a == "--rw"]
        assert rw == [str(tmp_path.resolve()), str(cache.resolve())]
        assert launch.env is not None
        assert launch.env["HOME"] == "/kept"
        assert launch.env["UV_CACHE_DIR"] == str(cache)

    def test_seatbelt_runs_the_shell_under_sandbox_exec(self, tmp_path: Path) -> None:
        launch = _sys.jail_launch((tmp_path,), "echo hi", "seatbelt", network=False)
        assert launch.argv[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert "(deny network*)" in launch.argv[2]
        assert launch.argv[-3:] == ["/bin/sh", "-c", "echo hi"]

    def test_seatbelt_command_argv_runs_the_server_without_a_shell(self, tmp_path: Path) -> None:
        argv = _sys.seatbelt_command_argv((tmp_path,), ["srv", "--x"], network=True)
        assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert argv[3:] == ["srv", "--x"]

    def test_docker_names_a_container_and_leaves_the_process_env_to_the_cli(
        self, tmp_path: Path
    ) -> None:
        launch = _sys.jail_launch((tmp_path,), "true", "docker", env={"A": "1"})
        assert launch.env is None
        assert launch.container.startswith("docket-sbx-")
        assert launch.argv[:2] == ["docker", "run"]
        assert "A=1" in launch.argv

    def test_no_backend_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            _sys.jail_launch((tmp_path,), "true", "none")


class TestVerifyUnderJail:
    def test_no_usable_backend_runs_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        marker = tmp_path / "ran"
        passed, output = _sys.run_verify_cmd(
            f"touch {marker}", str(tmp_path), jail=_sys.JailPolicy()
        )
        assert passed is False
        assert "verify not run" in output
        assert not marker.exists()

    def test_high_risk_refusal_comes_before_the_jail(self, tmp_path: Path) -> None:
        passed, output = _sys.run_verify_cmd(
            "git push origin production", str(tmp_path), jail=_sys.JailPolicy()
        )
        assert passed is False
        assert "refused" in output


# ── seatbelt backend ──────────────────────────────────────────────────────────


def _pin_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_sys.sys, "prefix", "/opt/py")
    monkeypatch.setattr(_sys.os.path, "realpath", lambda p: str(p))
    monkeypatch.setattr(_sys, "_mount_dirs", lambda roots: ([str(r) for r in roots], []))
    monkeypatch.setattr(_sys.tempfile, "gettempdir", lambda: "/var/tmp/x")


_PROFILE_HEAD = (
    "(version 1)\n"
    "(deny default)\n"
    "(allow process-exec* process-fork sysctl-read mach-lookup file-read-metadata)\n"
    "(allow signal (target self))\n"
    '(allow file-read* (subpath "/usr") (subpath "/bin") (subpath "/sbin") (subpath "/etc")'
    ' (subpath "/private/etc") (subpath "/System/Library") (subpath "/Library")'
    ' (subpath "/opt/py"))\n'
    '(allow file-read* (literal "/dev/random") (literal "/dev/urandom"))\n'
    '(allow file-read* file-write* (literal "/dev/null") (literal "/dev/zero")'
    ' (literal "/dev/tty") (literal "/dev/dtracehelper"))\n'
)


class TestSeatbeltBackend:
    def test_profile_is_byte_exact_for_two_roots_under_both_network_modes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        roots = (Path("/w/a"), Path("/w/b"))
        body = (
            '(allow file-read* file-write* (subpath "/w/a"))\n'
            '(allow file-read* file-write* (subpath "/w/b"))\n'
            '(allow file-read* file-write* (subpath "/var/tmp/x"))\n'
        )
        assert _sys.seatbelt_profile(roots, False) == (_PROFILE_HEAD + body + "(deny network*)\n")
        assert _sys.seatbelt_profile(roots, True) == (_PROFILE_HEAD + body + "(allow network*)\n")

    def test_paths_are_quoted_for_the_profile_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        monkeypatch.setattr(_sys.tempfile, "gettempdir", lambda: '/w/a"b\\c')
        profile = _sys.seatbelt_profile((Path('/w/a"b\\c'),), True)
        assert '(subpath "/w/a\\"b\\\\c"))\n(allow network*)\n' in profile

    def test_guarded_git_paths_are_denied_after_the_grant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        monkeypatch.setattr(_sys.tempfile, "gettempdir", lambda: "/w/a")
        monkeypatch.setattr(_sys, "_mount_dirs", lambda roots: (["/w/a"], ["/w/a/.git/hooks"]))
        profile = _sys.seatbelt_profile((Path("/w/a"),), False)
        assert profile.endswith(
            '(allow file-read* file-write* (subpath "/w/a"))\n'
            '(deny file-write* (subpath "/w/a/.git/hooks"))\n(deny network*)\n'
        )

    def test_argv_runs_sandbox_exec_with_the_profile_and_a_shell(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        argv = _sys.seatbelt_argv((Path("/w/a"),), "echo hi", network=False)
        assert argv == [
            "/usr/bin/sandbox-exec",
            "-p",
            _sys.seatbelt_profile((Path("/w/a"),), False),
            "/bin/sh",
            "-c",
            "echo hi",
        ]

    def test_available_only_on_darwin_with_sandbox_exec(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_PROBE", raising=False)
        monkeypatch.setattr(_sys.os.path, "exists", lambda p: p == "/usr/bin/sandbox-exec")
        monkeypatch.setattr(_sys.sys, "platform", "linux")
        assert _sys.seatbelt_available() is False
        monkeypatch.setattr(_sys.sys, "platform", "darwin")
        assert _sys.seatbelt_available() is True
        monkeypatch.setattr(_sys.os.path, "exists", lambda p: False)
        assert _sys.seatbelt_available() is False

    def test_the_probe_override_hides_seatbelt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_sys.sys, "platform", "darwin")
        monkeypatch.setattr(_sys.os.path, "exists", lambda p: True)
        monkeypatch.setenv("DOCKET_SANDBOX_PROBE", "none")
        assert _sys.seatbelt_available() is False

    def test_darwin_prefers_seatbelt_over_docker_and_is_overridable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.delenv("DOCKET_SANDBOX_PROBE", raising=False)
        monkeypatch.setattr(_sys.sys, "platform", "darwin")
        monkeypatch.setattr(_sys.os.path, "exists", lambda p: p == "/usr/bin/sandbox-exec")
        monkeypatch.setattr(_sys, "landlock_available", lambda: False)
        monkeypatch.setattr(_sys, "docker_daemon_reachable", lambda: True)
        availability = _sys.sandbox_availability("auto")
        assert availability.backend == "seatbelt"
        assert availability.landlock is False
        monkeypatch.setattr(_sys.os.path, "exists", lambda p: False)
        assert _sys.sandbox_availability("auto").backend == "none"
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "seatbelt")
        assert _sys.sandbox_availability().backend == "seatbelt"


# the Landlock git-dir grants and host-side git trust


class TestLandlockGitMounts:
    def _argv(self, root: Path, dirs: list[Path]) -> list[str]:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(_sys, "git_dirs", lambda r: dirs)
            return _sys.landlock_argv((root,), "true")

    def _values(self, argv: list[str], flag: str) -> list[str]:
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]

    def test_a_linked_worktree_gets_the_writable_parts_not_the_git_dir(
        self, tmp_path: Path
    ) -> None:
        wt, common = tmp_path / "wt", tmp_path / "main" / ".git"
        gitdir = common / "worktrees" / "wt"
        for d in (wt, gitdir, common / "objects", common / "refs"):
            d.mkdir(parents=True)
        argv = self._argv(wt, [gitdir, common])
        rw = self._values(argv, "--rw")
        assert str(common) not in rw and str(common / "hooks") not in rw
        assert {str(common / "objects"), str(common / "refs"), str(gitdir)} <= set(rw)
        assert self._values(argv, "--ro") == [str(common)]

    def test_a_root_with_a_git_directory_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        argv = self._argv(tmp_path, [tmp_path / ".git"])
        assert ".git directory" in self._values(argv, "--refuse")[0]

    def test_a_root_with_a_git_file_is_not_refused(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: elsewhere\n")
        assert self._values(self._argv(tmp_path, []), "--refuse") == []


class TestTrustedWorktree:
    def test_git_dirs_answers_from_the_record(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        gitdir, common = tmp_path / "c" / "worktrees" / "wt", tmp_path / "c"
        _sys.trust_worktree(str(wt), str(gitdir), str(common))
        assert _sys.git_dirs(wt) == [gitdir.resolve(), common.resolve()]

    def test_host_git_names_the_recorded_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt = tmp_path / "wt2"
        wt.mkdir()
        seen: dict[str, Any] = {}

        def fake(argv: list[str], **kw: Any) -> _FakeCompleted:
            seen.update(kw)
            return _FakeCompleted(0, "main\n")

        monkeypatch.setattr(_sys.subprocess, "run", fake)
        _sys.trust_worktree(str(wt), str(tmp_path / "g"), str(tmp_path / "c"))
        _sys._git_run(str(wt), ["status"], 5)
        env = seen["env"]
        assert env["GIT_DIR"] == str(tmp_path / "g") and env["GIT_COMMON_DIR"] == str(
            tmp_path / "c"
        )
        assert env["GIT_WORK_TREE"] == str(wt.resolve())

    def test_a_poisoned_worktree_config_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt, gitdir, common = tmp_path / "wt3", tmp_path / "g3", tmp_path / "c3"
        for d in (wt, gitdir, common):
            d.mkdir()
        (gitdir / "config.worktree").write_text("[core]\n")
        (common / "config").write_text("[extensions]\n\tworktreeConfig = true\n")
        ran: list[object] = []
        monkeypatch.setattr(_sys.subprocess, "run", lambda *a, **k: ran.append(a))
        _sys.trust_worktree(str(wt), str(gitdir), str(common))
        out = _sys._git_run(str(wt), ["status"], 5)
        assert out.returncode == 1 and ran == []
