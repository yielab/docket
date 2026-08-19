---
name: docket-context-runtime
description: Diagnose or change Docket session history, context compilation, handoffs, memory, agent-loop budgets, tool-output limits, or MCP context. Use for live-turn context efficiency and correctness; not for generic feature work.
---

# Docket Context Runtime

Use this together with `$docket-spec-work` for behavior changes.

Begin with targeted searches for the exact setting/helper and every caller. Build the live path from
dispatch through driver, loop, session, and backend before proposing a fix. Distinguish:

- compiled hop context: estimated tokens;
- one turn's hard budget: measured backend usage;
- durable session history: stored messages and compaction.

Do not claim one budget bounds another. Avoid sending both raw cross-role history and a typed handoff
unless the contract explicitly requires both.

Read [references/live-path.md](references/live-path.md) before editing session compaction, loop
composition, handoff/session keys, MCP output, or memory injection. It contains the non-obvious
atomicity, recursion, trace, and small-context validation requirements.

Prefer deterministic reduction in this order: omit irrelevant sources, select a bounded section,
use typed artifacts, visibly truncate low-priority fields, then summarize. Never silently truncate a
tool call, tool result, decision, or unresolved action.
