"""``bash`` commands that outlive the call: start, read, stop, and stop what the turn left.

A background command runs in its own session with its output in a log file, so the call returns
at once with a handle (the pgid). Like ``toolbox`` this makes no decision: every call reaches it
through ``dispatch_tool``. The turn's driver stops every live process when the turn ends, so
nothing outlives the turn it was started in (specs/functional/agent-loop.spec.md 99-101)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.agent.tools.builtins import toolbox
from docket.kernel.home import current_home
from docket.kernel.tool_outcome import ToolOutcome

OnProcess = Callable[[str, dict[str, Any]], None]


@dataclass
class BackgroundProcess:
    """One background command of a turn: its process, its log and whether its exit was reported."""

    pgid: int
    proc: subprocess.Popen[bytes]
    log: Path
    exit_reported: bool = False


Processes = dict[int, BackgroundProcess]


def _report(on_process: OnProcess | None, kind: str, data: dict[str, Any]) -> None:
    if on_process is not None:
        on_process(kind, {**data, "tool": "bash"})


def _log_dir(cache_dir: Path | None, agent_id: str) -> Path | None:
    """The jail's cache dir when jailed, else the home's directory for the agent."""
    if cache_dir is not None:
        return cache_dir / "processes"
    return current_home().process_logs_dir(agent_id) if agent_id else None


def start(
    processes: Processes,
    roots: tuple[Path, ...],
    command: str,
    *,
    env: dict[str, str],
    sandbox: toolbox.SandboxMode,
    network: bool,
    agent_id: str,
    cache_dir: Path | None,
    read_only: tuple[Path, ...],
    on_process: OnProcess | None,
) -> ToolOutcome:
    """Start *command* in the background and register it in *processes*."""
    directory = _log_dir(cache_dir, agent_id)
    if directory is None:
        return ToolOutcome(
            False,
            error="background needs a log directory (<dir>/processes/<pgid>.log); a turn with no "
            "agent and no jail cache has none",
        )
    # The log is named by the pgid, which the process only has once it runs: a private name
    # first, then the rename.
    pending = directory / f".starting-{id(processes)}-{len(processes)}.log"
    started = toolbox.start_process(
        roots, command, sandbox, env, network, cache_dir, read_only, log=pending
    )
    if isinstance(started, ToolOutcome):
        pending.unlink(missing_ok=True)
        return started
    pgid = started.proc.pid
    log = directory / f"{pgid}.log"
    pending.rename(log)
    processes[pgid] = BackgroundProcess(pgid, started.proc, log)
    _report(on_process, "started", {"pgid": pgid, "background": True})
    marker = f" [{started.tag}]" if started.tag else ""
    return ToolOutcome(True, content=f"started pgid={pgid} log={log}{marker}")


def _lookup(processes: Processes, pgid: int) -> BackgroundProcess | ToolOutcome:
    found = processes.get(pgid)
    if found is None:
        return ToolOutcome(False, error=f"no background process {pgid} in this turn")
    return found


def _settle(
    entry: BackgroundProcess, on_process: OnProcess | None, *, kill: bool, **extra: Any
) -> None:
    """Report *entry*'s exit, once: ``exitCode`` if it ended on its own, else ``signal``. With
    *kill* the group is killed first, so a child the command left behind goes too."""
    ended = entry.proc.poll()
    if kill:
        toolbox.kill_group(entry.proc)
    if entry.exit_reported:
        return
    entry.exit_reported = True
    payload: dict[str, Any] = {"pgid": entry.pgid}
    if ended is None:
        payload["signal"] = "SIGKILL"
    else:
        payload["exitCode"] = ended
    _report(on_process, "exited", {**payload, **extra})


def output(
    processes: Processes,
    pgid: int,
    offset: int,
    limit: int,
    on_process: OnProcess | None,
) -> ToolOutcome:
    """``alive``, the exit code once ended, the next ``offset`` and the log text from *offset*
    (at most *limit* bytes)."""
    entry = _lookup(processes, pgid)
    if isinstance(entry, ToolOutcome):
        return entry
    code = entry.proc.poll()
    if code is not None:
        _settle(entry, on_process, kill=False)
    with entry.log.open("rb") as handle:
        handle.seek(max(0, offset))
        chunk = handle.read(max(1, limit))
    head = [f"alive: {'true' if code is None else 'false'}"]
    if code is not None:
        head.append(f"exit: {code}")
    head.append(f"offset: {max(0, offset) + len(chunk)}")
    return ToolOutcome(True, content="\n".join(head) + "\n" + chunk.decode("utf-8", "replace"))


def stop(processes: Processes, pgid: int, on_process: OnProcess | None) -> ToolOutcome:
    """Kill *pgid*'s group (nothing is killed once it has ended) and report its exit."""
    entry = _lookup(processes, pgid)
    if isinstance(entry, ToolOutcome):
        return entry
    _settle(entry, on_process, kill=True)
    return ToolOutcome(True, content=f"stopped pgid={pgid}")


def stop_all(processes: Processes, on_process: OnProcess | None, *, reason: str) -> None:
    """Stop every process of the turn still alive and report each exit with *reason*."""
    for entry in processes.values():
        _settle(entry, on_process, kill=True, reason=reason)
