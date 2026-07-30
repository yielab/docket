# Cost Tracking Specification

**Version**: 1.2.0
**Status**: Implemented (reporting, caps, and auto-pause are all real; enforcement remains
scoped to the pod-dispatch lane — see "Enforcement, warnings, and pause")
**Last Updated**: 2026-07-30

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
2. Costs **MUST** be derived from session data under `~/.openclaw/agents/*/sessions/*.jsonl`.
3. Dollar figures are the daemon's **recorded** spend, taken verbatim from the session
   files' `usage.cost.total`. docket **MUST NOT** substitute its own pricing math for
   recorded spend: when the daemon records no cost, `docket cost` **MUST** say so
   ("none recorded by the daemon for these sessions") rather than print a computed
   figure as if recorded. The bundled pricing table powers comparative estimates only
   (see model-profiles.spec.md).

### Budget caps

1. `docket profile <id> --budget <USD>` **MUST** store a `budgetUsd` cap in `.docket-meta.json`.
2. A cap of `0` **MUST** mean "no cap" and **MUST** clear any existing cap.
3. Setting a non-zero budget **MUST** clear a prior `paused` state (and, when the target is a
   pod's Lead, unblocks that pod's budget-blocked tasks — see pod-dispatch.spec.md).
4. The budget value **MUST** be a non-negative number.
5. Budget fields (`budgetUsd`, `paused`, `pausedReason`) are docket-local (decision D-9);
   the daemon never reads them. Enforcement therefore exists only where docket itself is
   in the execution path.
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
   through `edges/store.py`/the ACL — never synced to `openclaw.json`, per D-9). Once paused,
   dispatch refuses **every** further claim for that pod outright — before a task is even
   flipped to `running`, not merely re-blocked hop by hop — and emits a `paused_refused` trace
   event each time. This is a claim-time check (`core/dispatch.py`'s `_claim_next_task`), so a
   paused pod costs nothing further to not dispatch: no claim write, no wasted agent turn.
3. **Implemented — resume.** `docket profile <id> --resume` clears both fields and writes an
   audit entry (see "Budget caps" above); a fresh dispatch attempt can claim again.
4. **Implemented — labelled estimate fallback for gating.** Recorded pod spend can legitimately
   read `0` forever: daemon v2026.2.23 may never write `usage.cost.total` at all (see
   model-profiles.spec.md's `MODEL_PRICING` note). When that happens, the budget gate falls
   back to a token-count × pricing-table estimate (`core/utils.estimate_cost_usd`) so a real
   cap can still trip. This estimate is used **only** for gating and warning displays — it is
   always rendered clearly labelled (e.g. `~$X.XX (estimated — daemon recorded no cost)`) and
   **MUST NOT** be mixed into, or presented as, recorded spend; `docket cost`'s reported figures
   and provenance line are completely unaffected by this fallback (see "Cost reporting" above).
5. `docket doctor` and `docket cost` **MUST** warn at ≥80% and flag ≥100% of cap (using recorded
   spend, the same figure `docket cost` reports), and flag runaway sessions (turn/cost
   thresholds) — these two checks remain display-only, independent of the pause writer.
6. **Known scope limit (unchanged by R-5):** enforcement exists only where docket itself is in
   the execution path — the pod-dispatch lane. A budget cap set on a non-pod agent, or spend
   from a Telegram session / direct daemon use outside dispatch, is still entirely ungated
   (per D-9/the "docket orchestrates hops" principle in ROADMAP §4.5) — there is no code path
   observing those turns to pause anything.

## Interface Contracts

### CLI Command Signatures

```bash
docket cost [agent-id]            # Usage and recorded cost (table)
docket cost --json                # Machine-readable (see cli-json-shapes.spec.md)
docket cost --history [--days N]  # Daily recorded-cost history
docket profile <agent-id> --budget <USD>   # Set/clear a cap (0 = none)
docket profile <agent-id> --resume         # Clear an auto-pause; unblocks a paused pod's Lead
docket doctor                     # Includes budget/runaway check (display only)
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid budget value)

## Examples

### Reporting cost and setting a cap

```bash
$ docket cost mywebsite
  Input tokens:   50,000
  Output tokens:  25,000
                              Total:  $0.5300 (recorded by daemon)

$ docket profile mywebsite --budget 5
[SUCCESS] Budget cap set to $5 for 'mywebsite'.
```

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

### A cap reached via the estimate fallback (daemon recorded no cost)

```bash
$ docket pod myproject dispatch
✗   myproject-lead: pod budget reached (~$4.80 (estimated — daemon recorded no cost) ≥ $1.00) before implementer
```

## Validation

### Pre-conditions

- For `--budget`, the value **MUST** parse as a non-negative number.

### Post-conditions

- After `--budget <n>` with n>0, `.docket-meta.json` **MUST** contain `budgetUsd = n` and no
  `paused` flag.
- After `--budget 0`, no active cap **MUST** remain.
- After a pod's spend (recorded, or estimated when the daemon recorded none) reaches its Lead's
  `budgetUsd`, the Lead's `.docket-meta.json` **MUST** contain `paused = true`,
  `pausedReason = "budget"`, and a subsequent dispatch attempt for that pod **MUST** claim
  nothing.
- After `--resume`, the target's `.docket-meta.json` **MUST** contain `paused = false`,
  `pausedReason = ""`, and an audit-log entry with `action = "profile.resume"` **MUST** exist.

### Invariants

- Reported dollar figures (`docket cost`) are daemon-recorded spend, never silently computed —
  unaffected by the gating estimate fallback in any way.
- A `paused` agent **MUST** always carry a `pausedReason`.
- An estimate used for budget gating **MUST** always render clearly labelled as an estimate and
  **MUST NOT** be summed into, or presented as, recorded spend.

## Changelog

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
