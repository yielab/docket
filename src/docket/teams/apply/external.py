"""``docket pod update <dir>``: plan the ``mcp-servers/*`` and ``services/*`` documents of a recipe
directory, the kinds a pod declares for something outside docket. ``teams.apply.plan`` composes
this with the other kinds' planners."""

from __future__ import annotations

from pathlib import Path

from docket.kernel import mcp as _mcp
from docket.kernel.home import current_home
from docket.platform import mkdir_private
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import services as _services
from docket.teams.apply.model import (
    ApplyAction,
    ApplyItem,
    PodApplyError,
    _McpServerWrite,
    _ServiceWrite,
)
from docket.teams.apply.recipes import _declared_servers, _server_files


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
        conflict = _services.service_name_conflict(name)
        if conflict:
            raise PodApplyError(f"mcp-servers: {conflict}")
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


def plan_services(directory: Path, project: str) -> tuple[list[ApplyItem], list[_ServiceWrite]]:
    """Plan ``services/*`` into *project*'s own ``services/`` by bytes. An invalid file, a name
    declared twice or equal to an operator service or any MCP server (stored or declared in
    *directory*) raises ``PodApplyError``; services the directory does not name are kept."""
    declared: dict[str, tuple[Path, bytes]] = {}
    for path in _services.service_files(directory):
        try:
            config = _services.load_service_document(path)
        except _services.ServiceDocError as exc:
            raise PodApplyError(str(exc)) from exc
        if config.name in declared:
            raise PodApplyError(f"{path}: service {config.name!r} is declared twice")
        declared[config.name] = (path, path.read_bytes())
    if not declared:
        return [], []
    operator_names = {s.name for s in _services.load_services()}
    declared_servers = {c.name for c in _declared_servers(directory)}
    for name in declared:
        if name in operator_names:
            raise PodApplyError(
                f"services: {name!r} collides with an operator service; "
                "rename it or remove the operator's"
            )
        conflict = _services.mcp_name_conflict(name)
        if conflict:
            raise PodApplyError(f"services: {conflict}")
        if name in declared_servers:
            raise PodApplyError(
                f"services: {name!r} is also an MCP server in mcp-servers/; "
                "a service and an MCP server never share a name"
            )
    items: list[ApplyItem] = []
    writes: list[_ServiceWrite] = []
    dest_dir = _services.pod_services_dir(project)
    for name, (path, source) in declared.items():
        dest = dest_dir / path.name
        if dest.is_file() and dest.read_bytes() == source:
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_ServiceWrite(name=path.name, source=source))
        items.append(ApplyItem(kind="service", name=name, action=action))
    return items, writes


def write_services(project: str, writes: tuple[_ServiceWrite, ...]) -> None:
    """Write each planned service file into *project*'s overlay, private."""
    if not writes:
        return
    folder = _services.pod_services_dir(project)
    mkdir_private(folder)
    for write in writes:
        dest = folder / write.name
        dest.write_bytes(write.source)
        dest.chmod(0o600)


def export_services(project: str, directory: Path) -> None:
    """Copy *project*'s own service files byte-for-byte as ``services/<name>``."""
    files = _services.service_files(current_home().pod_config_dir(project))
    if not files:
        return
    (directory / "services").mkdir(parents=True, exist_ok=True)
    for f in files:
        (directory / "services" / f.name).write_bytes(f.read_bytes())
