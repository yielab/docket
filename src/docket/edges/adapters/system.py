"""System adapter: typed wrappers over docker, bwrap, and git.

Every shell-out to a container runtime, sandbox tool, or git lives here.

Design notes:
  * Every subprocess call catches FileNotFoundError / TimeoutExpired / OSError
    and degrades gracefully so a missing binary never crashes a command.
  * Functions are module-level and typed so callers can monkeypatch them in tests.

This module imports ``docket.core.security`` for its pure, side-effect-free
command classifier (``match_high_risk`` -- no I/O of its own). ``run_verify_cmd``
is the one function here that launches a fully free-form, operator-composed
command string through a real shell (``shell=True``) -- every other function
in this module runs a fixed argv list it built itself, which is not a
comparable classification target (see ``security-gates.spec.md``'s
"Docket-launched process classification" section for the full scoping
rationale).

The "exec sandbox" section below adds bwrap alongside docker as a second,
weaker-but-dependency-free jail backend for ``edges/adapters/toolbox.py``'s
``run_bash``. Detection (``sandbox_availability``) and argv construction
(``bwrap_argv``/``docker_run_argv``) are mechanism only, the same "no policy
vocabulary" split ``core.security``'s classifier already has from this
module -- *whether* to ask for a jail is a decision made by
``core/tools.py``'s ``ToolContext.sandbox`` (opt-in, default ``"off"``), never
by this module.

There is no daemon and no gateway process any more, so there is nothing left
to start, restart, or probe. ``gateway_active`` stays as an honest,
always-``False`` stub (see its docstring) -- ``docket snapshot`` and the
``serve`` read API (``specs/data/serve-read-api.spec.md``) still expose a
``gateway`` field to external consumers, and this keeps that field truthful
without a breaking API change. ``restart_gateway()`` was removed outright
rather than kept as a matching stub: unlike ``gateway_active``, nothing
external ever observed its return value, so every call site was pure
ceremony (call it, render a result that prints nothing for the only status a
real call could ever produce) -- a no-op that many sites ceremonially call
is dead code, not a truthful stub worth keeping.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
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


def secret_tool_lookup(service: str, key: str) -> str | None:
    """Look up one secret's value in the OS keyring via `secret-tool lookup`.

    Returns ``None`` on any failure (binary missing, timeout, no match) --
    ``core/secrets.py``'s keyring backend treats that as "no value", never
    an error. This is the one shell-out `core/secrets.py` needs -- every
    shell-out funnels through ``edges/adapters/``, never ``core/`` directly.
    """
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


def gateway_active() -> bool:
    """No daemon gateway exists any more.

    Kept as a stable, always-``False`` call site so every existing caller
    (``cli/__init__.py``'s status line, ``cli/_doctor.py``, ``serve.py``'s
    ``/status.json``/``/metrics``/``/health``) reads an honest answer instead
    of needing an individual rewrite.
    """
    return False


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


def docker_ps() -> list[str]:
    """Return running container names, or [] if docker is unavailable/unreachable.

    Degrades gracefully: a missing binary, an unreachable daemon, or a timeout
    all yield an empty list rather than raising.

    No production caller yet. Kept (rather than deleted) because Docker
    workspace isolation is a live,
    opt-in feature (`docket gates isolate`) and this is the obvious primitive
    for a future `docket doctor`/`docket gates isolate status` check that
    confirms an isolated agent's container is actually running, not just
    configured — the tested, typed adapter is cheaper to keep than to
    rewrite when that check gets built. Re-evaluate if it still has no
    caller by the time isolation grows another feature.
    """
    if not docker_available():
        return []
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


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

SandboxBackend = Literal["docker", "bwrap", "none"]

# Detection probes must be fast (they run on every "auto" call) and must
# never hang a tool call over a jail that turns out to be unusable.
_SANDBOX_PROBE_TIMEOUT = 5


def docker_daemon_reachable() -> bool:
    """True if docker is on PATH AND its daemon actually answers.

    `docker_available()` only checks the binary. A daemon that is not
    running, not reachable (a socket permission the current user lacks), or
    simply absent behind an installed CLI is common enough -- rootless
    setups, a freshly installed package whose service was never started --
    that treating "binary present" as "usable" is exactly the silent
    degrade this card exists to prevent.
    """
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


def bwrap_available() -> bool:
    """True if bwrap is on PATH AND can actually build a sandbox right now.

    The binary alone is not enough evidence: a kernel with unprivileged user
    namespaces disabled (hardened hosts, and some already-containerized CI
    runners) makes bwrap fail at its very first real invocation despite
    being installed. Detection therefore runs a real, harmless,
    side-effect-free smoke test -- bind the whole host root over itself and
    run `true` -- rather than trusting `which`.
    """
    if not _which("bwrap"):
        return False
    try:
        result = subprocess.run(
            [
                "bwrap",
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind",
                "/",
                "/",
                "--",
                "/bin/true",
            ],
            capture_output=True,
            timeout=_SANDBOX_PROBE_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@dataclass(frozen=True)
class SandboxAvailability:
    """One probe of both backends: the strongest usable one, and the raw
    per-backend result that explains why not, when neither is usable.

    This is the "am I actually sandboxed, and by what" capability check --
    answerable with no command run at all, for `docket doctor` and this
    card's own honest per-call reporting (`toolbox.run_bash`'s ``[sandbox:
    ...]`` marker uses `docker`/`bwrap` to build the reason when `backend`
    comes back "none"). It is deliberately a different question from "did
    *this* command run in a jail" -- a boolean here answers the first, never
    the second.
    """

    backend: SandboxBackend
    docker: bool
    bwrap: bool


def sandbox_availability() -> SandboxAvailability:
    """Probe both backends once and report the strongest usable one.

    Descending strength: a container (docker, only if its daemon answers)
    beats a namespace jail (bwrap, only if it can really build one) beats no
    jail at all. Honors DOCKET_SANDBOX_BACKEND as an override -- for tests,
    and for an operator who wants to force or disable a backend regardless
    of what is actually installed.
    """
    docker_ok = docker_daemon_reachable()
    bwrap_ok = bwrap_available()
    override = os.environ.get("DOCKET_SANDBOX_BACKEND")
    backend: SandboxBackend
    if override in ("docker", "bwrap", "none"):
        backend = override  # type: ignore[assignment]
    elif docker_ok:
        backend = "docker"
    elif bwrap_ok:
        backend = "bwrap"
    else:
        backend = "none"
    return SandboxAvailability(backend=backend, docker=docker_ok, bwrap=bwrap_ok)


def bwrap_argv(roots: tuple[Path, ...], command: str) -> list[str]:
    """Build the bwrap argv that jails *command* to *roots*.

    The whole host filesystem is bound read-only over itself, then each of
    *roots* is re-bound read-write on top -- the same "contain to a known
    set of roots, not a blanket allow" shape `toolbox.resolve_within` uses
    for file tools, extended to the exec surface. `--unshare-all` gives the
    command its own pid/ipc/uts/mount namespaces, so it cannot see or signal
    any process outside its own tree -- and, since Linux tears down an
    entire pid namespace when its first process dies, killing this call's
    process group cannot leave a namespace orphan behind (verified: see
    test_sandboxed_exec.py's process-tree test). Network is left
    shared (`--share-net` overrides `--unshare-all`'s default): most
    legitimate bash-tool work (git fetch/push, package installs) needs it,
    and cutting it is a materially larger, separate decision this card does
    not make.
    """
    argv = [
        "bwrap",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    for root in roots:
        resolved = str(root.resolve())
        argv += ["--bind", resolved, resolved]
    argv += ["--", "/bin/sh", "-c", command]
    return argv


def docker_run_argv(
    container_name: str, roots: tuple[Path, ...], command: str, env: dict[str, str] | None
) -> list[str]:
    """Build the ``docker run`` argv that jails *command* to *roots*.

    Each of *roots* is bind-mounted read-write at its own path; nothing else
    of the host is visible at all (a container's filesystem is empty apart
    from the image, which is the whole point). Runs as the calling user's
    uid/gid so files it creates in a mounted root are not left root-owned on
    the host (verified: the docker default -- no `--user` -- does exactly
    that). *env* carries only what the caller explicitly asked to inject
    (`ToolContext.env`, e.g. `DOCKET_SCRATCH_DIR`) -- deliberately **not**
    the full host environment: a container starts with none of it by
    default, and forwarding it back in would hand a jailed command every
    credential the unsandboxed path has, undermining the containment this
    backend exists to add. Network is left at the image's default bridge,
    for the same reason `bwrap_argv` keeps `--share-net`.
    """
    argv = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]
    for root in roots:
        resolved = str(root.resolve())
        argv += ["-v", f"{resolved}:{resolved}"]
    argv += ["-w", str(roots[0].resolve())]
    for key, value in (env or {}).items():
        argv += ["-e", f"{key}={value}"]
    argv += [_cfg.SANDBOX_DOCKER_IMAGE, "sh", "-c", command]
    return argv


def docker_kill(container_name: str) -> None:
    """Force-stop (and, via the original run's ``--rm``, remove) a
    docker-jailed run by name. Best-effort; never raises.

    The one behavior a container backend needs that a plain subprocess does
    not: ``docker run``'s own CLI process is a thin client whose process
    group does NOT reach the container the daemon actually runs -- killing
    only the CLI leaves the container executing under dockerd, an orphan no
    host process is watching (verified empirically: a ``docker run --rm``
    process killed via its own process group left its container running).
    ``docker kill`` reaches the daemon directly instead. Swallows every
    failure -- this runs from a timeout handler, where a hung kill must not
    become a second hang, and a container that already exited on its own is
    not an error here.
    """
    import contextlib

    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)


_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces


def run_verify_cmd(cmd: str, cwd: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a user-supplied verification command in *cwd*.

    Returns ``(passed, combined_output)``.  Non-zero exit → False.  A timeout,
    missing binary, or OS error also returns False with a short error description
    instead of raising.  Output is capped at _VERIFY_MAX_OUTPUT characters; the
    caller is responsible for redacting secrets before writing the output to a
    trace. The command is run with ``shell=True`` so pipelines and shell builtins
    work (e.g. ``uv run pytest && uv run ruff check .``).

    *cmd* is classified against ``core.security``'s built-in high-risk
    action classes (money-movement / prod-deploy / secret-access) BEFORE the
    subprocess is ever started -- a match fails closed, so the shell command is
    never run. Refusing outright, rather than routing to an approval prompt, is
    the only honest posture available here: this call is synchronous, inside a
    dispatch hop, with no interactive approver reachable to answer it.
    ``cwd``/``timeout`` are never classified -- they are not operator-composed
    shell text, just plumbing for where/how long the already-cleared command
    runs.
    """
    risk_cls = _sec.match_high_risk(cmd)
    if risk_cls is not None:
        return False, (
            f"[verify command refused: matches high-risk class '{risk_cls.name}' "
            f"({risk_cls.description}) -- see `docket gates classes`]"
        )
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        combined = (result.stdout + result.stderr).strip()
        return result.returncode == 0, combined[:_VERIFY_MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        return False, f"[verify timed out after {timeout}s]"
    except (FileNotFoundError, OSError) as exc:
        return False, f"[verify error: {exc}]"


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
    """SIGTERM a process group; escalate to SIGKILL if still alive after *grace_s*.

    Used by ``core/runs.py``'s ``cancel_run`` (an operator-requested
    ``docket runs cancel``) — the one place that knows how to actually stop
    an in-flight hop's subprocess *and everything it shelled out to*, not
    just its immediate pid. Relies on the subprocess having been started
    with ``start_new_session=True`` (so its own pid doubles as its process
    group id); calling this on a pid that was never started that way would
    signal whatever unrelated group happens to share that id, so callers
    must only ever pass a pid reported via a driver's own ``on_spawn`` hook.

    Returns ``True`` if the group was observed alive at all (a signal was
    meaningfully sent), ``False`` if it was already gone — a harmless no-op,
    not an error. Never raises: a process that exits mid-call (a real race,
    not a bug) is treated the same as one that was already gone.
    """
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
    """Return the current git branch for `cwd`, or '' if not a repo / unavailable.

    Degrades gracefully on a missing binary, a non-repo directory, or a timeout.

    This is the ``diff_ref`` producer for an Implementer hop's
    ``HandoffArtifact`` (`core/dispatch.py`'s ``_implementer_diff_probe``
    calls it against the resolved member cwd).
    """
    if not git_available():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
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
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def git_changed_files(cwd: str) -> list[str]:
    """Return paths with uncommitted changes in `cwd` (staged, unstaged, untracked).

    The `files_changed` producer for an Implementer hop's `HandoffArtifact`
    (`core/dispatch.py`'s `_implementer_diff_probe`). Uses `git status
    --porcelain` rather than a
    diff against a fixed base ref, so it reflects the real working-tree state
    regardless of whether the Implementer has committed anything this hop —
    the same "check the tree, not an assumption about it" spirit as
    `resolve_member_cwd`. A rename line (`R  old -> new`) reports only the
    new path. Degrades to `[]` on a missing git binary, a non-repo directory,
    a timeout, or a clean tree — never raises. Sorted for determinism (the
    porcelain output order is otherwise directory-scan order, which is not
    guaranteed stable across platforms).
    """
    if not git_available():
        return []
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
        )
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


def git_worktree_add(repo_dir: str, worktree_path: str, branch: str) -> tuple[bool, str]:
    """Create a git worktree at ``worktree_path`` on a new branch ``branch``.

    Returns ``(success, error_message)``.  On success the worktree directory
    exists and the branch is checked out there.  Degrades gracefully: returns
    ``(False, reason)`` on any error rather than raising.
    """
    if not git_available():
        return False, "git not found on PATH"
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "worktree", "add", "-b", branch, worktree_path],
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
    """Remove the git worktree at ``worktree_path``.

    Uses ``--force`` to handle unclean worktrees.  Returns ``(success, message)``.
    Degrades gracefully on errors.
    """
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
