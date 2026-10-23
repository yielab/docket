"""The sandbox port: detecting which jail backend this host can use, building the argv that applies
it, and running a command under it.

The *decision* to ask for a jail lives with the caller (``ToolContext.sandbox``, the pod's
isolation setting); this port only detects and constructs. The real adapter is
``sandbox.launch.Launcher``, built by ``bootstrap`` with the policy it must consult (the fleet's
recorded backend, the credential names, the high-risk classes); a test binds
``tests.support.fakes.FakeJail`` with ``use_jail``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from docket.kernel.binding import Binding

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


_BINDING: Binding[Jail] = Binding("jail")
jail: Jail = _BINDING.proxy()


def bind_jail(adapter: Jail) -> None:
    _BINDING.bind(adapter)


def use_jail(adapter: Jail) -> AbstractContextManager[Jail]:
    """Make *adapter* the jail of this block (a test's fake)."""
    return _BINDING.use(adapter)
