---
name: docket-spec-work
description: Implement or change Docket behavior with its spec-first, test-first contract and proportional validation. Use for product code, CLI behavior, persisted shapes, or user-facing behavior claims; not for planning-only work.
---

# Docket Spec Work

Start from the behavior boundary, not from a broad repository tour.

1. Find the owning row in `specs/README.md`, then read only that spec and neighboring tests.
2. Trace the real caller into the implementation. A writer, parser, flag, or helper without a live
   caller is not evidence that a capability works.
3. Update the current-state spec first: requirement, version, status, last-updated date, and changelog.
4. Add a behavioral test that fails for the intended reason. Prefer a property/live-path assertion
   over wording, source-line, or fixture-only checks.
5. Implement the smallest coherent change, keeping `cli -> core -> edges` inward-only boundaries.
6. Run the focused test and static check while iterating. Before handoff, run the gates required by
   the affected surface.

Read [references/validation.md](references/validation.md) when selecting final gates or when CLI,
packaging, specs, documentation claims, or dependency bounds are affected.

Keep test output out of the conversation unless it explains a failure. Report command + outcome,
not full logs. Never change a golden or metrics/spec validator merely to turn a gate green.
