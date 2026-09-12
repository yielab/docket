"""list, info, cost — fully-ported read-only commands.

All tests run `python -m docket` as a subprocess with DOCKET_HOME overridden
to a temp directory so tests are hermetic and never touch the real ~/.docket.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
}

# Agent registration + channel bindings live in fleet.json.
FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    """Build subprocess env with DOCKET_HOME overridden to a temp dir, or a
    real subprocess would fall back to the real ~/.docket."""
    return {**os.environ, "DOCKET_HOME": str(oc_dir)}


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    """Create a minimal agent workspace + fleet.json in tmp_path."""
    oc_dir = tmp_path / ".docket"
    oc_dir.mkdir()

    agent_ws = oc_dir / "workspaces" / "projects" / agent_id
    (agent_ws / "memory").mkdir(parents=True)

    (agent_ws / ".docket-meta.json").write_text(json.dumps(META))
    (agent_ws / "SOUL.md").write_text("# SOUL\n")
    (agent_ws / "MEMORY.md").write_text("# MEMORY\n")

    (oc_dir / "fleet.json").write_text(json.dumps(FLEET_CONFIG))

    return oc_dir


def _write_docket_session(
    oc_dir: Path,
    session_key: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    turns: int = 1,
    updated: str = "2024-03-15T10:00:00Z",
) -> None:
    """Seed a docket-native session (``core/session.py``'s on-disk shape)
    directly -- a pod-dispatch hop's turns land here, through
    ``DocketDriver``.
    """
    from urllib.parse import quote

    sdir = oc_dir / "sessions" / quote(session_key, safe="")
    sdir.mkdir(parents=True, exist_ok=True)
    record = {
        "sessionKey": session_key,
        "created": updated,
        "updated": updated,
        "messages": [],
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cachedTokens": cached_tokens,
            "turns": turns,
        },
    }
    (sdir / "session.json").write_text(json.dumps(record))


def _run(args: list[str], oc_dir: Path) -> tuple[int, str, str]:
    """Run `python -m docket <args>` with DOCKET_HOME overridden."""
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
        # Write fleet.json with an empty agents list (registration lives here)
        (oc_dir / "fleet.json").write_text(
            json.dumps({"agents": [], "bindings": [], "defaults": {"model": ""}})
        )
        rc, out, _ = _run(["list", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["agents"][0]["registered"] is False

    def test_list_json_telegram_binding(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        fleet = {
            **FLEET_CONFIG,
            "bindings": [
                {
                    "agentId": "myshop",
                    "channel": "telegram",
                    "peerKind": "group",
                    "peerId": "-123456",
                }
            ],
        }
        (oc_dir / "fleet.json").write_text(json.dumps(fleet))
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
        assert "ORG SPECIALISTS" in out

    def test_list_empty_no_agents(self, tmp_path: Path) -> None:
        oc_dir = tmp_path / ".docket"
        oc_dir.mkdir()
        rc, out, _err = _run(["list"], oc_dir)
        assert rc == 0
        assert "No project agents" in out

    def test_list_json_multiple_agents(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, "myshop")
        # Add second agent
        ws2 = oc_dir / "workspaces" / "projects" / "blog"
        ws2.mkdir(parents=True)
        meta2 = {**META, "name": "Blog"}
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
        _write_docket_session(
            oc_dir,
            "agent:myshop:default",
            input_tokens=1000,
            output_tokens=200,
            cached_tokens=500,
        )
        rc, out, _ = _run(["cost", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        a = data["agents"][0]
        assert a["input"] == 1000
        assert a["output"] == 200
        assert a["turns"] == 1
        # DocketDriver never reports a USD cost -- CLAUDE.md's standing rule
        # against turning a measured-token count into a billing claim, the
        # same "0.0 with real token counts recorded" contract run_turn
        # already had, now visible through `docket cost` too (a named,
        # permanent capability gap).
        assert a["costUsd"] == 0.0
        assert data["totalUsd"] == 0.0

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
        """``DocketDriver.usage().by_day`` is always ``[]`` -- a session's
        stored usage is one running total for its lifetime, with no per-turn
        timestamp to bucket by day (see
        ``edges/adapters/docket_runtime.py``'s ``usage()`` docstring).
        ``docket cost --history`` is an honest empty list against the
        production driver -- a named, permanent capability gap, not a bug
        this test should paper over.
        """
        oc_dir = _setup_agent(tmp_path)
        _write_docket_session(oc_dir, "agent:myshop:default", input_tokens=500, output_tokens=100)
        rc, out, _ = _run(["cost", "--history", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["history"] == []

    def test_cost_history_days_filter(self, tmp_path: Path) -> None:
        """Same gap as above: real usage exists, but --history stays empty
        regardless of --days since DocketDriver reports no daily breakdown."""
        oc_dir = _setup_agent(tmp_path)
        _write_docket_session(oc_dir, "agent:myshop:default", input_tokens=1, output_tokens=1)
        rc, out, _ = _run(["cost", "--history", "--days", "2", "--json"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["history"] == []


# ---------------------------------------------------------------------------
# default invocation — no subcommand
# ---------------------------------------------------------------------------


class TestDefaultInvocation:
    def test_no_args_prints_state_free_command_guide(self, tmp_path: Path) -> None:
        """Bare docket is concise and does not render the fleet implicitly."""
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run([], oc_dir)
        assert rc == 0
        assert "docket init" in out
        assert "docket status" in out
        assert "myshop" not in out
