"""Docket as an MCP server — the tool layer (`interfaces/cli/commands/mcp.py`).

Exercises the ``tool_*`` functions directly — plain Python with no dependency on the ``mcp``
SDK — covering every tool's happy path, that every call writes an audit entry, and that the
mutating tools (``dispatch``, ``delegate``, ``resolve``) call straight through
to the same ``core/`` functions the CLI and ``docket start`` webhook use: no parallel logic, no
MCP-side bypass of an approval or budget gate.

SDK-presence-dependent coverage lives in ``test_mcp_optional_dep.py``.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.escalations import approval_escalation
from tests.support.fakes import FakeDriver
from tests.support.pods import seed_pod as _seed_pod
from tests.support.tasks import put_task, put_tasks, task
from tests.support.trace import audit_entries as _audit_actions

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import mcp as _mcp
from docket.interfaces.cli.commands import pod as _pod_cli
from docket.kernel.home import Home, use_home
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import task as _task
from docket.tasks.domain.state import Status
from docket.teams import fleet as _fleet

SUBJECT = "docket.interfaces.cli.commands.mcp"

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - lead: lead
  - ask:
      input:
        from: lead
  - implementer: implementer
"""

# ── hermetic environment (mirrors test_dispatch.py / test_pod_provisioning.py) ──


_GATED_PIPELINE_YAML = """\
name: gated
steps:
  - lead: lead
  - implementer: implementer
    approval: true
"""


def _gate_implementer(project: str) -> None:
    _bind_ask_pipeline(project, _GATED_PIPELINE_YAML)


def _bind_ask_pipeline(project: str, text: str = _ASK_PIPELINE_YAML) -> None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod_cli.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod_cli.pod.member_id(project, "lead"), "pipeline", digest)


@contextmanager
def _seed_parked_task(tmp_path: Path, project: str = "demo") -> Iterator[_task.TaskRecord]:
    """A real pod with a real ``waiting_input`` task, reached by actually dispatching
    through an ``input`` step -- mirrors ``tests/unit/core/test_answers.py``."""
    with _seed_pod(tmp_path, project=project):
        _bind_ask_pipeline(project)
        put_task(project, task(description="needs a decision"))
        _sweep.dispatch_pod(project, runner=FakeDriver())
        yield TaskRepository.for_pod(project).list()[0]


def _wait_for_terminal_run(run_id: str, timeout: float = 3.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = _runs.get_run(run_id)
        if rec is not None and rec["state"] in ("succeeded", "failed"):
            return rec
        time.sleep(0.02)
    raise AssertionError(f"run {run_id!r} never reached a terminal state")


# ── status / pods / cost (read-only) ────────────────────────────────────────


class TestToolStatus:
    def test_returns_the_serve_status_shape(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _mcp.tool_status()
            assert result["apiVersion"] == "6"
            assert isinstance(result["agents"], list)
            assert "totalCostUsd" in result

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _mcp.tool_status()
            assert len(_audit_actions("mcp.status")) == 1


class TestToolPods:
    def test_lists_the_seeded_pod_and_members(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            result = _mcp.tool_pods()
            assert result["pods"][0]["project"] == "demo"
            members = result["pods"][0]["members"]
            assert [m["id"] for m in members] == ["demo-lead", "demo-implementer"]
            assert [m["role"] for m in members] == ["lead", "implementer"]
            assert all(m["model"] for m in members)

    def test_no_pods_returns_empty_list(self, tmp_path: Path) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)):
            assert _mcp.tool_pods() == {"pods": []}

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _mcp.tool_pods()
            assert len(_audit_actions("mcp.pods")) == 1


class TestToolCost:
    def test_all_agents_shape(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _mcp.tool_cost()
            assert "agents" in result and "totalUsd" in result
            ids = {a["id"] for a in result["agents"]}
            assert {"demo-lead", "demo-implementer"} <= ids

    def test_the_snapshot_is_the_one_status_builds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.interfaces.cli.commands import status as _status

        with _seed_pod(tmp_path):
            row = {"id": "demo-lead", "costUsd": 0.0}
            monkeypatch.setattr(
                _status, "cost_snapshot", lambda: {"agents": [row], "totalUsd": 0.0}
            )

            assert _mcp.tool_cost() == {"agents": [row], "totalUsd": 0.0}
            assert _mcp.tool_cost("demo-lead") == row

    def test_single_agent_lookup(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _mcp.tool_cost("demo-lead")
            assert result["id"] == "demo-lead"

    def test_unknown_agent_raises(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path),
            pytest.raises(_mcp.McpToolError, match="not found"),
        ):
            _mcp.tool_cost("no-such-agent")

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _mcp.tool_cost()
            assert len(_audit_actions("mcp.cost")) == 1


# ── queue / delegate (pod task queue) ────────────────────────────────────────


class TestToolDelegate:
    def test_queues_a_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            task = _mcp.tool_delegate("demo", "fix the login bug")
            assert task["description"] == "fix the login bug"
            assert task["priority"] == "normal"
            assert task["status"] == "pending"

    def test_priority_is_honored(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            task = _mcp.tool_delegate("demo", "urgent fix", priority="high")
            assert task["priority"] == "high"

    def test_empty_description_rejected(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path, project="demo"),
            pytest.raises(_mcp.McpToolError, match="required"),
        ):
            _mcp.tool_delegate("demo", "")

    def test_too_long_description_rejected(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path, project="demo"),
            pytest.raises(_mcp.McpToolError, match="too long"),
        ):
            _mcp.tool_delegate("demo", "x" * 501)

    def test_invalid_priority_rejected(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path, project="demo"),
            pytest.raises(_mcp.McpToolError, match="Invalid priority"),
        ):
            _mcp.tool_delegate("demo", "task", priority="urgent")

    def test_unknown_project_rejected(self, tmp_path: Path) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)), pytest.raises(_mcp.McpToolError, match="no pod"):
            _mcp.tool_delegate("ghost-project", "task")

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            _mcp.tool_delegate("demo", "task")
            assert len(_audit_actions("mcp.delegate")) == 1

    def test_calls_the_real_enqueue_task_once_no_duplicated_logic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the tool defers to `tasks.application.queue.enqueue_task_once` rather than
        re-implementing the queue write itself."""
        with _seed_pod(tmp_path, project="demo"):
            calls: list[tuple[str, str, str]] = []
            real = _queue.enqueue_task_once

            def _spy(
                project: str, description: str, priority: str = "normal", *, channel: str
            ) -> tuple[dict[str, Any], bool]:
                calls.append((project, description, priority))
                assert channel == "mcp"
                return real(project, description, priority, channel=channel)

            monkeypatch.setattr(_mcp._queue, "enqueue_task_once", _spy)
            _mcp.tool_delegate("demo", "task", priority="low")
            assert calls == [("demo", "task", "low")]


class TestToolQueue:
    def test_lists_queued_tasks(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            put_tasks("demo", task(description="task one"), task(description="task two"))
            result = _mcp.tool_queue("demo")
            assert result["project"] == "demo"
            assert [t["description"] for t in result["tasks"]] == ["task one", "task two"]

    @pytest.mark.parametrize("status", ["blocked", "failed"])
    def test_retry_requeues_a_blocked_or_failed_task(self, tmp_path: Path, status: str) -> None:
        with _seed_pod(tmp_path, project="demo"):
            record = task(status=status)
            put_task("demo", record)

            result = _mcp.tool_queue("demo", retry_task_id=record.id)

            statuses = {t["id"]: t["status"] for t in result["tasks"]}
            assert statuses[record.id] == "pending"

    def test_retry_unknown_task_raises(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path, project="demo"),
            pytest.raises(_mcp.McpToolError, match="not a failed or blocked task"),
        ):
            _mcp.tool_queue("demo", retry_task_id="task-does-not-exist")

    def test_retry_of_a_pending_task_raises(self, tmp_path: Path) -> None:
        record = task()
        with (
            _seed_pod(tmp_path, project="demo"),
            pytest.raises(_mcp.McpToolError, match="not a failed or blocked task"),
        ):
            put_task("demo", record)
            _mcp.tool_queue("demo", retry_task_id=record.id)

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            _mcp.tool_queue("demo")
            assert len(_audit_actions("mcp.queue")) == 1


# ── dispatch (mutating, costed — the highest-stakes tool) ───────────────────


class TestToolDispatch:
    def test_returns_a_queryable_run_id_and_the_run_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path, project="demo"):
            put_task("demo", task(description="do the thing"))

            def _fake_dispatch_pod(proj: str, **kw: object) -> list[_task.TaskResult]:
                return [_task.TaskResult(task_id="task-x", status="done")]

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake_dispatch_pod)

            result = _mcp.tool_dispatch("demo")
            assert result["ok"] is True
            assert result["project"] == "demo"
            assert result["status"] == "dispatched"
            run_id = result["run"]
            assert run_id.startswith("run-")

            rec = _wait_for_terminal_run(run_id)
            assert rec["source"] == "mcp"
            assert rec["state"] == "succeeded"
            assert rec["taskIds"] == ["task-x"]

    def test_exception_is_recorded_without_raising_out_of_the_tool_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mirrors the webhook's contract (test_dispatch_run_records.py): the tool
        call itself must not block on — or fail because of — a real agent
        turn's outcome; the run registry is where a failure becomes visible."""
        with _seed_pod(tmp_path, project="demo"):

            def _boom(proj: str, **kw: object) -> list[_task.TaskResult]:
                raise RuntimeError("dispatch exploded")

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _boom)

            result = _mcp.tool_dispatch("demo")
            assert result["ok"] is True
            rec = _wait_for_terminal_run(result["run"])
            assert rec["state"] == "failed"
            assert "dispatch exploded" in rec["error"]

    def test_invalid_timeout_rejected(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path, project="demo"),
            pytest.raises(_mcp.McpToolError, match="positive integer"),
        ):
            _mcp.tool_dispatch("demo", timeout=0)

    def test_call_is_audited_immediately_even_though_dispatch_is_async(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path, project="demo"):

            def _slow(proj: str, **kw: object) -> list[_task.TaskResult]:
                time.sleep(0.05)
                return []

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _slow)
            result = _mcp.tool_dispatch("demo")
            # The audit entry exists right away — it does not wait for the
            # background pipeline thread to finish.
            assert len(_audit_actions("mcp.dispatch")) == 1
            # Keep the background thread inside this test's monkeypatch lifetime;
            # otherwise it can resolve dispatch_pod after the next test installs a
            # different spy and overwrite that test's observations.
            _wait_for_terminal_run(result["run"])

    def test_resume_and_timeout_are_threaded_through_to_dispatch_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves this tool is a thin wrapper over `hops.application.sweep.dispatch_pod`
        (same gates, same knobs) rather than a parallel dispatch path."""
        with _seed_pod(tmp_path, project="demo"):
            seen: dict[str, object] = {}

            def _spy(proj: str, **kw: object) -> list[_task.TaskResult]:
                seen.update(kw)
                return []

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _spy)
            result = _mcp.tool_dispatch("demo", resume=True, timeout=45)
            _wait_for_terminal_run(result["run"])
            assert seen["resume"] is True
            assert seen["turn_timeout"] == 45
            assert seen["verify_timeout"] == 45


# ── runs ─────────────────────────────────────────────────────────────────────


class TestToolRuns:
    def test_lists_all_runs_newest_first(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            first = _runs.create_run("cli", "alpha")
            second = _runs.create_run("mcp", "beta")
            result = _mcp.tool_runs()
            assert [r["id"] for r in result["runs"]] == [second["id"], first["id"]]

    def test_filters_by_project(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            _runs.create_run("cli", "alpha")
            _runs.create_run("cli", "beta")
            result = _mcp.tool_runs(project="alpha")
            assert len(result["runs"]) == 1
            assert result["runs"][0]["project"] == "alpha"

    def test_fetch_by_id_returns_bare_record(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            rec = _runs.create_run("cli", "demo")
            result = _mcp.tool_runs(run_id=rec["id"])
            assert result["id"] == rec["id"]
            assert "runs" not in result

    def test_unknown_id_raises(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            with pytest.raises(_mcp.McpToolError, match="Unknown run"):
                _mcp.tool_runs(run_id="run-nope")

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            _mcp.tool_runs()
            assert len(_audit_actions("mcp.runs")) == 1


# ── approvals: list / grant / deny ───────────────────────────────────────────


class TestToolInbox:
    def test_returns_the_same_shape_docket_inbox_json_prints(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            put_task("demo", task(description="ship it"))
            result = _mcp.tool_inbox()
            assert set(result.keys()) == {
                "needsYou",
                "failed",
                "doneSince",
                "running",
                "next",
                "escalations",
            }

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            _mcp.tool_inbox()
            assert len(_audit_actions("mcp.inbox")) == 1


class TestToolEscalations:
    def test_returns_the_document_get_escalations_serves(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            token = _approval.approval_create("demo", "implementer", "bash: rm -rf build")
            _escalations.open_for_approval(token, kind="approval", task_id="", caused_by="c1")

            result = _mcp.tool_escalations()

            assert result["next"] == 1
            (view,) = result["escalations"]
            assert (view["kind"], view["state"], view["seq"]) == ("approval", "pending", 1)
            assert _mcp.tool_escalations(since=1) == {"escalations": [], "next": 1}

    def test_call_is_audited(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            _mcp.tool_escalations()
            assert len(_audit_actions("mcp.escalations")) == 1


# ── "every call is audited" — one consolidated pass over every tool ───


class TestEveryToolCallIsAudited:
    def test_every_tool_call_writes_exactly_one_mcp_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path, project="demo"):
            # Parked with the real `dispatch_pod` -- before it is stubbed below -- so the
            # pre-grant has a genuine task to name.
            _bind_ask_pipeline("demo")
            put_task("demo", task(description="needs a decision"))
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            parked = next(
                t for t in TaskRepository.for_pod("demo").list() if t.status == Status.waiting_input
            )

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", lambda proj, **kw: [])

            _mcp.tool_status()
            _mcp.tool_pods()
            _mcp.tool_queue("demo")
            _mcp.tool_delegate("demo", "a task")
            dispatch_result = _mcp.tool_dispatch("demo")
            _mcp.tool_runs()
            _mcp.tool_task_pregrant("demo", parked.id, "git push origin main")
            _mcp.tool_inbox()
            _mcp.tool_escalations()
            _mcp.tool_resolve(approval_escalation("gate").id, "approve_once")
            _mcp.tool_cost()
            _wait_for_terminal_run(dispatch_result["run"])

            entries = [e for e in _audit.read_audit() if e["action"].startswith("mcp.")]
            actions = [e["action"] for e in entries]
            for tool in _mcp._TOOL_NAMES:
                assert actions.count(f"mcp.{tool}") == 1, f"expected exactly one mcp.{tool} entry"


# ── grant/deny resolve the dispatch task they gated (pod-dispatch.spec.md req. 4) ──
