# Pod Dispatch Pipeline Specification

**Version**: 5.0.0
**Status**: Complete. Task cancellation and parallel hop execution (ROADMAP Phase 16 W-2) and
generalized gate execution (Phase 16 W-8) are now implemented — see "Generalized gate execution",
"Parallel step groups", and "Cancellation" below. The require_approval gate
(Requirements → "require_approval gate and waiting_approval") now ships with **two** wired
sources (pod-level and pipeline-defined); the policy-driven source (Phase 15 G-2) remains an
explicit, inert seam — see that section's "Sources" list. Hops run through the RuntimeDriver port
(Phase 18 L-1) — a containment refactor with no behavior change. The role-archetype registry's
`gateContract` (Phase 16 W-6) is now load-bearing: it is the fallback a step's gate resolves to
when the step declares none of its own. **Structured handoff artifacts (ROADMAP Phase 16 W-5)**
are implemented — see "Structured handoff artifacts" below: a hop's output is a typed
`HandoffArtifact` (`core/handoff.py`), not a raw string; the next hop's prompt is composed from
its rendered form, and it is persisted alongside the hop record so `--resume` recovers it exactly.
The `core/dispatch.py:1313` `print()` (a layering violation — `core/` never prints) is also gone:
a mechanical gate's unset-command skip is now a typed `HopResult.verification_skipped` flag
rendered by `cli/_pod.py`, plus a `tool_result` trace event carrying the same fact — see
"Implementer verification gate" and "Generalized gate execution" below. **ROADMAP Phase 17's C-1
(the context compiler) is now implemented** — see "Bounded hop prompts" below, rewritten: R-7's
process-wide byte cap and its blind head+tail truncation are retired (`_hop_carryover_budget`/
`_truncate_carryover` are no longer called by `_hop_message`, though — per this card's declared
file-ownership carve-out, which permitted editing only that one function — they remain defined,
unused, in `core/dispatch.py` for a future cleanup to remove); every prior hop's rendered artifact
is now fit to a **per-role token budget** (`core/archetypes.py`'s `RoleArchetype.token_budget`, see
`role-archetypes.spec.md` v1.3.0) via `core/context.py`'s `compile_artifact`, which sheds
`HandoffArtifact.DROP_ORDER` fields before ever truncating `summary` itself.
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
that missing producer. **ROADMAP Phase 16 W-2 (executor) / W-8 (generalized gates)** — shipped
together per ROADMAP's explicit sequencing rule ("W-6/7/8 land with the executor, not after") —
is this version's own major change: `core/orchestrator.py` resolves a
`~docket.core.pipeline.PipelineSpec` (W-1) against a pod's live roster into a deterministic
`ExecutionPlan` and runs it over this exact state machine (claiming, budget/approval gates,
retries, crash resume all unchanged); gate execution reads each step's *resolved* gate — its own
declared `gate`, or (only when a step omits one) its archetype's `gateContract` (W-6) — instead of
branching on a hardcoded role name; a `parallel` step's children run concurrently via a bounded
worker pool and join before the pipeline advances; and `docket runs cancel <id>` kills an
in-flight hop's process group. This version documents that machine as it actually ships.

## Scope

This specification covers:

- The task record's full lifecycle: creation, locked claiming, persisted `running` state,
  per-hop incremental persistence, terminal states, and how a task moves between them
- Crash recovery: the stale-claim sweep and `--resume`-driven continuation from the last
  persisted hop (including mid-rework, and — best-effort — mid-parallel-group)
- Concurrency: why two dispatchers can never double-run one task
- Pipeline step order and which roles/agents participate for a given pod and spec, including a
  verdict gate's bounded rework loop (a step may run more than once within one dispatch attempt)
  and a `parallel` group's concurrent children
- Per-hop execution: message construction (with a bounded-size carryover cap), environment
  injection, the real agent turn, and retries of a transient failure
- Timeout configuration: independent agent-turn vs. `verifyCmd` timeouts and their resolution
  order, including a step's own `retries`/`timeout` override
- The gates that can block pipeline advancement mid-run: budget (with auto-pause), the
  require_approval gate (waits on a human decision, resumable — now with two wired sources),
  a `mechanical` gate (`verifyCmd`-equivalent, worktree-aware cwd resolution for any role), and a
  `verdict` gate (generalizing the pre-W-8 hardcoded Reviewer APPROVE/REQUEST-CHANGES and Tester
  PASS/FAIL gates to any archetype's marker vocabulary)
- **Generalized gate execution** (W-8): how a step's gate is resolved (its own, or its
  archetype's fallback), how a `VerdictGate`/`MechanicalGate`/`ApprovalGate` is evaluated
  generically, and the byte-identical-behavior guarantee for the four built-in roles
- **Parallel step groups** (W-2): bounded concurrent execution of a group's children, join
  semantics, and per-hop persistence ordering
- **Cancellation** (W-2): how an in-flight hop's process group is tracked and killed by
  `docket runs cancel <id>`
- The require_approval gate's two wired sources for this version (a pod-level Lead-meta role
  list, and a pipeline step whose resolved gate is `approval`), how a fired gate is resolved
  (grant resumes at the exact hop, deny fails the task immediately, an expiry fail-closes to
  denied), and why a `waiting_approval` task is never claimable by a plain dispatch run
- **Structured handoff artifacts** (W-5): the `HandoffArtifact` model's fields and field-priority
  drop order, how a hop's artifact is built and rendered into the next hop's prompt, and its
  persistence/backward-compatibility contract for `--resume`
- The complete task-status and failure-kind vocabulary, and every trace event this pipeline emits

This specification does NOT cover:

- The `.docket-meta.json` fields that configure a pod member (`portRangeStart`,
  `portRangeCount`, `scratchDir`, `verifyCmd`, `turnTimeoutS`, `verifyTimeoutS`,
  `maxReworkCycles`, `requireApprovalRoles`, `paused`/`pausedReason`) — see `docket-meta.spec.md`
- A policy-driven require_approval match (ROADMAP Phase 15 G-2) — an explicit, documented seam
  in `core/dispatch.py` (`_policy_requires_approval`) that always returns `False` today; not wired
  to any real source yet, and this spec does not invent one. (The pipeline-defined `approval` step
  source, ROADMAP Phase 16 W-1/W-2, **is** wired now — see "Generalized gate execution" below.)
- `core/approval.py`'s own approval-record lifecycle (`pending`/`granted`/`denied`, the CLI/HTTP
  channels, audit-log parity) — see `security-gates.spec.md`. This spec covers only how
  *dispatch* creates and reacts to a record, not the record's own store contract
- The CLI surface for queuing/inspecting/dispatching tasks (`docket pod <project>
  delegate/queue/add/set-verify/dispatch`, `docket pipeline validate/plan/run`, `docket runs
  cancel`, including their flags) — see `cli-interface.spec.md`
- Budget-cap accounting in general, and the `docket profile <id> --budget`/`--resume` CLI
  contract — see `cost-tracking.spec.md`. This spec covers only the pre-hop budget check and the
  auto-pause/claim-refusal mechanics it drives
- The persisted dispatch-run registry (`core/runs.py`, `docket runs`, `GET /runs`) that records
  *invocations* of this pipeline (one record per `dispatch_pod` call, whatever triggered it),
  including its `pids`/cancellation-outcome fields — see `serve-read-api.spec.md` and
  `cli-json-shapes.spec.md`. This spec is scoped to what happens *inside* one such invocation and
  to how a hop's pid is reported into that registry (`core.runs.add_hop_pid`/`current_run_id`),
  not the registry's own record shape
- `edges/store.py`'s `with_lock`/`read_modify_write` locking primitive itself (this spec only
  relies on its atomicity guarantee) — see the module's own docstring
- The retired org-wide `docket team` queue (removed-command notice only; durable record in
  ROADMAP decision D-11 — its spec was removed 2026-07-30)
- The declarative role-archetype registry's schema itself (`gateContract`'s closed kinds, the
  built-in/starter-library archetypes, the user overlay) — see `role-archetypes.spec.md`. This
  spec covers only how the executor *consumes* an archetype's `gateContract` as a gate fallback,
  not the registry's own authoring/validation contract
- Pod provisioning / blueprints (which roles a pod actually has, `--count N` duplicate members,
  workspace kind) — see `workspace-structure.spec.md` and ROADMAP Phase 16 card W-7 (not shipped)
- `core/context.py`'s own internals (the chars-per-token approximation, `compile_artifact`'s
  field-shedding/summary-truncation mechanics, `RoleArchetype.token_budget`'s schema) — see
  `role-archetypes.spec.md` for the archetype-side schema and `core/context.py`'s own module
  docstring for the compiler itself. This spec covers only how `_hop_message` *consumes* that
  compiler to build one hop's message — see "Bounded hop prompts" below
- A real `files_changed`/`diff_ref` producer (a git-diff probe) — `HandoffArtifact` declares both
  fields but dispatch does not populate them as of this version; see `core/handoff.py`'s own
  module docstring for why (the git shell-out surface belongs to a different in-flight card) and
  "Structured handoff artifacts" below

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

1. A dispatch run **MUST** drive steps in the order declared by its `PipelineSpec` (W-1) —
   `dispatch_task`'s `spec` parameter; `None` (every pre-W-2 caller, and `docket pod <project>
   dispatch` today) resolves `effective_pipeline(project, None)`, which is `core/pipeline.py`'s
   `default_pipeline()` — Lead → Implementer → Reviewer → Tester, byte-identical to the pre-W-2
   hardcoded `PIPELINE_ORDER` walk — patched only so its Reviewer step's rework budget reflects
   this pod's own `maxReworkCycles` (see "Reviewer verdict gate and bounded rework"). A
   role-targeted step whose role the pod does not have is skipped and consumes no pipeline
   position (`core.orchestrator.resolve_plan`'s `skipped` flag), the same behavior
   `PIPELINE_ORDER`-filtering always had. A lean pod (Lead + Implementer only) running the default
   pipeline still runs exactly two hops per pass; a full pod runs up to four, plus any rework
   cycles (see below).
2. A pod **MUST** have a Lead to be dispatchable at all; dispatching a project with no pod, or a
   pod with no Lead, **MUST** raise a `DispatchError` rather than attempt any hop.
3. Dispatch **MUST NOT** send a task to any agent outside the target project's own pod — each
   hop's member id is asserted against the pod before its turn runs, raising `DispatchError` on a
   mismatch. This applies identically to a `parallel` group's children (see "Parallel step
   groups").
4. A step **MAY** legitimately run more than once within one dispatch attempt: a verdict-gated
   step's rework-triggering marker re-runs its gate's declared `rework.to` target and then the
   gating step again (bounded — see "Reviewer verdict gate and bounded rework" and "Generalized
   gate execution"). The pipeline position is tracked as an index that can move backward for a
   rework cycle, not a per-role "has this run yet" set; rework-cycle counts are tracked per
   *gated step id*, not one pod-wide counter, since a custom pipeline may declare more than one
   independent rework-capable gate (the built-in pipeline only ever has one — the Reviewer's).
5. A custom `PipelineSpec` **MAY** target a role `docket pod`'s legacy four-role
   `PIPELINE_ORDER` doesn't know about (e.g. a starter-library `researcher`/`critic`) —
   `pod_full_roster` resolves *every* role the pod's members actually carry (first member per
   role), not just the four legacy ones `pod_pipeline` considers.

### Per-hop execution

1. Each hop **MUST** be one real, costed agent turn via the `RuntimeDriver` port's `run_turn`
   (`core/runtime_driver.py`; **Phase 18 L-1 / D-14** — `dispatch_task`'s default runner is
   `edges.adapters.openclaw.default_driver().run_turn`, a one-line swap from the pre-L-1
   `_oc.agent_run` at the same call site) — dispatch never simulates or skips a turn to save
   cost. `OpenClawDriver.run_turn` is a thin delegation to the pre-existing `agent_run` free
   function, so this is a containment refactor, not a behavior change: the daemon subprocess
   call, its argv, and its JSON-parsing are exactly what they were before L-1.
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

1. Every agent turn's outcome (`core.runtime_driver.TurnResult` — the pre-Phase-18 alias
   `edges/adapters/openclaw.AgentRunResult` that used to re-export this same type is gone as of
   ROADMAP Phase 16 W-5, which finished Phase 18 CL-1's blocked sweep: `core/dispatch.py`'s
   `Runner` type alias and every test call site now spell `TurnResult` directly, so the alias had
   zero references left anywhere in the tree) **MUST** carry a `failure_kind` on failure: `timeout` (the turn exceeded
   its timeout), `daemon_error` (a CLI/daemon-level failure — process couldn't run, OS error,
   malformed daemon response), `nonzero_exit` (the daemon ran and returned a real non-zero
   result), or `invalid_output` (the daemon succeeded but its output couldn't be used). A
   successful turn carries no `failure_kind`.
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

### require_approval gate and waiting_approval (ROADMAP Phase 15 G-1 / Phase 16 W-2)

1. Immediately after the budget gate (affordability) and before a hop's message is composed or
   its agent turn runs (permission), dispatch **MUST** evaluate whether that hop requires a human
   decision (`_hop_requires_approval`). This is an **OR** of independent sources — any one of them
   firing is enough to gate:
   - **Pod-level (wired):** the pod Lead's `requireApprovalRoles` meta field, a comma-separated,
     case-insensitive role list (e.g. `"implementer,reviewer"`) — see `docket-meta.spec.md`. Read
     the same way `maxReworkCycles`/`budgetUsd` are: only the Lead's value is consulted, and it
     has no dedicated CLI setter yet (`meta-set` only).
   - **Policy-driven (seam only — ROADMAP Phase 15 G-2, not wired):** `_policy_requires_approval`
     always returns `False` today. No policy source (e.g. a high-risk action-class match) is
     consulted. This is an explicit, documented gap, not a claim of coverage.
   - **Pipeline-defined (wired — ROADMAP Phase 16 W-2):** `_pipeline_step_requires_approval(gate)`
     returns `True` exactly when the current pipeline position's *resolved* gate (its own declared
     `gate`, or its archetype's `gateContract` fallback — see "Generalized gate execution") is an
     `ApprovalGate`. This applies to any role/archetype, not just a hardcoded one, and composes
     with the pod-level source (either firing is enough). Only meaningful for a top-level step —
     see "Parallel step groups" for why a group's children never check this source at all.
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

*(This is a `mechanical` gate — see "Generalized gate execution" for how W-8 generalizes the
mechanics below to any role's mechanically-gated step, not just one hardcoded to "implementer".
Every requirement below still holds byte-for-byte for the Implementer specifically.)*

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
   record (honesty rule: an operator can tell a gate was configured or not, never guess). As of
   ROADMAP Phase 16 W-5 this is a `tool_result` trace event (`{"verification": "skipped",
   "member": <id>}`) plus the hop's own `HopResult.verification_skipped` flag, which
   `cli/_pod.py`'s dispatch renderer prints as `[dispatch] verification skipped — verifyCmd not
   set for <id>` — the same visible wording a bare `print()` inside `core/dispatch.py` produced
   before this card, now emitted by the `cli/` layer instead (`core/` never prints — see
   CLAUDE.md's layering rule).
6. This gate only applies to the Implementer hop; Reviewer and Tester hops are never subject to
   it.

### Reviewer verdict gate and bounded rework

*(This is a `verdict` gate — see "Generalized gate execution" for how W-8 generalizes the marker
parsing below to any role's verdict-gated step via `core.orchestrator.parse_verdict`, instead of
a Reviewer-specific hardcoded parser. Every requirement below still holds byte-for-byte for the
Reviewer specifically — this is what "byte-identical built-in behavior" means in practice.)*

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

### Generalized gate execution (ROADMAP Phase 16 W-8)

1. Before a hop's agent turn runs, dispatch **MUST** resolve the current pipeline position's gate
   (`core.orchestrator.resolve_gate`): the step's own declared `gate` (W-1) if present, else —
   only when the step omits one — its resolved archetype's `gateContract` (W-6), looked up by the
   step's `archetype` field if set, else its `role`. A step with neither an explicit `gate` nor a
   resolvable archetype **MUST** have no gate at all — the step always advances once its turn
   completes, the same as today's Lead hop.
2. Gate *evaluation* **MUST** be driven by the resolved gate's own type
   (`MechanicalGate`/`VerdictGate`/`ApprovalGate`/none), never by a hardcoded role-name check:
   - A `MechanicalGate` **MUST** run `gate.command` if set, else the target member's own
     `verifyCmd` meta (the same "defer to the member's own check" convention "Implementer
     verification gate" documents) via `core/pod.py`'s `resolve_member_cwd` — worktree-aware cwd
     resolution now applies to **any** mechanically-gated step, not only one hardcoded to
     "implementer". A nonzero exit **MUST** fail the step and emit a `verification_failed` trace
     event; a pass **MUST** emit a `tool_result` event and advance. An unset command (both
     `gate.command` and the member's `verifyCmd`) **MUST** produce the same honesty-rule signal
     "Implementer verification gate" documents (a `tool_result` "skipped" trace event plus the
     hop's own `verification_skipped` flag), generalized to name the actual member id — for any
     mechanically-gated role, not only "implementer".
   - A `VerdictGate` **MUST** parse the hop's reply via `core.orchestrator.parse_verdict` —
     generalizing "Reviewer verdict gate"/"Tester PASS/FAIL gate"'s marker parsing to the gate's
     own `pattern`/`passValues`/`caseSensitive`/`rework` instead of two separate hardcoded
     Reviewer/Tester regexes and parsers (both removed from `core/dispatch.py` once this shipped).
     A matched value in `passValues` **MUST** advance the pipeline; a matched value in a
     configured `rework.when` **MUST** trigger a bounded rework cycle to `rework.to` (any earlier
     top-level step id, not hardcoded to "implementer") while that gate's own rework-cycle count
     (tracked per gated step id) is below `rework.maxCycles`; anything else (no rework configured,
     the value matches neither list, or no match at all) **MUST** fail the step.
   - An `ApprovalGate` **MUST** be evaluated **pre-hop** (see "require_approval gate and
     waiting_approval") — by the time a hop's turn has actually run, an `ApprovalGate` gate simply
     advances (the gate already did its job before the turn, or a granted single-use override
     already let it through).
3. **Byte-identical behavior for the four built-in roles is a hard requirement, not a best
   effort.** For the built-in `default_pipeline()`, every step already declares its own explicit
   gate (Lead: none; Implementer: `MechanicalGate(command=None)`; Reviewer/Tester:
   `VerdictGate(...)`), so the archetype-fallback path in requirement 1 above never fires for any
   of them — their gate behavior, reasons, and trace event *payloads* are unchanged from the
   pre-W-8 hardcoded implementation. Trace event *names* for a verdict outcome are preserved via a
   lookup (`_verdict_event_names`), not a decision branch: `reviewer`/`tester` keep emitting
   exactly the event names they always have
   (`rework_started`/`review_rejected`/`reviewer_verdict_unparseable` for reviewer,
   `tester_verdict_failed` for tester, both slots for tester since it has no rework); any other
   role/archetype emits the new generic names `verdict_rework_started`/`verdict_rejected`/
   `verdict_unparseable` instead.
4. A step **MAY** declare its own `retries`/`timeout`, overriding the pod's role-based retry
   budget / resolved agent-turn timeout for that step only; a `MechanicalGate`'s own `timeout`
   (if set) overrides the resolved `verifyCmd` timeout for that step's mechanical check only.
   Omitting either **MUST** fall back to the pre-W-8 pod-wide resolution ("Timeout configuration",
   "Retries and the failure-kind taxonomy") — the built-in pipeline's steps never set either, so
   this is never a behavior change for it.

### Parallel step groups (ROADMAP Phase 16 W-2)

1. A `parallel` step's children (W-1's shape) **MUST** run concurrently via a bounded thread pool
   (`core.orchestrator.run_group`; hops are subprocess-bound, so this is a real resource bound,
   not a code-tidiness knob) and **MUST** all be observed (joined) before the pipeline advances
   past that position — a group is one pipeline position, not one per child.
2. Every child **MUST** independently go through the same budget gate, hop execution, and gate
   evaluation a top-level step does — each child is a real, costed agent turn. A child's resolved
   gate being an `ApprovalGate` **MUST** fail that child clearly (an explicit configuration error,
   e.g. "an 'approval' gate is not supported inside a parallel group") rather than attempting
   fragile mid-group human-approval semantics — approval gating applies only to top-level steps
   (see "require_approval gate and waiting_approval").
3. The group's outcome **MUST** merge its children's outcomes by priority: `blocked` (any child)
   > `failed` (any child) > `advance` (all children). A rework outcome is impossible inside a
   group — the pipeline format's own validator forbids a `rework` edge on a step nested inside a
   `parallel` group.
4. Each child's hop **MUST** be persisted (`on_hop`) the moment that child's turn completes — not
   deferred until the whole group joins — so a crash in one sibling **MUST NOT** lose a hop that
   already finished in another (R-1's crash-safety guarantee, generalized to a concurrent
   fan-out). The task's in-memory `hops[]`/persisted queue record **MUST** reflect children in
   their **declaration** order regardless of completion order.
5. Trace writes from concurrent children **MUST** be serialized against each other (a shared lock)
   since they append to the same task session's tracefile — `core/trace.py`'s append is not
   itself filelocked (the documented D-12 exemption for an append-only log), which is safe across
   *different* sessions but not within one.
6. **Known, documented limitation:** resuming a task that crashed mid-group re-runs the **entire**
   group from scratch on `--resume`, including any child that had already completed — there is no
   child-by-child resume granularity. (This does not affect the rework-replay path at all, per
   requirement 3.)

### Cancellation (ROADMAP Phase 16 W-2)

1. `docket runs cancel <id>` **MUST** kill every hop subprocess currently recorded as in-flight
   for that run's id, and **MUST** mark the run a new terminal state, `"cancelled"` — see
   `serve-read-api.spec.md`/`cli-json-shapes.spec.md` for the run record's own `pids`/state
   fields; this spec covers only how a hop's pid gets into that list and what killing it does to
   the task it belongs to.
2. Each hop subprocess (`edges.adapters.openclaw.agent_run`) **MUST** run in its own session
   (`start_new_session=True`), so its pid doubles as its process group id. Cancelling **MUST**
   kill the whole group (`edges.adapters.system.kill_process_group`: SIGTERM, a bounded grace
   period, then SIGKILL if still alive), not just the immediate `openclaw` process — it may have
   shelled out further, and an orphaned process group is exactly the failure mode this guards
   against. The same mechanism **MUST** apply when a hop's own turn timeout expires (not only an
   explicit operator cancel).
3. A hop's pid **MUST** be tracked only while its production driver's subprocess is actually
   running (added right before the blocking call, removed right after it returns) — never for an
   injected test runner/fake, which has no real OS process to report. A long multi-hop task
   **MUST NOT** accumulate stale pids from hops that already finished.
4. Killing a hop's process group **MUST NOT** invent a new task-status vocabulary: the killed
   subprocess surfaces as an ordinary hop failure (a nonzero/negative exit code) through the
   existing state machine ("Hop-failure semantics"), transitioning the task to `failed` exactly as
   any other hop failure would.
5. Cancelling an already-terminal run (`succeeded`/`failed`/`cancelled`) **MUST** be a no-op,
   reported as such, never re-signalled or double-finished. A run's own normal completion
   (`core.runs.execute`) **MUST NOT** clobber a `"cancelled"` state a concurrent cancel already
   wrote back to `"succeeded"`/`"failed"`.

### Hop-failure semantics (general)

1. If a hop's underlying `agent_run` call is not `ok` and its failure was not retried away (see
   "Retries"), the task **MUST** immediately transition to `failed` with a reason naming the role
   and the underlying error, and **MUST NOT** attempt any later hop.
2. A `failed` task **MUST** persist its full per-hop record (`role`, `member`, `ok`, `costUsd`,
   `error`, `attempts`) so a caller can see exactly which hop stopped the pipeline, how many
   attempts it took, and why.

### Structured handoff artifacts (ROADMAP Phase 16 W-5)

1. Every hop **MUST** produce a typed `HandoffArtifact` (`core/handoff.py`) — a Pydantic model with
   exactly five fields: `summary` (the hop's full reply text — always populated), `verdict`
   (the parsed gate marker for a `VerdictGate`-gated hop, else `None`), `files_changed` and
   `diff_ref` (structurally real fields; not populated by dispatch as of this version — see
   `core/handoff.py`'s own module docstring for the honest reason and what would need to change to
   populate them), and `notes` (free-form, reserved, no producer yet). `HopResult.artifact` **MUST**
   always be set once a hop is constructed — a hop built without one explicitly backfills via
   `HandoffArtifact.from_legacy_output(output)` (treating the raw text as `summary`, every other
   field at its default) in `__post_init__`.
2. The next hop's prompt **MUST** be composed from the prior hop's *rendered artifact*
   (`HandoffArtifact.render()`), never from its raw `output` string directly. `render()` returns
   exactly `summary` unchanged when every other field is at its default (true for every hop today
   except a verdict-gated one) — so a hop with nothing else to report composes byte-identically to
   the pre-W-5 raw-text behaviour; a populated `verdict` (Reviewer/Tester and any verdict-gated
   archetype) appends a `"Verdict: <value>"` line the raw reply itself does not structurally
   carry.
3. The artifact **MUST** be persisted alongside its hop record (an `artifact` key in the
   persisted `hops[]` entry, dumped via `HandoffArtifact.model_dump()`) so `--resume` recovers it
   exactly, not just the raw `output` string it was already persisting. A hop record persisted
   before this version (or any record whose `artifact` value fails to validate) **MUST** degrade
   via `HandoffArtifact.from_legacy_output` — the backward-compatibility requirement this card
   added; a pre-W-5 queue file **MUST** still resume correctly with no separate migration step.
4. `HandoffArtifact.DROP_ORDER` **MUST** declare a least-valuable-first field-shedding order
   (`notes`, `diff_ref`, `files_changed`, `verdict` — `summary` is deliberately never included, it
   is the artifact's minimum viable content) and a `dropped(field)` helper that returns a copy with
   *field* reset to empty. **ROADMAP Phase 17's C-1 (the context compiler) is this seam's real
   consumer** — see "Bounded hop prompts" below for how `core/context.py`'s `compile_artifact`
   walks `DROP_ORDER` to budget one hop's carryover against its role's token budget.
5. This module **MUST** stay pure — no filesystem I/O, no subprocess, no import of
   `core/dispatch.py` (the same "leaf" shape as `core/pipeline.py`).

### Bounded hop prompts (ROADMAP Phase 17 C-1 — the context compiler)

*(Before this version, ROADMAP Phase 14 R-7 bounded this same message with one process-wide byte
constant and truncated whatever didn't fit blindly — head and tail kept, the middle cut with no
regard for what was actually in it. This section documents the compiler that replaced that
mechanism; R-7's own helpers, `core/dispatch.py`'s `_hop_carryover_budget`/`_truncate_carryover`,
are no longer called by `_hop_message` — the two mechanisms are never layered — though they remain
defined, unused, in that module: this card's file-ownership carve-out permitted editing only
`_hop_message` itself, so their removal is left for a follow-up. See `role-archetypes.spec.md`
v1.3.0 for the archetype-side `tokenBudget` schema this section consumes.)*

1. The message composed for a hop **MUST** cap how much of each *prior* hop's rendered artifact it
   carries forward (not the raw hop output — see "Structured handoff artifacts"): a **per-role
   token budget** (`core/archetypes.py`'s `RoleArchetype.token_budget`, resolved via
   `core/context.py`'s `budget_for_role`) that halves for each step further into the past
   (`core.context.hop_share`: `total_budget >> (rank + 1)`, rank 0 = the most recent prior hop) —
   the same partial-geometric-series allocation R-7 used, now denominated in tokens, that never
   sums past the configured total no matter how many prior hops exist, while the most recent
   (most relevant) hop is squeezed the least.
2. The role's total token budget **MUST** first be reduced by the (approximate) token cost of the
   task's own description and that role's fixed instruction footer (the trailing "You are the
   Implementer/Reviewer/Tester..." text) — what remains funds the carryover budget requirement 1
   describes. The task's own description **MUST NEVER** itself be truncated or shed — only a
   prior hop's rendered artifact is subject to budgeting.
3. When a prior hop's rendered artifact does not fit its share, `core.context.compile_artifact`
   **MUST** shed `HandoffArtifact.DROP_ORDER`'s fields one at a time, least-valuable-first
   (`notes`, then `diff_ref`, then `files_changed`, then `verdict`), re-measuring the rendered
   text against the budget after each drop and stopping the moment it fits. A field that is
   already empty **MUST NOT** be reported as dropped — only a field whose removal actually changed
   the rendered text counts. The token estimate this checks **MUST** be the rendered artifact's
   size (`summary` plus any appended `Verdict:`/other labelled lines), not `summary` alone, so the
   budget bounds the same structured content the next hop actually reasons about.
4. `summary` **MUST NEVER** be shed outright (it is deliberately absent from `DROP_ORDER` — see
   "Structured handoff artifacts"). If the rendered text still does not fit its share once every
   droppable field is gone, `summary` **MUST** be truncated head + tail (kept in roughly equal
   shares of the remaining room) with an explicit `[... summary truncated: N bytes omitted ...]`
   marker recording exactly how many bytes were omitted — never a silent cut, and never an empty
   section. A share too small to fit even the marker itself (a degenerate, near-zero budget)
   **MUST** still emit the marker in full rather than silently produce nothing.
5. A rework cycle's REQUEST-CHANGES note (see "Reviewer verdict gate") is exempt from the
   generic recency-ranked loop and its budgeting — it gets the full carryover budget on its own
   (fit via the same `compile_artifact` rule as any other section), since it is what the rework
   Implementer hop exists to address.
6. Every hop **MUST** emit a `context_composed` trace event recording, per section (the rework
   note if present, and each prior hop carried forward): the role, original byte count, sent byte
   count, whether it was truncated, and which fields (if any) were dropped — plus the task
   description's byte count and the composed message's total size.
7. No tokenizer dependency **MUST** be introduced for any of the above (ROADMAP §4.5's
   no-new-heavyweight-deps rule) — `core/context.py`'s `estimate_tokens` reuses the project's
   existing, already-documented `config.CONTEXT_BYTES_PER_TOKEN` bytes-per-token approximation
   (default 4, the same ratio `cli/_agents.py`'s `maintain check`/`maintain sessions` already use),
   not a second, independently-tunable one. This is an honest approximation, not an exact count
   from any real model tokenizer, and is never used to bill against.

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
`docket pipeline run <project> [--file <path>] [--resume] [--timeout <seconds>]`, `docket serve
--dispatch`) is documented in `cli-interface.spec.md`. The persisted run-registry record each
invocation of this pipeline creates (`docket runs`, `GET /runs`), including its `pids` field and
the `"cancelled"` state `docket runs cancel <id>` produces, is documented in
`serve-read-api.spec.md`/`cli-json-shapes.spec.md`.

### Trace events this pipeline emits

```text
session_start              # once, at the start of dispatch_task; carries whether this is a resume
context_composed           # before each hop's turn — composed-prompt byte accounting
tool_call                  # before each hop's agent_run attempt
hop_retry                  # before each retry attempt of a retryable failure
tool_result                 # after a successful hop; also emitted (payload {"verification":
                             #   "skipped", "member": <id>}) when a mechanical gate's command was
                             #   unset — W-5, parity with the "passed" case, replacing a print()
error                       # after a failed hop (in place of tool_result)
cost_charged                # after any hop with nonzero cost
budget_exceeded             # the budget gate blocked a hop (task -> blocked)
verification_failed         # a mechanical gate's command exited nonzero (any role, not just implementer)
tester_verdict_failed       # the Tester's reply was FAIL or unparseable (legacy name, preserved)
rework_started               # a Reviewer REQUEST-CHANGES triggered a bounded rework cycle (legacy name, preserved)
review_rejected              # a second REQUEST-CHANGES exhausted the rework budget (legacy name, preserved)
reviewer_verdict_unparseable # the Reviewer's reply had no APPROVE/REQUEST-CHANGES first line (legacy name, preserved)
verdict_rework_started       # W-8: a non-built-in verdict gate's rework-triggering marker fired
verdict_rejected              # W-8: a non-built-in verdict gate's reply matched but wasn't pass/rework
verdict_unparseable           # W-8: a non-built-in verdict gate's reply had no recognized marker
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
  pod — including every child of a `parallel` group.
- Two concurrent `dispatch_pod` calls against the same pod **MUST NOT** both claim (flip to
  `running`) the same task.
- A gate (budget, require_approval, `mechanical`, `verdict`) **MUST NOT** be bypassed by an
  otherwise-`ok` subprocess call — `ok=True` is necessary but not sufficient for pipeline
  advancement past a mechanically- or verdict-gated hop, for any role/archetype, not only the
  four built-in ones.
- A hop's failure **MUST NOT** be retried unless its `failure_kind` is `timeout` or
  `daemon_error` — including a hop killed by `docket runs cancel`, which always surfaces as a
  non-retryable `nonzero_exit`/negative-signal exit, never masked as transient.
- A paused pod's queue **MUST NOT** yield any claim until the pause is explicitly cleared.
- A `waiting_approval` task **MUST NOT** be claimable by any `dispatch_pod` call, with or without
  `--resume`, until its approval resolves (grant or deny).
- The gate-override handoff (`gateOverridePipelineIndex`) **MUST** be consumed at most once per
  grant: captured and cleared from storage atomically at claim time, and consumed in memory the
  first time the resumed run reaches that pipeline position — a later occurrence of the same
  position within the same run (a rework cycle) **MUST** gate again, not skip silently.
- `core.orchestrator.resolve_plan` **MUST** be deterministic: the same `PipelineSpec` + the same
  roster + the same archetype registry **MUST** always resolve to a byte-identical
  `ExecutionPlan`, independent of wall-clock time, dict-construction order, or which thread calls
  it — the property `docket pipeline plan` and the real executor both rely on to never drift from
  each other.
- Every hop, gate pass, gate failure, retry, claim, and sweep **MUST** be traceable via `docket
  trace tail <project>` — nothing in the pipeline is silent (including the printed
  verification-skipped notice), for any role/archetype, not only the built-in four.
- Cancelling a run (`docket runs cancel`) **MUST** kill a hop's entire process group, never leave
  an orphaned child process running after the run is marked `"cancelled"`.

## Changelog

### Version 5.0.0 (2026-07-30)

- **ROADMAP Phase 17, card C-1 (context compiler) — supersedes ROADMAP Phase 14 R-7's stopgap.**
  See the rewritten "Bounded hop prompts" above for the full requirements; summary of what
  changed:
  - New module `core/context.py` (pure, no filesystem I/O beyond the archetype registry read, no
    subprocess, no import of `core/dispatch.py` — the same "leaf" shape as `core/handoff.py`):
    `estimate_tokens` (the bytes/`config.CONTEXT_BYTES_PER_TOKEN` approximation), `budget_for_role`
    (resolves a role against the live archetype registry), `hop_share` (R-7's recency-halving
    series, now in tokens), and `compile_artifact` (the field-shedding + marked-summary-truncation
    compiler). See `tests/python/test_c1_context_compiler.py` for its own unit coverage.
  - `core/archetypes.py`'s `RoleArchetype` gains `token_budget` (positive integer, default 6000;
    `tokenBudget` on the wire) — every built-in and starter-library archetype now declares one.
    See `role-archetypes.spec.md` v1.3.0.
  - `core/dispatch.py`'s `_hop_message` is rewritten to compose via `core/context.py` instead of
    R-7's byte cap: the role's token budget is reduced by the task description's and the role's
    instruction footer's estimated cost, and what remains funds the recency-weighted carryover
    loop and any rework note, each fit via `compile_artifact`. `_hop_carryover_budget`/
    `_truncate_carryover`/`config.HOP_CARRYOVER_BYTES` are no longer called from here — the two
    truncation mechanisms are never layered — but the first two remain defined, unused, in
    `core/dispatch.py` (this card's file-ownership carve-out permitted editing only
    `_hop_message`; their removal is left for a follow-up card, per the project's dead-code
    register convention).
  - The `context_composed` trace event's per-section payload gains a `dropped_fields` list (which
    `HandoffArtifact.DROP_ORDER` fields, if any, were shed for that section) alongside its
    pre-existing `original_bytes`/`sent_bytes`/`truncated` keys.
  - `HandoffArtifact.DROP_ORDER`/`dropped()` (ROADMAP Phase 16 W-5) now has its intended real
    consumer — see "Structured handoff artifacts" requirement 4, reworded to point here instead of
    describing this as future work.
  - No CLI surface added; `bash tests/golden/run.sh verify-all` stays byte-identical (none of the
    18 cases exercise the pod-dispatch runtime pipeline). Message *layout* is unchanged for the
    common (small-output) case — a hop whose carryover already fits its budget composes
    byte-identically to before this card; only the behavior once a budget is actually exceeded
    changes (structured field-shedding instead of a blind byte-halving truncation).

### Version 4.0.0 (2026-07-30)

- **ROADMAP Phase 16, card W-5 (structured handoff artifacts) — gates Phase 17's C-1.** Hops used
  to exchange concatenated raw text (`HopResult.output`, threaded straight into the next hop's
  message by `_hop_message`). This card replaces that with a typed record:
  - New module `core/handoff.py`: `HandoffArtifact` (Pydantic, `extra="forbid"`, frozen) —
    `summary` (required), `files_changed`, `diff_ref`, `verdict`, `notes`. `DROP_ORDER` declares a
    least-valuable-first field-shedding order (`notes`, `diff_ref`, `files_changed`, `verdict` —
    `summary` is never in it) and `dropped(field)` returns a copy with that field reset to empty —
    the seam Phase 17's C-1 is expected to use to budget tokens per field. `render()` returns
    exactly `summary` when every other field is at its default (true for every hop today except a
    verdict-gated one), so a hop with nothing else to report composes byte-identically to the
    pre-W-5 raw-text behaviour. `from_legacy_output(output)` degrades a bare string to
    `summary`-only — the backward-compatibility path.
  - `HopResult` gains an `artifact: HandoffArtifact | None = None` field, backfilled in
    `__post_init__` via `from_legacy_output(output)` when unset — every `HopResult` therefore
    always carries a real artifact, whether built explicitly (`_execute_unit`, verdict pre-parsed
    and embedded before the hop is persisted) or hand-built by an existing test that only ever
    passed `output=`. `rendered_artifact()` is the one accessor `_hop_message` uses.
  - `_hop_message` now composes both the rework-note section and the generic prior-hop carryover
    loop from `h.rendered_artifact()`, never `h.output` directly — see "Bounded hop prompts" for
    how R-7's byte-budget cap now applies to that rendered text (unchanged cap mechanics, a
    different, structurally richer input).
  - `_hop_record`/`_hop_from_record` persist/restore the artifact (`artifact` key, a
    `model_dump()`/`model_validate()` round trip) alongside the pre-existing `output` field
    (never replacing it). A record with no `artifact` key (every task queued before this version)
    or a malformed one degrades via `from_legacy_output` — verified end to end, including a
    simulated crash-and-`--resume` round trip through the exact persisted-record shape.
  - `files_changed`/`diff_ref` are real fields but **not populated by dispatch** as of this
    version — an honest, documented seam (`core/handoff.py`'s own docstring explains why: doing so
    needs a real git-diff probe, and the git shell-out surface belongs to a different in-flight
    card this wave). `verdict` **is** populated: parsed once (reusing the existing
    `core.orchestrator.parse_verdict` call `_execute_unit`'s `VerdictGate` branch already made,
    now computed before the hop is constructed so it lands in the same artifact that gets
    persisted) for any `VerdictGate`-gated hop (Reviewer/Tester, or a W-8 non-built-in verdict
    gate); `None` for every other hop.
- **Dead-code register, three items this card's owner (`core/dispatch.py`) closed:**
  1. The `print(f"[dispatch] verification skipped...")` at the old line 1313 — a layering
     violation (`core/` never prints). Replaced with a `tool_result` trace event
     (`{"verification": "skipped", "member": <id>}`, parity with the existing "passed" case) plus
     a new `HopResult.verification_skipped` flag; `cli/_pod.py`'s dispatch renderer prints the
     exact same wording the old `print()` produced, in the same position (before the task's own
     summary line). See "Implementer verification gate" and "Generalized gate execution".
  2. `dispatch_all_pods` (flagged uncalled) — **deleted, not wired**. Investigated: it has zero
     production callers for a real reason, not an oversight — R-3 replaced its one former call
     site (`serve.py`'s sweep loop) with a per-pod loop over `dispatchable_pods()` +
     `dispatch_pod()` through `core.runs.execute`, specifically for the per-pod run-registry
     granularity `dispatch_all_pods`'s coarse "one sweep, swallow `DispatchError`" shape did not
     have (`tests/python/test_r3_no_suppressed_dispatch.py` pins both halves of this fact). Wiring
     it back would reintroduce the exact behaviour R-3 deliberately replaced.
  3. Finished Phase 18 CL-1's blocked sweep: the ~76 `edges.adapters.openclaw.AgentRunResult(...)`
     call sites across `test_r2/r4/r5/r6/r7`, `test_cd2`, `test_dispatch`, `test_g1_*`, `test_l1_*`
     now spell `core.runtime_driver.TurnResult` directly (`core/dispatch.py`'s own `Runner` type
     alias too). With zero references left anywhere in the tree, the `AgentRunResult` alias itself
     (kept alive by exactly this file's `Runner` alias, per CL-1's own note) was deleted from
     `edges/adapters/openclaw.py` — not left as a compatibility shim nobody uses.
- No CLI surface added; `bash tests/golden/run.sh verify-all` stays byte-identical (none of the 18
  cases exercise the pod-dispatch runtime pipeline). One existing test's trace-event count
  (`test_dispatch.py::TestPipeline::test_traces_written_per_hop`) updated to account for the new
  "skipped" `tool_result` event on a lean pod's un-configured Implementer verify gate — a real,
  intentional, additive observability improvement, not a bug.

### Version 3.0.0 (2026-07-30)

- **ROADMAP Phase 16, card W-2 (executor) / W-8 (generalized gates), shipped together** per
  ROADMAP's explicit sequencing rule ("W-6/7/8 land with the executor, not after — an executor
  that hardcodes roles a second time forces a second migration"). This is a generalization, not a
  behavior change: the built-in lead/implementer/reviewer/tester pipeline's observable behavior
  (task status, hop sequence, trace event names/payloads, reasons, retries, budget/approval
  gating, crash resume, rework bounds) is byte-identical to 2.1.0, verified by the full pre-
  existing test suite passing unchanged.
  - `dispatch_task`/`dispatch_pod` gain an optional `spec: PipelineSpec | None` parameter — `None`
    (every pre-W-2 caller) resolves `effective_pipeline(project, None)`, the pod's zero-migration
    pipeline (`core/pipeline.py`'s `default_pipeline()`, patched only so its Reviewer rework
    budget reflects this pod's `maxReworkCycles`, since the pipeline format necessarily hardcodes
    a fixed default and there is no "pod" concept at that layer).
  - Gate execution reads each step's *resolved* gate (`core.orchestrator.resolve_gate`) instead of
    branching on a hardcoded role name — see "Generalized gate execution". `_parse_reviewer_
    verdict`/`_parse_tester_verdict`/`_REVIEWER_VERDICT_RE`/`_TESTER_VERDICT_RE` (dispatch's own
    private, independent copy of what the pipeline format already declared) are deleted; the
    single source of truth for those patterns is now `core/pipeline.py`'s `default_pipeline()`,
    cross-checked against the W-6 archetype registry by test.
  - `_pipeline_step_requires_approval` — G-1's deliberately inert seam ("W-1/W-2 fills this"),
    previously a permanently-`False` stub — is now real: a step whose resolved gate is
    `ApprovalGate` genuinely gates pre-hop, composing with the pod-level source.
  - A `parallel` step's children now actually execute — see "Parallel step groups": a bounded
    thread pool, join semantics, per-child persistence as each completes (not deferred to the
    group's join, preserving R-1's crash-safety guarantee for a concurrent fan-out), and a
    documented limitation that a mid-group crash resumes by re-running the whole group.
  - `docket runs cancel <id>` — see "Cancellation": kills every pid recorded in-flight for a run
    (its whole process group, not just the immediate child — every hop subprocess now starts its
    own session), and marks the run a new terminal state, `"cancelled"`.
  - `_replay_pipeline_position` (crash resume) generalizes from a role-keyed set to a step-id-
    keyed replay driven by each position's own resolved gate, with per-gate rework-cycle counters
    (a pipeline may declare more than one independent rework-capable gate) instead of one pod-wide
    counter. Persisted hop records gain a `stepId` field (defaulting to `role` for a legacy
    record — no behavior change for the built-in pipeline, whose step ids equal their role names).
  - `pod_full_roster` resolves every role a pod's members actually carry (not just the four legacy
    ones `pod_pipeline` considers), so a custom pipeline can target a non-legacy (e.g.
    starter-library) role.
  - New trace event types: `verdict_rework_started`/`verdict_rejected`/`verdict_unparseable` (any
    non-built-in verdict-gated role/archetype); the two built-in verdict roles keep their exact
    legacy event names.
  - `docket pipeline validate|plan|run` (see `cli-interface.spec.md`) is the new CLI surface that
    drives a custom `PipelineSpec` through this machine; `plan` renders directly from
    `core.orchestrator.resolve_plan`/`render_plan` — the same function the real executor calls,
    never a second, drift-prone pretty-printer.

### Version 2.1.1 (2026-07-30)

- **Phase 18 CL-1 (legacy/dead-code cleanup) — documentation only, no behavior change.**
  `edges/adapters/openclaw.py`'s own code (the `agent_run` free function and its docstring) now
  spells the canonical name `core.runtime_driver.TurnResult` directly instead of the Phase 18
  L-1 alias `AgentRunResult`. The `AgentRunResult` name itself is **not** deleted — it still
  has one real consumer, `core/dispatch.py`'s `Runner = Callable[..., _oc.AgentRunResult]` type
  alias, and that file is owned by a different in-flight card (Phase 16 W-2) and out of CL-1's
  file scope. This section's wording is updated to match; the alias, its fields, and its
  positional-construction compatibility are otherwise unchanged from 2.0.1.

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

### Version 2.0.1 (2026-07-30)

- ROADMAP Phase 18 L-1 (D-14): each hop's agent turn now runs through the typed `RuntimeDriver`
  port (`core/runtime_driver.py`) — `dispatch_task`'s default runner is
  `edges.adapters.openclaw.default_driver().run_turn`, swapped in at the exact call site that
  used to read `_oc.agent_run` (a one-line change; `core/dispatch.py` is otherwise untouched).
  `OpenClawDriver.run_turn` delegates straight through to the pre-existing `agent_run` free
  function, so the daemon subprocess call, its argv, and its retry/timeout/failure-kind semantics
  are byte-for-byte unchanged — this is a containment refactor (closing an ACL leak the
  session-JSONL cost/trace parsing had opened), not a behavior change to the pipeline.
  `AgentRunResult` is now an alias of `core.runtime_driver.TurnResult`; every existing
  positional-construction call site (tests included) keeps working unchanged. Test coverage
  gained a shared `FakeDriver` test double (`tests/python/fakes.py`) implementing the full
  `RuntimeDriver` protocol, adopted by `test_dispatch.py` in place of its former ad-hoc
  `_RecordingRunner` shim.
- Cross-reference only (ROADMAP Phase 16 W-6): named the new declarative role-archetype registry
  (role-archetypes.spec.md) in "Does NOT cover" and clarified that its `gateContract` field is
  descriptive data only today — this pipeline's own Reviewer/Tester/Implementer gate logic is
  unchanged and still independently hardcoded (wiring the two together is Phase 16 W-8). No
  behavior in this pipeline changed.

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
