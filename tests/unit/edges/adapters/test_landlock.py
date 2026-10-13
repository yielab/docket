"""Ruleset planning and the seccomp program, evaluated by a tiny BPF interpreter. No syscall is made."""

from __future__ import annotations

import struct

import pytest

from docket.edges.adapters import landlock

SUBJECT = "docket.edges.adapters.landlock"


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
