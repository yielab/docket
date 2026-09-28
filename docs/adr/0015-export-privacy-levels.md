# ADR 0015 (D-49): what a trace destination may see is a declared privacy level, enforced by an allowlist and shown before it is shared

**Question:** Phase 32 (D-48, ADR 0014) ships traces to any OpenTelemetry or Langfuse endpoint
from a `kind: exporter` document, with one knob, `payload: metadata|full`. The live Langfuse
run on 2026-09-28 showed every generation's Input/Output empty, and tracing why found three
things. `full` changes nothing a destination renders: `gen_ai.chat` and `execute_tool` have
closed attribute sets and `llm_call` never records message content. `metadata` is a denylist
over eight payload key names, so any other free-text key already leaves the host under the
default: an approval's `action` (the command line waiting for a human) and a run `error`'s text
reach every enabled destination today. And nothing tells an operator, before or after enabling,
which of those facts leave. The 2026-09-28 request: architect this solidly and configurably, with
privacy levels the operator chooses consciously and can see, so they know what they are sharing
and can change it from the exporter's own settings. What is the shape?

**Where decided:** 2026-09-28, as Phase 33. **Activation gate:** Phase 32 closed at `5f53e52`
and its Langfuse follow-up at `940c3cd`; the integrator batches by function-level contention.

**Evidence** (read at `940c3cd`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| Payload reduction is a denylist of eight key names, applied before projection | `core/telemetry.py::_CONTENT_KEYS`, `_reduce_metadata`, `ExportPolicy.admit` |
| The generic handler forwards every scalar payload key as `docket.<key>` | `core/telemetry.py::_handle_generic_event` |
| `approval_requested` carries the action text (secret-redacted, otherwise verbatim) and is in `DEFAULT_EVENTS` | `core/approval.py` (`_emit_trace(..., {"token", "action"})`), `core/telemetry.py::DEFAULT_EVENTS` |
| A run failure carries free-text `error` and `error` is in `DEFAULT_EVENTS` | `core/runs.py` (`trace_event(..., "error", {"run", "source", "error"})`) |
| The model call is recorded with no content: model, provider, `ok`, finish reason, tokens, latency | `core/agent_loop.py::_trace_llm_call` |
| Both call sites hold the exact request (`messages`) and the reply (`response.message`) | `_TurnState.call_backend_and_handle_response`, the compaction summarizer's `backend.complete` |
| The local trace already holds tool arguments (≤141 chars measured) and tool output (`tool_result.text`, ≤1,846 chars measured, bounded by `DOCKET_TOOL_MAX_OUTPUT_CHARS`) | `~/.docket/traces/<p>/*.jsonl` of the 2026-09-28 dispatches |
| Secret shapes are scrubbed once, at write, for every record | `core/trace.py::trace_event`, `redact` |
| One `Pipeline` and one `ExportPolicy` per enabled exporter, built in `start` | `core/telemetry.py::start` |
| OTel GenAI semantic conventions: content attributes are `Opt-In`; instrumentations "SHOULD NOT capture them by default, but SHOULD provide an option for users to opt in"; names `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`; per-message truncation that preserves JSON structure is allowed | `open-telemetry/semantic-conventions-genai`, `docs/gen-ai/gen-ai-spans.md` |
| Langfuse reads exactly those five names natively (system instructions are prepended as a system message; tool spans take arguments/result as input/output) | `langfuse/langfuse`, `packages/shared/src/server/otel/OtelIngestionProcessor.ts` |

## Decision

**What leaves the host is a set of named content classes, chosen per exporter as a level or an
explicit list, enforced where spans are built by an allowlist that maps every exported
attribute to exactly one class, captured upstream only when an enabled exporter asks for it,
and shown to the operator before, while and after it is shared.** Every built-in ships the
lowest level; widening is an operator command that names what will leave and to where, is
confirmed, and is audited. `payload` is retired.

### 1. Classes and levels

A class is a kind of fact an agent run produces. `structure` is always sent; the others are
opt-in, and each owns a fixed set of OTel attributes:

| Class | What it is | Attributes (OTel GenAI names where one exists) |
| --- | --- | --- |
| `structure` | names, ids, timing, status, model and provider, measured token counts, tool names, `ok`, blocking policy ids, verdicts, hop, task id | today's `gen_ai.chat`/`execute_tool`/`docket.session` attributes, and per-event structural keys (§2 rule 2) |
| `toolArguments` | what the agent asked a tool to do: paths, commands, patterns; an approval's action | `gen_ai.tool.call.arguments`; `docket.approval.action` |
| `errors` | free-text failure messages | `docket.error.message` (the failure kind stays `structure`) |
| `toolResults` | what a tool returned: file contents, command output | `gen_ai.tool.call.result` |
| `completions` | what the model wrote: its text and the tool calls it requested | `gen_ai.output.messages` |
| `prompts` | the conversation sent to the model: the task, user and assistant turns, tool turns | `gen_ai.input.messages` |
| `instructions` | the system prompt: `SOUL.md`, `AGENTS.md`, project instructions, the skills index | `gen_ai.system_instructions` |

A level is a named, monotonic set of classes. An exporter declares one or the other:

| `privacy:` | Shares, beyond `structure` | Answers |
| --- | --- | --- |
| `minimal` (default, every built-in) | nothing | how long, how many tokens, which tools, did it pass |
| `actions` | `toolArguments`, `errors` | what the agent did |
| `conversation` | `actions` + `prompts`, `completions`, `toolResults` | what was said and read |
| `full` | `conversation` + `instructions` | everything the model saw |

```yaml
kind: exporter
name: langfuse
privacy: conversation          # or: share: [toolArguments, completions]
contentMaxChars: 4000          # per message part / per attribute, structure preserved
```

`privacy` and `share` are mutually exclusive; `docket validate` refuses a document with both,
an unknown level or an unknown class.

### 2. The rules

1. **An allowlist, not a denylist.** `core/telemetry.py` holds one table,
   `ATTRIBUTE_CLASSES`, mapping every attribute any handler can emit to exactly one class. A
   handler adds a content attribute only through one function that checks the exporter's granted
   classes; nothing reaches a `Span` by key name. A new trace field is invisible to every
   destination until someone assigns it a class — the default for a new fact is *not shared*.
2. **The generic path forwards declared structure only.** `_handle_generic_event` forwards the
   structural keys declared per event type (`hook`, `policy`, `token`, `run`, `status`, …), never
   "every scalar". `approval_requested.action` moves to `toolArguments`; `error.error` to
   `errors`. Under `minimal` neither leaves any more — that closes today's leak.
3. **Class membership is per message part, not per attribute.** A conversation contains other
   classes: a tool-role turn is a tool result, an assistant tool call carries arguments, a system
   turn is instructions. Building `gen_ai.input.messages` keeps each part only if its own class
   is granted and replaces a withheld part with `{"type": "withheld", "class": "<class>"}`, so
   `share: [prompts]` never exports a file's contents through the history.
4. **Capture follows demand.** `core.telemetry.capture_classes()` returns the union of the
   classes the started exporters were granted — empty when none is enabled. `_trace_llm_call`
   records `inputMessages`, `outputMessages` and `systemInstructions` (the OTel message shape:
   `role` + `parts`) only for classes in that union. With no exporter above `minimal`, the local
   trace, harness stdout and `/traces` are byte-for-byte what they are today.
5. **Content is bounded and scrubbed once.** Captured content goes through `trace_event`, so
   `redact` scrubs secret shapes before disk and before any subscriber. Each text part is cut to
   `contentMaxChars` with a visible marker, keeping JSON structure. System instructions are
   recorded on a session's first call and whenever their SHA-256 changes; every `gen_ai.chat`
   carries `docket.instructions.sha256`.
6. **The trace stays the one signal.** Content is part of the record when it is captured, not a
   side channel into the exporter: the local JSONL is still the source of truth, and everything
   that reads it (`docket trace`, harness stdout, `GET /traces`) sees what was captured. The
   operator's own disk holds what the operator chose to share; retention (`docket trace expire`)
   applies to it unchanged.
7. **Defaults and migrations only narrow.** Every built-in ships `minimal`, including
   `otel-collector` (a collector exists to forward, so "loopback" is not "stays here"). A stored
   document still carrying the retired `payload` key loads as `minimal` with a notice naming the
   command that widens it — never as a wider level.
8. **Widening is a command, confirmed and audited.** `docket exporters privacy <name>
   <level>|--share a,b` and `enable --privacy` print the classes that will start leaving, with one
   example attribute each, and the destination host; on a TTY they ask, off one they refuse
   without `--yes`. `docket exporters add` applies the same rule to a document above `minimal`.
   Narrowing never asks. Each change audits `exporter.privacy` with from → to and the host, never
   content. A hand edit cannot be prevented; rule 9 makes it visible.
9. **Evident everywhere, including at the destination.** `docket exporters list` gains a
   `SHARES` column; `show` prints a "Leaves this host" block (class, ✓/✗, attributes); `enable`,
   `config explain` and `doctor` print the level (doctor notes `conversation`/`full` to a
   non-loopback host). Every root span carries `docket.privacy` (the level or `custom`) and
   `docket.privacy.classes`, so the destination itself shows what produced the trace.
10. **See before sharing.** `docket exporters preview <name> [--session <id>]` projects a real
    local session through that exporter's policy and prints exactly what would be sent (the
    attributes per span, content truncated for display), with no network call. `--json` prints
    the encoded OTLP document byte-for-byte.
11. **Standard names, no vendor code.** Content uses the OTel GenAI names above, which Langfuse
    reads natively. A destination expecting other names maps them through the existing `aliases`
    data, so adding a vendor's names stays a YAML edit (ADR 0014 §3).

### 3. What stands, and the boundary

ADR 0014 stands whole except `payload`/`payloadMaxChars`, which this replaces. D-24 stands: no
SDK, no sampling. The trace store's shape stays additive (three optional `llm_call` keys).

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| Classes, levels, `ATTRIBUTE_CLASSES` allowlist, per-part filtering, the generic-path fix, `capture_classes()` | **DO** | P33-1 | the enforcement point; closes the `action`/`error` leak |
| `privacy`/`share`/`contentMaxChars` in `kind: exporter`, built-ins at `minimal`, legacy `payload` → `minimal`, `start` builds the policy | **DO** | P33-2 | configurable from the exporter's own settings, as requested |
| `llm_call` captures messages, output and instructions on demand, bounded, deduplicated | **DO** | P33-3 | the content Langfuse needs; zero cost when nobody asks |
| `docket exporters privacy`, `enable --privacy`, `preview`, `SHARES`, "Leaves this host", explain/doctor lines, audit | **DO** | P33-4 | the conscious and evident half of the request |
| Docs, live proof at each level against Langfuse, canary on the real wire, close | **DO** (integrator) | P33-5 | D-37; the claim is proven by what the destination shows |
| Regex or ML scrubbing beyond `redact`'s secret shapes | **DEFER** | — | **Trigger:** a secret or personal datum observed past `redact` in a captured trace |
| Content stored locally, exported by reference (the OTel "external storage" pattern) | **DEFER** | — | **Trigger:** a destination refuses or truncates span size at `contentMaxChars` |
| A per-pod privacy cap in `pod.yaml` (may only narrow) | **DEFER** | — | **Trigger:** a second pod needing a stricter level than its exporter's |
| Per-role or per-tool levels | **CUT** | — | no measured need; classes already separate what varies |
| Sampling; exporting `audit.log` | **CUT** | — | D-24 / ADR 0014 stand |

## Test discipline

One RED behavioural test per card in the module's `SUBJECT` file. The oracle for P33-1 is a
**canary property**: every string field of every `EVENT_TYPES` payload (and every captured
message part) is seeded with a unique marker; projected and encoded under `minimal` the OTLP
bytes contain no marker, and under each level and each single-class `share` markers appear only
in attributes of granted classes. P33-3's negative case: with no exporter above `minimal`, a turn
writes an `llm_call` record byte-identical to today's. P33-4's: widening off a TTY without
`--yes` exits 1 and writes nothing. The integrator owns the seam test between P33-1 (reads
`inputMessages`/`outputMessages`/`systemInstructions`) and P33-3 (writes them): the real
`_trace_llm_call` into the real projection. No worker probes a real vendor host; the integrator
sends one real dispatch to Langfuse at `minimal`, `actions` and `conversation` and records what
its Input/Output show.
