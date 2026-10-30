"""A pod's records in one SQLite file: the `RecordStore` adapter (`pod-records.spec.md`).

`SqliteRecordStore` is the only module in `src/docket` that imports `sqlite3`
(`tests/architecture/test_records_writer.py`), and `bootstrap` the only one that imports it
(`tests/architecture/test_records_adapter.py`). It keeps what is SQLite and nothing else: each call
opens and closes its own connection, a write inside one `BEGIN IMMEDIATE` transaction, a read on a
separate `mode=ro` connection whose authorizer allows only reads and whose progress handler stops it
at a time bound. The rules every backend shares are in `kernel.records_rules`. A SQLite records file
is not docket-owned JSON, so `platform/store.py` stays the only writer of that.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from docket.kernel import clock as _clock
from docket.kernel.records import RecordColumn, RecordsError, RecordSet
from docket.kernel.records_port import (
    AddOutcome,
    ReadLimits,
    RecordOrigin,
    Row,
    Rows,
    SetChange,
)
from docket.kernel.records_rules import (
    bound_rows,
    check_add,
    check_declaration,
    check_format,
    check_update,
    plan_change,
    write_export,
)

_SQL_TYPE = {
    "string": "TEXT",
    "integer": "INTEGER",
    "number": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
}
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


def _quote(name: str) -> str:
    return '"' + name + '"'


def _declared(db: sqlite3.Connection, set_name: str) -> RecordSet | None:
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
    columns = [RecordColumn(name=r[0], type=r[1]) for r in rows]
    return RecordSet(name=set_name, columns=columns, key=key)


def _require(db: sqlite3.Connection, set_name: str) -> RecordSet:
    declared = _declared(db, set_name)
    if declared is None:
        raise RecordsError(f"set {set_name!r} is not declared")
    return declared


def _row(declared: RecordSet, row: sqlite3.Row) -> Row:
    out = dict(row)
    for column in declared.columns:
        if column.type == "boolean" and out.get(column.name) is not None:
            out[column.name] = bool(out[column.name])
    return out


def _declare(db: sqlite3.Connection, set_name: str, column: RecordColumn, is_key: bool) -> None:
    db.execute(
        'INSERT INTO "_declared" (set_name, column_name, type, is_key) VALUES (?, ?, ?, ?)',
        (set_name, column.name, column.type, int(is_key)),
    )


def _create(db: sqlite3.Connection, record_set: RecordSet) -> None:
    table = _quote(record_set.name)
    parts = [
        "_id INTEGER PRIMARY KEY AUTOINCREMENT",
        "_at TEXT NOT NULL",
        "_task TEXT",
        "_session TEXT",
        "_step TEXT",
        "_updated_at TEXT",
    ]
    for column in record_set.columns:
        not_null = " NOT NULL" if column.name == record_set.key else ""
        parts.append(f"{_quote(column.name)} {_SQL_TYPE[column.type]}{not_null}")
    db.execute(f"CREATE TABLE {table} ({', '.join(parts)})")
    if record_set.key is not None:
        index = _quote("ux_" + record_set.name)
        db.execute(f"CREATE UNIQUE INDEX {index} ON {table} ({_quote(record_set.key)})")
    for column in record_set.columns:
        _declare(db, record_set.name, column, column.name == record_set.key)


def _authorize(action: int, *_: object) -> int:
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY


class SqliteRecordStore:
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

    def declare(self, record_set: RecordSet) -> SetChange:
        check_declaration(record_set)
        with self._transaction() as db:
            db.execute(_DECLARED_DDL)
            current = _declared(db, record_set.name)
            change = plan_change(current, record_set)
            if current is None:
                _create(db, record_set)
                return change
            for column in record_set.columns:
                if column.name in change.added:
                    db.execute(
                        f"ALTER TABLE {_quote(record_set.name)} ADD COLUMN "
                        f"{_quote(column.name)} {_SQL_TYPE[column.type]}"
                    )
                    _declare(db, record_set.name, column, False)
            return change

    def plan(self, record_set: RecordSet) -> SetChange:
        if not self.path.exists():
            return plan_change(None, record_set)
        with self._reader(_BUSY_S) as db:
            current = _declared(db, record_set.name)
        return plan_change(current, record_set)

    def has(self, set_name: str) -> bool:
        if not self.path.exists():
            return False
        with self._reader(_BUSY_S) as db:
            return _declared(db, set_name) is not None

    def add(self, set_name: str, values: Row, origin: RecordOrigin) -> AddOutcome:
        with self._transaction() as db:
            declared = _require(db, set_name)
            clean = check_add(declared, values)
            table = _quote(set_name)
            if declared.key is not None:
                found = db.execute(
                    f"SELECT * FROM {table} WHERE {_quote(declared.key)} = ?",
                    (clean[declared.key],),
                ).fetchone()
                if found is not None:
                    return AddOutcome(_row(declared, found), created=False)
            names = ["_at", "_task", "_session", "_step", *clean]
            args = [_clock.stamp(), origin.task, origin.session, origin.step, *clean.values()]
            marks = ", ".join("?" for _ in names)
            columns = ", ".join(_quote(n) for n in names)
            cursor = db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", args)
            made = db.execute(f"SELECT * FROM {table} WHERE _id = ?", (cursor.lastrowid,))
            return AddOutcome(_row(declared, made.fetchone()), created=True)

    def update(self, set_name: str, match: Row, values: Row, origin: RecordOrigin) -> Row:
        with self._transaction() as db:
            declared = _require(db, set_name)
            column, wanted, clean = check_update(declared, match, values)
            table = _quote(set_name)
            found = db.execute(
                f"SELECT _id FROM {table} WHERE {_quote(column)} = ?", (wanted,)
            ).fetchone()
            if found is None:
                raise RecordsError(f"set {set_name!r} has no row with {column} = {wanted!r}")
            names = [*clean, "_updated_at", "_task", "_session", "_step"]
            args = [*clean.values(), _clock.stamp(), origin.task, origin.session, origin.step]
            assigns = ", ".join(f"{_quote(n)} = ?" for n in names)
            db.execute(f"UPDATE {table} SET {assigns} WHERE _id = ?", [*args, found["_id"]])
            row = db.execute(f"SELECT * FROM {table} WHERE _id = ?", (found["_id"],)).fetchone()
            return _row(declared, row)

    def read(self, statement: str, limits: ReadLimits) -> Rows:
        with self._reader(limits.timeout_s) as db:
            cursor = db.execute(statement)
            return bound_rows([d[0] for d in cursor.description or ()], cursor, limits)

    def export(self, statement: str, target: Path, fmt: str, limits: ReadLimits) -> int:
        check_format(fmt)
        with self._reader(limits.timeout_s) as db:
            cursor = db.execute(statement)
            return write_export(target, fmt, [d[0] for d in cursor.description or ()], cursor)
