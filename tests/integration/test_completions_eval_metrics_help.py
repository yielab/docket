"""metrics and help commands.

These call the public run_* entry points in-process. stdout is captured with
capsys to assert on the rendered text; the return value is the process exit
code. Config-dependent modules (metrics) are repointed at a temp DOCKET_HOME.

`docket eval` is not a command — see tests/guards/test_removed_commands.py for its
removed-command-notice coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _help, _metrics

SUBJECT = "docket.cli"

# ── metrics ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / ".docket"
    d.mkdir()
    repoint_docket_home(monkeypatch, d)
    return d


class TestMetrics:
    def test_no_traces_dir_returns_1(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _metrics.run_metrics()
        out = capsys.readouterr().out
        assert rc == 1
        assert "No traces directory found" in out
        assert "docket trace ingest" in out

    def test_empty_traces_dir_no_sessions(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (oc_dir / "traces").mkdir()
        rc = _metrics.run_metrics()
        out = capsys.readouterr().out
        assert rc == 0
        assert "No terminal sessions found" in out

    def test_help_prints_usage(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _metrics.run_metrics(show_help=True)
        out = capsys.readouterr().out
        assert rc == 0
        assert "docket metrics" in out
        assert "Filter by agent role" in out

    def test_computes_success_rate(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        proj = oc_dir / "traces" / "myapp"
        proj.mkdir(parents=True)
        session = [
            {
                "event_type": "session_start",
                "ts": "2026-06-23T10:00:00",
                "agent_role": "programmer",
            },
            {"event_type": "cost_charged", "cost_usd": 0.05},
            {
                "event_type": "session_end",
                "ts": "2026-06-23T10:01:00",
                "agent_role": "programmer",
                "payload": {"status": "success"},
            },
        ]
        (proj / "sess1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in session) + "\n", encoding="utf-8"
        )
        rc = _metrics.run_metrics()
        out = capsys.readouterr().out
        assert rc == 0
        assert "docket metrics" in out
        assert "Success rate" in out
        assert "100.0%" in out
        assert "1 success / 0 failure / 0 aborted" in out
        assert "total=$0.05" in out

    def test_role_filter(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        proj = oc_dir / "traces" / "myapp"
        proj.mkdir(parents=True)
        rec = [
            {"event_type": "session_start", "ts": "2026-06-23T10:00:00", "agent_role": "tester"},
            {
                "event_type": "session_end",
                "ts": "2026-06-23T10:00:30",
                "agent_role": "tester",
                "payload": {"status": "success"},
            },
        ]
        (proj / "s.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rec) + "\n", encoding="utf-8"
        )
        rc = _metrics.run_metrics(role="programmer")
        out = capsys.readouterr().out
        assert rc == 0
        # role filter excludes the tester session
        assert "No terminal sessions found" in out

    def test_guardrail_block_reported_from_a_real_g2_producer(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`guardrail_block` is the live-path producer this reader waits for, bucketed by the
        tripped policy's id -- the reader's `payload.get("action", etype)` convention is fed
        the policy id, not the generic word "block", so the table names which policy fired."""
        proj = oc_dir / "traces" / "myapp"
        proj.mkdir(parents=True)
        session = [
            {"event_type": "session_start", "ts": "2026-06-23T10:00:00", "agent_role": "lead"},
            {
                "event_type": "guardrail_check",
                "ts": "2026-06-23T10:00:05",
                "agent_role": "lead",
                "payload": {"hook": "pre_output", "policy": "forbidden-marker", "action": "block"},
            },
            {
                "event_type": "guardrail_block",
                "ts": "2026-06-23T10:00:05",
                "agent_role": "lead",
                "payload": {
                    "hook": "pre_output",
                    "policy": "forbidden-marker",
                    "action": "forbidden-marker",
                },
            },
            {
                "event_type": "session_end",
                "ts": "2026-06-23T10:00:10",
                "agent_role": "lead",
                "payload": {"status": "failure"},
            },
        ]
        (proj / "sess1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in session) + "\n", encoding="utf-8"
        )
        rc = _metrics.run_metrics()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Guardrail trips:" in out
        assert "forbidden-marker" in out
        # guardrail_check is a pure audit-trail event, deliberately not tallied
        # here too — it would double-count the same trip guardrail_block already
        # reports (see core/dispatch.py's module docstring).
        assert out.count("forbidden-marker") == 1


# ── help ────────────────────────────────────────────────────────────────────────


class TestHelp:
    def test_prints_all_sections(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _help.run_help()
        out = capsys.readouterr().out
        assert rc == 0
        for section in (
            "AGENT TYPES",
            "USAGE",
            "LIFECYCLE",
            "MAINTENANCE",
            "TELEGRAM",
            "CONFIGURATION",
            "CONTEXT & MEMORY",
            "MONITORING",
            "OBSERVABILITY",
            "PODS & QUEUE",
            "UTILITIES",
            "MODEL POLICY",
            "EXAMPLES",
            "PATHS",
        ):
            assert section in out, f"missing section: {section}"

    def test_includes_resolved_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        _help.run_help()
        out = capsys.readouterr().out
        # cheap/strong labels with a resolved model id each
        assert "cheap" in out
        assert "strong" in out
        assert "/" in out  # provider/model ids rendered

    def test_lists_core_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        _help.run_help()
        out = capsys.readouterr().out
        for cmd in ("install", "list", "add", "doctor", "completions", "help"):
            assert cmd in out

    def test_topic_prints_that_commands_own_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _help.run_help("status")
        out = capsys.readouterr().out
        assert rc == 0
        assert "status" in out
        assert "AGENT TYPES" not in out  # differs from the bare `docket help` reference

    def test_unknown_topic_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _help.run_help("not-a-real-command")
        err = capsys.readouterr().err
        assert rc == 1
        assert "not-a-real-command" in err

    def test_topic_differs_from_bare_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        _help.run_help("status")
        topic_out = capsys.readouterr().out
        _help.run_help()
        bare_out = capsys.readouterr().out
        assert topic_out != bare_out
