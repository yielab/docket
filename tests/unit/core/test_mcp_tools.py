"""MCP tools reachable in a live turn (`core/mcp_tools.py`).

Covers `DocketDriver.run_turn` calling `load_mcp_tools` via its
`mcp_loader` seam before per-turn role narrowing, and every MCP-adapted
tool registering `kind="write"` unconditionally so `registry_for_role`
excludes it by capability from a write-denied role. No real subprocess.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import mcp_tools as _mt
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolSpec, assistant
from docket.core.tools import ToolRegistry, builtin_registry
from docket.edges import store as _store
from docket.edges.adapters.docket_runtime import DocketDriver, _load_mcp_tools
from docket.edges.adapters.toolbox import ToolOutcome

SUBJECT = "docket.core.mcp_tools"


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repoint_docket_home(monkeypatch, tmp_path / "docket")
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


def _write_meta(agent_id: str, **overrides: object) -> Path:
    ws = _cfg.workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "role": "implementer", "model": "test/model"}
    data.update(overrides)
    _store.write_json(_cfg.meta_path(agent_id), data)
    return ws


class _ScriptedBackend:
    """Redefined locally, matching this suite's per-file convention (see
    test_docket_driver.py's identical docstring note)."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.tools_seen: list[Sequence[ToolSpec]] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        self.tools_seen.append(tools)
        return self._responses.pop(0)


def _final(text: str = "done") -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


def _remote(name: str = "danger_write") -> _mt.McpRemoteTool:
    return _mt.McpRemoteTool(
        name=name,
        description="does something to a file",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )


def _fake_mcp_loader(
    tools: tuple[_mt.McpRemoteTool, ...] = (),
    *,
    server_name: str = "fake",
) -> Any:
    """A `DocketDriver.mcp_loader`-shaped fake: registers *tools* into
    whatever registry it's handed, like `load_mcp_tools` for a server that
    answered instantly -- no subprocess, no `mcp` SDK involved."""

    def _loader(registry: ToolRegistry, role: str) -> list[_mt.McpServerLoadResult]:
        config = _mt.McpServerConfig(name=server_name, command="stub")
        return _mt.load_mcp_tools(
            registry,
            servers=[config],
            list_tools=lambda _c, _t: _mt.McpListResult(ok=True, tools=tools),
            call_tool=lambda *a: ToolOutcome(True, content="pwned"),
            role=role,
        )

    return _loader


def _unreachable_mcp_loader() -> Any:
    def _loader(registry: ToolRegistry, role: str) -> list[_mt.McpServerLoadResult]:
        config = _mt.McpServerConfig(name="down", command="stub")
        return _mt.load_mcp_tools(
            registry,
            servers=[config],
            list_tools=lambda _c, _t: _mt.McpListResult(ok=False, error="connection refused"),
            call_tool=lambda *a: ToolOutcome(False, error="unreachable"),
            role=role,
        )

    return _loader


def _malformed_mcp_loader() -> Any:
    """Simulates a listing that decodes into garbage, proving `load_mcp_tools`
    (and therefore the wired driver) degrades the same way the raw SDK
    boundary does when the injected `list_tools` itself misbehaves."""

    def _loader(registry: ToolRegistry, role: str) -> list[_mt.McpServerLoadResult]:
        def _boom(_c: _mt.McpServerConfig, _t: float) -> _mt.McpListResult:
            raise ValueError("malformed tool listing: not valid JSON-RPC")

        config = _mt.McpServerConfig(name="garbled", command="stub")
        return _mt.load_mcp_tools(
            registry,
            servers=[config],
            list_tools=_boom,
            call_tool=lambda *a: ToolOutcome(False, error="unreachable"),
            role=role,
        )

    return _loader


# ── the wire itself: DocketDriver actually calls load_mcp_tools ────────────


class TestDocketDriverCallsLoadMcpTools:
    def test_a_configured_servers_tool_is_advertised_to_the_model(self) -> None:
        _write_meta("impl-1", role="implementer")
        backend = _ScriptedBackend([_final()])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            mcp_loader=_fake_mcp_loader((_remote("get_forecast"),)),
        )

        result = driver.run_turn("impl-1", "agent:impl-1:default", "hi", 30)

        assert result.ok is True
        advertised = {spec.name for spec in backend.tools_seen[0]}
        assert "mcp__fake__get_forecast" in advertised

    def test_default_mcp_loader_is_the_real_load_mcp_tools_wrapper(self) -> None:
        """Wiring sanity: the production default is not a test-only stub."""
        assert DocketDriver().mcp_loader is _load_mcp_tools


# ── THE load-bearing test: role narrowing survives MCP tools ───────────────


class TestReviewerNeverGainsAWriteCapableMcpTool:
    """Every adapted MCP tool is `kind="write"` (`core/mcp_tools.py::_build_tool`),
    so excluding by kind, not name, is required: a name-based denylist could
    never catch `mcp__fake__danger_write` and would hand a Reviewer a write tool."""

    def test_reviewer_is_never_advertised_the_mcp_tool(self) -> None:
        _write_meta("rev-1", role="reviewer")
        backend = _ScriptedBackend([_final("noted")])
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            mcp_loader=_fake_mcp_loader((_remote(),)),
        )

        result = driver.run_turn("rev-1", "agent:rev-1:default", "review this", 30)

        assert result.ok is True
        advertised = {spec.name for spec in backend.tools_seen[0]}
        assert not any(name.startswith("mcp__") for name in advertised)
        assert "write" not in advertised and "edit" not in advertised and "bash" not in advertised

    def test_lead_also_loses_it_coordination_only(self) -> None:
        """Lead denies write/edit/bash exactly like Reviewer -- same kind set, same outcome, proving this isn't a Reviewer-only special case."""
        _write_meta("lead-1", role="lead")
        backend = _ScriptedBackend([_final()])
        driver = DocketDriver(
            backend_factory=lambda model: backend, mcp_loader=_fake_mcp_loader((_remote(),))
        )

        driver.run_turn("lead-1", "agent:lead-1:default", "coordinate", 30)

        advertised = {spec.name for spec in backend.tools_seen[0]}
        assert not any(name.startswith("mcp__") for name in advertised)

    def test_tester_loses_the_mcp_tool_but_keeps_bash(self) -> None:
        """Tester denies only write/edit (kind `write`) -- bash (kind `exec`) stays so it can run the suite it reports on, but the MCP tool (kind `write`) is excluded by the same rule as `write`/`edit`."""
        _write_meta("test-1", role="tester")
        backend = _ScriptedBackend([_final()])
        driver = DocketDriver(
            backend_factory=lambda model: backend, mcp_loader=_fake_mcp_loader((_remote(),))
        )

        driver.run_turn("test-1", "agent:test-1:default", "run the suite", 30)

        advertised = {spec.name for spec in backend.tools_seen[0]}
        assert not any(name.startswith("mcp__") for name in advertised)
        assert "bash" in advertised

    def test_implementer_does_get_the_mcp_tool(self) -> None:
        """Contrast case: the exclusion is role-specific (kind-implied by that role's own denied_tools), not a blanket ban on MCP tools -- an Implementer, already trusted with write/edit/bash, keeps it."""
        _write_meta("impl-2", role="implementer")
        backend = _ScriptedBackend([_final()])
        driver = DocketDriver(
            backend_factory=lambda model: backend, mcp_loader=_fake_mcp_loader((_remote(),))
        )

        driver.run_turn("impl-2", "agent:impl-2:default", "implement it", 30)

        advertised = {spec.name for spec in backend.tools_seen[0]}
        assert "mcp__fake__danger_write" in advertised

    def test_a_stale_client_calling_the_mcp_tool_anyway_is_refused_at_dispatch(self) -> None:
        """Belt and suspenders: even if a Reviewer's model somehow emitted a call for the excluded tool (a stale client, a hallucination), dispatch_tool must refuse it as unknown -- the same guarantee TestReviewerCannotDispatchAWrite proves for built-ins."""
        import json

        from docket.core.llm import ToolCall

        _write_meta("rev-2", role="reviewer")
        call = ToolCall(
            id="c1", name="mcp__fake__danger_write", arguments=json.dumps({"path": "x"})
        )
        backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final("refused, moving on"),
            ]
        )
        driver = DocketDriver(
            backend_factory=lambda model: backend, mcp_loader=_fake_mcp_loader((_remote(),))
        )

        result = driver.run_turn("rev-2", "agent:rev-2:default", "try it anyway", 30)

        assert result.ok is True
        tool_msg = next(m for m in backend.calls[1] if m.role == "tool")
        assert "unknown tool" in tool_msg.content
        assert "REFUSED" in tool_msg.content


# ── zero configured servers: byte-identical to before this card ────────────


class TestZeroServersIsUnchanged:
    def test_no_configured_servers_advertises_exactly_the_builtins(self) -> None:
        _write_meta("solo-1", role="implementer")
        backend = _ScriptedBackend([_final()])
        # Default mcp_loader (the real one) against an isolated,
        # never-written MCP_SERVERS_FILE -- the overwhelming common case.
        driver = DocketDriver(backend_factory=lambda model: backend)

        driver.run_turn("solo-1", "agent:solo-1:default", "hi", 30)

        advertised = sorted(spec.name for spec in backend.tools_seen[0])
        assert advertised == sorted(builtin_registry().names())

    def test_load_mcp_tools_with_zero_servers_does_not_touch_the_registry(self) -> None:
        registry = builtin_registry()
        before = set(registry.names())
        reports = _mt.load_mcp_tools(registry, role="implementer")
        assert reports == []
        assert set(registry.names()) == before


# ── failure isolation, through the wired driver ─────────────────────────────


class TestFailureIsolationThroughTheDriver:
    def test_an_unreachable_server_does_not_fail_an_otherwise_successful_turn(self) -> None:
        _write_meta("impl-3", role="implementer")
        backend = _ScriptedBackend([_final("carried on anyway")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, mcp_loader=_unreachable_mcp_loader()
        )

        result = driver.run_turn("impl-3", "agent:impl-3:default", "hi", 30)

        assert result.ok is True
        assert result.output == "carried on anyway"

    def test_a_malformed_listing_is_skipped_not_propagated(self) -> None:
        _write_meta("impl-4", role="implementer")
        backend = _ScriptedBackend([_final("still fine")])
        driver = DocketDriver(
            backend_factory=lambda model: backend, mcp_loader=_malformed_mcp_loader()
        )

        result = driver.run_turn("impl-4", "agent:impl-4:default", "hi", 30)

        assert result.ok is True
        advertised = {spec.name for spec in backend.tools_seen[0]}
        assert not any(name.startswith("mcp__") for name in advertised)
