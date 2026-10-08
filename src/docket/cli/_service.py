"""The start and stop commands: the background service and its two-stage stop."""

from __future__ import annotations

import contextlib
import os
import signal
import time
from pathlib import Path

import typer

import docket.config as _cfg
from docket import ui
from docket.cli import _contract

_GRACE_S = 15
_ABANDON_S = 5


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running_pid() -> int | None:
    """The pid recorded for a live `docket start`, or None."""
    pid = _read_pid(_cfg.SERVE_PID_FILE)
    return pid if pid is not None and _alive(pid) else None


def is_running() -> bool:
    """True when the service recorded in ``serve.pid`` is still a live process."""
    return running_pid() is not None


def _wait_gone(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def cmd_start(
    port: int = typer.Option(7331, "--port", "-p", help="Port to bind (default 7331)"),
    interval: int = typer.Option(
        30, "--interval", "-i", help="Sweep refresh interval in seconds (default 30)"
    ),
    dispatch: bool = typer.Option(
        False,
        "--dispatch",
        help="Also run each pod's queued tasks through its pipeline (real, costed agent turns)",
    ),
    telegram: bool = typer.Option(
        False, "--telegram", help="Also long-poll docket's own Telegram bot (needs a stored token)"
    ),
    mcp: bool = typer.Option(
        False, "--mcp", help="Serve the control plane as an MCP server on stdio instead"
    ),
    token_file: str | None = typer.Option(
        None,
        "--token-file",
        help="Write the bearer token to this file (0600) instead of printing it",
    ),
) -> None:
    """Start the background service: the local HTTP API, sweeps, and what you turn on.

    Binds 127.0.0.1 only. Always runs the sweeps and /status.json /metrics /health.
    --dispatch also runs every pod's queue (spends budget), --telegram polls the
    Telegram bot, --mcp serves docket's tools over stdio and runs nothing else.
    Stop it with `docket stop`.

    Example: docket start --dispatch
    """
    if mcp:
        if dispatch or telegram or token_file is not None:
            ui.error(
                "--mcp serves stdio on its own", "Drop --dispatch, --telegram and --token-file"
            )
            raise typer.Exit(2)
        from docket.cli._mcp import serve_stdio

        raise typer.Exit(serve_stdio())

    existing = running_pid()
    if existing is not None:
        ui.error(f"docket is already running (pid {existing})", "Run `docket stop` first")
        raise typer.Exit(1)

    from docket.serve import run_serve

    pid_file = _cfg.SERVE_PID_FILE
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        run_serve(
            port=port,
            interval=interval,
            dispatch=dispatch,
            telegram=telegram,
            token_file=token_file,
        )
    finally:
        if _read_pid(pid_file) == os.getpid():
            with contextlib.suppress(OSError):
                pid_file.unlink()


def cmd_stop(
    wait: int = typer.Option(
        _GRACE_S, "--wait", help="Seconds to let running sweeps finish before abandoning them"
    ),
) -> None:
    """Stop the background service: let sweeps finish, then abandon them if they hang.

    Sends the service one signal and waits up to --wait seconds for it to exit; a
    second signal abandons any sweep still running.

    Example: docket stop
    """
    pid = running_pid()
    if pid is None:
        with contextlib.suppress(OSError):
            _cfg.SERVE_PID_FILE.unlink()
        ui.info("docket is not running.")
        return

    os.kill(pid, signal.SIGTERM)
    if not _wait_gone(pid, wait):
        ui.warn(f"Still running after {wait}s; abandoning the running sweeps.")
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        if not _wait_gone(pid, _ABANDON_S):
            ui.error(f"docket (pid {pid}) did not exit", f"Run `kill -9 {pid}`")
            raise typer.Exit(1)
    with contextlib.suppress(OSError):
        _cfg.SERVE_PID_FILE.unlink()
    ui.success("docket stopped.")
    _contract.next_step("docket start")
