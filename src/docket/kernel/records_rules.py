"""The rules every records backend shares, pure and engine-free
(specs/functional/pod-records.spec.md "The store", "Queries"): names, values against a column type,
the declaration check and its refusals, the row and character bound of a read, and the rendering
of an export. An adapter keeps only what is its engine's."""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from docket.kernel.records import COLUMN_TYPES, RecordsError, RecordSet
from docket.kernel.records_port import ReadLimits, Row, Rows, SetChange
from docket.kernel.text import ellipsize

EXPORT_FORMATS = ("csv", "markdown")

_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _types(record_set: RecordSet) -> dict[str, str]:
    return {c.name: c.type for c in record_set.columns}


def _check_name(what: str, name: object) -> str:
    if not isinstance(name, str) or not _NAME.match(name):
        raise RecordsError(
            f"{what} name {name!r} must be lowercase letters, digits and underscores, "
            "starting with a letter"
        )
    return name


def _shown(value: object) -> str:
    return ellipsize(repr(value), 40)


def _valid_date(text: str) -> bool:
    if not _DATE.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def check_value(column: str, kind: str, value: object) -> object:
    """*value* when it is of type *kind* or null; `RecordsError` naming *column* otherwise."""
    if value is None:
        return None
    ok: bool
    if kind == "string":
        ok = isinstance(value, str)
    elif kind == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        ok = ok and math.isfinite(value)  # type: ignore[arg-type]
    elif kind == "boolean":
        ok = isinstance(value, bool)
    elif kind == "date":
        ok = isinstance(value, str) and _valid_date(value)
    else:
        raise RecordsError(f"column {column!r} has the unknown type {kind!r}")
    if not ok:
        raise RecordsError(f"column {column!r}: {_shown(value)} is not a valid {kind}")
    return value


def _checked(declared: RecordSet, values: Row) -> Row:
    types = _types(declared)
    out: Row = {}
    for name, value in values.items():
        kind = types.get(name)
        if kind is None:
            raise RecordsError(f"set {declared.name!r} has no column {name!r}")
        out[name] = check_value(name, kind, value)
    return out


def check_add(declared: RecordSet, values: Row) -> Row:
    """*values* checked against the declared columns; the key column must be present and not null."""
    clean = _checked(declared, values)
    if declared.key is not None and clean.get(declared.key) is None:
        raise RecordsError(f"set {declared.name!r}: the key column {declared.key!r} is required")
    return clean


def check_update(declared: RecordSet, match: Row, values: Row) -> tuple[str, Any, Row]:
    """The column and value that name the one row to change, and *values* checked."""
    name = declared.name
    allowed = ["_id", *([declared.key] if declared.key else [])]
    if len(match) != 1 or next(iter(match)) not in allowed:
        raise RecordsError(
            f"set {name!r}: match one row by {' or '.join(map(repr, allowed))}, "
            f"not by {sorted(match)}"
        )
    column, wanted = next(iter(match.items()))
    if column == "_id":
        if not isinstance(wanted, int) or isinstance(wanted, bool):
            raise RecordsError(f"set {name!r}: _id must be an integer, not {_shown(wanted)}")
    else:
        check_value(column, _types(declared)[column], wanted)
    if not values:
        raise RecordsError(f"set {name!r}: an update needs at least one value")
    if declared.key in values:
        raise RecordsError(f"set {name!r}: the key column {declared.key!r} cannot change")
    return column, wanted, _checked(declared, values)


def check_declaration(record_set: RecordSet) -> None:
    """Refuse a declaration no backend may store: a bad name or type, a repeat, a key that is no
    column, no column at all."""
    _check_name("set", record_set.name)
    if not record_set.columns:
        raise RecordsError(f"set {record_set.name!r} needs at least one column")
    seen: set[str] = set()
    for column in record_set.columns:
        _check_name("column", column.name)
        if column.type not in COLUMN_TYPES:
            raise RecordsError(
                f"column {column.name!r} has the type {column.type!r}; "
                f"use one of {', '.join(COLUMN_TYPES)}"
            )
        if column.name in seen:
            raise RecordsError(f"column {column.name!r} is declared twice")
        seen.add(column.name)
    if record_set.key is not None and record_set.key not in seen:
        raise RecordsError(
            f"the key {record_set.key!r} is not a declared column of set {record_set.name!r}"
        )


def plan_change(current: RecordSet | None, wanted: RecordSet) -> SetChange:
    """What declaring *wanted* over *current* (None: not declared yet) does. Refuses, changing
    nothing, a bad declaration, a removal, a rename, a retype and a new key."""
    check_declaration(wanted)
    if current is None:
        return SetChange(created=True, added=())
    name, have, want = wanted.name, _types(current), _types(wanted)
    for column, kind in have.items():
        if column not in want:
            raise RecordsError(
                f"set {name!r}: column {column!r} is declared and was left out "
                "(a removal or a rename); nothing was changed"
            )
        if want[column] != kind:
            raise RecordsError(
                f"set {name!r}: column {column!r} is declared {kind}, not {want[column]}; "
                "nothing was changed"
            )
    if wanted.key != current.key:
        raise RecordsError(
            f"set {name!r}: the key is {current.key!r}, not {wanted.key!r}; "
            "the key cannot change; nothing was changed"
        )
    return SetChange(created=False, added=tuple(n for n in want if n not in have))


def bound_rows(columns: Sequence[str], rows: Iterable[Sequence[Any]], limits: ReadLimits) -> Rows:
    """The rows that fit `limits.max_rows` and, as JSON, `limits.max_chars`, in order; the rest
    count as cut."""
    kept: list[tuple[Any, ...]] = []
    used = 0
    cut = 0
    full = False
    for row in rows:
        size = len(json.dumps(list(row), default=str))
        fits_rows = limits.max_rows is None or len(kept) < limits.max_rows
        fits_chars = limits.max_chars is None or used + size <= limits.max_chars
        if not full and fits_rows and fits_chars:
            kept.append(tuple(row))
            used += size
        else:
            full = True
            cut += 1
    return Rows(tuple(columns), kept, cut)


def check_format(fmt: str) -> None:
    """Refuse an export format that is not one of `EXPORT_FORMATS`."""
    if fmt not in EXPORT_FORMATS:
        raise RecordsError(f"cannot export as {fmt!r}; use {' or '.join(EXPORT_FORMATS)}")


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_lines(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> Iterator[str]:
    yield "| " + " | ".join(_cell(c) for c in columns) + " |\n"
    yield "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows:
        yield "| " + " | ".join(_cell(v) for v in row) + " |\n"


def write_export(target: Path, fmt: str, columns: Sequence[str], rows: Iterable[Any]) -> int:
    """Write *columns* and every row of *rows* to *target* as csv or markdown (`|` and newlines in
    a cell escaped, null empty) through a `.part` file, so a failure leaves no half file. Returns the
    number of rows."""
    partial = target.with_name(target.name + ".part")
    count = 0

    def counted() -> Iterator[Any]:
        nonlocal count
        for row in rows:
            count += 1
            yield row

    try:
        with partial.open("w", encoding="utf-8", newline="") as out:
            if fmt == "csv":
                writer = csv.writer(out)
                writer.writerow(columns)
                writer.writerows(counted())
            else:
                out.writelines(_markdown_lines(columns, counted()))
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return count
