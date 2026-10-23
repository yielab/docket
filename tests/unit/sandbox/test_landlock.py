"""Ruleset planning and the seccomp program, evaluated by a tiny BPF interpreter. No syscall is made."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from docket.edges.adapters import system as _sys
from docket.sandbox import docker as _docker
from docket.sandbox import landlock
from docket.sandbox import launch as _launch
from docket.sandbox import seatbelt as _seatbelt

SUBJECT = "docket.sandbox.landlock"


def _run(program: bytes, arch: int, nr: int, arg0: int) -> int:
    words = {0: nr, 4: arch, 16: arg0}
    insns = [struct.unpack("=HBBI", program[i : i + 8]) for i in range(0, len(program), 8)]
    acc = pc = 0
    while True:
        code, jt, jf, k = insns[pc]
        if code == 0x20:
            acc = words[k]
        elif code == 0x15:
            pc += jt if acc == k else jf
        elif code == 0x35:
            pc += jt if acc >= k else jf
        elif code == 0x06:
            return k
        pc += 1


ALLOW, EPERM = 0x7FFF0000, 0x00050001
X86 = 0xC000003E


class TestSocketFilter:
    def _x86(self) -> bytes:
        program = landlock.socket_filter("x86_64")
        assert program is not None
        return program

    @pytest.mark.parametrize("family", [2, 10])
    def test_inet_sockets_get_eperm(self, family: int) -> None:
        assert _run(self._x86(), X86, 41, family) == EPERM

    def test_unix_sockets_and_other_syscalls_pass(self) -> None:
        assert _run(self._x86(), X86, 41, 1) == ALLOW
        assert _run(self._x86(), X86, 0, 2) == ALLOW

    def test_io_uring_x32_and_foreign_arches_are_denied(self) -> None:
        assert _run(self._x86(), X86, 425, 0) == EPERM
        assert _run(self._x86(), X86, 0x40000029, 2) == EPERM
        assert _run(self._x86(), 0x40000003, 41, 1) == EPERM

    def test_aarch64_uses_its_own_socket_number(self) -> None:
        program = landlock.socket_filter("aarch64")
        assert program is not None
        assert _run(program, 0xC00000B7, 198, 2) == EPERM
        assert _run(program, 0xC00000B7, 41, 2) == ALLOW

    def test_an_uncovered_architecture_has_no_program(self) -> None:
        assert landlock.socket_filter("riscv64") is None


class TestPlanRuleset:
    def _plan(self, abi: int, network: bool = True) -> landlock.RulesetPlan:
        return landlock.plan_ruleset(
            abi,
            ("/work",),
            ("/usr", "/missing"),
            network,
            is_dir=lambda p: not p.startswith("/dev"),
            exists=lambda p: p != "/missing",
        )

    def test_handled_rights_follow_the_abi(self) -> None:
        assert landlock.handled_fs_for(1) == (1 << 13) - 1
        assert landlock.handled_fs_for(2) & landlock.FS_REFER
        assert landlock.handled_fs_for(3) & landlock.FS_TRUNCATE
        assert landlock.handled_fs_for(5) & landlock.FS_IOCTL_DEV
        assert not landlock.handled_fs_for(4) & landlock.FS_IOCTL_DEV

    def test_roots_get_everything_and_read_roots_only_read(self) -> None:
        plan = dict(self._plan(5).rules)
        assert plan["/work"] == landlock.handled_fs_for(5)
        assert plan["/usr"] == landlock.READ_RIGHTS
        assert "/missing" not in plan
        assert "/home" not in plan

    def test_the_shared_system_temp_dir_is_not_granted(self) -> None:
        plan = dict(self._plan(5).rules)
        assert "/tmp" not in plan

    def test_device_files_get_file_rights_only(self) -> None:
        plan = dict(self._plan(5).rules)
        assert plan["/dev/null"] == (
            landlock.FS_EXECUTE
            | landlock.FS_WRITE_FILE
            | landlock.FS_READ_FILE
            | landlock.FS_TRUNCATE
            | landlock.FS_IOCTL_DEV
        )
        assert plan["/dev/zero"] == landlock.FS_READ_FILE | landlock.FS_EXECUTE

    def test_tcp_is_handled_only_without_network_and_with_abi_4(self) -> None:
        both = landlock.NET_BIND_TCP | landlock.NET_CONNECT_TCP
        assert self._plan(4, network=False).handled_net == both
        assert self._plan(3, network=False).handled_net == 0
        assert self._plan(5, network=True).handled_net == 0


# ── landlock backend ──────────────────────────────────────────────────────────


class TestLandlockBackend:
    def test_argv_runs_the_jail_entry_with_the_roots_and_network_mode(self, tmp_path: Path) -> None:
        argv = landlock.landlock_argv((tmp_path,), "echo hi", network=False)
        assert argv[:3] == [_sys.sys.executable, "-m", "docket.sandbox.jail"]
        assert argv[argv.index("--rw") + 1] == str(tmp_path.resolve())
        assert argv[argv.index("--net") + 1] == "none"
        assert argv[-4:] == ["--", "/bin/sh", "-c", "echo hi"]
        assert landlock.landlock_argv((tmp_path,), "x")[argv.index("--net") + 1] == "open"

    def test_command_argv_passes_the_argv_through(self, tmp_path: Path) -> None:
        argv = landlock.landlock_command_argv((tmp_path,), ["srv", "--x"], network=True)
        assert argv[-3:] == ["--", "srv", "--x"]

    def test_landlock_is_probed_first_and_overridable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.setattr(landlock, "landlock_available", lambda: True)
        monkeypatch.setattr(_seatbelt, "seatbelt_available", lambda: False)
        monkeypatch.setattr(_docker, "docker_daemon_reachable", lambda: True)
        assert _launch.sandbox_availability("auto").backend == "landlock"
        monkeypatch.setattr(landlock, "landlock_available", lambda: False)
        assert _launch.sandbox_availability("auto").backend == "none"
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        assert _launch.sandbox_availability().backend == "landlock"

    def test_availability_follows_the_abi_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from docket.sandbox import landlock

        monkeypatch.delenv("DOCKET_SANDBOX_PROBE", raising=False)
        monkeypatch.setattr(landlock, "abi_version", lambda: 0)
        assert landlock.landlock_available() is False
        monkeypatch.setattr(landlock, "abi_version", lambda: 3)
        assert landlock.landlock_available() is True

    def test_the_probe_override_hides_the_kernel_feature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``DOCKET_SANDBOX_PROBE=none`` reports Landlock absent whatever the kernel says."""
        from docket.sandbox import landlock

        monkeypatch.setattr(landlock, "abi_version", lambda: 5)
        monkeypatch.setenv("DOCKET_SANDBOX_PROBE", "none")
        assert landlock.landlock_available() is False


# the Landlock git-dir grants and host-side git trust


class TestLandlockGitMounts:
    def _argv(self, root: Path, dirs: list[Path]) -> list[str]:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(landlock, "git_dirs", lambda r: dirs)
            return landlock.landlock_argv((root,), "true")

    def _values(self, argv: list[str], flag: str) -> list[str]:
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]

    def _linked(self, tmp_path: Path, head: str) -> tuple[Path, Path, Path]:
        wt, common = tmp_path / "wt", tmp_path / "main" / ".git"
        gitdir = common / "worktrees" / "wt"
        for d in (wt, gitdir, common / "objects", common / "refs"):
            d.mkdir(parents=True)
        (gitdir / "HEAD").write_text(head)
        return wt, common, gitdir

    def test_a_task_worktree_gets_only_its_branch_ref_directory(self, tmp_path: Path) -> None:
        wt, common, gitdir = self._linked(tmp_path, "ref: refs/heads/docket/pod/wt\n")
        rw = self._values(self._argv(wt, [gitdir, common]), "--rw")
        assert str(common) not in rw and str(common / "hooks") not in rw
        assert str(common / "refs") not in rw and str(common / "logs") not in rw
        assert {
            str(common / "objects"),
            str(common / "refs" / "heads" / "docket" / "pod"),
            str(common / "logs" / "refs" / "heads" / "docket" / "pod"),
            str(gitdir),
        } <= set(rw)

    @pytest.mark.parametrize(
        "head",
        [
            "ref: refs/heads/main\n",
            "ref: refs/heads/docket/pod/other\n",
            "ref: refs/heads/docket/wt\n",
            "ref: refs/heads/docket/../wt\n",
            "ref: refs/tags/docket/pod/wt\n",
            "0123456789abcdef0123456789abcdef01234567\n",
        ],
    )
    def test_a_worktree_not_on_its_own_task_branch_gets_no_ref_grant(
        self, tmp_path: Path, head: str
    ) -> None:
        wt, common, gitdir = self._linked(tmp_path, head)
        rw = self._values(self._argv(wt, [gitdir, common]), "--rw")
        assert not [p for p in rw if p.startswith(str(common / "refs")) or "/logs" in p]
        assert self._values(self._argv(wt, [gitdir, common]), "--ro") == [str(common)]

    def test_a_root_with_a_git_directory_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        argv = self._argv(tmp_path, [tmp_path / ".git"])
        assert ".git directory" in self._values(argv, "--refuse")[0]

    def test_a_root_with_a_git_file_is_not_refused(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: elsewhere\n")
        assert self._values(self._argv(tmp_path, []), "--refuse") == []
