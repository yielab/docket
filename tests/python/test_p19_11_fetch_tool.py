"""The `fetch` tool -- an inspectable, allowlisted egress path.

docket's real network-egress gap: `curl`/`wget` correctly ask through the
`bash` command classifier, but `python3 -c "import urllib..."`, `node`, and
`git clone <url>` are curated-allowlist escape hatches that reach the network
unattended. `fetch` closes that gap without a `--network none` lockdown
(deferred -- it breaks `npm install`/`pip`/`git clone` when on, for no
measured need). What this file pins, in order of how much it matters:

1. **The domain allowlist is real containment, not decoration.** A host off
   the allowlist is refused *before* a socket is ever opened -- proven by
   making `urllib.request.build_opener` raise if called at all -- and a
   redirect off the allowlist is refused the same way `urllib`'s own
   extension point (`redirect_request`) is meant to be used for exactly this.
2. **The response size cap and timeout are enforced**, with truncation
   always announced in the returned text (same discipline as
   `toolbox.MAX_OUTPUT_CHARS`).
3. **`fetch` is gated exactly like every other built-in.** It is registered
   in `core/tools.py`'s `builtin_registry()`, `kind="read"`, and a
   `pre_tool_call` policy denies a `fetch` call through the real,
   unmodified `dispatch_tool` -- proving there is no second execution path
   around the chokepoint.

A real local HTTP server (stdlib `http.server`) backs every network-shaped
test here rather than mocking `urlopen` internals, so the redirect-refusal
behavior in particular is proven against real HTTP semantics, not an
assumption about what `urllib` would have done.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core.llm import ToolCall
from docket.core.tools import ToolContext, builtin_registry, dispatch_tool
from docket.edges.adapters import fetch as _fetch


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every docket-owned store this module touches, matching the
    convention `test_p19_3_pre_tool_call.py` set for gate tests, and default
    the fetch allowlist closed so each test opts a host in explicitly.
    """
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)
    monkeypatch.setattr(_cfg, "FETCH_ALLOWED_DOMAINS", (), raising=True)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet the test output
        pass

    def _reply(self, status: int, body: bytes = b"", content_type: str = "text/plain") -> None:
        self.send_response(status)
        if body:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # BaseHTTPRequestHandler's own naming convention
        if self.path == "/ok":
            self._reply(200, b"hello world")
        elif self.path == "/big":
            # 'z' deliberately, not 'x' -- so counting filler bytes in the
            # truncated result can't be confused by an incidental 'x' in the
            # "HTTP 200 text/plain" header or the "truncated" message.
            self._reply(200, b"z" * 5000)
        elif self.path == "/slow":
            time.sleep(2)
            self._reply(200, b"too late")
        elif self.path == "/missing":
            self._reply(404, b"not found")
        elif self.path == "/redirect-allowed":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/redirect-blocked":
            self.send_response(302)
            self.send_header("Location", "http://evil.example.test/pwned")
            self.end_headers()
        else:
            self._reply(404, b"unknown path")


@pytest.fixture
def server() -> Iterator[str]:
    """A real local HTTP server; yields its base URL (``http://127.0.0.1:<port>``)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = srv.server_address[0], srv.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def _allow(monkeypatch: pytest.MonkeyPatch, server_url: str) -> None:
    host = server_url.split("//", 1)[1].split(":")[0]
    monkeypatch.setattr(_cfg, "FETCH_ALLOWED_DOMAINS", (host,), raising=True)


class TestDomainAllowlist:
    def test_denied_when_no_domain_is_configured(self, server: str) -> None:
        out = _fetch.fetch_url(f"{server}/ok")
        assert not out.ok
        assert "not on the fetch domain allowlist" in out.error

    def test_disallowed_domain_is_never_connected_to(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The refusal happens before any socket opens -- proven, not assumed."""

        def _must_not_be_called(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("must not open a connection for a disallowed domain")

        monkeypatch.setattr(_fetch.urllib.request, "build_opener", _must_not_be_called)
        out = _fetch.fetch_url("http://example.test/ok")
        assert not out.ok
        assert "not on the fetch domain allowlist" in out.error

    def test_allowed_domain_succeeds(self, server: str, monkeypatch: pytest.MonkeyPatch) -> None:
        _allow(monkeypatch, server)
        out = _fetch.fetch_url(f"{server}/ok")
        assert out.ok
        assert "hello world" in out.content

    def test_only_http_and_https_schemes_are_fetchable(self) -> None:
        out = _fetch.fetch_url("ftp://example.test/file")
        assert not out.ok
        assert "unsupported scheme" in out.error

    def test_unparseable_host_is_refused(self) -> None:
        out = _fetch.fetch_url("http:///no-host")
        assert not out.ok
        assert "could not parse a host" in out.error


class TestResponseSizeCap:
    def test_large_response_is_truncated_with_an_announcement(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        monkeypatch.setattr(_cfg, "FETCH_MAX_RESPONSE_BYTES", 100, raising=True)
        out = _fetch.fetch_url(f"{server}/big")
        assert out.ok
        assert "[truncated: response exceeded 100 bytes]" in out.content
        # exactly 100 filler bytes were kept, not the full 5000
        assert out.content.count("z") == 100

    def test_response_under_the_cap_is_not_annotated(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        out = _fetch.fetch_url(f"{server}/ok")
        assert out.ok
        assert "[truncated" not in out.content


class TestTimeout:
    def test_a_slow_response_times_out(self, server: str, monkeypatch: pytest.MonkeyPatch) -> None:
        _allow(monkeypatch, server)
        out = _fetch.fetch_url(f"{server}/slow", timeout=1)
        assert not out.ok
        assert "timed out after 1s" in out.error

    def test_zero_timeout_falls_back_to_the_configured_default(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        monkeypatch.setattr(_cfg, "FETCH_TIMEOUT_S", 1.0, raising=True)
        out = _fetch.fetch_url(f"{server}/slow", timeout=0)
        assert not out.ok
        assert "timed out after 1" in out.error


class TestRedirects:
    def test_redirect_to_an_allowed_host_is_followed(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        out = _fetch.fetch_url(f"{server}/redirect-allowed")
        assert out.ok
        assert "hello world" in out.content

    def test_redirect_off_the_allowlist_is_refused(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        out = _fetch.fetch_url(f"{server}/redirect-blocked")
        assert not out.ok
        assert "not on the fetch domain allowlist" in out.error


class TestHTTPErrors:
    def test_404_is_reported_with_the_status_code(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        out = _fetch.fetch_url(f"{server}/missing")
        assert not out.ok
        assert "HTTP 404" in out.error


class TestGatedExactlyLikeABuiltin:
    """The registration itself must not create a second execution path."""

    def test_fetch_is_registered_as_a_read_kind_tool(self) -> None:
        tool = builtin_registry().get("fetch")
        assert tool is not None
        assert tool.kind == "read"
        assert tool.required_args == ("url",)

    def test_dispatch_tool_reaches_the_real_handler(
        self, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _allow(monkeypatch, server)
        ctx = ToolContext(agent_id="t", roots=(Path("/tmp"),))
        call = ToolCall(id="c1", name="fetch", arguments=json.dumps({"url": f"{server}/ok"}))
        res = dispatch_tool(call, ctx, builtin_registry())
        assert res.ok and res.executed
        assert "hello world" in res.content

    def test_missing_url_argument_is_denied_before_any_side_effect(self) -> None:
        ctx = ToolContext(agent_id="t", roots=(Path("/tmp"),))
        call = ToolCall(id="c1", name="fetch", arguments="{}")
        res = dispatch_tool(call, ctx, builtin_registry())
        assert res.denied and not res.executed
        assert "url" in res.reason

    def test_a_pre_tool_call_policy_gates_fetch_exactly_like_a_builtin(self) -> None:
        """A `pre_tool_call` policy denies a fetch call before the handler
        ever runs -- proof `fetch` runs through the existing gate
        (`evaluate_tool_call`) rather than around it."""
        _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
        doc = {
            "id": "no-fetch-test",
            "description": "test-only policy",
            "applies_to": ["*"],
            "hook": "pre_tool_call",
            "match": {"type": "regex", "pattern": r"^fetch\b"},
            "action": "block",
            "message": "fetch disabled by policy",
        }
        (_cfg.POLICIES_DIR / "no-fetch-test.json").write_text(json.dumps(doc), encoding="utf-8")

        ctx = ToolContext(agent_id="t", roots=(Path("/tmp"),))
        call = ToolCall(
            id="c1", name="fetch", arguments=json.dumps({"url": "http://example.test/ok"})
        )
        res = dispatch_tool(call, ctx, builtin_registry())
        assert res.denied and not res.executed
        assert "fetch disabled by policy" in res.reason
