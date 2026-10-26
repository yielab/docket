"""`docket start --mcp`'s contract holds against the real, installed `mcp` SDK.

Proves it through the SDK's own in-memory transport rather than by calling
`tool_*` directly (test_mcp_server.py's job): the dependency pin, the single
`MCPServer` code path, round-trip result/error/audit shape, and parity with
the CLI's own core state for a mutating tool.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from tests.support.escalations import approval_escalation
from tests.support.pods import seed_pod as _seed_pod
from tests.support.trace import audit_entries as _audit_actions

from docket.interfaces.cli.commands import mcp as _mcp
from docket.kernel.home import Home, use_home
from docket.platform import read_escalation
from docket.tasks.application.repository import TaskRepository

SUBJECT = "docket.interfaces.cli.commands.mcp"

_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


# ── 1. the pin itself ───────────────────────────────────────────────────────


class TestNoUpperBoundPin:
    def test_mcp_extra_has_no_ceiling(self) -> None:
        doc = tomllib.loads(_PYPROJECT.read_text())
        specs = doc["project"]["optional-dependencies"]["mcp"]
        assert len(specs) == 1
        assert specs[0].startswith("mcp>=2.0.0")
        assert "<" not in specs[0], f"expected no upper bound, got {specs[0]!r}"


# ── 2. one code path, on the real successor API ─────────────────────────────


class TestSingleCodePathOnRealSdk:
    def test_build_server_is_the_real_mcpserver_class(self) -> None:
        pytest.importorskip("mcp")
        server = _mcp._build_server()
        assert type(server).__name__ == "MCPServer"
        assert type(server).__module__.startswith("mcp.server")

    def test_build_server_source_has_no_fastmcp_reference_or_fallback(self) -> None:
        """`_build_server()` imports `mcp.server.MCPServer` and nothing else —
        no `try`/`except ImportError` chain between two SDK generations, no
        reference to the retired `fastmcp` module."""
        import inspect

        source = inspect.getsource(_mcp._build_server)
        assert "fastmcp" not in source.lower()
        assert "from mcp.server import MCPServer" in source

    def test_every_control_plane_tool_is_registered_with_the_real_sdk(self) -> None:
        pytest.importorskip("mcp")
        import asyncio

        server = _mcp._build_server()
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert names == set(_mcp._TOOL_NAMES)


# ── hermetic environment for the real-transport round trips below ──────────
# (mirrors test_mcp_server.py's fixtures — duplicated rather than
# cross-imported, matching this suite's existing convention of one
# self-contained module per test file)


async def _call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Round-trip through the real SDK's in-memory `Client`, not the bare `server.call_tool()`
    convenience method, which skips the exception-to-isError handling the stdio transport
    actually applies."""
    from mcp import Client

    async with Client(server) as client:
        return await client.call_tool(name, arguments)


# ── 3. real-transport round trip: structured_content + isError + audit ─────


class TestRealTransportRoundTrip:
    def test_status_round_trips_a_bare_dict_as_structured_content(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        import asyncio

        with _seed_pod(tmp_path):
            server = _mcp._build_server()

            result = asyncio.run(_call(server, "status", {}))
            assert result.is_error is False
            assert result.structured_content["apiVersion"] == "6"
            assert isinstance(result.structured_content["agents"], list)
            # Round-trips through the SDK's own JSON serialization too.
            assert json.loads(json.dumps(result.structured_content)) == result.structured_content

    def test_status_call_is_audited_exactly_once(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        import asyncio

        with _seed_pod(tmp_path):
            server = _mcp._build_server()
            asyncio.run(_call(server, "status", {}))
            assert len(_audit_actions("mcp.status")) == 1

    def test_a_raising_tool_becomes_an_iserror_result_not_a_protocol_crash(
        self, tmp_path: Path
    ) -> None:
        """A raised `McpToolError` surfaces as `isError=True`, never a crash."""
        # tool_runs raises for an unknown run id; over the real SDK transport
        # that must become an error result carrying the message, not an
        # uncaught exception that would kill the stdio session.
        pytest.importorskip("mcp")
        import asyncio

        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            server = _mcp._build_server()

            result = asyncio.run(_call(server, "runs", {"run_id": "run-does-not-exist"}))
            assert result.is_error is True
            text = "".join(getattr(block, "text", "") for block in result.content)
            assert "Unknown run" in text

    def test_audit_is_written_before_work_even_when_the_call_raises(self, tmp_path: Path) -> None:
        """A call that ends in `isError` still recorded exactly one audit entry."""
        # _audit() runs before the lookup that goes on to fail, so the
        # audit-before-work guarantee holds even over the real SDK transport.
        pytest.importorskip("mcp")
        import asyncio

        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            server = _mcp._build_server()

            result = asyncio.run(_call(server, "runs", {"run_id": "run-does-not-exist"}))
            assert result.is_error is True
            assert len(_audit_actions("mcp.runs")) == 1

    def test_unknown_escalation_is_audited_then_surfaces_as_iserror(self, tmp_path: Path) -> None:
        pytest.importorskip("mcp")
        import asyncio

        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            server = _mcp._build_server()

            result = asyncio.run(
                _call(server, "resolve", {"escalation_id": "esc-000000000000", "option_id": "deny"})
            )
            assert result.is_error is True
            text = "".join(getattr(block, "text", "") for block in result.content)
            assert "no escalation" in text
            # Audited even though nothing was resolved.
            assert len(_audit_actions("mcp.resolve")) == 1
            assert len(_audit_actions("escalation.resolve")) == 0

    def test_the_retired_approval_and_answer_tools_are_ordinary_unknowns(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio

        with use_home(Home(tmp_path / ".docket")):
            (tmp_path / ".docket").mkdir(exist_ok=True)
            server = _mcp._build_server()

            for name in ("approvals_list", "approvals_grant", "approvals_deny", "task_answer"):
                assert name not in _mcp._TOOL_NAMES
                result = asyncio.run(_call(server, name, {}))
                assert result.is_error is True
                assert _audit_actions(f"mcp.{name}") == []


# ── 4. no MCP-side bypass, proven end-to-end through the real transport ────


class TestNoBypassThroughRealTransport:
    def test_delegate_through_the_real_sdk_lands_in_the_same_queue_the_cli_uses(
        self, tmp_path: Path
    ) -> None:
        """A `delegate` call over the real transport lands in the CLI's own queue."""
        # Calls delegate through the real mcp.Client transport, not the Python
        # function directly, and confirms the task lands in the exact same
        # on-disk queue the CLI would write -- no parallel MCP-side write path.
        pytest.importorskip("mcp")
        import asyncio

        with _seed_pod(tmp_path, project="demo"):
            server = _mcp._build_server()

            result = asyncio.run(
                _call(server, "delegate", {"project": "demo", "description": "ship the migration"})
            )
            assert result.is_error is False
            assert result.structured_content["description"] == "ship the migration"

            tasks = TaskRepository.for_pod("demo").list()
            assert [t.description for t in tasks] == ["ship the migration"]

    def test_resolve_through_the_real_sdk_calls_the_same_core_function(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio

        with _seed_pod(tmp_path, project="demo"):
            escalation = approval_escalation("gate")
            server = _mcp._build_server()

            result = asyncio.run(
                _call(
                    server,
                    "resolve",
                    {"escalation_id": escalation.id, "option_id": "approve_once"},
                )
            )
            assert result.is_error is False
            assert result.structured_content == {
                "ok": True,
                "escalation": escalation.id,
                "state": "resolved",
            }
            # The exact escalation transition happened -- not a parallel one.
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.state == "resolved"
            entry = _audit_actions("escalation.resolve")[-1]
            assert f"escalation={escalation.id}" in entry["detail"]
            assert "channel=mcp" in entry["detail"]


# ── stdio discipline sanity: no tool import ever pulls in docket.interfaces.cli.render.ui ────────


class TestNoUiImportEvenWithTheSdkInstalled:
    def test_mcp_module_source_never_references_ui(self) -> None:
        """`interfaces/cli/commands/mcp.py` never imports or calls `docket.interfaces.cli.render.ui`."""
        # Rich output to stdout would corrupt the stdio JSON-RPC stream;
        # re-checked here with the real SDK installed.
        pytest.importorskip("mcp")
        import importlib

        importlib.reload(_mcp)
        import_lines = [
            ln.strip()
            for ln in Path(_mcp.__file__).read_text().splitlines()
            if ln.strip().startswith(("import ", "from "))
        ]
        assert not any(
            "docket.interfaces.cli.render.ui" in ln or "docket import ui" in ln
            for ln in import_lines
        )
        assert "ui" not in dir(_mcp)
