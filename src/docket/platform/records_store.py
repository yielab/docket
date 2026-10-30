"""A pod's records: declared, typed tables in one SQLite file (`pod-records.spec.md`).

`RecordsStore` is the only module in `src/docket` that imports `sqlite3`
(`tests/architecture/test_records_writer.py`). Each call opens and closes its own connection: a
write inside one `BEGIN IMMEDIATE` transaction, a read on a separate `mode=ro` connection whose
authorizer allows only reads and whose progress handler stops it at a time bound. A SQLite records
file is not docket-owned JSON, so `platform/store.py` stays the only writer of that.
"""

from __future__ import annotations

import contextlib
import csv
import json
import math
import os
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput
from docket.kernel.text import ellipsize

COLUMN_TYPES = ("string", "integer", "number", "boolean", "date")
EXPORT_FORMATS = ("csv", "markdown")

_SQL_TYPE = {
    "string": "TEXT",
    "integer": "INTEGER",
    "number": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
}
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_BUSY_S = 5.0
_VALUE_LENGTH_LIMIT = 1_000_000
_PROGRESS_STEPS = 1000
_READ_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, "SQLITE_RECURSIVE", 33),
    }
)
_DECLARED_DDL = (
    'CREATE TABLE IF NOT EXISTS "_declared" '
    "(set_name TEXT NOT NULL, column_name TEXT NOT NULL, type TEXT NOT NULL, "
    "is_key INTEGER NOT NULL, PRIMARY KEY (set_name, column_name))"
)


class RecordsError(InvalidInput):
    """A request the store refused; the file is as it was."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class RecordMeta:
    """The hop a write came from; docket fills it, the model never does."""

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


@dataclass(frozen=True)
class _Declared:
    columns: dict[str, str]
    key: str | None


def _check_name(what: str, name: object) -> str:
    if not isinstance(name, str) or not _NAME.match(name):
        raise RecordsError(
            f"{what} name {name!r} must be lowercase letters, digits and underscores, "
            "starting with a letter"
        )
    return name


def _quote(name: str) -> str:
    return '"' + name + '"'


def _shown(value: object) -> str:
    return ellipsize(repr(value), 40)


def check_value(column: Column, value: object) -> object:
    """*value* when it is of *column*'s type or null; `RecordsError` naming the column otherwise."""
    if value is None:
        return None
    kind = column.type
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
        raise RecordsError(f"column {column.name!r} has the unknown type {kind!r}")
    if not ok:
        raise RecordsError(f"column {column.name!r}: {_shown(value)} is not a valid {kind}")
    return value


def _valid_date(text: str) -> bool:
    if not _DATE.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_lines(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> Iterator[str]:
    yield "| " + " | ".join(_cell(c) for c in columns) + " |\n"
    yield "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows:
        yield "| " + " | ".join(_cell(v) for v in row) + " |\n"


def render_markdown(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A Markdown table; `|` and newlines in a cell are escaped, null is empty."""
    return "".join(_markdown_lines(columns, rows))


def _declared(db: sqlite3.Connection, set_name: str) -> _Declared | None:
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name = '_declared'").fetchone()
    if not exists:
        return None
    rows = db.execute(
        'SELECT column_name, type, is_key FROM "_declared" WHERE set_name = ? ORDER BY rowid',
        (set_name,),
    ).fetchall()
    if not rows:
        return None
    key = next((r[0] for r in rows if r[2]), None)
    return _Declared({r[0]: r[1] for r in rows}, key)


def _require(db: sqlite3.Connection, set_name: str) -> _Declared:
    declared = _declared(db, set_name)
    if declared is None:
        raise RecordsError(f"set {set_name!r} is not declared")
    return declared


def _row(declared: _Declared, row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for name, kind in declared.columns.items():
        if kind == "boolean" and out.get(name) is not None:
            out[name] = bool(out[name])
    return out


def _checked(declared: _Declared, set_name: str, values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in values.items():
        kind = declared.columns.get(name)
        if kind is None:
            raise RecordsError(f"set {set_name!r} has no column {name!r}")
        checked = check_value(Column(name, kind), value)
        out[name] = (1 if checked else 0) if kind == "boolean" and checked is not None else checked
    return out


def _check_declaration(set_name: str, columns: Sequence[Column], key: str | None) -> dict[str, str]:
    _check_name("set", set_name)
    if not columns:
        raise RecordsError(f"set {set_name!r} needs at least one column")
    wanted: dict[str, str] = {}
    for column in columns:
        _check_name("column", column.name)
        if column.type not in COLUMN_TYPES:
            raise RecordsError(
                f"column {column.name!r} has the type {column.type!r}; "
                f"use one of {', '.join(COLUMN_TYPES)}"
            )
        if column.name in wanted:
            raise RecordsError(f"column {column.name!r} is declared twice")
        wanted[column.name] = column.type
    if key is not None and key not in wanted:
        raise RecordsError(f"the key {key!r} is not a declared column of set {set_name!r}")
    return wanted


def _refuse_unsafe_change(
    set_name: str, current: _Declared, wanted: dict[str, str], key: str | None
) -> None:
    for name, kind in current.columns.items():
        if name not in wanted:
            raise RecordsError(
                f"set {set_name!r}: column {name!r} is declared and was left out "
                "(a removal or a rename); nothing was changed"
            )
        if wanted[name] != kind:
            raise RecordsError(
                f"set {set_name!r}: column {name!r} is declared {kind}, not {wanted[name]}; "
                "nothing was changed"
            )
    if key != current.key:
        raise RecordsError(
            f"set {set_name!r}: the key is {current.key!r}, not {key!r}; "
            "the key cannot change; nothing was changed"
        )


class RecordsStore:
    """One pod's records file; every call opens and closes its own connection."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        db = sqlite3.connect(self.path, timeout=_BUSY_S, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        except sqlite3.Error as exc:
            raise RecordsError(f"the records file failed: {exc}") from exc
        finally:
            db.close()

    def ensure_table(
        self, set_name: str, columns: Sequence[Column], key: str | None = None
    ) -> EnsureResult:
        """Create the set or add its new columns; refuse a removal, rename, retype or new key."""
        wanted = _check_declaration(set_name, columns, key)
        with self._transaction() as db:
            db.execute(_DECLARED_DDL)
            current = _declared(db, set_name)
            if current is None:
                self._create(db, set_name, wanted, key)
                return EnsureResult(created=True, added=())
            _refuse_unsafe_change(set_name, current, wanted, key)
            added = tuple(name for name in wanted if name not in current.columns)
            for name in added:
                db.execute(
                    f"ALTER TABLE {_quote(set_name)} ADD COLUMN {_quote(name)} "
                    f"{_SQL_TYPE[wanted[name]]}"
                )
                self._declare(db, set_name, name, wanted[name], False)
            return EnsureResult(created=False, added=added)

    @staticmethod
    def _declare(db: sqlite3.Connection, set_name: str, name: str, kind: str, is_key: bool) -> None:
        db.execute(
            'INSERT INTO "_declared" (set_name, column_name, type, is_key) VALUES (?, ?, ?, ?)',
            (set_name, name, kind, int(is_key)),
        )

    def _create(
        self, db: sqlite3.Connection, set_name: str, wanted: dict[str, str], key: str | None
    ) -> None:
        parts = [
            "_id INTEGER PRIMARY KEY AUTOINCREMENT",
            "_at TEXT NOT NULL",
            "_task TEXT",
            "_session TEXT",
            "_step TEXT",
            "_updated_at TEXT",
        ]
        for name, kind in wanted.items():
            not_null = " NOT NULL" if name == key else ""
            parts.append(f"{_quote(name)} {_SQL_TYPE[kind]}{not_null}")
        db.execute(f"CREATE TABLE {_quote(set_name)} ({', '.join(parts)})")
        if key is not None:
            index = _quote("ux_" + set_name)
            db.execute(f"CREATE UNIQUE INDEX {index} ON {_quote(set_name)} ({_quote(key)})")
        for name, kind in wanted.items():
            self._declare(db, set_name, name, kind, name == key)

    def add(self, set_name: str, values: dict[str, Any], meta: RecordMeta) -> AddResult:
        """Insert a row, or return the row that holds the same key with `created` false."""
        with self._transaction() as db:
            declared = _require(db, set_name)
            clean = _checked(declared, set_name, values)
            table = _quote(set_name)
            if declared.key is not None:
                key_value = clean.get(declared.key)
                if key_value is None:
                    raise RecordsError(
                        f"set {set_name!r}: the key column {declared.key!r} is required"
                    )
                found = db.execute(
                    f"SELECT * FROM {table} WHERE {_quote(declared.key)} = ?", (key_value,)
                ).fetchone()
                if found is not None:
                    return AddResult(_row(declared, found), created=False)
            names = ["_at", "_task", "_session", "_step", *clean]
            args = [_clock.stamp(), meta.task, meta.session, meta.step, *clean.values()]
            marks = ", ".join("?" for _ in names)
            columns = ", ".join(_quote(n) for n in names)
            cursor = db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", args)
            made = db.execute(f"SELECT * FROM {table} WHERE _id = ?", (cursor.lastrowid,))
            return AddResult(_row(declared, made.fetchone()), created=True)

    def update(
        self, set_name: str, match: dict[str, Any], values: dict[str, Any], meta: RecordMeta
    ) -> dict[str, Any]:
        """Change declared columns of the one row `match` names by `_id` or by the key."""
        with self._transaction() as db:
            declared = _require(db, set_name)
            column, wanted = self._match(declared, set_name, match)
            if not values:
                raise RecordsError(f"set {set_name!r}: an update needs at least one value")
            if declared.key in values:
                raise RecordsError(
                    f"set {set_name!r}: the key column {declared.key!r} cannot change"
                )
            clean = _checked(declared, set_name, values)
            table = _quote(set_name)
            found = db.execute(
                f"SELECT _id FROM {table} WHERE {_quote(column)} = ?", (wanted,)
            ).fetchone()
            if found is None:
                raise RecordsError(f"set {set_name!r} has no row with {column} = {wanted!r}")
            names = [*clean, "_updated_at", "_task", "_session", "_step"]
            args = [*clean.values(), _clock.stamp(), meta.task, meta.session, meta.step]
            assigns = ", ".join(f"{_quote(n)} = ?" for n in names)
            db.execute(f"UPDATE {table} SET {assigns} WHERE _id = ?", [*args, found["_id"]])
            row = db.execute(f"SELECT * FROM {table} WHERE _id = ?", (found["_id"],)).fetchone()
            return _row(declared, row)

    @staticmethod
    def _match(declared: _Declared, set_name: str, match: dict[str, Any]) -> tuple[str, Any]:
        allowed = ["_id", *([declared.key] if declared.key else [])]
        if len(match) != 1 or next(iter(match)) not in allowed:
            raise RecordsError(
                f"set {set_name!r}: match one row by {' or '.join(map(repr, allowed))}, "
                f"not by {sorted(match)}"
            )
        column, value = next(iter(match.items()))
        if column == "_id":
            if not isinstance(value, int) or isinstance(value, bool):
                raise RecordsError(f"set {set_name!r}: _id must be an integer, not {_shown(value)}")
        else:
            check_value(Column(column, declared.columns[column]), value)
        return column, value

    @contextlib.contextmanager
    def _reader(self, timeout_s: float) -> Iterator[sqlite3.Connection]:
        """A `mode=ro` connection that allows only reads and stops at *timeout_s*."""
        if not self.path.exists():
            raise RecordsError("there are no records yet: the pod has written none")
        deadline = _clock.monotonic() + timeout_s
        db = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=_BUSY_S,
            isolation_level=None,
        )
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _VALUE_LENGTH_LIMIT)
        db.set_authorizer(_authorize)

        def stopped() -> bool:
            return _clock.monotonic() > deadline

        db.set_progress_handler(stopped, _PROGRESS_STEPS)
        try:
            yield db
        except sqlite3.Error as exc:
            if stopped():
                raise RecordsError(f"the query was stopped after {timeout_s:g} s") from exc
            raise RecordsError(f"the query was refused: {exc}") from exc
        finally:
            db.close()

    def query(self, sql: str, max_rows: int, max_chars: int, timeout_s: float = 5.0) -> QueryResult:
        """Run a read-only statement; return at most *max_rows* rows and the count left out."""
        with self._reader(timeout_s) as db:
            cursor = db.execute(sql)
            columns = tuple(d[0] for d in cursor.description or ())
            rows: list[tuple[Any, ...]] = []
            used = 0
            cut = 0
            full = False
            for row in cursor:
                size = len(json.dumps(list(row), default=str))
                if not full and len(rows) < max_rows and used + size <= max_chars:
                    rows.append(tuple(row))
                    used += size
                else:
                    full = True
                    cut += 1
            return QueryResult(columns, rows, cut)

    def export(self, sql: str, path: Path, fmt: str, timeout_s: float = 30.0) -> int:
        """Write every row of a read-only statement to *path*; return how many."""
        if fmt not in EXPORT_FORMATS:
            raise RecordsError(f"cannot export as {fmt!r}; use {' or '.join(EXPORT_FORMATS)}")
        partial = path.with_name(path.name + ".part")
        count = 0
        try:
            with (
                self._reader(timeout_s) as db,
                partial.open("w", encoding="utf-8", newline="") as out,
            ):
                cursor = db.execute(sql)
                columns = [d[0] for d in cursor.description or ()]

                def counted() -> Iterator[Any]:
                    nonlocal count
                    for row in cursor:
                        count += 1
                        yield row

                if fmt == "csv":
                    writer = csv.writer(out)
                    writer.writerow(columns)
                    writer.writerows(counted())
                else:
                    out.writelines(_markdown_lines(columns, counted()))
            os.replace(partial, path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return count


def _authorize(action: int, *_: object) -> int:
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY
