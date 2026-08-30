---
name: docket-roadmap
description: Scope, schedule, claim, or resume Docket roadmap work from the active board and durable decisions. Use for roadmap planning and card lifecycle; do not use for an already-scoped code edit.
---

# Docket Roadmap

Build a small task packet instead of loading the planning corpus.

1. Run `python3 .agents/skills/docket-roadmap/scripts/context_snapshot.py`.
   Treat `dirty: unknown`, an ambiguous board marker, or clipped dirty paths as a fail-closed
   precondition: obtain the full read-only Git status before claiming work or declaring lanes
   parallel-safe. Never interpret an unavailable Git probe as a clean worktree.
2. Treat `TODO.md` as the active board. Once a card id is known, run
   `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>` and use that exact card
   instead of loading the active section. The helper refuses duplicate or oversized cards rather
   than silently truncating acceptance evidence. Read the active section only when selecting or
   changing cards. If the board is clear, do not mine historical sections for work.
3. Use `ROADMAP.md` only for a named decision, principle, phase, or trigger. Locate it with `rg -n`
   and read that bounded section.
4. Locate the owning current-state spec through `specs/README.md`; do not read all specs.

For a new card, record the measured trigger, goal, non-goals, exact live-path owner, files/functions,
acceptance criteria, focused tests, full gates, and any file-contention dependency. Prefer one
independently shippable behavior over a phase-sized bundle.

For a quantitative or deferred scheduling trigger, evidence names a source/locator, metric,
observation window, threshold, and observed value. An estimate may justify bounded measurement; it
does not fire that trigger. For an explicit scoped request or deterministic regression, record the
request or exact expected/actual reproduction instead of inventing a metric, window, or threshold.
Make acceptance executable with at least one representative initial state, public action,
observable result, side-effect/rollback check, and named oracle. A card whose only test claim is
“works” or a helper-only assertion is not ready.

For a runtime incident, separate independently shippable causes instead of giving the symptom one
catch-all card. Record the failing call ordinal, configured limit, measured or estimated request
size, and which context source grew. Do not schedule a larger limit as the fix unless bounded
composition already exists and the measured workload genuinely requires the capacity.

Read [references/board-contract.md](references/board-contract.md) only when changing `TODO.md` or
`ROADMAP.md`, claiming work, or closing a card.

Read [references/real-world-tests.md](references/real-world-tests.md) when designing a card's
real-case acceptance evidence; do not load it for ordinary board lookup. Skill maintainers use
[references/forward-tests.md](references/forward-tests.md) only as an evaluator-side rubric after
the evaluated agent finishes. An evaluated agent must not load that rubric.

Read [references/multi-agent-delivery.md](references/multi-agent-delivery.md) when two or more agents
may work concurrently. It defines coordinator ownership, isolated worktree/state requirements,
conflict-graph scheduling, minimal worker packets, delta-only returns, and merge gates. Do not load
it for ordinary single-card work.

Return or record a task packet covering decision, evidence, scope, contract/spec, validation, risks,
next action, pending work in the current card, and later follow-ups. Link to large sources rather
than copying them; never repeat the selected card, raw logs, full diffs, or prior conversation in a
handoff. Keep this packet separate from, and append, `AGENTS.md`'s required end-of-work control
summary; neither shape replaces the other.

At close or resume, run the snapshot again and apply `AGENTS.md`'s end-of-work control. Choose the
next ideal task only from a ready card, an unmet acceptance criterion, or a measured risk whose
trigger fired. Keep “pending in this card” separate from later follow-up work.

Assess parallel work by dependency and contention, not by similar titles. Two lanes are parallel-safe
only when neither needs the other's result and they do not share owning specs, files/functions,
persisted state, or a mutable live environment. If the board has no ready card, report that the next
ideal action is bounded triage/measurement; do not revive historical work implicitly.

For a coordinated wave, one integrator owns central rollups and compiles worker packets from the
card plus locators. Workers receive one owner/worktree/base, unique `DOCKET_HOME`/temp/ports, exact
allowed and forbidden ownership, RED/final gates, and merge order. Prefer minimal-history workers
when that packet is self-contained; the integrator is the fan-in point and dependent workers never
relay each other's raw handoffs.
