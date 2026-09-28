# Observability Export Specification

**Version**: 1.0.0
**Status**: Draft - model and projection implemented; no exporter yet. `core/telemetry.py`
provides the neutral span model, the incremental projection, and the export policy; no
destination, wire encoding, queue, or CLI surface exists yet.
**Last Updated**: 2026-09-27

## Purpose

Docket's per-session JSONL trace (`trace-store.spec.md`) is a closed, docket-specific
vocabulary. This specification defines the neutral, vendor-agnostic layer built on top of it:
a deterministic projection of trace records into spans and span events (`core/telemetry.py`),
and the policy that decides what a caller may send off the host and how much of a payload it
carries. It is the abstraction that keeps wire formats and vendor knowledge out of `core/`,
while the trace store itself stays the single source of truth.

## Scope

This specification covers:

- The `Span`/`SpanEvent` dataclasses: their fields, deterministic id derivation, and the
  restriction of attribute values to `str | int | bool`.
- `ProjectionState` and the incremental `project(record, state)` / `flush_open(state)`
  functions: which trace record types open a span, which close one, which become a span event
  on which span, and the fallback rule for a record type with no explicit case.
- `ExportPolicy` and `admit(record)`: event-type admission and payload reduction
  (`metadata`/`full`).

This specification does NOT cover, and each is planned for a later card that will extend this
document rather than replace it:

- Any wire encoding of a `Span` (an `otlp-http` dialect).
- A destination document (`kind: exporter`), its credentials, or a built-in catalog.
- The bounded queue or background thread that would carry spans off the calling thread.
- A `docket exporters` command or any other CLI surface.
- `task_id` on the trace record itself (`trace-store.spec.md` owns the record shape); this
  module only reads it defensively (`record.get("task_id", "")`), so nothing here changes when
  the field arrives.

## Requirements

### Span model

1. `SpanEvent` **MUST** carry `name`, `ts`, and `attributes` (a mapping whose values are each
   `str`, `int`, or `bool`).
2. `Span` **MUST** carry `trace_id`, `span_id`, `parent_id` (`None` only for a root span),
   `name`, `start_ts`, `end_ts`, `status`, `attributes`, and `events` (zero or more
   `SpanEvent`). Both dataclasses **MUST** be immutable (`frozen=True`).
3. `trace_id` **MUST** be derived from the session id alone (`sha256(session_id)` truncated to
   32 hex characters), so every span belonging to one session shares one trace id.
4. `span_id` **MUST** be derived from `(session_id, kind, key)` (`sha256` of the pipe-joined
   triple, truncated to 16 hex characters), so a record that is replayed (a retried hop, a
   re-ingested log) derives the same id instead of a duplicate span.
5. Timestamps on a `Span` **MUST** remain the record's own ISO-8601 string form; no numeric
   time unit (nanoseconds, epoch seconds) is introduced at this layer.

### Projection

6. `project(record, state)` **MUST** be a pure, incremental fold: given one trace record and
   the running `ProjectionState`, it **MUST** return exactly the spans this record closes, and
   **MUST NOT** re-emit a span already returned by an earlier call.
7. A `session_start` record **MUST** open one root span named `docket.session`, with
   `docket.project`, `docket.role`, `docket.session_id`, and `session.id` attributes, and
   **MUST NOT** itself return a closed span.
8. An `llm_call` record **MUST** produce one complete child span named `gen_ai.chat`, parented
   to the session root, with `start_ts` computed as the record's `ts` minus its `duration_ms`,
   and attributes `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
   `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`, and `docket.iteration`. Its
   `status` **MUST** be `"error"` when the payload's `ok` field is `false`.
9. A `tool_call` record **MUST** open a span named `execute_tool <tool>`, with attributes
   `gen_ai.tool.name` and `gen_ai.tool.call.id`; the matching `tool_result` record (same
   `callId`) **MUST** close it, adding `docket.tool.ok` and, when the payload names a blocking
   policy, `docket.tool.blocked_by`.
10. `hop_retry`, `rework_started`, `verdict_rework_started`, `verdict_rejected`,
    `verdict_unparseable`, `route_taken`, `command_step`, `review_rejected`,
    `tester_verdict_failed`, and `verification_failed` **MUST** become a `SpanEvent` on the
    session root (never on a nested span), named for the record's `event_type`, carrying
    `docket.hop`/`docket.task_id` only when the record supplies them.
11. Every other trace record type **MUST** become a `SpanEvent` on the innermost span still
    open for that session, named for the record's `event_type`, with one attribute per scalar
    (`str`/`int`/`bool`) payload field, each prefixed `docket.`.
12. A `session_end` record **MUST** close the root span and every span still open for that
    session, each with `status: "unset"`, and **MUST** remove that session's state so nothing
    further is emitted for it.
13. `flush_open(state)` **MUST** close every span still open across every session `state` still
    holds, at that session's last-seen timestamp, and **MUST** clear `state` for each session it
    closes.
14. A record whose `event_type` this module does not recognise **MUST** be ignored — it
    **MUST NOT** raise, and **MUST NOT** mutate `state`.

### Export policy

15. `ExportPolicy.admit(record)` **MUST** return `None` when `events` is not `None` and the
    record's `event_type` is not a member of it, and **MUST NOT** mutate the input record.
16. Under `payload="metadata"` (the module's default), `admit` **MUST** drop the payload keys
    `arguments`, `text`, `content`, `output`, `result`, `prompt`, `messages`, and `summary`, and
    **MUST** keep every other payload key unchanged.
17. Under `payload="full"`, `admit` **MUST** keep every payload key, but **MUST** truncate the
    string form of each key named in requirement 16 to `payload_max_chars` characters.
18. `DEFAULT_EVENTS` **MUST** exclude any record type whose payload is expected to carry
    prompt or message content by construction (`context_composed`, `prompt_composed`,
    `session_compaction`, `request_fit`), **MUST** exclude `cost_charged` (an estimate is never
    exported as a measurement), and **MUST** exclude `run_cancellation_observed`/`step_skipped`
    (no destination has asked for either).

## Interface Contracts

### Module API (`docket.core.telemetry`)

```python
AttrValue = str | int | bool
Attributes = dict[str, AttrValue]

@dataclass(frozen=True)
class SpanEvent:
    name: str
    ts: str
    attributes: Attributes = ...

@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start_ts: str
    end_ts: str
    status: str
    attributes: Attributes
    events: tuple[SpanEvent, ...] = ()

class ProjectionState: ...  # opaque; one instance per consumer, never per record

def project(record: dict[str, Any], state: ProjectionState) -> list[Span]: ...
def flush_open(state: ProjectionState) -> list[Span]: ...

DEFAULT_EVENTS: frozenset[str]

@dataclass(frozen=True)
class ExportPolicy:
    events: frozenset[str] | None = None   # None = admit every event type
    payload: str = "metadata"              # "metadata" | "full"
    payload_max_chars: int = 4000

    def admit(self, record: dict[str, Any]) -> dict[str, Any] | None: ...
```

## Examples

### Projecting one session

```python
from docket.core import telemetry

state = telemetry.ProjectionState()
spans: list[telemetry.Span] = []
for record in records:            # one session's trace_event() records, in order
    spans.extend(telemetry.project(record, state))
spans.extend(telemetry.flush_open(state))   # closes anything session_end did not
```

### Reducing a payload before export

```python
policy = telemetry.ExportPolicy(events=telemetry.DEFAULT_EVENTS, payload="metadata")
admitted = policy.admit(record)
if admitted is not None:
    send(admitted)   # never carries "arguments", "output", "prompt", ...
```

## Validation

### Pre-conditions

- A record handed to `project` **MUST** carry at least `event_type` and `session_id`; every
  other field is read defensively (`.get(...)` with a default), so a minimal or partial record
  never raises.

### Post-conditions

- After feeding a full session's records to `project` in order and then calling `flush_open`,
  the combined output **MUST** contain exactly one root span, and every non-root span's
  `parent_id` **MUST** name a `span_id` present in that same output.
- Running the same sequence of records through a fresh `ProjectionState` a second time **MUST**
  produce the identical set of `(trace_id, span_id)` pairs.

### Invariants

- `core/telemetry.py` **MUST NOT** import anything from `edges/`, open a socket, print, or
  write to disk.
- Redaction of secret shapes happens once, in `core.trace.trace_event`, before a record is
  written; this module never re-redacts and never widens what `metadata` mode already dropped.

## Changelog

### Version 1.0.0 (2026-09-27)

- Initial specification: the neutral `Span`/`SpanEvent` model, deterministic id derivation, the
  incremental `project`/`flush_open` projection over every `core.trace.EVENT_TYPES` member, and
  `ExportPolicy`'s event admission and payload reduction. No exporter, wire encoding, queue, or
  CLI surface exists yet; later cards extend this document with those sections.
