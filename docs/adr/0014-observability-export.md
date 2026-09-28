# ADR 0014 (D-48): observability as configuration — one signal, a neutral span model, destinations as `kind: exporter` documents

> **Amended by [ADR 0015](0015-export-privacy-levels.md) (D-49, 2026-09-28).** The
> `payload: metadata|full` switch and `payloadMaxChars` wherever they appear below are replaced by
> a declared privacy level enforced by an attribute allowlist, with content captured on demand.
> The rest of this decision stands.

**Question:** docket already records everything an agent does: a per-session JSONL trace with a
closed vocabulary and a fixed record shape (`core/trace.py::trace_event`), a synchronous
subscriber seam the harness streams through (`trace.subscribe`), measured token counts per
exchange (`core.llm.TokenUsage`), a Prometheus text endpoint (`serve.py::render_metrics`) and a
cursor read API (`GET /traces/<project>?since=`). Yet none of it can reach an OpenTelemetry
collector, Jaeger, Langfuse, Honeycomb or Phoenix, the trace has no event for the model call
itself (usage is persisted in the session record, not the trace; latency is measured nowhere),
the only configuration is five environment variables, and the second writer of trace records
(`trace_ingest`) bypasses the seam. D-24 (ADR 0005) cut "OpenTelemetry spans + OTLP export"
on 2026-07-31 as a platform-team solution imported into a one-operator system, and D-25 left it
schedulable only when a two-runtime proof named a trace requirement JSONL could not satisfy.
The 2026-09-27 request: make observability and telemetry configurable and easy to adapt to
standards such as OpenTelemetry or Langfuse; solid, maintainable, with enough abstraction that
adding a remote destination later is simple; destinations as YAML like providers; Langfuse and
OpenTelemetry shipped as ready documents that only need authenticating; without over-sizing.
What is the shape, what stands from D-24, and what earns a card?

**Where decided:** 2026-09-27, as Phase 32. **Activation gate:** none (Phase 31 closed at
`3f39484`, README follow-up at `0191ffe`); the integrator batches by function-level contention.

**Evidence** (read at `0191ffe`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| One record shape, one closed vocabulary, redaction before write, a `"suppressed"` outcome under `DOCKET_NO_TRACE=1` | `core/trace.py::trace_event`, `EVENT_TYPES`, `redact`, `config.no_trace` |
| A synchronous, best-effort subscriber seam with exactly one consumer | `core/trace.py::subscribe`, `_notify_subscribers`; `cli/_harness.py::_emit` |
| The ingestion bridge appends without notifying subscribers | `core/trace.py::trace_ingest` calls `_append` directly |
| No trace event per model call; usage goes to the session record | `core/agent_loop.py::_TurnState.call_backend_and_handle_response` (`append_messages(..., usage=)`); `EVENT_TYPES` has no `llm_call` |
| Latency is not measured; the adapter only uses `timeout` | `edges/adapters/llm.py::OpenAIChatClient.complete` |
| `ChatResponse` carries usage but neither model nor latency | `core/llm.py::ChatResponse` |
| Recorded dollar spend is `0.0` by design; `docket cost` shows a labelled estimate | `edges/adapters/docket_runtime.py::run_turn` (`cost_usd`), `cost-tracking.spec.md` |
| Dispatch carries `taskId` in the hop's `context`, never on the record | `core/dispatch.py` (`context={"taskId": ...}`); `docket_runtime.py::run_turn(trace_project, trace_session_key)` |
| The harness event *is* the trace record, "not a second vocabulary"; `additionalProperties: true` | `specs/api/harness-mode.spec.md` (event table); `docs/contracts/harness-v1/schema.json` |
| Prometheus text already served, computed from trace and audit files per scrape; counters are not monotonic (known limit 4) | `serve.py::render_metrics`, `_collect_trace_loop_metrics`, `_collect_audit_loop_metrics` |
| Providers are `kind: provider` documents: built-in + global nearest-wins, closed `dialect`, credentials by name, verified registration, `explain` names the source | `core/provider.py::ProviderSpec`, `AuthSpec`, `Catalog`, `verify_endpoint`; `edges/adapters/llm.py::_DIALECTS`, `client_for`; `cli/_provider.py` |
| The `kind` envelope is a closed tuple with one model per kind | `core/config_docs.py::KINDS`, `_MODEL_FOR_KIND`, `load_document` |
| Hidden credential prompt exists once, inline | `cli/_keys.py::_keys_add` (`getpass`) |
| The runtime wheel ships a measured closure; a new module on the turn path must be listed | `packages/docket-runtime/hatch_build.py`; ADR 0013's P31-6 finding |
| The trace store has no owning spec; its rules are split across three | `pod-dispatch.spec.md`, `serve-read-api.spec.md`, `harness-mode.spec.md` |
| D-24 cut OTel; D-25's trigger | `docs/adr/0005-prioritization-ruling-viable-vs-overengineering.md`; ROADMAP §6 D-25, "Tracked decisions" table |

The trigger is an explicit scoped request. No quantitative threshold is invented, and D-25's
two-runtime trigger has **not** fired: this decision records what changed since D-24 rather than
reinterpreting it. Full analysis: `internal-docs/observability-export-audit-2026-09-27.es.md`
and `internal-docs/observability-export-plan-2026-09-27.es.md` (gitignored).

## Decision

**docket keeps one signal, the trace record, and enriches it with the model call. A small
neutral span model in `core/` projects that vocabulary once. A destination is a `kind: exporter`
document whose closed `dialect` selects the one edge module that knows its wire format; v1
ships one dialect, `otlp-http`, and five ready built-ins (a local collector, Jaeger, Langfuse,
Honeycomb, Phoenix) that the operator only enables and authenticates. The local JSONL stays the
source of truth; export is a best-effort mirror that never blocks a turn and never sends
repository content off the host unless the operator says so.**

### 1. What stands from D-24, and what changed

D-24's verdict on the OpenTelemetry **SDK** stands: no `opentelemetry-*` dependency, no
auto-instrumentation, no context propagation, no OTLP metrics or logs, no sampling. What
changed since 2026-07-31: (1) a real external consumer exists (Tack, over the Phase 22 cursor
API), so "nobody reads the traces outside docket" is false; (2) Phases 26–29 made every other
surface a `kind:` document with a schema, and telemetry is the last one configured only by
environment variables, so making it configurable is the configuration contract (D-42) applied,
not a new feature; (3) the subscriber seam was paid for by harness mode (Phase 24), so the
marginal cost of an exporter is a projection and one wire module, not "importing OTel"; (4) the
explicit request. D-25's trigger stays as written for anything beyond this phase.

### 2. The rules

1. **One signal.** `EVENT_TYPES` gains `llm_call` (model, provider, ok, finish reason, failure
   kind, measured input/output/cached tokens, iteration; `duration_ms` = latency measured in
   `edges/adapters/llm.py`), one per request, failures included, never `cost_usd`. The record
   gains an optional `task_id`. `trace_ingest` notifies subscribers. Harness, `/traces` and
   `docket trace` show the new field and event with no contract change (additive).
2. **A neutral model, in `core/`, that knows no vendor.** `core/telemetry.py::Span`/`SpanEvent`
   (frozen dataclasses) and `project(record, state)`, an incremental pure projection with
   deterministic ids (`sha256(session_id)[:32]` as trace id; `sha256(session_id, kind, key)[:16]`
   as span id) so a retry never duplicates. Sessions become root spans, `llm_call` a `gen_ai.chat`
   child with GenAI semantic-convention attributes, `tool_call`+`tool_result` paired by `callId`
   into `execute_tool <name>`, hops and verdicts into `docket.hop <role>`, everything else a
   span event on the active span. A test fails when an `EVENT_TYPES` member has no rule.
3. **Policy before the queue.** `ExportPolicy` (`events: default|all|[...]`, `payload:
   metadata|full`, `payloadMaxChars`) is applied in the calling thread, O(1) per record.
   `metadata` (default) sends names, ids, counts, sizes, verdicts and finish reasons; never tool
   arguments, tool results or prompt text. `full` is an explicit, audited operator choice. As
   shipped, the `gen_ai.chat`/`execute_tool` spans' attribute sets are closed (Requirements 8-9)
   and never include prompt, message, or tool argument/output content at either setting --
   `llm_call` itself never records that content (measured tokens and latency only); `payload`
   currently governs only the handful of other trace event types whose payload carries a
   content-named field. Found live 2026-09-28 (P32-9 follow-up); wiring real content through
   under `full` would be a deliberate, separately-scoped privacy decision, not a bug fix.
4. **The pipeline never blocks a turn.** `core/telemetry.py::Pipeline`: bounded `queue.Queue`,
   one daemon thread, batches, drop-and-count on saturation, `flush(timeout)` at the end of
   `run_turn`, `close()` at exit. Zero enabled exporters means no thread and no subscription:
   the default path is unchanged (the MCP-servers rule).
5. **A destination is data; a wire is code.** `core/exporter.py::ExporterSpec` mirrors
   `ProviderSpec`: `name`, `dialect` (closed), `endpoint`, `auth` (`bearer|header|basic|none`,
   credentials by **name**), `headers`, `resource` (static resource attributes), `aliases`
   (copy an attribute under another key), `events`, `payload`, `enabled`, `note`. Two scopes,
   nearest-wins by name: built-in `templates/exporters/NN-<name>.yaml` and the operator's
   `docket-exporters.json`; a global entry under a built-in's name inherits its identity.
   `edges/adapters/exporters/_DIALECTS` maps a dialect to a `SpanSink`; `otlp_http.py` is the
   only module that knows OTLP/HTTP JSON (stdlib `urllib`, `application/json`, 5 s timeout,
   retry only on 429/5xx honouring `Retry-After` up to `DISPATCH_RETRY_MAX_WAIT_S`).
6. **Built-ins are complete and dormant.** Five documents ship `enabled: false`. `docket
   exporters enable <name>` prompts for each missing credential through the same hidden path
   `docket keys add` uses, probes the endpoint with an empty `resourceSpans` POST, classifies the
   answer as `verify_endpoint` does (only a transport failure refuses), writes **only**
   `{name, enabled: true, overrides…}` to the global catalog, and audits (`exporter.enabled`,
   with `payload` and `endpoint`, never a value). A present key never activates anything by
   itself: data leaving the host is a command.
7. **A recipe may name a destination, never carry one.** `pod.yaml` gains `exporters:
   [<name>…]`; `summarize_recipe`, `validate`, `recipes show` list it; `pod apply` prints each
   name's state (`enabled` / `needs credential X` / `disabled`) and the exact command, and
   activates nothing (ADR 0012 rule 1). Activation stays global: one operator (D-22).
8. **Observability of the exporter itself.** `exporters-health.json` (through `store.py`)
   records per exporter `exported`, `dropped`, `failed`, `lastError`, `lastOk`; `config explain`
   and `docket doctor` read it; `DOCKET_NO_EXPORT=1` no-ops export with an observable outcome.
9. **What is not exported.** `audit.log` (local by design; the chain proves nothing off-host),
   the cost estimate under any attribute, `/metrics` as OTLP metrics (Prometheus text is a
   standard the collector's `prometheus` receiver scrapes unchanged).

### 3. Adding a destination after this phase

| Case | Touches | Size |
| --- | --- | --- |
| Langfuse, collector, Jaeger, Honeycomb, Phoenix | `docket exporters enable <name>`, paste the key | none |
| Another OTLP backend (Tempo, SigNoz, Grafana Cloud, Datadog agent) | one YAML: a template (becomes a built-in) or `docket exporters add` | XS, no code |
| A backend wanting its own attribute names | the same YAML's `aliases`/`resource` | XS, no code |
| A backend that only accepts OTLP protobuf | `edges/adapters/exporters/otlp_proto.py` + one `_DIALECTS` entry | S–M |
| A backend with its own API | one dialect module that receives `Span`; nothing in `core/` | S |
| Per-pod destinations | `--pod` on `docket exporters`, the Phase 27 mould | S; trigger: a second operator |

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| `llm_call` with measured latency; the trace store gets its own spec | **DO** | P32-1 | the one signal both standards need; a spec owner the store never had |
| Neutral `Span`/`SpanEvent`, deterministic projection, `ExportPolicy` | **DO** | P32-2 | the abstraction that keeps vendors out of `core/`; two dataclasses, not a framework |
| `task_id` on the record; `trace_ingest` through the seam | **DO** | P32-3 | correlation without payload heuristics; the second writer was a silent gap |
| `kind: exporter`, two scopes, schema, five built-in documents, health file shape | **DO** | P32-4 | the provider mould, applied to the output side |
| `otlp-http` dialect, hand-rolled JSON over `urllib`, golden fixture | **DO** | P32-5 | one module knows the wire; zero dependencies (D-19: rent the protocol) |
| Bounded pipeline, lazy start and flush in `run_turn`, live proof | **DO** | P32-6 | the card that has failed five times before: wiring, proven by a real span |
| `docket exporters` with `enable` prompting for credentials; `explain`; `doctor` | **DO** | P32-7 | "only authenticate" is the requested experience |
| `exporters:` in `pod.yaml` as names | **DO** | P32-8 | the repository states the standard; the operator activates |
| Docs, README line, external verification (collector + Langfuse), close | **DO** (integrator) | P32-9 | D-37; the external proof needs real credentials |
| The OpenTelemetry SDK, an `[otel]` extra | **CUT** | — | D-24 stands; the SDK owns the span lifecycle docket already owns |
| OTLP metrics or logs; exporting `audit.log` | **CUT** | — | Prometheus text is already scraped; audit is local by design |
| Exporter plugins loaded from disk | **CUT** | — | no measured need; `core/plugins.py` exists where the operator must own code |
| A credential activating an exporter by presence | **CUT** | — | data leaving the host is a command, audited |
| Sampling, context propagation, streaming spans | **CUT** | — | no measured need in a one-operator system |
| OTLP protobuf dialect | **DEFER** | — | **Trigger:** a destination in use that rejects `application/json` (P32-9 measures Langfuse and the collector) |
| Per-pod exporters | **DEFER** | — | **Trigger:** a second operator |
| Monotonic counters for `/metrics` | **DEFER** | — | known limit 4; its own trigger (an alert built on `rate()`) |

## Test discipline

One RED behavioural test per card in the module's `SUBJECT` file or the integration file the card
names; a negative case only for a fail-closed property (P32-2: `metadata` never carries
`arguments`; P32-6: an endpoint that accepts and never answers does not lengthen the turn;
P32-7: `enable` without a TTY and without keys exits 1 naming them, writing nothing). A captured
real dispatch trace (`tests/fixtures/traces/dispatch-3-hops.jsonl`) is the projection's fixture
and, encoded, the wire golden (`tests/fixtures/otlp-v1/`). No worker probes a real vendor host;
the integrator sends the golden to a real collector and to Langfuse once, and the spec records
the answer. Goldens change only where a card lists the lines (`docket trace <id>` gains one line
per request; `completions` and `docket exporters list` are new cases).
