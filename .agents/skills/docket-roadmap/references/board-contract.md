# Board contract

Read this only when the task changes planning state.

- `TODO.md` is the only executable standing board. A clear board means no work is implicitly queued.
- `ROADMAP.md` is the durable decision and historical record. A deferred item becomes schedulable
  only when its named trigger has fired with evidence from this system.
- Preserve the existing status vocabulary and keep one owner per in-progress card.
- Schedule by file/function contention, not by thematic similarity or phase number.
- Before a claim, require a known full Git status and compare the selected card with every active
  lane across owning spec, files/functions, persisted state, and mutable environment. If the status
  probe is unavailable or clipped, resolve it first; unknown is not clean.
- A card must name: measured trigger, goal, non-goals, exact functions/files, acceptance criteria,
  RED test, full validation gates, and documentation/spec updates.
- A quantitative or deferred trigger must name its source/locator, metric, observation window,
  threshold, and observed value. Label an estimate as such and schedule measurement rather than
  treating it as fired. For an explicit scoped request or deterministic bug, cite that request or
  exact expected/actual reproduction; do not fabricate quantitative fields.
- Acceptance must include a representative fixture or state, the public action, observable result,
  durable side effects or rollback expectation, and the oracle that distinguishes pass from merely
  exercising a helper.
- Closing a card requires its spec status/version/changelog to match what shipped. Do not mark broad
  capabilities complete when only machinery or an unused code path exists.
- Central rollups should state the current truth once. Avoid duplicating detailed task prose between
  `TODO.md`, `ROADMAP.md`, specs, and implementation comments.

When scoping, resuming, or closing work, use this semantic task-packet shape (wording may vary):

```text
Decision:
Evidence:
Scope:
Contract / spec:
Validation:
Risks:
Next action:
Pending in current card:
Later follow-ups:
```

Then append the separate end-of-work control summary required by `AGENTS.md`, including Feature,
Outcome, Missing / failed, Pending, Next ideal task, and Parallel work. Do not merge the two shapes
in a way that drops fields from either contract.
