"""The optional org Portfolio Manager (opt-in, single, never a pod member)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _install
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core import secrets as _secrets

_ORG_SPECIALISTS = ("manager", "knowledge", "security")
PM = "portfolio-manager"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint config modules at a temp DOCKET_HOME (mirrors test_install.py)."""
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "SITES_DIR", home / "Sites", raising=True)
    monkeypatch.setattr(_cfg, "LOG_DIR", home / "logs", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    # install also seeds guardrail policies (Step 9) — repoint
    # POLICIES_DIR too, or that step would touch the real ~/.docket/policies
    # on whatever machine runs this test.
    monkeypatch.setattr(_cfg, "POLICIES_DIR", home / "policies", raising=True)
    monkeypatch.setattr(_secrets, "SECRETS_FILE", home / "secrets.json", raising=True)
    monkeypatch.setattr(_secrets, "SECRETS_META_FILE", home / "secrets.meta.json", raising=True)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps({"agents": [], "bindings": []}))
    fleet_file.chmod(0o600)
    _point_at(home, monkeypatch)
    _secrets.save_secrets({"ANTHROPIC_API_KEY": "sk-ant-test-1234567890"})
    return home


def _ids(home: Path) -> set[str]:
    return {a.id for a in _fleet.list_agents()}


# ── config invariants ────────────────────────────────────────────────────────────


class TestConfig:
    def test_is_an_org_specialist_role(self) -> None:
        assert _cfg.is_specialist(PM)
        assert _cfg.role_scope(PM) == "org"

    def test_not_auto_installed_but_in_display_order(self) -> None:
        # Opt-in: never in the default install/missing-check order …
        assert PM not in _cfg.ORG_SPECIALIST_ORDER
        # … but present in the display/monitor order (shown only when it exists).
        assert PM in _cfg.ORG_DISPLAY_ORDER

    def test_is_never_a_pod_member(self) -> None:
        # pod_of returns None (its suffix 'manager' isn't a pod role), and it is
        # excluded from every project's member roster.
        assert _pod.pod_of(PM) is None
        assert _pod.members_of([PM, "demo-lead", "demo-implementer"], "portfolio") == []


# ── provisioning ─────────────────────────────────────────────────────────────────


class TestProvisioning:
    def test_flag_off_does_not_create_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        rc = _install.run_install(want_gates=False, assume_yes=True, want_portfolio=False)
        assert rc == 0
        assert _ids(home) == set(_ORG_SPECIALISTS)
        assert PM not in _ids(home)
        assert not (home / "workspaces" / PM).exists()

    def test_flag_on_creates_one_org_scoped_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        rc = _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)
        assert rc == 0
        assert PM in _ids(home)
        # Pods still function: the org specialists are all there too.
        assert set(_ORG_SPECIALISTS).issubset(_ids(home))

        meta: dict[str, Any] = json.loads((home / "workspaces" / PM / _cfg.META_FILE).read_text())
        assert meta["kind"] == "specialist"
        assert meta["scope"] == "org"
        assert meta["role"] == PM
        assert meta["modelSource"] == "policy"
        assert meta["sessionKey"] == f"agent:{PM}:org"
        assert meta["projectKey"] == "org"
        soul = (home / "workspaces" / PM / "SOUL.md").read_text()
        assert "Portfolio Manager" in soul
        assert "never" in soul.lower()  # never edits code
        assert f"agent:{PM}:org" in soul

    def test_gets_full_workspace_contract(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Portfolio Manager gets the same durable workspace set every
        other org specialist gets, not just a hardcoded SOUL.md.
        """
        from docket.core import memory as _mem

        home = _seed(tmp_path, monkeypatch)
        _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)

        ws = home / "workspaces" / PM
        assert ws.stat().st_mode & 0o777 == 0o700
        for fname in (
            "SOUL.md",
            "AGENTS.md",
            "HEARTBEAT.md",
            _mem.REQUIRED_STARTUP_FILE,
            _mem.MEMORY_FILE,
        ):
            fpath = ws / fname
            assert fpath.is_file(), f"missing {fname}"
            assert fpath.stat().st_mode & 0o777 == 0o600
        assert _mem.contract_ok(ws)
        assert (ws / _mem.today_memory_relpath()).is_file()

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _seed(tmp_path, monkeypatch)
        _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)
        _install._provision_portfolio_manager()  # run the step again directly
        registered = [a for a in _ids(home) if a == PM]
        assert registered == [PM]  # exactly one, not duplicated

    def test_shows_in_list_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)
        # The specialist section renders only when at least one project exists.
        proj = home / "workspaces" / "projects" / "demo"
        proj.mkdir(parents=True)
        (proj / _cfg.META_FILE).write_text(
            json.dumps({"kind": "project", "scope": "project", "type": "repo", "name": "demo"})
        )
        capsys.readouterr()  # drop install output
        from docket.cli import _cmd_list_human

        _cmd_list_human()
        out = capsys.readouterr().out
        assert PM in out
