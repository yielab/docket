"""A task's processes never see docket's credentials.

Drives the real ``run_verify_cmd`` and the unjailed ``run_bash`` with credentials exported into
the host environment and a stored secret, then reads what the child process actually received.
See specs/functional/security-gates.spec.md, "Credentials in task processes".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.core import provider as _provider
from docket.core import secrets as _secrets
from docket.edges.adapters import system as _system
from docket.edges.adapters import toolbox as _toolbox

SUBJECT = "docket.edges.adapters.system"

# Host env is long enough to hit the output cap, so print only the names under test.
_ENV_CMD = "env | grep -E '^(OPENAI|DOCKET|TELEGRAM|MY_STORED|HARMLESS|PATH|CATALOG)'"


@pytest.fixture
def exported(monkeypatch: pytest.MonkeyPatch) -> None:
    _secrets.save_secrets({"MY_STORED_SECRET": "stored-value"})
    monkeypatch.setenv("MY_STORED_SECRET", "stored-value")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-canary")
    monkeypatch.setenv("DOCKET_LLM_API_KEY", "sk-override-canary")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-canary")
    monkeypatch.setenv("HARMLESS_VAR", "harmless-canary")


def _assert_scrubbed(out: str) -> None:
    for gone in ("sk-openai-canary", "sk-override-canary", "tg-canary", "stored-value"):
        assert gone not in out
    for name in ("OPENAI_API_KEY", "DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN", "MY_STORED_SECRET"):
        assert f"{name}=" not in out
    assert "harmless-canary" in out
    assert "PATH=" in out


def test_verify_cmd_env_has_no_credentials(exported: None, tmp_path: Path) -> None:
    ok, out = _system.run_verify_cmd(_ENV_CMD, str(tmp_path))
    assert ok
    _assert_scrubbed(out)


def test_verify_cmd_overlay_still_arrives(exported: None, tmp_path: Path) -> None:
    ok, out = _system.run_verify_cmd(_ENV_CMD, str(tmp_path), env={"DOCKET_TASK_ID": "t-1"})
    assert ok
    assert "DOCKET_TASK_ID=t-1" in out
    _assert_scrubbed(out)


def test_unjailed_bash_env_has_no_credentials(exported: None, tmp_path: Path) -> None:
    res = _toolbox.run_bash((tmp_path,), _ENV_CMD, env={"DOCKET_TASK_ID": "t-2"}, sandbox="off")
    _assert_scrubbed(res.content)
    assert "DOCKET_TASK_ID=t-2" in res.content


def test_catalog_declared_credential_is_stripped(
    exported: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = next(s for s in _provider.load_catalog().entries.values() if s.auth.credentials)
    monkeypatch.setenv(spec.auth.credentials[0], "catalog-canary")
    monkeypatch.setenv("CATALOG_CONTROL", "control-canary")
    ok, out = _system.run_verify_cmd(f"{_ENV_CMD}; env | grep catalog-canary; true", str(tmp_path))
    assert ok
    assert "catalog-canary" not in out
    assert "control-canary" in out


def test_reading_the_secret_store_does_not_create_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "absent-home"
    repoint_docket_home(monkeypatch, home)
    assert "PATH" in _system.task_environment()
    assert not home.exists()
