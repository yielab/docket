"""Operations imported from an OpenAPI 3 or 2 (Swagger) document into a ``kind: service`` configuration
(specs/functional/service-client.spec.md, "From OpenAPI"). The mapping is built as a plain
``kind: service`` mapping and validated by the same model a written document passes through; an
operation that cannot be mapped is skipped and listed, never guessed. No network is touched and a
``$ref`` is followed only inside the file."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from docket.kernel.errors import InvalidInput
from docket.kernel.service import Operation, ServiceConfig
from docket.kernel.text import one_line
from docket.teams import services as _services

_METHODS = ("get", "post", "put", "patch", "delete")
_UNSUPPORTED = ("head", "options", "trace")
_SCALARS = ("string", "integer", "number", "boolean")


@dataclass(frozen=True)
class OpenApiImport:
    """The service built from a document, the operations skipped and the parameters dropped."""

    config: ServiceConfig
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class _Skip(InvalidInput):
    """One operation cannot be mapped; the message is the reason listed for it."""


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InvalidInput(f"{path}: cannot read document: {exc}") from exc
    if not isinstance(raw, dict):
        raise InvalidInput(f"{path}: document must be a mapping")
    if not (_is_v2(raw) or str(raw.get("openapi", "")).startswith("3.")):
        raise InvalidInput(
            f"{path}: not an OpenAPI 3 or Swagger 2 document (needs 'openapi: 3.x' or 'swagger: 2.0')"
        )
    return raw


def _is_v2(doc: dict[str, Any]) -> bool:
    return str(doc.get("swagger", "")).startswith("2.")


def _pointer(doc: dict[str, Any], ref: str) -> Any:
    node: Any = doc
    for part in ref[2:].split("/"):
        key = unquote(part).replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            raise _Skip(f"$ref {ref!r} does not resolve in this file")
    return node


def _deref(node: Any, doc: dict[str, Any], trail: tuple[str, ...] = ()) -> Any:
    """*node* with every in-file ``$ref`` replaced by its target."""
    if isinstance(node, list):
        return [_deref(item, doc, trail) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        if not ref.startswith("#/"):
            raise _Skip(f"$ref {ref!r} points outside this file")
        if ref in trail:
            raise _Skip(f"$ref {ref!r} is a cycle")
        return _deref(_pointer(doc, ref), doc, (*trail, ref))
    return {key: _deref(value, doc, trail) for key, value in node.items()}


def _merged(
    item: dict[str, Any], op: dict[str, Any], doc: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    """The path item's parameters overridden by the operation's, keyed by name and location."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*item.get("parameters", []), *op.get("parameters", [])]:
        param = _deref(raw, doc)
        merged[(str(param.get("name")), str(param.get("in")))] = param
    return merged


def _params(
    merged: dict[tuple[str, str], dict[str, Any]], v2: bool, label: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """The operation's path and query parameters and the notes for what was dropped."""
    mapped: list[dict[str, Any]] = []
    notes: list[str] = []
    for (name, where), param in merged.items():
        if v2 and where == "body":
            continue
        if where == "formData":
            raise _Skip(f"formData parameter {name!r} cannot be sent as JSON")
        if where not in ("path", "query"):
            if param.get("required"):
                raise _Skip(f"required {where} parameter {name!r} cannot be sent")
            notes.append(f"{label}: optional {where} parameter {name!r} dropped")
            continue
        kind = (param if v2 else param.get("schema") or {}).get("type", "string")
        if kind not in _SCALARS:
            raise _Skip(f"parameter {name!r} is of type {kind}, not a scalar")
        mapped.append(
            {"name": name, "in": where, "type": kind, "required": bool(param.get("required"))}
        )
    return mapped, notes


def _is_json(media: Any) -> bool:
    kind = str(media).split(";")[0].strip().lower()
    return kind == "application/json" or kind.endswith("+json")


def _body_v2(
    merged: dict[tuple[str, str], dict[str, Any]], op: dict[str, Any], doc: dict[str, Any]
) -> dict[str, Any] | None:
    """The schema of the ``in: body`` parameter, when the operation accepts JSON."""
    found = [param for (_, where), param in merged.items() if where == "body"]
    if not found:
        return None
    media = op.get("consumes") or doc.get("consumes") or []
    if media and not any(_is_json(kind) for kind in media):
        raise _Skip(f"request body has no JSON form ({', '.join(map(str, media))})")
    schema = found[0].get("schema")
    if not isinstance(schema, dict):
        raise _Skip(f"body parameter {found[0].get('name')!r} has no schema")
    return dict(schema)


def _body(op: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any] | None:
    request = _deref(op.get("requestBody"), doc) if op.get("requestBody") else {}
    content = request.get("content") or {}
    if not content:
        return None
    for media, entry in content.items():
        if _is_json(media):
            return dict((entry or {}).get("schema") or {"type": "object"})
    raise _Skip(f"request body has no JSON form ({', '.join(map(str, content))})")


def _summary(op: dict[str, Any]) -> str:
    text = str(op.get("summary") or op.get("description") or "")
    return one_line(text)


def _map(
    item: dict[str, Any], op: dict[str, Any], method: str, path: str, doc: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """One ``operations`` entry (checked by the ``Operation`` model) and its notes."""
    label = str(op["operationId"])
    v2 = _is_v2(doc)
    merged = _merged(item, op, doc)
    params, notes = _params(merged, v2, label)
    entry: dict[str, Any] = {
        "name": label,
        "method": method.upper(),
        "path": path,
        "params": params,
        "description": _summary(op),
    }
    body = _body_v2(merged, op, doc) if v2 else _body(op, doc)
    if body is not None:
        entry["body"] = body
    try:
        Operation.model_validate(entry)
    except ValidationError as exc:
        raise _Skip(_services.first_error(exc)) from exc
    return entry, notes


def _candidates(doc: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], str, str]]:
    found = []
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in (*_METHODS, *_UNSUPPORTED):
            if isinstance(item.get(method), dict):
                found.append((item, item[method], method, str(path)))
    return found


def _server_url(doc: dict[str, Any]) -> str:
    servers = doc.get("servers") or []
    return str(servers[0].get("url", "")) if servers and isinstance(servers[0], dict) else ""


def _swagger_url(doc: dict[str, Any]) -> str:
    """``scheme://host/basePath`` from an OpenAPI 2 document, or empty when it cannot be built."""
    schemes = [str(kind).lower() for kind in doc.get("schemes") or []]
    scheme = next((kind for kind in schemes if kind in ("http", "https")), "")
    host = str(doc.get("host") or "")
    base = str(doc.get("basePath") or "").strip("/")
    return f"{scheme}://{host}/{base}" if scheme and host else ""


def _base_url(doc: dict[str, Any], given: str, source: Path) -> str:
    if given:
        return given.rstrip("/")
    url = _swagger_url(doc) if _is_v2(doc) else _server_url(doc)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or "{" in url:
        raise InvalidInput(f"{source}: no absolute server URL in the document; give --base-url")
    return url.rstrip("/")


def _auth(header: str, secret: str) -> dict[str, str] | None:
    if bool(header) != bool(secret):
        raise InvalidInput("--auth-header and --secret go together")
    return {"header": header, "value": "${secret:" + secret + "}"} if header else None


def import_openapi(
    path: str | Path,
    name: str,
    *,
    operations: Sequence[str] = (),
    base_url: str = "",
    auth_header: str = "",
    secret: str = "",
) -> OpenApiImport:
    """Build service *name* from the OpenAPI 3 or 2 document at *path*. *operations* narrows to those
    ``operationId`` values. Raises ``InvalidInput`` for an unreadable document, an unknown id, no
    usable base URL, no mappable operation or a configuration the service model refuses."""
    source = Path(path)
    doc = _read(source)
    auth = _auth(auth_header, secret)
    url = _base_url(doc, base_url, source)
    candidates = _candidates(doc)
    ids = {str(op.get("operationId")) for _, op, _, _ in candidates if op.get("operationId")}
    unknown = [wanted for wanted in operations if wanted not in ids]
    if unknown:
        raise InvalidInput(f"{source}: no operationId {', '.join(unknown)}")
    mapped: list[dict[str, Any]] = []
    skipped: list[str] = []
    notes: list[str] = []
    for item, op, method, route in candidates:
        label = str(op.get("operationId") or f"{method.upper()} {route}")
        if operations and op.get("operationId") not in operations:
            continue
        try:
            if method in _UNSUPPORTED:
                raise _Skip(f"{method.upper()} is not a supported method")
            if not op.get("operationId"):
                raise _Skip("no operationId")
            if any(entry["name"] == label for entry in mapped):
                raise _Skip("operationId appears twice")
            entry, entry_notes = _map(item, op, method, route, doc)
        except _Skip as exc:
            skipped.append(f"{label}: {exc}")
            continue
        mapped.append(entry)
        notes.extend(entry_notes)
    if not mapped:
        reasons = "".join(f"\n  {line}" for line in skipped)
        raise InvalidInput(f"{source}: no operation could be imported{reasons}")
    raw: dict[str, Any] = {"kind": "service", "name": name, "baseUrl": url, "operations": mapped}
    if auth:
        raw["auth"] = auth
    return OpenApiImport(_services.service_from_mapping(raw, str(source)), skipped, notes)
