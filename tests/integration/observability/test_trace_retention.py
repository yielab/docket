"""observability.trace's age-based retention sweep (expire_old_traces) + `docket task prune --traces`.

Mirrors the fixture pattern in test_trace_audit.py: trace.py reads paths from
current_home() at call time, so each test runs in a `use_home` block on a temp seed
rather than mocking the module.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.trace import write_trace as _write_trace

from docket.interfaces.cli.app import app
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as trace_core

SUBJECT = "docket.observability.trace"


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp DOCKET_HOME with config paths repointed for trace retention."""
    d = tmp_path / ".docket"
    d.mkdir()
    with (
        use_home(Home(d)),
        use_home(
            dataclasses.replace(current_home(), session_timeout=3600, trace_retention_days=30)
        ),
    ):
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        yield d


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
        recent = _clock.stamp()
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
        """No session_end at all means a live session could still be appending to this file, so
        it must be kept regardless of age, independent of the retention window."""
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
        report = trace_core.expire_old_traces(dry_run=True)

        assert tf.exists()
        assert report.dry_run is True
        assert report.expired_count == 1
        assert report.bytes_reclaimed == 0

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
        recent = _clock.stamp()
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
        # clock.stamp() vs. the sub-second "now" this function computes.
        report = trace_core.expire_old_traces(retention_s=-1)
        assert not tf.exists()
        assert report.expired_count == 1


def _prune(*extra: str) -> int:
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["task", "prune", "--traces", "--pod", "myshop", *extra])
    print(result.output)
    return result.exit_code


class TestTaskPruneTraces:
    def test_prune_dry_run(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pdir = oc_dir / "traces" / "myshop"
        _write_trace(
            pdir,
            "old",
            [{"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}],
        )
        rc = _prune("--dry-run")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Would delete" in out
        assert (pdir / "old.jsonl").exists()

    def test_prune_deletes(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pdir = oc_dir / "traces" / "myshop"
        _write_trace(
            pdir,
            "old",
            [{"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}],
        )
        rc = _prune()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Deleted" in out
        assert not (pdir / "old.jsonl").exists()

    def test_prune_days_override(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pdir = oc_dir / "traces" / "myshop"
        recent = _clock.stamp()
        _write_trace(
            pdir,
            "recent",
            [
                {"ts": recent, "event_type": "session_start"},
                {"ts": recent, "event_type": "session_end"},
            ],
        )
        rc = _prune("--days", "0")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Deleted" in out
        assert not (pdir / "recent.jsonl").exists()


class TestArtifactsExpireWithTheirTrace:
    def _artifact(self, oc_dir: Path) -> Path:
        directory = oc_dir / "workspaces" / "pods" / "myshop" / "cache" / "artifacts"
        directory.mkdir(parents=True)
        path = directory / ("a" * 64 + ".txt")
        path.write_text("the whole result")
        return path

    def _trace(self, oc_dir: Path, artifact: Path, end: str) -> Path:
        return _write_trace(
            oc_dir / "traces" / "myshop",
            "old",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {
                    "ts": "2000-01-01T00:01:00Z",
                    "event_type": "tool_result",
                    "payload": {"tool": "bash", "artifact": str(artifact)},
                },
                {"ts": end, "event_type": "session_end"},
            ],
        )

    def test_an_expired_trace_takes_its_artifact_with_it(self, oc_dir: Path) -> None:
        artifact = self._artifact(oc_dir)
        trace = self._trace(oc_dir, artifact, "2000-01-01T00:05:00Z")

        report = trace_core.expire_old_traces()

        assert not trace.exists()
        assert not artifact.exists()
        assert report.bytes_reclaimed > len("the whole result")

    def test_a_dry_run_keeps_the_artifact(self, oc_dir: Path) -> None:
        artifact = self._artifact(oc_dir)
        self._trace(oc_dir, artifact, "2000-01-01T00:05:00Z")

        trace_core.expire_old_traces(dry_run=True)

        assert artifact.exists()

    def test_a_recent_trace_keeps_its_artifact(self, oc_dir: Path) -> None:
        artifact = self._artifact(oc_dir)
        self._trace(oc_dir, artifact, _clock.stamp())
        # the first records are old, but the last event decides the age
        trace_core.expire_old_traces()

        assert artifact.exists()

    def test_a_path_outside_a_pods_artifacts_directory_is_never_deleted(self, oc_dir: Path) -> None:
        stray = oc_dir / "precious.txt"
        stray.write_text("keep me")
        self._trace(oc_dir, stray, "2000-01-01T00:05:00Z")

        trace_core.expire_old_traces()

        assert stray.exists()
