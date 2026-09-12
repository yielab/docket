"""logs command.

All tests invoke the CLI in-process via CliRunner, with every DOCKET_HOME-derived
config constant patched to a fresh temp home per call. fleet.json is docket's only
agent/binding registry, so `docket logs` has no "Gateway log" section (there is no
gateway log to scan) -- see cli/__init__.py's cmd_logs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import app as _app

SUBJECT = "logs command"

_runner = CliRunner()

# Every DOCKET_HOME-derived config constant `docket logs` (or its neighbors in
# this suite) can touch, paired with its path under a fresh home.
_HOME_ATTRS: tuple[tuple[str, str], ...] = (
    ("DOCKET_HOME", ""),
    ("WORKSPACES_DIR", "workspaces"),
    ("PROJECTS_DIR", "workspaces/projects"),
    ("FLEET_FILE", "fleet.json"),
    ("TRACES_DIR", "traces"),
    ("AUDIT_LOG", "audit.log"),
    ("SESSIONS_DIR", "sessions"),
    ("MODEL_REGISTRY_FILE", "docket-models.json"),
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
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-999"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    *,
    fleet_config: dict[str, Any] | None = None,
) -> Path:
    """Create a minimal project workspace with memory log. Returns DOCKET_HOME."""
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    ws = home / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    mem_dir = ws / "memory"
    mem_dir.mkdir()
    (mem_dir / "2026-06-20.md").write_text("# Day log\n" + "line\n" * 50)
    (home / "fleet.json").write_text(json.dumps(fleet_config or FLEET_CONFIG))
    return home


def _run(
    args: list[str],
    home: Path,
    stdin_text: str = "",
) -> tuple[int, str, str]:
    with pytest.MonkeyPatch.context() as mp:
        _patch_home(mp, home)
        result = _runner.invoke(_app, args, input=stdin_text)
    return result.exit_code, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# docket logs
# ---------------------------------------------------------------------------


class TestCmdLogs:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["logs", "ghost"], home)
        assert rc == 1
        assert "ghost" in err

    def test_shows_memory_log_header(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], home)
        assert rc == 0
        assert "Latest memory log" in out
        assert "2026-06-20.md" in out

    def test_shows_first_40_lines(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], home)
        assert rc == 0
        # File has 51 lines (# Day log + 50 "line\n")
        assert "more lines" in out

    def test_no_memory_log_message(self, tmp_path: Path) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        ws = home / "workspaces" / "projects" / "bare"
        ws.mkdir(parents=True)
        (ws / ".docket-meta.json").write_text(json.dumps(META))
        (home / "fleet.json").write_text(json.dumps(FLEET_CONFIG))
        rc, out, _ = _run(["logs", "bare"], home)
        assert rc == 0
        assert "No memory logs" in out

    def test_non_tty_without_id_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["logs"], home)
        assert rc == 1
        assert "required" in err.lower()

    def test_no_gateway_section_daemon_is_gone(self, tmp_path: Path) -> None:
        # There is no daemon gateway log to scan for a bound peer's
        # activity, so the section is gone outright -- not conditional on a
        # binding. Deliberately verified absent regardless of binding state.
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], home)
        assert rc == 0
        assert "Gateway log" not in out
        retired_brand = "open" + "claw"
        assert retired_brand not in out.lower()


# ---------------------------------------------------------------------------
# Confirm logs is not exit 127 (i.e. did not fall through to Bash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["logs", "x"]])
def test_wave3b_not_exit_127(cmd: list[str], tmp_path: Path) -> None:
    """logs must NOT fall through to Bash (exit 127)."""
    home = _setup_agent(tmp_path)
    rc, _, _ = _run(cmd, home)
    assert rc != 127
