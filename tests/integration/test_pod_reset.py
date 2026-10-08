"""`docket pod reset`: distill a member's memory first, fail closed, then rebuild.

Drives the leaf in-process with `default_driver` monkeypatched to `FakeDriver`, so no live
endpoint is involved. The hermetic no-fake proof (the production driver failing with no
provider credentials) is the `exec`/dispatch suites' job.
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
from docket.core import memory as _mem
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


def _use_fake_driver(monkeypatch: pytest.MonkeyPatch, fake: FakeDriver) -> None:
    monkeypatch.setattr(_dr, "default_driver", lambda: fake)


def _reset(*extra: str) -> tuple[int, str]:
    result = _runner.invoke(_pod.pod_app, ["reset", _MEMBER, "--pod", "demo", *extra])
    return result.exit_code, result.output


class TestPodReset:
    def test_distills_first_then_clears_and_keeps_the_fresh_memory_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Old\nkeep this\n", encoding="utf-8")
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)

        code, out = _reset("--yes")

        assert code == 0, out
        assert len(fake.calls) == 1  # distillation ran
        assert not log.exists()
        assert list((ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).rglob("*.md"))
        mem_text = (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert "keep this" in mem_text
        assert "Distilled" in mem_text
        hb_text = (ws / "HEARTBEAT.md").read_text(encoding="utf-8")
        assert "a real task" not in hb_text
        assert "_none yet_" in hb_text

    def test_a_failed_distillation_blocks_the_whole_reset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\nkeep this\n", encoding="utf-8")
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        soul = (ws / "SOUL.md").read_text(encoding="utf-8")
        (ws / "SOUL.md").write_text("hand edited\n", encoding="utf-8")
        fake = FakeDriver(fail_role="implementer", error="boom", failure_kind="daemon_error")
        _use_fake_driver(monkeypatch, fake)

        code, out = _reset("--yes")

        assert code == 1
        assert "daemon_error" in out, "the failure kind must reach the operator"
        assert "Nothing was deleted" in out
        assert log.exists()
        assert "keep this" in (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert "a real task" in (ws / "HEARTBEAT.md").read_text(encoding="utf-8")
        assert (ws / "SOUL.md").read_text(encoding="utf-8") == "hand edited\n"
        assert soul != "hand edited\n"

    def test_rebuilds_workspace_files_from_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        original = (ws / "SOUL.md").read_text(encoding="utf-8")
        (ws / "SOUL.md").write_text("hand edited\n", encoding="utf-8")
        _use_fake_driver(monkeypatch, FakeDriver())

        code, out = _reset("--yes")

        assert code == 0, out
        assert (ws / "SOUL.md").read_text(encoding="utf-8") == original

    def test_off_a_tty_without_yes_refuses_before_any_distillation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)

        code, out = _reset()

        assert code == 1
        assert "--yes" in out
        assert fake.calls == []
        assert log.exists()

    def test_a_name_outside_the_pod_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_ws(tmp_path, monkeypatch)
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)

        result = _runner.invoke(_pod.pod_app, ["reset", "other-lead", "--pod", "demo", "--yes"])

        assert result.exit_code == 1
        assert fake.calls == []
