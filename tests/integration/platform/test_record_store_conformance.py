"""What every `RecordStore` backend does (`kernel/records_port.py`, pod-records.spec.md 3-14).

Pins typed adds, key idempotence, additive-only schema change, a read-only bounded read and the
exports. A new backend adds one entry to `BACKENDS` and inherits every case."""

from __future__ import annotations

import csv
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from docket.kernel.records import RecordColumn, RecordsError, RecordSet
from docket.kernel.records_port import ReadLimits, RecordOrigin, RecordStore
from docket.platform.records_sqlite import SqliteRecordStore

SUBJECT = "docket.kernel.records_port"

# A backend: how to open the store of a named pod under a scratch directory. Two opens of one
# name reach the same records.
BACKENDS: dict[str, Callable[[Path, str], RecordStore]] = {
    "sqlite": lambda scratch, pod: SqliteRecordStore(scratch / pod / "records.sqlite"),
}

ORIGIN = RecordOrigin(task="t-1", session="s-1", step="scan")
ALL = ReadLimits(max_rows=10, max_chars=1000)


def _set(*columns: tuple[str, str], key: str | None = None, name: str = "listings") -> RecordSet:
    made = [RecordColumn(name=n, type=t) for n, t in columns]  # type: ignore[arg-type]
    return RecordSet(name=name, columns=made, key=key)


LISTINGS = _set(("url", "string"), ("price", "integer"), ("seen", "date"), key="url")
NOTES = _set(("body", "string"), name="notes")


@pytest.fixture(params=sorted(BACKENDS))
def open_store(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[str], RecordStore]:
    backend = BACKENDS[request.param]
    return lambda pod="pod": backend(tmp_path, pod)


@pytest.fixture
def blank(open_store: Callable[..., RecordStore]) -> RecordStore:
    return open_store("pod")


@pytest.fixture
def store(blank: RecordStore) -> RecordStore:
    blank.declare(LISTINGS)
    return blank


def _count(store: RecordStore, table: str = "listings") -> int:
    return store.read(f"SELECT count(*) FROM {table}", ALL).rows[0][0]


class TestDeclare:
    def test_creates_a_set_and_reports_it(self, blank: RecordStore) -> None:
        out = blank.declare(NOTES)
        assert (out.created, out.added) == (True, ())
        assert blank.has("notes")

    def test_a_repeated_declaration_changes_nothing(self, store: RecordStore) -> None:
        out = store.declare(LISTINGS)
        assert (out.created, out.added) == (False, ())

    def test_an_added_column_keeps_the_rows(self, store: RecordStore) -> None:
        store.add("listings", {"url": "a", "price": 5}, ORIGIN)
        wider = _set(*[(c.name, c.type) for c in LISTINGS.columns], ("agent", "string"), key="url")
        out = store.declare(wider)
        assert out.added == ("agent",)
        row = store.read("SELECT url, price, agent FROM listings", ALL).rows
        assert row == [("a", 5, None)]

    def test_a_dropped_column_is_refused_and_the_set_unchanged(self, store: RecordStore) -> None:
        store.add("listings", {"url": "a", "price": 5}, ORIGIN)
        with pytest.raises(RecordsError, match="price"):
            store.declare(_set(("url", "string"), ("seen", "date"), key="url"))
        assert store.read("SELECT url, price FROM listings", ALL).rows == [("a", 5)]

    def test_a_retyped_column_is_refused_naming_it(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="price"):
            store.declare(_set(("url", "string"), ("price", "number"), key="url"))

    def test_a_renamed_column_is_refused_and_adds_nothing(self, store: RecordStore) -> None:
        renamed = _set(("url", "string"), ("cost", "integer"), ("seen", "date"), key="url")
        with pytest.raises(RecordsError, match="price"):
            store.declare(renamed)
        assert "cost" not in store.read("SELECT * FROM listings", ALL).columns

    def test_a_changed_key_is_refused(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="key"):
            store.declare(_set(*[(c.name, c.type) for c in LISTINGS.columns], key="price"))

    @pytest.mark.parametrize("bad", ["Listings", "1x", "a-b", "", "_hidden"])
    def test_a_bad_column_name_is_refused_and_nothing_is_declared(
        self, blank: RecordStore, bad: str
    ) -> None:
        column = RecordColumn.model_construct(name=bad, type="string")
        unchecked = RecordSet.model_construct(name="s", columns=[column], key=None)
        with pytest.raises(RecordsError, match="name"):
            blank.declare(unchecked)
        assert not blank.has("s")

    def test_an_unknown_type_is_refused(self, blank: RecordStore) -> None:
        column = RecordColumn.model_construct(name="a", type="blob")
        with pytest.raises(RecordsError, match="blob"):
            blank.declare(RecordSet.model_construct(name="s", columns=[column], key=None))


class TestPlan:
    def test_a_new_set_is_reported_and_not_declared(self, blank: RecordStore) -> None:
        out = blank.plan(NOTES)
        assert (out.created, out.added) == (True, ())
        assert not blank.has("notes")
        with pytest.raises(RecordsError):
            blank.read("SELECT 1", ALL)

    def test_an_added_column_is_reported_and_not_added(self, store: RecordStore) -> None:
        wider = _set(*[(c.name, c.type) for c in LISTINGS.columns], ("agent", "string"), key="url")
        out = store.plan(wider)
        assert (out.created, out.added) == (False, ("agent",))
        assert store.read("SELECT * FROM listings", ALL).columns[-1] == "seen"

    def test_a_set_the_records_lack_is_created_not_refused(self, store: RecordStore) -> None:
        assert store.plan(NOTES).created is True

    def test_the_refusals_are_declares(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="price"):
            store.plan(_set(("url", "string"), ("seen", "date"), key="url"))
        with pytest.raises(RecordsError, match="key"):
            store.plan(_set(*[(c.name, c.type) for c in LISTINGS.columns]))


class TestHas:
    def test_is_false_before_anything_is_written_and_true_once_declared(
        self, blank: RecordStore
    ) -> None:
        assert blank.has("listings") is False
        blank.declare(LISTINGS)
        assert (blank.has("listings"), blank.has("notes")) == (True, False)


class TestAdd:
    def test_a_string_in_an_integer_column_is_refused_naming_the_column(
        self, store: RecordStore
    ) -> None:
        with pytest.raises(RecordsError, match="price"):
            store.add("listings", {"url": "a", "price": "abc"}, ORIGIN)
        assert _count(store) == 0

    def test_a_bad_date_and_an_undeclared_column_are_refused(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="seen"):
            store.add("listings", {"url": "a", "seen": "31/12/2026"}, ORIGIN)
        with pytest.raises(RecordsError, match="colour"):
            store.add("listings", {"url": "a", "colour": "red"}, ORIGIN)

    def test_an_undeclared_set_is_refused(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="ghosts"):
            store.add("ghosts", {"a": 1}, ORIGIN)

    def test_two_adds_with_one_key_leave_one_row(self, store: RecordStore) -> None:
        first = store.add("listings", {"url": "a", "price": 5}, ORIGIN)
        second = store.add("listings", {"url": "a", "price": 99}, ORIGIN)
        assert (first.created, second.created) == (True, False)
        assert second.row["price"] == 5
        assert second.row["_id"] == first.row["_id"]
        assert _count(store) == 1

    def test_the_key_is_required(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="url"):
            store.add("listings", {"price": 5}, ORIGIN)

    def test_the_hop_fills_the_implicit_columns(self, store: RecordStore) -> None:
        row = store.add("listings", {"url": "a"}, ORIGIN).row
        assert (row["_task"], row["_session"], row["_step"]) == ("t-1", "s-1", "scan")
        assert row["_at"].endswith("Z")
        assert row["_updated_at"] is None

    def test_a_boolean_round_trips_as_a_bool_and_is_not_an_integer(
        self, blank: RecordStore
    ) -> None:
        blank.declare(_set(("on", "boolean"), ("n", "integer"), name="flags"))
        assert blank.add("flags", {"on": True}, ORIGIN).row["on"] is True
        with pytest.raises(RecordsError, match="n"):
            blank.add("flags", {"n": True}, ORIGIN)

    def test_a_set_without_a_key_adds_every_time(self, blank: RecordStore) -> None:
        blank.declare(NOTES)
        blank.add("notes", {"body": "x"}, ORIGIN)
        assert blank.add("notes", {"body": "x"}, ORIGIN).created is True
        assert _count(blank, "notes") == 2


class TestUpdate:
    def test_updates_by_key_and_by_id(self, store: RecordStore) -> None:
        row = store.add("listings", {"url": "a", "price": 5}, ORIGIN).row
        later = RecordOrigin(task="t-2", session="s-2", step="fix")
        by_key = store.update("listings", {"url": "a"}, {"price": 6}, later)
        by_id = store.update("listings", {"_id": row["_id"]}, {"price": 7}, later)
        assert (by_key["price"], by_id["price"]) == (6, 7)
        assert by_id["_updated_at"] is not None
        assert (by_id["_task"], by_id["_at"]) == ("t-2", row["_at"])

    def test_refusals_name_what_they_refused(self, store: RecordStore) -> None:
        store.add("listings", {"url": "a", "price": 5}, ORIGIN)
        with pytest.raises(RecordsError, match="nowhere"):
            store.update("listings", {"url": "nowhere"}, {"price": 1}, ORIGIN)
        with pytest.raises(RecordsError, match="price"):
            store.update("listings", {"price": 5}, {"price": 1}, ORIGIN)
        with pytest.raises(RecordsError, match="_task"):
            store.update("listings", {"url": "a"}, {"_task": "x"}, ORIGIN)
        with pytest.raises(RecordsError, match="url"):
            store.update("listings", {"url": "a"}, {"url": "b"}, ORIGIN)
        with pytest.raises(RecordsError, match="price"):
            store.update("listings", {"url": "a"}, {"price": "high"}, ORIGIN)
        assert store.read("SELECT price FROM listings", ALL).rows == [(5,)]

    def test_an_undeclared_set_is_refused(self, store: RecordStore) -> None:
        with pytest.raises(RecordsError, match="ghosts"):
            store.update("ghosts", {"_id": 1}, {"a": 1}, ORIGIN)


class TestRead:
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
        self, store: RecordStore, sql: str
    ) -> None:
        store.add("listings", {"url": "a", "price": 5}, ORIGIN)
        with pytest.raises(RecordsError):
            store.read(sql, ALL)
        assert store.read("SELECT url, price FROM listings", ALL).rows == [("a", 5)]

    def test_a_with_query_and_a_join_work(self, store: RecordStore) -> None:
        store.declare(_set(("url", "string"), name="sold"))
        store.add("listings", {"url": "a", "price": 5}, ORIGIN)
        store.add("listings", {"url": "b", "price": 9}, ORIGIN)
        store.add("sold", {"url": "b"}, ORIGIN)
        cte = store.read("WITH x AS (SELECT * FROM listings) SELECT count(*) FROM x", ALL)
        assert cte.rows == [(2,)]
        joined = store.read(
            "SELECT l.url, l.price FROM listings l JOIN sold s ON s.url = l.url", ALL
        )
        assert joined.columns == ("url", "price")
        assert joined.rows == [("b", 9)]

    def test_rows_over_the_bound_are_counted_as_cut(self, store: RecordStore) -> None:
        for n in range(300):
            store.add("listings", {"url": f"u{n}", "price": n}, ORIGIN)
        out = store.read("SELECT url FROM listings ORDER BY _id", ReadLimits(200, 10_000_000))
        assert (len(out.rows), out.cut) == (200, 100)
        assert out.rows[0] == ("u0",)

    def test_rows_over_the_character_bound_are_counted_as_cut(self, store: RecordStore) -> None:
        for n in range(50):
            store.add("listings", {"url": f"https://example.test/{n}", "price": n}, ORIGIN)
        out = store.read("SELECT url FROM listings ORDER BY _id", ReadLimits(1000, 200))
        assert 0 < len(out.rows) < 50
        assert len(out.rows) + out.cut == 50

    def test_a_statement_that_never_ends_is_stopped_by_the_time_bound(
        self, store: RecordStore
    ) -> None:
        endless = (
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT max(x) FROM c"
        )
        began = time.monotonic()
        with pytest.raises(RecordsError, match="stopped"):
            store.read(endless, ReadLimits(10, 1000, timeout_s=0.3))
        assert time.monotonic() - began < 5

    def test_a_pod_that_has_written_nothing_is_refused_not_created(
        self, blank: RecordStore
    ) -> None:
        with pytest.raises(RecordsError):
            blank.read("SELECT 1", ALL)
        assert blank.has("listings") is False


class TestExport:
    def test_csv_header_is_the_columns_and_the_count_is_every_row(
        self, store: RecordStore, tmp_path: Path
    ) -> None:
        for n in range(300):
            store.add("listings", {"url": f"u{n}", "price": n}, ORIGIN)
        out = tmp_path / "out.csv"
        statement = "SELECT url, price FROM listings ORDER BY _id"
        written = store.export(statement, out, "csv", ReadLimits())
        rows = list(csv.reader(out.open(encoding="utf-8")))
        assert written == 300
        assert rows[0] == ["url", "price"]
        assert len(rows) == 301
        assert rows[2] == ["u1", "1"]

    def test_markdown_is_a_table_with_pipes_escaped(
        self, store: RecordStore, tmp_path: Path
    ) -> None:
        store.add("listings", {"url": "a|b", "price": 1}, ORIGIN)
        out = tmp_path / "out.md"
        assert store.export("SELECT url, price FROM listings", out, "markdown", ReadLimits()) == 1
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "| url | price |"
        assert lines[2] == "| a\\|b | 1 |"

    def test_an_unknown_format_and_a_write_are_refused_and_leave_no_file(
        self, store: RecordStore, tmp_path: Path
    ) -> None:
        with pytest.raises(RecordsError, match="xml"):
            store.export("SELECT 1", tmp_path / "o.xml", "xml", ReadLimits())
        with pytest.raises(RecordsError):
            store.export("DELETE FROM listings", tmp_path / "o.csv", "csv", ReadLimits())
        assert not list(tmp_path.glob("o.*"))


def test_a_second_handle_on_the_same_pod_sees_the_rows(
    store: RecordStore, open_store: Callable[..., RecordStore]
) -> None:
    store.add("listings", {"url": "a"}, ORIGIN)
    assert _count(open_store("pod")) == 1
    assert open_store("other").has("listings") is False
