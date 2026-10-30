"""docket pod routine: what a pod creates for itself on a schedule.

A routine is a ``kind: routine`` document (config-format.spec.md); the service fires it under
``docket start --dispatch`` (pod-dispatch.spec.md "Routines"). This group only reads."""

from __future__ import annotations

import typer
from rich.markup import escape

from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.render import ui
from docket.kernel import clock as _clock
from docket.tasks.application import routines as _routines

routine_app = typer.Typer(
    name="routine",
    help="What this pod creates for itself on a schedule: list its routines.",
    no_args_is_help=True,
)


@routine_app.command("list")
def cmd_routine_list(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod_name: str | None = pod_option(),
) -> None:
    """List the pod's routines with their next and last slot (UTC).

    Example: docket pod routine list --json"""
    project = _contract.require_pod(pod_name)
    found, problems = _routines.load_routines(project)
    now = _clock.now()
    rows = [_routines.status(project, routine, now) for routine in found]
    if json_out:
        _contract.emit_json(rows)
    elif not rows and not problems:
        ui.dim(f"No routines in pod '{project}'.")
    elif rows:
        ui.table(
            [
                [
                    escape(r["name"]),
                    escape(r["schedule"]),
                    r["tz"],
                    r["next"] or "-",
                    r["last"] or "-",
                    "yes" if r["enabled"] else "no",
                ]
                for r in rows
            ],
            ["NAME", "SCHEDULE", "TZ", "NEXT", "LAST", "ENABLED"],
        )
    for problem in problems:
        ui.error(escape(problem), "Fix the file, then list again")
    if problems:
        raise typer.Exit(1)
