"""`docket exporters` -- enable an observability destination by authenticating.

The requested experience is "the YAML exists, I only put the key": `enable` prompts for a
missing credential on a TTY, else names `docket keys add` and refuses without writing anything;
a reachable endpoint activates the exporter with a minimal patch document, inheriting the rest
from the built-in at read time (`core.exporter._merge_with_builtin_raw`). See
specs/functional/observability-export.spec.md "Activation".
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import app as _app
from docket.core import secrets as _secrets
from docket.core.audit import read_audit

SUBJECT = "docket.core.exporter"

_runner = CliRunner()

_PUBLIC_KEY = "pk-lf-testvalue00000000000000"
_SECRET_KEY = "sk-lf-testvalue00000000000000"


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir()
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    return home


def _store_langfuse_keys() -> None:
    """Seed both Langfuse credentials in the secret store (not the environment), so a test can
    assert `disable` leaves them alone."""
    _secrets.save_secrets({"LANGFUSE_PUBLIC_KEY": _PUBLIC_KEY, "LANGFUSE_SECRET_KEY": _SECRET_KEY})


@contextlib.contextmanager
def _serve(status: int, body: bytes = b"{}") -> Iterator[str]:
    """A real local HTTP server answering every POST with *status*/*body* -- the endpoint
    `otlp_http.probe` sends its empty ``resourceSpans`` document to."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # quiet the test output
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1/traces"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def _global_exporters(_home: Path) -> dict:
    if not _cfg.EXPORTERS_FILE.is_file():
        return {}
    cfg = json.loads(_cfg.EXPORTERS_FILE.read_text())
    exporters = cfg.get("exporters", {})
    assert isinstance(exporters, dict)
    return exporters


class TestEnableWithoutCredentials:
    def test_enable_without_tty_and_without_keys_exits_1_writing_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RED on the base: `docket exporters` does not exist as a command. Once it does, a
        non-TTY caller with no stored credential is refused, naming both missing names, with
        `docket-exporters.json` never created (ADR 0014's fail-closed negative case)."""
        _seed(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        result = _runner.invoke(_app, ["exporters", "enable", "langfuse"])

        assert result.exit_code == 1
        combined = result.stdout + result.stderr
        assert "docket keys add LANGFUSE_PUBLIC_KEY" in combined
        assert "docket keys add LANGFUSE_SECRET_KEY" in combined
        assert not _cfg.EXPORTERS_FILE.exists()


class TestEnableWithLocalServer:
    def test_enable_writes_minimal_document_and_lists_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _store_langfuse_keys()

        with _serve(200) as endpoint:
            result = _runner.invoke(
                _app, ["exporters", "enable", "langfuse", "--endpoint", endpoint]
            )
        assert result.exit_code == 0, result.stdout + result.stderr

        entries = _global_exporters(home)
        assert entries["langfuse"] == {
            "kind": "exporter",
            "name": "langfuse",
            "enabled": True,
            "endpoint": endpoint,
        }

        list_result = _runner.invoke(_app, ["exporters", "list", "--json"])
        assert list_result.exit_code == 0
        rows = {row["name"]: row for row in json.loads(list_result.stdout)}
        assert rows["langfuse"]["state"] == "enabled"

        audit_entries = read_audit()
        enabled_entries = [e for e in audit_entries if e["action"] == "exporter.enabled"]
        assert len(enabled_entries) == 1
        assert "privacy=minimal" in enabled_entries[0]["detail"]
        assert _SECRET_KEY not in json.dumps(audit_entries)

        show_result = _runner.invoke(_app, ["exporters", "show", "langfuse"])
        assert show_result.exit_code == 0
        assert "session.id" in show_result.stdout  # the built-in's inherited alias

        disable_result = _runner.invoke(_app, ["exporters", "disable", "langfuse"])
        assert disable_result.exit_code == 0
        assert _global_exporters(home)["langfuse"]["enabled"] is False
        assert _secrets.load_secrets()["LANGFUSE_SECRET_KEY"] == _SECRET_KEY

    def test_enable_refuses_on_transport_failure_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The kept negative case: a transport failure is the one outcome that still refuses
        and leaves the catalog untouched, even once the missing-credential gate is past."""
        home = _seed(tmp_path, monkeypatch)
        _store_langfuse_keys()

        result = _runner.invoke(
            _app,
            ["exporters", "enable", "langfuse", "--endpoint", "http://127.0.0.1:1/v1/traces"],
        )

        assert result.exit_code == 1
        assert _global_exporters(home) == {}
        assert not _cfg.EXPORTERS_FILE.exists()
        assert "Could not reach" in result.stderr


class TestRemoveBuiltin:
    def test_remove_builtin_without_global_entry_exits_1_naming_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        result = _runner.invoke(_app, ["exporters", "remove", "jaeger"])
        assert result.exit_code == 1
        assert "built-in" in result.stderr
        assert "jaeger" in result.stderr


class TestConfigExplainExporters:
    def test_config_explain_json_reports_enabled_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.cli import _config
        from docket.cli import _pod as _pod_cli

        _seed(tmp_path, monkeypatch)
        (_cfg.DOCKET_HOME / "workspaces" / "projects").mkdir(parents=True)
        _pod_cli.build_pod("demo", ("lead",), codebase="/src/demo")
        _store_langfuse_keys()

        with _serve(200) as endpoint:
            enable_result = _runner.invoke(
                _app, ["exporters", "enable", "langfuse", "--endpoint", endpoint]
            )
        assert enable_result.exit_code == 0, enable_result.stdout + enable_result.stderr

        capsys.readouterr()
        _config.dispatch("explain", ["demo-lead", "--json"])
        report = json.loads(capsys.readouterr().out)
        by_name = {e["name"]: e for e in report["exporters"]}
        assert by_name["langfuse"]["state"] == "enabled"


class TestDoctorExporterHealth:
    def test_doctor_warns_naming_exporters_test_on_recorded_failures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.cli._doctor import run_doctor

        _seed(tmp_path, monkeypatch)
        _store_langfuse_keys()
        with _serve(200) as endpoint:
            enable_result = _runner.invoke(
                _app, ["exporters", "enable", "langfuse", "--endpoint", endpoint]
            )
        assert enable_result.exit_code == 0, enable_result.stdout + enable_result.stderr

        _cfg.EXPORTERS_HEALTH_FILE.write_text(json.dumps({"langfuse": {"failed": 3, "lastOk": ""}}))

        capsys.readouterr()
        run_doctor()
        out = capsys.readouterr().out
        assert "docket exporters test langfuse" in out


_CANARY = "rm -rf CANARY-TOOL-ARG-MARKER"


def _seed_session(
    home: Path, project: str = "docket-dev", session_id: str = "sess-preview-1"
) -> str:
    """Write one hand-built trace file with a canary in a tool call's arguments -- enough to
    open and close a `gen_ai.chat` span with no content and an `execute_tool` span carrying a
    `toolArguments`-class attribute. Returns *session_id*."""
    pdir = home / "traces" / project
    pdir.mkdir(parents=True)
    records = [
        {
            "event_type": "session_start",
            "session_id": session_id,
            "ts": "2026-09-28T00:00:00Z",
            "project": project,
            "agent_role": "implementer",
            "payload": {},
        },
        {
            "event_type": "llm_call",
            "session_id": session_id,
            "ts": "2026-09-28T00:00:01Z",
            "duration_ms": 100,
            "payload": {"provider": "local", "model": "test-model", "ok": True, "iteration": 1},
        },
        {
            "event_type": "tool_call",
            "session_id": session_id,
            "ts": "2026-09-28T00:00:02Z",
            "payload": {"tool": "bash", "callId": "c1", "arguments": _CANARY},
        },
        {
            "event_type": "tool_result",
            "session_id": session_id,
            "ts": "2026-09-28T00:00:03Z",
            "payload": {"tool": "bash", "callId": "c1", "ok": True, "text": "done"},
        },
        {
            "event_type": "session_end",
            "session_id": session_id,
            "ts": "2026-09-28T00:00:04Z",
            "payload": {},
        },
    ]
    text = "\n".join(json.dumps(r) for r in records) + "\n"
    (pdir / f"{session_id}.jsonl").write_text(text, encoding="utf-8")
    return session_id


def _snapshot(home: Path) -> tuple[bytes | None, bytes | None, bytes | None]:
    def _read(p: Path) -> bytes | None:
        return p.read_bytes() if p.is_file() else None

    return _read(_cfg.EXPORTERS_FILE), _read(_cfg.EXPORTERS_HEALTH_FILE), _read(_cfg.AUDIT_LOG)


class TestPreview:
    """`docket exporters preview` -- see what a destination would receive before sharing it
    (ADR 0015 rule 10). RED on the base: `preview` is not a registered `exporters` action, so
    every call here fails with 'Unknown exporters action'."""

    def test_minimal_hides_the_canary_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        session_id = _seed_session(home)
        before = _snapshot(home)

        result = _runner.invoke(_app, ["exporters", "preview", "langfuse", "--session", session_id])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert _CANARY not in result.stdout
        assert "toolArguments: 0" in result.stdout
        assert _snapshot(home) == before

    def test_actions_level_shows_the_canary_under_tool_call_arguments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        session_id = _seed_session(home)
        before = _snapshot(home)

        result = _runner.invoke(
            _app,
            ["exporters", "preview", "langfuse", "--session", session_id, "--level", "actions"],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert _CANARY in result.stdout
        assert "gen_ai.tool.call.arguments [toolArguments]" in result.stdout
        assert "toolArguments: 1" in result.stdout
        assert _snapshot(home) == before

    def test_json_output_equals_otlp_http_encode_of_the_same_projection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import exporter as _exp
        from docket.core import privacy as _privacy
        from docket.core import telemetry as _telemetry
        from docket.core import trace as _trace
        from docket.edges.adapters.exporters import otlp_http as _otlp_http

        home = _seed(tmp_path, monkeypatch)
        session_id = _seed_session(home)

        result = _runner.invoke(
            _app,
            [
                "exporters",
                "preview",
                "langfuse",
                "--session",
                session_id,
                "--level",
                "actions",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr

        spec = _exp.load_catalog().get("langfuse")
        assert spec is not None
        _label, classes = _privacy.resolve("actions", None)
        policy = _telemetry.ExportPolicy(
            events=_telemetry.DEFAULT_EVENTS,
            classes=classes,
            label="actions",
            content_max_chars=spec.content_max_chars,
        )
        state = _telemetry.ProjectionState()
        spans = []
        tracefile = _trace.find_trace(session_id)
        assert tracefile is not None
        for record in _trace.read_trace(tracefile):
            admitted = policy.admit(record)
            if admitted is None:
                continue
            spans.extend(_telemetry.project(admitted, state, policy))
        spans.extend(_telemetry.flush_open(state))
        expected = _otlp_http.encode(spans, resource=spec.resource, aliases=spec.aliases)

        assert json.loads(result.stdout) == expected
        assert result.stdout.strip().encode() == json.dumps(expected).encode()

    def test_footer_notes_when_the_level_grants_content_the_session_never_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`llm_call` above never carried `inputMessages`/`outputMessages`/`systemInstructions`
        (minimal was in effect when it was captured) -- previewing it at `conversation` must
        say so instead of silently showing less than a later, wider-captured session would."""
        home = _seed(tmp_path, monkeypatch)
        session_id = _seed_session(home)

        result = _runner.invoke(
            _app,
            [
                "exporters",
                "preview",
                "langfuse",
                "--session",
                session_id,
                "--level",
                "conversation",
            ],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "recorded no conversation content" in result.stdout
        assert "captured only once an exporter grants it" in result.stdout
