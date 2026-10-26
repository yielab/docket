"""Serve auth hardening.

Covers:
  - `_DocketHandler._check_auth` compares the bearer token with
    `secrets.compare_digest` (timing-safe), not `==`
  - a wrong token is still rejected (behaviour unchanged, just the compare
    mechanism)
  - `run_serve(token_file=...)` writes the bearer token to a 0600 file
    instead of printing it to stdout
  - the bind-semantics documentation exists (default 127.0.0.1, loopback-only)
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from docket.interfaces.http import server
from docket.kernel import threads as _threads

SUBJECT = "docket.interfaces.http.server"


# ── token file option ──────────────────────────────────────────────────────────


class _FakeServer:
    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


class TestTokenFileOption:
    def test_token_written_to_file_with_0600(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "fixed-test-token-abc")

        token_path = tmp_path / "serve-token.txt"
        server.run_serve(port=0, interval=30, token_file=str(token_path))

        assert token_path.read_text().strip() == "fixed-test-token-abc"
        mode = stat.S_IMODE(token_path.stat().st_mode)
        assert mode == 0o600

    def test_token_not_printed_to_stdout_when_token_file_given(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "should-not-appear-on-stdout")

        token_path = tmp_path / "serve-token.txt"
        server.run_serve(port=0, interval=30, token_file=str(token_path))

        out = capsys.readouterr().out
        assert "should-not-appear-on-stdout" not in out
        assert str(token_path) in out

    def test_token_printed_to_stdout_without_token_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "printed-token-xyz")

        server.run_serve(port=0, interval=30)

        out = capsys.readouterr().out
        assert "printed-token-xyz" in out

    def test_creates_parent_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "nested-dir-token")

        token_path = tmp_path / "nested" / "dir" / "serve-token.txt"
        server.run_serve(port=0, interval=30, token_file=str(token_path))

        assert token_path.exists()
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


# ── bind semantics documentation ────────────────────────────────────────────────


class TestBindSemanticsDocumented:
    def test_module_docstring_documents_loopback_default(self) -> None:
        assert "127.0.0.1" in (server.__doc__ or "")
        assert "loopback" in (server.__doc__ or "").lower()

    def test_run_serve_docstring_documents_bind(self) -> None:
        assert "127.0.0.1" in (server.run_serve.__doc__ or "")

    def test_startup_banner_prints_bind_address(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "banner-test-token")

        server.run_serve(port=0, interval=30)
        out = capsys.readouterr().out
        assert "Bind: 127.0.0.1" in out
        assert "loopback-only" in out

    def test_non_loopback_bind_gets_a_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "warn-test-token")

        server.run_serve(port=0, interval=30, bind="0.0.0.0")
        out = capsys.readouterr().out
        assert "WARNING" in out
