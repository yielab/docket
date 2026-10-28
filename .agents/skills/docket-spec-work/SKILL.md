---
name: docket-spec-work
description: Implement or change Docket behavior with its spec-first, test-first contract and proportional validation. Use for product code, CLI behavior, persisted shapes, or user-facing behavior claims; not for planning-only work.
---

# Docket Spec Work

Start from the behavior boundary, not from a broad repository tour.

1. Find the owning row in `specs/README.md`. Start with the card-named requirements, invariants
   and targeted test classes; expand to other sections only when those
   sources cross-reference them. Do not read a large spec or test module end to end by default.
2. Inventory callers with targeted `rg`, then inspect one representative public caller plus every
   caller whose return, error, or side-effect semantics the change can alter. A writer, parser,
   flag, or helper without a live caller is not evidence of a shipped capability. Do not expand
   explicitly requested internal scaffolding into a public feature; describe it as unshipped until
   a caller consumes it.
3. Classify the contract change. New or changed behavior requires the current-state spec's
   requirement, version, status and last-updated date first (a spec has no changelog; its history
   is `git log`). A clarification of already
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
   not the caller or state transition being proved. Place the test where `specs/test-framework.md`
   §"Lanes and placement" says: the unit file named for the module (declare `SUBJECT`), or
   `integration/` when several modules or a real process boundary are the subject. A check on
   prose, artifacts or the agent's own scripts goes to the agent lane with its header and counts
   against that lane's budget; it never enters the default suite. One-line test docstrings, no
   card ids or dates anywhere in the file.
6. Implement the smallest coherent change inside ADR 0030's layers (`platform < governance < agent <
   models < observability < pipeline < teams < sandbox < operator < tasks < hops`; a context imports
   only those below it, no function-local `docket.*` import, no module over 700 lines). The two
   invariants hold: every tool call passes `dispatch_tool`, and docket-owned JSON is written only by
   `platform/store.py`. `tests/architecture/` (3 s) is the check.
7. Test by cost, as [references/validation.md](references/validation.md) measures it: per commit the
   static gates and `pytest --co -q` (~4 s, no tests); while iterating only the unit file whose
   `SUBJECT` is the changed module, by path under `timeout 120`; before handoff the gate the card
   names. A worker never runs the full suite (84 s) or the agent lane (3.5 min); the integrator does,
   once per merge or phase close. Don't rerun a test that passed unless its subject changed since.

Fit the work to the model running it and its context window. A card names its model (`**Model:**`):
Haiku edits data, docs and spec text the card spells out; Sonnet changes behavior in `src/`. Spend
tokens on the change, not the tour: grep the card's line locators instead of reading a module whole,
open only the files the card names, and when the card turns out to need more, park with the
missing locator rather than exploring.

When executing one card in a coordinated wave, the card packet is the scope boundary. Work in its
assigned worktree/state, edit only declared files/functions plus the owning behavior spec/tests,
and leave central roadmap/README/spec-index/metric rollups to the integrator. Return compact delta
evidence; record adjacent defects as follow-ups instead of fixing them without a claim. Roadmap
ownership and merge scheduling remain governed by `docket-roadmap`.

If acceptance requires a forbidden/shared file, or the selected card contradicts the owning spec,
stop before writing the RED test. Return the exact ambiguity and locators to the integrator so scope
and ownership can be reconciled once instead of letting workers implement competing contracts.

Read [references/validation.md](references/validation.md) before the first test run of a card: it
routes each surface to its check and gives each check's measured cost.

Read [references/real-world-tests.md](references/real-world-tests.md) when designing realistic
product fixtures. Skill maintainers use
[references/forward-tests.md](references/forward-tests.md) only as an evaluator-side rubric after
the evaluated agent finishes. An evaluated agent must not load that rubric.

When a persisted shape changes, exercise the real reader and sole writer with an empty-state fixture
and every prior shape the contract promises to support. Assert semantic round-trip behavior,
preservation of unknown/unaffected data, and failure atomicity when migration can write.

Keep test output out of the conversation unless it explains a failure: send it to a file and read
the `FAILED` lines. Report command + outcome, not full logs. Never change a golden or metrics/spec validator merely to turn a gate green.

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
