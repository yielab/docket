"""L-6: migrate `docket mcp serve` to the current (2.x) `mcp` SDK.

L-3 shipped `docket mcp serve` against the SDK's 1.x line
(`mcp.server.fastmcp.FastMCP`), pinned defensively at `mcp>=1.2.0,<2.0.0`
because that agent could not verify what the SDK's 2.0 API actually looked
like. This card installs the real `mcp==2.0.0` release and reads the shipped
package directly: `mcp.server.fastmcp` was removed outright in 2.0 (not
deprecated in place) and replaced by `mcp.server.MCPServer` — a rename and
relocation, not a redesign. `MCPServer` keeps `FastMCP`'s exact registration
ergonomics (`add_tool(fn, name=...)`, `server.run(transport="stdio")`), so
`cli/_mcp.py`'s `_build_server()` needed only an import-path/class-name swap;
every `tool_*` function (the plain-Python layer with no `mcp` import) is
untouched.

This file's job is to *prove* — against the real installed SDK, not by
inspection — that the migration didn't quietly change the contract:

  1. the `docket[mcp]` pin has no upper bound anymore (the whole point of the
     migration);
  2. `_build_server()` really is built on `mcp.server.MCPServer`, and
     `mcp.server.fastmcp` genuinely no longer exists to fall back to — there
     is exactly one code path, not a version-sniffing shim;
  3. a full round trip through the real SDK's in-memory transport
     (`mcp.Client` talking to the `MCPServer` instance, which exercises the
     same request-dispatch/exception-handling code the stdio transport uses)
     still round-trips a tool's bare-dict return as `structured_content`,
     still turns a raised `McpToolError` into an `isError` result, and the
     audit-before-work guarantee (an `mcp.<tool>` entry written before/
     regardless of whether the call raises) still holds;
  4. a mutating tool called through that same real transport still lands in
     the exact `core/` state the CLI itself would produce — no MCP-side
     bypass, proven end-to-end through the actual SDK rather than by calling
     the Python function directly (which is what test_l3_mcp_server.py
     already covers).

All of this is skipped (`pytest.importorskip("mcp")`) when the optional
extra isn't installed — this file is real-SDK-only coverage, matching
test_l3_mcp_optional_dep.py's `TestRealSdkIntegration` precedent. The rest of
the suite (test_l3_mcp_server.py's tool-layer tests) needs no SDK at all.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _mcp
from docket.cli import _pod as _pod_cli
from docket.core import approval as _approval
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch

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
        """Documents the actual finding this migration is based on: `mcp` 2.0
        removed `mcp.server.fastmcp` outright rather than deprecating it in
        place, so there is nothing left to fall back to and no reason for a
        version-sniffing shim in `cli/_mcp.py`."""
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
# (mirrors test_l3_mcp_server.py's fixtures — duplicated rather than
# cross-imported, matching this suite's existing convention of one
# self-contained module per test file)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", home / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "RUNS_FILE", home / "docket-runs.json", raising=True)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
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
        """`tool_runs` raises `McpToolError` for an unknown run id; through the
        real SDK transport that MUST surface as `CallToolResult(isError=True)`
        carrying the message, never an uncaught exception that would kill the
        stdio session."""
        pytest.importorskip("mcp")
        import asyncio

        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        server = _mcp._build_server()

        result = asyncio.run(_call(server, "runs", {"run_id": "run-does-not-exist"}))
        assert result.is_error is True
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "Unknown run" in text

    def test_audit_is_written_before_work_even_when_the_call_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The audit-before-work guarantee re-proved through the real SDK
        transport: even a call that ends in `isError` still recorded exactly
        one `mcp.<tool>` entry, because `_audit()` runs before the lookup that
        goes on to fail."""
        pytest.importorskip("mcp")
        import asyncio

        _point_at(tmp_path / ".docket", monkeypatch)
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

        _point_at(tmp_path / ".docket", monkeypatch)
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
        """Calls `delegate` through the real `mcp.Client` transport (not the
        Python function directly) and confirms the task lands in the exact
        same on-disk queue `core.dispatch.enqueue_task`/the CLI would write —
        proving there is no parallel MCP-side write path even when the call
        arrives through the actual SDK's request/response cycle."""
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

        _point_at(tmp_path / ".docket", monkeypatch)
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
        """`cli/_mcp.py` must never import or call `docket.ui` (Rich output to
        stdout would corrupt the stdio JSON-RPC stream) — re-checked here with
        the real SDK installed, in case adding it changed anything at import
        time."""
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
