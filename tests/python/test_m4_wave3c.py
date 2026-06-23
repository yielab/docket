"""M4 wave-3c tests: team.

All tests run `python -m docket` as a subprocess with OPENCLAW_DIR overridden
and DOCKET_NO_RESTART=1 so no systemctl calls are made.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

OC_CONFIG_EMPTY: dict[str, Any] = {
    "agents": {"defaults": {"model": ""}, "list": []},
    "bindings": [],
    "channels": {},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _run(
    args: list[str],
    env: dict[str, str],
    stdin_text: str = "",
) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def _setup_bare(tmp_path: Path) -> Path:
    """Minimal .openclaw with no agents or workspaces."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG_EMPTY))
    return oc_dir


def _setup_specialists(
    tmp_path: Path,
    roles: list[str] | None = None,
    *,
    with_soul: bool = True,
    docket_optimized: bool = False,
) -> Path:
    """
    Create specialist workspaces under ~/.openclaw/workspaces/<role>/.
    If `docket_optimized`, the SOUL.md contains a DOCKET keyword.
    """
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(exist_ok=True)
    all_roles = roles or ["manager", "programmer", "reviewer", "tester", "knowledge", "security"]
    oc_config: dict[str, Any] = {
        "agents": {
            "defaults": {"model": ""},
            "list": [{"id": r, "model": "", "metadata": {}} for r in all_roles],
        },
        "bindings": [],
        "channels": {},
        "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
    }
    (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
    ws_root = oc_dir / "workspaces"
    for role in all_roles:
        ws = ws_root / role
        ws.mkdir(parents=True, exist_ok=True)
        (ws / ".docket-meta.json").write_text(json.dumps({"kind": "specialist", "name": role}))
        if with_soul:
            soul_text = (
                "# DOCKET Architecture\n# role soul\n" if docket_optimized else "# role soul\n"
            )
            (ws / "SOUL.md").write_text(soul_text)
    return oc_dir


def _setup_manager_with_tasks(
    tmp_path: Path,
    tasks: list[dict[str, Any]] | None = None,
) -> Path:
    """Create a manager workspace with an optional TASK_LIST.json."""
    oc_dir = _setup_bare(tmp_path)
    mgr_ws = oc_dir / "workspaces" / "manager"
    mgr_ws.mkdir(parents=True)
    task_data: dict[str, Any] = {"tasks": tasks or []}
    (mgr_ws / "TASK_LIST.json").write_text(json.dumps(task_data, indent=2))
    return oc_dir


# ---------------------------------------------------------------------------
# docket team status
# ---------------------------------------------------------------------------


class TestCmdTeamStatus:
    def test_shows_specialist_grid(self, tmp_path: Path) -> None:
        oc_dir = _setup_specialists(tmp_path, docket_optimized=True)
        rc, out, _ = _run(["team", "status"], _make_env(oc_dir))
        assert rc == 0
        assert "Specialist Team Status" in out
        assert "manager" in out
        assert "programmer" in out

    def test_marks_not_installed_when_no_workspace(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, _ = _run(["team", "status"], _make_env(oc_dir))
        assert rc == 0
        assert "Not installed" in out

    def test_marks_missing_soul_md(self, tmp_path: Path) -> None:
        oc_dir = _setup_specialists(tmp_path, with_soul=False)
        rc, out, _ = _run(["team", "status"], _make_env(oc_dir))
        assert rc == 0
        assert "Missing SOUL.md" in out

    def test_standard_upgrade_hint(self, tmp_path: Path) -> None:
        oc_dir = _setup_specialists(tmp_path, docket_optimized=False)
        rc, out, _ = _run(["team", "status"], _make_env(oc_dir))
        assert rc == 0
        assert "upgrade" in out.lower()


# ---------------------------------------------------------------------------
# docket team check
# ---------------------------------------------------------------------------


class TestCmdTeamCheck:
    def test_all_healthy(self, tmp_path: Path) -> None:
        oc_dir = _setup_specialists(tmp_path)
        rc, out, _ = _run(["team", "check"], _make_env(oc_dir))
        assert rc == 0
        assert "healthy" in out.lower() or "registered" in out.lower()

    def test_exits_1_when_missing(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["team", "check"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert "missing" in combined.lower() or "NOT registered" in combined


# ---------------------------------------------------------------------------
# docket team roles
# ---------------------------------------------------------------------------


class TestCmdTeamRoles:
    def test_shows_role_info(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, _ = _run(["team", "roles"], _make_env(oc_dir))
        assert rc == 0
        assert "Programmer" in out
        assert "Reviewer" in out
        assert "Manager" in out


# ---------------------------------------------------------------------------
# docket team delegate
# ---------------------------------------------------------------------------


class TestCmdTeamDelegate:
    def test_adds_task_to_json(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path)
        rc, out, _ = _run(["team", "delegate", "Fix the login bug"], _make_env(oc_dir))
        assert rc == 0
        assert "Task queued" in out
        task_list = json.loads((oc_dir / "workspaces" / "manager" / "TASK_LIST.json").read_text())
        assert len(task_list["tasks"]) == 1
        assert task_list["tasks"][0]["description"] == "Fix the login bug"
        assert task_list["tasks"][0]["status"] == "pending"

    def test_requires_description(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path)
        rc, _, err = _run(["team", "delegate"], _make_env(oc_dir))
        assert rc == 1
        assert (
            "usage" in err.lower() or "required" in err.lower() or "task description" in err.lower()
        )

    def test_priority_flag_accepted(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path)
        rc, _out, _ = _run(
            ["team", "delegate", "--priority", "high", "Urgent task"],
            _make_env(oc_dir),
        )
        assert rc == 0
        task_list = json.loads((oc_dir / "workspaces" / "manager" / "TASK_LIST.json").read_text())
        assert task_list["tasks"][0]["priority"] == "high"

    def test_invalid_priority_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path)
        rc, _, err = _run(
            ["team", "delegate", "--priority", "critical", "Some task"],
            _make_env(oc_dir),
        )
        assert rc == 1
        assert "priority" in err.lower() or "invalid" in err.lower()

    def test_description_too_long_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path)
        long_desc = "x" * 501
        rc, _, err = _run(["team", "delegate", long_desc], _make_env(oc_dir))
        assert rc == 1
        assert "long" in err.lower() or "500" in err


# ---------------------------------------------------------------------------
# docket team queue
# ---------------------------------------------------------------------------


class TestCmdTeamQueue:
    def test_shows_active_tasks(self, tmp_path: Path) -> None:
        tasks = [
            {
                "id": "task-001",
                "description": "Write tests",
                "priority": "normal",
                "created": "2026-06-23T10:00:00",
                "startedAt": None,
                "completedAt": None,
                "status": "pending",
                "source": "operator",
            }
        ]
        oc_dir = _setup_manager_with_tasks(tmp_path, tasks)
        rc, out, _ = _run(["team", "queue"], _make_env(oc_dir))
        assert rc == 0
        assert "Write tests" in out
        assert "task-001" in out

    def test_empty_queue_message(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path, [])
        rc, out, _ = _run(["team", "queue"], _make_env(oc_dir))
        assert rc == 0
        assert "No active tasks" in out

    def test_all_flag_shows_done_tasks(self, tmp_path: Path) -> None:
        tasks = [
            {
                "id": "task-done-1",
                "description": "Completed task",
                "priority": "normal",
                "created": "2026-06-23T09:00:00",
                "startedAt": "2026-06-23T09:30:00",
                "completedAt": "2026-06-23T10:00:00",
                "status": "done",
                "source": "operator",
            }
        ]
        oc_dir = _setup_manager_with_tasks(tmp_path, tasks)
        rc, out, _ = _run(["team", "queue", "--all"], _make_env(oc_dir))
        assert rc == 0
        assert "Completed task" in out
        assert "done" in out


# ---------------------------------------------------------------------------
# docket team start / done / cancel
# ---------------------------------------------------------------------------


class TestCmdTeamTransitions:
    def _pending_task(self, tid: str = "task-abc", desc: str = "Do something") -> dict[str, Any]:
        return {
            "id": tid,
            "description": desc,
            "priority": "normal",
            "created": "2026-06-23T10:00:00",
            "startedAt": None,
            "completedAt": None,
            "status": "pending",
            "source": "operator",
        }

    def test_start_moves_to_in_progress(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path, [self._pending_task()])
        rc, out, _ = _run(["team", "start", "task-abc"], _make_env(oc_dir))
        assert rc == 0
        assert "in_progress" in out
        data = json.loads((oc_dir / "workspaces" / "manager" / "TASK_LIST.json").read_text())
        assert data["tasks"][0]["status"] == "in_progress"
        assert data["tasks"][0]["startedAt"] is not None

    def test_done_moves_to_done(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path, [self._pending_task("task-xyz")])
        rc, out, _ = _run(["team", "done", "task-xyz"], _make_env(oc_dir))
        assert rc == 0
        assert "done" in out
        data = json.loads((oc_dir / "workspaces" / "manager" / "TASK_LIST.json").read_text())
        assert data["tasks"][0]["status"] == "done"

    def test_cancel_moves_to_cancelled(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path, [self._pending_task("task-zzz")])
        rc, out, _ = _run(["team", "cancel", "task-zzz"], _make_env(oc_dir))
        assert rc == 0
        assert "cancelled" in out
        data = json.loads((oc_dir / "workspaces" / "manager" / "TASK_LIST.json").read_text())
        assert data["tasks"][0]["status"] == "cancelled"

    def test_start_requires_task_id(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path)
        rc, _, err = _run(["team", "start"], _make_env(oc_dir))
        assert rc == 1
        assert "usage" in err.lower() or "task-id" in err.lower() or "required" in err.lower()

    def test_invalid_transition_exits_1(self, tmp_path: Path) -> None:
        done_task = {
            "id": "task-fin",
            "description": "Already done",
            "priority": "normal",
            "created": "2026-06-23T10:00:00",
            "startedAt": "2026-06-23T10:01:00",
            "completedAt": "2026-06-23T10:02:00",
            "status": "done",
            "source": "operator",
        }
        oc_dir = _setup_manager_with_tasks(tmp_path, [done_task])
        rc, _, err = _run(["team", "start", "task-fin"], _make_env(oc_dir))
        assert rc == 1
        assert "cannot" in err.lower() or "invalid" in err.lower() or "status" in err.lower()

    def test_not_found_task_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path, [])
        rc, _, err = _run(["team", "done", "nonexistent"], _make_env(oc_dir))
        assert rc == 1
        assert "not found" in err.lower()

    def test_prefix_match_works(self, tmp_path: Path) -> None:
        oc_dir = _setup_manager_with_tasks(tmp_path, [self._pending_task("task-1234567890")])
        rc, out, _ = _run(["team", "done", "task-123"], _make_env(oc_dir))
        assert rc == 0
        assert "done" in out


# ---------------------------------------------------------------------------
# Confirm team is no longer in the 127-exit list
# ---------------------------------------------------------------------------


def test_wave3c_not_exit_127(tmp_path: Path) -> None:
    """team must NOT fall through to Bash (exit 127)."""
    oc_dir = _setup_bare(tmp_path)
    rc, _, _ = _run(["team", "status"], _make_env(oc_dir))
    assert rc != 127
