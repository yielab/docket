# Trace Store Specification

**Version**: 4.1.0
**Status**: Implemented and live. Every component that traces writes through `trace_event` into
one append-only JSONL file per session; the periodic sweep of `docket start` closes stale traces
and expires old ones.
**Last Updated**: 2026-10-28

## Purpose

Docket traces every agent action it can observe to `$TRACES_DIR/<project>/<session_id>.jsonl`,
one append-only file per session. This specification defines that store: the record shape written
per line, the closed `EVENT_TYPES` vocabulary an event type must belong to before it is accepted,
the subscriber seam (`subscribe`, `add_subscriber`) through which an in-process consumer receives
each record as it is written without reading the file (the `docket run` progress view and the
trace exporter pipeline), `redact`'s secret-shape scrubbing, the sweep that closes stale traces
(`sweep_all`), the retention function (`expire_old_traces`) that keeps the store bounded, and the
terminal-outcome summary read from it (`terminal_outcomes`).

## Scope

This specification covers:

- The on-disk JSONL record shape and its required/optional fields
- `EVENT_TYPES`, the closed set of event-type strings `trace_event` accepts
- `trace_event`'s three-outcome return contract (`TraceStatus`) and `DOCKET_NO_TRACE=1`
- The `subscribe`/`add_subscriber`/`TraceSink` seam: synchronous, best-effort, redacted-record
  delivery
- `redact`: the always-on secret-shape patterns plus stored- and exported-secret-value scrubbing
- `sweep_all`/`expire_old_traces`: synthetic `session_end` for stale-open traces, and retention
  deletion of terminated traces past the retention window
- How every reader treats a line that is not a JSON object
- The payload keys of `llm_call` and `tool_result` that carry captured content and the request
  breakdown, and the `process_started`/`process_exited` lifecycle events
- `terminal_outcomes`: the count of a pod's finished sessions read back from its trace files

This specification does NOT cover:

- What each individual event type's payload *means*, beyond the shape needed to validate and
  redact it — the producing component's own spec owns that: `agent-loop.spec.md` owns
  `tool_call`, `tool_result`, `prompt_composed`, `session_compaction`, `request_fit` and the
  meaning of `llm_call`; `pod-dispatch.spec.md` owns the verdict/rework/approval/run-cancellation
  and hop event family, `cost_charged` and `budget_exceeded`; `security-gates.spec.md` owns
  `guardrail_check`/`guardrail_block`; `cost-tracking.spec.md` owns `budget_warning`'s unpriced
  action; `operator-loop.spec.md` owns the `escalation_*` family
- The read API surface over this store (`docket task trace`, `GET` routes) — see
  `serve-read-api.spec.md`
- How a trace record is projected into an exported span — see `observability-export.spec.md`
- Audit (the hash-chained `audit.log`) — a separate store, separate guarantees, never merged
  with this one

## Requirements

### Record shape and validation

1. Every accepted event **MUST** be appended as one JSON object per line to
   `$TRACES_DIR/<project>/<session_id>.jsonl`, containing at minimum `ts` (UTC, second
   precision, `YYYY-MM-DDTHH:MM:SSZ`), `project`, `session_id`, `agent_role`, `event_type`, and
   `payload` (a JSON value; a payload that fails to parse as JSON **MUST** be wrapped as
   `{"text": <redacted string>}` rather than rejected). A trace file is created mode 0600, and
   a project directory the write creates is mode 0700.
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
6. `EVENT_TYPES` **MUST** be exactly these 49 members: `session_start`, `tool_call`,
   `tool_result`, `context_composed`, `prompt_composed`, `session_compaction`, `request_fit`,
   `guardrail_check`, `guardrail_block`, `approval_granted`,
   `approval_denied`, `cost_charged`, `budget_warning`, `budget_exceeded`,
   `verification_failed`, `tester_verdict_failed`, `reviewer_verdict_unparseable`,
   `rework_started`, `review_rejected`, `stale_claim`, `dispatch_refused`, `hop_retry`,
   `paused_refused`, `approval_required`, `approval_resumed`, `approval_task_denied`,
   `run_cancellation_observed`, `run_cancelled`, `verdict_rework_started`, `verdict_rejected`,
   `verdict_unparseable`, `verdict_reasked`, `step_skipped`, `command_step`, `route_taken`,
   `escalation_asked`,
   `escalation_delivered`, `escalation_resolved`, `escalation_expired`, `escalation_decided`,
   `llm_call`, `hop_started`,
   `hop_finished`, `memory_update`, `prepare`, `process_started`, `process_exited`, `error`,
   `session_end`. Adding a member **MUST** be a one-line change to this frozenset; removing one
   is a breaking change to every consumer enumerated in Scope above.

### Redaction

7. `redact` **MUST** run before a record's payload is stored, applying every always-on pattern
   (key-shaped assignments; vendor-prefixed names, `ANTHROPIC`, `OPENAI`, `GOOGLE`, `OPENROUTER`,
   `AI_GATEWAY`, `VERCEL`, `COHERE`, followed by a value; a generic
   `NAME_API_KEY`/`_SECRET`/`_TOKEN`/`_KEY` assignment; bare vendor tokens with no prefix at all,
   `sk-`/`sk-ant-`/`sk-proj-`, `ghp_`/`gho_`/`ghs_`, `xox[abp]-`, and a Telegram bot token
   `<8-10 digits>:<35 chars>`; and email addresses) and replacing each match with the literal
   `[REDACTED]`. The key-shaped pattern's labels (`sk`, `pk`, `api`, `key`, `tok`, `secret`,
   `bearer`, `auth`, `Basic`, matched case-insensitively) **MUST** match only where no letter or
   digit precedes them, so `task=<id>` and `risk=<value>` pass unchanged while `api_key=<value>`
   (the `_` is a boundary) is still redacted.
8. `redact` **MUST** additionally replace, after the pattern pass, the exact value of every
   secret held in the file-backed secret store (`secrets.json`; the keyring backend keeps no
   values at rest, so it contributes none) and of every credential-shaped variable in the
   process environment (`DOCKET_LLM_API_KEY`, `TELEGRAM_BOT_TOKEN`, any name ending in
   `_API_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD`), in both cases only for values longer than 8
   characters, so a credential that does not match any generic shape -- stored, or exported in
   the shell and never stored -- is still scrubbed by its own value.
9. `redact` **MUST NOT** raise for any input, including a secrets-store read failure — a
   redaction fault degrades to "no stored-value scrubbing this call", never a lost or blocked
   trace write.
9a. `trace_event` **MUST** parse the payload as JSON first and apply `redact` to every string
   value of the parsed document (nested dicts and lists included), then serialize, so redaction
   never changes whether a payload is structured: a secret-shaped substring inside a string value
   is replaced and every sibling field survives intact. Only a payload that does not parse is
   redacted as a whole string and wrapped as `{"text": ...}` (requirement 1).

### Subscriber seam

10. `subscribe(sink)` **MUST** register *sink* to receive the exact (already redacted) record
    about to be appended, synchronously, on the calling thread, before the append, for the
    duration of its context manager, and **MUST** deregister exactly that one registration on
    exit — including when two subscriptions of the same callable are active, where exiting one
    **MUST** leave the other in place.
11. A raising subscriber **MUST NOT** change `trace_event`'s return value or prevent the
    append; the exception is suppressed and no other subscriber is skipped because of it.
12. `DOCKET_NO_TRACE=1` **MUST** suppress subscriber notification along with the write: under
    it, a subscriber **MUST NOT** observe any record from `trace_event` or `sweep_all`.
35. `add_subscriber(sink)` **MUST** register *sink* on the same subscriber list, with the same
    delivery rules as requirements 10-12, for a long-lived subscriber that has no single `with`
    block to own, and **MUST** return a callable that removes exactly that one registration.
    `subscribe` is the context-manager form of the same registration.

### Stale-trace sweep

36. `sweep_all()` **MUST** append a synthetic `session_end` (`payload.status == "aborted"`,
    `payload.source == "timeout-sweep"`, `agent_role` `"unknown"`) to every trace file under
    `$TRACES_DIR` whose last record's `ts` is older than `SESSION_TIMEOUT` seconds and that has
    no `session_end` yet, and **MUST** leave every other file unchanged. Each synthetic record
    **MUST** be delivered to every registered subscriber before it is appended, the same
    notify-then-append order `trace_event` uses (requirement 10). Under `DOCKET_NO_TRACE=1`
    `sweep_all` **MUST** append nothing and notify no subscriber (requirement 12). The periodic
    sweep of `docket start` runs it once at startup and then on every interval, before
    the retention sweep.

### Retention

16. `expire_old_traces` **MUST** delete a trace file only when it already carries a
    `session_end` event (real or synthetic) and the `ts` of its last timestamped record (not
    necessarily the `session_end`) is older than the retention window (`TRACE_RETENTION_DAYS`,
    30 days by default, unless the caller passes `retention_s`); a trace with no `session_end`, or with no parseable `ts`, **MUST** be
    kept regardless of age. It runs on every periodic sweep of `docket start`, and on demand,
    scoped to one pod, through `docket task prune --traces` (`--days` sets the window). When it
    deletes a trace it also deletes the stored tool results (artifacts) that trace names, only
    files directly inside a pod's `cache/artifacts` directory, and counts their bytes as reclaimed.
17. `expire_old_traces(dry_run=True)` **MUST** report exactly what a real run would delete
    (`TraceExpiryReport.expired`) without deleting anything.

### Task attribution

19. A record **MAY** carry an optional `task_id` field, included only when the caller passes a
    non-empty value, and placed immediately after `event_type` in the record's key order so a
    reader sees it early; a record written with no `task_id` **MUST NOT** carry the key at all
    (never an empty string).

### Captured content

21. An `llm_call` record **MAY** carry four additional optional keys — `inputMessages`,
    `outputMessages`, `systemInstructions` (each in the OTel GenAI `{"role", "parts"}`
    conversation shape) and `systemInstructionsSha256` (a hex SHA-256 string) — written only
    when the caller supplies the exchange's messages and only for the content classes an
    enabled exporter has been granted (`capture_classes()`, ADR 0015). A call made with no
    messages, or with an empty grant, **MUST** produce a payload carrying none of these keys.
    Requirement 28's `request` key is not one of these keys and does not depend on the grant.
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
    trace key in the process or a later call whose system text's SHA-256 differs from the last
    one recorded for that trace key. `systemInstructionsSha256` **MUST** accompany every such
    call regardless of whether the text itself was repeated, so a reader can always tell whether
    the instructions changed even when the text was omitted to avoid repeating it.
25. Every captured text value — a `text` part's `content`, a `tool_call` part's `arguments`, a
    `tool_call_response` part's `response`, and `systemInstructions` — **MUST** be cut to a fixed
    4,000-character on-disk bound, followed by a `…[truncated N chars]` marker naming how much
    was cut, before the record is handed to `trace_event`, independent of any exporter's own
    narrower truncation at projection time.
26. Captured content receives no redaction pass of its own: requirement 7's whole-payload
    `redact` call, which already runs before every record is stored, is the only scrubbing it
    receives — a secret-shaped substring anywhere in a captured part is scrubbed exactly as it
    would be in any other payload field.
27. A `tool_result` record **MUST** carry a `text` key — the tool output fed back to the model,
    cut to the same 4,000-character bound — only when `"toolResults"` is granted and the call
    produced output; with no such grant its payload **MUST** carry no `text` key.

### Request breakdown

28. An `llm_call` record **MUST** carry `request` whenever the backend returned a measure of the
    request it sent (`ChatResponse.request_bytes`): the OpenAI-compatible adapter, the only
    component that knows the wire format, counts the body it actually sent (`request_part_bytes`)
    and returns it on every reply it decodes; a reply that failed before a body was decoded, and
    a backend that does not measure, leave the key out. `request` **MUST** hold exactly the keys
    `system`, `tools`, `toolResults`, `assistant` and `user`, each an object `{"bytes": int,
    "estTokens": int}`. `bytes` is the UTF-8 length of the JSON encoding, as the transport
    serialises it, of each object in that part: `system` counts the messages with role `system`,
    `toolResults` the role `tool` messages, `assistant` the `assistant` messages, `user` the
    `user` messages, and `tools` the advertised tool definitions. The request envelope (the model,
    stream, sampling and tool-choice keys, and the array brackets and separators) is not counted,
    so the five `bytes` values sum to the bytes of the messages and tools as sent. The JSON is
    encoded as UTF-8 (`ensure_ascii=False`) by the transport and the measure alike, so a non-ASCII
    part is its UTF-8 length, not six bytes per escaped character. `estTokens` is
    `bytes // CONTEXT_BYTES_PER_TOKEN`: an estimate, never a measured count, which stays
    `inputTokens`. A compaction call advertises no tools, so its `tools` part is `{"bytes": 0,
    "estTokens": 0}`.
    An `llm_call` record **MUST** also carry `cacheWriteTokens` (the part of `inputTokens` the
    endpoint reported writing to a cache, `TokenUsage.cache_write_tokens`) when it is positive,
    and no such key otherwise, so a record of an endpoint that reports none carries no such key.

### Process lifecycle events

One event marks the start, and one the matching exit, of a real OS process group a tool handler
spawns (ADR 0017). The only producer is the `bash` built-in tool: `run_bash` reports each
lifecycle step to the turn's `ToolContext.on_process` callback, and `DocketDriver` turns each
report into a trace event, so an external plan-of-record can show and cancel a long-running
`bash` call spawned by a pod task.

29. `EVENT_TYPES` **MUST** include `process_started` and `process_exited`.
30. `process_started`'s payload **MUST** carry exactly `{"pgid": <int>}` — the spawned process
    group's id — as reported by `run_bash`; the `bash` tool handler further tags it with
    `"tool": "bash"` before it reaches this store (`run_bash` itself knows nothing about which
    tool called it).
31. `process_exited`'s payload **MUST** carry `pgid` plus exactly one of `exitCode` (int, the
    process's real exit status, including a normal zero) or `signal` (the string `"SIGKILL"`,
    present only when `run_bash` itself killed the group on a timeout or a cancellation) — never
    both, never neither — and is tagged with `"tool": "bash"` the same way.
32. Exactly one `process_started`/`process_exited` pair **MUST** be emitted per process group a
    tool handler starts, and **MUST** fire even when the process is killed rather than left to
    exit on its own and when reading the command's output fails (the call then fails; the
    event carries `exitCode` if the command had already exited, otherwise `run_bash` kills the
    group and the event carries `signal`); a `Popen` call that raises before a process exists
    **MUST NOT** produce either event.
33. A turn with no process-spawning tool call **MUST** produce a trace carrying no
    `process_started`/`process_exited` events at all.
34. When a dispatch run is current (`current_run_id()` is not `None`) at the moment a
    `process_started`/`process_exited` event is reported, the reporting driver **MUST**
    register or clear that pgid against the run (`add_hop_pid`/`remove_hop_pid`) so
    `docket task cancel` reaches it; with no run current, the event is still traced, but no pid
    is registered anywhere.

This store owns only the shape and firing rule of these events, not a consumer's contract.

### Terminal outcomes

37. `terminal_outcomes(project, window=N)` **MUST** read the project's trace files and classify
    each by the `payload.status` of its last `session_end`: `done`/`success`
    count as success, `failed`/`failure` as failure, `cancelled`/`blocked`/`aborted` as aborted,
    and a `session_end` with a dict payload but no `status` as success. A file with no
    `session_end`, with a non-dict payload, or with any other status (a parked `waiting_*` task)
    **MUST** be skipped. It **MUST** order the classified files by the `ts` of their last
    `session_end` (ties by file name, oldest first) and keep only the last *N* of that order (all
    of them when *N* is 0 or less) and report each one's duration from its last `session_start`
    `ts` to its `session_end` `ts`, in milliseconds, when both parse. `docket status` reads it
    with `METRICS_WINDOW` (50 by default).

### Derived figures

39. The cache-hit ratio of an `llm_call` record **MUST** be derived on read as
    `payload.cachedTokens / payload.inputTokens` and **MUST NOT** be stored on the record: no
    `cacheHit` key appears in any payload, so a trace written before this requirement reads the
    same as one written after. `cache_hit(payload)` returns `None` when `inputTokens` is missing,
    not an integer or not positive. A `cachedTokens` of 0 means "not reported" as much as "no
    hit" (`agent/ports.py::TokenUsage`), so a backend that reports no cache reads 0.0.
40. `fold_cache_hits(records)` **MUST** fold the `llm_call` records it is given into the summed
    `inputTokens` and `cachedTokens` per `task_id`, per `agent_role` and over all of them
    (`total`); its ratio is the sums'
    quotient (never a mean of ratios). A record with no `task_id` counts toward its role only;
    one with no role counts toward its task only; a record that is not an `llm_call`, or whose
    payload is not an object, is skipped. It **MUST** only read.

### Lines that are not records

38. `read_trace`, `export_lines`, `sweep_all`, `expire_old_traces` and `terminal_outcomes`
    **MUST** treat a line that is blank, is not valid JSON, or is valid JSON but not an object, as
    carrying no record: `read_trace`, `sweep_all`, `expire_old_traces` and `terminal_outcomes` skip it, and `export_lines` with a
    `since` filter keeps it, as it keeps any line with no parseable `ts`. None of them
    raises because of it.

## Interface Contracts

### Module API

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
def add_subscriber(sink: TraceSink) -> Callable[[], None]: ...
def redact(text: str) -> str: ...
def sweep_all() -> None: ...

def expire_old_traces(
    retention_s: int | None = None, dry_run: bool = False, project: str | None = None,
) -> TraceExpiryReport: ...

def read_trace(tracefile: Path) -> list[dict[str, Any]]: ...
def find_trace(session_id: str) -> Path | None: ...
def project_trace_dir(project: str) -> Path: ...
def export_lines(project: str, since: str = "") -> list[str]: ...
def terminal_outcomes(project: str, *, window: int) -> TerminalOutcomes: ...

# observability/figures.py
def cache_hit(payload: Mapping[str, Any]) -> float | None: ...
def fold_cache_hits(records: Iterable[Mapping[str, Any]]) -> CacheFigures: ...
def tokens_per_accepted_task(counted: Sequence[int]) -> float | None: ...

class CacheTotals:                  # input_tokens: int; cached_tokens: int; ratio: float | None
class CacheFigures:                 # total: CacheTotals; by_task, by_role: dict[str, CacheTotals]
def recorded_cache_figures() -> CacheFigures: ...   # the fold over every project's trace files

class ExpiredTrace:                 # one file the retention sweep deleted (or would)
    project: str; session_id: str; path: Path; last_event_ts: str; age_days: float; bytes: int

class TraceExpiryReport:
    dry_run: bool; retention_s: int; scanned: int = 0
    expired: list[ExpiredTrace] = []; kept_open: int = 0; kept_recent: int = 0
    bytes_reclaimed: int = 0
    expired_count: int              # property: len(expired)

class TerminalOutcomes:             # frozen
    success: int = 0; failure: int = 0; aborted: int = 0
    durations_ms: tuple[int, ...] = ()
    total: int; mean_ms: int | None; p95_ms: int | None   # properties
```

### Environment

```text
TRACES_DIR              default $DOCKET_HOME/traces
TRACE_RETENTION_DAYS    default 30      (retention window = days * 86400 seconds)
SESSION_TIMEOUT         default 3600    (seconds before an open trace counts as stale)
CONTEXT_BYTES_PER_TOKEN default 4       (divisor of requirement 28's estTokens; at least 1)
METRICS_WINDOW          default 50      (requirement 37's window for docket status)
DOCKET_NO_TRACE         unset/"0" normally; "1" suppresses every trace_event/sweep_all write
                        and subscriber notification
```

## Examples

### A subscriber sees exactly what was written

```python
received: list[dict[str, object]] = []
with subscribe(received.append):
    status = trace_event("proj", "s1", "tester", "session_start", '{"a": 1}')
# status == "written"
# received == read_trace(project_trace_dir("proj") / "s1.jsonl")
```

### An `llm_call` record

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

### A record with `task_id`

```json
{"ts": "2026-09-27T18:04:11Z", "project": "docket-dev", "session_id": "agent:demo:task-9",
 "agent_role": "implementer", "event_type": "tool_call", "task_id": "task-9",
 "payload": {"tool": "read", "callId": "c1", "arguments": "{}"}}
```

`task_id` sits between `event_type` and `payload`; a record from a caller that passes no task id
(most direct `trace_event` callers outside a pod-dispatch hop) has no `task_id` key at all.

## Validation

### Pre-conditions

- *project*/*session_id* **MUST** be non-empty strings; this store treats both as opaque
  coordinates, exactly as `session-history.spec.md` does for its own session key.
- A payload passed to `trace_event` **MUST** be a string (already-serialized JSON or plain
  text) — never a live object the store would need to serialize itself.

### Post-conditions

- After a `"written"` return, `read_trace` on that session's file **MUST** include the new
  record, in append order, as the last line.
- After a `"rejected"` or `"suppressed"` return, the session's trace file **MUST** be unchanged.

### Invariants

- Two distinct `(project, session_id)` pairs **MUST NOT** ever share a trace file.
- A record's `payload` written by `trace_event` **MUST NOT** contain a value `redact` would have
  scrubbed — redaction runs before the write, never after, and never conditionally.
- Every deleted trace file **MUST** already have a `session_end`; `expire_old_traces` **MUST
  NEVER** delete a file a live turn could still be appending to.

## Implementation

- `src/docket/observability/trace.py`: `trace_event`, `TraceStatus`, `TraceSink`, `EVENT_TYPES`,
  `subscribe`, `add_subscriber`, `redact`, `sweep_all`, `expire_old_traces`,
  `ExpiredTrace`, `TraceExpiryReport`, `read_trace`, `find_trace`, `project_trace_dir`,
  `export_lines`, `terminal_outcomes`, `TerminalOutcomes`
- `src/docket/observability/figures.py`: `cache_hit`, `fold_cache_hits`, `CacheFigures`,
  `CacheTotals`, `recorded_cache_figures`, `tokens_per_accepted_task` (requirements 39-40)
- `src/docket/kernel/home.py`: the `Home` members `traces_dir`, `trace_retention_days`,
  `trace_retention_s`, `session_timeout`, `context_bytes_per_token`, `metrics_window`
- `src/docket/platform/process.py`: `no_trace` (`DOCKET_NO_TRACE`, read live)
- `src/docket/governance/secrets.py`: `secret_values` (the stored values requirement 8 scrubs)
- `src/docket/agent/loop.py`: the `llm_call` and `tool_result` payload builders
  (requirements 21-28)
- `src/docket/observability/telemetry.py`: `capture_classes`, and the exporter pipeline that registers
  through `add_subscriber`
- `src/docket/agent/ports.py`: `ChatResponse.request_bytes`
- `src/docket/agent/session.py`: `TokenUsage.cache_write_tokens`
- `src/docket/models/adapters/openai_http.py`: `request_part_bytes`
- `src/docket/agent/tools/builtins/toolbox.py`: `run_bash` (the `on_process` reports)
- `src/docket/agent/tools/registry.py`: `ToolContext.on_process`, the `bash` handler's `"tool": "bash"` tag
- `src/docket/hops/application/driver.py`: `DocketDriver` (turns `on_process` reports into
  `process_*` events, registers pgids)
- `src/docket/tasks/application/runs.py`: `current_run_id`, `add_hop_pid`, `remove_hop_pid`
- `src/docket/interfaces/http/server.py`: the periodic sweep that calls `sweep_all` then `expire_old_traces`
- `src/docket/interfaces/cli/render/progress.py`: the `docket run` progress view's `subscribe` consumer
- `src/docket/interfaces/cli/commands/task.py`: `docket task trace` (`--tail` polls the file), `docket task prune
  --traces`
- `src/docket/interfaces/cli/commands/status.py`: the `docket status` caller of `terminal_outcomes`
