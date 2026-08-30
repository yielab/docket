"""Run registry — one persisted record per dispatch invocation.

Background dispatch used to be unobservable: the serve webhook returned 200
before any work was attempted, the scheduler and sweeper fired dispatch in
daemon threads, and every one of those paths wrapped the actual call in
``contextlib.suppress(Exception)`` — an operator had no run id, no status
query, and no way to tell "done" from "failed" from "never ran".

This module is the fix: every time something asks a pod to dispatch (the CLI,
the serve webhook, a due schedule, the periodic sweep loop, or an MCP tool
call — ``docket mcp serve``'s ``dispatch`` tool) a run record is
created *before* the work starts and folded to a terminal state when it
finishes — successfully or not. Records persist to ``cfg.RUNS_FILE`` (a single
docket-owned JSON document, one list of records) through
``edges/store.py``'s locked read-modify-write, the same pattern used for
the pod task queue, since multiple threads (webhook handler, schedule thread,
sweep loop) and the CLI can all be appending/updating concurrently.

This module never imports ``core/dispatch.py`` — ``execute()`` takes an
arbitrary zero-arg callable and duck-types a ``task_id`` attribute off
whatever it returns (matching ``dispatch.TaskResult`` without a hard
dependency), so the run registry stays agnostic of what it is recording and
``core/dispatch.py`` needs no changes at all to be recorded here.

Cancellation: ``execute()`` publishes "which
run id is currently executing" via a ``contextvars.ContextVar`` for the
duration of *fn* — ``core/dispatch.py``'s production-driver hop call site
reads it (``current_run_id()``) to know which run to record a spawned
subprocess's pid against (``add_hop_pid``/``remove_hop_pid``), and
``core.orchestrator.run_group`` explicitly propagates that context into a
parallel group's worker threads (``ThreadPoolExecutor.submit`` does not do
this on its own). ``pids`` is a *list* on the run record, not a scalar,
because a parallel step can have more than one hop genuinely in flight at
once. ``cancel_run`` — the ``docket runs cancel`` CLI's real work — kills
every recorded pid's process *group* (``edges.adapters.system.
kill_process_group``; each hop subprocess starts its own session, so its pid
doubles as its group id) and marks the run a new terminal state,
``"cancelled"``, distinct from an ordinary ``"failed"`` invocation.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import docket.config as _cfg
from docket.core.audit import audit_log
from docket.edges import store as _store
from docket.edges.adapters import system as _sys

RunSource = Literal["cli", "webhook", "schedule", "sweep", "mcp"]
RunState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RunTerminalState = Literal["succeeded", "failed", "cancelled"]

_SOURCES: frozenset[str] = frozenset({"cli", "webhook", "schedule", "sweep", "mcp"})
_TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
_RETURNED_FAILURE_ERROR_CHARS = 1_024
_RETURNED_FAILURE_ID_CHARS = 80
_RETURNED_FAILURE_REASON_CHARS = 200
_RETURNED_FAILURE_DETAILS = 3

# Which run id (if any) the *current thread* is executing under — set by
# `execute()` for the duration of its `fn()` call. `None` outside any run
# (e.g. a test calling `dispatch_task` directly).
_CURRENT_RUN_ID: ContextVar[str | None] = ContextVar("_CURRENT_RUN_ID", default=None)


@dataclass
class CancelOutcome:
    """Result of :func:`cancel_run` — what a ``docket runs cancel <id>`` call
    found and did. ``core/`` returns typed results; ``cli/`` renders them."""

    ok: bool
    message: str
    killed_pids: list[int] = field(default_factory=list)


class RunError(Exception):
    """Raised for an invalid run source/state or other misuse of this API."""


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def runs_path() -> Path:
    return _cfg.RUNS_FILE


def _runs_list(doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = doc.get("runs")
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def create_run(
    source: RunSource, project: str, *, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Persist a new run record in ``queued`` state and return it.

    *source* identifies what triggered the dispatch attempt
    (``cli|webhook|schedule|sweep|mcp``); *project* is the pod being dispatched.
    Called **before** any dispatch work starts, so a caller like the serve
    webhook can hand the run id back to its own caller before the outcome is
    known.

    *variables* is the pipeline variable namespace this run was
    resolved against — today, only the serve webhook populates it (a
    payload's params, run through ``core.pipeline.resolve_variables`` against
    the pod's effective pipeline before this run is even created); every
    other source passes ``None`` and gets an empty ``{}``, so this field is
    purely additive to the schema. Recording it here — not
    just accepting it as a dispatch argument — is what lets ``docket runs
    show <id>``/``GET /runs/<id>`` answer "what variables did this dispatch
    actually see", since nothing else in the run's lifecycle persists them.
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
        # pids of any hop subprocess currently in flight for this run —
        # see add_hop_pid/remove_hop_pid/cancel_run.
        "pids": [],
        # The resolved variable namespace this run was dispatched with.
        "variables": dict(variables) if variables else {},
    }

    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        runs = _runs_list(doc)
        runs.append(record)
        return {"runs": runs}

    _store.read_modify_write(runs_path(), _fn)
    return record


def mark_running(run_id: str) -> bool:
    """Atomically claim a queued run; return false if it is no longer startable."""
    applied = False

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal applied
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") == run_id:
                if str(r.get("state", "")) != "queued":
                    return None
                r["state"] = "running"
                r["startedAt"] = _now()
                applied = True
                return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _fn)
    return applied


def _finish_run_transition(
    run_id: str,
    *,
    state: RunTerminalState,
    task_ids: list[str] | None = None,
    error: str = "",
    preserve_cancelled: bool = False,
) -> bool:
    """Atomically apply one terminal transition and report whether it won."""
    if state not in _TERMINAL_STATES:
        raise RunError(f"finish_run: invalid terminal state {state!r}")

    applied = False

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal applied
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") != run_id:
                continue
            if preserve_cancelled and str(r.get("state", "")) == "cancelled":
                return None
            r["state"] = state
            r["finishedAt"] = _now()
            r["error"] = error
            if task_ids is not None:
                r["taskIds"] = list(task_ids)
            applied = True
            return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _fn)
    return applied


def finish_run(
    run_id: str,
    *,
    state: RunTerminalState,
    task_ids: list[str] | None = None,
    error: str = "",
) -> None:
    """Mark a run terminal (including ``cancelled``). No-op if unknown.

    *task_ids* — when given — replaces the record's task-id list (the tasks
    this dispatch invocation actually touched); *error* is the exception text
    for a ``failed`` run (empty for ``succeeded``).
    """
    _finish_run_transition(run_id, state=state, task_ids=task_ids, error=error)


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


def current_run_id() -> str | None:
    """The run id this thread's :func:`execute` call is currently inside, if any.

    Set only while ``execute()``'s *fn* is running, and propagated into a
    parallel group's worker threads via ``contextvars.copy_context()`` (see
    ``core.orchestrator.run_group``). ``None`` outside any run — e.g. a test
    that calls ``dispatch_task`` directly, never through ``execute()``.
    """
    return _CURRENT_RUN_ID.get()


def add_hop_pid(run_id: str, pid: int) -> None:
    """Record a newly-spawned hop subprocess's pid as in-flight for *run_id*.

    A run's ``pids`` field is a *list*, not a scalar — a ``parallel``
    pipeline step can have more than one hop genuinely in flight at once.
    Called from a driver's ``run_turn``'s ``on_spawn`` hook via
    ``core/dispatch.py``'s production-driver hop call site (never for an
    injected test runner — see that module's ``dispatch_task``); the
    production ``DocketDriver`` ignores ``on_spawn`` since
    it backs onto no OS process for this to ever fire against, so this stays
    reachable only through a driver that does spawn one. No-op if *run_id*
    is unknown (e.g. a stale/racing caller).
    """

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") == run_id:
                pids = r.get("pids")
                if not isinstance(pids, list):
                    pids = []
                if pid not in pids:
                    pids.append(pid)
                r["pids"] = pids
                return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _fn)


def remove_hop_pid(run_id: str, pid: int) -> None:
    """Clear a completed hop's pid from *run_id*'s in-flight list.

    No-op if the pid (or the run) is already gone — a hop that finished
    normally, or a run already cancelled, is a harmless race, not an error.
    """

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") == run_id:
                pids = r.get("pids")
                if isinstance(pids, list) and pid in pids:
                    r["pids"] = [p for p in pids if p != pid]
                    return {"runs": runs}
                return None
        return None

    _store.read_modify_write(runs_path(), _fn)


def cancel_run(run_id: str) -> CancelOutcome:
    """Cancel an in-flight dispatch run (``docket runs cancel <id>``).

    Kills every pid recorded as currently in flight for *run_id* — each
    hop's whole process *group*, not just the immediate child (see
    ``edges.adapters.system.kill_process_group``; every hop subprocess
    starts its own session, so its pid doubles as its group id) — then
    marks the run terminally ``"cancelled"``, distinct from an ordinary
    ``"failed"`` invocation.

    Idempotent: a run already in a terminal state
    (``succeeded``/``failed``/``cancelled``) is left untouched and reported
    as a no-op, never re-signalled or double-finished. A recorded pid that's
    already gone by the time this runs (the hop finished on its own between
    the read and the kill attempt — an inherent, harmless race) is silently
    skipped by ``kill_process_group`` itself.
    """
    rec = get_run(run_id)
    if rec is None:
        return CancelOutcome(ok=False, message=f"unknown run: {run_id}")
    state = str(rec.get("state", ""))
    if state in _TERMINAL_STATES:
        return CancelOutcome(ok=False, message=f"run {run_id} is already {state}")

    pids_raw = rec.get("pids")
    pids = [int(p) for p in pids_raw] if isinstance(pids_raw, list) else []
    killed = [pid for pid in pids if _sys.kill_process_group(pid)]

    def _clear_pids(doc: dict[str, Any]) -> dict[str, Any] | None:
        runs = _runs_list(doc)
        for r in runs:
            if r.get("id") == run_id:
                r["pids"] = []
                return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _clear_pids)
    finish_run(run_id, state="cancelled", error="cancelled by operator")
    message = (
        f"cancelled run {run_id} ({len(killed)} process group(s) killed)"
        if killed
        else f"cancelled run {run_id} (nothing in flight to kill)"
    )
    # Every other privileged action writes an audit entry; `docket runs
    # cancel` matches that. Logged only on an actual cancellation
    # (this line), never for the unknown-id/already-terminal no-op returns
    # above — those change nothing, so there is nothing to audit. `state` here
    # is still the run's pre-cancel state (captured before the terminal-state
    # check above), so the entry records exactly what changed.
    audit_log(
        "runs.cancel",
        f"run={run_id} project={rec.get('project', '')} was={state} killed={len(killed)}",
    )
    return CancelOutcome(ok=True, message=message, killed_pids=killed)


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


def _bounded_failure_field(value: object, *, limit: int, fallback: str) -> str:
    """Normalize one operator-facing field without serializing its source object."""
    normalized = " ".join(str(value).split()) or fallback
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def _returned_failure_summary(failures: list[Any]) -> str:
    """Build a deterministic, content-bounded summary from task ids/reasons only."""
    details: list[str] = []
    for result in failures[:_RETURNED_FAILURE_DETAILS]:
        task_id = _bounded_failure_field(
            getattr(result, "task_id", ""),
            limit=_RETURNED_FAILURE_ID_CHARS,
            fallback="<unknown-task>",
        )
        reason = _bounded_failure_field(
            getattr(result, "reason", ""),
            limit=_RETURNED_FAILURE_REASON_CHARS,
            fallback="no reason provided",
        )
        details.append(f"{task_id}: {reason}")

    omitted = len(failures) - len(details)
    omitted_text = f"; +{omitted} more" if omitted else ""
    summary = f"{len(failures)} returned task(s) failed: {'; '.join(details)}{omitted_text}"
    return summary[:_RETURNED_FAILURE_ERROR_CHARS]


def execute(run_id: str, fn: Callable[[], list[Any]]) -> list[Any] | None:
    """Run *fn* (a zero-arg dispatch call) under an already-created run record.

    Marks the record ``running``, invokes *fn*, and folds the outcome back in:
    ``succeeded`` plus the task ids *fn*'s results expose (a duck-typed
    ``task_id`` attribute — this is ``dispatch.TaskResult`` shaped, without
    this module importing ``core/dispatch.py``), or ``failed`` plus a bounded
    summary when any returned result exposes ``status="failed"``. Exceptions
    retain their exception text. Both failure paths emit the same ``error``
    trace event.

    Returns *fn*'s result list whenever *fn* returns normally, including when
    that list makes the run outcome ``failed``. It returns ``None`` when the
    run cannot be claimed or *fn* raises; this function itself never raises.
    That is what lets every dispatch call site
    (the webhook thread, the schedule thread, the sweep loop, the CLI) replace
    a bare ``contextlib.suppress(Exception)`` with a real, queryable outcome
    instead of one silently discarded.

    Publishes ``run_id`` via ``current_run_id()`` for the duration of
    *fn* (a ``contextvars.ContextVar``, so it is thread-local and safely
    propagated into a parallel group's worker threads — see
    ``core.orchestrator.run_group``), and never lets a normal completion
    clobber a run a concurrent ``docket runs cancel`` already marked
    ``"cancelled"`` back to ``"succeeded"``/``"failed"``.
    """
    if not mark_running(run_id):
        return None
    rec = get_run(run_id)
    project = str(rec.get("project", "")) if rec else ""
    source = str(rec.get("source", "")) if rec else ""
    token = _CURRENT_RUN_ID.set(run_id)
    try:
        results = fn()
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        applied = _finish_run_transition(
            run_id,
            state="failed",
            error=error_text,
            preserve_cancelled=True,
        )
        if applied:
            _emit_error_trace(project, run_id, source, error_text)
        return None
    finally:
        _CURRENT_RUN_ID.reset(token)

    task_ids: list[str] = []
    failures: list[Any] = []
    for result in results:
        task_ids.append(str(getattr(result, "task_id", "")))
        if str(getattr(result, "status", "")) == "failed":
            failures.append(result)

    error_text = _returned_failure_summary(failures) if failures else ""
    applied = _finish_run_transition(
        run_id,
        state="failed" if failures else "succeeded",
        task_ids=task_ids,
        error=error_text,
        preserve_cancelled=True,
    )
    if failures and applied:
        _emit_error_trace(project, run_id, source, error_text)
    return results
