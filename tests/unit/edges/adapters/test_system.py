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


class TestBwrapHidesDocketHome:
    """The jail binds the host read-only, which would expose docket's own store (secrets,
    sessions, traces of every pod); DOCKET_HOME is masked before the roots are bound."""

    def test_the_argv_masks_docket_home_before_binding_the_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.conftest import repoint_docket_home

        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)
        ws = tmp_path / "ws"
        ws.mkdir()
        assert "--tmpfs" not in _sys.bwrap_argv((ws,), "true")  # no home yet: nothing to hide
        home.mkdir()
        argv = _sys.bwrap_argv((ws,), "true")
        assert "--tmpfs" in argv
        mask = argv.index("--tmpfs")
        assert argv[mask + 1] == str(home)
        assert argv.index("--ro-bind") < mask < argv.index("--bind")

    @pytest.mark.skipif(not _sys.bwrap_available(), reason="bwrap not usable here")
    def test_a_jailed_command_cannot_read_the_secret_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.conftest import repoint_docket_home

        from docket.edges.adapters import toolbox

        home = tmp_path / "home"
        home.mkdir()
        (home / "secrets.json").write_text('{"K": "SECRET-VALUE-0b3e7"}')
        repoint_docket_home(monkeypatch, home)
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        out = toolbox.run_bash((ws,), f"cat {home / 'secrets.json'}; ls {home}", sandbox="auto")
        assert "SECRET-VALUE-0b3e7" not in (out.content or "")


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
        monkeypatch.setattr(_sys, "bwrap_available", lambda: True)
        monkeypatch.setattr(_sys, "docker_daemon_reachable", lambda: True)
        assert _sys.sandbox_availability().backend == "landlock"
        monkeypatch.setattr(_sys, "landlock_available", lambda: False)
        assert _sys.sandbox_availability().backend == "bwrap"
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
