# Context-efficient agent handoffs

Read this when designing or reviewing cross-agent/coordinator handoffs. It governs development
context, not the product's persisted runtime handoff schema.

## Preserve decisions, omit replay

A receiving agent needs the current objective, authority, scope boundary, unresolved decisions,
evidence locators, validation state, and next action. It does not need the prior conversation,
search narrative, successful command output, whole diff, or copied source/spec prose.

Prefer this reduction order:

1. Remove unrelated sources and completed reasoning.
2. Replace source copies with stable path/section/test/artifact locators.
3. Send one selected card and one owning spec section.
4. Collapse passing evidence to command plus result count/status.
5. Preserve the first actionable failure, unresolved risk, and rollback/side-effect state.

Never omit a user constraint, destructive-action boundary, active owner, dependency, failed gate,
uncommitted path, unresolved decision, or persisted-state compatibility risk merely to shorten the
handoff.

## Evidence ledger

Record each load-bearing fact once:

```text
Fact | measured / inferred | source locator | affected card/decision
```

Use measured only for direct output/state/wire evidence. Market comparison, likely contention, or
predicted savings are inferences until exercised. Workers cite the ledger row rather than repeating
its prose.

## Coordinator-to-worker packet

Send identifiers and locators sufficient for a minimal-context worker:

```text
card + owner + base/worktree
goal + non-goals
allowed and forbidden ownership
decision/trigger/spec/test/live-path locators
RED and validation commands
dependency + merge order + mutable-state isolation
```

When the repository provides a card extractor, use it instead of loading or copying the board.
When a durable phase handoff exists, read only the current-state and selected-lane sections.

## Worker-to-coordinator delta

Report user-visible behavior first, then changed paths/functions, spec version, acceptance oracles,
compact test outcomes, missing evidence, remaining work, contention, and one next action. Target
1,500–3,000 UTF-8 characters for routine work. Link large artifacts and logs; include only the first
actionable failure inline.

Do not relay one worker's raw handoff through another worker. The coordinator is the fan-in point
and sends a newly compiled packet to any dependent lane.

## Correctness checks

- A receiver can identify exactly what is complete, partial, blocked, and still unverified.
- No duplicated task prose or raw conversation is needed to resume.
- Tool-call/result, decision/result, and unresolved-action pairs stay atomic.
- Central files and mutable environments have one named owner.
- A failed or skipped gate is visible rather than summarized as success.
- Before/after token or byte savings are labeled measured only when both values were captured.
