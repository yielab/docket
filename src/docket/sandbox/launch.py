from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from docket.kernel import ids as _ids
from docket.kernel.errors import InvalidInput
from docket.kernel.git import git as _git
from docket.kernel.home import current_home
from docket.kernel.jail import JailLaunch, JailPolicy, SandboxAvailability, SandboxBackend
from docket.sandbox import docker as _docker
from docket.sandbox import landlock as _landlock
from docket.sandbox import seatbelt as _seatbelt

# ── exec sandbox ─────────────────────────────────────────────────────────────
#
# `agent/tools/builtins/toolbox.py`'s `run_bash` has no jail of its own -- the
# gate decides whether a command may run at all, not what it can reach once
# it does. The `Launcher` is the mechanism half of that: detecting which
# jail backend is actually usable on this host (not just installed) and
# building the argv that applies it. The *decision* to ask for one lives on
# `ToolContext.sandbox` (`agent/tools/registry.py`, opt-in, default "off") -- this
# module never decides, only detects and constructs, matching the existing
# split with `governance.security`'s classifier. What it must consult from other contexts
# (the fleet's recorded backend, the credential names, the high-risk classes) it is given by
# `bootstrap` at construction.


class HighRiskClass(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...


_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces
_CACHE_ENV_VARS = (
    "HOME",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "UV_CACHE_DIR",
    "PIP_CACHE_DIR",
    "npm_config_cache",
)
_TMP_ENV_VARS = ("TMPDIR", "TMP", "TEMP")


def cache_environment(cache_dir: Path) -> dict[str, str]:
    """The six variables that point a tool's home and caches at *cache_dir*."""
    return {name: str(cache_dir) for name in _CACHE_ENV_VARS}


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


@dataclass(frozen=True)
class Launcher:
    """The ``kernel.jail.Jail`` adapter. The first three fields are what other contexts own and
    ``bootstrap`` supplies; the probes default to the backends' own and are what a unit test
    replaces."""

    recorded_backend: Callable[[], str]
    credential_source: Callable[[], set[str]]
    high_risk: Callable[[str], HighRiskClass | None]
    probe_landlock: Callable[[], bool] = _landlock.landlock_available
    probe_seatbelt: Callable[[], bool] = _seatbelt.seatbelt_available
    probe_docker: Callable[[], bool] = _docker.docker_daemon_reachable

    def sandbox_availability(self, choice: str | None = None) -> SandboxAvailability:
        """Probe the backends once. ``auto`` (the recorded default) is landlock on Linux or
        seatbelt on macOS, nothing else; ``docker`` is docker only, and is the one case docker is
        probed. *choice* defaults to the fleet's recorded ``sandboxBackend``.
        ``DOCKET_SANDBOX_BACKEND`` forces a backend for tests or an operator."""
        if choice is None:
            choice = self.recorded_backend()
        override = os.environ.get("DOCKET_SANDBOX_BACKEND")
        landlock_ok = self.probe_landlock()
        seatbelt_ok = self.probe_seatbelt()
        docker_ok = (choice == "docker" or override == "docker") and self.probe_docker()
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

    def credential_names(self) -> set[str]:
        """Every environment name docket treats as a credential: ``DOCKET_LLM_API_KEY``,
        ``TELEGRAM_BOT_TOKEN`` and what the source adds (the provider catalog's names and each in
        the secret store). Reads files only; never creates the home."""
        return {"DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN"} | self.credential_source()

    def task_environment(
        self, overlay: dict[str, str] | None = None, cache_dir: Path | None = None
    ) -> dict[str, str]:
        """The host environment minus docket's credentials (``credential_names``), with the pod
        cache variables (when *cache_dir* is given) and then *overlay* applied last."""
        names = self.credential_names()
        merged = {k: v for k, v in os.environ.items() if k not in names}
        if cache_dir is not None:
            merged.update(cache_environment(cache_dir))
        if overlay:
            merged.update(overlay)
        return merged

    def jail_tmp_dir(self, roots: tuple[Path, ...], cache_dir: Path | None) -> Path:
        """The launch's private temp dir (0700): ``<cache_dir>/tmp``, else ``JAIL_TMP_DIR``
        keyed by the first root. Reused across runs like the cache."""
        if cache_dir is not None:
            path = cache_dir / "tmp"
        else:
            key = hashlib.sha256(str(roots[0].resolve()).encode()).hexdigest()[:12]
            current_home().jail_tmp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = current_home().jail_tmp_dir / key
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
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
        """The one place a backend, the roots and *extra_rw* become a jailed shell command. The
        first root is the cwd; *extra_rw* and *cache_dir* (home and caches) are writable beside
        the roots, *read_only* (the operator's toolchain grants) readable. Raises ``InvalidInput``
        for ``none``."""
        all_roots = (*roots, *extra_rw)
        merged = {**_git.git_identity_env(roots[0].resolve()), **(env or {})}
        if cache_dir is not None:
            all_roots = (*all_roots, cache_dir.resolve())
            merged = {**cache_environment(cache_dir), **merged}
        if backend == "docker":
            name = _ids.new_short_id("docket-sbx")
            argv = _docker.docker_run_argv(name, all_roots, command, merged, network, read_only)
            return JailLaunch(argv, None, name)
        if backend in ("landlock", "seatbelt"):
            tmp = self.jail_tmp_dir(roots, cache_dir)
            all_roots = (*all_roots, tmp)
            merged = {**tmp_environment(tmp), **merged}
            build = _landlock.landlock_argv if backend == "landlock" else _seatbelt.seatbelt_argv
            return JailLaunch(build(all_roots, command, network, read_only), jailed_env(merged))
        raise InvalidInput(f"no sandbox backend to launch under: {backend}")

    def run_command(
        self,
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

        *cmd* is classified against ``governance.security``'s high-risk classes and
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
        risk_cls = self.high_risk(cmd)
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
                    env=self.task_environment(env),
                )
            else:
                backend = self.sandbox_availability().backend
                if backend == "none" or not cwd:
                    return (
                        None,
                        "[verify not run: no sandbox backend is usable or no working directory]",
                    )
                launch = self.jail_launch(
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
                _docker.docker_kill(container)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, _signal.SIGKILL)
            with contextlib.suppress(subprocess.SubprocessError, OSError):
                proc.communicate(timeout=5)
            return None, f"[verify timed out after {timeout}s]"
        except OSError as exc:
            return None, f"[verify error: {exc}]"
        combined = (stdout + stderr).strip()
        return proc.returncode, combined[:_VERIFY_MAX_OUTPUT]

    def docker_daemon_reachable(self) -> bool:
        return self.probe_docker()

    def docker_image_has_git(self, image: str | None = None) -> bool | None:
        return _docker.docker_image_has_git(image)

    def docker_kill(self, container_name: str) -> None:
        _docker.docker_kill(container_name)

    def docker_command_argv(
        self,
        container_name: str,
        roots: tuple[Path, ...],
        argv: list[str],
        env: dict[str, str] | None,
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]:
        return _docker.docker_command_argv(container_name, roots, argv, env, network, read_only)

    def landlock_command_argv(
        self,
        roots: tuple[Path, ...],
        argv: list[str],
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]:
        return _landlock.landlock_command_argv(roots, argv, network, read_only)

    def seatbelt_command_argv(
        self,
        roots: tuple[Path, ...],
        argv: list[str],
        network: bool = True,
        read_only: tuple[Path, ...] = (),
    ) -> list[str]:
        return _seatbelt.seatbelt_command_argv(roots, argv, network, read_only)

    def worktree_git_dirs(self, path: str) -> tuple[str, str] | None:
        return _landlock.worktree_git_dirs(path)
