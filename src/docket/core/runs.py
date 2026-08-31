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
once. ``cancel_run`` — the ``docket runs cancel`` CLI's real work — persists
one request atomically before signalling every captured pid's process group.
Queued work is stopped immediately; running in-process work remains visibly
requested until its owning ``execute()`` call returns and records observation
and full stop. A :class:`RunCancellationSignal` always rereads that persisted
record, so a separate CLI process and the executor share one authority.
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
_CANCELLATION_REASON = "operator request"
_CANCELLATION_SOURCE = "cli"
_CANCELLATION_REASON_CHARS = 200
_CANCELLATION_SOURCE_CHARS = 32

# Which run id (if any) the *current thread* is executing under — set by
# `execute()` for the duration of its `fn()` call. `None` outside any run
# (e.g. a test calling `dispatch_task` directly).
_CURRENT_RUN_ID: ContextVar[str | None] = ContextVar("_CURRENT_RUN_ID", default=None)


@dataclass(frozen=True, slots=True)
class CancellationLifecycle:
    """Typed view of one run record's persisted cancellation lifecycle."""

    requested_at: str | None = None
    observed_at: str | None = None
    stopped_at: str | None = None
    reason: str = ""
    source: str = ""

    @property
    def requested(self) -> bool:
        return self.requested_at is not None

    def to_record(self) -> dict[str, str | None]:
        return {
            "requestedAt": self.requested_at,
            "observedAt": self.observed_at,
            "stoppedAt": self.stopped_at,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class RunCancellationSignal:
    """Cross-process cancellation handle whose identity is the persisted run id.

    Each call reads the authoritative run record; the object contains no local
    event or cached cancellation state. Malformed lifecycle data fails closed:
    readers stop, but no observation/stopped timestamp is fabricated.
    """

    run_id: str

    def is_requested(self) -> bool:
        rec = get_run(self.run_id)
        if rec is None:
            return False
        lifecycle, valid = _cancellation_lifecycle(rec)
        return not valid or lifecycle.requested

    def observe(self) -> bool:
        """Record first observation when requested; return whether work must stop."""
        must_stop = False

        def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal must_stop
            runs = _runs_list(doc)
            for rec in runs:
                if rec.get("id") != self.run_id:
                    continue
                lifecycle, valid = _cancellation_lifecycle(rec)
                if not valid:
                    must_stop = True
                    return None
                if not lifecycle.requested:
                    return None
                must_stop = True
                if lifecycle.observed_at is not None:
                    return None
                observed = CancellationLifecycle(
                    requested_at=lifecycle.requested_at,
                    observed_at=_now(),
                    stopped_at=lifecycle.stopped_at,
                    reason=lifecycle.reason,
                    source=lifecycle.source,
                )
                _set_cancellation_lifecycle(rec, observed)
                return {"runs": runs}
            return None

        _store.read_modify_write(runs_path(), _fn)
        return must_stop


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


def _valid_timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = _dt.datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _cancellation_lifecycle(
    rec: dict[str, Any],
) -> tuple[CancellationLifecycle, bool]:
    """Parse a lifecycle without mutating legacy records that omit it."""
    if "cancellation" not in rec:
        return CancellationLifecycle(), True
    raw = rec.get("cancellation")
    if not isinstance(raw, dict):
        return CancellationLifecycle(), False
    required = {"requestedAt", "observedAt", "stoppedAt", "reason", "source"}
    if not required.issubset(raw):
        return CancellationLifecycle(), False
    requested_at = raw.get("requestedAt")
    observed_at = raw.get("observedAt")
    stopped_at = raw.get("stoppedAt")
    reason = raw.get("reason")
    source = raw.get("source")
    if not all(_valid_timestamp(value) for value in (requested_at, observed_at, stopped_at)):
        return CancellationLifecycle(), False
    if not isinstance(reason, str) or len(reason) > _CANCELLATION_REASON_CHARS:
        return CancellationLifecycle(), False
    if not isinstance(source, str) or len(source) > _CANCELLATION_SOURCE_CHARS:
        return CancellationLifecycle(), False
    if requested_at is None and (observed_at is not None or stopped_at is not None):
        return CancellationLifecycle(), False
    if observed_at is None and stopped_at is not None:
        return CancellationLifecycle(), False
    timestamps = [
        _dt.datetime.fromisoformat(value)
        for value in (requested_at, observed_at, stopped_at)
        if isinstance(value, str)
    ]
    if timestamps != sorted(timestamps):
        return CancellationLifecycle(), False
    return (
        CancellationLifecycle(
            requested_at=requested_at if isinstance(requested_at, str) else None,
            observed_at=observed_at if isinstance(observed_at, str) else None,
            stopped_at=stopped_at if isinstance(stopped_at, str) else None,
            reason=reason,
            source=source,
        ),
        True,
    )


def _set_cancellation_lifecycle(rec: dict[str, Any], lifecycle: CancellationLifecycle) -> None:
    """Update known lifecycle fields while preserving forward-compatible keys."""
    raw = rec.get("cancellation")
    cancellation = dict(raw) if isinstance(raw, dict) else {}
    cancellation.update(lifecycle.to_record())
    rec["cancellation"] = cancellation


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
        "cancellation": CancellationLifecycle().to_record(),
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
            current_state = str(r.get("state", ""))
            if current_state in _TERMINAL_STATES:
                return None
            lifecycle, valid_lifecycle = _cancellation_lifecycle(r)
            if valid_lifecycle and lifecycle.requested:
                stopped_at = _now()
                observed_at = lifecycle.observed_at or stopped_at
                _set_cancellation_lifecycle(
                    r,
                    CancellationLifecycle(
                        requested_at=lifecycle.requested_at,
                        observed_at=observed_at,
                        stopped_at=stopped_at,
                        reason=lifecycle.reason,
                        source=lifecycle.source,
                    ),
                )
                r["state"] = "cancelled"
                r["finishedAt"] = stopped_at
                r["error"] = "cancelled by operator"
                if task_ids is not None:
                    r["taskIds"] = list(task_ids)
                return {"runs": runs}
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


def current_cancellation_signal() -> RunCancellationSignal | None:
    """Return a typed persisted signal for the current ``execute`` call."""
    run_id = current_run_id()
    return RunCancellationSignal(run_id) if run_id is not None else None


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

    One locked registry transition chooses request-versus-terminal winner,
    captures and clears every in-flight pid, and persists the request before
    any signalling. Queued work is fully stopped in that transition. Running
    in-process work stays nonterminal until :func:`execute` returns. Repeated,
    terminal, unknown, and malformed requests are stable no-ops.
    """
    decision = "unknown"
    prior_state = ""
    project = ""
    pids: list[int] = []

    def _request(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal decision, prior_state, project, pids
        runs = _runs_list(doc)
        for rec in runs:
            if rec.get("id") != run_id:
                continue
            prior_state = str(rec.get("state", ""))
            project = str(rec.get("project", ""))
            if prior_state in _TERMINAL_STATES:
                decision = "terminal"
                return None
            if prior_state not in {"queued", "running"}:
                decision = "malformed"
                return None
            lifecycle, valid = _cancellation_lifecycle(rec)
            if not valid:
                decision = "malformed"
                return None
            if lifecycle.requested:
                decision = "requested"
                return None
            pids_raw = rec.get("pids")
            if isinstance(pids_raw, list):
                pids = [pid for pid in pids_raw if isinstance(pid, int) and pid > 0]
            requested_at = _now()
            stopped_at = requested_at if prior_state == "queued" else None
            _set_cancellation_lifecycle(
                rec,
                CancellationLifecycle(
                    requested_at=requested_at,
                    observed_at=stopped_at,
                    stopped_at=stopped_at,
                    reason=_CANCELLATION_REASON,
                    source=_CANCELLATION_SOURCE,
                ),
            )
            rec["pids"] = []
            if prior_state == "queued":
                rec["state"] = "cancelled"
                rec["finishedAt"] = stopped_at
                rec["error"] = "cancelled by operator"
            decision = "applied"
            return {"runs": runs}
        return None

    _store.read_modify_write(runs_path(), _request)
    if decision == "unknown":
        return CancelOutcome(ok=False, message=f"unknown run: {run_id}")
    if decision == "terminal":
        return CancelOutcome(ok=False, message=f"run {run_id} is already {prior_state}")
    if decision == "requested":
        return CancelOutcome(ok=False, message=f"run {run_id} cancellation already requested")
    if decision == "malformed":
        return CancelOutcome(ok=False, message=f"run {run_id} has invalid cancellation state")

    killed = [pid for pid in pids if _sys.kill_process_group(pid)]
    message = (
        f"requested cancellation for run {run_id} ({len(killed)} process group(s) killed)"
        if killed
        else f"requested cancellation for run {run_id} (nothing in flight to kill)"
    )
    # Every other privileged action writes an audit entry; `docket runs
    # cancel` matches that. Logged only on an actual cancellation
    # (this line), never for the unknown-id/already-terminal no-op returns
    # above — those change nothing, so there is nothing to audit. `state` here
    # is still the run's pre-cancel state (captured before the terminal-state
    # check above), so the entry records exactly what changed.
    audit_log(
        "runs.cancel",
        f"run={run_id} project={project} was={prior_state} killed={len(killed)}",
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
