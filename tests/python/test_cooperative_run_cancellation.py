"""Whole-path cooperative run cancellation and durable reconciliation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import agent_loop as _agent_loop
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    for name, relative in (
        ("FLEET_FILE", "fleet.json"),
        ("WORKSPACES_DIR", "workspaces"),
        ("PROJECTS_DIR", "workspaces/projects"),
        ("PODS_DIR", "workspaces/pods"),
        ("MODEL_REGISTRY_FILE", "docket-models.json"),
        ("ARCHETYPE_REGISTRY_FILE", "docket-roles.json"),
        ("TRACES_DIR", "traces"),
        ("SESSIONS_DIR", "sessions"),
        ("APPROVALS_DIR", "approvals"),
        ("POLICIES_DIR", "policies"),
        ("RUNS_FILE", "docket-runs.json"),
        ("AUDIT_LOG", "audit.log"),
    ):
        monkeypatch.setattr(_cfg, name, home / relative, raising=True)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
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
    _point_at(home, monkeypatch)
    run = _runs.create_run("cli", "demo")
    result = _dispatch.TaskResult("task-cancelled", "cancelled", "run cancellation requested")

    assert _runs.execute(run["id"], lambda: [result]) == [result]

    persisted = _runs.get_run(run["id"])
    assert persisted is not None
    assert persisted["state"] == "cancelled"
    assert persisted["taskIds"] == ["task-cancelled"]
