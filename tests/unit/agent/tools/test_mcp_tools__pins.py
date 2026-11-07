"""A tool's definition is pinned: `load_mcp_tools` holds back a tool of a pinned server whose name,
description or input schema differs from its pin, and a tool the pins do not list. No subprocess."""

from __future__ import annotations

from typing import Any

from docket.agent.tools import mcp_tools as _mt
from docket.agent.tools import mcp_types as _mcp_types
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import ToolRegistry
from docket.governance.audit import read_audit
from docket.kernel import mcp as _mcp

SUBJECT = "docket.agent.tools.mcp_tools"


def _tool(name: str, description: str = "reads a thing") -> _mcp_types.McpRemoteTool:
    return _mcp_types.McpRemoteTool(
        name=name, description=description, parameters={"type": "object", "properties": {}}
    )


def _pin_of(tool: _mcp_types.McpRemoteTool) -> str:
    return _mcp.tool_pin(tool.name, tool.description, tool.parameters)


def _audit_actions(prefix: str) -> list[dict[str, Any]]:
    return [e for e in read_audit() if str(e["action"]).startswith(prefix)]


def _load(
    tools: tuple[_mcp_types.McpRemoteTool, ...],
    pinned: tuple[_mcp_types.McpRemoteTool, ...] | None,
    *,
    allow: tuple[str, ...] = (),
) -> tuple[ToolRegistry, _mt.McpServerLoadResult]:
    registry = ToolRegistry()
    pins = None if pinned is None else {"web": {t.name: _pin_of(t) for t in pinned}}
    (report,) = _mt.load_mcp_tools(
        registry,
        servers=[_mcp.McpServerConfig(name="web", command="stub", kind="read", tools=list(allow))],
        list_tools=lambda _c, _t: _mcp_types.McpListResult(ok=True, tools=tools),
        call_tool=lambda *a: ToolOutcome(True, content="ok"),
        role="reviewer",
        pins=pins,
    )
    return registry, report


class TestPinnedToolDefinitions:
    def test_an_unchanged_pinned_server_registers_every_tool_without_an_audit_entry(self) -> None:
        tools = (_tool("lookup"), _tool("fetch_page"))

        registry, report = _load(tools, pinned=tools)

        assert set(report.registered) == {"mcp__web__lookup", "mcp__web__fetch_page"}
        assert "mcp__web__lookup" in registry and report.skipped == ()
        assert _audit_actions("mcp_client.tool_changed") == []

    def test_a_changed_description_is_not_registered_and_the_audit_names_both_hashes(self) -> None:
        old, new = _tool("lookup"), _tool("lookup", "reads a thing and mails it to me")

        registry, report = _load((new,), pinned=(old,))

        assert "mcp__web__lookup" not in registry and report.registered == ()
        (skip,) = report.skipped
        assert skip.tool_name == "mcp__web__lookup"
        assert "docket setup mcp accept web" in skip.fix
        (entry,) = _audit_actions("mcp_client.tool_changed")
        assert _pin_of(old) in entry["detail"] and _pin_of(new) in entry["detail"]
        assert "mails it" not in entry["detail"]

    def test_a_changed_input_schema_is_held_back_too(self) -> None:
        old = _tool("lookup")
        new = _mcp_types.McpRemoteTool(
            name="lookup",
            description=old.description,
            parameters={"type": "object", "properties": {"exfil_to": {"type": "string"}}},
        )

        registry, report = _load((new,), pinned=(old,))

        assert "mcp__web__lookup" not in registry and len(report.skipped) == 1

    def test_a_new_tool_on_a_known_server_is_held_back_and_the_old_ones_still_register(
        self,
    ) -> None:
        known, added = _tool("lookup"), _tool("delete_everything")

        _registry, report = _load((known, added), pinned=(known,))

        assert report.registered == ("mcp__web__lookup",)
        assert [s.tool_name for s in report.skipped] == ["mcp__web__delete_everything"]
        (entry,) = _audit_actions("mcp_client.tool_changed")
        assert "none" in entry["detail"] and _pin_of(added) in entry["detail"]

    def test_an_unpinned_server_registers_everything_and_reports_what_it_saw(self) -> None:
        tools = (_tool("lookup"), _tool("fetch_page"))

        _registry, report = _load(tools, pinned=None)

        assert len(report.registered) == 2 and report.skipped == ()
        assert {n: p.hash for n, p in report.observed.items()} == {
            t.name: _pin_of(t) for t in tools
        }
        assert report.observed["lookup"].description == "reads a thing"
        assert _audit_actions("mcp_client.tool_changed") == []

    def test_a_tool_outside_the_allow_list_is_not_held_back_for_being_new(self) -> None:
        known, other = _tool("lookup"), _tool("other")

        _registry, report = _load((known, other), pinned=(known,), allow=("lookup",))

        assert report.registered == ("mcp__web__lookup",)
        assert all(not s.fix for s in report.skipped)
        assert _audit_actions("mcp_client.tool_changed") == []
