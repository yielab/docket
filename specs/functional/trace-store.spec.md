# Trace Store Specification

**Version**: 1.3.0
**Status**: Implemented and live. `core/trace.py` is the durable per-session JSONL trace store
every trace-emitting module writes through: `core/agent_loop.py` (tool and model-call events),
`core/dispatch.py` (pod-dispatch verdict/approval/run events), `core/approval.py`,
`core/security.py`'s guardrail checks, and `core/harness.py`'s subscriber stream. Before v1.0.0
the store had callers and consumers (`pod-dispatch.spec.md`, `serve-read-api.spec.md`,
`harness-mode.spec.md`) but no spec of its own defining the record shape, `EVENT_TYPES`, or the
subscriber/retention machinery; this specification is that owner.
**Last Updated**: 2026-09-27

## Purpose

Docket traces every agent action it can observe to `$TRACES_DIR/<project>/<session_id>.jsonl`,
one append-only file per session. This specification defines that store: the record shape written
per line, the full `EVENT_TYPES` vocabulary an event type must belong to before it is accepted,
the `subscribe` seam a live consumer (`docket trace tail`, `docket harness run`) reads from
without touching disk, `redact`'s secret-shape scrubbing, the `trace_ingest` bridge that projects
a driver's own session log into this store, and the retention functions (`sweep_all`,
`expire_old_traces`) that keep it bounded.

## Scope

This specification covers:

- The on-disk JSONL record shape and its required/optional fields
- `EVENT_TYPES`, the closed set of event-type strings `trace_event` accepts
- `trace_event`'s three-outcome return contract (`TraceStatus`) and `DOCKET_NO_TRACE=1`
- The `subscribe`/`TraceSink` seam: synchronous, best-effort, redacted-record delivery
- `redact`: the always-on secret-shape patterns plus stored-secret-value scrubbing
- `trace_ingest`: idempotent, offset-tracked projection of a `RuntimeDriver`'s own session log
  into `tool_call`/`tool_result`/`session_start`/`session_end` records
- `sweep_all`/`expire_old_traces`: synthetic `session_end` for stale-open traces, and retention
  deletion of terminated traces past `TRACE_RETENTION_S`
- The `llm_call` event type this version adds (ROADMAP P32-1, ADR 0014 rule 1)

This specification does NOT cover:

- What each individual event type's payload *means*, beyond the shape needed to validate and
  redact it — the producing module's own spec owns that: `agent-loop.spec.md` owns `tool_call`,
  `tool_result`, `session_compaction`, `request_fit`, and (as of its 1.25.0) `llm_call`;
  `pod-dispatch.spec.md` owns the verdict/rework/approval/run-cancellation event family;
  `security-gates.spec.md` owns `guardrail_check`/`guardrail_block`; `cost-tracking.spec.md`
  owns `cost_charged`/`budget_warning`/`budget_exceeded`
- The read API surface over this store (`docket trace`, `GET` routes) — see
  `serve-read-api.spec.md`
- The harness-mode NDJSON wire pass-through of these same records — see `harness-mode.spec.md`,
  whose `event` field is defined as exactly what `trace_event` produced, unmodified
- Audit (`core/audit.py`'s hash-chained log) — a separate store, separate guarantees, never
  merged with this one

## Requirements

### Record shape and validation

1. Every accepted event **MUST** be appended as one JSON object per line to
   `$TRACES_DIR/<project>/<session_id>.jsonl`, containing at minimum `ts` (UTC, second
   precision, `YYYY-MM-DDTHH:MM:SSZ`), `project`, `session_id`, `agent_role`, `event_type`, and
   `payload` (a JSON value; a payload that fails to parse as JSON **MUST** be wrapped as
   `{"text": <redacted string>}` rather than rejected).
2. `event_type` **MUST** be a member of `EVENT_TYPES`; `trace_event` **MUST** return
   `"rejected"` and write nothing for any other value.
3. `trace_event` **MUST** return `"suppressed"` and write nothing whenever `DOCKET_NO_TRACE=1`,
   checked before event-type validation.
4. `trace_event` **MUST** return `"written"` only after a real append to the session's file.
   `"written"`, `"rejected"`, and `"suppressed"` **MUST** remain three distinct, never-conflated
   outcomes, so a caller can tell a real record from a no-op.
5. `cost_usd` **MUST** be included on a record only when the caller passes a value that parses
   as `float`; when included, it **MUST** be the field name `cost_usd`. `duration_ms` follows the
   same optional-inclusion rule, parsed as `int`.
6. `EVENT_TYPES` **MUST** include exactly: `session_start`, `tool_call`, `tool_result`,
   `context_composed`, `prompt_composed`, `session_compaction`, `request_fit`,
   `guardrail_check`, `guardrail_block`, `approval_requested`, `approval_granted`,
   `approval_denied`, `cost_charged`, `budget_warning`, `budget_exceeded`, `drift_alert`,
   `verification_failed`, `tester_verdict_failed`, `reviewer_verdict_unparseable`,
   `rework_started`, `review_rejected`, `stale_claim`, `hop_retry`, `paused_refused`,
   `approval_required`, `approval_resumed`, `approval_task_denied`,
   `run_cancellation_observed`, `run_cancelled`, `verdict_rework_started`, `verdict_rejected`,
   `verdict_unparseable`, `step_skipped`, `command_step`, `route_taken`, `llm_call`, `error`,
   `session_end`. Adding a member **MUST** be a one-line change to this frozenset; removing one
   is a breaking change to every consumer enumerated in Scope above.

### Redaction

7. `redact` **MUST** run before a record's payload is stored, applying every pattern in
   `_REDACT_PATTERNS` (key-shaped assignments, vendor-prefixed env-var names, a generic
   `NAME_API_KEY`/`_SECRET`/`_TOKEN` shape, and email addresses) and replacing each match with
   the literal `[REDACTED]`.
8. `redact` **MUST** additionally replace the exact value of any secret currently held in
   `core/secrets.py`'s store (values longer than 8 characters), after the regex pass, so a
   stored credential that does not match any generic shape is still scrubbed by its own value.
9. `redact` **MUST NOT** raise for any input, including a secrets-store read failure — a
   redaction fault degrades to "no stored-value scrubbing this call", never a lost or blocked
   trace write.

### Subscriber seam

10. `subscribe(sink)` **MUST** register *sink* to receive the exact (already redacted) record
    about to be appended, synchronously, on the calling thread, for the duration of its context
    manager, and **MUST** deregister exactly that one registration on exit — including when two
    subscriptions of the same callable are active, where exiting one **MUST** leave the other in
    place.
11. A raising subscriber **MUST NOT** change `trace_event`'s return value or prevent the
    append; the exception is suppressed and no other subscriber is skipped because of it.
12. `DOCKET_NO_TRACE=1` **MUST** suppress subscriber notification along with the write — a
    subscriber **MUST NOT** ever observe a record that was not durably written.

### Ingestion bridge

13. `trace_ingest(project)` **MUST** be idempotent: each session's own `.ingest-index.json`
    offset **MUST** ensure a turn already projected is never re-emitted on a later call.
14. `trace_ingest` **MUST** read a driver's session log only through the `RuntimeDriver` port
    (`core/runtime_driver.py`) — it **MUST NOT** parse any driver's on-disk format directly.
15. `trace_ingest` **MUST** synthesize a `session_end` record (`payload.status == "aborted"`,
    `payload.source == "timeout-sweep"`) for a session whose last observed turn is older than
    `config.SESSION_TIMEOUT`, and **MUST NOT** do so for a session that already has one.

### Retention

16. `expire_old_traces` **MUST** delete a trace file only when it already carries a
    `session_end` event (real or synthetic) whose timestamp is older than the retention window
    (`config.TRACE_RETENTION_S` by default); a trace with no `session_end` **MUST** be kept
    regardless of age.
17. `expire_old_traces(dry_run=True)` **MUST** report exactly what a real run would delete
    (`TraceExpiryReport.expired`) without deleting anything or mutating any `.ingest-index.json`.
18. Deleting a session's trace file **MUST** also drop that session's id from its project's
    `.ingest-index.json`, since a session id is never reused and a stale offset entry for one
    can never be read again.

### Task attribution (v1.1.0)

19. A record **MAY** carry an optional `task_id` field, included only when the caller passes a
    non-empty value, and placed immediately after `event_type` in the record's key order so a
    reader sees it early; a record written with no `task_id` **MUST NOT** carry the key at all
    (never an empty string).
20. `trace_ingest` **MUST** notify every registered subscriber with each record it is about to
    append — including the synthetic `session_end` for a timed-out session — before that record
    is durably written, the same notify-then-append order `trace_event` itself uses (requirement
    10). Before this version, `trace_ingest` appended directly and no subscriber ever observed an
    ingested record.

### Captured content

21. An `llm_call` record **MAY** carry four additional optional keys — `inputMessages`,
    `outputMessages`, `systemInstructions` (each in the OTel GenAI `{"role", "parts"}`
    conversation shape) and `systemInstructionsSha256` (a hex SHA-256 string) — written only
    when the caller supplies the exchange's messages and only for the content classes an
    enabled exporter has been granted (`core.telemetry.capture_classes()`, ADR 0015). A call
    made with no messages, or with an empty grant, **MUST** produce a payload carrying none of
    these keys, with the same keys and the same insertion order a payload built before this
    capability existed would have.
22. `outputMessages` **MUST** appear only when `"completions"` is granted, and **MUST** render
    the reply message as one entry: a `text` part for its text (when non-empty) and one
    `tool_call` part per requested tool call, each carrying `id`, `name` and `arguments`.
23. `inputMessages` **MUST** appear only when `"prompts"` is granted, **MUST** exclude the
    system turn entirely, and **MUST** render every remaining message as one `{"role", "parts"}`
    entry: a `tool`-role message becomes a single `tool_call_response` part (`id`, `response`),
    an assistant message's requested tool calls become `tool_call` parts, and any other text
    becomes a `text` part.
24. `systemInstructions` **MUST** appear only when `"instructions"` is granted and a system
    message is present in the captured exchange, and then only on the first call recorded for a
    trace key or a later call whose system text's SHA-256 differs from the last one recorded for
    that trace key. `systemInstructionsSha256` **MUST** accompany every such call regardless of
    whether the text itself was repeated, so a reader can always tell whether the instructions
    changed even when the text was omitted to avoid repeating it.
25. Every captured text value — a `text` part's `content`, a `tool_call` part's `arguments`, a
    `tool_call_response` part's `response`, and `systemInstructions` — **MUST** be cut to a fixed
    4,000-character on-disk bound before the record is handed to `trace_event`, independent of
    any exporter's own narrower truncation at projection time.
26. Captured content receives no redaction pass of its own: requirement 7's whole-payload
    `redact` call, which already runs before every record is stored, is the only scrubbing it
    receives — a secret-shaped substring anywhere in a captured part is scrubbed exactly as it
    would be in any other payload field.
27. A `tool_result` record **MUST** carry a `text` key — the tool output fed back to the model,
    cut to the same 4,000-character bound — only when `"toolResults"` is granted; with no such
    grant its payload **MUST** carry no `text` key. (Found by the live privacy proof: the
    projection's `gen_ai.tool.call.result` read a `text` key that the live loop never wrote.)

## Process lifecycle events

Added by P35-3 (ADR 0017 section 2): one event marking the start, and one marking the matching
exit, of a real OS process group a tool handler spawns. The only current producer is
`edges/adapters/toolbox.py::run_bash`'s `on_process` callback, threaded through
`core/tools.py::ToolContext.on_process` and wired to real trace emission by
`edges/adapters/docket_runtime.py::DocketDriver`. Built for an external plan-of-record (Tack)
that needs to show and cancel a long-running `bash` call spawned through `docket harness run`.

1. `EVENT_TYPES` **MUST** additionally include `process_started` and `process_exited`.
2. `process_started`'s payload **MUST** carry exactly `{"pgid": <int>}` — the spawned process
   group's id — as reported by `run_bash`; the `bash` tool handler further tags it with
   `"tool": "bash"` before it reaches this store (added in `core/tools.py`, not by `run_bash`
   itself, which knows nothing about which tool called it).
3. `process_exited`'s payload **MUST** carry `pgid` plus exactly one of `exitCode` (int, the
   process's real exit status, including a normal zero) or `signal` (the string `"SIGKILL"`,
   present only when `run_bash` itself killed the group on a timeout or a cancellation) — never
   both, never neither.
4. Exactly one `process_started`/`process_exited` pair **MUST** be emitted per process group a
   tool handler starts, and **MUST** fire even when the process is killed rather than left to
   exit on its own; a `Popen` call that raises before a process exists **MUST NOT** produce
   either event.
5. A turn with no process-spawning tool call **MUST** produce a trace carrying no
   `process_started`/`process_exited` events at all — byte-identical to a trace recorded before
   this capability existed.
6. When a dispatch run is current (`core.runs.current_run_id()` is not `None`) at the moment a
   `process_started`/`process_exited` event is reported, the reporting driver **MUST**
   register or clear that pgid against the run (`core.runs.add_hop_pid`/`remove_hop_pid`) so
   `docket runs cancel` reaches it; with no run current, the event is still traced, but no pid
   is registered anywhere.

See `harness-mode.spec.md`'s Contract 1.1 (owned by a separate card in this same wave) for how an
external consumer is expected to use these events; this store owns only their shape and firing
rule, not that consumer's contract.

## Interface Contracts

### Module API (`docket.core.trace`)

```python
TraceStatus = Literal["written", "rejected", "suppressed"]
TraceSink = Callable[[dict[str, Any]], None]

EVENT_TYPES: frozenset[str]  # the full set enumerated in requirement 6

def trace_event(
    project: str, session_id: str, agent_role: str, event_type: str, payload: str,
    cost_usd: float | str | None = None, duration_ms: int | str | None = None,
    *, task_id: str = "",
) -> TraceStatus: ...

def subscribe(sink: TraceSink) -> AbstractContextManager[None]: ...
def redact(text: str) -> str: ...
def trace_ingest(project: str) -> None: ...
def sweep_all() -> None: ...

def expire_old_traces(
    retention_s: int | None = None, dry_run: bool = False, project: str | None = None,
) -> TraceExpiryReport: ...

def read_trace(tracefile: Path) -> list[dict[str, Any]]: ...
def find_trace(session_id: str) -> Path | None: ...
def project_trace_dir(project: str) -> Path: ...
def latest_trace_file(project: str) -> Path | None: ...
def export_lines(project: str, since: str = "") -> list[str]: ...

class ExpiredTrace:                 # one file the retention sweep deleted (or would)
    project: str; session_id: str; path: Path; last_event_ts: str; age_days: float; bytes: int

class TraceExpiryReport:
    dry_run: bool; retention_s: int; scanned: int = 0
    expired: list[ExpiredTrace] = []; kept_open: int = 0; kept_recent: int = 0
    bytes_reclaimed: int = 0
```

### Config (`docket.config`)

```text
TRACES_DIR              default $DOCKET_HOME/traces
TRACE_RETENTION_DAYS    default 30      (TRACE_RETENTION_S = days * 86400)
DOCKET_NO_TRACE         unset/"0" normally; "1" suppresses every write and subscriber notification
```

## Examples

### A subscriber sees exactly what was written

```python
from docket.core import trace

received: list[dict[str, object]] = []
with trace.subscribe(received.append):
    status = trace.trace_event("proj", "s1", "tester", "session_start", '{"a": 1}')
# status == "written"
# received == trace.read_trace(trace.project_trace_dir("proj") / "s1.jsonl")
```

### An `llm_call` record (P32-1)

```json
{"ts": "2026-09-27T18:04:11Z", "project": "docket-dev", "session_id": "agent:demo:default",
 "agent_role": "implementer", "event_type": "llm_call",
 "payload": {"model": "qwen3.6-35b", "provider": "local", "ok": true,
             "finishReason": "tool_calls", "failureKind": null,
             "inputTokens": 812, "outputTokens": 64, "cachedTokens": 0, "iteration": 1},
 "duration_ms": 743}
```

No `cost_usd` key appears on this or any `llm_call` record: token counts are measured, but this
store never carries a dollar figure (see `agent-loop.spec.md` requirement 71).

### A record with `task_id` (v1.1.0)

```json
{"ts": "2026-09-27T18:04:11Z", "project": "docket-dev", "session_id": "agent:demo:task-9",
 "agent_role": "implementer", "event_type": "tool_call", "task_id": "task-9",
 "payload": {"tool": "read", "callId": "c1", "arguments": "{}"}}
```

`task_id` sits between `event_type` and `payload`; a record from a caller that passes no task id
(most direct `trace_event` callers outside a pod-dispatch hop) has no `task_id` key at all.

## Validation

### Pre-conditions

- *project*/*session_id* **MUST** be non-empty strings; this module treats both as opaque
  coordinates, exactly as `session-history.spec.md` does for its own session key.
- A payload passed to `trace_event` **MUST** be a string (already-serialized JSON or plain
  text) — never a live object the module would need to serialize itself.

### Post-conditions

- After a `"written"` return, `read_trace` on that session's file **MUST** include the new
  record, in append order, as the last line.
- After a `"rejected"` or `"suppressed"` return, the session's trace file **MUST** be unchanged.

### Invariants

- Two distinct `(project, session_id)` pairs **MUST NOT** ever share a trace file.
- A record's `payload` **MUST NOT** contain a value `redact` would have scrubbed — redaction
  runs before the write, never after, and never conditionally.
- Every deleted trace file **MUST** already have a `session_end`; `expire_old_traces` **MUST
  NEVER** delete a file a live turn could still be appending to.

## Changelog

### Version 1.3.0 (2026-09-28)

- **`tool_result` captures its output on demand.** Requirement 27: `text` appears only while an
  exporter grants `toolResults`. The live proof at `conversation` showed Langfuse's tool
  observation with no output because `_trace_tool_result` never recorded one; every earlier
  test fed synthetic records that already had it.

### Version 1.2.0 (2026-09-28)

- **Captured content (P33-3).** New section "Captured content" (requirements 21-26): an
  `llm_call` record carries `inputMessages`, `outputMessages`, `systemInstructions` and
  `systemInstructionsSha256` only for the classes an enabled exporter was granted; with no
  grant the record is byte-identical to before.

### Version 1.1.0 (2026-09-27)

- Adds the optional `task_id` record field (requirement 19; ROADMAP P32-3, ADR 0014): written by
  `trace_event` only when the caller passes a non-empty value, placed right after `event_type`.
  `core/agent_loop.py::run_agent_turn` threads it through every `_trace_*` helper; the single
  pod-dispatch call site (`core/dispatch.py`) now passes the claimed task's id.
- `trace_ingest` now notifies every registered subscriber with each record (including the
  synthetic `session_end`) before appending it (requirement 20) — closing the gap where an
  ingested `tool_call`/`tool_result` never reached a live subscriber.

### Version 1.0.0 (2026-09-27)

- Initial specification (ROADMAP P32-1, ADR 0014 rule 1: "the one signal both standards need; a
  spec owner the store never had"). Documents the existing record shape, the full `EVENT_TYPES`
  set, `redact`, the `subscribe` seam, `trace_ingest`, retention (`sweep_all`/
  `expire_old_traces`), `DOCKET_NO_TRACE`, and the three `TraceStatus` outcomes — all previously
  undocumented at the store's own level — plus the new `llm_call` event type this same card adds.
  Cross-referenced from `agent-loop.spec.md` 1.25.0 and `harness-mode.spec.md` 1.1.2; does not
  move any content out of `pod-dispatch.spec.md` or `serve-read-api.spec.md`.
