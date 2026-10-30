"""Declared external services: the ``kind: service`` document, the operator's file
(``Home.services_file``, written through ``platform/store.py``), a pod's own ``services/`` files, and
the rule that a service and an MCP server never share a name
(specs/functional/service-client.spec.md). A ``${secret:<name>}`` reference is kept as written."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.kernel.service import ServiceConfig, ServiceRegistry
from docket.platform import read_json, read_modify_write
from docket.teams import mcp_servers as _mcp_servers


class ServiceDocError(InvalidInput):
    """A ``kind: service`` document is unreadable or invalid; the message names the file."""


class ServiceDocument(ServiceConfig):
    """A ``kind: service`` document: the service's fields under the ``kind`` envelope."""

    kind: Literal["service"]


def load_service_document(path: str | Path) -> ServiceConfig:
    """Read *path* as a ``kind: service`` document. Raises ``ServiceDocError`` naming the file and
    the first failing field."""
    p = Path(path)
    try:
        import yaml as _yaml  # type: ignore[import-untyped]

        raw = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except ImportError:
        raise ServiceDocError(f"{p}: PyYAML not installed -- run: pip install pyyaml") from None
    except Exception as exc:
        raise ServiceDocError(f"{p}: cannot read document: {exc}") from exc
    if not isinstance(raw, dict):
        raise ServiceDocError(f"{p}: document must be a mapping")
    try:
        document = ServiceDocument.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        message = str(first["msg"]).removeprefix("Value error, ")
        raise ServiceDocError(f"{p}: {field}: {message}") from exc
    return ServiceConfig.model_validate(document.model_dump(by_alias=True, exclude={"kind"}))


def service_files(directory: Path) -> list[Path]:
    """``services/*.yaml|yml`` directly under *directory*, sorted by name."""
    folder = directory / "services"
    return sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]) if folder.is_dir() else []


def pod_services_dir(project: str) -> Path:
    """Where *project*'s own services live: ``<pod config dir>/services``."""
    return current_home().pod_config_dir(project) / "services"


def load_pod_services(project: str) -> list[ServiceConfig]:
    """*project*'s own services, by file name. A file that no longer validates is skipped."""
    found: list[ServiceConfig] = []
    for path in service_files(current_home().pod_config_dir(project)):
        try:
            found.append(load_service_document(path))
        except ServiceDocError:
            continue
    return found


def load_services(project: str = "") -> list[ServiceConfig]:
    """The operator's services, in on-disk order. With *project*, the pod's own come first and win
    a name collision (the one scope order every kind resolves in)."""
    stored = ServiceRegistry.model_validate(read_json(current_home().services_file)).services
    if not project:
        return stored
    own = load_pod_services(project)
    taken = {s.name for s in own}
    return [*own, *(s for s in stored if s.name not in taken)]


def pod_scoped_owner(name: str) -> str:
    """The pod whose own ``services/`` declare *name*, else ``""``."""
    if not current_home().pods_dir.is_dir():
        return ""
    for entry in sorted(current_home().pods_dir.iterdir()):
        if any(s.name == name for s in load_pod_services(entry.name)):
            return entry.name
    return ""


def service_name_conflict(name: str) -> str:
    """Why an MCP server may not be named *name*: the service that holds it, else ``""``."""
    if any(s.name == name for s in load_services()):
        return f"a service named {name!r} is already configured; a service and an MCP server never share a name"
    owner = pod_scoped_owner(name)
    if owner:
        return f"pod {owner!r} declares a service named {name!r}; a service and an MCP server never share a name"
    return ""


def mcp_name_conflict(name: str) -> str:
    """Why a service may not be named *name*: the MCP server that holds it, else ``""``."""
    if any(s.name == name for s in _mcp_servers.load_mcp_servers()):
        return f"an MCP server named {name!r} is already configured; a service and an MCP server never share a name"
    owner = _mcp_servers.pod_scoped_owner(name)
    if owner:
        return f"pod {owner!r} declares an MCP server named {name!r}; a service and an MCP server never share a name"
    return ""


def add_service(config: ServiceConfig) -> None:
    """Store one service in the operator's file. Raises ``InvalidInput`` for a stored name or a
    name an MCP server holds; nothing is written then. Lock-safe through ``read_modify_write``."""
    conflict = mcp_name_conflict(config.name)
    if conflict:
        raise InvalidInput(conflict)

    def _add(current: dict[str, Any]) -> dict[str, Any]:
        registry = ServiceRegistry.model_validate(current)
        if any(s.name == config.name for s in registry.services):
            raise InvalidInput(f"a service named {config.name!r} is already configured")
        registry.services.append(config)
        return registry.model_dump(mode="json", by_alias=True)

    read_modify_write(current_home().services_file, _add)


def remove_service(name: str) -> bool:
    """Remove the operator's service *name*. ``False`` when it was not there."""
    removed = False

    def _remove(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal removed
        registry = ServiceRegistry.model_validate(current)
        kept = [s for s in registry.services if s.name != name]
        if len(kept) == len(registry.services):
            return None
        removed = True
        return ServiceRegistry(services=kept).model_dump(mode="json", by_alias=True)

    read_modify_write(current_home().services_file, _remove)
    return removed
