"""L-3: docket as an MCP server — the tool layer (`cli/_mcp.py`).

These tests exercise the ``tool_*`` functions directly — plain Python
functions with no dependency on the ``mcp`` SDK — so the suite never needs
the optional dependency installed to cover the actual control-plane logic:
every tool's happy path, that every call writes an audit entry, and that the
mutating tools (``dispatch``, ``delegate``, ``approvals_grant``/``deny``) call
straight through to the exact same ``core/`` functions the CLI and
``docket serve`` webhook already use — no parallel/duplicated logic, no
MCP-side bypass of an approval or budget gate.

SDK-presence-dependent coverage (the optional-dependency degrade path, and a
real end-to-end call through the actual ``mcp`` SDK when installed) lives in
``test_l3_mcp_optional_dep.py``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _mcp
from docket.cli import _pod as _pod_cli
from docket.core import approval as _approval
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import runs as _runs

# ── hermetic environment (mirrors test_dispatch.py / test_pod_provisioning.py) ──


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", home / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "RUNS_FILE", home / "docket-runs.json", raising=True)


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    _pod_cli.build_pod(project, _pod_cli.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _audit_actions(action: str) -> list[dict[str, Any]]:
    return [e for e in _audit.read_audit() if e["action"] == action]


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
    def test_returns_the_serve_status_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _mcp.tool_status()
        assert result["apiVersion"] == "2"
        assert "gateway" in result
        assert isinstance(result["agents"], list)
        assert "totalCostUsd" in result

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _mcp.tool_status()
        assert len(_audit_actions("mcp.status")) == 1


class TestToolPods:
    def test_lists_the_seeded_pod_and_members(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        result = _mcp.tool_pods()
        assert result["pods"][0]["project"] == "demo"
        members = result["pods"][0]["members"]
        assert [m["id"] for m in members] == ["demo-lead", "demo-implementer"]
        assert [m["role"] for m in members] == ["lead", "implementer"]
        assert all(m["model"] for m in members)

    def test_no_pods_returns_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        _point_at(home, monkeypatch)
        assert _mcp.tool_pods() == {"pods": []}

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _mcp.tool_pods()
        assert len(_audit_actions("mcp.pods")) == 1


class TestToolCost:
    def test_all_agents_shape(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _mcp.tool_cost()
        assert "agents" in result and "totalUsd" in result
        ids = {a["id"] for a in result["agents"]}
        assert {"demo-lead", "demo-implementer"} <= ids

    def test_single_agent_lookup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = _mcp.tool_cost("demo-lead")
        assert result["id"] == "demo-lead"

    def test_unknown_agent_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(_mcp.McpToolError, match="not found"):
            _mcp.tool_cost("no-such-agent")

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _mcp.tool_cost()
        assert len(_audit_actions("mcp.cost")) == 1


# ── queue / delegate (pod task queue) ────────────────────────────────────────


class TestToolDelegate:
    def test_queues_a_task(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        task = _mcp.tool_delegate("demo", "fix the login bug")
        assert task["description"] == "fix the login bug"
        assert task["priority"] == "normal"
        assert task["status"] == "pending"

    def test_priority_is_honored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        task = _mcp.tool_delegate("demo", "urgent fix", priority="high")
        assert task["priority"] == "high"

    def test_empty_description_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        with pytest.raises(_mcp.McpToolError, match="required"):
            _mcp.tool_delegate("demo", "")

    def test_too_long_description_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        with pytest.raises(_mcp.McpToolError, match="too long"):
            _mcp.tool_delegate("demo", "x" * 501)

    def test_invalid_priority_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        with pytest.raises(_mcp.McpToolError, match="Invalid priority"):
            _mcp.tool_delegate("demo", "task", priority="urgent")

    def test_unknown_project_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        _point_at(home, monkeypatch)
        with pytest.raises(_mcp.McpToolError, match="no pod"):
            _mcp.tool_delegate("ghost-project", "task")

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _mcp.tool_delegate("demo", "task")
        assert len(_audit_actions("mcp.delegate")) == 1

    def test_calls_the_real_enqueue_task_no_duplicated_logic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the tool defers to `core.dispatch.enqueue_task` rather than
        re-implementing the queue write itself."""
        _seed_pod(tmp_path, monkeypatch, project="demo")
        calls: list[tuple[str, str, str]] = []
        real = _dispatch.enqueue_task

        def _spy(project: str, description: str, priority: str = "normal") -> dict[str, Any]:
            calls.append((project, description, priority))
            return real(project, description, priority)

        monkeypatch.setattr(_mcp._dispatch, "enqueue_task", _spy)
        _mcp.tool_delegate("demo", "task", priority="low")
        assert calls == [("demo", "task", "low")]


class TestToolQueue:
    def test_lists_queued_tasks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _dispatch.enqueue_task("demo", "task one")
        _dispatch.enqueue_task("demo", "task two")
        result = _mcp.tool_queue("demo")
        assert result["project"] == "demo"
        assert [t["description"] for t in result["tasks"]] == ["task one", "task two"]

    def test_retry_unblocks_a_blocked_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        task = _dispatch.enqueue_task("demo", "blocked task")
        # Hand-flip to blocked (mirrors how a budget cap would leave it).
        path = _dispatch.pod_task_list_path("demo")
        doc = json.loads(path.read_text())
        for t in doc["tasks"]:
            if t["id"] == task["id"]:
                t["status"] = "blocked"
        path.write_text(json.dumps(doc))

        result = _mcp.tool_queue("demo", retry_task_id=task["id"])
        statuses = {t["id"]: t["status"] for t in result["tasks"]}
        assert statuses[task["id"]] == "pending"

    def test_retry_unknown_task_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        with pytest.raises(_mcp.McpToolError, match="not a blocked task"):
            _mcp.tool_queue("demo", retry_task_id="task-does-not-exist")

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _mcp.tool_queue("demo")
        assert len(_audit_actions("mcp.queue")) == 1


# ── dispatch (mutating, costed — the highest-stakes tool) ───────────────────


class TestToolDispatch:
    def test_returns_a_queryable_run_id_and_the_run_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _dispatch.enqueue_task("demo", "do the thing")

        def _fake_dispatch_pod(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            return [_dispatch.TaskResult(task_id="task-x", status="done")]

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

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
        """Mirrors the webhook's contract (test_r3_dispatch_paths.py): the tool
        call itself must not block on — or fail because of — a real agent
        turn's outcome; the run registry is where a failure becomes visible."""
        _seed_pod(tmp_path, monkeypatch, project="demo")

        def _boom(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            raise RuntimeError("dispatch exploded")

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _boom)

        result = _mcp.tool_dispatch("demo")
        assert result["ok"] is True
        rec = _wait_for_terminal_run(result["run"])
        assert rec["state"] == "failed"
        assert "dispatch exploded" in rec["error"]

    def test_invalid_timeout_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        with pytest.raises(_mcp.McpToolError, match="positive integer"):
            _mcp.tool_dispatch("demo", timeout=0)

    def test_call_is_audited_immediately_even_though_dispatch_is_async(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")

        def _slow(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            time.sleep(0.05)
            return []

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _slow)
        _mcp.tool_dispatch("demo")
        # The audit entry exists right away — it does not wait for the
        # background pipeline thread to finish.
        assert len(_audit_actions("mcp.dispatch")) == 1

    def test_resume_and_timeout_are_threaded_through_to_dispatch_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves this tool is a thin wrapper over `core.dispatch.dispatch_pod`
        (same gates, same knobs) rather than a parallel dispatch path."""
        _seed_pod(tmp_path, monkeypatch, project="demo")
        seen: dict[str, object] = {}

        def _spy(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            seen.update(kw)
            return []

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _spy)
        result = _mcp.tool_dispatch("demo", resume=True, timeout=45)
        _wait_for_terminal_run(result["run"])
        assert seen["resume"] is True
        assert seen["turn_timeout"] == 45
        assert seen["verify_timeout"] == 45


# ── runs ─────────────────────────────────────────────────────────────────────


class TestToolRuns:
    def test_lists_all_runs_newest_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        first = _runs.create_run("cli", "alpha")
        second = _runs.create_run("mcp", "beta")
        result = _mcp.tool_runs()
        assert [r["id"] for r in result["runs"]] == [second["id"], first["id"]]

    def test_filters_by_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        _runs.create_run("cli", "alpha")
        _runs.create_run("cli", "beta")
        result = _mcp.tool_runs(project="alpha")
        assert len(result["runs"]) == 1
        assert result["runs"][0]["project"] == "alpha"

    def test_fetch_by_id_returns_bare_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        rec = _runs.create_run("cli", "demo")
        result = _mcp.tool_runs(run_id=rec["id"])
        assert result["id"] == rec["id"]
        assert "runs" not in result

    def test_unknown_id_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        with pytest.raises(_mcp.McpToolError, match="Unknown run"):
            _mcp.tool_runs(run_id="run-nope")

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        _mcp.tool_runs()
        assert len(_audit_actions("mcp.runs")) == 1


# ── approvals: list / grant / deny ───────────────────────────────────────────


class TestToolApprovalsList:
    def test_lists_pending_approvals(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        token = _approval.approval_create("demo", "implementer", "deploy prod")
        result = _mcp.tool_approvals_list()
        assert [p["token"] for p in result["pending"]] == [token]

    def test_call_is_audited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        _mcp.tool_approvals_list()
        assert len(_audit_actions("mcp.approvals_list")) == 1


class TestToolApprovalsGrantDeny:
    def _seed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        return _approval.approval_create("demo", "implementer", "deploy prod")

    def test_grant_transitions_to_granted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = self._seed(tmp_path, monkeypatch)
        result = _mcp.tool_approvals_grant(token)
        assert result == {"ok": True, "token": token, "state": "granted"}
        assert _approval.approval_get(token)["state"] == "granted"

    def test_deny_transitions_to_denied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = self._seed(tmp_path, monkeypatch)
        result = _mcp.tool_approvals_deny(token)
        assert result == {"ok": True, "token": token, "state": "denied"}
        assert _approval.approval_get(token)["state"] == "denied"

    def test_grant_uses_the_real_approval_grant_tagged_channel_mcp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The no-bypass guarantee: this tool calls `core.approval.approval_grant`
        (the exact function the CLI's `docket approve` and the HTTP webhook call)
        with channel="mcp" — never a parallel/duplicated grant path."""
        token = self._seed(tmp_path, monkeypatch)
        _mcp.tool_approvals_grant(token)
        entry = _audit_actions("approval.grant")[-1]
        assert entry["detail"] == f"token={token} project=demo channel=mcp"

    def test_deny_uses_the_real_approval_deny_tagged_channel_mcp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = self._seed(tmp_path, monkeypatch)
        _mcp.tool_approvals_deny(token)
        entry = _audit_actions("approval.deny")[-1]
        assert entry["detail"] == f"token={token} project=demo channel=mcp"

    def test_double_grant_raises_instead_of_silently_reporting_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = self._seed(tmp_path, monkeypatch)
        _mcp.tool_approvals_grant(token)
        with pytest.raises(_mcp.McpToolError, match="Already granted"):
            _mcp.tool_approvals_grant(token)

    def test_grant_unknown_token_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        with pytest.raises(_mcp.McpToolError, match="not found"):
            _mcp.tool_approvals_grant("apr-does-not-exist")

    def test_deny_after_grant_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        token = self._seed(tmp_path, monkeypatch)
        _mcp.tool_approvals_grant(token)
        with pytest.raises(_mcp.McpToolError):
            _mcp.tool_approvals_deny(token)

    def test_grant_call_is_audited_under_its_own_mcp_action_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every MCP call gets a uniform `mcp.<tool>` entry in addition to
        whatever domain-specific entry the underlying core call already
        writes (here, `approval.grant`) — see module docstring."""
        token = self._seed(tmp_path, monkeypatch)
        _mcp.tool_approvals_grant(token)
        assert len(_audit_actions("mcp.approvals_grant")) == 1
        assert len(_audit_actions("approval.grant")) == 1


# ── "every call is audited" — one consolidated pass over all ten tools ──────


class TestEveryToolCallIsAudited:
    def test_all_ten_tools_each_write_exactly_one_mcp_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", lambda proj, **kw: [])
        token = _approval.approval_create("demo", "implementer", "deploy")

        _mcp.tool_status()
        _mcp.tool_pods()
        _mcp.tool_queue("demo")
        _mcp.tool_delegate("demo", "a task")
        dispatch_result = _mcp.tool_dispatch("demo")
        _mcp.tool_runs()
        _mcp.tool_approvals_list()
        _mcp.tool_approvals_grant(token)
        second_token = _approval.approval_create("demo", "implementer", "deploy2")
        _mcp.tool_approvals_deny(second_token)
        _mcp.tool_cost()
        _wait_for_terminal_run(dispatch_result["run"])

        entries = [e for e in _audit.read_audit() if e["action"].startswith("mcp.")]
        actions = [e["action"] for e in entries]
        for tool in _mcp._TOOL_NAMES:
            assert actions.count(f"mcp.{tool}") == 1, f"expected exactly one mcp.{tool} entry"
