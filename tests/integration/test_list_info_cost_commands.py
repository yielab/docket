"""The bare `docket` guide.

All tests invoke the CLI in-process via CliRunner, inside a `use_home` block on a
temp directory so tests are hermetic and never touch
the real ~/.docket.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.kernel.home import Home, use_home

SUBJECT = "docket.interfaces.cli.app"

_runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
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


def _run(args: list[str], oc_dir: Path) -> tuple[int, str, str]:
    """Invoke the CLI in-process against *oc_dir* as an isolated DOCKET_HOME."""
    with use_home(Home(oc_dir)):
        result = _runner.invoke(_app, args)
    return result.exit_code, result.stdout, result.stderr


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
