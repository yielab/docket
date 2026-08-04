"""core.trace's age-based retention sweep (expire_old_traces) + `docket trace expire`.

Mirrors the fixture pattern in test_trace_audit.py: trace.py reads paths from
docket.config at call time, so config attributes are repointed at a temp seed
per test rather than mocking the module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _trace as trace_cli
from docket.core import trace as trace_core


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp DOCKET_HOME with config paths repointed for trace retention."""
    d = tmp_path / ".docket"
    d.mkdir()
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", d / "traces", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 3600, raising=True)
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", d / "sessions", raising=True)
    monkeypatch.setattr(_cfg, "TRACE_RETENTION_DAYS", 30, raising=True)
    monkeypatch.setattr(_cfg, "TRACE_RETENTION_S", 30 * 86400, raising=True)
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    return d


def _write_trace(pdir: Path, name: str, lines: list[dict[str, object]]) -> Path:
    pdir.mkdir(parents=True, exist_ok=True)
    tf = pdir / f"{name}.jsonl"
    tf.write_text("\n".join(json.dumps(r) for r in lines) + "\n", encoding="utf-8")
    return tf


class TestExpireOldTraces:
    def test_old_terminated_trace_expires(self, oc_dir: Path) -> None:
        pdir = oc_dir / "traces" / "myshop"
        tf = _write_trace(
            pdir,
            "old",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "session_end"},
            ],
        )
        report = trace_core.expire_old_traces()
        assert not tf.exists()
        assert report.expired_count == 1
        assert report.expired[0].session_id == "old"
        assert report.expired[0].project == "myshop"
        assert report.bytes_reclaimed > 0

    def test_recent_terminated_trace_survives(self, oc_dir: Path) -> None:
        pdir = oc_dir / "traces" / "myshop"
        recent = trace_core._now_iso()
        tf = _write_trace(
            pdir,
            "recent",
            [
                {"ts": recent, "event_type": "session_start"},
                {"ts": recent, "event_type": "session_end"},
            ],
        )
        report = trace_core.expire_old_traces()
        assert tf.exists()
        assert report.expired_count == 0
        assert report.kept_recent == 1

    def test_open_session_survives_regardless_of_age(self, oc_dir: Path) -> None:
        """No session_end at all -- a live session could still be appending to
        this file -- so it must be kept no matter how old the last event is,
        independent of the retention window.
        """
        pdir = oc_dir / "traces" / "myshop"
        tf = _write_trace(
            pdir,
            "open",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "tool_call"},
            ],
        )
        report = trace_core.expire_old_traces(retention_s=1)
        assert tf.exists()
        assert report.expired_count == 0
        assert report.kept_open == 1

    def test_index_stays_consistent_after_deletion(self, oc_dir: Path) -> None:
        pdir = oc_dir / "traces" / "myshop"
        _write_trace(
            pdir,
            "old",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "session_end"},
            ],
        )
        recent = trace_core._now_iso()
        _write_trace(
            pdir,
            "recent",
            [
                {"ts": recent, "event_type": "session_start"},
                {"ts": recent, "event_type": "session_end"},
            ],
        )
        index_file = pdir / ".ingest-index.json"
        index_file.write_text(json.dumps({"old": 42, "recent": 7}), encoding="utf-8")

        trace_core.expire_old_traces()

        index = json.loads(index_file.read_text(encoding="utf-8"))
        assert "old" not in index
        assert index["recent"] == 7

    def test_dry_run_deletes_nothing(self, oc_dir: Path) -> None:
        pdir = oc_dir / "traces" / "myshop"
        tf = _write_trace(
            pdir,
            "old",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "session_end"},
            ],
        )
        index_file = pdir / ".ingest-index.json"
        index_file.write_text(json.dumps({"old": 3}), encoding="utf-8")

        report = trace_core.expire_old_traces(dry_run=True)

        assert tf.exists()
        assert report.dry_run is True
        assert report.expired_count == 1
        assert report.bytes_reclaimed == 0
        # dry-run must not touch the index either
        assert json.loads(index_file.read_text(encoding="utf-8")) == {"old": 3}

    def test_audit_log_untouched_by_sweep(self, oc_dir: Path) -> None:
        audit_log = oc_dir / "audit.log"
        audit_log.write_text('{"seq": 1, "action": "keep-me"}\n', encoding="utf-8")
        before = audit_log.read_text(encoding="utf-8")

        pdir = oc_dir / "traces" / "myshop"
        _write_trace(
            pdir,
            "old",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "session_end"},
            ],
        )
        trace_core.expire_old_traces()

        assert audit_log.read_text(encoding="utf-8") == before

    def test_project_filter_scopes_the_sweep(self, oc_dir: Path) -> None:
        pdir_a = oc_dir / "traces" / "shopA"
        pdir_b = oc_dir / "traces" / "shopB"
        tf_a = _write_trace(
            pdir_a,
            "old",
            [{"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}],
        )
        tf_b = _write_trace(
            pdir_b,
            "old",
            [{"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}],
        )
        report = trace_core.expire_old_traces(project="shopA")
        assert not tf_a.exists()
        assert tf_b.exists()
        assert report.expired_count == 1

    def test_retention_override_wins_over_config_default(self, oc_dir: Path) -> None:
        pdir = oc_dir / "traces" / "myshop"
        recent = trace_core._now_iso()
        tf = _write_trace(
            pdir,
            "recent",
            [
                {"ts": recent, "event_type": "session_start"},
                {"ts": recent, "event_type": "session_end"},
            ],
        )
        # A negative override should expire even a just-terminated trace --
        # negative avoids any flakiness from same-second truncation in
        # _now_iso() vs. the sub-second "now" this function computes.
        report = trace_core.expire_old_traces(retention_s=-1)
        assert not tf.exists()
        assert report.expired_count == 1


class TestRunTraceExpireCommand:
    def test_expire_subcommand_dry_run(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pdir = oc_dir / "traces" / "myshop"
        _write_trace(
            pdir,
            "old",
            [{"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}],
        )
        rc = trace_cli.run_trace("expire", None, None, True, None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Would delete" in out
        assert (pdir / "old.jsonl").exists()

    def test_expire_subcommand_deletes(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pdir = oc_dir / "traces" / "myshop"
        _write_trace(
            pdir,
            "old",
            [{"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}],
        )
        rc = trace_cli.run_trace("expire", None, None, False, None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "deleted" in out
        assert not (pdir / "old.jsonl").exists()

    def test_expire_subcommand_days_override(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pdir = oc_dir / "traces" / "myshop"
        recent = trace_core._now_iso()
        _write_trace(
            pdir,
            "recent",
            [
                {"ts": recent, "event_type": "session_start"},
                {"ts": recent, "event_type": "session_end"},
            ],
        )
        rc = trace_cli.run_trace("expire", None, None, False, -1)
        out = capsys.readouterr().out
        assert rc == 0
        assert "deleted" in out
        assert not (pdir / "recent.jsonl").exists()
