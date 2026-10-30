# Pod Dispatch Pipeline Specification

**Version**: 11.9.0
**Status**: Implemented and live. `docket run` and the `docket start --dispatch` sweep claim a pod's
queued tasks and drive each through its pipeline, one real agent turn per hop, with locked claims,
crash resume, gates, parked approvals and questions, task worktrees and per-hop evidence.
**Last Updated**: 2026-10-30

## Purpose

This specification defines the pod dispatch pipeline's state machine: how `docket run` (and the
opt-in `docket start --dispatch` sweep) claims queued tasks and drives them through a pod's roles
hop by hop, how a task survives a crash mid-run, how it retries, blocks, waits for a human decision
or answer, and resumes, which gates can stop advancement at each hop, and what a caller can observe
afterwards (task status, per-hop record, trace events). The pipeline a task runs is a
`PipelineSpec` resolved against the pod's live roster into a deterministic `ExecutionPlan`; the
executor walks that plan step by step, evaluating each step's resolved gate by its type, running a
`parallel` group's children concurrently, and honouring each step's own `on:` routes.

## Scope

This specification covers:

- The task record's lifecycle: creation, locked claiming, the persisted `running` state, per-hop
  incremental persistence, terminal and waiting states, and how a task moves between them
- Crash recovery: the stale-claim sweep and `--resume`-driven continuation from the last persisted
  hop (including mid-rework, and, at group granularity, mid-parallel-group)
- Concurrency: why two dispatchers can never double-run one task
- Pipeline step order and which roles and agents take part for a given pod and spec, including a
  verdict gate's bounded rework loop and a `parallel` group's concurrent children
- Per-hop execution: message construction under per-role token budgets, environment injection,
  the real agent turn, and retries of a transient failure
- Timeout configuration: independent agent-turn and verify-command timeouts and their resolution
  order, including a step's own `retries`/`timeout` override
- The gates that can stop a task mid-run: budget (with auto-pause), the require_approval gate,
  `mechanical`, `verdict` and `external` gates, a task's own gate, and the protected-path check at
  the end of a run
- Parked approvals and operator questions, pre-grants, and task briefs
- Cancellation: how `docket task cancel <ref>` reaches an in-flight hop and a parked task
- Registry retention: the shared trigger and liveness rule that bound `docket-runs.json`, the
  approval store and the conversation registry
- Structured handoff artifacts, the diff producer, hop evidence, hop events and task usage
- Task worktrees, worktree preparation, and the evidence document a task's hops produce
- The complete task-status and failure-kind vocabulary, and every trace event this pipeline emits

This specification does NOT cover:

- The member-level `.docket-meta.json` fields dispatch reads (`portRangeStart`, `portRangeCount`,
  `scratchDir`, `verifyCmd`, `paused`/`pausedReason`): see `docket-meta.spec.md`. The pod
  settings dispatch reads are listed under "Pod dispatch settings" below
- The approval store's own record lifecycle (`pending`/`granted`/`denied`, the CLI/HTTP
  channels, audit-log parity): see `security-gates.spec.md`. This spec covers only how dispatch
  creates and reacts to a record
- The CLI surface for queuing, inspecting and dispatching tasks (`docket task add|list|show|diff|trace|prune`,
  `docket pod add`, `docket pod set`, `docket run`, `docket task cancel`, and their flags) beyond the
  behaviour stated here: see `cli-interface.spec.md`
- Budget-cap accounting in general and the `docket pod set budgetUsd` contract: see
  `cost-tracking.spec.md`. This spec covers the pre-hop budget check and the auto-pause it drives
- The persisted dispatch-run registry (`GET /runs`, `docket log`) that records each invocation of
  this pipeline, including its `pids` and cancellation fields: see `serve-read-api.spec.md` and
  `cli-json-shapes.spec.md`. This spec covers what happens inside one invocation and how a hop's
  pid is reported into that registry
- The locked read-modify-write primitive itself; this spec relies only on its atomicity
- The role-archetype registry's schema (`gateContract`, the built-in and starter archetypes, the
  overlay): see `role-archetypes.spec.md`. This spec covers how the executor consumes a
  `gateContract` as a gate fallback
- Pod provisioning and blueprints (which roles a pod has, `--count N` members, workspace kind):
  see `workspace-structure.spec.md` and `pod-blueprints.spec.md`
- The context compiler's internals (the chars-per-token approximation, field shedding, summary
  truncation, `RoleArchetype.token_budget`'s schema): see `role-archetypes.spec.md`. This spec
  covers how a hop's message consumes that compiler

## Requirements

### Task lifecycle and identity

1. A newly queued task (`enqueue_task_once`) **MUST** be created with a unique `task-<uuid4>` id (not a
   timestamp: concurrent enqueues under the same millisecond would otherwise collide and leak
   false ordering), `status: "pending"`, a `created` timestamp, `priority` (`high`/`normal`/`low`;
   any other value is stored as `normal`), `channel`, an empty `hops` array,
   `costUsd: 0.0`, `reason: ""`, and `claimedAt`/`startedAt`/`completedAt` all unset. The record
   carries no claim token: a stale claim is read from `claimPid` with `claimedAt`, and `channel`
   says where the task came from.
   Enqueue screens the description through `pre_input` once: a `block` raises `DispatchError` and
   stores nothing; a `require_approval` stores the task `waiting_approval` with
   `pendingApprovalIndex: 0`, opens the `approval` escalation of the approval it creates once the
   task is stored (a lost idempotency race opens none) and traces `approval_required` naming that
   escalation (`security-gates.spec.md`), so the inbox lists the pause once
   (`operator-loop.spec.md` area 11).
   Enqueueing into a project with no pod raises `DispatchError`.
2. Every read of a pod's queue (`TaskRepository.list`) **MUST** fill each field enqueue does not write with
   its default (`priority`, `status`, `startedAt`, `completedAt`, `reason`, `costUsd`,
   `claimedAt`, `pendingApprovalIndex`,
   a fresh empty `hops` list, `created`, `id`); no
   separate migration step exists or is required.
3. A task's status **MUST** be one of exactly eight values: `pending`, `running`,
   `waiting_approval`, `waiting_input`, `blocked`, `done`, `failed`, `cancelled`. (See "Task
   status vocabulary" below for terminal vs. non-terminal.)

#### Task text at the CLI

`docket task add` **MUST** take the task text as a single argument (quote it in the shell) and
refuse, exiting 1 without enqueueing, an empty text or a text longer than 500 characters.
`--priority` accepts only `high`, `normal` or `low`; any other value exits 2 without enqueueing.

#### Enqueue channel

`enqueue_task_once` **MUST** take a required keyword `channel`, one of `cli`, `http`, `telegram`,
`mcp` or `routine` (a task a routine created, "Routines"), persist it on the task as `channel` beside `source`, and append `task.enqueue` to the audit
log naming the project, the task and the channel. `source` stays the origin class (`operator`,
`reviewer` for a rework task) and alone drives the `pre_input` trust default; `channel` never
changes trust. The detail names no description text. `POST /dispatch/<project>` **MUST** append
`run.dispatch` naming the run, the project and `channel=http` beside the run record it creates.

#### Addressable task (ADR 0027)

1. `enqueue_task_once` **MUST** accept `external_ref`, `idempotency_key`, `base_ref`, `pipeline`,
   `gate`, `max_tokens`, `prepare`, `restrictions` and `autonomy` as keyword arguments, validate them through
   `validate_task_options` (shape and narrowing only) before anything is persisted, and store each
   one that is set on the task record verbatim under its camelCase key: `externalRef`,
   `idempotencyKey`, `baseRef`, `pipeline`, `gate`, `maxTokens`, `prepare`, `restrictions`,
   `autonomy`. A field left unset is absent from the record. `baseRef`, `pipeline`, `gate` and `prepare` are
   acted on at claim, `gate`, `maxTokens` and `restrictions` at hop time; enqueue acts on none of
   them.
2. A wrongly shaped field (a non-string `externalRef`, an empty string, a blank `pipeline`, a
   `maxTokens` that is not a positive integer, a `gate` without a `command`, an invalid
   `prepare` command, an `autonomy` outside `L3`/`L4`/`L5`) raises `DispatchError`. An `autonomy`
   above the pod profile's ceiling raises `TaskRestrictionError` (`422`). A `restrictions` entry that would widen --
   `network` other than `"none"`, a `deniedTools` name outside `BUILTIN_TOOL_KINDS`, a policy
   whose action is not `block` or that does not validate -- raises `TaskRestrictionError`, a
   `DispatchError` subclass, so a caller can tell `422` from `400`. Nothing is persisted and no
   `task.enqueue` is audited in either case.
3. When `idempotency_key` is set and a task in this pod's queue already carries that
   `idempotencyKey`, the lookup runs inside the same locked read-modify-write that appends, the
   queue is left untouched, no `task.enqueue` is audited, and that existing record is returned.
   `enqueue_task_once(...)` returns `(task, created)`.

### Task references

1. `resolve_task(project, ref)` **MUST** resolve a full task id, the short id `task list` prints
   (the first 18 characters), or any unambiguous prefix, within one pod or, when `project` is
   `None`, across every dispatchable pod. An exact id wins over longer ids it prefixes.
2. A reference beginning `run-` **MUST** resolve through the run record to the task that run
   dispatched; a run that dispatched no queued task, or more than one, or belongs to another pod
   than the one asked for, **MUST** raise `TaskRefError`.
3. The result `TaskRef` **MUST** carry `task_id`, `project`, `session_key` (equal to
   `step_session_key` for the Lead hop), `run_ids` (every run record listing the task, newest
   first) and the recorded worktree directory, empty when the task runs in place.
4. An ambiguous reference **MUST** raise `TaskRefError` listing every candidate id with its pod;
   an unknown one **MUST** raise it naming the pods searched. The resolver reads the queue and
   never writes.

### Claiming (locked, race-free)

1. Before a task's first hop runs, it **MUST** be **claimed**: a single locked read-modify-write
   of the pod's queue file (holding its filelock for the whole operation) that selects the next
   eligible task, flips its status to `running`, clears its `failureKind`, and persists
   `startedAt`, `claimedAt`, and `claimPid` (the claiming process's pid; the concurrency guarantee
   comes from the filelock held during the read-modify-write, not from any token) -- all **before** the claim returns and before any hop is attempted.
2. Because the read (which task is next), the mutation (flip to `running`) and the write all
   happen inside one lock acquisition, two concurrent `dispatch_pod` calls against the same pod
   (different threads, or different processes) **MUST NOT** be able to claim the same task: the
   second caller's read already observes the first caller's claim and either picks a different
   eligible task or finds none left. This is what makes the HTTP webhook, the schedule, the sweep,
   the MCP dispatch tool and a manual `docket run` all safe to run concurrently against one pod.
3. Eligible-for-claim rules: a `pending` task is always eligible. A `failed` task whose
   `failureKind` is one of `RESUMABLE_FAILURE_KINDS` -- `"stale_claim"` (see "Crash recovery"
   below) or `"dispatch_refused"` (see "Deterministic refusal inside a claimed task" below) -- is
   eligible **only** when the caller passed `resume=True` (`docket run --resume`); crash and
   refusal recovery is opt-in, never automatic, and neither tag waits out a staleness timer at
   claim time (a swept `stale_claim` already waited for `CLAIM_STALE_TIMEOUT` to be tagged; a
   `dispatch_refused` task's claim was never left dangling). No other status is ever claimable (in
   particular, `blocked`, `waiting_approval`, `waiting_input` and a plain `failed` task -- one
   whose failure was a real graded hop or gate outcome -- are never reclaimed by a dispatch run;
   see "blocked and terminal-failure re-entry" below).
   Within one dispatch run a task is claimed **at most once**: a `dispatch_refused` task that
   the run just settled is not claimed again by the same run, so a resuming sweep cannot spin on
   a refusal that only an operator action can clear.
4. Among eligible tasks, the highest-priority one is claimed first (`high` < `normal` < `low`
   rank); ties are broken by queue order (a stable sort preserves each task's original enqueue
   position).
5. A pod whose Lead is currently paused (see "Budget gate and auto-pause") **MUST** refuse every
   claim outright -- no task is even flipped to `running`, and a `paused_refused` trace event
   (payload: the pause reason) is emitted every time a claim is attempted against a paused pod.
   This check happens before the locked claim operation (pause changes are rare, operator-driven
   events, not something concurrent claims race over), so a paused pod costs nothing further: no
   claim write, no wasted agent turn.
6. `docket run --resume` **MUST NOT** require a `pending` or already-tagged-resumable task to
   exist before it attempts a dispatch when some task is `running`. A `running` task's claim may
   or may not be stale -- the CLI does not duplicate that judgment -- so it only lets the call
   proceed into `dispatch_pod`, whose own stale-claim handling (see "Per-hop incremental
   persistence and crash recovery") decides and reclaims within that same call. An operator facing
   an orphaned `running` task can therefore trigger recovery without queueing an unrelated task.

### Per-hop incremental persistence and crash recovery

1. As each hop completes -- success or failure, including every rework hop (see "Reviewer verdict
   gate") -- its record **MUST** be appended to the task's persisted `hops[]` array immediately
   (and the task's `costUsd` recomputed from them), not held in memory until the whole task
   finishes. A crash between hop *N* finishing and hop *N+1* starting therefore loses at most the
   in-flight attempt, never a completed hop.
2. Every hop-completion persist, every retry attempt (see "Retries") and every `started`
   process event of a turn that serves the task **MUST** refresh the task's `claimedAt` timestamp
   -- each is forward progress, not staleness, and this is what stops a legitimately long-running
   hop (especially one retrying, or one running one command after another) from being mistaken
   for a crashed claim by a *concurrent* dispatcher's stale-claim sweep.
3. At the top of every `dispatch_pod` call (including one made by a different thread or process
   than the one that claimed a task), any `running` task whose `claimedAt` is older than
   `max(CLAIM_STALE_TIMEOUT, lease)` (`CLAIM_STALE_TIMEOUT` defaults to 1800s and is
   env-overridable; the lease is the pod's `turnTimeoutS` plus `verifyTimeoutS` of requirement 4a,
   so a pod with a long turn is never swept inside it) **MUST** be swept to `failed` with
   `failureKind: "stale_claim"`, reason `stale claim — dispatcher likely crashed mid-task`, and a
   `stale_claim` trace event (payload: the task and its `claimedAt`), and
   its already-persisted `hops[]` left untouched. This is the presumption that the dispatcher which
   claimed it crashed mid-task.
4. `docket run --resume` **MUST** reclaim a `stale_claim`-failed task (per the eligibility rule
   above) and continue it from its last persisted hop rather than hop 0: the claimed task's
   existing `hops[]` seed `dispatch_task`'s `resume_from`, and the steps they represent are skipped
   rather than re-invoked. Without `--resume`, a swept task **MUST** stay `failed` and untouched by
   future dispatch runs (crash recovery is never automatic).
4a. A `running` task is **stale** when either condition holds: (i) the dispatcher process that
   claimed it is gone -- the claim records `claimPid`, and a process-liveness check reports that
   pid dead -- or (ii) its `claimedAt` is older than the pod's `turnTimeoutS` plus
   `verifyTimeoutS` (each falling back to `DEFAULT_TIMEOUT` when unset). Under `--resume`,
   `dispatch_pod` **MUST** reclaim a stale `running` task immediately, with no wait for
   `CLAIM_STALE_TIMEOUT` (`reclaim_stale_running`): it is settled to `failed`/`stale_claim`, its
   `hops[]` kept, claimed again and continued from its last persisted hop, a `task.reclaimed`
   audit entry records the task id and which condition fired, and the same `stale_claim` trace
   event as requirement 3 (payload: the task and its `claimedAt`) marks the task's trace, so a
   restarted hop is distinguishable from an ordinary retry. A `running` task whose claimant is
   alive and whose claim is inside the lease **MUST NOT** be reclaimed. Without `--resume` nothing
   is reclaimed this way (requirement 4); the `CLAIM_STALE_TIMEOUT` sweep of requirement 3 still
   runs.
4b. `dispatch_pod(stop=)` **MUST** evaluate `stop()` before each claim and return once it is true,
   leaving unclaimed tasks `pending`; a task already claimed runs to its terminal or waiting state
   (the stop is never checked inside a task). The `docket start --dispatch` sweep passes the
   server's stop event and `resume=True`; `reclaim_stale_running` on a queue with no stale claim
   **MUST NOT** write the queue, trace or audit.
5. Resuming correctly requires more than "which roles already ran", because a step can
   legitimately appear more than once in a resumed task's history (the Implementer re-runs after a
   REQUEST-CHANGES, then the Reviewer re-reviews; an `on:` route revisits a step). Resume **MUST**
   replay the persisted hop sequence to recompute the exact pipeline position, the rework-cycle
   and route counts, and (if resuming mid-rework) which hop's text still needs to reach the rework
   target -- the same decision a live run makes -- so a task resumed mid-rework re-enters the
   rework Implementer hop, never a stale position past the Reviewer.

### Deterministic refusal inside a claimed task

1. `dispatch_task` **MUST** catch a `DispatchError` raised anywhere on the path it drives for one
   already-claimed task -- the cross-pod membership check ("Pipeline order and participation"
   requirement 3), its own up-front pod and Lead revalidation, a step `model` that does not
   resolve, a task restriction policy that is invalid or not `block` ("Per-hop execution"
   requirement 7), a task gate with no step to follow ("Generalized gate execution" requirement 7),
   an unmet `lights-out` profile (audited `profile.refused`), and the driver's refused isolation or
   network posture (`security-gates.spec.md`; never retried) -- and fold it into a normal return: a
   `TaskResult` with `status="failed"`, `reason` set to the `DispatchError`'s message verbatim, and
   `failure_kind="dispatch_refused"`. It **MUST NOT** let the exception propagate to
   `dispatch_pod`.
2. `dispatch_pod` therefore always settles this task exactly as it does any other terminal result:
   the stored task gets `status: "failed"`, the refusal `reason` and `failureKind:
   "dispatch_refused"`, and the claim is settled, not orphaned -- and
   the loop **MUST** continue to the pod's next eligible task rather than aborting the whole
   dispatch run. Any hop that completed before the refusal (e.g. the Lead's) was already persisted
   incrementally and **MUST** remain in the task's `hops[]`.
3. A `dispatch_refused`-tagged `failed` task **MUST** be reclaimable by `docket run --resume` (per
   "Claiming" requirement 3) once its underlying cause is fixed -- a corrected pipeline file naming
   a real pod member, for instance -- and **MUST** then continue from its last persisted hop exactly
   as a resumed `stale_claim` task does (requirements 4-5 above apply identically; it is not a
   separate pipeline-position scheme). This reclaim needs no `CLAIM_STALE_TIMEOUT` wait and no decoy
   task queued first: the claim was already cleanly settled, not crashed.
4. This is scoped to `DispatchError` specifically, never any other exception. A real crash (the
   agent-turn process dying, a network failure, an unhandled bug) **MUST** still propagate out of
   `dispatch_pod` unchanged, leaving the task `running` for the stale-claim sweep -- catching a
   broader exception class here would wrongly settle a genuinely orphaned claim as a clean
   `"failed"` outcome instead of leaving it for crash recovery.
5. `dispatch_task` **MUST** emit a `dispatch_refused` trace event (payload: the refusal reason) at
   the point it catches the error, in addition to the `session_end` event every `dispatch_task`
   call emits with the final status. The run registry needs nothing further to record this: a
   `TaskResult` returned with `status="failed"` already finishes that run as `"failed"` with an
   error summary and its own `error` trace event, the same as any other failed task.

### Mechanical HEARTBEAT ledger

The pod Lead's `HEARTBEAT.md` carries a docket-owned dispatch ledger inside `## Active Tasks`,
kept equal to the queue's `running` tasks mechanically, whether or not an agent writes anything
itself. `workspace-structure.spec.md` owns the file-level contract.

1. A successful claim (see "Claiming") **MUST** sync the pod Lead's ledger (`sync_dispatch_tasks`)
   from the queue's own `running` tasks, before the claim returns and before any hop is attempted.
   The ledger entry for a task therefore exists *before* its first hop runs.
2. Every hop-completion persist and every retry-attempt claim refresh **MUST** re-sync the same
   ledger from the queue's current `running` tasks -- so a task's entry reflects its current hop
   count and refreshes its shown claim time across a long retry loop.
3. Once a task leaves `running` (to any other status, including through a claim-time refusal, a
   parked-task cancellation or a resolved `check_changed` approval), the ledger **MUST** be
   re-synced so that task's entry is removed: the ledger reflects exactly the set of tasks
   currently `running` in `TASK_LIST.json`, for this pod, at all times -- never a task that has left
   that state, and never one that has not been claimed yet.
4. The ledger sync **MUST NOT** clobber anything outside its own delimited region
   (`DISPATCH_BLOCK_BEGIN`/`_END`, two HTML-comment markers inside `## Active Tasks`) -- an agent's
   own hand-written entries under the same heading, and every other section of `HEARTBEAT.md`
   (`## Pending Decisions`, `## Notes`, anything else), **MUST** survive every dispatch-driven
   rewrite byte-for-byte. The first sync against a file with no such region yet **MUST** insert one
   immediately after the `## Active Tasks` heading (or, if that heading is missing entirely, append
   a fresh one at end-of-file) rather than require the region to pre-exist.
5. Two tasks concurrently `running` in the same pod (see "Claiming" -- two concurrent
   `dispatch_pod` calls may each claim a different task) **MUST** both appear in the ledger; a sync
   triggered by either task's lifecycle **MUST** regenerate the *whole* region from the queue's
   current state, never just the one task that triggered it, so neither dispatcher's sync can
   silently erase the other's entry.
6. `docket setup` **MUST** flag a divergence between `TASK_LIST.json`'s `running` tasks and the
   Lead's ledger -- a task `running` with no matching ledger entry, or a ledger entry naming a task
   that is not `running` -- and **MUST**, under `--fix`, resolve it by re-syncing the ledger from
   `TASK_LIST.json` (the same sync dispatch calls) -- always safe, since `TASK_LIST.json` is this
   pipeline's own source of truth and the ledger's dispatch region is entirely docket-owned.
7. Every write of the queue **MUST** re-sync the ledger once the write is done, whichever
   operation made it: the writes through `TaskRepository` (enqueue, claim, hop persist, claim
   refresh, finalize, stale sweep, reclaim, `retry_task`, `unblock_pod`, parked cancellation,
   approval resolution, worktree prune, a stored worktree or prepare record) are all covered, so
   a ledger entry left behind by a task that is no longer `running` goes with the next write,
   `retry_task` included. A call that changes nothing writes nothing and re-syncs nothing.

### Conversation registry auto-population

The conversation registry is seeded at binding time (`docket setup notify bind`); dispatch keeps a
wired agent's conversation current with the task it is working.

1. After each hop persists, every tracked conversation belonging to that hop's agent
   (`hop.member_id`) -- there **MAY** be more than one, across different channels and peers --
   **MUST** have its `last_message` (a short preview of the hop's output) and `task_ref` (the
   dispatched task's id) refreshed (`touch_for_hop_durable`), and its `updated` timestamp bumped. A
   pod member with no tracked conversation **MUST NOT** have one fabricated by this path -- it is a
   no-op for an unwired member.
2. This path **MUST NOT** alter a conversation's `topic`, `status`, `channel`, `peer_id`, or
   `peer_kind` -- only `last_message`/`task_ref`/`updated` move; an operator's own classification
   of a thread is never overwritten by dispatch activity.
3. A hop for one pod member (e.g. the Implementer) **MUST NOT** touch a different member's (e.g.
   the Lead's) conversation -- each hop only refreshes the conversation(s) keyed to its own
   `member_id`.
4. A hop touch, and every public durable conversation mutation, **MUST** read, transform, and write
   the registry within one locked read-modify-write boundary. Concurrent mutations for different
   conversations **MUST** merge; concurrent mutations for the same conversation are serialized by
   that boundary, so the later completed mutation is the durable value. An unwired hop and an
   unknown conversation resume are true no-ops: they **MUST NOT** rewrite the registry. Invalid
   registry data and a mutation exception **MUST** leave the existing file untouched. The boundary
   preserves unknown registry and conversation fields and writes no raw full hop output (only the
   bounded preview).

### blocked and terminal-failure re-entry

1. A task that is stopped by the budget gate (see "Budget gate and auto-pause"), by a brief's
   missing resources ("Task brief" requirement 3), or by an expired question ("Operator input steps
   and answers" requirement 8) **MUST** transition to `blocked`, **MUST NOT** be silently rewritten
   back to `pending`, and **MUST** persist a `blockedReason`. A `blocked` task is not attempted
   again by any future `dispatch_pod` call -- it is not in the claimable set at all -- until one of
   exactly two operator-driven actions moves it back to `pending`:
   - `retry_task` (`docket task retry <task-id>`) -- a single named task, a no-op if that task is
     neither `blocked` nor `failed` (requirement 2).
   - `unblock_pod`, which flips **every** `blocked` task in the pod's queue back to `pending`
     whatever its `blockedReason`, and clears that reason. It runs on every
     `docket pod set budgetUsd <n>` and `docket pod unset budgetUsd`, and on `docket run --resume`
     (see `cost-tracking.spec.md`).
2. A plain `failed` task (a real graded gate or hop outcome -- not a `RESUMABLE_FAILURE_KINDS`
   settlement) is terminal for that dispatch attempt and **MUST NOT** be automatically retried by a
   later `dispatch_pod` call, with or without `--resume`. It **MUST** be retryable by an operator:
   `retry_task(project, task_id)` flips a `failed` (or `blocked`) task of any `failureKind` to
   `pending`, keeps its `hops[]`, clears `failureKind`/`reason`/`completedAt`/`blockedReason`, and
   writes a `task.retry` audit entry. It returns False for a missing task or any other status.
   `docket task retry <ref>` is the operator surface: it calls `retry_task` for the resolved task,
   exits 1 naming the task's status when it returns False, and otherwise ends with the run hint.

### Pipeline order and participation

1. A dispatch run **MUST** drive steps in the order declared by its `PipelineSpec` --
   `dispatch_pod`'s and `dispatch_task`'s `spec` parameter. `None` (every caller that names no
   pipeline: `docket run` without `--pipeline`, the `docket start` sweep, schedule and webhook, and
   the MCP dispatch tool) resolves `effective_pipeline(project, None)`. The resolution order is: a
   caller-supplied `spec` always wins outright (returned unpatched); otherwise this pod's **bound
   pipeline** (`PodSettings.pipeline`, see "Pod dispatch settings" below) wins next, also
   unpatched; otherwise the Lead's `blueprint` is looked up (`get_blueprint`) and, when it names a
   known blueprint, that blueprint's `defaultPipeline` is the base pipeline; when it is absent,
   empty, or names an unknown blueprint, the base pipeline is `default_pipeline()` -- Lead ->
   Implementer -> Reviewer. Only the blueprint or built-in base pipeline is then patched
   so every `VerdictGate` step with a rework edge reflects this pod's own `maxReworkCycles` (see
   "Reviewer verdict gate and bounded rework") -- for a blueprint pipeline this reaches whichever
   step declares the rework edge (e.g. the `research`/`content` blueprints' Reviewer step), not only a
   step named `reviewer`. A bound pipeline is caller-supplied-like and is **never** patched this way
   -- an operator who hand-wrote a rework edge's own `maxCycles` did not ask for the pod setting to
   override it, the same as a `docket run --pipeline` file. A role-targeted step whose role the pod
   does not have is skipped and consumes no pipeline position (the plan marks it `skipped`), for a
   bound pipeline exactly as for any other. A lean `software` pod (Lead + Implementer only) running
   the default pipeline runs exactly two hops per pass; a full pod runs up to four, plus any rework
   cycles (see below); a `research`, `content`, or `ops` pod runs its blueprint's full roster and
   gates. Before any task is claimed, `dispatch_pod` **MUST** refuse (`DispatchError`) a run whose
   variables leave a step's `instructions` with an unresolved reference (`pipeline-format.spec.md`
   "Variables"), or a `required` variable missing, unless a task still in the queue carries its own
   `variables` or names its own `pipeline`: those variables are the task's to supply, so the check
   waits for the claim. A task claimed under that deferral with neither its own `variables`, nor a
   `pipeline`, nor a kept `pipelineSpec` **MUST** settle `failed` with `failureKind: "pipeline"`
   and the same reason, before any hop (requirement 7).
2. A pod **MUST** have a Lead to be dispatchable at all; dispatching a project with no pod, or a pod
   with no Lead, **MUST** raise a `DispatchError` rather than attempt any hop.
3. Dispatch **MUST NOT** send a task to any agent outside the target project's own pod -- each
   hop's member id is asserted against the pod before its turn runs, raising `DispatchError` on a
   mismatch. This applies identically to a `parallel` group's children (see "Parallel step
   groups"). This check is `pod_of`, which **MUST** resolve a member's pod from its own recorded
   `.docket-meta.json` (`pod` field) first, falling back to id-string parsing only for a member with
   no meta or no recorded `pod` -- a member id ending in a registered role name that is not its own
   role (e.g. a custom `security-reviewer` role's member id `<project>-security-reviewer`, whose
   tail `reviewer` is itself a registered role) is not misread as belonging to a truncated project
   name. A member id with no recorded pod and no id-string match is still refused.
4. A step **MAY** legitimately run more than once within one dispatch attempt: a verdict-gated
   step's rework-triggering marker re-runs its gate's declared `rework.to` target and then the
   gating step again, and an `on:` route can send the task backward (bounded -- see "Reviewer
   verdict gate and bounded rework" and "Generalized gate execution"). The pipeline position is
   tracked as an index that can move backward, not a per-role "has this run yet" set; rework-cycle
   counts are tracked per *gated step id*, not one pod-wide counter, since a custom pipeline may
   declare more than one independent rework-capable gate (the built-in pipeline has one -- the
   Reviewer's).
5. A custom `PipelineSpec` **MAY** target a role outside the built-in three (`PIPELINE_ORDER`), e.g.
   a starter-library `researcher`/`writer`, or a role defined only in this pod's own overlay --
   `pod_full_roster` resolves *every* role the pod's members carry (first member per role), not
   just the three built-in ones `pod_pipeline` considers. The pod's roster resolution **MUST**
   resolve a role against the pod's own archetype overlay as well as the global registry, so a
   pod-only custom role is a real roster member, not only visible to `docket pod roles --pod`.
6. `docket pod set pipeline <file>` **MUST** validate *file* (`load_pipeline`) and plan it against
   the pod's *current* roster (`resolve_plan`) before accepting it: a role-targeted step whose role
   the roster lacks, or an agent-targeted step naming a member outside this pod, **MUST** refuse at
   `set` (exit 1, settings untouched) rather than silently binding a pipeline that can never fully
   run -- this is stricter than requirement 1's ordinary skip-on-run behaviour, which still applies
   once a pipeline is bound and a role is later removed from the pod. On success, `set` **MUST**
   write a docket-owned copy of *file*'s contents (`PIPELINE.yaml` in the Lead's workspace,
   `bound_pipeline_path`, mode 0600) and persist only that copy's sha256 hex digest as the Lead's
   `pipeline` setting -- never the operator's original path, which can drift or disappear -- and
   audit `pod.config`. `effective_pipeline` **MUST** re-read that copy and verify it still hashes
   to the stored digest on every resolution; a missing or unreadable copy, a hash mismatch, or a
   copy that no longer validates **MUST** raise `DispatchError` naming the reason and the rebind
   command -- fail loud, never a silent fall back to the blueprint or built-in pipeline.
   `unset pipeline` **MUST** clear the stored digest (falling back to requirement 1's blueprint or
   built-in resolution) and **SHOULD** best-effort remove the stored copy, never failing the unset
   if that removal fails. `docket pod plan` **MUST** name its resolved source: `file '<path>'` for
   `--pipeline <file>`, `bound pipeline (hash <first 12 hex>...)`, `blueprint '<name>'`, or
   `built-in default`.
7. **Pipeline per task.** A claimed task that carries a `pipeline` name (a string,
   `^[a-z0-9][a-z0-9._-]*$`; a name with a path separator never reaches the filesystem) **MUST**
   run that pipeline instead of the pod's effective one, resolved once at claim: first
   `<pod config dir>/pipelines/<name>.yaml` (or `.yml`), source `pod:<name>`; then a recipe
   directory of that name (the operator's `recipes/` before the shipped ones) holding a
   `pipeline.yaml`, source `recipe:<name>`; otherwise the task is refused. A task with no
   `pipeline`, claimed under a caller-supplied file (`docket run --pipeline <file>`), runs that
   file, records source `file` and **MUST** keep the file's spec on the task as `pipelineSpec`;
   an answer to a question it parks, and a later claim of it with no file, run that kept spec,
   never the pod's; a later claim under a file runs that file and keeps it instead. A task with neither runs the default and records source
   `default`. A chosen pipeline is
   caller-supplied-like: it is never patched with the pod's `maxReworkCycles`, and its variables
   are resolved per task as the default's are. A name that resolves to nothing, a file that does
   not validate, unresolved step variables, or a task `gate` that cannot be built **MUST** settle
   the claimed task `failed` with `failureKind: "pipeline"` and the reason, before any hop and with
   no hop recorded, and emit one `dispatch_refused` trace event naming the reason; the dispatch
   loop then continues to the next task. `pipeline` is not in `RESUMABLE_FAILURE_KINDS`:
   `--resume` does not reclaim it. The claim records `pipelineSource` on the task.

### Per-hop execution

1. Each hop **MUST** be one real agent turn via the `RuntimeDriver` port's `run_turn`. With no
   injected runner, dispatch calls `default_driver().run_turn` (`DocketDriver`); dispatch never
   simulates or skips a turn to save usage. `DocketDriver` reports measured tokens but no USD
   cost, as specified under "Runtime driver resolution" below.
2. The message handed to each role **MUST** thread prior hops' output so a later role sees what
   earlier roles produced, subject to the per-role token budget (see "Bounded hop prompts" below);
   the Reviewer's message additionally states their required verdict-marker reply
   convention verbatim, and a non-Implementer verdict-gated hop with a task worktree is reminded
   that its final message must end with the marker as its last line.
3. An **Implementer** hop with an allocated pod port range (`portRangeStart` set) **MUST** receive
   `DOCKET_PORT_BASE`, `DOCKET_PORT_COUNT`, and `DOCKET_SCRATCH_DIR` in its tool subprocesses' real
   environment (layered on top of the parent environment, which is never mutated). Every other hop
   (Lead, Reviewer, or an Implementer with no allocation) **MUST** receive no such override.
   See `docket-meta.spec.md` for the fields themselves.
   A **jailed** command (a hop's `bash`, a `verifyCmd`, a gate command or a `run:` step, with a
   sandbox backend resolved for it) **MUST** additionally run with `HOME`, `XDG_CACHE_HOME`,
   `XDG_CONFIG_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR` and `npm_config_cache` all set to the pod's
   cache directory (mode 0700, created beside the scratch directory at provisioning), and that
   directory **MUST** be a read-write root of the jail; the file tools' roots are unchanged. An
   unjailed command never has its `HOME` redirected. The `GIT_AUTHOR_*`/`GIT_COMMITTER_*` identity
   comes from the variables dispatch sets, not from `HOME`.
4. Every hop **MUST** emit a `context_composed` event (the composed prompt's byte accounting -- see
   "Bounded hop prompts"), a `tool_call` hop marker and a `hop_started` event before the turn, and
   a `tool_result` (on success) or `error` (on failure) event after it; a nonzero-cost turn **MUST**
   additionally emit a `cost_charged` event.
5. A planned unit whose pipeline step declared its own `model` (`pipeline-format.spec.md`'s
   "Steps" Requirement 10) **MUST** run that hop on the resolved model instead of the target agent's
   own role-policy model -- resolution (`cheap`/`strong` via the live rank anchors, else the literal
   id as given) is `model-profiles.spec.md`'s "Where a member's model comes from". This resolution
   **MUST** happen once per hop and **MUST NOT** write `.docket-meta.json`: the member's own
   persisted `model` is unchanged before, during and after the hop, so `docket pod show` keeps
   reporting the agent's standing model, never the step's transient override. The override reaches
   only the production `RuntimeDriver.run_turn` call; an injected five-argument runner runs its own
   agent's configured model. A step `model` that does not resolve refuses the task
   (`dispatch_refused`). A step `model` literal whose provider is absent from the provider catalog
   **MUST** be a `docket pod validate`/`docket pod plan` error naming the step, the same "caught
   before dispatch" posture an unresolvable `role`/`agent` target gets.
6. Every trace event the turn loop writes for a hop (`tool_call`, `tool_result`, `llm_call`,
   `session_compaction`, `request_fit`, `budget_warning`) **MUST** carry `task_id` equal to the
   claimed task's id, threaded from dispatch's single `run_turn` call (`trace_task_id`;
   `trace-store.spec.md`). The events dispatch writes itself (`session_start`, `session_end`,
   `context_composed`, the hop's `tool_call` marker, `hop_started`/`hop_finished`, gate, route and
   refusal events) carry no `task_id`, except `prepare`.
7. A task's `restrictions` (operator-api.spec.md "Arguments") **MUST** narrow every hop of that
   task: dispatch hands the denied tools, the `none` network and the block-only policy documents to
   the driver (security-gates.spec.md "Task restrictions"); a policy document that is not valid or
   whose action is not `block` **MUST** refuse the hop before it starts (`dispatch_refused`).
8. A task's `maxTokens` **MUST** bound its counted usage: a hop runs with
   `token_budget = maxTokens - sum(input - cached + output of the task's persisted hops)` (read from
   the queue record so a sibling's or earlier hop's usage counts). A hop that would start with
   `<= 0` left **MUST NOT** run; the task fails with `failureKind: "budget"` and a reason naming the
   cap (`task token budget reached (maxTokens=<n>) before <role>`). A hop the turn loop stops on its
   `token_budget` (`stop_reason == "token_budget"`) under a task `maxTokens` **MUST** fail the task
   with the same `failureKind`. An unset `maxTokens` leaves the turn loop's configured default.

### Step-scoped durable runtime history

1. A pod-dispatch task's audit and trace identity **MUST** be `agent:<project>:<task-id>` for
   `session_start`, every hop and gate event, and `session_end`. History scope **MUST NOT** split one
   task's audit trail into per-step trace files.
2. Each runnable pipeline unit **MUST** use a durable-history key of the form
   `agent:<member-id>:<project>:task:<task-id>:step:<step-id>` (`step_session_key`). Every dynamic
   component **MUST** be UTF-8 percent-encoded as necessary with no delimiter treated as safe,
   making the mapping deterministic and collision-free even when a custom `step_id` contains `:` or
   `/`.
3. The key **MUST** use the resolved pipeline node's globally unique `step_id`, not its role.
   Distinct repeated-role steps and distinct children of a parallel group therefore receive
   distinct histories; a parallel group container receives none because it runs no turn itself.
4. Every retry of one hop, every bounded rework revisit to that node, and a crash `--resume` that
   re-enters that same node **MUST** reuse its exact step-history key. A different step targeting
   the same member **MUST NOT** reuse it.
5. `dispatch_task` **MUST** pass the step-history key as `RuntimeDriver.run_turn`'s ordinary
   `session_key`. On the production `DocketDriver` path it **MUST** additionally pass the project and
   task-wide identity as `trace_project`/`trace_session_key`; an injected five-argument runner
   receives the step-history key.
6. A downstream step's model-visible messages **MUST NOT** replay a previous step's assistant-role
   messages from durable history. Prior cross-step work **MUST** arrive only through the hop
   message's bounded `HandoffArtifact` sections. This does not remove the artifact summary; it
   removes a second raw-history copy of that summary.
7. Dispatch **MUST NOT** delete, rename, or migrate a session file. A member's step histories are
   listed by `DocketDriver.list_sessions(member_id)` because their keys begin with that member's
   namespace.
8. `session_key(project, project_key)` **MUST** keep producing the base scoped key persisted in
   member metadata. It is not the dispatch-history key, and changing pipeline steps **MUST NOT**
   rewrite `.docket-meta.json`.

### Retries and the failure-kind taxonomy

1. Every agent turn's outcome (`TurnResult`) **MUST** carry a `failure_kind` on failure: `timeout`
   (the turn exceeded its timeout), `daemon_error` (the stable label for a runtime or transport
   failure), `nonzero_exit` (an invoked process returned a real non-zero result), `invalid_output`
   (the runtime returned output that could not be used, including a turn stopped on an approval it
   could not get), or `run_cancelled` (the owning run's cancellation signal was observed -- see
   "Cancellation"). A successful turn carries no `failure_kind`. The `daemon_error` spelling is
   persisted API vocabulary; it does not imply an external process dependency.
2. Only `timeout` and `daemon_error` **MUST** be treated as retryable -- a transient hiccup, not a
   real answer. `nonzero_exit` and `invalid_output` (and, separately, a bad Reviewer
   verdict -- see that gate) **MUST NEVER** be retried: retrying a real failure risks masking it
   as transient and burns budget for nothing.
3. A retryable failure **MUST** be retried in place, up to a per-role budget
   (`DISPATCH_RETRIES_PER_ROLE`, default 2 additional attempts -- 3 total tries -- for each of the
   four built-in roles, each overridable via `DISPATCH_RETRIES_<ROLE>`; any other role uses
   `DISPATCH_RETRIES_DEFAULT`, default 2). The sleep before retry attempt N **MUST** be
   `min(max(DISPATCH_RETRY_BACKOFF_S * N, retryAfter), DISPATCH_RETRY_MAX_WAIT_S)` seconds
   (`DISPATCH_RETRY_BACKOFF_S` default base 2s, `DISPATCH_RETRY_MAX_WAIT_S` default ceiling 60s),
   where `retryAfter` is the failing attempt's endpoint-reported `Retry-After` in seconds
   (`TurnResult.retry_after_s`) when the failure came from a retryable HTTP status, else `0` -- so a
   linear backoff still applies when the endpoint names no wait, and an endpoint's requested wait
   still yields to the ceiling rather than sleeping unbounded. Exhausting the retry budget **MUST**
   fall through to the same failed-hop handling as a non-retryable failure.
4. The **total number of tries made** for a hop (1 if it succeeded or failed non-retryably on the
   first attempt; more only for a retried hop) **MUST** be persisted on that hop's record as
   `attempts`.
5. Every retry attempt (before its backoff sleep) **MUST** emit a `hop_retry` trace event naming
   the attempt number, the role, the retry budget, the failure kind that triggered it, the error,
   and the `retry_after_s` value that failure carried (`null` when the endpoint named none) -- and
   **MUST** refresh the task's `claimedAt` (see "Per-hop incremental persistence") before sleeping,
   so a long retry loop is never swept as a stale claim by a concurrent dispatcher.

### Timeout configuration

1. The agent-turn timeout and the verify-command timeout **MUST** be independently configurable --
   `turnTimeoutS` and `verifyTimeoutS` respectively, both optional pod settings stored on the pod
   Lead's `.docket-meta.json` (see `docket-meta.spec.md`).
2. Resolution order for a given dispatch invocation, highest precedence first: (a) an explicit
   override passed to that invocation -- `docket run --timeout <seconds>` for a CLI-triggered run
   or the MCP dispatch tool's `timeout` (each overrides **both** the turn and verify timeout for that
   run), or the process-wide `DISPATCH_TURN_TIMEOUT_S`/`DISPATCH_VERIFY_TIMEOUT_S` environment
   config for a run `docket start` triggers (webhook, due schedule, or the sweep); (b) the pod
   Lead's own `turnTimeoutS`/`verifyTimeoutS`; (c) `DEFAULT_TIMEOUT` (300 seconds) as the fallback
   of last resort.
3. When `docket start`'s process-wide timeout variables are set, they take the "explicit override"
   slot for every pod that server instance dispatches (webhook, schedule, sweep) -- for those runs
   they are resolved *before* that pod's own setting is consulted, not layered beneath it. A
   CLI-triggered `docket run` (no `--timeout`) is unaffected by the server-wide variables; it
   resolves straight to the pod's setting, then `DEFAULT_TIMEOUT`.

### Pod dispatch settings (`PodSettings`)

1. Every pod setting (`PodSettings.KEYS`: `budgetUsd`, `maxReworkCycles`, `turnTimeoutS`,
   `verifyTimeoutS`, `approvalMode`, `approvalExpiryHours`, `inputExpiryHours`, `allowCommands`,
   `pipeline`, `schedule`, `projectInstructions`, `mcpServers`, `deniedTools`, `requireVerify`,
   `maxConsultationsPerTask`, `consultMode`, `network`, `profile`, `readOnly`, `prepare`, `protects`) **MUST** be
   read through one typed, validated model (`PodSettings.load_for`), not independent ad hoc
   parsers. A missing or blank stored key resolves to that field's declared default (e.g. `0.0`,
   `1`, `None`, `None` for `budgetUsd`, `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS`); a
   *present but malformed* stored value (e.g. a hand-edited `.docket-meta.json` with
   `"turnTimeoutS": "abc"`) **MUST** raise, naming the key and the reason, and **MUST NOT** be
   silently replaced by the default. Every dispatch reader of a pod setting (`pod_budget`,
   `pod_max_rework_cycles`, `pod_turn_timeout`, `pod_verify_timeout`, ...) lets that refusal
   propagate as a `DispatchError` rather than catching it.
2. `docket pod show [--json]`, `docket pod set <key> <value>` and `docket pod unset <key>` are the
   CLI surface for these keys -- see `cli-json-shapes.spec.md` for the `show --json` shape. `set`
   validates (`PodSettings.coerce`) before writing and persists through the same meta writer every
   other pod-meta setter uses (`meta_set`); an invalid value or an unknown key exits 1 with the
   stored settings untouched, and a recorded key (`configSource`, `configDigest`, `exporters`) is
   refused as written by `docket pod update`, not by `set`. `unset` clears an override by writing
   `null` (read back as absent), falling back to the field's default. Every write is audit-logged as
   `pod.config`. `docket pod set budgetUsd <usd>` persists `budgetUsd` as the validated number, not
   the raw CLI argument string; any `set` or `unset` of `budgetUsd`, whatever the value, re-queues
   the pod's blocked tasks (`unblock_pod`) and clears the Lead's `paused`/`pausedReason`. The line
   it prints counts every task `unblock_pod` re-queued, whatever its `blockedReason`:
   `Unblocked <n> blocked task(s)`. `docket pod set maxReworkCycles` on a pod with a bound pipeline
   **MUST** be refused with exit 2 and the stored settings untouched, the message
   (`REWORK_BOUND_BY_PIPELINE`) naming the pipeline's own bound, `on: {<label>: {goto: <step>,
   max: <n>}}`: a bound pipeline is never patched with the pod's `maxReworkCycles`, so the setting
   would be accepted and ignored. The other order is refused the same way: `docket pod set pipeline`
   on a pod that stores a `maxReworkCycles` **MUST** exit 2, bind nothing, and name `docket pod
   unset maxReworkCycles`. `unset` is always allowed. `docket pod show` reports a bound
   pod's `maxReworkCycles` with source `pipeline` and, as its value, the bounds the pipeline itself
   carries (`<step>:<max>` comma-joined, `none` when it has none).
3. `approvalMode` (`"wait"` | `"park"` | `"refuse"`, field default `"wait"`) is a setting on the
   same model (`PodSettings.approval_mode`), writable through the same `show`/`set`/`unset` surface.
   A present-but-invalid stored value (anything other than the three literals) raises exactly like a
   malformed numeric setting -- naming the key -- and refuses dispatch rather than defaulting to
   `"wait"`. The read path's message is `<key>: invalid stored value <v!r> (<rule>)`; the `set`
   path's is `<key>: invalid value <v!r> (<rule>)`. "Unset" (no `approvalMode` key at all in the
   Lead's stored settings, `pod_approval_mode_is_set`) is a distinct state from a stored `"wait"` --
   see "Parked approvals" below for what it resolves to. `approvalExpiryHours` (int `>= 1`, default
   `24`) and `inputExpiryHours` (int `>= 1`, default `72`) are two further keys on the same model,
   likewise writable through `docket pod set`/`unset`; `inputExpiryHours` is the default deadline of
   every parked question: when a question's escalation is opened, `expiresAt` is stamped (now plus
   the hours) on a question that has none. An `input` step's own `expiresHours` wins and is never
   overwritten. Expiry blocks the task `input_expired` (operator-loop.spec.md area 7), never
   `failed`.
4. `PodSettings` also carries `pipeline` (`str | None`, a 64-character lowercase hex sha256 digest):
   the hash of this pod's bound pipeline copy (`bound_pipeline_path`), or unset. Unlike the scalar
   keys, `docket pod set pipeline <file>` is a dedicated CLI path that reads *file*, validates and
   plans it, writes the docket-owned copy, and only then persists its digest through `meta_set`.
   See "Pipeline order and participation" requirement 6 for the full validate-plan-store-verify
   contract.
5. `PodSettings` also carries `schedule` (`str | None`): an `@every`/`HH:MM`/cron spec (see
   "Schedule configuration and doctor visibility" below), validated through the same `coerce` path
   every scalar key uses -- an unrecognized spec raises `PodSettingsError` naming the key and the
   reason `describe_spec_error` gives, refusing the write rather than storing or silently ignoring
   it. `set schedule <spec>` is a dedicated CLI path that, after validating, persists *spec* into
   `docket-schedules.json`'s `schedules[project]` through `set_schedule` (the schedule's real
   source of truth for the server's sweep) and mirrors the same string into the Lead's settings so
   `docket pod show` can display it through the same `value_and_source` path every other setting
   uses. `unset schedule` clears both.
6. `PodSettings` also carries `projectInstructions` (`tuple[str, ...]`, comma-joined in storage like
   `allowCommands`): relative paths inside this pod's codebase root that the opt-in
   project-instructions section composes into a live turn's system prompt right after
   `INSTRUCTIONS.md` (see `agent-loop.spec.md`) -- the AGENTS.md/CLAUDE.md convention, never
   auto-discovered, unset by default. `set projectInstructions <paths>` goes through the generic
   `coerce`-then-`meta_set` path. Its `coerce` validator refuses an absolute path, a home-relative
   (`~`) path, a path with a NUL byte, or any path containing a `..` segment, naming the offending
   path, because those are the only shapes that could resolve outside the codebase root once joined
   against it; the check is purely syntactic (no filesystem access), so it fires at `set` even
   before this pod has a resolved codebase root.
7. `PodSettings` also carries `mcpServers` (`tuple[str, ...] | None`, `None` by default): this pod's
   selection from the MCP server catalog. `None` means "every configured server". Written through
   the generic `coerce`-then-`meta_set` path. Unlike `allowCommands`/`projectInstructions`, its
   validator is **not** purely syntactic -- it checks every comma-separated name against the *live*
   catalog (the global servers plus this pod's own pod-scoped servers), at `set` time and on every
   later read alike, raising `PodSettingsError` naming the first unrecognized name (and naming the
   owning pod when the name is another pod's server). Because this re-check runs on every read, a
   selection that was valid when written but has since been renamed or removed surfaces the next
   time this pod's settings are read -- see `mcp-client.spec.md`'s "Pod-scoped server selection"
   for how the driver turns that `PodSettingsError` into a `DispatchError` naming the stale
   selection, refusing the dispatch rather than loading a subset or none of the servers.
8. `PodSettings` also carries `deniedTools` (`tuple[str, ...]`, comma-joined in storage, empty by
   default): built-in tool names (the `BUILTIN_TOOL_KINDS` universe) this pod's *every* role
   additionally denies, on top of each role's own archetype-declared `denied_tools`. Written
   through the generic `coerce`-then-`meta_set` path; its validator refuses a name outside that
   universe, naming it. See `role-archetypes.spec.md`'s "Per-role tool sets" for how
   `registry_for_role` unions this setting with the role's own denylist before narrowing -- a
   pod-level denial reaches every role in it. Unlike `mcpServers`, unreadable or malformed stored
   settings degrade here to "no additional pod-level denial" rather than raising, because
   `BUILTIN_TOOL_KINDS` is a fixed set and `registry_for_role` runs on every turn's live path, which
   must never crash over a hand-edited meta file.
9. `PodSettings` also carries `network` (`none`|`open`, default `open`; any other value is refused
   at `set`). `none` cuts the network of this pod's jailed tool calls; it only narrows the global
   `docket setup sandbox network` mode (a pod `open` under a global `none` stays `none`), via
   `effective_network`, which `DocketDriver` reads each turn; unreadable pod settings fail closed to
   `none`. See `security-gates.spec.md` "Network egress".
10. `PodSettings` also carries `prepare` (`str`, `""` by default, at most 1,000 characters, no NUL
    or newline): the install command a pod's tasks run in a fresh worktree, or `none` to turn
    preparation off (see "Task preparation"). Written by `pod.yaml`'s top-level `prepare:` (never
    inside `settings`, like `pipeline`; a blank value means `none`) or by `docket pod set prepare`
    through the generic `coerce`-then-`meta_set` path. `""` is unset: the lockfile decides.
11. `PodSettings` also carries `protects` (a comma-joined list of glob patterns in storage, `()` by
    default): the paths a task may not change without a person ("A change that edits its own
    check"). It adds to the defaults and never removes one. Written by `pod.yaml`'s top-level
    `protects:` list (never inside `settings`) or by `docket pod set protects`. A pattern is a
    non-empty repository-relative glob of at most 200 characters with no comma, NUL, newline,
    leading `/` or `..` segment; at most 50.

### Schedule configuration and doctor visibility

1. Reading schedules is tolerant by design: `load_schedules`/`load_last_run` return `{}` on any read
   or parse error, `is_schedule_due` treats an unrecognized spec as never due, and the model-policy
   and archetype registries (see `model-profiles.spec.md`, `role-archetypes.spec.md`) skip a
   malformed entry. None of these crashes the sweep or a live fleet; requirements 2-4 make each case
   visible to an operator instead of silent.
2. `docket pod set schedule "<spec>"` **MUST** validate *spec* (rejecting an unrecognized
   `@every`/`HH:MM`/cron string with exit 1 and the settings untouched, same as every other
   setting) and, on success, persist it into `docket-schedules.json` via `set_schedule`.
   `unset schedule` **MUST** remove the project's entry via `unset_schedule`, leaving `lastRun`
   as-is. Both go through a locked read-modify-write, never a direct file write.
3. `docket setup` **MUST** run a read-only check over `docket-schedules.json`
   (`find_schedule_problems`) and report every entry that `is_schedule_due` would silently treat as
   never-due, or an unreadable or malformed file itself -- naming the file, the project key, and the
   reason. It never edits the file.
4. The `docket start --dispatch` sweep **MUST** print one line naming the project and reason
   (`[serve] sweep: schedule '<project>' skipped — <reason>`) for each schedule entry
   `describe_spec_error` rejects, once per sweep pass, instead of falling through to
   `is_schedule_due`'s silent skip. This is diagnostic output only -- the schedule is not fired, and
   no failure kind, trace event, or task status is involved.
5. The schedule spec vocabulary is `@every`, `HH:MM` and 5-field cron; validation only makes an
   unrecognized spec loud, it adds no format.

### Routines (ADR 0036)

A routine is a pod's own standing order: on a schedule the service enqueues a task, so a pod
works with nobody adding one. It is separate from `docket pod set schedule`, which only
dispatches the queue that already exists and is unchanged.

1. A routine **MUST** be a `kind: routine` document (config-format.spec.md "The `routine` kind")
   resolved by name from `Home.scopes("routines", pod)`: the pod's overlay `routines/` directory,
   then the operator's `config/routines/`. The nearer scope wins a name. `docket pod update` writes a
   recipe's `routines/*.yaml` byte-for-byte into the pod overlay, as it does a named pipeline. A file
   that does not load is ignored by the sweep and reported by `docket pod routine list` and
   `docket pod validate`. A routine with `enabled: false` never fires.
2. Slots are evaluated in the routine's `tz` (an IANA name, default `UTC`) on the kernel clock.
   A cron `schedule` has a slot at every local minute its five fields match; a local time that
   does not exist that day (the clock jumped over it) has no slot, and one that occurs twice
   (the clock fell back) has one slot, the first. `0 9 * * 1-5` in `Europe/Madrid` is therefore 09:00
   local before and after a change of offset. `@every <N><s|m|h>` has a slot every N seconds, the
   first at the moment the service first sees the routine. `HH:MM` is not accepted. The due slots
   of a routine are those after the last fired (or first seen) moment up to now; at most the last
   31 days are examined.
3. The first sighting of a routine **MUST** record `seen` (now) and fire nothing for a cron
   `schedule`: history is never replayed. When several slots are due at once, `catchUp: skip` (the
   default) **MUST** fire the latest only and drop the earlier; `catchUp: once` **MUST** fire one task
   for all of them: the same latest slot, with `(catch-up: N scheduled runs were missed; this one
   run stands for all of them)` appended to the task's description. Either way every due slot is
   consumed, so the next tick sees none of them.
4. A fire **MUST** be `enqueue_task_once(pod, description, priority, channel="routine",
   idempotency_key="routine:<name>:<slot>", pipeline=..., variables=...)`, where `<slot>` is the
   slot in UTC as `YYYY-MM-DDTHH:MM:SSZ`: the task carries the document's `task.description`,
   `task.priority` (default `normal`), `task.pipeline` and `task.variables`, and two fires of one
   slot create one task. The enqueue audits `task.enqueue` with `channel=routine`, and the fire
   also audits `routine.fire` naming the pod, the routine, the slot and the task id.
5. `overlap: skip` (the default) **MUST** fire nothing while a task of the same routine (an
   idempotency key starting `routine:<name>:`) is not terminal, so `pending`, `running`, `blocked`
   and every `waiting_*` status all hold it; `overlap: queue` fires regardless. A slot that is not
   fired because of overlap, or because its enqueue was refused, is consumed and **MUST** append a
   `step_skipped` trace event to the session `routine:<pod>:<name>` with the payload `{routine,
   slot, reason}`, reason `overlap` or `refused: <why>`; so does a `catchUp: skip` that dropped
   earlier slots, reason `missed N earlier slot(s)`, beside the fire.
6. The last fired slot and the first-seen moment per pod and routine **MUST** persist in
   `Home.routines_state_file` (`state/docket-routines.json`, written only through `platform/store.py`), updated after the enqueue,
   so a restart does not fire a slot again, and a crash between the enqueue and the update fires
   it again as the same key, hence once. A slot older than the saved one is never fired.
7. `fire_due(now=None)` in `tasks/application/routines.py` **MUST** do the above for every
   dispatchable pod and return the task ids it created. The `docket start --dispatch` sweep calls
   it once per pass, in `check_schedules`, before it checks schedules; a failure is reported on
   the sweep's own line and never stops the sweep. `docket run` and a service without `--dispatch`
   **MUST NOT** fire routines: firing needs the service, and precision is the sweep interval.
8. `docket pod routine list [--json]` **MUST** print, per routine in the pod's scopes, its name,
   schedule, tz, next slot, last fired slot and whether it is enabled, and read nothing it could
   change (cli-interface.spec.md "docket pod").

### Unattended approval posture (`approvalMode`)

1. Under `"wait"`, a hop that hits an `ask` policy verdict with nobody able to answer blocks that
   hop for up to `TOOL_APPROVAL_TIMEOUT` (120s, see `security-gates.spec.md`) per gated call;
   `approvalMode` lets a pod that runs unattended choose another posture.
2. For every hop, dispatch **MUST** resolve `pod_approval_mode(project, caller_default=...)` and,
   when the resolved mode is `"refuse"` or `"park"`, set `DOCKET_APPROVAL_MODE` to that value in
   that hop's tool environment -- merged into whatever environment the hop already carries (e.g. an
   Implementer's `DOCKET_PORT_*`/`DOCKET_SCRATCH_DIR`, or a downstream hop's worktree coordinate),
   never replacing it. This is an internal dispatch-to-driver coordinate: `DocketDriver.run_turn`
   pops it out of the tool environment before building the tool context, so it is never a real
   tool-visible environment variable, and maps it onto `ToolContext.approval_mode`
   (`security-gates.spec.md`). See "Parked approvals" below for `caller_default`'s resolution and
   for `park`'s own behaviour.
3. Under `"wait"`, no approval-mode key is added to a hop's environment.
4. Under `"refuse"`, a gated call inside that hop ends immediately with the `approval_unavailable`
   denial (no approval record created, no wait), the agent loop stops on
   `stop_reason="approval_unavailable"`, and the hop's `TurnResult` comes back `ok=False` with
   `failure_kind="invalid_output"` and `error` naming the tool, call id and policy
   (`approval_unavailable_error`). Dispatch's ordinary hop-failure path then fails the task with
   reason `"<role> hop failed: approval_unavailable: ..."`, traces it as an `error` event, and never
   retries it (`invalid_output` is not retryable).
5. Dispatch does not detect whether an approval channel is live before resolving the mode; the
   mode is configuration, not a probe.

### Parked approvals (`approvalMode: "park"`, ADR 0016)

1. The `docket start --dispatch` sweep runs each pod on its own worker (see "Sweep workers"); a hop
   waiting on an `ask` under `"wait"` would hold that worker for up to `TOOL_APPROVAL_TIMEOUT`.
   `"park"` defers the call to a human instead, without losing it the way `"refuse"` does.
2. **Caller-scoped default.** An *unset* pod `approvalMode` (no key at all in the Lead's stored
   settings -- `pod_approval_mode_is_set`) resolves through the caller's own `caller_default`: the
   sweep passes `"park"`; `docket run` passes `"wait"` when standard input is a real TTY, else
   `"park"`; every other caller (the webhook, a due schedule, the MCP dispatch tool) passes nothing,
   so `dispatch_pod`'s default `"wait"` applies. An explicit stored `approvalMode` (including an
   explicit `"wait"`) always wins over the caller's default.
3. **The park itself.** Under a resolved `"park"`, dispatch sets `DOCKET_APPROVAL_MODE=park` in the
   hop's tool environment (`ToolContext.approval_mode`). An `ask` verdict there records the exact
   call (tool name plus a canonical-JSON argument digest) and the task position, creates an approval
   record with `context.parked = true`, and ends the turn on `stop_reason="approval_parked"` -- the
   agent loop's `error` string carries the token in the same `key=value` shape
   `approval_unavailable_error` uses (`approval_parked_error`). The persisted hop's `error`, the
   task's `reason` and the trace withhold that `approval_token=` pair: they name the pause by its
   escalation, never by the token behind it.
4. **From denial to a durable park.** Dispatch parses that token back out of the hop's
   `TurnResult.error`, failing closed -- an unparseable token falls through to an ordinary `failed`
   outcome, never a silent forever-wait. When found, the hop is persisted with `parked: true` (a
   boolean on the persisted hop record, `false` otherwise) **before** the crash-safety `on_hop`
   callback runs, and the unit outcome is the same `waiting_approval` shape the pre-hop
   `require_approval` gate produces, carrying this hop's own pipeline index -- see "Task status
   vocabulary" item 6. The event traced is `approval_required`: "a require_approval-equivalent gate
   fired; task -> waiting_approval", whichever of the two triggers fired it. A parked token that
   belongs to a `consult` question instead parks the task `waiting_input` (operator-loop.spec.md);
   under a resolved `"wait"` (a TTY `docket run`) a `consult` does not park, it waits in the turn
   for the person at that terminal (operator-loop.spec.md "Consult" item 3).
5. **Expiry.** Under a resolved `"park"`, dispatch also sets `DOCKET_APPROVAL_EXPIRES_AT` (ISO UTC,
   `now + approvalExpiryHours`, computed fresh per hop); the tool gate stamps this onto the parked
   record's own `expiresAt`, which `sweep_escalations`'s fail-closed deadline logic prefers over
   the generic `APPROVAL_TIMEOUT`. Past that deadline the sweep resolves the record to **denied**,
   and the waiting task fails exactly as an explicit human deny does
   (`failureKind: "approval_denied"`).
6. **Resume at the same index.** Resume treats a `hop.parked` entry as an attempt, not a decided
   outcome: it neither advances past it nor evaluates it as a rework or route target, and sets the
   resume position to that hop's own index -- re-running the exact step rather than the one after it.
   The step id may then appear more than once in the task's persisted `hops` (the parked attempt,
   then the real one), the same "each attempt is its own audit record" shape a rework cycle's
   repeated Reviewer hop has. This is not the pre-hop gate's skipped position: that skips a gate
   check at a position no hop was attempted at, and a granted parked approval never names one.
7. **Single-use pre-grant on resume.** The grant of a record whose context carries `parked: true`
   only reopens the task `pending`; the granted record itself, whose context names the task, the
   tool and the call's `argsDigest`, is the pre-grant. Dispatch reads the task's unspent pre-grants
   (granted approval records naming the task, not yet consumed) from the approval store and
   serialises them as JSON `{token, tool, argsDigest}` into `DOCKET_PREGRANTS` on every hop it
   composes for that task; the tool gate's pre-grant matcher consumes at most one entry per exact
   `(tool, argsDigest)` match, so the re-run hop's identical call passes once without asking
   again, and anything else still asks. A grant that chose `approve_task` is also a task-wide
   grant (at most `TASK_GRANT_CAP`, 20, per task; audited `approval.task_grant`, or
   `approval.task_grant_refused` past the cap, in which case the call is approved once only), from
   which dispatch mints one single-use pre-grant per grant for each later hop of the same role
   (operator-loop.spec.md). A pre-grant minted that way is marked as such and is never read as a
   grant of its own. The task keeps none of this: its terminal status ends its grants.
8. **Denial.** The denial of a parked record behaves exactly like a pre-hop gate's deny: the task moves straight to `failed`, `failureKind: "approval_denied"`,
   never reclaimable by `--resume`.
9. A re-run hop is a new turn sharing the same durable step history; the granted call's result is
   not injected into the turn that parked.

### Pre-grants from intake (ADR 0016)

1. A pre-grant can be recorded before any hop runs, for a command a Lead brief's
   `expectedRiskyActions` (see "Task brief" below) names, so the task is not interrupted for it
   later.
2. `record_pregrant(project, task_id, command, *, tool="bash", channel, actor)` is the write side,
   callable ahead of any dispatch: it looks *task_id* up in the pod's queue (refusing one from
   another pod with `InterruptionsError`), collapses whitespace in *command*, and computes
   `canonical_args_digest(tool, {"command": normalized})` -- the exact digest the tool gate's park
   and consume matcher computes for a live call. It then calls `create_pregrant(project,
   "implementer", tool, digest, task_id=task_id, expires_at=<now + this pod's approvalExpiryHours>,
   channel=channel, actor=actor)`.
3. The record is the pre-grant: it names the task in its context, so dispatch reads it from the
   approval store like the grant of a parked call ("Parked approvals" item 7) and serialises it
   into `DOCKET_PREGRANTS` on that task's very first hop, not only a re-run after a park. A command pre-granted this way that never runs,
   or runs with different arguments, is never consumed -- it expires by the same
   `approvalExpiryHours` deadline like any other pre-grant, with no other effect on the task.
4. This writer produces the same record shape a live grant leaves; the matcher and
   `create_pregrant` consume it unchanged. See operator-loop.spec.md, "Seeing it coming, and not
   being interrupted twice", for the CLI/HTTP/MCP surface and the forecast this pairs with.

### Operator input steps and answers (ADR 0016)

1. When the pipeline reaches a planned unit whose `input` is set (see pipeline-format.spec.md,
   "Operator input steps"), dispatch **MUST** run no agent turn: it mints a `Question`
   (MCP-elicitation-shaped) from the step's `from:` source, opens the `input` escalation that
   carries it, and returns a `waiting_input` outcome with reason `awaiting operator answer for
   step '<id>' (escalation=<id>)`. No hop is persisted for this attempt -- the same posture the
   pre-hop `require_approval` gate's `waiting_approval` has. The task lists the escalation and
   keeps no copy of the question. When the `from` step's latest hop holds a gate that did not pass, the question's message
   **MUST** append that gate's report (its screened reasons, else its redacted output tail) under
   `The gate on step '<from>' reported:`, so the operator decides on what the verifier saw.
2. **The question's schema.** A generic `input` step (no Lead intake brief attached) asks a single
   free-text property: `{"type": "object", "properties": {"answer": {"type": "string"}},
   "required": ["answer"]}`. A brief with questions gets a richer schema ("Task brief"
   requirement 5).
3. **Resolution.** An answer is received in two steps. `resolve` (operator-loop.spec.md area 10)
   validates *content* against the question's schema (`validate_answer`), screens every string
   value in *content* through `pre_input` as untrusted Lead input -- a `block` action writes
   nothing -- records the answer as the escalation's `resolution` and reopens the task `pending`;
   it resolves no pipeline and takes the pod's task-list lock only for that one status change. The next **claim** applies the answer: before the task's resume position is
   computed, dispatch reads the escalations the task lists (`escalations`) and, for each `input`
   record in state `resolved` whose `resolution.appliedAt` is unset, resolves the step's own `on:`
   route (`answered` for `accept`, `declined` for `decline`/`cancel`) the way a live hop's route
   is resolved, minus the tracing. The parked position is located by the record's own `step`
   against the pipeline the claimed task runs with (requirement 1 of "Pipeline order and
   participation"); a position that no longer names that step fails the task `dispatch_refused`
   (an answer is accepted by `resolve` without that check, so this is where a stale one is
   refused).
   Only then is `appliedAt` stamped, so a crash between the two leaves the record to be applied
   again and the application is idempotent (item 4). A record in state `expired` or `decided` is
   never applied. Every string
   value screened is caller-supplied answer content, never the question text itself.
4. **The synthetic hop.** An applied answer persists one `HopResult(role="operator",
   member_id="operator", step_id=<the input step's id>, ok=True, output="answered:
   <escalation id>", next_step=<the resolved route target, or None for an ordinary advance>)`. Its
   `artifact.verdict` is set to the outcome label (`"answered"`/`"declined"`) -- not a real verdict
   marker, but the same field resume's route-count rebuild keys a backward or self route by; a plain
   `HandoffArtifact.from_output` fallback would leave `verdict` `None` there and mis-key every
   reconstructed route as `"fail"`. The claim persists it inside the pod's task-list lock and only
   when the task's hops hold no operator hop for that step and escalation already, so a task claimed
   twice (a crash, a `stale_claim` reclaim) gains one hop, not two.
5. **Terminal routes settle at the claim.** A route resolving to `"fail"` (or an `on:` target that
   names no known step id, or a backward route whose cap is exhausted) settles the task `failed`;
   one resolving to `"stop"` settles it `done` -- both by the claim that applies the answer, which
   persists the synthetic hop and returns that result without running a hop (`session_start` and
   `session_end` are traced around it, `completedAt` is set by the ordinary finalisation). Until
   that claim the task is `pending`. Any other target (or no `on:` entry for the label at all)
   leaves the task running its pipeline from the synthetic hop's `next_step`.
6. **Resume.** Resume treats the synthetic `operator` hop like any other routed hop: `hop.next_step`
   (when it names a known step id) becomes the resume position, bumping the route count keyed by
   `(step_id, hop.artifact.verdict)` when the target is backward or self. A cap exhausted by that
   rebuild settles the task `failed` at the claim that would have routed backward again.
7. **The Lead's next hop.** The Lead's hop message appends `\n\n## Operator answers\n` followed by
   one `Q: <message>\nA: <rendered content>` block per resolved `consult` or `input` escalation
   the task lists (`answers_of`), oldest first, capped
   near 4,000 characters with the context compiler's truncation marker (never silently cut). `A:`
   renders an `accept`'s single `answer` property value directly (other accepted content as sorted
   JSON), else `(declined)`/`(cancelled)`/`(no answer)`.
8. **Expiry.** `sweep_escalations`, run on every `docket start` sweep,, moves a `waiting_input` task whose question's `expiresAt` has passed to
   `blocked`/`blockedReason: "input_expired"` and writes `escalation_expired` -- never `failed`. No hop
   was persisted for the parked attempt, so `retry_task`/`unblock_pod` reopening it to `pending`
   sends the next claim straight back to the same `input` step, which mints a new `Question`.

### Wait steps (ADR 0036)

1. **The pause.** When the pipeline reaches a planned unit whose `wait` is set (pipeline-format.spec.md,
   "Wait steps") and its `when` holds, dispatch **MUST** run no agent turn. With `until`, the probe
   command first passes the guard of a `run:` step ("Conditional steps and command steps" item 2): it
   is classified, a non-`allow` verdict fails the step under `approvalMode: "refuse"` and otherwise
   gates like a pipeline `approval` step at this pipeline position, and a task at a level that denies
   approvals fails it `needs_human`. Then it opens the step's `wait` escalation (operator-loop.spec.md
   area 11: `policy` `machine`, one option `resume`, `expiresAt` the due time, `onExpiry` `block`),
   writes the task's `wait` (item 2) and returns a `waiting_input` outcome with reason `waiting until
   <due> at step '<id>' (escalation=<id>)`. No hop is persisted for the attempt and no
   `escalation_asked` is traced, because nobody is asked.
2. **The task's wait.** `TaskRecord.wait` (key `wait`, absent while the task waits on no step) is
   `{step, dueAt, until?, everyS?, nextProbeAt?, probes, routed, outcome?}`: the step id, the due
   time (park time plus the step's `wait`), the probe command and interval, the next probe time
   (park time plus `every`), how many probes ran, whether the step declares `on.timeout`, and, once
   the task is woken, the `outcome` (`resumed` or `timeout`). It is written only through the task
   store, with the status change that parks the task, and **MUST** be removed by every move to
   `blocked`, `done`, `failed` or `cancelled` (`state.decide`); a move to `pending` or `running`
   keeps it, because the claim still has to apply `outcome`.
3. **The tick.** `sweep_waits(now, pod=None, probe=None)` (`tasks/application/escalation_sweep.py`)
   visits every `pending` `wait` escalation whose task is `waiting_input` on it (a record whose pause
   already ended is settled `expired` with no side effect). `sweep_escalations` calls it with no
   probe, so a due timer wakes on every periodic sweep of `docket start`, dispatching or not; a probe
   is a command, so it runs only in a sweep that dispatches: `dispatch_pod` calls it, with the probe
   and its own pod, before it claims anything (`docket run`, the `docket start --dispatch` sweep,
   `POST /dispatch/<pod>`). For each wait, in this order:
   - **Probe due** (`nextProbeAt` reached, `until` set, a probe supplied): run it. Exit `0` settles
     the wait by `resolve` (option `resume`, `by` `probe`, channel `sweep`) and wakes the task
     `resumed`. Any other result, a timeout or a refusal of the jail counts as not met: `probes` grows
     by one and `nextProbeAt` becomes now plus `every`. The probe's output is never stored.
   - **Due time reached** (`dueAt <= now`): with no `until`, the record is settled `expired`
     (`escalation_expired`) and the task woken `resumed`. With `until`, the timer was the probe's
     ceiling: the record is settled `expired`; when the step declares `on.timeout` the task is woken
     `timeout`; with no route it is moved to `blocked` with `blockedReason: "wait_expired"` and the
     reason `wait at step '<id>' expired: '<command>' never exited 0`. A wait never fails a task.
   - Waking a task sets `wait.outcome` and moves the task `waiting_input` to `pending` in one
     update, and does so only while the task still waits on this escalation. Two sweeps over the same
     wait wake it once.
   `resolve` with `resume` (a person, `POST /escalations/<id>`) is the early exit: the same wake with
   outcome `resumed`, the record stamped applied at once.
4. **The claim applies the outcome.** Before the resume position is computed, and after the answers
   of "Operator input steps and answers", a claimed task whose `wait.outcome` is set gets one
   synthetic hop (`role` the step id, `member_id` `""`, `ok` true, `output` `waited: <outcome>`,
   `artifact.verdict` the outcome, `step_id` the wait step's id, `next_step` the resolved target of
   its `on.timeout` route when the outcome is `timeout`, else `None`) and loses its `wait`, both in
   one task-store update, so a task claimed twice gains one hop. `resumed` continues at the next step.
   A `timeout` route resolves as an `input` step's does (`fail` ends the task `failed`, `stop` ends it
   `done`, a backward target is bounded by its `max`, counted from the hops on resume); the hops
   before the wait are never re-run.
5. **Blocked and retried.** A task blocked `wait_expired` has no `wait` and no hop for the step, so
   `retry_task` or `unblock_pod` sends the next claim straight back to the wait step, which parks with
   a new due time and a new escalation.
6. **The probe runs where a `run:` step does.** Its working directory is the task's worktree, else the
   Lead's codebase, else the pod's working directory; it runs under the pod's isolation posture (the
   jail when isolation is on, refused when on and no backend is usable, the host otherwise), bounded by
   the pod's `verifyTimeoutS`, with `DOCKET_TASK_ID`, `DOCKET_BASE_COMMIT` and `DOCKET_HEAD_COMMIT` set
   as for a command step. There is no other way a wait runs a command.
7. **Not a person.** A task parked on a wait is `waiting_input` for the state machine and the
   operator contract's `escalation` link, but it is not waiting for anyone: the inbox lists it
   neither in `needsYou` nor in `running` (its escalation is under `escalations`), and its
   `a2aState` is `WORKING` (operator-loop.spec.md areas 1 and 5).

### Task brief (ADR 0016)

1. **Parsing.** `parse_brief(text)` reads the **last** fenced ` ```json ` block in *text* and, only
   if it both parses as JSON and validates as `TaskBrief`, returns it -- any other outcome (no
   fence, invalid JSON, a non-object payload, a schema mismatch) returns `None`, never raises.
   Dispatch calls this on every successful hop's output and sets the resulting
   `HandoffArtifact.brief` -- so a brief is not limited to the Lead role by construction, though in
   practice only a Lead step's own instructions produce one. `HandoffArtifact.brief` is excluded
   from `DROP_ORDER`, the same posture `summary` has: a token-budgeted consumer never sheds it.
2. **The intake recipe's gate.** The shipped `intake` recipe's Lead step matches one of
   `READY`/`NEEDS-INPUT`/`REJECT` with a `passValues` sentinel its pattern can never capture, so
   every real marker is resolved through the step's own `on:` map (`pipeline-format.spec.md`,
   "Outcome routing") rather than an unconditional pass -- `on: {READY: build, NEEDS-INPUT: ask,
   REJECT: fail}`. This is a property of that recipe's YAML, not a dispatch mechanism: any custom
   pipeline may use the ordinary pass-value shortcut instead, and requirement 3 applies to it
   identically.
3. **The resource pre-check.** For any outcome labelled `READY` (case-insensitive) whose hop
   carries a brief -- whether that outcome advanced (the label matched the gate's `passValues`) or
   was routed (the label matched an `on:` entry, requirement 2's shape) -- dispatch **MUST** check
   the brief's own `resources[]` and collect every entry a deterministic check cannot confirm:
   `secret:<NAME>` against the configured secret names, `path:<p>` against the path existing, and
   the literal `verify` against the pod's Implementer having a non-empty `verifyCmd`. The check is
   pure -- no writes, no trace. A non-empty result ends the task `blocked` with `blockedReason:
   "resources"` (a short code preferred over `reason`'s free text, so the A2A state mapping's
   `AUTH_REQUIRED` check has something stable to key on) and `reason` `brief names missing
   resources: <items>`, with no further hop attempted for that task; the run goes on to claim the
   pod's next task. A brief naming no `resources[]`, or every one
   present, is unaffected -- the pipeline proceeds as an ordinary `READY` outcome would.
4. **`REJECT` fails with a kind.** A route to `fail` from the label `REJECT` (matched uppercased)
   **MUST** set the task's `failureKind` to `rejected`; every other label routed to `fail` sets none
   (an external gate's own label excepted, see "Generalized gate execution" requirement 6). The A2A
   state mapping then resolves `failed` with `rejected` to `REJECTED` rather than the generic
   `FAILED`.
5. **The question's schema from a brief.** An `input` step resolves the `from:` step's most recent
   hop; when that hop's artifact carries a brief with a non-empty `questions[]`, the minted
   `Question.requested_schema` has one required string property per question (`q1`..`qn`, `title`
   = the question's text) instead of the generic single `answer` property, and `Question.message`
   is `"The Lead needs answers before starting: <brief.objective>"` instead of the step's own
   configured `message` or fallback. A step whose `from:` hop has no brief, or a brief with no
   questions, is unaffected.
6. **The Implementer's view.** The Implementer's hop message finds the most recent prior hop whose
   artifact carries a brief (recency, not role -- see requirement 1) and, for that hop only,
   replaces its usual carried-forward prose with `## Brief\n<render_brief(brief)>` -- the brief's
   own fields (objective, acceptance, context, constraints, assumptions, resources,
   expectedRiskyActions, questions), in that fixed order, never the Lead's raw reply text for that
   hop. Every other prior hop in the same message is unaffected and still goes through the ordinary
   token-budget compiler. A reply with no parseable brief is unaffected: the Implementer sees the
   Lead's prose.
7. **A pre-brief at enqueue.** `enqueue_task_once(..., brief: dict | None = None)` validates *brief* as a
   `TaskBrief` (an invalid one raises `DispatchError`, nothing persisted), folds `render_brief` of it
   into the enqueued `description` under its own `## Pre-brief` heading **before** the `pre_input`
   gate runs -- so the same screen that covers every other human-sent string at enqueue covers this
   text too -- and stores the validated brief on the task's own `brief` field (by alias). The Lead's
   first hop therefore sees the pre-brief as part of its task description.
8. **The verdict rule is unaffected by a brief.** A reply with no parseable brief
   (`HandoffArtifact.brief is None`) but a valid `READY` (or any other) marker advances or routes as
   its gate says -- a brief is always optional, and requirement 3's check is skipped whenever
   `brief is None`.

### Budget gate and auto-pause

1. Before **every** hop (not just the first, and including a rework hop), dispatch **MUST** check
   the pod's accumulated spend (summed across all pod members) against the pod's budget cap (the
   Lead's `budgetUsd`, `0` = unlimited). A task's own `maxTokens` is checked first ("Per-hop
   execution" requirement 8).
2. Spend for this check **MUST** prefer recorded cost; when recorded cost is exactly `0` across the
   pod (always true under `DocketDriver`, which reports `cost_usd = 0.0` -- see "Runtime driver
   resolution" and `cost-tracking.spec.md`), dispatch **MUST** fall back to a labelled token-based
   estimate (`pod_gating_cost`) so a real cap can still trip. This estimate is for gating only and
   is rendered distinctly labelled wherever it appears (never mixed into `docket status`'s recorded
   figures). Under a cap, a hop whose model has no price emits a `budget_warning` and runs.
3. If the cap is met or exceeded, the task **MUST** transition to `blocked` (see "blocked and
   terminal-failure re-entry"; `blockedReason` persisted as the reason, `pod budget reached (<spent>
   ≥ $<cap>) before <role>`, the spent figure labelled `(estimated — no cost recorded)` when
   estimated) and the pipeline **MUST NOT** attempt the gated hop or any later one for this task. A
   `budget_exceeded` trace event **MUST** be emitted naming the role the budget was checked before,
   the spend, the cap, and whether the spend figure was estimated.
4. The same check that blocks the task **MUST** also mark the pod's Lead paused (`paused = true`,
   `pausedReason = "budget"`, through `meta_set`). From that point on, **every** further claim
   attempt against this pod -- for this task or any other in its queue -- **MUST** be refused
   outright at claim time (see "Claiming", item 5), not merely re-blocked hop by hop, until an
   operator clears the pause (`docket run --resume`, or a new positive `budgetUsd`; see
   `cost-tracking.spec.md`). After a task ends `blocked` on the budget, `dispatch_pod` claims no
   further task in that run; a task blocked on its brief's missing resources ("Task brief"
   requirement 3) does not stop the run, because the pause is what makes the budget pod-wide.

### require_approval gate and waiting_approval

1. Immediately after the budget gate (affordability) and before a hop's message is composed or its
   agent turn runs (permission), dispatch **MUST** evaluate whether that hop requires a human
   decision. The one source is the pipeline; no pod setting and no policy (e.g. a high-risk
   action-class match) is consulted at this point, and in-turn tool-call policies are the tool
   gate's (`security-gates.spec.md`):
   - **Pipeline-defined:** the current pipeline position's *resolved* gate (its own declared `gate`,
     or its archetype's `gateContract` fallback -- see "Generalized gate execution") is an
     `ApprovalGate`. This applies to any role or archetype, and composes with the pod-level source.
     Only meaningful for a top-level step -- see "Parallel step groups" for why a group's children
     never check it.
2. A fired gate **MUST**: create a real, persisted approval record via `approval_create` (project,
   role, a human-readable action string, and a `context` of `{"taskId", "pipelineIndex"}` so the
   record can be traced back to the exact task and hop it gated); open the `gate` escalation that
   record backs; emit an `approval_required` trace event on the task's own session naming the
   escalation; and transition the task to `waiting_approval` (reason `approval required before
   <role> hop (escalation=<id>)`) **without** running the gated hop's agent turn. The task lists
   the escalation and its `pendingApprovalIndex` (the pipeline position the gate fired at)
   **MUST** be persisted; the task holds no token.
3. A `waiting_approval` task **MUST NOT** be claimable by any dispatch run, with or without
   `--resume` -- only `pending` and a `RESUMABLE_FAILURE_KINDS`-tagged `failed` task are eligible. It
   re-enters `pending` only through a resolved approval (below), never automatically, and never via
   `retry_task` or `unblock_pod` (those accept only `blocked`/`failed`).
4. Resolving the gate's escalation (`resolve_waiting_approval`, called by `resolve` for every
   surface -- `docket task answer`, `POST /escalations/<id>`, the MCP `resolve` tool, Telegram
   `/answer`, the `docket run` progress view's in-place prompt -- and by `sweep_escalations`'s
   fail-closed timeout path -- see `security-gates.spec.md`) **MUST**:
   - **On a grant:** transition the task `waiting_approval` -> `pending`, clear
     `pendingApprovalIndex`, and leave the exact pipeline position the gate fired at
     to the *next* claim (item 5) -- "the next dispatch continues from that hop." No agent turn
     runs as part of resolving the grant itself; a real dispatch invocation is still required to
     continue the pipeline.
   - **On a deny:** transition the task `waiting_approval` -> `failed` **immediately** (no agent
     turn needed to fail a task that never ran its gated hop), `failureKind: "approval_denied"`,
     `reason: "approval denied"` (or `approval denied: <reason>` when the decision carried the
     operator's reason, so the inbox's Failed entry and `task show` say why), `completedAt` set,
     the task's grants ended. Never auto-retried by a later `dispatch_pod` call,
     with or without `--resume`.
   - Each resolution traces `approval_resumed` (grant) or `approval_task_denied` (deny) on the
     task's session.
   - **The resumed hop is told which call to issue again.** The next claim re-runs the step of the
     hop that parked a call, on the session that still holds the earlier `approval_parked`
     refusal. That hop's message **MUST** end with a note naming each call a person approved for
     this task and the hop's role that no hop has spent yet: the tool and the one-line, redacted
     summary of the call (the `call=` part of the approval's `action`), and saying to issue the
     same call again now, with the same arguments, because it runs once without asking. A call
     approved ahead with `docket task pregrant` is not named. Without a granted call the message
     is unchanged. When the latest parked call of this task and role was denied and a hop of that
     role runs again (a retried task), the note says that call was refused and is not to be issued
     again; a denial still fails the task as above.
   - **A hop that ignores the note is reported.** A hop that ends `ok` while a call named in its
     note is still unspent **MUST** trace `approval_unused` on the task's session (`task`, `role`,
     `tool`, `escalation`) and `docket task show` **MUST** print one line per such event. The
     task's status is what the pipeline gives it; nothing here adds a status or executes the call.
   - Resolving an approval not created by a dispatch gate (no `context.taskId` and no escalation
     naming a task, or no `project`), an unknown approval, or a task no longer `waiting_approval`
     on that exact escalation (already resolved by a concurrent caller) **MUST** be a harmless
     no-op -- it **MUST NOT** raise.
5. The gate-override handoff **MUST** be single-use and applied exactly once at claim time:
   `dispatch_task` reads the task's escalations (`apply_resolutions`), takes the pipeline position
   from the approval record of each `approval` or `gate` escalation that is `resolved` and not
   stamped (`context.pipelineIndex`), and stamps it `appliedAt` -- so it can never leak into a
   later, unrelated claim of the same task (e.g. a crash-and-`--resume`, or the task revisiting the
   same pipeline position on a rework cycle), and a record that is `expired`, `decided` or still
   `pending` is never applied. `dispatch_task` consumes the
   override **in memory** the first time it reaches that exact pipeline position in the run; a later
   hop at the same position within the *same* run (a rework cycle sending the task back to the
   Implementer a second time) **MUST** gate again normally, with a fresh token -- the override never
   suppresses more than the one resumed hop it was minted for.
6. The require_approval gate **MUST NOT** bypass, or be bypassed by, the budget gate -- budget is
   always checked first (affordability before permission); a hop blocked on budget **MUST**
   transition to `blocked`, not `waiting_approval`, and no approval record is created for it.
7. Every trace event this pipeline's approval mechanics produce -- including an **in-turn** tool-call
   gate reached from inside a dispatch hop's agent turn, not only the gates above -- **MUST** file
   under the pod's own trace directory (`traces/<project>/`), never under the hop's agent id.
   `DocketDriver.run_turn` builds the tool context a hop's turn runs under; its `project` field
   **MUST** resolve to the caller-supplied `trace_project` (the pod, passed by dispatch) when one is
   given, else the agent's own pod, else the agent id. This is the project `approval_create`,
   `approval_grant` and `approval_deny` file their `approval_granted`/`approval_denied` events
   against, so an in-turn gate's approval trace lands beside everything
   else that hop did.

### Registry retention (runs, approvals, conversations)

1. `docket-runs.json`, the approval store's per-token files under `$APPROVALS_DIR`, and
   `docket-conversations.json` **MUST** each be bounded by a retention sweep sharing
   `TRACE_RETENTION_S` -- the same knob trace expiry uses -- rather than growing forever. This spec
   covers only that these three stores share the trigger and the liveness rule below; each store's
   own record shape and CLI surface are documented where the rest of that store is (see "does NOT
   cover" above for the run registry and `security-gates.spec.md` for the approval record).
2. A **live** record **MUST NEVER** be removed regardless of age: a `queued`/`running` run, a
   `pending` approval, or a conversation not in `done` status. Only a record already terminal (a run
   in `succeeded`/`failed`/`cancelled`/`waiting_input`/`waiting_approval`; an approval in
   `granted`/`denied`/`expired`; a conversation `done`) is eligible, and only once it has sat
   terminal past the retention window.
3. Eligibility is measured from when a record **became** terminal, not from when it was created: a
   run's `finishedAt`, an approval file's own mtime (its state transition is its only write after
   creation), and a conversation's `updated` timestamp.
4. `docket start`'s periodic sweep **MUST** run all three prunes, each independently best-effort
   like the trace and approval-expiry sweeps -- one store's prune failing **MUST NOT** block the
   others or the server. `docket task prune --traces [--days N]` **MUST** expose the trace expiry
   and the run-record prune for one pod on demand between sweeps (`--days` needs `--traces`).

### Implementer verification gate (`verifyCmd`)

The built-in pipeline's Implementer step carries a `mechanical` gate whose command is the
Implementer's own `verifyCmd`; "Generalized gate execution" states the same mechanics for any
mechanically gated step.

1. After a **successful** Implementer hop, if the Implementer's `verifyCmd` is set, dispatch
   **MUST** run it and treat a nonzero exit as a gate failure.
2. The command **MUST** run in the task's **worktree** directory if one is recorded (created at
   claim -- see "Task worktrees"); otherwise the Implementer's `codebase`; otherwise the
   Implementer's own docket workspace directory (`resolve_member_cwd` -- the single helper shared
   with the TOOLS.md generator so the two can never disagree about which tree an Implementer's work
   is checked against).
3. The verify command **MUST** use its own timeout (`verifyTimeoutS`, see "Timeout configuration"),
   independent of the agent-turn timeout -- a hung test suite and a hung LLM turn never share one
   budget.
4. A verification failure **MUST** transition the task to `failed` (reason `verifyCmd failed:
   '<cmd>'`), emit a `verification_failed` trace event with the command and its redacted output, and
   **MUST NOT** advance to the Reviewer.
5. If `verifyCmd` is unset or empty, dispatch **MUST NOT** silently skip without a visible record
   (an operator can tell whether a gate was configured, never guess): it emits a `tool_result` trace
   event (`{"verification": "skipped", "member": <id>}`) and sets the hop's own in-memory
   `HopResult.verification_skipped` flag, which `docket run` prints as `verification skipped —
   verifyCmd not set for <id>`.
6. In the built-in pipeline only the Implementer step carries a mechanical gate; a Reviewer
   step runs no verify command unless its own pipeline step declares one.
7. With isolation recorded on, the verify command **MUST** run inside the same jail a `bash` call of
   the pod takes (`security-gates.spec.md` Exec sandbox): cwd the task worktree, the worktree its
   read-write root, the pod's network, and every prepared cache entry the worktree links into as a
   read-only root. With no usable backend it **MUST NOT** run and the gate fails (`[verify not run:
   ...]`, audited `isolation.refused`). With isolation off it runs on the host.

#### Verify tool

8. A hop other than the Lead's **MUST** be told how it will be judged, whatever its role: when the hop's step has a verify
   command its instruction names it ("Hop instructions" in `role-archetypes.spec.md`), and the hop's turn
   **MUST** be offered a `verify` tool. The tool is registered for that hop only when the step has
   a verify command; it takes no parameters and **MUST** run exactly that command, never another.
9. `verify` **MUST** run through the gate's own execution path, so the model sees what the gate will
   see: the same working directory (requirement 2), the same jail or host posture (requirement 7),
   the same timeout (the gate's `timeout`, else `verifyTimeoutS`), the same output cap and the same
   secret redaction. Its result is `exit <N>` followed by the captured output; a command that never
   reached an exit (refused, timed out, no usable backend) reports `exit none` and the reason the
   runner gave. The tool is `exec`-kind, so a role denied `bash` is not offered it (Lead, Reviewer).
10. `verify` does not replace the gate: the mechanical gate **MUST** still run after the hop and
    decide the step, whatever the model did or did not do with the tool.

### Required verification (`requireVerify`)

1. A pod **MAY** set the `requireVerify` pod setting (default `false`) to declare that every
   Implementer hop **MUST** have a `verifyCmd` configured, either through the Implementer's
   `verifyCmd` or the mechanical gate's own `command` field.
2. When `requireVerify` is `true` and an Implementer hop's mechanical gate finds no command,
   dispatch **MUST** transition the task to `failed` (reason: `"verifyCmd required but not set"`)
   and **MUST NOT** advance to the Reviewer.
3. A `verification_failed` trace event **MUST** be emitted with `{"reason": "verification_missing",
   "member": <implementer_id>}` when this rule triggers.
4. When `requireVerify` is `false` (the default), an unset `verifyCmd` behaves as documented in
   "Implementer verification gate" requirement 5 (skipped with a trace event and the
   `verification_skipped` flag).

### Reviewer verdict gate and bounded rework

The built-in Reviewer step carries a `verdict` gate; "Generalized gate execution" states the same
parsing for any verdict-gated step (`parse_verdict`).

1. After a **successful** Reviewer hop, dispatch **MUST** read the verdict with `parse_verdict`
   (`pipeline-format.spec.md` "Gates") against `^\s*(APPROVE|REQUEST-CHANGES)\b`,
   case-insensitively: each line is stripped of markdown decoration, the last marker line is the
   verdict, a marker embedded later in prose does not count, and zero marker lines is
   unparseable. The Reviewer's instruction **MUST** say that the last line of its final message is
   exactly `APPROVE` or `REQUEST-CHANGES`, with nothing else on that line and reasons above it.
2. An `APPROVE` verdict **MUST** allow the pipeline to advance past the Reviewer normally.
3. A `REQUEST-CHANGES` verdict **MUST NOT** immediately fail the task. Instead, while the pod's
   rework budget (`maxReworkCycles`, a pod setting, default `1`; `0` disables rework entirely,
   making the Reviewer a hard gate) is not yet exhausted, dispatch **MUST**: emit a
   `rework_started` trace event; jump the pipeline position back to the Implementer; re-run the
   Implementer's hop with the Reviewer's REQUEST-CHANGES text rendered as its own prominent
   `--- REWORK REQUIRED: <role> requested changes ---` prompt section (sized off the full per-hop
   carryover budget and excluded from the generic recency-ranked carryover loop, so the one thing
   this hop must not lose to truncation never is, and it is never rendered twice); then re-run the
   Reviewer. Each REQUEST-CHANGES that starts a rework cycle is also recorded in the pod's
   corrections ledger.
4. A **further** `REQUEST-CHANGES` for the same task once the rework budget is exhausted (or,
   defensively, if the rework target is not in the plan) **MUST** become terminal: the task
   transitions to `failed`, a `review_rejected` trace event is emitted naming the number of rework
   cycles consumed, and the reason states the rejection occurred "after N rework cycle(s)"
   (`reviewer rejected after N rework cycle(s): REQUEST-CHANGES`).
5. Reviewer output with zero recognized marker lines, after the one re-ask of "Generalized gate
   execution", **MUST** be treated as unparseable -- distinct from an explicit `REQUEST-CHANGES` rejection,
   so a verdict is never guessed. This **MUST** emit a
   `reviewer_verdict_unparseable` trace event and fail the task immediately (unparseable output is
   never given a rework cycle).
6. Every rework cycle's hops (the re-run Implementer, the re-run Reviewer) **MUST** persist into the
   task's `hops[]` through the same incremental per-hop persistence as any other hop, so the full
   rework history is visible afterward and correctly replayable on resume (see "Per-hop incremental
   persistence and crash recovery").
7. This gate **MUST NOT** affect pods with no Reviewer member -- the check only runs when a Reviewer
   hop is part of the pipeline for that pod.

### Generalized gate execution

1. Before a hop's agent turn runs, dispatch **MUST** resolve the current pipeline position's gate
   (`resolve_gate`): the step's own declared `gate` if present, else -- only when the step omits one
   -- its resolved archetype's `gateContract`, looked up by the step's `archetype` field if set,
   else its `role`. A step with neither an explicit `gate` nor a resolvable archetype **MUST** have
   no gate at all -- the step always advances once its turn completes, like the Lead hop.
2. Gate *evaluation* **MUST** be driven by the resolved gate's own type
   (`MechanicalGate`/`VerdictGate`/`ApprovalGate`/`ExternalGate`/none), never by a role-name check:
   - A `MechanicalGate` **MUST** run `gate.command` if set, else the target member's own `verifyCmd`
     (the same "defer to the member's own check" convention "Implementer verification gate"
     documents) in the directory `resolve_member_cwd` gives -- worktree-aware cwd resolution applies
     to **any** mechanically gated step. A nonzero exit **MUST** fail the step and emit a
     `verification_failed` trace event; a pass **MUST** emit a `tool_result` event and advance --
     **unless** the step's own `on` map (`pipeline-format.spec.md`'s "Outcome routing") names the
     resulting `"pass"`/`"fail"` label, in which case that outcome **MUST** be routed instead (see
     item 5 below) and the ordinary trace event above **MUST NOT** fire. An unset command (both
     `gate.command` and the member's `verifyCmd`) **MUST** produce the honesty-rule signal
     "Implementer verification gate" documents (a `tool_result` "skipped" trace event plus the hop's
     own `verification_skipped` flag), naming the actual member id, for any mechanically gated role;
     routing never applies to a skipped check.
   - A `VerdictGate` **MUST** parse the hop's reply via `parse_verdict` with the gate's own
     `pattern`/`passValues`/`caseSensitive`/`rework`. A matched value in `passValues` **MUST**
     advance the pipeline; otherwise, when the step's own `on` map names the matched value, that
     outcome **MUST** be routed instead (item 5 below, beating the rework/fail handling that
     follows); otherwise a matched value in a configured `rework.when` **MUST** trigger a bounded
     rework cycle to `rework.to` (any earlier top-level step id) while that gate's own rework-cycle
     count (tracked per gated step id) is below `rework.maxCycles`; anything else (no rework
     configured, the value matches neither list, or no match at all) **MUST** fail the step.
   - A verdict-gated hop whose successful turn carries no verdict (neither a `handoff` call's
     `verdict` nor a marker line) **MUST** be asked once more before that failure: dispatch sends
     exactly one further request on the hop's own session with the message `Your reply had no
     verdict. Call \`handoff\` with your verdict: <v1> or <v2>.` (the gate's allowed values,
     upper-case unless the gate is case-sensitive, joined by ` or `), emits one `verdict_reasked`
     trace event, and reads the verdict from the original reply followed by the answer, a
     `handoff` call the answer makes being the turn's. The re-ask happens at most once per hop
     attempt, never when the first turn carries a verdict, and a failed re-ask request leaves the
     original reply and its unparseable outcome in place. A turn that still has no verdict fails
     exactly as before.
   - A hop **MUST** be offered a `handoff` tool (`kind="read"`) when its step has a verdict gate
     or the hop's prompt declares `output: handoff/v1` (every built-in hop prompt does; dispatch
     tells the driver by the `DOCKET_HANDOFF` environment coordinate), and **MUST NOT** be offered
     a tool named `verdict`. Its description is "Record your handoff and finish. Call this once, as
     your last action." and its parameters are the `handoff/v1` schema: `summary` (string),
     `filesChanged` (list of strings), `verdict` (string), `assumptions` and `questions` (lists of
     strings), none required; the `summary` description says it is what the next hop reads in place of
     the reply (the decisions, values, names and paths it must use), not a description of the work, because
     the artifact's `summary` is the call's. On a verdict-gated step `verdict` **MUST** be required and a string
     with a JSON-schema `enum` of the gate's allowed values (upper-case unless the gate is
     case-sensitive). A call whose arguments do not validate against the schema, or whose
     `verdict` is outside the enum (matched ignoring case unless the gate is case-sensitive),
     **MUST** fail with the allowed values named and **MUST NOT** end the turn; any other call
     **MUST** succeed and end the turn (`agent-loop.spec.md` "A tool that ends the turn"). The
     hop's output is the assistant text of that message followed by a final line holding the
     recorded `verdict` (its `summary` when it gave none), and the call's arguments reach the
     hop's record ("Structured handoff artifacts" requirement 6), so the verdict, gate, rework and
     routing handling are unchanged. The text marker remains accepted: a hop that never calls
     `handoff` is parsed, and re-asked, exactly as above.
   - An `ApprovalGate` **MUST** be evaluated **pre-hop** (see "require_approval gate and
     waiting_approval") -- by the time a hop's turn has run, an `ApprovalGate` simply advances.
     Outcome routing (item 5) does not apply to an approval gate.
   - An `ExternalGate` is evaluated as item 6 describes.
3. **Byte-identical behaviour for the three built-in roles is a hard requirement.** In the built-in
   `default_pipeline()`, every step declares its own explicit gate (Lead: none; Implementer:
   `MechanicalGate(command=None)`; Reviewer: `VerdictGate(...)`), so the archetype-fallback
   path in requirement 1 never fires for any of them. Trace event *names* for a verdict outcome come
   from a lookup by role, not a decision branch: `reviewer` emits
   `rework_started`/`review_rejected`/`reviewer_verdict_unparseable`; any other role or
   archetype emits the generic names `verdict_rework_started`/`verdict_rejected`/
   `verdict_unparseable`.
4. A step **MAY** declare its own `retries`/`timeout`, overriding the pod's role-based retry budget
   or resolved agent-turn timeout for that step only; a `MechanicalGate`'s or `ExternalGate`'s own
   `timeout` (if set) overrides the resolved verify timeout for that step's check only. Omitting
   either **MUST** fall back to the pod-wide resolution ("Timeout configuration", "Retries and the
   failure-kind taxonomy") -- the built-in pipeline's steps set neither.
5. **Outcome routing.** When a mechanical, external or verdict gate's outcome (or a command step's
   outcome, see "Conditional steps and command steps") is named in the step's own `on` map
   (`pipeline-format.spec.md`'s "Outcome routing", labels compared case-insensitively), dispatch
   **MUST** resolve it against that map instead of the outcome's ordinary handling: `fail` **MUST**
   fail the task naming the step and outcome; `stop` **MUST** end the task `done`; a step id
   **MUST** continue the pipeline there, a backward or self target counted against its own `max`
   (default 1) in a per-`(step id, outcome label)` budget analogous to `rework.maxCycles`, exhausted
   **MUST** fail the task naming the step, outcome and budget; a target that names no known step id
   fails the task. Every routing decision **MUST** emit one `route_taken` trace event naming the
   step, outcome and target; an outcome the map does not name is never routed and keeps emitting
   its ordinary trace event. A routed hop's persisted record **MUST** carry the resolved target
   (`nextStep`), so a resumed task follows the same decision rather than re-deriving it.
6. **The external gate (ADR 0025).** An `ExternalGate` **MUST** run `gate.command` and nothing else
   (the member's `verifyCmd` is not run), under the same envelope as a verify command, in the
   directory a mechanical gate uses, with the task coordinates (`DOCKET_TASK_ID`,
   `DOCKET_BASE_COMMIT`, `DOCKET_HEAD_COMMIT`, see "Conditional steps and command steps"
   requirement 4) plus `DOCKET_GATE_REASONS_FILE`, bounded by the gate's `timeout` else
   `verifyTimeoutS`. The reasons file lives under the pod cache directory (a read-write jail root),
   one per task and step, is deleted before the command runs and is never read from a prior run. Its
   envelope, working-tree fingerprint, output redaction and `hop.verify` are the mechanical gate's
   own (one shared helper). The process's exit code maps through `exitMap` to `pass`, `fail` or
   `needs_human`; an unmapped code, a timeout, a command that never ran to an exit, and a jail
   refusal (`[verify not run: ...]`) are `error`. After the command, the reasons file, when present,
   **MUST** be read: UTF-8 JSON of at most 64 KiB shaped `{"reasons": [{"summary": str, ...}]}`;
   anything else sets `reasonsInvalid` and the redacted output tail stands in as the reasons.
   Reasons are untrusted: each text field (`summary`, `id`, `path`, `severity`, `detail`) is
   redacted and screened as `pre_input` the way an MCP result is, a blocked one makes the file
   invalid, and no reason field drives control flow. A routed outcome (`on` names the label)
   **MUST** persist `hop.verify` with the label and route; an unrouted `fail`, `needs_human` or
   `error` **MUST** fail the task with failure kind `gate_failed`, `gate_needs_human` or
   `gate_error` (also when one of these labels is routed straight to `fail`); an unrouted `pass`
   advances. The exit status is always the process's own, never a value the command wrote. When the
   reasons file's directory cannot be prepared, the gate still runs, no reasons are read, and the
   output tail is the reasons.
7. **Gate per task.** A claimed task that carries a `gate` (`{"command": str, "timeoutS"?: int,
   "map"?: {exit code: label}}`) **MUST** get an `ExternalGate` built from it (`map` moves the named
   codes to their label over the default `pass: 0`, `fail: 1`, `needs_human: 2`), evaluated after
   the own gate of the pipeline's **last `implementer` step** (else the last step that runs an agent
   turn; a `run` or `input` step never takes it) has advanced, and never in place of that gate. It
   uses the step's own `on` map and the same label handling as item 6. The step's own gate is
   evaluated first: a non-advancing outcome (a failure, or a route other than `pass`) stands and the
   task gate does not run. A task gate that does not pass decides the hop's outcome, so
   `{"command": "false"}` fails the task `gate_failed` after the Implementer passed `verifyCmd`. The
   trace events of item 6 carry `"source": "task"` in their payload, and `hop.verify` carries
   `"source": "task"` and, when the step's own gate also produced evidence and the task gate passed,
   the step's own evidence with the task gate's nested under `taskGate`. A gate that cannot be built
   refuses the task at claim as item 7 of "Pipeline order and participation" does
   (`failureKind: "pipeline"`); a pipeline with no step to attach it to refuses it inside the task
   run (`failureKind: "dispatch_refused"`, see "Deterministic refusal inside a claimed task"). The
   claim records `gateApplied` (`true` when the task carries a gate) on the task.

### Conditional steps and command steps

1. Before a top-level step's gate or hop runs, dispatch **MUST** evaluate its `when` (if any):
   `changed` matches when any path matches the glob among the paths changed between the latest `ok`
   hop's evidence (the latest hop that has any, whatever its role) `baseCommit` and `commit`
   together with the uncommitted paths git reports, both read in the task's worktree (or the pod Lead's own codebase when the task runs in
   place, or the pod's working directory when the pod is `workdir`-kind, where a command step's
   command runs too), because the hop's own work is committed by then ("Task worktrees" requirement 8);
   `var`/`is` compares this run's resolved pipeline variable namespace (stringified) against the
   given value; `memberPresent` checks the role against `pod_full_roster`. Every predicate set on the
   step **MUST** be ANDed. A false predicate **MUST** emit a `step_skipped` trace event naming the
   step and its `when`, and the pipeline **MUST** advance to the next position with no hop, no agent
   turn, and no cost.
2. A `run` step (pipeline-format.spec.md's Steps Requirement 9) **MUST** execute its command
   directly: no agent turn, no session, no cost. Its command **MUST** first be classified
   (`classify_command`, extended by the pod's own `allowCommands`); an `allow` verdict **MUST** run
   it in the same directory this section's `changed` predicate reads, bounded by the step's own
   `timeout` else the pod's `verifyTimeoutS`. With isolation recorded on, the command **MUST** run in
   the same jail as the verify command ("Implementer verification gate" requirement 7) and a missing
   backend fails the step. A non-`allow` verdict **MUST NOT** run the command: a `deny` verdict
   (an empty or unparseable command) and, under the pod's resolved `approvalMode: "refuse"`, an `ask` verdict
   **MUST** fail the step immediately, naming the classifier's reason; under `"wait"` or `"park"`
   an `ask` **MUST** gate exactly like a pipeline `approval` step, keyed to the step's own pipeline
   position, so a granted single-use override lets a resumed run through without asking again.
3. A command step's outcome label is the last non-blank output line when that line is a single
   upper-case token (e.g. `PASS`, `NEEDS-REVIEW`), else `pass` for exit `0` and `fail` otherwise. A
   label named in the step's own `on` map is routed (Generalized gate execution item 5); otherwise
   exit `0` advances and a nonzero exit fails the task with a reason naming the step and command.
   Its `HopResult` **MUST** carry `role` set to the step id, `member_id=""`, the redacted captured
   output, and `ok` set to whether the exit was `0`; it is persisted through the same incremental
   path as any other hop, so it is visible and replayable on resume like an agent hop. A
   `command_step` trace event `{"step", "cmd", "exit"}` **MUST** be emitted for every command that
   ran (`exit` is `0`/`1`); a step refused under `approvalMode: "refuse"` without running **MUST**
   also emit `command_step` with `exit: null`, so an operator can tell "never ran" apart from "ran
   and failed".
4. A command step's process **MUST** receive the task's coordinates as environment variables, merged
   over the inherited environment: `DOCKET_TASK_ID`, and `DOCKET_BASE_COMMIT` /
   `DOCKET_HEAD_COMMIT` taken from the `evidence` (`baseCommit` / `commit`) of the latest `ok`
   hop of the run that has evidence, whatever its role. With no such hop, or a missing value, each **MUST** be the empty
   string, never absent. They **MUST NOT** be computed from git or from a worktree path: the
   recorded evidence is the one source, so a check recipe and the evidence it is judged against
   agree.
   A step's own `env` ("pipeline-format.spec.md") **MUST** be merged under these coordinates, so a
   coordinate always wins. Its values **MUST NOT** appear in the `command_step` trace event, which
   records the command text only.
5. **Known limitation:** this section covers only a **top-level** step. A `parallel` group's
   children run as ordinary units (see "Parallel step groups"), which do not evaluate `when` or
   execute a `run` command -- a child declaring either is not a supported combination.

### Parallel step groups

1. A `parallel` step's children **MUST** run concurrently via a bounded thread pool (`run_group`, at
   most `DEFAULT_MAX_PARALLEL_WORKERS`, 4; hops are subprocess-bound, so this is a real resource
   bound) and **MUST** all be observed (joined) before the pipeline advances past that position -- a
   group is one pipeline position, not one per child.
2. Every child **MUST** independently go through the same budget gate, hop execution, and gate
   evaluation a top-level step does -- each child is a real, costed agent turn. A child's resolved
   gate being an `ApprovalGate` **MUST** fail that child clearly (`<role>: an 'approval' gate is not
   supported inside a parallel group`) rather than attempt mid-group human-approval semantics --
   approval gating applies only to top-level steps (see "require_approval gate and
   waiting_approval").
3. The group's outcome **MUST** merge its children's outcomes by priority: `cancelled` (any child) >
   `blocked` (any child) > `failed` (any child) > `advance` (all children). A rework outcome is
   impossible inside a group -- the pipeline format's own validator forbids a `rework` edge on a step
   nested inside a `parallel` group. The merged `failed` outcome **MUST** keep the failing child's
   `failure_kind` (a child stopped by the task's `maxTokens` makes the group, and the task,
   `failureKind: "budget"`).
4. Each child's hop **MUST** be persisted the moment that child's turn completes -- not deferred
   until the whole group joins -- so a crash in one sibling **MUST NOT** lose a hop that already
   finished in another. The group's merged outcome, and the task's `hops[]` as persisted when the
   task settles, **MUST** list children in their **declaration** order regardless of completion
   order.
5. Trace writes from concurrent children **MUST** be serialized against each other because they
   append to the same task trace: the trace store holds an in-process append lock covering loop
   events as well as dispatch events, and dispatch's group-level lock additionally preserves its
   event ordering. The JSONL store has no cross-process read-modify-write lock under the documented
   D-12 append-only exemption.
6. **Known limitation:** resuming a task that crashed mid-group re-runs the **entire** group on
   `--resume`, including any child that had already completed -- there is no child-by-child resume
   granularity. (This does not affect the rework-replay path, per requirement 3.) A group counts as
   finished on resume only when every child's **latest** persisted hop succeeded and was not parked;
   a child whose latest hop failed (a budget stop, a backend error) re-runs the group, so a
   `docket task retry` after a failed review branch never ends the task `done` with that gate unmet.

### Runtime driver resolution

1. Dispatch's production hop-execution path **MUST** resolve `default_driver()` (`DocketDriver`).
   `DocketDriver` dispatches every tool call through the gated tool chokepoint (`pre_tool_call`,
   approval, and audit). An **injected** `runner` (a test double or explicit alternate
   implementation) always wins; this requirement governs the no-injected-runner path used by real
   `docket run`, `docket run --pipeline` and `docket start` invocations.
2. A driver-backed hop's `cost_usd` **MUST** stay `0.0` when the resolved driver's
   `capabilities().reports_cost_usd` is `False` (true for `DocketDriver`, always) -- real measured
   token counts are still recorded (`MeasuredUsage`, surfaced through `aggregate_cost`), but a token
   count **MUST NOT** be converted into a dollar figure at this boundary. The budget gate's
   estimate fallback (`pod_gating_cost`) accounts for a driver that records tokens but not cost.

### Cancellation

1. `docket task cancel <ref>` **MUST** resolve the task through `resolve_task`, then (`cancel_task`)
   call `cancel_run` for every queued or running run of the task's pod that lists the task or, while
   the task is `running`, names none yet (a run lists its tasks only when it finishes), recording
   the calling channel (`cli`, `http`, `mcp`) as the cancellation's `source`, and **MUST**
   settle a `running` task whose claimant is gone through `reclaim_stale_running` (`failed`,
   `failureKind: "stale_claim"`, audited `task.reclaimed`), ending with
   `Next: docket task retry <id>`. A task parked in `waiting_input` or `waiting_approval` **MUST** be
   cancelled through `cancel_parked_task`: it ends `cancelled` (reason `cancelled by operator`) with
   no hop run, its pending index cleared and its task grants ended, the approval record behind each
   of its pending escalations denied on the calling channel (so nothing it waited on stays in the
   inbox), the
   Lead's ledger is re-synced and one `task.cancel` audit entry names the prior state and channel.
   Stopping a live run of a task that was not parked also writes one `task.cancel` entry. With no
   live run, no stale claim and no parked state it **MUST** exit 1 and change nothing. `cancel_run`
   **MUST** durably request cancellation and kill every tracked process group currently recorded as
   in-flight for that run. Queued work becomes terminal immediately; running work remains `running`
   with a visible request until its executor observes the signal and finishes stopping -- see
   `serve-read-api.spec.md`/`cli-json-shapes.spec.md` for the run record's own `pids` and state
   fields; this spec covers only how a hop's pid gets into that list and what killing it does to the
   task it belongs to.
2. Any tracked child process (an in-flight `bash` tool command whose process group was registered
   against the current run) **MUST** run in its own session (`start_new_session=True`), so its pid
   doubles as its process-group id. Cancelling **MUST** kill the whole group (SIGTERM, a bounded
   grace period, then SIGKILL), and completed work **MUST NOT** leave stale pids behind.

   A command dispatch runs itself -- a verify command, a gate command, a `run:` step or a prepare
   command -- is a **narrower** case: it also **MUST** run in its own session and its whole group
   **MUST** be killed (`SIGKILL`, tolerating an already-exited process) when the command's own
   *timeout* expires, so a command that backgrounds work leaves no orphan behind. But its pid is
   never registered, so it is **not** reachable from `docket task cancel`; a cancelled run's
   in-flight verify command keeps running until it returns or times out on its own. This is a known
   limit.
3. An injected test runner or in-process `DocketDriver` call has no OS pid and **MUST NOT** report
   one. The turn loop cooperatively checks the run signal at turn boundaries, after the backend
   response, before each tool dispatch, and after each tool result. A response or tool result that
   loses a cancellation race **MUST** be discarded and later handlers **MUST NOT** start. An
   in-flight `bash` tool command is the one handler interrupted mid-call: the same signal reaches the
   `bash` handler through `ToolContext.cancellation_check`, which kills the command's process group
   -- see `security-gates.spec.md` and `agent-loop.spec.md`.
4. A hop stopped by that signal returns the typed, non-retryable `run_cancelled` failure kind.
   Dispatch **MUST** persist the hop evidence and transition its owning task to the terminal status
   `cancelled` (reason `run cancellation requested`), never `failed`; no later pipeline hop may
   start. Parallel children fold cancellation atomically so a sibling success cannot overwrite it.
4a. A run's terminal state is the worst outcome among the tasks it returned: `cancelled`, else
   `failed`, else `waiting_approval`/`waiting_input` when a task parked (the first parked task in
   return order decides), else `succeeded`. A run whose task parked **MUST NOT** be recorded
   `succeeded`; `waiting_input` and `waiting_approval` are terminal run states (the dispatch
   invocation is over; the task is not) and are retained and pruned like the other three.
5. Cancelling an already-terminal run (`succeeded`/`failed`/`cancelled`/`waiting_input`/
   `waiting_approval`) **MUST** be a no-op, reported as such, never re-signalled or double-finished.
   A run's own normal completion **MUST NOT** clobber a `"cancelled"` state a concurrent cancel
   already wrote back to `"succeeded"`/`"failed"`.
6. Apart from an in-flight `bash` command (requirement 3), the cooperative boundary does not abort
   Python or backend computation already executing in the current call. The run therefore remains
   visibly `running` with cancellation requested until that call returns to a checkpoint;
   `stoppedAt` and terminal `cancelled` are written only after the dispatch body has fully returned.

### Hop-failure semantics (general)

1. If a hop's underlying `run_turn` call is not `ok` and its failure was not retried away (see
   "Retries"), the task **MUST** immediately transition to `failed` with a reason naming the role and
   the underlying error (`<role> hop failed: <error>`), and **MUST NOT** attempt any later hop. A
   `pre_output` `block` verdict fails an otherwise successful hop the same way
   (`security-gates.spec.md`).
2. A `failed` task **MUST** persist its full per-hop record (`role`, `member`, `ok`, `costUsd`,
   `error`, `attempts`) so a caller can see exactly which hop stopped the pipeline, how many
   attempts it took, and why.

### Structured handoff artifacts

1. Every hop **MUST** produce a typed `HandoffArtifact` -- a Pydantic model with exactly nine
   fields: `summary` (the `summary` of the hop's `handoff` call when it gave one, else the hop's
   full reply text -- always populated), `verdict` (the `handoff` call's `verdict`, else the parsed
   gate marker, for a `VerdictGate`-gated hop; else `None`), `assumptions` and `questions` (the
   `handoff` call's lists, `[]` when there was none; a question informs the next hop and the
   operator and **MUST NOT** park a task), `files_changed` (populated by a real git
   probe for any hop that changed the tree -- see "Implementer diff producer" below), `diff_ref` (the
   same probe, Implementer hops only), `diff` (the capped text of what a hop that changed the tree
   wrote, `""` otherwise), `brief` (a parsed `TaskBrief`, see "Task brief", else `None`). `HopResult.artifact` **MUST** always be set once a hop is constructed -- a hop built
   without one backfills `HandoffArtifact.from_output(output)` (the raw text as `summary`, every other
   field at its default).
2. The next hop's prompt **MUST** be composed from the prior hop's *rendered artifact*
   (`HandoffArtifact.render()`), never from its raw `output` string directly. `render()` returns
   exactly `summary` unchanged when every other field is at its default; otherwise it appends, in
   this fixed order, a `"Diff:"` block, a `"Brief:"` block, a `"Verdict: <value>"` line, an
   `"Assumptions:"` block, a `"Questions:"` block (one `- ` line per item), a
   `"Files changed: ..."` line, a `"Diff ref: ..."` line for each field
   that is set, so the next hop sees structure the raw reply does not carry, and the diff only once.
3. The artifact **MUST** be persisted alongside its hop record (an `artifact` key in the persisted
   `hops[]` entry, `HandoffArtifact.model_dump()`) so `--resume` recovers it exactly, not just the
   raw `output` string. A hop record whose `artifact` is missing or fails to validate **MUST**
   degrade to `HandoffArtifact.from_output(output)` rather than fail the resume. Replay **MUST** use
   a persisted artifact's normalized `verdict` without reparsing its raw model prose. A record whose
   artifact carries no verdict falls back to parsing the hop's raw output.
4. `HandoffArtifact.DROP_ORDER` **MUST** declare a least-valuable-first field-shedding order
   (`diff`, `diff_ref`, `files_changed`, `assumptions`, `questions`, `verdict` -- `summary` and `brief` are never
   included; `summary` is the artifact's minimum viable content) and a `dropped(field)` helper that
   returns a copy with *field* reset to empty. The context compiler (`compile_artifact`) walks
   `DROP_ORDER` to budget one hop's carryover against its role's token budget (see "Bounded hop
   prompts").
5. The artifact module **MUST** stay pure -- no filesystem I/O, no subprocess, and no dependency on
   the dispatch state machine.
6. A hop whose turn closed with a `handoff` call that validates against `handoff/v1` **MUST**
   take its artifact's `summary`, `verdict`, `assumptions` and `questions` from the call; the git
   probe's `files_changed`, `diff_ref` and `diff` stay the record's (the call's `filesChanged` is
   advisory and never replaces git's). The gate reads the artifact's `verdict` first and a marker
   line in the output second (`parse_verdict`), the pattern of a `VerdictGate` still deciding what
   counts as a verdict. A hop with no call, a call that does not validate, or an output an output
   guardrail rewrote derives its artifact from the reply text as before. The artifact's
   `assumptions` and `questions` are omitted from its persisted dump while empty, so a record
   written before they existed loads and dumps unchanged.

### Implementer diff producer

1. After a **successful** hop, dispatch **MUST** attempt to populate that hop's artifact
   `files_changed`/`diff_ref`/`diff` before the artifact is constructed. `diff_ref` and the
   `evidence` of "Hop evidence" are Implementer-only (`None` for every other role); `files_changed`
   and `diff` are filled for any role whose hop left the working tree changed (requirements 6-8).
2. The probe **MUST** resolve the member's working tree via `resolve_member_cwd` -- the same task
   worktree -> member codebase -> member workspace-dir preference order the mechanical verify gate
   uses (see "Implementer verification gate") -- so the diff probe and the verify gate can never
   disagree about which tree is being inspected.
3. When the resolved directory is a real git repository and a `git` binary is on `PATH`, the probe
   **MUST** set `files_changed` from the working tree's uncommitted staged, unstaged and untracked
   paths (not a diff against a fixed base ref) and `diff_ref` from the member's current branch name
   (`None` rather than `""` when detached or unresolvable). Every git call goes through the
   side-effect adapter layer; **no domain module shells out to `git` directly.**
4. The probe **MUST** degrade to `files_changed=[]`/`diff_ref=None` -- never raise, never fail the
   hop, never stop the pipeline -- for each of: a `workdir`-kind (non-codebase) pod, whose Implementer
   has no codebase and no worktree and therefore resolves to its own plain workspace dir (never a git
   repository); a `codebase` that exists on disk but was never `git init`-ed (the task runs in place,
   see `workspace-structure.spec.md`, and the probe reaches the same conclusion independently); and a
   host with no `git` binary on `PATH` at dispatch time, even against an otherwise-real git
   repository.
5. `diff_ref` is the member's current branch as git reports it (`git_current_branch`), the same
   helper the in-place evidence's base-branch lookup uses.
6. `diff` **MUST** be the tracked changes (`git diff HEAD`) followed by the content of each new
   untracked file (`.gitignore` respected), each introduced by a `--- new file: <path>` line, in path
   order, read before an Implementer hop is pinned. A symlink, a non-regular file or a binary file
   contributes its header and a one-line note, never its content. `diff` **MUST** be cut at
   `HANDOFF_DIFF_MAX_CHARS` (8000) and end with a `[diff cut at N characters; M more not shown]`
   marker when it was cut; a tree with no change gives `""`.
7. A hop that left no change adds no `diff`: when the probe's text equals the `diff` of the most
   recent earlier hop of the run that carried one, a non-Implementer hop's `files_changed` and `diff`
   are `[]`/`""`, so a read-only hop after a writing hop does not hand the same text on again. An
   Implementer hop keeps its `files_changed`. A tree already dirty before the task (an in-place task)
   is delivered once, with the first hop that finds it, not per hop.
8. The next hop's message **MUST** carry the diff once, from the artifact's `render()` (so the
   per-hop token budget sheds it first); it **MUST NOT** carry the list of files the previous hop
   read.
9. In a task worktree, a non-Implementer hop that hands on a `diff` (requirement 7) **MUST** commit
   the tree on the task branch, as the Implementer's pin does (`git add -A`, message `<task subject>`
   then `docket task <id>, <role> hop`), so a pipeline with no Implementer (a research or content
   team) leaves its work on the branch. Its `diff_ref` and `evidence` stay `None`; in place, nothing
   is committed for it.

### Hop evidence (ADR 0017)

Two independently optional `HopResult` fields record what a hop's gate ran and what its work
changed, for an external consumer that reads the hop record instead of trace text.

1. `HopResult.verify` **MUST** be a `dict | None`: `None` for any hop whose step has no mechanical or
   external gate, or whose mechanical gate had no command configured (`HopResult.verification_skipped`
   covers that "no check configured" case; `verify` staying `None` is consistent with it). For a hop
   whose gate **did** run a command, dispatch **MUST** populate `verify` on **both** a pass and a
   fail, before checking the step's own `on` route (so a routed outcome carries the same evidence as
   an ordinary pass or fail), with exactly these keys:
   - `cmd` (`str`): the exact command that ran (`gate.command` or the resolved `verifyCmd`, the same
     string the `verification_failed` and `tool_result` "passed" trace events carry).
   - `exitCode` (`int`): for a mechanical gate, `0` when the command passed and `1` otherwise (a
     real nonzero exit, a timeout, a refused command, or a missing binary all read as `1`) -- the
     pass/fail projection, not the process's own status.
   - `durationS` (`float`): wall-clock seconds the command took, measured around the call, rounded to
     milliseconds (3 decimal places).
   - `outputTail` (`str`): the last `VERIFY_EVIDENCE_TAIL_CHARS` (4000) characters of the command's
     combined stdout and stderr, **after** redaction -- the same redaction applied to the
     `verification_failed` trace event's `output` field. A stored secret echoed by the verify command
     **MUST NOT** appear anywhere in a persisted `outputTail`.
   - An external gate's `verify` also carries `label` (`pass|fail|needs_human|error`), and its
     `exitCode` is the process's own exit code (`-1` when the command never reached one, e.g. a
     timeout or a refusal), plus `reasons` (the screened, redacted entries, absent when there are
     none) and `reasonsInvalid` (`bool`, `true` when the file was present but unusable). A mechanical
     gate adds no `label`.
   - `touched` (`list[str]`): absolute paths a git status snapshot taken immediately before and after
     the command shows as created or changed by it. Empty off a git checkout. It is internal and is
     never published in an evidence document.
2. `verify` is a field on the hop record, not a trace event: the `verification_failed` trace event
   (cmd + redacted output) and the `tool_result` "passed"/"skipped" trace events **MUST** be emitted
   whether or not `verify` is set, with their own payloads.
3. `HopResult.evidence` **MUST** be a `dict | None`: `None` for any non-Implementer hop. For an
   Implementer hop whose diff probe runs (the hop succeeded), the probe **MUST** always return an
   `evidence` dict with exactly these keys, each independently `None` rather than the whole dict
   collapsing to `None`:
   - `commit` (`str | None`): the commit that holds the hop's work, pinned at the close of the hop
     ("Task worktrees" requirement 8), 40 hex characters when present; `None` when pinning failed. It
     is never the bare HEAD of a tree with uncommitted work: an Implementer normally leaves its work
     uncommitted, and that HEAD is the base, so every check reading `commit` would see no change.
   - `baseCommit` (`str | None`): for a task with a recorded worktree, the `baseCommit` recorded on
     `task["worktree"]` at claim (the codebase HEAD the task branch was created from), so a task's
     `diffStat` never includes another task's commits. For a task that runs in place, the merge-base
     of that HEAD with the current branch of the member's codebase.
   - `diffStat` (`dict | None`): `{"files": int, "insertions": int, "deletions": int}` from
     `git diff --shortstat` of `baseCommit` against `commit`, so the stat and the commit describe the
     same change; `None` when either is `None`.
   Each of these git reads **MUST** degrade to `None` -- never raise -- on a missing `git` binary, a
   non-repository directory, an unresolvable ref, or a timeout, the same degrade-to-empty convention
   `files_changed`/`diff_ref` use. When the resolved working tree is not a git repository at all (or
   `git` is unavailable), the probe **MUST** still return an `evidence` dict with all three keys
   `None`, not `None` itself -- this dict is what proves "checked, found nothing" rather than "never
   checked."
4. Both fields **MUST** round-trip through persistence: the hop record persists `verify` and
   `evidence` verbatim (each `None` when the hop never set it), and reading a hop record back
   restores both, accepting only a `dict` value for each key and defaulting to `None` on any other
   type (including the key being absent). A hop record with no `verify`/`evidence` key at all
   **MUST** still load without raising, with both fields `None` -- the same contract "Structured
   handoff artifacts" states for `artifact`.
5. Neither field changes gating. `verify`/`evidence` are record-keeping, read by nothing on the live
   gate-decision path (the `GATE FAILED` carryover and an `input` step's gate report read them to
   compose text, not to decide).

### Hop prompt manifest (ADR 0035)

1. `HopResult.prompt_manifest` (persisted and served as `promptManifest`) **MUST** record which
   prompts the hop's turn was composed from: `layers`, one entry per prompt layer in composition
   order, each `{layer, name, version, sha256, scope, tokens}`, then `model` (the hop's planned
   model), `family` (its provider), `class` (the hop prompt's `modelClass`, `any` when none) and
   `profile` (the model profile's name). The layers are `identity` (the role's identity prompt,
   when a scope holds one) and `hop` (the hop's instruction: the shipped or overriding prompt,
   a step's own `instructions` as scope `pipeline`, a role's generated one as scope `generated`);
   a non-Lead hop also records `task`, the `## Task` section of "Bounded hop prompts" requirement 11
   (scope `task`, version `""`, `sha256` and `tokens` of that section's text), between the two. The
   `hop` layer names the hop's instruction, not the whole `## Hop` section.
2. A layer's `sha256` **MUST** be the hash of its prompt's text as UTF-8 (a shipped prompt's equals
   the hash of its file's body), `version` is the prompt's own semantic version (`""` for a text
   with no file), `scope` is where the loader found it (`shipped`, `operator`, `pod`,
   `repository`) and `tokens` is the estimate the context compiler budgets with.
3. The manifest is empty for a hop recorded before the field existed; a record with no
   `promptManifest` key, or a malformed one, **MUST** load with an empty manifest, and an empty
   manifest **MUST** be omitted from the persisted dump.

### Hop events and task usage (ADR 0027)

Two trace events bracket each hop, and the hop record and task record carry the model and token
counts to attribute usage to.

1. Every hop **MUST** write a `hop_started` trace event in the task's session, immediately after its
   `tool_call` hop marker and before the turn. Its payload is exactly these keys: `task` (the task
   id), `step` (the hop's pipeline step id), `role`, `member` (the hop's member id), `model`,
   `provider`, `cycle` (the task's rework cycles consumed so far in this run, summed over every
   gated step; `0` before any rework) and `attempt` (always `1`: retries are `hop_retry` events, not
   new starts).
2. Every hop **MUST** write a `hop_finished` trace event after its closing record (`tool_result` or
   `error`, and `cost_charged` when present) and before the hop is persisted. Its payload is the
   `hop_started` keys, with `attempt` set to the hop's total tries (`HopResult.attempts`), and these
   additional keys: `ok` (the hop's outcome), `verdict` (`HopResult.artifact.verdict`, or `null`),
   `gate` (the mechanical gate's `pass`/`fail` from its exit code, an external gate's `label`, or
   `null` for a hop with no `verify`), `usage` (`HopResult.usage`,
   `{input, cached, cacheWrite, output}`, or `null`), `durationMs` (the hop's trace window,
   `HopResult.trace` `lastTs` minus `firstTs`, in milliseconds at the trace's one-second precision;
   `null` when tracing is off) and `error` (`HopResult.error`, `""` when none).
3. `HopResult` **MUST** carry `model: str = ""` and `provider: str = ""`. `model` is the served model
   in the form `<provider>/<model id>` (the form `usage.byModel` keys use); `provider` is the catalog
   provider name. The hop record persists both as `model` and `provider` keys, and a record that has
   neither reads back as `""`. Both are additive: the evidence document does not read them, and no
   other key changes meaning.
4. `hop_started`'s `model` and `provider` name the **planned** model: the step's own `model` override
   (resolved as "Per-hop execution" requirement 5) when the step declares one, else the member's
   configured `model` in `.docket-meta.json`, else the configured default model; `provider` is the
   part before `/`. The `hop_started` event is written before the turn, so it cannot name the served
   model. `hop_finished`'s `model` and `provider` name the **served** model the turn reported, and
   the hop record persists the same served values. A hop whose turn reported no served model records
   `""` for both. The two events can differ when the endpoint serves a different model than the one
   requested.
5. Each time `dispatch_pod` settles a task from a dispatch result (a terminal state or a waiting
   one), it **MUST** write `task["usage"]` as `{"input": n, "cached": n, "cacheWrite": n, "output":
   n, "byModel": {<model>: {"input": n, "cached": n, "cacheWrite": n, "output": n}}}`, summed over the
   result's hops (a hop with `usage` `null` adds nothing). A hop whose `model` is `""` is summed under
   the `""` key. A task that has never settled this way has no `usage` key.

### Task worktrees

1. Provisioning a pod member (`docket pod add`, `docket init`) **MUST NOT** create a git worktree
   and records no per-member worktree fields; worktrees exist only per task, created at claim.
2. At claim, for a task with no `worktree` recorded, a pod whose Implementer has a `codebase`
   **MUST** get `<Implementer workspace>/tasks/<taskId>` created on a new branch
   `docket/<project>/<taskId>` from the codebase's HEAD, and **MUST** record `task["worktree"] =
   {dir, branch, baseCommit, gitDir, commonDir}` through a locked write of the queue; `baseCommit`
   is the new worktree's HEAD, the creation commit; `gitDir`/`commonDir` are the worktree's git dirs
   as git reported them at creation. Resolving the task's worktree registers them
   (`trust_worktree`), so host-side git in it names them explicitly and never reads the
   agent-writable `.git` file (`security-gates.spec.md`).
3. Every hop, verify gate and `when`/command directory of that task **MUST** resolve to that
   directory. A task that already records a worktree (parked `waiting_input`/`waiting_approval`,
   resumed, or retried) **MUST** reuse it; claim never creates a second one.
4. When git is missing, the codebase is not a repo, or `worktree add` fails, the task **MUST** run in
   place and record `worktree = {dir: "", branch: "", baseCommit: "", fallbackReason}`, unless the
   task carries a `baseRef` (requirement 4a). An Implementer with no `codebase` records no worktree.
   - 4a. A task with a `baseRef` **MUST** get its worktree created on the new task branch from that
     ref (`git worktree add -b <branch> <dir> <baseRef>`), record `worktree.baseRef` as given, and
     `baseCommit` is the new worktree's HEAD, the commit the ref resolved to. A ref that begins with
     `-` is refused outright. The caller asked for a base, so running in place is wrong: when the ref
     does not resolve, the codebase is not a repo, git is missing, or the Implementer has no
     codebase, claim **MUST** record no `worktree`, leave no worktree directory or task branch
     behind, and settle the task through the claim-time refusal (requirement 4b) with `failureKind:
     "base_ref"` and a reason naming the ref. No hop runs.
   - 4b. The claim-time refusal settles the claimed task `failed` with `failureKind`, `reason` and
     `completedAt`, leaves the recorded `hops` untouched, re-syncs the ledger, and
     writes a `dispatch_refused` trace event whose payload carries the refusal `reason` and
     `failureKind`; `dispatch_pod` then continues to the next eligible task. `base_ref` is not in
     `RESUMABLE_FAILURE_KINDS`: a resume would refuse again, so the operator re-enqueues with a
     corrected ref.
5. Removing the Implementer (`docket pod remove`, `teardown_member`) **MUST** remove every task
   worktree under its `tasks/` directory and delete each task branch merged into the codebase's
   current branch; a branch that is not merged is kept and reported with the manual
   `git branch -D` command.
6. Docket never merges a task's work. A finished task's worktree lives until the member is removed or
   `docket task prune` removes it (requirement 7).
7. `prune_task_worktrees(project, force=False, dry_run=False)` **MUST** consider only tasks whose
   status is `done`, `failed` or `cancelled`, with a recorded `worktree.dir` and no
   `worktree.prunedAt`; a pending, running, blocked or waiting task is never touched, and neither is a
   `failed` task whose `failureKind` is resumable (`docket run --resume` re-claims it in its recorded
   worktree), even with `force`. `worktree.dir` **MUST** resolve directly inside a pod member's
   `tasks/` directory before anything is removed, else the task is kept and reported. Without
   `force` it removes the worktree and deletes the branch only when the branch is merged into the
   codebase's current branch and the worktree has no uncommitted change to a tracked file; every
   other task is kept with its reason. Untracked files (build and verify artifacts such as
   `__pycache__/`) do not keep a worktree: they are discarded with it and counted in the entry's
   reason. `force` removes the worktree regardless, deletes the branch only when merged (an unmerged
   branch is kept and reported), and writes a `pod.worktrees.prune` audit entry. `dry_run` changes
   nothing. A removal records `worktree.prunedAt` through a locked write of the queue.
8. When an Implementer hop ends `ok`, dispatch **MUST** pin the hop's working tree in a commit before
   reading its evidence, so the evidence `commit`, `DOCKET_HEAD_COMMIT`, the `diffStat` and the task
   branch all hold the work the agent left, committed or not. The paths `files_changed` reports are
   read before pinning.
   - A task with a recorded worktree `dir`: every change in it, untracked files included and
     `.gitignore` respected, **MUST** be committed on the task branch (`git_commit_all`), so
     `git merge <branch>` (the command `docket task show` prints) brings the work and
     `docket task prune` keeps the worktree until that branch is merged. The commit's subject is the
     task description's first line cut to at most 72 characters at a word boundary (the whole line
     when it fits; a single word longer than 72 is cut at 72), else `docket task <id>`; its body
     names the task id and the hop; it runs with repository hooks and commit signing disabled
     (bookkeeping, not a gate), as the operator's git identity, else `docket <docket@localhost>`. A
     tree with nothing to commit **MUST NOT** get a commit; `commit` is then its HEAD.
   - A task that runs in place: the tree **MUST** be pinned in a snapshot commit parented on HEAD
     through a temporary index (`git_snapshot_commit`), leaving the index, the branch and the working
     tree untouched; a tree equal to HEAD's yields HEAD itself.
   - A failure of either **MUST** leave `commit` `None` (never the unpinned HEAD), so a check step
     receives an empty `DOCKET_HEAD_COMMIT` and fails instead of comparing the base to itself. The
     shipped `anti-tautology` and `mutation` recipes **MUST** fail on an empty `DOCKET_HEAD_COMMIT`.

### Task preparation (ADR 0029)

A task's worktree is a bare checkout: nothing the project's own checks import is installed in it.
Dispatch prepares it once per claim, before any hop.

1. After the claim-time refusals (requirement 4b of "Task worktrees") and the task's pipeline and
   gate resolution, and before the task's first hop, `dispatch_pod` **MUST** prepare the claimed
   task's worktree. A task with no recorded worktree `dir` (one that runs in place) **MUST NOT** be
   prepared: docket installs only into a checkout it made. No hop runs, and no token is spent, until
   preparation has finished.
2. The command is the first of these that is present; a blank string or `none` (any case) at a level
   turns preparation off and wins over every lower level:
   1. the task's own `prepare` (`POST /tasks/<pod>`, stored on the task record before it runs);
   2. the pod's `prepare` setting (`PodSettings.prepare`, set by `pod.yaml`'s top-level `prepare:`
      or `docket pod set prepare`);
   3. the command for the first lockfile found at the worktree's root, in this order:
      `package-lock.json` -> `npm ci`; `pnpm-lock.yaml` -> `pnpm install --frozen-lockfile`;
      `yarn.lock` -> `yarn install --immutable`; `uv.lock` -> `uv sync --frozen`; `poetry.lock` ->
      `poetry install`; `Cargo.lock` -> `cargo fetch`.
   No command and no lockfile **MUST** run nothing, record nothing and write no event: docket never
   guesses an install.
3. The command **MUST** run with the worktree as its working directory and `PREPARE_TIMEOUT_S` (900
   seconds) as its limit, under the same posture as a `verifyCmd`: on the host when isolation is off,
   and when isolation is on through the pod's jail with the worktree writable and **the network open
   for this launch only** whatever the pod's `network` records; the hops keep the pod's setting
   (`security-gates.spec.md` Exec sandbox). Isolation on with no usable backend refuses the run like
   any other command: the task fails `prepare` with that reason.
4. Cache. With a lockfile present, what the command installs is kept in
   `DOCKET_HOME/cache/prepare/<codebase name>-<8 hex of the codebase path's sha256>/<lock>-<cmd>/`,
   `<lock>` being the first 16 hex characters of the lockfile's sha256 and `<cmd>` the first 8 of the
   command's. Only `node_modules` is kept and linked: it is the one install directory that is
   relocatable; a `.venv` or a Cargo registry is rebuilt by the command in every worktree. Rules:
   - A hit (the entry exists) runs no command: `node_modules` is symlinked into the worktree.
   - A miss runs the command in the worktree, then moves `node_modules` into a `.partial` sibling,
     renames it to the entry (never visible half-built) and symlinks it back. The whole of a miss
     runs under a `filelock` on `<codebase dir>/.lock`, so two tasks of one codebase never build the
     same entry twice; a failed command leaves no entry.
   - After a build, the three most recently used entries of the codebase are kept and the others
     removed; a hit refreshes its entry's modification time.
   - A name that already exists in the worktree (a tracked `node_modules`) is left alone.
   - The linked names are added to the repository's `info/exclude` (common git dir) so the link is
     never part of the task's commit.
5. Record and resume. A prepared task records `prepared = {command, source, lockHash, cacheHit}`
   (`source` is `task`, `pod` or `lockfile`; `lockHash` the lockfile's full sha256, `""` without
   one). A claimed task whose record carries the same `command` and `lockHash` and whose links still
   resolve **MUST NOT** be prepared again; a link whose cache entry was removed since is replaced.
6. A failing command (non-zero exit, timeout, refusal), or unreadable pod settings, **MUST** settle
   the task `failed` through the claim-time refusal with `failureKind: "prepare"` and a `reason` of
   `prepare failed: <command> (exit <n>): <tail>` (`no exit status` in place of `exit <n>` when the
   command never reached one), the tail being the last `VERIFY_EVIDENCE_TAIL_CHARS` characters of the
   redacted output. No hop runs. `prepare` is not in `RESUMABLE_FAILURE_KINDS`: a resume would fail
   the same way, so the operator fixes the command or the lockfile and re-enqueues.
7. Every preparation that runs a command or links a cache entry **MUST** write one `prepare` trace
   event (`trace-store.spec.md`) with `{command, source, cacheHit, seconds, exit}`; `exit` is `null`
   on a hit and when the command could not start.
8. Hops and gates **MUST** be able to read what was linked but not write it: the cache entry is a
   read-only root of every jailed hop and gate command whose worktree links into it
   (`security-gates.spec.md` Exec sandbox). A tool that writes into `node_modules` (a `.cache` or
   `.vite` directory) therefore cannot, under isolation.

### A change that edits its own check (ADR 0029)

A team's gate is quick feedback for the agent; it reads configuration the agent can edit. The
protected-path rules (defaults, `protects`, command-named files) are `security-gates.spec.md`
"Protected paths", pure functions over a list of paths.

1. When `dispatch_task`'s pipeline ends `done` and the task records a worktree (`dir`, `branch`,
   `baseCommit`), dispatch **MUST** list the paths the task changed: `git diff --name-only
   <baseCommit> <branch>` united with the worktree's uncommitted and untracked paths
   (`git status --porcelain --untracked-files=all`, so a file inside a new directory is listed by its
   own path), read host-side. A task with no worktree record (it ran in place) **MUST NOT** be
   checked: it has no base to diff against.
2. The patterns are the defaults, the pod's `protects` setting, and every tracked file of the
   worktree that a command the task ran as a check names: the Implementer's `verifyCmd`, the command
   of every `mechanical` or `external` gate and every `run:` step of the resolved pipeline (a
   `parallel` group's children too), and the task's own `gate.command`.
3. A changed path that is protected **MUST** park the task `waiting_approval` instead of `done`,
   whatever the pod's `profile` (`lights-out` included) and `approvalMode`: dispatch creates an
   approval through `approval_create` with context `{"kind": "check_changed", "taskId", "paths"}`,
   sets `task["checkChanged"]` to all the sorted protected paths, opens the `check_changed`
   escalation the approval backs, gives the task a `reason` of
   `the change edits what checks it: <paths> (escalation=<id>)` (the text lists at most 20 paths,
   then `and <n> more`), and traces `approval_required` with `kind: "check_changed"`.
   `pendingApprovalIndex` is `null`. No hop runs after the pipeline's last hop.
4. `resolve_waiting_approval` for a `check_changed` approval: a **grant** ends the task `done`
   (reason `check_changed approved`, `completedAt` set, `checkChanged` kept as the record of what
   was granted) and never `pending` or a gate override; a **deny**, or an approval that expired,
   ends it `failed` with `failureKind: "check_changed"` and `reason` `approval denied[: <reason>]`,
   `checkChanged` kept. Either outcome re-syncs the ledger. `docket task answer`, `POST
   /escalations/<id>`, MCP `resolve` and Telegram `/answer` all resolve it, and each decision
   writes the audit entry with its channel that every approval writes.
5. `check_changed` is not in `RESUMABLE_FAILURE_KINDS`. A `failed` task retried runs the pipeline
   again and is checked again; settling a result that carries no protected paths clears a stale
   `checkChanged` from the task.
6. Files are not restored before a gate, and nothing is checked at claim; the check runs once, after
   the pipeline ends `done`.

### Downstream worktree continuity

1. When the task has a recorded worktree, every non-Lead hop (the Implementer included) **MUST**
   have its tools rooted in that checkout, passed as an internal dispatch-to-driver coordinate; its
   message states that root only as "the repository root" (the `Working directory:` line of "Bounded
   hop prompts" requirement 10) and never carries the checkout's absolute path, because a model
   copies a path it is shown and misspells it. A downstream hop **MUST NOT**
   inspect the unchanged origin checkout when judging or testing the Implementer's result.
2. `DocketDriver` **MUST** accept that root only when it resolves to a directory directly under a
   same-pod Implementer's `tasks/` directory (`<member workspace>/tasks/<taskId>`). An absent,
   malformed, cross-pod, or unregistered path **MUST** be ignored; it is never a caller-controlled
   arbitrary root expansion.
3. The coordinate **MUST** be removed before constructing the tool subprocess environment.
   The Reviewer's tool capabilities remain role-narrowed; this changes which checkout they can
   read, not whether they can write.
4. The path note is bounded context, not copied session history. The typed artifact remains the only
   prior-hop content carried into the downstream session.

### Bounded hop prompts

1. The message composed for a hop **MUST** cap how much of each *prior* hop's rendered artifact it
   carries forward (not the raw hop output -- see "Structured handoff artifacts"): a **per-role token
   budget** (`RoleArchetype.token_budget`, resolved via `budget_for_role`) that halves for each step
   further into the past (`hop_share`: `total_budget >> (rank + 1)`, rank 0 = the most recent prior
   hop) -- a partial geometric series that never sums past the configured total no matter how many
   prior hops exist, while the most recent (most relevant) hop is squeezed the least.
2. The role's total token budget **MUST** first be reduced by the (approximate) token cost of the
   task's own description, the `## Task` section's map and `## Hop` working-directory line
   (requirements 10-11) and that role's fixed instruction text -- what remains funds the carryover budget requirement 1 describes. The task's
   own description **MUST NEVER** itself be truncated or shed -- only a prior hop's rendered artifact
   is subject to budgeting.
3. When a prior hop's rendered artifact does not fit its share, `compile_artifact` **MUST** shed
   `HandoffArtifact.DROP_ORDER`'s fields one at a time, least-valuable-first (`diff`, then
   `diff_ref`, then `files_changed`, then `verdict`), re-measuring the rendered text against
   the budget after each drop and stopping the moment it fits. A field that is already empty **MUST
   NOT** be reported as dropped -- only a field whose removal changed the rendered text counts. The
   token estimate this checks **MUST** be the rendered artifact's size (`summary` plus any appended
   labelled lines), not `summary` alone, so the budget bounds the same structured content the next
   hop reasons about. When `diff` was non-empty and is shed, the rendered text **MUST** carry, in
   the diff's place, the single line `[diff omitted: N chars over budget; run git diff in the
   worktree]` (`N` the dropped diff's length in characters), so a reader is told the diff is
   missing and where to find it. The line is not counted when deciding what to shed (the drop order
   and the fields kept are those of the artifact without it), and it is kept when `summary` is
   truncated. An artifact that never had a diff carries no marker.
4. `summary` **MUST NEVER** be shed outright (it is absent from `DROP_ORDER` -- see "Structured
   handoff artifacts"). If the rendered text still does not fit its share once every droppable field
   is gone, `summary` **MUST** be truncated head + tail (kept in roughly equal shares of the
   remaining room) with an explicit `[... summary truncated: N bytes omitted ...]` marker recording
   exactly how many bytes were omitted -- never a silent cut, and never an empty section. A share too
   small to fit even the marker itself **MUST** still emit the marker in full rather than silently
   produce nothing.
5. A rework cycle's REQUEST-CHANGES note (see "Reviewer verdict gate") is exempt from the generic
   recency-ranked loop and its budgeting -- it gets the full carryover budget on its own (fit via the
   same `compile_artifact` rule as any other section), since it is what the rework Implementer hop
   exists to address.
6. Every hop **MUST** emit a `context_composed` trace event recording, per section (the rework or
   gate-failed note if present, and each prior hop carried forward): the role, original byte count,
   sent byte count, whether it was truncated, and which fields (if any) were dropped -- plus the task
   description's byte count, the composed message's total size and whether anything was truncated.
7. No tokenizer dependency **MUST** be introduced for any of the above -- `estimate_tokens` uses the
   project's documented `CONTEXT_BYTES_PER_TOKEN` bytes-per-token approximation (default 4,
   env-overridable), not a second, independently tunable one. This is an approximation, not an exact
   count from any model tokenizer, and is never used to bill against.
8. The Lead's hop message (`role == "lead"`) **MUST NOT** be a process-wide hardcoded string: it
   **MUST** resolve its instruction segment through `resolve_hop_instruction` against the `lead`
   archetype, exactly as for any custom role -- the built-in `lead` archetype carries a
   `hopInstruction`, so a pod with no `lead` overlay sees the built-in text. A step's own
   `instructions` (see `pipeline-format.spec.md`'s "Steps" Requirement 8) **MUST** override that
   resolved text for a step targeting `role: lead`, the same as for every other role. On a
   `workdir`-kind pod, while the `lead` archetype still holds the shipped instruction, the Lead
   reads the shipped `hop/lead-workdir` prompt instead of `hop/lead`: the same offer of `handoff`,
   and "a concrete plan for the role that follows in the pipeline (you never do that work
   yourself)" where `hop/lead` says "the Implementer". A `codebase`-kind pod's Lead message is
   unchanged, byte for byte. The `web-research` recipe's Lead step declares its own `instructions`,
   so a pod that applies it is never told to plan for the Implementer. The Lead's hop
   message **MUST** still be composed without the token budgeting of requirements 1-2 (it carries no
   prior-hop carryover): its instruction, then the task description, then the working-directory
   block, then any operator answers ("Operator input steps and answers" requirement 7).
9. A **backward `on:` route out of a mechanical or external gate** (the target is at or before the
   routed step, e.g. `until: verify`) **MUST** carry the gate's output into the target's next hop.
   When the routed hop holds `verify` evidence of a gate that did not pass (exit code nonzero, or a
   label other than `pass`), dispatch **MUST** hand that hop to the target's next hop as its
   carryover, and the hop message **MUST** render a section `--- GATE FAILED: <step id> ---` followed
   by the hop's persisted, redacted `verify.outputTail` (never raw output), fit to the carryover
   budget with the usual visible truncation marker and recorded in the `context_composed` sections as
   role `gate_failed`. One function writes this text. The routed hop's own output stays in the
   generic carryover, and the Implementer instruction is the ordinary one, not the rework text. A
   resume rebuilds the carryover from the last routed hop the way it rebuilds a rework hop. For an
   external gate the section carries its screened `verify.reasons` (one line each: severity,
   `path:line`, summary, then an indented detail) in place of the output tail, which stands in only
   when there are none; and when the gate's routed hop went forward to an `input` step, the
   operator's `answered` route back to the gated step carries the same section into that retry:
   replay hands the gate-failed hop to the target of the operator hop that follows it. That retry's
   section **MUST** also carry the operator's latest answer (`Operator answer:`), rendered like the
   Lead's operator answers, because it is what the human decided. A forward route, a backward `pass`
   route, an unrouted gate and a verdict rework **MUST** compose no such section.
10. **Task root and repository map (ADR 0028, ADR 0035).** The hop message **MUST** state where the
    hop's tools start without naming a path: the line `Working directory: the repository root (your
    tools start there; give paths relative to it).`, then a repository map. The message **MUST NOT**
    contain the absolute path of the task's worktree, of the pod's codebase or of any other root,
    anywhere. The root the tools use is the task's recorded worktree when it has one (for every hop
    but the Lead's), else the pod's codebase or working directory (the same root the driver gives
    the tools); when no root resolves there is neither the line nor a map. The Lead, which has no
    brief, gets the capped map: `Repository map (tracked files by directory):` followed by
    `render_repo_map`, derived from `git ls-files`, as relative directories with their file counts at
    the deepest directory depth (3, 2, then 1) that fits `REPO_MAP_MAX_CHARS`, skipping the
    directories the built-in `glob`/`grep` skip. A root that is not a git repository gets the line
    and no map. Neither the line nor the map is shed by the budget compiler; their estimated tokens
    are reserved before the carryover budget is computed. A pod's system prompt carries neither the
    root nor the map, so it is identical between tasks. On a `workdir`-kind pod
    (`pod-blueprints.spec.md` "Workspace kind and the working directory") the line reads `Working
    directory: the pod's working directory (your tools start there; give paths relative to it).`
    and the message carries no map, for the Lead and every other role: a working directory is not a
    repository, so the words "repository root" and "Repository map" never reach a model that has
    none.
11. **Two sections after the identity layer (ADR 0035).** A non-Lead hop's message **MUST** be two
    named sections in a fixed order. `## Task` holds the task description (never truncated) and the
    repository map bounded by relevance; `## Hop` holds the working-directory line, the operator's
    answer, the gate failure, the rework note, the prior artifacts (the Lead's brief included) and
    the role's instruction. The `## Task` section **MUST** be byte-identical across the non-Lead hops
    of one task, so it is derived only from the description, the Lead's brief and the task's base
    commit (never from the worktree's index or files, which a hop changes), and from the task's
    structured `task` request (operator-api.spec.md) when it has one. That request renders after the
    description, one labelled line or `- ` list per field that is set, in the fixed order objective,
    done when, acceptance, constraints, risk, answers, verify, kind, paths; a description-only task
    renders exactly as before. The `paths` of that request are named like a brief's text for the
    map, so a task that carries them gets the bounded map before any Lead brief exists. The bounded map lists,
    for every path the Lead's latest brief names, the entries directly in that path's directory
    (the path itself when it is a directory), as relative paths with a trailing `/` on a directory;
    a path is named by a whitespace-delimited token of the brief's text (an optional `path:` prefix,
    `#` suffix, surrounding punctuation and a leading `./` removed) that is a tracked file or a
    directory holding one. A brief that names none lists the root's direct entries. The map is cut
    at `REPO_MAP_MAX_CHARS` with a `... N more entries` line, and its last line names the built-in
    `glob` tool for the rest. A task whose Lead has not run (no brief) gets the capped map of
    requirement 10 in `## Task`. The Lead's own message keeps its layout of requirement 8 and has no
    section headings. The `## Task` text is derived from the base commit's tree when the task's
    worktree records one, else from the index.

### Task status vocabulary

1. `pending` -- queued, not yet claimed by any dispatch run (or moved back here by `retry_task`,
   `unblock_pod`, a granted approval, or an answered question). Not terminal.
2. `running` -- claimed by a dispatch run; at least the claim has been persisted, and zero or more
   hops may have completed and been persisted. Not terminal -- either a live dispatcher is working
   it, or (if its claim has gone stale) a later `dispatch_pod` call will move it to
   `failed`/`stale_claim`.
3. `done` -- every present hop ran and passed all applicable gates (including any rework cycles), or
   a route ended it with `stop`, and, for a task with a worktree, its diff touched no protected path
   or a person granted it ("A change that edits its own check"). Terminal.
4. `failed` -- a hop failed (after exhausting any retries), a gate failed (`verifyCmd`, an external
   or task gate, a Reviewer's exhausted rework budget or
   unparseable verdict), a route went to `fail`, a claim-time or in-run refusal settled it, a stale
   claim was swept, or an approval was denied. Terminal for this dispatch attempt, **except** that a
   `failureKind` in `RESUMABLE_FAILURE_KINDS` (`stale_claim`, `dispatch_refused`) is reclaimable via
   `--resume` (see "Crash recovery"); `approval_denied`, `check_changed` and every other kind are
   never reclaimed by `--resume`. Any `failed` task can be put back on the queue by `retry_task`.
5. `blocked` -- the pod's budget cap was reached before a hop could run, a brief named missing
   resources (`blockedReason: "resources"`), or a parked question's `expiresAt` passed unanswered
   (`blockedReason: "input_expired"`), or a `wait` step's deadline passed with a probe that never
   exited `0` and no `timeout` route (`blockedReason: "wait_expired"`). Not terminal -- re-enters `pending` only via `retry_task` or
   `unblock_pod` (never automatically, never via a plain dispatch run). An expired question is never
   `failed`; `retry_task` accepts any `blockedReason`.
6. `waiting_approval` -- a require_approval gate fired before a hop could run, a hop's in-turn tool
   call parked mid-turn under `approvalMode: "park"`, a `run:` step needs approval, or the enqueue
   screen required approval; either way a real approval record exists and the task is waiting on a
   human (or automated headless) decision. Not terminal -- re-enters `pending` only via a granted
   approval (a resolved approval escalation), never automatically, never via a plain dispatch run,
   `retry_task`, or `unblock_pod`. The pre-hop gate's grant hands the exact pipeline position back to
   the next claim as a single-use override (item 5 of "require_approval gate and
   waiting_approval"); a parked call's grant instead leaves a single-use pre-grant in the approval
   store and resumes the already-attempted hop at its own index (see "Parked approvals"); a grant
   that chose `approve_task` is also a task-wide grant, from which dispatch mints one single-use
   pre-grant per grant for each later hop (operator-loop.spec.md). A denied (or fail-closed-expired) approval moves the task straight to
   `failed` without passing through `pending`. A `check_changed` approval ("A change that edits its
   own check") is the one exception to re-entering `pending`: its grant ends the task `done` and its
   denial `failed`, and it is never skipped by a profile or an `approvalMode`. `docket task cancel`
   ends a waiting task `cancelled`.
7. `cancelled` -- the owning run's persisted cancellation signal was observed during execution, or
   `docket task cancel` cancelled a parked task. Terminal. The task retains its completed and
   cancelled-hop evidence, records `completedAt`, and cannot be reclaimed or overwritten by a late
   successful response.
8. `waiting_input` -- an `input` step parked the task, or a hop parked a `consult` question
   (operator-loop.spec.md), waiting on an operator's answer to the escalation that carries the
   minted `Question`; or a `wait` step parked it ("Wait steps"), waiting on a time or a probe and
   asking nobody. Not terminal -- re-enters `pending` only via a resolution of that escalation
   (`resolve`; the claim that follows may then settle it `failed`/`done` by the step's route, and
   expiry moves it to `blocked` -- see "Operator input steps and answers"), or, for a wait, the
   sweep that finds its time or its probe met; never via a plain dispatch run's claim,
   `retry_task`, or `unblock_pod`. Never claimable by any dispatch run, the same
   posture `waiting_approval` has.
9. Failure kinds. A `failed` task's `failureKind` **MUST** be one of: `stale_claim`,
   `dispatch_refused`, `base_ref`, `pipeline`, `prepare`, `budget`, `rejected`, `gate_failed`,
   `gate_needs_human`, `gate_error`, `approval_denied`, `check_changed`, `needs_human` (a tool
   call needed approval at autonomy level `L5`, security-gates.spec.md "Autonomy levels" item 4),
   or absent for an ordinary
   graded hop or gate failure (a hop's own `TurnResult.failure_kind`, see "Retries", is not copied
   onto the task). A new terminal result replaces any earlier `failureKind`.
10. Transitions. A task's `status` **MUST** change only through `tasks.domain.state.decide`, applied by
    `tasks.application.transitions.apply_to_task` (the one assignment of `status`; an architecture
    test refuses a second). `decide` is pure: given the record's status, the target and the facts
    (time, reason, failure kind, ...), it returns the fields to set and drop, or raises
    `IllegalTransition` before the record is touched. The table is: a pipeline result or an operator
    action may end a task `waiting_input`, `waiting_approval`, `blocked`, `done`, `failed` or
    `cancelled` from whatever status the record holds (a stale sweep or a retry can race the run still
    finishing, and the record takes the run's outcome); a claim moves `pending` or `failed` to
    `running`; `blocked`, `failed`, `waiting_input` and `waiting_approval` move to `pending`. Nothing
    else is a transition: a `done` or `cancelled` task never
    moves to `pending` or `running`. A `stale_claim` failure is evidence of a lost claim: it stamps
    no `completedAt` and keeps the claim's pid and the task's grants. A `retry` move clears the
    previous outcome (`reason`, `failureKind`, `completedAt`, `blockedReason`); an `unblock` clears
    only `blockedReason`.

### Evidence v1 (ADR 0018)

One stable document of what a task's hops kept, for an external verifier, built from the persisted
hop records. It scores nothing and carries no dollar figure.

1. The evidence models **MUST** be: `HopEvidence{role, stepId, ok, verdict, verify, commit,
   baseCommit, diffStat, usage{input, output}, trace{project, session, firstTs, lastTs}}` and
   `TaskEvidence{v, pod, taskId, status, hops}` with camelCase wire names. The version constant is
   `EVIDENCE_V1_1` (`"1.1.0"`). The schema is generated into
   `docs/contracts/evidence-v1.1/schema.json` by a generator whose `--check` runs in CI's docs job.
2. `task_evidence(project, task_id, version)` **MUST** be the only builder, reading the pod's queue.
   An unknown task raises `EvidenceNotFound` (surfaces map it to 404 / exit 1); an unknown version
   raises `ValueError`.
3. `verify` in evidence **MUST** carry exactly `cmd`, `exitCode`, `durationS`, `outputTail`.
4. Each hop record **MUST** persist `usage` (`{"input", "cached", "cacheWrite", "output"}`, the turn's
   measured `TokenUsage`, never an estimate; evidence projects `input` and `output`) and `trace`
   (`{"project", "session", "firstTs", "lastTs"}`). `TurnResult.usage` carries the measured counts;
   `DocketDriver` sets it, and leaves it `None` when the endpoint reported no tokens, in which case
   the hop's `usage` is `null`. `trace` is `null` under `DOCKET_NO_TRACE`.
5. The trace link is an identifier the existing readers accept: `session` is the task's trace session
   id (`agent:<project>:<taskId>`), the file `docket task trace <ref>` reads
   (`<TRACES_DIR>/<project>/<session>.jsonl`); `project` is the argument of
   `GET /traces/<project>`. `firstTs` is taken just before the hop's turn and `lastTs` after its
   closing `tool_result`/`error` event is written (before the hop is persisted), both in the trace's
   one-second `%Y-%m-%dT%H:%M:%SZ` form. The hop's events are those of that file whose `ts` lies in
   `[firstTs, lastTs]` and whose `agent_role` is the hop's role; hops of a parallel group share a file
   and may overlap in time.
6. A hop record that lacks these fields **MUST** still build: `usage`, `trace`, `verify`, `commit`,
   `baseCommit` and `diffStat` are `null`.
7. **Evidence 1.1.0** (ADR 0025) adds exactly two optional fields and nothing else. `task_evidence`
   **MUST** take the version `"1.1.0"`, the only evidence version; any other version raises `ValueError`.
   `docket task show --json` and `GET /tasks/<pod>/<id>/evidence` **MUST** serve `"1.1.0"`.
8. Under `"1.1.0"`, `HopEvidence.gate` is `{label, exitCode, reasonsInvalid}`, copied from the hop's
   `verify` and present only when that `verify` carries a `label` (a hop that ran an external gate);
   it adds no verdict about the work. `TaskEvidence.directives` is a list of `{path, sha256}`: the
   distinct pairs over the task's hops, in first-seen order, read from each hop record's persisted
   `repoFiles` (the `TurnResult.repo_files` the turn composed from the task's base commit; dispatch
   copies it onto the hop, evidence never recomputes it). A field with nothing to say **MUST** be
   absent from the document, not `null`. The 1.1.0 schema is generated into
   `docs/contracts/evidence-v1.1/schema.json`.

### Sweep workers

1. The `docket start --dispatch` sweep **MUST** sweep each dispatchable pod on a pool worker (one run
   record, source `"sweep"`, then `dispatch_pod` with `resume=True`) and return without waiting for
   the turns, so a pod blocked in a hop never delays another pod's task. At most
   `DISPATCH_SWEEP_WORKERS` (env-overridable, default 4; 1 is serial) sweeps run at once. The same
   sweep also expires approvals and questions, prunes the registries, and checks due schedules.
   A pod with nothing a resuming dispatch could claim (no claimable task and no `running` one)
   **MUST** be skipped before its run record is created (`tasks.application.queue.
   has_claimable_work`): an idle tick writes nothing. Measured 2026-10-24: one record per pod per
   tick had grown a live `docket-runs.json` to 85,540 empty records and 47 MB in a week, and its
   rewrites missed the 10 s store lock.
2. A pod whose previous sweep has not ended **MUST** be skipped by the next tick; a pod is never
   swept twice concurrently by the sweep loop.
3. The sweep loop **MUST**, once its stop event is set, wait for the in-flight sweeps to end before
   returning, and `docket start` joins it on shutdown.
4. `docket start` **MUST** stop in two stages on SIGINT/SIGTERM (handlers installed in the main
   thread before the startup sweep). The first signal stops the server and the sweep loop, prints one
   line (`stopping: waiting for N pod sweep(s); signal again to abandon`) and waits for in-flight
   sweeps (requirement 3). The second signal **MUST** request cancellation (`cancel_run`) of every
   in-flight sweep run (each pod's sweep records its run id), cancel queued sweeps, wait at most
   `SWEEP_ABANDON_WAIT_S` (5 s) for the runs to settle, and exit 130 (SIGINT) or 143 (SIGTERM)
   without running interpreter teardown, so a wedged worker thread cannot hold the process.
5. An abandoned sweep follows the ordinary cancellation path ("Cancellation"): a hop in flight has its
   process group killed, the hop returns `run_cancelled`, and the task ends terminal `cancelled` with
   its persisted hops kept (never requeued to `pending`); the run record ends `cancelled`. A run whose
   body never observes the request (a wedged thread) stays nonterminal with
   `cancellation.requestedAt` set. Dispatch itself is unchanged by the stop.

### CLI entry: `docket run`

1. `docket run` **MUST** be the one foreground entry to this pipeline. It takes `--resume`,
   `--timeout S`, `--progress`, `--no-prompt`, `--pipeline FILE`, repeatable `--var k=v`, `--dry-run`
   and the pod selector; an undeclared flag **MUST** exit 2 naming it, never be dropped. A malformed
   `--var` exits 2; an invalid `--pipeline` file exits 1.
2. `--dry-run` **MUST** print the plan `render_plan` renders for the effective pipeline against the
   pod's roster and **MUST NOT** claim a task, create a run record, write a trace event or change a
   task status. It **MUST NOT** require a model endpoint.
3. The banner `Running <n> pending task(s) through: <steps>` (under `--resume` also
   `, <n> resumable` and, when some task is running, `, <n> running (reclaimed only if the claim is
   stale)`) **MUST** list the effective pipeline's runnable steps after roster filtering, so a
   two-member pod names two hops, not four. With nothing to run it prints `No pending tasks in pod
   '<pod>'` with the `docket task add` hint and starts nothing.
4. Without a model endpoint `run` **MUST** exit 1 with `No model endpoint yet` and the hint
   `Run docket setup` before any run record exists.
5. `--resume` **MUST** clear the Lead's pause (audited `run.resume` when a pause was cleared) and
   re-queue the pod's blocked tasks (`unblock_pod`; every `blockedReason`, see "blocked and
   terminal-failure re-entry") before it reclaims stale claims.
6. A run prints one line per task (`[<task-id>] done — <n> hop(s)`, or `[<task-id>] <status> —
   <reason>`), then one summary line (`<n> done · <n> failed`, then `· <n> waiting` and
   `· <n> blocked` when non-zero, then `· <tokens> tokens (~$<x> est.)`, the dollar figure a
   labelled estimate, never billed spend) and one `Next:` line (`docket inbox` when anything failed,
   waits or is blocked, else `docket status`). It exits 1 when the run record ended `failed`.

### An escalation for every park

1. Each of the five ways a task stops for a person (a `wait` step opens a sixth record, for nobody:
   "Wait steps") MUST open one escalation record
   (`operator-loop.spec.md` "Escalations") when the pause is created, before the task is written
   `waiting_approval` or `waiting_input`, and append its id to the task's `escalations`: a parked
   in-turn tool call (`approval`), a parked `consult` (`consult`), an `input` step (`input`), the
   pipeline `approval` gate (`gate`) and a change that edits its own check (`check_changed`).
2. The record is the pause. The task holds no approval token, question or answer, only the
   escalations it lists and a `reason` naming the escalation; an approval, gate or changed-check
   escalation is backed by an approval record that names it back, and a `consult` waiting in the
   turn has one beside it.
3. **Resume reads the record.** A claim reads the task's `escalations` (see "Operator input steps
   and answers" item 3): a `consult` record in state `resolved` with no `resolution.appliedAt`
   is read by the re-run hop of its step (the note its message ends with, `consult_note`) and
   stamped once a hop of that step is persisted,
   an `input` record becomes the synthetic hop and route, an `approval` or `gate` at a pipeline
   position becomes the position the run skips the approval at once, and each is then stamped
   `appliedAt`. A record already stamped, `expired`, `decided` or still `pending` is skipped, so a
   resolution is applied once however many times the task is claimed. `resolve` does the status
   change of an approval (the grant reopens the task `pending`, a denial fails it, a changed check
   ends it) and stamps the record when nothing is left for the claim: a denial, a changed check,
   a wait in the turn and a parked call, whose grant the hop reads from the approval store (item 7
   of "Parked approvals"). The inbox's `approved ready` state reads the same two places: an
   unspent pre-grant of the task, or a resolved approval not yet stamped.

## Interface Contracts

This spec defines behaviour only; the CLI surface that triggers it (`docket task retry <task-id>`,
`docket run [--pipeline <file>] [--var k=v] [--resume] [--timeout <seconds>] [--dry-run]`,
`docket start --dispatch`) is documented in `cli-interface.spec.md`. The persisted run-registry
record each invocation of this pipeline creates (`docket log`, `GET /runs`), including its `pids`
field and the `"cancelled"` state `docket task cancel <ref>` produces, is documented in
`serve-read-api.spec.md`/`cli-json-shapes.spec.md`.

### Trace events this pipeline emits

```text
session_start                # once, at the start of dispatch_task; carries whether this is a resume
context_composed             # before each hop's turn: composed-prompt byte accounting
tool_call                    # the hop marker, before each hop's run_turn attempt
hop_started                  # after the hop marker, before the turn: task/step/role/member/model
hop_retry                    # before each retry attempt of a retryable failure
tool_result                  # after a successful hop; also {"verification": "passed"|"skipped", ...}
                             #   for a gate command that passed or a mechanical gate with no command
error                        # after a failed hop (in place of tool_result)
cost_charged                 # after any hop with nonzero cost
hop_finished                 # after the hop's closing events, before the hop is persisted
guardrail_check              # a pre_output policy verdict other than allow on a hop's output
guardrail_block              # a pre_output block failed the hop
budget_exceeded              # the budget gate blocked a hop (task -> blocked)
budget_warning               # action "unpriced_model": the hop's model has no price, so the cap
                             #   cannot stop it; the hop runs (cost-tracking.spec.md)
verification_failed          # a mechanical or external gate did not pass (any role); an external
                             #   gate's payload carries its label and `source: "task"` for a task gate
rework_started               # a Reviewer REQUEST-CHANGES triggered a bounded rework cycle
review_rejected              # a REQUEST-CHANGES after the rework budget was exhausted
verdict_reasked              # a verdict-gated hop's reply had no marker; one more request was sent
reviewer_verdict_unparseable # the Reviewer's reply had no marker, even after the re-ask
verdict_rework_started       # another role's verdict gate triggered a rework cycle
verdict_rejected             # another role's verdict matched but was neither pass nor rework
verdict_unparseable          # another role's verdict gate found no recognized marker
route_taken                  # a step's own `on` map resolved an outcome (naming step/outcome/target)
stale_claim                  # the crash sweep failed a running task whose claim went stale
dispatch_refused             # a DispatchError on the claimed-task path settled the task as failed;
                             #   also a claim-time refusal (base_ref, pipeline, prepare), payload `reason`
paused_refused               # a claim attempt was refused because the pod's Lead is paused
approval_required            # a require_approval gate or a parked call fired (task -> waiting_approval); names the escalation
approval_resumed             # a granted approval moved the task on (pending, or done for check_changed)
approval_task_denied         # a denied approval failed the task terminally
approval_unused              # a hop ended ok without issuing the call a person approved for it
session_end                  # once, at the end of dispatch_task, carrying the final status
run_cancellation_observed    # once when execution first observes the persisted run request
run_cancelled                # once when execution has fully stopped and terminalizes the run
step_skipped                 # a `when` predicate was false; the step advanced with no hop
command_step                 # a `run` step executed (or was refused), carrying its exit code
escalation_asked             # a pause was opened (operator-loop.spec.md area 11 item 11); with
escalation_delivered         #   escalation_resolved, escalation_expired and escalation_decided
escalation_resolved          #   these five describe every park of a task
escalation_expired
escalation_decided
prepare                      # a claimed task's worktree was prepared (command, source, cacheHit, seconds, exit)
```

## Examples

The CLI output below is the plain console voice (`ok`, `!`, `x`, `->`) a piped `docket` prints; the
`Next:` line goes to stderr.

### A lean pod (Lead + Implementer, no `verifyCmd`) completing normally

```text
$ docket run
-> Running 1 pending task(s) through: lead → implementer
verification skipped — verifyCmd not set for myapp-implementer
ok   [task-3f2a1c9e-...] done — 2 hop(s)
ok 1 done · 0 failed · 6.1k tokens (~$0.00 est.)
-> Next: docket status
```

### A full pod stopped by an exhausted rework budget

```text
$ docket run
-> Running 1 pending task(s) through: lead → implementer → reviewer
x   [task-91a2c410-...] failed — reviewer rejected after 1 rework cycle(s): REQUEST-CHANGES
x 0 done · 1 failed · 18.4k tokens (~$0.00 est.)
-> Next: docket inbox
```

(The command exits 1 because the run ended `failed`; a run whose task ends `blocked`,
`waiting_approval` or `waiting_input` exits 0 -- see `cli-interface.spec.md`.)

### A Reviewer REQUEST-CHANGES driving one rework cycle, then approving

```text
$ docket run
-> Running 1 pending task(s) through: lead → implementer → reviewer
ok   [task-7c1e2b90-...] done — 5 hop(s)
ok 1 done · 0 failed · 31.0k tokens (~$0.00 est.)
-> Next: docket status
```

(`hops[]` for this task shows: lead, implementer, reviewer [REQUEST-CHANGES], implementer [rework],
reviewer [APPROVE] -- five hops, because the one rework cycle re-ran the Implementer
and Reviewer once each.)

### A pod blocked on budget, auto-paused, then resumed

```text
$ docket run
-> Running 2 pending task(s) through: lead → implementer
  Pod budget cap: $5.00 (estimate so far ~$0.00, no cost recorded)
!   [task-c410e91a-...] blocked — pod budget reached (~$5.12 (estimated — no cost recorded) ≥ $5.00) before implementer
ok 0 done · 0 failed · 1 blocked · 2.3k tokens (~$0.04 est.)
-> Next: docket inbox

$ docket pod set budgetUsd 10
-> Unblocked 1 blocked task(s)
ok Set budgetUsd=10.0 for pod 'myapp'
-> Next: docket pod show
```

(The second task was never claimed: after a budget `blocked` result `dispatch_pod` stops the run, and the
Lead stays paused. A positive new cap re-queues the blocked task and clears the pause;
`docket run --resume` does the same without changing the cap.)

### A crashed dispatch resumed

```text
$ docket run --resume
-> Running 0 pending, 0 resumable, 1 running (reclaimed only if the claim is stale) task(s) through: lead → implementer → reviewer
ok   [task-a1b2c3d4-...] done — 3 hop(s)
ok 1 done · 0 failed · 9.7k tokens (~$0.00 est.)
-> Next: docket status
```

(The dispatcher that claimed the task is gone, so `--resume` settles its claim `stale_claim`,
reclaims it, and continues from its last persisted hop: the Implementer hop that completed before the
crash is not re-invoked, and the run continues from the Reviewer.)

### A pipeline `approval` step, granted, then continued

The pod's pipeline declares `gate: {type: approval}` on its implementer step.

```text
$ docket run
-> Running 1 pending task(s) through: lead → implementer
!   [task-9a1b2c3d-...] waiting_approval — approval required before implementer hop (escalation=esc-...)
ok 0 done · 0 failed · 1 waiting · 1.8k tokens (~$0.00 est.)
-> Next: docket inbox

$ docket task answer task-9a1b2c3d --option approve_once
ok Approved task-9a1b2c3d-4e5f
-> Next: docket run --pod myapp

$ docket run
-> Running 1 pending task(s) through: lead → implementer
ok   [task-9a1b2c3d-...] done — 2 hop(s)
ok 1 done · 0 failed · 5.2k tokens (~$0.00 est.)
-> Next: docket status
```

(The Lead hop that completed before the gate fired is not re-invoked; `docket task answer` moves the
task back to `pending`, and the *next* `docket run` continues from the Implementer -- the exact hop
the gate stopped it on.)

### The same gate, denied instead

```text
$ docket task answer task-9a1b2c3d --option deny --reason "touches production"
ok Denied task-9a1b2c3d-4e5f; the action is blocked
```

(The task is now `failed`, `failureKind: "approval_denied"`, reason `approval denied: touches
production`, immediately -- no further dispatch run is needed to observe this; a later `docket run`,
with or without `--resume`, will not touch it again. `docket task retry` can put it back on the
queue.)

## Validation

### Pre-conditions

- The target project **MUST** have a provisioned pod with at least a Lead.
- The task **MUST** already be queued and eligible for claim (`pending`, or `failed` with a
  `RESUMABLE_FAILURE_KINDS` kind when `--resume` is passed).

### Post-conditions

- After a claim, the task's `status`, `startedAt`, `claimedAt` and `claimPid` **MUST** be
  persisted to the pod's `TASK_LIST.json` before the first hop runs.
- After each hop, that hop's record (including `attempts`) **MUST** be persisted and `claimedAt`
  refreshed, before the next hop is attempted.
- After a run reaches a terminal or waiting state, the task's `status`, `reason`, `hops`, `costUsd`
  and `usage` **MUST** be persisted back.
- A `blocked` task **MUST** stay `blocked` in storage -- it is never rewritten to `pending` by
  `dispatch_pod` itself.
- A gate firing **MUST** persist the task's `pendingApprovalIndex` and the id of its escalation
  before `dispatch_pod` returns, and **MUST** create the approval record and its escalation before
  the task is persisted as `waiting_approval` (never the reverse -- a persisted `waiting_approval`
  task **MUST NOT** exist without a corresponding approval record and escalation).
- After a claim, and after every hop-completion persist and retry-attempt claim refresh, the pod
  Lead's `HEARTBEAT.md` dispatch ledger **MUST** be re-synced from `TASK_LIST.json`'s `running`
  tasks (see "Mechanical HEARTBEAT ledger"); after a task leaves `running`, that same sync **MUST**
  leave its entry removed.
- After each hop, any conversation tracked for that hop's agent **MUST** have its
  `last_message`/`task_ref` refreshed (see "Conversation registry auto-population").

### Invariants

- Dispatch **MUST NOT** cross pods: every hop's member id belongs to the dispatched project's own pod
  -- including every child of a `parallel` group.
- Two concurrent `dispatch_pod` calls against the same pod **MUST NOT** both claim (flip to
  `running`) the same task.
- A gate (budget, require_approval, `mechanical`, `verdict`, `external`) **MUST NOT** be bypassed by
  an otherwise-`ok` turn -- `ok=True` is necessary but not sufficient for pipeline advancement past a
  gated hop, for any role or archetype, not only the four built-in ones.
- A hop's failure **MUST NOT** be retried unless its `failure_kind` is `timeout` or `daemon_error`.
  Cooperative run cancellation always surfaces as non-retryable `run_cancelled`; a killed external
  subprocess may surface as a non-retryable `nonzero_exit` or negative-signal exit.
- A paused pod's queue **MUST NOT** yield any claim until the pause is explicitly cleared.
- A `waiting_approval` or `waiting_input` task **MUST NOT** be claimable by any `dispatch_pod` call,
  with or without `--resume`, until its approval resolves or its question is answered.
- The gate-override handoff **MUST** be consumed at most once per
  grant: applied and stamped at claim time (the escalation's `appliedAt`), and consumed in memory the first
  time the resumed run reaches that pipeline position -- a later occurrence of the same position
  within the same run (a rework cycle) **MUST** gate again, not skip silently.
- `resolve_plan` **MUST** be deterministic: the same `PipelineSpec` + the same roster + the same
  archetype registry **MUST** always resolve to a byte-identical `ExecutionPlan`, independent of
  wall-clock time, dict-construction order, or which thread calls it -- the property `docket pod plan`,
  `docket run --dry-run` and the real executor rely on to never drift from each other.
- Every hop, gate pass, gate failure, retry, claim, and sweep **MUST** be traceable via
  `docket task trace <ref> --tail` -- nothing in the pipeline is silent (including a skipped
  verification), for any role or archetype.
- Every production pod-turn loop event **MUST** join that same task-wide trace even though its
  messages and measured usage are persisted under a step-scoped history key.
- Cancelling a run (`docket task cancel`) **MUST** kill a hop's entire registered process group,
  never leave an orphaned child process running after the cancellation lifecycle reaches full stop.
- The HEARTBEAT dispatch ledger sync **MUST NOT** alter any byte outside its own delimited region --
  an agent's own prose anywhere else in `HEARTBEAT.md` survives every dispatch-driven rewrite.
- The ledger **MUST** always equal the pod's current `running` task ids -- never a superset (a stale
  entry for a finished task) or a subset (a running task missing its entry) once a sync has run
  against current state.

## Implementation

The dispatch state machine, by module (public names first, then private ones for orientation):

- `src/docket/tasks/application/queue.py`: `enqueue_task_once`,
  `validate_task_options`, `RESUMABLE_FAILURE_KINDS`, `pod_full_roster`, `dispatchable_pods`,
  `pod_roster`; the claim (`claim_next_task`, `refuse_claimed_task`,
  `prepare_claimed_task`), `touch_claim`
- `src/docket/tasks/application/repository.py`: `TaskRepository`, the one door to a pod's queue
  (`get`, `list`, `add`, `update`, `update_each`, `claim_next`); `claimable`; `Claim`
- `src/docket/tasks/application/json_store.py`: `JsonTaskStore`, the queue file as `TaskRecord`s
- `src/docket/hops/application/sweep.py`: `dispatch_pod`
- `src/docket/tasks/application/lifecycle.py`: `reclaim_stale_running`, `retry_task`, `cancel_task`,
  `cancel_parked_task`, `task_diff`, `unblock_pod`; `finalize_task`, `_apply_result`,
  `sweep_stale_claims`
- `src/docket/tasks/application/escalations.py`: the escalation opener (`operator-loop.spec.md`
  "Escalations"), called from the five park sites
- `src/docket/tasks/application/actions.py`: `TASK_GRANT_CAP`, `resolve_waiting_approval`,
  `resolve_waiting_approval_detail`
- `src/docket/tasks/domain/task.py`: `DispatchError`, `TaskRestrictionError`, `TaskRunRefusal`,
  `TaskNotFoundError`, `HopResult`, `TaskResult`, `TaskRecord`
- `src/docket/teams/settings.py`: `pod_task_list_path`, `DEFAULT_TIMEOUT`, `pod_budget`,
  `pod_max_rework_cycles`, `pod_turn_timeout`, `pod_verify_timeout`, `pod_approval_mode`,
  `pod_approval_mode_is_set`, `pod_recorded_cost`
- `src/docket/hops/application/steps.py`: `PIPELINE_ORDER`, `TASK_PIPELINE_NAME`,
  `pod_pipeline`, `effective_pipeline`, `effective_pipeline_source`, `unpriced_budget_models`;
  the step loop's `_run_command_step`, `_run_input_step`
- `src/docket/hops/application/executor.py`: `dispatch_task`; the step loop's `_run_pipeline`,
  `_run_group_node`, `_step_skipped`, `_route_outcome`
- `src/docket/hops/application/runner.py`: `step_session_key`; the hop's `_run_hop_turn`,
  and the step loop's `execute_unit`
- `src/docket/hops/application/compose.py`: the hop's `_compose_hop`, `_hop_message`,
  `_gate_failed_section`
- `src/docket/tasks/application/record.py`: `hop_env`; `persist_hop_and_trace`, `persist_hop`,
  `verdict_event_names`, resume (`replay_pipeline_position`,
  `_group_complete`)
- `src/docket/hops/gates/pre_hop.py`: `pod_gating_cost`; gates (`_gate_budget`,
  `_gate_pre_hop_approval`, `_pipeline_step_requires_approval`, `_check_brief_resources`,
  `_park_if_check_changed`)
- `src/docket/hops/gates/post_hop.py`: gates (`_evaluate_mechanical_gate`,
  `_evaluate_external_gate`, `_evaluate_verdict_gate`); the hop's `_task_command_env`,
  `_run_in_envelope`
- `src/docket/teams/workspace/worktree.py`: the claim's `ensure_task_worktree`, which returns the worktree record or a refusal and
  never touches the queue; `trusted_worktree_dir`; the hop's
  `hop_diff_probe` (it takes the task's id, description, worktree directory and base commit, not
  the record), `_pin_hop_tree`
- `src/docket/pipeline/domain/plan.py`: `resolve_plan`, `resolve_gate`, `parse_verdict`,
  `normalize_values`, `render_plan`, `run_group`, `ExecutionPlan`, `PlannedUnit`, `PlannedGroup`,
  `DEFAULT_MAX_PARALLEL_WORKERS`, `trace_write_lock`
- `src/docket/pipeline/domain/spec.py`: `PipelineSpec`, `default_pipeline`, `load_pipeline`,
  `MechanicalGate`, `VerdictGate`, `ApprovalGate`, `ExternalGate`, `resolve_variables`,
  `unresolved_step_variables`
- `src/docket/tasks/domain/options.py`: `validate_task_options`, `TaskOptions`, `TASK_STATUSES`
- `src/docket/tasks/domain/refs.py`: `resolve_task`, `TaskRef`, `TaskRefError`, `SHORT_ID_LEN`
- `src/docket/teams/pod.py`: `PodSettings` (`KEYS`, `RECORDED_KEYS`, `load_for`, `coerce`,
  `value_and_source`), `PodSettingsError`, `pod_of`, `members_of`, `member_id`, `session_key`,
  `resolve_member_cwd`, `bound_pipeline_path`, `effective_network`, `effective_read_only`
- `src/docket/tasks/application/answers.py`: `answers_of`, `consult_note`;
  `src/docket/hops/application/resolutions.py`: `apply_resolutions`
- `src/docket/hops/application/interruptions.py`: `record_pregrant`, `forecast`, `InterruptionsError`
- `src/docket/kernel/handoff.py`: `HandoffArtifact` (`DROP_ORDER`, `render`, `dropped`,
  `from_output`), `parse_brief`, `render_brief`, `cap_diff`
- `src/docket/agent/context.py`: `compile_artifact`, `budget_for_role`, `hop_share`,
  `estimate_tokens`, `SUMMARY_TRUNCATION_MARKER`
- `src/docket/teams/workspace/repo_map.py`: `render_repo_map`, `task_root_block`
- `src/docket/teams/roles.py`: `load_registry`, `resolve_hop_instruction`, `registry_for_role`,
  `BUILTIN_TOOL_KINDS`
- `src/docket/teams/blueprints.py`: `get_blueprint`
- `src/docket/tasks/application/evidence.py`: `task_evidence`, `EVIDENCE_V1_1`, `HopEvidence`,
  `TaskEvidence`, `EvidenceNotFound`
- `src/docket/teams/workspace/prepare.py`: preparation resolution, cache and record (`resolve`,
  `needs_prepare`, `prepare_worktree`, `linked_entries`)
- `src/docket/kernel/protected_paths.py`: `changed_protected`, `check_pattern`, `MAX_LISTED_PATHS`
- `src/docket/teams/agent_memory.py`: `sync_dispatch_tasks`, `read_dispatch_task_ids`,
  `DISPATCH_BLOCK_BEGIN`/`DISPATCH_BLOCK_END`
- `src/docket/teams/conversations.py`: `touch_for_hop_durable`, `prune_closed_durable`
- `src/docket/tasks/application/runs.py`: `execute`, `create_run`, `cancel_run`, `current_run_id`,
  `add_hop_pid`, `remove_hop_pid`, `prune_terminal`
- `src/docket/governance/approval.py`: `approval_create`, `approval_grant`, `approval_deny`,
  `expire_approval`, `prune_unconsumed_pregrants`, `create_pregrant`, `prune_resolved`
- `src/docket/pipeline/application/schedule.py`: `set_schedule`, `unset_schedule`, `find_schedule_problems`,
  `describe_spec_error`, `load_schedules`, `load_last_run`, `is_schedule_due`
- `src/docket/agent/loop.py`: `run_agent_turn` (`trace_task_id`),
  `approval_unavailable_error`, `approval_parked_error`, the cooperative cancellation checks
- `src/docket/agent/ports.py`: `RuntimeDriver`, `TurnResult`
- `src/docket/kernel/operator_contract.py`: `Question`, `TaskBrief`, `validate_answer`,
  `canonical_args_digest`, `a2a_state`
- `src/docket/governance/security.py`: `classify_command`
- `src/docket/teams/pod_provisioning.py`: `provision_task_worktree`, `prune_task_worktrees`,
  `teardown_member`
- `src/docket/hops/application/driver.py`: `DocketDriver`, `default_driver`,
  `resolve_command_jail`, `PIPELINE_WORKTREE_ENV` and the other internal coordinates
- `src/docket/sandbox/launch.py`: `run_command`, `task_environment`, `cache_environment`
- `src/docket/platform/process.py`: `process_alive`, `kill_process_group`
- `src/docket/platform/git.py`: `trust_worktree`,
  `git_worktree_add`, `git_commit_all`, `git_snapshot_commit`, `git_changed_files`,
  `git_current_branch`, `git_merge_base`, `git_diff_stat`, `git_diff_names`, `git_ls_files`
- `src/docket/platform/store.py`: `read_modify_write`
- `src/docket/tasks/domain/state.py`: `Status`, `FailureKind`, `decide`; `src/docket/tasks/application/transitions.py`: `apply_to_task`
- `src/docket/kernel/home.py`: the `Home` members `claim_stale_timeout`, `dispatch_retries_default`,
  `dispatch_retries_per_role`, `dispatch_retry_backoff_s`, `dispatch_retry_max_wait_s`,
  `dispatch_turn_timeout_s`, `dispatch_verify_timeout_s`, `dispatch_sweep_workers`,
  `handoff_diff_max_chars`, `repo_map_max_chars`, `context_bytes_per_token`,
  `verify_evidence_tail_chars`, `prepare_timeout_s`, `trace_retention_s`, `pod_cache_dir`
- `src/docket/interfaces/http/server.py`: the periodic sweep (`_run_sweeps`, `_sweep_one_pod`,
  `_abandon_sweeps`)
- `src/docket/interfaces/http/sweeps.py`: `check_schedules`, `SWEEP_ABANDON_WAIT_S`
- `src/docket/interfaces/http/routes/dispatch.py`: `POST /dispatch/<project>`
- `src/docket/interfaces/http/routes/escalations.py`: `POST /escalations/<id>`
- `src/docket/interfaces/http/routes/tasks.py`: `GET /tasks/<pod>/<id>/evidence`
- `src/docket/interfaces/cli/commands/run.py`: `docket run`
- `src/docket/interfaces/cli/commands/task.py`: `docket task add|retry|cancel|answer|pregrant|prune|show`
- `src/docket/interfaces/cli/commands/pod.py`: `docket pod set|unset` (pipeline and schedule paths, budget re-queue)
- `src/docket/interfaces/cli/commands/pod_config.py`: `docket pod plan|validate`
- `src/docket/interfaces/cli/render/progress.py`: the `docket run` progress view's in-place approval prompt
- `src/docket/interfaces/cli/commands/setup_check.py`: the ledger and schedule checks of `docket setup`
- `src/docket/interfaces/cli/commands/mcp.py`: the MCP `dispatch`, `delegate`, `queue` and `approvals_*` tools
- `scripts/gen_evidence_schema.py`: the evidence schema generator (`--check` in CI)
