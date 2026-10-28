"""Figures derived from records docket already keeps: cache-hit ratio and tokens per accepted task.

Read-only. ``cache_hit`` is derived on read and never stored on an ``llm_call`` record.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from docket.kernel.home import current_home
from docket.observability import trace as _trace


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
