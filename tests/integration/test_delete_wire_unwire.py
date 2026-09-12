"""delete, wire, unwire — writer commands.

All tests run `python -m docket` as a subprocess with DOCKET_HOME overridden
so tests are hermetic. fleet.json is docket's only agent/binding registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
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

FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}

FLEET_CONFIG_WITH_BINDING: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-123456789"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _make_env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DOCKET_HOME": str(home),
    }


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    with_binding: bool = False,
) -> Path:
    home = tmp_path / ".docket"
    home.mkdir()
    ws = home / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    fleet_cfg = FLEET_CONFIG_WITH_BINDING if with_binding else FLEET_CONFIG
    (home / "fleet.json").write_text(json.dumps(fleet_cfg))
    return home


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
# docket delete
# ---------------------------------------------------------------------------


class TestCmdDelete:
    def test_delete_specialist_blocked(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        # Set up a specialist workspace so workspace_dir resolves
        spec_ws = home / "workspaces" / "programmer"
        spec_ws.mkdir(parents=True)
        (spec_ws / ".docket-meta.json").write_text(json.dumps(META))
        rc, _, err = _run(["delete", "programmer"], _make_env(home))
        assert rc == 1
        assert "specialist" in err.lower()

    def test_delete_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["delete", "ghost"], _make_env(home), "n\nghost\n")
        assert rc == 1
        assert "not found" in err

    def test_delete_aborts_on_wrong_confirm(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["delete", "myshop"], _make_env(home), "n\nwrong-id\n")
        assert rc == 0
        assert "Aborted" in out or "Aborted" in _

    def test_delete_removes_registration(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["delete", "myshop"], _make_env(home), "n\nmyshop\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        fleet = json.loads((home / "fleet.json").read_text())
        registered_ids = [a["id"] for a in fleet["agents"]]
        assert "myshop" not in registered_ids

    def test_delete_keeps_workspace_when_n(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        ws = home / "workspaces" / "projects" / "myshop"
        _run(["delete", "myshop"], _make_env(home), "n\nmyshop\n")
        assert ws.is_dir()

    def test_delete_removes_workspace_when_y(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        ws = home / "workspaces" / "projects" / "myshop"
        rc, _, _ = _run(["delete", "myshop"], _make_env(home), "y\nmyshop\n")
        assert rc == 0
        assert not ws.exists()

    def test_delete_removes_telegram_binding(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_binding=True)
        rc, _, err = _run(["delete", "myshop"], _make_env(home), "n\nmyshop\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        fleet = json.loads((home / "fleet.json").read_text())
        myshop_bindings = [b for b in fleet["bindings"] if b["agentId"] == "myshop"]
        assert not myshop_bindings

    def test_delete_shows_summary_before_confirm(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        _, out, _ = _run(["delete", "myshop"], _make_env(home), "n\nmyshop\n")
        assert "myshop" in out
        assert "Workspace" in out or "workspace" in out


# ---------------------------------------------------------------------------
# docket unwire
# ---------------------------------------------------------------------------


class TestCmdUnwire:
    def test_unwire_no_binding_exits_0(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["unwire", "myshop"], _make_env(home), "y\n")
        assert rc == 0
        combined = out + err
        assert "no" in combined.lower() or "binding" in combined.lower()

    def test_unwire_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["unwire", "ghost"], _make_env(home))
        assert rc == 1
        assert "not found" in err

    def test_unwire_aborts_when_declined(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_binding=True)
        rc, _, _ = _run(["unwire", "myshop"], _make_env(home), "n\n")
        assert rc == 0
        # Binding must still be there
        fleet = json.loads((home / "fleet.json").read_text())
        myshop_bindings = [b for b in fleet["bindings"] if b["agentId"] == "myshop"]
        assert len(myshop_bindings) == 1

    def test_unwire_removes_binding(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_binding=True)
        rc, _, err = _run(["unwire", "myshop"], _make_env(home), "y\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        fleet = json.loads((home / "fleet.json").read_text())
        myshop_bindings = [b for b in fleet["bindings"] if b["agentId"] == "myshop"]
        assert not myshop_bindings

    def test_unwire_custom_channel_no_binding(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["unwire", "myshop", "--channel", "slack"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "no" in combined.lower() or "binding" in combined.lower()


# ---------------------------------------------------------------------------
# docket wire
# ---------------------------------------------------------------------------


class TestCmdWire:
    """`docket wire` discovers Telegram groups through docket's bot, while
    retaining manual entry as a fallback. The binding it records is the
    *entire* authorization boundary (see core/telegram.py), so the output
    states that plainly.
    """

    def test_wire_discovers_group_without_numeric_id_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        import docket.config as cfg
        from docket.cli import app
        from docket.core import telegram

        home = _setup_agent(tmp_path)
        monkeypatch.setattr(cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
        monkeypatch.setattr(cfg, "FLEET_FILE", home / "fleet.json", raising=True)
        monkeypatch.setattr(
            cfg, "CONVERSATIONS_FILE", home / "docket-conversations.json", raising=True
        )
        monkeypatch.setattr(telegram, "wire_discovery_configured", lambda: True, raising=False)
        monkeypatch.setattr(
            telegram,
            "discover_wire_groups",
            lambda challenge: SimpleNamespace(
                ok=True,
                configured=True,
                groups=(SimpleNamespace(chat_id="-100456", title="My Shop Team"),),
                error="",
            ),
            raising=False,
        )
        monkeypatch.setattr("secrets.token_hex", lambda size: "a1b2c3")

        result = CliRunner().invoke(app, ["wire", "myshop"], input="\n")

        assert result.exit_code == 0, result.output
        assert "/wire A1B2C3" in result.output
        assert "My Shop Team" in result.output
        fleet = json.loads((home / "fleet.json").read_text())
        assert fleet["bindings"][0]["peerId"] == "-100456"

    def test_wire_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["wire", "ghost"], _make_env(home))
        assert rc == 1
        assert "not found" in err

    def test_wire_empty_entry_aborts(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["wire", "myshop"], _make_env(home), stdin_text="\n")
        assert rc == 0
        combined = out + err
        assert "aborted" in combined.lower()
        fleet = json.loads((home / "fleet.json").read_text())
        assert not fleet["bindings"]

    def test_wire_manual_entry_records_binding(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(
            ["wire", "myshop"],
            _make_env(home),
            stdin_text="-999888777\n",
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        fleet = json.loads((home / "fleet.json").read_text())
        binding = next((b for b in fleet["bindings"] if b["agentId"] == "myshop"), None)
        assert binding is not None
        assert binding["peerId"] == "-999888777"
        # Honest: the binding IS the authorization boundary now.
        combined = out + err
        assert "whole authorization story" in combined.lower()

    def test_wire_shows_existing_binding_warning(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_binding=True)
        _, out, err = _run(
            ["wire", "myshop"],
            _make_env(home),
            stdin_text="\n",
        )
        combined = out + err
        assert "-123456789" in combined  # current binding shown

    def test_wire_updates_existing_binding(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_binding=True)
        rc, _, err = _run(
            ["wire", "myshop"],
            _make_env(home),
            stdin_text="-1001234567890\n",
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        fleet = json.loads((home / "fleet.json").read_text())
        binding = next((b for b in fleet["bindings"] if b["agentId"] == "myshop"), None)
        assert binding is not None
        assert binding["peerId"] == "-1001234567890"


# ---------------------------------------------------------------------------
# stub list confirms delete/wire/unwire no longer exit 127
# ---------------------------------------------------------------------------


class TestM4Wave2CommandsPortedFromStubs:
    @pytest.mark.parametrize(
        "cmd",
        [
            ["delete", "ghost"],  # exits 1 (not found) — not 127
            ["wire", "ghost"],  # exits 1 (not found) — not 127
            ["unwire", "ghost"],  # exits 1 (not found) — not 127
        ],
    )
    def test_does_not_exit_127(self, cmd: list[str], tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, _ = _run(cmd, _make_env(home))
        assert rc != 127, f"`docket {' '.join(cmd)}` still exits 127 (not ported)"
