"""The ports docket binds at its edges: git, the host's process tools and the sandbox launcher.

A port is a ``Protocol`` here plus a ``Binding``: ``bootstrap`` binds the real adapter once per
entry (``bind_git``, ``bind_process``, ``bind_jail``), and a test swaps in a fake for a block
with ``<port>_port.use(fake)``, the shape ``clock.use_clock`` gives the clock. The object a
caller imports (``git``, ``process``, ``jail``) forwards each attribute to whatever its binding
holds at call time, so a caller keeps writing ``git.git_head_sha(cwd)`` and never names an
adapter. Everything is in one module because ``kernel`` modules import nothing from docket.

Real adapters: ``platform.git``, ``platform.process`` and ``sandbox.launch.Launcher``. Fakes:
``tests/support/fakes.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, Protocol, TypeVar, cast

T = TypeVar("T")


class PortNotBound(RuntimeError):
    """A port was used before any entry bound an adapter to it."""


class Binding(Generic[T]):
    def __init__(self, name: str) -> None:
        self._name = name
        self._bound: T | None = None
        self._override: ContextVar[T | None] = ContextVar(f"docket_{name}_port", default=None)

    def bind(self, adapter: T) -> None:
        """Make *adapter* the process default; called by an entry point, never by a caller."""
        self._bound = adapter

    @contextmanager
    def use(self, adapter: T) -> Iterator[T]:
        """Make *adapter* the one of this block. Threads need ``kernel.threads`` to inherit it."""
        token = self._override.set(adapter)
        try:
            yield adapter
        finally:
            self._override.reset(token)

    def current(self) -> T:
        adapter = self._override.get() or self._bound
        if adapter is None:
            raise PortNotBound(
                f"the {self._name} port has no adapter: an entry point must call "
                "docket.bootstrap.bind_adapters() before it runs"
            )
        return adapter

    def proxy(self) -> T:
        return cast(T, _Proxy(self))


class _Proxy:
    def __init__(self, binding: Binding[Any]) -> None:
        self._binding = binding

    def __getattr__(self, name: str) -> object:
        return getattr(self._binding.current(), name)


# ── git ──────────────────────────────────────────────────────────────────────


class GitResult(Protocol):
    """What a caller reads of a finished git command (``subprocess.CompletedProcess`` fits)."""

    returncode: int
    stdout: str
    stderr: str


class Git(Protocol):
    def git_available(self) -> bool: ...
    def git_identity_env(self, root: Path) -> dict[str, str]: ...
    def trust_worktree(self, path: str, git_dir: str, common_dir: str) -> None: ...
    def trusted_dirs(self, path: str) -> tuple[str, str] | None:
        """The ``(git dir, common dir)`` docket recorded for the worktree at *path*, if any."""
        ...

    def git_plain(self, cwd: str, args: list[str]) -> GitResult | None:
        """``git -C cwd <args>`` with no trusted-tree handling; ``None`` when git cannot run."""
        ...

    def git_current_branch(self, cwd: str) -> str: ...
    def git_is_repo(self, cwd: str) -> bool: ...
    def git_changed_files(self, cwd: str, *, all_untracked: bool = False) -> list[str]: ...
    def git_worktree_changes(self, cwd: str) -> list[tuple[str, str]]: ...
    def git_worktree_add(
        self, repo_dir: str, worktree_path: str, branch: str, start_point: str = ""
    ) -> tuple[bool, str]: ...
    def git_info_exclude(self, common_dir: str, patterns: tuple[str, ...]) -> None: ...
    def git_worktree_remove(self, repo_dir: str, worktree_path: str) -> tuple[bool, str]: ...
    def git_worktree_prune(self, repo_dir: str) -> None: ...
    def git_branch_merged(self, repo_dir: str, branch: str, into: str) -> bool: ...
    def git_branch_delete(self, repo_dir: str, branch: str) -> tuple[bool, str]: ...
    def git_head_sha(self, cwd: str) -> str | None: ...
    def git_read_blob(self, cwd: str, rev: str, rel: str) -> bytes | None: ...
    def git_path_exists_at(self, cwd: str, rev: str, rel: str) -> bool: ...
    def git_list_tree_dirs(self, cwd: str, rev: str, rel: str) -> list[str] | None: ...
    def git_merge_base(self, cwd: str, other_branch: str) -> str | None: ...
    def git_diff_stat(
        self, cwd: str, base: str, head: str | None = None
    ) -> dict[str, int] | None: ...
    def git_diff(self, path: str, base: str) -> str | None: ...
    def git_diff_range(self, repo_dir: str, base: str, ref: str) -> str | None: ...
    def git_new_files_text(self, cwd: str, limit: int) -> str: ...
    def git_ls_files(self, cwd: str) -> list[str] | None: ...
    def git_untracked(self, worktree: str) -> list[str]: ...
    def git_rev_parse(self, cwd: str, ref: str) -> str | None: ...
    def git_diff_names(self, cwd: str, base: str, head: str) -> list[str]: ...
    def git_tracked_files(self, cwd: str) -> list[str]: ...
    def git_blob_ids(self, cwd: str, paths: list[str]) -> dict[str, str]: ...
    def git_commit_all(self, cwd: str, message: str) -> str | None: ...
    def git_snapshot_commit(self, cwd: str, message: str) -> str | None: ...


git_port: Binding[Git] = Binding("git")
git: Git = git_port.proxy()


def bind_git(adapter: Git) -> None:
    git_port.bind(adapter)


# ── process ──────────────────────────────────────────────────────────────────


PROBE_TIMEOUT_S = 5


class Process(Protocol):
    def which(self, binary: str) -> bool:
        """Whether *binary* resolves on PATH (``False`` on any error)."""
        ...

    def secret_tool_available(self) -> bool: ...
    def desktop_notifications_available(self) -> bool: ...
    def secret_tool_lookup(self, service: str, key: str) -> str | None: ...
    def secret_tool_store(self, service: str, key: str, value: str) -> bool: ...
    def secret_tool_clear(self, service: str, key: str) -> bool: ...
    def make_non_dumpable(self) -> None: ...
    def process_alive(self, pid: int) -> bool: ...
    def kill_process_group(self, pgid: int, grace_s: float = 2.0) -> bool: ...
    def env_value(self, name: str) -> str: ...
    def credential_env_values(
        self, names: tuple[str, ...], suffixes: tuple[str, ...]
    ) -> list[str]: ...
    def secrets_backend_requested(self) -> str: ...
    def no_trace(self) -> bool: ...
    def no_export(self) -> bool: ...


process_port: Binding[Process] = Binding("process")
process: Process = process_port.proxy()


def bind_process(adapter: Process) -> None:
    process_port.bind(adapter)


# ── jail ─────────────────────────────────────────────────────────────────────


SandboxBackend = Literal["landlock", "seatbelt", "docker", "none"]


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


class Jail(Protocol):
    def sandbox_availability(self, choice: str | None = None) -> SandboxAvailability:
        """Probe the backends once. *choice* defaults to the fleet's recorded backend."""
        ...

    def credential_names(self) -> set[str]:
        """Every environment name docket treats as a credential."""
        ...

    def task_environment(
        self, overlay: dict[str, str] | None = None, cache_dir: Path | None = None
    ) -> dict[str, str]:
        """The host environment minus the credentials, the cache variables, then *overlay*."""
        ...

    def jail_tmp_dir(self, roots: tuple[Path, ...], cache_dir: Path | None) -> Path: ...
    def tmp_environment(self, tmp: Path) -> dict[str, str]: ...
    def jail_launch(
        self,
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
        """The one place a backend and the roots become a jailed shell command. Raises
        ``InvalidInput`` for ``none``."""
        ...

    def run_command(
        self,
        cmd: str,
        cwd: str,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        jail: JailPolicy | None = None,
    ) -> tuple[int | None, str]:
        """Run a verification command; ``(exit status, capped output)``, never raises."""
        ...

    def docker_daemon_reachable(self) -> bool: ...
    def docker_image_has_git(self, image: str | None = None) -> bool | None: ...
    def docker_kill(self, container_name: str) -> None: ...
    def docker_command_argv(
        self,
        container_name: str,
        roots: tuple[Path, ...],
        argv: list[str],
        env: dict[str, str] | None,
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]: ...
    def landlock_command_argv(
        self,
        roots: tuple[Path, ...],
        argv: list[str],
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]: ...
    def seatbelt_command_argv(
        self,
        roots: tuple[Path, ...],
        argv: list[str],
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]: ...
    def worktree_git_dirs(self, path: str) -> tuple[str, str] | None: ...


jail_port: Binding[Jail] = Binding("jail")
jail: Jail = jail_port.proxy()


def bind_jail(adapter: Jail) -> None:
    jail_port.bind(adapter)
