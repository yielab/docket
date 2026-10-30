"""Whole-path cooperative run cancellation and durable reconciliation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import record_isolation_off
from tests.support.pods import build_pod
from tests.support.tasks import update_task

from docket.agent import loop_steps as _loop_steps
from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.governance import audit as _audit
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.kernel.threads import new_thread
from docket.observability import trace as _trace
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import task as _task

SUBJECT = "docket.tasks.application.runs"


@contextmanager
def _seed_pod(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        yield home


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
        top_p: float | None = None,
        tool_choice: str | None = None,
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
    for trace_file in (home / "state" / "traces" / "demo").glob("*.jsonl"):
        events.extend(_trace.read_trace(trace_file))
    return events


def test_separate_cli_request_stays_nonterminal_until_dispatch_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _seed_pod(tmp_path) as home:
        backend = _BarrierBackend()
        driver = DocketDriver(backend_factory=lambda _model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)
        dispatched_tools = 0

        def _unexpected_dispatch(*args: object, **kwargs: object) -> object:
            nonlocal dispatched_tools
            del args, kwargs
            dispatched_tools += 1
            raise AssertionError("a cancellation race loser dispatched a tool")

        monkeypatch.setattr(_loop_steps, "dispatch_tool", _unexpected_dispatch)
        task = _queue.enqueue_task_once("demo", "cancel this live turn", channel="cli")[0]
        run = _runs.create_run("cli", "demo")
        returned: list[object] = []

        thread = new_thread(
            target=lambda: returned.append(
                _runs.execute(run["id"], lambda: _sweep.dispatch_pod("demo", max_tasks=1))
            )
        )
        thread.start()
        assert backend.entered.wait(timeout=5)

        env = os.environ.copy()
        env["DOCKET_HOME"] = str(home)
        cancelled = subprocess.run(
            [sys.executable, "-m", "docket", "task", "cancel", task.id, "--pod", "demo"],
            cwd=Path(__file__).parents[3],
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
        assert results[0].task_id == task.id
        assert results[0].status == "cancelled"
        persisted_task = TaskRepository.for_pod("demo").list()[0]
        assert persisted_task.status == "cancelled"
        assert persisted_task.completed_at

        stopped = _runs.get_run(run["id"])
        assert stopped is not None
        assert stopped["state"] == "cancelled"
        assert stopped["taskIds"] == [task.id]
        assert stopped["cancellation"]["observedAt"] is not None
        assert stopped["cancellation"]["stoppedAt"] is not None
        assert (
            len([entry for entry in _audit.read_audit() if entry["action"] == "runs.cancel"]) == 1
        )

        event_types = [event["event_type"] for event in _events(home)]
        assert event_types.count("run_cancellation_observed") == 1
        assert event_types.count("run_cancelled") == 1


def test_returned_cancelled_task_terminalizes_the_run(tmp_path: Path) -> None:
    home = tmp_path / ".docket"
    home.mkdir()
    with use_home(Home(home)):
        record_isolation_off(home)
        run = _runs.create_run("cli", "demo")
        result = _task.TaskResult("task-cancelled", "cancelled", "run cancellation requested")

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
        top_p: float | None = None,
        tool_choice: str | None = None,
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


def test_docket_task_cancel_reaches_a_real_bash_sleep(tmp_path: Path) -> None:
    """The whole-path proof: `docket task cancel`, through the production
    driver, terminalizes a run whose hop is sitting inside a real `bash
    sleep`-shaped command."""
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)

        codebase = tmp_path / "codebase"
        codebase.mkdir()
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(codebase))
        agent_id = _pod.pod.member_id("demo", "implementer")
        task = _queue.enqueue_task_once("demo", "sleep in bash", channel="cli")[0]
        update_task("demo", task.id, status="running")

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
            return [_task.TaskResult("task-1", status, turn.error)]

        thread = new_thread(target=lambda: results.append(_runs.execute(run["id"], _fn)))
        thread.start()
        # No barrier to synchronize on here (the tool call itself is the long
        # pole) -- a short, generous sleep lets the hop reach the running `bash`
        # call before cancellation is requested.
        time.sleep(1)

        env = os.environ.copy()
        env["DOCKET_HOME"] = str(home)
        requested_at = time.monotonic()
        cancelled = subprocess.run(
            [sys.executable, "-m", "docket", "task", "cancel", task.id, "--pod", "demo"],
            cwd=Path(__file__).parents[3],
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
