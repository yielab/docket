"""Whole-path cooperative run cancellation and durable reconciliation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod
from docket.core import agent_loop as _agent_loop
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.core.runs"


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    return home


class _BarrierBackend:
    """Return a poisoned tool call only after another process requests cancellation."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        del messages, tools, max_tokens, temperature, timeout
        self.entered.set()
        assert self.release.wait(timeout=5)
        call = ToolCall(id="must-not-run", name="read", arguments='{"path":"README.md"}')
        return ChatResponse(
            ok=True,
            message=assistant("late success", tool_calls=[call]),
            finish_reason="tool_calls",
            usage=TokenUsage(5, 5),
        )


def _events(home: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for trace_file in (home / "traces" / "demo").glob("*.jsonl"):
        events.extend(_trace.read_trace(trace_file))
    return events


def test_separate_cli_request_stays_nonterminal_until_dispatch_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _seed_pod(tmp_path, monkeypatch)
    backend = _BarrierBackend()
    driver = DocketDriver(backend_factory=lambda _model: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    dispatched_tools = 0

    def _unexpected_dispatch(*args: object, **kwargs: object) -> object:
        nonlocal dispatched_tools
        del args, kwargs
        dispatched_tools += 1
        raise AssertionError("a cancellation race loser dispatched a tool")

    monkeypatch.setattr(_agent_loop, "dispatch_tool", _unexpected_dispatch)
    task = _dispatch.enqueue_task("demo", "cancel this live turn")
    run = _runs.create_run("cli", "demo")
    returned: list[object] = []

    thread = threading.Thread(
        target=lambda: returned.append(
            _runs.execute(run["id"], lambda: _dispatch.dispatch_pod("demo", max_tasks=1))
        )
    )
    thread.start()
    assert backend.entered.wait(timeout=5)

    env = os.environ.copy()
    env["DOCKET_HOME"] = str(home)
    cancelled = subprocess.run(
        [sys.executable, "-m", "docket", "runs", "cancel", run["id"]],
        cwd=Path(__file__).parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert cancelled.returncode == 0, cancelled.stderr
    assert "requested cancellation" in cancelled.stdout
    requested = _runs.get_run(run["id"])
    assert requested is not None
    assert requested["state"] == "running"
    assert requested["cancellation"]["requestedAt"] is not None
    assert requested["cancellation"]["stoppedAt"] is None

    backend.release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert dispatched_tools == 0

    results = returned[0]
    assert isinstance(results, list)
    assert results[0].task_id == task["id"]
    assert results[0].status == "cancelled"
    persisted_task = _dispatch.read_tasks("demo")[0]
    assert persisted_task["status"] == "cancelled"
    assert persisted_task["completedAt"]

    stopped = _runs.get_run(run["id"])
    assert stopped is not None
    assert stopped["state"] == "cancelled"
    assert stopped["taskIds"] == [task["id"]]
    assert stopped["cancellation"]["observedAt"] is not None
    assert stopped["cancellation"]["stoppedAt"] is not None
    assert len([entry for entry in _audit.read_audit() if entry["action"] == "runs.cancel"]) == 1

    event_types = [event["event_type"] for event in _events(home)]
    assert event_types.count("run_cancellation_observed") == 1
    assert event_types.count("run_cancelled") == 1


def test_returned_cancelled_task_terminalizes_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / ".docket"
    home.mkdir()
    repoint_docket_home(monkeypatch, home)
    run = _runs.create_run("cli", "demo")
    result = _dispatch.TaskResult("task-cancelled", "cancelled", "run cancellation requested")

    assert _runs.execute(run["id"], lambda: [result]) == [result]

    persisted = _runs.get_run(run["id"])
    assert persisted is not None
    assert persisted["state"] == "cancelled"
    assert persisted["taskIds"] == ["task-cancelled"]


class _OneShotBashBackend:
    """Requests one real, long-running `bash` call, then a response it must
    never be asked for -- proves the run stops on the first hop, not on a
    retried one."""

    def __init__(self, command: str) -> None:
        self._command = command
        self.calls = 0

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        del messages, tools, max_tokens, temperature, timeout
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("must not be asked for a second turn after cancellation")
        call = ToolCall(id="bash-1", name="bash", arguments=json.dumps({"command": self._command}))
        return ChatResponse(
            ok=True,
            message=assistant("", tool_calls=[call]),
            finish_reason="tool_calls",
            usage=TokenUsage(10, 5),
        )


def _write_agent_meta(agent_id: str, codebase: Path) -> None:
    workspace = _cfg.PROJECTS_DIR / agent_id
    workspace.mkdir(parents=True, exist_ok=True)
    meta = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": "implementer",
        "name": agent_id,
        "codebase": str(codebase),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{agent_id}:demo",
        "projectKey": "demo",
        "created": "2026-09-12T00:00:00+00:00",
    }
    (workspace / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(agent_id, meta["model"], meta["sessionKey"], "demo")


def test_docket_runs_cancel_reaches_a_real_bash_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole-path proof: `docket runs cancel`, through the production
    driver, terminalizes a run whose hop is sitting inside a real `bash
    sleep`-shaped command."""
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)

    codebase = tmp_path / "codebase"
    codebase.mkdir()
    agent_id = "demo-implementer"
    _write_agent_meta(agent_id, codebase)

    # `python3` is on the command classifier's curated allowlist, so this
    # reaches `run_bash` on a bare "allow" verdict -- the subject here is
    # cancellation reaching an in-flight process, not the gate itself.
    backend = _OneShotBashBackend('python3 -c "import time; time.sleep(30)"')
    driver = DocketDriver(backend_factory=lambda _model: backend)

    run = _runs.create_run("cli", "demo")
    results: list[object] = []

    def _fn() -> list[Any]:
        turn = driver.run_turn(agent_id, f"agent:{agent_id}:demo", "run the long command", 60)
        status = "cancelled" if turn.failure_kind == "run_cancelled" else "failed"
        return [_dispatch.TaskResult("task-1", status, turn.error)]

    thread = threading.Thread(target=lambda: results.append(_runs.execute(run["id"], _fn)))
    thread.start()
    # No barrier to synchronize on here (the tool call itself is the long
    # pole) -- a short, generous sleep lets the hop reach the running `bash`
    # call before cancellation is requested.
    time.sleep(1)

    env = os.environ.copy()
    env["DOCKET_HOME"] = str(home)
    requested_at = time.monotonic()
    cancelled = subprocess.run(
        [sys.executable, "-m", "docket", "runs", "cancel", run["id"]],
        cwd=Path(__file__).parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert cancelled.returncode == 0, cancelled.stderr
    assert "requested cancellation" in cancelled.stdout

    thread.join(timeout=10)
    assert not thread.is_alive()
    elapsed = time.monotonic() - requested_at
    assert elapsed < 3, f"the run took {elapsed:.2f}s to terminalize, not within 3s"

    stopped = _runs.get_run(run["id"])
    assert stopped is not None
    assert stopped["state"] == "cancelled"
    assert stopped["cancellation"]["observedAt"] is not None
    assert stopped["cancellation"]["stoppedAt"] is not None
