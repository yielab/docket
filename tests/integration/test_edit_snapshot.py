"""edit, snapshot commands.

All tests invoke the CLI in-process via CliRunner, with every DOCKET_HOME-derived
config constant patched to a temp directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import app as _app

SUBJECT = "edit snapshot"

_runner = CliRunner()

# Every DOCKET_HOME-derived config constant this suite's commands can touch.
_HOME_ATTRS: tuple[tuple[str, str], ...] = (
    ("DOCKET_HOME", ""),
    ("WORKSPACES_DIR", "workspaces"),
    ("PROJECTS_DIR", "workspaces/projects"),
    ("FLEET_FILE", "fleet.json"),
    ("SESSIONS_DIR", "sessions"),
)


def _patch_home(mp: pytest.MonkeyPatch, home: Path) -> None:
    for attr, leaf in _HOME_ATTRS:
        mp.setattr(_cfg, attr, home / leaf if leaf else home, raising=True)


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
        _patch_home(mp, home)
        for key in unset or ():
            mp.delenv(key, raising=False)
        for key, value in (env or {}).items():
            mp.setenv(key, value)
        result = _runner.invoke(_app, args, input=stdin_text)
    return result.exit_code, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# docket edit
# ---------------------------------------------------------------------------


class TestCmdEdit:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["edit", "ghost"], oc_dir)
        assert rc == 1
        assert "ghost" in err

    def test_no_files_exits_0(self, tmp_path: Path) -> None:
        # Workspace exists but has no SOUL/AGENTS/etc.
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["edit", "myshop"], oc_dir)
        assert rc == 0
        assert "no workspace files" in (out + err).lower()

    def test_opens_files_with_editor(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md", "AGENTS.md"])
        rc, out, _ = _run(["edit", "myshop"], oc_dir, env={"EDITOR": "true"})
        assert rc == 0
        assert "Edits saved" in out

    def test_lists_files_before_opening(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md", "HEARTBEAT.md"])
        rc, out, _ = _run(["edit", "myshop"], oc_dir, env={"EDITOR": "true"})
        assert rc == 0
        assert "SOUL.md" in out
        assert "HEARTBEAT.md" in out

    def test_uses_visual_when_no_editor(self, tmp_path: Path) -> None:
        # VISUAL is the fallback when EDITOR is unset
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md"])
        rc, out, _ = _run(["edit", "myshop"], oc_dir, env={"VISUAL": "true"}, unset=["EDITOR"])
        assert rc == 0
        assert "Edits saved" in out

    def test_missing_editor_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md"])
        rc, _, err = _run(
            ["edit", "myshop"],
            oc_dir,
            env={"EDITOR": "nonexistent_editor_xyz_99"},
            unset=["VISUAL"],
        )
        assert rc == 1
        assert "not found" in err.lower()

    def test_non_tty_without_agent_id_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["edit"], oc_dir)
        assert rc == 1
        assert "required" in err.lower()

    def test_specialist_workspace_opened(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # Create specialist workspace
        spec_ws = oc_dir / "workspaces" / "programmer"
        spec_ws.mkdir(parents=True)
        (spec_ws / ".docket-meta.json").write_text(
            json.dumps({"kind": "specialist", "name": "programmer"})
        )
        (spec_ws / "SOUL.md").write_text("# Programmer\nI write code.\n")
        rc, out, _ = _run(["edit", "programmer"], oc_dir, env={"EDITOR": "true"})
        assert rc == 0
        assert "Edits saved" in out


# ---------------------------------------------------------------------------
# docket snapshot
# ---------------------------------------------------------------------------


class TestCmdSnapshot:
    def test_json_output_has_required_keys(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        for key in ("timestamp", "gateway", "channels", "agents", "totalCostUsd"):
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

    def test_specialist_included_when_workspace_exists(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        spec_ws = oc_dir / "workspaces" / "programmer"
        spec_ws.mkdir(parents=True)
        (spec_ws / ".docket-meta.json").write_text(
            json.dumps({"kind": "specialist", "name": "Programmer"})
        )
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "programmer" in ids

    def test_specialist_not_included_when_no_workspace(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], oc_dir)
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "programmer" not in ids

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
# Confirm edit + snapshot are no longer in the 127-exit list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["edit", "x"], ["snapshot"]])
def test_wave3a_not_exit_127(cmd: list[str], tmp_path: Path) -> None:
    """edit and snapshot must NOT fall through to Bash (exit 127)."""
    oc_dir = _setup_agent(tmp_path)
    rc, _, _ = _run(cmd, oc_dir, env={"EDITOR": "true"})
    assert rc != 127
