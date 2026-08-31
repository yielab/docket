"""profile, scope, models — writer commands.

All tests run `python -m docket` as a subprocess with DOCKET_HOME overridden
so tests are hermetic and never touch the real ~/.docket.
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


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DOCKET_HOME": str(oc_dir),
    }


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    oc_dir = tmp_path / ".docket"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
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

    def test_profile_pin_updates_meta_only(self, tmp_path: Path) -> None:
        """Model lives in .docket-meta.json only -- the fleet registry never
        tracks per-agent model (see core/fleet.py)."""
        oc_dir = _setup_agent(tmp_path)
        _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["model"] == "anthropic/claude-opus-4-6"

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
        (oc_dir / "fleet.json").write_text(
            json.dumps(
                {
                    "agents": [],
                    "bindings": [],
                    "providers": {
                        "openai": {
                            "baseUrl": "http://127.0.0.1:9999/v1",
                            "apiKey": "local",
                            "models": [{"id": "gpt-4.1-mini"}],
                        }
                    },
                }
            )
        )
        rc, _out, err = _run(["models", "preset", "openai"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        # strong roles get gpt-4.1-mini (standard for openai)
        assert reg["roles"]["programmer"] == "openai/gpt-4.1-mini"

    @pytest.mark.parametrize("preset", ["anthropic", "openai", "google", "local"])
    def test_preset_without_required_registered_endpoint_fails_without_writing(
        self, tmp_path: Path, preset: str
    ) -> None:
        oc_dir = _setup_agent(tmp_path)

        rc, out, err = _run(["models", "preset", preset], oc_dir)

        assert rc == 1
        assert not (oc_dir / "docket-models.json").exists()
        assert "registered OpenAI-compatible endpoint" in out + err
        assert "docket models provider add" in out + err

    def test_local_preset_selects_the_exact_registered_model(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        (oc_dir / "fleet.json").write_text(
            json.dumps(
                {
                    "agents": [],
                    "bindings": [],
                    "providers": {
                        "local": {
                            "baseUrl": "http://127.0.0.1:8081/v1",
                            "apiKey": "local",
                            "models": [
                                {
                                    "id": "qwen-live-id",
                                    "contextWindow": 16384,
                                    "maxTokens": 8192,
                                }
                            ],
                        }
                    },
                }
            )
        )

        rc, out, err = _run(["models", "preset", "local"], oc_dir)

        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["default"] == "local/qwen-live-id"
        assert set(reg["roles"].values()) == {"local/qwen-live-id"}
        assert "local/qwen-live-id" in out
        assert "Registered local endpoint selected; no API key needed." in out

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


# ---------------------------------------------------------------------------
# stub list confirms profile/scope/models no longer exit 127
# ---------------------------------------------------------------------------


class TestM4CommandsPortedFromStubs:
    @pytest.mark.parametrize("cmd", [["profile", "ghost"], ["scope", "ghost"], ["models"]])
    def test_does_not_exit_127(self, cmd: list[str], tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _ = _run(cmd, oc_dir)
        assert rc != 127, f"`docket {' '.join(cmd)}` still exits 127 (not ported)"
