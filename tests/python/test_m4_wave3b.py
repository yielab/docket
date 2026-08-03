"""M4 wave-3b tests: logs.

All tests run `python -m docket` as a subprocess with OPENCLAW_DIR overridden
and DOCKET_NO_RESTART=1 so no systemctl calls are made.

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

OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [
            {
                "id": "myshop",
                "model": "anthropic/claude-sonnet-4-6",
                "metadata": {"sessionKey": "agent:myshop:default"},
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

# P19-6: agent registration + channel bindings live in fleet.json now, not
# openclaw.json's `agents`/`bindings` above.
FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-999"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_HOME": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    *,
    oc_config: dict[str, Any] | None = None,
    fleet_config: dict[str, Any] | None = None,
) -> Path:
    """Create a minimal project workspace with memory log.  Returns oc_dir."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(exist_ok=True)
    ws = oc_dir / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    mem_dir = ws / "memory"
    mem_dir.mkdir()
    (mem_dir / "2026-06-20.md").write_text("# Day log\n" + "line\n" * 50)
    (oc_dir / "openclaw.json").write_text(json.dumps(oc_config or OC_CONFIG))
    (oc_dir / "fleet.json").write_text(json.dumps(fleet_config or FLEET_CONFIG))
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
# docket logs
# ---------------------------------------------------------------------------


class TestCmdLogs:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["logs", "ghost"], _make_env(oc_dir))
        assert rc == 1
        assert "ghost" in err

    def test_shows_memory_log_header(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], _make_env(oc_dir))
        assert rc == 0
        assert "Latest memory log" in out
        assert "2026-06-20.md" in out

    def test_shows_first_40_lines(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["logs", "myshop"], _make_env(oc_dir))
        assert rc == 0
        # File has 51 lines (# Day log + 50 "line\n")
        assert "more lines" in out

    def test_no_memory_log_message(self, tmp_path: Path) -> None:
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        ws = oc_dir / "workspaces" / "projects" / "bare"
        ws.mkdir(parents=True)
        (ws / ".docket-meta.json").write_text(json.dumps(META))
        (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))
        rc, out, _ = _run(["logs", "bare"], _make_env(oc_dir))
        assert rc == 0
        assert "No memory logs" in out

    def test_non_tty_without_id_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["logs"], _make_env(oc_dir))
        assert rc == 1
        assert "required" in err.lower()

    def test_gateway_section_shown_with_binding(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # Write a fake log file for today
        import datetime as dt

        today = dt.date.today().strftime("%Y-%m-%d")
        log_dir = tmp_path / "oclog"
        log_dir.mkdir()
        log_file = log_dir / f"openclaw-{today}.log"
        log_file.write_text("-999 some event\n-999 another event\n")
        env = {**_make_env(oc_dir), "OPENCLAW_LOG_DIR": str(log_dir)}
        rc, out, _ = _run(["logs", "myshop"], env)
        assert rc == 0
        assert "Gateway log" in out
        assert "2 entries" in out

    def test_gateway_section_absent_without_binding(self, tmp_path: Path) -> None:
        fleet_config = {**FLEET_CONFIG, "bindings": []}
        oc_dir = _setup_agent(tmp_path, fleet_config=fleet_config)
        rc, out, _ = _run(["logs", "myshop"], _make_env(oc_dir))
        assert rc == 0
        assert "Gateway log" not in out


# ---------------------------------------------------------------------------
# Confirm logs is not exit 127 (i.e. did not fall through to Bash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["logs", "x"]])
def test_wave3b_not_exit_127(cmd: list[str], tmp_path: Path) -> None:
    """logs must NOT fall through to Bash (exit 127)."""
    oc_dir = _setup_agent(tmp_path)
    rc, _, _ = _run(cmd, _make_env(oc_dir))
    assert rc != 127
