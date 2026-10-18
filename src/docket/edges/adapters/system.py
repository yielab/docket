"""System adapter: typed wrappers over docker, sandbox-exec, and git.

Every shell-out to a container runtime, sandbox tool, or git lives here. Every subprocess call
catches FileNotFoundError / TimeoutExpired / OSError and degrades gracefully so a missing binary
never crashes a command. Functions are module-level and typed so callers can monkeypatch them.
Imports ``docket.core.security`` for ``match_high_risk``. ``run_verify_cmd`` is the only function
here that runs a free-form command through a real shell (``shell=True``); every other function
builds a fixed argv itself -- see ``specs/functional/security-gates.spec.md`` for the scoping
rationale, which also covers the exec-sandbox section below (mechanism only; the decision to use
one belongs to ``core/tools.py``'s ``ToolContext.sandbox``).
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Literal

import docket.config as _cfg
from docket.core import security as _sec

# Kept short so a hung subprocess never blocks a CLI command.
_QUERY_TIMEOUT = 5


def _which(binary: str) -> bool:
    """Return True if `binary` resolves on PATH (degrades to False on error)."""
    try:
        result = subprocess.run(
            ["command", "-v", binary],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    # `command` is a shell builtin and may not exist as an executable; fall back
    # to a PATH scan so detection works regardless of how we are invoked.
    path = os.environ.get("PATH", "")
    for directory in path.split(os.pathsep):
        if directory and os.access(os.path.join(directory, binary), os.X_OK):
            return True
    return False


def secret_tool_available() -> bool:
    """Return True if the `secret-tool` (libsecret) binary is on PATH."""
    return _which("secret-tool")


def desktop_notifications_available() -> bool:
    """True when the `desktop` channel dialect could deliver here: `osascript` on macOS, or a
    graphical session (`DISPLAY`/`WAYLAND_DISPLAY`) plus `notify-send` elsewhere."""
    if sys.platform == "darwin":
        return _which("osascript")
    has_session = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return has_session and _which("notify-send")


def secret_tool_lookup(service: str, key: str) -> str | None:
    """Look up one secret's value via `secret-tool lookup`; returns ``None``
    on any failure (missing binary, timeout, no match) -- treated as "no
    value", never an error, by `core/secrets.py`'s backend."""
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", service, "key", key],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout or None


def keyring_secret(name: str) -> str | None:
    """*name*'s value from the OS keyring under docket's service, or ``None`` when ``secret-tool``
    is missing or the lookup fails (no D-Bus session, no entry)."""
    if not secret_tool_available():
        return None
    from docket import config as _cfg

    value = secret_tool_lookup(_cfg.KEYRING_SERVICE, name)
    return value.strip() if value else None


def secret_tool_store(service: str, key: str, value: str) -> bool:
    """Store one secret via `secret-tool store` (value piped over stdin, never argv). Returns
    ``False`` on any failure -- unlike `secret_tool_lookup`, the caller treats that as an
    error, since a silent fallback to plaintext storage would defeat the keyring backend."""
    try:
        result = subprocess.run(
            ["secret-tool", "store", "--label", f"docket: {key}", "service", service, "key", key],
            input=value,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def secret_tool_clear(service: str, key: str) -> bool:
    """Remove one secret via `secret-tool clear`; best-effort like `secret_tool_lookup` --
    returns ``False`` on any failure, but the caller does not fail the surrounding command
    on that (the secrets.json index entry is removed either way)."""
    try:
        result = subprocess.run(
            ["secret-tool", "clear", "service", service, "key", key],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


# ── exec sandbox ─────────────────────────────────────────────────────────────
#
# `edges/adapters/toolbox.py`'s `run_bash` has no jail of its own -- the
# gate decides whether a command may run at all, not what it can reach once
# it does. These functions are the mechanism half of that: detecting which
# jail backend is actually usable on this host (not just installed) and
# building the argv that applies it. The *decision* to ask for one lives on
# `ToolContext.sandbox` (`core/tools.py`, opt-in, default "off") -- this
# module never decides, only detects and constructs, matching the existing
# split with `core.security`'s classifier.

SandboxBackend = Literal["landlock", "seatbelt", "docker", "none"]

# Detection probes must be fast (they run on every "auto" call) and must
# never hang a tool call over a jail that turns out to be unusable.
_SANDBOX_PROBE_TIMEOUT = 5


def docker_daemon_reachable() -> bool:
    """True if docker is on PATH AND its daemon answers, unlike `docker_available()` (binary only). A
    daemon absent or unreachable (rootless setups, a service never started) is common enough that
    treating "present" as "usable" would be a silent, incorrect degrade."""
    if not docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def landlock_available() -> bool:
    """True on Linux when the kernel reports a Landlock ABI of at least 1 (a probe that restricts
    nothing). ``DOCKET_SANDBOX_PROBE=none`` reports false, as a host without the kernel feature."""
    if os.environ.get("DOCKET_SANDBOX_PROBE") == "none":
        return False
    from docket.edges.adapters import landlock

    return landlock.abi_version() >= 1


_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def seatbelt_available() -> bool:
    """True on macOS when ``/usr/bin/sandbox-exec`` exists. ``DOCKET_SANDBOX_PROBE=none`` reports
    false. Apple deprecates ``sandbox-exec`` but still ships it; Claude Code and Codex rely on it."""
    if os.environ.get("DOCKET_SANDBOX_PROBE") == "none":
        return False
    return sys.platform == "darwin" and os.path.exists(_SANDBOX_EXEC)


@dataclass(frozen=True)
class SandboxAvailability:
    """One probe of the backends: the usable one, plus the raw per-backend result explaining why
    not. Answers "is a jail available", never "did this command run in one" -- see
    ``specs/functional/security-gates.spec.md``'s capability-reporting rule. ``docker`` is probed
    only when the operator chose it."""

    backend: SandboxBackend
    docker: bool
    landlock: bool = False
    seatbelt: bool = False


def sandbox_availability(choice: str | None = None) -> SandboxAvailability:
    """Probe the backends once. ``auto`` (the recorded default) is landlock on Linux or seatbelt on
    macOS, nothing else; ``docker`` is docker only, and is the one case docker is probed. *choice*
    defaults to the fleet's recorded ``sandboxBackend``. ``DOCKET_SANDBOX_BACKEND`` forces a
    backend for tests or an operator."""
    if choice is None:
        from docket.core import fleet as _fleet

        choice = _fleet.get_sandbox_backend()
    override = os.environ.get("DOCKET_SANDBOX_BACKEND")
    landlock_ok = landlock_available()
    seatbelt_ok = seatbelt_available()
    docker_ok = (choice == "docker" or override == "docker") and docker_daemon_reachable()
    backend: SandboxBackend
    if override in ("landlock", "seatbelt", "docker", "none"):
        backend = override  # type: ignore[assignment]
    elif choice == "docker":
        backend = "docker" if docker_ok else "none"
    elif landlock_ok:
        backend = "landlock"
    elif seatbelt_ok:
        backend = "seatbelt"
    else:
        backend = "none"
    return SandboxAvailability(
        backend=backend, docker=docker_ok, landlock=landlock_ok, seatbelt=seatbelt_ok
    )


_TRUSTED_TREES: dict[str, tuple[str, str]] = {}


def trust_worktree(path: str, git_dir: str, common_dir: str) -> None:
    """Record the git dir and common dir docket created for the task worktree at *path*. Host-side
    git then names them explicitly and never reads the worktree's ``.git`` file, which the
    jailed agent can rewrite."""
    if path and git_dir and common_dir:
        _TRUSTED_TREES[os.path.realpath(path)] = (git_dir, common_dir)


def worktree_git_dirs(path: str) -> tuple[str, str] | None:
    """``(git dir, common dir)`` of the worktree at *path* straight from git, for the record
    taken at provisioning; ``None`` when *path* is not a git checkout."""
    result = _git_plain(path, ["rev-parse", "--absolute-git-dir", "--git-common-dir"])
    lines = result.stdout.split() if result is not None and result.returncode == 0 else []
    if len(lines) != 2:
        return None
    common = Path(lines[1])
    if not common.is_absolute():
        common = Path(path) / common
    return lines[0], str(common.resolve())


def _git_plain(cwd: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


_WORKTREE_CONFIG_ON = re.compile(r"^\s*worktreeconfig\s*=\s*(true|yes|on|1)\s*$", re.I | re.M)


def _worktree_config_poisoned(git_dir: str, common_dir: str) -> bool:
    """True when a per-worktree config file exists and the shared config makes git read it: the
    jail can write that file under Landlock, and a config key can name a program."""
    if not os.path.exists(os.path.join(git_dir, "config.worktree")):
        return False
    try:
        text = Path(common_dir, "config").read_text(errors="replace")
    except OSError:
        return True
    return bool(_WORKTREE_CONFIG_ON.search(text))


def _trusted_git_env(
    cwd: str, env: dict[str, str] | None
) -> tuple[dict[str, str] | None, str | None]:
    """The environment for host-side git in *cwd*, and a refusal reason or ``None``. In a worktree
    docket recorded, the git dir, common dir and work tree are named through the environment, so
    nothing the agent wrote at ``.git`` is read; a poisoned per-worktree config is refused."""
    trusted = _TRUSTED_TREES.get(os.path.realpath(cwd))
    if trusted is None:
        return env, None
    git_dir, common_dir = trusted
    if _worktree_config_poisoned(git_dir, common_dir):
        return env, "refused: the worktree config could name a program to run"
    return {
        **(os.environ if env is None else env),
        "GIT_DIR": git_dir,
        "GIT_COMMON_DIR": common_dir,
        "GIT_WORK_TREE": os.path.realpath(cwd),
    }, None


def _git_run(
    cwd: str,
    args: list[str],
    timeout: float,
    env: dict[str, str] | None = None,
    config: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C cwd <config> <args>``; a worktree docket recorded is addressed through its
    recorded git dirs (see ``_trusted_git_env``) and fails closed on a poisoned config."""
    env, refused = _trusted_git_env(cwd, env)
    if refused is not None:
        return subprocess.CompletedProcess(args, 1, "", refused)
    return subprocess.run(
        ["git", "-C", cwd, *config, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def git_dirs(root: Path) -> list[Path]:
    """The repository dirs of *root* (per-worktree dir first, then the common dir), else []. A
    worktree docket recorded answers from the record, never from its ``.git`` file."""
    trusted = _TRUSTED_TREES.get(os.path.realpath(root))
    if trusted is not None:
        git_dir, common = (Path(p).resolve() for p in trusted)
        return [git_dir] if git_dir == common else [git_dir, common]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
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
    """The argv running *command* under ``python -m docket.jail``: the roots (and their repository
    dirs) read-write, *read_only* readable, nothing else of the host. The first root is the cwd."""
    return [*_landlock_prefix(roots, network, read_only), "/bin/sh", "-c", command]


_SEATBELT_READ = (
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/opt",
    "/private/etc",
    "/System/Library",
    "/Library",
)
_SEATBELT_READ_DEVICES = ("/dev/random", "/dev/urandom")
_SEATBELT_WRITE_DEVICES = ("/dev/null", "/dev/zero", "/dev/tty", "/dev/dtracehelper")


def _sbpl(path: str) -> str:
    """Quote *path* as a Seatbelt profile string literal."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def seatbelt_profile(
    roots: tuple[Path, ...], network: bool = True, read_only: tuple[Path, ...] = ()
) -> str:
    """The fixed Seatbelt profile: deny by default, system paths, ``sys.prefix`` and *read_only*
    readable, the roots (with their repository dirs) read-write, guarded git paths not writable."""
    rw, ro = _mount_dirs(roots)
    prefixes = (os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix))
    granted = (os.path.realpath(p) for p in read_only)
    read = list(dict.fromkeys((*_SEATBELT_READ, *prefixes, *granted)))
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec* process-fork sysctl-read mach-lookup file-read-metadata)",
        "(allow signal (target self))",
        # macOS 26 aborts every process (SIGABRT, no output) that cannot list "/"; the names only.
        '(allow file-read-data (literal "/"))',
        "(allow file-read* " + " ".join(f"(subpath {_sbpl(p)})" for p in read) + ")",
        "(allow file-read* "
        + " ".join(f"(literal {_sbpl(p)})" for p in _SEATBELT_READ_DEVICES)
        + ")",
        "(allow file-read* file-write* "
        + " ".join(f"(literal {_sbpl(p)})" for p in _SEATBELT_WRITE_DEVICES)
        + ")",
    ]
    lines += [f"(allow file-read* file-write* (subpath {_sbpl(p)}))" for p in rw]
    lines += [f"(deny file-write* (subpath {_sbpl(p)}))" for p in ro]
    lines += [
        f"(allow file-read* file-write* (subpath {_sbpl(p)}))" for p in _mount_reopened(roots)
    ]
    lines.append("(allow network*)" if network else "(deny network*)")
    return "\n".join(lines) + "\n"


def seatbelt_argv(
    roots: tuple[Path, ...],
    command: str,
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The argv running *command* under ``sandbox-exec -p <profile>``; the first root is the cwd."""
    profile = seatbelt_profile(roots, network, read_only)
    return [_SANDBOX_EXEC, "-p", profile, "/bin/sh", "-c", command]


def seatbelt_command_argv(
    roots: tuple[Path, ...],
    argv: list[str],
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The same jail as :func:`seatbelt_argv`, running *argv* directly (no shell)."""
    return [_SANDBOX_EXEC, "-p", seatbelt_profile(roots, network, read_only), *argv]


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
    argv = [sys.executable, "-m", "docket.jail"]
    for path in rw:
        argv += ["--rw", path]
    for path in ro:
        argv += ["--ro", path]
    for root in roots:
        if (root / ".git").is_dir() and not (root / ".git").is_symlink():
            argv += ["--refuse", _GIT_DIR_IN_ROOT.format(root=root.resolve())]
            break
    return [*argv, "--net", "open" if network else "none", "--"]


_GIT_IDENTITY_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


def git_identity_env(root: Path) -> dict[str, str]:
    """The operator's git identity for a jailed command in *root*: the four ``GIT_AUTHOR_*``/
    ``GIT_COMMITTER_*`` variables when set, else ``user.name``/``user.email`` as git resolves
    them on the host there. Identity only, never a credential; empty when git knows none."""
    found = {k: os.environ[k] for k in _GIT_IDENTITY_VARS if os.environ.get(k)}
    if len(found) == len(_GIT_IDENTITY_VARS) or not git_available():
        return found
    resolved: dict[str, str] = {}
    for key in ("name", "email"):
        try:
            out = _git_run(str(root), ["config", "--get", f"user.{key}"], _QUERY_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            resolved[key] = out.stdout.strip()
    for var in _GIT_IDENTITY_VARS:
        value = resolved.get(var.rsplit("_", 1)[1].lower())
        if var not in found and value:
            found[var] = value
    return found


def docker_run_argv(
    container_name: str,
    roots: tuple[Path, ...],
    command: str,
    env: dict[str, str] | None,
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """Build the ``docker run`` argv that jails *command* to *roots*: each root bind-mounted read-write,
    nothing else of the host visible. Runs as the caller's uid/gid so mounted files are not left root-owned.
    *env* injects only `ToolContext.env` (e.g. `DOCKET_SCRATCH_DIR`), never the full host environment --
    see ``specs/functional/security-gates.spec.md`` for why (env minimization) and the network-bridge rationale."""
    prefix = _docker_prefix(container_name, roots, env, network, read_only=read_only)
    return [*prefix, "sh", "-c", command]


def docker_command_argv(
    container_name: str,
    roots: tuple[Path, ...],
    argv: list[str],
    env: dict[str, str] | None,
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The same jail as :func:`docker_run_argv`, running *argv* directly with stdin kept open (``-i``)."""
    prefix = _docker_prefix(
        container_name, roots, env, network, interactive=True, read_only=read_only
    )
    return [*prefix, *argv]


def _docker_prefix(
    container_name: str,
    roots: tuple[Path, ...],
    env: dict[str, str] | None,
    network: bool,
    interactive: bool = False,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    argv = [
        "docker",
        "run",
        "--rm",
        *(["-i"] if interactive else []),
        "--name",
        container_name,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]
    if not network:
        argv += ["--network", "none"]
    rw, ro = _mount_dirs(roots)
    for resolved in rw:
        argv += ["-v", f"{resolved}:{resolved}"]
    for guarded in ro:
        argv += ["-v", f"{guarded}:{guarded}:ro"]
    for reopened in _mount_reopened(roots):
        argv += ["-v", f"{reopened}:{reopened}"]
    for granted in _existing_resolved(read_only):
        argv += ["-v", f"{granted}:{granted}:ro"]
    argv += ["-w", str(roots[0].resolve())]
    for key, value in (env or {}).items():
        argv += ["-e", f"{key}={value}"]
    argv.append(_cfg.SANDBOX_DOCKER_IMAGE)
    return argv


def docker_image_has_git(image: str | None = None) -> bool | None:
    """True when *image* (default the configured jail image) has ``git`` on its PATH, False when it
    does not or is not present locally, None when the probe itself could not run or timed out."""
    try:
        result = subprocess.run(
            [
                *["docker", "run", "--rm", "--pull", "never"],
                image or _cfg.SANDBOX_DOCKER_IMAGE,
                *["sh", "-c", "command -v git"],
            ],
            capture_output=True,
            timeout=_IMAGE_PROBE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.returncode == 0


def docker_kill(container_name: str) -> None:
    """Force-stop (and, via the original run's ``--rm``, remove) a docker-jailed
    run by name. Needed because ``docker run``'s own CLI process group does
    NOT reach the container the daemon actually runs -- killing only the CLI
    leaves it running (see ``specs/functional/security-gates.spec.md``).
    Swallows every failure: runs from a timeout handler, where a hung kill
    must not become a second hang."""
    import contextlib

    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)


_IMAGE_PROBE_TIMEOUT = 30
_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces


_REGISTERED_CREDENTIAL_NAMES: set[str] = set()


def register_credential_name(name: str) -> None:
    """Treat *name* as a credential in this process (stripped from every child environment)."""
    if name:
        _REGISTERED_CREDENTIAL_NAMES.add(name)


def credential_names() -> set[str]:
    """Every environment name docket treats as a credential: ``DOCKET_LLM_API_KEY``,
    ``TELEGRAM_BOT_TOKEN``, each name the provider catalog declares and each in the secret store.
    Reads files only; never creates the home."""
    from docket.core import provider as _provider
    from docket.core import secrets as _secrets

    names = {"DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN", *_REGISTERED_CREDENTIAL_NAMES}
    names.update(_secrets.secrets_keys())
    for spec in _provider.load_catalog().entries.values():
        names.update(spec.auth.credentials)
    return names


_CACHE_ENV_VARS = (
    "HOME",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "UV_CACHE_DIR",
    "PIP_CACHE_DIR",
    "npm_config_cache",
)


def cache_environment(cache_dir: Path) -> dict[str, str]:
    """The six variables that point a tool's home and caches at *cache_dir*."""
    return {name: str(cache_dir) for name in _CACHE_ENV_VARS}


def task_environment(
    overlay: dict[str, str] | None = None, cache_dir: Path | None = None
) -> dict[str, str]:
    """The host environment minus docket's credentials (``credential_names``), with the pod
    cache variables (when *cache_dir* is given) and then *overlay* applied last."""
    names = credential_names()
    merged = {k: v for k, v in os.environ.items() if k not in names}
    if cache_dir is not None:
        merged.update(cache_environment(cache_dir))
    if overlay:
        merged.update(overlay)
    return merged


@dataclass(frozen=True)
class JailLaunch:
    """What to hand ``Popen`` for a jailed command: the argv, the child environment (``None``
    for docker, whose container gets its variables through ``-e`` flags) and the container name."""

    argv: list[str]
    env: dict[str, str] | None
    container: str = ""


@dataclass(frozen=True)
class JailPolicy:
    """The jail a docket-launched command must run in: the pod's network, extra rw roots and
    the pod cache dir."""

    network: bool = True
    extra_rw: tuple[Path, ...] = ()
    cache_dir: Path | None = None
    read_only: tuple[Path, ...] = ()


_TMP_ENV_VARS = ("TMPDIR", "TMP", "TEMP")


def jail_tmp_dir(roots: tuple[Path, ...], cache_dir: Path | None) -> Path:
    """The launch's private temp dir (0700): ``<cache_dir>/tmp``, else ``JAIL_TMP_DIR``
    keyed by the first root. Reused across runs like the cache."""
    if cache_dir is not None:
        path = cache_dir / "tmp"
    else:
        key = hashlib.sha256(str(roots[0].resolve()).encode()).hexdigest()[:12]
        _cfg.JAIL_TMP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = _cfg.JAIL_TMP_DIR / key
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path.resolve()


def tmp_environment(tmp: Path) -> dict[str, str]:
    """The variables that point a tool's temp files at *tmp*."""
    return {name: str(tmp) for name in _TMP_ENV_VARS}


def jailed_env(env: dict[str, str] | None) -> dict[str, str]:
    """PATH plus the explicit overlay: never the host environment, so a jailed command cannot
    inherit a credential the unjailed path would."""
    minimal = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if env:
        minimal.update(env)
    return minimal


def jail_launch(
    roots: tuple[Path, ...],
    command: str,
    backend: SandboxBackend,
    *,
    network: bool = True,
    env: dict[str, str] | None = None,
    extra_rw: tuple[Path, ...] = (),
    cache_dir: Path | None = None,
    read_only: tuple[Path, ...] = (),
) -> JailLaunch:
    """The one place a backend, the roots and *extra_rw* become a jailed shell command. The first
    root is the cwd; *extra_rw* and *cache_dir* (home and caches) are writable beside the roots,
    *read_only* (the operator's toolchain grants) readable. Raises ``ValueError`` for ``none``."""
    all_roots = (*roots, *extra_rw)
    merged = {**git_identity_env(roots[0].resolve()), **(env or {})}
    if cache_dir is not None:
        all_roots = (*all_roots, cache_dir.resolve())
        merged = {**cache_environment(cache_dir), **merged}
    if backend == "docker":
        name = f"docket-sbx-{uuid.uuid4().hex[:12]}"
        argv = docker_run_argv(name, all_roots, command, merged, network, read_only)
        return JailLaunch(argv, None, name)
    if backend in ("landlock", "seatbelt"):
        tmp = jail_tmp_dir(roots, cache_dir)
        all_roots = (*all_roots, tmp)
        merged = {**tmp_environment(tmp), **merged}
        build = landlock_argv if backend == "landlock" else seatbelt_argv
        return JailLaunch(build(all_roots, command, network, read_only), jailed_env(merged))
    raise ValueError(f"no sandbox backend to launch under: {backend}")


def run_verify_cmd(
    cmd: str,
    cwd: str,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    jail: JailPolicy | None = None,
) -> tuple[bool, str]:
    """``run_command`` projected onto ``(passed, output)``: only exit status 0 passes."""
    code, output = run_command(cmd, cwd, timeout, env=env, jail=jail)
    return code == 0, output


def run_command(
    cmd: str,
    cwd: str,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    jail: JailPolicy | None = None,
) -> tuple[int | None, str]:
    """Run a user-supplied verification command in *cwd*. Returns
    ``(exit_status, combined_output)`` capped at _VERIFY_MAX_OUTPUT; the caller
    must redact secrets before tracing it. Never raises: a refusal, timeout,
    missing binary, or OS error returns ``None`` with a short error string
    instead. The status is the process's own, never a value the command wrote.

    *cmd* is classified against ``core.security``'s high-risk classes and
    fails closed -- refused outright, never run -- before the subprocess
    starts. That is the only honest posture here: this call is synchronous
    inside a dispatch hop, with no interactive approver reachable (see
    ``specs/functional/security-gates.spec.md``). ``cwd``/``timeout`` are
    never classified: they are plumbing, not operator-composed shell text. *env*, when
    given, is merged over the inherited environment minus docket's credentials.

    Runs in its own session (``start_new_session=True``) so a timeout can kill the
    command's whole process group, not just the immediate ``sh`` child -- otherwise a
    command that backgrounds work (``build & wait``, a test runner spawning workers)
    leaves orphans behind every time it is killed on timeout. The pid is never
    registered anywhere, so this group is reachable only from inside this function;
    ``docket task cancel`` cannot interrupt an in-flight verify command (see
    ``specs/functional/pod-dispatch.spec.md``'s Cancellation requirement 2).

    With *jail* the command runs under the strongest sandbox backend, rooted at *cwd*, and never
    on the host: no usable backend means it is not run. See specs/functional/security-gates.spec.md."""
    risk_cls = _sec.match_high_risk(cmd)
    if risk_cls is not None:
        return None, (
            f"[verify command refused: matches high-risk class '{risk_cls.name}' "
            f"({risk_cls.description}) -- see `docket setup sandbox classes`]"
        )
    container = ""
    try:
        if jail is None:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=task_environment(env),
            )
        else:
            backend = sandbox_availability().backend
            if backend == "none" or not cwd:
                return (
                    None,
                    "[verify not run: no sandbox backend is usable or no working directory]",
                )
            launch = jail_launch(
                (Path(cwd),),
                cmd,
                backend,
                network=jail.network,
                env=env,
                extra_rw=jail.extra_rw,
                cache_dir=jail.cache_dir,
                read_only=jail.read_only,
            )
            container = launch.container
            proc = subprocess.Popen(
                launch.argv,
                shell=False,
                cwd=str(Path(cwd).resolve()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=launch.env,
            )
    except (FileNotFoundError, OSError) as exc:
        return None, f"[verify error: {exc}]"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        import contextlib
        import signal as _signal

        if container:
            docker_kill(container)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, _signal.SIGKILL)
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            proc.communicate(timeout=5)
        return None, f"[verify timed out after {timeout}s]"
    except OSError as exc:
        return None, f"[verify error: {exc}]"
    combined = (stdout + stderr).strip()
    return proc.returncode, combined[:_VERIFY_MAX_OUTPUT]


def make_non_dumpable() -> None:
    """Set PR_SET_DUMPABLE to 0 so a same-uid process cannot read this one's /proc environ or
    mem. Linux only; a no-op elsewhere and on any failure. Reset by execve, so children are unaffected."""
    if not sys.platform.startswith("linux"):
        return
    try:
        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)
    except (OSError, AttributeError):
        return


def process_alive(pid: int) -> bool:
    """Whether a process with *pid* exists (signal 0 = probe only). A pid we may not signal
    still exists; a non-positive pid never does."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_alive(pgid: int) -> bool:
    """Best-effort liveness check for a process group (signal 0 = probe only)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but we can't signal it — treat as alive (a real, distinct
        # failure mode from "already gone"; escalation below will hit the
        # same PermissionError and just stop trying, never crash the caller).
        return True
    return True


def kill_process_group(pgid: int, grace_s: float = 2.0) -> bool:
    """SIGTERM a process group; escalate to SIGKILL if still alive after
    *grace_s*. Requires the subprocess to have been started with
    ``start_new_session=True`` (pid doubles as process group id) -- a pid
    from anywhere else would signal an unrelated group, so callers must only
    pass one reported via a driver's ``on_spawn`` hook.

    Returns ``True`` if the group was observed alive (a signal was
    meaningfully sent), ``False`` if already gone -- a harmless no-op, not
    an error. Never raises: a process exiting mid-call is treated the same
    as one already gone."""
    import contextlib
    import signal as _signal

    if not _process_group_alive(pgid):
        return False
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, _signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and _process_group_alive(pgid):
        time.sleep(0.05)
    if _process_group_alive(pgid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, _signal.SIGKILL)
    return True


def git_available() -> bool:
    """Return True if a git binary is on PATH."""
    return _which("git")


def git_current_branch(cwd: str) -> str:
    """Return the current git branch for `cwd`, or '' if not a repo or unavailable; degrades
    gracefully on a missing binary, non-repo directory, or timeout. The ``diff_ref`` producer for an
    Implementer hop's ``HandoffArtifact`` (`core/dispatch.py`'s `_hop_diff_probe`)."""
    if not git_available():
        return ""
    try:
        result = _git_run(cwd, ["rev-parse", "--abbrev-ref", "HEAD"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_is_repo(cwd: str) -> bool:
    """Return True if ``cwd`` is inside a git repository."""
    if not git_available():
        return False
    try:
        result = _git_run(cwd, ["rev-parse", "--git-dir"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def git_changed_files(cwd: str) -> list[str]:
    """Return paths with uncommitted changes in `cwd` (staged, unstaged,
    untracked); the `files_changed` producer for an Implementer hop's
    `HandoffArtifact`. Uses `git status --porcelain` (not a diff against a
    fixed base ref) so it reflects the real tree regardless of what the
    Implementer has committed this hop. Degrades to `[]` -- never raises --
    on a missing binary, non-repo directory, timeout, or clean tree. Sorted
    for determinism (porcelain order is otherwise platform-dependent)."""
    if not git_available():
        return []
    try:
        result = _git_run(cwd, ["status", "--porcelain"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1: two status chars, a space, then the path. A rename/copy
        # line reads "R  old/path -> new/path" — keep only the new path.
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip())
    return sorted(files)


def git_worktree_changes(cwd: str) -> list[tuple[str, str]]:
    """Return ``(status, absolute path)`` for every path ``git status`` reports in the repository
    containing `cwd`, untracked files listed one by one. Degrades to ``[]`` -- never raises --
    on a missing binary, non-repo directory, or timeout, like `git_changed_files`."""
    if not git_available():
        return []
    try:
        top = _git_run(cwd, ["rev-parse", "--show-toplevel"], _QUERY_TIMEOUT)
        status = _git_run(
            cwd, ["status", "--porcelain", "-z", "--untracked-files=all"], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if top.returncode != 0 or status.returncode != 0:
        return []
    root = top.stdout.strip()
    fields = status.stdout.split("\0")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        # With -z a rename or copy is "XY new\0old\0": the original path is its own field.
        if code[0] in "RC":
            index += 1
        changes.append((code, os.path.join(root, path)))
    return changes


def git_worktree_fingerprint(cwd: str) -> dict[str, tuple[str, int, int]]:
    """Map every path `git_worktree_changes` reports to ``(status, size, mtime_ns)``, so two
    snapshots can tell a path that changed between them from one that merely stayed dirty. A
    path that no longer exists (a deletion) fingerprints as size and mtime ``-1``."""
    prints: dict[str, tuple[str, int, int]] = {}
    for code, path in git_worktree_changes(cwd):
        try:
            stat = os.stat(path)
            prints[path] = (code, stat.st_size, stat.st_mtime_ns)
        except OSError:
            prints[path] = (code, -1, -1)
    return prints


def git_worktree_add(
    repo_dir: str, worktree_path: str, branch: str, start_point: str = ""
) -> tuple[bool, str]:
    """Create a worktree at ``worktree_path`` on new branch ``branch`` (from ``start_point`` if
    given). Returns ``(success, error_message)``; never raises, returning ``(False, reason)``."""
    if not git_available():
        return False, "git not found on PATH"
    if start_point.startswith("-"):
        return False, f"invalid start point {start_point!r}"
    argv = ["git", "-C", repo_dir, "worktree", "add", "-b", branch, worktree_path]
    if start_point:
        argv.append(start_point)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_worktree_remove(repo_dir: str, worktree_path: str) -> tuple[bool, str]:
    """Remove the git worktree at ``worktree_path`` (``--force``, to handle
    unclean worktrees). Returns ``(success, message)``; degrades gracefully
    on errors."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "worktree", "remove", "--force", worktree_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_worktree_prune(repo_dir: str) -> None:
    """Drop worktree records whose directory is gone; silent on every error."""
    if not git_available():
        return
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            ["git", "-C", repo_dir, "worktree", "prune"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )


def git_branch_merged(repo_dir: str, branch: str, into: str) -> bool:
    """True if ``branch`` is fully merged into ``into`` in ``repo_dir``; False on a missing
    binary, non-repo directory, timeout, or a genuinely unmerged branch."""
    if not git_available():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "--merged", into],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    # "*" marks the current branch, "+" a branch checked out in another worktree.
    names = {line.strip().lstrip("*+ ").strip() for line in result.stdout.splitlines()}
    return branch in names


def git_branch_delete(repo_dir: str, branch: str) -> tuple[bool, str]:
    """Delete a local branch with ``-d`` (refuses an unmerged branch; never ``-D``).
    Returns ``(success, message)``; degrades gracefully on errors."""
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "-d", branch],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def git_head_sha(cwd: str) -> str | None:
    """Return the full 40-hex-char HEAD sha for `cwd`, or ``None`` if not a repo or
    unavailable; degrades gracefully like `git_current_branch`. The ``commit`` producer
    for an Implementer hop's persisted evidence."""
    if not git_available():
        return None
    try:
        result = _git_run(cwd, ["rev-parse", "HEAD"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


_FULL_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _repo_rel_path_ok(rel: str) -> bool:
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and all(p not in ("", ".", "..") for p in parts)


def git_read_blob(cwd: str, rev: str, rel: str) -> bytes | None:
    """The bytes of repository path *rel* at commit *rev* (a full sha), read host-side through the
    git dirs docket recorded for the worktree at *cwd* when it recorded any. ``None`` when the
    path is absent at *rev*, is not a blob, *rev*/*rel* are malformed, or git is unavailable."""
    if not _FULL_SHA.match(rev) or not _repo_rel_path_ok(rel) or not git_available():
        return None
    env, refused = _trusted_git_env(cwd, None)
    if refused is not None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "cat-file", "blob", f"{rev}:{rel}"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


def git_path_exists_at(cwd: str, rev: str, rel: str) -> bool:
    """Whether repository path *rel* (a file or a directory) exists at commit *rev* (a full sha),
    asked host-side like ``git_read_blob``; ``False`` for a malformed *rev* or *rel* and when
    git is unavailable."""
    if not _FULL_SHA.match(rev) or not _repo_rel_path_ok(rel) or not git_available():
        return False
    env, refused = _trusted_git_env(cwd, None)
    if refused is not None:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "cat-file", "-e", f"{rev}:{rel}"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def git_list_tree_dirs(cwd: str, rev: str, rel: str) -> list[str] | None:
    """Names of the subdirectories directly under *rel* at commit *rev*, sorted, read like
    ``git_read_blob``; ``None`` when *rel* is absent at *rev* or not a directory."""
    if not _FULL_SHA.match(rev) or not _repo_rel_path_ok(rel) or not git_available():
        return None
    env, refused = _trusted_git_env(cwd, None)
    if refused is not None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "ls-tree", "-d", "--name-only", "-z", f"{rev}:{rel}"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return sorted(n.decode("utf-8", "replace") for n in result.stdout.split(b"\0") if n)


def git_merge_base(cwd: str, other_branch: str) -> str | None:
    """Return the merge-base sha of HEAD and `other_branch` in `cwd`, or ``None`` if not a
    repo, `other_branch` is unknown, or git is unavailable; degrades gracefully like
    `git_current_branch`. The ``baseCommit`` producer for an Implementer hop's evidence."""
    if not git_available():
        return None
    try:
        result = _git_run(cwd, ["merge-base", "HEAD", other_branch], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


_SHORTSTAT_FILES = re.compile(r"(\d+) files? changed")
_SHORTSTAT_INSERTIONS = re.compile(r"(\d+) insertions?\(\+\)")
_SHORTSTAT_DELETIONS = re.compile(r"(\d+) deletions?\(-\)")


def git_diff_stat(cwd: str, base: str, head: str | None = None) -> dict[str, int] | None:
    """Return ``{"files", "insertions", "deletions"}`` diffing `base` against `head`, else against
    `cwd`'s current state (``git diff --shortstat``), or ``None`` if not a repo, a ref is missing,
    or git is unavailable; an empty summary (no changes) reports all-zero counts, not ``None``."""
    if not git_available():
        return None
    try:
        result = _git_run(
            cwd, ["diff", "--shortstat", base, *([head] if head else [])], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    summary = result.stdout.strip()
    files_match = _SHORTSTAT_FILES.search(summary)
    insertions_match = _SHORTSTAT_INSERTIONS.search(summary)
    deletions_match = _SHORTSTAT_DELETIONS.search(summary)
    return {
        "files": int(files_match.group(1)) if files_match else 0,
        "insertions": int(insertions_match.group(1)) if insertions_match else 0,
        "deletions": int(deletions_match.group(1)) if deletions_match else 0,
    }


def git_diff(path: str, base: str) -> str | None:
    """Return ``git diff <base>`` for the tree at `path`, or ``None`` if git is unavailable,
    `path` is not a repo or `base` is unknown; an unchanged tree returns an empty string."""
    if not git_available():
        return None
    try:
        result = _git_run(path, ["diff", base], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


DIFF_MAX_CHARS = 500_000
_DIFF_TIMEOUT = 30


def git_diff_range(repo_dir: str, base: str, ref: str) -> str | None:
    """``git diff <base>..<ref>`` in *repo_dir*, cut at ``DIFF_MAX_CHARS`` with a trailing marker
    line; ``None`` when git is unavailable, *repo_dir* is not a repo or a ref is unknown."""
    if not git_available():
        return None
    try:
        result = _git_run(repo_dir, ["diff", f"{base}..{ref}"], _DIFF_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    patch = result.stdout
    if len(patch) > DIFF_MAX_CHARS:
        patch = f"{patch[:DIFF_MAX_CHARS]}\n[diff truncated at {DIFF_MAX_CHARS} characters]\n"
    return patch


def git_new_files_text(cwd: str, limit: int) -> str:
    """Each new untracked file's content under a ``--- new file: <path>`` line, path order, read up
    to about `limit` characters; a symlink, non-regular or binary file gets a note, not content.
    ``""`` on no git, no repo or no new file."""
    parts: list[str] = []
    size = 0
    for _code, path in sorted(c for c in git_worktree_changes(cwd) if c[0] == "??"):
        if size > limit:
            break
        rel = os.path.relpath(path, cwd)
        body = _read_new_file(path, limit - size + 1)
        parts.append(f"--- new file: {rel}\n{body}")
        size += len(parts[-1])
    return "".join(part if part.endswith("\n") else part + "\n" for part in parts)


def _read_new_file(path: str, limit: int) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return "(not a regular file; content not shown)"
    with os.fdopen(fd, "rb") as handle:
        if not S_ISREG(os.fstat(handle.fileno()).st_mode):
            return "(not a regular file; content not shown)"
        data = handle.read(max(limit, 1))
    if b"\0" in data:
        return "(binary file; content not shown)"
    return data.decode("utf-8", errors="replace")


def git_ls_files(cwd: str) -> list[str] | None:
    """Tracked paths of the repository at *cwd*, repository-relative and sorted; ``None`` when
    git is missing, *cwd* is not a repository, or the listing fails or times out."""
    if not git_available():
        return None
    try:
        result = _git_run(cwd, ["ls-files", "-z"], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return sorted(path for path in result.stdout.split("\0") if path)


def git_untracked(worktree: str) -> list[str]:
    """Paths git reports as untracked (``??``) in *worktree*, sorted; ``[]`` on a missing binary,
    non-repo directory or timeout."""
    if not git_available():
        return []
    try:
        result = _git_run(
            worktree, ["status", "--porcelain", "--untracked-files=all"], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return sorted(line[3:] for line in result.stdout.splitlines() if line.startswith("?? "))


def git_rev_parse(cwd: str, ref: str) -> str | None:
    """The commit *ref* names in *cwd*, else ``None`` (no repo, unknown ref, no git)."""
    if not git_available():
        return None
    try:
        result = _git_run(
            cwd, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], _QUERY_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def git_diff_names(cwd: str, base: str, head: str) -> list[str]:
    """Paths changed between `base` and `head` (``git diff --name-only``), sorted; ``[]`` on a
    missing binary, non-repo directory, unknown ref, or timeout."""
    if not git_available():
        return []
    try:
        result = _git_run(cwd, ["diff", "--name-only", base, head], _QUERY_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return sorted(line for line in result.stdout.splitlines() if line.strip())


_PIN_TIMEOUT = 60
# Repository hooks and signing stay off: a pin is bookkeeping, and a hook is the codebase's own
# code, which docket never runs on the host outside a gate.
_PIN_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false")


def _pin_env(cwd: str) -> dict[str, str]:
    """The environment for a pin commit: the operator's git identity, else ``docket``."""
    identity = {
        "GIT_AUTHOR_NAME": "docket",
        "GIT_AUTHOR_EMAIL": "docket@localhost",
        "GIT_COMMITTER_NAME": "docket",
        "GIT_COMMITTER_EMAIL": "docket@localhost",
    }
    return {**os.environ, **identity, **git_identity_env(Path(cwd))}


def _pin_git(
    cwd: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return _git_run(cwd, list(args), _PIN_TIMEOUT, env=env, config=_PIN_CONFIG)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def git_commit_all(cwd: str, message: str) -> str | None:
    """Commit every change in `cwd`'s tree (``git add -A``, so untracked files too and
    ``.gitignore`` respected) on its current branch and return the new HEAD sha; a tree with
    nothing to commit returns HEAD unchanged. ``None`` on any failure, never raising."""
    if not git_available():
        return None
    env = _pin_env(cwd)
    added = _pin_git(cwd, "add", "-A", env=env)
    if added is None or added.returncode != 0:
        return None
    staged = _pin_git(cwd, "diff", "--cached", "--quiet", env=env)
    if staged is None or staged.returncode not in (0, 1):
        return None
    if staged.returncode == 1:
        done = _pin_git(cwd, "commit", "--no-verify", "-q", "-m", message, env=env)
        if done is None or done.returncode != 0:
            return None
    return git_head_sha(cwd)


def git_snapshot_commit(cwd: str, message: str) -> str | None:
    """Pin `cwd`'s whole tree (untracked too, ``.gitignore`` respected) in a branchless commit on
    HEAD through a temporary index, leaving index, branch and working tree untouched; HEAD itself
    when the tree is HEAD's, ``None`` on any failure."""
    head = git_head_sha(cwd)
    if head is None:
        return None
    env = _pin_env(cwd)
    index_path = _pin_git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "index")
    with tempfile.TemporaryDirectory(prefix="docket-pin-") as tmp:
        index = os.path.join(tmp, "index")
        env["GIT_INDEX_FILE"] = index
        real_index = index_path.stdout.strip() if index_path and index_path.returncode == 0 else ""
        if real_index and os.path.isfile(real_index):
            # A copy keeps the stat cache, so only files that changed are hashed again.
            shutil.copyfile(real_index, index)
        else:
            read = _pin_git(cwd, "read-tree", "HEAD", env=env)
            if read is None or read.returncode != 0:
                return None
        added = _pin_git(cwd, "add", "-A", ":/", env=env)
        tree = _pin_git(cwd, "write-tree", env=env)
        if added is None or added.returncode != 0 or tree is None or tree.returncode != 0:
            return None
    tree_sha = tree.stdout.strip()
    head_tree = _pin_git(cwd, "rev-parse", "HEAD^{tree}")
    if head_tree is not None and head_tree.stdout.strip() == tree_sha:
        return head
    done = _pin_git(cwd, "commit-tree", tree_sha, "-p", head, "-m", message, env=env)
    if done is None or done.returncode != 0:
        return None
    return done.stdout.strip() or None
