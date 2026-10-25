# Observability Export Specification

**Version**: 2.4.0
**Status**: Implemented and live. Trace records project into vendor-neutral spans and are sent,
off the turn's thread, to every enabled `kind: exporter` destination over the one `otlp-http`
dialect; what a destination receives beyond structure is set by its own privacy level.
**Last Updated**: 2026-10-25

## Purpose

Docket's per-session JSONL trace (`trace-store.spec.md`) is a closed, docket-specific
vocabulary. This specification defines the neutral, vendor-agnostic layer built on top of it: a
deterministic projection of trace records into spans and span events, the policy that decides
which records a destination admits and which content classes it may see, the `kind: exporter`
destination catalog, the one wire dialect that sends spans off the host, and the bounded
background pipeline that connects them to a live turn. Wire formats and vendor knowledge stay in
the wire dialect; the trace store stays the single source of truth.

## Scope

This specification covers:

- The `Span`/`SpanEvent` model: fields, deterministic id derivation, and attribute values
  restricted to `str | int | bool`.
- `ProjectionState` and the incremental `project`, `flush_turn` and `flush_open` functions: which
  trace record types open a span, which close one, which become a span event on which span, and
  the fallback for a record type with no explicit case.
- `ExportPolicy` and `admit`: event-type admission only, never payload reduction.
- The privacy content classes and levels, and the allowlist projection (`ATTRIBUTE_CLASSES`, the
  per-event structural keys, per-message-part filtering, `capture_classes`) that decides what a
  granted class shares (ADR 0015).
- The `kind: exporter` document (`ExporterSpec`/`ExporterAuth`): field shape, credential-name
  validation, the four authentication types, and the privacy fields.
- The built-in + global exporter catalog and the five built-in documents shipped with docket.
- Activation classification (`activation_state`), endpoint-probe classification
  (`verify_endpoint`), and the shape of the health file `exporters-health.json`.
- The `otlp-http` dialect: the OTLP JSON encoding of a `Span`/`SpanEvent`, `OtlpHttpSink`'s
  transport and retry behaviour, and `probe`'s reachability check.
- The bounded queue and background sender (`Pipeline`) and the module-level
  `start`/`flush`/`close`/`health` registry, and `sink_for`, which builds a `SpanSink` from a
  resolved `ExporterSpec` and its already-resolved credential values.
- How `DocketDriver.run_turn` wires the pipeline into a live turn, and the process-exit hook that
  closes it.
- The `docket setup export` commands' behaviour: activation, the non-TTY refusals, the widening
  confirmation, the audit entries, and the offline `preview`. The command syntax is
  `cli-interface.spec.md` §"setup export".

This specification does NOT cover:

- The trace record shape, `EVENT_TYPES`, the `add_subscriber` seam the pipeline registers
  through, `task_id` on a record, and the capture of conversation content into the trace
  (`trace-store.spec.md`). This layer reads every record field defensively.
- The `pod.yaml` `exporters:` key, which a recipe declares and `apply` reports but never applies
  (`config-format.spec.md`).

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
5. Timestamps on a `Span` **MUST** remain ISO-8601 strings; no numeric time unit (nanoseconds,
   epoch seconds) is introduced at this layer.

### Projection

6. `project(record, state)` **MUST** be a pure, incremental fold: given one trace record and
   the running `ProjectionState`, it **MUST** return exactly the spans this record closes, and
   **MUST NOT** re-emit a span already returned by an earlier call.
7. A `session_start` record **MUST** open one root span named `docket.session`, with
   `docket.project`, `docket.role`, `docket.session_id`, and `session.id` attributes (plus the
   privacy attributes of requirement 79), and **MUST NOT** itself return a closed span. Any
   other handled record for a session with no open root **MUST** open that root first, from the
   same record's fields.
8. An `llm_call` record **MUST** produce one complete child span named `gen_ai.chat`, parented
   to the session root, with `start_ts` computed as the record's `ts` minus its `duration_ms`,
   and attributes `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
   `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`, and `docket.iteration`. Its
   `status` **MUST** be `"error"` when the payload's `ok` field is `false`, and `"ok"`
   otherwise. Its `span_id` key is fixed by requirement 103.
9. A `tool_call` record **MUST** open a span named `execute_tool <tool>` (`execute_tool` when
   the payload names no tool), with attributes `gen_ai.tool.name` and `gen_ai.tool.call.id`; the
   matching `tool_result` record (same `callId`) **MUST** close it with status `"unset"`, adding
   `docket.tool.ok` when the payload carries `ok` and, when the payload names a blocking policy
   (`policyId`), `docket.tool.blocked_by`. A `tool_result` whose `callId` matches no open span
   **MUST** become a span of its own, keyed by that `callId`. A record without a `callId` is
   keyed and paired per requirement 108.
10. `hop_retry`, `rework_started`, `verdict_rework_started`, `verdict_rejected`,
    `verdict_unparseable`, `verdict_reasked`, `route_taken`, `command_step`, `review_rejected`,
    `tester_verdict_failed`, and `verification_failed` **MUST** become a `SpanEvent` on the
    session root (never on a nested span), named for the record's `event_type`, carrying
    `docket.hop`/`docket.task_id` only when the record supplies them.
11. Every other `EVENT_TYPES` record type (the `escalation_*` family aside, requirements 110-115) **MUST** become a `SpanEvent` on the innermost span
    still open for that session, named for the record's `event_type`, carrying one
    `docket.<key>` attribute for each of that event type's *declared* structural payload keys
    present with a scalar (`str`/`int`/`bool`) value (requirement 70). An undeclared key
    **MUST NOT** be forwarded, and an event type's own content key (`approval_requested`'s
    `action`, `error`'s `error`) **MUST** instead be gated through the allowlist, never forwarded
    unconditionally.
12. A `session_end` record **MUST** close the root span and every span still open for that
    session, each with `status: "unset"`, and **MUST** remove that session's state so nothing
    further is emitted for it. An escalation span (requirement 110) is not a span of the session:
    it stays open across `session_end` and `flush_turn`, and only `flush_open` closes it (requirement 13).
13. `flush_open(state)` **MUST** close every span still open across every session `state` still
    holds, at that session's last-seen timestamp, and **MUST** clear `state` for each session it
    closes. It also closes every open escalation span, at the last timestamp seen for the session
    that asked it (its `start_ts` when that session has ended), with status `"unset"`; the
    settlement that follows sends the span whole under the same `span_id`, so a destination that
    upserts ends with the real wait.
14. A record whose `event_type` this layer does not recognise **MUST** be ignored: it
    **MUST NOT** raise, and **MUST NOT** mutate `state`.

### Export policy

15. `ExportPolicy.admit(record)` **MUST** return `None` when `events` is not `None` and the
    record's `event_type` is not a member of it, and **MUST NOT** mutate the input record.
16. `admit` **MUST NOT** alter, reduce, or truncate the record's payload for any event type:
    filtering by `events` is its only effect. Content reduction happens in `project`'s
    allowlist (requirements 67-79), never in `admit`.
17. What a policy shares beyond bare structure **MUST** be named by `classes` (a set of content
    classes) and shown by `label` (requirements 64-67); `ExportPolicy` carries no field that
    reduces a payload.
18. `DEFAULT_EVENTS` **MUST** exclude any record type whose payload is expected to carry
    prompt or message content by construction (`context_composed`, `prompt_composed`,
    `session_compaction`, `request_fit`), **MUST** exclude `cost_charged` (an estimate is never
    exported as a measurement), and **MUST** exclude `run_cancellation_observed`/`step_skipped`
    (no destination has asked for either).

### Exporter documents

19. A `kind: exporter` document **MUST** validate through `ExporterSpec` (`populate_by_name`),
    carrying `kind` (`Literal["exporter"]`), `name` (`^[a-z0-9][a-z0-9-]*$`), `dialect`
    (`Literal["otlp-http"]`, default `"otlp-http"`), `endpoint` (an `http://`/`https://` URL),
    `auth`, `headers`, `resource` (default `{"service.name": "docket"}`), `aliases`, `events`
    (`"default"` | `"all"` | a list of `EVENT_TYPES` members), the privacy fields of
    requirement 80, `enabled` (default `False`), and `note`.
20. `auth.type` **MUST** be one of `bearer`, `header`, `basic`, `none`, and **MUST** require
    exactly the credential-name arity that type implies: zero for `none`, exactly one for
    `bearer` and `header`, exactly two (ordered: username, then password) for `basic`.
    `auth.header` **MUST** be present when `auth.type` is `"header"`.
21. Every name in `auth.credentials` **MUST** match `^[A-Z][A-Z0-9_]*$`. A value that instead
    looks like a credential *value* (matches `^[A-Za-z0-9/_\-+.]{20,}$`) **MUST** be refused
    naming `auth.credentials`: a document never carries a secret, only the name of one already
    in the store.
22. `headers` **MUST** refuse the reserved names `authorization`, `content-type`, `accept`
    (docket sends these itself), the same rule a `kind: provider` document's `headers` follows.
23. A malformed document (unknown `kind`, missing `name`, an unknown `dialect`/`auth.type`, or
    any requirement 20-22 failure) **MUST** raise `ExporterError` naming the file, field, and
    message, with the same shape as `ProviderError` (`file`, `field`, `message`, `valid`).

### Catalog and scopes

24. The exporter catalog **MUST** have two scopes, nearest-wins by name: built-in (the five
    documents shipped with docket: `otel-collector`, `jaeger`, `langfuse`, `honeycomb`,
    `phoenix`) and global (`docket-exporters.json` under `DOCKET_HOME`, `$EXPORTERS_FILE`, the
    operator's own, written only through the docket-owned JSON store). `Catalog.get(name)`/
    `source_of(name)` **MUST** report which scope resolved a name. A global entry that does not
    validate is left out of the catalog, so the built-in of that name, if any, resolves instead.
25. A global entry sharing a built-in's name **MUST** inherit every field it does not itself
    set from that built-in, so an override is typically a one- or two-field tweak (`endpoint`,
    `enabled`), never a from-scratch redeclaration.
26. `delete_exporter(name)` **MUST** refuse (naming the built-in scope) when *name* is a
    built-in with no global override, and **MUST** refuse naming "not in the exporter catalog"
    when *name* is not in the catalog at all; otherwise it removes the global entry.
27. `export_exporter(name)` **MUST** render the resolved catalog entry as a `kind: exporter`
    YAML document and **MUST NOT** ever include a credential value: `ExporterSpec` holds only
    credential names.

### Activation state

28. `activation_state(spec, health)` **MUST NOT** write anything or perform any I/O other than
    credential resolution (requirement 29), and **MUST** return `"disabled"` whenever
    `spec.enabled` is `False`, checked before anything else: a present credential **MUST NOT**,
    by itself, activate an exporter.
29. When enabled, `activation_state` **MUST** return `("needs credential", [<missing names>])`
    naming every `auth.credentials` entry that resolves to no value (through
    `resolve_credentials`, which tries an environment variable of the same name first, then the
    secret store).
30. When enabled and every credential resolves, `activation_state` **MUST** return
    `"unreachable"` when *health*'s `lastErrorAt` is present and newer than its `lastOk` (or
    `lastOk` is absent), and `"enabled"` otherwise.
31. `verify_endpoint(spec, probe)` **MUST** classify a `ProbeResult` the same way a provider
    endpoint probe is classified (`model-profiles.spec.md`): `probe.status is None` is the
    only `reachable=False` outcome; a 2xx status carries no warning; `401`/`403` names the
    credential as rejected or missing; any other status names the HTTP status. Like
    `activation_state`, its only I/O is credential resolution.

### Health file

32. `exporters-health.json` under `DOCKET_HOME` (`$EXPORTERS_HEALTH_FILE`) **MUST** hold a
    mapping of exporter name to `{"exported": int, "dropped": int, "failed": int, "lastOk":
    <timestamp>, "lastError": <string>, "lastErrorAt": <timestamp>}`. It is written by the turn
    driver (requirement 55) and the process-exit hook (requirement 109); `read_health()`
    **MUST** read it through the docket-owned JSON store and **MUST NOT** write it.

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
    `bearer`/`basic`/custom-header credential is resolved by the caller; the dialect reads no
    credential name) plus any static headers, and **MUST** return a `SinkResult` naming how many
    spans were accepted (all of them on a 2xx response, none otherwise). An empty batch **MUST**
    send nothing and report `accepted=0, status=None`.
40. `emit` **MUST** retry the POST exactly once, and only for an HTTP 429/502/503/504 response,
    sleeping `min(Retry-After, $DISPATCH_RETRY_MAX_WAIT_S)` seconds before the retry (1 second
    when the response names no integer-seconds `Retry-After`, or names `0`); any other non-2xx
    response, and a second retryable response, **MUST** report `accepted=0` without a further
    retry.
41. `emit` **MUST NOT** raise for a transport failure (refused connection, timeout, DNS
    failure); such a failure **MUST** report `SinkResult(accepted=0, status=None,
    error=<non-empty>)`.
42. `emit` and `probe` **MUST** accept their clock, sleep, and HTTP opener as parameters with
    real defaults (`time.monotonic`, `time.sleep`, and `open_same_origin`, an opener that follows
    a redirect only within the request's own origin), so a test can replace all three without a
    real socket or a real wait.
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
    `last_error` set to the exception text): `Pipeline` enforces the outcome whatever the sink
    promises.
48. `Pipeline.flush(timeout_s)` **MUST** close and enqueue every open span the turn owns, keeping
    each session root and hop span open (requirement 106), then wait **at most** `timeout_s` for
    the drain thread to have sent everything queued as of that call: a slow or hung `sink.emit`
    **MUST NOT** make `flush` wait longer than `timeout_s`, whether or not the send has finished
    by then. `Pipeline.flush(timeout_s, final=True)` **MUST** instead close every open span,
    roots included (`flush_open`).
49. `Pipeline.close()` **MUST** flush with `final=True`, stop the drain thread, and release the
    sink, each step bounded by `$EXPORT_FLUSH_TIMEOUT_S`; it **MUST** be safe to call on a
    `Pipeline` that has already sent everything, and **MUST NOT** raise.

### The module-level registry and wiring

50. `load_enabled_exporters()` **MUST** return every catalog entry (`load_catalog`) with
    `enabled: true`; it performs no credential resolution -- that is `start`'s job.
51. `start(specs, sink_for)` **MUST** build one `Pipeline` for every entry in `specs` that is
    both enabled and has every `auth.credentials` name resolved (`resolve_credentials`), and
    **MUST** subscribe exactly one fan-out callable for all of them through `add_subscriber`
    (`trace-store.spec.md`) -- never one subscriber per exporter.
52. `start` **MUST** return `0` and register nothing -- no `Pipeline`, no subscriber -- under
    `DOCKET_NO_EXPORT=1`, when no entry in `specs` is both enabled and fully credentialed, or
    when the registry already has a pipeline registered from an earlier call in this process.
    A later call in the same process, before `close()`, **MUST** therefore be a no-op.
53. `flush(timeout_s)` **MUST** flush every registered `Pipeline` (requirement 48), each bounded
    to at most `timeout_s`; `close()` **MUST** close every registered `Pipeline` (requirement
    49) and unsubscribe the fan-out callable, and **MUST** be a safe no-op when nothing was ever
    started.
54. `health()` **MUST** return one entry per registered `Pipeline`, in `exporters-health.json`'s
    shape (requirement 32); it performs no I/O itself -- writing the file is the caller's job.
55. `DocketDriver.run_turn` **MUST** call `start(load_enabled_exporters(), sink_for)` before
    running the turn, and **MUST**, in a `finally` block covering every return path of
    `run_turn` (including an early return before the turn itself starts), call
    `flush($EXPORT_FLUSH_TIMEOUT_S)` and then write `health()` to `exporters-health.json`
    through the docket-owned JSON store.
56. With zero enabled exporters, `run_turn` **MUST** start no background thread and register no
    trace subscriber -- `start`'s cost in that case is one catalog read and nothing else.
57. `sink_for(spec, values)` **MUST** dispatch on `spec.dialect` and build the wire sink with an
    auth header pair derived from `spec.auth.type` and *values* (already resolved by the
    caller): `bearer` -> `("Authorization", "Bearer <values[0]>")`, `basic` ->
    `("Authorization", "Basic <base64 of values[0]:values[1]>")`, `header` ->
    `(spec.auth.header, values[0])`, `none` -> `None`. An unrecognized `dialect` **MUST** raise
    `ValueError`.

### Activation (CLI)

58. `enable_exporter(name, overrides)` **MUST** refuse a *name* absent from the catalog
    (built-in or global), and on success **MUST** write only `{kind, name, enabled: true,
    <overrides>}` into that name's global entry, merged over whatever that entry already
    stores, never the full inherited document, so the rest of the entry keeps resolving from
    the built-in of the same name at read time (requirement 25). An override of `privacy` **MUST**
    also store `share` as `null`, and an override of `share` **MUST** also store `privacy` as
    `null`, so the entry never holds both. Before it writes, `enable_exporter` **MUST** check that
    the merged entry is a valid exporter document, and **MUST** raise `InvalidInput`, writing no
    file and no audit entry, when it is not (for instance when *overrides* names both `privacy`
    and `share`).
59. `disable_exporter(name)` **MUST** flip only `enabled` to `false` in the global catalog,
    leaving any other stored override (e.g. a prior `endpoint` override) untouched, and **MUST
    NOT** remove or alter any credential in the secret store.
60. `docket setup export enable <name>` **MUST NOT** activate an exporter whose declared
    credentials do not all resolve (requirement 29): on a TTY it prompts for and stores each
    missing one; on a non-TTY it **MUST** exit non-zero naming every missing credential and
    **MUST NOT** write the global catalog file at all.
61. `docket setup export enable`/`add` **MUST** probe the endpoint (after any `--endpoint`
    override) and classify it exactly as requirement 31 describes before writing anything; a
    `reachable=False` classification **MUST** exit non-zero and **MUST NOT** write the global
    catalog file, unless the operator passed `--no-verify`. `enable`'s `--endpoint` and
    `--events` overrides are written as part of requirement 58's patch.
62. Enabling, disabling, adding, or removing an exporter **MUST** append one audit entry --
    `exporter.enabled` / `exporter.disabled` / `exporter.added` / `exporter.removed` -- whose
    detail names the exporter and, for `enabled`/`disabled`/`added`, its `privacy` label and
    `endpoint` (requirement 87); the detail **MUST NOT** ever include a credential value.
63. `docket setup export test <name>` **MUST** probe and classify *name*'s endpoint the same way
    `enable` does, exiting non-zero when the endpoint is unreachable or the classification
    carries a warning, and **MUST NOT** write the global catalog file, the health file, or an
    audit entry.

### Privacy classes and levels

64. `CONTENT_CLASSES` **MUST** be the six-tuple `("toolArguments", "errors", "toolResults",
    "completions", "prompts", "instructions")`, and `LEVELS` **MUST** map `"minimal"` to the
    empty set and `"actions"`/`"conversation"`/`"full"` to strictly increasing supersets,
    `"full"` equalling every member of `CONTENT_CLASSES` (ADR 0015 §1).
65. The privacy `resolve(privacy, share)` **MUST** raise `ValueError` when both arguments are
    given, when `privacy` names a level absent from `LEVELS`, or when `share` contains a class
    absent from `CONTENT_CLASSES`; **MUST** return `("minimal", frozenset())` when neither
    argument is given; and **MUST** return the name of the `LEVELS` entry a given `share` set
    equals, or `"custom"` when it equals none of them.
66. `describe(classes)` **MUST** return one `(class, granted, attribute_names)` tuple per member
    of `CONTENT_CLASSES`, in that order, with `granted` `True` exactly for the members of
    *classes*, for a CLI's "what leaves this host" listing.

### Allowlist projection

67. `ExportPolicy` **MUST** carry `classes: frozenset[str]` (default empty), `label: str`
    (default `"minimal"`) and `content_max_chars: int` (default `4000`);
    `project(record, state, policy=MINIMAL_POLICY)` **MUST** apply *policy* to the record it
    projects.
68. `ATTRIBUTE_CLASSES` **MUST** map every attribute name the projection can set that is not
    bare structure to exactly one of `CONTENT_CLASSES`'s members; an attribute absent from this
    table **MUST** be treated as structure and **MUST** always be forwarded regardless of
    `policy.classes` (`gen_ai.input.messages` is deliberately absent: requirement 75 governs it
    per message part instead of as one whole-attribute class).
69. A content attribute (any attribute named in `ATTRIBUTE_CLASSES`, and each individually
    filtered message part inside `gen_ai.input.messages`) **MUST** be set only when its class is
    a member of `policy.classes`, decided by one grant check that every content attribute goes
    through (nothing else in the projection decides a grant from `policy.classes`), and
    **MUST** be entirely absent (or, for a message part, replaced by the withheld marker of
    requirement 75) otherwise.
70. A generic event (requirement 11) **MUST** forward only the payload keys declared as
    structure for its event type; an event type with no declared keys **MUST** forward no keys
    at all.
71. `approval_requested`'s `action` payload key **MUST** be exposed as the
    `docket.approval.action` attribute, class `toolArguments`, gated by requirement 69, and
    **MUST NOT** also be forwarded as a structural `docket.action` attribute.
72. `error`'s `error` payload key **MUST** be exposed as the `docket.error.message` attribute,
    class `errors`, gated by requirement 69, and **MUST NOT** also be forwarded as a structural
    `docket.error` attribute.
73. `tool_call`'s `arguments` payload key **MUST** be exposed as the
    `gen_ai.tool.call.arguments` attribute, class `toolArguments`, gated by requirement 69.
74. `tool_result`'s `text` payload key, or `output` when `text` is absent, **MUST** be exposed
    as the `gen_ai.tool.call.result` attribute, class `toolResults`, gated by requirement 69.
75. An `llm_call` record's `inputMessages` payload key, when present, **MUST** become the
    `gen_ai.input.messages` attribute: one `{"role", "parts"}` object per message, each part
    kept (its text fields truncated per requirement 78) when its own class is granted, or
    replaced by `{"type": "withheld", "class": "<class>"}` otherwise. A `system`-role message's
    parts **MUST** be class `instructions`; a `tool`-role message's parts **MUST** be class
    `toolResults`; an `assistant`-role message's `tool_call`-type parts **MUST** be class
    `toolArguments`; every other part **MUST** be class `prompts`. When no part is kept, the
    attribute **MUST** be absent, never a list of withheld markers.
76. An `llm_call` record's `outputMessages` payload key **MUST** become the
    `gen_ai.output.messages` attribute, class `completions`, as a whole (never split per part,
    since it is one class end to end, ADR 0015 §1): present in full (parts' text fields
    truncated per requirement 78) when granted, absent entirely otherwise.
77. An `llm_call` record's `systemInstructions` payload key **MUST** become the
    `gen_ai.system_instructions` attribute, class `instructions`, gated by requirement 69 (a
    string is truncated per requirement 78; a list of parts is sent as JSON with each part's
    text fields truncated); its `systemInstructionsSha256` key, when present, **MUST** always
    become the structural `docket.instructions.sha256` attribute regardless of `policy.classes`.
78. Every text value placed in a content attribute or message part (for a part: its `content`,
    `arguments` and `response`) **MUST** be cut to `policy.content_max_chars` characters with
    the suffix `…[truncated <n> chars]` (*n* the number of characters removed) when it exceeds
    that length, and **MUST** remain a valid string once re-encoded as JSON.
79. Every root `docket.session` span **MUST** carry `docket.privacy` (the policy's `label`) and
    `docket.privacy.classes` (its `classes`, comma-joined in sorted order, the empty string for
    `minimal`).

### Escalation spans

An escalation is one pause for a decision from outside the task (`operator-loop.spec.md` "Escalations");
its trace events share one payload (`operator-loop.spec.md` "Escalation events"), and the span is the
wait: its duration is the time between the ask and the settlement.

110. An `escalation_asked` record **MUST** open one span named `docket.escalation` and return no
     closed span. Its `span_id` is derived from `(session_id, "escalation", <escalation id>)`,
     its `start_ts` is the payload's `askedAt` (the record's `ts` when absent), and its parent is
     the innermost open hop span of the record's session, else that session's root. The open span
     is held by escalation id, outside every session's stack, so it survives the session's end
     and the turn's flush (requirement 12).
111. An `escalation_resolved`, `escalation_expired` or `escalation_decided` record **MUST** close
     that escalation's span with `end_ts` the record's `ts`, and `status` `"ok"` for resolved and
     decided, `"error"` for expired. A settling record whose escalation has no open span (a
     restart between ask and settlement, or a pod-decided consult, which is never asked) **MUST**
     still return the complete span, built from its payload: `start_ts` is `askedAt`, the parent
     is the session root. The projection **MUST NOT** open a session root for it.
112. An `escalation_delivered` record **MUST** become a `SpanEvent` named `escalation_delivered`,
     carrying `docket.escalation.channel`, on that escalation's open span; with no open span it
     is a generic event (requirement 11) on the innermost open span of its session.
113. The `docket.escalation` span **MUST** carry the structural attributes
     `docket.escalation.id`, `.kind`, `.policy`, `.task`, `.step` and `.outcome` (`resolved`,
     `expired` or `decided`, set when it closes), plus `.by` (`person`, `policy` or `timeout`) and
     `.channel` and `.level` whenever the payload that closes it, or the one that opened it,
     carries them. Every `escalation_*` payload of a record that has a level carries `level`
     (`L3`, `L4` or `L5`, operator-loop.spec.md "Escalations" item 12).
114. The escalation's `prompt` payload key **MUST** be exposed as `docket.escalation.prompt`, class
     `prompts`, gated by requirement 69; at `minimal`, `actions` and any `share` list without
     `prompts` the attribute **MUST** be absent. The ids and labels of the options and the
     recommendation are not exported.
115. `DEFAULT_EVENTS` **MUST** include the five `escalation_*` event types.

### Exporter privacy fields

80. `ExporterSpec` **MUST** carry `privacy` (`Literal["minimal", "actions", "conversation",
    "full"] | None`, default `None`), `share` (`list[str] | None`, default `None`), and
    `contentMaxChars` (alias for `content_max_chars: int`, default `4000`, `gt=0`,
    `le=100_000`).
81. A document setting both `privacy` and `share` **MUST** be refused, naming both fields; a
    `share` entry absent from `CONTENT_CLASSES` **MUST** be refused naming it -- both resolved
    through the privacy `resolve(spec.privacy, spec.share)`. A `privacy` value outside `LEVELS`
    **MUST** be refused naming the field and the valid values, through the field's own closed
    `Literal` vocabulary (the same refinement an unknown `dialect`/`auth.type` gets).
82. `ExporterSpec.privacy_label` **MUST** return the resolved level name (`resolve` applied to
    `(spec.privacy, spec.share)`): `"minimal"` when neither field is set.
83. `ExporterSpec.privacy_classes` **MUST** return the resolved `frozenset[str]` of granted
    content classes for the same input: the empty set when neither field is set.
84. A document carrying a key `ExporterSpec` does not declare (for example `payload` or
    `payloadMaxChars`) **MUST** load successfully with that key ignored: it **MUST NOT** reach
    `privacy`/`share`/`content_max_chars` or widen `privacy_label` past `"minimal"` (ADR 0015
    rule 7), and it is not written back out by `save_exporter`/`export_exporter`. Nothing
    records or reports that it was present.
85. Every built-in exporter document **MUST** declare `privacy: minimal` (or omit
    `privacy`/`share` entirely), including `otel-collector`, since a collector forwards to
    whatever its own config names.
86. `start` **MUST** build each started `Pipeline`'s `ExportPolicy` from its exporter document's
    own resolved fields: `events` (`"default"` -> `DEFAULT_EVENTS`, `"all"` -> `None`, a list ->
    exactly those types), `classes=spec.privacy_classes`, `label=spec.privacy_label`,
    `content_max_chars=spec.content_max_chars`; no exporter shares beyond structure until its
    own document says so.
87. The audit detail of `enable_exporter`, `disable_exporter` and `docket setup export add`
    **MUST** name `privacy=<privacy_label>`.

### Privacy commands and disclosure

88. `set_privacy(name, privacy=None, share=None, content_max_chars=None)` **MUST** refuse a
    *name* absent from the catalog and **MUST** refuse an invalid `privacy`/`share` value the
    same way the privacy `resolve` does. On success it **MUST** write only the changed key(s)
    into the global override, the same minimal patch `enable_exporter` writes, and setting
    `privacy` **MUST** clear a stored `share` to `null` (and vice versa) so the two stay
    mutually exclusive on disk. Before it writes, `set_privacy` **MUST** check that the merged entry
    is a valid exporter document, and **MUST** raise `InvalidInput`, writing no file and no
    audit entry, when it is not (a `content_max_chars` of 0 or below, or above 100,000, for
    instance). Called with all three arguments `None`, it **MUST** make no change and write
    nothing.
89. `is_widening(old, new)` **MUST** return `True` exactly when `new` (a `frozenset[str]` of
    content classes) contains a class absent from `old`, and `False` for an equal or narrower
    set.
90. `docket setup export privacy <name>` given no level, no `--share` and no `--max-chars`
    **MUST** print the same "Leaves this host" disclosure `docket setup export show <name>`
    prints (one line per `describe` class, granted or not, its example attributes, and the fixed
    line naming that credentials and secret-shaped values are never sent) and **MUST NOT** write
    anything.
91. `docket setup export privacy <name> <level>` or `--share a,b` **MUST** resolve the requested
    classes through the privacy `resolve` and compare them, via `is_widening`, against the
    exporter's presently effective classes (`spec.privacy_classes`) before writing.
92. A widening call **MUST** print each newly granted class (present in the requested classes,
    absent from the current ones) with one example attribute and the destination host (the
    endpoint's hostname, never the full URL, path or any content), then, on a TTY
    (`sys.stdin.isatty()`), ask `[y/N]`; anything but `y`/`yes` **MUST** refuse and write
    nothing. Off a TTY, a widening call **MUST** exit `1` naming `--yes`, ask nothing, and write
    nothing. `--yes` **MUST** skip the confirmation and write directly.
93. A narrowing or equal call (`is_widening` `False`) **MUST NOT** ask for confirmation, on or
    off a TTY, and **MUST** write directly.
94. Every `set_privacy` call that writes **MUST** append one `exporter.privacy` audit entry
    naming `name`, `from` (the previous label), `to` (the new label) and `host` (the endpoint's
    hostname), never content.
95. `docket setup export enable <name> --privacy <level>|--share a,b` **MUST** apply the same
    widening confirmation (requirements 92-93), comparing against the exporter's classes before
    enabling, before it probes or writes.
96. `docket setup export add <file.yaml>` whose resolved document shares beyond `minimal`
    **MUST** apply the same widening confirmation, comparing against the classes of any existing
    catalog entry of the same name, or the empty set when there is none.
97. `docket setup export list` **MUST** carry a `SHARES` column (the exporter's
    `privacy_label`); `docket setup export enable` **MUST** always print `shares: <label>
    (<classes, comma-joined, or "structure only">)`; `docket pod show` **MUST** print the
    privacy label per exporter and its `--json` form's `exporters` entries **MUST** carry
    `privacy: {label, classes}`; `docket setup` **MUST** warn (counted as an issue, naming
    `docket setup export test <name>`) for an enabled exporter whose health records failures,
    and **MUST** add one informational line (not counted as an issue) per enabled exporter at
    `conversation`/`full` sharing to a non-loopback host.

### Preview

98. `docket setup export preview <name> [--session <id>] [--level <level>|--share a,b] [--json]`
    **MUST** resolve *name* through `load_catalog()`, build an `ExportPolicy` from that exporter
    document's own resolved `privacy`/`share`/`events`/`content_max_chars` fields the same way
    `start` builds one for a started `Pipeline` (or, when `--level` or `--share` is given, from
    the privacy `resolve` applied to the override instead), and project the named local session
    (default: the newest `*.jsonl` under `$TRACES_DIR` by mtime, across every project) through
    it with `project`/`flush_open`. An override **MUST NOT** be written to the exporter's
    document.
99. `preview` **MUST NOT** open a socket, write any docket-owned file, or append an audit entry;
    a call with `--session <id>` naming an unknown session **MUST** exit `1` naming the session
    and touch nothing.
100. Without `--json`, `preview` **MUST** print, per projected span, its name and every
     attribute (including each span event's own attributes) with the content class that
     attribute belongs to (`ATTRIBUTE_CLASSES`, `"structure"` for an attribute absent from that
     table, and `"per part"` for `gen_ai.input.messages`), with each value cut to 200 characters
     for display (suffix `…[+<n> chars]`); a footer **MUST** count spans, attributes per class,
     and the total byte size of the OTLP document the same projection would encode.
101. `preview --json` **MUST** print the document `encode` produces for the projected spans with
     the exporter's own `resource` and `aliases`: the encoding an enabled exporter's sink applies
     to the same spans under the same policy, as one document rather than in batches.
102. Without `--json`, when the effective policy grants `prompts`, `completions`, or
     `instructions`, and no `llm_call` record in the previewed session carries a truthy
     `inputMessages`, `outputMessages`, or `systemInstructions` payload key, `preview` **MUST**
     print one line stating that the session recorded no conversation content and that content
     is captured only once an exporter grants it, so a later session would also send it: a
     session recorded under `minimal` never carries that content, whatever level it is later
     previewed at (ADR 0015 §2 rule 4).

### One session across hops

A pod dispatch runs every hop under one trace key, so one session holds several agent turns,
each restarting its iteration count at 1, and `DocketDriver.run_turn` flushes the pipeline at
the end of each of them. These requirements keep that session one complete trace.

103. An `llm_call` span's `span_id` key (requirement 4) **MUST** be `<role>|<purpose>|<iteration>|
     <ts>` -- the record's `agent_role`, its payload `purpose` (`task` when absent), its
     `iteration`, and its own `ts` -- so two hops, or two runs of one role, in one session never
     share a span id, while a replayed record still derives the same one.
104. When `prompts` is granted, the session root **MUST** carry `docket.session.input`: the first
     `text` part of the first `user`-role message in the first `llm_call` whose
     `inputMessages` has one, set once and never replaced, truncated per requirement 78. It is
     class `prompts` in `ATTRIBUTE_CLASSES` and absent otherwise.
105. When `completions` is granted, the session root **MUST** carry `docket.session.output`: the
     last `text` part of the most recent `llm_call` whose `outputMessages` has one, replaced by
     each later such call, truncated per requirement 78. It is class `completions` in
     `ATTRIBUTE_CLASSES` and absent otherwise.
106. `flush_turn` (the non-final `Pipeline.flush`) **MUST** close and return every open span the
     turn owns, and keep each open session root, and each open hop span (requirement 108), open
     in its state, unsent, with its original `start_ts`, attributes and events: both wrap the
     turn that flushes. A session's root **MUST** be sent exactly once: when a `session_end`
     record closes it, or when `Pipeline.close` closes every span still open (`flush_open`),
     because Langfuse keeps a trace's Input and Output from the first root observation it
     receives. Pod dispatch writes `session_end` when a task's run ends; a library caller that
     never does gets its root at process exit (requirement 109).
107. The built-in `langfuse` document **MUST** alias `docket.session.input` to
     `langfuse.observation.input` and `docket.session.output` to `langfuse.observation.output`,
     so Langfuse derives the trace's Input and Output from the root observation.
108. A `tool_call` record without a `callId` -- the marker pod dispatch writes when a hop starts
     (payload `hop`/`agent`) -- **MUST** key its span (requirement 4) as `<role>|<ts>`. A
     `tool_result` without a `callId` (the hop's reply, `text`) **MUST** close the most recent
     open span of the same role that has no `callId`; one with no such span open (the
     implementer's verification result) **MUST** become its own span keyed
     `<role>|<ts>|result`. So each hop is one span, from its start to its reply, and each
     verification is its own, in a destination that upserts by span id, and a replayed record
     still derives the same id.
109. `close()` **MUST** return the closed pipelines' final counters in `health()`'s shape (`{}`
     when nothing was started), and `DocketDriver`'s process-exit hook (registered with `atexit`
     when the driver is imported) **MUST** write a non-empty result to `exporters-health.json`
     through the docket-owned JSON store, so the delivery of the spans the final flush sends
     (the session root, per requirement 106) is recorded like any other.

## Interface Contracts

### Privacy classes and levels

```python
CONTENT_CLASSES: tuple[str, ...]   # ("toolArguments", "errors", "toolResults", "completions",
                                    #  "prompts", "instructions")
LEVELS: dict[str, frozenset[str]]  # "minimal" | "actions" | "conversation" | "full"

def resolve(privacy: str | None, share: Sequence[str] | None) -> tuple[str, frozenset[str]]: ...
def describe(classes: frozenset[str]) -> list[tuple[str, bool, tuple[str, ...]]]: ...
```

### Span model, projection and export policy

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
def flush_turn(state: ProjectionState) -> list[Span]: ...   # keeps roots and hop spans open
def flush_open(state: ProjectionState) -> list[Span]: ...   # closes everything

DEFAULT_EVENTS: frozenset[str]
ATTRIBUTE_CLASSES: dict[str, str]     # non-structural attribute name -> its content class
                                      # (docket.escalation.prompt -> prompts)
```

### Pipeline and registry

```python
class SinkOutcome(Protocol):        # structural match to SinkResult's field names
    @property
    def accepted(self) -> int: ...
    @property
    def status(self) -> int | None: ...
    @property
    def error(self) -> str: ...
    @property
    def retry_after_s(self) -> float | None: ...

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
    def flush(self, timeout_s: float, *, final: bool = False) -> None: ...
    def close(self) -> None: ...
    def stats(self) -> PipelineStats: ...
    @property
    def policy(self) -> ExportPolicy: ...

SinkFactory = Callable[[Any, list[str]], SpanSink]   # (ExporterSpec, resolved credential values)

def load_enabled_exporters() -> list[Any]: ...        # list[ExporterSpec], enabled entries only
def start(specs: Sequence[Any], sink_for: SinkFactory) -> int: ...
def flush(timeout_s: float) -> None: ...
def close() -> dict[str, dict[str, Any]]: ...         # final counters, health()'s shape
def health() -> dict[str, dict[str, Any]]: ...        # exporters-health.json's shape
def capture_classes() -> frozenset[str]: ...          # union of every started pipeline's classes
```

### Exporter documents and catalog

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

    @property
    def privacy_label(self) -> str: ...           # resolve(privacy, share)[0]
    @property
    def privacy_classes(self) -> frozenset[str]: ...  # resolve(privacy, share)[1]

class ExporterError(Exception):
    def __init__(
        self, file: Path | str, field: str, message: str, valid: tuple[str, ...] = ()
    ) -> None: ...
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
    def source_of(self, name: str) -> str: ...  # "" when name is not in the catalog

def load_catalog() -> Catalog: ...
def save_exporter(spec: ExporterSpec) -> None: ...
def delete_exporter(name: str) -> None: ...     # raises ExporterError
def export_exporter(name: str) -> str: ...      # YAML, never a credential value
def resolve_credentials(spec: ExporterSpec) -> tuple[list[str], str]: ...
    # (values, source); an unresolved name yields ""; source is env|store|mixed|none
def enable_exporter(name: str, overrides: dict[str, Any] | None = None) -> ExporterSpec: ...
def disable_exporter(name: str) -> ExporterSpec: ...   # both raise ExporterError
def is_widening(old: frozenset[str], new: frozenset[str]) -> bool: ...
def set_privacy(
    name: str,
    privacy: str | None = None,
    share: list[str] | None = None,
    content_max_chars: int | None = None,
) -> ExporterSpec: ...                                 # raises ExporterError

ExporterState = Literal["enabled", "needs credential", "disabled", "unreachable"]

def activation_state(
    spec: ExporterSpec, health: dict[str, Any] | None
) -> tuple[ExporterState, list[str]]: ...

@dataclass(frozen=True)
class ProbeResult:              # the catalog's own probe type; imports no wire adapter
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

### The `otlp-http` dialect

```python
AuthHeader = tuple[str, str] | None   # (header name, resolved value); None = no auth

def encode(
    spans: Sequence[Span],
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
        opener: Callable[..., Any] = open_same_origin,
    ) -> None: ...

    def emit(self, spans: Sequence[Span]) -> SinkResult: ...
    def close(self) -> None: ...

@dataclass(frozen=True)
class ProbeResult:              # the wire probe's raw result
    status: int | None
    error: str = ""

def probe(
    endpoint: str,
    auth_header: AuthHeader,
    headers: Mapping[str, str],
    timeout_s: float = 5.0,
    opener: Callable[..., Any] = open_same_origin,
) -> ProbeResult: ...
```

### Sink factory

```python
def sink_for(spec: ExporterSpec, values: list[str]) -> SpanSink: ...
    # dispatches on spec.dialect; raises ValueError for an unknown one
```

### Environment

| Variable | Default | Effect |
|---|---|---|
| `DOCKET_NO_EXPORT` | `0` | `1` makes `start` a no-op (requirement 52) |
| `EXPORTERS_FILE` | `$DOCKET_HOME/docket-exporters.json` | the global exporter catalog |
| `EXPORTERS_HEALTH_FILE` | `$DOCKET_HOME/exporters-health.json` | the health file |
| `EXPORT_QUEUE_MAX` | `1000` | each `Pipeline`'s queue bound |
| `EXPORT_FLUSH_TIMEOUT_S` | `5.0` | each flush's wall-clock bound |
| `DISPATCH_RETRY_MAX_WAIT_S` | `60` | ceiling on `emit`'s retry sleep |
| `TRACES_DIR` | `$DOCKET_HOME/traces` | where `preview` finds sessions |

## Examples

### Projecting one session

```python
state = ProjectionState()
spans: list[Span] = []
for record in records:            # one session's trace_event() records, in order
    spans.extend(project(record, state))
spans.extend(flush_open(state))   # closes anything session_end did not
```

### Sharing beyond structure, deliberately

```python
label, classes = resolve("actions", None)   # ("actions", {"toolArguments", "errors"})
policy = ExportPolicy(events=DEFAULT_EVENTS, classes=classes, label=label)
admitted = policy.admit(record)          # filtered by event type only, payload untouched
if admitted is not None:
    spans = project(admitted, state, policy)
    # a granted class's content attribute is present; every other content attribute is absent
```

### Checking whether a shipped destination is ready

```python
spec = load_catalog().get("langfuse")    # a built-in, disabled until enabled: true
health = read_health().get("langfuse")
state, missing = activation_state(spec, health)
# state == "disabled" until an operator both enables it and stores
# LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY.
```

### Enabling a destination once its credentials are stored

```python
# both credentials are already in the secret store; probe + verify_endpoint
# already classified the endpoint as reachable
enabled = enable_exporter("langfuse", {"endpoint": "https://collector.example/traces"})
enabled.enabled            # True
# docket-exporters.json now holds exactly {kind, name, enabled: true, endpoint: ...} --
# aliases, resource, and every other field still resolve from the built-in.
```

### Encoding and sending one batch

```python
document = encode(
    spans, resource={"service.name": "docket"}, aliases={"session.id": "langfuse.session.id"}
)
sink = OtlpHttpSink(
    endpoint="https://collector.example/v1/traces",
    auth_header=("Authorization", "Bearer <resolved-token>"),
)
result = sink.emit(spans)   # never raises; result.status is None only for a transport failure
```

### Starting the pipeline for a turn

```python
started = start(load_enabled_exporters(), sink_for)
# started == 0 with every exporter disabled (the shipped default) -- no thread, no subscriber
...
flush(5.0)                  # $EXPORT_FLUSH_TIMEOUT_S; bounded even if a sink hangs
health()                    # {} when started == 0
```

### Raising what one destination sees

```text
$ docket setup export privacy langfuse conversation --yes
! 'langfuse' will widen from 'minimal' to 'conversation':
    + toolArguments  (e.g. gen_ai.tool.call.arguments)
    + errors  (e.g. docket.error.message)
    + toolResults  (e.g. gen_ai.tool.call.result)
    + completions  (e.g. gen_ai.output.messages)
    + prompts  (e.g. gen_ai.input.messages)
  destination: cloud.langfuse.com
ok Exporter privacy updated: langfuse
  shares: conversation (completions, errors, prompts, toolArguments, toolResults)
-> Next: docket setup export preview langfuse
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

- The projection, policy and pipeline code **MUST NOT** import a wire adapter, print, or write
  to disk; `Pipeline` **MUST NOT** open a socket itself: it drains into a `SpanSink` object it
  is handed, and never constructs one (that is `sink_for`'s job).
- `Pipeline.offer`, `Pipeline.flush`, and `Pipeline.close`, and the module-level `start`,
  `flush`, and `close`, **MUST NOT** raise for an ordinary failure -- a raising `policy`, a
  corrupt record, a raising `sink.emit`, or a full queue are all handled outcomes, never
  exceptions that reach the caller (`DocketDriver.run_turn`, which itself promises never to
  raise for an ordinary failure).
- A `Pipeline.flush(timeout_s)` call **MUST** return within `timeout_s` of its own wall-clock
  budget regardless of how long the underlying `sink.emit` takes: a hung or slow destination
  **MUST NOT** make a turn's `run_turn` call take meaningfully longer than
  `$EXPORT_FLUSH_TIMEOUT_S` on top of the turn's own time.
- Redaction of secret shapes happens once, in `trace_event`, before a record is written; this
  layer never re-redacts, and the allowlist only ever narrows what a policy's ungranted classes
  already withhold, never widens it.
- The exporter catalog code **MUST NOT** import a wire adapter; its own probe type
  (`ProbeResult`) is a plain dataclass so it never needs to.
- `activation_state` and `verify_endpoint` **MUST NOT** write anything; their only read is
  credential resolution.
- The exporter catalog **MUST NOT** ever hold, log, or serialize a credential *value*: only
  credential *names* are ever fields of `ExporterSpec`.
- The `otlp-http` dialect **MUST NOT** import `ExporterSpec` or any other destination-document
  type; it receives only primitive values (an endpoint string, an already-resolved auth header
  pair, plain mappings) and never reads a credential by name.
- Projecting the committed three-hop fixture trace, then `encode`-ing it with
  `resource={"service.name": "docket"}` and `aliases={"session.id": "langfuse.session.id"}`,
  **MUST** byte-match the committed OTLP golden (`json.dumps(sort_keys=True, indent=2) + "\n"`;
  both files are named in Implementation).
- `OtlpHttpSink.emit` and `probe` **MUST NOT** raise for any transport or HTTP-level failure;
  every outcome is a typed result.

## Implementation

- `src/docket/observability/telemetry.py`: `Span`, `SpanEvent`, `ProjectionState`, `ExportPolicy`,
  `MINIMAL_POLICY`, `project`, `flush_turn`, `flush_open`, `DEFAULT_EVENTS`,
  `ATTRIBUTE_CLASSES`, the structural-key table (`_STRUCTURAL_KEYS`), the grant check
  (`_granted`), `SinkOutcome`, `SpanSink`, `PipelineStats`, `Pipeline`, `SinkFactory`,
  `load_enabled_exporters`, `start`, `flush`, `close`, `health`, `capture_classes`
- `src/docket/governance/privacy.py`: `CONTENT_CLASSES`, `LEVELS`, `resolve`, `describe`
- `src/docket/observability/exporter.py`: `ExporterAuth`, `ExporterSpec`, `ExporterError`,
  `load_exporter_document`, `Catalog`, `load_catalog`, `save_exporter`, `delete_exporter`,
  `export_exporter`, `resolve_credentials`, `enable_exporter`, `disable_exporter`,
  `is_widening`, `set_privacy`, `ExporterState`, `activation_state`, `ProbeResult`,
  `ExporterVerification`, `verify_endpoint`, `read_health`
- `src/docket/models/catalog.py`: `ProviderError`, the provider `verify_endpoint` (requirements
  22-23, 31)
- `src/docket/observability/adapters/otlp_http.py`: `AuthHeader`, `encode`, `SinkResult`,
  `OtlpHttpSink`, `ProbeResult`, `probe`
- `src/docket/observability/adapters/sinks.py`: `sink_for`
- `src/docket/platform/redirects.py`: `open_same_origin`
- `src/docket/hops/application/driver.py`: `DocketDriver.run_turn` (requirement 55), the
  `atexit` hook `_close_telemetry` (requirement 109)
- `src/docket/platform/store.py`: the docket-owned JSON store (`read_json`, `write_json`,
  `read_modify_write`)
- `src/docket/hops/application/compose.py`, `src/docket/tasks/application/record.py`: the hop
  marker and hop reply (requirement 108)
- `src/docket/hops/application/executor.py`: the `session_end` write (requirement 106)
- `src/docket/kernel/home.py`: the `Home` members `exporters_file`, `exporters_health_file`,
  `export_queue_max`, `export_flush_timeout_s`, `dispatch_retry_max_wait_s`, `traces_dir`
- `src/docket/kernel/templates.py`: `EXPORTER_TEMPLATES_DIR`
- `src/docket/models/document_fields.py`: `check_name`, `check_http_url`, `check_credential_name`, `reject_reserved_headers`
- `src/docket/platform/process.py`: `no_export` (`DOCKET_NO_EXPORT`, read live)
- `src/docket/templates/exporters/`: the five built-in documents
- `src/docket/interfaces/cli/commands/setup_export.py`: `docket setup export` (requirements 60-63, 90-102)
- `src/docket/interfaces/cli/commands/setup_check.py`: the `docket setup` exporter lines (requirement 97)
- `src/docket/interfaces/cli/commands/pod_show.py`, `src/docket/hops/application/report.py`: `docket pod show`'s exporters
  report (requirement 97)
- `tests/fixtures/traces/dispatch-3-hops.jsonl`, `tests/fixtures/otlp-v1/dispatch-3-hops.json`:
  the fixture trace and its OTLP golden
