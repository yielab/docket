"""`docket mcp serve`'s contract holds against the real, installed `mcp` SDK.

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
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _mcp
from docket.cli import _pod as _pod_cli
from docket.core import approval as _approval
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch

SUBJECT = "docket.core"

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


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
    def test_fastmcp_module_no_longer_exists(self) -> None:
        """`mcp.server.fastmcp` is removed outright, not deprecated in place."""
        # Nothing left to fall back to, and no reason for a version-sniffing
        # shim in cli/_mcp.py.
        pytest.importorskip("mcp")
        with pytest.raises(ModuleNotFoundError):
            import mcp.server.fastmcp  # noqa: F401

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

    def test_all_ten_tools_are_registered_with_the_real_sdk(self) -> None:
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


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    _pod_cli.build_pod(project, _pod_cli.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _audit_actions(action: str) -> list[dict[str, Any]]:
    return [e for e in _audit.read_audit() if e["action"] == action]


async def _call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Round-trip a tool call through the real SDK's in-memory `Client`
    transport (not the bare `server.call_tool()` convenience method, which
    does not go through the same exception-to-isError handling the stdio
    transport actually uses) — see `mcp.Client`'s own docs: it can talk
    straight to a server object with no network/subprocess in between, which
    is exactly the "real dispatch path, no transport" fixture this needs."""
    from mcp import Client

    async with Client(server) as client:
        return await client.call_tool(name, arguments)


# ── 3. real-transport round trip: structured_content + isError + audit ─────


class TestRealTransportRoundTrip:
    def test_status_round_trips_a_bare_dict_as_structured_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio

        _seed_pod(tmp_path, monkeypatch)
        server = _mcp._build_server()

        result = asyncio.run(_call(server, "status", {}))
        assert result.is_error is False
        assert result.structured_content["apiVersion"] == "2"
        assert isinstance(result.structured_content["agents"], list)
        # Round-trips through the SDK's own JSON serialization too.
        assert json.loads(json.dumps(result.structured_content)) == result.structured_content

    def test_status_call_is_audited_exactly_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio

        _seed_pod(tmp_path, monkeypatch)
        server = _mcp._build_server()
        asyncio.run(_call(server, "status", {}))
        assert len(_audit_actions("mcp.status")) == 1

    def test_a_raising_tool_becomes_an_iserror_result_not_a_protocol_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raised `McpToolError` surfaces as `isError=True`, never a crash."""
        # tool_runs raises for an unknown run id; over the real SDK transport
        # that must become an error result carrying the message, not an
        # uncaught exception that would kill the stdio session.
        pytest.importorskip("mcp")
        import asyncio

        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        (tmp_path / ".docket").mkdir(exist_ok=True)
        server = _mcp._build_server()

        result = asyncio.run(_call(server, "runs", {"run_id": "run-does-not-exist"}))
        assert result.is_error is True
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "Unknown run" in text

    def test_audit_is_written_before_work_even_when_the_call_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A call that ends in `isError` still recorded exactly one audit entry."""
        # _audit() runs before the lookup that goes on to fail, so the
        # audit-before-work guarantee holds even over the real SDK transport.
        pytest.importorskip("mcp")
        import asyncio

        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        (tmp_path / ".docket").mkdir(exist_ok=True)
        server = _mcp._build_server()

        result = asyncio.run(_call(server, "runs", {"run_id": "run-does-not-exist"}))
        assert result.is_error is True
        assert len(_audit_actions("mcp.runs")) == 1

    def test_unknown_approval_token_is_audited_then_surfaces_as_iserror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio

        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        (tmp_path / ".docket").mkdir(exist_ok=True)
        server = _mcp._build_server()

        result = asyncio.run(_call(server, "approvals_grant", {"token": "apr-does-not-exist"}))
        assert result.is_error is True
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "not found" in text
        # Audited even though the underlying grant never happened.
        assert len(_audit_actions("mcp.approvals_grant")) == 1
        assert len(_audit_actions("approval.grant")) == 0


# ── 4. no MCP-side bypass, proven end-to-end through the real transport ────


class TestNoBypassThroughRealTransport:
    def test_delegate_through_the_real_sdk_lands_in_the_same_queue_the_cli_uses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `delegate` call over the real transport lands in the CLI's own queue."""
        # Calls delegate through the real mcp.Client transport, not the Python
        # function directly, and confirms the task lands in the exact same
        # on-disk queue the CLI would write -- no parallel MCP-side write path.
        pytest.importorskip("mcp")
        import asyncio

        _seed_pod(tmp_path, monkeypatch, project="demo")
        server = _mcp._build_server()

        result = asyncio.run(
            _call(server, "delegate", {"project": "demo", "description": "ship the migration"})
        )
        assert result.is_error is False
        assert result.structured_content["description"] == "ship the migration"

        tasks = _dispatch.read_tasks("demo")
        assert [t["description"] for t in tasks] == ["ship the migration"]

    def test_approvals_grant_through_the_real_sdk_calls_the_same_core_function(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio

        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        (tmp_path / ".docket").mkdir(exist_ok=True)
        token = _approval.approval_create("demo", "implementer", "deploy prod")
        server = _mcp._build_server()

        result = asyncio.run(_call(server, "approvals_grant", {"token": token}))
        assert result.is_error is False
        assert result.structured_content == {"ok": True, "token": token, "state": "granted"}
        # The exact core.approval state transition happened — not a parallel one.
        assert _approval.approval_get(token)["state"] == "granted"
        entry = _audit_actions("approval.grant")[-1]
        assert entry["detail"] == f"token={token} project=demo channel=mcp"


# ── stdio discipline sanity: no tool import ever pulls in docket.ui ────────


class TestNoUiImportEvenWithTheSdkInstalled:
    def test_mcp_module_source_never_references_ui(self) -> None:
        """`cli/_mcp.py` never imports or calls `docket.ui`."""
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
        assert not any("docket.ui" in ln or "docket import ui" in ln for ln in import_lines)
        assert "ui" not in dir(_mcp)
