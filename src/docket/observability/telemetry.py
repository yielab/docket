"""Neutral span model over the trace vocabulary, and the policy that reduces a payload
before export. ``Span``/``SpanEvent``/``project``/``flush_open``/``ExportPolicy`` are pure: no
socket, no queue, no vendor knowledge -- ``project`` turns ``observability/trace.py`` records into spans
deterministically, so a retried record never produces a duplicate one. ``Pipeline`` and the
module-level registry below them are the one impure part of this module: a bounded queue and a
background sender per enabled exporter, wired to ``observability.trace.add_subscriber``."""

from __future__ import annotations

import contextlib
import queue
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from docket.kernel import clock as _clock
from docket.kernel import threads as _threads
from docket.kernel.home import current_home
from docket.kernel.ports import process as _process
from docket.observability import exporter as _exporter
from docket.observability import trace
from docket.observability.projection import DEFAULT_EVENTS, flush_open, flush_turn, project
from docket.observability.spans import (
    ExportPolicy,
    ProjectionState,
    Span,
)

# ── Export pipeline: bounded queue, background sender, module registry ──
#
# Everything below is deliberately impure -- a queue, a thread, a module-level registry -- unlike
# the projection/policy above it. `Pipeline` never imports `observability/adapters`: it receives an already-built
# `SpanSink` object and never constructs one itself (`observability/adapters` does that).


# Matched structurally against observability/adapters/otlp_http.py::SinkResult's field names,
# never imported by name, so this module still never imports anything from observability/adapters/. Declared as
# read-only properties, not plain attributes: a frozen dataclass only satisfies a Protocol that
# asks for a get, never one that also demands a set.
class SinkOutcome(Protocol):
    """The shape `Pipeline` reads off whatever `SpanSink.emit` returns."""

    @property
    def accepted(self) -> int: ...
    @property
    def status(self) -> int | None: ...
    @property
    def error(self) -> str: ...
    @property
    def retry_after_s(self) -> float | None: ...


class SpanSink(Protocol):
    """What a wire adapter must supply for `Pipeline` to drain into it. One instance per enabled
    exporter, built by `observability/adapters` from an `ExporterSpec` -- this module never
    builds one itself."""

    def emit(self, spans: Sequence[Span]) -> SinkOutcome: ...
    def close(self) -> None: ...


@dataclass
class PipelineStats:
    """One exporter's delivery counters -- the exact per-name shape
    `Home.exporters_health_file` holds (observability-export.spec.md requirement 32)."""

    exported: int = 0
    dropped: int = 0
    failed: int = 0
    last_ok: str = ""
    last_error: str = ""
    last_error_at: str = ""


class _FlushMarker:
    """Sentinel pushed onto a `Pipeline`'s queue: the drain thread sends whatever batch is
    already forming, then sets this event. Never mistaken for a real span -- checked with
    `isinstance` before anything treats a queued item as one."""

    __slots__ = ("event",)

    def __init__(self) -> None:
        self.event = threading.Event()


_STOP = object()


# `offer` runs `policy.admit` and `project` in the caller's thread (whichever thread
# `observability.trace.trace_event` runs on) and enqueues the spans it closes with `put_nowait`; a full
# queue increments `dropped` and returns rather than blocking the caller. One daemon thread
# drains the queue in batches (up to `batch_max` items, or `batch_wait_s` since the first item
# in a forming batch) and calls `sink.emit`, folding the result into `PipelineStats`.
class Pipeline:
    """One exporter's bounded queue and background sender. Never raises out of `offer`,
    `flush`, or `close`."""

    def __init__(
        self,
        sink: SpanSink,
        policy: ExportPolicy,
        *,
        queue_max: int,
        batch_max: int = 100,
        batch_wait_s: float = 1.0,
        clock: Callable[[], float],
    ) -> None:
        self._sink = sink
        self._policy = policy
        self._batch_max = batch_max
        self._batch_wait_s = batch_wait_s
        self._clock = clock
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=queue_max)
        self._state = ProjectionState()
        self._project_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = PipelineStats()
        self._thread = _threads.start_thread(self._drain)

    def offer(self, record: dict[str, Any]) -> None:
        """Admit *record* through `policy`, project it, and enqueue any spans it closes."""
        try:
            admitted = self._policy.admit(record)
            if admitted is None:
                return
            with self._project_lock:
                spans = project(admitted, self._state, self._policy)
        except Exception:
            return
        for span in spans:
            self._enqueue(span)

    def _enqueue(self, item: Any) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._stats_lock:
                self._stats.dropped += 1

    def flush(self, timeout_s: float, *, final: bool = False) -> None:
        """Force-close every span still open, enqueue it, then wait at most *timeout_s* for the
        drain thread to have sent everything queued as of this call -- never longer. A session
        root stays open for the session's next turn unless *final*."""
        try:
            with self._project_lock:
                closed = flush_open(self._state) if final else flush_turn(self._state)
            for span in closed:
                self._enqueue(span)
            marker = _FlushMarker()
            try:
                self._queue.put_nowait(marker)
            except queue.Full:
                return
            marker.event.wait(timeout_s)
        except Exception:
            return

    def close(self) -> None:
        """Flush, then stop the drain thread and release the sink."""
        with contextlib.suppress(Exception):
            self.flush(current_home().export_flush_timeout_s, final=True)
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_STOP)
        self._thread.join(timeout=current_home().export_flush_timeout_s)
        with contextlib.suppress(Exception):
            self._sink.close()

    def stats(self) -> PipelineStats:
        with self._stats_lock:
            return replace(self._stats)

    @property
    def policy(self) -> ExportPolicy:
        return self._policy

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is _STOP:
                return
            batch: list[Span] = []
            markers: list[_FlushMarker] = []
            if isinstance(item, _FlushMarker):
                markers.append(item)
            else:
                batch.append(item)
                deadline = self._clock() + self._batch_wait_s
                while len(batch) < self._batch_max:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        break
                    try:
                        item = self._queue.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if item is _STOP:
                        if batch:
                            self._send(batch)
                        return
                    if isinstance(item, _FlushMarker):
                        markers.append(item)
                        break
                    batch.append(item)
            if batch:
                self._send(batch)
            for marker in markers:
                marker.event.set()

    def _send(self, batch: list[Span]) -> None:
        try:
            result = self._sink.emit(batch)
        except Exception as exc:
            with self._stats_lock:
                self._stats.failed += len(batch)
                self._stats.last_error = str(exc)
                self._stats.last_error_at = _clock.stamp()
            return
        accepted = max(0, min(int(result.accepted), len(batch)))
        with self._stats_lock:
            self._stats.exported += accepted
            if accepted < len(batch):
                self._stats.failed += len(batch) - accepted
            if result.error:
                self._stats.last_error = result.error
                self._stats.last_error_at = _clock.stamp()
            elif accepted:
                self._stats.last_ok = _clock.stamp()


SinkFactory = Callable[[Any, list[str]], SpanSink]

_REGISTRY: dict[str, Pipeline] = {}
_REGISTRY_LOCK = threading.Lock()
_UNSUBSCRIBE: Callable[[], None] | None = None


def _events_for(spec: Any) -> frozenset[str] | None:
    if spec.events == "all":
        return None
    if spec.events == "default":
        return DEFAULT_EVENTS
    return frozenset(spec.events)


def load_enabled_exporters() -> list[Any]:
    """Every entry in the exporter catalog (`observability.exporter.load_catalog`) with `enabled: true`
    -- credential resolution is `start`'s job, not this loader's, so a caller can hand this
    straight to `start` every turn without duplicating that check."""
    return [spec for spec in _exporter.load_catalog().entries.values() if spec.enabled]


def _fan_out(record: dict[str, Any]) -> None:
    with _REGISTRY_LOCK:
        pipelines = list(_REGISTRY.values())
    for pipeline in pipelines:
        with contextlib.suppress(Exception):
            pipeline.offer(record)


# A no-op (returns 0) under `DOCKET_NO_EXPORT=1`, when *specs* has nothing enabled, or when the
# registry is already started -- this registry starts at most once per process.
def start(specs: Sequence[Any], sink_for: SinkFactory) -> int:
    """Build one `Pipeline` per *specs* entry that is enabled and whose credentials all resolve,
    subscribing one fan-out sink through `observability.trace.add_subscriber`. Returns the count of
    pipelines actually started."""
    global _UNSUBSCRIBE
    if _process.no_export():
        return 0
    with _REGISTRY_LOCK:
        if _REGISTRY or _UNSUBSCRIBE is not None:
            return 0
        started = 0
        for spec in specs:
            if not spec.enabled:
                continue
            values, _source = _exporter.resolve_credentials(spec)
            if spec.auth.credentials and any(not value for value in values):
                continue
            sink = sink_for(spec, values)
            policy = ExportPolicy(
                events=_events_for(spec),
                classes=spec.privacy_classes,
                label=spec.privacy_label,
                content_max_chars=spec.content_max_chars,
            )
            _REGISTRY[spec.name] = Pipeline(
                sink, policy, queue_max=current_home().export_queue_max, clock=_clock.monotonic
            )
            started += 1
        if started:
            _UNSUBSCRIBE = trace.add_subscriber(_fan_out)
        return started


def flush(timeout_s: float) -> None:
    """Flush every started `Pipeline`, each bounded to at most *timeout_s*. Never raises."""
    with _REGISTRY_LOCK:
        pipelines = list(_REGISTRY.values())
    for pipeline in pipelines:
        with contextlib.suppress(Exception):
            pipeline.flush(timeout_s)


def close() -> dict[str, dict[str, Any]]:
    """Flush and stop every started `Pipeline`, unsubscribe the fan-out sink, and return the
    final counters in `health()`'s shape so the caller can record what the final flush sent.
    Safe to call more than once, or when nothing was started (returns ``{}``)."""
    global _UNSUBSCRIBE
    with _REGISTRY_LOCK:
        unsubscribe = _UNSUBSCRIBE
        _UNSUBSCRIBE = None
        items = list(_REGISTRY.items())
        _REGISTRY.clear()
    if unsubscribe is not None:
        with contextlib.suppress(Exception):
            unsubscribe()
    for _name, pipeline in items:
        with contextlib.suppress(Exception):
            pipeline.close()
    return _health_of(items)


def capture_classes() -> frozenset[str]:
    """Union of the content classes every started pipeline's policy grants -- empty when
    none is started. A caller uses this to decide what to capture, only on demand, so with
    every exporter at `minimal` the local trace stays exactly what it is today."""
    with _REGISTRY_LOCK:
        pipelines = list(_REGISTRY.values())
    classes: set[str] = set()
    for pipeline in pipelines:
        classes |= pipeline.policy.classes
    return frozenset(classes)


def health() -> dict[str, dict[str, Any]]:
    """Every started exporter's current counters, in `Home.exporters_health_file`'s shape --
    the caller (`hops/application/driver.py::run_turn`) writes this through
    `platform/store.py`; this function itself performs no I/O."""
    with _REGISTRY_LOCK:
        items = list(_REGISTRY.items())
    return _health_of(items)


def _health_of(items: list[tuple[str, Pipeline]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, pipeline in items:
        stats = pipeline.stats()
        out[name] = {
            "exported": stats.exported,
            "dropped": stats.dropped,
            "failed": stats.failed,
            "lastOk": stats.last_ok,
            "lastError": stats.last_error,
            "lastErrorAt": stats.last_error_at,
        }
    return out
