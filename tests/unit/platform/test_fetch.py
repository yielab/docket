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
from docket.platform import fetch as _fetch

SUBJECT = "docket.platform.fetch"


_hermetic = _support_fetch.hermetic


class TestDomainAllowlist:
    def test_disallowed_domain_is_never_connected_to(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The refusal happens before any socket opens -- proven, not assumed."""

        def _must_not_be_called(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("must not open a connection for a disallowed domain")

        monkeypatch.setattr(_fetch.urllib.request, "build_opener", _must_not_be_called)
        out = _fetch.fetch_url("http://example.test/ok")
        assert not out.ok
        assert "not on the fetch domain allowlist" in out.error

    def test_only_http_and_https_schemes_are_fetchable(self) -> None:
        out = _fetch.fetch_url("ftp://example.test/file")
        assert not out.ok
        assert "unsupported scheme" in out.error

    def test_unparseable_host_is_refused(self) -> None:
        out = _fetch.fetch_url("http:///no-host")
        assert not out.ok
        assert "could not parse a host" in out.error


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
