"""The workstation bootstrap provisions no shared agent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _install, app
from docket.core import fleet as _fleet
from docket.core import secrets as _secrets

SUBJECT = "docket.cli._install"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
    root = tmp_path / ".docket"
    root.mkdir(parents=True)
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (root / "fleet.json").chmod(0o600)
    repoint_docket_home(monkeypatch, root)
    _secrets.save_secrets({"ANTHROPIC_API_KEY": "fake-anthropic-credential-1234"})
    return root


def test_first_init_creates_no_shared_workspace(home: Path) -> None:
    assert _install.bootstrap_workstation(assume_yes=True, continuing_to_project=True) == 0

    workspaces = home / "workspaces"
    assert sorted(p.name for p in workspaces.iterdir()) == ["projects"]
    assert list((workspaces / "projects").iterdir()) == []
    assert _fleet.list_agents() == []


def test_init_rejects_the_removed_portfolio_option(home: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--portfolio"])

    assert result.exit_code == 2
    assert not (home / "workspaces" / "portfolio-manager").exists()
