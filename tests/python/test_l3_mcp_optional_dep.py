"""L-3: the optional `mcp` SDK dependency degrade path + real-SDK smoke test.

`docket mcp serve` needs the official MCP Python SDK (`mcp`), which is an
*optional* extra (`docket[mcp]`) — kept out of the base install so
`pip install docket` stays dependency-light (the SDK pulls in starlette,
uvicorn, cryptography, jsonschema, opentelemetry, ...). This file covers both
sides of that split:

  1. A real absence check (mirrors the existing PyYAML precedent in
     ``test_m4_final.py::test_from_yaml_without_pyyaml_gives_error`` — skip if
     the SDK happens to be installed in this environment, since then there is
     nothing to observe).
  2. A deterministic, environment-independent version of the same check that
     *simulates* the SDK being absent by making the import fail regardless of
     whether it is actually installed — so this file's coverage of the degrade
     path does not depend on luck about what happens to be in the test venv
     (this repo's own CI installs every extra via `uv sync --all-extras`).
  3. A real end-to-end smoke test through the actual SDK — skipped when the
     SDK is not installed (`pytest.importorskip`).

Either way the suite stays green: nothing here requires the SDK to be
installed to pass.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from typing import Any

import pytest

from docket.cli import _mcp


class TestMissingSdkRealAbsence:
    def test_serve_stdio_gives_actionable_hint_when_sdk_genuinely_absent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        try:
            import mcp  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("mcp SDK installed in this environment; cannot test genuine absence")

        rc = _mcp.serve_stdio()
        assert rc == 1
        err = capsys.readouterr().err
        assert "docket[mcp]" in err
        assert "pip install" in err


class TestMissingSdkSimulated:
    """Deterministic coverage of the same path, independent of what's installed."""

    def test_serve_stdio_gives_actionable_hint_via_simulated_import_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        real_import = builtins.__import__

        def _blocked_import(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            if name == "mcp.server.fastmcp" or name.startswith("mcp.server.fastmcp."):
                raise ImportError("simulated: mcp SDK not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)
        # Also evict any already-imported submodule so the blocked `__import__`
        # is actually exercised rather than served from sys.modules' cache.
        for name in list(sys.modules):
            if name == "mcp.server.fastmcp" or name.startswith("mcp.server.fastmcp."):
                monkeypatch.delitem(sys.modules, name, raising=False)

        rc = _mcp.serve_stdio()
        assert rc == 1
        err = capsys.readouterr().err
        assert err == _mcp.MISSING_SDK_HINT + "\n"

    def test_run_mcp_serve_returns_the_same_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _fake_serve_stdio() -> int:
            return 1

        monkeypatch.setattr(_mcp, "serve_stdio", _fake_serve_stdio)
        assert _mcp.run_mcp("serve", []) == 1


class TestUsage:
    def test_no_subcommand_prints_usage_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp(None, [])
        assert rc == 0
        err = capsys.readouterr().err
        assert "docket mcp serve" in err

    def test_unknown_subcommand_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("bogus", [])
        assert rc == 1

    def test_mcp_command_is_wired_on_the_typer_app(self) -> None:
        """Smoke-test only — never invokes `serve` (which would block on stdio
        or, if the SDK isn't installed, still just print+exit; either way this
        test proves wiring only, mirroring test_r3_runs_cli.py's pattern)."""
        from typer.testing import CliRunner

        from docket.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["mcp"])
        assert result.exit_code == 0
        assert "docket mcp serve" in result.output

    def test_mcp_is_a_top_level_command(self) -> None:
        import typer.main

        from docket.cli import app

        click_command = typer.main.get_command(app)
        assert "mcp" in click_command.commands


class TestRealSdkIntegration:
    """Only runs when the optional `mcp` SDK is actually installed."""

    def test_all_ten_tools_are_registered_with_the_real_sdk(self) -> None:
        pytest.importorskip("mcp")
        import asyncio

        server = _mcp._build_server()
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert names == set(_mcp._TOOL_NAMES)

    def test_a_real_call_through_the_sdk_round_trips_a_dict_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("mcp")
        import asyncio
        import json as _json

        import docket.config as _cfg
        from docket.edges.adapters import openclaw as _oc

        # Isolate from the real ~/.openclaw — this exercises a real tool call
        # (status → core.utils/serve.build_status → the ACL), so it must not
        # touch the developer's actual daemon config.
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        cfg_file = oc_dir / "openclaw.json"
        cfg_file.write_text(_json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))
        monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
        monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
        monkeypatch.setattr(_cfg, "AUDIT_LOG", oc_dir / "audit.log", raising=True)
        monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
        monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)

        server = _mcp._build_server()

        # mcp>=2.0's `MCPServer.call_tool` returns a `CallToolResult` object
        # (`.structured_content`/`.is_error`), not the 1.x line's
        # `(content, structured_dict)` tuple — see test_l6_mcp_sdk_v2.py for
        # the full migration write-up.
        async def _call() -> Any:
            return await server.call_tool("status", {})

        result = asyncio.run(_call())
        structured = result.structured_content
        assert isinstance(structured, dict)
        assert structured["apiVersion"] == "2"
        # Round-trips through the SDK's own JSON serialization too.
        assert _json.loads(_json.dumps(structured)) == structured
