"""A pod's records: the ``kind: records`` document, the files it is read from and the pod's records
file it is applied to (specs/functional/pod-records.spec.md). The documents are pod-scoped only; the
file is ``Home.pod_records_path``, reached through the ``RecordStore`` port (``records.open``)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.kernel.ports import records
from docket.kernel.records import RecordSet
from docket.kernel.records_port import ReadLimits, Rows, SetChange

_COUNT_LIMIT = 5
_READ = ReadLimits(max_chars=200_000, timeout_s=5.0)
_EXPORT = ReadLimits(timeout_s=30.0)
_IMPLICIT = ("_id", "_at", "_task", "_session", "_step", "_updated_at")


class RecordsDocError(InvalidInput):
    """A ``kind: records`` document is unreadable or invalid; the message names the file."""


class RecordsDocument(RecordSet):
    """A ``kind: records`` document: the set's fields under the ``kind`` envelope."""

    kind: Literal["records"]


def load_records_document(path: str | Path) -> RecordSet:
    """Read *path* as a ``kind: records`` document. Raises ``RecordsDocError`` naming the file and
    the first failing field."""
    p = Path(path)
    try:
        import yaml as _yaml  # type: ignore[import-untyped]

        raw = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except ImportError:
        raise RecordsDocError(f"{p}: PyYAML not installed -- run: pip install pyyaml") from None
    except Exception as exc:
        raise RecordsDocError(f"{p}: cannot read document: {exc}") from exc
    if not isinstance(raw, dict):
        raise RecordsDocError(f"{p}: document must be a mapping")
    try:
        document = RecordsDocument.model_validate({"kind": "records", **raw})
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        message = str(first["msg"]).removeprefix("Value error, ")
        raise RecordsDocError(f"{p}: {field}: {message}") from exc
    return RecordSet.model_validate(document.model_dump(exclude={"kind"}))


def records_files(directory: Path) -> list[Path]:
    """``records/*.yaml|yml`` directly under *directory*, sorted by name."""
    folder = directory / "records"
    return sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]) if folder.is_dir() else []


def pod_records_dir(project: str) -> Path:
    """Where *project*'s own record documents live: ``<pod config dir>/records``."""
    return current_home().pod_config_dir(project) / "records"


def pod_record_sets(project: str) -> tuple[list[RecordSet], list[str]]:
    """*project*'s sets by file name, and one message for each file that does not load."""
    found: list[RecordSet] = []
    problems: list[str] = []
    for path in records_files(current_home().pod_config_dir(project)):
        try:
            found.append(load_records_document(path))
        except RecordsDocError as exc:
            problems.append(str(exc))
    return found, problems


def find_set(project: str, name: str) -> RecordSet | None:
    """The set *project*'s documents declare under *name*, or None."""
    return next((s for s in pod_record_sets(project)[0] if s.name == name), None)


def check_set(project: str, record_set: RecordSet) -> SetChange:
    """What applying *record_set* to *project*'s records would do; a refusal changes nothing."""
    return records.open(project).plan(record_set)


def ensure_set(project: str, record_set: RecordSet) -> SetChange:
    """Declare *record_set* in *project*'s records: create it or add its new columns."""
    return records.open(project).declare(record_set)


def row_count(project: str, record_set: RecordSet) -> int:
    """How many rows *record_set* holds; 0 while it is not declared."""
    store = records.open(project)
    if not store.has(record_set.name):
        return 0
    sql = f'SELECT count(*) FROM "{record_set.name}"'
    return int(store.read(sql, replace(_READ, max_rows=_COUNT_LIMIT)).rows[0][0])


def default_sql(record_set: RecordSet, newest_first: bool = False) -> str:
    """The statement run when none is given: the set in `_id` order, or newest first."""
    return f'SELECT * FROM "{record_set.name}" ORDER BY _id{" DESC" if newest_first else ""}'


def read_rows(
    project: str, record_set: RecordSet, sql: str | None, limit: int, newest_first: bool = False
) -> Rows:
    """Run *sql* (the whole set when omitted, newest first if asked) as a read, at most *limit*
    rows. A set that is not declared yet reads as no rows."""
    store = records.open(project)
    if sql is None and not store.has(record_set.name):
        columns = (*_IMPLICIT, *(c.name for c in record_set.columns))
        return Rows(columns=columns, rows=[], cut=0)
    statement = sql if sql is not None else default_sql(record_set, newest_first)
    return store.read(statement, replace(_READ, max_rows=limit))


def export_csv(project: str, record_set: RecordSet, sql: str | None, path: Path) -> int:
    """Write every row *sql* (the whole set when omitted) returns to *path* as CSV; the count."""
    statement = sql if sql is not None else default_sql(record_set)
    return records.open(project).export(statement, path, "csv", _EXPORT)


def rows_payload(record_set: RecordSet, result: Rows) -> dict[str, object]:
    """``{set, columns, rows, cut}``: *result* with each row an object keyed by column name."""
    names = list(result.columns)
    return {
        "set": record_set.name,
        "columns": names,
        "rows": [dict(zip(names, row, strict=True)) for row in result.rows],
        "cut": result.cut,
    }
