# Pod Dispatch Pipeline Specification

**Version**: 2.1.0
**Status**: Complete for what it documents (task cancellation and parallel hop execution are
explicitly out of scope — see "Does NOT cover"; tracked as Phase 16 W-2). The require_approval
gate itself (Requirements → "require_approval gate and waiting_approval") ships with exactly one
wired source (pod-level); its two other documented sources are explicit, inert seams — see that
section's "Sources" list.
**Last Updated**: 2026-07-30

## Purpose

This specification defines the pod dispatch pipeline's state machine — how `docket pod
<project> dispatch` (and the opt-in `docket serve --dispatch` loop) claims and drives queued
tasks through a pod's roles hop by hop, how it survives a crash mid-task, how a task retries,
blocks, waits for a human decision, and resumes, what gates can stop advancement at each hop, and
what a caller can observe (task status, per-hop record, trace events) after a run. The pipeline
itself lives in `src/docket/core/dispatch.py`; this document is its behavioral contract.
**Version 1.0.0** (Phase 12/13) documented the original straight-line pipeline (three gates,
`done`/`failed`/`blocked` only, no persisted `running` state, no retries, one hardcoded timeout).
**ROADMAP Phase 14** (R-1…R-7, "runtime truth & dispatch hardening") rebuilt the state machine
underneath that contract: locked claims, a persisted `running` state, crash recovery, retries
with a failure taxonomy, independent timeouts, a real Reviewer gate with bounded rework, real
budget auto-pause, and a bounded hop prompt. **ROADMAP Phase 15 G-1** ("approval-gated dispatch")
added a sixth task status, `waiting_approval`, and the require_approval gate that produces it —
`core/approval.py`'s pending-approval store previously had no production producer at all; this is
that missing producer. This version documents that machine as it actually ships.

## Scope

This specification covers:

- The task record's full lifecycle: creation, locked claiming, persisted `running` state,
  per-hop incremental persistence, terminal states, and how a task moves between them
- Crash recovery: the stale-claim sweep and `--resume`-driven continuation from the last
  persisted hop (including mid-rework)
- Concurrency: why two dispatchers can never double-run one task
- Pipeline hop order and which roles participate for a given pod, including the Reviewer's
  bounded rework loop (a role may run more than once within one dispatch attempt)
- Per-hop execution: message construction (with a bounded-size carryover cap), environment
  injection, the real agent turn, and retries of a transient failure
- Timeout configuration: independent agent-turn vs. `verifyCmd` timeouts and their resolution
  order
- The gates that can block pipeline advancement mid-run: budget (with auto-pause), the
  require_approval gate (waits on a human decision, resumable), Implementer verification
  (`verifyCmd`, run in the correct working tree), Reviewer verdict (with bounded rework), and
  Tester PASS/FAIL
- The require_approval gate's single wired source for this version (a pod-level Lead-meta role
  list), how a fired gate is resolved (grant resumes at the exact hop, deny fails the task
  immediately, an expiry fail-closes to denied), and why a `waiting_approval` task is never
  claimable by a plain dispatch run
- The complete task-status and failure-kind vocabulary, and every trace event this pipeline emits

This specification does NOT cover:

- The `.docket-meta.json` fields that configure a pod member (`portRangeStart`,
  `portRangeCount`, `scratchDir`, `verifyCmd`, `turnTimeoutS`, `verifyTimeoutS`,
  `maxReworkCycles`, `requireApprovalRoles`, `paused`/`pausedReason`) — see `docket-meta.spec.md`
- A policy-driven require_approval match (ROADMAP Phase 15 G-2) and a pipeline-defined `approval`
  step (ROADMAP Phase 16 W-1/W-2) — both are explicit, documented seams in `core/dispatch.py`
  (`_policy_requires_approval`, `_pipeline_step_requires_approval`) that always return `False`
  today; neither is wired to any real source yet, and this spec does not invent one
- `core/approval.py`'s own approval-record lifecycle (`pending`/`granted`/`denied`, the CLI/HTTP
  channels, audit-log parity) — see `security-gates.spec.md`. This spec covers only how
  *dispatch* creates and reacts to a record, not the record's own store contract
- The CLI surface for queuing/inspecting/dispatching tasks (`docket pod <project>
  delegate/queue/add/set-verify/dispatch`, including their flags) — see `cli-interface.spec.md`
- Budget-cap accounting in general, and the `docket profile <id> --budget`/`--resume` CLI
  contract — see `cost-tracking.spec.md`. This spec covers only the pre-hop budget check and the
  auto-pause/claim-refusal mechanics it drives
- The persisted dispatch-run registry (`core/runs.py`, `docket runs`, `GET /runs`) that records
  *invocations* of this pipeline (one record per `dispatch_pod` call, whatever triggered it) — see
  `serve-read-api.spec.md` and `cli-json-shapes.spec.md`. This spec is scoped to what happens
  *inside* one such invocation
- `edges/store.py`'s `with_lock`/`read_modify_write` locking primitive itself (this spec only
  relies on its atomicity guarantee) — see the module's own docstring
- Task **cancellation** (killing an in-flight hop's process) and **parallel** hop execution —
  neither exists; both are tracked as ROADMAP Phase 16 W-2 and require an executor this pipeline
  does not have today
- The retired org-wide `docket team` queue (removed-command notice only; durable record in
  ROADMAP decision D-11 — its spec was removed 2026-07-30)

## Requirements

### Task lifecycle and identity

1. A newly queued task (`docket pod <project> delegate`) **MUST** be created with a unique
   `task-<uuid4>` id (not a timestamp — concurrent enqueues under the same millisecond would
   otherwise collide and leak false ordering), `status: "pending"`, a `created` timestamp,
   `priority` (`high`/`normal`/`low`, default `normal`), an empty `hops` array, `costUsd: 0.0`,
   and `claimId`/`claimedAt`/`startedAt`/`completedAt` all unset.
2. A task record loaded from a pre-Phase-14 queue file (missing the fields this version adds)
   **MUST** be transparently backfilled with their defaults on every read (`_normalize_task`) —
   no separate migration step exists or is required.
3. A task's status **MUST** be one of exactly five values: `pending`, `running`, `done`,
   `failed`, `blocked`. (See "Task status vocabulary" below for terminal vs. non-terminal.)

### Claiming (locked, race-free)

1. Before a task's first hop runs, it **MUST** be **claimed**: a single locked
   read-modify-write (`edges/store.py`'s `read_modify_write`, holding the queue file's
   per-directory filelock for the whole operation) that selects the next eligible task, flips its
   status `pending` → `running`, and persists `startedAt`, a fresh `claimId` (a `uuid4` token,
   regenerated on every claim — an identifying/observability value, not itself compared on a
   later write; the concurrency guarantee comes from the filelock held during the
   read-modify-write, not from a claimId check), and `claimedAt` — all **before** the function
   returns and before any hop is attempted.
2. Because the read (which task is next), the mutation (flip to `running`), and the write all
   happen inside one lock acquisition, two concurrent `dispatch_pod` calls against the same pod
   (different threads, or different processes) **MUST NOT** be able to claim the same task: the
   second caller's read already observes the first caller's claim and either picks a different
   eligible task or finds none left. This is what makes the serve webhook thread, the schedule
   thread, the sweep loop, and a manual CLI dispatch all safe to run concurrently against one
   pod.
3. Eligible-for-claim rules: a `pending` task is always eligible. A `failed` task whose
   `failureKind` is `"stale_claim"` (see "Crash recovery" below) is eligible **only** when the
   caller passed `resume=True` (`docket pod <project> dispatch --resume`) — crash recovery is
   opt-in, never automatic. No other status is ever claimable (in particular, `blocked` and a
   plain `failed` — one whose failure was a real gate/hop failure, not a swept stale claim — are
   never reclaimed by a dispatch run; see "blocked and terminal-failure re-entry" below).
4. Among eligible tasks, the highest-priority one is claimed first (`high` < `normal` < `low`
   rank); ties are broken by queue order (a stable sort preserves each task's original enqueue
   position).
5. A pod whose Lead is currently paused (see "Budget gate and auto-pause") **MUST** refuse every
   claim outright — no task is even flipped to `running`, and a `paused_refused` trace event is
   emitted every time a claim is attempted against a paused pod. This check happens before the
   locked claim operation (pause changes are rare, operator-driven events, not something
   concurrent claims race over), so a paused pod costs nothing further to not dispatch: no claim
   write, no wasted agent turn.

### Per-hop incremental persistence and crash recovery

1. As each hop completes — success or failure, including every rework hop (see "Reviewer verdict
   gate") — its record **MUST** be appended to the task's persisted `hops[]` array immediately
   (`_persist_hop`), not held in memory until the whole task finishes. A crash between hop *N*
   finishing and hop *N+1* starting therefore loses at most the in-flight attempt, never a
   completed hop.
2. Every hop-completion persist, and every retry attempt (see "Retries"), **MUST** refresh the
   task's `claimedAt` timestamp (`_persist_hop`/`_touch_claim`) — both are forward progress, not
   staleness, and this is what stops a legitimately long-running hop (especially one retrying)
   from being mistaken for a crashed claim by a *concurrent* dispatcher's stale-claim sweep.
3. At the top of every `dispatch_pod` call (including one made by a different thread/process
   than the one that claimed a task), any `running` task whose `claimedAt` is older than
   `CLAIM_STALE_TIMEOUT` (default 1800s, env-overridable) **MUST** be swept to `failed` with
   `failureKind: "stale_claim"` and a `stale_claim` trace event, its `claimId` cleared, and its
   already-persisted `hops[]` left untouched. This is the presumption that the dispatcher which
   claimed it crashed mid-task.
4. `docket pod <project> dispatch --resume` **MUST** reclaim a `stale_claim`-failed task (per the
   eligibility rule above) and continue it from its last persisted hop rather than hop 0: the
   claimed task's existing `hops[]` seed `dispatch_task`'s `resume_from`, and the roles they
   represent are skipped rather than re-invoked. Without `--resume`, a swept task **MUST** stay
   `failed` and untouched by future dispatch runs (crash recovery is never automatic).
5. Resuming correctly requires more than "which roles already ran" once the Reviewer's bounded
   rework loop exists, because a role can legitimately appear more than once in a resumed task's
   history (the Implementer re-runs after a REQUEST-CHANGES, then the Reviewer re-reviews).
   `_replay_pipeline_position` **MUST** replay the persisted hop sequence to recompute the exact
   pipeline position, rework-cycle count, and (if resuming mid-rework) which Reviewer hop's text
   still needs to reach the Implementer — the same decision a live run makes — so a task resumed
   mid-rework re-enters the rework Implementer hop, never a stale position past the Reviewer.

### blocked and terminal-failure re-entry

1. A task the budget gate stops (see "Budget gate and auto-pause") **MUST** transition to
   `blocked`, **MUST NOT** be silently rewritten back to `pending`, and **MUST** persist a
   `blockedReason`. A `blocked` task is not attempted again by any future `dispatch_pod` call —
   it is not in the claimable set at all — until one of exactly two operator-driven actions moves
   it back to `pending`:
   - `docket pod <project> queue --retry <task-id>` (`retry_task`) — a single named task, a
     no-op if that task isn't currently `blocked`.
   - A pod-wide budget change on the Lead (`docket profile <lead-id> --budget <n>` with `n > 0`,
     or `docket profile <lead-id> --resume`) — `unblock_pod` flips **every** `blocked` task in
     that pod's queue back to `pending` (see `cost-tracking.spec.md`).
2. A plain `failed` task (a real gate/hop failure — not a swept stale claim) is terminal for
   that dispatch attempt and **MUST NOT** be automatically retried by a later `dispatch_pod`
   call, with or without `--resume` (`--resume` only reclaims `stale_claim`-tagged failures).
   There is no CLI action that moves a plain `failed` task back to `pending` today — queuing a
   fresh task is the only path forward for a real failure.

### Pipeline order and participation

1. A dispatch run **MUST** drive hops in the fixed order Lead → Implementer → Reviewer → Tester
   (`PIPELINE_ORDER`), skipping any role the pod does not have. A lean pod (Lead + Implementer
   only) runs exactly two hops per pass; a full pod runs up to four, plus any rework cycles (see
   below).
2. A pod **MUST** have a Lead to be dispatchable at all; dispatching a project with no pod, or a
   pod with no Lead, **MUST** raise a `DispatchError` rather than attempt any hop.
3. Dispatch **MUST NOT** send a task to any agent outside the target project's own pod — each
   hop's member id is asserted against the pod before its turn runs, raising `DispatchError` on a
   mismatch.
4. Unlike the pre-Phase-14 pipeline, a role **MAY** legitimately run more than once within one
   dispatch attempt: a Reviewer REQUEST-CHANGES verdict re-runs the Implementer and then the
   Reviewer again (bounded — see "Reviewer verdict gate and bounded rework"). The pipeline
   position is tracked as an index that can move backward for a rework cycle, not a per-role
   "has this run yet" set.

### Per-hop execution

1. Each hop **MUST** be one real, costed agent turn via the ACL's `agent_run` — dispatch never
   simulates or skips a turn to save cost.
2. The message handed to each role **MUST** thread prior hops' output so a later role sees what
   earlier roles produced, subject to the bounded carryover cap (see "Bounded hop prompts"
   below); the Reviewer and Tester messages additionally state their required verdict-marker
   reply convention verbatim.
3. An **Implementer** hop with an allocated pod port range (`portRangeStart` set) **MUST**
   receive `DOCKET_PORT_BASE`, `DOCKET_PORT_COUNT`, and `DOCKET_SCRATCH_DIR` in its subprocess's
   real environment (layered on top of the parent env, which is never mutated). Every other hop
   (Lead, Reviewer, Tester, or an Implementer with no allocation) **MUST** receive no environment
   override — today's inherit-the-parent-env behavior. See `docket-meta.spec.md` for the fields
   themselves.
4. Every hop **MUST** emit a `context_composed` event (the composed prompt's byte accounting —
   see "Bounded hop prompts") and a `tool_call` trace event before the turn, and a `tool_result`
   (on success) or `error` (on failure) event after it; a nonzero-cost turn **MUST** additionally
   emit a `cost_charged` event.

### Retries and the failure-kind taxonomy

1. Every agent turn's outcome (`AgentRunResult`, the ACL's `agent_run` return value) **MUST**
   carry a `failure_kind` on failure: `timeout` (the turn exceeded its timeout), `daemon_error`
   (a CLI/daemon-level failure — process couldn't run, OS error, malformed daemon response),
   `nonzero_exit` (the daemon ran and returned a real non-zero result), or `invalid_output`
   (the daemon succeeded but its output couldn't be used). A successful turn carries no
   `failure_kind`.
2. Only `timeout` and `daemon_error` **MUST** be treated as retryable — a transient hiccup, not a
   real answer. `nonzero_exit` and `invalid_output` (and, separately, a bad Reviewer/Tester
   verdict — see those gates) **MUST NEVER** be retried: retrying a real failure risks masking it
   as transient and burns budget for nothing.
3. A retryable failure **MUST** be retried in place, up to a per-role budget
   (`config.DISPATCH_RETRIES_PER_ROLE`, default 2 additional attempts — 3 total tries — per
   role, individually overridable per role via `DISPATCH_RETRIES_<ROLE>` env vars), with linear
   backoff between attempts (`attempt * DISPATCH_RETRY_BACKOFF_S` seconds, default base 2s).
   Exhausting the retry budget **MUST** fall through to the same failed-hop handling as a
   non-retryable failure.
4. The **total number of tries made** for a hop (1 if it succeeded or failed non-retryably on
   the first attempt; more only for a retried, ultimately-successful-or-exhausted hop) **MUST**
   be persisted on that hop's record as `attempts`.
5. Every retry attempt (before its backoff sleep) **MUST** emit a `hop_retry` trace event naming
   the attempt number, the role, the retry budget, and the failure kind that triggered it — and
   **MUST** refresh the task's `claimedAt` (see "Per-hop incremental persistence") before
   sleeping, so a long retry loop is never swept as a stale claim by a concurrent dispatcher.

### Timeout configuration

1. The agent-turn timeout and the `verifyCmd` timeout **MUST** be independently configurable —
   `turnTimeoutS` and `verifyTimeoutS` respectively, both optional fields on the pod Lead's
   `.docket-meta.json` (see `docket-meta.spec.md`).
2. Resolution order for a given dispatch invocation, highest precedence first: (a) an explicit
   override passed to that specific invocation — `docket pod <project> dispatch --timeout
   <seconds>` for a CLI-triggered run (this one flag overrides **both** the turn and verify
   timeout for that run), or the process-wide `DISPATCH_TURN_TIMEOUT_S`/`DISPATCH_VERIFY_TIMEOUT_S`
   env config for a run `docket serve` triggers (webhook, due schedule, or the sweep loop); (b)
   the pod Lead's own `turnTimeoutS`/`verifyTimeoutS` meta; (c) `DEFAULT_TIMEOUT` (300 seconds,
   `core/dispatch.py`) as the fallback of last resort.
3. When `docket serve`'s process-wide timeout env vars are set, they take the "explicit
   override" slot for every pod that server instance dispatches (webhook/schedule/sweep) — for
   those runs they are resolved *before* that pod's own Lead-meta setting is even consulted, not
   layered beneath it. A CLI-triggered `docket pod <project> dispatch` (no `--timeout`) is
   unaffected by the serve-wide env vars; it resolves straight to Lead-meta, then
   `DEFAULT_TIMEOUT`.

### Budget gate and auto-pause

1. Before **every** hop (not just the first, and including a rework hop), dispatch **MUST**
   check the pod's accumulated spend (summed across all pod members) against the pod's budget
   cap (the Lead's `budgetUsd`, `0` = unlimited).
2. Spend for this check **MUST** prefer the daemon's recorded cost; when the daemon has recorded
   exactly `0` across the pod (a real gap in some daemon versions — see `cost-tracking.spec.md`),
   dispatch **MUST** fall back to a labelled token-based estimate (`pod_gating_cost`) so a real
   cap can still trip. This estimate is for gating only and is rendered distinctly labelled
   wherever it appears (never mixed into `docket cost`'s recorded figures).
3. If the cap is met or exceeded, the task **MUST** transition to `blocked` (see "blocked and
   terminal-failure re-entry"; `blockedReason` persisted) and the pipeline **MUST NOT** attempt
   the gated hop or any later one for this task. A `budget_exceeded` trace event **MUST** be
   emitted naming the role the budget was checked before, the spend, the cap, and whether the
   spend figure was estimated.
4. The same check that blocks the task **MUST** also mark the pod's Lead paused
   (`_pause_lead_for_budget`: `paused = true`, `pausedReason = "budget"`, through the ACL/`meta_set`
   — never synced to `openclaw.json`, per D-9). From that point on, **every** further claim
   attempt against this pod — for this task or any other in its queue — **MUST** be refused
   outright at claim time (see "Claiming", item 6), not merely re-blocked hop by hop, until an
   operator clears the pause (`docket profile <lead-id> --resume`; see `cost-tracking.spec.md`).

### require_approval gate and waiting_approval (ROADMAP Phase 15 G-1)

1. Immediately after the budget gate (affordability) and before a hop's message is composed or
   its agent turn runs (permission), dispatch **MUST** evaluate whether that hop requires a human
   decision (`_hop_requires_approval`). This is an **OR** of independent sources — any one of them
   firing is enough to gate:
   - **Pod-level (wired this version):** the pod Lead's `requireApprovalRoles` meta field, a
     comma-separated, case-insensitive role list (e.g. `"implementer,reviewer"`) — see
     `docket-meta.spec.md`. Read the same way `maxReworkCycles`/`budgetUsd` are: only the Lead's
     value is consulted, and it has no dedicated CLI setter yet (`meta-set` only).
   - **Policy-driven (seam only — ROADMAP Phase 15 G-2, not wired):** `_policy_requires_approval`
     always returns `False` today. No policy source (e.g. a high-risk action-class match) is
     consulted. This is an explicit, documented gap, not a claim of coverage.
   - **Pipeline-defined (seam only — ROADMAP Phase 16 W-1/W-2, not wired):** `_pipeline_step_requires_approval`
     always returns `False` today — no task record has an explicit per-step `approval` format;
     this spec does not invent one.
2. A fired gate **MUST**: create a real, persisted approval record via `core/approval.py`'s
   `approval_create` (project, role, a human-readable action string, and a `context` of
   `{"taskId", "pipelineIndex"}` so the record can be traced back to the exact task and hop it
   gated); emit an `approval_required` trace event on the task's own session; and transition the
   task to `waiting_approval` **without** running the gated hop's agent turn at all. The task's
   `approvalToken` and `pendingApprovalIndex` (the pipeline position the gate fired at) **MUST**
   be persisted; its `claimId` **MUST** be cleared (no active claim while waiting). This is a real
   producer for a store that, before this card, had zero production callers.
3. A `waiting_approval` task **MUST NOT** be claimable by any dispatch run, with or without
   `--resume` — `_eligible_for_claim` recognizes only `pending` and a `stale_claim`-tagged
   `failed`. It re-enters `pending` only through a resolved approval (below), never automatically,
   and never via `retry_task`/`unblock_pod` (those are budget-gate-only escape hatches).
4. Resolving the gate's approval (`core/dispatch.py`'s `resolve_waiting_approval`, called by
   `docket approve`/`docket deny`, `serve.py`'s `POST /approvals/<token>`, and
   `approval_sweep_expired`'s fail-closed timeout path — see `security-gates.spec.md`) **MUST**:
   - **On a grant:** transition the task `waiting_approval` -> `pending`, clear `approvalToken`/
     `pendingApprovalIndex`, and hand the exact pipeline position the gate fired at to the *next*
     claim as a **single-use** `gateOverridePipelineIndex` — "the next dispatch continues from
     that hop." No agent turn runs as part of resolving the grant itself; a real dispatch
     invocation is still required to actually continue the pipeline.
   - **On a deny:** transition the task `waiting_approval` -> `failed` **immediately** (no agent
     turn needed to fail a task that never ran its gated hop), `failureKind: "approval_denied"`,
     `reason: "approval denied"`, `completedAt` set, `claimId` cleared. Terminal — never
     auto-retried by a later `dispatch_pod` call, with or without `--resume`.
   - Resolving a token not created by this gate (missing `context.taskId`/`project`), an unknown
     token, or a task no longer `waiting_approval` on that exact token (already resolved by a
     concurrent caller) **MUST** be a harmless no-op — it **MUST NOT** raise.
5. The gate-override handoff **MUST** be single-use and consumed atomically at claim time: the
   *next* `_claim_next_task` call for this task captures `gateOverridePipelineIndex` into the
   claimed copy handed to `dispatch_task`, then clears it from the **stored** record in the same
   locked operation — so it can never leak into a later, unrelated claim of the same task (e.g. a
   crash-and-`--resume`, or the task revisiting the same pipeline position on a Reviewer rework
   cycle). `dispatch_task` consumes the override **in memory** the first time it reaches that
   exact pipeline position in the run; a later hop at the same role within the *same* run (a
   rework cycle sending the task back to the Implementer a second time) **MUST** gate again
   normally, with a fresh token — the override never suppresses more than the one resumed hop it
   was minted for.
6. The require_approval gate **MUST NOT** bypass, or be bypassed by, the budget gate — budget is
   always checked first (affordability before permission); a hop blocked on budget **MUST**
   transition to `blocked`, not `waiting_approval`, and no approval record is created for it.

### Implementer verification gate (`verifyCmd`)

1. After a **successful** Implementer hop, if the Implementer's `verifyCmd` is set, dispatch
   **MUST** run it via `run_verify_cmd` and treat a nonzero exit as a gate failure.
2. The command **MUST** run in the Implementer's **worktree** directory if one is allocated
   (`worktreeDir`, set at pod provisioning for a worktree-isolated pod); otherwise the pod's
   shared `codebase` root; otherwise the Implementer's own docket workspace directory
   (`core/pod.py`'s `resolve_member_cwd` — the single helper shared with the TOOLS.md generator
   so the two can never disagree about which tree an Implementer's work is checked against).
3. The verify command **MUST** use its own timeout (`verifyTimeoutS`, see "Timeout
   configuration"), independent of the agent-turn timeout — a hung test suite and a hung LLM
   turn are never forced to share one budget.
4. A verification failure **MUST** transition the task to `failed` (reason includes the
   command), emit a `verification_failed` trace event with the (redacted) command output, and
   **MUST NOT** advance to Reviewer/Tester.
5. If `verifyCmd` is unset or empty, dispatch **MUST NOT** silently skip without a visible
   trace — today this is a printed `[dispatch] verification skipped` message (honesty rule: an
   operator can tell a gate was configured or not, never guess).
6. This gate only applies to the Implementer hop; Reviewer and Tester hops are never subject to
   it.

### Reviewer verdict gate and bounded rework

1. After a **successful** Reviewer hop, dispatch **MUST** parse the Reviewer's reply for a
   verdict marker: the first non-blank line of the output, matched case-insensitively against
   `^(APPROVE|REQUEST-CHANGES)\b` — the same structural convention (and same parsing helper
   shape) as the Tester's PASS/FAIL gate.
2. An `APPROVE` verdict **MUST** allow the pipeline to advance past the Reviewer normally.
3. A `REQUEST-CHANGES` verdict **MUST NOT** immediately fail the task. Instead, while the pod's
   rework budget (`maxReworkCycles`, a Lead-meta field, default `1`; `0` disables rework
   entirely, making the Reviewer a hard gate) is not yet exhausted, dispatch **MUST**: emit a
   `rework_started` trace event; jump the pipeline position back to the Implementer; re-run the
   Implementer's hop with the Reviewer's REQUEST-CHANGES text rendered as its own prominent
   "REWORK REQUIRED" prompt section (sized off the full, un-derated per-hop carryover budget and
   excluded from the generic recency-ranked carryover loop, so the one thing this hop must not
   lose to truncation never is, and it is never rendered twice); then re-run the Reviewer.
4. A **second** `REQUEST-CHANGES` for the same task once the rework budget is exhausted (or,
   defensively, if the pod has no Implementer to rework against) **MUST** become terminal: the
   task transitions to `failed`, a `review_rejected` trace event is emitted naming the number of
   rework cycles consumed, and the reason states the rejection occurred "after N rework
   cycle(s)".
5. Reviewer output whose first non-blank line does not match the marker at all (including empty
   output) **MUST** be treated as unparseable — distinct from an explicit `REQUEST-CHANGES`
   rejection, mirroring the Tester gate's FAIL-vs-unparseable distinction. This **MUST** emit a
   `reviewer_verdict_unparseable` trace event and fail the task immediately (unparseable output
   is never given a rework cycle).
6. Every rework cycle's hops (the re-run Implementer, the re-run Reviewer) **MUST** persist into
   the task's `hops[]` through the same incremental per-hop persistence as any other hop, so the
   full rework history is visible afterward, and correctly replayable on resume (see
   "Per-hop incremental persistence and crash recovery").
7. This gate **MUST NOT** affect pods with no Reviewer member — the check only runs when a
   Reviewer hop is actually part of the pipeline for that pod.

### Tester PASS/FAIL gate

1. After a **successful** Tester hop (`agent_run` returned `ok`), dispatch **MUST** parse the
   Tester's reply for a verdict marker: the first non-blank line of the output is matched,
   case-insensitively, against `^(PASS|FAIL)\b`.
2. A `PASS` verdict **MUST** allow the pipeline to advance normally.
3. A `FAIL` verdict, or output whose first non-blank line does not match the marker at all
   (unparseable — including empty output), **MUST** block pipeline advancement: the task
   transitions to `failed` with a distinct reason (`"tester reported FAIL"` vs `"tester output
   unparseable (expected a PASS/FAIL first line)"`), and a `tester_verdict_failed` trace event
   **MUST** be emitted carrying the parsed verdict (`"fail"` or `"unparseable"`) and the redacted
   output. FAIL and unparseable **MUST** remain distinguishable in the reason and are never
   conflated.
4. This gate **MUST NOT** affect pods with no Tester member. Unlike the Reviewer gate, there is
   no rework loop on a Tester FAIL — it is a hard terminal gate.
5. This gate is structural, not textual advice: a successful subprocess call alone (`ok=True`) is
   insufficient for the pipeline to advance past a Tester hop — the reply content itself is
   inspected.

### Hop-failure semantics (general)

1. If a hop's underlying `agent_run` call is not `ok` and its failure was not retried away (see
   "Retries"), the task **MUST** immediately transition to `failed` with a reason naming the role
   and the underlying error, and **MUST NOT** attempt any later hop.
2. A `failed` task **MUST** persist its full per-hop record (`role`, `member`, `ok`, `costUsd`,
   `error`, `attempts`) so a caller can see exactly which hop stopped the pipeline, how many
   attempts it took, and why.

### Bounded hop prompts

1. The message composed for a hop **MUST** cap how much of each *prior* hop's raw output it
   carries forward: a per-hop byte budget (`config.HOP_CARRYOVER_BYTES`, default 32 KiB) that
   halves for each step further into the past (`total_budget >> (rank + 1)`, rank 0 = the most
   recent prior hop) — a partial geometric series that never sums past the configured total no
   matter how many prior hops exist, while the most recent (most relevant) hop is squeezed the
   least.
2. The task's own description **MUST NEVER** be truncated — only prior hops' output is subject
   to the cap.
3. When a prior hop's output does not fit its budget, it **MUST** be truncated head + tail (kept
   in roughly equal shares of the remaining room) with an explicit `[... truncated N bytes ...]`
   marker recording exactly how many bytes were omitted — never a silent cut.
4. A rework cycle's REQUEST-CHANGES note (see "Reviewer verdict gate") is exempt from the
   generic recency-ranked loop and its budgeting — it gets the full per-hop budget on its own,
   since it is what the rework Implementer hop exists to address.
5. Every hop **MUST** emit a `context_composed` trace event recording, per section (the rework
   note if present, and each prior hop carried forward): the role, original byte count, sent byte
   count, and whether it was truncated — plus the task description's byte count and the
   composed message's total size. This is a measured baseline for Phase 17's context compiler,
   not a compiler itself; it does not change what gets sent, only records it.

### Task status vocabulary

1. `pending` — queued, not yet claimed by any dispatch run (or a `blocked`/`stale_claim`-failed
   task explicitly moved back here — see "blocked and terminal-failure re-entry"). Not terminal.
2. `running` — claimed by a dispatch run; at least the claim has been persisted, and zero or
   more hops may have completed and been persisted. Not terminal — either a live dispatcher is
   working it, or (if `claimedAt` has gone stale) the next `dispatch_pod` call's sweep will move
   it to `failed`/`stale_claim`.
3. `done` — every present hop ran and passed all applicable gates (including any rework cycles).
   Terminal.
4. `failed` — a hop's subprocess call failed (after exhausting any retries), a `verifyCmd`
   failed, a Tester verdict was FAIL/unparseable, a Reviewer's rework budget was exhausted or its
   verdict was unparseable, a stale claim was swept, or a require_approval gate's approval was
   denied (`failureKind: "approval_denied"`, see below). Terminal for this dispatch attempt,
   **except** a `failureKind: "stale_claim"` failure, which is reclaimable via `--resume` (see
   "Crash recovery") — a `failureKind: "approval_denied"` failure is **never** reclaimable, with
   or without `--resume`.
5. `blocked` — the pod's budget cap was reached before a hop could run. Not terminal — re-enters
   `pending` only via `docket pod <project> queue --retry <task-id>` or a pod-wide budget change
   on the Lead (never automatically, never via a plain dispatch run).
6. `waiting_approval` (ROADMAP Phase 15 G-1) — a require_approval gate fired before a hop could
   run; a real approval record was created and the task is waiting on a human (or automated
   headless) decision. Not terminal — re-enters `pending` only via a granted approval
   (`resolve_waiting_approval`, handing the exact pipeline position back as a single-use
   override), never automatically, never via a plain dispatch run, `retry_task`, or `unblock_pod`.
   A denied (or fail-closed-expired) approval instead moves the task straight to `failed` (see
   above) — it does not pass through `pending` at all.

## Interface Contracts

This spec defines behavior only; the CLI surface that triggers it (`docket pod <project>
dispatch [--resume] [--timeout <seconds>]`, `docket pod <project> queue --retry <task-id>`,
`docket serve --dispatch`) is documented in `cli-interface.spec.md`. The persisted run-registry
record each invocation of this pipeline creates (`docket runs`, `GET /runs`) is documented in
`serve-read-api.spec.md`/`cli-json-shapes.spec.md`.

### Trace events this pipeline emits

```text
session_start              # once, at the start of dispatch_task; carries whether this is a resume
context_composed           # before each hop's turn — composed-prompt byte accounting
tool_call                  # before each hop's agent_run attempt
hop_retry                  # before each retry attempt of a retryable failure
tool_result                 # after a successful hop
error                       # after a failed hop (in place of tool_result)
cost_charged                # after any hop with nonzero cost
budget_exceeded             # the budget gate blocked a hop (task -> blocked)
verification_failed         # the Implementer's verifyCmd exited nonzero
tester_verdict_failed       # the Tester's reply was FAIL or unparseable
rework_started               # a Reviewer REQUEST-CHANGES triggered a bounded rework cycle
review_rejected              # a second REQUEST-CHANGES exhausted the rework budget (task -> failed)
reviewer_verdict_unparseable # the Reviewer's reply had no APPROVE/REQUEST-CHANGES first line
stale_claim                  # the crash sweep failed a running task whose claim went stale
paused_refused                # a claim attempt was refused because the pod's Lead is paused
approval_required              # a require_approval gate fired (task -> waiting_approval)
approval_resumed                # a granted approval flipped the task back to pending (G-1)
approval_task_denied             # a denied approval failed the task terminally (G-1)
session_end                  # once, at the end of dispatch_task, carrying the final status
```

## Examples

### A lean pod (Lead + Implementer, no `verifyCmd`) completing normally

```text
$ docket pod myapp dispatch
[dispatch] verification skipped — verifyCmd not set for myapp-implementer
  [task-3f2a1c9e-...] done — 2 hop(s), $0.0142
```

### A full pod blocked by a Tester FAIL

```text
$ docket pod myapp dispatch
  [task-91a2c410-...] failed — tester reported FAIL
```

### A Reviewer REQUEST-CHANGES driving one rework cycle, then approving

```text
$ docket pod myapp dispatch
Dispatching 1 pending task(s) through: lead → implementer → reviewer → tester
  [task-7c1e2b90-...] done — 6 hop(s), $0.0891
```

(`hops[]` for this task shows: lead, implementer, reviewer [REQUEST-CHANGES], implementer
[rework], reviewer [APPROVE], tester [PASS] — six hops, because the one rework cycle re-ran the
Implementer and Reviewer once each.)

### A pod blocked on budget, auto-paused, then resumed

```text
$ docket pod myapp dispatch
  [task-c410e91a-...] blocked — pod budget reached ($5.12 ≥ $5.00) before implementer

$ docket profile myapp-lead --resume
  Unblocked 1 budget-blocked task(s) in pod 'myapp'.
✓ Resumed 'myapp-lead' — auto-pause cleared.
```

### A crashed dispatch resumed

```text
$ docket pod myapp dispatch --resume
Dispatching 0 pending task(s), 1 resumable task(s) through: lead → implementer → reviewer
  [task-a1b2c3d4-...] done — 3 hop(s), $0.0456
```

(The Implementer hop that had already completed before the crash is not re-invoked; the resumed
run continues from the Reviewer.)

### A require_approval gate (pod-level), granted, then continued (G-1)

```text
$ docket pod myapp dispatch
  [task-9a1b2c3d-...] waiting_approval — approval required before implementer hop (token=apr-...)

$ docket approve apr-1234
✓ Approval granted: apr-1234
  The waiting action may now proceed.

$ docket pod myapp dispatch
  [task-9a1b2c3d-...] done — 2 hop(s), $0.0091
```

(The Lead hop already completed before the gate fired is not re-invoked; `docket approve` moves
the task back to `pending`, and the *next* `docket pod myapp dispatch` continues from the
Implementer — the exact hop the gate stopped it on.)

### The same gate, denied instead

```text
$ docket pod myapp dispatch
  [task-9a1b2c3d-...] waiting_approval — approval required before implementer hop (token=apr-...)

$ docket deny apr-1234
✓ Approval denied: apr-1234
  The waiting action has been blocked.
```

(The task is now `failed`, `failureKind: "approval_denied"`, immediately — no further dispatch
run is needed to observe this; a later `docket pod myapp dispatch` — with or without `--resume`
— will not touch it again.)

## Validation

### Pre-conditions

- The target project **MUST** have a provisioned pod with at least a Lead.
- The task **MUST** already be queued (`docket pod <project> delegate`) and eligible for claim
  (`pending`, or `failed`/`stale_claim` when `--resume` is passed).

### Post-conditions

- After a claim, the task's `status`, `startedAt`, `claimId`, and `claimedAt` **MUST** be
  persisted to the pod's `TASK_LIST.json` before the first hop runs.
- After each hop, that hop's record (including `attempts`) **MUST** be persisted and
  `claimedAt` refreshed, before the next hop is attempted.
- After a run reaches a terminal state, the task's `status`, `reason`, `hops`, and `costUsd`
  **MUST** be persisted back, and its `claimId` cleared.
- A `blocked` task **MUST** stay `blocked` in storage — it is never rewritten to `pending` by
  `dispatch_pod` itself.
- A gate firing **MUST** persist the task's `approvalToken` and `pendingApprovalIndex` before
  `dispatch_pod` returns, and **MUST** create the approval record before the task is persisted as
  `waiting_approval` (never the reverse — a persisted `waiting_approval` task **MUST NOT** exist
  without a corresponding approval record for its `approvalToken`).

### Invariants

- Dispatch **MUST NOT** cross pods: every hop's member id belongs to the dispatched project's own
  pod.
- Two concurrent `dispatch_pod` calls against the same pod **MUST NOT** both claim (flip to
  `running`) the same task.
- A gate (budget, require_approval, `verifyCmd`, Reviewer verdict, Tester verdict) **MUST NOT** be
  bypassed by an otherwise-`ok` subprocess call — `ok=True` is necessary but not sufficient for
  pipeline advancement past the Implementer, Reviewer, or Tester hops.
- A hop's failure **MUST NOT** be retried unless its `failure_kind` is `timeout` or
  `daemon_error`.
- A paused pod's queue **MUST NOT** yield any claim until the pause is explicitly cleared.
- A `waiting_approval` task **MUST NOT** be claimable by any `dispatch_pod` call, with or without
  `--resume`, until its approval resolves (grant or deny).
- The gate-override handoff (`gateOverridePipelineIndex`) **MUST** be consumed at most once per
  grant: captured and cleared from storage atomically at claim time, and consumed in memory the
  first time the resumed run reaches that pipeline position — a later occurrence of the same
  position within the same run (a Reviewer rework cycle) **MUST** gate again, not skip silently.
- Every hop, gate pass, gate failure, retry, claim, and sweep **MUST** be traceable via `docket
  trace tail <project>` — nothing in the pipeline is silent (including the printed
  verification-skipped notice).

## Changelog

### Version 2.1.0 (2026-07-30)

- **ROADMAP Phase 15 G-1 — approval-gated dispatch.** `core/approval.py`'s pending-approval
  store previously had zero production callers (`approval_create` was called only by tests); this
  card gives it its first one. Added:
  - A sixth task status, `waiting_approval`, and the require_approval gate that produces it
    (`_hop_requires_approval`, evaluated pre-hop, after the budget gate and before the hop's
    message is composed or its agent turn runs).
  - One wired gate source for this version: the pod Lead's `requireApprovalRoles` meta field
    (`_pod_requires_approval`). Two more sources are documented, explicit, inert seams —
    `_policy_requires_approval` (ROADMAP Phase 15 G-2) and `_pipeline_step_requires_approval`
    (ROADMAP Phase 16 W-1/W-2) — both always return `False` today; neither is claimed as wired.
  - `resolve_waiting_approval`: reacts to a grant/deny already applied by `core/approval.py` (via
    `docket approve`/`docket deny`, `serve.py`'s `POST /approvals/<token>`, or the expiry sweep)
    by moving the gated task `waiting_approval` -> `pending` (grant, with a single-use
    `gateOverridePipelineIndex` handoff to the next claim) or `waiting_approval` -> `failed`
    (deny, immediately, `failureKind: "approval_denied"`, never reclaimed).
  - Three new trace events: `approval_required`, `approval_resumed`, `approval_task_denied`.
  - `core/approval.py`'s `approval_sweep_expired` now resolves a stale pending record to
    **denied** (fail-closed), not the prior, read-by-nobody `"expired"` state, and reaches into
    dispatch (a guarded, best-effort local import) to fail any task waiting on that exact token —
    see `security-gates.spec.md` v0.5.0 for the approval-store side of this change.
  - `docket pod <project> dispatch`'s human-readable output now renders `waiting_approval` with
    the same warn-not-error treatment as `blocked` (an expected pause, not a failure).
  - Not shipped: a policy-driven gate source and a pipeline-defined `approval` step (see the
    seams above); task cancellation of an in-flight hop remains out of scope per Phase 16 W-2
    (unchanged from 2.0.0).

### Version 2.0.0 (2026-07-30)

- **ROADMAP Phase 14, R-1…R-7 — the dispatch-hardening program.** This is a rewrite, not an
  incremental update; nearly every requirement above is new or materially changed from 1.0.0:
  - **R-1**: persisted `running` state; locked claiming (`edges/store.py`'s new
    `with_lock`/`read_modify_write`) closing the concurrent-dispatch race; per-hop incremental
    persistence; the stale-claim crash sweep and `--resume`-driven continuation from the last
    hop; `blocked` no longer silently rewritten to `pending` (moves only via `retry_task`/
    `unblock_pod`); `task-<uuid4>` ids.
  - **R-2**: the `AgentRunResult.failure_kind` taxonomy and retryable-kind policy; per-role retry
    budget + linear backoff; `attempts` persisted per hop; the `hop_retry` trace event; claim
    refresh on every retry/completed hop; independent `turnTimeoutS`/`verifyTimeoutS` with a
    `--timeout` CLI override and a serve-wide config knob.
  - **R-3**: out of this spec's direct scope (it built the *run registry* around invocations of
    this pipeline, not the pipeline itself — see `serve-read-api.spec.md`) but referenced above
    since a caller now observes a dispatch run through both this spec's task record and that
    registry.
  - **R-4**: the Reviewer verdict gate and its bounded rework loop (`maxReworkCycles`), the
    pipeline-position replay needed to resume correctly mid-rework, and the three new Reviewer
    trace events.
  - **R-5**: real budget auto-pause (`_pause_lead_for_budget`) and claim-time refusal for a
    paused pod (`paused_refused`), plus the labelled estimate fallback for budget gating when the
    daemon has recorded no cost.
  - **R-6**: `verifyCmd` now runs in the Implementer's actual worktree (falling back to
    `codebase`, then the workspace dir) via the shared `resolve_member_cwd` helper, instead of
    always the shared codebase root.
  - **R-7**: the bounded, recency-weighted hop-carryover cap and the `context_composed` trace
    event.
  - Rewrote "Task status vocabulary" to add `pending`/`running` and the crash/resume-relevant
    distinction within `failed`; rewrote the trace-event list (9 new event types); replaced every
    example with one reflecting the current CLI output and state machine.

### Version 1.0.0 (2026-07-02)

- FD-6: initial specification. No prior spec owned the dispatch pipeline's state machine
  directly (confirmed absent per Phase 12's CH-10 audit); this document closed that gap for the
  behavior Phase 13 made real: FD-0's environment injection for Implementer hops, and FD-2's
  structural Tester PASS/FAIL gate (`tester_verdict_failed`). The pre-existing budget gate,
  general hop-failure semantics, and CD-2's `verifyCmd` gate (previously undocumented as a state
  machine, only as data fields in `docket-meta.spec.md`) were documented here for the first time
  as the current, shipped behavior.
