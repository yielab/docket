"""First run: `init` no longer bootstraps the home; `setup` owns the steps and the readiness report.

Readiness is read from the stored credential, the registered provider and the role policy;
the baseline policies and the owner-only permissions are steps of `setup`, not of `init`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import docket.kernel.templates as _templates
from docket.governance import secrets as _secrets
from docket.interfaces.cli.commands import agents as _agents
from docket.interfaces.cli.commands import setup as _setup
from docket.kernel.home import Home, current_home, use_home
from docket.models import catalog as _prov
from docket.teams import model_selection as _models_policy

SUBJECT = "docket.interfaces.cli.commands.setup"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@contextmanager
def _seed_fresh(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    Home(home).config_dir.mkdir(parents=True)
    Home(home).state_dir.mkdir(parents=True)
    with use_home(Home(home)):
        yield home


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


def test_an_unresolved_default_is_missing_and_names_the_command(tmp_path: Path) -> None:
    with _seed_fresh(tmp_path):
        _secrets.save_secrets({})

        piece = _setup.readiness().endpoint

        assert piece.ok is False
        assert "ANTHROPIC_API_KEY is required for the resolved endpoint" in piece.reason
        assert piece.command.startswith("docket setup provider add")


def test_a_direct_anthropic_key_is_sufficient_endpoint_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _seed_fresh(tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-var")

        piece = _setup.readiness().endpoint

        assert piece.ok is True
        assert piece.command == ""


def test_a_registered_local_endpoint_needs_no_api_key(tmp_path: Path) -> None:
    with _seed_fresh(tmp_path):
        _register_local("local", "http://127.0.0.1:8081/v1", "qwen-local")

        piece = _setup.readiness().endpoint

        assert piece.ok is True
        assert "local/qwen-local" in piece.reason


# ── the steps ───────────────────────────────────────────────────────────────────────


def test_step_security_hardens_world_readable_secrets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _seed_fresh(tmp_path) as home:
        secrets_file = Home(home).secrets_file
        secrets_file.write_text("{}")
        secrets_file.chmod(0o644)

        _setup.step_security()

        assert secrets_file.stat().st_mode & 0o777 == 0o600
        assert "Tightened permissions to 600" in capsys.readouterr().out


def test_step_policies_seeds_the_shipped_set_and_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _seed_fresh(tmp_path) as home:
        _setup.step_policies()
        first = capsys.readouterr().out
        _setup.step_policies()
        second = capsys.readouterr().out

        installed = {f.name for f in Home(home).policies_dir.glob("*.json")}
        assert installed == {f.name for f in _templates.POLICY_TEMPLATES_DIR.glob("*.json")}
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
    with _seed_fresh(tmp_path) as home:
        monkeypatch.delenv("DOCKET_NO_HINTS", raising=False)

        rc = _agents.run_init(_init_args(tmp_path))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No model endpoint yet" in captured.out
        assert "docket setup" in captured.err
        assert (Home(home).projects_dir / "demo-lead").is_dir()
        assert not Home(home).model_registry_file.exists()
        # The guardrail policies are installed by init itself (security-gates "Policy engine on
        # the live path" 1), not deferred to setup: a fresh home must not screen nothing.
        assert (Home(home).policies_dir / "prompt-injection.yaml").is_file()


def test_init_with_an_endpoint_does_not_mention_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _seed_fresh(tmp_path):
        _register_local("local", "http://127.0.0.1:8081/v1", "qwen-local")

        rc = _agents.run_init(_init_args(tmp_path))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No model endpoint yet" not in captured.out
        assert json.loads(Path(current_home().fleet_file).read_text())["agents"]
        assert os.path.isdir(current_home().projects_dir)
