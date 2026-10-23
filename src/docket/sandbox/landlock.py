"""Landlock and seccomp through ctypes: the Linux execution envelope's kernel layer.

``plan_ruleset`` and ``socket_filter`` are pure; only ``abi_version``, ``enforce`` and
``install_socket_filter`` make syscalls. See specs/functional/security-gates.spec.md item 10."""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform
import re
import struct
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docket.kernel.errors import Unavailable
from docket.kernel.git import git as _git
from docket.kernel.process import PROBE_TIMEOUT_S
from docket.sandbox import landlock

SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
CREATE_RULESET_VERSION = 1 << 0
RULE_PATH_BENEATH = 1

FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_REFER = 1 << 13
FS_TRUNCATE = 1 << 14
FS_IOCTL_DEV = 1 << 15
NET_BIND_TCP = 1 << 0
NET_CONNECT_TCP = 1 << 1

# every filesystem right of ABI 1 (bits 0-12); handled_fs_for adds the later ones
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


def landlock_available() -> bool:
    """True on Linux when the kernel reports a Landlock ABI of at least 1 (a probe that restricts
    nothing). ``DOCKET_SANDBOX_PROBE=none`` reports false, as a host without the kernel feature."""
    if os.environ.get("DOCKET_SANDBOX_PROBE") == "none":
        return False

    return landlock.abi_version() >= 1


def worktree_git_dirs(path: str) -> tuple[str, str] | None:
    """``(git dir, common dir)`` of the worktree at *path* straight from git, for the record
    taken at provisioning; ``None`` when *path* is not a git checkout."""
    result = _git.git_plain(path, ["rev-parse", "--absolute-git-dir", "--git-common-dir"])
    lines = result.stdout.split() if result is not None and result.returncode == 0 else []
    if len(lines) != 2:
        return None
    common = Path(lines[1])
    if not common.is_absolute():
        common = Path(path) / common
    return lines[0], str(common.resolve())


def git_dirs(root: Path) -> list[Path]:
    """The repository dirs of *root* (per-worktree dir first, then the common dir), else []. A
    worktree docket recorded answers from the record, never from its ``.git`` file."""
    trusted = _git.trusted_dirs(str(root))
    if trusted is not None:
        git_dir, common = (Path(p).resolve() for p in trusted)
        return [git_dir] if git_dir == common else [git_dir, common]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    out: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        path = Path(line)
        if not path.is_absolute():
            path = Path(root) / path
        path = path.resolve()
        if path not in out:
            out.append(path)
    return out


_SUBMODULE_DEPTH = 8


def _submodule_git_dirs(base: Path) -> list[Path]:
    """Git dirs of submodules under ``base/modules`` (any depth): a directory holding ``HEAD``.
    Walks the filesystem only -- never runs git in a submodule -- and never follows symlinks."""
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > _SUBMODULE_DEPTH:
            return
        try:
            children = sorted(c for c in directory.iterdir() if c.is_dir() and not c.is_symlink())
        except OSError:
            return
        for child in children:
            if (child / "HEAD").is_file():
                found.append(child)
                walk(child / "modules", depth + 1)
            else:
                walk(child, depth + 1)

    walk(base / "modules", 0)
    return found


def _submodule_worktree_git_file(subgit: Path) -> Path | None:
    """The ``.git`` file of a submodule's checkout, located through the ``worktree =`` line of its
    git dir's config (read as text); None when absent or not a file."""
    try:
        text = (subgit / "config").read_text(errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*worktree\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    checkout = Path(match.group(1))
    if not checkout.is_absolute():
        checkout = subgit / checkout
    dotgit = Path(os.path.normpath(checkout)) / ".git"
    return dotgit if dotgit.is_file() else None


def _guarded_paths(root: Path, dirs: list[Path]) -> list[Path]:
    """Every path under the git dirs (and root's ``.git`` file) that the operator's next host-side
    git command would execute or trust, so the jail must not be able to write it."""
    gitdir, common = dirs[0], dirs[-1]
    guarded = [
        common / "hooks",
        common / "config",
        gitdir / "config.worktree",
        common / "info" / "attributes",
    ]
    if (root / ".git").is_file():
        guarded.append(root / ".git")
    if gitdir != common:
        guarded += [gitdir / "gitdir", gitdir / "commondir"]
    for base in dict.fromkeys(dirs):
        for sub in _submodule_git_dirs(base):
            guarded += [sub / "hooks", sub / "config", sub / "config.worktree"]
            guarded += [sub / "info" / "attributes"]
            checkout_git = _submodule_worktree_git_file(sub)
            if checkout_git is not None:
                guarded.append(checkout_git)
    for g in guarded:
        _materialize_guard(g)
    return [g for g in guarded if g.is_dir() or g.is_file()]


def _materialize_guard(path: Path) -> None:
    """Create an absent ``hooks`` dir or ``info/attributes`` file, empty, so it can be bound
    read-only: a path missing at jail start would otherwise be creatable from inside it."""
    if path.exists():
        return
    with contextlib.suppress(OSError):
        if path.name == "hooks" and path.parent.is_dir():
            path.mkdir()
        elif path.name == "attributes" and path.parent.parent.is_dir():
            path.parent.mkdir(exist_ok=True)
            path.touch()


def _mount_dirs(roots: tuple[Path, ...]) -> tuple[list[str], list[str]]:
    """Read-write mounts (roots plus their repository dirs) and the read-only overlays on top.
    Hooks, config, attributes, submodule equivalents and ``.git`` pointer files stay read-only: a
    writable one lets the jail plant code the operator's next host git command runs. Bind them last."""
    rw: list[str] = []
    ro: list[str] = []
    for root in roots:
        dirs = git_dirs(root)
        resolved_root = root.resolve()
        for path in [resolved_root, *dirs]:
            if str(path) not in rw:
                rw.append(str(path))
        if dirs:
            for guarded in [*_guarded_paths(resolved_root, dirs), *_linked_ref_overlays(dirs)]:
                if str(guarded) not in ro:
                    ro.append(str(guarded))
    return rw, ro


def _linked_ref_overlays(dirs: list[Path]) -> list[Path]:
    """A linked worktree's shared ``refs``, ``logs/refs`` and ``packed-refs``, read-only. A main
    checkout (git dir equal to common dir) keeps them writable."""
    gitdir, common = dirs[0], dirs[-1]
    if gitdir == common:
        return []
    packed = common / "packed-refs"
    if not packed.exists():
        with contextlib.suppress(OSError):
            packed.touch()
    paths = [common / "refs", common / "logs" / "refs", packed]
    return [p for p in paths if p.exists()]


def _mount_reopened(roots: tuple[Path, ...]) -> list[str]:
    """The task branch's ref and reflog dirs of each task worktree root, to grant read-write
    after the read-only ref overlays."""
    out: list[str] = []
    for root in roots:
        dirs = git_dirs(root)
        if dirs and dirs[0] != dirs[-1]:
            out += [str(d) for d in _task_ref_dirs(dirs[-1], dirs[0]) if str(d) not in out]
    return out


def landlock_argv(
    roots: tuple[Path, ...],
    command: str,
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The argv running *command* under ``python -m docket.sandbox.jail``: the roots (and their repository
    dirs) read-write, *read_only* readable, nothing else of the host. The first root is the cwd."""
    return [*_landlock_prefix(roots, network, read_only), "/bin/sh", "-c", command]


def landlock_command_argv(
    roots: tuple[Path, ...],
    argv: list[str],
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The same jail as :func:`landlock_argv`, running *argv* directly (no shell)."""
    return [*_landlock_prefix(roots, network, read_only), *argv]


_GIT_WRITABLE_PARTS = ("objects", "refs", "logs")
_TASK_BRANCH_PREFIX = "refs/heads/docket/"
_GIT_DIR_IN_ROOT = (
    "{root} holds a .git directory, and Landlock cannot keep its hooks and config read-only "
    "inside a writable root; use a git worktree as the root, or choose docker with "
    "'docket setup sandbox backend docker'"
)


def _task_ref_dirs(common: Path, gitdir: Path) -> list[Path]:
    """The ref and reflog directories holding the task branch the linked worktree *gitdir* is on:
    ``HEAD`` must name ``refs/heads/docket/<pod>/<name>`` with ``<name>`` equal to the git dir's
    own name. Anything else (not a linked worktree, another branch) yields no grant."""
    try:
        head = (gitdir / "HEAD").read_text().strip()
    except OSError:
        return []
    ref = head.removeprefix("ref: ")
    parts = ref.split("/")
    if ref == head or not ref.startswith(_TASK_BRANCH_PREFIX) or len(parts) != 5:
        return []
    if gitdir == common or parts[-1] != gitdir.name or ".." in parts:
        return []
    out: list[Path] = []
    for root in (common / "refs" / "heads", common / "logs" / "refs" / "heads"):
        branch_dir = root.joinpath(*parts[2:-1])
        with contextlib.suppress(OSError):
            branch_dir.mkdir(parents=True, exist_ok=True)
        out.append(branch_dir)
    return out


def _landlock_git_mounts(root: Path, dirs: list[Path]) -> tuple[list[str], list[str]]:
    """``(rw, ro)`` for a root's git dirs: the common dir read-only but ``objects``, the task
    branch's ref and reflog dirs and submodule git dirs, plus a linked worktree's own git dir;
    never hooks, config or ``packed-refs``."""
    gitdir, common = dirs[0], dirs[-1]
    rw = [str(common / "objects"), *map(str, _task_ref_dirs(common, gitdir))]
    ro = [str(common)]
    for base in _submodule_git_dirs(common):
        with contextlib.suppress(OSError):
            (base / "logs").mkdir(exist_ok=True)
        rw += [str(base / part) for part in _GIT_WRITABLE_PARTS]
    if gitdir != common:
        rw.append(str(gitdir))
    return rw, ro


def _existing_resolved(paths: tuple[Path, ...]) -> list[Path]:
    """*paths* resolved, skipping one gone from disk (docker would create it, owned by root)."""
    return [p.resolve() for p in paths if p.exists()]


def _landlock_mounts(roots: tuple[Path, ...]) -> tuple[list[str], list[str]]:
    rw: list[str] = []
    ro: list[str] = []
    for root in roots:
        resolved = root.resolve()
        dirs = git_dirs(root)
        git_rw, git_ro = _landlock_git_mounts(resolved, dirs) if dirs else ([], [])
        for path in [str(resolved), *git_rw]:
            if path not in rw:
                rw.append(path)
        ro += [p for p in git_ro if p not in ro]
    return rw, ro


def _landlock_prefix(
    roots: tuple[Path, ...], network: bool, read_only: tuple[Path, ...] = ()
) -> list[str]:
    rw, ro = _landlock_mounts(roots)
    ro += [p for p in map(str, _existing_resolved(read_only)) if p not in ro]
    argv = [sys.executable, "-m", "docket.sandbox.jail"]
    for path in rw:
        argv += ["--rw", path]
    for path in ro:
        argv += ["--ro", path]
    for root in roots:
        if (root / ".git").is_dir() and not (root / ".git").is_symlink():
            argv += ["--refuse", _GIT_DIR_IN_ROOT.format(root=root.resolve())]
            break
    return [*argv, "--net", "open" if network else "none", "--"]
