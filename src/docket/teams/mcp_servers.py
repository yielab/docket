from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.kernel.mcp import McpServerConfig, McpServerRegistry
from docket.platform import mkdir_private, read_json, read_modify_write, write_json

# A configured server's *local* name is docket-owned config, not remote input,
# but it still ends up as a path-like fragment in a tool name shown to a
# model -- restrict it to an unambiguous charset rather than trusting an
# operator not to fat-finger something that renders confusingly.
_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def pod_mcp_servers_file(project: str) -> Path:
    """Where *project*'s own pod-scoped servers live: ``<pod config dir>/mcp-servers.json``."""
    return current_home().pod_config_dir(project) / "mcp-servers.json"


def load_pod_mcp_servers(project: str) -> list[McpServerConfig]:
    """*project*'s own pod-scoped servers, in on-disk order. Empty when it has none."""
    data = read_json(pod_mcp_servers_file(project))
    return McpServerRegistry.model_validate(data).servers


def load_mcp_servers(project: str = "") -> list[McpServerConfig]:
    """The configured MCP servers, in on-disk order; empty when unconfigured. With *project*,
    the pod's own pod-scoped servers come first and win a name collision, then the operator's
    (the one scope order every kind resolves in, config-format.spec.md)."""
    data = read_json(current_home().mcp_servers_file)
    servers = McpServerRegistry.model_validate(data).servers
    if not project:
        return servers
    own = load_pod_mcp_servers(project)
    taken = {s.name for s in own}
    return [*own, *(s for s in servers if s.name not in taken)]


def write_pod_mcp_servers(project: str, servers: list[McpServerConfig]) -> None:
    """Replace *project*'s pod-scoped server file with *servers*, through ``platform/store.py``."""
    path = pod_mcp_servers_file(project)
    mkdir_private(path.parent)
    write_json(path, McpServerRegistry(servers=servers))


def pod_scoped_owner(name: str, *, exclude: str = "") -> str:
    """The pod (other than *exclude*) whose pod-scoped file declares *name*, else ``""``."""
    if not current_home().pods_dir.is_dir():
        return ""
    for entry in sorted(current_home().pods_dir.iterdir()):
        if entry.name == exclude or not pod_mcp_servers_file(entry.name).is_file():
            continue
        if any(s.name == name for s in load_pod_mcp_servers(entry.name)):
            return entry.name
    return ""


class McpServerDocError(InvalidInput):
    """A ``kind: mcp-server`` document is unreadable or invalid; the message names the file."""


class McpServerDocument(BaseModel):
    """A ``kind: mcp-server`` document: the global server fields, with the read/write assertion
    under ``access`` because ``kind`` is the envelope."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["mcp-server"]
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = 0.0
    access: Literal["read", "write"] = "write"
    tools: list[str] = Field(default_factory=list)

    def to_config(self) -> McpServerConfig:
        return McpServerConfig(
            name=self.name,
            command=self.command,
            args=self.args,
            env=self.env,
            timeout=self.timeout,
            kind=self.access,
            tools=self.tools,
        )


def mcp_server_document(config: McpServerConfig) -> dict[str, Any]:
    """*config* as a ``kind: mcp-server`` document mapping (the inverse of ``to_config``)."""
    doc: dict[str, Any] = {"kind": "mcp-server", "name": config.name, "command": config.command}
    if config.args:
        doc["args"] = list(config.args)
    if config.env:
        doc["env"] = dict(config.env)
    if config.timeout:
        doc["timeout"] = config.timeout
    doc["access"] = config.kind
    if config.tools:
        doc["tools"] = list(config.tools)
    return doc


def load_mcp_server_document(path: str | Path) -> McpServerConfig:
    """Read *path* as a ``kind: mcp-server`` document. Raises ``McpServerDocError`` naming the
    file on any failure, including a name that would not be a legal server name."""
    p = Path(path)
    try:
        import yaml as _yaml  # type: ignore[import-untyped]

        raw = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except ImportError:
        raise McpServerDocError(f"{p}: PyYAML not installed -- run: pip install pyyaml") from None
    except Exception as exc:
        raise McpServerDocError(f"{p}: cannot read document: {exc}") from exc
    if not isinstance(raw, dict):
        raise McpServerDocError(f"{p}: document must be a mapping")
    try:
        config = McpServerDocument.model_validate(raw).to_config()
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        raise McpServerDocError(f"{p}: {field}: {first['msg']}") from exc
    if not _NAME_RE.fullmatch(config.name):
        raise McpServerDocError(
            f"{p}: name {config.name!r} must contain only letters, digits, '-' or '_'"
        )
    return config


def add_mcp_server(config: McpServerConfig) -> None:
    """Add one server config. Raises ``ValueError`` on a bad/duplicate name.

    Lock-safe: uses ``platform/store.py``'s ``read_modify_write`` so two concurrent ``add`` calls
    cannot race each other into losing an entry."""
    if not config.name:
        raise InvalidInput("MCP server name is required")
    if not _NAME_RE.fullmatch(config.name):
        raise InvalidInput(
            f"MCP server name {config.name!r} must contain only letters, digits, '-' or '_'"
        )

    def _add(current: dict[str, Any]) -> dict[str, Any]:
        reg = McpServerRegistry.model_validate(current)
        if any(s.name == config.name for s in reg.servers):
            raise InvalidInput(f"an MCP server named {config.name!r} is already configured")
        reg.servers.append(config)
        return reg.model_dump(by_alias=True)

    read_modify_write(current_home().mcp_servers_file, _add)


def remove_mcp_server(name: str) -> bool:
    """Remove a configured server by name. Returns False if it wasn't there."""
    removed = False

    def _remove(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal removed
        reg = McpServerRegistry.model_validate(current)
        kept = [s for s in reg.servers if s.name != name]
        if len(kept) == len(reg.servers):
            return None  # nothing changes -- read_modify_write leaves the file untouched
        removed = True
        return McpServerRegistry(servers=kept).model_dump(by_alias=True)

    read_modify_write(current_home().mcp_servers_file, _remove)
    return removed
