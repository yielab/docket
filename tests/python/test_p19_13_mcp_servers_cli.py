"""P19-13: `docket mcp servers add/list/remove` -- a CLI over P19-10's client config.

P19-10 shipped `add_mcp_server`/`load_mcp_servers`/`remove_mcp_server` (`core/mcp_tools.py`) as
tested, uncalled library functions. This card's entire job is to give them a CLI --
`cli/_mcp.py`'s `_servers_list`/`_servers_add`/`_servers_remove`, dispatched from `run_mcp`. This
module is pure presentation: it validates flags and calls the existing `core/mcp_tools.py`
functions unchanged. It never talks to a remote server and never touches `core/tools.py` or any
built-in tool registration -- see `TestServersCliNeverReachesTheToolboxOrCoreTools` below, which
is the guard this card's own instructions call out by name ("stay inside your ownership row").

What's pinned here:

1. `list`/`add`/`remove` round-trip against the real `core/mcp_tools.py` functions (no
   reimplemented persistence logic).
2. `add`'s `--`-separator parsing: everything after a literal `--` is the server's launch command
   verbatim, so a command carrying its own flags (`npx -y ...`) is never misparsed as docket's own
   flags. Missing `--`, malformed `--env`, and an unknown flag before `--` are all rejected with an
   actionable error and exit 1 -- never a traceback.
3. `add_mcp_server`'s `ValueError` (bad/duplicate name) surfaces as a CLI error (exit 1), not a
   stack trace.
4. `add`/`remove` write an audit entry (`mcp_servers.add`/`mcp_servers.remove`) naming the server
   and (for `add`) its launch command -- and, security-load-bearing, an `--env` *value* is never
   written to the audit log or printed by `list` (masked as `KEY=****`), mirroring `keys.add`'s
   "name the secret, never its value" convention.
5. The CLI never imports a handler function from `edges/adapters/toolbox.py`, nor anything from
   `core/tools.py` -- the ownership-row guard for this card ("you may NOT touch core/tools.py at
   all... work through the public Tool/ToolRegistry.register API").
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _mcp
from docket.core import audit as _audit
from docket.core import mcp_tools as _mt

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "MCP_SERVERS_FILE", tmp_path / "mcp-servers.json", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)


def _audit_actions() -> list[str]:
    return [e["action"] for e in _audit.read_audit()]


def _audit_details(action: str) -> list[str]:
    return [e["detail"] for e in _audit.read_audit() if e["action"] == action]


# ── list ─────────────────────────────────────────────────────────────────────


class TestServersList:
    def test_no_servers_configured(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "No MCP servers configured" in out
        assert _audit_actions() == []  # read-only: never audited

    def test_shows_configured_server_and_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        _mt.add_mcp_server(_mt.McpServerConfig(name="weather", command="npx", args=["-y", "wx"]))
        rc = _mcp.run_mcp("servers", ["list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "weather" in out
        assert "npx -y wx" in out

    def test_env_values_are_masked_never_printed_in_the_clear(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mt.add_mcp_server(
            _mt.McpServerConfig(
                name="search", command="search-server", env={"SEARCH_API_KEY": "sk-super-secret"}
            )
        )
        out = capsys.readouterr().out  # drain the add's own output first
        rc = _mcp.run_mcp("servers", ["list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "SEARCH_API_KEY" in out
        assert "sk-super-secret" not in out

    def test_never_connects_to_a_server_pure_read(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`list` must be a pure `load_mcp_servers()` read -- proven by making
        `load_mcp_tools` (the only thing that would ever connect to a server)
        explode if called, then confirming `list` still succeeds."""

        def _boom(*a: object, **kw: object) -> None:
            raise AssertionError("docket mcp servers list must never call load_mcp_tools")

        monkeypatch.setattr(_mt, "load_mcp_tools", _boom, raising=True)
        _mt.add_mcp_server(_mt.McpServerConfig(name="weather", command="npx"))
        rc = _mcp.run_mcp("servers", ["list"])
        assert rc == 0


# ── add ──────────────────────────────────────────────────────────────────────


class TestServersAdd:
    def test_basic_add_persists_via_core_mcp_tools(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp(
            "servers", ["add", "playwright", "--", "npx", "-y", "@playwright/mcp@latest"]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "playwright" in out
        loaded = _mt.load_mcp_servers()
        assert len(loaded) == 1
        assert loaded[0].name == "playwright"
        assert loaded[0].command == "npx"
        assert loaded[0].args == ["-y", "@playwright/mcp@latest"]

    def test_env_and_timeout_flags_before_the_separator(self) -> None:
        rc = _mcp.run_mcp(
            "servers",
            [
                "add",
                "search",
                "--env",
                "SEARCH_API_KEY=sk-123",
                "--timeout",
                "20",
                "--",
                "search-server",
                "--flag-that-belongs-to-the-command",
            ],
        )
        assert rc == 0
        loaded = _mt.load_mcp_servers()[0]
        assert loaded.env == {"SEARCH_API_KEY": "sk-123"}
        assert loaded.timeout == 20.0
        assert loaded.command == "search-server"
        assert loaded.args == ["--flag-that-belongs-to-the-command"]

    def test_env_equals_flag_form(self) -> None:
        rc = _mcp.run_mcp("servers", ["add", "s", "--env=KEY=value", "--", "cmd"])
        assert rc == 0
        assert _mt.load_mcp_servers()[0].env == {"KEY": "value"}

    def test_missing_separator_is_rejected_not_misparsed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp("servers", ["add", "playwright", "npx", "-y", "@playwright/mcp@latest"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "--" in err
        assert _mt.load_mcp_servers() == []

    def test_no_command_after_separator_is_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp("servers", ["add", "playwright", "--"])
        assert rc == 1
        assert _mt.load_mcp_servers() == []

    def test_malformed_env_flag_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["add", "s", "--env", "NOT_KEY_VALUE", "--", "cmd"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "KEY=VALUE" in err
        assert _mt.load_mcp_servers() == []

    def test_malformed_timeout_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["add", "s", "--timeout", "not-a-number", "--", "cmd"])
        assert rc == 1
        assert _mt.load_mcp_servers() == []

    def test_unknown_flag_before_separator_is_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp("servers", ["add", "s", "--bogus", "--", "cmd"])
        assert rc == 1
        assert _mt.load_mcp_servers() == []

    def test_no_args_at_all_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["add"])
        assert rc == 1

    def test_duplicate_name_surfaces_as_a_cli_error_not_a_traceback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mt.add_mcp_server(_mt.McpServerConfig(name="weather", command="npx"))
        rc = _mcp.run_mcp("servers", ["add", "weather", "--", "npx", "-y", "wx2"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "already configured" in err
        # the original config survives untouched
        assert _mt.load_mcp_servers()[0].args == []

    def test_invalid_name_surfaces_as_a_cli_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["add", "not a valid name!", "--", "npx"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "letters, digits" in err

    def test_add_writes_an_audit_entry_naming_server_and_command(self) -> None:
        _mcp.run_mcp("servers", ["add", "playwright", "--", "npx", "-y", "@playwright/mcp@latest"])
        entries = _audit_details("mcp_servers.add")
        assert len(entries) == 1
        assert "playwright" in entries[0]
        assert "npx" in entries[0]

    def test_add_audit_entry_never_contains_an_env_secret_value(self) -> None:
        _mcp.run_mcp(
            "servers",
            ["add", "search", "--env", "SEARCH_API_KEY=sk-super-secret", "--", "search-server"],
        )
        entries = _audit_details("mcp_servers.add")
        assert len(entries) == 1
        assert "sk-super-secret" not in entries[0]

    def test_a_failed_add_writes_no_audit_entry(self) -> None:
        _mcp.run_mcp("servers", ["add", "s", "npx"])  # missing "--"
        assert _audit_actions() == []


# ── remove ───────────────────────────────────────────────────────────────────


class TestServersRemove:
    def test_removes_a_configured_server(self, capsys: pytest.CaptureFixture[str]) -> None:
        _mt.add_mcp_server(_mt.McpServerConfig(name="weather", command="npx"))
        rc = _mcp.run_mcp("servers", ["remove", "weather"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "removed" in out.lower()
        assert _mt.load_mcp_servers() == []

    def test_unknown_server_is_a_non_zero_noop(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["remove", "ghost"])
        assert rc == 1
        assert _audit_actions() == []

    def test_no_name_given_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _mcp.run_mcp("servers", ["remove"])
        assert rc == 1

    def test_remove_writes_an_audit_entry_naming_the_server(self) -> None:
        _mt.add_mcp_server(_mt.McpServerConfig(name="weather", command="npx"))
        _mcp.run_mcp("servers", ["remove", "weather"])
        entries = _audit_details("mcp_servers.remove")
        assert len(entries) == 1
        assert "weather" in entries[0]


# ── run_mcp dispatch / usage ─────────────────────────────────────────────────


class TestRunMcpServersDispatch:
    def test_bare_servers_prints_usage_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp("servers", [])
        out = capsys.readouterr().out
        assert rc == 0
        assert "docket mcp servers" in out

    def test_unknown_servers_subcommand_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _mcp.run_mcp("servers", ["bogus"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "docket mcp servers" in err

    def test_top_level_usage_still_mentions_serve(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Pre-existing test_l3_mcp_optional_dep.py::TestUsage asserts this
        substring against run_mcp(None, []) -- pinned again here so a future
        edit to the merged usage message cannot silently drop it."""
        rc = _mcp.run_mcp(None, [])
        err = capsys.readouterr().err
        assert rc == 0
        assert "docket mcp serve" in err
        assert "docket mcp servers" in err


# ── ownership-row guard: never reaches core/tools.py or a toolbox handler ────


class TestServersCliNeverReachesTheToolboxOrCoreTools:
    """This card's own ownership row: 'you may NOT touch core/tools.py at all,
    nor any built-in tool registration... work through the public Tool/
    ToolRegistry.register API, exactly as P19-10 did.' `docket mcp servers`
    doesn't even need the public API -- it never builds a Tool at all, only
    configuration -- so the bar here is stricter: cli/_mcp.py's servers
    commands must not import core.tools or a toolbox handler function at all.

    This mirrors test_p19_10_mcp_client.py's TestOnlyTheInertResultTypeIsImported
    for this card's own file.
    """

    FILE = "src/docket/cli/_mcp.py"

    def test_no_core_tools_import(self) -> None:
        path = REPO_ROOT / self.FILE
        tree = ast.parse(path.read_text())
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        offenders = {m for m in modules if m == "docket.core.tools" or m.endswith(".core.tools")}
        assert not offenders, f"{self.FILE} must never import core.tools: {offenders}"

    def test_no_toolbox_handler_import(self) -> None:
        path = REPO_ROOT / self.FILE
        tree = ast.parse(path.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "toolbox" in (node.module or ""):
                imported.update(alias.name for alias in node.names)
        assert not imported, f"{self.FILE} must never import from toolbox: {imported}"
