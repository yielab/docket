"""M4 wave-1 tests: profile, scope, models — writer commands.

All tests run `python -m docket` as a subprocess with OPENCLAW_DIR overridden
and DOCKET_NO_RESTART=1 so no systemctl calls are made.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
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


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))
    return oc_dir


def _run(args: list[str], oc_dir: Path) -> tuple[int, str, str]:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        env=_make_env(oc_dir),
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# docket profile
# ---------------------------------------------------------------------------


class TestCmdProfile:
    def test_profile_show_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["profile", "myshop"], oc_dir)
        assert rc == 0
        assert "myshop" in out
        assert "claude-sonnet-4-6" in out

    def test_profile_show_contains_role(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["profile", "myshop"], oc_dir)
        assert rc == 0
        assert "repo" in out  # role for type=repo project

    def test_profile_show_contains_source(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["profile", "myshop"], oc_dir)
        assert rc == 0
        assert "policy" in out

    def test_profile_pin_model(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        assert "pinned" in out.lower() or "pinned" in err.lower() or "claude-opus" in out

        # Verify meta was updated
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["model"] == "anthropic/claude-opus-4-6"
        assert meta["modelSource"] == "pinned"

    def test_profile_pin_also_updates_openclaw(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        agent = next(a for a in oc["agents"]["list"] if a["id"] == "myshop")
        assert agent["model"] == "anthropic/claude-opus-4-6"

    def test_profile_default_sets_policy(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # First pin it
        _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        # Then reset to policy
        rc, _out, _ = _run(["profile", "myshop", "default"], oc_dir)
        assert rc == 0
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["modelSource"] == "policy"

    def test_profile_noop_when_unchanged(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # Already on policy/sonnet — setting default again is a no-op
        rc, out, err = _run(["profile", "myshop", "default"], oc_dir)
        assert rc == 0
        combined = out + err
        assert "No change" in combined

    def test_profile_invalid_model_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["profile", "myshop", "not-a-valid-model"], oc_dir)
        assert rc == 1
        assert "Invalid" in err

    def test_profile_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["profile", "no-such-agent"], oc_dir)
        assert rc == 1
        assert "not found" in err

    def test_profile_budget_set(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, _ = _run(["profile", "myshop", "--budget", "5.00"], oc_dir)
        assert rc == 0
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["budgetUsd"] == "5.00"

    def test_profile_budget_zero_removes_cap(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["profile", "myshop", "--budget", "5.00"], oc_dir)
        rc, out, _ = _run(["profile", "myshop", "--budget", "0"], oc_dir)
        assert rc == 0
        assert "removed" in out

    def test_profile_budget_invalid_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["profile", "myshop", "--budget", "notanumber"], oc_dir)
        assert rc == 1
        assert "Invalid" in err

    def test_profile_budget_negative_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["profile", "myshop", "--budget", "-1"], oc_dir)
        assert rc == 1

    def test_profile_alias_resolves(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["profile", "myshop", "anthropic/claude-sonnet-4"], oc_dir)
        # Should warn about alias, not hard-fail
        assert rc == 0 or "alias" in err

    def test_profile_dry_run_gateway(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        assert rc == 0
        assert "[dry-run]" in out  # DOCKET_NO_RESTART=1


# ---------------------------------------------------------------------------
# docket scope
# ---------------------------------------------------------------------------


class TestCmdScope:
    def test_scope_show_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["scope", "myshop"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        assert "default" in out
        assert "agent:myshop:default" in out

    def test_scope_show_explicit_subcommand(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["scope", "myshop", "show"], oc_dir)
        assert rc == 0
        assert "agent:myshop:default" in out

    def test_scope_set_updates_meta(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["scope", "myshop", "set", "billing"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["projectKey"] == "billing"
        assert meta["sessionKey"] == "agent:myshop:billing"

    def test_scope_set_does_not_write_metadata_to_openclaw(self, tmp_path: Path) -> None:
        # sessionKey lives in .docket-meta.json (asserted above); it is NEVER
        # written into openclaw.json — the daemon rejects a `metadata` key on an
        # agent entry, so the ACL strips it (any seed metadata is dropped too).
        oc_dir = _setup_agent(tmp_path)
        _run(["scope", "myshop", "set", "billing"], oc_dir)
        oc = json.loads((oc_dir / "openclaw.json").read_text())
        agent = next(a for a in oc["agents"]["list"] if a["id"] == "myshop")
        assert "metadata" not in agent

    def test_scope_set_without_key_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["scope", "myshop", "set"], oc_dir)
        assert rc == 1
        assert "required" in err.lower() or "key" in err.lower()

    def test_scope_reset_restores_default(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["scope", "myshop", "set", "billing"], oc_dir)
        rc, _, _ = _run(["scope", "myshop", "reset"], oc_dir)
        assert rc == 0
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["projectKey"] == "default"
        assert meta["sessionKey"] == "agent:myshop:default"

    def test_scope_unknown_action_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["scope", "myshop", "fly"], oc_dir)
        assert rc == 1
        assert "Unknown" in err

    def test_scope_unknown_agent_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["scope", "ghost", "show"], oc_dir)
        assert rc == 1
        assert "not found" in err

    def test_scope_set_dry_run_gateway(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["scope", "myshop", "set", "work"], oc_dir)
        assert rc == 0
        assert "[dry-run]" in out


# ---------------------------------------------------------------------------
# docket models
# ---------------------------------------------------------------------------


class TestCmdModels:
    def test_models_list_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["models"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        assert "repo" in out
        assert "manager" in out

    def test_models_list_shows_all_roles(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["models"], oc_dir)
        assert rc == 0
        for role in (
            "manager",
            "programmer",
            "reviewer",
            "tester",
            "knowledge",
            "security",
            "repo",
        ):
            assert role in out

    def test_models_list_shows_pricing(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["models"], oc_dir)
        assert rc == 0
        assert "$" in out  # pricing column

    def test_models_set_role(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["roles"]["programmer"] == "anthropic/claude-haiku-4-5"

    def test_models_set_default(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _ = _run(["models", "set", "default", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 0
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["default"] == "anthropic/claude-haiku-4-5"

    def test_models_set_reapplies_policy(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # myshop type=repo, role=repo, source=policy
        _run(["models", "set", "repo", "anthropic/claude-haiku-4-5"], oc_dir)
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["model"] == "anthropic/claude-haiku-4-5"

    def test_models_set_unknown_role_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["models", "set", "unicorn", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 1
        assert "Unknown" in err

    def test_models_set_invalid_model_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["models", "set", "programmer", "notamodel"], oc_dir)
        assert rc == 1
        assert "Invalid" in err

    def test_models_set_missing_args_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["models", "set", "programmer"], oc_dir)
        assert rc == 1

    def test_models_preset_list_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["models", "preset"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        for p in ("anthropic", "openai", "google", "openrouter-free", "openrouter"):
            assert p in out

    def test_models_preset_apply(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "openai"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        # strong roles get gpt-4.1-mini (standard for openai)
        assert reg["roles"]["programmer"] == "openai/gpt-4.1-mini"

    def test_models_preset_unknown_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["models", "preset", "notapreset"], oc_dir)
        assert rc == 1
        assert "Unknown" in err

    def test_models_unknown_subcommand_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["models", "fly"], oc_dir)
        assert rc == 1
        assert "Unknown" in err

    def test_models_set_pinned_agent_not_touched(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # Pin myshop first
        _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        # Change the repo role policy
        _run(["models", "set", "repo", "anthropic/claude-haiku-4-5"], oc_dir)
        # Pinned agent should NOT have changed
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["model"] == "anthropic/claude-opus-4-6"

    def test_models_set_dry_run_gateway(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 0
        assert "[dry-run]" in out


# ---------------------------------------------------------------------------
# stub list confirms profile/scope/models no longer exit 127
# ---------------------------------------------------------------------------


class TestM4CommandsPortedFromStubs:
    @pytest.mark.parametrize("cmd", [["profile", "ghost"], ["scope", "ghost"], ["models"]])
    def test_does_not_exit_127(self, cmd: list[str], tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _ = _run(cmd, oc_dir)
        assert rc != 127, f"`docket {' '.join(cmd)}` still exits 127 (not ported)"
