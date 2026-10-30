"""A pod's records: the ``kind: records`` document, the files it is read from and the pod's records
file it is applied to (specs/functional/pod-records.spec.md). The documents are pod-scoped only; the
file is ``Home.pod_records_path``, written through ``platform.RecordsStore``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.kernel.records import RecordSet
from docket.platform import Column, EnsureResult, QueryResult, RecordsStore

_COUNT_LIMIT = 5
_MAX_CHARS = 200_000
_QUERY_TIMEOUT_S = 5.0
_EXPORT_TIMEOUT_S = 30.0
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


def _store(project: str) -> RecordsStore:
    return RecordsStore(current_home().pod_records_path(project))


def _columns(record_set: RecordSet) -> list[Column]:
    return [Column(c.name, c.type) for c in record_set.columns]


def check_set(project: str, record_set: RecordSet) -> EnsureResult:
    """What applying *record_set* to *project*'s file would do; a refusal changes nothing."""
    return _store(project).check_table(record_set.name, _columns(record_set), record_set.key)


def ensure_set(project: str, record_set: RecordSet) -> EnsureResult:
    """Create *record_set*'s table in *project*'s file or add its new columns."""
    return _store(project).ensure_table(record_set.name, _columns(record_set), record_set.key)


def _table_exists(project: str, name: str) -> bool:
    if not current_home().pod_records_path(project).exists():
        return False
    sql = f"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '{name}'"
    return bool(_store(project).query(sql, 1, _MAX_CHARS, _QUERY_TIMEOUT_S).rows)


def row_count(project: str, record_set: RecordSet) -> int:
    """How many rows *record_set* holds; 0 while its table does not exist."""
    if not _table_exists(project, record_set.name):
        return 0
    sql = f'SELECT count(*) FROM "{record_set.name}"'
    return int(_store(project).query(sql, _COUNT_LIMIT, _MAX_CHARS, _QUERY_TIMEOUT_S).rows[0][0])


def default_sql(record_set: RecordSet, newest_first: bool = False) -> str:
    """The statement run when none is given: the set in `_id` order, or newest first."""
    return f'SELECT * FROM "{record_set.name}" ORDER BY _id{" DESC" if newest_first else ""}'


def read_rows(
    project: str, record_set: RecordSet, sql: str | None, limit: int, newest_first: bool = False
) -> QueryResult:
    """Run *sql* (the whole set when omitted, newest first if asked) on the read-only connection,
    at most *limit* rows. A set whose table does not exist yet reads as no rows."""
    if sql is None and not _table_exists(project, record_set.name):
        columns = (*_IMPLICIT, *(c.name for c in record_set.columns))
        return QueryResult(columns=columns, rows=[], cut=0)
    statement = sql if sql is not None else default_sql(record_set, newest_first)
    return _store(project).query(statement, limit, _MAX_CHARS, _QUERY_TIMEOUT_S)


def export_csv(project: str, record_set: RecordSet, sql: str | None, path: Path) -> int:
    """Write every row *sql* (the whole set when omitted) returns to *path* as CSV; the count."""
    statement = sql if sql is not None else default_sql(record_set)
    return _store(project).export(statement, path, "csv", _EXPORT_TIMEOUT_S)


def rows_payload(record_set: RecordSet, result: QueryResult) -> dict[str, object]:
    """``{set, columns, rows, cut}``: *result* with each row an object keyed by column name."""
    names = list(result.columns)
    return {
        "set": record_set.name,
        "columns": names,
        "rows": [dict(zip(names, row, strict=True)) for row in result.rows],
        "cut": result.cut,
    }
