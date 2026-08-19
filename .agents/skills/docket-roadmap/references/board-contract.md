# Board contract

Read this only when the task changes planning state.

- `TODO.md` is the only executable standing board. A clear board means no work is implicitly queued.
- `ROADMAP.md` is the durable decision and historical record. A deferred item becomes schedulable
  only when its named trigger has fired with evidence from this system.
- Preserve the existing status vocabulary and keep one owner per in-progress card.
- Schedule by file/function contention, not by thematic similarity or phase number.
- A card must name: measured trigger, goal, non-goals, exact functions/files, acceptance criteria,
  RED test, full validation gates, and documentation/spec updates.
- Closing a card requires its spec status/version/changelog to match what shipped. Do not mark broad
  capabilities complete when only machinery or an unused code path exists.
- Central rollups should state the current truth once. Avoid duplicating detailed task prose between
  `TODO.md`, `ROADMAP.md`, specs, and implementation comments.

When resuming work, emit this compact handoff shape:

```text
Card / objective:
Decision and evidence:
Touched files:
Checks already green:
Unresolved risk or failure:
Exact next action:
```
