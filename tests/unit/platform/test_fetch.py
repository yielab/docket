"""The `fetch` tool -- an inspectable, allowlisted egress path (`platform/fetch.py`).

Pins the domain allowlist as real containment (redirects included), the
response size cap and timeout with announced truncation, and that `fetch`
is gated exactly like any other built-in through the real, unmodified
`dispatch_tool`. The wire-level tests are in tests/integration/platform/test_fetch__wire.py.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from tests.support import fetch as _support_fetch

from docket.agent.ports import ToolCall
from docket.agent.tools.registry import ToolContext, dispatch_tool
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import ToolOutcome
from docket.platform import fetch as _fetch

SUBJECT = "docket.platform.fetch"


_hermetic = _support_fetch.hermetic


class TestDomainAllowlist:
    def test_disallowed_domain_is_never_connected_to(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The refusal happens before any socket opens -- proven, not assumed."""

        def _must_not_be_called(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("must not open a connection for a disallowed domain")

        monkeypatch.setattr(_fetch, "build_opener", _must_not_be_called)
        out = _fetch.fetch_url("http://example.test/ok", ())
        assert not out.ok
        assert "not on the fetch domain allowlist" in out.error

    def test_only_http_and_https_schemes_are_fetchable(self) -> None:
        out = _fetch.fetch_url("ftp://example.test/file", ())
        assert not out.ok
        assert "unsupported scheme" in out.error

    @pytest.mark.parametrize(
        ("host", "allowed", "reached"),
        [
            ("a.example.org", ("*.example.org",), True),
            ("b.a.example.org", ("*.example.org",), True),
            ("example.org", ("*.example.org",), False),
            ("badexample.org", ("*.example.org",), False),
            ("example.org.evil.test", ("*.example.org",), False),
            ("docs.python.org", ("docs.python.org",), True),
            ("x.docs.python.org", ("docs.python.org",), False),
            ("EXAMPLE.org", ("example.org",), True),
            ("anywhere.test", ("*",), True),
            ("anywhere.test", (), False),
        ],
    )
    def test_the_wildcard_matches_subdomains_and_never_the_apex(
        self, monkeypatch: pytest.MonkeyPatch, host: str, allowed: tuple[str, ...], reached: bool
    ) -> None:
        opened: list[object] = []

        def _opener(*_args: object, **_kwargs: object) -> _FakeOpener:
            opened.append(_args)
            return _FakeOpener(_FakeResponse(b"ok", "text/plain"))

        monkeypatch.setattr(_fetch, "build_opener", _opener)
        out = _fetch.fetch_url(f"http://{host}/page", allowed)
        assert out.ok is reached
        assert bool(opened) is reached
        if not reached:
            assert out.refusal == "fetch_not_allowed"

    def test_the_perimeter_gets_the_one_matcher_and_only_the_exact_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        given: list[tuple[object, ...]] = []

        def _opener(*args: object, **_kwargs: object) -> _FakeOpener:
            given.append(args)
            return _FakeOpener(_FakeResponse(b"ok", "text/plain"))

        monkeypatch.setattr(_fetch, "build_opener", _opener)
        allowed = ("*.example.org", "SearXNG.lan", "localhost", "*")
        _fetch.fetch_url("http://searxng.lan/", allowed)
        ((permits, exact),) = given
        assert exact == frozenset({"searxng.lan", "localhost"})  # type: ignore[comparison-overlap]
        assert permits("anything.test") is True  # type: ignore[operator]  # the `*` entry
        _fetch.fetch_url("http://a.example.org/", ("*.example.org", "x.test"))
        permits, exact = given[1]
        assert permits("b.a.example.org") is True  # type: ignore[operator]
        assert permits("example.org") is False  # type: ignore[operator]
        assert exact == frozenset({"x.test"})

    def test_unparseable_host_is_refused(self) -> None:
        out = _fetch.fetch_url("http:///no-host", ())
        assert not out.ok
        assert "could not parse a host" in out.error


_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "fetch"


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type} if content_type else {}
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read1(self, n: int) -> bytes:
        chunk, self._body = self._body[:n], self._body[n:]
        return chunk


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def open(self, _request: object, timeout: float = 0) -> _FakeResponse:
        return self._response


def _outcome_with(
    monkeypatch: pytest.MonkeyPatch, body: bytes, content_type: str, **home_changes: object
) -> ToolOutcome:
    monkeypatch.setattr(
        _fetch,
        "build_opener",
        lambda *_args, **_kwargs: _FakeOpener(_FakeResponse(body, content_type)),
    )
    home = dataclasses.replace(
        current_home(),
        fetch_allowed_domains=("pages.example.test",),
        tool_max_output_chars=100_000,
        **home_changes,
    )
    with use_home(home):
        return _fetch.fetch_url("http://pages.example.test/page", ("pages.example.test",))


def _pdf_with(
    monkeypatch: pytest.MonkeyPatch, body: bytes, content_type: str, **home_changes: object
) -> ToolOutcome | _fetch.FetchedPdf:
    monkeypatch.setattr(
        _fetch,
        "build_opener",
        lambda *_args, **_kwargs: _FakeOpener(_FakeResponse(body, content_type)),
    )
    home = dataclasses.replace(current_home(), fetch_allowed_domains=("pages.example.test",))
    with use_home(dataclasses.replace(home, **home_changes)):  # type: ignore[arg-type]
        return _fetch.fetch_url("http://pages.example.test/page", ("pages.example.test",))


def _fetch_with(
    monkeypatch: pytest.MonkeyPatch, body: bytes, content_type: str, **home_changes: object
) -> str:
    out = _outcome_with(monkeypatch, body, content_type, **home_changes)
    assert out.ok, out.error
    return out.content


class TestOnlyTextArrives:
    @pytest.mark.parametrize(
        "content_type",
        [
            "text/plain",
            "TEXT/HTML; charset=utf-8",
            "text/csv",
            "application/json",
            "application/ld+json",
            "application/json; charset=utf-8",
            "application/xml",
            "application/atom+xml",
            "application/xhtml+xml",
            "application/javascript",
            "application/vnd.api+json",
        ],
    )
    def test_a_text_type_passes(self, monkeypatch: pytest.MonkeyPatch, content_type: str) -> None:
        out = _outcome_with(monkeypatch, b"plain words", content_type)
        assert out.ok, out.error
        assert "plain words" in out.content

    @pytest.mark.parametrize(
        "content_type",
        [
            "application/octet-stream",
            "application/zip",
            "application/x-tar",
            "image/png",
            "audio/mpeg",
            "video/mp4",
            "font/woff2",
            "application/msword",
        ],
    )
    def test_a_binary_type_is_refused_and_none_of_the_body_arrives(
        self, monkeypatch: pytest.MonkeyPatch, content_type: str
    ) -> None:
        out = _outcome_with(monkeypatch, b"%PDF-1.7 secret words", content_type)
        media = content_type.split(";")[0].strip().lower()
        assert not out.ok
        assert out.content == ""
        assert out.refusal == "fetch_not_allowed"
        assert out.error == f"content type {media!r} is not text; fetch reads text pages"
        assert "secret words" not in out.error

    def test_a_body_that_only_starts_like_a_pdf_is_not_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = _outcome_with(monkeypatch, b"%PDF\x00 secret words", "image/png")
        assert not out.ok
        assert out.content == ""
        assert out.refusal == "fetch_not_allowed"

    def test_a_body_with_no_type_is_text_when_it_has_no_nul_byte(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = _outcome_with(monkeypatch, "caf\u00e9 au lait".encode(), "")
        assert out.ok
        assert out.content == "caf\u00e9 au lait"

    def test_a_body_with_no_type_and_a_nul_byte_in_its_first_8k_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = _outcome_with(monkeypatch, b"%PDF" + b"\x00" * 10 + b"secret words", "")
        assert not out.ok
        assert out.content == ""
        assert out.refusal == "fetch_not_allowed"
        assert "binary" in out.error
        assert "fetch reads text pages" in out.error

    def test_a_nul_byte_past_the_first_8k_does_not_make_an_untyped_body_binary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = _outcome_with(monkeypatch, b"a" * 8192 + b"\x00", "")
        assert out.ok


class TestAPdfArrivesAsBytes:
    """`fetch_url` hands a PDF to its caller as typed bytes; it never reads one as text."""

    @pytest.mark.parametrize("content_type", ["application/pdf", "Application/PDF; charset=binary"])
    def test_a_pdf_type_comes_back_as_bytes_beside_its_type(
        self, monkeypatch: pytest.MonkeyPatch, content_type: str
    ) -> None:
        body = b"%PDF-1.7 \x00\x01 binary words"
        got = _pdf_with(monkeypatch, body, content_type)
        assert isinstance(got, _fetch.FetchedPdf)
        assert (got.status, got.content_type, got.body) == (200, content_type, body)

    def test_a_body_with_no_type_that_starts_with_the_pdf_marker_is_a_pdf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\x00 words"
        got = _pdf_with(monkeypatch, body, "")
        assert isinstance(got, _fetch.FetchedPdf)
        assert got.body == body
        assert got.content_type == ""

    def test_a_declared_text_body_that_starts_with_the_marker_stays_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        got = _pdf_with(monkeypatch, b"%PDF-1.7 about the format", "text/plain")
        assert isinstance(got, ToolOutcome)
        assert got.ok

    def test_a_pdf_over_the_response_cap_arrives_whole(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = b"%PDF-1.7 " + b"a" * 300_000
        got = _pdf_with(monkeypatch, body, "application/pdf", fetch_max_response_bytes=1000)
        assert isinstance(got, _fetch.FetchedPdf)
        assert got.body == body

    @pytest.mark.parametrize("content_type", ["application/pdf", ""])
    def test_a_pdf_over_the_document_cap_is_refused_whole_naming_the_setting(
        self, monkeypatch: pytest.MonkeyPatch, content_type: str
    ) -> None:
        got = _pdf_with(
            monkeypatch,
            b"%PDF-1.7 secret words" + b"a" * 100,
            content_type,
            fetch_max_document_bytes=100,
        )
        assert isinstance(got, ToolOutcome)
        assert not got.ok
        assert got.content == ""
        assert got.refusal == "fetch_not_allowed"
        assert "FETCH_MAX_DOCUMENT_BYTES" in got.error
        assert "secret words" not in got.error

    def test_a_pdf_exactly_at_the_document_cap_arrives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = b"%PDF-1.7" + b"a" * 92
        got = _pdf_with(monkeypatch, body, "application/pdf", fetch_max_document_bytes=100)
        assert isinstance(got, _fetch.FetchedPdf)

    def test_a_pdf_carries_the_calls_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        got = _pdf_with(monkeypatch, b"%PDF-1.7", "application/pdf")
        assert isinstance(got, _fetch.FetchedPdf)
        assert got.deadline > 0

    def test_an_untyped_text_body_over_the_response_cap_is_still_cut_and_announced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        got = _pdf_with(monkeypatch, b"a" * 50, "", fetch_max_response_bytes=10)
        assert isinstance(got, ToolOutcome)
        assert got.ok
        assert "[truncated: response exceeded 10 bytes]" in got.content


class TestHtmlArrivesAsText:
    def test_a_page_becomes_the_committed_text_under_15_percent_of_its_length(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = (_FIXTURES / "page.html").read_bytes()
        expected = (_FIXTURES / "page.txt").read_text()
        content = _fetch_with(monkeypatch, html, "text/html; charset=utf-8")
        header, _, text = content.partition("\n\n")
        assert header == f"HTTP 200 text/html; charset=utf-8; {len(expected)} chars of text"
        assert text == expected
        assert len(text) < 0.15 * len(html)

    def test_a_body_that_starts_like_html_is_converted_whatever_its_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content = _fetch_with(monkeypatch, b"  <!DOCTYPE html><p>one</p><p>two</p>", "text/plain")
        assert content.endswith("\n\none\n\ntwo")
        assert content.startswith("HTTP 200 text/plain; 8 chars of text")

    def test_json_and_plain_text_pass_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = b'{"a": "<p>not html</p>"}'
        assert (
            _fetch_with(monkeypatch, body, "application/json")
            == 'HTTP 200 application/json\n\n{"a": "<p>not html</p>"}'
        )
        assert (
            _fetch_with(monkeypatch, b"a  b\n\n\nc", "text/plain")
            == "HTTP 200 text/plain\n\na  b\n\n\nc"
        )

    def test_a_truncated_page_is_converted_and_the_truncation_still_announced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = b"<html><body><p>" + b"word " * 100 + b"</p></body></html>"
        content = _fetch_with(monkeypatch, html, "text/html", fetch_max_response_bytes=40)
        assert "<" not in content
        assert content.endswith("[truncated: response exceeded 40 bytes]")


class TestGatedExactlyLikeABuiltin:
    """The registration itself must not create a second execution path."""

    """The registration itself must not create a second execution path."""

    def test_fetch_is_registered_as_a_read_kind_tool(self) -> None:
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            tool = builtin_registry().get("fetch")
            assert tool is not None
            assert tool.kind == "read"
            assert tool.required_args == ("url",)

    def test_an_empty_allowlist_leaves_fetch_out_of_the_offered_tools(self) -> None:
        registry = builtin_registry()
        assert "fetch" not in registry.names()
        assert "fetch" not in [spec.name for spec in registry.specs()]

    def test_a_configured_allowlist_offers_fetch(self) -> None:
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            assert "fetch" in builtin_registry().names()

    def test_a_call_to_an_unoffered_fetch_is_refused_like_an_unknown_tool(self) -> None:
        ctx = ToolContext(agent_id="t", roots=(Path("/tmp"),))
        call = ToolCall(
            id="c1", name="fetch", arguments=json.dumps({"url": "http://example.test/ok"})
        )
        res = dispatch_tool(call, ctx, builtin_registry())
        assert res.denied and not res.executed

    def test_missing_url_argument_is_denied_before_any_side_effect(self) -> None:
        with use_home(
            dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        ):
            ctx = ToolContext(agent_id="t", roots=(Path("/tmp"),))
            call = ToolCall(id="c1", name="fetch", arguments="{}")
            res = dispatch_tool(call, ctx, builtin_registry())
            assert res.denied and not res.executed
            assert "url" in res.reason

    def test_a_pre_tool_call_policy_gates_fetch_exactly_like_a_builtin(self) -> None:
        """A `pre_tool_call` policy denies a fetch call before the handler ever runs -- proof `fetch` runs through the existing gate (`evaluate_tool_call`) rather than around it."""
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        doc = {
            "kind": "policy",
            "name": "no-fetch-test",
            "description": "test-only policy",
            "appliesTo": ["*"],
            "on": "toolCall",
            "when": {"matches": r"^fetch\b"},
            "then": "block",
            "message": "fetch disabled by policy",
        }
        (current_home().policies_dir / "no-fetch-test.json").write_text(
            json.dumps(doc), encoding="utf-8"
        )
        with use_home(dataclasses.replace(current_home(), fetch_allowed_domains=("example.test",))):
            ctx = ToolContext(agent_id="t", roots=(Path("/tmp"),))
            call = ToolCall(
                id="c1", name="fetch", arguments=json.dumps({"url": "http://example.test/ok"})
            )
            res = dispatch_tool(call, ctx, builtin_registry())
            assert res.denied and not res.executed
            assert "fetch disabled by policy" in res.reason
