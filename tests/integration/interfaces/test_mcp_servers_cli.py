"""`docket setup mcp add/list/remove` -- a CLI over the MCP client config.
Pure presentation over the tested `agent/tools/mcp_tools.py` functions (`add_mcp_server`/
`load_mcp_servers`/`remove_mcp_server`): validates flags, calls them unchanged, never talks to a
remote server, and never touches `agent/tools/registry.py` or built-in tool registration (the ownership-row
guard checked by `TestServersCliNeverReachesTheToolboxOrCoreTools` below).
Pins: `add`'s `--`-separator (everything after a literal `--` is the launch command verbatim;
a missing command, malformed `--env`, or an unknown flag before it all reject, never a
traceback); a bad/duplicate name's `ValueError` surfacing the same way; `add`/`remove`
writing an audit entry that never carries an `--env` *value* in the clear (masked `KEY=****` in
both the audit log and `list`, mirroring `keys.add`). See specs/functional/mcp-client.spec.md
Requirements 21-24.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.trace import audit_actions as _audit_actions
from typer.testing import CliRunner

from docket.agent.tools import mcp_tools as _mt
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.interfaces.cli.app import app
from docket.kernel import mcp as _mcp
from docket.kernel.home import Home, current_home, use_home
from docket.teams import mcp_servers as _mcp_servers

SUBJECT = "docket.interfaces.cli.commands.setup_mcp"

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path) -> Iterator[None]:
    with use_home(
        dataclasses.replace(current_home(), mcp_servers_file_override=tmp_path / "mcp-servers.json")
    ):
        yield


_runner = CliRunner()


def _mcp_run(args: list[str]) -> tuple[int, str, str]:
    result = _runner.invoke(app, ["setup", "mcp", *args])
    return result.exit_code, result.stdout, result.stderr


def _audit_details(action: str) -> list[str]:
    return [e["detail"] for e in _audit.read_audit() if e["action"] == action]


# ── list ─────────────────────────────────────────────────────────────────────


class TestServersList:
    def test_no_servers_configured(self) -> None:
        rc, out, _ = _mcp_run(["list"])
        assert rc == 0
        assert "No MCP servers configured" in out
        assert _audit_actions() == []  # read-only: never audited

    def test_shows_configured_server_and_command(self) -> None:
        _mcp_servers.add_mcp_server(
            _mcp.McpServerConfig(name="weather", command="npx", args=["-y", "wx"])
        )
        rc, out, _ = _mcp_run(["list"])
        assert rc == 0
        assert "weather" in out
        assert "npx -y wx" in out

    def test_env_values_are_masked_never_printed_in_the_clear(self) -> None:
        _mcp_servers.add_mcp_server(
            _mcp.McpServerConfig(
                name="search", command="search-server", env={"SEARCH_API_KEY": "tok-super-secret"}
            )
        )
        rc, out, _ = _mcp_run(["list"])
        assert rc == 0
        assert "SEARCH_API_KEY" in out
        assert "tok-super-secret" not in out

    def test_never_connects_to_a_server_pure_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`list` must be a pure `load_mcp_servers()` read -- proven by making
        `load_mcp_tools` (the only thing that would ever connect to a server)
        explode if called, then confirming `list` still succeeds."""

        def _boom(*a: object, **kw: object) -> None:
            raise AssertionError("docket setup mcp list must never call load_mcp_tools")

        monkeypatch.setattr(_mt, "load_mcp_tools", _boom, raising=True)
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="weather", command="npx"))
        assert _mcp_run(["list"])[0] == 0


# ── add ──────────────────────────────────────────────────────────────────────


class TestServersAdd:
    def test_basic_add_persists_via_core_mcp_tools(self) -> None:
        rc, out, _ = _mcp_run(["add", "playwright", "--", "npx", "-y", "@playwright/mcp@latest"])
        assert rc == 0
        assert "playwright" in out
        loaded = _mcp_servers.load_mcp_servers()
        assert len(loaded) == 1
        assert loaded[0].name == "playwright"
        assert loaded[0].command == "npx"
        assert loaded[0].args == ["-y", "@playwright/mcp@latest"]

    def test_env_and_timeout_flags_before_the_separator(self) -> None:
        rc, _, _ = _mcp_run(
            [
                "add",
                "search",
                "--env",
                "SEARCH_API_KEY=tok-123",
                "--timeout",
                "20",
                "--",
                "search-server",
                "--flag-that-belongs-to-the-command",
            ]
        )
        assert rc == 0
        loaded = _mcp_servers.load_mcp_servers()[0]
        assert loaded.env == {"SEARCH_API_KEY": "tok-123"}
        assert loaded.timeout == 20.0
        assert loaded.command == "search-server"
        assert loaded.args == ["--flag-that-belongs-to-the-command"]

    def test_env_equals_flag_form(self) -> None:
        rc, _, _ = _mcp_run(["add", "s", "--env=KEY=value", "--", "cmd"])
        assert rc == 0
        assert _mcp_servers.load_mcp_servers()[0].env == {"KEY": "value"}

    def test_a_command_flag_without_the_separator_is_rejected_not_misparsed(self) -> None:
        rc, _, _ = _mcp_run(["add", "playwright", "npx", "-y", "@playwright/mcp@latest"])
        assert rc != 0
        assert _mcp_servers.load_mcp_servers() == []

    def test_no_command_after_separator_is_rejected(self) -> None:
        rc, _, _ = _mcp_run(["add", "playwright", "--"])
        assert rc != 0
        assert _mcp_servers.load_mcp_servers() == []

    def test_malformed_env_flag_is_rejected(self) -> None:
        rc, _, err = _mcp_run(["add", "s", "--env", "NOT_KEY_VALUE", "--", "cmd"])
        assert rc == 1
        assert "KEY=VALUE" in err
        assert _mcp_servers.load_mcp_servers() == []

    def test_malformed_timeout_is_rejected(self) -> None:
        rc, _, _ = _mcp_run(["add", "s", "--timeout", "not-a-number", "--", "cmd"])
        assert rc != 0
        assert _mcp_servers.load_mcp_servers() == []

    def test_unknown_flag_before_separator_is_rejected(self) -> None:
        rc, _, _ = _mcp_run(["add", "s", "--bogus", "--", "cmd"])
        assert rc != 0
        assert _mcp_servers.load_mcp_servers() == []

    def test_a_bad_kind_is_rejected(self) -> None:
        rc, _, _ = _mcp_run(["add", "s", "--kind", "bogus", "--", "cmd"])
        assert rc == 1
        assert _mcp_servers.load_mcp_servers() == []

    def test_kind_send_is_stored_and_listed(self) -> None:
        assert _mcp_run(["add", "mailer", "--kind", "send", "--", "cmd"])[0] == 0
        assert _mcp_run(["add", "mailbox", "--kind", "read", "--", "cmd"])[0] == 0
        stored = {s.name: s.kind for s in _mcp_servers.load_mcp_servers()}
        assert stored == {"mailer": "send", "mailbox": "read"}
        assert "send" in _mcp_run(["list"])[1]

    def test_a_bad_lifetime_is_rejected(self) -> None:
        rc, _, err = _mcp_run(["add", "s", "--lifetime", "forever", "--", "cmd"])
        assert rc == 1 and "--lifetime" in err
        assert _mcp_servers.load_mcp_servers() == []

    def test_lifetime_hop_is_stored_and_call_is_the_default(self) -> None:
        assert _mcp_run(["add", "kept", "--lifetime", "hop", "--", "cmd"])[0] == 0
        assert _mcp_run(["add", "plain", "--", "cmd"])[0] == 0
        stored = {s.name: s.lifetime for s in _mcp_servers.load_mcp_servers()}
        assert stored == {"kept": "hop", "plain": "call"}

    def test_secret_writes_the_reference_and_never_reads_the_value(self) -> None:
        _secrets.save_secrets({"crm": "crm-live-0123456789"})

        rc, out, _ = _mcp_run(
            ["add", "crm", "--secret", "API_TOKEN=crm", "--env", "REGION=eu", "--", "cmd"]
        )

        assert rc == 0
        assert _mcp_servers.load_mcp_servers()[0].env == {
            "API_TOKEN": "secret:crm",
            "REGION": "eu",
        }
        raw = current_home().mcp_servers_file.read_text()
        assert "secret:crm" in raw and "crm-live-0123456789" not in raw + out
        assert "crm-live-0123456789" not in " ".join(_audit_details("mcp_servers.add"))

    def test_a_secret_not_yet_stored_is_added_with_a_warning(self) -> None:
        rc, out, err = _mcp_run(["add", "crm", "--secret", "API_TOKEN=later", "--", "cmd"])

        assert rc == 0
        assert "API_TOKEN" in out + err and "later" in out + err

    @pytest.mark.parametrize(
        "args",
        [["--secret", "API_TOKEN"], ["--secret", "=crm"], ["--secret", "API_TOKEN=a b"]],
    )
    def test_a_malformed_secret_is_rejected(self, args: list[str]) -> None:
        rc, _, err = _mcp_run(["add", "s", *args, "--", "cmd"])

        assert rc == 1 and "--secret" in err
        assert _mcp_servers.load_mcp_servers() == []

    def test_a_variable_given_to_env_and_secret_is_rejected(self) -> None:
        rc, _, err = _mcp_run(
            ["add", "s", "--env", "API_TOKEN=x", "--secret", "API_TOKEN=crm", "--", "cmd"]
        )

        assert rc == 1 and "API_TOKEN" in err

    def test_no_args_at_all_is_rejected(self) -> None:
        assert _mcp_run(["add"])[0] != 0

    def test_duplicate_name_surfaces_as_a_cli_error_not_a_traceback(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="weather", command="npx"))
        rc, _, err = _mcp_run(["add", "weather", "--", "npx", "-y", "wx2"])
        assert rc == 1
        assert "already configured" in err
        # the original config survives untouched
        assert _mcp_servers.load_mcp_servers()[0].args == []

    def test_invalid_name_surfaces_as_a_cli_error(self) -> None:
        rc, _, err = _mcp_run(["add", "not a valid name!", "--", "npx"])
        assert rc == 1
        assert "letters, digits" in err

    def test_add_writes_an_audit_entry_naming_server_and_command(self) -> None:
        _mcp_run(["add", "playwright", "--", "npx", "-y", "@playwright/mcp@latest"])
        entries = _audit_details("mcp_servers.add")
        assert len(entries) == 1
        assert "playwright" in entries[0]
        assert "npx" in entries[0]

    def test_add_audit_entry_never_contains_an_env_secret_value(self) -> None:
        _mcp_run(
            ["add", "search", "--env", "SEARCH_API_KEY=tok-super-secret", "--", "search-server"]
        )
        entries = _audit_details("mcp_servers.add")
        assert len(entries) == 1
        assert "tok-super-secret" not in entries[0]

    def test_a_failed_add_writes_no_audit_entry(self) -> None:
        _mcp_run(["add", "s", "--kind", "bogus", "--", "npx"])
        assert _audit_actions() == []


# ── remove ───────────────────────────────────────────────────────────────────


class TestServersRemove:
    def test_removes_a_configured_server(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="weather", command="npx"))
        rc, out, _ = _mcp_run(["remove", "weather"])
        assert rc == 0
        assert "removed" in out.lower()
        assert _mcp_servers.load_mcp_servers() == []

    def test_unknown_server_is_a_non_zero_noop(self) -> None:
        rc, _, _ = _mcp_run(["remove", "ghost"])
        assert rc == 1
        assert _audit_actions() == []

    def test_no_name_given_is_rejected(self) -> None:
        assert _mcp_run(["remove"])[0] != 0

    def test_remove_writes_an_audit_entry_naming_the_server(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="weather", command="npx"))
        _mcp_run(["remove", "weather"])
        entries = _audit_details("mcp_servers.remove")
        assert len(entries) == 1
        assert "weather" in entries[0]


# ── the group ────────────────────────────────────────────────────────────────


class TestGroup:
    def test_bare_group_prints_help_and_names_its_verbs(self) -> None:
        _, out, _ = _mcp_run([])
        assert "add" in out and "remove" in out and "list" in out


# ── ownership-row guard: never reaches agent/tools/registry.py or a toolbox handler ────


class TestServersCliNeverReachesTheToolboxOrCoreTools:
    """The ownership row: `interfaces/cli/commands/setup_mcp.py` never builds a Tool, so it must not import
    `agent.tools.registry` or any toolbox handler function -- a stricter bar than the public
    Tool/ToolRegistry.register API the MCP client itself uses."""

    FILE = "src/docket/interfaces/cli/commands/setup_mcp.py"

    def test_no_core_tools_import(self) -> None:
        path = REPO_ROOT / self.FILE
        tree = ast.parse(path.read_text())
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        offenders = {
            m
            for m in modules
            if m == "docket.agent.tools.registry" or m.endswith(".agent.tools.registry")
        }
        assert not offenders, f"{self.FILE} must never import agent.tools.registry: {offenders}"

    def test_no_toolbox_handler_import(self) -> None:
        path = REPO_ROOT / self.FILE
        tree = ast.parse(path.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "toolbox" in (node.module or ""):
                imported.update(alias.name for alias in node.names)
        assert not imported, f"{self.FILE} must never import from toolbox: {imported}"


# ── real entry point: the "--" separator across the Click seam ──────────────


def _child_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["DOCKET_HOME"] = str(home / ".docket")
    env.pop("DOCKET_NO_TRACE", None)
    return env


def _run_docket(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "docket", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


class TestServersAddThroughTheRealEntryPoint:
    """These drive the real `python -m docket` process, where Click's own arg parser sees the
    literal `--` first."""

    def test_add_with_separator_persists_the_command(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".docket").mkdir(parents=True)
        env = _child_env(home)
        result = _run_docket(
            ["setup", "mcp", "add", "playwright", "--", "npx", "-y", "@playwright/mcp@latest"],
            env,
        )
        assert result.returncode == 0, result.stderr
        stored = json.loads(Home(home / ".docket").mcp_servers_file.read_text())["servers"]
        assert stored[0]["command"] == "npx"
        assert stored[0]["args"] == ["-y", "@playwright/mcp@latest"]

    def test_env_and_timeout_before_separator_flags_after_belong_to_the_command(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        (home / ".docket").mkdir(parents=True)
        env = _child_env(home)
        result = _run_docket(
            [
                "setup",
                "mcp",
                "add",
                "s",
                "--env",
                "K=V",
                "--timeout",
                "5",
                "--",
                "cmd",
                "--env",
                "X=Y",
            ],
            env,
        )
        assert result.returncode == 0, result.stderr
        stored = json.loads(Home(home / ".docket").mcp_servers_file.read_text())["servers"]
        assert stored[0]["env"] == {"K": "V"}
        assert stored[0]["timeout"] == 5.0
        assert stored[0]["command"] == "cmd"
        assert stored[0]["args"] == ["--env", "X=Y"]

    def test_a_missing_command_is_still_rejected(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".docket").mkdir(parents=True)
        result = _run_docket(["setup", "mcp", "add", "s", "--"], _child_env(home))
        assert result.returncode != 0
        assert not Home(home / ".docket").mcp_servers_file.exists()
