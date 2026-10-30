"""docket pod records: what a pod keeps in its records file, read-only.

A set is a ``kind: records`` document (pod-records.spec.md); this lists the sets with their row
counts and shows a set's rows through the store's read-only query. It never writes."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
from rich.markup import escape

from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.render import ui
from docket.kernel.errors import InvalidInput
from docket.kernel.records import RecordSet
from docket.teams import records as _records


def _fail(what: str, do: str = "") -> NoReturn:
    ui.error(escape(what), do)
    raise typer.Exit(1)


def _cell(value: object) -> str:
    return "-" if value is None else escape(str(value))


def _list(project: str, json_out: bool) -> None:
    found, problems = _records.pod_record_sets(project)
    rows = [
        {
            "name": s.name,
            "rows": _records.row_count(project, s),
            "columns": len(s.columns),
            "key": s.key,
            "description": s.description,
        }
        for s in found
    ]
    if json_out:
        _contract.emit_json(rows)
    elif not rows and not problems:
        ui.dim(f"No records in pod '{project}'.")
    elif rows:
        ui.table(
            [
                [_cell(r[k]) for k in ("name", "rows", "columns", "key", "description")]
                for r in rows
            ],
            ["SET", "ROWS", "COLUMNS", "KEY", "DESCRIPTION"],
        )
    for problem in problems:
        ui.error(escape(problem), "Fix the file, then list again")
    if problems:
        raise typer.Exit(1)


def _find(project: str, name: str) -> RecordSet:
    found, _ = _records.pod_record_sets(project)
    for record_set in found:
        if record_set.name == name:
            return record_set
    known = ", ".join(s.name for s in found) or "none"
    _fail(f"Pod '{project}' declares no record set '{name}' (it declares: {known})")


def _show(project: str, record_set: RecordSet, sql: str | None, limit: int, json_out: bool) -> None:
    result = _records.read_rows(project, record_set, sql, limit)
    if json_out:
        names = list(result.columns)
        _contract.emit_json(
            {
                "set": record_set.name,
                "columns": names,
                "rows": [dict(zip(names, row, strict=True)) for row in result.rows],
                "cut": result.cut,
            }
        )
        return
    if result.rows:
        ui.table([[_cell(v) for v in row] for row in result.rows], list(result.columns))
    else:
        ui.dim(f"No rows in '{record_set.name}'.")
    if result.cut:
        ui.dim(f"  {result.cut} more rows not shown; raise --limit or use --csv FILE")


def cmd_records(
    set_name: str | None = typer.Argument(None, metavar="[SET]", help="A record set to read"),
    sql: str | None = typer.Option(None, "--sql", help="A read-only SELECT instead of the set"),
    limit: int = typer.Option(50, "--limit", min=1, help="Rows to show"),
    csv_file: Path | None = typer.Option(
        None, "--csv", help="Write every row of the statement to this file as CSV"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod_name: str | None = pod_option(),
) -> None:
    """List the pod's record sets with their row counts, or show one set's rows.

    Reads only: --sql runs on a read-only connection, so anything but one SELECT is refused.
    --csv FILE writes every row, whatever --limit says.

    Example: docket pod records leads --sql "SELECT email FROM leads" --limit 20"""
    project = _contract.require_pod(pod_name)
    if set_name is None:
        if sql is not None or csv_file is not None:
            _fail("--sql and --csv read one set", "Name the set: docket pod records <set>")
        _list(project, json_out)
        return
    record_set = _find(project, set_name)
    try:
        if csv_file is not None:
            count = _records.export_csv(project, record_set, sql, csv_file)
            ui.success(f"Wrote {count} rows of '{set_name}' to {csv_file}")
        else:
            _show(project, record_set, sql, limit, json_out)
    except InvalidInput as exc:
        _fail(str(exc), f"See: docket pod records {set_name}")
