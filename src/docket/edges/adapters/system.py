"""System adapter: typed wrappers over systemctl, docker, and git.

This is the canonical home for every shell-out to a host service manager or
container runtime. It mirrors lib/helpers/service.sh (service_manager,
service_hint, service_ctl, restart_gateway) and the scattered `command -v
docker` / `systemctl` calls in lib/.

Design notes:
  * docket began life Linux/systemd-only. service_manager() picks the init
    system so we can degrade cleanly on macOS (launchd) or where there is no
    user service manager, instead of calling systemctl blindly.
  * Every subprocess call catches FileNotFoundError / TimeoutExpired / OSError
    and degrades gracefully (returns False / "" / a not-active result) so a
    missing binary never crashes a command.
  * Functions are module-level, typed and small so callers can monkeypatch
    `subprocess.run` (or the helpers here) in tests.

KEEP IN SYNC: core/utils.py historically owned gateway_active()/restart_gateway()
using subprocess directly. Those remain importable; this module is the new
canonical implementation and they may delegate here, but nothing here imports
from utils to avoid a cycle.
"""

from __future__ import annotations

import os
import subprocess
import time

from docket import ui

# ── constants ──────────────────────────────────────────────────────────────────

GATEWAY_UNIT = "openclaw-gateway.service"

# Timeouts (seconds) kept short so a hung daemon never blocks a CLI command.
_QUERY_TIMEOUT = 5
_RESTART_TIMEOUT = 15


# ── service manager detection ──────────────────────────────────────────────────


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
    Mirrors service_manager() in service.sh.
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
    """Return the command string a user would run for `action` on this platform.

    For use in hint messages only. Mirrors service_hint() in service.sh.
    Usage: service_hint("start" | "restart" | "status").
    """
    mgr = service_manager()
    if mgr == "systemd":
        return f"systemctl --user {action} {GATEWAY_UNIT}"
    if mgr == "launchd":
        return f"openclaw gateway {action}  (or your launchd service)"
    return f"openclaw gateway {action}"


# ── systemctl wrappers ─────────────────────────────────────────────────────────


def systemctl_is_active(unit: str = GATEWAY_UNIT) -> bool:
    """Return True if a systemd --user unit is active.

    Off systemd (or if systemctl is missing) this reports not-active, matching
    the Bash service_ctl is-active fallback (return 1).
    """
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
    """Restart a systemd --user unit. Returns True on success.

    Off systemd this is a no-op that returns False (caller should use a hint).
    """
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


# ── gateway lifecycle ──────────────────────────────────────────────────────────


def gateway_active() -> bool:
    """Return True if the OpenClaw gateway service is active.

    Canonical implementation of the gateway is-active check used across
    list/doctor/serve/snapshot. Mirrors `service_ctl is-active`.
    """
    return systemctl_is_active(GATEWAY_UNIT)


def restart_gateway() -> bool:
    """Restart the OpenClaw gateway if it is running.

    Honors DOCKET_NO_RESTART=1 for test hermeticity (prints a dry-run notice and
    returns True). Returns True on success or when the service is already down;
    False if the restart was attempted and failed.
    Mirrors restart_gateway() in service.sh.
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


# ── docker wrappers ────────────────────────────────────────────────────────────


def docker_available() -> bool:
    """Return True if a usable docker binary is on PATH.

    Mirrors `command -v docker` in gates.sh. Presence of the binary only — it
    does not verify the daemon is reachable (use docker_ps for that).
    """
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


# ── verification gate ─────────────────────────────────────────────────────────

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


# ── git wrappers ───────────────────────────────────────────────────────────────


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
