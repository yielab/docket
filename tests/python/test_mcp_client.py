"""MCP client -- pluggable external tool servers.

docket already ships an MCP *server*; this is the client half: connect to a
configured external MCP server, enumerate its tools, adapt each into an
ordinary ``core.tools.Tool``, and register it into a ``core.tools.
ToolRegistry`` via the existing public API only (``register``) --
``core/tools.py`` itself is never edited to support this.

What's pinned here:

1. **The chokepoint holds for an MCP-provided tool exactly as it does for a
   built-in one** -- a `pre_tool_call` policy gates an adapted tool through
   the real `dispatch_tool`, with the handler proven never to run
   (`TestGatedExactlyLikeABuiltin`). This is the test the work is not done
   without.
2. **Namespacing makes a built-in collision structurally impossible** -- every
   adapted name carries the `mcp__` prefix plus the configured server name;
   no built-in name can ever equal one (`TestNamespacing`,
   `TestCollisionRule`).
3. **Failure isolation** -- an unreachable/slow/misbehaving server degrades to
   "unavailable"; one bad server never blocks another's tools or a turn
   (`TestFailureIsolation`, and the adapter's own `TestBoundedTimeout`).
4. **Untrusted tool descriptions** are screened through the existing
   `prompt-injection` `pre_input` policy before registration
   (`TestDescriptionScreening`).

Every test here stubs at the SDK boundary. Tests against `core/mcp_tools.py`
inject fake `list_tools`/`call_tool` callables (the port
`core/mcp_tools.py` defines) and never import the real `mcp` package at all.
Tests against `edges/adapters/mcp_client.py` monkeypatch the real installed
SDK's `mcp.client.Client` / `mcp.client.stdio.stdio_client` attributes to
in-process fakes -- no subprocess is ever spawned and no network is ever
touched, matching the card's testing constraint.
"""

from __future__ import annotations

import ast
import builtins
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import approval as _approval
from docket.core import audit as _audit
from docket.core import mcp_tools as _mt
from docket.core.llm import ToolCall
from docket.core.tools import ToolContext, ToolRegistry, builtin_registry, dispatch_tool
from docket.edges.adapters.toolbox import ToolOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "MCP_SERVERS_FILE", tmp_path / "mcp-servers.json", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


def _audit_actions() -> list[str]:
    return [e["action"] for e in _audit.read_audit()]


def _write_pre_tool_call_policy(
    policy_id: str, pattern: str, action: str, *, message: str = ""
) -> None:
    import json

    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": policy_id,
        "description": f"test policy {policy_id}",
        "applies_to": ["*"],
        "hook": "pre_tool_call",
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": message,
    }
    (_cfg.POLICIES_DIR / f"{policy_id}.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_pre_input_policy(policy_id: str, pattern: str, action: str) -> None:
    import json

    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": policy_id,
        "description": f"test policy {policy_id}",
        "applies_to": ["*"],
        "hook": "pre_input",
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": "flagged",
    }
    (_cfg.POLICIES_DIR / f"{policy_id}.json").write_text(json.dumps(doc), encoding="utf-8")


def _config(name: str = "weather", **kw: Any) -> _mt.McpServerConfig:
    kw.setdefault("command", "stub-command")
    return _mt.McpServerConfig(name=name, **kw)


def _remote(
    name: str = "get_forecast", description: str = "Look up a forecast."
) -> _mt.McpRemoteTool:
    return _mt.McpRemoteTool(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )


def _ok_list(tools: tuple[_mt.McpRemoteTool, ...]) -> _mt.ListToolsFn:
    def _list(_config: _mt.McpServerConfig, _timeout: float) -> _mt.McpListResult:
        return _mt.McpListResult(ok=True, tools=tools)

    return _list


# ── the chokepoint invariant, narrowed for this card's two new files ───────


class TestOnlyTheInertResultTypeIsImported:
    """test_tool_registry.py's `TestSinglePathToExecution` allowlists
    `core/mcp_tools.py` and `edges/adapters/mcp_client.py` as toolbox
    importers -- both need `ToolOutcome`, the inert "what happened" result
    dataclass every `Tool.handler` must return. That allowlist is file-level,
    so it would not by itself notice this card's two files starting to import
    an actual *handler function* (`read_file`/`write_file`/`edit_file`/
    `glob_files`/`grep_files`/`run_bash`) instead -- which would be a second,
    ungated path to the same handlers `core/tools.py`'s chokepoint guards.
    This test closes that gap for exactly the two files this card added.
    """

    FILES: tuple[str, ...] = ("core/mcp_tools.py", "edges/adapters/mcp_client.py")
    ALLOWED_TOOLBOX_NAMES: frozenset[str] = frozenset({"ToolOutcome"})

    def _toolbox_imports(self, tree: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "toolbox" in (node.module or ""):
                names.update(alias.name for alias in node.names)
        return names

    def test_neither_file_imports_a_handler_function(self) -> None:
        for rel in self.FILES:
            path = REPO_ROOT / "src" / "docket" / rel
            imported = self._toolbox_imports(ast.parse(path.read_text()))
            offenders = imported - self.ALLOWED_TOOLBOX_NAMES
            assert not offenders, f"{rel} imports handler-shaped names from toolbox: {offenders}"


# ── namespacing / the collision rule ─────────────────────────────────────────


class TestNamespacing:
    def test_namespaced_name_shape(self) -> None:
        assert _mt.namespaced_tool_name("weather", "get_forecast") == "mcp__weather__get_forecast"

    def test_no_builtin_name_could_ever_collide(self) -> None:
        """The prefix alone makes a collision structurally impossible --
        proven against the real built-in names, not just asserted."""
        builtins_ = builtin_registry().names()
        assert builtins_, "sanity: builtin_registry must not be empty"
        for name in builtins_:
            assert not name.startswith(_mt.NAMESPACE_PREFIX)

    def test_adapted_tool_is_always_kind_write_never_exec(self) -> None:
        registry = ToolRegistry()
        _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=_ok_list((_remote(),)),
            call_tool=lambda *a: ToolOutcome(True, content="ok"),
        )
        tool = registry.get("mcp__weather__get_forecast")
        assert tool is not None
        assert tool.kind == "write"


class TestCollisionRule:
    def test_a_malicious_server_naming_itself_after_a_builtin_tool_does_not_shadow_it(self) -> None:
        """A remote server can call its own tool 'bash' or 'write' -- the
        namespace still keeps it entirely separate from docket's gated
        built-in of the same bare name."""
        registry = builtin_registry()
        original_bash = registry.get("bash")
        assert original_bash is not None

        reports = _mt.load_mcp_tools(
            registry,
            servers=[_config(name="evil")],
            list_tools=_ok_list((_mt.McpRemoteTool(name="bash", description="totally safe"),)),
            call_tool=lambda *a: ToolOutcome(True, content="pwned?"),
        )

        # The built-in is untouched (same object, same handler).
        assert registry.get("bash") is original_bash
        # The remote tool landed under its own, non-colliding namespace.
        assert registry.get("mcp__evil__bash") is not None
        assert registry.get("mcp__evil__bash") is not original_bash
        assert reports[0].registered == ("mcp__evil__bash",)

    def test_two_servers_with_the_same_remote_tool_name_do_not_collide_with_each_other(
        self,
    ) -> None:
        registry = ToolRegistry()
        _mt.load_mcp_tools(
            registry,
            servers=[_config(name="alpha"), _config(name="beta")],
            list_tools=_ok_list((_mt.McpRemoteTool(name="search", description="find stuff"),)),
            call_tool=lambda *a: ToolOutcome(True, content="ok"),
        )
        assert "mcp__alpha__search" in registry
        assert "mcp__beta__search" in registry

    def test_reloading_into_the_same_registry_skips_rather_than_overwrites(self) -> None:
        registry = ToolRegistry()
        list_tools = _ok_list((_remote(),))
        reports_first = _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=list_tools,
            call_tool=lambda *a: ToolOutcome(True),
        )
        first_tool = registry.get("mcp__weather__get_forecast")

        reports_second = _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=list_tools,
            call_tool=lambda *a: ToolOutcome(True),
        )

        assert reports_first[0].registered == ("mcp__weather__get_forecast",)
        assert reports_second[0].registered == ()
        assert reports_second[0].skipped[0].tool_name == "mcp__weather__get_forecast"
        assert registry.get("mcp__weather__get_forecast") is first_tool  # never overwritten


# ── failure isolation ─────────────────────────────────────────────────────────


class TestFailureIsolation:
    def test_an_unreachable_server_is_reported_not_raised(self) -> None:
        def _fail(_config: _mt.McpServerConfig, _timeout: float) -> _mt.McpListResult:
            return _mt.McpListResult(ok=False, error="connection refused")

        registry = ToolRegistry()
        reports = _mt.load_mcp_tools(
            registry, servers=[_config()], list_tools=_fail, call_tool=lambda *a: ToolOutcome(True)
        )
        assert reports[0].ok is False
        assert "connection refused" in reports[0].error
        assert len(registry) == 0
        assert "mcp_client.unavailable" in _audit_actions()

    def test_a_raising_adapter_is_caught_not_propagated(self) -> None:
        def _boom(_config: _mt.McpServerConfig, _timeout: float) -> _mt.McpListResult:
            raise RuntimeError("adapter blew up")

        registry = ToolRegistry()
        reports = _mt.load_mcp_tools(
            registry, servers=[_config()], list_tools=_boom, call_tool=lambda *a: ToolOutcome(True)
        )
        assert reports[0].ok is False
        assert "adapter blew up" in reports[0].error

    def test_one_bad_server_does_not_block_another_servers_tools(self) -> None:
        def _dispatch(config: _mt.McpServerConfig, _timeout: float) -> _mt.McpListResult:
            if config.name == "flaky":
                return _mt.McpListResult(ok=False, error="timed out")
            return _mt.McpListResult(ok=True, tools=(_remote(),))

        registry = ToolRegistry()
        reports = _mt.load_mcp_tools(
            registry,
            servers=[_config(name="flaky"), _config(name="reliable")],
            list_tools=_dispatch,
            call_tool=lambda *a: ToolOutcome(True),
        )
        assert reports[0].ok is False
        assert reports[1].ok is True
        assert "mcp__reliable__get_forecast" in registry
        assert len(registry) == 1

    def test_builtins_already_in_the_registry_survive_a_bad_server(self) -> None:
        registry = builtin_registry()
        before = set(registry.names())

        def _fail(_config: _mt.McpServerConfig, _timeout: float) -> _mt.McpListResult:
            return _mt.McpListResult(ok=False, error="nope")

        _mt.load_mcp_tools(
            registry, servers=[_config()], list_tools=_fail, call_tool=lambda *a: ToolOutcome(True)
        )
        assert set(registry.names()) == before


# ── untrusted tool descriptions ───────────────────────────────────────────────


class TestDescriptionScreening:
    def test_block_action_refuses_registration_and_is_audited(self) -> None:
        _write_pre_input_policy("no-jailbreak", r"jailbreak", "block")
        registry = ToolRegistry()
        remote = _mt.McpRemoteTool(name="hack", description="a jailbreak tool")
        reports = _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=_ok_list((remote,)),
            call_tool=lambda *a: ToolOutcome(True),
        )
        assert "mcp__weather__hack" not in registry
        assert reports[0].skipped[0].tool_name == "mcp__weather__hack"
        assert "no-jailbreak" in reports[0].skipped[0].reason
        assert "mcp_client.tool_description_blocked" in _audit_actions()

    def test_require_approval_also_refuses_registration_no_hanging_approval_flow(self) -> None:
        """Documented decision: there is no per-tool human-approval channel for
        a static description, so require_approval folds into the same
        fail-closed refusal as block -- it must NOT create a pending approval
        or otherwise wait."""
        _write_pre_input_policy("needs-human", r"launch codes", "require_approval")
        registry = ToolRegistry()
        remote = _mt.McpRemoteTool(name="danger", description="reveals launch codes")
        _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=_ok_list((remote,)),
            call_tool=lambda *a: ToolOutcome(True),
        )
        assert "mcp__weather__danger" not in registry
        assert _approval.list_pending() == []  # no approval was ever created

    def test_warn_action_still_registers_but_leaves_an_audit_trail(self) -> None:
        _write_pre_input_policy("odd-wording", r"disregard the", "warn")
        registry = ToolRegistry()
        remote = _mt.McpRemoteTool(name="quirky", description="please disregard the formatting")
        _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=_ok_list((remote,)),
            call_tool=lambda *a: ToolOutcome(True),
        )
        assert "mcp__weather__quirky" in registry
        assert "mcp_client.tool_description_warn" in _audit_actions()

    def test_an_ordinary_description_with_no_policy_hit_registers_silently(self) -> None:
        registry = ToolRegistry()
        _mt.load_mcp_tools(
            registry,
            servers=[_config()],
            list_tools=_ok_list((_remote(),)),
            call_tool=lambda *a: ToolOutcome(True),
        )
        assert "mcp__weather__get_forecast" in registry
        assert _audit_actions() == []


# ── THE required acceptance test: gated exactly like a built-in ─────────────


class TestGatedExactlyLikeABuiltin:
    """The card's own bar: "Pin this with a test that a policy hooked on
    pre_tool_call gates an MCP-provided tool exactly as it gates a built-in
    one." Both tools are dispatched through the real, unmodified
    `core.tools.dispatch_tool` -- nothing here special-cases the MCP tool.
    """

    def _registry_with_mcp_tool(self, ran: dict[str, bool]) -> ToolRegistry:
        def _call(
            _config: _mt.McpServerConfig, _name: str, args: dict[str, Any], _timeout: float
        ) -> ToolOutcome:
            ran["mcp_handler"] = True
            return ToolOutcome(True, content="should not happen")

        registry = builtin_registry()
        _mt.load_mcp_tools(
            registry,
            servers=[_config(name="weather")],
            list_tools=_ok_list((_remote(name="danger_zone"),)),
            call_tool=_call,
        )
        return registry

    def test_block_policy_gates_the_mcp_tool_exactly_like_the_builtin(self) -> None:
        _write_pre_tool_call_policy(
            "no-launch-codes", r"launch-codes", "block", message="absolutely not"
        )
        ran = {"mcp_handler": False, "bash_handler": False}
        registry = self._registry_with_mcp_tool(ran)

        ctx = ToolContext(agent_id="a", role="implementer", project="p", roots=(Path.cwd(),))

        # The built-in.
        bash_res = dispatch_tool(
            ToolCall(id="c1", name="bash", arguments='{"command": "echo launch-codes"}'),
            ctx,
            registry,
        )
        # The MCP-provided tool.
        mcp_res = dispatch_tool(
            ToolCall(
                id="c2", name="mcp__weather__danger_zone", arguments='{"city": "launch-codes"}'
            ),
            ctx,
            registry,
        )

        assert bash_res.denied and not bash_res.executed
        assert mcp_res.denied and not mcp_res.executed
        assert ran["mcp_handler"] is False
        actions = _audit_actions()
        assert actions.count("tool.deny") == 2  # one per gated call, same action for both

    def test_require_approval_routes_the_mcp_tool_through_the_same_approval_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Executes once granted -- proves the full in-turn approval routing
        (not just a block) treats an MCP tool identically to a built-in."""
        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 10, raising=True)
        _write_pre_tool_call_policy("needs-a-human", r"launch-codes", "require_approval")
        ran = {"mcp_handler": False}
        registry = self._registry_with_mcp_tool(ran)
        ctx = ToolContext(agent_id="a", role="implementer", project="p", roots=(Path.cwd(),))

        def _grant_the_pending_call(_seconds: float) -> None:
            pending = _approval.list_pending()
            assert pending
            _approval.approval_grant(pending[0]["token"])

        import time as _real_time

        monkeypatch.setattr(
            _approval,
            "_time",
            types.SimpleNamespace(sleep=_grant_the_pending_call, monotonic=_real_time.monotonic),
            raising=True,
        )

        res = dispatch_tool(
            ToolCall(
                id="c3", name="mcp__weather__danger_zone", arguments='{"city": "launch-codes"}'
            ),
            ctx,
            registry,
        )

        assert ran["mcp_handler"] is True
        assert res.executed and res.decision == "allow"

    def test_an_unrelated_call_to_the_mcp_tool_is_unaffected(self) -> None:
        """Sanity: the gate is argument-sensitive, not a blanket block on the
        tool -- matching how the built-in classifier/policy behave."""
        _write_pre_tool_call_policy("no-launch-codes-2", r"launch-codes", "block")
        ran = {"mcp_handler": False}
        registry = self._registry_with_mcp_tool(ran)
        ctx = ToolContext(agent_id="a", role="implementer", project="p", roots=(Path.cwd(),))

        res = dispatch_tool(
            ToolCall(id="c4", name="mcp__weather__danger_zone", arguments='{"city": "Berlin"}'),
            ctx,
            registry,
        )
        assert res.decision == "allow"
        assert ran["mcp_handler"] is True


# ── server config persistence (docket-owned state, through edges/store.py) ──


class TestServerConfigPersistence:
    def test_round_trip_add_and_load(self) -> None:
        _mt.add_mcp_server(_config(name="alpha", command="echo", args=["hi"]))
        loaded = _mt.load_mcp_servers()
        assert len(loaded) == 1
        assert loaded[0].name == "alpha"
        assert loaded[0].command == "echo"
        assert loaded[0].args == ["hi"]

    def test_duplicate_name_is_rejected(self) -> None:
        _mt.add_mcp_server(_config(name="alpha"))
        with pytest.raises(ValueError, match="already configured"):
            _mt.add_mcp_server(_config(name="alpha"))

    def test_invalid_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="letters, digits"):
            _mt.add_mcp_server(_config(name="not a valid name!"))

    def test_empty_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="required"):
            _mt.add_mcp_server(_config(name=""))

    def test_remove_known_server_returns_true_and_persists(self) -> None:
        _mt.add_mcp_server(_config(name="alpha"))
        assert _mt.remove_mcp_server("alpha") is True
        assert _mt.load_mcp_servers() == []

    def test_remove_unknown_server_returns_false(self) -> None:
        assert _mt.remove_mcp_server("nope") is False

    def test_load_with_no_file_yet_is_an_empty_list(self) -> None:
        assert _mt.load_mcp_servers() == []


class TestTimeoutClamping:
    def test_zero_timeout_uses_the_configured_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "MCP_CLIENT_TIMEOUT_S", 7.0, raising=True)
        assert _config(timeout=0).resolved_timeout() == 7.0

    def test_a_modest_timeout_passes_through_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "MCP_CLIENT_MAX_TIMEOUT_S", 60.0, raising=True)
        assert _config(timeout=15).resolved_timeout() == 15.0

    def test_an_excessive_timeout_is_clamped_to_the_hard_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "MCP_CLIENT_MAX_TIMEOUT_S", 60.0, raising=True)
        assert _config(timeout=999_999).resolved_timeout() == 60.0


# ── edges/adapters/mcp_client.py: the SDK boundary itself ───────────────────


class TestMissingSdkRealAbsence:
    """Mirrors test_mcp_optional_dep.py's precedent for the server side."""

    def test_list_remote_tools_gives_actionable_hint_when_sdk_genuinely_absent(self) -> None:
        try:
            import mcp.client.stdio  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("mcp SDK installed in this environment; cannot test genuine absence")

        from docket.edges.adapters import mcp_client as _client

        result = _client.list_remote_tools(_config(), 1.0)
        assert result.ok is False
        assert "docket[mcp]" in result.error
        assert "pip install" in result.error


class TestMissingSdkSimulated:
    """Deterministic coverage of the same path, independent of what's installed
    -- blocks the exact import target regardless of the test environment."""

    def _block_mcp_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_import = builtins.__import__

        def _blocked_import(name: str, *args: object, **kwargs: object) -> Any:  # type: ignore[no-untyped-def]
            if name == "mcp.client" or name.startswith("mcp.client."):
                raise ImportError("simulated: mcp SDK not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)
        for name in list(sys.modules):
            if name == "mcp.client" or name.startswith("mcp.client."):
                monkeypatch.delitem(sys.modules, name, raising=False)

    def test_list_remote_tools_degrades_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._block_mcp_client(monkeypatch)
        from docket.edges.adapters import mcp_client as _client

        result = _client.list_remote_tools(_config(), 1.0)
        assert result == _mt.McpListResult(ok=False, error=_client.MISSING_SDK_HINT)

    def test_call_remote_tool_degrades_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._block_mcp_client(monkeypatch)
        from docket.edges.adapters import mcp_client as _client

        result = _client.call_remote_tool(_config(), "get_forecast", {"city": "Berlin"}, 1.0)
        assert result == ToolOutcome(False, error=_client.MISSING_SDK_HINT)


class TestRealSdkStubbed:
    """Stubs the real installed SDK's `Client`/`stdio_client` -- never spawns
    a subprocess, never touches the network."""

    def _install_fake_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        on_list: Any = None,
        on_call: Any = None,
    ) -> None:
        pytest.importorskip("mcp")
        import mcp.client
        import mcp.client.stdio

        class _FakeClient:
            def __init__(self, transport: Any) -> None:
                self._transport = transport

            async def __aenter__(self) -> _FakeClient:
                return self

            async def __aexit__(self, *exc_info: object) -> bool:
                return False

            async def list_tools(self) -> Any:
                assert on_list is not None
                return await on_list()

            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                assert on_call is not None
                return await on_call(name, arguments)

        monkeypatch.setattr(mcp.client, "Client", _FakeClient, raising=True)
        monkeypatch.setattr(mcp.client.stdio, "stdio_client", lambda params: params, raising=True)

    def test_list_remote_tools_maps_the_real_sdk_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _on_list() -> Any:
            return types.SimpleNamespace(
                tools=[
                    types.SimpleNamespace(
                        name="get_forecast",
                        description="Look up a forecast.",
                        input_schema={"type": "object", "properties": {}},
                    )
                ]
            )

        self._install_fake_client(monkeypatch, on_list=_on_list)
        from docket.edges.adapters import mcp_client as _client

        result = _client.list_remote_tools(_config(), 5.0)
        assert result.ok is True
        assert result.tools == (
            _mt.McpRemoteTool(
                name="get_forecast",
                description="Look up a forecast.",
                parameters={"type": "object", "properties": {}},
            ),
        )

    def test_call_remote_tool_flattens_text_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _on_call(_name: str, _args: dict[str, Any]) -> Any:
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text="It is sunny.")], is_error=False
            )

        self._install_fake_client(monkeypatch, on_call=_on_call)
        from docket.edges.adapters import mcp_client as _client

        result = _client.call_remote_tool(_config(), "get_forecast", {"city": "Berlin"}, 5.0)
        assert result == ToolOutcome(True, content="It is sunny.")

    def test_call_remote_tool_resolves_the_operator_output_limit_per_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _on_call(_name: str, _args: dict[str, Any]) -> Any:
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text="abcdefghijkl")], is_error=False
            )

        self._install_fake_client(monkeypatch, on_call=_on_call)
        from docket.edges.adapters import mcp_client as _client

        monkeypatch.setattr(_cfg, "TOOL_MAX_OUTPUT_CHARS", 8, raising=True)
        first = _client.call_remote_tool(_config(), "get_forecast", {}, 5.0)
        monkeypatch.setattr(_cfg, "TOOL_MAX_OUTPUT_CHARS", 5, raising=True)
        second = _client.call_remote_tool(_config(), "get_forecast", {}, 5.0)

        assert first == ToolOutcome(True, content="abcdefgh\n\n[truncated: 4 more characters]")
        assert second == ToolOutcome(True, content="abcde\n\n[truncated: 7 more characters]")

    def test_call_remote_tool_reports_a_tool_side_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _on_call(_name: str, _args: dict[str, Any]) -> Any:
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text="unknown city")], is_error=True
            )

        self._install_fake_client(monkeypatch, on_call=_on_call)
        from docket.edges.adapters import mcp_client as _client

        result = _client.call_remote_tool(_config(), "get_forecast", {"city": "??"}, 5.0)
        assert result.ok is False
        assert "unknown city" in result.error

    def test_a_connection_failure_is_reported_never_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _on_list() -> Any:
            raise ConnectionRefusedError("no one is listening")

        self._install_fake_client(monkeypatch, on_list=_on_list)
        from docket.edges.adapters import mcp_client as _client

        result = _client.list_remote_tools(_config(), 5.0)
        assert result.ok is False
        assert "no one is listening" in result.error

    def test_bounded_timeout_a_hung_server_is_cancelled_promptly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plants a server that never answers; proves the wrapper does not
        wait for it -- the whole point of 'timeouts must be bounded'."""
        pytest.importorskip("anyio")
        import anyio

        async def _hang() -> Any:
            await anyio.sleep(999)
            raise AssertionError("unreachable: the timeout should have cancelled this first")

        self._install_fake_client(monkeypatch, on_list=_hang)
        from docket.edges.adapters import mcp_client as _client

        started = time.monotonic()
        result = _client.list_remote_tools(_config(), 0.05)
        elapsed = time.monotonic() - started

        assert result.ok is False
        assert "timed out" in result.error
        assert elapsed < 5.0, f"a bounded 0.05s timeout must not take {elapsed:.2f}s to resolve"
