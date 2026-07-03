# Pod Dispatch Pipeline Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-07-02

## Purpose

This specification defines the pod dispatch pipeline's state machine — how `docket pod
<project> dispatch` (and the opt-in `docket serve --dispatch` loop) drives one queued task
through a pod's roles hop by hop, what blocks advancement at each hop, and what a caller can
observe (task status, per-hop record, trace events) after a run. The pipeline itself lives in
`src/docket/core/dispatch.py`; this document is its behavioral contract, filling the gap Phase
12's audit (CH-10) found — no spec previously owned this state machine directly (the closest
prior document, `team-coordination.spec.md`, covers the retired manager queue only).

## Scope

This specification covers:

- Pipeline hop order and which roles participate for a given pod
- Per-hop execution: message construction, environment injection, the real agent turn
- The three gates that can block pipeline advancement mid-run: budget, implementer
  verification (`verifyCmd`), and tester PASS/FAIL
- Hop-failure semantics common to all hops (a failed subprocess call)
- The task-level status vocabulary (`done` / `failed` / `blocked`) and what persists
- Trace events emitted per hop and per gate outcome

This specification does NOT cover:

- The `.docket-meta.json` fields that configure a pod member (`portRangeStart`,
  `portRangeCount`, `scratchDir`, `verifyCmd`) — see `docket-meta.spec.md`
- The CLI surface for queuing/inspecting tasks (`docket pod <project>
  delegate/queue/add/set-verify`) — see `cli-interface.spec.md`
- Budget-cap accounting and pause behavior in general (see `cost-tracking.spec.md`) — this
  spec covers only the pre-hop budget check that blocks a dispatch run
- The retired org-wide `docket team` queue (see `team-coordination.spec.md`'s "Retired" section)

## Requirements

### Pipeline order and participation

1. A dispatch run **MUST** drive hops in the fixed order Lead → Implementer → Reviewer →
   Tester (`PIPELINE_ORDER`), skipping any role the pod does not have. A lean pod (Lead +
   Implementer only) runs exactly two hops; a full pod runs four.
2. A pod **MUST** have a Lead to be dispatchable at all; dispatching a project with no pod, or
   a pod with no Lead, **MUST** raise a `DispatchError` rather than attempt any hop.
3. Dispatch **MUST NOT** send a task to any agent outside the target project's own pod — each
   hop's member id is asserted against the pod before its turn runs.

### Per-hop execution

1. Each hop **MUST** be one real, costed agent turn via the ACL's `agent_run` — dispatch never
   simulates or skips a turn to save cost.
2. The message handed to each role **MUST** thread prior hops' output so a later role sees
   what earlier roles produced (the Tester's message additionally states its required
   PASS/FAIL reply convention verbatim, see "Tester PASS/FAIL gate" below).
3. An **Implementer** hop with an allocated pod port range (`portRangeStart` set) **MUST**
   receive `DOCKET_PORT_BASE`, `DOCKET_PORT_COUNT`, and `DOCKET_SCRATCH_DIR` in its subprocess's
   real environment (layered on top of the parent env, which is never mutated). Every other
   hop (Lead, Reviewer, Tester, or an Implementer with no allocation) **MUST** receive no
   environment override — today's inherit-the-parent-env behavior. See `docket-meta.spec.md`
   for the fields themselves.
4. Every hop **MUST** emit a `tool_call` trace event before the turn and a `tool_result` (on
   success) or `error` (on failure) event after it; a nonzero-cost turn **MUST** additionally
   emit a `cost_charged` event.

### Budget gate

1. Before **every** hop (not just the first), dispatch **MUST** check the pod's accumulated
   recorded spend (summed across all pod members) against the pod's budget cap (the Lead's
   `budgetUsd`, `0` = unlimited).
2. If the cap is met or exceeded, the task **MUST** be left in a `blocked` status (persisted
   back to the queue as `pending`, with `blockedReason` set) and the pipeline **MUST NOT**
   attempt the gated hop or any later one. A `budget_exceeded` trace event **MUST** be emitted
   naming the role the budget was checked before.
3. A `blocked` task **MUST** remain in the queue for a later dispatch run once budget allows —
   it is not a terminal failure.

### Hop-failure semantics (general)

1. If a hop's underlying `agent_run` call is not `ok` (CLI missing, timeout, nonzero exit, or
   an OS-level failure), the task **MUST** immediately transition to `failed` with a reason
   naming the role and the underlying error, and **MUST NOT** attempt any later hop.
2. A `failed` task **MUST** persist its full per-hop record (`role`, `member`, `ok`, `costUsd`,
   `error`) so a caller can see exactly which hop stopped the pipeline and why.

### Implementer verification gate (`verifyCmd`)

1. After a **successful** Implementer hop, if the Implementer's `verifyCmd` is set, dispatch
   **MUST** run it via `run_verify_cmd` in the Implementer's codebase (or its workspace
   directory for a task-type agent) and treat a nonzero exit as a gate failure.
2. A verification failure **MUST** transition the task to `failed` (reason includes the
   command), emit a `verification_failed` trace event with the (redacted) command output, and
   **MUST NOT** advance to Reviewer/Tester.
3. If `verifyCmd` is unset or empty, dispatch **MUST NOT** silently skip without a visible
   trace — today this is a printed `[dispatch] verification skipped` message (honesty rule:
   an operator can tell a gate was configured or not, never guess).
4. This gate only applies to the Implementer hop; Reviewer and Tester hops are never subject
   to it.

### Tester PASS/FAIL gate

1. After a **successful** Tester hop (`agent_run` returned `ok`), dispatch **MUST** parse the
   Tester's reply for a verdict marker: the first non-blank line of the output is matched,
   case-insensitively, against `^(PASS|FAIL)\b`.
2. A `PASS` verdict **MUST** allow the pipeline to advance to `done` normally.
3. A `FAIL` verdict, or output whose first non-blank line does not match the marker at all
   (unparseable — including empty output), **MUST** block pipeline advancement: the task
   transitions to `failed` with a distinct reason (`"tester reported FAIL"` vs `"tester output
   unparseable (expected a PASS/FAIL first line)"`), and a `tester_verdict_failed` trace event
   **MUST** be emitted carrying the parsed verdict (`"fail"` or `"unparseable"`) and the
   redacted output. FAIL and unparseable **MUST** remain distinguishable in the reason and are
   never conflated.
4. This gate **MUST NOT** affect pods with no Tester member — the check only runs when a
   Tester hop is actually part of the pipeline for that pod.
5. This gate is structural, not textual advice: a successful subprocess call alone (`ok=True`)
   is insufficient for the pipeline to advance past a Tester hop — the reply content itself is
   inspected.
6. The Reviewer hop has no equivalent gate — its signal is already the adapter-level `ok` from
   its own turn; there is no separate text convention to parse for Reviewer.

### Task status vocabulary

1. `done` — every present hop ran and passed all applicable gates.
2. `failed` — a hop's subprocess call failed, a `verifyCmd` failed, or a Tester verdict was
   FAIL/unparseable. Terminal for this dispatch attempt; the task is not automatically retried.
3. `blocked` — the pod's budget cap was reached before a hop could run. Not terminal — the task
   is left `pending` in the queue for a future dispatch run.

## Interface Contracts

This spec defines behavior only; the CLI surface that triggers it
(`docket pod <project> dispatch`, `docket serve --dispatch`) is documented in
`cli-interface.spec.md`.

### Trace events this pipeline emits

```text
session_start          # once, at the start of dispatch_task
tool_call               # before each hop's agent_run
tool_result             # after a successful hop
error                   # after a failed hop (in place of tool_result)
cost_charged            # after any hop with nonzero cost
budget_exceeded         # the budget gate blocked a hop
verification_failed     # the Implementer's verifyCmd exited nonzero
tester_verdict_failed   # the Tester's reply was FAIL or unparseable
session_end             # once, at the end of dispatch_task, carrying the final status
```

## Examples

### A lean pod (Lead + Implementer, no `verifyCmd`) completing normally

```text
$ docket pod myapp dispatch
[dispatch] verification skipped — verifyCmd not set for myapp-implementer
Task task-1720000000000: done ($0.0142)
```

### A full pod blocked by a Tester FAIL

```text
$ docket pod myapp dispatch
Task task-1720000000001: failed — tester reported FAIL
```

### A pod blocked on budget before the Implementer hop

```text
$ docket pod myapp dispatch
Task task-1720000000002: pending (blocked) — pod budget reached ($5.00 >= $5.00) before implementer
```

## Validation

### Pre-conditions

- The target project **MUST** have a provisioned pod with at least a Lead.
- The task **MUST** already be queued (`docket pod <project> delegate`) with status `pending`.

### Post-conditions

- After a run, the task's `status`, `reason`, `hops`, and `costUsd` **MUST** be persisted back
  to the pod's `TASK_LIST.json`.
- A `blocked` task **MUST** be re-persisted as `pending` (with `blockedReason` set) so it is
  picked up again by a later dispatch run.

### Invariants

- Dispatch **MUST NOT** cross pods: every hop's member id belongs to the dispatched project's
  own pod.
- A gate (budget, `verifyCmd`, Tester verdict) **MUST NOT** be bypassed by an otherwise-`ok`
  subprocess call — `ok=True` is necessary but not sufficient for pipeline advancement past the
  Implementer or Tester hops.
- Every hop, gate pass, and gate failure **MUST** be traceable via `docket trace tail
  <project>` — nothing in the pipeline is silent (including the printed
  verification-skipped notice).

## Changelog

### Version 1.0.0 (2026-07-02)

- FD-6: initial specification. No prior spec owned the dispatch pipeline's state machine
  directly (confirmed absent per Phase 12's CH-10 audit); this document closes that gap for the
  behavior Phase 13 made real: FD-0's environment injection for Implementer hops, and FD-2's
  structural Tester PASS/FAIL gate (`tester_verdict_failed`). The pre-existing budget gate,
  general hop-failure semantics, and CD-2's `verifyCmd` gate (previously undocumented as a
  state machine, only as data fields in `docket-meta.spec.md`) are documented here for the
  first time as the current, shipped behavior.
