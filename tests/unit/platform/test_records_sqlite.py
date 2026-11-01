"""What only the SQLite adapter has (`platform/records_sqlite.py`): the file, its mode and WAL, the
stored form of a boolean, and that reading never creates the file. The behaviour every backend
shares is `tests/integration/platform/test_record_store_conformance.py`."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from docket.kernel.records import RecordColumn, RecordsError, RecordSet
from docket.kernel.records_port import ReadLimits, RecordOrigin
from docket.platform.records_sqlite import SqliteRecordStore

SUBJECT = "docket.platform.records_sqlite"

FLAGS = RecordSet(
    name="flags",
    columns=[RecordColumn(name="on", type="boolean"), RecordColumn(name="n", type="integer")],
)


def test_the_file_is_created_private_in_a_private_directory(tmp_path: Path) -> None:
    path = tmp_path / "pod" / "records.sqlite"
    SqliteRecordStore(path).declare(FLAGS)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_the_file_is_wal(tmp_path: Path) -> None:
    path = tmp_path / "records.sqlite"
    SqliteRecordStore(path).declare(FLAGS)
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_a_boolean_is_stored_as_zero_or_one(tmp_path: Path) -> None:
    path = tmp_path / "records.sqlite"
    store = SqliteRecordStore(path)
    store.declare(FLAGS)
    store.add("flags", {"on": True}, RecordOrigin())
    store.add("flags", {"on": False}, RecordOrigin())
    with sqlite3.connect(path) as raw:
        assert raw.execute('SELECT "on" FROM flags ORDER BY _id').fetchall() == [(1,), (0,)]


def test_planning_and_asking_create_neither_the_file_nor_its_directory(tmp_path: Path) -> None:
    store = SqliteRecordStore(tmp_path / "pod" / "records.sqlite")
    store.plan(FLAGS)
    assert store.has("flags") is False
    with pytest.raises(RecordsError):
        store.read("SELECT 1", ReadLimits())
    with pytest.raises(RecordsError):
        store.export("SELECT 1", tmp_path / "out.csv", "csv", ReadLimits())
    assert not (tmp_path / "pod").exists()


def test_a_refused_declaration_does_not_create_the_file(tmp_path: Path) -> None:
    path = tmp_path / "pod" / "records.sqlite"
    column = RecordColumn.model_construct(name="Bad", type="string")
    with pytest.raises(RecordsError):
        SqliteRecordStore(path).declare(
            RecordSet.model_construct(name="s", columns=[column], key=None)
        )
    assert not path.parent.exists()


def _file_without_role(path: Path) -> None:
    """A records file as it was written before `_role` existed: one set, one row, no such column."""
    store = SqliteRecordStore(path)
    store.declare(FLAGS)
    store.add("flags", {"on": True, "n": 1}, RecordOrigin(task="t-0"))
    with sqlite3.connect(path) as raw:
        raw.execute('ALTER TABLE "flags" DROP COLUMN _role')


def _columns(path: Path) -> list[str]:
    with sqlite3.connect(path) as raw:
        return [row[1] for row in raw.execute('PRAGMA table_info("flags")')]


def test_a_file_written_before_role_gains_the_column_when_the_set_is_declared(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records.sqlite"
    _file_without_role(path)
    assert "_role" not in _columns(path)

    SqliteRecordStore(path).declare(FLAGS)

    assert "_role" in _columns(path)
    store = SqliteRecordStore(path)
    store.add("flags", {"on": False, "n": 2}, RecordOrigin(task="t-1", role="lead"))
    rows = store.read('SELECT n, "_role" FROM flags ORDER BY _id', ReadLimits(10, 1000)).rows
    assert [tuple(r) for r in rows] == [(1, None), (2, "lead")]


def test_a_write_to_a_file_written_before_role_still_records_the_role(tmp_path: Path) -> None:
    path = tmp_path / "records.sqlite"
    _file_without_role(path)

    SqliteRecordStore(path).add("flags", {"on": True, "n": 3}, RecordOrigin(role="reviewer"))

    assert "_role" in _columns(path)
