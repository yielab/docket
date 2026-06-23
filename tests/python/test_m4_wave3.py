"""M4 wave-3a tests: edit, snapshot.

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

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
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
    "bindings": [
        {
            "agentId": "myshop",
            "match": {"channel": "telegram", "peer": {"kind": "group", "id": "-999"}},
        }
    ],
    "channels": {"telegram": {"enabled": True}},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    workspace_files: list[str] | None = None,
) -> Path:
    """Create a minimal project workspace.  Returns the oc_dir."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(exist_ok=True)
    ws = oc_dir / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    for fname in workspace_files or []:
        (ws / fname).write_text(f"# {agent_id}\n")
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))
    return oc_dir


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


# ---------------------------------------------------------------------------
# docket edit
# ---------------------------------------------------------------------------


class TestCmdEdit:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        env = _make_env(oc_dir)
        rc, _, err = _run(["edit", "ghost"], env)
        assert rc == 1
        assert "ghost" in err

    def test_no_files_exits_0(self, tmp_path: Path) -> None:
        # Workspace exists but has no SOUL/AGENTS/etc.
        oc_dir = _setup_agent(tmp_path)
        env = _make_env(oc_dir)
        rc, out, err = _run(["edit", "myshop"], env)
        assert rc == 0
        assert "no workspace files" in (out + err).lower()

    def test_opens_files_with_editor(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md", "AGENTS.md"])
        env = {**_make_env(oc_dir), "EDITOR": "true"}
        rc, out, _ = _run(["edit", "myshop"], env)
        assert rc == 0
        assert "Edits saved" in out

    def test_lists_files_before_opening(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md", "HEARTBEAT.md"])
        env = {**_make_env(oc_dir), "EDITOR": "true"}
        rc, out, _ = _run(["edit", "myshop"], env)
        assert rc == 0
        assert "SOUL.md" in out
        assert "HEARTBEAT.md" in out

    def test_uses_visual_when_no_editor(self, tmp_path: Path) -> None:
        # VISUAL is the fallback when EDITOR is unset
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md"])
        env = {**_make_env(oc_dir), "VISUAL": "true"}
        env.pop("EDITOR", None)
        rc, out, _ = _run(["edit", "myshop"], env)
        assert rc == 0
        assert "Edits saved" in out

    def test_missing_editor_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, workspace_files=["SOUL.md"])
        env = {**_make_env(oc_dir), "EDITOR": "nonexistent_editor_xyz_99"}
        env.pop("VISUAL", None)
        rc, _, err = _run(["edit", "myshop"], env)
        assert rc == 1
        assert "not found" in err.lower()

    def test_non_tty_without_agent_id_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        env = _make_env(oc_dir)
        rc, _, err = _run(["edit"], env)
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
        env = {**_make_env(oc_dir), "EDITOR": "true"}
        rc, out, _ = _run(["edit", "programmer"], env)
        assert rc == 0
        assert "Edits saved" in out


# ---------------------------------------------------------------------------
# docket snapshot
# ---------------------------------------------------------------------------


class TestCmdSnapshot:
    def test_json_output_has_required_keys(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        for key in ("timestamp", "gateway", "channels", "agents", "totalCostUsd"):
            assert key in data, f"Missing key: {key}"

    def test_includes_project_agent(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "myshop" in ids

    def test_agent_entry_structure(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        agent = next(a for a in data["agents"] if a["id"] == "myshop")
        for key in ("id", "name", "type", "kind", "model", "registered", "bindings", "lastActivity", "costUsd"):
            assert key in agent, f"Agent missing key: {key}"
        assert agent["kind"] == "project"
        assert agent["name"] == "My Shop"

    def test_bindings_included(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        agent = next(a for a in data["agents"] if a["id"] == "myshop")
        assert len(agent["bindings"]) == 1
        assert agent["bindings"][0]["channel"] == "telegram"
        assert agent["bindings"][0]["peerId"] == "-999"

    def test_channels_list(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        assert "telegram" in data["channels"]

    def test_output_to_file(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        out_file = tmp_path / "snap.json"
        rc, stdout, _ = _run(["snapshot", "--output", str(out_file)], _make_env(oc_dir))
        assert rc == 0
        assert "Snapshot written" in stdout
        data = json.loads(out_file.read_text())
        assert "agents" in data

    def test_output_file_shorthand(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        out_file = tmp_path / "snap2.json"
        rc, _, _ = _run(["snapshot", "-o", str(out_file)], _make_env(oc_dir))
        assert rc == 0
        assert out_file.exists()

    def test_specialist_included_when_workspace_exists(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        spec_ws = oc_dir / "workspaces" / "programmer"
        spec_ws.mkdir(parents=True)
        (spec_ws / ".docket-meta.json").write_text(
            json.dumps({"kind": "specialist", "name": "Programmer"})
        )
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "programmer" in ids

    def test_specialist_not_included_when_no_workspace(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        ids = [a["id"] for a in data["agents"]]
        assert "programmer" not in ids

    def test_total_cost_usd_is_float(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        assert isinstance(data["totalCostUsd"], float)

    def test_timestamp_format(self, tmp_path: Path) -> None:
        import re
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["snapshot"], _make_env(oc_dir))
        assert rc == 0
        data = json.loads(out)
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data["timestamp"])

    def test_empty_openclaw_graceful(self, tmp_path: Path) -> None:
        # Minimal openclaw.json with no channels, no bindings, no agents
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        (oc_dir / "openclaw.json").write_text(
            json.dumps({"agents": {"defaults": {"model": ""}, "list": []}, "bindings": []})
        )
        rc, out, _ = _run(["snapshot"], {**os.environ, "OPENCLAW_DIR": str(oc_dir), "DOCKET_NO_RESTART": "1"})
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
    env = {**_make_env(oc_dir), "EDITOR": "true"}
    rc, _, _ = _run(cmd, env)
    assert rc != 127
