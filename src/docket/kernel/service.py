"""The typed configuration of a declared external HTTP service: its address, how it authenticates and
the operations a pod may perform, each with the access it needs. Pure data and the rules that
bound it; nothing here makes a call or resolves a secret (specs/functional/service-client.spec.md).
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# A `${secret:<name>}` in an auth value names a stored secret; it is kept as written until a call
# resolves it.
_SECRET_REF = re.compile(r"\$\{secret:([A-Za-z0-9_.-]+)\}")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

SERVICE_TOOL_PREFIX = "svc__"


def service_tool_name(service: str, operation: str = "") -> str:
    """``svc__<service>__<operation>``, or ``svc__<service>`` for the whole service."""
    return f"{SERVICE_TOOL_PREFIX}{service}" + (f"__{operation}" if operation else "")


def service_of_tool(tool_name: str) -> str:
    """The service a ``svc__<service>__<operation>`` tool belongs to; ``''`` for any other name."""
    if not tool_name.startswith(SERVICE_TOOL_PREFIX):
        return ""
    service, sep, operation = tool_name[len(SERVICE_TOOL_PREFIX) :].partition("__")
    return service if sep and operation else ""


def secret_names(value: str) -> list[str]:
    """The secret names *value* refers to, in order."""
    return _SECRET_REF.findall(value)


class ServiceAuth(BaseModel):
    """The header every call carries; ``value`` may hold ``${secret:<name>}`` references."""

    model_config = ConfigDict(extra="forbid")

    header: str = Field(pattern=r"^[A-Za-z0-9-]+$")
    value: str = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def _references_are_well_formed(cls, value: str) -> str:
        if "${secret:" in _SECRET_REF.sub("", value):
            raise ValueError("a ${secret:<name>} reference needs a name of letters, digits, - _ .")
        return value


class OperationParam(BaseModel):
    """One typed parameter of an operation: a path segment or a query value."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    in_: Literal["path", "query"] = Field(alias="in")
    type: Literal["string", "integer", "number", "boolean"] = "string"
    required: bool = False

    @model_validator(mode="after")
    def _a_path_param_is_required(self) -> OperationParam:
        if self.in_ == "path":
            self.required = True
        return self


class Operation(BaseModel):
    """One call a pod may make. ``access`` is resolved from the method when omitted."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(pattern=r"^/[^\s?#]*$")
    params: list[OperationParam] = Field(default_factory=list)
    body: dict[str, Any] | None = None
    access: Literal["read", "send"] | None = None
    description: str = ""

    @field_validator("body")
    @classmethod
    def _body_is_an_object_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and value.get("type", "object") != "object":
            raise ValueError("body must be a JSON Schema of type object")
        return value

    @model_validator(mode="after")
    def _rules(self) -> Operation:
        who = f"operation {self.name!r}"
        if self.access is None:
            self.access = "send" if self.method in _WRITE_METHODS else "read"
        elif self.method in _WRITE_METHODS and self.access != "send":
            raise ValueError(f"{who}: {self.method} is always send, not {self.access}")
        if self.method == "GET" and self.body is not None:
            raise ValueError(f"{who}: a GET has no body")
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise ValueError(f"{who}: a parameter is declared twice")
        in_path = {p.name for p in self.params if p.in_ == "path"}
        placeholders = set(_PLACEHOLDER.findall(self.path))
        if placeholders - in_path:
            missing = min(placeholders - in_path)
            raise ValueError(f"{who}: path placeholder {{{missing}}} has no 'in: path' parameter")
        if in_path - placeholders:
            raise ValueError(
                f"{who}: path parameter {min(in_path - placeholders)!r} is not in the path"
            )
        return self


class ServiceConfig(BaseModel):
    """One declared service. ``baseUrl`` carries no credentials, query or fragment; ``hosts`` are
    extra hosts a call may reach; ``timeout`` 0 means the default."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    baseUrl: str
    auth: ServiceAuth | None = None
    hosts: list[str] = Field(default_factory=list)
    timeout: float = Field(default=0.0, ge=0)
    idempotencyHeader: str = Field(default="", pattern=r"^[A-Za-z0-9-]*$")
    operations: list[Operation] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_has_no_double_underscore(cls, value: str) -> str:
        if "__" in value:
            raise ValueError("name must not contain '__' (it separates the parts of a tool name)")
        return value

    @field_validator("baseUrl")
    @classmethod
    def _an_http_address(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("baseUrl must be an http or https URL with a host")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("baseUrl carries no user information, query or fragment")
        return value

    @field_validator("hosts")
    @classmethod
    def _host_names(cls, value: list[str]) -> list[str]:
        for host in value:
            if not re.fullmatch(r"[A-Za-z0-9.:\[\]-]+", host):
                raise ValueError(f"{host!r} is not a host name")
        return value

    @model_validator(mode="after")
    def _operation_names_are_unique(self) -> ServiceConfig:
        names = [op.name for op in self.operations]
        for name in names:
            if names.count(name) > 1:
                raise ValueError(f"operation {name!r} is declared twice")
        return self


class ServiceRegistry(BaseModel):
    """The on-disk shape of ``Home.services_file``."""

    model_config = ConfigDict(extra="forbid")

    services: list[ServiceConfig] = Field(default_factory=list)
