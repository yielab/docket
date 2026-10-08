"""snapshot command.

All tests invoke the CLI in-process via CliRunner, with every DOCKET_HOME-derived
config constant patched to a temp directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import app as _app

SUBJECT = "docket.cli"

_runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared helpers
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
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-999"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    workspace_files: list[str] | None = None,
) -> Path:
    """Create a minimal project workspace.  Returns the docket home dir."""
    oc_dir = tmp_path / ".docket"
    oc_dir.mkdir(exist_ok=True)
    ws = oc_dir / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    for fname in workspace_files or []:
        (ws / fname).write_text(f"# {agent_id}\n")
    (oc_dir / "fleet.json").write_text(json.dumps(FLEET_CONFIG))
    return oc_dir


def _run(
    args: list[str],
    home: Path,
    stdin_text: str = "",
    env: dict[str, str] | None = None,
    unset: list[str] | None = None,
) -> tuple[int, str, str]:
    with pytest.MonkeyPatch.context() as mp:
        repoint_docket_home(mp, home)
        for key in unset or ():
            mp.delenv(key, raising=False)
        for key, value in (env or {}).items():
            mp.setenv(key, value)
        result = _runner.invoke(_app, args, input=stdin_text)
    return result.exit_code, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# docket snapshot
# ---------------------------------------------------------------------------


class TestCmdSnapshot:
    def test_json_output_has_required_keys(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        for key in ("timestamp", "channels", "agents", "totalCostUsd"):
            assert key in data, f"Missing key: {key}"

    def test_includes_project_agent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "myshop" in ids

    def test_agent_entry_structure(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        agent = next(a for a in data["agents"] if a["id"] == "myshop")
        for key in (
            "id",
            "name",
            "kind",
            "model",
            "registered",
            "bindings",
            "lastActivity",
            "costUsd",
        ):
            assert key in agent, f"Agent missing key: {key}"
        assert agent["kind"] == "project"
        assert agent["name"] == "My Shop"

    def test_last_activity_is_never_when_no_logs(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        agent = next(a for a in data["agents"] if a["id"] == "myshop")
        assert agent["lastActivity"] == "never"

    def test_bindings_included(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        agent = next(a for a in data["agents"] if a["id"] == "myshop")
        assert len(agent["bindings"]) == 1
        assert agent["bindings"][0]["channel"] == "telegram"
        assert agent["bindings"][0]["peerId"] == "-999"

    def test_channels_list(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert "telegram" in data["channels"]

    def test_output_to_file(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        out_file = tmp_path / "snap.json"
        rc, stdout, _ = _run(["snapshot", "--output", str(out_file)], oc_dir)
        assert rc == 0
        assert "Snapshot written" in stdout
        data = json.loads(out_file.read_text())
        assert "agents" in data

    def test_output_file_shorthand(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        out_file = tmp_path / "snap2.json"
        rc, _, _ = _run(["snapshot", "-o", str(out_file)], oc_dir)
        assert rc == 0
        assert out_file.exists()

    def test_leftover_shared_directory_not_included(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        spec_ws = oc_dir / "workspaces" / "knowledge"
        spec_ws.mkdir(parents=True)
        (spec_ws / ".docket-meta.json").write_text(json.dumps({"kind": "project"}))
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "knowledge" not in ids

    def test_total_cost_usd_is_float(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert isinstance(data["totalCostUsd"], float)

    def test_timestamp_format(self, tmp_path: Path) -> None:
        import re

        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data["timestamp"])

    def test_empty_fleet_graceful(self, tmp_path: Path) -> None:
        # No fleet.json at all -- channels, bindings, and agents must all default empty.
        oc_dir = tmp_path / ".docket"
        oc_dir.mkdir()
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        assert data["agents"] == []
        assert data["totalCostUsd"] == 0.0


# ---------------------------------------------------------------------------
# Confirm snapshot is no longer in the 127-exit list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["snapshot"]])
def test_wave3a_not_exit_127(cmd: list[str], tmp_path: Path) -> None:
    """snapshot must NOT fall through to Bash (exit 127)."""
    oc_dir = _setup_agent(tmp_path)
    rc, _, _ = _run(cmd, oc_dir)
    assert rc != 127
