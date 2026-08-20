---
name: docket-roadmap
description: Scope, schedule, claim, or resume Docket roadmap work from the active board and durable decisions. Use for roadmap planning and card lifecycle; do not use for an already-scoped code edit.
---

# Docket Roadmap

Build a small task packet instead of loading the planning corpus.

1. Run `python3 .agents/skills/docket-roadmap/scripts/context_snapshot.py`.
2. Treat `TODO.md` as the active board. Read only its current active section and the selected
   card. If the board is clear, do not mine historical sections for work.
3. Use `ROADMAP.md` only for a named decision, principle, phase, or trigger. Locate it with `rg -n`
   and read that bounded section.
4. Locate the owning current-state spec through `specs/README.md`; do not read all specs.

For a new card, record the measured trigger, goal, non-goals, exact live-path owner, files/functions,
acceptance criteria, focused tests, full gates, and any file-contention dependency. Prefer one
independently shippable behavior over a phase-sized bundle.

For a runtime incident, separate independently shippable causes instead of giving the symptom one
catch-all card. Record the failing call ordinal, configured limit, measured or estimated request
size, and which context source grew. Do not schedule a larger limit as the fix unless bounded
composition already exists and the measured workload genuinely requires the capacity.

Read [references/board-contract.md](references/board-contract.md) only when changing `TODO.md` or
`ROADMAP.md`, claiming work, or closing a card.

Return or record a task packet containing only: decision, evidence, scope, contract/spec, validation,
risks, and next action. Link to large sources rather than copying them.

At close or resume, run the snapshot again and apply `AGENTS.md`'s end-of-work control. Choose the
next ideal task only from a ready card, an unmet acceptance criterion, or a measured risk whose
trigger fired. Keep “pending in this card” separate from later follow-up work.

Assess parallel work by dependency and contention, not by similar titles. Two lanes are parallel-safe
only when neither needs the other's result and they do not share owning specs, files/functions,
persisted state, or a mutable live environment. If the board has no ready card, report that the next
ideal action is bounded triage/measurement; do not revive historical work implicitly.
