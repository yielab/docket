"""First run: `init` no longer bootstraps the home; `setup` owns the steps and the readiness report.

Readiness is read from the stored credential, the registered provider and the role policy;
the baseline policies and the owner-only permissions are steps of `setup`, not of `init`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _agents, _setup
from docket.core import models_policy as _models_policy
from docket.core import provider as _prov
from docket.core import secrets as _secrets

SUBJECT = "docket.core"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _seed_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir(parents=True)
    repoint_docket_home(monkeypatch, home)
    return home


def _register_local(name: str, base_url: str, model_id: str) -> None:
    _prov.save_provider(
        _prov.ProviderSpec(
            name=name,
            baseUrl=base_url,
            auth=_prov.AuthSpec(type="none"),
            local=True,
            models=[_prov.ModelRow(id=model_id, contextWindow=16384, maxTokens=8192)],
        )
    )
    _models_policy.write_registry(
        {
            "default": f"{name}/{model_id}",
            **{f"role.{role}": f"{name}/{model_id}" for role in _models_policy.ALL_ROLES},
        }
    )


# ── readiness: the endpoint piece ───────────────────────────────────────────────────


def test_an_unresolved_default_is_missing_and_names_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _secrets.save_secrets({})

    piece = _setup.readiness().endpoint

    assert piece.ok is False
    assert "ANTHROPIC_API_KEY is required for the resolved endpoint" in piece.reason
    assert piece.command.startswith("docket setup provider add")


def test_a_direct_anthropic_key_is_sufficient_endpoint_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-var")

    piece = _setup.readiness().endpoint

    assert piece.ok is True
    assert piece.command == ""


def test_a_registered_local_endpoint_needs_no_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _register_local("local", "http://127.0.0.1:8081/v1", "qwen-local")

    piece = _setup.readiness().endpoint

    assert piece.ok is True
    assert "local/qwen-local" in piece.reason


# ── the steps ───────────────────────────────────────────────────────────────────────


def test_step_security_hardens_world_readable_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)
    secrets_file = home / "secrets.json"
    secrets_file.write_text("{}")
    secrets_file.chmod(0o644)

    _setup.step_security()

    assert secrets_file.stat().st_mode & 0o777 == 0o600
    assert "Tightened permissions to 600" in capsys.readouterr().out


def test_step_policies_seeds_the_shipped_set_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)

    _setup.step_policies()
    first = capsys.readouterr().out
    _setup.step_policies()
    second = capsys.readouterr().out

    installed = {f.name for f in (home / "policies").glob("*.json")}
    assert installed == {f.name for f in _cfg.policy_templates_dir().glob("*.json")}
    assert "Installed" in first
    assert "Installed" not in second


# ── init ────────────────────────────────────────────────────────────────────────────


def _init_args(tmp_path: Path) -> _agents.InitRequest:
    repo = tmp_path / "repo"
    repo.mkdir()
    return _agents.InitRequest(location=str(repo), name="demo")


def test_init_without_an_endpoint_builds_the_team_and_points_at_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)
    monkeypatch.delenv("DOCKET_NO_HINTS", raising=False)

    rc = _agents.run_init(_init_args(tmp_path))

    captured = capsys.readouterr()
    assert rc == 0
    assert "No model endpoint yet" in captured.out
    assert "docket setup" in captured.err
    assert (home / "workspaces" / "projects" / "demo-lead").is_dir()
    assert not (home / "docket-models.json").exists()
    assert not (home / "policies").exists()


def test_init_with_an_endpoint_does_not_mention_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _register_local("local", "http://127.0.0.1:8081/v1", "qwen-local")

    rc = _agents.run_init(_init_args(tmp_path))

    captured = capsys.readouterr()
    assert rc == 0
    assert "No model endpoint yet" not in captured.out
    assert json.loads(Path(_cfg.FLEET_FILE).read_text())["agents"]
    assert os.path.isdir(_cfg.PROJECTS_DIR)
