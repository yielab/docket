"""Figures derived from records docket already keeps: cache-hit ratio, tokens per accepted task
and whether the work goes well (success, rework, rejection, asks and denials).

Read-only. ``cache_hit`` is derived on read and never stored on an ``llm_call`` record, and the
work figures are folded from task records, trace files and the audit log, never from the
metrics counters.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.observability import trace as _trace

DEFAULT_WINDOW_S = 7 * 24 * 3600


@dataclass
class CacheTotals:
    """Summed input and cache-read tokens of a set of ``llm_call`` events."""

    input_tokens: int = 0
    cached_tokens: int = 0

    @property
    def ratio(self) -> float | None:
        """Cache reads over input, from the sums; ``None`` when no input was recorded."""
        return self.cached_tokens / self.input_tokens if self.input_tokens > 0 else None


@dataclass
class CacheFigures:
    """The fold of ``llm_call`` events per ``task_id``, per ``agent_role`` and in all."""

    total: CacheTotals = field(default_factory=CacheTotals)
    by_task: dict[str, CacheTotals] = field(default_factory=dict)
    by_role: dict[str, CacheTotals] = field(default_factory=dict)


def _count(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def cache_hit(payload: Mapping[str, Any]) -> float | None:
    """``cachedTokens / inputTokens`` of one ``llm_call`` payload; ``None`` without a positive
    integer ``inputTokens``. A ``cachedTokens`` of 0 also means "not reported"."""
    input_tokens = _count(payload, "inputTokens")
    if input_tokens is None or input_tokens <= 0:
        return None
    return (_count(payload, "cachedTokens") or 0) / input_tokens


def fold_cache_hits(records: Iterable[Mapping[str, Any]]) -> CacheFigures:
    """Fold the ``llm_call`` records into summed tokens per task and per role."""
    folded = CacheFigures()
    for record in records:
        payload = record.get("payload")
        if record.get("event_type") != "llm_call" or not isinstance(payload, dict):
            continue
        input_tokens = _count(payload, "inputTokens")
        if input_tokens is None:
            continue
        cached = _count(payload, "cachedTokens") or 0
        folded.total.input_tokens += input_tokens
        folded.total.cached_tokens += cached
        for table, key in (
            (folded.by_task, record.get("task_id")),
            (folded.by_role, record.get("agent_role")),
        ):
            if key and isinstance(key, str):
                totals = table.setdefault(key, CacheTotals())
                totals.input_tokens += input_tokens
                totals.cached_tokens += cached
    return folded


def recorded_cache_figures() -> CacheFigures:
    """``fold_cache_hits`` over every project's trace files under ``traces/``."""
    traces_dir = current_home().traces_dir
    if not traces_dir.is_dir():
        return CacheFigures()
    return fold_cache_hits(
        record for tf in sorted(traces_dir.glob("*/*.jsonl")) for record in _trace.read_trace(tf)
    )


def tokens_per_accepted_task(counted: Sequence[int]) -> float | None:
    """The mean of the counted tokens of the tasks that ended ``done``; ``None`` when none did."""
    return sum(counted) / len(counted) if counted else None


Key = tuple[str, str]
_UNKNOWN = "unknown"
_ASK_RE = re.compile(r"role=(\S+) project=(\S+)")
_APPROVAL_RE = re.compile(r"token=(\S+) project=(\S+) channel=(\S+)")
_PASSING_VERDICT = "approve"
_REWORK_EVENTS = frozenset({"rework_started", "verdict_rework_started"})


@dataclass(frozen=True)
class Ratio:
    """A count over the sample it came from; ``value`` is ``None`` when the sample is empty."""

    numerator: int
    n: int

    @property
    def value(self) -> float | None:
        return self.numerator / self.n if self.n > 0 else None

    @property
    def per_100(self) -> float | None:
        return 100 * self.numerator / self.n if self.n > 0 else None


@dataclass(frozen=True)
class TaskOutcome:
    """A task in a terminal status: its pod, the role of its last hop, whether it ended ``done``,
    when it completed (epoch) and the ``(role, lowercase verdict)`` of each hop that carries one."""

    pod: str
    role: str
    done: bool
    completed: float
    verdicts: tuple[tuple[str, str], ...] = ()


@dataclass
class WorkFigures:
    """Each figure keyed by ``(pod, role)``; a key with an empty sample is absent."""

    success: dict[Key, Ratio] = field(default_factory=dict)
    rework_cycles: dict[Key, Ratio] = field(default_factory=dict)
    reviewer_rejection: dict[Key, Ratio] = field(default_factory=dict)
    human_denials: dict[Key, Ratio] = field(default_factory=dict)
    asks: dict[Key, Ratio] = field(default_factory=dict)
    granted: dict[Key, Ratio] = field(default_factory=dict)


def _tally(table: dict[Key, list[int]], key: Key, numerator: int, n: int) -> None:
    cell = table.setdefault(key, [0, 0])
    cell[0] += numerator
    cell[1] += n


def _ratios(table: Mapping[Key, list[int]]) -> dict[Key, Ratio]:
    return {k: Ratio(c[0], c[1]) for k, c in table.items() if c[1] > 0}


def _role(raw: str) -> str:
    return _UNKNOWN if raw in ("", "?") else raw


def _fold_outcomes(figs: WorkFigures, outcomes: Iterable[TaskOutcome], since: float) -> None:
    success: dict[Key, list[int]] = {}
    rejection: dict[Key, list[int]] = {}
    for outcome in outcomes:
        if outcome.completed < since:
            continue
        _tally(success, (outcome.pod, outcome.role), int(outcome.done), 1)
        for role, verdict in outcome.verdicts:
            _tally(rejection, (outcome.pod, role), int(verdict != _PASSING_VERDICT), 1)
    figs.success = _ratios(success)
    figs.reviewer_rejection = _ratios(rejection)


def _dispatched(records: Sequence[Mapping[str, Any]], since: float) -> bool:
    """Whether the file's first non-resumed dispatch ``session_start`` is inside the window."""
    for record in records:
        payload = record.get("payload")
        if record.get("event_type") != "session_start" or not isinstance(payload, dict):
            continue
        if payload.get("source") == "dispatch" and not payload.get("resumed"):
            started = _clock.parse_epoch(record.get("ts"))
            return started is not None and started >= since
    return False


def _fold_rework(
    figs: WorkFigures, files: Iterable[Sequence[Mapping[str, Any]]], since: float
) -> None:
    rework: dict[Key, list[int]] = {}
    for records in files:
        if not _dispatched(records, since):
            continue
        cycles: dict[Key, int] = {}
        for record in records:
            pod, role = str(record.get("project") or ""), str(record.get("agent_role") or "")
            if pod and role:
                cycles.setdefault((pod, role), 0)
                if record.get("event_type") in _REWORK_EVENTS:
                    cycles[(pod, role)] += 1
        for key, count in cycles.items():
            _tally(rework, key, count, 1)
    figs.rework_cycles = _ratios(rework)


def _fold_calls(files: Iterable[Sequence[Mapping[str, Any]]], since: float) -> dict[Key, int]:
    calls: dict[Key, int] = {}
    for records in files:
        for record in records:
            payload = record.get("payload")
            decision = payload.get("decision") if isinstance(payload, dict) else None
            at = _clock.parse_epoch(record.get("ts"))
            if record.get("event_type") != "tool_result" or not decision or decision == "deferred":
                continue
            if at is None or at < since:
                continue
            key = (str(record.get("project") or ""), _role(str(record.get("agent_role") or "")))
            calls[key] = calls.get(key, 0) + 1
    return calls


def _fold_audit(
    figs: WorkFigures,
    audit: Iterable[Mapping[str, Any]],
    calls: Mapping[Key, int],
    roles: Mapping[str, str],
    since: float,
) -> None:
    asked: dict[Key, int] = {}
    denied: dict[Key, int] = {}
    granted: dict[Key, int] = {}
    for entry in audit:
        at = _clock.parse_epoch(entry.get("ts"))
        action, detail = entry.get("action"), str(entry.get("detail") or "")
        if at is None or at < since:
            continue
        if action == "tool.ask" and (hit := _ASK_RE.search(detail)):
            key = (hit.group(2), _role(hit.group(1)))
            asked[key] = asked.get(key, 0) + 1
        elif action in ("approval.grant", "approval.deny") and (hit := _APPROVAL_RE.search(detail)):
            token, pod, channel = hit.groups()
            key = (pod, _role(roles.get(token, "")))
            if action == "approval.grant":
                granted[key] = granted.get(key, 0) + 1
            elif channel != "timeout":
                denied[key] = denied.get(key, 0) + 1
    figs.asks = _ratios({k: [asked.get(k, 0), n] for k, n in calls.items()})
    figs.human_denials = _ratios({k: [denied.get(k, 0), n] for k, n in asked.items()})
    figs.granted = _ratios({k: [granted.get(k, 0), n] for k, n in asked.items()})


def fold_work_figures(
    *,
    since: float,
    outcomes: Iterable[TaskOutcome] = (),
    trace_files: Iterable[Sequence[Mapping[str, Any]]] = (),
    audit: Iterable[Mapping[str, Any]] = (),
    approval_roles: Mapping[str, str] | None = None,
) -> WorkFigures:
    """Fold the six work figures over the window starting at epoch *since*; ``trace_files`` holds
    one record list per session file, ``approval_roles`` maps an approval token to its role."""
    figs = WorkFigures()
    files = [list(f) for f in trace_files]
    _fold_outcomes(figs, outcomes, since)
    _fold_rework(figs, files, since)
    _fold_audit(figs, audit, _fold_calls(files, since), approval_roles or {}, since)
    return figs


def _audit_generations() -> list[dict[str, Any]]:
    """Entries of ``audit.log.1`` then of the current ``audit.log``, so one rotation loses none."""
    logf = current_home().audit_log
    entries: list[dict[str, Any]] = []
    backup = Path(str(logf) + ".1")
    try:
        lines = backup.read_text(encoding="utf-8").splitlines() if backup.is_file() else []
    except OSError:
        lines = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries + _audit.read_audit()


def recorded_work_figures(outcomes: Iterable[TaskOutcome], since: float) -> WorkFigures:
    """``fold_work_figures`` over every project's trace files, both audit generations and the
    approval records, with *outcomes* the terminal tasks (``accepted.terminal_task_outcomes``)."""
    traces_dir = current_home().traces_dir
    files = (
        [_trace.read_trace(tf) for tf in sorted(traces_dir.glob("*/*.jsonl"))]
        if traces_dir.is_dir()
        else []
    )
    roles = {
        str(r["token"]): str(r.get("role") or "")
        for r in _approval.list_records()
        if r.get("token")
    }
    return fold_work_figures(
        since=since,
        outcomes=outcomes,
        trace_files=files,
        audit=_audit_generations(),
        approval_roles=roles,
    )
