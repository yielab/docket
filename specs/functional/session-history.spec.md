# Session History Specification

**Version**: 1.8.0
**Status**: Implemented and live. `core/agent_loop.py` loads, compacts, and appends this durable
history on the production `DocketDriver` path. Wave 20 card W20-C2 wired the previously dormant
compactor before each task-completion backend call. Wave 20 card W20-C4 gives every pod-dispatch
pipeline step its own history key while preserving the task-wide trace identity. Wave 25 adds a
bounded range mode so per-request fit can preserve the current task verbatim while compacting only
older history or completed same-turn tool units.
**Last Updated**: 2026-10-18

## Purpose

Docket owns the durable state that survives between and inside agent turns: the `HEARTBEAT.md`
task ledger, conversation registry, memory logs, hash-chained audit log, per-hop traces, and the
turn history replayed on each model call (see `workspace-structure.spec.md`, `audit.spec.md`).
This specification defines the bounded turn-history store: `core/session.py`.

## Scope

This specification covers:

- The on-disk storage layout for one session's turn history, keyed by an opaque docket session
  coordinate. Interactive/scoped turns use `agent:<id>:<project>`; pod-dispatch turns use the
  step-scoped coordinate defined by `pod-dispatch.spec.md`.
- Lossless round-trip serialisation of a chat message and its tool calls
- The atomic tool-call/tool-result unit that compaction must never split, and the fail-closed
  contract when the summarisation call itself fails
- How a session's compaction budget is resolved, and the distinction between a *measured* token
  count (real, from the completion endpoint) and an *estimated* one (the existing bytes/divisor
  approximation)

This specification does NOT cover:

- The rest of the turn loop (`core/agent_loop.py`); this spec covers only the compactor boundary
  it consumes, while `agent-loop.spec.md` owns trigger ordering, usage accounting, and tracing
- The chat-completion wire protocol or the gated tool registry (`core/llm.py`, `core/tools.py`,
  ROADMAP Phase 19 P19-1/P19-2) — this spec only depends on the `ChatMessage`/`ToolCall`/
  `TokenUsage` shapes those modules define
- The hop-to-hop context compiler used by the existing pod-dispatch pipeline
  (`core/context.py`'s `compile_artifact`/`HandoffArtifact.DROP_ORDER`, see
  `pod-dispatch.spec.md`'s "Bounded hop prompts") — session compaction reuses that module's
  token-estimation and per-role budget primitives (`estimate_tokens`, `budget_for_role`) but
  implements its own compaction strategy, documented below, because a list of chat messages is
  not a `HandoffArtifact`
- Pod memory (`core/pod_memory.py`) — a separate store with its own rules (workspace-structure.spec.md
  "Pod memory"); the daily-log distillation that session compaction once mirrored was removed
  (ADR 0028 point 7). Compaction keeps the fail-closed call pattern (decision D-18)

## Requirements

### Storage layout and isolation

1. Turn history **MUST** be persisted durably by the exact opaque session key supplied by the
   caller, so it survives a process restart. `core/session.py` **MUST NOT** parse, normalize, or
   collapse interactive and pod-dispatch key formats.
2. Each session's history **MUST** be stored under its own subdirectory, so that reading,
   appending to, or compacting one session's history **MUST NOT** be able to corrupt, or block
   on, another session's history.
3. A session key **MUST** map to its storage location via a deterministic, collision-free
   encoding, so that no two distinct session keys can ever resolve to the same file.
4. An unknown session key **MUST** load as an empty history rather than an error.
5. Introducing a new caller-level key format **MUST NOT** delete, rename, or migrate an existing
   session directory. Records written under older keys remain directly readable through the same
   `load_session`/`load_messages` APIs.

### Message round-trip

6. Appending messages to a session and reading them back **MUST** reproduce every message field
   exactly, including a tool-call-carrying message's `tool_calls` (each call's `id`/`name`/
   `arguments`), and a tool-result message's `tool_call_id` and `name`.
7. Measured token usage (real per-call counts reported by the completion endpoint) **MAY** be
   recorded alongside a session's history and **MUST** accumulate additively across appends.
8. Appending to the same session key concurrently **MUST NOT** be able to silently drop either
   append's messages.

### Compaction and atomicity

9. An assistant message carrying one or more tool calls, together with every tool-role message
   answering one of those calls, **MUST** be treated as one atomic unit that compaction never
   splits.
10. Compaction **MUST NOT** produce a resulting history containing an orphaned tool result (a
   tool-role message answering no preceding call in that same history) or an orphaned tool call
   (a call with no later answering tool-role message) — including the boundary case where a
   naive size-based cut would otherwise land in the middle of one atomic unit.
11. When a session's estimated size exceeds its budget, compaction **MUST** replace the oldest
    atomic units with a single summarising message rather than truncating or deleting them
    outright.
12. Whole-session compaction **MUST** always retain at least the single most-recent atomic unit,
    even if that unit alone exceeds the configured budget. A caller selecting a bounded message
    range **MAY** explicitly allow every unit in that range to be summarized only when at least one
    unselected message remains as the verbatim conversational anchor.
13. Compaction **MUST** always retain any leading system-role messages verbatim.

### Budgeting honesty

14. A session's compaction budget **MUST** be resolved via the same per-role token-budget
    mechanism the hop-to-hop context compiler uses, not a second, independently-tunable table.
    `core.context.budget_for_role` **MAY** additionally accept a resolved model context window to
    compute a documented window-share default for a role with no positive archetype `token_budget`
    (`core.context.resolve_window_share_tokens`, see `agent-loop.spec.md`'s requirement 30); neither
    `compact_session` nor its `core/agent_loop.py` caller passes that window, so a session's
    resolved compaction budget **MUST** remain exactly `context.budget_for_role(role)` with no
    window argument, byte-for-byte unchanged by this option existing.
15. Token counts used to decide whether to compact **MUST** be computed via the existing
    bytes/divisor approximation and **MUST NOT** be described as an exact count.
16. Measured usage (real counts from the completion endpoint) and estimated size (the
    bytes/divisor approximation) **MUST** be recorded and named distinctly in code and in any
    user-facing text, and **MUST NOT** be combined into one number or used interchangeably.

### Fail-closed summarisation

17. `compact_session`'s injected summarizer **MUST** retain the five-argument driver-shaped port,
    but its live `core/agent_loop.py` adapter **MUST** use the already-resolved `ChatBackend` port
    directly for one tool-free completion. It **MUST NOT** call `run_agent_turn`, resolve a second
    backend, or implement a vendor client.
18. If the summarisation call fails, or replies with nothing usable, compaction **MUST** leave
    the session's stored history completely unchanged and report failure — mirroring the
    fail-closed call pattern decision D-18 set for docket's self-originated model calls.
19. Compaction **MUST NOT** ever persist a candidate result that would contain an orphaned tool
    call or tool result, even if that would require refusing to persist an otherwise-valid
    summarisation.
20. The summarizer session key **MUST** be distinct from the target session key. The live adapter
    persists no summarizer messages under either key; the distinct key remains part of the port
    contract so a future adapter cannot accidentally write prompts into the history it replaces.
21. `compact_session` **MUST** reject nested compaction before acquiring a session lock or calling
    another summarizer. This re-entry guard is independent of session key, so changing keys cannot
    turn recursive summarization into infinite regress.
22. Every result **MUST** report before/after message counts and before/after *estimated* tokens.
    Failure reports identical before/after values; no-op reports the unchanged values; success
    reports the persisted candidate. These fields **MUST NOT** be presented as measured usage.
23. The complete summarizer prompt for each compaction round **MUST** fit a bounded estimated-token
    input budget. By default that input budget is the role's configured history budget (independent
    of a caller's one-off target-budget override); an explicit input override exists for
    deterministic tests, not as a second role-budget registry.
24. When all units selected by the compaction plan do not fit one summary prompt, compaction
    **MUST** summarize the largest fitting oldest prefix, preserve every remaining unit, and repeat
    hierarchically until every selected raw old unit has been folded into bounded summaries. No
    intermediate candidate may be written. A degenerate target smaller than the irreducible summary
    marker plus the mandatory newest unit **MAY** finish above target rather than repeatedly
    re-summarizing the same summary without new information.
25. A system message produced by compaction **MAY** be summarized again in a later round. Any real
    leading system message that was not produced by compaction **MUST** remain byte-identical.
26. Every round **MUST** reduce the candidate's estimated size and the operation **MUST** have a
    deterministic round cap. Failure to make progress, exceeding the cap, or finding one atomic
    unit whose complete summary prompt cannot fit **MUST** fail closed without writing.
27. `groups_summarized` **MUST** count every atomic group processed across all rounds. The result
    **MUST** also report the number of summary rounds and the largest estimated summary-prompt size,
    named explicitly as estimates.
28. An optional half-open compaction range **MUST** preserve every message outside that range
    byte-for-byte and **MUST** reject a boundary that splits an assistant/tool-result atomic unit.
    Range indexes apply to the record loaded under the session lock. This mode exists for the live
    request-fit caller to compact prior history separately from completed same-turn tool units while
    retaining the current user task verbatim; it **MUST NOT** introduce an in-memory-only history
    that differs from the durable record sent after reload.

### Request projection

29. `condense_history(messages, keep=HISTORY_KEEP_FULL_RESULTS, budget=HISTORY_FULL_RESULTS_CHARS)`
    **MUST** be a pure function: the
    same messages always yield the same bytes, the input list and its messages are never changed,
    and nothing is read from or written to disk. It is applied to the request only; the stored
    history keeps every byte (`core/agent_loop.py::_TurnState.messages_for_durable` is its one
    live caller).
30. The last `keep` (at least 1) answered `tool` messages stay whole; older ones stay whole too,
    newest first, while the characters of all whole results fit in `budget` (6,000, one default
    `read` window). From the first that does not fit, it and every older one **MUST** have their
    `content` replaced by `[<tool> <path|command|pattern|url>: N lines, M characters, already
    seen and omitted; call <tool> again only for exact text you still need]`, built from the matching call, unless the notice is not shorter
    than the content. Each message keeps its role, `tool_call_id` and `name`. A result beginning
    `ERROR:`, `REFUSED [` or `AWAITING APPROVAL:` stays whole up to 400 characters and is
    otherwise cut to its first 400 with a count of the rest. User and system messages are never
    changed.
31. For a call whose result was condensed, the string arguments `content` (`write`),
    `new_string` and `old_string` (`edit`) **MUST** be replaced by `[wrote <path>: N characters]`
    (`[replaced <path>: N characters]` for `old_string`) when that is shorter; the other keys and
    the call id are kept and the arguments remain a JSON object. Arguments that do not parse as a
    JSON object are left as they are. A message that gains a result later changes only at that
    message, so the request prefix before it is byte-identical between consecutive requests.

## Interface Contracts

### Module API (`docket.core.session`)

```python
# storage models
class StoredToolCall(BaseModel): ...          # id, name, arguments
class StoredMessage(BaseModel): ...           # role, content, tool_calls, tool_call_id, name
class MeasuredUsage(BaseModel): ...           # inputTokens, outputTokens, cachedTokens, turns
class SessionRecord(BaseModel): ...           # sessionKey, created, updated, messages, usage

# pure compaction planning
def group_atomic_units(messages: Sequence[ChatMessage]) -> list[list[ChatMessage]]: ...

# request projection (pure; requirements 29-31)
HISTORY_KEEP_FULL_RESULTS = 2
HISTORY_FULL_RESULTS_CHARS = 6_000
def condense_history(
    messages: Sequence[ChatMessage], keep: int = HISTORY_KEEP_FULL_RESULTS,
    budget: int = HISTORY_FULL_RESULTS_CHARS,
) -> list[ChatMessage]: ...
def find_orphaned_tool_messages(messages: Sequence[ChatMessage]) -> list[int]: ...
def find_unanswered_tool_calls(messages: Sequence[ChatMessage]) -> list[str]: ...

class CompactionPlan:                          # keep_head, to_summarize, keep_tail, .needed
    ...

def plan_compaction(
    messages: Sequence[ChatMessage], budget_tokens: int, *, keep_latest_unit: bool = True,
) -> CompactionPlan: ...

# durable I/O (edges/store.py underneath)
def load_session(session_key: str, *, sessions_dir: Path | None = None) -> SessionRecord: ...
def load_messages(session_key: str, *, sessions_dir: Path | None = None) -> list[ChatMessage]: ...

def append_messages(
    session_key: str,
    messages: Sequence[ChatMessage],
    *,
    usage: TokenUsage | None = None,
    now: str | None = None,
    sessions_dir: Path | None = None,
) -> SessionRecord: ...

# the shape a caller's driver must satisfy
SessionSummaryRunner = Callable[[str, str, str, int, dict[str, str] | None], TurnResult]

class CompactionResult:                        # plus summary rounds/prompt max and before/after counts
    ...

def compact_session(
    session_key: str,
    *,
    role: str,
    agent_id: str,
    summarizer: SessionSummaryRunner,
    summarizer_session_key: str | None = None, # default: derived key distinct from session_key
    budget_tokens: int | None = None,          # default: context.budget_for_role(role)
    summary_input_budget_tokens: int | None = None, # default: context.budget_for_role(role)
    compact_range: tuple[int, int] | None = None, # half-open; boundaries must be atomic
    keep_latest_unit: bool = True, # False requires a non-empty unselected anchor
    timeout: int | None = None,
    label: str = "",
    now: str | None = None,
    sessions_dir: Path | None = None,
) -> CompactionResult: ...
```

### Wire format (one session's `session.json`)

```json
{
  "sessionKey": "agent:demo-lead:demo",
  "created": "2026-07-31T12:00:00Z",
  "updated": "2026-07-31T12:05:00Z",
  "messages": [
    { "role": "system", "content": "be helpful", "toolCalls": [], "toolCallId": "", "name": "" },
    { "role": "user", "content": "read notes.md", "toolCalls": [], "toolCallId": "", "name": "" },
    {
      "role": "assistant",
      "content": "",
      "toolCalls": [{ "id": "call_1", "name": "read", "arguments": "{\"path\": \"notes.md\"}" }],
      "toolCallId": "",
      "name": ""
    },
    {
      "role": "tool",
      "content": "alpha\nbeta\n",
      "toolCalls": [],
      "toolCallId": "call_1",
      "name": "read"
    }
  ],
  "usage": { "inputTokens": 512, "outputTokens": 64, "cachedTokens": 0, "turns": 2 }
}
```

### Storage path

```text
$SESSIONS_DIR/<percent-encoded session key>/session.json
```

`$SESSIONS_DIR` defaults to `~/.docket/sessions` (`SESSIONS_DIR` in `config.py`, overridable
via the `SESSIONS_DIR` environment variable, matching every other docket-owned path).

### Return values

- `CompactionResult.ok=False` **MUST** mean the on-disk record for that session key was not
  written at all by that call.
- `CompactionResult.compacted=True` only ever appears alongside `ok=True`, and distinguishes "a
  summarisation actually ran" from "nothing needed compacting".

## Examples

### Round trip

```python
from docket.core import session as sess
from docket.core.llm import ToolCall, assistant, tool_result, user

call = ToolCall(id="call_1", name="read", arguments='{"path": "notes.md"}')
sess.append_messages("agent:demo-lead:demo", [
    user("read notes.md"),
    assistant("", tool_calls=[call]),
    tool_result(call, "alpha\nbeta\n"),
])

history = sess.load_messages("agent:demo-lead:demo")
# history[1].tool_calls == [call]
# history[2].tool_call_id == "call_1"
```

### Compaction preserving an atomic unit

Given a session whose oldest content is `[user_msg, assistant_tool_call_msg, tool_result_msg]`
followed by recent messages that alone fit the budget, `plan_compaction` either keeps
`assistant_tool_call_msg` and `tool_result_msg` together in `keep_tail`, or folds both of them
together into `to_summarize` — never one without the other. `compact_session` then either
persists the pair verbatim or replaces both with one summarising `system` message; the resulting
history always passes `find_orphaned_tool_messages(...) == []` and
`find_unanswered_tool_calls(...) == []`.

### Fail-closed compaction

```python
def failing_driver(agent_id, session_key, message, timeout, env=None):
    return TurnResult(False, "", 0.0, {}, "timed out", failure_kind="timeout")

result = sess.compact_session(
    "agent:demo-lead:demo", role="lead", agent_id="demo-lead",
    summarizer=failing_driver, budget_tokens=1,
)
# result.ok is False; sess.load_messages(...) is byte-identical to before the call.
```

## Validation

### Pre-conditions

- A session key **MUST** be a non-empty string; this module treats it as opaque (it does not
  parse or validate the `agent:<id>:<project>` shape itself — see `session-scoping.spec.md` for
  where that format is defined and enforced).
- `compact_session` **MUST** be given a `summarizer` matching the documented 5-argument shape.

### Post-conditions

- After `append_messages`, `load_messages` for the same session key **MUST** include every
  appended message, in order, with every field intact.
- After a `compact_session` call with `ok=True, compacted=True`, the stored history **MUST**
  contain no orphaned tool call or tool result.
- After a `compact_session` call with `ok=False`, the stored history **MUST** be unchanged from
  immediately before the call.

### Invariants

- Two distinct session keys **MUST NOT** ever be able to read or write each other's history.
- `group_atomic_units` **MUST** partition any message list into groups that a compaction pass can
  only keep or replace as a whole — never a boundary internal to one assistant/tool-call group.
- Estimated and measured token figures **MUST** remain distinct fields, never merged.
- A compaction summarizer **MUST NOT** be able to re-enter compaction, even with another key.
- `condense_history` **MUST NOT** change what `load_messages` returns; it shapes a request only.

## Changelog

### Version 1.8.0 (2026-10-18)

- The condensation notice says the result was already seen and asks for a new call only for
  exact text still needed (requirement 30). "call <tool> again if needed" read as an invitation:
  in the Phase 44 rerun a model re-read a file it had just read until the no-progress stop.

### Version 1.7.0 (2026-10-18)

- Condensation counts characters as well as results (requirement 30). Older results stay whole
  while all whole results fit in `HISTORY_FULL_RESULTS_CHARS` (6,000); from the first that does
  not fit, it and every older one become notices, so a result only ever moves from whole to
  notice and the request prefix stays stable. Found by the Phase 44 real rerun: with K=2 alone,
  a model making one call per round lost a 1,099-character README two rounds after reading it,
  re-read it and a 2,362-character script in a loop (16 calls, 44,031 input tokens, nothing
  written) until the no-progress stop ended the step. Replay bench, policy `phase44`, sent as a
  fraction of baseline (critic / implementer-a / implementer-b / researcher): 0.68 / 0.25 /
  0.50 / 0.45 at 6,000, against 0.63 / 0.25 / 0.49 / 0.37 with the count alone. The bench
  replays the recorded calls, so it shows the cost of keeping more and never the re-reads it
  saves.

### Version 1.6.0 (2026-10-18)

- Request projection (requirements 29-31, ADR 0028 section 4): `condense_history` turns tool
  results older than the last `HISTORY_KEEP_FULL_RESULTS` (2) into one-line notices and large
  old `write`/`edit` arguments into character counts, applied only when a request is built.
  K chosen on the replay bench (`context_replay.py`, committed fixtures, policy `phase44` =
  tool output then condensation; sent tokens as a fraction of baseline, per step critic /
  implementer-a / implementer-b / researcher, then total): K=1 0.58 / 0.20 / 0.44 / 0.33
  (0.38), K=2 0.63 / 0.25 / 0.49 / 0.37 (0.43), K=3 0.65 / 0.29 / 0.56 / 0.40 (0.47). K=2 is
  the largest that keeps every step under half where any K can: the critic's floor is its
  system prompt and tool schemas (about 3,200 measured tokens), which no K reaches, and K=3
  puts implementer-b over half. The provider cache loses only the last two messages.

### Version 1.5.0 (2026-09-26)

- P26-3 clarifies requirement 14: `core.context.budget_for_role` gained an optional window-share
  resolution for its unregistered-role fallback (`agent-loop.spec.md`'s requirement 30 owns the
  formula), but neither `compact_session` nor `core/agent_loop.py`'s call to it passes a window, so
  a session's resolved compaction budget is unaffected — still exactly
  `context.budget_for_role(role)` with no window argument. No compaction behaviour changed.

### Version 1.4.0 (2026-08-22)

- W25-C2 adds fail-closed ranged compaction: the request-fit loop can preserve the exact current
  task outside the selected range while atomically summarizing older history or completed
  same-turn tool units, then reload the single durable result before transport.

### Version 1.3.0 (2026-08-19)

- **Wave 20, card W20-C4.** Documented caller-owned opaque history coordinates and the
  non-destructive compatibility rule that keeps existing task-wide session records readable when
  pod dispatch begins writing step-scoped records.

### Version 1.2.0 (2026-08-19)

- **Wave 20, card W20-C2b.** Bounded every summarizer prompt and made oversized aggregate history
  compact through atomic, hierarchical rounds. Intermediate summaries remain in memory until the
  final candidate fits; any later failure leaves the original record untouched.

### Version 1.1.0 (2026-08-19)

- **Wave 20, card W20-C2.** Wired compaction into the live agent loop. The live summarizer is a
  non-recursive, tool-free call through the already-resolved `ChatBackend`; it persists no
  summarizer conversation. Added isolated summarizer-key, re-entry-guard, and before/after
  estimated-size result contracts.

### Version 1.0.0 (2026-07-31)

- Initial specification: durable per-session turn history, lossless message round-trip,
  atomic tool-call/tool-result compaction, and fail-closed summarisation (ROADMAP Phase 19 P19-4).
