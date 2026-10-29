"""Shared test doubles for the docket Python suite.

``FakeDriver`` is the one double for ``docket.agent.ports.RuntimeDriver``: construct one, tune its
canned behaviour through the constructor fields, and pass it (it is callable, matching dispatch's
``Runner`` type) or its bound ``run_turn``. ROADMAP section 4.5: one typed port, one shipped
driver, one fake.

The kernel ports bound at the edges each have one fake here too: ``FakeGit``, ``FakeProcess``
and ``FakeJail``. The ``fake_git``, ``fake_process`` and ``fake_jail`` fixtures in
``tests/conftest.py`` bind them; ``launcher_with`` is the real jail adapter on a host whose
probes answer as the test says.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket.agent.ports import (
    DriverCapabilities,
    FailureKind,
    SessionSummary,
    TurnResult,
    UsageReport,
    UsageTotals,
)
from docket.governance import security as _security
from docket.kernel.errors import InvalidInput
from docket.kernel.ports import (
    JailLaunch,
    JailPolicy,
    SandboxAvailability,
    SandboxBackend,
    jail_port,
)
from docket.sandbox.launch import Launcher, cache_environment, tmp_environment
from docket.teams import fleet as _fleet


@dataclass
class FakeDriver:
    """In-memory ``RuntimeDriver`` double — deterministic, no subprocess, no disk.

    ``ok``/``cost``/``fail_role`` mirror the original ``_RecordingRunner`` shims'
    constructor exactly, so existing call sites port over by substituting the
    class name. ``run_turn`` records every call in ``calls`` for assertions.
    """

    ok: bool = True
    cost: float = 0.02
    fail_role: str | None = None
    error: str = "boom"
    failure_kind: FailureKind | None = None

    sessions_by_agent: dict[str, list[SessionSummary]] = field(default_factory=dict)
    usage_by_agent: dict[str, UsageReport] = field(default_factory=dict)

    calls: list[tuple[str, str, str, int, dict[str, str] | None]] = field(default_factory=list)

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        """Callable directly as a dispatch.py ``Runner`` — forwards to ``run_turn``."""
        return self.run_turn(agent_id, session_key, message, timeout, env)

    def run_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
        *,
        on_spawn: Callable[[int], None] | None = None,
        trace_project: str | None = None,
        trace_session_key: str | None = None,
        trace_task_id: str | None = None,
        model: str | None = None,
    ) -> TurnResult:
        """``on_spawn``/``model`` are accepted (per the ``RuntimeDriver`` Protocol's own
        signature) and ignored, matching every real driver that backs onto no
        OS process a caller could report a pid for -- this fake never has one
        either. Not recorded in ``calls`` (a 5-tuple, unchanged) since no
        existing assertion needs it; add a field if a test ever does."""
        self.calls.append((agent_id, session_key, message, timeout, env))
        role = agent_id.rsplit("-", 1)[-1]
        if self.fail_role and role == self.fail_role:
            return TurnResult(False, "", 0.0, {}, self.error, failure_kind=self.failure_kind)
        return TurnResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        return list(self.sessions_by_agent.get(agent_id, []))

    def usage(self, agent_id: str) -> UsageReport:
        return self.usage_by_agent.get(agent_id, UsageReport(totals=UsageTotals()))

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            driver_name="fake",
            reports_cost_usd=self.cost > 0,
            supports_sessions=True,
        )


# -- the git, process and jail ports --------------------------------------------------------
#
# Each fake is in memory and answers what its adapter answers where git, the host or a jail
# is absent: neutral values, never an exception. A test sets the few answers it cares about
# on the instance (``fake.git_head_sha = lambda cwd: "..."``) and binds it with ``use_git`` (the
# ``fake_git`` fixture does both). ``tests/contracts`` run each fake beside its real adapter.


@dataclass
class FakeRepo:
    """What ``FakeGit`` knows about the repository at one path."""

    branch: str = "main"
    head: str = "a" * 40
    changed: list[str] = field(default_factory=list)
    tracked: list[str] = field(default_factory=list)


class FakeGit:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.repos: dict[str, FakeRepo] = {}
        self.trusted: dict[str, tuple[str, str]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def add_repo(self, cwd: str | Path, **fields: Any) -> FakeRepo:
        repo = self.repos[str(cwd)] = FakeRepo(**fields)
        return repo

    def _repo(self, cwd: str) -> FakeRepo | None:
        return self.repos.get(str(cwd)) if self.available else None

    def git_available(self) -> bool:
        return self.available

    def git_identity_env(self, root: Path) -> dict[str, str]:
        return {}

    def trust_worktree(self, path: str, git_dir: str, common_dir: str) -> None:
        self.trusted[str(path)] = (git_dir, common_dir)

    def trusted_dirs(self, path: str) -> tuple[str, str] | None:
        return self.trusted.get(str(path))

    def git_plain(self, cwd: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
        return None

    def git_current_branch(self, cwd: str) -> str:
        repo = self._repo(cwd)
        return repo.branch if repo else ""

    def git_is_repo(self, cwd: str) -> bool:
        return self._repo(cwd) is not None

    def git_changed_files(self, cwd: str, *, all_untracked: bool = False) -> list[str]:
        repo = self._repo(cwd)
        return list(repo.changed) if repo else []

    def git_worktree_changes(self, cwd: str) -> list[tuple[str, str]]:
        repo = self._repo(cwd)
        return [("M", str(Path(cwd) / name)) for name in repo.changed] if repo else []

    def git_worktree_add(
        self, repo_dir: str, worktree_path: str, branch: str, start_point: str = ""
    ) -> tuple[bool, str]:
        return False, "fake git creates no worktree"

    def git_info_exclude(self, common_dir: str, patterns: tuple[str, ...]) -> None:
        return None

    def git_worktree_remove(self, repo_dir: str, worktree_path: str) -> tuple[bool, str]:
        return False, "fake git has no worktree"

    def git_worktree_prune(self, repo_dir: str) -> None:
        return None

    def git_branch_merged(self, repo_dir: str, branch: str, into: str) -> bool:
        return False

    def git_branch_delete(self, repo_dir: str, branch: str) -> tuple[bool, str]:
        return False, "fake git has no branch"

    def git_head_sha(self, cwd: str) -> str | None:
        repo = self._repo(cwd)
        return repo.head if repo else None

    def git_read_blob(self, cwd: str, rev: str, rel: str) -> bytes | None:
        return None

    def git_path_exists_at(self, cwd: str, rev: str, rel: str) -> bool:
        return False

    def git_list_tree_dirs(self, cwd: str, rev: str, rel: str) -> list[str] | None:
        return None

    def git_merge_base(self, cwd: str, other_branch: str) -> str | None:
        return None

    def git_diff_stat(self, cwd: str, base: str, head: str | None = None) -> dict[str, int] | None:
        return None

    def git_diff(self, path: str, base: str) -> str | None:
        return None

    def git_diff_range(self, repo_dir: str, base: str, ref: str) -> str | None:
        return None

    def git_new_files_text(self, cwd: str, limit: int) -> str:
        return ""

    def git_ls_files(self, cwd: str, rev: str = "") -> list[str] | None:
        repo = self._repo(cwd)
        return list(repo.tracked) if repo else None

    def git_untracked(self, worktree: str) -> list[str]:
        return []

    def git_rev_parse(self, cwd: str, ref: str) -> str | None:
        repo = self._repo(cwd)
        return repo.head if repo and ref == "HEAD" else None

    def git_diff_names(self, cwd: str, base: str, head: str) -> list[str]:
        return []

    def git_tracked_files(self, cwd: str) -> list[str]:
        repo = self._repo(cwd)
        return list(repo.tracked) if repo else []

    def git_blob_ids(self, cwd: str, paths: list[str]) -> dict[str, str]:
        return {}

    def git_commit_all(self, cwd: str, message: str) -> str | None:
        return None

    def git_snapshot_commit(self, cwd: str, message: str) -> str | None:
        return None


class FakeProcess:
    """The host as a dict: the environment, the binaries on PATH, the stored secrets and the
    process ids that are alive."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        binaries: set[str] | None = None,
        desktop: bool = False,
    ) -> None:
        self.env: dict[str, str] = dict(env or {})
        self.binaries: set[str] = set(binaries or ())
        self.desktop = desktop
        self.secrets: dict[tuple[str, str], str] = {}
        self.alive: set[int] = set()

    def which(self, binary: str) -> bool:
        return binary in self.binaries

    def secret_tool_available(self) -> bool:
        return "secret-tool" in self.binaries

    def desktop_notifications_available(self) -> bool:
        return self.desktop

    def secret_tool_lookup(self, service: str, key: str) -> str | None:
        return self.secrets.get((service, key)) if self.secret_tool_available() else None

    def secret_tool_store(self, service: str, key: str, value: str) -> bool:
        if not self.secret_tool_available():
            return False
        self.secrets[(service, key)] = value
        return True

    def secret_tool_clear(self, service: str, key: str) -> bool:
        if not self.secret_tool_available():
            return False
        return self.secrets.pop((service, key), None) is not None

    def make_non_dumpable(self) -> None:
        return None

    def process_alive(self, pid: int) -> bool:
        return pid > 0 and pid in self.alive

    def kill_process_group(self, pgid: int, grace_s: float = 2.0) -> bool:
        if pgid not in self.alive:
            return False
        self.alive.discard(pgid)
        return True

    def env_value(self, name: str) -> str:
        return self.env.get(name, "").strip()

    def credential_env_values(self, names: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
        values = [
            raw.strip()
            for name, raw in self.env.items()
            if (name in names or name.endswith(suffixes)) and raw.strip()
        ]
        return values

    def secrets_backend_requested(self) -> str:
        return self.env.get("DOCKET_SECRETS_BACKEND", "file")

    def no_trace(self) -> bool:
        return self.env.get("DOCKET_NO_TRACE", "0") == "1"

    def no_export(self) -> bool:
        return self.env.get("DOCKET_NO_EXPORT", "0") == "1"


class RealExcept:
    """A real adapter with a few calls replaced: ``RealExcept(platform.git, git_worktree_add=f)``
    runs real git except for ``git_worktree_add``. For a test that needs the rest of the adapter
    to be real, where a fake would answer for all of it."""

    def __init__(self, real: object, **overrides: Callable[..., Any]) -> None:
        self._real = real
        for name, fn in overrides.items():
            setattr(self, name, fn)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class FakeJail:
    """A jail host with no real backend: the usable one is whatever the test sets."""

    def __init__(
        self,
        backend: SandboxBackend = "none",
        *,
        docker: bool = False,
        credentials: set[str] | None = None,
    ) -> None:
        self.availability = SandboxAvailability(backend=backend, docker=docker)
        self.credentials: set[str] = set(credentials or ())
        self.run_result: tuple[int | None, str] = (0, "")
        self.commands: list[tuple[str, str, JailPolicy | None]] = []
        self.killed: list[str] = []
        self.docker_has_git: bool | None = True
        self.git_dirs: dict[str, tuple[str, str]] = {}

    def sandbox_availability(self, choice: str | None = None) -> SandboxAvailability:
        return self.availability

    def credential_names(self) -> set[str]:
        return {"DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN"} | self.credentials

    def task_environment(
        self, overlay: dict[str, str] | None = None, cache_dir: Path | None = None
    ) -> dict[str, str]:
        names = self.credential_names()
        merged = {k: v for k, v in os.environ.items() if k not in names}
        if cache_dir is not None:
            merged.update(cache_environment(cache_dir))
        merged.update(overlay or {})
        return merged

    def jail_tmp_dir(self, roots: tuple[Path, ...], cache_dir: Path | None) -> Path:
        path = (cache_dir or roots[0]) / "tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def tmp_environment(self, tmp: Path) -> dict[str, str]:
        return tmp_environment(tmp)

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
        if backend == "none":
            raise InvalidInput(f"no sandbox backend to launch under: {backend}")
        return JailLaunch([f"fake-{backend}", command], dict(env or {}))

    def run_command(
        self,
        cmd: str,
        cwd: str,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        jail: JailPolicy | None = None,
    ) -> tuple[int | None, str]:
        self.commands.append((cmd, cwd, jail))
        return self.run_result

    def docker_daemon_reachable(self) -> bool:
        return self.availability.docker

    def docker_image_has_git(self, image: str | None = None) -> bool | None:
        return self.docker_has_git

    def docker_kill(self, container_name: str) -> None:
        self.killed.append(container_name)

    def docker_command_argv(
        self,
        container_name: str,
        roots: tuple[Path, ...],
        argv: list[str],
        env: dict[str, str] | None,
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]:
        return ["fake-docker", container_name, *argv]

    def landlock_command_argv(
        self,
        roots: tuple[Path, ...],
        argv: list[str],
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]:
        return ["fake-landlock", *argv]

    def seatbelt_command_argv(
        self,
        roots: tuple[Path, ...],
        argv: list[str],
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]:
        return ["fake-seatbelt", *argv]

    def worktree_git_dirs(self, path: str) -> tuple[str, str] | None:
        return self.git_dirs.get(path)


def launcher_with(
    *,
    landlock: bool | None = None,
    seatbelt: bool | None = None,
    docker: bool | None = None,
    credentials: set[str] | None = None,
) -> Launcher:
    """The real jail adapter on a host whose backend probes answer as given (``None`` keeps the
    real probe). It reads the recorded backend from the fleet of the test's home and knows no
    credential beyond *credentials*."""
    probes: dict[str, Callable[[], bool]] = {}
    for name, answer in (("landlock", landlock), ("seatbelt", seatbelt), ("docker", docker)):
        if answer is not None:
            probes[f"probe_{name}"] = lambda answer=answer: answer  # type: ignore[misc]
    return Launcher(
        recorded_backend=_fleet.get_sandbox_backend,
        credential_source=lambda: set(credentials or ()),
        high_risk=_security.match_high_risk,
        **probes,
    )


@contextmanager
def landlock_host() -> Iterator[None]:
    """A host whose landlock probe answers yes, unless the test already bound its own jail fake."""
    if isinstance(jail_port.current(), Launcher):
        with jail_port.use(launcher_with(landlock=True)):
            yield
    else:
        yield
