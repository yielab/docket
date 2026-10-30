"""A pod's records: declared, typed tables in one SQLite file (`pod-records.spec.md`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COLUMN_TYPES = ("string", "integer", "number", "boolean", "date")


class RecordsError(ValueError):
    """A request the store refused; the file is as it was."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class RecordMeta:
    task: str | None = None
    session: str | None = None
    step: str | None = None


@dataclass(frozen=True)
class EnsureResult:
    created: bool
    added: tuple[str, ...]


@dataclass(frozen=True)
class AddResult:
    row: dict[str, Any]
    created: bool


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    cut: int


def check_value(column: Column, value: object) -> object:
    raise NotImplementedError


def render_markdown(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    raise NotImplementedError


class RecordsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def ensure_table(
        self, set_name: str, columns: Sequence[Column], key: str | None = None
    ) -> EnsureResult:
        raise NotImplementedError

    def add(self, set_name: str, values: dict[str, Any], meta: RecordMeta) -> AddResult:
        raise NotImplementedError

    def update(
        self, set_name: str, match: dict[str, Any], values: dict[str, Any], meta: RecordMeta
    ) -> dict[str, Any]:
        raise NotImplementedError

    def query(self, sql: str, max_rows: int, max_chars: int, timeout_s: float = 5.0) -> QueryResult:
        raise NotImplementedError

    def export(self, sql: str, path: Path, fmt: str, timeout_s: float = 30.0) -> int:
        raise NotImplementedError
