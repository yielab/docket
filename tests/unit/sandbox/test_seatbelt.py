"""Real git evidence helpers (`git_head_sha`, `git_merge_base`, `git_diff_stat`).

Each degrades to `None` rather than raising -- the same convention `git_current_branch`/
`git_changed_files` already use -- on a missing binary, a non-repository directory, or an
unresolvable ref. `subprocess.run` is monkeypatched throughout, mirroring
`tests/integration/test_system_adapter.py`'s pattern; no real git process ever runs here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.sandbox import docker as _docker
from docket.sandbox import landlock as _landlock
from docket.sandbox import launch as _launch
from docket.sandbox import seatbelt as _seatbelt

SUBJECT = "docket.sandbox.seatbelt"


# ── seatbelt backend ──────────────────────────────────────────────────────────


def _pin_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_seatbelt.sys, "prefix", "/opt/py")
    monkeypatch.setattr(_seatbelt.sys, "base_prefix", "/opt/py")
    monkeypatch.setattr(_seatbelt.os.path, "realpath", lambda p: str(p))
    monkeypatch.setattr(_seatbelt, "_mount_dirs", lambda roots: ([str(r) for r in roots], []))


_PROFILE_HEAD = (
    "(version 1)\n"
    "(deny default)\n"
    "(allow process-exec* process-fork sysctl-read mach-lookup file-read-metadata)\n"
    "(allow signal (target self))\n"
    '(allow file-read-data (literal "/"))\n'
    '(allow file-read* (subpath "/usr") (subpath "/bin") (subpath "/sbin") (subpath "/etc")'
    ' (subpath "/opt") (subpath "/private/etc") (subpath "/System/Library") (subpath "/Library")'
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
        )
        assert _seatbelt.seatbelt_profile(roots, False) == (
            _PROFILE_HEAD + body + "(deny network*)\n"
        )
        assert _seatbelt.seatbelt_profile(roots, True) == (
            _PROFILE_HEAD + body + "(allow network*)\n"
        )

    def test_a_read_only_grant_is_readable_and_never_writable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        profile = _seatbelt.seatbelt_profile((Path("/w/a"),), False, read_only=(Path("/h/tool"),))
        read_rule = next(line for line in profile.splitlines() if '(subpath "/usr")' in line)
        assert '(subpath "/h/tool")' in read_rule and "file-write" not in read_rule
        assert profile.count('"/h/tool"') == 1

    def test_paths_are_quoted_for_the_profile_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        profile = _seatbelt.seatbelt_profile((Path('/w/a"b\\c'),), True)
        assert '(subpath "/w/a\\"b\\\\c"))\n(allow network*)\n' in profile

    def test_guarded_git_paths_are_denied_after_the_grant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        monkeypatch.setattr(_seatbelt, "_mount_dirs", lambda roots: (["/w/a"], ["/w/a/.git/hooks"]))
        profile = _seatbelt.seatbelt_profile((Path("/w/a"),), False)
        assert profile.endswith(
            '(allow file-read* file-write* (subpath "/w/a"))\n'
            '(deny file-write* (subpath "/w/a/.git/hooks"))\n(deny network*)\n'
        )

    def test_argv_runs_sandbox_exec_with_the_profile_and_a_shell(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_profile_env(monkeypatch)
        argv = _seatbelt.seatbelt_argv((Path("/w/a"),), "echo hi", network=False)
        assert argv == [
            "/usr/bin/sandbox-exec",
            "-p",
            _seatbelt.seatbelt_profile((Path("/w/a"),), False),
            "/bin/sh",
            "-c",
            "echo hi",
        ]

    def test_available_only_on_darwin_with_sandbox_exec(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_PROBE", raising=False)
        monkeypatch.setattr(_seatbelt.os.path, "exists", lambda p: p == "/usr/bin/sandbox-exec")
        monkeypatch.setattr(_seatbelt.sys, "platform", "linux")
        assert _seatbelt.seatbelt_available() is False
        monkeypatch.setattr(_seatbelt.sys, "platform", "darwin")
        assert _seatbelt.seatbelt_available() is True
        monkeypatch.setattr(_seatbelt.os.path, "exists", lambda p: False)
        assert _seatbelt.seatbelt_available() is False

    def test_the_probe_override_hides_seatbelt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_seatbelt.sys, "platform", "darwin")
        monkeypatch.setattr(_seatbelt.os.path, "exists", lambda p: True)
        monkeypatch.setenv("DOCKET_SANDBOX_PROBE", "none")
        assert _seatbelt.seatbelt_available() is False

    def test_darwin_prefers_seatbelt_over_docker_and_is_overridable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.delenv("DOCKET_SANDBOX_PROBE", raising=False)
        monkeypatch.setattr(_seatbelt.sys, "platform", "darwin")
        monkeypatch.setattr(_seatbelt.os.path, "exists", lambda p: p == "/usr/bin/sandbox-exec")
        monkeypatch.setattr(_launch, "landlock_available", lambda: False)
        monkeypatch.setattr(_docker, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(_launch, "docker_daemon_reachable", lambda: True)
        availability = _launch.sandbox_availability("auto")
        assert availability.backend == "seatbelt"
        assert availability.landlock is False
        monkeypatch.setattr(_seatbelt.os.path, "exists", lambda p: False)
        assert _launch.sandbox_availability("auto").backend == "none"
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "seatbelt")
        assert _launch.sandbox_availability().backend == "seatbelt"


class TestRefNarrowingOnSeatbelt:
    def _linked(self, tmp_path: Path, head: str) -> tuple[Path, Path, Path]:
        wt, common = tmp_path / "wt", tmp_path / "main" / ".git"
        gitdir = common / "worktrees" / "wt"
        for d in (wt, gitdir, common / "objects", common / "refs", common / "logs" / "refs"):
            d.mkdir(parents=True)
        (gitdir / "HEAD").write_text(head)
        return wt, common, gitdir

    def test_seatbelt_allows_the_task_branch_dirs_after_the_ref_denies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt, common, gitdir = self._linked(tmp_path, "ref: refs/heads/docket/pod/wt\n")
        monkeypatch.setattr(_landlock, "git_dirs", lambda r: [gitdir, common])
        lines = _seatbelt.seatbelt_profile((wt,), False).splitlines()
        deny = lines.index(f'(deny file-write* (subpath "{common / "refs"}"))')
        branch = common / "refs" / "heads" / "docket" / "pod"
        allow = lines.index(f'(allow file-read* file-write* (subpath "{branch}"))')
        assert allow > deny
        assert f'(deny file-write* (subpath "{common / "packed-refs"}"))' in lines
