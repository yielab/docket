"""The ``kind: records`` document: its typed config, its loader and the files it is read from."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml

from docket.kernel import records as _kernel_records
from docket.platform.records_store import COLUMN_TYPES, QueryResult
from docket.teams import config_docs as _config_docs
from docket.teams import records as _records

SUBJECT = "docket.teams.records"

_DOC: dict[str, Any] = {
    "kind": "records",
    "name": "leads",
    "description": "People the pod has contacted.",
    "key": "email",
    "columns": [
        {"name": "email", "type": "string", "required": True, "description": "Who."},
        {"name": "score", "type": "integer"},
        {"name": "seen", "type": "date"},
    ],
}


def _write(tmp_path: Path, doc: dict[str, Any], name: str = "leads.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def _with_columns(*columns: dict[str, Any], **fields: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_DOC)
    doc["columns"] = list(columns)
    doc.update(fields)
    return doc


def test_a_valid_document_round_trips(tmp_path: Path) -> None:
    loaded = _records.load_records_document(_write(tmp_path, _DOC))

    assert (loaded.name, loaded.key, [c.name for c in loaded.columns]) == (
        "leads",
        "email",
        ["email", "score", "seen"],
    )
    assert loaded.columns[0].required is True and loaded.columns[1].required is False
    dumped = {"kind": "records", **loaded.model_dump(mode="json", exclude_defaults=True)}
    again = _records.load_records_document(_write(tmp_path, dumped, "again.yaml"))
    assert again == loaded
    assert dumped == _DOC


def test_a_column_type_the_store_lacks_cannot_be_declared() -> None:
    assert get_args(_kernel_records.ColumnType) == COLUMN_TYPES


@pytest.mark.parametrize(
    ("doc", "field"),
    [
        (_with_columns({"name": "_x", "type": "string"}, key=None), r"columns\.0\.name"),
        (_with_columns({"name": "_at", "type": "string"}, key=None), r"columns\.0\.name"),
        (_with_columns({"name": "Price", "type": "integer"}, key=None), r"columns\.0\.name"),
        (_with_columns({"name": "a", "type": "money"}, key=None), r"columns\.0\.type"),
        (_with_columns({"name": "a", "type": "string"}, key="b"), r"\bkey\b"),
        (
            _with_columns({"name": "a", "type": "string"}, {"name": "a", "type": "integer"}),
            r"\bcolumns\b",
        ),
        (_with_columns({"name": "a", "type": "string", "unique": True}, key=None), r"unique"),
        (_with_columns(key=None), r"\bcolumns\b"),
        ({**_DOC, "name": "9lives"}, r"\bname\b"),
        ({**_DOC, "owner": "me"}, r"owner"),
    ],
)
def test_a_bad_document_is_refused_naming_the_file_and_the_field(
    tmp_path: Path, doc: dict[str, Any], field: str
) -> None:
    path = _write(tmp_path, doc)
    with pytest.raises(_records.RecordsDocError, match=field) as raised:
        _records.load_records_document(path)
    assert str(path) in str(raised.value)


def test_a_set_has_at_most_forty_columns(tmp_path: Path) -> None:
    forty = [{"name": f"c{i}", "type": "string"} for i in range(40)]
    assert (
        len(
            _records.load_records_document(
                _write(tmp_path, _with_columns(*forty, key=None))
            ).columns
        )
        == 40
    )
    with pytest.raises(_records.RecordsDocError, match=r"\bcolumns\b"):
        extra = [*forty, {"name": "c40", "type": "string"}]
        _records.load_records_document(_write(tmp_path, _with_columns(*extra, key=None), "x.yaml"))


def test_the_underscore_message_says_why(tmp_path: Path) -> None:
    doc = _with_columns({"name": "_x", "type": "string"}, key=None)
    with pytest.raises(_records.RecordsDocError, match="underscore"):
        _records.load_records_document(_write(tmp_path, doc))


def test_config_docs_loads_a_records_document_by_kind_and_by_location(tmp_path: Path) -> None:
    named = _config_docs.load_document(_write(tmp_path, _DOC))
    assert (named.kind, named.name) == ("records", "leads")

    folder = tmp_path / "records"
    folder.mkdir()
    bare = {k: v for k, v in _DOC.items() if k != "kind"}
    located = _config_docs.load_document(_write(folder, bare))
    assert located.kind == "records"

    bad = _write(folder, {**_DOC, "key": "nope"}, "bad.yaml")
    with pytest.raises(_config_docs.ConfigDocError, match="key"):
        _config_docs.load_document(bad)
    assert folder / "leads.yaml" in _config_docs.discover_config_paths(tmp_path)


def test_records_files_are_the_yaml_files_of_the_directory_sorted(tmp_path: Path) -> None:
    folder = tmp_path / "records"
    folder.mkdir()
    for name in ("b.yml", "a.yaml", "c.json", "notes.md"):
        (folder / name).write_text("x", encoding="utf-8")

    assert [f.name for f in _records.records_files(tmp_path)] == ["a.yaml", "b.yml"]
    assert _records.records_files(tmp_path / "nowhere") == []


def test_rows_payload_keys_each_row_by_column_name() -> None:
    record_set = _kernel_records.RecordSet.model_validate(
        {"name": "leads", "columns": [{"name": "email", "type": "string"}]}
    )
    result = QueryResult(columns=("_id", "email"), rows=[(1, "a@x.test")], cut=3)

    assert _records.rows_payload(record_set, result) == {
        "set": "leads",
        "columns": ["_id", "email"],
        "rows": [{"_id": 1, "email": "a@x.test"}],
        "cut": 3,
    }
