"""Stub: the service executor's surface, so the RED tests collect and fail on behaviour."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from docket.kernel.tool_outcome import ToolOutcome


class Refused(Exception):
    kind = ""


@dataclass(frozen=True)
class ServiceRequest:
    method: str
    base_url: str
    path: str = ""
    path_params: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, object] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: object | None = None
    hosts: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()


def build_url(request: ServiceRequest) -> str:
    raise NotImplementedError


def address_refused(address: str) -> bool:
    raise NotImplementedError


def check_headers(headers: Mapping[str, str]) -> None:
    raise NotImplementedError


def redactions(headers: Mapping[str, str], secrets: tuple[str, ...]) -> tuple[str, ...]:
    raise NotImplementedError


def redact(text: str, values: tuple[str, ...]) -> str:
    raise NotImplementedError


def call_operation(request: ServiceRequest) -> ToolOutcome:
    raise NotImplementedError
