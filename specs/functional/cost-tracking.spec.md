# Cost Tracking Specification

**Version**: 1.5.0
**Status**: Implemented (reporting, caps, and auto-pause are all real; enforcement remains
scoped to the pod-dispatch lane — see "Enforcement, warnings, and pause"). **ROADMAP Phase 19
P19-7a (the runtime cutover)** repointed cost reporting at `edges.adapters.docket_runtime`'s
`DocketDriver`. **ROADMAP Phase 19 P19-7b then deleted the ACL and `OpenClawDriver` outright**
— `DocketDriver` is now the *only* `RuntimeDriver`, not merely the default one; every "daemon
recorded no cost" phrasing below is corrected to "no cost recorded" (there is no daemon left to
attribute the absence to). See requirements 2-4 below.
**Last Updated**: 2026-08-03

## Purpose

This specification defines how docket reports token usage and dollar cost per agent, stores
per-agent budget caps, and where those caps are (and are not) enforced today.

## Scope

This specification covers:

- Reporting usage and cost (`docket cost`)
- Per-agent budget caps (`docket profile --budget`)
- Budget/runaway warnings (`docket doctor`, `docket cost`) and the pause contract

This specification does NOT cover the role→model policy or pricing table (see
model-profiles.spec.md), nor the pod-dispatch pre-hop budget gate's mechanics (see
pod-dispatch.spec.md).

## Requirements

### Cost reporting (docket cost)

1. `docket cost [agent-id]` **MUST** report token usage and dollar cost; with no id it
   **MUST** aggregate across all agents.
2. Costs **MUST** be derived from `DocketDriver`'s session data
   (`core.utils.aggregate_cost`/`cost_history`, delegating to
   `edges.adapters.docket_runtime.default_driver()`), reading `core/session.py`'s own storage
   under `$DOCKET_HOME/sessions` — the **only** shape there is to read since ROADMAP Phase 19
   P19-7b deleted the ACL and `OpenClawDriver` outright. There is no more `~/.openclaw/agents/
   */sessions/*.jsonl` daemon format, and no second driver implementation to read it.
3. Dollar figures are the resolved driver's **recorded** spend, never docket's own pricing math
   substituted for it: when the driver records no cost, `docket cost` **MUST** say so ("none
   recorded for these sessions") rather than print a computed figure as if recorded.
   `DocketDriver` **never** reports a cost (`capabilities().reports_cost_usd` is always `False`
   — see `core/runtime_driver.py`'s `TurnResult.cost_usd` docstring), so this branch is the
   **only** case in production now (not merely "the normal case" alongside a daemon-recorded
   alternative — that alternative no longer exists); the bundled pricing table powers
   comparative estimates only (see model-profiles.spec.md).
4. **(Phase 18 L-1 / D-14; the ACL half retired at P19-7b)** The session-format parsing behind
   requirement 2 **MUST** live entirely inside `DocketDriver`
   (`edges/adapters/docket_runtime.py`, docket-native `core/session.py` storage) and **MUST
   NOT** appear anywhere under `core/`. `core/utils.py`'s `aggregate_cost`/`cost_history` are
   pure translations of whatever `edges.adapters.docket_runtime.default_driver()` resolves —
   `DocketDriver`, unconditionally — into the legacy `CostTotals`/`DayRecord` shapes
   `cli/_cost.py`, `cli/_doctor.py`, and `core/dispatch.py` already depend on; they no longer
   open a session file themselves. A guard test
   (`test_no_openclaw_references.py::test_no_live_openclaw_reference_outside_comments_and_docstrings`,
   which replaced the retired `test_ch2_openclaw_acl_guard.py::test_core_has_no_session_format_knowledge`)
   fails the build if daemon session-format knowledge — or any other live `openclaw` reference
   — regresses back into `src/`.

### Budget caps

1. `docket profile <id> --budget <USD>` **MUST** store a `budgetUsd` cap in `.docket-meta.json`.
2. A cap of `0` **MUST** mean "no cap" and **MUST** clear any existing cap.
3. Setting a non-zero budget **MUST** clear a prior `paused` state (and, when the target is a
   pod's Lead, unblocks that pod's budget-blocked tasks — see pod-dispatch.spec.md).
4. The budget value **MUST** be a non-negative number.
5. Budget fields (`budgetUsd`, `paused`, `pausedReason`) are docket-local (decision D-9) —
   there is no daemon left to read them even if one wanted to (ROADMAP Phase 19 P19-7b).
   Enforcement therefore exists only where docket itself is in the execution path.
6. `docket profile <id> --resume` **MUST** clear `paused`/`pausedReason` on *id* and **MUST**
   write a `profile.resume` audit-log entry. When *id* is a pod's Lead, it additionally
   unblocks that pod's budget-blocked tasks (mirroring the `--budget` behavior above) — a
   resume that left the tasks queued up behind the pause permanently `blocked` would not
   actually resume anything.

### Enforcement, warnings, and pause (ROADMAP Phase 14 R-5)

1. **Implemented — cap enforcement.** The pod-dispatch lane checks the pod's spend against
   the Lead's `budgetUsd` before each hop and blocks the task when the cap is reached
   (pod-dispatch.spec.md).
2. **Implemented — auto-pause.** The same check that blocks a task also marks the pod's Lead
   `paused = true`, `pausedReason = "budget"` (`core/dispatch.py`'s `_pause_lead_for_budget`,
   through `edges/store.py` — `openclaw.json` is deleted, there is nothing left to sync to,
   per D-9). Once paused,
   dispatch refuses **every** further claim for that pod outright — before a task is even
   flipped to `running`, not merely re-blocked hop by hop — and emits a `paused_refused` trace
   event each time. This is a claim-time check (`core/dispatch.py`'s `_claim_next_task`), so a
   paused pod costs nothing further to not dispatch: no claim write, no wasted agent turn.
3. **Implemented — resume.** `docket profile <id> --resume` clears both fields and writes an
   audit entry (see "Budget caps" above); a fresh dispatch attempt can claim again.
4. **Implemented — labelled estimate fallback for gating.** Recorded pod spend legitimately
   reads `0` always now: `DocketDriver` never reports a cost at all
   (`capabilities().reports_cost_usd` is unconditionally `False` — see requirement 3 above and
   `core/runtime_driver.py`'s `TurnResult.cost_usd` docstring), so this is the **only** case in
   production, not an occasional gap the pre-P19-7b daemon might close. The budget gate falls
   back to a token-count × pricing-table estimate (`core/utils.estimate_cost_usd`) so a real
   cap can still trip. This estimate is used **only** for gating and warning displays — it is
   always rendered clearly labelled (`core/dispatch.py`'s literal label string is `~$X.XX
   (estimated — no cost recorded)`; corrected at P19-7b from the stale `daemon recorded no
   cost` wording, which had no daemon left to refer to) and **MUST NOT** be mixed into, or
   presented as, recorded spend; `docket cost`'s reported figures and provenance line are
   completely unaffected by this fallback (see "Cost reporting" above).
5. `docket doctor` and `docket cost` **MUST** warn at ≥80% and flag ≥100% of cap (using recorded
   spend, the same figure `docket cost` reports), and flag runaway sessions (turn/cost
   thresholds) — these two checks remain display-only, independent of the pause writer.
6. **Known scope limit (unchanged by R-5):** enforcement exists only where docket itself is in
   the execution path — the pod-dispatch lane. A budget cap set on a non-pod agent, or spend
   from a Telegram session / any driver use outside dispatch, is still entirely ungated
   (per D-9/the "docket orchestrates hops" principle in ROADMAP §4.5) — there is no code path
   observing those turns to pause anything.

## Interface Contracts

### CLI Command Signatures

```bash
docket cost [agent-id]            # Usage and recorded cost (table)
docket cost --json                # Machine-readable (see cli-json-shapes.spec.md)
docket cost --history [--days N]  # Daily recorded-cost history (see "Known gap" below)
docket profile <agent-id> --budget <USD>   # Set/clear a cap (0 = none)
docket profile <agent-id> --resume         # Clear an auto-pause; unblocks a paused pod's Lead
docket doctor                     # Includes budget/runaway check (display only)
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid budget value)

### Known gap: `--history` is always empty against the production driver (P19-7a; the only driver since P19-7b)

`DocketDriver.usage().by_day` is always `[]` — a session's stored usage
(`core.session.MeasuredUsage`) is one running total for its whole lifetime, with no per-turn
timestamp to bucket by day (unlike the now-deleted `OpenClawDriver.usage()`'s daemon-JSONL
reads, which timestamped every record — historical comparison only; that driver no longer
exists to fall back to). `docket cost --history` therefore returns an honest empty history
against real production data, regardless of `--days`; `docket cost` (non-history) is unaffected —
totals still aggregate correctly. Adding a per-turn usage log to fabricate a daily breakdown is
new scope for `core/session.py`, not part of P19-7a; this is a named capability gap, not a bug.

## Examples

### Reporting cost and setting a cap

```bash
$ docket cost mywebsite
  Input:            50,000 tokens
  Output:           25,000 tokens
  Total cost:       none recorded for these sessions

$ docket profile mywebsite --budget 5
[SUCCESS] Budget cap set to $5 for 'mywebsite'.
```

`DocketDriver` never reports a cost (requirement 3), so "none recorded for these sessions" —
`cli/_cost.py`'s real output — is the normal-case transcript in production, not the
old `$0.5300 (recorded by daemon)` shape a prior version of this spec showed; that shape
required a daemon that reported a real dollar figure, which no longer exists.

### A pod pausing at its cap, and resuming

```bash
$ docket pod myproject dispatch
✗   myproject-lead: pod budget reached ($5.12 ≥ $5.00) before implementer

$ docket info myproject-lead
  ...
  Status:           PAUSED (budget)

$ docket profile myproject-lead --resume
  Unblocked 1 budget-blocked task(s) in pod 'myproject'.
[SUCCESS] Resumed 'myproject-lead' — auto-pause cleared.
```

### A cap reached via the estimate fallback (no cost recorded)

```bash
$ docket pod myproject dispatch
✗   myproject-lead: pod budget reached (~$4.80 (estimated — no cost recorded) ≥ $1.00) before implementer
```

## Validation

### Pre-conditions

- For `--budget`, the value **MUST** parse as a non-negative number.

### Post-conditions

- After `--budget <n>` with n>0, `.docket-meta.json` **MUST** contain `budgetUsd = n` and no
  `paused` flag.
- After `--budget 0`, no active cap **MUST** remain.
- After a pod's spend (recorded, or estimated when none was recorded) reaches its Lead's
  `budgetUsd`, the Lead's `.docket-meta.json` **MUST** contain `paused = true`,
  `pausedReason = "budget"`, and a subsequent dispatch attempt for that pod **MUST** claim
  nothing.
- After `--resume`, the target's `.docket-meta.json` **MUST** contain `paused = false`,
  `pausedReason = ""`, and an audit-log entry with `action = "profile.resume"` **MUST** exist.

### Invariants

- Reported dollar figures (`docket cost`) are the driver's recorded spend, never silently computed —
  unaffected by the gating estimate fallback in any way.
- A `paused` agent **MUST** always carry a `pausedReason`.
- An estimate used for budget gating **MUST** always render clearly labelled as an estimate and
  **MUST NOT** be summed into, or presented as, recorded spend.

## Changelog

### Version 1.5.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7b — the OpenClaw daemon and `OpenClawDriver` are deleted outright.**
  Completes the P19-7a cutover 1.4.0 documented: `DocketDriver` is no longer merely the
  production default among two `RuntimeDriver` implementations, it is the *only* one this
  codebase ships. Updated requirements 2 and 4 (Cost reporting) to drop the "`OpenClawDriver`
  still reads daemon-format JSONL when directly constructed" carve-out — there is no such driver
  left to construct — and to name the new guard test
  (`test_no_openclaw_references.py`, which replaced the retired
  `test_ch2_openclaw_acl_guard.py`). Corrected the Enforcement section's estimate-fallback
  reasoning (requirement 4): recorded pod spend reading `0` is not an occasional daemon quirk
  ("may never write `usage.cost.total`") any more, it is the unconditional, only case in
  production, since `DocketDriver.capabilities().reports_cost_usd` is always `False` by design.
  Fixed the D-9 budget-fields note (there is no daemon left to sync `openclaw.json` to, not
  merely "the daemon never reads them"). Corrected the Examples section: the single-agent
  `docket cost` transcript now shows the real `cli/_cost.py` output ("Total cost: none recorded
  for these sessions"), not the stale `$0.5300 (recorded by daemon)` shape that required a
  daemon-reported dollar figure which no longer exists; the estimate-fallback example and its
  heading now read "no cost recorded", matching `core/dispatch.py`'s corrected label string
  (was the stale `daemon recorded no cost` wording). Fixed the matching Post-condition and
  Invariants wording ("the driver's recorded spend", not "daemon-recorded spend").

### Version 1.4.0 (2026-08-03)

- **ROADMAP Phase 19, card P19-7a (the runtime cutover).** `core/utils.py`'s `aggregate_cost`/
  `cost_history` now resolve `edges.adapters.docket_runtime.default_driver()` (`DocketDriver` in
  production), not `edges.adapters.openclaw.default_driver()` (`OpenClawDriver`). Updated
  requirements 2-4. Real behavior changes documented, not smoothed over:
  - `docket cost`'s "none recorded" branch (requirement 3) is now the **normal** production case,
    since `DocketDriver` never reports a cost at all — wording changed from "none recorded by the
    daemon" to "none recorded", since there is no daemon in the loop for a `DocketDriver`-executed
    turn.
  - New "Known gap" section: `docket cost --history` always returns an empty history against the
    production driver (`DocketDriver.usage().by_day` is unconditionally `[]`) — named explicitly,
    not fixed by this version.
  - `docket cost` (non-history) totals are unaffected — real recorded token counts still
    aggregate correctly through `DocketDriver`'s own session storage.
  - `OpenClawDriver`'s daemon-JSONL reading is untouched and still real when directly constructed
    or explicitly resolved; only the production default moved.

### Version 1.3.0 (2026-07-30)

- ROADMAP Phase 18 L-1 (D-14): the session-JSONL parsing behind cost reporting (requirement 2)
  moved from `core/utils.py` into `edges/adapters/openclaw.py`'s `OpenClawDriver` — the one
  shipped implementation of the new `RuntimeDriver` port (`core/runtime_driver.py`). This closes
  an ACL leak a 2026-07-29 platform audit found: `core/utils.py`'s `aggregate_cost`/
  `cost_history` used to open `sessions/*.jsonl` and parse the daemon's `message.usage` record
  shape directly. Both functions keep their exact names, signatures, and return shapes
  (`CostTotals`/`DayRecord`) — every existing caller (`cli/_cost.py`, `cli/_doctor.py`,
  `core/dispatch.py`'s `pod_recorded_cost`/`pod_gating_cost`) is unaffected — but they are now
  pure translations of `OpenClawDriver.usage()`'s `UsageReport`, not parsers. Added requirement 4
  naming the guard test that enforces this going forward. No behavior change to what `docket
  cost` reports or how it's derived — this is a containment refactor, not a new capability.

### Version 1.2.0 (2026-07-30)

- ROADMAP Phase 14 R-5: implemented auto-pause for real. `core/dispatch.py`'s budget gate now
  writes `paused = true, pausedReason = "budget"` on the pod's Lead the first time the cap is
  reached (previously nothing ever did — the Phase 1 Bash-era claim had not survived the Python
  port); `docket profile <id> --resume` clears it (with an audit entry) and unblocks the pod's
  budget-blocked tasks when the target is a Lead. Dispatch now refuses every claim for a paused
  pod outright at claim time (a `paused_refused` trace event), not merely re-blocking each task
  hop by hop.
- Added the labelled token-based estimate fallback for gating: when the daemon has recorded no
  cost at all, the gate falls back to a `MODEL_PRICING`-derived estimate so the cap can still
  trip — always clearly labelled, never contaminating `docket cost`'s recorded-spend figures.
- Status raised from "Partially implemented" to "Implemented" (the enforcement-scope limit —
  pod-dispatch lane only — remains and is now stated as a permanent, documented boundary rather
  than a pending gap).
- Added the `--resume` CLI signature, an example transcript for pause/resume and for the
  estimate-labelled block reason, and post-conditions/invariants for the new behavior.

### Version 1.1.0 (2026-07-30)

- Truth pass (Platformization baseline): Status downgraded from Complete. Auto-pause is
  explicitly marked unimplemented (no writer of `paused=true` exists; the Phase 1 claim
  was Bash-era and did not survive the Python port) and tracked as ROADMAP Phase 14 R-5.
  Cost provenance corrected: dollars are the daemon's recorded spend, not computed from
  the pricing table. CLI signature corrected to the real flags
  (`--json/--history/--days`; the spec'd `--period/--by-model/--csv` never existed).
  Return codes corrected to the actual 0/1 convention. Added the D-9 note (budget fields
  are docket-local) and the enforcement-scope note (dispatch lane only).

### Version 1.0.0 (2026-06-09)

- Initial cost-tracking specification
- Defined reporting, budget caps, and runaway/pause behavior
