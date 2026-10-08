"""CLI tests: init, status and the removed top-level names.

All tests invoke the CLI in-process via CliRunner, with every DOCKET_HOME-derived
config constant patched to a temp directory. Agent registration is seeded via
fleet.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _pod
from docket.cli import app as _app

SUBJECT = "docket.cli"

_runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

FLEET_EMPTY: dict[str, Any] = {"agents": [], "bindings": []}

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "Test Agent",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/tmp/testcodebase",
    "sessionKey": "agent:test-agent:default",
    "projectKey": "default",
    "description": "A test agent",
    "templateVersion": 1,
}


def _run(
    args: list[str],
    home: Path,
    stdin_text: str = "",
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    target: Any = None,
) -> tuple[int, str, str]:
    with pytest.MonkeyPatch.context() as mp:
        repoint_docket_home(mp, home)
        for key, value in (env or {}).items():
            mp.setenv(key, value)
        if cwd is not None:
            mp.chdir(cwd)
        result = _runner.invoke(target or _app, args, input=stdin_text)
    return result.exit_code, result.stdout, result.stderr


def _setup_agent(
    tmp_path: Path,
    agent_id: str = "test-agent",
    *,
    with_memory: bool = False,
    with_heartbeat_tasks: bool = False,
) -> Path:
    """Create a minimal project workspace. Returns DOCKET_HOME."""
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    ws = home / "workspaces" / "projects" / agent_id
    ws.mkdir(parents=True, exist_ok=True)

    meta = {**META, "sessionKey": f"agent:{agent_id}:default"}
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    (ws / "SOUL.md").write_text(
        f"# SOUL.md — Test Agent\n\n**Session Key:** `agent:{agent_id}:default`\n"
    )
    (ws / "AGENTS.md").write_text("# AGENTS.md\n")
    (ws / "TOOLS.md").write_text("# TOOLS.md\n")
    (ws / "HEARTBEAT.md").write_text(
        "# HEARTBEAT.md\n\n## Active Tasks\n"
        + ("- [ ] Task one\n- [x] Done task\n" if with_heartbeat_tasks else "_none_\n")
    )
    (ws / "memory").mkdir(exist_ok=True)

    if with_memory:
        import datetime

        today = datetime.date.today().strftime("%Y-%m-%d")
        (ws / "memory" / f"{today}.md").write_text(
            "# Memory\n\n**key-concept** and `code-snippet` used here.\n"
        )
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Architecture\n\n## Known Issues\n")

    fleet_config: dict[str, Any] = {
        "agents": [{"id": agent_id}],
        "bindings": [],
    }
    (home / "fleet.json").write_text(json.dumps(fleet_config))
    return home


def _setup_bare(tmp_path: Path) -> Path:
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    (home / "fleet.json").write_text(json.dumps(FLEET_EMPTY))
    return home


# ---------------------------------------------------------------------------
# TestCmdAdd
# ---------------------------------------------------------------------------


class TestCmdAdd:
    def _spec_file(self, tmp_path: Path, content: str, name: str = "spec.json") -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    def test_from_valid_json_provisions_agent(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        spec = self._spec_file(
            tmp_path,
            json.dumps(
                {
                    "id": "myshop",
                    "name": "My Shop",
                    "codebase": "/tmp/myshop",
                    "stack": "Node.js",
                    "description": "Test shop agent",
                }
            ),
        )
        rc, _out, _err = _run(["init", "--from", str(spec)], home)
        assert rc == 0
        # Check workspace created
        ws = home / "workspaces" / "projects" / "myshop"
        assert ws.is_dir()
        assert (ws / "SOUL.md").is_file()
        assert (ws / "AGENTS.md").is_file()
        assert (ws / "TOOLS.md").is_file()
        assert (ws / "HEARTBEAT.md").is_file()
        assert (ws / ".docket-meta.json").is_file()
        # Check meta content
        meta = json.loads((ws / ".docket-meta.json").read_text())
        assert meta["name"] == "My Shop"
        assert "type" not in meta  # agent-type concept removed — every agent is a repo

    def test_from_missing_file_exits_1(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["init", "--from", "/nonexistent/spec.json"], home)
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "spec file" in combined.lower()

    def test_init_uses_project_provisioning_path(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["init", "--from", "/nonexistent/spec.json"], home)
        assert rc == 1
        combined = out + err
        assert "spec file" in combined.lower()
        assert "no such command" not in combined.lower()

    def test_from_existing_agent_skips(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, "test-agent")
        spec = self._spec_file(
            tmp_path,
            json.dumps({"id": "test-agent", "name": "Test Agent"}),
        )
        rc, out, err = _run(["init", "--from", str(spec)], home)
        assert rc == 0
        combined = out + err
        assert "already exists" in combined.lower() or "skipping" in combined.lower()

    def test_init_without_tty_derives_project_from_cwd(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        repo = tmp_path / "my-project"
        repo.mkdir()

        rc, out, err = _run(["init"], home, cwd=repo)

        assert rc == 0, out + err
        assert (home / "workspaces" / "projects" / "my-project-lead").is_dir()
        assert (home / "workspaces" / "projects" / "my-project-implementer").is_dir()

    def test_first_init_bootstraps_global_foundation_and_project(self, tmp_path: Path) -> None:
        home = tmp_path / ".docket"
        repo = tmp_path / "fresh-project"
        repo.mkdir()
        env = {
            "DOCKET_LLM_BASE_URL": "http://127.0.0.1:9999/v1",
            "DOCKET_LLM_API_KEY": "recording-test-key",
        }

        rc, out, err = _run(["init"], home, cwd=repo, env=env)

        assert rc == 0, out + err
        fleet = json.loads((home / "fleet.json").read_text())
        ids = {agent["id"] for agent in fleet["agents"]}
        assert ids == {"fresh-project-lead", "fresh-project-implementer"}

    def test_add_extends_current_projects_existing_pod(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        repo = tmp_path / "current-project"
        repo.mkdir()
        rc, out, err = _run(["init"], home, cwd=repo)
        assert rc == 0, out + err

        rc, out, err = _run(["add", "reviewer"], home, cwd=repo, target=_pod.pod_app)

        assert rc == 0, out + err
        assert (home / "workspaces" / "projects" / "current-project-reviewer").is_dir()

    @pytest.mark.parametrize(
        "command", ["install", "add", "info", "delete", "maintain", "profile", "config"]
    )
    def test_redundant_bootstrap_commands_do_not_exist(self, tmp_path: Path, command: str) -> None:
        home = tmp_path / ".docket"

        rc, out, err = _run([command], home)

        assert rc == 2
        assert "No such command" in (out + err)
        assert not home.exists()

    def test_bare_docket_prints_only_a_compact_command_guide(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)

        rc, out, err = _run([], home)

        assert rc == 0, err
        assert "docket init" in out
        assert "docket status" in out
        assert "docket setup" in out
        assert "PROJECT AGENTS" not in out
        assert "ORG SPECIALISTS" not in out

    def test_status_resolves_the_current_project(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        repo = tmp_path / "current-project"
        repo.mkdir()
        rc, out, err = _run(["init"], home, cwd=repo)
        assert rc == 0, out + err

        rc, out, err = _run(["status"], home, cwd=repo)

        assert rc == 0, out + err
        assert "current-project" in out
        assert str(repo) in out
        assert "lead" in out
        assert "implementer" in out
        assert "dispatch history scoped by step" in out

    def test_status_all_summarizes_projects_not_agents(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        for name in ("project-one", "project-two"):
            repo = tmp_path / name
            repo.mkdir()
            rc, out, err = _run(["init"], home, cwd=repo)
            assert rc == 0, out + err

        rc, out, err = _run(["status", "--all", "--json"], home)

        assert rc == 0, out + err
        payload = json.loads(out)
        assert [project["id"] for project in payload["projects"]] == [
            "project-one",
            "project-two",
        ]
        assert all(project["memberCount"] == 2 for project in payload["projects"])

    def test_status_outside_a_project_is_actionable(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)

        rc, out, err = _run(["status"], home, cwd=tmp_path)

        assert rc == 1
        assert "docket init" in (out + err)
        assert "--pod" in (out + err)

    def test_from_yaml_without_pyyaml_gives_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _setup_bare(tmp_path)
        spec = tmp_path / "spec.yaml"
        spec.write_text("id: myagent\nname: My Agent\n")
        monkeypatch.setitem(sys.modules, "yaml", None)

        rc, out, err = _run(["init", "--from", str(spec)], home)
        assert rc == 1
        combined = out + err
        assert (
            "pyyaml" in combined.lower()
            or "yaml" in combined.lower()
            or "install" in combined.lower()
        )

    def test_from_list_of_agents(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        spec = self._spec_file(
            tmp_path,
            json.dumps(
                [
                    {"id": "agent-a", "name": "Agent A", "description": "First"},
                    {"id": "agent-b", "name": "Agent B", "description": "Second"},
                ]
            ),
        )
        rc, _out, _err = _run(["init", "--from", str(spec)], home)
        assert rc == 0
        assert (home / "workspaces" / "projects" / "agent-a").is_dir()
        assert (home / "workspaces" / "projects" / "agent-b").is_dir()


# ---------------------------------------------------------------------------
# Confirm new commands are no longer exit 127
# ---------------------------------------------------------------------------


def test_auth_context_maintain_keys_add_not_exit_127(tmp_path: Path) -> None:
    """These commands must not fall through to an unported stub (exit 127)."""
    home = _setup_bare(tmp_path)
    for cmd in [["setup", "model"]]:
        rc, _, _ = _run(cmd, home)
        assert rc != 127, f"docket {' '.join(cmd)} still exits 127"
