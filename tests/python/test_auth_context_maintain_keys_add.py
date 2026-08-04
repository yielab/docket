"""CLI tests: auth, context, maintain, keys, add.

All tests run `python -m docket` as a subprocess with DOCKET_HOME overridden.
Agent registration is seeded via fleet.json.
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

FLEET_EMPTY: dict[str, Any] = {"agents": [], "bindings": []}

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "Test Agent",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/tmp/testcodebase",
    "sessionKey": "agent:test-agent:default",
    "projectKey": "default",
    "description": "A test agent",
    "templateVersion": 1,
}


def _make_env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DOCKET_HOME": str(home),
    }


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
# TestCmdAuth
# ---------------------------------------------------------------------------


class TestCmdAuth:
    def test_status_no_profiles_file(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["auth"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "no provider api keys stored" in combined.lower()

    def test_unknown_subcommand_exits_1(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["auth", "foobar"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert "unknown" in combined.lower() or "usage" in combined.lower() or "foobar" in combined

    def test_login_reports_no_docket_native_flow(self, tmp_path: Path) -> None:
        # There is no daemon to shell out to, so `docket auth login` cannot
        # degrade to a "binary not found" error -- it must say plainly that
        # no docket-native replacement exists (see cli/_keys.py's run_auth /
        # _AUTH_GONE_MESSAGE).
        home = _setup_bare(tmp_path)
        env = {**_make_env(home), "PATH": "/nonexistent"}
        rc, out, err = _run(["auth", "login"], env)
        assert rc == 1
        combined = out + err
        assert "no docket-native provider-auth flow exists" in combined.lower()
        assert "docket keys add" in combined.lower()


# ---------------------------------------------------------------------------
# TestCmdContext
# ---------------------------------------------------------------------------


class TestCmdContext:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["context", "nonexistent-agent"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "nonexistent-agent" in combined

    def test_show_exits_0_and_shows_recent_activity(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_memory=True)
        rc, out, _err = _run(["context", "test-agent", "show"], _make_env(home))
        assert rc == 0
        assert "Recent Activity" in out

    def test_project_shows_metadata(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["context", "test-agent", "project"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert (
            "codebase" in combined.lower()
            or "model" in combined.lower()
            or "project" in combined.lower()
        )


# ---------------------------------------------------------------------------
# TestCmdMaintain
# ---------------------------------------------------------------------------


class TestCmdMaintain:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["maintain", "nonexistent-agent"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "nonexistent-agent" in combined

    def test_check_on_healthy_workspace(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["maintain", "test-agent", "check"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "healthy" in combined.lower() or "ok" in combined.lower()

    def test_clean_non_tty_cancelled(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["maintain", "test-agent", "clean"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "cancelled" in combined.lower() or "non-interactive" in combined.lower()

    def test_reset_non_tty_cancelled(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["maintain", "test-agent", "reset"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "cancelled" in combined.lower() or "non-interactive" in combined.lower()

    def test_sessions_no_sessions_dir(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["maintain", "test-agent", "sessions"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "no session storage found" in combined.lower()

    def test_rebuild_non_tty_aborts(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        _rc, out, err = _run(["maintain", "test-agent", "rebuild"], _make_env(home))
        # Should either exit 0 (with cancel message) or 1
        combined = out + err
        assert "confirmation failed" in combined.lower() or "aborted" in combined.lower()

    def test_distill_hermetic_no_daemon_fails_closed(self, tmp_path: Path) -> None:
        """No provider credentials configured -> the driver call fails ->
        nothing is deleted.

        Fail-closed distillation, exercised against the real production
        driver (no `FakeDriver` injection anywhere in this test) -- proof the
        guarantee holds against a real failure, not just a mocked stand-in.
        The fake-driven success/failure matrix lives in
        test_memory_distillation.py and test_maintain_distill_cli.py.
        """
        import datetime

        home = _setup_agent(tmp_path, with_memory=True)
        today = datetime.date.today().strftime("%Y-%m-%d")
        ws = home / "workspaces" / "projects" / "test-agent"
        log_path = ws / "memory" / f"{today}.md"
        assert log_path.is_file()

        env = {**_make_env(home), "PATH": "/nonexistent"}
        rc, out, err = _run(["maintain", "test-agent", "distill"], env)

        assert rc == 1
        combined = (out + err).lower()
        assert "fail" in combined
        # Fail closed: the log is neither deleted nor archived, and
        # MEMORY.md was never touched.
        assert log_path.is_file()
        assert not (ws / "memory" / ".distilled").exists()
        assert "distilled" not in (ws / "MEMORY.md").read_text(encoding="utf-8").lower()

    def test_distill_subcommand_listed_in_unknown_mode_message(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path)
        rc, out, err = _run(["maintain", "test-agent", "bogus"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert "distill" in combined.lower()


# ---------------------------------------------------------------------------
# TestCmdKeys
# ---------------------------------------------------------------------------


class TestCmdKeys:
    def _write_secrets(self, oc_dir: Path, data: dict[str, str]) -> None:
        path = oc_dir / "secrets.json"
        path.write_text(json.dumps(data, indent=2))
        path.chmod(0o600)

    def test_list_with_no_secrets(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["keys", "list"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert (
            "no api keys" in combined.lower()
            or "no keys" in combined.lower()
            or "stored" in combined.lower()
        )

    def test_list_with_secrets_shows_masked(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        self._write_secrets(
            home, {"ANTHROPIC_API_KEY": "sk-ant-api03-ABC123456789abcdefghijklmnopqrstuvwxyz"}
        )
        rc, out, _err = _run(["keys", "list"], _make_env(home))
        assert rc == 0
        assert "ANTHROPIC_API_KEY" in out
        # Should show masked value (not the full key)
        assert "sk-ant-api03-ABC123456789" not in out  # shouldn't show full
        assert "****" in out or "sk-a" in out  # should show masked or prefix

    def test_add_requires_name(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["keys", "add"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert (
            "usage" in combined.lower()
            or "key_name" in combined.lower()
            or "required" in combined.lower()
        )

    def test_validate_with_valid_key(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        # Write a valid-format key
        self._write_secrets(
            home, {"ANTHROPIC_API_KEY": "sk-ant-valid-key-abcdefghijklmnopqrstuvwxyz0123456"}
        )
        rc, out, err = _run(["keys", "validate", "ANTHROPIC_API_KEY"], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "✓" in combined or "valid" in combined.lower() or "ok" in combined.lower()

    def test_validate_with_invalid_key_format(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        # Write an invalid key (wrong prefix)
        self._write_secrets(home, {"ANTHROPIC_API_KEY": "wrong-prefix-key"})
        rc, out, err = _run(["keys", "validate", "ANTHROPIC_API_KEY"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert (
            "⚠" in combined
            or "should start" in combined
            or "invalid" in combined.lower()
            or "prefix" in combined.lower()
        )

    def test_export_prints_export_statements(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        self._write_secrets(home, {"MY_CUSTOM_KEY": "abc123"})
        rc, out, _err = _run(["keys", "export"], _make_env(home))
        assert rc == 0
        assert "export MY_CUSTOM_KEY=" in out
        assert "abc123" in out


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
        rc, _out, _err = _run(["add", "--from", str(spec)], _make_env(home))
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
        rc, out, err = _run(["add", "--from", "/nonexistent/spec.json"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "spec file" in combined.lower()

    def test_from_existing_agent_skips(self, tmp_path: Path) -> None:
        home = _setup_agent(tmp_path, "test-agent")
        spec = self._spec_file(
            tmp_path,
            json.dumps({"id": "test-agent", "name": "Test Agent"}),
        )
        rc, out, err = _run(["add", "--from", str(spec)], _make_env(home))
        assert rc == 0
        combined = out + err
        assert "already exists" in combined.lower() or "skipping" in combined.lower()

    def test_interactive_non_tty_exits_1(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        rc, out, err = _run(["add"], _make_env(home))
        assert rc == 1
        combined = out + err
        assert (
            "tty" in combined.lower()
            or "interactive" in combined.lower()
            or "requires" in combined.lower()
        )

    def test_from_yaml_without_pyyaml_gives_error(self, tmp_path: Path) -> None:
        home = _setup_bare(tmp_path)
        spec = tmp_path / "spec.yaml"
        spec.write_text("id: myagent\nname: My Agent\n")

        # Try importing yaml — if PyYAML is installed this test won't test the error path
        try:
            import yaml  # noqa: F401

            pytest.skip("PyYAML installed; cannot test missing-pyyaml error path")
        except ImportError:
            pass

        rc, out, err = _run(["add", "--from", str(spec)], _make_env(home))
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
        rc, _out, _err = _run(["add", "--from", str(spec)], _make_env(home))
        assert rc == 0
        assert (home / "workspaces" / "projects" / "agent-a").is_dir()
        assert (home / "workspaces" / "projects" / "agent-b").is_dir()


# ---------------------------------------------------------------------------
# Confirm new commands are no longer exit 127
# ---------------------------------------------------------------------------


def test_auth_context_maintain_keys_add_not_exit_127(tmp_path: Path) -> None:
    """These commands must not fall through to an unported stub (exit 127)."""
    home = _setup_bare(tmp_path)
    env = _make_env(home)
    for cmd in [["auth"], ["keys", "list"]]:
        rc, _, _ = _run(cmd, env)
        assert rc != 127, f"docket {' '.join(cmd)} still exits 127"
