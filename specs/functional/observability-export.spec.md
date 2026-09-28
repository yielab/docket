# Observability Export Specification

**Version**: 1.2.0
**Status**: Draft - model, projection, the exporter catalog, and the `otlp-http` wire dialect
are implemented. `core/telemetry.py` provides the neutral span model, the incremental
projection, and the export policy; `core/exporter.py` provides the `kind: exporter` document,
the built-in + global catalog, and pure activation classification;
`edges/adapters/exporters/otlp_http.py` provides the one shipped wire encoding and transport. No
bounded queue, background sender, health-file writer, or CLI surface exists yet.
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
- The `kind: exporter` document (`core/exporter.py`'s `ExporterSpec`/`ExporterAuth`): field
  shape, credential-name validation, and the four authentication types.
- The built-in + global exporter catalog (`Catalog`, `load_catalog`, `save_exporter`,
  `delete_exporter`, `_with_inherited_identity`, `export_exporter`) and the five built-in
  documents shipped under `templates/exporters/`.
- Pure activation classification (`activation_state`) and endpoint-probe classification
  (`verify_endpoint`), and the read-only shape of the health file (`read_health`).
- The `otlp-http` dialect (`edges/adapters/exporters/otlp_http.py`): the OTLP JSON encoding of a
  `Span`/`SpanEvent`, `OtlpHttpSink`'s transport and retry behaviour, and `probe`'s reachability
  check. This is the only module in docket that knows OTLP's wire shape.

This specification does NOT cover, and each is planned for a later card that will extend this
document rather than replace it:

- The bounded queue or background thread that would carry spans off the calling thread, and the
  code that actually writes the health file (`core/exporter.py::read_health` is read-only).
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

### Exporter documents

19. A `kind: exporter` document **MUST** validate through `core.exporter.ExporterSpec`
    (`populate_by_name`), carrying `kind` (`Literal["exporter"]`), `name`
    (`^[a-z0-9][a-z0-9-]*$`), `dialect` (`Literal["otlp-http"]`, default `"otlp-http"`),
    `endpoint` (an `http://`/`https://` URL), `auth`, `headers`, `resource` (default
    `{"service.name": "docket"}`), `aliases`, `events` (`"default"` | `"all"` | a list of
    `core.trace.EVENT_TYPES` members), `payload` (`"metadata"` | `"full"`, default
    `"metadata"`), `payloadMaxChars` (default `2000`), `enabled` (default `False`), and `note`.
20. `auth.type` **MUST** be one of `bearer`, `header`, `basic`, `none`, and **MUST** require
    exactly the credential-name arity that type implies: zero for `none`, exactly one for
    `bearer` and `header`, exactly two (ordered: username, then password) for `basic`.
    `auth.header` **MUST** be present exactly when `auth.type` is `"header"`.
21. Every name in `auth.credentials` **MUST** match `^[A-Z][A-Z0-9_]*$`. A value that instead
    looks like a credential *value* (matches `^[A-Za-z0-9/_\-+.]{20,}$`) **MUST** be refused
    naming `auth.credentials` — a document never carries a secret, only the name of one already
    in the store.
22. `headers` **MUST** refuse the reserved names `authorization`, `content-type`, `accept`
    (docket sends these itself), the same rule `core.provider.ProviderSpec.headers` applies.
23. A malformed document (unknown `kind`, missing `name`, an unknown `dialect`/`auth.type`, or
    any Requirement 20-22 failure) **MUST** raise `ExporterError` naming the file, field, and
    message, mirroring `core.provider.ProviderError`'s shape exactly (`file`, `field`,
    `message`, `valid`).

### Catalog and scopes

24. The exporter catalog **MUST** have two scopes, nearest-wins by name: built-in
    (`config.EXPORTER_TEMPLATES_DIR`, the five documents under `templates/exporters/` —
    `otel-collector`, `jaeger`, `langfuse`, `honeycomb`, `phoenix`) and global
    (`config.EXPORTERS_FILE`, the operator's own, written through `edges/store.py`).
    `Catalog.get(name)`/`source_of(name)` **MUST** report which scope resolved a name.
25. A global entry sharing a built-in's name **MUST** inherit every field it does not itself
    set, from that built-in — an override is typically a one- or two-field tweak (`endpoint`,
    `enabled`), never a from-scratch redeclaration.
26. `delete_exporter(name)` **MUST** refuse (naming the built-in scope) when *name* is a
    built-in with no global override, and **MUST** refuse naming "not in the exporter catalog"
    when *name* is not in the catalog at all; otherwise it removes the global entry.
27. `export_exporter(name)` **MUST** render the resolved catalog entry as a `kind: exporter`
    YAML document and **MUST NOT** ever include a credential value — only credential names are
    ever held by `ExporterSpec` in the first place.

### Activation state

28. `activation_state(spec, health)` **MUST** be pure (no I/O) and **MUST** return
    `"disabled"` whenever `spec.enabled` is `False`, checked before anything else — a present
    credential **MUST NOT**, by itself, activate an exporter.
29. When enabled, `activation_state` **MUST** return `("needs credential", [<missing names>])`
    naming every `auth.credentials` entry that resolves to no value (checked via
    `resolve_credentials`, which tries an environment variable of the same name first, then
    `core.secrets.secret_value`).
30. When enabled and every credential resolves, `activation_state` **MUST** return
    `"unreachable"` when *health*'s `lastErrorAt` is present and newer than its `lastOk` (or
    `lastOk` is absent), and `"enabled"` otherwise.
31. `verify_endpoint(spec, probe)` **MUST** classify a `ProbeResult` the same way
    `core.provider.verify_endpoint` classifies a provider probe: `probe.status is None` is the
    only `reachable=False` outcome; a 2xx status carries no warning; `401`/`403` names the
    credential as rejected or missing; any other status names the HTTP status.

### Health file

32. `config.EXPORTERS_HEALTH_FILE` (`exporters-health.json`) **MUST** hold a mapping of
    exporter name to `{"exported": int, "dropped": int, "failed": int, "lastOk": <timestamp>,
    "lastError": <string>, "lastErrorAt": <timestamp>}`. `core.exporter.read_health()` **MUST**
    read it through `edges/store.py` and **MUST NOT** write it — the background sender that
    writes this file is out of this specification's scope (see Scope, above).

### The otlp-http dialect

33. `encode(spans, *, resource, aliases)` **MUST** return one OTLP JSON `resourceSpans`
    document: one resource carrying `resource`'s attributes, one `scopeSpans` entry whose
    `scope` is `{"name": "docket", "version": <docket.__version__>}`, and one wire span per
    input `Span`, in input order.
34. Each wire span **MUST** carry `traceId`, `spanId`, and `parentSpanId` as lowercase hex
    strings (`parentSpanId` is the empty string for a root span, never an omitted key), `name`,
    `kind` (`3` for a span named `gen_ai.chat`, `1` otherwise), `startTimeUnixNano` and
    `endTimeUnixNano` as decimal-string nanoseconds
    (`str(int(datetime.fromisoformat(ts).timestamp() * 1e9))`), and `attributes`.
35. An OTLP attribute value **MUST** encode a `str` as `{"stringValue": ...}`, a `bool` as
    `{"boolValue": ...}`, and an `int` as `{"intValue": "<decimal string>"}` (never a bare JSON
    number, per OTLP JSON's int64-as-string convention); the attribute list **MUST** be sorted
    by key so the encoding is deterministic.
36. `aliases` **MUST** duplicate a matching attribute under its alias key on every attribute map
    it is applied to (the resource and each span's and event's attributes); it **MUST NOT**
    remove or rename the source key.
37. A wire span's `status` object (`{"code": 1}` for `Span.status == "ok"`, `{"code": 2}` for
    `"error"`) **MUST** be present only when the span's status is not `"unset"`; an `"unset"`
    span **MUST** carry no `status` key.
38. A `SpanEvent` **MUST** encode as `{"timeUnixNano", "name", "attributes"}`; a span with no
    events **MUST** carry no `events` key.
39. `OtlpHttpSink.emit(spans)` **MUST** POST `encode(...)` as `application/json` to the sink's
    configured endpoint, using the caller-supplied, already-resolved auth header pair (a
    `bearer`/`basic`/custom-header credential is resolved by the caller; this module reads no
    credential name) plus any static headers, and **MUST** return a `SinkResult` naming how many
    spans were accepted.
40. `emit` **MUST** retry the POST exactly once, and only for an HTTP 429/502/503/504 response,
    sleeping `min(Retry-After, DISPATCH_RETRY_MAX_WAIT_S)` seconds (1 second when the response
    names no `Retry-After`) before the retry; any other non-2xx response, and a second retryable
    response, **MUST** report `accepted=0` without a further retry.
41. `emit` **MUST NOT** raise for a transport failure (refused connection, timeout, DNS
    failure); such a failure **MUST** report `SinkResult(accepted=0, status=None,
    error=<non-empty>)`.
42. `emit` and `probe` **MUST** accept their clock, sleep, and HTTP opener as parameters with
    real defaults (`time.monotonic`, `time.sleep`, `urllib.request.urlopen`), so a test can
    replace all three without a real socket or a real wait.
43. `probe(endpoint, auth_header, headers, timeout_s)` **MUST** POST `{"resourceSpans": []}` and
    return a `ProbeResult` naming the raw HTTP status (`None` only for a transport failure) and
    any error text; it **MUST NOT** classify the outcome itself (that is the caller's job).

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

### Module API (`docket.core.exporter`)

```python
class ExporterAuth(BaseModel):
    type: Literal["bearer", "header", "basic", "none"]
    header: str = ""
    credentials: list[str] = []

class ExporterSpec(BaseModel):
    kind: Literal["exporter"]
    name: str
    dialect: Literal["otlp-http"] = "otlp-http"
    endpoint: str
    auth: ExporterAuth = ExporterAuth(type="none")
    headers: dict[str, str] = {}
    resource: dict[str, str] = {"service.name": "docket"}
    aliases: dict[str, str] = {}
    events: Literal["default", "all"] | list[str] = "default"
    payload: Literal["metadata", "full"] = "metadata"
    payload_max_chars: int = 2000               # alias "payloadMaxChars"
    enabled: bool = False
    note: str = ""

class ExporterError(Exception):
    file: Path
    field: str
    message: str
    valid: tuple[str, ...]

def load_exporter_document(path: str | Path) -> ExporterSpec: ...

@dataclass(frozen=True)
class Catalog:
    entries: dict[str, ExporterSpec]
    scopes: dict[str, str]                      # name -> "built-in" | "global"
    def get(self, name: str) -> ExporterSpec | None: ...
    def source_of(self, name: str) -> str: ...

def load_catalog() -> Catalog: ...
def save_exporter(spec: ExporterSpec) -> None: ...
def delete_exporter(name: str) -> None: ...     # raises ExporterError
def export_exporter(name: str) -> str: ...      # YAML, never a credential value
def resolve_credentials(spec: ExporterSpec) -> tuple[list[str], str]: ...

ExporterState = Literal["enabled", "needs credential", "disabled", "unreachable"]

def activation_state(
    spec: ExporterSpec, health: dict[str, Any] | None
) -> tuple[ExporterState, list[str]]: ...

@dataclass(frozen=True)
class ProbeResult:
    status: int | None
    error: str = ""

@dataclass(frozen=True)
class ExporterVerification:
    reachable: bool
    status: int | None
    credential_present: bool
    credential_name: str
    warning: str

def verify_endpoint(spec: ExporterSpec, probe: ProbeResult) -> ExporterVerification: ...
def read_health() -> dict[str, dict[str, Any]]: ...   # read-only
```

### Module API (`docket.edges.adapters.exporters.otlp_http`)

```python
AuthHeader = tuple[str, str] | None   # (header name, resolved value); None = no auth

def encode(
    spans: Sequence[telemetry.Span],
    *,
    resource: Mapping[str, str],
    aliases: Mapping[str, str],
) -> dict[str, Any]: ...

@dataclass(frozen=True)
class SinkResult:
    accepted: int
    status: int | None
    error: str = ""
    retry_after_s: float | None = None

class OtlpHttpSink:
    def __init__(
        self,
        endpoint: str,
        auth_header: AuthHeader,
        headers: Mapping[str, str] | None = None,
        resource: Mapping[str, str] | None = None,
        aliases: Mapping[str, str] | None = None,
        timeout_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None: ...

    def emit(self, spans: Sequence[telemetry.Span]) -> SinkResult: ...
    def close(self) -> None: ...

@dataclass(frozen=True)
class ProbeResult:
    status: int | None
    error: str = ""

def probe(
    endpoint: str,
    auth_header: AuthHeader,
    headers: Mapping[str, str],
    timeout_s: float = 5.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> ProbeResult: ...
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

### Checking whether a shipped destination is ready

```python
from docket.core import exporter

catalog = exporter.load_catalog()
spec = catalog.get("langfuse")           # a built-in, disabled until enabled: true
health = exporter.read_health().get("langfuse")
state, missing = exporter.activation_state(spec, health)
# state == "disabled" until an operator both enables it and stores
# LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY.
```

### Encoding and sending one batch

```python
from docket.edges.adapters.exporters import otlp_http

document = otlp_http.encode(
    spans, resource={"service.name": "docket"}, aliases={"session.id": "langfuse.session.id"}
)
sink = otlp_http.OtlpHttpSink(
    endpoint="https://collector.example/v1/traces",
    auth_header=("Authorization", "Bearer <resolved-token>"),
)
result = sink.emit(spans)   # never raises; result.status is None only for a transport failure
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
- `core/exporter.py` **MUST NOT** import anything from `edges/adapters/`; its own probe type
  (`ProbeResult`) is a plain dataclass so the module never needs to. `core/exporter.py` and
  `core/provider.py` are a deliberate duplication, not a shared base — refactoring them to share
  code is a follow-up measurement, not a requirement of this specification.
- `activation_state` and `verify_endpoint` **MUST** be pure: no I/O, no import of `edges/store.py`.
- Nothing in `core/exporter.py` **MUST** ever hold, log, or serialize a credential *value* — only
  credential *names* are ever fields of `ExporterSpec`.
- `edges/adapters/exporters/otlp_http.py` **MUST NOT** import `core.exporter.ExporterSpec` or
  any other destination-document type; it receives only primitive values (an endpoint string,
  an already-resolved auth header pair, plain mappings) and never reads a credential by name.
- Encoding the committed fixture (`tests/fixtures/traces/dispatch-3-hops.jsonl`, projected, then
  `encode`d with `resource={"service.name": "docket"}` and
  `aliases={"session.id": "langfuse.session.id"}`) **MUST** byte-match
  `tests/fixtures/otlp-v1/dispatch-3-hops.json` (`json.dumps(sort_keys=True, indent=2) + "\n"`).
- `OtlpHttpSink.emit` and `probe` **MUST NOT** raise for any transport or HTTP-level failure;
  every outcome is a typed result.

## Changelog

### Version 1.2.0 (2026-09-27)

- Added the `otlp-http` dialect: `encode`'s OTLP JSON mapping (attribute value encoding,
  deterministic sort order, alias duplication, nanosecond timestamps, `status`/`kind` rules),
  `OtlpHttpSink`'s transport (auth header pass-through, single retry on 429/502/503/504
  honouring `Retry-After` capped by `DISPATCH_RETRY_MAX_WAIT_S`, never-raises contract), and
  `probe`'s reachability check. Added the committed wire golden
  `tests/fixtures/otlp-v1/dispatch-3-hops.json`. Written in the same wave as, and merged after,
  the exporter catalog added at 1.1.0. No bounded queue or CLI surface exists yet; later cards
  extend this document with those sections.

### Version 1.1.0 (2026-09-27)

- **The exporter catalog.** New "Exporter documents", "Catalog and scopes", "Activation state",
  and "Health file" Requirements sections (19-32): `core.exporter.ExporterSpec`/`ExporterAuth`
  (a deliberate copy of `core.provider.ProviderSpec`'s shape, not a shared base), the built-in +
  global catalog (five built-in documents under `templates/exporters/`: `otel-collector`,
  `jaeger`, `langfuse`, `honeycomb`, `phoenix`), full-field inheritance for a global override
  sharing a built-in's name, and the pure `activation_state`/`verify_endpoint` classifiers. A
  present credential never activates an exporter by itself — `enabled` is checked first. The
  wire encoding, the bounded queue/background sender, the health-file writer, and the CLI
  surface remain out of scope; later cards extend this document with those sections.

### Version 1.0.0 (2026-09-27)

- Initial specification: the neutral `Span`/`SpanEvent` model, deterministic id derivation, the
  incremental `project`/`flush_open` projection over every `core.trace.EVENT_TYPES` member, and
  `ExportPolicy`'s event admission and payload reduction. No exporter, wire encoding, queue, or
  CLI surface exists yet; later cards extend this document with those sections.
