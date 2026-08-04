"""``docket runs`` — inspect the dispatch run registry.

One record per dispatch invocation — CLI (`docket pod <p> dispatch`), the serve
webhook (`POST /dispatch/<project>`), a due schedule, or the periodic sweep
loop (`docket serve --dispatch`) — see `core/runs.py`. This is the answer to
"is it done, did it fail, or did it never run" for background dispatch, which
used to be answerable only by discarding the exception and returning 200.
"""

from __future__ import annotations

import json

from rich.table import Table

from docket import ui
from docket.core import runs as _runs

_STATE_STYLE: dict[str, str] = {
    "succeeded": "green",
    "failed": "red",
    "cancelled": "magenta",
    "running": "yellow",
    "queued": "dim",
}


def _flag(args: list[str], name: str) -> str | None:
    """Return the value after ``--name`` (or ``--name=value``), else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def run_runs(sub: str | None, args: list[str]) -> int:
    """Dispatch ``docket runs <sub> ...``. Returns a process exit code."""
    sub = (sub or "list").lower()
    if sub == "list":
        return _list(args)
    if sub == "show":
        return _show(args)
    if sub == "cancel":
        return _cancel(args)
    ui.error(f"Unknown subcommand '{sub}'. Use: list | show <id> | cancel <id>.")
    return 1


def _list(args: list[str]) -> int:
    project = _flag(args, "--project")
    json_out = "--json" in args
    records = _runs.list_runs(project)

    if json_out:
        print(json.dumps({"runs": records}, indent=2))
        return 0

    title = f"Dispatch runs — {project}" if project else "Dispatch runs"
    if not records:
        ui.header(title)
        ui.console.print()
        ui.info("No dispatch runs recorded yet.")
        ui.console.print(
            "  A run is created every time a pod is dispatched — via the CLI, the "
            "serve webhook, a due schedule, or the sweep loop."
        )
        ui.console.print()
        return 0

    table = Table(title=title)
    table.add_column("ID", style="bold")
    table.add_column("SOURCE")
    table.add_column("PROJECT")
    table.add_column("STATE")
    table.add_column("TASKS", justify="right")
    table.add_column("CREATED", style="dim")
    table.add_column("ERROR", style="dim")
    for r in records:
        state = str(r.get("state", "?"))
        style = _STATE_STYLE.get(state, "")
        state_cell = f"[{style}]{state}[/{style}]" if style else state
        task_ids = r.get("taskIds") or []
        error = str(r.get("error", ""))
        error_cell = f"{error[:40]}…" if len(error) > 40 else error
        table.add_row(
            str(r.get("id", "?")),
            str(r.get("source", "?")),
            str(r.get("project", "?")),
            state_cell,
            str(len(task_ids)),
            str(r.get("created", ""))[:19],
            error_cell,
        )
    ui.console.print(table)
    return 0


def _show(args: list[str]) -> int:
    if not args:
        ui.error("Usage: docket runs show <id> [--json]")
        return 1
    run_id = args[0]
    json_out = "--json" in args[1:]

    rec = _runs.get_run(run_id)
    if rec is None:
        ui.error(f"Unknown run: {run_id}")
        return 1

    if json_out:
        print(json.dumps(rec, indent=2))
        return 0

    ui.header(f"Run — {rec.get('id', run_id)}")
    ui.console.print()
    task_ids = rec.get("taskIds") or []
    variables = rec.get("variables") or {}
    for label, val in (
        ("Source", rec.get("source", "?")),
        ("Project", rec.get("project", "?")),
        ("State", rec.get("state", "?")),
        ("Tasks", ", ".join(str(t) for t in task_ids) if task_ids else "—"),
        # The pipeline variable namespace this run was dispatched with —
        # today, only a webhook-triggered run ever has a non-empty one (its
        # JSON body's params, resolved against the pod's effective pipeline).
        (
            "Variables",
            ", ".join(f"{k}={v}" for k, v in variables.items()) if variables else "—",
        ),
        ("Created", rec.get("created", "") or "—"),
        ("Started", rec.get("startedAt") or "—"),
        ("Finished", rec.get("finishedAt") or "—"),
    ):
        ui.console.print(f"  [bold]{label + ':':<10}[/bold] {val}")
    error = str(rec.get("error", ""))
    if error:
        ui.console.print()
        ui.error(error)
    ui.console.print()
    return 0


def _cancel(args: list[str]) -> int:
    """``docket runs cancel <id>`` — kill the run's in-flight hop's process
    group and mark it terminally ``cancelled``."""
    if not args:
        ui.error("Usage: docket runs cancel <id>")
        return 1
    run_id = args[0]
    outcome = _runs.cancel_run(run_id)
    if not outcome.ok:
        ui.error(outcome.message)
        return 1
    ui.success(outcome.message)
    return 0
