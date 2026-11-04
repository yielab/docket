"""Run one extractor command in the sandbox's jail and collect what it wrote.

The runner starts the command in a process group of its own under a landlock, seatbelt or docker
backend, bounds its output and its time, and kills the whole group afterwards. It never runs a
command unjailed: a backend that is not a jail raises `Unavailable` before anything is started.
"""

from __future__ import annotations

import contextlib
import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from docket.kernel import clock as _clock
from docket.kernel import ids as _ids
from docket.kernel.errors import Unavailable
from docket.kernel.ports import jail as _jail


@dataclass(frozen=True)
class JailedRun:
    """One extractor run: *command* in *root*, the jail's only root, under *backend* with the
    network off. *env* is the whole environment it gets; *seconds* and *max_output* bound it."""

    backend: str
    root: Path
    command: tuple[str, ...]
    env: dict[str, str]
    read_only: tuple[Path, ...]
    seconds: float
    max_output: int
    network: bool = False
    # The docker backend's bounds (0 is none); the other backends are bounded by the extractor itself.
    memory_bytes: int = 0
    max_pids: int = 0


@dataclass(frozen=True)
class Ran:
    """What a run left: its exit status (None when killed at the deadline), what it wrote."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    cut: bool = False


_STDERR_BYTES = 4096


def _jailed_argv(run: JailedRun) -> tuple[list[str], str]:
    """The jail's argv for *run* and the docker container's name ("" otherwise). Fails closed:
    a backend that is not a jail yields no argv, so nothing is started."""
    roots, command = (run.root,), list(run.command)
    if run.backend == "landlock":
        return _jail.landlock_command_argv(roots, command, run.network, run.read_only), ""
    if run.backend == "seatbelt":
        return _jail.seatbelt_command_argv(roots, command, run.network, run.read_only), ""
    if run.backend == "docker":
        name = _ids.new_short_id("docket-pdf")
        argv = _jail.docker_command_argv(
            name,
            roots,
            command,
            run.env,
            run.network,
            run.read_only,
            run.memory_bytes,
            run.max_pids,
        )
        return argv, name
    raise Unavailable(f"no sandbox backend to run under: {run.backend!r}")


def _leader_exited(proc: subprocess.Popen[bytes], deadline: float) -> bool:
    """Wait for the group leader to exit without reaping it, so its process group id cannot be
    recycled before the group is killed. False when the deadline passes first."""
    while True:
        try:
            if os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return True
        except (AttributeError, ChildProcessError):
            return proc.poll() is not None
        if _clock.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def run_jailed(run: JailedRun) -> Ran:
    """Run *run* in its jail, in a process group of its own that is killed at the deadline, when
    its output passes *max_output* and after the leader exits. Raises, never runs unjailed."""
    argv, container = _jailed_argv(run)
    deadline = _clock.monotonic() + run.seconds
    proc = subprocess.Popen(
        argv,
        cwd=run.root,
        env=run.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert proc.stdout is not None and proc.stderr is not None
    out, err = bytearray(), bytearray()
    timed_out = cut = False
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout, selectors.EVENT_READ, out)
            sel.register(proc.stderr, selectors.EVENT_READ, err)
            while sel.get_map() and not cut:
                left = deadline - _clock.monotonic()
                if left <= 0:
                    timed_out = True
                    break
                for key, _ in sel.select(min(left, 0.25)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    buf: bytearray = key.data
                    room = (run.max_output if buf is out else _STDERR_BYTES) - len(buf)
                    buf += chunk[: max(room, 0)]
                    cut = cut or (buf is out and len(chunk) > room)
        if not (timed_out or cut) and not _leader_exited(proc, deadline):
            timed_out = True
    finally:
        # The leader is not reaped yet, so its group id is still its own: kill the whole group.
        if container:
            _jail.docker_kill(container)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
    return Ran(None if timed_out else proc.returncode, bytes(out), bytes(err), timed_out, cut)
