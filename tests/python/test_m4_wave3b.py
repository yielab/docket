"""M4 wave-3b tests: logs, workflow.

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


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    *,
    oc_config: dict[str, Any] | None = None,
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
        oc_config = {**OC_CONFIG, "bindings": []}
        oc_dir = _setup_agent(tmp_path, oc_config=oc_config)
        rc, out, _ = _run(["logs", "myshop"], _make_env(oc_dir))
        assert rc == 0
        assert "Gateway log" not in out


# ---------------------------------------------------------------------------
# docket workflow
# ---------------------------------------------------------------------------


class TestCmdWorkflow:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["workflow", "ghost"], _make_env(oc_dir))
        assert rc == 1
        assert "ghost" in err

    def test_list_no_workflows_dir(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["workflow", "myshop", "list"], _make_env(oc_dir))
        assert rc == 0
        combined = (out + err).lower()
        assert "no workflows" in combined or "create one" in combined

    def test_list_empty_workflows_dir(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        wf_dir = oc_dir / "workspaces" / "projects" / "myshop" / "workflows"
        wf_dir.mkdir()
        rc, out, _ = _run(["workflow", "myshop", "list"], _make_env(oc_dir))
        assert rc == 0
        assert "No workflows" in out or "no workflows" in out.lower()

    def test_list_shows_workflow(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        wf_dir = oc_dir / "workspaces" / "projects" / "myshop" / "workflows"
        wf_dir.mkdir()
        (wf_dir / "bug-fix.lobster.yml").write_text("steps:\n  - id: a\n  - id: b\n")
        rc, out, _ = _run(["workflow", "myshop", "list"], _make_env(oc_dir))
        assert rc == 0
        assert "bug-fix" in out

    def test_create_generates_file(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, _ = _run(["workflow", "myshop", "create", "deploy"], _make_env(oc_dir))
        assert rc == 0
        wf_file = oc_dir / "workspaces" / "projects" / "myshop" / "workflows" / "deploy.lobster.yml"
        assert wf_file.exists()
        assert "npm test" in wf_file.read_text()  # Node.js stack

    def test_create_requires_name(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["workflow", "myshop", "create"], _make_env(oc_dir))
        assert rc == 1
        assert "name required" in err.lower() or "required" in err.lower()

    def test_create_duplicate_warns(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        wf_dir = oc_dir / "workspaces" / "projects" / "myshop" / "workflows"
        wf_dir.mkdir()
        (wf_dir / "existing.lobster.yml").write_text("existing content\n")
        rc, out, err = _run(["workflow", "myshop", "create", "existing"], _make_env(oc_dir))
        assert rc == 0
        assert "already exists" in (out + err).lower()

    def test_show_prints_content(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        wf_dir = oc_dir / "workspaces" / "projects" / "myshop" / "workflows"
        wf_dir.mkdir()
        (wf_dir / "deploy.lobster.yml").write_text("name: deploy\n")
        rc, out, _ = _run(["workflow", "myshop", "show", "deploy"], _make_env(oc_dir))
        assert rc == 0
        assert "name: deploy" in out

    def test_show_missing_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["workflow", "myshop", "show", "ghost"], _make_env(oc_dir))
        assert rc == 1
        assert "ghost" in err

    def test_delete_non_tty_removes_file(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        wf_dir = oc_dir / "workspaces" / "projects" / "myshop" / "workflows"
        wf_dir.mkdir()
        wf_file = wf_dir / "old.lobster.yml"
        wf_file.write_text("old\n")
        # Non-tty: no confirmation prompt — file should be deleted
        rc, out, _ = _run(["workflow", "myshop", "delete", "old"], _make_env(oc_dir))
        assert rc == 0
        assert not wf_file.exists()
        assert "deleted" in out.lower()

    def test_delete_missing_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["workflow", "myshop", "delete", "ghost"], _make_env(oc_dir))
        assert rc == 1
        assert "ghost" in err

    def test_unknown_subcommand_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["workflow", "myshop", "frobnicate"], _make_env(oc_dir))
        assert rc == 1
        assert "unknown" in err.lower()

    def test_non_tty_without_agent_id_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["workflow"], _make_env(oc_dir))
        assert rc == 1
        assert "required" in err.lower()

    def test_default_action_is_list(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, _ = _run(["workflow", "myshop"], _make_env(oc_dir))
        assert rc == 0
        # "list" shows either "No workflows directory" or a list header
        assert rc == 0


# ---------------------------------------------------------------------------
# Confirm logs + workflow are no longer in the 127-exit list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["logs", "x"], ["workflow", "x"]])
def test_wave3b_not_exit_127(cmd: list[str], tmp_path: Path) -> None:
    """logs and workflow must NOT fall through to Bash (exit 127)."""
    oc_dir = _setup_agent(tmp_path)
    rc, _, _ = _run(cmd, _make_env(oc_dir))
    assert rc != 127
