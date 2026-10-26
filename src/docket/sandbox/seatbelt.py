from __future__ import annotations

import os
import sys
from pathlib import Path

from docket.sandbox.landlock import _mount_dirs, _mount_reopened

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def seatbelt_available() -> bool:
    """True on macOS when ``/usr/bin/sandbox-exec`` exists. ``DOCKET_SANDBOX_PROBE=none`` reports
    false. Apple deprecates ``sandbox-exec`` but still ships it; Claude Code and Codex rely on it."""
    if os.environ.get("DOCKET_SANDBOX_PROBE") == "none":
        return False
    return sys.platform == "darwin" and os.path.exists(_SANDBOX_EXEC)


_SEATBELT_READ = (
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/opt",
    "/private/etc",
    "/System/Library",
    "/Library",
)
_SEATBELT_READ_DEVICES = ("/dev/random", "/dev/urandom")
_SEATBELT_WRITE_DEVICES = ("/dev/null", "/dev/zero", "/dev/tty", "/dev/dtracehelper")


def _sbpl(path: str) -> str:
    """Quote *path* as a Seatbelt profile string literal."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def seatbelt_profile(
    roots: tuple[Path, ...], network: bool = True, read_only: tuple[Path, ...] = ()
) -> str:
    """The fixed Seatbelt profile: deny by default, system paths, ``sys.prefix`` and *read_only*
    readable, the roots (with their repository dirs) read-write, guarded git paths not writable."""
    rw, ro = _mount_dirs(roots)
    prefixes = (os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix))
    granted = (os.path.realpath(p) for p in read_only)
    read = list(dict.fromkeys((*_SEATBELT_READ, *prefixes, *granted)))
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec* process-fork sysctl-read mach-lookup file-read-metadata)",
        "(allow signal (target self))",
        # macOS 26 aborts every process (SIGABRT, no output) that cannot list "/"; the names only.
        '(allow file-read-data (literal "/"))',
        "(allow file-read* " + " ".join(f"(subpath {_sbpl(p)})" for p in read) + ")",
        "(allow file-read* "
        + " ".join(f"(literal {_sbpl(p)})" for p in _SEATBELT_READ_DEVICES)
        + ")",
        "(allow file-read* file-write* "
        + " ".join(f"(literal {_sbpl(p)})" for p in _SEATBELT_WRITE_DEVICES)
        + ")",
    ]
    lines += [f"(allow file-read* file-write* (subpath {_sbpl(p)}))" for p in rw]
    lines += [f"(deny file-write* (subpath {_sbpl(p)}))" for p in ro]
    lines += [
        f"(allow file-read* file-write* (subpath {_sbpl(p)}))" for p in _mount_reopened(roots)
    ]
    lines.append("(allow network*)" if network else "(deny network*)")
    return "\n".join(lines) + "\n"


def seatbelt_argv(
    roots: tuple[Path, ...],
    command: str,
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The argv running *command* under ``sandbox-exec -p <profile>``; the first root is the cwd."""
    profile = seatbelt_profile(roots, network, read_only)
    return [_SANDBOX_EXEC, "-p", profile, "/bin/sh", "-c", command]


def seatbelt_command_argv(
    roots: tuple[Path, ...],
    argv: list[str],
    network: bool = True,
    read_only: tuple[Path, ...] = (),
) -> list[str]:
    """The same jail as :func:`seatbelt_argv`, running *argv* directly (no shell)."""
    return [_SANDBOX_EXEC, "-p", seatbelt_profile(roots, network, read_only), *argv]
