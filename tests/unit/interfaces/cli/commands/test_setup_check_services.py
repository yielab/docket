"""`docket setup --fix` — system-wide health checks + JSON health probe.

Calls `run_check()` in-process with `DOCKET_HOME`/`FLEET_FILE`
monkeypatched to a temp seed. stdout is captured to assert on the human
report; the return value is the process exit code.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_services as _setup_check_services
from docket.kernel.home import Home, current_home, use_home
from docket.operator import channel as _channel

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


@contextmanager
def _point_config_at(
    home: Path,
) -> Iterator[None]:
    """Repoint the already-imported config module at a temp DOCKET_HOME."""
    with use_home(Home(home)):
        yield


@contextmanager
def _seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    full_workspace: bool = True,
    budget: str | None = None,
    register: bool = True,
    meta_model: str = "anthropic/claude-sonnet-4-6",
    secrets: dict[str, str] | None = None,
    notify: bool = True,
) -> Iterator[Path]:
    """Create a temp DOCKET_HOME with one myshop agent and repoint config; a healthy home
    has a channel that delivers beyond the console, so `desktop` is enabled unless asked not to."""
    home = tmp_path / ".docket"
    ws = home / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)

    meta = {**_FULL_META, "model": meta_model}
    if budget is not None:
        meta["budgetUsd"] = budget
    (ws / ".docket-meta.json").write_text(json.dumps(meta))

    files = ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md") if full_workspace else ("SOUL.md",)
    for f in files:
        (ws / f).write_text(f"# {f}\n")

    fleet = json.loads(json.dumps(_FLEET_CONFIG))
    if not register:
        fleet["agents"] = []
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps(fleet))
    fleet_file.chmod(0o600)

    if secrets is not None:
        sfile = home / "secrets.json"
        sfile.write_text(json.dumps(secrets))
        sfile.chmod(0o600)

    with _point_config_at(home):
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        if notify:
            _channel.enable_channel("desktop")
        yield home


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
