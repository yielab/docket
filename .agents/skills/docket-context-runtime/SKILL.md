---
name: docket-context-runtime
description: Diagnose or change Docket session history, context compilation, handoffs, memory, agent-loop budgets, tool-output limits, or MCP context. Use for live-turn context efficiency and correctness; not for generic feature work.
---

# Docket Context Runtime

Use this together with the `docket-spec-work` skill for behavior changes.

Begin with targeted searches for the exact setting/helper and every caller. Build the live path from
dispatch through driver, loop, session, and backend before proposing a fix. Distinguish:

- compiled hop context: estimated tokens;
- one turn's hard budget: measured backend usage;
- durable session history: stored messages and compaction.

For an overflow, capture the exact prospective request ordinal and break it into system context,
replay/active-turn messages, tool schemas, protocol overhead, and requested output reserve. Record
separately whether transport was attempted. Compare the request with the selected provider/model's
live registered window. Label byte-ratio or payload estimates as estimates; endpoint tokenizer
counts are measured only when the endpoint reports them.

Distinguish the prospective request sequence from backend transports actually attempted in the
incident evidence and recording test. Use the shipped trace vocabulary from the owning spec:
`purpose=task|compaction`, fit status, estimated input, output reserve, registered window, and the
estimate marker. Do not invent ordinal or transport-count trace fields without a scoped spec change.

Do not claim one budget bounds another. Avoid sending both raw cross-role history and a typed handoff
unless the contract explicitly requires both.

Read [references/live-path.md](references/live-path.md) before editing session compaction, loop
composition, handoff/session keys, MCP output, or memory injection. It contains the non-obvious
atomicity, recursion, trace, and small-context validation requirements.

Read [references/provider-compatibility.md](references/provider-compatibility.md) when changing a
model endpoint, hosted gateway, provider credential, model id, or gateway-reported usage/context.

Read [references/real-world-tests.md](references/real-world-tests.md) when reproducing a context
incident or designing its RED test. Skill maintainers use
[references/forward-tests.md](references/forward-tests.md) only as an evaluator-side rubric after
the evaluated agent finishes. An evaluated agent must not load that rubric.

Read [references/handoff-economy.md](references/handoff-economy.md) when designing or reviewing a
cross-agent/coordinator handoff. Send decisions, scope, unresolved work, validation state, and
evidence locators—not prior conversation, duplicated task/spec prose, raw logs, or whole diffs.

Prefer deterministic reduction in this order: omit irrelevant sources, select a bounded section,
use typed artifacts, visibly truncate low-priority fields, then summarize. Never silently truncate a
tool call, tool result, decision, or unresolved action.

At handoff, apply `AGENTS.md`'s end-of-work control and describe the user-visible context improvement
before the mechanism. Return a delta that names changed paths/functions, acceptance oracles,
compact command outcomes, missing evidence, contention, and one next action; link large artifacts.
Report token/byte reduction as measured only when before/after evidence exists; otherwise label it
an inference. Name any remaining duplication, overflow path, atomicity risk, or live-path gap
explicitly.

The next ideal context task should target the largest measured remaining waste or correctness risk.
Parallel context work is safe only when the lanes have independent history/trace identities and do
not touch the same compiler, loop, session, handoff, budget, or live endpoint state.

Preflight every imminent model request, including compaction calls and later tool-loop iterations;
include advertised tools and an output reserve. A pre-turn compaction does not bound messages added
during the active turn. When reduction is required, preserve assistant tool calls with every
answering result as atomic units keyed by tool-call ID, reload the accepted compacted state, and
retry the fit check. Do not compact the same stored revision repeatedly: after one accepted summary
and recheck, use another bounded reduction or fail locally. If the irreducible request cannot fit,
fail before transport with an actionable reason; never silently cut a task, tool decision/result,
or unresolved action.
