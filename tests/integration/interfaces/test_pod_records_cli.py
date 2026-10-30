"""A pod's ``kind: records`` documents: ``pod update`` creates and extends the table, ``pod export``
writes the document back without a row, and ``docket pod records`` reads the rows."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.kernel.home import Home, current_home, use_home
from docket.platform.records_store import RecordMeta, RecordsStore
from docket.teams import pod
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.interfaces.cli.commands.pod_records"

_runner = CliRunner()

_LEADS = """\
kind: records
name: leads
description: People the pod has contacted.
key: email
columns:
  - {name: email, type: string, required: true}
  - {name: score, type: integer}
"""
_LEADS_WIDER = _LEADS + "  - {name: agent, type: string}\n"
_LEADS_WITHOUT_SCORE = _LEADS.replace("  - {name: score, type: integer}\n", "")


@pytest.fixture(autouse=True)
def _pods_home(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("shop", pod.DEFAULT_POD_ROLES, codebase="/src/shop")
        yield


def _recipe(tmp_path: Path, text: str = _LEADS, name: str = "recipe") -> Path:
    directory = tmp_path / name
    (directory / "records").mkdir(parents=True, exist_ok=True)
    (directory / "records" / "leads.yaml").write_text(text, encoding="utf-8")
    (directory / "pod.yaml").write_text("kind: pod\nname: r\n", encoding="utf-8")
    return directory


def _update(directory: Path) -> _model.ApplyResult:
    return _write.apply(_pod_apply.plan_apply("shop", directory))


def _store() -> RecordsStore:
    return RecordsStore(current_home().pod_records_path("shop"))


def _count() -> int:
    return int(_store().query("SELECT count(*) FROM leads", 5, 1000).rows[0][0])


def _fill(n: int) -> None:
    for i in range(n):
        _store().add("leads", {"email": f"p{i}@x.test", "score": i}, RecordMeta("t", "s", "scan"))


def _records(*args: str) -> tuple[int, str]:
    result = _runner.invoke(app, ["pod", "records", "--pod", "shop", *args])
    return result.exit_code, result.output


def _items(plan: _model.ApplyPlan) -> list[tuple[str, str, str]]:
    return [(i.name, i.action, i.note) for i in plan.items if i.kind == "records"]


def test_pod_update_creates_the_table_and_a_second_update_skips(tmp_path: Path) -> None:
    directory = _recipe(tmp_path)
    plan = _pod_apply.plan_apply("shop", directory)
    assert _items(plan) == [("leads", "add", "creates the table")]
    assert not current_home().pod_records_path("shop").exists()

    _write.apply(plan)

    assert _count() == 0
    assert (current_home().pod_config_dir("shop") / "records" / "leads.yaml").read_text() == _LEADS
    assert [i[1] for i in _items(_pod_apply.plan_apply("shop", directory))] == ["skip"]
    lock = json.loads((current_home().pod_config_dir("shop") / "applied.lock").read_text())
    (item,) = [i for i in lock["items"] if i["kind"] == "records"]
    assert item["name"] == "leads" and item["applied"] == "records/leads.yaml"


def test_a_column_added_to_the_document_keeps_the_rows(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))
    _fill(3)

    wider = _recipe(tmp_path, _LEADS_WIDER, "wider")
    assert _items(_pod_apply.plan_apply("shop", wider)) == [
        ("leads", "replace", "adds column agent")
    ]
    _update(wider)

    assert _count() == 3
    assert _store().query("SELECT agent FROM leads", 5, 1000).columns == ("agent",)


def test_a_column_removed_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))
    _fill(2)
    before = (current_home().pod_config_dir("shop") / "records" / "leads.yaml").read_bytes()

    with pytest.raises(_model.PodApplyError, match="score"):
        _pod_apply.plan_apply("shop", _recipe(tmp_path, _LEADS_WITHOUT_SCORE, "narrower"))

    assert _count() == 2
    assert _store().query("SELECT * FROM leads", 5, 1000).columns[-1] == "score"
    assert (current_home().pod_config_dir("shop") / "records" / "leads.yaml").read_bytes() == before


def test_a_bad_document_refuses_the_update_naming_the_file(tmp_path: Path) -> None:
    bad = _recipe(tmp_path, _LEADS.replace("key: email", "key: nobody"))

    with pytest.raises(_model.PodApplyError, match=r"leads\.yaml"):
        _pod_apply.plan_apply("shop", bad)
    assert not current_home().pod_records_path("shop").exists()


def test_a_second_file_for_one_set_is_refused(tmp_path: Path) -> None:
    directory = _recipe(tmp_path)
    (directory / "records" / "again.yaml").write_text(_LEADS, encoding="utf-8")

    with pytest.raises(_model.PodApplyError, match="leads"):
        _pod_apply.plan_apply("shop", directory)


def test_the_list_names_each_set_with_its_row_count(tmp_path: Path) -> None:
    code, out = _records()
    assert code == 0 and "No records in pod 'shop'" in out

    _update(_recipe(tmp_path))
    _fill(2)
    code, out = _records("--json")

    assert code == 0
    assert json.loads(out) == [
        {
            "name": "leads",
            "rows": 2,
            "columns": 2,
            "key": "email",
            "description": "People the pod has contacted.",
        }
    ]
    assert "leads" in _records()[1]


def test_a_set_declared_but_never_applied_lists_zero_rows(tmp_path: Path) -> None:
    overlay = current_home().pod_config_dir("shop") / "records"
    overlay.mkdir(parents=True)
    (overlay / "leads.yaml").write_text(_LEADS, encoding="utf-8")

    rows = json.loads(_records("--json")[1])
    assert [(r["name"], r["rows"]) for r in rows] == [("leads", 0)]
    code, out = _records("leads", "--json")
    assert code == 0 and json.loads(out)["rows"] == []


def test_a_set_shows_its_rows_up_to_the_limit_and_counts_the_rest(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))
    _fill(5)

    code, out = _records("leads", "--limit", "2", "--json")
    shown = json.loads(out)

    assert code == 0
    assert (shown["set"], shown["cut"], len(shown["rows"])) == ("leads", 3, 2)
    assert shown["rows"][0]["email"] == "p0@x.test" and "_id" in shown["columns"]
    assert "3 more" in _records("leads", "--limit", "2")[1]


def test_sql_runs_a_select_and_refuses_a_write_leaving_the_rows(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))
    _fill(3)

    code, out = _records("leads", "--sql", "SELECT email FROM leads WHERE score >= 1", "--json")
    assert code == 0
    assert [r["email"] for r in json.loads(out)["rows"]] == ["p1@x.test", "p2@x.test"]

    code, out = _records("leads", "--sql", "DELETE FROM leads")
    assert code == 1 and "refused" in out
    assert _count() == 3


def test_csv_writes_every_row_regardless_of_the_limit(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))
    _fill(4)
    target = tmp_path / "leads.csv"

    code, out = _records("leads", "--limit", "1", "--csv", str(target))

    assert code == 0 and "4" in out
    with target.open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][:2] == ["_id", "_at"] and len(rows) == 5


def test_an_undeclared_set_and_a_bad_limit_exit_nonzero(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))

    code, out = _records("ghosts")
    assert code == 1 and "ghosts" in out and "leads" in out
    assert _records("leads", "--limit", "0")[0] != 0


def test_pod_export_writes_the_document_back_and_never_a_row(tmp_path: Path) -> None:
    _update(_recipe(tmp_path))
    _fill(2)
    exported = tmp_path / "export"

    result = _runner.invoke(app, ["pod", "export", str(exported), "--pod", "shop"])

    assert result.exit_code == 0
    assert yaml.safe_load((exported / "records" / "leads.yaml").read_text())["name"] == "leads"
    assert "records.sqlite" in result.output and "never exported" in result.output
    assert not [p for p in exported.rglob("*") if p.suffix in {".sqlite", ".csv"}]
    assert "p0@x.test" not in "".join(p.read_text() for p in exported.rglob("*") if p.is_file())


def test_pod_validate_checks_a_records_directory(tmp_path: Path) -> None:
    good = _recipe(tmp_path)
    assert _runner.invoke(app, ["pod", "validate", str(good)]).exit_code == 0

    bad = _recipe(tmp_path, _LEADS.replace("integer", "money"), "bad")
    result = _runner.invoke(app, ["pod", "validate", str(bad)])
    assert result.exit_code == 1 and "type" in result.output
