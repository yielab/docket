"""`docket pod reset`: rebuild a member's files and ledger, leave every memory file alone.

Drives the leaf in-process; no model is involved, and a driver that is called fails the test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.agent import driver as _dr
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home

SUBJECT = "docket.interfaces.cli.commands.pod"

_runner = CliRunner()
_MEMBER = "demo-implementer"


@contextmanager
def _make_ws(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        ws = current_home().projects_dir / _MEMBER
        (ws / "memory").mkdir(exist_ok=True)
        (ws / "HEARTBEAT.md").write_text(
            "# HEARTBEAT.md\n\n## Active Tasks\n- [ ] a real task\n", encoding="utf-8"
        )
        yield ws


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
        self, tmp_path: Path, fake_driver: FakeDriver
    ) -> None:
        with _make_ws(tmp_path) as ws:
            code, out = _reset("--yes")

            assert code == 0, out
            assert fake_driver.calls == []
            hb_text = (ws / "HEARTBEAT.md").read_text(encoding="utf-8")
            assert "a real task" not in hb_text
            assert "_none yet_" in hb_text

    def test_leaves_memory_md_the_daily_logs_and_the_pod_memory_alone(
        self, tmp_path: Path, fake_driver: FakeDriver
    ) -> None:
        with _make_ws(tmp_path) as ws:
            (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Old\nkeep this\n", encoding="utf-8")
            log = ws / "memory" / "2026-07-01.md"
            log.write_text("notes\n", encoding="utf-8")
            pod_memory = current_home().pod_memory_path("demo")
            pod_memory.parent.mkdir(parents=True, exist_ok=True)
            pod_memory.write_text('{"entries": []}\n', encoding="utf-8")

            code, out = _reset("--yes")

            assert code == 0, out
            assert "keep this" in (ws / "MEMORY.md").read_text(encoding="utf-8")
            assert log.read_text(encoding="utf-8") == "notes\n"
            assert pod_memory.read_text(encoding="utf-8") == '{"entries": []}\n'
            assert not (ws / "memory" / ".distilled").exists()

    def test_rebuilds_workspace_files_from_metadata(
        self, tmp_path: Path, fake_driver: FakeDriver
    ) -> None:
        with _make_ws(tmp_path) as ws:
            original = (ws / "SOUL.md").read_text(encoding="utf-8")
            (ws / "SOUL.md").write_text("hand edited\n", encoding="utf-8")

            code, out = _reset("--yes")

            assert code == 0, out
            assert (ws / "SOUL.md").read_text(encoding="utf-8") == original

    def test_off_a_tty_without_yes_refuses_and_changes_nothing(
        self, tmp_path: Path, fake_driver: FakeDriver
    ) -> None:
        with _make_ws(tmp_path) as ws:
            code, out = _reset()

            assert code == 1
            assert "--yes" in out
            assert "a real task" in (ws / "HEARTBEAT.md").read_text(encoding="utf-8")

    def test_a_name_outside_the_pod_is_refused(
        self, tmp_path: Path, fake_driver: FakeDriver
    ) -> None:
        with _make_ws(tmp_path):
            result = _runner.invoke(_pod.pod_app, ["reset", "other-lead", "--pod", "demo", "--yes"])

            assert result.exit_code == 1
