"""What a docket home holds after a release journey, read through ``Home`` so a test never
assumes where the layout keeps a file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.kernel.home import Home


@dataclass(frozen=True)
class HomeEvidence:
    runs: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    sessions: list[Path]
    trace_files: list[Path]
    trace_text: str
    audit: str
    fleet: str
    projects: list[str]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def read_home(root: Path) -> HomeEvidence:
    """Everything a journey leaves under *root*; an absent file reads as empty."""
    home = Home(root)
    runs = json.loads(_text(home.runs_file) or "{}").get("runs", [])
    lists = sorted(home.projects_dir.glob("*/TASK_LIST.json"))
    tasks = json.loads(lists[0].read_text(encoding="utf-8")).get("tasks", []) if lists else []
    traces = sorted(home.traces_dir.glob("**/*.jsonl"))
    return HomeEvidence(
        runs=runs,
        tasks=tasks,
        sessions=sorted(home.sessions_dir.glob("*/session.json")),
        trace_files=traces,
        trace_text="\n".join(path.read_text(encoding="utf-8") for path in traces),
        audit=_text(home.audit_log),
        fleet=_text(home.fleet_file),
        projects=sorted(p.name for p in home.projects_dir.glob("*") if p.is_dir()),
    )
