"""setup model — writer commands.

All tests invoke the CLI in-process via CliRunner, with every DOCKET_HOME-derived
config constant patched to a temp directory so tests are hermetic and never touch
the real ~/.docket.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import register_local_provider, repoint_docket_home
from typer.testing import CliRunner

from docket.cli import app as _app

SUBJECT = "docket.cli"

_runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
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
    with pytest.MonkeyPatch.context() as mp:
        repoint_docket_home(mp, oc_dir)
        result = _runner.invoke(_app, args)
    return result.exit_code, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# docket models
# ---------------------------------------------------------------------------


class TestCmdModels:
    def test_models_list_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["setup", "model"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        assert "implementer" in out
        assert "lead" in out

    def test_models_list_shows_all_roles(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["setup", "model"], oc_dir)
        assert rc == 0
        for role in (
            "lead",
            "implementer",
            "reviewer",
            "tester",
            "researcher",
            "analyst",
            "writer",
            "critic",
            "operator",
            "monitor",
        ):
            assert role in out

    def test_models_list_shows_pricing(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _ = _run(["setup", "model"], oc_dir)
        assert rc == 0
        assert "$" in out  # pricing column

    def test_models_set_role(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(
            ["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["roles"]["implementer"] == "anthropic/claude-haiku-4-5"

    def test_models_set_default(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _ = _run(["setup", "model", "set", "default", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 0
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["default"] == "anthropic/claude-haiku-4-5"

    def test_models_set_reapplies_policy(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        # myshop is a bare project agent: follows the implementer row, source=policy
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        meta = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert meta["model"] == "anthropic/claude-haiku-4-5"

    def test_models_set_unknown_role_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(
            ["setup", "model", "set", "unicorn", "anthropic/claude-haiku-4-5"], oc_dir
        )
        assert rc == 1
        assert "Unknown" in err

    def test_models_set_invalid_model_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["setup", "model", "set", "implementer", "notamodel"], oc_dir)
        assert rc == 1
        assert "Invalid" in err

    def test_models_set_missing_args_is_a_usage_error(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["setup", "model", "set", "implementer"], oc_dir)
        assert rc == 2

    def test_models_preset_list_exits_zero(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, err = _run(["setup", "model", "preset"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        for p in ("anthropic", "openai", "google", "openrouter-free", "openrouter"):
            assert p in out

    def test_models_preset_apply(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        (oc_dir / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        register_local_provider(oc_dir, "openai", [{"id": "gpt-4.1-mini"}])
        rc, _out, err = _run(["setup", "model", "preset", "openai"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        # strong roles get gpt-4.1-mini (standard for openai)
        assert reg["roles"]["implementer"] == "openai/gpt-4.1-mini"

    @pytest.mark.parametrize("preset", ["anthropic", "openai", "google", "local"])
    def test_preset_with_no_separate_registration_now_succeeds(
        self, tmp_path: Path, preset: str
    ) -> None:
        """anthropic/openai/google/local are built-in catalog documents, so applying one of
        these presets needs no separate `docket setup provider add` first (model-profiles
        spec, "Presets")."""
        oc_dir = _setup_agent(tmp_path)

        rc, out, err = _run(["setup", "model", "preset", preset], oc_dir)

        assert rc == 0, f"exit {rc}\nstderr: {err}"
        assert (oc_dir / "docket-models.json").exists()
        assert f"Preset {preset} applied" in out + err

    def test_local_preset_selects_the_exact_registered_model(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        (oc_dir / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        register_local_provider(
            oc_dir,
            "local",
            [{"id": "qwen-live-id", "contextWindow": 16384, "maxTokens": 8192}],
            base_url="http://127.0.0.1:8081/v1",
        )

        rc, out, err = _run(["setup", "model", "preset", "local"], oc_dir)

        assert rc == 0, f"exit {rc}\nstderr: {err}"
        reg = json.loads((oc_dir / "docket-models.json").read_text())
        assert reg["default"] == "local/qwen-live-id"
        assert set(reg["roles"].values()) == {"local/qwen-live-id"}
        assert "local/qwen-live-id" in out
        assert "Registered local endpoint selected; no API key needed." in out

    def test_models_preset_unknown_exits_1(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, err = _run(["setup", "model", "preset", "notapreset"], oc_dir)
        assert rc == 1
        assert "Unknown" in err

    def test_models_unknown_subcommand_is_a_usage_error(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["setup", "model", "fly"], oc_dir)
        assert rc == 2


# ---------------------------------------------------------------------------
# stub list confirms setup model no longer exits 127
# ---------------------------------------------------------------------------


class TestM4CommandsPortedFromStubs:
    @pytest.mark.parametrize("cmd", [["setup", "model"]])
    def test_does_not_exit_127(self, cmd: list[str], tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _ = _run(cmd, oc_dir)
        assert rc != 127, f"`docket {' '.join(cmd)}` still exits 127 (not ported)"
