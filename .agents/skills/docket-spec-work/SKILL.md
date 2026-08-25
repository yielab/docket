---
name: docket-spec-work
description: Implement or change Docket behavior with its spec-first, test-first contract and proportional validation. Use for product code, CLI behavior, persisted shapes, or user-facing behavior claims; not for planning-only work.
---

# Docket Spec Work

Start from the behavior boundary, not from a broad repository tour.

1. Find the owning row in `specs/README.md`, then read only that spec and neighboring tests.
2. Trace the real caller into the implementation. A writer, parser, flag, or helper without a live
   caller is not evidence of a shipped capability. Do not expand explicitly requested internal
   scaffolding into a public feature; describe it as unshipped until a caller consumes it.
3. Classify the contract change. New or changed behavior requires the current-state spec's
   requirement, version, status, last-updated date, and changelog first. A clarification of already
   contracted behavior needs live evidence but no invented version churn; purely editorial text
   gets proportional documentation checks.
4. For a behavior change, build a small case matrix before the RED test: representative success,
   closest rejection or failure, and any compatibility/retry/idempotency boundary the contract
   actually exposes. For each case, name initial state, public action, result, durable side effects,
   and oracle. A docs-only claim needs the representative live case, not artificial edge cases.
5. For a behavior change, add a behavioral test that fails for the intended reason and run it before
   implementation. For a clarification or editorial change, confirm existing behavioral evidence;
   add a test only when the claim lacks coverage, without inventing a RED state. Prefer a property or
   live-path assertion over wording, source-line, or fixture-only checks. Mock true external edges,
   not the caller or state transition being proved.
6. Implement the smallest coherent change, keeping `cli -> core -> edges` inward-only boundaries.
7. Run the focused test and static check while iterating. Before handoff, run the gates required by
   the affected surface.

Read [references/validation.md](references/validation.md) when selecting final gates or when CLI,
packaging, specs, documentation claims, or dependency bounds are affected.

Read [references/real-world-tests.md](references/real-world-tests.md) when designing realistic
product fixtures. Skill maintainers use
[references/forward-tests.md](references/forward-tests.md) only as an evaluator-side rubric after
the evaluated agent finishes. An evaluated agent must not load that rubric.

When a persisted shape changes, exercise the real reader and sole writer with an empty-state fixture
and every prior shape the contract promises to support. Assert semantic round-trip behavior,
preservation of unknown/unaffected data, and failure atomicity when migration can write.

Keep test output out of the conversation unless it explains a failure. Report command + outcome,
not full logs. Never change a golden or metrics/spec validator merely to turn a gate green.

Before the final handoff, compare the delivered behavior against every acceptance criterion and use
`AGENTS.md`'s end-of-work control. Explain the feature at product level, then state what actually
shipped. A focused pass with missing full gates is `partial`, not `complete`; a skipped environment
case is missing evidence unless the contract explicitly marks it expected.

Name the exact failed check or unimplemented behavior instead of saying only “there are issues.”
Recommend one next action that closes the highest-impact remaining gap. Suggest parallel work only
when its owning spec and touched code/state do not overlap this change; roadmap scheduling still
belongs to the `docket-roadmap` skill.

When a CLI contract accepts free-form text across one or more positionals, or promises equivalent
quoted and split forms, test the real parser boundary with one argv item and the equivalent split
positional argv. Shell quote delimiters are gone before application parsing. Preserve a contract
that intentionally accepts exactly one argv item instead of inventing split-form support. Assert the
exact value that reaches persisted or dispatched state, not only the success message; keep literal
quote characters out of argv fixtures, and include an adjacent option only when that command has one
that reconstruction could consume.
