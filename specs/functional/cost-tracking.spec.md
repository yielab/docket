# Cost Tracking Specification

**Version**: 1.10.1
**Status**: Implemented (reporting, caps, and auto-pause are all real; enforcement remains
scoped to the pod-dispatch lane — see "Enforcement, warnings, and pause"). Cost reporting resolves
Docket's own `DocketDriver` and session store. See requirements 2-4 below.
**Last Updated**: 2026-10-18

## Purpose

This specification defines how docket reports token usage and dollar cost per agent, stores
per-agent budget caps, and where those caps are (and are not) enforced today.

## Scope

This specification covers:

- Reporting usage and cost (`docket status`)
- Per-agent budget caps (`docket pod set budgetUsd`)
- Budget/runaway warnings (`docket setup`) and the pause contract

This specification does NOT cover the role→model policy or pricing table (see
model-profiles.spec.md), nor the pod-dispatch pre-hop budget gate's mechanics (see
pod-dispatch.spec.md).

## Requirements

### Cost reporting (docket status)

1. `docket status` **MUST** report the pod's measured token usage and its labelled dollar
   estimate, per pod, beside the pod's success/failure/aborted counts and latency (read from
   trace `session_end` events through `core.trace.terminal_outcomes`); `status --all --json`
   **MUST** carry every agent's recorded `costUsd` and the fleet `totalCostUsd`.
2. Costs **MUST** be derived from `DocketDriver`'s session data
   (`core.utils.aggregate_cost`/`cost_history`, delegating to
   `edges.adapters.docket_runtime.default_driver()`), reading `core/session.py`'s own storage
   under `$DOCKET_HOME/sessions`, the only live session shape.
3. Dollar figures are the resolved driver's **recorded** spend, never docket's own pricing math
   substituted for it: when the driver records no cost, `docket status` **MUST** show only the token
   counts and an estimate marked `est.`, never a computed figure as if recorded.
   `DocketDriver` **never** reports a cost (`capabilities().reports_cost_usd` is always `False`
   — see `core/runtime_driver.py`'s `TurnResult.cost_usd` docstring), so this branch is the
   production case; the bundled pricing table powers comparative estimates only (see
   model-profiles.spec.md).
4. The session-format parsing behind requirement 2 **MUST** live entirely inside `DocketDriver`
   (`edges/adapters/docket_runtime.py`, docket-native `core/session.py` storage) and **MUST
   NOT** appear anywhere under `core/`. `core/utils.py`'s `aggregate_cost`/`cost_history` are
   pure translations of whatever `edges.adapters.docket_runtime.default_driver()` resolves —
   `DocketDriver`, unconditionally — into the legacy `CostTotals`/`DayRecord` shapes
   `cli/_status.py`, `cli/_doctor.py`, and `core/dispatch.py` already depend on; they no longer
   open a session file themselves. A guard test
   (`test_no_external_daemon_coupling.py::test_product_code_has_no_retired_daemon_reference`)
   fails the build if external-runtime coupling regresses into `src/`.

### Budget caps

1. `docket pod set budgetUsd <USD>` **MUST** store a `budgetUsd` cap in `.docket-meta.json`.
2. A cap of `0` **MUST** mean "no cap" and **MUST** clear any existing cap.
3. Setting a non-zero budget **MUST** clear a prior `paused` state (and, when the target is a
   pod's Lead, unblocks that pod's budget-blocked tasks — see pod-dispatch.spec.md).
4. The budget value **MUST** be a non-negative number.
5. Budget fields (`budgetUsd`, `paused`, `pausedReason`) are Docket-local (decision D-9).
   Enforcement therefore exists only where Docket itself is in the execution path.
6. `docket run --resume` **MUST** clear `paused`/`pausedReason` on *id* and **MUST**
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
   through `edges/store.py`, per D-9). Once paused,
   dispatch refuses **every** further claim for that pod outright — before a task is even
   flipped to `running`, not merely re-blocked hop by hop — and emits a `paused_refused` trace
   event each time. This is a claim-time check (`core/dispatch.py`'s `_claim_next_task`), so a
   paused pod costs nothing further to not dispatch: no claim write, no wasted agent turn.
3. **Implemented — resume.** `docket run --resume` clears both fields and writes an
   audit entry (see "Budget caps" above); a fresh dispatch attempt can claim again.
4. **Implemented — labelled estimate fallback for gating.** Recorded pod spend legitimately
   reads `0` always now: `DocketDriver` never reports a cost at all
   (`capabilities().reports_cost_usd` is unconditionally `False` — see requirement 3 above and
   `core/runtime_driver.py`'s `TurnResult.cost_usd` docstring), so this is the **only** case in
   production. The budget gate falls
   back to a token-count × pricing-table estimate (`core/utils.estimate_cost_usd`) so a real
   cap can still trip. The estimate prices `input_tokens - cache_read - cache_write` at the input
   rate, `cache_read` at the cache-read rate and `cache_write` at the cache-write rate, because an
   endpoint's input count already contains its cache reads and writes; a cached token is never
   charged at two rates. `DocketDriver.usage` sums each session's `cacheWriteTokens`. This estimate is used **only** for gating and warning displays — it is
   always rendered clearly labelled (`core/dispatch.py`'s literal label string is `~$X.XX
   (estimated — no cost recorded)`) and **MUST NOT** be mixed into, or
   presented as, recorded spend; `docket status --all --json`'s recorded `costUsd` fields are
   completely unaffected by this fallback (see "Cost reporting" above).
5. **Implemented — budget/runaway warnings read the same gating figure as the dispatch gate.**
   `docket setup`'s per-agent budget check (`cli/_setup_check.py::_check_budget`) 
   **MUST** warn/flag against the same recorded-or-estimated gating figure requirement 4
   describes (`core/utils.gating_cost`: recorded spend if nonzero, else the
   `estimate_cost_usd` token-count × pricing-table fallback), clearly labelled with the same
   `estimated — no cost recorded` marker requirement 4 uses whenever it is an estimate,
   at each check's own decimal precision — an estimate **MUST NOT** be
   presented as, or mixed into, recorded spend. Because recorded spend is always `0` under
   `DocketDriver` (requirement 4), in production both checks fire from the estimate: the ≥80%
   warning / ≥100% flag in `docket setup`. These remain display-only, independent of the pause writer. The turn-count
   runaway check is unaffected (it never depended on cost); so is `docket setup`'s `--json` per-agent `budget`/`runaway`
   results, which still report only recorded spend (see "Cost reporting" above) — a known,
   unfixed instance of the same blind spot this requirement closes for the two human-facing
   warnings above.
6. **Implemented — a model the estimate cannot price is named, not counted as $0.** A model
   with no catalog price and no `local` provider adds nothing to requirement 4's estimate, so a
   cap cannot stop its spend. Docket warns and does not refuse (the operator's choice,
   2026-10-18): before each hop of a pod with a cap, a hop whose model (the step's own `model`,
   else the member's) is unpriced emits a `budget_warning` trace event with `action:
   "unpriced_model"`, `status: "unenforced"` and a `reason` naming the cap and the model, and the
   hop runs. `core.dispatch.unpriced_budget_models(project)` lists such models across the pod's
   members and its pipeline's steps (empty without a cap); `docket pod show [--json]`, `GET
   /pods/<p>` (`budgetUnpriced`) and `docket status [--json]` (a `Budget` row, `budgetUnpriced`
   only when non-empty) show it. Known gap: the estimate still prices every token of a member at
   the member's own model, so a step `model:` override is checked here but not priced.
7. **Known scope limit (unchanged by R-5):** enforcement exists only where docket itself is in
   the execution path — the pod-dispatch lane. A budget cap set on a non-pod agent, or spend
   from a Telegram session / any driver use outside dispatch, is still entirely ungated
   (per D-9/the "docket orchestrates hops" principle in ROADMAP §4.5) — there is no code path
   observing those turns to pause anything.

## Interface Contracts

### CLI Command Signatures

```bash
docket status                     # Pod tokens, labelled estimate, outcomes (table)
docket status --all --json        # Machine-readable (see cli-json-shapes.spec.md)
docket status --history [--days N]  # Daily history (see "Known gap" below)
docket pod set budgetUsd <USD>   # Set/clear a cap (0 = none)
docket run --resume         # Clear an auto-pause; unblocks a paused pod's Lead
docket run --resume                        # Same clear, then reclaims stale claims
docket setup                     # Includes budget/runaway check (display only)
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid budget value)

### Known gap: `--history` is always empty

`DocketDriver.usage().by_day` is always `[]` — a session's stored usage
(`core.session.MeasuredUsage`) is one running total for its whole lifetime, with no per-turn
timestamp to bucket by day. `docket status --history` therefore returns an honest empty history
against real production data, regardless of `--days`; `docket status` (non-history) is unaffected —
totals still aggregate correctly. Adding a per-turn usage log to fabricate a daily breakdown is
new scope for `core/session.py`, not part of P19-7a; this is a named capability gap, not a bug.

## Examples

### Reporting cost and setting a cap

```bash
$ docket status --pod mywebsite
  Tokens:                   50.0K in / 25.0K out (~$0.12 est.)

$ docket pod set budgetUsd 5
✓ Budget cap set to $5 for 'mywebsite'.
```

`DocketDriver` never reports a cost (requirement 3), so the dollar figure is always the
labelled `est.` estimate in production; a recorded figure would require a driver that reports a
real dollar amount, which none does.

### A pod pausing at its cap, and resuming

Recorded pod spend is always `0` in production (requirement 4), so the block reason always
carries the labelled estimate; the unlabelled `($X.XX ≥ $Y.YY)` form only appears if a driver
ever records a real cost.

```bash
$ docket run --pod myproject
⚠   [<task-id>] blocked — pod budget reached (~$5.12 (estimated — no cost recorded) ≥ $5.00) before implementer

$ docket pod show --pod myproject
  ...
  Status:           PAUSED (budget)

$ docket run --resume
→   Unblocked 1 budget-blocked task(s) in pod 'myproject'.
✓ Resumed 'myproject-lead' — auto-pause cleared.
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

- Reported recorded-spend figures (`docket status --all --json`) are the driver's own, never silently computed —
  unaffected by the gating estimate fallback in any way.
- A `paused` agent **MUST** always carry a `pausedReason`.
- An estimate used for budget gating **MUST** always render clearly labelled as an estimate and
  **MUST NOT** be summed into, or presented as, recorded spend.
