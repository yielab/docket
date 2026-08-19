# Live context path invariants

Read this for changes touching `core/dispatch.py`, `edges/adapters/docket_runtime.py`,
`core/agent_loop.py`, `core/session.py`, `core/context.py`, `core/handoff.py`, identity/memory
composition, or MCP/tool output.

## Prove the wire

- Trace the default production caller. Implemented and unit-tested machinery with no live consumer
  is still absent product behavior.
- Configuration has one owner in `config.py`; context-sensitive values must be resolved at call
  time when tests/operators can change them after import.
- MCP tools load before role narrowing. Every adapted capability must still cross
  `dispatch_tool`; remote names never weaken kind-based denial.

## Preserve history integrity

- An assistant message with tool calls and every answering tool result is one atomic unit.
- Truncated model responses are neither dispatched nor persisted.
- Compaction is fail-closed: a failed/empty summary leaves stored history byte-identical.
- A live compactor needs an explicit recursion barrier. Its summarizer must not re-enter compaction
  on the same session, and its session/key/persistence behavior must be specified and tested.
- Emit a trace for attempted/succeeded/failed compaction with counts, never raw sensitive history.

## Budget honestly

- `core.context.estimate_tokens` is an approximation for fitting context, never billed usage.
- `TokenUsage` is measured backend usage for the hard turn budget.
- Bound every model-visible tool result, including MCP, through the same operator-configurable
  ceiling and visible truncation contract.
- Test against a deliberately small context budget. A large hosted window can hide redundant
  history and oversized tool output.

## Acceptance evidence

- RED test reaches the default path, not only the helper.
- Atomic tool units survive the boundary.
- No-op path makes no summarizer call and no unnecessary write.
- Failure path preserves prior history and reports/ traces the failure.
- Cross-role handoff does not carry the previous role's raw session in addition to its typed artifact
  unless a spec explicitly opts into that cost.
