"""The typed configuration of a pod's records: one set (a table), its optional key and its typed
columns. Pure data and the rules that bound it; nothing here opens a file
(specs/functional/pod-records.spec.md "The document")."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

ColumnType = Literal["string", "integer", "number", "boolean", "date"]

_NAME = r"^[a-z][a-z0-9_]*$"
MAX_COLUMNS = 40

RECORDS_TOOL_PREFIX = "rec__"
# The allow-list entry that names every record tool of the pod.
RECORDS_ALL_ENTRY = "rec"
RECORDS_QUERY_TOOL = RECORDS_TOOL_PREFIX + "query"


def records_tool_name(set_name: str = "", operation: str = "") -> str:
    """``rec__<set>__<operation>``, ``rec__<set>`` for the whole set or ``rec__<operation>`` for a
    tool of the pod (``rec__query``, ``rec__export``)."""
    return RECORDS_TOOL_PREFIX + "__".join(part for part in (set_name, operation) if part)


class RecordColumn(BaseModel):
    """One column of a set. ``required`` is carried and published; the tools enforce it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_NAME)
    type: ColumnType
    required: bool = False
    description: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def _not_reserved(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith("_"):
            raise ValueError(
                "a column name cannot start with an underscore: docket fills _id, _at, _task, "
                "_session, _step and _updated_at itself"
            )
        return value


class RecordSet(BaseModel):
    """A set: ``name``, an optional ``key`` column and 1 to 40 ``columns``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_NAME)
    description: str = ""
    columns: list[RecordColumn] = Field(min_length=1, max_length=MAX_COLUMNS)
    key: str | None = None

    @field_validator("columns")
    @classmethod
    def _names_are_unique(cls, columns: list[RecordColumn]) -> list[RecordColumn]:
        seen: set[str] = set()
        for column in columns:
            if column.name in seen:
                raise ValueError(f"column {column.name!r} is declared twice")
            seen.add(column.name)
        return columns

    @field_validator("key")
    @classmethod
    def _key_is_a_column(cls, key: str | None, info: ValidationInfo) -> str | None:
        columns = info.data.get("columns")
        if key is not None and columns is not None and key not in [c.name for c in columns]:
            raise ValueError(f"the key {key!r} is not one of the columns")
        return key
