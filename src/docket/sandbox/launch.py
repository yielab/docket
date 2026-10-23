from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from docket.governance import security as _sec
from docket.kernel import ids as _ids
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.platform.git import git_identity_env
from docket.sandbox.docker import docker_daemon_reachable, docker_kill, docker_run_argv
from docket.sandbox.landlock import landlock_argv, landlock_available
from docket.sandbox.seatbelt import seatbelt_argv, seatbelt_available

# ── exec sandbox ─────────────────────────────────────────────────────────────
#
# `agent/tools/builtins/toolbox.py`'s `run_bash` has no jail of its own -- the
# gate decides whether a command may run at all, not what it can reach once
# it does. These functions are the mechanism half of that: detecting which
# jail backend is actually usable on this host (not just installed) and
# building the argv that applies it. The *decision* to ask for one lives on
# `ToolContext.sandbox` (`agent/tools/registry.py`, opt-in, default "off") -- this
# module never decides, only detects and constructs, matching the existing
# split with `governance.security`'s classifier.

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


def sandbox_availability(choice: str | None = None) -> SandboxAvailability:
    """Probe the backends once. ``auto`` (the recorded default) is landlock on Linux or seatbelt on
    macOS, nothing else; ``docker`` is docker only, and is the one case docker is probed. *choice*
    defaults to the fleet's recorded ``sandboxBackend``. ``DOCKET_SANDBOX_BACKEND`` forces a
    backend for tests or an operator."""
    if choice is None:
        from docket.teams import fleet as _fleet

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


_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces


def credential_names() -> set[str]:
    """Every environment name docket treats as a credential: ``DOCKET_LLM_API_KEY``,
    ``TELEGRAM_BOT_TOKEN``, each name the provider catalog declares and each in the secret store.
    Reads files only; never creates the home."""
    from docket.governance import secrets as _secrets
    from docket.models import catalog as _provider

    names = {"DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN"}
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
        current_home().jail_tmp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = current_home().jail_tmp_dir / key
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
        name = _ids.new_short_id("docket-sbx")
        argv = docker_run_argv(name, all_roots, command, merged, network, read_only)
        return JailLaunch(argv, None, name)
    if backend in ("landlock", "seatbelt"):
        tmp = jail_tmp_dir(roots, cache_dir)
        all_roots = (*all_roots, tmp)
        merged = {**tmp_environment(tmp), **merged}
        build = landlock_argv if backend == "landlock" else seatbelt_argv
        return JailLaunch(build(all_roots, command, network, read_only), jailed_env(merged))
    raise InvalidInput(f"no sandbox backend to launch under: {backend}")


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
