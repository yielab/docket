"""`docket pod reset`: rebuild a member's files and ledger, leave every memory file alone.

Drives the leaf in-process; no model is involved, and a driver that is called fails the test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home
from tests.fakes import FakeDriver
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _pod
from docket.edges.adapters import docket_runtime as _dr

SUBJECT = "docket.cli._pod"

_runner = CliRunner()
_MEMBER = "demo-implementer"


def _make_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    ws = _cfg.PROJECTS_DIR / _MEMBER
    (ws / "memory").mkdir(exist_ok=True)
    (ws / "HEARTBEAT.md").write_text(
        "# HEARTBEAT.md\n\n## Active Tasks\n- [ ] a real task\n", encoding="utf-8"
    )
    return ws


@pytest.fixture
def fake_driver(monkeypatch: pytest.MonkeyPatch) -> FakeDriver:
    fake = FakeDriver()
    monkeypatch.setattr(_dr, "default_driver", lambda: fake)
    return fake


def _reset(*extra: str) -> tuple[int, str]:
    result = _runner.invoke(_pod.pod_app, ["reset", _MEMBER, "--pod", "demo", *extra])
    return result.exit_code, result.output


class TestPodReset:
    def test_resets_the_ledger_and_calls_no_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_driver: FakeDriver
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)

        code, out = _reset("--yes")

        assert code == 0, out
        assert fake_driver.calls == []
        hb_text = (ws / "HEARTBEAT.md").read_text(encoding="utf-8")
        assert "a real task" not in hb_text
        assert "_none yet_" in hb_text

    def test_leaves_memory_md_the_daily_logs_and_the_pod_memory_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_driver: FakeDriver
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Old\nkeep this\n", encoding="utf-8")
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        pod_memory = _cfg.pod_memory_path("demo")
        pod_memory.parent.mkdir(parents=True, exist_ok=True)
        pod_memory.write_text('{"entries": []}\n', encoding="utf-8")

        code, out = _reset("--yes")

        assert code == 0, out
        assert "keep this" in (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert log.read_text(encoding="utf-8") == "notes\n"
        assert pod_memory.read_text(encoding="utf-8") == '{"entries": []}\n'
        assert not (ws / "memory" / ".distilled").exists()

    def test_rebuilds_workspace_files_from_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_driver: FakeDriver
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        original = (ws / "SOUL.md").read_text(encoding="utf-8")
        (ws / "SOUL.md").write_text("hand edited\n", encoding="utf-8")

        code, out = _reset("--yes")

        assert code == 0, out
        assert (ws / "SOUL.md").read_text(encoding="utf-8") == original

    def test_off_a_tty_without_yes_refuses_and_changes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_driver: FakeDriver
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)

        code, out = _reset()

        assert code == 1
        assert "--yes" in out
        assert "a real task" in (ws / "HEARTBEAT.md").read_text(encoding="utf-8")

    def test_a_name_outside_the_pod_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_driver: FakeDriver
    ) -> None:
        _make_ws(tmp_path, monkeypatch)

        result = _runner.invoke(_pod.pod_app, ["reset", "other-lead", "--pod", "demo", "--yes"])

        assert result.exit_code == 1
