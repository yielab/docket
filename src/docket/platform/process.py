from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time

from docket.kernel import clock as _clock

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


def desktop_notifications_available() -> bool:
    """True when the `desktop` channel dialect could deliver here: `osascript` on macOS, or a
    graphical session (`DISPLAY`/`WAYLAND_DISPLAY`) plus `notify-send` elsewhere."""
    if sys.platform == "darwin":
        return _which("osascript")
    has_session = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return has_session and _which("notify-send")


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


# Detection probes must be fast (they run on every "auto" call) and must
# never hang a tool call over a jail that turns out to be unusable.
_SANDBOX_PROBE_TIMEOUT = 5


_TRUSTED_TREES: dict[str, tuple[str, str]] = {}


def make_non_dumpable() -> None:
    """Set PR_SET_DUMPABLE to 0 so a same-uid process cannot read this one's /proc environ or
    mem. Linux only; a no-op elsewhere and on any failure. Reset by execve, so children are unaffected."""
    if not sys.platform.startswith("linux"):
        return
    try:
        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)
    except (OSError, AttributeError):
        return


def process_alive(pid: int) -> bool:
    """Whether a process with *pid* exists (signal 0 = probe only). A pid we may not signal
    still exists; a non-positive pid never does."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    deadline = _clock.monotonic() + grace_s
    while _clock.monotonic() < deadline and _process_group_alive(pgid):
        time.sleep(0.05)
    if _process_group_alive(pgid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, _signal.SIGKILL)
    return True
