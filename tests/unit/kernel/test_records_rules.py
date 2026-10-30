"""The rules every records backend shares (`kernel/records_rules.py`): values against a column type,
the checks of an add and an update, the declaration change, the read bound and the export rendering."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from docket.kernel.records import COLUMN_TYPES, RecordColumn, RecordsError, RecordSet
from docket.kernel.records_port import ReadLimits
from docket.kernel.records_rules import (
    EXPORT_FORMATS,
    bound_rows,
    check_add,
    check_declaration,
    check_format,
    check_update,
    check_value,
    plan_change,
    write_export,
)

SUBJECT = "docket.kernel.records_rules"


def _set(*columns: tuple[str, str], key: str | None = None, name: str = "listings") -> RecordSet:
    return RecordSet(
        name=name,
        key=key,
        columns=[RecordColumn(name=n, type=t) for n, t in columns],  # type: ignore[arg-type]
    )


LISTINGS = _set(("url", "string"), ("price", "integer"), key="url")


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("string", "x"),
        ("integer", 3),
        ("number", 3),
        ("number", 2.5),
        ("boolean", False),
        ("date", "2026-10-30"),
    ],
)
def test_a_value_of_the_column_type_is_accepted(kind: str, value: object) -> None:
    assert check_value("c", kind, value) == value


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("string", 3),
        ("integer", "abc"),
        ("integer", 2.5),
        ("integer", True),
        ("number", True),
        ("number", "1"),
        ("number", float("inf")),
        ("boolean", 1),
        ("date", "2026-13-01"),
        ("date", "30/10/2026"),
        ("date", 20261030),
    ],
)
def test_a_value_of_another_type_is_refused_naming_the_column(kind: str, value: object) -> None:
    with pytest.raises(RecordsError, match="'c'"):
        check_value("c", kind, value)


def test_null_is_accepted_for_every_type() -> None:
    assert [check_value("c", kind, None) for kind in COLUMN_TYPES] == [None] * len(COLUMN_TYPES)


def test_an_unknown_type_is_refused() -> None:
    with pytest.raises(RecordsError, match="blob"):
        check_value("c", "blob", 1)


class TestCheckAdd:
    def test_the_values_come_back_checked(self) -> None:
        assert check_add(LISTINGS, {"url": "a", "price": 5}) == {"url": "a", "price": 5}

    def test_an_undeclared_column_and_a_wrong_type_are_refused_naming_them(self) -> None:
        with pytest.raises(RecordsError, match="colour"):
            check_add(LISTINGS, {"url": "a", "colour": "red"})
        with pytest.raises(RecordsError, match="price"):
            check_add(LISTINGS, {"url": "a", "price": "abc"})

    @pytest.mark.parametrize("values", [{"price": 5}, {"url": None}])
    def test_the_key_is_required_and_not_null(self, values: dict[str, object]) -> None:
        with pytest.raises(RecordsError, match="url"):
            check_add(LISTINGS, values)

    def test_a_set_without_a_key_needs_none(self) -> None:
        assert check_add(_set(("body", "string")), {}) == {}


class TestCheckUpdate:
    def test_a_match_by_id_or_by_key_names_the_column_and_value(self) -> None:
        assert check_update(LISTINGS, {"_id": 3}, {"price": 6}) == ("_id", 3, {"price": 6})
        assert check_update(LISTINGS, {"url": "a"}, {"price": 6}) == ("url", "a", {"price": 6})

    @pytest.mark.parametrize(
        ("match", "values", "named"),
        [
            ({"price": 5}, {"price": 1}, "price"),
            ({"_id": 1, "url": "a"}, {"price": 1}, "url"),
            ({"_id": "1"}, {"price": 1}, "_id"),
            ({"_id": True}, {"price": 1}, "_id"),
            ({"url": 3}, {"price": 1}, "url"),
            ({"url": "a"}, {}, "at least one"),
            ({"url": "a"}, {"url": "b"}, "key"),
            ({"url": "a"}, {"_task": "x"}, "_task"),
            ({"url": "a"}, {"price": "high"}, "price"),
        ],
    )
    def test_a_refusal_names_what_it_refused(
        self, match: dict[str, object], values: dict[str, object], named: str
    ) -> None:
        with pytest.raises(RecordsError, match=named):
            check_update(LISTINGS, match, values)

    def test_a_set_without_a_key_matches_only_by_id(self) -> None:
        with pytest.raises(RecordsError, match="_id"):
            check_update(_set(("body", "string")), {"body": "x"}, {"body": "y"})


class TestDeclaration:
    def test_a_new_set_is_created(self) -> None:
        change = plan_change(None, LISTINGS)
        assert (change.created, change.added) == (True, ())

    def test_a_repeated_declaration_changes_nothing_and_a_new_column_is_added(self) -> None:
        assert plan_change(LISTINGS, LISTINGS).added == ()
        wider = _set(("url", "string"), ("price", "integer"), ("agent", "string"), key="url")
        change = plan_change(LISTINGS, wider)
        assert (change.created, change.added) == (False, ("agent",))

    @pytest.mark.parametrize(
        ("wanted", "named"),
        [
            (_set(("url", "string"), key="url"), "price"),
            (_set(("url", "string"), ("cost", "integer"), key="url"), "price"),
            (_set(("url", "string"), ("price", "number"), key="url"), "price"),
            (_set(("url", "string"), ("price", "integer"), key="price"), "key"),
            (_set(("url", "string"), ("price", "integer")), "key"),
        ],
    )
    def test_a_removal_rename_retype_or_new_key_is_refused(
        self, wanted: RecordSet, named: str
    ) -> None:
        with pytest.raises(RecordsError, match=named):
            plan_change(LISTINGS, wanted)

    @pytest.mark.parametrize("bad", ["Listings", "1x", "a-b", "", "_hidden"])
    def test_a_bad_name_is_refused_even_on_a_set_built_around_validation(self, bad: str) -> None:
        column = RecordColumn.model_construct(name=bad, type="string")
        with pytest.raises(RecordsError, match="name"):
            check_declaration(RecordSet.model_construct(name="s", columns=[column], key=None))
        with pytest.raises(RecordsError, match="name"):
            check_declaration(RecordSet.model_construct(name=bad, columns=[], key=None))

    def test_an_unknown_type_a_repeat_a_missing_key_and_no_column_are_refused(self) -> None:
        def built(columns: list[RecordColumn], key: str | None = None) -> RecordSet:
            return RecordSet.model_construct(name="s", columns=columns, key=key)

        blob = RecordColumn.model_construct(name="a", type="blob")
        text = RecordColumn.model_construct(name="a", type="string")
        with pytest.raises(RecordsError, match="blob"):
            check_declaration(built([blob]))
        with pytest.raises(RecordsError, match="twice"):
            check_declaration(built([text, text]))
        with pytest.raises(RecordsError, match="key"):
            check_declaration(built([text], key="b"))
        with pytest.raises(RecordsError, match="at least one"):
            check_declaration(built([]))


class TestBoundRows:
    ROWS: ClassVar[list[tuple[str, int]]] = [(f"u{n}", n) for n in range(300)]

    def test_rows_over_the_row_bound_are_counted_as_cut(self) -> None:
        out = bound_rows(["url", "n"], self.ROWS, ReadLimits(max_rows=200))
        assert (out.columns, len(out.rows), out.cut) == (("url", "n"), 200, 100)
        assert out.rows[0] == ("u0", 0)

    def test_rows_over_the_character_bound_are_counted_as_cut(self) -> None:
        out = bound_rows(["url", "n"], self.ROWS, ReadLimits(max_chars=200))
        assert 0 < len(out.rows) < 300
        assert len(out.rows) + out.cut == 300

    def test_no_bound_keeps_every_row(self) -> None:
        out = bound_rows(["url", "n"], self.ROWS, ReadLimits())
        assert (len(out.rows), out.cut) == (300, 0)

    def test_once_a_row_does_not_fit_no_later_row_is_kept(self) -> None:
        out = bound_rows(["v"], [("x" * 50,), ("y",), ("z",)], ReadLimits(max_chars=20))
        assert (out.rows, out.cut) == ([], 3)


class TestExport:
    def test_csv_has_the_columns_as_header_and_returns_the_count(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        assert write_export(out, "csv", ["a", "b"], iter([(1, "x,y"), (2, None)])) == 2
        assert out.read_bytes() == b'a,b\r\n1,"x,y"\r\n2,\r\n'
        assert not (tmp_path / "out.csv.part").exists()

    def test_markdown_escapes_pipes_and_newlines_and_shows_null_as_empty(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.md"
        write_export(out, "markdown", ["a", "b"], [("x|y", "l1\nl2"), (None, 3)])
        assert out.read_text(encoding="utf-8") == (
            "| a | b |\n| --- | --- |\n| x\\|y | l1 l2 |\n|  | 3 |\n"
        )

    def test_a_failing_row_source_leaves_no_file(self, tmp_path: Path) -> None:
        def broken() -> object:
            yield (1,)
            raise OSError("gone")

        with pytest.raises(OSError, match="gone"):
            write_export(tmp_path / "o.csv", "csv", ["a"], broken())  # type: ignore[arg-type]
        assert list(tmp_path.iterdir()) == []

    def test_only_the_closed_list_of_formats_is_accepted(self) -> None:
        assert EXPORT_FORMATS == ("csv", "markdown")
        for fmt in EXPORT_FORMATS:
            check_format(fmt)
        with pytest.raises(RecordsError, match="xml"):
            check_format("xml")
