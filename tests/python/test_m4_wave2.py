"""M4 wave-2 tests: delete, wire, unwire — writer commands.

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

OC_CONFIG_WITH_BINDING: dict[str, Any] = {
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
            "match": {"channel": "telegram", "peer": {"kind": "group", "id": "-123456789"}},
        }
    ],
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _make_env_wire(oc_dir: Path, log_dir: Path) -> dict[str, str]:
    return {
        **_make_env(oc_dir),
        "OPENCLAW_LOG_DIR": str(log_dir),
    }


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "myshop",
    with_binding: bool = False,
) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    oc_cfg = OC_CONFIG_WITH_BINDING if with_binding else OC_CONFIG
    (oc_dir / "openclaw.json").write_text(json.dumps(oc_cfg))
    return oc_dir


def _setup_wire_env(
    tmp_path: Path,
    groups: list[tuple[str, str]],
    with_binding: bool = False,
) -> tuple[Path, Path]:
    """Set up oc_dir and log_dir for wire tests.

    groups: list of (chat_id, title); log entries are written to a dated log file.
    Returns (oc_dir, log_dir).
    """
    oc_dir = _setup_agent(tmp_path, with_binding=with_binding)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    if groups:
        lines = [
            f'{{"timestamp":"2026-06-22T10:00:00Z","chatId":{gid},"title":"{title}"}}'
            for gid, title in groups
        ]
        (log_dir / "openclaw-2026-06-22.log").write_text("\n".join(lines) + "\n")

    return oc_dir, log_dir


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
        oc_dir = _setup_agent(tmp_path)
        # Set up a specialist workspace so workspace_dir resolves
        spec_ws = oc_dir / "workspaces" / "programmer"
        spec_ws.mkdir(parents=True)
        (spec_ws / ".docket-meta.json").write_text(json.dumps(META))
        rc, _, err = _run(["delete", "programmer"], _make_env(oc_dir))
        assert rc == 1
        assert "specialist" in err.lower()

    def test_delete_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["delete", "ghost"], _make_env(oc_dir), "n\nghost\n")
        assert rc == 1
        assert "not found" in err

    def test_delete_aborts_on_wrong_confirm(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["delete", "myshop"], _make_env(oc_dir), "n\nwrong-id\n")
        assert rc == 0
        assert "Aborted" in out or "Aborted" in _

    def test_delete_removes_registration(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["delete", "myshop"], _make_env(oc_dir), "n\nmyshop\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        registered_ids = [a["id"] for a in oc["agents"]["list"]]
        assert "myshop" not in registered_ids

    def test_delete_keeps_workspace_when_n(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        _run(["delete", "myshop"], _make_env(oc_dir), "n\nmyshop\n")
        assert ws.is_dir()

    def test_delete_removes_workspace_when_y(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        rc, _, _ = _run(["delete", "myshop"], _make_env(oc_dir), "y\nmyshop\n")
        assert rc == 0
        assert not ws.exists()

    def test_delete_removes_telegram_binding(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_binding=True)
        rc, _, err = _run(["delete", "myshop"], _make_env(oc_dir), "n\nmyshop\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        myshop_bindings = [b for b in oc["bindings"] if b["agentId"] == "myshop"]
        assert not myshop_bindings

    def test_delete_dry_run_gateway(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["delete", "myshop"], _make_env(oc_dir), "n\nmyshop\n")
        assert rc == 0
        assert "[dry-run]" in out

    def test_delete_shows_summary_before_confirm(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _, out, _ = _run(["delete", "myshop"], _make_env(oc_dir), "n\nmyshop\n")
        assert "myshop" in out
        assert "Workspace" in out or "workspace" in out


# ---------------------------------------------------------------------------
# docket unwire
# ---------------------------------------------------------------------------


class TestCmdUnwire:
    def test_unwire_no_binding_exits_0(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["unwire", "myshop"], _make_env(oc_dir), "y\n")
        assert rc == 0
        combined = out + err
        assert "no" in combined.lower() or "binding" in combined.lower()

    def test_unwire_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["unwire", "ghost"], _make_env(oc_dir))
        assert rc == 1
        assert "not found" in err

    def test_unwire_aborts_when_declined(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_binding=True)
        rc, _, _ = _run(["unwire", "myshop"], _make_env(oc_dir), "n\n")
        assert rc == 0
        # Binding must still be there
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        myshop_bindings = [b for b in oc["bindings"] if b["agentId"] == "myshop"]
        assert len(myshop_bindings) == 1

    def test_unwire_removes_binding(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_binding=True)
        rc, _, err = _run(["unwire", "myshop"], _make_env(oc_dir), "y\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        myshop_bindings = [b for b in oc["bindings"] if b["agentId"] == "myshop"]
        assert not myshop_bindings

    def test_unwire_dry_run_gateway(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_binding=True)
        rc, out, _ = _run(["unwire", "myshop"], _make_env(oc_dir), "y\n")
        assert rc == 0
        assert "[dry-run]" in out

    def test_unwire_custom_channel_no_binding(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["unwire", "myshop", "--channel", "slack"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "no" in combined.lower() or "binding" in combined.lower()


# ---------------------------------------------------------------------------
# docket wire
# ---------------------------------------------------------------------------


class TestCmdWire:
    def test_wire_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        rc, _, err = _run(["wire", "ghost"], _make_env_wire(oc_dir, log_dir))
        assert rc == 1
        assert "not found" in err

    def test_wire_no_logs_exits_0(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()  # empty log dir — no groups
        rc, out, err = _run(["wire", "myshop"], _make_env_wire(oc_dir, log_dir))
        assert rc == 0
        combined = out + err
        assert "no" in combined.lower()

    def test_wire_no_log_dir_exits_0(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        nonexistent = tmp_path / "no-such-dir"
        rc, _, _ = _run(["wire", "myshop"], _make_env_wire(oc_dir, nonexistent))
        assert rc == 0

    def test_wire_single_unbound_group_accept(self, tmp_path: Path) -> None:
        oc_dir, log_dir = _setup_wire_env(tmp_path, [("-123456789", "Dev Group")])
        rc, _, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="Y\n",
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        binding = next(
            (b for b in oc["bindings"] if b["agentId"] == "myshop"), None
        )
        assert binding is not None
        assert binding["match"]["peer"]["id"] == "-123456789"

    def test_wire_single_unbound_group_reject(self, tmp_path: Path) -> None:
        oc_dir, log_dir = _setup_wire_env(tmp_path, [("-123456789", "Dev Group")])
        rc, out, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="n\n",
        )
        assert rc == 0
        combined = out + err
        assert "Aborted" in combined

    def test_wire_multiple_unbound_groups_pick(self, tmp_path: Path) -> None:
        oc_dir, log_dir = _setup_wire_env(
            tmp_path,
            [("-111", "Group A"), ("-222", "Group B")],
        )
        rc, _, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="1\n",
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        binding = next((b for b in oc["bindings"] if b["agentId"] == "myshop"), None)
        assert binding is not None
        assert binding["match"]["peer"]["id"] == "-111"

    def test_wire_multiple_unbound_groups_abort(self, tmp_path: Path) -> None:
        oc_dir, log_dir = _setup_wire_env(
            tmp_path,
            [("-111", "Group A"), ("-222", "Group B")],
        )
        rc, out, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="\n",  # Enter to cancel
        )
        assert rc == 0
        combined = out + err
        assert "Aborted" in combined

    def test_wire_manual_entry(self, tmp_path: Path) -> None:
        oc_dir, log_dir = _setup_wire_env(
            tmp_path,
            [("-111", "Group A"), ("-222", "Group B")],
        )
        rc, _, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="0\n-999888777\n",  # 0 = manual, then ID
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        binding = next((b for b in oc["bindings"] if b["agentId"] == "myshop"), None)
        assert binding is not None
        assert binding["match"]["peer"]["id"] == "-999888777"

    def test_wire_all_bound_then_abort(self, tmp_path: Path) -> None:
        # Agent already has a binding; the one group in logs is already bound.
        oc_dir, log_dir = _setup_wire_env(
            tmp_path,
            [("-123456789", "My Group")],
            with_binding=True,
        )
        rc, out, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="\n",  # Enter to cancel
        )
        assert rc == 0
        combined = out + err
        assert "Aborted" in combined

    def test_wire_dry_run_gateway(self, tmp_path: Path) -> None:
        oc_dir, log_dir = _setup_wire_env(tmp_path, [("-123456789", "Dev Group")])
        rc, out, _ = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="Y\n",
        )
        assert rc == 0
        assert "[dry-run]" in out

    def test_wire_shows_existing_binding_warning(self, tmp_path: Path) -> None:
        # Agent already has a binding — wire should warn about it.
        oc_dir, log_dir = _setup_wire_env(
            tmp_path,
            [("-123456789", "My Group"), ("-999", "Other")],
            with_binding=True,
        )
        _, out, err = _run(
            ["wire", "myshop"],
            _make_env_wire(oc_dir, log_dir),
            stdin_text="\n",
        )
        combined = out + err
        assert "-123456789" in combined  # current binding shown


# ---------------------------------------------------------------------------
# stub list confirms delete/wire/unwire no longer exit 127
# ---------------------------------------------------------------------------


class TestM4Wave2CommandsPortedFromStubs:
    @pytest.mark.parametrize(
        "cmd",
        [
            ["delete", "ghost"],  # exits 1 (not found) — not 127
            ["wire", "ghost"],    # exits 1 (not found) — not 127
            ["unwire", "ghost"],  # exits 1 (not found) — not 127
        ],
    )
    def test_does_not_exit_127(self, cmd: list[str], tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        rc, _, _ = _run(cmd, _make_env_wire(oc_dir, log_dir))
        assert rc != 127, f"`docket {' '.join(cmd)}` still exits 127 (not ported)"
