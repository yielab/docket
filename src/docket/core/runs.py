"""Run registry — one persisted record per dispatch invocation (R-3 / D-17).

Background dispatch used to be unobservable: the serve webhook returned 200
before any work was attempted, the scheduler and sweeper fired dispatch in
daemon threads, and every one of those paths wrapped the actual call in
``contextlib.suppress(Exception)`` — an operator had no run id, no status
query, and no way to tell "done" from "failed" from "never ran".

This module is the fix: every time something asks a pod to dispatch (the CLI,
the serve webhook, a due schedule, the periodic sweep loop, or an MCP tool
call — ``docket mcp serve``'s ``dispatch`` tool, Phase 18 L-3) a run record is
created *before* the work starts and folded to a terminal state when it
finishes — successfully or not. Records persist to ``cfg.RUNS_FILE`` (a single
docket-owned JSON document, one list of records) through
``edges/store.py``'s locked read-modify-write, the same pattern R-1 uses for
the pod task queue, since multiple threads (webhook handler, schedule thread,
sweep loop) and the CLI can all be appending/updating concurrently.

This module never imports ``core/dispatch.py`` — ``execute()`` takes an
arbitrary zero-arg callable and duck-types a ``task_id`` attribute off
whatever it returns (matching ``dispatch.TaskResult`` without a hard
dependency), so the run registry stays agnostic of what it is recording and
``core/dispatch.py`` needs no changes at all for this card.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import docket.config as _cfg
from docket.edges import store as _store

RunSource = Literal["cli", "webhook", "schedule", "sweep", "mcp"]
RunState = Literal["queued", "running", "succeeded", "failed"]
RunTerminalState = Literal["succeeded", "failed"]

_SOURCES: frozenset[str] = frozenset({"cli", "webhook", "schedule", "sweep", "mcp"})
_TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "failed"})


class RunError(Exception):
    """Raised for an invalid run source/state or other misuse of this API."""


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def runs_path() -> Path:
    return _cfg.RUNS_FILE


def _runs_list(doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = doc.get("runs")
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def create_run(source: RunSource, project: str) -> dict[str, Any]:
    """Persist a new run record in ``queued`` state and return it.

    *source* identifies what triggered the dispatch attempt
    (``cli|webhook|schedule|sweep|mcp``); *project* is the pod being dispatched.
    Called **before** any dispatch work starts, so a caller like the serve
    webhook can hand the run id back to its own caller before the outcome is
    known.
    """
    if source not in _SOURCES:
        raise RunError(f"unknown run source: {source!r}")
    if not project:
        raise RunError("create_run: project is required")

    record: dict[str, Any] = {
        "id": f"run-{_uuid.uuid4()}",
        "source": source,
        "project": project,
        "state": "queued",
        "taskIds": [],
        "error": "",
        "created": _now(),
        "startedAt": None,
        "finishedAt": None,
    }

    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        runs = _runs_list(doc)
        runs.append(record)
        return {"runs": runs}

    _store.read_modify_write(runs_path(), _fn)
    return record


def mark_running(run_id: str) -> None:
    """Flip a run to ``running`` and stamp ``startedAt``. No-op if unknown."""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") == run_id:
                r["state"] = "running"
                r["startedAt"] = _now()
                return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _fn)


def finish_run(
    run_id: str,
    *,
    state: RunTerminalState,
    task_ids: list[str] | None = None,
    error: str = "",
) -> None:
    """Mark a run terminal (``succeeded``/``failed``). No-op if unknown.

    *task_ids* — when given — replaces the record's task-id list (the tasks
    this dispatch invocation actually touched); *error* is the exception text
    for a ``failed`` run (empty for ``succeeded``).
    """
    if state not in _TERMINAL_STATES:
        raise RunError(f"finish_run: invalid terminal state {state!r}")

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") == run_id:
                r["state"] = state
                r["finishedAt"] = _now()
                r["error"] = error
                if task_ids is not None:
                    r["taskIds"] = list(task_ids)
                return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _fn)


def get_run(run_id: str) -> dict[str, Any] | None:
    """Return one run record by id, or ``None`` if unknown."""
    doc = _store.read_json(runs_path())
    for r in _runs_list(doc):
        if r.get("id") == run_id:
            return r
    return None


def list_runs(project: str | None = None) -> list[dict[str, Any]]:
    """Return run records, newest first, optionally filtered to one project."""
    doc = _store.read_json(runs_path())
    runs = _runs_list(doc)
    if project:
        runs = [r for r in runs if r.get("project") == project]
    return sorted(runs, key=lambda r: str(r.get("created", "")), reverse=True)


def _emit_error_trace(project: str, run_id: str, source: str, error_text: str) -> None:
    """Best-effort ``error`` trace event for a failed dispatch invocation.

    Local import avoids a cycle with ``core/trace.py``; a trace failure must
    never break run recording (mirrors ``core/approval.py``'s ``_emit_trace``).
    """
    try:
        import json as _json

        from docket.core import trace as _trace

        _trace.trace_event(
            project,
            f"agent:{project}:dispatch",
            "lead",
            "error",
            _json.dumps({"run": run_id, "source": source, "error": error_text}),
        )
    except Exception:
        return None


def execute(run_id: str, fn: Callable[[], list[Any]]) -> list[Any] | None:
    """Run *fn* (a zero-arg dispatch call) under an already-created run record.

    Marks the record ``running``, invokes *fn*, and folds the outcome back in:
    ``succeeded`` plus the task ids *fn*'s results expose (a duck-typed
    ``task_id`` attribute — this is ``dispatch.TaskResult`` shaped, without
    this module importing ``core/dispatch.py``), or ``failed`` plus the
    exception text and a matching ``error`` trace event.

    Returns *fn*'s result list on success, or ``None`` on failure — this
    function itself never raises. That is what lets every dispatch call site
    (the webhook thread, the schedule thread, the sweep loop, the CLI) replace
    a bare ``contextlib.suppress(Exception)`` with a real, queryable outcome
    instead of one silently discarded.
    """
    mark_running(run_id)
    rec = get_run(run_id)
    project = str(rec.get("project", "")) if rec else ""
    source = str(rec.get("source", "")) if rec else ""
    try:
        results = fn()
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        finish_run(run_id, state="failed", error=error_text)
        _emit_error_trace(project, run_id, source, error_text)
        return None
    task_ids = [str(getattr(r, "task_id", "")) for r in results]
    finish_run(run_id, state="succeeded", task_ids=task_ids)
    return results
