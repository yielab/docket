from __future__ import annotations

import os
import subprocess
from pathlib import Path

from docket.kernel.home import current_home
from docket.platform.process import _SANDBOX_PROBE_TIMEOUT, _which
from docket.sandbox.landlock import _existing_resolved, _mount_dirs, _mount_reopened


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


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
    argv.append(current_home().sandbox_docker_image)
    return argv


def docker_image_has_git(image: str | None = None) -> bool | None:
    """True when *image* (default the configured jail image) has ``git`` on its PATH, False when it
    does not or is not present locally, None when the probe itself could not run or timed out."""
    try:
        result = subprocess.run(
            [
                *["docker", "run", "--rm", "--pull", "never"],
                image or current_home().sandbox_docker_image,
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
