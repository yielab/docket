"""M4 wave-3b tests: logs.

All tests run `python -m docket` as a subprocess with DOCKET_HOME overridden
and DOCKET_NO_RESTART=1 so no systemctl calls are made. Phase 19 P19-7b: the
daemon and openclaw.json are gone -- fleet.json is the only registry left,
and `docket logs`' old "Gateway log" section (which scanned the daemon's
gateway log for a bound peer's activity) has no successor -- there is no
gateway log to scan any more, so the section is simply gone (see
cli/__init__.py's cmd_logs).

(The `docket workflow` coverage this module used to carry was deleted when
that command was retired — see tests/python/test_w3_workflow_removed.py.)
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

FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-999"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _make_env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DOCKET_HOME": str(home),
        "DOCKET_NO_RESTART": "1",
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
# docket logs
# ---------------------------------------------------------------------------


class TestCmdLogs:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["logs", "ghost"], _make_env(home))
        assert rc == 1
        assert "ghost" in err

    def test_shows_memory_log_header(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], _make_env(home))
        assert rc == 0
        assert "Latest memory log" in out
        assert "2026-06-20.md" in out

    def test_shows_first_40_lines(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], _make_env(home))
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
        rc, out, _ = _run(["logs", "bare"], _make_env(home))
        assert rc == 0
        assert "No memory logs" in out

    def test_non_tty_without_id_exits_1(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, _, err = _run(["logs"], _make_env(home))
        assert rc == 1
        assert "required" in err.lower()

    def test_no_gateway_section_daemon_is_gone(self, tmp_path: Path) -> None:
        # P19-7b: there is no daemon gateway log left to scan for a bound
        # peer's activity, so the section is gone outright -- not
        # conditional on a binding any more. No successor; deliberately
        # verified absent regardless of binding state.
        home = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], _make_env(home))
        assert rc == 0
        assert "Gateway log" not in out
        assert "openclaw" not in out.lower()


# ---------------------------------------------------------------------------
# Confirm logs is not exit 127 (i.e. did not fall through to Bash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["logs", "x"]])
def test_wave3b_not_exit_127(cmd: list[str], tmp_path: Path) -> None:
    """logs must NOT fall through to Bash (exit 127)."""
    home = _setup_agent(tmp_path)
    rc, _, _ = _run(cmd, _make_env(home))
    assert rc != 127
