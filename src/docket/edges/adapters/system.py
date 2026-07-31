"""System adapter: typed wrappers over systemctl, docker, and git.

Every shell-out to a host service manager, container runtime, or git lives here.

Design notes:
  * service_manager() detects the init system so commands degrade cleanly on
    macOS (launchd) or hosts with no user service manager.
  * Every subprocess call catches FileNotFoundError / TimeoutExpired / OSError
    and degrades gracefully so a missing binary never crashes a command.
  * Functions are module-level and typed so callers can monkeypatch them in tests.

G-3 (ROADMAP Phase 15): this module imports ``docket.core.security`` for its
pure, side-effect-free command classifier (``match_high_risk`` -- no I/O of
its own; the ``docket.edges.adapters.openclaw`` import that module carries
for its *other* functions is unused by the classifier path and creates no
import cycle, since ``openclaw.py`` only reaches back into this module via a
deferred, in-function import). ``run_verify_cmd`` is the one function here
that launches a fully free-form, operator-composed command string through a
real shell (``shell=True``) -- every other function in this module runs a
fixed argv list it built itself, which is not a comparable classification
target (see ``security-gates.spec.md``'s "Docket-launched process
classification" section for the full scoping rationale).
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Literal

from docket.core import security as _sec

GATEWAY_UNIT = "openclaw-gateway.service"

# Kept short so a hung daemon never blocks a CLI command.
_QUERY_TIMEOUT = 5
_RESTART_TIMEOUT = 15

# Outcome tags for restart_gateway(); the cli layer renders these via ui.*
# (edges/ has no knowledge of terminals — see ROADMAP §2).
RestartStatus = Literal["dry_run", "not_running", "restarted", "failed"]


@dataclass(frozen=True)
class RestartResult:
    """Typed outcome of restart_gateway(). Never printed here — cli/ renders it.

    ``hint`` carries the platform command a user would run next (only set for
    ``not_running``/``failed``); ``ok`` mirrors the old boolean contract (False
    only for ``failed``).
    """

    status: RestartStatus
    ok: bool
    hint: str = ""


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


def service_manager() -> str:
    """Return the init system managing user services: 'systemd', 'launchd', 'none'.

    Honors DOCKET_SERVICE_MANAGER as an override (used by tests and exotic hosts).
    """
    override = os.environ.get("DOCKET_SERVICE_MANAGER")
    if override:
        return override
    if _which("systemctl"):
        return "systemd"
    if _which("launchctl"):
        return "launchd"
    return "none"


def service_hint(action: str) -> str:
    """Return the platform command a user would run for `action` (hint messages only)."""
    mgr = service_manager()
    if mgr == "systemd":
        return f"systemctl --user {action} {GATEWAY_UNIT}"
    if mgr == "launchd":
        return f"openclaw gateway {action}  (or your launchd service)"
    return f"openclaw gateway {action}"


def systemctl_is_active(unit: str = GATEWAY_UNIT) -> bool:
    """Return True if a systemd --user unit is active (False off systemd)."""
    if service_manager() != "systemd":
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def systemctl_restart(unit: str = GATEWAY_UNIT) -> bool:
    """Restart a systemd --user unit. Returns True on success, False off systemd."""
    if service_manager() != "systemd":
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", unit],
            capture_output=True,
            timeout=_RESTART_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def systemctl_start(unit: str = GATEWAY_UNIT) -> bool:
    """Start a systemd --user unit. Returns True on success (False off systemd)."""
    if service_manager() != "systemd":
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", unit],
            capture_output=True,
            timeout=_RESTART_TIMEOUT,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def gateway_active() -> bool:
    """Return True if the OpenClaw gateway service is active."""
    return systemctl_is_active(GATEWAY_UNIT)


def restart_gateway() -> RestartResult:
    """Restart the OpenClaw gateway if it is running.

    Honors DOCKET_NO_RESTART=1 for test hermeticity. Returns a RestartResult;
    ``ok`` is True on success or when the service is already down, False if the
    restart failed. Never prints — the cli layer renders the result via ui.*.
    """
    if os.environ.get("DOCKET_NO_RESTART") == "1":
        return RestartResult(status="dry_run", ok=True)

    if not gateway_active():
        return RestartResult(status="not_running", ok=True, hint=service_hint("start"))

    if not systemctl_restart(GATEWAY_UNIT):
        return RestartResult(status="failed", ok=False, hint=service_hint("status"))
    time.sleep(2)
    return RestartResult(status="restarted", ok=True)


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


def docker_ps() -> list[str]:
    """Return running container names, or [] if docker is unavailable/unreachable.

    Degrades gracefully: a missing binary, an unreachable daemon, or a timeout
    all yield an empty list rather than raising.

    2026-07-30 (CL-2 dead-code register): no production caller yet. Kept
    (rather than deleted) because Docker workspace isolation is a live,
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


_VERIFY_MAX_OUTPUT = 4096  # cap trace payload so one bad run doesn't bloat traces


def run_verify_cmd(cmd: str, cwd: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a user-supplied verification command in *cwd*.

    Returns ``(passed, combined_output)``.  Non-zero exit → False.  A timeout,
    missing binary, or OS error also returns False with a short error description
    instead of raising.  Output is capped at _VERIFY_MAX_OUTPUT characters; the
    caller is responsible for redacting secrets before writing the output to a
    trace. The command is run with ``shell=True`` so pipelines and shell builtins
    work (e.g. ``uv run pytest && uv run ruff check .``).

    G-3: *cmd* is classified against ``core.security``'s built-in high-risk
    action classes (money-movement / prod-deploy / secret-access) BEFORE the
    subprocess is ever started -- a match fails closed, so the shell command is
    never run. Refusing outright, rather than routing to an approval prompt, is
    the only honest posture available here: this call is synchronous, inside a
    dispatch hop, with no interactive approver reachable to answer. It is the
    same posture the daemon's own ``askFallback: deny`` takes when nobody
    answers a live prompt. ``cwd``/``timeout`` are never classified -- they are
    not operator-composed shell text, just plumbing for where/how long the
    already-cleared command runs.
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

    Used both by ``edges.adapters.openclaw.agent_run`` (a timed-out agent
    turn) and ``core/runs.py``'s ``cancel_run`` (an operator-requested
    ``docket runs cancel``) — the one place that knows how to actually stop
    an in-flight hop's subprocess *and everything it shelled out to*, not
    just its immediate pid. Relies on the subprocess having been started
    with ``start_new_session=True`` (so its own pid doubles as its process
    group id — see ``agent_run``); calling this on a pid that was never
    started that way would signal whatever unrelated group happens to share
    that id, so callers must only ever pass a pid ``agent_run`` itself
    reported via its ``on_spawn`` hook.

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

    ROADMAP Phase 16 follow-up W-5b: this is now the ``diff_ref`` producer for
    an Implementer hop's ``HandoffArtifact`` (`core/dispatch.py`'s
    ``_implementer_diff_probe`` calls it against the resolved member cwd) —
    the near-term caller the 2026-07-30 CL-2 dead-code note anticipated.
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

    ROADMAP Phase 16 follow-up W-5b: the `files_changed` producer for an
    Implementer hop's `HandoffArtifact` (`core/dispatch.py`'s
    `_implementer_diff_probe`). Uses `git status --porcelain` rather than a
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
