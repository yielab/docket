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

import json
import secrets as _secrets
import stat
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.serve as serve
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-g6-xyz789"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def approvals_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d, raising=True)
    return d


@pytest.fixture()
def live_server(approvals_dir: Path):  # type: ignore[no-untyped-def]
    """Real ThreadingHTTPServer on a random port. Yields (base_url, token)."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _get(url: str, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── secrets.compare_digest is actually used ────────────────────────────────────


class TestCompareDigestAuth:
    def test_compare_digest_is_invoked_on_authenticated_request(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str]] = []
        real_compare_digest = _secrets.compare_digest

        def spy(a: str, b: str) -> bool:
            calls.append((a, b))
            return bool(real_compare_digest(a, b))

        monkeypatch.setattr(serve.secrets, "compare_digest", spy)
        base_url, token = live_server
        status, _body = _get(f"{base_url}/approvals", token=token)
        assert status == 200
        assert calls, "_check_auth should call secrets.compare_digest"
        assert calls[0] == (f"Bearer {token}", f"Bearer {token}")

    def test_wrong_token_still_rejected(self, live_server: tuple[str, str]) -> None:
        base_url, _token = live_server
        status, body = _get(f"{base_url}/approvals", token="not-the-right-token")
        assert status == 401
        assert body["ok"] is False

    def test_no_token_still_rejected(self, live_server: tuple[str, str]) -> None:
        base_url, _token = live_server
        status, _body = _get(f"{base_url}/approvals")
        assert status == 401

    def test_correct_token_accepted(self, live_server: tuple[str, str]) -> None:
        base_url, token = live_server
        status, body = _get(f"{base_url}/approvals", token=token)
        assert status == 200
        assert body == {"pending": []}

    def test_empty_serve_token_denies_all_even_with_compare_digest(
        self, approvals_dir: Path
    ) -> None:
        """serve_token == "" must short-circuit before ever reaching
        compare_digest (an empty expected token must never validate)."""

        class _Handler(_DocketHandler):
            serve_token = ""

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, _body = _get(f"http://127.0.0.1:{port}/approvals", token="")
            assert status == 401
        finally:
            srv.shutdown()


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
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "fixed-test-token-abc")

        token_path = tmp_path / "serve-token.txt"
        serve.run_serve(port=0, interval=30, token_file=str(token_path))

        assert token_path.read_text().strip() == "fixed-test-token-abc"
        mode = stat.S_IMODE(token_path.stat().st_mode)
        assert mode == 0o600

    def test_token_not_printed_to_stdout_when_token_file_given(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "should-not-appear-on-stdout")

        token_path = tmp_path / "serve-token.txt"
        serve.run_serve(port=0, interval=30, token_file=str(token_path))

        out = capsys.readouterr().out
        assert "should-not-appear-on-stdout" not in out
        assert str(token_path) in out

    def test_token_printed_to_stdout_without_token_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "printed-token-xyz")

        serve.run_serve(port=0, interval=30)

        out = capsys.readouterr().out
        assert "printed-token-xyz" in out

    def test_creates_parent_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "nested-dir-token")

        token_path = tmp_path / "nested" / "dir" / "serve-token.txt"
        serve.run_serve(port=0, interval=30, token_file=str(token_path))

        assert token_path.exists()
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


# ── bind semantics documentation ────────────────────────────────────────────────


class TestBindSemanticsDocumented:
    def test_module_docstring_documents_loopback_default(self) -> None:
        assert "127.0.0.1" in (serve.__doc__ or "")
        assert "loopback" in (serve.__doc__ or "").lower()

    def test_run_serve_docstring_documents_bind(self) -> None:
        assert "127.0.0.1" in (serve.run_serve.__doc__ or "")

    def test_startup_banner_prints_bind_address(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "banner-test-token")

        serve.run_serve(port=0, interval=30)
        out = capsys.readouterr().out
        assert "Bind: 127.0.0.1" in out
        assert "loopback-only" in out

    def test_non_loopback_bind_gets_a_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "warn-test-token")

        serve.run_serve(port=0, interval=30, bind="0.0.0.0")
        out = capsys.readouterr().out
        assert "WARNING" in out
