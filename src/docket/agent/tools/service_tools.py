"""A declared service's operations as tools: one ``Tool`` per operation, registered into a
``ToolRegistry`` so every call still passes ``agent.tools.registry.dispatch_tool``
(specs/functional/service-client.spec.md, "Tools"). **Wired to the live turn path**:
``hops/application/driver_support.py`` loads the turn's services, resolves each ``auth`` secret
through the secret store and hands the result here. The tool's ``kind`` is the operation's
resolved access (``read`` or ``send``); the handler builds a ``ServiceRequest`` and returns what
``platform.call_operation`` reports, which holds the perimeter. ``load_service_tools`` never
raises."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.kernel.errors import InvalidInput
from docket.kernel.service import Operation, OperationParam, ServiceConfig, service_tool_name
from docket.kernel.tool_outcome import ToolOutcome
from docket.platform import ServiceRequest, call_operation

__all__ = ["ResolvedService", "ServiceLoadResult", "load_service_tools"]

_BAD_REQUEST = "service_bad_request"
_TASK_HEADER = "X-Docket-Task"
_KEY_DIGITS = 32
CallFn = Callable[[ServiceRequest], ToolOutcome]


@dataclass(frozen=True)
class ResolvedService:
    """A service ready to call: its document and the headers its ``auth`` resolved to (with the
    secret values they hold, so the executor can scrub them from what it returns)."""

    config: ServiceConfig
    headers: Mapping[str, str] = field(default_factory=dict)
    secrets: tuple[str, ...] = ()


@dataclass
class ServiceLoadResult:
    """Outcome of loading one service's tools: what was registered, or why it was left out."""

    service: str
    ok: bool
    registered: tuple[str, ...] = ()
    error: str = ""


def _schema(operation: Operation) -> dict[str, Any]:
    properties: dict[str, Any] = {p.name: {"type": p.type} for p in operation.params}
    required = [p.name for p in operation.params if p.required]
    if operation.body is not None:
        properties["body"] = operation.body
        if operation.body.get("required"):
            required.append("body")
    return {"type": "object", "properties": properties, "required": required}


def _value(param: OperationParam, value: Any) -> Any:
    """*value* as *param*'s type allows, else an ``InvalidInput`` naming the parameter."""
    plain = not isinstance(value, bool | dict | list | tuple)
    if param.type == "boolean" and isinstance(value, bool):
        return value
    if param.type == "integer" and isinstance(value, int) and plain:
        return value
    if param.type == "number" and isinstance(value, int | float) and plain:
        return value
    if param.type == "string" and isinstance(value, str | int | float) and plain:
        return str(value)
    raise InvalidInput(f"argument {param.name!r} must be a {param.type}")


def _request(
    service: ResolvedService, operation: Operation, args: dict[str, Any]
) -> ServiceRequest:
    """The request one call makes. Raises ``InvalidInput`` for an argument the operation does not
    declare or one of the wrong type."""
    declared = {p.name: p for p in operation.params}
    unknown = [name for name in args if name not in declared and name != "body"]
    if unknown or ("body" in args and operation.body is None):
        names = ", ".join(sorted([*unknown, *(["body"] if operation.body is None else [])]))
        raise InvalidInput(f"unknown argument(s): {names}")
    path_params: dict[str, str] = {}
    query: dict[str, object] = {}
    for name, value in args.items():
        if name == "body":
            continue
        param = declared[name]
        checked = _value(param, value)
        if param.in_ == "path":
            path_params[name] = str(checked)
        else:
            query[name] = checked
    body = args.get("body")
    if body is not None and not isinstance(body, dict):
        raise InvalidInput("argument 'body' must be an object")
    return ServiceRequest(
        method=operation.method,
        base_url=service.config.baseUrl,
        path=operation.path,
        path_params=path_params,
        query=query,
        headers=dict(service.headers),
        body=body,
        hosts=tuple(service.config.hosts),
        secrets=service.secrets,
        timeout=service.config.timeout,
    )


def _identified(
    service: ResolvedService, operation: Operation, request: ServiceRequest, ctx: ToolContext
) -> ServiceRequest:
    """*request* with the headers the hop supplies: the task it serves and, for a ``send``
    operation of a service that declares one, an idempotency key. Built from *ctx* and the
    validated arguments, never from the model, and set last so nothing else can override them."""
    headers = dict(request.headers)

    def put(name: str, value: str) -> None:
        for existing in [h for h in headers if h.lower() == name.lower()]:
            del headers[existing]
        headers[name] = value

    if ctx.task_id:
        put(_TASK_HEADER, ctx.task_id)
    if operation.access == "send" and service.config.idempotencyHeader:
        identity = [
            ctx.task_id,
            ctx.step_id,
            service.config.name,
            operation.name,
            dict(request.path_params),
            dict(request.query),
            request.body,
        ]
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        put(service.config.idempotencyHeader, digest[:_KEY_DIGITS])
    return dataclasses.replace(request, headers=headers)


def _build_tool(service: ResolvedService, operation: Operation, call: CallFn) -> Tool:
    """Adapt one operation into an ordinary ``Tool`` of its resolved access."""

    def _handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        # dispatch_tool has already gated the call; this builds the request and sends it.
        try:
            request = _request(service, operation, args)
        except InvalidInput as ex:
            return ToolOutcome(False, error=str(ex), refusal=_BAD_REQUEST)
        return call(_identified(service, operation, request, ctx))

    host = (urlsplit(service.config.baseUrl).hostname or "?").lower()
    return Tool(
        name=service_tool_name(service.config.name, operation.name),
        description=(
            f"[service:{service.config.name}] "
            f"{operation.description or f'{operation.method} {operation.path}'}"
        ),
        parameters=_schema(operation),
        handler=_handler,
        kind=operation.access or "read",
        audit_detail=f"method={operation.method} host={host!r}",
        deletes=operation.method == "DELETE",
    )


def load_service_tools(
    registry: ToolRegistry, *, services: Sequence[ResolvedService], call: CallFn = call_operation
) -> list[ServiceLoadResult]:
    """Register one tool per operation of every service in *services*. A name already in
    *registry* is skipped, never replaced. *call* is the executor; tests inject a fake."""
    reports: list[ServiceLoadResult] = []
    for service in services:
        registered: list[str] = []
        for operation in service.config.operations:
            tool = _build_tool(service, operation, call)
            if tool.name in registry:
                continue
            registry.register(tool)
            registered.append(tool.name)
        reports.append(
            ServiceLoadResult(service.config.name, ok=True, registered=tuple(registered))
        )
    return reports
