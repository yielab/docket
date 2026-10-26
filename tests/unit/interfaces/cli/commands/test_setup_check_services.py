"""`docket setup --fix` — system-wide health checks + JSON health probe.

Calls `run_check()` in-process with `DOCKET_HOME`/`FLEET_FILE`
monkeypatched to a temp seed. stdout is captured to assert on the human
report; the return value is the process exit code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import seed_setup_check_home as _seed

from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_services as _setup_check_services
from docket.kernel.home import current_home

SUBJECT = "docket.interfaces.cli.commands.setup_check_services"

# ── seed helpers ───────────────────────────────────────────────────────────────

_FULL_META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "type": "repo",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/tmp/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
    "templateVersion": str(current_home().template_version),
}

_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


class TestNotifications:
    def test_agents_and_only_console_is_a_counted_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, notify=False):
            issues = _setup_check_services._check_notifications(["myshop"])
            out = capsys.readouterr().out
            assert issues == 1
            assert "docket setup notify enable desktop" in out
            assert "docket inbox" in out

    def test_no_agents_is_informational(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, notify=False, register=False):
            issues = _setup_check_services._check_notifications([])
            out = capsys.readouterr().out
            assert issues == 0
            assert "docket setup notify enable desktop" in out

    def test_a_delivering_channel_is_named_and_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch):
            issues = _setup_check_services._check_notifications(["myshop"])
            out = capsys.readouterr().out
            assert issues == 0
            assert "desktop" in out
            assert "docket setup notify enable" not in out

    def test_json_names_the_delivering_channels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}):
            _setup_check.run_check(json_out=True)
            data = json.loads(capsys.readouterr().out)
            assert data["checks"]["notifications"] == {"ok": True, "delivering": ["desktop"]}
            assert data["healthy"] is True

    def test_json_only_console_with_an_agent_is_unhealthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, monkeypatch, secrets={"ANTHROPIC_API_KEY": "sk-ant-x"}, notify=False):
            rc = _setup_check.run_check(json_out=True)
            data = json.loads(capsys.readouterr().out)
            assert data["checks"]["notifications"] == {"ok": False, "delivering": []}
            assert data["healthy"] is False
            assert rc == 1
