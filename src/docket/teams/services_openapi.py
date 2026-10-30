"""Operations imported from an OpenAPI document (specs/functional/service-client.spec.md)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from docket.kernel.service import ServiceConfig


@dataclass(frozen=True)
class OpenApiImport:
    """The service built from a document, what was skipped and what was dropped."""

    config: ServiceConfig
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def import_openapi(
    path: str | Path,
    name: str,
    *,
    operations: Sequence[str] = (),
    base_url: str = "",
    auth_header: str = "",
    secret: str = "",
) -> OpenApiImport:
    raise NotImplementedError
