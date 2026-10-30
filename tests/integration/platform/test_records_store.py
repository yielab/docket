"""A pod's records file on a temporary path (`platform/records_store.py`).

Pins typed adds, key idempotence, additive-only schema change, and a read-only bounded query."""

from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path

import pytest

from docket.platform.records_store import (
    Column,
    RecordMeta,
    RecordsError,
    RecordsStore,
)

SUBJECT = "docket.platform.records_store"

META = RecordMeta(task="t-1", session="s-1", step="scan")
LISTINGS = [Column("url", "string"), Column("price", "integer"), Column("seen", "date")]


@pytest.fixture
def store(tmp_path: Path) -> RecordsStore:
    made = RecordsStore(tmp_path / "pod" / "records.sqlite")
    made.ensure_table("listings", LISTINGS, key="url")
    return made


def _count(store: RecordsStore, table: str = "listings") -> int:
    return store.query(f"SELECT count(*) FROM {table}", 10, 1000).rows[0][0]


class TestEnsureTable:
    def test_creates_a_table_and_reports_it(self, tmp_path: Path) -> None:
        made = RecordsStore(tmp_path / "r.sqlite")
        out = made.ensure_table("notes", [Column("body", "string")])
        assert out.created is True
        assert out.added == ()
        assert (tmp_path / "r.sqlite").stat().st_mode & 0o777 == 0o600

    def test_a_repeated_declaration_changes_nothing(self, store: RecordsStore) -> None:
        out = store.ensure_table("listings", LISTINGS, key="url")
        assert (out.created, out.added) == (False, ())

    def test_an_added_column_keeps_the_rows(self, store: RecordsStore) -> None:
        store.add("listings", {"url": "a", "price": 5}, META)
        out = store.ensure_table("listings", [*LISTINGS, Column("agent", "string")], key="url")
        assert out.added == ("agent",)
        row = store.query("SELECT url, price, agent FROM listings", 10, 1000).rows
        assert row == [("a", 5, None)]

    def test_a_dropped_column_is_refused_and_the_table_unchanged(self, store: RecordsStore) -> None:
        store.add("listings", {"url": "a", "price": 5}, META)
        with pytest.raises(RecordsError, match="price"):
            store.ensure_table("listings", [Column("url", "string"), Column("seen", "date")], "url")
        assert store.query("SELECT url, price FROM listings", 10, 1000).rows == [("a", 5)]

    def test_a_retyped_column_is_refused_naming_it(self, store: RecordsStore) -> None:
        with pytest.raises(RecordsError, match="price"):
            store.ensure_table(
                "listings", [Column("url", "string"), Column("price", "number")], "url"
            )

    def test_a_renamed_column_is_refused_and_adds_nothing(self, store: RecordsStore) -> None:
        renamed = [Column("url", "string"), Column("cost", "integer"), Column("seen", "date")]
        with pytest.raises(RecordsError, match="price"):
            store.ensure_table("listings", renamed, key="url")
        columns = store.query("SELECT * FROM listings", 10, 1000).columns
        assert "cost" not in columns

    def test_a_changed_key_is_refused(self, store: RecordsStore) -> None:
        with pytest.raises(RecordsError, match="key"):
            store.ensure_table("listings", LISTINGS, key="price")

    @pytest.mark.parametrize("bad", ["Listings", "1x", "a-b", "", "_hidden"])
    def test_a_bad_column_name_is_refused(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(RecordsError, match="name"):
            RecordsStore(tmp_path / "r.sqlite").ensure_table("s", [Column(bad, "string")])

    def test_an_unknown_type_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(RecordsError, match="blob"):
            RecordsStore(tmp_path / "r.sqlite").ensure_table("s", [Column("a", "blob")])


class TestAdd:
    def test_a_string_in_an_integer_column_is_refused_naming_the_column(
        self, store: RecordsStore
    ) -> None:
        with pytest.raises(RecordsError, match="price"):
            store.add("listings", {"url": "a", "price": "abc"}, META)
        assert _count(store) == 0

    def test_a_bad_date_and_an_undeclared_column_are_refused(self, store: RecordsStore) -> None:
        with pytest.raises(RecordsError, match="seen"):
            store.add("listings", {"url": "a", "seen": "31/12/2026"}, META)
        with pytest.raises(RecordsError, match="colour"):
            store.add("listings", {"url": "a", "colour": "red"}, META)

    def test_an_undeclared_set_is_refused(self, store: RecordsStore) -> None:
        with pytest.raises(RecordsError, match="ghosts"):
            store.add("ghosts", {"a": 1}, META)

    def test_two_adds_with_one_key_leave_one_row(self, store: RecordsStore) -> None:
        first = store.add("listings", {"url": "a", "price": 5}, META)
        second = store.add("listings", {"url": "a", "price": 99}, META)
        assert (first.created, second.created) == (True, False)
        assert second.row["price"] == 5
        assert second.row["_id"] == first.row["_id"]
        assert _count(store) == 1

    def test_the_key_is_required(self, store: RecordsStore) -> None:
        with pytest.raises(RecordsError, match="url"):
            store.add("listings", {"price": 5}, META)

    def test_the_hop_fills_the_implicit_columns(self, store: RecordsStore) -> None:
        row = store.add("listings", {"url": "a"}, META).row
        assert (row["_task"], row["_session"], row["_step"]) == ("t-1", "s-1", "scan")
        assert row["_at"].endswith("Z")
        assert row["_updated_at"] is None

    def test_a_boolean_round_trips_as_a_bool_and_is_not_an_integer(self, tmp_path: Path) -> None:
        made = RecordsStore(tmp_path / "r.sqlite")
        made.ensure_table("flags", [Column("on", "boolean"), Column("n", "integer")])
        assert made.add("flags", {"on": True}, META).row["on"] is True
        with pytest.raises(RecordsError, match="n"):
            made.add("flags", {"n": True}, META)

    def test_a_set_without_a_key_adds_every_time(self, tmp_path: Path) -> None:
        made = RecordsStore(tmp_path / "r.sqlite")
        made.ensure_table("notes", [Column("body", "string")])
        made.add("notes", {"body": "x"}, META)
        assert made.add("notes", {"body": "x"}, META).created is True
        assert _count(made, "notes") == 2


class TestUpdate:
    def test_updates_by_key_and_by_id(self, store: RecordsStore) -> None:
        row = store.add("listings", {"url": "a", "price": 5}, META).row
        later = RecordMeta(task="t-2", session="s-2", step="fix")
        by_key = store.update("listings", {"url": "a"}, {"price": 6}, later)
        by_id = store.update("listings", {"_id": row["_id"]}, {"price": 7}, later)
        assert (by_key["price"], by_id["price"]) == (6, 7)
        assert by_id["_updated_at"] is not None
        assert (by_id["_task"], by_id["_at"]) == ("t-2", row["_at"])

    def test_refusals_name_what_they_refused(self, store: RecordsStore) -> None:
        store.add("listings", {"url": "a", "price": 5}, META)
        with pytest.raises(RecordsError, match="nowhere"):
            store.update("listings", {"url": "nowhere"}, {"price": 1}, META)
        with pytest.raises(RecordsError, match="price"):
            store.update("listings", {"price": 5}, {"price": 1}, META)
        with pytest.raises(RecordsError, match="_task"):
            store.update("listings", {"url": "a"}, {"_task": "x"}, META)
        with pytest.raises(RecordsError, match="url"):
            store.update("listings", {"url": "a"}, {"url": "b"}, META)
        with pytest.raises(RecordsError, match="price"):
            store.update("listings", {"url": "a"}, {"price": "high"}, META)
        assert store.query("SELECT price FROM listings", 10, 1000).rows == [(5,)]


class TestQuery:
    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM listings",
            "UPDATE listings SET price = 0",
            "INSERT INTO listings (url) VALUES ('z')",
            "ATTACH DATABASE ':memory:' AS other",
            "PRAGMA journal_mode = DELETE",
            "DROP TABLE listings",
            "SELECT 1; DELETE FROM listings",
        ],
    )
    def test_anything_but_a_read_is_refused_and_the_data_unchanged(
        self, store: RecordsStore, sql: str
    ) -> None:
        store.add("listings", {"url": "a", "price": 5}, META)
        with pytest.raises(RecordsError):
            store.query(sql, 10, 1000)
        assert store.query("SELECT url, price FROM listings", 10, 1000).rows == [("a", 5)]

    def test_a_with_query_and_a_join_work(self, store: RecordsStore) -> None:
        store.ensure_table("sold", [Column("url", "string")])
        store.add("listings", {"url": "a", "price": 5}, META)
        store.add("listings", {"url": "b", "price": 9}, META)
        store.add("sold", {"url": "b"}, META)
        cte = store.query("WITH x AS (SELECT * FROM listings) SELECT count(*) FROM x", 10, 1000)
        assert cte.rows == [(2,)]
        joined = store.query(
            "SELECT l.url, l.price FROM listings l JOIN sold s ON s.url = l.url", 10, 1000
        )
        assert joined.columns == ("url", "price")
        assert joined.rows == [("b", 9)]

    def test_rows_over_the_bound_are_counted_as_cut(self, store: RecordsStore) -> None:
        for n in range(300):
            store.add("listings", {"url": f"u{n}", "price": n}, META)
        out = store.query("SELECT url FROM listings ORDER BY _id", 200, 10_000_000)
        assert (len(out.rows), out.cut) == (200, 100)
        assert out.rows[0] == ("u0",)

    def test_rows_over_the_character_bound_are_counted_as_cut(self, store: RecordsStore) -> None:
        for n in range(50):
            store.add("listings", {"url": f"https://example.test/{n}", "price": n}, META)
        out = store.query("SELECT url FROM listings ORDER BY _id", 1000, 200)
        assert 0 < len(out.rows) < 50
        assert len(out.rows) + out.cut == 50

    def test_a_query_that_never_ends_is_stopped_by_the_time_bound(
        self, store: RecordsStore
    ) -> None:
        endless = (
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT max(x) FROM c"
        )
        began = time.monotonic()
        with pytest.raises(RecordsError, match="stopped"):
            store.query(endless, 10, 1000, timeout_s=0.3)
        assert time.monotonic() - began < 5

    def test_a_missing_file_is_refused_not_created(self, tmp_path: Path) -> None:
        with pytest.raises(RecordsError):
            RecordsStore(tmp_path / "none.sqlite").query("SELECT 1", 10, 100)
        assert not (tmp_path / "none.sqlite").exists()


class TestExport:
    def test_csv_header_is_the_columns_and_the_count_is_every_row(
        self, store: RecordsStore, tmp_path: Path
    ) -> None:
        for n in range(300):
            store.add("listings", {"url": f"u{n}", "price": n}, META)
        out = tmp_path / "out.csv"
        written = store.export("SELECT url, price FROM listings ORDER BY _id", out, "csv")
        rows = list(csv.reader(out.open(encoding="utf-8")))
        assert written == 300
        assert rows[0] == ["url", "price"]
        assert len(rows) == 301
        assert rows[2] == ["u1", "1"]

    def test_markdown_is_a_table_with_pipes_escaped(
        self, store: RecordsStore, tmp_path: Path
    ) -> None:
        store.add("listings", {"url": "a|b", "price": 1}, META)
        out = tmp_path / "out.md"
        assert store.export("SELECT url, price FROM listings", out, "markdown") == 1
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "| url | price |"
        assert lines[2] == "| a\\|b | 1 |"

    def test_an_unknown_format_and_a_write_are_refused(
        self, store: RecordsStore, tmp_path: Path
    ) -> None:
        with pytest.raises(RecordsError, match="xml"):
            store.export("SELECT 1", tmp_path / "o.xml", "xml")
        with pytest.raises(RecordsError):
            store.export("DELETE FROM listings", tmp_path / "o.csv", "csv")


def test_the_file_is_wal_and_a_second_handle_sees_the_rows(
    store: RecordsStore, tmp_path: Path
) -> None:
    store.add("listings", {"url": "a"}, META)
    other = RecordsStore(tmp_path / "pod" / "records.sqlite")
    assert _count(other) == 1
    with sqlite3.connect(tmp_path / "pod" / "records.sqlite") as raw:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
