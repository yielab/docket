"""M3 tests: list, info, cost — fully-ported read-only commands.

All tests run the Python module via subprocess so they exercise the full stack
(config loading, ACL, store) through the same entry point the Bash dispatcher
uses.  The OPENCLAW_DIR env var is overridden per-test to a temp directory so
tests are hermetic and never touch the real ~/.openclaw.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
}

OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [
            {
                "id": "myshop",
                "model": "anthropic/claude-sonnet-4-6",
                "metadata": {"sessionKey": "agent:myshop:default", "projectKey": "default"},
            }
        ],
    },
    "bindings": [],
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    """Build subprocess env with OPENCLAW_DIR overridden."""
    return {**os.environ, "OPENCLAW_DIR": str(oc_dir)}


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    """Create a minimal agent workspace + openclaw.json in tmp_path."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()

    agent_ws = oc_dir / "workspaces" / "projects" / agent_id
    (agent_ws / "memory").mkdir(parents=True)

    (agent_ws / ".docket-meta.json").write_text(json.dumps(META))
    (agent_ws / "SOUL.md").write_text("# SOUL\n")
    (agent_ws / "MEMORY.md").write_text("# MEMORY\n")

    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))

    return oc_dir


def _run(args: list[str], oc_dir: Path) -> tuple[int, str, str]:
    """Run `python -m docket <args>` with OPENCLAW_DIR overridden."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=_make_env(oc_dir),
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# docket list
# ---------------------------------------------------------------------------


class TestCmdList:
    def test_list_json_structure(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["list", "--json"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        data = json.loads(out)
        assert "agents" in data
        assert len(data["agents"]) == 1
        a = data["agents"][0]
        assert a["id"] == "myshop"
        assert a["name"] == "My Shop"
        assert a["type"] == "repo"
        assert a["registered"] is True
        assert a["telegram"] is None
        assert a["stack"] == "Node.js"
        assert a["modelSource"] == "policy"

    def test_list_json_budget_empty_string_when_absent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["list", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["agents"][0]["budgetUsd"] == ""

    def test_list_json_unregistered_agent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # Write openclaw.json with empty agents list
        (oc_dir / "openclaw.json").write_text(
            json.dumps(
                {"agents": {"defaults": {"model": ""}, "list": []}, "bindings": []}
            )
        )
        rc, out, _ = _run(["list", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["agents"][0]["registered"] is False

    def test_list_json_telegram_binding(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        oc = {
            **OC_CONFIG,
            "bindings": [
                {
                    "agentId": "myshop",
                    "match": {"channel": "telegram", "peer": {"kind": "group", "id": "-123456"}},
                }
            ],
        }
        (oc_dir / "openclaw.json").write_text(json.dumps(oc))
        rc, out, _ = _run(["list", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["agents"][0]["telegram"] == "-123456"

    def test_list_human_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["list"], oc_dir)
        assert rc == 0
        assert "myshop" in out
        assert "My Shop" in out

    def test_list_human_shows_specialist_section(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["list"], oc_dir)
        assert rc == 0
        assert "SPECIALIST AGENTS" in out

    def test_list_empty_no_agents(self, tmp_path: Path) -> None:
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        (oc_dir / "openclaw.json").write_text(
            json.dumps({"agents": {"list": []}, "bindings": []})
        )
        rc, _out, err = _run(["list"], oc_dir)
        assert rc == 0
        assert "No project agents" in err

    def test_list_json_multiple_agents(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, "myshop")
        # Add second agent
        ws2 = oc_dir / "workspaces" / "projects" / "blog"
        ws2.mkdir(parents=True)
        meta2 = {**META, "name": "Blog", "type": "task"}
        (ws2 / ".docket-meta.json").write_text(json.dumps(meta2))
        rc, out, _ = _run(["list", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "blog" in ids
        assert "myshop" in ids
        assert ids == sorted(ids)  # sorted output


# ---------------------------------------------------------------------------
# docket info
# ---------------------------------------------------------------------------


class TestCmdInfo:
    def test_info_json_structure(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["info", "myshop", "--json"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        data = json.loads(out)
        assert data["id"] == "myshop"
        assert data["name"] == "My Shop"
        assert data["type"] == "repo"
        assert data["registered"] is True
        assert data["telegram"] is None
        assert data["paused"] is False
        assert data["sessionKey"] == "agent:myshop:default"
        assert data["projectKey"] == "default"
        assert data["stack"] == "Node.js"

    def test_info_json_budget_empty_when_absent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["info", "myshop", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["budgetUsd"] == ""

    def test_info_json_last_active_dash_when_no_logs(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["info", "myshop", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["lastActive"] == "—"

    def test_info_json_last_active_from_memory_log(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        mem = oc_dir / "workspaces" / "projects" / "myshop" / "memory"
        (mem / "2024-03-15.md").write_text("log")
        rc, out, _ = _run(["info", "myshop", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["lastActive"] == "2024-03-15"

    def test_info_json_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["info", "does-not-exist", "--json"], oc_dir)
        assert rc == 1
        assert "not found" in err

    def test_info_human_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["info", "myshop"], oc_dir)
        assert rc == 0
        assert "myshop" in out
        assert "My Shop" in out
        assert "Node.js" in out

    def test_info_human_shows_workspace_files(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["info", "myshop"], oc_dir)
        assert rc == 0
        assert "SOUL.md" in out
        assert "MEMORY.md" in out

    def test_info_json_paused_agent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        paused_meta = {**META, "paused": "true", "pausedReason": "budget exceeded"}
        (ws / ".docket-meta.json").write_text(json.dumps(paused_meta))
        rc, out, _ = _run(["info", "myshop", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["paused"] is True

    def test_info_json_no_id_errors(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["info", "--json"], oc_dir)
        assert rc == 1
        assert "required" in err.lower()


# ---------------------------------------------------------------------------
# docket cost
# ---------------------------------------------------------------------------


class TestCmdCost:
    def test_cost_json_no_sessions(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["cost", "--json"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        data = json.loads(out)
        assert "agents" in data
        assert "totalUsd" in data
        assert data["totalUsd"] == 0.0
        a = data["agents"][0]
        assert a["id"] == "myshop"
        assert a["input"] == 0
        assert a["output"] == 0
        assert a["turns"] == 0
        assert a["costUsd"] == 0.0
        assert a["pricingKnown"] is True

    def test_cost_json_with_session_data(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        sessions = oc_dir / "agents" / "myshop" / "sessions"
        sessions.mkdir(parents=True)
        session_line = json.dumps(
            {
                "timestamp": "2024-03-15T10:00:00Z",
                "message": {
                    "usage": {
                        "input": 1000,
                        "output": 200,
                        "cacheRead": 500,
                        "cacheWrite": 100,
                        "cost": {"total": 0.005},
                    }
                },
            }
        )
        (sessions / "session-1.jsonl").write_text(session_line + "\n")
        rc, out, _ = _run(["cost", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        a = data["agents"][0]
        assert a["input"] == 1000
        assert a["output"] == 200
        assert a["turns"] == 1
        assert abs(a["costUsd"] - 0.005) < 1e-9
        assert abs(data["totalUsd"] - 0.005) < 1e-9

    def test_cost_json_budget_null_when_absent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["cost", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["agents"][0]["budgetUsd"] is None

    def test_cost_human_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["cost"], oc_dir)
        assert rc == 0
        assert "myshop" in out

    def test_cost_single_agent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["cost", "myshop"], oc_dir)
        assert rc == 0
        assert "myshop" in out
        assert "Turns" in out

    def test_cost_single_agent_unknown_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["cost", "no-such-agent"], oc_dir)
        assert rc == 1
        assert "not found" in err

    def test_cost_history_json_no_data(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["cost", "--history", "--json"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        data = json.loads(out)
        assert data["scope"] == "all agents"
        assert data["history"] == []

    def test_cost_history_json_with_data(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        sessions = oc_dir / "agents" / "myshop" / "sessions"
        sessions.mkdir(parents=True)
        line = json.dumps(
            {
                "timestamp": "2024-03-15T10:00:00Z",
                "message": {
                    "usage": {
                        "input": 500,
                        "output": 100,
                        "cost": {"total": 0.002},
                    }
                },
            }
        )
        (sessions / "s.jsonl").write_text(line + "\n")
        rc, out, _ = _run(["cost", "--history", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert len(data["history"]) == 1
        row = data["history"][0]
        assert row["date"] == "2024-03-15"
        assert row["turns"] == 1

    def test_cost_history_days_filter(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        sessions = oc_dir / "agents" / "myshop" / "sessions"
        sessions.mkdir(parents=True)
        for day in ("2024-01-01", "2024-01-02", "2024-01-10"):
            line = json.dumps(
                {
                    "timestamp": f"{day}T10:00:00Z",
                    "message": {"usage": {"input": 1, "output": 1, "cost": {"total": 0.0}}},
                }
            )
            (sessions / f"{day}.jsonl").write_text(line + "\n")
        rc, out, _ = _run(["cost", "--history", "--days", "2", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        # Only the last 2 days: 2024-01-02 and 2024-01-10
        assert len(data["history"]) == 2
        assert data["history"][-1]["date"] == "2024-01-10"


# ---------------------------------------------------------------------------
# docket list (default invocation — no subcommand)
# ---------------------------------------------------------------------------


class TestDefaultInvocation:
    def test_no_args_calls_list(self, tmp_path: Path) -> None:
        """Running `python -m docket` with no args invokes list."""
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run([], oc_dir)
        assert rc == 0
        assert "myshop" in out
