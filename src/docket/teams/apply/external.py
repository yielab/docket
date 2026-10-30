"""``docket pod update <dir>``: plan the ``mcp-servers/*`` documents of a recipe directory, the
kind a pod declares for a server outside docket. ``teams.apply.plan`` composes this with the
other kinds' planners."""

from __future__ import annotations

from pathlib import Path

from docket.kernel import mcp as _mcp
from docket.teams import mcp_servers as _mcp_servers
from docket.teams.apply.model import ApplyAction, ApplyItem, PodApplyError, _McpServerWrite
from docket.teams.apply.recipes import _server_files


def plan_mcp_servers(
    directory: Path, project: str
) -> tuple[list[ApplyItem], _McpServerWrite | None]:
    """Plan ``mcp-servers/*`` into *project*'s own pod-scoped server file. A name equal to a
    global server is refused (never shadowed); a server already stored identically plans
    ``skip``; servers the recipe does not name are kept."""
    items: list[ApplyItem] = []
    declared: dict[str, _mcp.McpServerConfig] = {}
    for path in _server_files(directory):
        try:
            config = _mcp_servers.load_mcp_server_document(path)
        except _mcp_servers.McpServerDocError as exc:
            raise PodApplyError(str(exc)) from exc
        if config.name in declared:
            raise PodApplyError(f"{path}: MCP server {config.name!r} is declared twice")
        declared[config.name] = config
    if not declared:
        return items, None
    global_names = {s.name for s in _mcp_servers.load_mcp_servers()}
    for name in declared:
        if name in global_names:
            raise PodApplyError(
                f"mcp-servers: {name!r} collides with a global MCP server; "
                "rename it or remove the global one"
            )
    current = {s.name: s for s in _mcp_servers.load_pod_mcp_servers(project)}
    changed = False
    for name, config in declared.items():
        if name in current and current[name] == config:
            action: ApplyAction = "skip"
        else:
            action = "replace" if name in current else "add"
            changed = True
        items.append(ApplyItem(kind="mcp-server", name=name, action=action))
    if not changed:
        return items, None
    return items, _McpServerWrite(servers=tuple({**current, **declared}.values()))
