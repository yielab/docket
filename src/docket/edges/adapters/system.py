"""System adapter: typed wrappers over docker, bwrap, and git.

Every shell-out to a container runtime, sandbox tool, or git lives here. Every subprocess call
catches FileNotFoundError / TimeoutExpired / OSError and degrades gracefully so a missing binary
never crashes a command. Functions are module-level and typed so callers can monkeypatch them.
Imports ``docket.core.security`` for ``match_high_risk``. ``run_verify_cmd`` is the only function
here that runs a free-form command through a real shell (``shell=True``); every other function
builds a fixed argv itself -- see ``specs/functional/security-gates.spec.md`` for the scoping
rationale, which also covers the exec-sandbox section below (mechanism only; the decision to use
one belongs to ``core/tools.py``'s ``ToolContext.sandbox``). ``gateway_active`` is an honest,
always-``False`` stub (no daemon exists) -- see ``specs/data/serve-read-api.spec.md``.
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


def gateway_active() -> bool:
    """No daemon gateway exists; always returns ``False``. Kept as a stable
    call site for existing callers -- see ``specs/data/serve-read-api.spec.md``."""
    return False


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


def docker_ps() -> list[str]:
    """Return running container names, or [] if docker is unavailable or unreachable; degrades
    gracefully, never raises. No production caller yet -- kept for a future `docket gates isolate`
    status check; re-evaluate if still uncalled when isolation grows another feature."""
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


def bwrap_available() -> bool:
    """True if bwrap is on PATH AND can actually build a sandbox right now. The binary alone is not
    enough: disabled unprivileged user namespaces (hardened hosts, some containerized CI) make bwrap
    fail at its first real invocation despite being installed -- this runs a real smoke test, not `which`."""
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
    """One probe of both backends: the strongest usable one, plus the raw per-backend result
    explaining why not. Answers "is a jail available", never "did this command run in one" -- see
    ``specs/functional/security-gates.spec.md``'s capability-reporting rule."""

    backend: SandboxBackend
    docker: bool
    bwrap: bool


def sandbox_availability() -> SandboxAvailability:
    """Probe both backends once; report the strongest usable one: docker
    (daemon reachable) beats bwrap (smoke test passes) beats none.
    `DOCKET_SANDBOX_BACKEND` overrides this for tests or an operator."""
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
    """Build the bwrap argv that jails *command* to *roots*: host filesystem
    read-only except *roots* (read-write on top), the same "contain to known
    roots" shape `toolbox.resolve_within` uses for file tools. `--unshare-all`
    isolates pid/ipc/uts/mount, so killing this call's process group cannot
    leave a namespace orphan (Linux tears the pid namespace down with it).
    Network stays shared -- see ``specs/functional/security-gates.spec.md``
    for the isolation tradeoff this defers."""
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
    """Build the ``docker run`` argv that jails *command* to *roots*: each root bind-mounted read-write,
    nothing else of the host visible. Runs as the caller's uid/gid so mounted files are not left root-owned.
    *env* injects only `ToolContext.env` (e.g. `DOCKET_SCRATCH_DIR`), never the full host environment --
    see ``specs/functional/security-gates.spec.md`` for why (env minimization) and the network-bridge rationale."""
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
    """Force-stop (and, via the original run's ``--rm``, remove) a docker-jailed
    run by name. Needed because ``docker run``'s own CLI process group does
    NOT reach the container the daemon actually runs -- killing only the CLI
    leaves it running (see ``specs/functional/security-gates.spec.md``).
    Swallows every failure: runs from a timeout handler, where a hung kill
    must not become a second hang."""
    import contextlib

    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)


_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces


def run_verify_cmd(cmd: str, cwd: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a user-supplied verification command in *cwd*. Returns
    ``(passed, combined_output)`` capped at _VERIFY_MAX_OUTPUT; the caller
    must redact secrets before tracing it. Never raises: non-zero exit,
    timeout, missing binary, or OS error all return ``False`` with a short
    error string instead.

    *cmd* is classified against ``core.security``'s high-risk classes and
    fails closed -- refused outright, never run -- before the subprocess
    starts. That is the only honest posture here: this call is synchronous
    inside a dispatch hop, with no interactive approver reachable (see
    ``specs/functional/security-gates.spec.md``). ``cwd``/``timeout`` are
    never classified: they are plumbing, not operator-composed shell text.

    Runs in its own session (``start_new_session=True``) so a timeout can kill the
    command's whole process group, not just the immediate ``sh`` child -- otherwise a
    command that backgrounds work (``build & wait``, a test runner spawning workers)
    leaves orphans behind every time it is killed on timeout. The pid is never
    registered anywhere, so this group is reachable only from inside this function;
    ``docket runs cancel`` cannot interrupt an in-flight verify command (see
    ``specs/functional/pod-dispatch.spec.md``'s Cancellation requirement 2)."""
    risk_cls = _sec.match_high_risk(cmd)
    if risk_cls is not None:
        return False, (
            f"[verify command refused: matches high-risk class '{risk_cls.name}' "
            f"({risk_cls.description}) -- see `docket gates classes`]"
        )
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        return False, f"[verify error: {exc}]"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        import contextlib
        import signal as _signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, _signal.SIGKILL)
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            proc.communicate(timeout=5)
        return False, f"[verify timed out after {timeout}s]"
    except OSError as exc:
        return False, f"[verify error: {exc}]"
    combined = (stdout + stderr).strip()
    return proc.returncode == 0, combined[:_VERIFY_MAX_OUTPUT]


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
    Implementer hop's ``HandoffArtifact`` (`core/dispatch.py`'s `_implementer_diff_probe`)."""
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
    Returns ``(success, error_message)``; degrades gracefully, returning
    ``(False, reason)`` on any error rather than raising."""
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
    names = {line.strip().lstrip("* ").strip() for line in result.stdout.splitlines()}
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
