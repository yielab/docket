# Observability Export Specification

**Version**: 1.9.0
**Status**: Implemented and live. Model, projection, the exporter catalog, the `otlp-http` wire
dialect, the bounded queue/background sender, the `run_turn` wiring, CLI activation (`docket
exporters enable/disable/test/add/remove/list/show/export/privacy/preview`), `pod.yaml`'s
`exporters:` key and the privacy levels (ADR 0015) are all live, verified against a real
OpenTelemetry Collector and a real Langfuse project at `minimal`, `actions` and `conversation`
(see "External verification"). A destination receives structure only unless the exporter's own
document grants a content class; at `conversation` Langfuse shows each generation's Input and
Output and each tool's result. `core/telemetry.py` provides the neutral span
model, the incremental projection, the export policy, and `Pipeline`/the module-level
`start`/`flush`/`close`/`health` registry; `core/exporter.py` provides the `kind: exporter`
document, the built-in + global catalog, pure activation classification, and
`enable_exporter`/`disable_exporter`; `edges/adapters/exporters/otlp_http.py` provides the one
shipped wire encoding and transport; `edges/adapters/exporters/__init__.py` builds a `SpanSink`
from a resolved `ExporterSpec` (`sink_for`); `edges/adapters/docket_runtime.py::run_turn` starts
the pipeline lazily and flushes it, writing `config.EXPORTERS_HEALTH_FILE`, on every return path.
**Last Updated**: 2026-09-28

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
- `ExportPolicy` and `admit(record)`: event-type admission only, never payload reduction.
- `core/privacy.py`'s content classes and levels, and `core/telemetry.py`'s allowlist
  projection (`ATTRIBUTE_CLASSES`, `_STRUCTURAL_KEYS`, per-message-part filtering,
  `capture_classes()`) that decides what a granted class actually shares (ADR 0015).
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
- The bounded queue and background sender (`core/telemetry.py::Pipeline` and the module-level
  `start`/`flush`/`close`/`health` registry): batching, drop-on-full backpressure, the health
  counters `health()` reports, and `sink_for` (`edges/adapters/exporters/__init__.py`), which
  builds a `SpanSink` from a resolved `ExporterSpec` and its already-resolved credential values.
- How `edges/adapters/docket_runtime.py::run_turn` wires the pipeline into a live turn: lazy,
  idempotent start; a `flush` and a `config.EXPORTERS_HEALTH_FILE` write on every return path;
  `atexit`-registered `close`.
- Turning an exporter on or off by authenticating (`core/exporter.py::enable_exporter`/
  `disable_exporter`, `docket exporters`, `cli-interface.spec.md` §"docket exporters"): the
  minimal-write property, the non-TTY refusal, and the audit entries each of `enable`/
  `disable`/`add`/`remove` writes.

This specification does NOT cover, and each is planned for a later card that will extend this
document rather than replace it:

- `exporters:` as a `pod.yaml` key (P32-8).
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
    open for that session, named for the record's `event_type`, carrying one `docket.<key>`
    attribute for each of that event type's *declared* structural payload keys present with a
    scalar (`str`/`int`/`bool`) value (`_STRUCTURAL_KEYS`; see "Allowlist projection" below) —
    an undeclared key **MUST NOT** be forwarded, and an event type's own content key (e.g.
    `approval_requested`'s `action`, `error`'s `error`) **MUST** instead be gated through the
    allowlist, never forwarded unconditionally.
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
16. `admit` **MUST NOT** alter, reduce, or truncate the record's payload for any event type —
    filtering by `events` is its only effect. Content reduction, when it happens, is applied
    later, by `project`'s allowlist (see "Allowlist projection" below), never by `admit`.
17. Because `admit` performs no reduction, `ExportPolicy` carries no `payload`/
    `payload_max_chars` field (retired). What a policy shares beyond bare structure is instead
    named by `classes` (a set of content classes) and shown by `label` (see "Privacy classes
    and levels" below).
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
    `core.trace.EVENT_TYPES` members), `enabled` (default `False`), and `note`. `payload`/
    `payloadMaxChars` are retired (see "Exporter privacy fields" below).
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

### Pipeline

44. `Pipeline.offer(record)` **MUST** run `policy.admit` and `project` on the calling thread and
    enqueue every span the call closes; it **MUST NOT** block the caller and **MUST NOT** raise
    for any reason, including a raising `policy` or a corrupt `record`.
45. A `Pipeline` whose queue is full **MUST** drop the offered item and increment that pipeline's
    `dropped` counter rather than block `offer` or raise.
46. One background thread per `Pipeline` **MUST** drain the queue in batches -- up to
    `batch_max` items, or `batch_wait_s` since the first item of a forming batch, whichever comes
    first -- and call `sink.emit` on each batch.
47. After a `sink.emit` call, `accepted` (clamped to `[0, len(batch)]`) **MUST** be added to
    `exported`; any remainder **MUST** be added to `failed`; a non-empty `error` **MUST** set
    `last_error`/`last_error_at`; at least one accepted span with no error **MUST** set `last_ok`.
    A `sink.emit` that raises **MUST** be treated as a full-batch failure (`failed += len(batch)`,
    `last_error` set to the exception text) -- `Pipeline` never trusts a sink's never-raise
    contract, it enforces the outcome regardless.
48. `Pipeline.flush(timeout_s)` **MUST** force-close every span still open in its projection
    state, enqueue it, and then wait **at most** `timeout_s` for the drain thread to have sent
    everything queued as of that call -- a slow or hung `sink.emit` **MUST NOT** make `flush`
    wait longer than `timeout_s`, whether or not the send has actually finished by then.
49. `Pipeline.close()` **MUST** flush, stop the drain thread, and release the sink; it **MUST** be
    safe to call on a `Pipeline` that has already sent everything, and **MUST NOT** raise.

### The module-level registry and wiring

50. `load_enabled_exporters()` **MUST** return every catalog entry (`core.exporter.load_catalog`)
    with `enabled: true`; it performs no credential resolution -- that is `start`'s job.
51. `start(specs, sink_for)` **MUST** build one `Pipeline` for every entry in `specs` that is
    both enabled and has every `auth.credentials` name resolved (`core.exporter.
    resolve_credentials`), and **MUST** subscribe exactly one fan-out callable for all of them
    through `core.trace.add_subscriber` -- never one subscriber per exporter.
52. `start` **MUST** return `0` and register nothing -- no `Pipeline`, no subscriber -- under
    `DOCKET_NO_EXPORT=1`, when no entry in `specs` is both enabled and fully credentialed, or
    when the registry already has a pipeline registered from an earlier call in this process.
    A later call in the same process, before `close()`, **MUST** therefore be a no-op.
53. `flush(timeout_s)` **MUST** flush every registered `Pipeline`, each bounded to at most
    `timeout_s`; `close()` **MUST** flush and stop every registered `Pipeline` and unsubscribe
    the fan-out callable, and **MUST** be a safe no-op when nothing was ever started.
54. `health()` **MUST** return one entry per registered `Pipeline`, in `config.
    EXPORTERS_HEALTH_FILE`'s documented shape (requirement 32); it performs no I/O itself --
    writing the file is the caller's job.
55. `edges/adapters/docket_runtime.py::run_turn` **MUST** call `telemetry.start(telemetry.
    load_enabled_exporters(), exporters.sink_for)` before running the turn, and **MUST**, in a
    `finally` block covering every return path of `run_turn` (including an early return before
    the turn itself starts), call `telemetry.flush(config.EXPORT_FLUSH_TIMEOUT_S)` and then write
    `telemetry.health()` to `config.EXPORTERS_HEALTH_FILE` through `edges/store.py`.
56. With zero enabled exporters, `run_turn` **MUST** start no background thread and register no
    trace subscriber -- `start`'s cost in that case is one catalog read and nothing else.
57. `edges/adapters/exporters/__init__.py::sink_for(spec, values)` **MUST** dispatch on
    `spec.dialect` and build the wire sink with an auth header pair derived from `spec.auth.type`
    and *values* (already resolved by the caller): `bearer` -> `("Authorization", "Bearer
    <values[0]>")`, `basic` -> `("Authorization", "Basic <base64 of values[0]:values[1]>")`,
    `header` -> `(spec.auth.header, values[0])`, `none` -> `None`. An unrecognized `dialect`
    **MUST** raise `ValueError`.

### Activation (CLI)

58. `core.exporter.enable_exporter(name, overrides)` **MUST** refuse a *name* absent from the
    catalog (built-in or global), and on success **MUST** write only `{kind, name, enabled:
    true, <overrides>}` to the global catalog file — never the full inherited document — so the
    rest of the entry keeps resolving from the built-in of the same name at read time
    (Requirement 25).
59. `disable_exporter(name)` **MUST** flip only `enabled` to `false` in the global catalog,
    leaving any other stored override (e.g. a prior `endpoint` override) untouched, and **MUST
    NOT** remove or alter any credential in the secret store.
60. `docket exporters enable <name>` **MUST NOT** activate an exporter whose declared
    credentials do not all resolve (Requirement 29): on a TTY it prompts for and stores each
    missing one; on a non-TTY it **MUST** exit non-zero naming `docket keys add <NAME>` for
    every missing credential and **MUST NOT** write the global catalog file at all.
61. `docket exporters enable`/`add` **MUST** probe the (possibly `--endpoint`-overridden)
    endpoint and classify it exactly as Requirement 31 describes before writing anything; a
    `reachable=False` classification **MUST** exit non-zero and **MUST NOT** write the global
    catalog file, unless the operator passed `--no-verify`.
62. Enabling, disabling, adding, or removing an exporter **MUST** append one audit entry —
    `exporter.enabled` / `exporter.disabled` / `exporter.added` / `exporter.removed` — whose
    detail names the exporter and, for `enabled`/`added`, its `privacy` label and `endpoint`
    (requirement 87); **MUST NOT** ever include a credential value.
63. `docket exporters test <name>` **MUST** probe and classify *name*'s endpoint the same way
    `enable` does, and **MUST NOT** write the global catalog file, the health file, or an audit
    entry — it is read-only.

### Privacy classes and levels

64. `core.privacy.CONTENT_CLASSES` **MUST** be the six-tuple `("toolArguments", "errors",
    "toolResults", "completions", "prompts", "instructions")`, and `LEVELS` **MUST** map
    `"minimal"` to the empty set and `"actions"`/`"conversation"`/`"full"` to strictly
    increasing supersets, `"full"` equalling every member of `CONTENT_CLASSES` (ADR 0015 §1).
65. `core.privacy.resolve(privacy, share)` **MUST** raise `ValueError` when both arguments are
    given, when `privacy` names a level absent from `LEVELS`, or when `share` contains a class
    absent from `CONTENT_CLASSES`; **MUST** return `("minimal", frozenset())` when neither
    argument is given; and **MUST** return the name of the `LEVELS` entry a given `share` set
    equals, or `"custom"` when it equals none of them.
66. `core.privacy.describe(classes)` **MUST** return one `(class, granted, attribute_names)`
    tuple per member of `CONTENT_CLASSES`, in that order, with `granted` `True` exactly for the
    members of *classes*, for a CLI's "what leaves this host" listing.

### Allowlist projection

67. `ExportPolicy` **MUST** carry `classes: frozenset[str]` (default empty) and `label: str`
    (default `"minimal"`) in place of the retired `payload`/`payload_max_chars` fields, plus
    `content_max_chars: int` (default `4000`); `project(record, state, policy=MINIMAL_POLICY)`
    **MUST** thread *policy* to the handler it dispatches to.
68. `core.telemetry.ATTRIBUTE_CLASSES` **MUST** map every attribute name a handler can set that
    is not bare structure to exactly one of `core.privacy.CONTENT_CLASSES`'s members; an
    attribute absent from this table **MUST** be treated as structure and **MUST** always be
    forwarded regardless of `policy.classes` (`gen_ai.input.messages` is deliberately absent —
    requirement 75 governs it per message part instead of as one whole-attribute class).
69. A content attribute (any attribute named in `ATTRIBUTE_CLASSES`, and each individually
    filtered message part inside `gen_ai.input.messages`) **MUST** be set only when its class is
    a member of `policy.classes`, decided through exactly one function, `_granted(policy, cls)`
    — nothing else in `core/telemetry.py` **MUST** check `policy.classes` directly — and
    **MUST** be entirely absent (or, for a message part, replaced by the withheld marker of
    requirement 75) otherwise.
70. `_handle_generic_event` **MUST** forward only the payload keys declared for that event
    type's structure (`_STRUCTURAL_KEYS`), never every scalar payload key as before; an event
    type absent from that table **MUST** forward no keys at all.
71. `approval_requested`'s `action` payload key **MUST** be exposed as the
    `docket.approval.action` attribute, class `toolArguments`, gated by requirement 69 — never
    forwarded as an unconditional `docket.action` attribute the way requirement 11's prior form
    forwarded it.
72. `error`'s `error` payload key **MUST** be exposed as the `docket.error.message` attribute,
    class `errors`, gated by requirement 69 — never forwarded as an unconditional `docket.error`
    attribute.
73. `tool_call`'s `arguments` payload key **MUST** be exposed as the
    `gen_ai.tool.call.arguments` attribute, class `toolArguments`, gated by requirement 69.
74. `tool_result`'s `text` payload key, or `output` when `text` is absent, **MUST** be exposed
    as the `gen_ai.tool.call.result` attribute, class `toolResults`, gated by requirement 69.
75. An `llm_call` record's `inputMessages` payload key, when present, **MUST** become the
    `gen_ai.input.messages` attribute: one `{"role", "parts"}` object per message, each part
    kept (its `content` truncated per requirement 78) when its own class is granted, or replaced
    by `{"type": "withheld", "class": "<class>"}` otherwise. A `system`-role message's parts
    **MUST** be class `instructions`; a `tool`-role message's parts **MUST** be class
    `toolResults`; an `assistant`-role message's `tool_call`-type parts **MUST** be class
    `toolArguments`; every other part **MUST** be class `prompts`. When no part is kept, the
    attribute **MUST** be absent, never a list of withheld markers.
76. An `llm_call` record's `outputMessages` payload key **MUST** become the
    `gen_ai.output.messages` attribute, class `completions`, as a whole (never split per part,
    since it is one class end to end — ADR 0015 §1) — present in full (parts' `content`
    truncated per requirement 78) when granted, absent entirely otherwise.
77. An `llm_call` record's `systemInstructions` payload key **MUST** become the
    `gen_ai.system_instructions` attribute, class `instructions`, gated by requirement 69; its
    `systemInstructionsSha256` key, when present, **MUST** always become the structural
    `docket.instructions.sha256` attribute regardless of `policy.classes`.
78. Every text value placed in a content attribute or message part (a part's `content`,
    `arguments` and `response`) **MUST** be cut to
    `policy.content_max_chars` characters with the suffix `…[truncated <n> chars]` (*n* the
    number of characters removed) when it exceeds that length, and **MUST** remain a valid
    string once re-encoded as JSON.
79. Every root `docket.session` span **MUST** carry `docket.privacy` (the policy's `label`) and
    `docket.privacy.classes` (its `classes`, comma-joined in sorted order, the empty string for
    `minimal`).

### Exporter privacy fields

80. `core.exporter.ExporterSpec` **MUST** carry `privacy` (`Literal["minimal", "actions",
    "conversation", "full"] | None`, default `None`), `share` (`list[str] | None`, default
    `None`), and `contentMaxChars` (alias for `content_max_chars: int`, default `4000`, `gt=0`,
    `le=100_000`) in place of the retired `payload`/`payloadMaxChars`.
81. A document setting both `privacy` and `share` **MUST** be refused, naming both fields; a
    `share` entry absent from `core.privacy.CONTENT_CLASSES` **MUST** be refused naming it —
    both resolved through `core.privacy.resolve(spec.privacy, spec.share)`. A `privacy` value
    outside `core.privacy.LEVELS` **MUST** be refused naming the field and the valid values,
    through the field's own closed `Literal` vocabulary (the same refinement
    `_validation_to_exporter_error` already gives an unknown `dialect`/`auth.type`).
82. `ExporterSpec.privacy_label` **MUST** return the resolved level name (`core.privacy.resolve`
    applied to `(spec.privacy, spec.share)`) — `"minimal"` when neither field is set.
83. `ExporterSpec.privacy_classes` **MUST** return the resolved `frozenset[str]` of granted
    content classes for the same input — the empty set when neither field is set.
84. A document that still carries the retired `payload` and/or `payloadMaxChars` keys **MUST**
    load successfully: those keys **MUST NOT** reach `privacy`/`share`/`content_max_chars` or
    widen `privacy_label` past `"minimal"`, and each such key present on the document **MUST**
    be named, in the order encountered, in `ExporterSpec.legacy_fields` (ADR 0015 rule 7).
    `legacy_fields` **MUST NOT** be written back out by `save_exporter`/`export_exporter`.
85. Every built-in exporter document under `templates/exporters/` **MUST** declare `privacy:
    minimal` (or omit `privacy`/`share` entirely) — including `otel-collector`, whose prior
    `payload: full` is retired, since a collector forwards to whatever its own config names.
86. `core.telemetry.start` **MUST** build each started `Pipeline`'s `ExportPolicy` from its
    exporter document's own resolved fields: `classes=spec.privacy_classes`,
    `label=spec.privacy_label`, `content_max_chars=spec.content_max_chars` — no exporter shares
    beyond `structure` until its own document says so.
87. `enable_exporter`/`disable_exporter`'s audit detail, and the CLI's `exporters add` audit
    detail, **MUST** name `privacy=<privacy_label>` in place of the retired `payload=<payload>`.

### Privacy commands and disclosure

88. `core.exporter.set_privacy(name, privacy=None, share=None, content_max_chars=None)` **MUST**
    refuse a *name* absent from the catalog and **MUST** refuse an invalid `privacy`/`share`
    value the same way `core.privacy.resolve` does. On success it **MUST** write only the
    changed key(s) into the global override — the same minimal-patch mould
    `enable_exporter` uses — and setting `privacy` **MUST** clear a stored `share` to `null`
    (and vice versa) so the two stay mutually exclusive on disk. Called with all three
    arguments `None`, it **MUST** make no change and write nothing.
89. `core.exporter.is_widening(old, new)` **MUST** return `True` exactly when `new` (a
    `frozenset[str]` of content classes) contains a class absent from `old`, and `False` for an
    equal or narrower set.
90. `docket exporters privacy <name>` given no level, no `--share` and no `--max-chars`
    **MUST** print the same "Leaves this host" disclosure `docket exporters show <name>` prints
    (one line per `core.privacy.describe` class, granted or not, its example attributes, and
    the fixed line naming that credentials and secret-shaped values are never sent) and
    **MUST NOT** write anything.
91. `docket exporters privacy <name> <level>` or `--share a,b` **MUST** resolve the requested
    classes through `core.privacy.resolve` and compare them, via `core.exporter.is_widening`,
    against the exporter's presently effective classes (`spec.privacy_classes`) before writing.
92. A widening call **MUST** print each newly granted class (present in the requested classes,
    absent from the current ones) with one example attribute and the destination host (the
    endpoint's hostname, never the full URL, path or any content), then, on a TTY
    (`sys.stdin.isatty()`), ask `y/N`; anything but `y` **MUST** refuse and write nothing. Off a
    TTY, a widening call **MUST** exit `1` naming `--yes`, ask nothing, and write nothing.
    `--yes` **MUST** skip the confirmation and write directly.
93. A narrowing or equal call (`is_widening` `False`) **MUST NOT** ask for confirmation, on or
    off a TTY, and **MUST** write directly.
94. Every successful `set_privacy` call **MUST** append one `exporter.privacy` audit entry
    naming `name`, `from` (the previous label), `to` (the new label) and `host` (the endpoint's
    hostname) — never content.
95. `docket exporters enable <name> --privacy <level>|--share a,b` **MUST** apply the same
    widening/confirmation rule (requirements 91–94) before writing, comparing against the
    exporter's classes before enabling. The retired `--payload metadata|full` flag **MUST NOT**
    be accepted by `enable` — a document setting `privacy`/`share` is the only way to widen what
    an exporter shares.
96. `docket exporters add <file.yaml>` whose resolved document shares beyond `minimal`
    **MUST** apply the same widening/confirmation rule, comparing against the classes of any
    existing catalog entry of the same name, or the empty set when there is none.
97. `docket exporters list` **MUST** gain a `SHARES` column (the exporter's `privacy_label`);
    `docket exporters enable` **MUST** always print `shares: <label> (<classes, comma-joined,
    or "structure only">)` in place of the retired payload warning; `docket config explain`
    **MUST** print the privacy label per exporter and its `--json` form's `exporters` entries
    **MUST** carry `privacy: {label, classes}` in place of a bare label string; `docket doctor`
    **MUST** add one informational line (not counted as an issue) per enabled exporter at
    `conversation`/`full` sharing to a non-loopback host, and one per exporter still carrying a
    legacy `payload`/`payloadMaxChars` field, naming `docket exporters privacy <name> <level>`.

### Preview

98. `docket exporters preview <name> [--session <id>] [--level <level>|--share a,b] [--json]`
    **MUST** resolve *name* through `core.exporter.load_catalog()`, build an `ExportPolicy` from
    that exporter document's own resolved `privacy`/`share`/`events`/`content_max_chars` fields
    the same way `core.telemetry.start` builds one for a started `Pipeline` — or, when `--level`
    or `--share` is given, from `core.privacy.resolve` applied to the override instead — and
    project the named local session (default: the newest `*.jsonl` under `config.TRACES_DIR` by
    mtime, across every project) through it with `core.telemetry.project`/`flush_open`. An
    override **MUST NOT** be written to the exporter's document.
99. `preview` **MUST NOT** open a socket, write any docket-owned file, or append an audit entry;
    a call with `--session <id>` naming an unknown session **MUST** exit `1` naming the session
    and touch nothing.
100. Without `--json`, `preview` **MUST** print, per projected span, its name and every
     attribute (including each span event's own attributes) with the content class that
     attribute belongs to (`core.telemetry.ATTRIBUTE_CLASSES`, `"structure"` for an attribute
     absent from that table, and `"per part"` for `gen_ai.input.messages`, which is deliberately
     absent from `ATTRIBUTE_CLASSES` because its class varies by message part), with content
     truncated to 200 characters for display; a footer **MUST** count spans, attributes per
     class, and the total byte size of the OTLP document the same projection would encode.
101. `preview --json` **MUST** print the exact document `edges.adapters.exporters.otlp_http.encode`
     produces for the same spans, resource, and aliases — byte-identical to what an enabled
     exporter's `Pipeline` would send for this session under the same policy.
102. When the effective policy grants `prompts`, `completions`, or `instructions`, and no
     `llm_call` record in the previewed session carries a truthy `inputMessages`,
     `outputMessages`, or `systemInstructions` payload key, `preview` **MUST** print one line
     stating plainly that the session recorded no conversation content and that content is
     captured only once an exporter grants it, so a later session would also send it — a session
     recorded under `minimal` never carries that content, whatever level it is later previewed
     at (ADR 0015 §2 rule 4).

## Interface Contracts

### Module API (`docket.core.privacy`)

```python
CONTENT_CLASSES: tuple[str, ...]   # ("toolArguments", "errors", "toolResults", "completions",
                                    #  "prompts", "instructions")
LEVELS: dict[str, frozenset[str]]  # "minimal" | "actions" | "conversation" | "full"

def resolve(privacy: str | None, share: Sequence[str] | None) -> tuple[str, frozenset[str]]: ...
def describe(classes: frozenset[str]) -> list[tuple[str, bool, tuple[str, ...]]]: ...
```

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

@dataclass(frozen=True)
class ExportPolicy:
    events: frozenset[str] | None = None   # None = admit every event type
    classes: frozenset[str] = frozenset()  # granted content classes beyond bare structure
    label: str = "minimal"                 # a privacy level name, or "custom"
    content_max_chars: int = 4000

    def admit(self, record: dict[str, Any]) -> dict[str, Any] | None: ...

MINIMAL_POLICY: ExportPolicy   # ExportPolicy() -- project's default when no policy is given

def project(
    record: dict[str, Any], state: ProjectionState, policy: ExportPolicy = MINIMAL_POLICY
) -> list[Span]: ...
def flush_open(state: ProjectionState) -> list[Span]: ...

DEFAULT_EVENTS: frozenset[str]

ATTRIBUTE_CLASSES: dict[str, str]     # non-structural attribute name -> its content class
def capture_classes() -> frozenset[str]: ...  # union of every started pipeline's granted classes

class SinkOutcome(Protocol):        # structural match to otlp_http.SinkResult's field names
    accepted: int
    status: int | None
    error: str
    retry_after_s: float | None

class SpanSink(Protocol):
    def emit(self, spans: Sequence[Span]) -> SinkOutcome: ...
    def close(self) -> None: ...

@dataclass
class PipelineStats:
    exported: int = 0
    dropped: int = 0
    failed: int = 0
    last_ok: str = ""
    last_error: str = ""
    last_error_at: str = ""

class Pipeline:
    def __init__(
        self, sink: SpanSink, policy: ExportPolicy, *,
        queue_max: int, batch_max: int = 100, batch_wait_s: float = 1.0,
        clock: Callable[[], float],
    ) -> None: ...
    def offer(self, record: dict[str, Any]) -> None: ...
    def flush(self, timeout_s: float) -> None: ...
    def close(self) -> None: ...
    def stats(self) -> PipelineStats: ...

SinkFactory = Callable[[Any, list[str]], SpanSink]   # (ExporterSpec, resolved credential values)

def load_enabled_exporters() -> list[Any]: ...        # list[ExporterSpec], enabled entries only
def start(specs: Sequence[Any], sink_for: SinkFactory) -> int: ...
def flush(timeout_s: float) -> None: ...
def close() -> None: ...
def health() -> dict[str, dict[str, Any]]: ...        # config.EXPORTERS_HEALTH_FILE's shape
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
    privacy: Literal["minimal", "actions", "conversation", "full"] | None = None
    share: list[str] | None = None
    content_max_chars: int = 4000                # alias "contentMaxChars"
    enabled: bool = False
    note: str = ""
    legacy_fields: list[str] = []                # e.g. ["payload"]; never re-serialized

    @property
    def privacy_label(self) -> str: ...           # core.privacy.resolve(privacy, share)[0]
    @property
    def privacy_classes(self) -> frozenset[str]: ...  # core.privacy.resolve(privacy, share)[1]

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
def enable_exporter(name: str, overrides: dict[str, Any] | None = None) -> ExporterSpec: ...
def disable_exporter(name: str) -> ExporterSpec: ...   # both raise ExporterError

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

### Module API (`docket.edges.adapters.exporters`)

```python
def sink_for(spec: ExporterSpec, values: list[str]) -> telemetry.SpanSink: ...
    # dispatches on spec.dialect via _DIALECTS; raises ValueError for an unknown one
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

### Sharing beyond structure, deliberately

```python
from docket.core import privacy, telemetry

label, classes = privacy.resolve("actions", None)   # ("actions", {"toolArguments", "errors"})
policy = telemetry.ExportPolicy(events=telemetry.DEFAULT_EVENTS, classes=classes, label=label)
admitted = policy.admit(record)          # filtered by event type only, payload untouched
if admitted is not None:
    spans = telemetry.project(admitted, state, policy)
    # a granted class's content attribute is present; every other content attribute is absent
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

### Enabling a destination once its credentials are stored

```python
from docket.core import exporter

spec = exporter.load_catalog().get("langfuse")
# ... both credentials are already in the secret store; probe + verify_endpoint
# already classified the endpoint as reachable ...
enabled = exporter.enable_exporter("langfuse", {"endpoint": "https://collector.example/traces"})
enabled.enabled            # True
# docket-exporters.json now holds exactly {kind, name, enabled: true, endpoint: ...} --
# aliases, resource, and every other field still resolve from the built-in.
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

### Starting the pipeline for a turn

```python
from docket.core import telemetry
from docket.edges.adapters import exporters

started = telemetry.start(telemetry.load_enabled_exporters(), exporters.sink_for)
# started == 0 with every exporter disabled (the shipped default) -- no thread, no subscriber
...
telemetry.flush(config.EXPORT_FLUSH_TIMEOUT_S)      # bounded even if a sink hangs
health = telemetry.health()                         # {} when started == 0
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

- `core/telemetry.py` **MUST NOT** import anything from `edges/`, print, or write to disk;
  `Pipeline` **MUST NOT** open a socket itself -- it drains into a `SpanSink` object it is
  handed, and never constructs one (that is `edges/adapters/exporters`'s job).
- `Pipeline.offer`, `Pipeline.flush`, and `Pipeline.close`, and the module-level `start`,
  `flush`, and `close`, **MUST NOT** raise for any reason -- a raising `policy`, a corrupt
  record, a raising `sink.emit`, or a full queue are all handled outcomes, never exceptions
  that reach the caller (`edges/adapters/docket_runtime.py::run_turn`, which itself promises
  never to raise for an ordinary failure).
- A `Pipeline.flush(timeout_s)` call **MUST** return within `timeout_s` of its own wall-clock
  budget regardless of how long the underlying `sink.emit` takes -- a hung or slow destination
  **MUST NOT** make a turn's `run_turn` call take meaningfully longer than
  `config.EXPORT_FLUSH_TIMEOUT_S` on top of the turn's own time.
- Redaction of secret shapes happens once, in `core.trace.trace_event`, before a record is
  written; this module never re-redacts, and the allowlist only ever narrows what a policy's
  ungranted classes already withhold, never widens it.
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

## External verification

Live proof, captured on the development machine on 2026-09-28 (P32-9). Not requirements —
recorded evidence that Requirements 1-63 hold against a real dispatch and a real destination,
distinct from the committed fixture-driven unit tests above.

### OpenTelemetry Collector, `otlp-http`, `auth: none`

An `otel/opentelemetry-collector` container (image digest
`sha256:b6d2b9a85b1029d05b5ad913150c1f014eed4ae99be81a1813ca5ade4a191913`) ran locally with the
`debug` exporter on its `traces` pipeline, receiving OTLP/HTTP on `4318`.

```text
$ docket exporters enable otel-collector
✓ Exporter enabled: otel-collector  ->  http://127.0.0.1:4318/v1/traces
  scope: global  payload: full
⚠ tool arguments and results leave this host
```

A real `docket pod rack-cli dispatch` (a freshly provisioned `software` pod, full roster) ran
one task through all four hops -- Lead, Implementer, Reviewer, Tester -- against the local
llama.cpp endpoint (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`), and completed: `done -- 4 hop(s)`.

- The collector's own log recorded 5 `docket.session` root spans, 29 `gen_ai.chat` spans
  carrying real measured token counts (e.g. `gen_ai.usage.input_tokens: Int(2467)`,
  `gen_ai.usage.output_tokens: Int(63)`), and 39 `execute_tool` spans (`read`, `grep`, `glob`).
- `docket trace <session>` showed the matching 29 `llm_call` lines for the same session, with
  the same token counts, confirming the projected spans and the underlying trace agree.
- `docket exporters show otel-collector` reported `health exported=71 dropped=0 failed=0` --
  Requirement 28's health file is a non-zero, never-failed counter under real traffic.

This exercises the `auth: none` path (Requirements 24-27) end to end: catalog resolution,
`verify_endpoint` classification on enable (Requirement 31), the pipeline (Requirements 44-49),
and the module-level wiring into `run_turn` (Requirements 50-57).

### Langfuse, `otlp-http`, `auth: basic` -- live round-trip verified 2026-09-28

`docket exporters enable langfuse` was first run on this machine with no credential stored, and
correctly refused -- the real, reproducible non-TTY path Requirement 60 describes:

```text
$ docket exporters enable langfuse
✗ Error: Exporter 'langfuse' needs credentials that are not set:
  docket keys add LANGFUSE_PUBLIC_KEY
  docket keys add LANGFUSE_SECRET_KEY
```

The same refusal was reproduced for `honeycomb` (`auth: header`), confirming Requirement 60
across both non-`none` auth kinds.

The operator then stored both keys (`docket keys add LANGFUSE_PUBLIC_KEY` /
`LANGFUSE_SECRET_KEY`) and `enable` succeeded, probing the real endpoint with the real
credential:

```text
$ docket exporters enable langfuse
✓ Exporter enabled: langfuse  ->  https://cloud.langfuse.com/api/public/otel/v1/traces
  scope: global  payload: metadata
```

A second real `docket pod rack-cli dispatch` (4 hops, local model, 10 `llm_call` events) ran with
both `otel-collector` and `langfuse` enabled at once. `docket exporters show langfuse` afterward
reported `health exported=27 dropped=0 failed=0`: every one of the 27 spans this dispatch
produced (session roots, `gen_ai.chat`, `execute_tool`) got a 2xx response from Langfuse's real
cloud endpoint, under the real basic-auth credential -- `OtlpHttpSink.emit`'s `accepted` count
(Interface Contracts, `docket.edges.adapters.exporters.otlp_http`) only increments on
`200 <= status < 300`, so a non-zero `exported`/zero `failed` pair is not self-reported success,
it is the endpoint's own answer. The same dispatch's 27 spans also landed on the local
`otel-collector`, confirming both destinations receive the identical batch. This machine has no
browser access to Langfuse's own dashboard, so the generations' on-screen appearance is the one
detail only the operator can confirm directly; the HTTP-level delivery result above -- a 2xx
response for every span, from Langfuse's own server -- is what this specification records.

The operator then did view the dashboard directly and confirmed the trace, its
`docket.session` root, and its `gen_ai.chat` spans render there with real timing and token
counts -- and flagged that the `gen_ai.chat` generation's Input/Output fields read `null`/
`undefined`. Traced to the code: this is not a delivery or encoding defect. Requirement 8 closes
the `gen_ai.chat` attribute set to `gen_ai.system`/`gen_ai.request.model`/
`gen_ai.usage.input_tokens`/`gen_ai.usage.output_tokens`/`gen_ai.response.finish_reasons`/
`docket.iteration`, and Requirement 9 closes `execute_tool <name>` to
`gen_ai.tool.name`/`gen_ai.tool.call.id`/`docket.tool.ok`/`docket.tool.blocked_by` -- neither
list has ever included prompt, message, or tool argument/output content, at either `payload`
setting, because `_trace_llm_call` (`core/agent_loop.py`) never records message content in the
`llm_call` event to begin with (model, provider, `ok`, `finishReason`, token counts, latency
only). `ExportPolicy`'s `metadata`/`full` reduction (Requirements 15-17) is real and correctly
implemented, but has no observable effect on these two span kinds, since `project`'s handlers
for `llm_call`/`tool_call`/`tool_result` never read a content-bearing payload key into a `Span`
attribute regardless of what `admit` left in the record. This was accurately specified
(Requirements 8-9 never promised content) but under-documented: `docs/CONFIGURATION.md` §3.14,
`docs/SECURITY-SIMPLE.md`'s Layer 6, and this ADR's own §"Policy before the queue" previously
implied `full` would surface prompt/tool content for these spans; corrected 2026-09-28 to state
plainly that a destination's Input/Output will read empty for `gen_ai.chat`/`execute_tool`
regardless of `payload`, and that wiring real content through would be new, deliberately-scoped
work (a privacy decision, not a bug fix) -- not undertaken here.

### Recorded discrepancy: the fixture-replacement instruction

P32-9's own card text asked for `tests/fixtures/traces/dispatch-3-hops.jsonl` to be replaced
with this real capture. The fixture is not a loose example: `test_one_root_session_span`,
`test_two_llm_call_children_carry_measured_tokens` (which asserts the token set is exactly
`{120, 180}`), `test_guardrail_block_is_a_span_event_on_root`, and the golden byte-match against
`tests/fixtures/otlp-v1/dispatch-3-hops.json` are all pinned to its specific, deliberately
small, deterministic values -- including a `guardrail_block` event a real dispatch does not
reliably produce. Overwriting it with a 145-line real capture would either break those
committed assertions or require rewriting them to match arbitrary real numbers, trading a
readable, deterministic regression fixture for a volatile one, for no gain: the real capture's
event *shapes* (the same `event_type`/`payload` keys the fixture already models, confirmed
above) are what a live run can actually add over the fixture, and this section records that
instead. The fixture and its golden are unchanged.

### Privacy levels -- live, 2026-09-28

One real `docket harness run` turn per level against the local llama.cpp endpoint, each in a
fresh `DOCKET_HOME` with `otel-collector` (local container, `debug` exporter, `detailed`) and
`langfuse` (the operator's project) both enabled at that level by `docket exporters enable
<name> --privacy <level> --yes`. The task carried a unique `CANARY-TASK-<level>-<hex>` and the
file the agent was told to read held a unique `CANARY-FILE-<level>-<hex>`. After each turn,
`docket exporters preview langfuse` and `--json`, the collector's log since the turn began, and
the trace read back through Langfuse's public API (`/api/public/traces/<id>`) were searched for
both canaries. Every run: `result: ok`, `exported=4 dropped=0 failed=0` on both exporters.

| Level | Collector | Langfuse | `preview --json` | Local trace |
|---|---|---|---|---|
| `minimal` | 0 / 0 | 0 / 0; every observation's Input/Output empty | 0 / 0 | no file canary (nothing captured) |
| `actions` | 0 / 0; `gen_ai.tool.call.arguments: {"path": "notes.txt"}` present | 0 / 0; the `read` TOOL has input, generations empty | 0 / 0 | — |
| `conversation` | task and file canaries present, incl. `gen_ai.tool.call.result` | both present; both GENERATIONs have Input and Output, the `read` TOOL has input and output | both present | — |

(task canary / file canary; "present" = found at least once.) Both destinations carried
`docket.privacy`/`docket.privacy.classes` on the session root. `preview` matched what arrived:
the same canaries in every case.

**Found by this run and fixed before recording it:** the first `conversation` run showed
Langfuse's `read` TOOL with no output. `_handle_tool_result` reads a `text` key the live loop's
`_trace_tool_result` never wrote (P33-1's canary suite used synthetic records that had one),
so `toolResults` on a tool span was machinery with no live producer. `tool_result` now records
its output on demand (`trace-store.spec.md` requirement 27) and the wire seam test
(`tests/integration/test_otlp_export.py::TestCapturedContentReachesTheWire`) asserts it; the
`conversation` and `minimal` runs in the table are the re-runs on the fixed code.

**Found, not fixed (Phase 32 behaviour, outside this phase):** a session whose model call pauses
long enough for the pipeline's idle flush (`Pipeline._drain` calling `flush_open`) closes its
`docket.session` root early; the next record re-creates the root with the same span id, so the
destination receives two `docket.session` spans for one session (Langfuse lists both). It does
not affect what content is shared.

## Changelog

### Version 1.9.0 (2026-09-28)

- **Phase 33 closes; privacy levels verified live.** Status rewritten: the known limit recorded
  in 1.5.1 (Input/Output empty at any setting) is gone. "External verification" gains "Privacy
  levels": one real turn per level into the local collector and Langfuse, canaries in the task
  and in a file, none at `minimal`, arguments only at `actions`, the conversation and tool
  results at `conversation`; the run found and fixed `tool_result` never recording its output,
  and recorded the idle-flush duplicate root span as a Phase 32 follow-up.

### Version 1.8.0 (2026-09-28)

- **Privacy commands and disclosure (P33-4), preview (P33-5).** New section "Privacy commands
  and disclosure" (requirements 88-97): `set_privacy`/`is_widening`, `docket exporters privacy`,
  widening confirmed on a TTY or refused off one without `--yes`, narrowing never asks, the
  `exporter.privacy` audit entry (name, from, to, host), `enable --privacy|--share`, the retired
  `--payload` flag, the `SHARES` column, the "Leaves this host" block, `config explain` and
  `doctor` lines. New section "Preview" (requirements 98-102): `docket exporters preview`
  projects a local session through the exporter's policy with no socket, write or audit;
  `--json` is the exact wire document; a session with no captured conversation content says so
  when the previewed level would share it.

### Version 1.7.0 (2026-09-28)

- **Exporter privacy fields (P33-2) and the capture seam.** New section "Exporter privacy
  fields" (requirements 80-87): an exporter document declares `privacy` or `share` and
  `contentMaxChars`; `payload`/`payloadMaxChars` are retired and load as `minimal`, named in
  `legacy_fields`; every built-in is `minimal`; `core.telemetry.start` builds each pipeline's
  policy from its document. Requirement 78 now names the three part fields it bounds: the
  first real capture put tool results in `response` and tool-call arguments in `arguments`,
  which the projection had not cut to the exporter's own bound (fixed, with a test that runs a
  real turn onto the real wire).

### Version 1.6.0 (2026-09-28)

- **Privacy classes and the allowlist projection (Phase 33, P33-1).** New sections "Privacy
  classes and levels" (requirements 64-66) and "Allowlist projection" (67-79); requirements 11,
  16 and 17 amended: `ExportPolicy.admit` filters by event type only, and content reaches a span
  only through `ATTRIBUTE_CLASSES` and a granted class. Closes two leaks under the old default:
  `approval_requested.action` and `error.error` no longer forward as `docket.*` attributes; they
  are `docket.approval.action` (toolArguments) and `docket.error.message` (errors). Every root
  span carries `docket.privacy`/`docket.privacy.classes`. Requirement 75 also says an input
  message list with no kept part is omitted, never exported as withheld markers. Interim: every
  started exporter projects at `minimal` until the exporter document's fields are wired.

### Version 1.5.1 (2026-09-28)

- **Langfuse round-trip visually confirmed; a known content limit found and documented.** The
  operator supplied real `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, `docket exporters enable
  langfuse` succeeded, and a real dispatch's trace, `docket.session` root and `gen_ai.chat` spans
  rendered in Langfuse's own dashboard with real timing and token counts, closing the one item
  1.5.0 left open. Flagged live: the generation's Input/Output fields read `null`/`undefined`.
  Traced to Requirements 8-9's closed `gen_ai.chat`/`execute_tool` attribute sets and
  `core/agent_loop.py::_trace_llm_call`, which never records message content -- not a delivery
  or encoding defect, but `docs/CONFIGURATION.md` §3.14, `docs/SECURITY-SIMPLE.md`'s Layer 6, and
  ADR 0014 previously implied `payload: full` would surface it for these two span kinds; all
  three corrected. New "content in gen_ai.chat/execute_tool spans" paragraph in "External
  verification" records the finding; wiring real content through remains unscoped, deliberate
  future work.

### Version 1.5.0 (2026-09-28)

- **External verification (P32-9), close.** New "External verification" section: a real
  `docket pod` dispatch against a Docker `otel/opentelemetry-collector` proved the `auth: none`
  path end to end (real `gen_ai.chat` token counts, `execute_tool` spans, a matching `docket
  trace` view, a non-zero `exported` health counter); the `auth: header` and `auth: basic` paths
  were proved through their real, reproducible non-TTY credential refusal. A live Langfuse
  round-trip stays open, named as blocked on the operator's own keys rather than skipped
  silently. Status moves to "Implemented and live" -- every requirement in this specification,
  including `pod.yaml`'s `exporters:` key (P32-8, already live), now has external evidence
  behind it. Recorded, not applied: P32-9's own instruction to replace
  `tests/fixtures/traces/dispatch-3-hops.jsonl` with the real capture conflicts with that
  fixture's own committed, deterministic assertions (see "External verification"); the fixture
  and its golden are unchanged, and the real capture's evidence lives in this section instead.

### Version 1.4.0 (2026-09-27)

- Added the "Activation (CLI)" requirements (58-63) and `core.exporter.enable_exporter`/
  `disable_exporter`: turning an exporter on writes only `{kind, name, enabled: true,
  <overrides>}` to the global catalog, never the full inherited document; turning one off flips
  only `enabled`. `docket exporters enable` refuses on a non-TTY with a missing credential,
  naming `docket keys add <NAME>` per name and writing nothing; it verifies the endpoint the
  same way Requirement 31 classifies a probe before writing anything. Enabling, disabling,
  adding, and removing each append one audit entry naming the exporter (never a credential
  value). `docket exporters test` probes and classifies without writing anything. See
  `cli-interface.spec.md` 1.54.0 and `cli-json-shapes.spec.md` 1.15.0 for the command surface
  and JSON shapes this section's requirements back. Written in the same wave as, and merged
  after, the pipeline wiring added at 1.3.0.

### Version 1.3.0 (2026-09-27)

- **The pipeline, wired where turns run (P32-6).** New "Pipeline" and "The module-level registry
  and wiring" Requirements sections (44-57): `core.telemetry.Pipeline` (a bounded queue plus one
  daemon drain thread per enabled exporter, batching, drop-on-full, never-raise), `PipelineStats`
  (the exact per-name shape `config.EXPORTERS_HEALTH_FILE` holds), and the module-level
  `load_enabled_exporters`/`start`/`flush`/`close`/`health` registry, which subscribes one
  fan-out sink through the new `core.trace.add_subscriber` (see `trace-store.spec.md`).
  `edges/adapters/exporters/__init__.py::sink_for` builds a `SpanSink` from a resolved
  `ExporterSpec` and its already-resolved credential values, dispatching on `dialect`.
  `edges/adapters/docket_runtime.py::run_turn` starts the pipeline lazily (a no-op after the
  first successful start, and with zero enabled exporters), and flushes it plus writes
  `config.EXPORTERS_HEALTH_FILE` in a `finally` covering every return path -- see
  `agent-loop.spec.md` 1.26.0 for the `DocketDriver` conformance requirement this adds. Status
  moves to "Implemented -- awaiting external verification (P32-9)": every card through this one
  is live; only the CLI surface (P32-7) and `pod.yaml`'s `exporters:` key (P32-8) remain, plus a
  real collector/Langfuse round-trip (P32-9).

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
