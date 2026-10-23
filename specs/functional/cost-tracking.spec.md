# Cost Tracking Specification

**Version**: 1.10.2
**Status**: Implemented. Token usage is measured; docket records no dollar spend, so every dollar
figure it shows is a labelled estimate. Caps and auto-pause act only on pod dispatch.
**Last Updated**: 2026-10-22

## Purpose

This specification defines how docket reports token usage and a labelled dollar estimate per pod,
stores a per-pod budget cap, and where that cap is (and is not) enforced.

## Scope

This specification covers:

- Reporting usage and the estimate (`docket status`)
- The per-pod budget cap (`docket pod set budgetUsd`)
- Budget warnings (`docket setup`), the pre-hop gate and the pause contract

This specification does NOT cover the role→model policy or pricing table (see
model-profiles.spec.md), nor the pod-dispatch pre-hop budget gate's mechanics (see
pod-dispatch.spec.md).

## Requirements

### Cost reporting (docket status)

1. `docket status` **MUST** report the pod's measured token usage and its labelled dollar
   estimate beside the pod's success/failure/aborted counts and latency (read from trace
   `session_end` events); `status --json` carries them as `usage.input`, `usage.output` and
   `usage.estimateUsd`. `status --all --json` **MUST** also carry every agent's recorded `costUsd`
   and the fleet `totalCostUsd`.
2. Token and cost totals **MUST** be derived from `DocketDriver`'s usage report, which reads the
   session store under `$DOCKET_HOME/sessions`, the only live session shape.
3. A dollar figure labelled as recorded is the driver's **recorded** spend, never docket's own
   pricing math substituted for it: when the driver records no cost, `docket status` **MUST** show
   only the token counts and an estimate marked `est.`, never a computed figure as if recorded.
   `DocketDriver` **never** reports a cost (`capabilities().reports_cost_usd` is always `False`,
   its `cost_usd` is always `0.0`), so this branch is the production case; the catalog's model
   prices power estimates only (see model-profiles.spec.md).
4. The session-format parsing behind requirement 2 **MUST** live entirely inside `DocketDriver`
   and **MUST NOT** appear in the domain layer. The domain's `aggregate_cost` and `cost_history`
   are pure translations of whatever the default driver (`DocketDriver`, unconditionally)
   reports into the `CostTotals` and `DayRecord` shapes; they open no session file themselves. A
   guard test (`test_product_code_has_no_retired_daemon_reference`) fails the build if
   external-runtime coupling returns to `src/`.

### Budget caps

1. `docket pod set budgetUsd <USD>` **MUST** store a `budgetUsd` cap in the pod Lead's
   `.docket-meta.json`.
2. A cap of `0` **MUST** mean "no cap": a stored `0` reads back as unset. `docket pod unset
   budgetUsd` clears the cap too.
3. Setting a non-zero budget **MUST** clear a prior `paused` state, and unblock the pod's
   budget-blocked tasks (see pod-dispatch.spec.md). Setting `0` or unsetting unblocks those tasks
   but leaves `paused` as it is.
4. The budget value **MUST** be a non-negative number; anything else exits `1` naming the setting.
5. Budget fields (`budgetUsd`, `paused`, `pausedReason`) are docket-local (decision D-9).
   Enforcement therefore exists only where docket itself is in the execution path.
6. `docket run --resume` **MUST** clear `paused`/`pausedReason` on the pod's Lead and **MUST**
   write a `run.resume` audit-log entry when the Lead was paused. It also unblocks that pod's
   budget-blocked tasks whether or not the Lead was paused, then reclaims stale claims: a resume
   that left the tasks queued up behind the pause permanently `blocked` would not actually resume
   anything.

### Enforcement, warnings, and pause

1. **Cap enforcement.** The pod-dispatch lane checks the pod's spend against the Lead's
   `budgetUsd` before each hop and blocks the task when the cap is reached
   (pod-dispatch.spec.md). A `budget_exceeded` trace event records `spent`, `cap`, `role` and
   `estimated`.
2. **Auto-pause.** The same check that blocks a task also marks the pod's Lead
   `paused = true`, `pausedReason = "budget"` (through the store chokepoint, per D-9). Once
   paused, dispatch refuses **every** further claim for that pod outright, before a task is
   flipped to `running`, and emits a `paused_refused` trace event each time. A paused pod costs
   nothing further to not dispatch: no claim write, no wasted agent turn.
3. **Resume.** `docket run --resume` clears both fields and writes an audit entry (see "Budget
   caps" above); a fresh dispatch attempt can claim again.
4. **Labelled estimate fallback for gating.** Recorded pod spend always reads `0`
   (requirement 3 above), so the budget gate falls back to a token-count × catalog-price
   estimate so a real cap can still trip. The estimate prices `input_tokens - cache_read -
   cache_write` at the input rate, `cache_read` at the cache-read rate and `cache_write` at the
   cache-write rate, because an endpoint's input count already contains its cache reads and
   writes; a cached token is never charged at two rates. `DocketDriver`'s usage sums each
   session's cache-write tokens. This estimate is used **only** for gating and warning displays;
   it is always rendered clearly labelled (the gate's literal label is `~$X.XX (estimated — no
   cost recorded)`) and **MUST NOT** be mixed into, or presented as, recorded spend;
   `docket status --all --json`'s recorded `costUsd` fields are completely unaffected by this
   fallback (see "Cost reporting" above).
5. **Budget and runaway warnings read the same gating figure as the dispatch gate.**
   `docket setup`'s per-agent budget check **MUST** warn/flag against the same recorded-or-
   estimated gating figure requirement 4 describes (recorded spend if nonzero, else the
   token-count × price estimate), clearly labelled with the same `estimated — no cost recorded`
   marker whenever it is an estimate, at the check's own decimal precision. An estimate **MUST
   NOT** be presented as, or mixed into, recorded spend. Because recorded spend is always `0`, in
   production the check fires from the estimate: a warning at 80% or more of the cap, a flag at
   100% or more. It is display-only, independent of the pause writer. The turn-count runaway
   check never depended on cost. `docket setup --json`'s per-agent `budget` and `runaway` results
   report only recorded spend (always `0`), so they cannot flag an over-budget agent.
6. **A model the estimate cannot price is named, not counted as $0.** A model with no catalog
   price and no `local` provider adds nothing to requirement 4's estimate, so a cap cannot stop
   its spend. Docket warns and does not refuse: before each hop of a pod with a cap, a hop whose
   model (the step's own `model`, else the member's) is unpriced emits a `budget_warning` trace
   event with `action: "unpriced_model"`, `status: "unenforced"` and a `reason` naming the cap and
   the model, and the hop runs. The list of such models across the pod's members and its
   pipeline's steps is empty without a cap; `docket pod show [--json]`, `GET /pods/<p>`
   (`budgetUnpriced`) and `docket status [--json]` (a `Budget` row, `budgetUnpriced` only when
   non-empty) show it. Known gap: the estimate still prices every token of a member at the
   member's own model, so a step `model:` override is checked here but not priced.
7. **Scope limit.** Enforcement exists only where docket itself is in the execution path, the
   pod-dispatch lane, the only place a turn runs. A `budgetUsd` stored on a non-pod agent is read
   by the `docket setup` warning and nothing else; no code path pauses anything for it (per D-9
   and the "docket orchestrates hops" principle).

## Interface Contracts

### CLI Command Signatures

```bash
docket status                     # Pod tokens, labelled estimate, outcomes (table)
docket status --all --json        # Machine-readable (see cli-json-shapes.spec.md)
docket status --history [--days N]  # Daily history (see "Known gap" below)
docket pod set budgetUsd <USD>    # Set/clear a cap (0 = none)
docket pod unset budgetUsd        # Clear the cap
docket run --resume               # Clear an auto-pause, unblock budget-blocked tasks, reclaim stale claims
docket setup                      # Includes budget/runaway check (display only)
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown pod, invalid budget value)

### Known gap: `--history` is always empty

`DocketDriver`'s usage report has no per-day breakdown (`by_day` is always `[]`): a session's
stored usage is one running total for its whole lifetime, with no per-turn timestamp to bucket by
day. `docket status --history` therefore returns an honest empty history (`{"history": []}` with
`--json`, `No dated session data yet` otherwise) against real data, regardless of `--days`;
`docket status` (non-history) is unaffected: totals still aggregate correctly. Adding a per-turn
usage log to fabricate a daily breakdown is new scope for the session store; this is a named
capability gap, not a bug.

## Examples

### Reporting cost and setting a cap

```bash
$ docket status --pod mywebsite
  Tokens:                   50.0K in / 25.0K out (~$0.12 est.)

$ docket pod set budgetUsd 5
ok Set budgetUsd=5.0 for pod 'mywebsite'
```

`DocketDriver` never reports a cost (requirement 3), so the dollar figure is always the
labelled `est.` estimate; a recorded figure would require a driver that reports a real dollar
amount, which none does.

### A pod pausing at its cap, and resuming

Recorded pod spend is always `0`, so the block reason always carries the labelled estimate; the
unlabelled `($X.XX ≥ $Y.YY)` form only appears if a driver ever records a real cost.

```bash
$ docket run --pod myproject
! [<task-id>] blocked — pod budget reached (~$5.12 (estimated — no cost recorded) ≥ $5.00) before implementer

$ docket run --resume
-> Unblocked 1 budget-blocked task(s) in pod 'myproject'
```

## Validation

### Pre-conditions

- For `pod set budgetUsd`, the value **MUST** parse as a non-negative number.

### Post-conditions

- After `pod set budgetUsd <n>` with n>0, the Lead's `.docket-meta.json` **MUST** contain
  `budgetUsd = n` and no `paused` flag.
- After `pod set budgetUsd 0`, no active cap **MUST** remain.
- After a pod's spend (recorded, or estimated when none was recorded) reaches its Lead's
  `budgetUsd`, the Lead's `.docket-meta.json` **MUST** contain `paused = true`,
  `pausedReason = "budget"`, and a subsequent dispatch attempt for that pod **MUST** claim
  nothing.
- After `docket run --resume` on a paused pod, the Lead's `.docket-meta.json` **MUST** contain
  `paused = false`, `pausedReason = ""`, and an audit-log entry with `action = "run.resume"`
  **MUST** exist.

### Invariants

- Reported recorded-spend figures (`docket status --all --json`) are the driver's own, never
  silently computed, and unaffected by the gating estimate fallback in any way.
- A `paused` agent **MUST** always carry a `pausedReason`.
- An estimate used for budget gating **MUST** always render clearly labelled as an estimate and
  **MUST NOT** be summed into, or presented as, recorded spend.

## Implementation

- `src/docket/core/utils.py`: `CostTotals`, `DayRecord`, `aggregate_cost`, `cost_history`, `estimate_cost_usd`, `gating_cost`
- `src/docket/core/dispatch.py`: `pod_gating_cost`, `pod_recorded_cost`, `pod_budget`, `unpriced_budget_models`, `unblock_pod`, the pre-hop budget gate, the Lead pause writer, the claim-time pause check
- `src/docket/core/models_policy.py`: `price_for`
- `src/docket/core/trace.py`: `terminal_outcomes`, `EVENT_TYPES` (`budget_exceeded`, `budget_warning`, `paused_refused`)
- `src/docket/core/runtime_driver.py`: `TurnResult.cost_usd`, `UsageReport`, `DriverCapabilities.reports_cost_usd`
- `src/docket/edges/adapters/docket_runtime.py`: `DocketDriver.usage`, `DocketDriver.capabilities`
- `src/docket/cli/_status.py`: `docket status`, the per-pod usage summary, the fleet inventory
- `src/docket/cli/_pod.py`: `docket pod set|unset budgetUsd`
- `src/docket/cli/_run.py`: `docket run --resume`
- `src/docket/cli/_setup_check.py`: the `docket setup` budget and runaway checks
