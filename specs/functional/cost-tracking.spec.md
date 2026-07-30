# Cost Tracking Specification

**Version**: 1.1.0
**Status**: Partially implemented (reporting + caps complete; auto-pause NOT implemented — see Requirements)
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
3. Setting a non-zero budget **MUST** clear a prior `paused` state.
4. The budget value **MUST** be a non-negative number.
5. Budget fields (`budgetUsd`, `paused`, `pausedReason`) are docket-local (decision D-9);
   the daemon never reads them. Enforcement therefore exists only where docket itself is
   in the execution path.

### Enforcement, warnings, and pause

1. **Implemented:** the pod-dispatch lane checks recorded pod spend against the Lead's
   `budgetUsd` before each hop and blocks the task when the cap is reached
   (pod-dispatch.spec.md). `docket doctor` and `docket cost` **MUST** warn at ≥80% and
   flag ≥100% of cap, and flag runaway sessions (turn/cost thresholds) — display only.
2. **NOT implemented (tracked as ROADMAP Phase 14 R-5):** automatic pause. No code path
   currently writes `paused=true` — the capability line "auto-pause at cap" **MUST NOT**
   be claimed until R-5 lands. Turns outside the dispatch lane (Telegram sessions,
   direct daemon use) are entirely ungated today.
3. Target contract once R-5 lands: at ≥100% of cap the agent is marked `paused` with
   `pausedReason="budget"`, dispatch refuses paused members, and `docket profile <id>
   --resume` clears the state with an audit entry.

## Interface Contracts

### CLI Command Signatures

```bash
docket cost [agent-id]            # Usage and recorded cost (table)
docket cost --json                # Machine-readable (see cli-json-shapes.spec.md)
docket cost --history [--days N]  # Daily recorded-cost history
docket profile <agent-id> --budget <USD>   # Set/clear a cap (0 = none)
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

## Validation

### Pre-conditions

- For `--budget`, the value **MUST** parse as a non-negative number.

### Post-conditions

- After `--budget <n>` with n>0, `.docket-meta.json` **MUST** contain `budgetUsd = n` and no
  `paused` flag.
- After `--budget 0`, no active cap **MUST** remain.

### Invariants

- Reported dollar figures are daemon-recorded spend, never silently computed.
- A `paused` agent **MUST** always carry a `pausedReason` (enforceable once R-5 lands —
  today nothing writes either field).

## Changelog

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
