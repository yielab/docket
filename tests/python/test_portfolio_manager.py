"""AA-6: the optional org Portfolio Manager (opt-in, single, never a pod member)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _install
from docket.core import pod as _pod
from docket.edges.adapters import openclaw as _oc

_ORG_SPECIALISTS = ("manager", "knowledge", "security")
PM = "portfolio-manager"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, fake_openclaw: Path) -> None:
    # fake_openclaw puts a real `openclaw` shim on PATH so install's Step 1
    # dependency probe runs its real code (CI has no daemon). Only the daemon's
    # agents-add is simulated at the ACL boundary (register_agent_cli).
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "SITES_DIR", oc_dir / "Sites", raising=True)
    monkeypatch.setattr(_cfg, "LOG_DIR", oc_dir / "logs", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _fake)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))
    cfg_file.chmod(0o600)
    _point_at(oc_dir, monkeypatch)
    _fake_registration(monkeypatch)
    monkeypatch.setattr(_oc, "auth_profiles_summary", lambda agent="main": [])
    return oc_dir


def _ids(oc_dir: Path) -> set[str]:
    raw = json.loads((oc_dir / "openclaw.json").read_text())
    return {a["id"] for a in raw["agents"]["list"]}


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
        oc_dir = _seed(tmp_path, monkeypatch)
        rc = _install.run_install(want_gates=False, assume_yes=True, want_portfolio=False)
        assert rc == 0
        assert _ids(oc_dir) == set(_ORG_SPECIALISTS)
        assert PM not in _ids(oc_dir)
        assert not (oc_dir / "workspaces" / PM).exists()

    def test_flag_on_creates_one_org_scoped_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        rc = _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)
        assert rc == 0
        assert PM in _ids(oc_dir)
        # Pods still function: the org specialists are all there too.
        assert set(_ORG_SPECIALISTS).issubset(_ids(oc_dir))

        meta: dict[str, Any] = json.loads((oc_dir / "workspaces" / PM / _cfg.META_FILE).read_text())
        assert meta["kind"] == "specialist"
        assert meta["scope"] == "org"
        assert meta["role"] == PM
        assert meta["modelSource"] == "policy"
        soul = (oc_dir / "workspaces" / PM / "SOUL.md").read_text()
        assert "Portfolio Manager" in soul
        assert "never" in soul.lower()  # never edits code

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)
        _install._provision_portfolio_manager()  # run the step again directly
        registered = [a for a in _ids(oc_dir) if a == PM]
        assert registered == [PM]  # exactly one, not duplicated

    def test_shows_in_list_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _install.run_install(want_gates=False, assume_yes=True, want_portfolio=True)
        # The specialist section renders only when at least one project exists.
        proj = oc_dir / "workspaces" / "projects" / "demo"
        proj.mkdir(parents=True)
        (proj / _cfg.META_FILE).write_text(
            json.dumps({"kind": "project", "scope": "project", "type": "repo", "name": "demo"})
        )
        capsys.readouterr()  # drop install output
        from docket.cli import _cmd_list_human

        _cmd_list_human()
        out = capsys.readouterr().out
        assert PM in out
