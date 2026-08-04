"""Memory distillation (`core.memory.distill_memory`).

Pure `core/` coverage — no CLI, no subprocess, no live daemon. Covers:

* nothing pending short-circuits to `ok=True, skipped=True` without ever
  calling the driver;
* a driver failure (or an empty reply) leaves **every file on disk
  untouched** -- the fail-closed guarantee `maintain clean/reset
  --distill-first` depends on;
* a real distillation moves pending daily logs into
  `memory/.distilled/<day>/` and appends the driver's reply to `MEMORY.md`,
  preserving whatever was already there;
* the prompt sent to the driver inlines the logs' own content and respects
  `config.DISTILL_MAX_INPUT_BYTES`.

Uses `tests/python/fakes.py`'s `FakeDriver` (the one test double for the
`RuntimeDriver` port, ROADMAP §4.5) throughout -- this suite is green on a
machine with no `openclaw` binary and no daemon at all. CLI-level wiring
(`docket maintain <id> clean/reset/distill`, the `--no-distill-first`
opt-out) is covered separately in test_maintain_distill_cli.py.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import memory as _mem
from docket.core.runtime_driver import TurnResult

from .fakes import FakeDriver

# ── helpers ──────────────────────────────────────────────────────────────────


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    return ws


def _write_log(ws: Path, day: str, text: str = "did stuff\n") -> Path:
    p = ws / "memory" / f"{day}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _empty_output_driver(
    agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None = None
) -> TurnResult:
    """A driver that "succeeds" but replies with nothing usable."""
    return TurnResult(True, "   ", 0.0, {})


# ── pending_daily_logs ───────────────────────────────────────────────────────


class TestPendingDailyLogs:
    def test_no_memory_dir_returns_empty(self, tmp_path: Path) -> None:
        assert _mem.pending_daily_logs(tmp_path / "nope") == []

    def test_lists_logs_oldest_first_and_excludes_archive(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-02")
        _write_log(ws, "2026-07-01")
        archive = ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME / "2026-06-30"
        archive.mkdir(parents=True)
        (archive / "2026-06-29.md").write_text("old\n", encoding="utf-8")

        logs = _mem.pending_daily_logs(ws)

        assert [p.name for p in logs] == ["2026-07-01.md", "2026-07-02.md"]


# ── distill_memory: nothing pending ─────────────────────────────────────────


class TestDistillMemoryNothingPending:
    def test_skips_without_calling_the_driver(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        fake = FakeDriver()

        result = _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        assert result.ok is True
        assert result.skipped is True
        assert result.logs_distilled == 0
        assert fake.calls == []
        assert not (ws / "MEMORY.md").exists()


# ── distill_memory: fail-closed ──────────────────────────────────────────────


class TestDistillMemoryFailsClosed:
    def test_driver_failure_leaves_everything_untouched(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        log = _write_log(ws, "2026-07-01", "important stuff\n")
        fake = FakeDriver(fail_role="demo", error="boom", failure_kind="daemon_error")

        result = _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        assert result.ok is False
        assert result.error == "boom"
        assert result.failure_kind == "daemon_error"
        assert result.logs_distilled == 0
        assert result.archived == []
        # Nothing moved, nothing written -- fail-closed.
        assert log.exists()
        assert log.read_text(encoding="utf-8") == "important stuff\n"
        assert not (ws / "MEMORY.md").exists()
        assert not (ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).exists()

    def test_empty_reply_fails_closed(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        log = _write_log(ws, "2026-07-01")

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=_empty_output_driver,
        )

        assert result.ok is False
        assert result.failure_kind == "invalid_output"
        assert log.exists()
        assert not (ws / "MEMORY.md").exists()


# ── distill_memory: success ──────────────────────────────────────────────────


class TestDistillMemorySuccess:
    def test_archives_logs_and_appends_summary(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Existing\nkeep me\n", encoding="utf-8")
        log1 = _write_log(ws, "2026-07-01", "day one notes\n")
        log2 = _write_log(ws, "2026-07-02", "day two notes\n")
        fake = FakeDriver()

        result = _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=fake,
            day=_dt.date(2026, 7, 3),
        )

        assert result.ok is True
        assert result.skipped is False
        assert result.logs_distilled == 2
        assert result.summary  # FakeDriver's canned "done by demo"

        # Raw logs moved out of memory/*.md.
        assert not log1.exists()
        assert not log2.exists()
        assert _mem.pending_daily_logs(ws) == []
        archive_dir = ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME / "2026-07-03"
        assert sorted(p.name for p in archive_dir.iterdir()) == ["2026-07-01.md", "2026-07-02.md"]
        assert (archive_dir / "2026-07-01.md").read_text(encoding="utf-8") == "day one notes\n"
        assert set(result.archived) == {
            "memory/.distilled/2026-07-03/2026-07-01.md",
            "memory/.distilled/2026-07-03/2026-07-02.md",
        }

        # MEMORY.md gained a dated section; prior content untouched.
        mem_text = (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert "## Existing" in mem_text
        assert "keep me" in mem_text
        assert "## Distilled 2026-07-03" in mem_text
        assert "done by demo" in mem_text

        # One driver call, with both logs' content inlined into the prompt.
        assert len(fake.calls) == 1
        agent_id, session_key, message, timeout, _env = fake.calls[0]
        assert agent_id == "demo"
        assert session_key == "agent:demo:default"
        assert "day one notes" in message
        assert "day two notes" in message
        assert timeout == _cfg.DISTILL_TIMEOUT_S

    def test_creates_memory_md_when_absent(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-01", "notes\n")
        fake = FakeDriver()

        result = _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        assert result.ok is True
        assert (ws / "MEMORY.md").is_file()
        assert "done by demo" in (ws / "MEMORY.md").read_text(encoding="utf-8")

    def test_custom_timeout_overrides_config_default(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-01")
        fake = FakeDriver()

        _mem.distill_memory(
            ws,
            label="demo",
            agent_id="demo",
            session_key="agent:demo:default",
            driver=fake,
            timeout=7,
        )

        assert fake.calls[0][3] == 7


# ── the prompt itself is byte-budgeted ──────────────────────────────────────


class TestDistillationMessageBudget:
    def test_message_truncated_at_configured_byte_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "DISTILL_MAX_INPUT_BYTES", 200, raising=True)
        ws = _ws(tmp_path)
        _write_log(ws, "2026-07-01", "A" * 2000 + "\n")
        fake = FakeDriver()

        _mem.distill_memory(
            ws, label="demo", agent_id="demo", session_key="agent:demo:default", driver=fake
        )

        message = fake.calls[0][2]
        assert "A" * 2000 not in message
        assert "truncated" in message
