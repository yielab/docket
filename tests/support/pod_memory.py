"""Test-side pod memory: a one-commit repository, fake hops and a recorded task."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket.observability import trace as _trace
from docket.teams import memory as pm
from tests.support.git import git_identity_flags as _git

PROJECT = "demo"
TASK = "job-1"
SESSION = f"agent:{PROJECT}:{TASK}"


@dataclass
class Hop:
    role: str = "implementer"
    ok: bool = True
    output: str = ""
    evidence: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    trace: dict[str, str] | None = None


@dataclass
class Result:
    hops: list[Hop] = field(default_factory=list)
    status: str = "done"


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repository with ``dist/bundle.js`` and ``api/schema.proto`` in one commit."""
    root = tmp_path / "repo"
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "bundle.js").write_text("x\n")
    (root / "api").mkdir()
    (root / "api" / "schema.proto").write_text("syntax = 'proto3';\n")
    _git(root.parent, "init", "-q", str(root))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root, _git(root, "rev-parse", "HEAD")


def link(events: list[tuple[str, dict[str, Any]]], task: str = TASK) -> dict[str, str]:
    """Write *events* to the task's trace session and return the hop's trace link."""
    session = f"agent:{PROJECT}:{task}"
    for event_type, payload in events:
        _trace.trace_event(PROJECT, session, "implementer", event_type, json.dumps(payload))
    return {"project": PROJECT, "session": session, "firstTs": "0", "lastTs": "9"}


def empty_trace(task: str = TASK) -> dict[str, str]:
    return link([("session_start", {"source": "test"})], task)


def record(
    repo_root: Path,
    commit: str,
    output: str,
    *,
    trace: dict[str, str] | None = None,
    task: str = TASK,
) -> list[pm.MemoryEntry]:
    """Record *output* as the reply of one ok hop at *commit*."""
    hop = Hop(output=output, evidence={"commit": commit}, trace=trace or empty_trace(task))
    return pm.record_task_memory(PROJECT, task, Result([hop]), root=str(repo_root))
