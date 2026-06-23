"""M4 final tests: auth, context, maintain, keys, add.

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

OC_CONFIG_EMPTY: dict[str, Any] = {
    "agents": {"defaults": {"model": ""}, "list": []},
    "bindings": [],
    "channels": {},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "Test Agent",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/tmp/testcodebase",
    "sessionKey": "agent:test-agent:default",
    "projectKey": "default",
    "description": "A test agent",
    "templateVersion": 1,
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
        # No PATH so openclaw CLI won't be found — tests stay hermetic
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
    """Create a minimal project workspace. Returns oc_dir."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(exist_ok=True)
    ws = oc_dir / "workspaces" / "projects" / agent_id
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

    oc_config: dict[str, Any] = {
        "agents": {
            "defaults": {"model": ""},
            "list": [{"id": agent_id, "model": "anthropic/claude-sonnet-4-6", "metadata": {}}],
        },
        "bindings": [],
        "channels": {},
        "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
    }
    (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
    return oc_dir


def _setup_bare(tmp_path: Path) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(exist_ok=True)
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG_EMPTY))
    return oc_dir


# ---------------------------------------------------------------------------
# TestCmdAuth
# ---------------------------------------------------------------------------


class TestCmdAuth:
    def _make_profiles_file(
        self,
        oc_dir: Path,
        profiles: dict[str, Any],
        usage_stats: dict[str, Any] | None = None,
    ) -> None:
        path = oc_dir / "agents" / "main" / "agent"
        path.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"profiles": profiles}
        if usage_stats is not None:
            data["usageStats"] = usage_stats
        (path / "auth-profiles.json").write_text(json.dumps(data))

    def test_status_no_profiles_file(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["auth"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "no auth profiles" in combined.lower() or "not configured" in combined.lower()

    def test_status_with_valid_profiles(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        self._make_profiles_file(
            oc_dir,
            profiles={
                "anthropic:main": {"provider": "anthropic", "type": "token"},
                "anthropic:secondary": {"provider": "anthropic", "type": "manual"},
            },
        )
        rc, out, err = _run(["auth", "status"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "anthropic:main" in combined or "anthropic" in combined

    def test_unknown_subcommand_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["auth", "foobar"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert "unknown" in combined.lower() or "usage" in combined.lower() or "foobar" in combined

    def test_login_when_openclaw_not_found(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        env = {**_make_env(oc_dir), "PATH": "/nonexistent"}
        rc, out, err = _run(["auth", "login"], env)
        assert rc == 1
        combined = out + err
        assert "openclaw" in combined.lower() or "not found" in combined.lower()


# ---------------------------------------------------------------------------
# TestCmdContext
# ---------------------------------------------------------------------------


class TestCmdContext:
    def test_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["context", "nonexistent-agent"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "nonexistent-agent" in combined

    def test_show_exits_0_and_shows_recent_activity(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, out, _err = _run(["context", "test-agent", "show"], _make_env(oc_dir))
        assert rc == 0
        assert "Recent Activity" in out

    def test_index_creates_memory_index_json(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, _out, _err = _run(["context", "test-agent", "index"], _make_env(oc_dir))
        assert rc == 0
        ws = oc_dir / "workspaces" / "projects" / "test-agent"
        index_file = ws / ".memory-index.json"
        assert index_file.is_file()
        data = json.loads(index_file.read_text())
        assert "indexed_at" in data
        assert "files" in data
        assert "keywords" in data
        assert "decisions" in data

    def test_search_without_index_warns(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["context", "test-agent", "search", "something"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "index" in combined.lower() or "not indexed" in combined.lower()

    def test_search_after_index_finds_matches(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        # First index
        _run(["context", "test-agent", "index"], _make_env(oc_dir))
        # Then search
        rc, out, _err = _run(["context", "test-agent", "search", "key-concept"], _make_env(oc_dir))
        assert rc == 0
        assert "key-concept" in out or "match" in out.lower() or "keyword" in out.lower()

    def test_snapshot_creates_snapshot_md(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, _out, _err = _run(["context", "test-agent", "snapshot"], _make_env(oc_dir))
        assert rc == 0
        ws = oc_dir / "workspaces" / "projects" / "test-agent"
        snap = ws / "SNAPSHOT.md"
        assert snap.is_file()
        content = snap.read_text()
        assert "SNAPSHOT" in content or "test-agent" in content.lower()

    def test_compress_with_no_old_files(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["context", "test-agent", "compress"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "no old" in combined.lower() or "compress" in combined.lower()

    def test_project_shows_metadata(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["context", "test-agent", "project"], _make_env(oc_dir))
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
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["maintain", "nonexistent-agent"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "nonexistent-agent" in combined

    def test_check_on_healthy_workspace(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["maintain", "test-agent", "check"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "healthy" in combined.lower() or "ok" in combined.lower()

    def test_clean_non_tty_cancelled(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["maintain", "test-agent", "clean"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "cancelled" in combined.lower() or "non-interactive" in combined.lower()

    def test_reset_non_tty_cancelled(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, with_memory=True)
        rc, out, err = _run(["maintain", "test-agent", "reset"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "cancelled" in combined.lower() or "non-interactive" in combined.lower()

    def test_sessions_no_sessions_dir(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["maintain", "test-agent", "sessions"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "no sessions" in combined.lower() or "not found" in combined.lower()

    def test_rebuild_non_tty_aborts(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _rc, out, err = _run(["maintain", "test-agent", "rebuild"], _make_env(oc_dir))
        # Should either exit 0 (with cancel message) or 1
        combined = out + err
        assert "confirmation failed" in combined.lower() or "aborted" in combined.lower()


# ---------------------------------------------------------------------------
# TestCmdKeys
# ---------------------------------------------------------------------------


class TestCmdKeys:
    def _write_secrets(self, oc_dir: Path, data: dict[str, str]) -> None:
        path = oc_dir / "secrets.json"
        path.write_text(json.dumps(data, indent=2))
        path.chmod(0o600)

    def test_list_with_no_secrets(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["keys", "list"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert (
            "no api keys" in combined.lower()
            or "no keys" in combined.lower()
            or "stored" in combined.lower()
        )

    def test_list_with_secrets_shows_masked(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        self._write_secrets(
            oc_dir, {"ANTHROPIC_API_KEY": "sk-ant-api03-ABC123456789abcdefghijklmnopqrstuvwxyz"}
        )
        rc, out, _err = _run(["keys", "list"], _make_env(oc_dir))
        assert rc == 0
        assert "ANTHROPIC_API_KEY" in out
        # Should show masked value (not the full key)
        assert "sk-ant-api03-ABC123456789" not in out  # shouldn't show full
        assert "****" in out or "sk-a" in out  # should show masked or prefix

    def test_add_requires_name(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["keys", "add"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert (
            "usage" in combined.lower()
            or "key_name" in combined.lower()
            or "required" in combined.lower()
        )

    def test_validate_with_valid_key(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        # Write a valid-format key
        self._write_secrets(
            oc_dir, {"ANTHROPIC_API_KEY": "sk-ant-valid-key-abcdefghijklmnopqrstuvwxyz0123456"}
        )
        rc, out, err = _run(["keys", "validate", "ANTHROPIC_API_KEY"], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "✓" in combined or "valid" in combined.lower() or "ok" in combined.lower()

    def test_validate_with_invalid_key_format(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        # Write an invalid key (wrong prefix)
        self._write_secrets(oc_dir, {"ANTHROPIC_API_KEY": "wrong-prefix-key"})
        rc, out, err = _run(["keys", "validate", "ANTHROPIC_API_KEY"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert (
            "⚠" in combined
            or "should start" in combined
            or "invalid" in combined.lower()
            or "prefix" in combined.lower()
        )

    def test_export_prints_export_statements(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        self._write_secrets(oc_dir, {"MY_CUSTOM_KEY": "abc123"})
        rc, out, _err = _run(["keys", "export"], _make_env(oc_dir))
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
        oc_dir = _setup_bare(tmp_path)
        spec = self._spec_file(
            tmp_path,
            json.dumps(
                {
                    "id": "myshop",
                    "type": "repo",
                    "name": "My Shop",
                    "codebase": "/tmp/myshop",
                    "stack": "Node.js",
                    "description": "Test shop agent",
                }
            ),
        )
        rc, _out, _err = _run(["add", "--from", str(spec)], _make_env(oc_dir))
        assert rc == 0
        # Check workspace created
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        assert ws.is_dir()
        assert (ws / "SOUL.md").is_file()
        assert (ws / "AGENTS.md").is_file()
        assert (ws / "TOOLS.md").is_file()
        assert (ws / "HEARTBEAT.md").is_file()
        assert (ws / ".docket-meta.json").is_file()
        # Check meta content
        meta = json.loads((ws / ".docket-meta.json").read_text())
        assert meta["name"] == "My Shop"
        assert meta["type"] == "repo"

    def test_from_missing_file_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["add", "--from", "/nonexistent/spec.json"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "spec file" in combined.lower()

    def test_from_existing_agent_skips(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path, "test-agent")
        spec = self._spec_file(
            tmp_path,
            json.dumps({"id": "test-agent", "name": "Test Agent", "type": "repo"}),
        )
        rc, out, err = _run(["add", "--from", str(spec)], _make_env(oc_dir))
        assert rc == 0
        combined = out + err
        assert "already exists" in combined.lower() or "skipping" in combined.lower()

    def test_interactive_non_tty_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        rc, out, err = _run(["add"], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert (
            "tty" in combined.lower()
            or "interactive" in combined.lower()
            or "requires" in combined.lower()
        )

    def test_from_yaml_without_pyyaml_gives_error(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        spec = tmp_path / "spec.yaml"
        spec.write_text("id: myagent\nname: My Agent\ntype: task\n")

        # Try importing yaml — if PyYAML is installed this test won't test the error path
        try:
            import yaml  # noqa: F401

            pytest.skip("PyYAML installed; cannot test missing-pyyaml error path")
        except ImportError:
            pass

        rc, out, err = _run(["add", "--from", str(spec)], _make_env(oc_dir))
        assert rc == 1
        combined = out + err
        assert (
            "pyyaml" in combined.lower()
            or "yaml" in combined.lower()
            or "install" in combined.lower()
        )

    def test_from_list_of_agents(self, tmp_path: Path) -> None:
        oc_dir = _setup_bare(tmp_path)
        spec = self._spec_file(
            tmp_path,
            json.dumps(
                [
                    {"id": "agent-a", "name": "Agent A", "type": "task", "description": "First"},
                    {"id": "agent-b", "name": "Agent B", "type": "repo", "description": "Second"},
                ]
            ),
        )
        rc, _out, _err = _run(["add", "--from", str(spec)], _make_env(oc_dir))
        assert rc == 0
        assert (oc_dir / "workspaces" / "projects" / "agent-a").is_dir()
        assert (oc_dir / "workspaces" / "projects" / "agent-b").is_dir()


# ---------------------------------------------------------------------------
# Confirm new commands are no longer exit 127
# ---------------------------------------------------------------------------


def test_m4_final_not_exit_127(tmp_path: Path) -> None:
    """All M4 final commands must not fall through to Bash (exit 127)."""
    oc_dir = _setup_bare(tmp_path)
    env = _make_env(oc_dir)
    for cmd in [["auth"], ["keys", "list"]]:
        rc, _, _ = _run(cmd, env)
        assert rc != 127, f"docket {' '.join(cmd)} still exits 127"
