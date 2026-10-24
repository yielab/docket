# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> **Active: Phase 49** (D-70, ROADMAP §6; planned 2026-10-24 on a maintainer request): the task as
> a typed record behind one store. Cards P49-1..5 below run in order; P49-4 alone has three parallel
> lanes. The integration branch is `plan/phase-46-structure` until the maintainer merges it.

## ▶ PHASE 49 — ACTIVE (planned 2026-10-24, none started) — the task as a typed record behind one store (D-70)

**Why now, measured on 2026-10-24 (branch `plan/phase-46-structure`, `e8a56f2b`):**

| Measure | Value |
| --- | --- |
| Top-level keys of a task record (`TASK_LIST.json`, `{"tasks": [...]}`) | 44, plus about 50 inside nested dicts |
| `read_modify_write` closures that write the queue | 25, in 9 modules; 4 of them outside `tasks/` (`hops/application/{answers,interruptions,executor}.py`, `teams/workspace/worktree.py`) |
| Modules that read task fields as `dict.get` | about 30 (`hops`, `teams`, `operator`, `interfaces/cli`, `interfaces/http`, `interfaces/telegram`) |
| Find-by-id loops over the list | 13 inside closures, 7 more in readers |
| Keys written that nothing in `src/` reads | 7: `claimId`, `source`, `pipelineSource`, `gateApplied`, `checkChanged`, task-level `usage`, `worktree.fallbackReason` (Tack reads `checkChanged` and `usage`; the specs name the other three) |
| Places the record's defaults live | 3 (`_TASK_SCALAR_DEFAULTS`, the literal in `enqueue_task_once`, `_normalize_task`) |
| Test files that touch the queue file or its dicts by hand | 43 (33 write the JSON; 39 index `read_tasks()` as dicts) |

Every change to the task's shape is paid once per reader; this phase makes the shape one type.

**What stays the same:** the JSON on disk (same keys, `null` where `null` is today, absent where
absent is today, except the two deleted keys), the HTTP API 6 bodies (`GET /tasks/<pod>` dumps the
record), the CLI `--json` shapes, the goldens, the per-hop persistence and the lock discipline
(one `read_modify_write` per write, nothing that reads the Lead's meta inside the closure).

**What is deliberately not built:** a nested record (D-68), a `Protocol` for the store with fakes
(72 test files use the real queue on the test home), a unit of work (per-hop persistence is the
crash contract), an `on_saved` hook (the ledger sync is one direct call), a shared pydantic base
model or alias generator (the repo writes aliases by hand), the queue's move to
`workspaces/pods/<pod>/` (after this phase it is one function, `TaskRepository.for_pod`, and a
separate decision).

**Token discipline for every card.** The model writes what needs judgement; a tool enumerates and
rewrites what is mechanical; `mypy` and `pytest` output is the work queue. Never read a whole
module to find a closure: `rg -n "read_modify_write|\.get\(\"" <file>` and `Read` by line range.
`uv run mypy src 2>&1 | rg "TaskRecord|HopResult" | cut -d: -f1 | sort | uniq -c | sort -rn` is the
remaining-work list after P49-1. One throwaway script at most per card, one fix to it at most, then
by hand (rule 5.8 above).

**Order and contention:** P49-1 → P49-2 → P49-3 → P49-4 (lanes A ∥ B ∥ C, disjoint directories)
→ P49-5. P49-2 and P49-3 both touch `hops/application/sweep.py` (the claim's consumer), so they are
sequential. No other active lane exists.

**Spec owners:** `specs/functional/pod-dispatch.spec.md` (record keys, claiming, status vocabulary),
`specs/api/operator-api.spec.md` (`GET /tasks/<pod>` status filter), `specs/data/cli-json-shapes.spec.md`
("Task options on the queue record"), `specs/data/serve-read-api.spec.md` (unchanged unless a key moves).

### P49-1 — `TaskRecord`, `HopResult` as a model, the JSON store and the pod repository

**Status:** TODO · **Size:** L · **Model:** Sonnet · **Kind:** M + T (behaviour: two keys and one status value deleted)

- **Trigger:** the table above; this card is the type and the door, with no caller moved yet.
- **Read list:** this card; `src/docket/tasks/domain/{task,state,options}.py`;
  `tasks/application/transitions.py`; `tasks/application/record.py:64-128` (`hop_record`,
  `hop_from_record`); `platform/store.py::read_modify_write`;
  `tests/architecture/{test_status_writers,test_import_contracts}.py`; `tests/unit/tasks/domain/test_task.py`;
  pod-dispatch spec §"Task lifecycle and identity" items 1-3, §"Claiming", §"Task status vocabulary".
- **Goal.** Three new modules and two amended ones; nothing outside `tasks/` changes except the two
  test files named in step 3 and the specs.
  1. **`tasks/domain/parts.py`** (new): the nested shapes as pydantic models, each
     `extra="forbid", populate_by_name=True`, camelCase `Field(alias=...)` by hand, each copied
     from its writer: `Worktree` (`dir, branch, base_commit`; optional `base_ref, git_dir,
     common_dir, fallback_reason, pruned_at`; `teams/task_worktrees.py:40-45`), `Prepared`
     (`command, source, lock_hash, cache_hit`; `teams/workspace/prepare.py::record`), `Answer`
     (`hops/application/answers.py:157-171`), `ConsultAnswer` (`step, question_id, text`), `Grant`
     (`token, tool, args_digest`), `TaskGrant(Grant)` (`role, granted_at, actor, channel`;
     `tasks/application/actions.py:194-204`), `TaskUsage` (`input, cached, cache_write, output`,
     `by_model: dict[str, UsageTotals]`; `lifecycle.py:94-102`).
  2. **`tasks/domain/task.py`**: `HopResult` becomes a pydantic model with every field kept:
     aliases `member` (for `member_id`), `stepId`, `costUsd`, `nextStep`, `repoFiles`;
     `verification_skipped = Field(False, exclude=True)`; a `model_validator(mode="after")` that
     backfills `artifact` from `output` (today's `__post_init__`); `field_serializer`s so the dump
     equals today's `hop_record` (`stepId = step_id or role`, `costUsd` rounded to 6, `repoFiles`
     `None` when empty); `field_validator(mode="before")` on `artifact`, `verify`, `evidence`,
     `usage`, `trace`, `repo_files` that turn an invalid value into the default, as
     `hop_from_record` degrades each alone today (one old bad hop must not refuse the task).
     `TaskResult` stays a dataclass. Then `TaskRecord(BaseModel)`, flat, `extra="forbid"`,
     `populate_by_name=True`, with exactly these fields (alias in parentheses when it differs):
     - request: `id` (default `ids.new_id("task")`), `description: str`, `priority: str = "normal"`,
       `created` (default `clock.iso()`), `channel: str`, `brief: TaskBrief | None`,
       `external_ref` (`externalRef`), `idempotency_key` (`idempotencyKey`), `base_ref` (`baseRef`),
       `pipeline`, `gate: TaskGate | None`, `max_tokens` (`maxTokens`), `prepare`,
       `restrictions: TaskRestrictions | None`;
     - lifecycle: `status: Status = Status.pending`, `started_at` (`startedAt`), `completed_at`
       (`completedAt`), `claimed_at` (`claimedAt`), `claim_pid` (`claimPid`), `reason: str = ""`,
       `failure_kind` (`failureKind`), `blocked_reason` (`blockedReason`), `approval_token`
       (`approvalToken`), `pending_approval_index` (`pendingApprovalIndex`),
       `gate_override_pipeline_index` (`gateOverridePipelineIndex`), `question: QuestionV11 | Question | None`,
       `consult_answer: ConsultAnswer | None` (`consultAnswer`);
     - execution: `hops: list[HopResult] = []`, `cost_usd: float = 0.0` (`costUsd`),
       `worktree: Worktree | None`, `prepared: Prepared | None`, `pipeline_spec: dict[str, Any] | None`
       (`pipelineSpec`; the domain may not import `pipeline`, so it stays a validated-at-use dict),
       `pipeline_source` (`pipelineSource`), `gate_applied: bool | None` (`gateApplied`),
       `usage: TaskUsage | None`, `check_changed: list[str]` (`checkChanged`), `consultations: int = 0`,
       `answers: list[Answer] = []`, `pregrants: list[Grant] = []`, `task_grants: list[TaskGrant] = []`.

     **The absent-vs-null rule, one rule for the whole record.** Today two classes exist and 18
     tests pin the second: (a) always present, `null` when unset: `startedAt`, `completedAt`,
     `claimedAt`, `approvalToken`, `pendingApprovalIndex`, `gateOverridePipelineIndex` → plain
     `X | None = None`; (b) absent until written and absent again after a drop: `question`,
     `failureKind`, `blockedReason`, `claimPid`, `consultAnswer`, `taskGrants`, `checkChanged`,
     `worktree`, `prepared`, `pipelineSpec`, `pipelineSource`, `gateApplied`, `brief`, `gate`,
     `usage`, `restrictions`, and every request option → `Field(None, alias=..., exclude_if=lambda v:
     v is None)`; lists in class (b) use `exclude_if=lambda v: not v`. Never `exclude_none` or
     `exclude_unset` globally. `Field(exclude_if=...)` needs pydantic 2.12: raise the floor in
     `pyproject.toml` from `>=2.11` to `>=2.12` in this card (the floor CI job installs it).
     Properties on `TaskRecord`: `worktree_dir -> str` (the `worktree.dir` of a record whose worktree
     is present and not pruned, else `""`), `is_terminal` (via a new `Status.TERMINAL` frozenset
     equal to `decide`'s settle targets minus `waiting_input`/`waiting_approval`/`blocked`),
     `approved_ready` (`status == pending and (pregrants or gate_override_pipeline_index is not None)`,
     today `interfaces/cli/commands/status.py:65` and `inbox.py:46`), `question_is_consultation`
     (`question.kind in ("clarification", "decision")`, today in three places). Delete
     `_TASK_SCALAR_DEFAULTS`, `_normalize_task`, `Status.in_progress`, and the `claimId` and
     `source` keys (nothing reads them; `claimPid` + `claimedAt` detect a stale claim).
  3. **`tasks/domain/state.py`**: `decide()` returns `fields`/`drop` by field name
     (`started_at`, not `startedAt`). **`tasks/application/transitions.py::apply_to_task(record:
     TaskRecord, to, **facts)`**: `setattr(record, name, value)` for each field, `setattr(record,
     name, None)` (or `[]` for a list) for each dropped one, and the one explicit
     `record.status = transition.to`. In `tests/architecture/test_status_writers.py`,
     `_is_status_target` also accepts an `ast.Attribute` with `attr == "status"` whose value is a
     `Name` in `RECEIVERS` (add `"record"`), and `test_the_scan_sees_a_stray_writer` plants
     `t.status = ...`; `BASELINE` stays 1.
  4. **`tasks/adapters/json_store.py`** (new; `test_import_contracts.py:295` already allows it):
     `JsonTaskStore(path)` with `load() -> list[TaskRecord]` and
     `modify(fn: Callable[[list[TaskRecord]], bool]) -> list[TaskRecord]`: one `read_modify_write`,
     validate the list, run `fn`, write `{"tasks": [r.model_dump(by_alias=True, mode="json") ...]}`
     only when `fn` returned `True`. Imports `kernel`, `platform`, `tasks.domain` only. No
     `tasks/ports.py` (one implementation); amend that line of ADR 0030's target tree in the same commit.
  5. **`tasks/application/repository.py`** (new): `TaskRepository.for_pod(project)` (path from
     `teams/settings.pod_task_list_path`, Lead id from `teams/pod.member_id`) with `get(task_id)`,
     `list()`, `add(record) -> tuple[TaskRecord, bool]` (idempotency by `idempotency_key` inside the
     lock, as today's closure), `update(task_id, fn) -> TaskRecord | None` (`fn` mutates under the
     lock; written back; `None` when absent), `update_each(fn) -> list[TaskRecord]` (`fn(record) ->
     bool`; one write if any `True`), `claim_next(*, resume, skip=frozenset()) -> Claim | None`
     (today's pick and `apply_to_task(running)`, then the stored `gate_override_pipeline_index` is
     cleared; `Claim` is a frozen dataclass `(record, resume_hops, gate_override_index)` so the
     override is explicit instead of a copy that differs from disk). After every write, one
     `teams/agent_memory.sync_dispatch_tasks(...)` with the dumped records (today 8 sites repeat it
     and 17 writers never sync: the one behaviour change, pinned in step 6). Docstring rule from
     `hops/application/answers.py:319-325`: `fn` runs under the Lead directory's lock, so it must not
     call `load_pod_settings`, `meta_get` or anything reading that directory. No caller moves in
     this card: `queue.read_tasks` and every closure keep working on dicts.
  6. **Tests** (unit lane, each new module mirrored: `tests/unit/tasks/domain/test_parts.py`,
     `tests/unit/tasks/adapters/test_json_store.py`, `tests/unit/tasks/application/test_repository.py`;
     `test_task.py` rewritten for the model):
     - **Round trip on a real queue, the oracle for "same JSON"** (integration lane, it reads
       files: `tests/integration/tasks/test_task_record_round_trip.py`). The fixtures are committed:
       `tests/fixtures/task-records/task_list_2026-10-24.json` (35 scrubbed real records from two
       pods: `waiting_input`, `waiting_approval`, `done`, `failed`, `cancelled`; `question`, `brief`,
       `gate`, `restrictions`, `consultations`, `pregrants`, `prepared`, `usage`, `worktree`) and
       `task_list_2026-10-24.normalized.json` (what
       `read_tasks()` returned for it at `e8a56f2b`, minus `claimId` and `source`). The test loads
       the first with `JsonTaskStore.load()` and asserts each record's dump equals the second,
       record by record.
     - `HopResult`: today's `test_task.py` cases, plus a hop with `"artifact": "garbage"` loading
       with `artifact` rebuilt from `output`.
     - `decide`/`apply_to_task`: the table test on a `TaskRecord`; a dropped field is `None` after
       and absent from the dump.
     - `JsonTaskStore.modify`: `fn` returning `False` leaves the bytes unchanged; two concurrent
       `modify` calls serialize (the claim-race pattern in `tests/unit/tasks/application/test_queue.py`).
     - `TaskRepository`: `add` twice with one `idempotency_key` → `created=False`; `update` on an
       unknown id → `None`, nothing written; `claim_next` returns the override and the stored record
       has it cleared; after `update`, the Lead's `HEARTBEAT.md` lists the running task.
     - Architecture: new `tests/architecture/test_task_queue_writers.py`: every module under
       `src/docket` naming `pod_task_list_path(` with `read_modify_write(` or `read_json(`, or
       defining `_normalize_task`, `hop_record` or `hop_from_record`, must be in
       `task_queue_writers_baseline.txt` (written once: today's 9 modules plus the store; shrinks per
       card); a planted writer fails it (prove once, do not commit the plant).
  7. **Specs and docs, same commit as the deletion:** pod-dispatch §"Task lifecycle and identity"
     items 1-3 and §"Claiming" (no `claimId`, no `source`; `channel` stays), §"Task status
     vocabulary" and line 1917 (no `in_progress`); operator-api line 139 (`in_progress` leaves the
     filter; `400` like any unknown value); bump versions per `specs/README.md`; `CHANGELOG.md`
     "Removed" lines; `rg -n claimId docs` and fix what prints a record.
- **Steps, each green and committed:** (1) `parts.py` + tests; (2) `HopResult` as a model, with
  `hop_record`/`hop_from_record` delegating to it until P49-2 deletes them; (3) `TaskRecord` + the
  spec amendments + the positional `HopResult(...)` calls in `tests/unit/tasks/domain/test_task.py:201-218`
  and `tests/integration/tasks/test_dispatch_heartbeat_and_conversation_sync.py:250-251` made
  keyword calls; (4) `decide`/`apply_to_task` + the scanner; (5) `json_store.py`; (6) `repository.py`;
  (7) the architecture guard and its baseline; (8) the round-trip test and the pydantic floor.
- **Non-goals:** moving any caller (P49-2..4); the `TaskReader` port in `operator/` (stays dicts);
  deleting any other key (`pipelineSource`, `gateApplied` are spec contract).
- **Acceptance:** the four unit files and `tests/architecture` green; the round trip green on all
  30 records; `status_writers` at 1 with the attribute scan proven on a plant;
  `rg -n "in_progress|claimId|\"source\"" src specs` finds only hop-verify payloads and the runs'
  `source`; `uv run mypy src` clean; `pytest --co` count not lower.
- **Gate:** `uv run pytest tests/unit/tasks tests/architecture tests/integration/tasks/test_dispatch_heartbeat_and_conversation_sync.py -q`.

### P49-2 — the writers in `tasks/application` go through the repository

**Status:** TODO after P49-1 · **Size:** M · **Model:** Sonnet · **Kind:** M (one behaviour change: the ledger syncs on every write)

- **Trigger:** 15 of the 25 closures live in `tasks/application`; after this card the module that
  owns the task is the only one that still writes it by hand nowhere.
- **Read list:** this card; P49-1's `repository.py` and `task.py` (signatures only);
  `rg -n "read_modify_write|_normalize_task|hop_record|hop_from_record|read_tasks\(" src/docket/tasks src/docket/teams/workspace/worktree.py src/docket/hops/application/sweep.py`
  and `Read` each hit by range, never the whole file.
- **Goal, closure by closure** (file:function → repository call; keep each body, drop the loop):
  - `queue.py`: `enqueue_task_once` (build a `TaskRecord(...)` directly from the validated inputs,
    `brief=parsed_brief`, `**parsed_options.model_dump()` by field name; `repo.add`) ·
    `apply_transition` (`repo.update(task_id, lambda r: apply_to_task(r, to, **facts))`) ·
    `_store_prepared` (`repo.update`) · `claim_next_task` (`repo.claim_next`; then the worktree:
    `teams/workspace/worktree.py::ensure_task_worktree` **returns** `(worktree: dict | None,
    refusal: tuple[str, str] | None)` and no longer writes the queue (teams is below tasks and may
    not import the record); `claim_next_task` validates it into `Worktree`, stores it with
    `repo.update`, and returns a `Claim` that also carries `refusal`; `hops/application/sweep.py:91`
    reads `claim.refusal` instead of popping `claimRefusal`) · `touch_claim` (`repo.update`) ·
    `_task_record` → `repo.get` · `read_tasks(project)` keeps its name and dict return for this card
    only: `[r.model_dump(by_alias=True, mode="json") for r in repo.list()]`, so P49-3/4's readers
    are untouched here.
  - `lifecycle.py`: `finalize_task` (`repo.update` with `_apply_result(record, res, ...)` rewritten
    on attributes; `usage` built as a `TaskUsage`) · `sweep_stale_claims`, `reclaim_stale_running`,
    `unblock_pod` (`repo.update_each`) · `retry_task`, `cancel_parked_task` (`repo.update`) ·
    `cancel_task`, `task_diff` (`repo.get`, attributes, `record.worktree_dir`).
  - `record.py::persist_hop` (`repo.update`: `record.hops.append(hop)`, `cost_usd` recomputed,
    `claimed_at` refreshed); delete `hop_record`/`hop_from_record` and their three callers
    (`answers.py:264`, `lifecycle.py:66`, `queue.py:458` → `claim.resume_hops`), which is why
    `answers.py` gets one line here although it is a P49-3 file.
  - `actions.py::resolve_waiting_approval_detail` (`repo.update_each` with the id-or-token match;
    `pregrants.append(Grant(...))`; `_append_task_grant` appends a `TaskGrant`).
  - `worktree_prune.py::prune_task_worktrees` (`repo.update_each`; delete its private
    `_task_list_file` and its raw `read_json`; use `record.worktree_dir` and `Status.TERMINAL` in
    place of `PRUNABLE_TASK_STATUSES` if the sets are equal, else keep the constant and say why).
  - The 8 hand-written `_mem.sync_dispatch_tasks(...)` calls in these modules go away (the
    repository does it); keep the `_pod_memory.record_task_memory` and audit/trace calls outside
    the closures as they are.
- **Tests:** the existing tests of each function, by path, after each module; one new test in
  `tests/unit/tasks/application/test_queue.py`: `claim_next_task` on a task whose worktree add
  fails with a `baseRef` returns a `Claim` with `refusal` and the stored record has no `worktree`
  (today's `claimRefusal` path); the ledger test from P49-1 extended: `retry_task` now updates
  `HEARTBEAT.md` (it did not before; this is the behaviour change, named in CHANGELOG under
  "Changed").
- **Non-goals:** any reader outside `tasks/application`; `hops` closures (P49-3); the shape of any
  JSON.
- **Acceptance:** `rg -n "read_modify_write\(" src/docket/tasks` matches only `json_store.py`;
  `rg -n "_normalize_task|hop_record|hop_from_record" src tests` is empty; the architecture
  baseline loses `tasks/application/{queue,lifecycle,record,actions,worktree_prune}.py` and
  `teams/workspace/worktree.py` (deletions only); the round-trip test still passes; `uv run pytest
  tests/unit/tasks tests/integration/tasks -q` green.
- **Gate:** `uv run pytest tests/unit/tasks tests/integration/tasks tests/architecture -q`.

### P49-3 — `hops` reads and writes the typed record

**Status:** TODO after P49-2 · **Size:** L · **Model:** Sonnet · **Kind:** M

- **Trigger:** `hops` holds the other 4 writers and the densest readers, all sharing
  `UnitContext.task`; moving the writers without the readers leaves one dict and one model for the
  same task in one run.
- **Read list:** this card; `tasks/domain/task.py` (field names only);
  `rg -n "ctx\.task|task\.get\(|task\[|claimed\.get|read_modify_write\(|read_tasks\(" src/docket/hops`
  and `Read` by range.
- **Goal.**
  - `tasks/application/record.py::UnitContext.task: TaskRecord`; `hops/application/executor.py::dispatch_task(project, task: TaskRecord, *, gate_override_index: int | None = None, ...)`
    (today `_resolve_gate_override(task)` reads the key off the claimed copy; the sweep passes
    `claim.gate_override_index`). `_record_task_run` sets the three attributes on the record it
    holds and persists with `repo.update(task_id, ...)`; `_resolve_task_run`/`steps._task_pipeline`/
    `_task_gate` read attributes (`task.pipeline_spec` is validated with `PipelineSpec.model_validate`
    where it is used, unchanged).
  - `hops/application/answers.py`: `answer_task` → `repo.update` (the body unchanged: the pipeline
    is still resolved before the lock); `sweep_expired_questions` → `repo.update_each`;
    `_parked_task_pipeline` → `repo.get`; `question`, `answers`, `consult_answer`, `hops` by
    attribute (`Answer`, `ConsultAnswer` models). `hops/application/interruptions.py::record_pregrant`
    → `repo.update(..., lambda r: r.pregrants.append(Grant(...)))`.
  - Readers to attributes: `hops/gates/pre_hop.py` (`_current_task` → `repo.get`; `maxTokens`,
    `restrictions`, `consultations`, `description`, `worktree_dir`), `hops/gates/post_hop.py`
    (`gateOverridePipelineIndex` → the ctx field), `hops/domain/gate_decisions.py` (`max_tokens`,
    `hops[].usage`), `hops/application/compose.py` (`description`, `worktree_dir`, `answers`,
    `consult_answer`, `pregrants`, `task_grants`), `driver.py::_base_commit_view`
    (`repo.get(...).worktree`), `runner.py`, `steps.py`, `sweep.py` (`claim.record`, `claim.refusal`),
    `report.py::task_counts` (count by `Status`; delete the `completed` term, which counts a status
    that does not exist), `record.py::build_hop_result`/`persist_hop_and_trace` (`ctx.task`).
  - `tests/support/pods.py:436` (the `UnitContext` helper) and the two tests that construct one take
    a `TaskRecord`.
- **Tests:** the existing `tests/unit/hops`, `tests/integration/hops`, `tests/integration/tasks/dispatch`
  by path as each module lands; one new test: `dispatch_task` given `gate_override_index` skips the
  pre-hop approval at that index once and gates it on the rework revisit (today's behaviour, now
  through the argument); `task_counts` on a queue with every status returns each once and no
  `completed` key.
- **Non-goals:** `interfaces/`, `operator/`, `teams/agent_memory.py` (P49-4); the route resolution
  duplicate (`executor._route_outcome` vs `answers._resolve_route`) stays a follow-up.
- **Acceptance:** `rg -n "read_modify_write\(|read_tasks\(" src/docket/hops` is empty;
  `rg -n '\.get\("(status|hops|worktree|question|pregrants|maxTokens|description)"' src/docket/hops`
  is empty; the architecture baseline loses the three `hops` modules; `uv run mypy src` clean;
  the Phase 46 baseline comparison script's control flow is unchanged on the slow-stub dispatch
  tests (`tests/integration/tasks/dispatch`).
- **Gate:** `uv run pytest tests/unit/hops tests/integration/hops tests/integration/tasks tests/architecture -q`.

### P49-4 — the codemod and the remaining readers, three lanes

**Status:** TODO after P49-3 · **Size:** L (A, B, C each M) · **Model:** Sonnet per lane; the integrator runs the codemod · **Kind:** M

- **Trigger:** after P49-3 every remaining `dict` reader is outside `tasks/` and `hops/`:
  `interfaces/cli/commands/{task,task_render,status,inbox,run,mcp,setup_check,setup_check_budget}.py`,
  `interfaces/http/routes/{tasks,task_create,task_control,health}.py`, `interfaces/telegram/bot.py`,
  `teams/agent_memory.py`, `operator/` (through the `TaskReader` port), and the tests that index
  `read_tasks()` (39 files).
- **Step 0, integrator, one commit before the lanes:** `tasks/application/queue.py::read_tasks`
  is deleted; `TaskRepository.for_pod(project).list()` is the reader. Then the throwaway
  `scripts/maint/task_record_codemod.py` (AST, `libcst` is not a dependency; use `ast` + line edits
  or plain regex on known receivers) rewrites, over `src/` and `tests/`: `X.get("k")` → `X.f`,
  `X["k"]` → `X.f`, `X.get("k", d)` → `(X.f if X.f is not None else d)` for an optional field,
  `"k" in X` → `X.f is not None`, `X.pop("k", None)` → `X.f = None`, for `X` in `task`, `t`,
  `claimed`, `record`, `ctx.task`, `tasks[i]`, and `k` in the 42 keys; a line it cannot rewrite is
  printed with its path. One fix to the script at most; it is not committed. The leftover list,
  split by directory, is each lane's packet, together with
  `uv run mypy src 2>&1 | rg "<lane dirs>"`.
- **Lane A — `interfaces/cli`** (`src/docket/interfaces/cli/commands/{task,task_render,status,inbox,run,mcp,setup_check,setup_check_budget}.py`,
  `tests/unit/interfaces/cli`, `tests/integration/interfaces/test_cli*`): attributes everywhere;
  `status._approved_ready` and `inbox._approved_ready_tasks` → `record.approved_ready`;
  `run.py:251-263` → `queue.has_claimable_work` / `_eligible_for_claim` (one definition);
  `task_render._worktree` → `record.worktree` fields and `worktree_dir`; `--json` output is
  `record.model_dump(by_alias=True, mode="json")` where the spec says the record is printed
  (cli-json-shapes §"docket task list --json", §"docket task show --json": same keys, so the goldens
  stay). `mcp.tool_queue`: the same dump; fix its message that only `blocked` tasks can be retried
  (`retry_task` also takes `failed`).
- **Lane B — `interfaces/http` + `interfaces/telegram`** (`src/docket/interfaces/http/routes/{tasks,task_create,task_control,health}.py`,
  `src/docket/interfaces/telegram/bot.py`, `tests/unit/interfaces/http`, `tests/integration/interfaces/test_serve*`,
  `tests/unit/interfaces/telegram`, `tests/integration/interfaces/telegram`): `GET /tasks/<pod>[/<id>]`
  dumps the record and adds `tokenBudget` (`health._with_token_budget` takes the record);
  `test_serve_tasks_endpoint.py:131-133` (body equals the dump minus `tokenBudget`) is the oracle;
  `task_create` builds its response from the record; the `status` filter rejects `in_progress`
  like any unknown value (operator-api line 139 already amended in P49-1). Telegram `_handle_answer`
  reads `record.question`.
- **Lane C — `teams/agent_memory.py`, `operator`, the rest of `tasks/application`**
  (`src/docket/teams/agent_memory.py::sync_dispatch_tasks` keeps its `Iterable[Mapping]` signature
  and the repository passes dumps; the `TaskReader` adapter bound in `bootstrap.py` returns
  `[r.model_dump(by_alias=True, mode="json") for r in repo.list()]` and `operator/inbox.py` is
  untouched; `tasks/application/{evidence,escalation}.py` and `hops/application/report.py` leftovers
  to attributes; `tests/unit/tasks`, `tests/integration/tasks`, `tests/unit/teams`,
  `tests/unit/operator`, `tests/integration/governance`): the 33 test files that write partial task
  dicts get `tests/support/tasks.py::task(**overrides) -> TaskRecord` (one factory, defaults for
  every field, `put_task` accepts it) and each test sets only what it asserts on.
- **Lane rule:** a lane edits only its directories; a leftover in another lane's file is reported,
  not fixed. Lanes share no spec and no persisted state. Merge order A, B, C; the integrator runs
  the default suite once after the three merges.
- **Tests:** no new behaviour except the MCP message; every lane's existing tests by path; the HTTP
  API 6 tests and the CLI goldens byte for byte.
- **Acceptance:** `rg -n '\.get\("[a-zA-Z]+"\)' src/docket/interfaces src/docket/teams/agent_memory.py`
  finds no task key (the 42-key list is the check); `rg -n "read_tasks\(" src tests` is empty;
  `uv run mypy src` clean; the architecture baseline is `tasks/adapters/json_store.py` alone;
  `bash tests/golden/run.sh verify-all` 9/9.
- **Gate per lane:** its test directories under `timeout 600`; integrator: the full parallel suite once.

### P49-5 — close: measures, specs, the real run

**Status:** TODO after P49-4 · **Size:** S · **Model:** integrator · **Kind:** D

- **Goal:** the phase's own evidence and the gates that run once per phase.
  1. Measures, after vs the table at the top of this section, written to
     `internal-docs/baselines/phase-49/` (gitignored) and the two that matter copied into the
     ROADMAP row: closures on the queue (25 → the store's one), modules naming the queue file (9 →
     1), `isinstance(..., dict)` in `tasks/` and `hops/`, `dict[str, Any]` annotations in `tasks/`
     and `hops/`, net lines (`git diff --shortstat <P49 base>..HEAD -- src`).
  2. ADR 0030: the target tree row for `tasks/` lists `adapters/json_store.py` and no `ports.py`;
     the "What this unlocks after Phase 47" entry for the typed aggregate is marked done by D-70.
  3. `CHANGELOG.md`: Removed (`claimId`, `source`, `in_progress`), Changed (ledger sync on every
     write; `tokenBudget` unchanged), Internal (the record and the store).
  4. Phase-close gates: goldens `verify-all`, `uv run pytest tests/agent`,
     `scripts/maint/pytest-without-sandbox.sh -q` (the 7 parked serial failures are pre-existing;
     any new one stops the close), the escape matrix, `bash scripts/validate-specs.sh`,
     `uv run python scripts/metrics.py --check`, `uv run python scripts/gen_cli_docs.py --check`,
     `split_board.py check`; `CONTRIBUTING.md`'s test count.
  5. The real run: reinstall with `./install.sh`, reset the live queue by hand (the one `fab-dev`
     task carries `claimId` and `source`; D-57, no migration), dispatch one task on `fab-dev`
     against the local endpoint with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`, compare control flow with
     `internal-docs/baselines/phase-47/after/` using the backup's `compare.py`.
  6. Board: archive P49-1..5 with `split_board.py archive`, ROADMAP row to complete, §6 unchanged,
     CLAUDE.md state line.
- **Acceptance:** every gate above green or parked with its line; the real run's status sequence
  matches; the measures table filled.

## How work runs on this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 40 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, `metrics.py --check`, the generated-docs checks and the real run: once, at
      the phase close.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **Nothing is kept for the past** (D-57): no alias,
   re-export, shim or compatibility reader; a replaced name is deleted in the same change.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`;
Phases 46-47 run on `plan/phase-46-structure` until the maintainer integrates it). `main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** Fabulada's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: on a real run, measure which calls repeat before cutting anything.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **The serial no-sandbox run fails 7 tests that pass alone** (`scripts/maint/pytest-without-sandbox.sh
  -q`, found at the Phase 48 close; the same 7 at `d6b16df5` in a clean worktree, so older than
  Phase 48). They are `test_step__step_env.py::TestShape::test_a_secret_store_name_is_refused`, two
  in `tests/integration/hops/test_diff_probe.py::TestHopDiffProbeUnit` and four in
  `tests/integration/sandbox/test_task_credentials.py`; the parallel default suite never orders
  them that way. Hypothesis: an earlier test in the same process leaves a process-wide binding
  changed (a bound port, the credential catalog or the secret-store names). Next: bisect the
  serial order with `-p no:randomly` and the file list before the first failure. Trigger: now,
  since the `no-sandbox` CI job runs this script serially once the branch is pushed.

- **Timing flakes seen once each:** `test_kernel_adoption.py` over its 2 s guard ceiling,
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Provider rows lag the models in use:** Anthropic advertises dated ids while the template rows use
  aliases (limits stay `unknown`), and no row prices `claude-sonnet-5-5` or `claude-opus-5-5`
  (`task show` prints `cost: -`). Trigger: a run on an alias id whose window matters, or an operator
  asking for the estimate.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **`docket setup` without `--fix` writes:** its report re-seeds `WORKFLOW_AUTO.md`
  (`interfaces/cli/commands/setup_check.py`). A check that writes is a defect. Trigger: the next edit
  of that file.
- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.
- **A team's skills:** `hops/workspace/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope.

**Channels, inbox and the HTTP API.**

- **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`interfaces/http/server.py:200`).
- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump.
- **`GET /pods` (the list) was not checked** for the invalid-settings failure fixed on `/pods/<p>`.
- **`POST /pods/<p>/apply` with every item skipped writes no `pod.apply` audit entry.**
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.
- **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**
  (`packages/docket-runtime/src/docket_runtime/adapters/`). Trigger: someone reads that usage.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison; `scripts/smoke_workflow.py`'s memory scenario needs a live run.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
