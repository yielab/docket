"""Project-level status views for the current directory or every pod."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.edges import store


def _project_ids() -> list[str]:
    """Return registered pod ids once each, excluding flat legacy agents."""
    projects: set[str] = set()
    for agent in _fleet.list_agents():
        raw = store.read_json(_cfg.meta_path(agent.id))
        project = str(raw.get("pod", "")) or (_pod.pod_of(agent.id) or "")
        if project:
            projects.add(project)
    return sorted(projects)


def _project_summary(project: str) -> dict[str, Any]:
    registered = {agent.id for agent in _fleet.list_agents()}
    members = _pod.members_of(sorted(registered), project)
    member_rows: list[dict[str, str]] = []
    roots: list[str] = []
    degraded = False

    for member_id, role, _index in members:
        raw = store.read_json(_cfg.meta_path(member_id))
        root = str(raw.get("workDir") or raw.get("codebase") or "")
        if root:
            roots.append(root)
        workspace = _cfg.workspace_dir(member_id)
        healthy = workspace.is_dir() and (workspace / _cfg.META_FILE).is_file()
        degraded = degraded or not healthy
        member_rows.append(
            {"id": member_id, "role": role, "status": "ready" if healthy else "missing"}
        )

    tasks = _dispatch.read_tasks(project)
    counts = Counter(str(task.get("status", "pending")) for task in tasks)
    if degraded or not members:
        state = "degraded"
    elif counts["waiting_approval"]:
        state = "waiting"
    elif counts["running"]:
        state = "active"
    elif counts["failed"]:
        state = "attention"
    else:
        state = "ready"

    return {
        "id": project,
        "path": roots[0] if roots else "",
        "status": state,
        "memberCount": len(member_rows),
        "isolation": "project workspaces; dispatch history scoped by step",
        "members": member_rows,
        "tasks": {
            "pending": counts["pending"],
            "running": counts["running"],
            "waitingApproval": counts["waiting_approval"],
            "failed": counts["failed"],
            "completed": counts["completed"],
        },
    }


def _render_current(summary: dict[str, Any]) -> None:
    tasks = summary["tasks"]
    roles = ", ".join(member["role"] for member in summary["members"])
    ui.console.print(f"[bold]Project:[/bold] {summary['id']}")
    ui.console.print(f"[bold]Path:[/bold] {summary['path'] or '—'}")
    ui.console.print(f"[bold]Status:[/bold] {summary['status']}")
    ui.console.print(f"[bold]Members:[/bold] {summary['memberCount']} ({roles})")
    ui.console.print(f"[bold]Isolation:[/bold] {summary['isolation']}")
    ui.console.print(
        "[bold]Tasks:[/bold] "
        f"{tasks['pending']} pending · {tasks['running']} running · "
        f"{tasks['waitingApproval']} waiting approval · {tasks['failed']} failed"
    )


def _render_all(summaries: list[dict[str, Any]]) -> None:
    from rich.table import Table

    if not summaries:
        ui.warn("No initialized projects. Run 'docket init' inside a project directory.")
        return
    table = Table(title="Docket projects — global status")
    table.add_column("PROJECT", style="bold")
    table.add_column("STATUS")
    table.add_column("MEMBERS", justify="right")
    table.add_column("TASKS")
    table.add_column("PATH", style="dim")
    for summary in summaries:
        tasks = summary["tasks"]
        task_text = (
            f"{tasks['pending']} pending / {tasks['running']} running / "
            f"{tasks['waitingApproval']} waiting"
        )
        table.add_row(
            summary["id"],
            summary["status"],
            str(summary["memberCount"]),
            task_text,
            summary["path"] or "—",
        )
    ui.console.print(table)


def run_status(*, all_projects: bool, json_out: bool, directory: Path | None = None) -> int:
    """Render current-project status by default, or one row per pod globally."""
    summaries = [_project_summary(project) for project in _project_ids()]
    if all_projects:
        if json_out:
            print(json.dumps({"projects": summaries}, indent=2))
        else:
            _render_all(summaries)
        return 0

    from docket.cli._agents import _pod_for_directory

    project, matches = _pod_for_directory(directory or Path.cwd())
    if project is None:
        if matches:
            ui.error(
                "Current directory matches multiple projects: "
                f"{', '.join(matches)}. Use 'docket status --all'."
            )
        else:
            ui.error(
                "This directory is not inside an initialized Docket project. "
                "Run 'docket init' here, or use 'docket status --all'."
            )
        return 1

    summary = next((item for item in summaries if item["id"] == project), _project_summary(project))
    if json_out:
        print(json.dumps(summary, indent=2))
    else:
        _render_current(summary)
    return 0
