"""Landlock and seccomp through ctypes: the Linux execution envelope's kernel layer.

``plan_ruleset`` and ``socket_filter`` are pure; only ``abi_version``, ``enforce`` and
``install_socket_filter`` make syscalls. See specs/functional/security-gates.spec.md item 10."""

from __future__ import annotations

import ctypes
import os
import platform
import struct
import sys
from collections.abc import Callable
from dataclasses import dataclass

from docket.kernel.errors import Unavailable

SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
CREATE_RULESET_VERSION = 1 << 0
RULE_PATH_BENEATH = 1
RULE_NET_PORT = 2

FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_REMOVE_DIR = 1 << 4
FS_REMOVE_FILE = 1 << 5
FS_MAKE_CHAR = 1 << 6
FS_MAKE_DIR = 1 << 7
FS_MAKE_REG = 1 << 8
FS_MAKE_SOCK = 1 << 9
FS_MAKE_FIFO = 1 << 10
FS_MAKE_BLOCK = 1 << 11
FS_MAKE_SYM = 1 << 12
FS_REFER = 1 << 13
FS_TRUNCATE = 1 << 14
FS_IOCTL_DEV = 1 << 15
NET_BIND_TCP = 1 << 0
NET_CONNECT_TCP = 1 << 1

_FS_BASE = (1 << 13) - 1
_FILE_RIGHTS = FS_EXECUTE | FS_WRITE_FILE | FS_READ_FILE | FS_TRUNCATE | FS_IOCTL_DEV
READ_RIGHTS = FS_EXECUTE | FS_READ_FILE | FS_READ_DIR

DEFAULT_RO = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/opt")
DEFAULT_RO_FILES = ("/dev/zero", "/dev/urandom")
DEFAULT_RW_FILES = ("/dev/null", "/dev/tty")

PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000
_EPERM = 1
_AF_INET, _AF_INET6 = 2, 10
_X32_BIT = 0x40000000
_IO_URING_SETUP = 425
_ARCHES = {
    "x86_64": (0xC000003E, 41),
    "aarch64": (0xC00000B7, 198),
}

_BPF_LD_W_ABS = 0x20
_BPF_JEQ_K = 0x15
_BPF_JGE_K = 0x35
_BPF_RET_K = 0x06
_OFF_NR, _OFF_ARCH, _OFF_ARG0 = 0, 4, 16


class LandlockError(Unavailable):
    """The kernel layer could not be built or enforced."""


@dataclass(frozen=True)
class RulesetPlan:
    """What a ruleset handles and grants, computed without a syscall."""

    abi: int
    handled_fs: int
    handled_net: int
    rules: tuple[tuple[str, int], ...]


def handled_fs_for(abi: int) -> int:
    handled = _FS_BASE
    if abi >= 2:
        handled |= FS_REFER
    if abi >= 3:
        handled |= FS_TRUNCATE
    if abi >= 5:
        handled |= FS_IOCTL_DEV
    return handled


def default_ro_roots() -> tuple[str, ...]:
    # A venv's interpreter and stdlib live under base_prefix, often in the operator's home.
    return tuple(dict.fromkeys((*DEFAULT_RO, sys.prefix, sys.base_prefix)))


def plan_ruleset(
    abi: int,
    rw: tuple[str, ...],
    ro: tuple[str, ...],
    network: bool,
    *,
    is_dir: Callable[[str], bool] = os.path.isdir,
    exists: Callable[[str], bool] = os.path.exists,
) -> RulesetPlan:
    """Every right the ABI knows is handled; rw roots get all of them, ro roots read and execute."""
    handled = handled_fs_for(abi)
    rules: dict[str, int] = {}

    def grant(path: str, access: int) -> None:
        if not exists(path):
            return
        mask = access if is_dir(path) else access & _FILE_RIGHTS
        rules[path] = rules.get(path, 0) | (mask & handled)

    for path in ro:
        grant(path, READ_RIGHTS)
    for path in DEFAULT_RO_FILES:
        grant(path, READ_RIGHTS)
    for path in rw:
        grant(path, handled)
    for path in DEFAULT_RW_FILES:
        grant(path, handled)
    net = 0 if network or abi < 4 else NET_BIND_TCP | NET_CONNECT_TCP
    return RulesetPlan(abi, handled, net, tuple(rules.items()))


@dataclass(frozen=True)
class _Insn:
    """One BPF instruction; a jump target is an offset or the name of a labelled instruction."""

    code: int
    jt: str | int
    jf: str | int
    k: int
    label: str = ""


def socket_filter(machine: str | None = None) -> bytes | None:
    """The BPF program denying inet sockets, or None on an architecture it does not cover."""
    arch = _ARCHES.get(machine or platform.machine())
    if arch is None:
        return None
    audit_arch, socket_nr = arch
    x86 = audit_arch == 0xC000003E
    prog: list[_Insn] = [
        _Insn(_BPF_LD_W_ABS, 0, 0, _OFF_ARCH),
        _Insn(_BPF_JEQ_K, 0, "deny", audit_arch),
        _Insn(_BPF_LD_W_ABS, 0, 0, _OFF_NR),
    ]
    if x86:
        prog.append(_Insn(_BPF_JGE_K, "deny", 0, _X32_BIT))
    prog += [
        _Insn(_BPF_JEQ_K, "deny", 0, _IO_URING_SETUP),
        _Insn(_BPF_JEQ_K, 0, "allow", socket_nr),
        _Insn(_BPF_LD_W_ABS, 0, 0, _OFF_ARG0),
        _Insn(_BPF_JEQ_K, "deny", 0, _AF_INET),
        _Insn(_BPF_JEQ_K, "deny", 0, _AF_INET6),
        _Insn(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW, label="allow"),
        _Insn(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | _EPERM, label="deny"),
    ]
    labels = {ins.label: i for i, ins in enumerate(prog) if ins.label}

    def offset(target: str | int, index: int) -> int:
        return labels[target] - index - 1 if isinstance(target, str) else target

    return b"".join(
        struct.pack("=HBBI", ins.code, offset(ins.jt, i), offset(ins.jf, i), ins.k)
        for i, ins in enumerate(prog)
    )


class _PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def abi_version() -> int:
    """The kernel's Landlock ABI, or 0 when Landlock is absent or blocked. Restricts nothing."""
    if not sys.platform.startswith("linux"):
        return 0
    try:
        libc = _libc()
        version = libc.syscall(
            SYS_LANDLOCK_CREATE_RULESET, None, ctypes.c_size_t(0), CREATE_RULESET_VERSION
        )
    except (OSError, AttributeError):
        return 0
    return int(version) if version > 0 else 0


def _check(result: int, what: str) -> None:
    if result < 0:
        err = ctypes.get_errno()
        raise LandlockError(f"{what}: {os.strerror(err)}")


def no_new_privs() -> None:
    _check(_libc().prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0), "PR_SET_NO_NEW_PRIVS")


def enforce(plan: RulesetPlan) -> None:
    """Create the ruleset, add its rules and restrict this thread and its future children."""
    libc = _libc()
    attr = _RulesetAttr(plan.handled_fs, plan.handled_net)
    size = ctypes.sizeof(attr) if plan.abi >= 4 else 8
    fd = libc.syscall(SYS_LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(size), 0)
    _check(fd, "landlock_create_ruleset")
    try:
        for path, access in plan.rules:
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = _PathBeneath(access, parent)
                _check(
                    libc.syscall(
                        SYS_LANDLOCK_ADD_RULE, fd, RULE_PATH_BENEATH, ctypes.byref(rule), 0
                    ),
                    f"landlock_add_rule {path}",
                )
            finally:
                os.close(parent)
        _check(libc.syscall(SYS_LANDLOCK_RESTRICT_SELF, fd, 0), "landlock_restrict_self")
    finally:
        os.close(fd)


def install_socket_filter(program: bytes) -> None:
    """Install the BPF *program* with seccomp; NO_NEW_PRIVS must already be set."""
    buf = ctypes.create_string_buffer(program, len(program))
    fprog = _SockFprog(len(program) // 8, ctypes.cast(buf, ctypes.c_void_p).value)
    _check(
        _libc().prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0),
        "PR_SET_SECCOMP",
    )
