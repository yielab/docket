# Token Usage and Budget Caps Specification

**Version**: 2.0.0
**Status**: Implemented. Token usage is measured and reported in tokens only: docket keeps no
rate table, no cost and no dollar estimate (ADR 0038 decision 5). Caps and auto-pause act only on pod
dispatch.
**Last Updated**: 2026-11-03

## Purpose

This specification defines how docket reports measured token usage per pod, stores a per-pod
budget cap, and where that cap is (and is not) enforced. docket reports no dollar figure anywhere:
no rate table, no cost, no estimate. A backend that converts tokens to money itself (an
observability exporter's receiver, a provider's bill) still can; docket sends it tokens only.

## Scope

This specification covers:

- Reporting usage (`docket status`)
- The per-pod budget cap (`docket pod set budgetTokens`), a count of tokens, and the window it is
  counted over (`docket pod set budgetWindow`)
- Budget warnings (`docket setup`), the pre-hop gate and the pause contract

This specification does NOT cover the role→model policy (see model-profiles.spec.md), nor the pod-dispatch pre-hop budget gate's mechanics (see
pod-dispatch.spec.md).

## Requirements

### Usage reporting (docket status)

1. `docket status` **MUST** report the pod's measured token usage beside the pod's
   success/failure/aborted counts and latency (read from trace `session_end` events);
   `status --json` carries it as `usage.input` and `usage.output`, and no key anywhere in the
   payload names a cost, a rate or a dollar. `status --all --json` carries the fleet inventory
   with the same rule.
2. Token totals **MUST** be derived from `DocketDriver`'s usage report, which reads the
   session store under `$DOCKET_HOME/sessions`, the only live session shape.
3. docket **MUST NOT** turn a token count into a dollar figure: no rate table, no estimate label,
   no recorded-versus-estimated distinction. A turn result, a hop, a task, a trace event, a
   metric and a wire payload carry tokens and no dollar field. A record written before this
   contract that still holds a stored cost key loads, and its next write drops the key.
4. The session-format parsing behind requirement 2 **MUST** live entirely inside `DocketDriver`
   and **MUST NOT** appear in the domain layer. The domain's `aggregate_usage` and
   `usage_history` return whatever the default driver (`DocketDriver`, unconditionally) reports, as
   the `UsageTotals` and `UsageDay` shapes the driver port defines; they open no session file
   themselves. A guard test (`test_product_code_has_no_retired_daemon_reference`) fails the build if
   external-runtime coupling returns to `src/`.
5. Wherever `docket run` shows a pod's cap, it **MUST** show it in tokens beside the pod's counted
   tokens so far (`Pod budget cap: N tokens (M counted so far)`), the figure the gate compares.

6. **Tokens per accepted task** is the counted tokens (input minus cache reads, plus output) of
   every task whose status is `done` and that carries a `usage` block, summed across the
   dispatchable pods and divided by their number; a task that did not end `done`, or that has no
   `usage`, is not in it, so a failed attempt's tokens never lower the figure. `docket log
   --summary` **MUST** print it as `tokens per accepted task: N counted (K done tasks)` (rounded
   to a whole token; `no done task with usage yet` when there is none), followed by the cache-hit
   ratio of every recorded `llm_call` (`trace-store.spec.md` requirements 39-40). The same figure
   is the `docket_tokens_per_accepted_task` metric (`serve-read-api.spec.md`). Both are measured
   tokens read from records docket already keeps; neither is a projection.
7. `docket status --history [--days N]` **MUST** print one row per UTC day on which any of the
   pod's members spent tokens, summed over the members' sessions and read from each session's
   `usageByDay` buckets (`DocketDriver.usage(...).by_day`); with `--json` it emits `{"history":
   [...]}` (cli-json-shapes.spec.md). A session written before the buckets existed has no day, so
   it adds no row; a home with no dated usage prints `No dated session data yet` and `{"history":
   []}`.

### Budget caps

1. `docket pod set budgetTokens <N>` **MUST** store a `budgetTokens` cap, a whole number of
   counted tokens above `0`, in the pod Lead's `.docket-meta.json`. The pod's counted tokens are
   the measure a task's `maxTokens` uses: input minus cache reads, plus output, summed over the
   pod's members.
2. A pod has no cap while `budgetTokens` is absent. `docket pod unset budgetTokens` clears the
   cap. There is no `0` for "none": `0` is refused like any value that is not a positive whole
   number.
3. Setting a budget or unsetting it **MUST** clear a prior `paused` state and
   unblock the pod's blocked tasks (see pod-dispatch.spec.md), so no task is refused at claim by
   a pause the cap no longer justifies.
4. A value that is not a whole number above `0` exits `1` naming the setting, and the stored
   settings are untouched.
5. **`budgetUsd` is gone.** `docket pod set budgetUsd`, a pod document, an `agents --from` entry,
   a `POST /pods` body or a stored meta that still carries `budgetUsd` (or the old HTTP `budget`)
   **MUST** be refused, naming `budgetTokens`; nothing is converted or ignored. docket records
   no dollars (ADR 0038 decision 5), so a dollar cap gated an estimate from a rate table and
   never tripped on a model the table did not list. docket keeps no rate table at all.
6. Budget fields (`budgetTokens`, `paused`, `pausedReason`) are docket-local (decision D-9).
   Enforcement therefore exists only where docket itself is in the execution path.
7. One writer, `resume_pod`, serves `docket run --resume`, `docket pod set`/`unset` of
   `budgetTokens` or `budgetWindow` and `POST /pods/<p>/resume`. It **MUST** clear
   `paused`/`pausedReason` on the pod's Lead and **MUST** write a `run.resume` audit-log entry
   when the Lead was paused (the HTTP route's carries `channel=http`; a call on a pod that is not
   paused writes none). It also unblocks that pod's
   blocked tasks whether or not the Lead was paused, then reclaims stale claims: a resume
   that left the tasks queued up behind the pause permanently `blocked` would not actually resume
   anything.
8. No blueprint sets a pod budget: a cap is opt-in, and a task's `maxTokens` and the per-turn
   token budget already bound spend.
9. **The window.** `docket pod set budgetWindow <day|week|none>` stores the span the cap is counted
   over; absent reads as `none`, and any other value is refused naming the three. `none` counts
   every token the pod has ever spent (requirement 1). `day` counts from 00:00 UTC today and `week`
   from 00:00 UTC on the most recent Monday: the tokens of the days on or after that date, each
   day's tokens being those of the sessions' appends made on that UTC day
   (session-history.spec.md requirement 7). The window is calendar-aligned, never a rolling span,
   and a session written before the day buckets existed counts toward `none` only. Setting or
   unsetting `budgetWindow` clears a prior `paused` state and unblocks the pod's blocked tasks, as
   `budgetTokens` does (requirement 3).

### Enforcement, warnings, and pause

1. **Cap enforcement.** The pod-dispatch lane compares the pod's counted tokens, over the pod's
   `budgetWindow`, with the Lead's `budgetTokens` before each hop and blocks the task when the cap
   is reached (pod-dispatch.spec.md). The comparison needs no rate, so it holds for every model, a
   model the catalog does not list included. A `budget_exceeded` trace event records `spent`,
   `cap` and `role`, all integers, and `window` (`none`, `day` or `week`) and `windowStart` (the
   UTC instant the count began, `null` for `none`). The hop's token ceiling (requirement 4) counts
   the same window.
2. **Auto-pause.** The same check that blocks a task also marks the pod's Lead
   `paused = true`, `pausedReason = "budget"` (through the store chokepoint, per D-9). Once
   paused, dispatch refuses **every** further claim for that pod outright, before a task is
   flipped to `running`, and emits a `paused_refused` trace event each time. A paused pod costs
   nothing further to not dispatch: no claim write, no wasted agent turn.
3. **Resume.** `docket run --resume` clears both fields and writes an audit entry (see "Budget
   caps" above); a fresh dispatch attempt can claim again.
4. **A hop runs under what the pod has left.** The hop's token ceiling is the tighter of the
   task's `maxTokens` leftover and the pod's `budgetTokens` leftover (the per-turn default
   otherwise, which a pod leftover only ever lowers). When the pod's leftover is the tighter, a
   stop on it is a `budget_exhausted` stop with `source: "pod_budget"` and `raise:
   "budgetTokens"` (agent-loop.spec.md requirement 107), so the plan of record reads what to raise.
5. **Budget and runaway warnings.** `docket setup`'s per-agent budget check **MUST** compare the
   agent's counted tokens with its `budgetTokens`: a warning at 80% or more of the cap, a flag at
   100% or more. It is display-only, independent of the pause writer. The turn-count runaway
   check compares turns only (`runaway_turns_threshold`, `RUNAWAY_TURNS_THRESHOLD`). `docket setup --json`'s per-agent `budget`
   results carry `tokens`, `budgetTokens` (`null` without a cap), `pct` (only with a cap) and
   `ok`; its `runaway` results carry `id`, `turns` and `ok`.
6. **Scope limit.** Enforcement exists only where docket itself is in the execution path, the
   pod-dispatch lane, the only place a turn runs. A `budgetTokens` stored on a non-pod agent is
   read by the `docket setup` warning and nothing else; no code path pauses anything for it (per
   D-9 and the "docket orchestrates hops" principle).

## Interface Contracts

### CLI Command Signatures

```bash
docket status                     # Pod tokens and outcomes (table)
docket status --all --json        # Machine-readable (see cli-json-shapes.spec.md)
docket status --history [--days N]  # Tokens per UTC day, from the sessions' day buckets
docket log --summary              # Tokens per accepted task and cache-hit ratio (not with --json)
docket pod set budgetTokens <N>   # Set a cap, in counted tokens (a whole number above 0)
docket pod unset budgetTokens     # Clear the cap
docket pod set budgetWindow <day|week|none>  # Count the cap from today or this Monday, UTC
docket run --resume               # Clear an auto-pause, unblock blocked tasks, reclaim stale claims
docket setup                      # Includes budget/runaway check (display only)
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown pod, invalid budget value)

## Examples

### Reporting usage and setting a cap

```bash
$ docket status --pod mywebsite
  Tokens:                   50.0K in / 25.0K out

$ docket pod set budgetTokens 500000
ok Set budgetTokens=500000 for pod 'mywebsite'
```

### A pod pausing at its cap, and resuming

The block reason carries the counted tokens and the cap, both measured.

```bash
$ docket run --pod myproject
! [<task-id>] blocked — pod budget reached (512340 of 500000 tokens counted) before implementer

$ docket run --resume
-> Unblocked 1 blocked task(s) in pod 'myproject'
```

## Validation

### Pre-conditions

- For `pod set budgetTokens`, the value **MUST** parse as a whole number above `0`.

### Post-conditions

- After `pod set budgetTokens <n>`, the Lead's `.docket-meta.json` **MUST** contain
  `budgetTokens = n` (an integer) and no `paused` flag.
- After `pod unset budgetTokens`, no active cap **MUST** remain.
- After a pod's counted tokens reach its Lead's `budgetTokens`, the Lead's `.docket-meta.json`
  **MUST** contain `paused = true`,
  `pausedReason = "budget"`, and a subsequent dispatch attempt for that pod **MUST** claim
  nothing.
- After `docket run --resume` on a paused pod, the Lead's `.docket-meta.json` **MUST** contain
  `paused = false`, `pausedReason = ""`, and an audit-log entry with `action = "run.resume"`
  **MUST** exist.

### Invariants

- No payload, table, metric or trace record docket writes carries a dollar figure.
- A `paused` agent **MUST** always carry a `pausedReason`.
- The budget gate reads measured tokens only: no rate, estimate or model name enters it.

## Implementation

- `src/docket/hops/application/usage.py`: `aggregate_usage`, `usage_history`, `pod_counted_tokens`
- `src/docket/agent/session.py`: `SessionRecord.usageByDay`, written by `append_messages`
- `src/docket/hops/gates/pre_hop.py`: the pre-hop budget gate (`_gate_budget`), the hop's token ceiling, the Lead pause writer
- `src/docket/hops/domain/gate_decisions.py`: `decide_pod_budget`, `turn_token_ceiling`, `window_start`
- `src/docket/teams/settings.py`: `pod_budget`
- `src/docket/teams/pod_settings.py`: `PodSettings.budget_window`
- `src/docket/tasks/application/lifecycle.py`: `unblock_pod`, `resume_pod`
- `src/docket/hops/application/report.py`: `_budget_fields` (the `budget` object of `GET /pods`, `GET /pods/<p>`)
- `src/docket/tasks/application/queue.py`: the claim-time pause check
- `src/docket/observability/trace.py`: `terminal_outcomes`, `EVENT_TYPES` (`budget_exceeded`, `paused_refused`)
- `src/docket/agent/ports.py`: `UsageTotals`, `UsageDay`, `UsageReport`, `DriverCapabilities`
- `src/docket/hops/application/driver.py`: `DocketDriver.usage`, `DocketDriver.capabilities`
- `src/docket/interfaces/cli/commands/status.py`: `docket status`, the per-pod usage summary, the fleet inventory, `usage_snapshot` (the MCP `usage` tool reads it)
- `src/docket/interfaces/cli/commands/pod.py`: `docket pod set|unset budgetTokens`, `budgetWindow`
- `src/docket/interfaces/cli/commands/run.py`: `docket run --resume`, the cap header
- `src/docket/interfaces/cli/commands/setup_check.py`: the `docket setup` budget and runaway checks
