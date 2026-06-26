"""System adapter: typed wrappers over systemctl, docker, and git.

Every shell-out to a host service manager, container runtime, or git lives here.

Design notes:
  * service_manager() detects the init system so commands degrade cleanly on
    macOS (launchd) or hosts with no user service manager.
  * Every subprocess call catches FileNotFoundError / TimeoutExpired / OSError
    and degrades gracefully so a missing binary never crashes a command.
  * Functions are module-level and typed so callers can monkeypatch them in tests.
"""

from __future__ import annotations

import os
import subprocess
import time

from docket import ui

GATEWAY_UNIT = "openclaw-gateway.service"

# Kept short so a hung daemon never blocks a CLI command.
_QUERY_TIMEOUT = 5
_RESTART_TIMEOUT = 15


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


def restart_gateway() -> bool:
    """Restart the OpenClaw gateway if it is running.

    Honors DOCKET_NO_RESTART=1 for test hermeticity. Returns True on success or
    when the service is already down; False if the restart failed.
    """
    if os.environ.get("DOCKET_NO_RESTART") == "1":
        print("[dry-run] restart_gateway called")
        return True

    if not gateway_active():
        ui.warn("Gateway not running. Start it with:")
        print(f"  {service_hint('start')}")
        return True  # nothing to restart — not an error

    ui.info("Restarting gateway...")
    if not systemctl_restart(GATEWAY_UNIT):
        ui.warn("Gateway restart failed.")
        print(f"  Check: {service_hint('status')}")
        return False
    time.sleep(2)
    ui.success("Gateway restarted")
    return True


def docker_available() -> bool:
    """Return True if a docker binary is on PATH (does not verify daemon reachability)."""
    return _which("docker")


def docker_ps() -> list[str]:
    """Return running container names, or [] if docker is unavailable/unreachable.

    Degrades gracefully: a missing binary, an unreachable daemon, or a timeout
    all yield an empty list rather than raising.
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
    """
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


def git_available() -> bool:
    """Return True if a git binary is on PATH."""
    return _which("git")


def git_current_branch(cwd: str) -> str:
    """Return the current git branch for `cwd`, or '' if not a repo / unavailable.

    Degrades gracefully on a missing binary, a non-repo directory, or a timeout.
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
