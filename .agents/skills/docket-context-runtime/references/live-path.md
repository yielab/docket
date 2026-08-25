# Live context path invariants

Read this for changes touching `core/dispatch.py`, `edges/adapters/docket_runtime.py`,
`core/agent_loop.py`, `core/session.py`, `core/context.py`, `core/handoff.py`, identity/memory
composition, or MCP/tool output.

## Prove the wire

- Trace the default production caller. Implemented and unit-tested machinery with no live consumer
  is still absent product behavior.
- Locate the configuration owner named by the owning spec and resolve it at the contract's stated
  time. MCP output currently reads `config.py` per call; built-ins expose the imported
  `toolbox.MAX_OUTPUT_CHARS` override. Test the declared owner with the same constructed runtime
  before and after mutation; unifying owners is a separate behavior change, not assumed evidence.
- MCP tools load before role narrowing. Every adapted capability must still cross
  `dispatch_tool`; remote names never weaken kind-based denial.

## Preserve history integrity

- An assistant message with tool calls and every answering tool result is one atomic unit keyed by
  tool-call ID. Reordered results must pair by ID; duplicate, orphaned, or missing IDs stay visibly
  pending or fail locally rather than producing a half-unit.
- Truncated model responses are neither dispatched nor persisted.
- Compaction is fail-closed: a failed/empty summary leaves stored history byte-identical.
- A live compactor needs an explicit recursion barrier. Its summarizer must not re-enter compaction
  on the same session, and its session/key/persistence behavior must be specified and tested.
- A successful summary gets one reload and fit recheck for the source revision it summarized. If it
  still does not fit, do not summarize that revision in a loop; apply another bounded reduction or
  fail locally without transport.
- Emit a trace for attempted/succeeded/failed compaction with counts, never raw sensitive history.

## Budget honestly

- `core.context.estimate_tokens` is an approximation for fitting context, never billed usage.
- `TokenUsage` is measured backend usage for the hard turn budget.
- Bound every model-visible tool result, including MCP, through the same operator-configurable
  ceiling and visible truncation contract. Locate the owning contract and assert its unit, marker,
  retained metadata, and whether the marker/envelope counts inside the ceiling; do not substitute a
  substring assertion for the contract.
- Test against a deliberately small context budget. A large hosted window can hide redundant
  history and oversized tool output.
- In a recording test, track prospective request sequence separately from actual backend calls; a
  preflight rejection makes no backend call. Keep the shipped `request_fit` trace aligned with its
  owning spec: purpose (`task` or `compaction`), fit status, estimated input, output reserve,
  registered window, and estimate marker. New telemetry fields require a spec change first.

## Acceptance evidence

- RED test reaches the default path, not only the helper.
- Atomic tool units survive the boundary.
- Multi-call results in reverse order pair by ID; incomplete units never cross the boundary as if
  complete.
- No-op path makes no summarizer call and no unnecessary write.
- Failure path preserves prior history and reports or traces the failure.
- Cross-role handoff does not carry the previous role's raw session in addition to its typed artifact
  unless a spec explicitly opts into that cost.
