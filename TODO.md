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
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## ◇ Phase 46 closed 2026-10-23

> Phase 46 (organize by context, refactor by tool, D-66,
> [ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md)) closed 2026-10-23 on branch
> `plan/phase-46-structure`, archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> `src/docket/` is `kernel`, twelve context packages, `interfaces/` and `bootstrap.py`; no module is
> over 700 lines; `tests/architecture/` holds the import contracts and the size and local-import
> ratchets at their recorded baselines. A real run on `fab-dev` matches the baseline hop for hop and
> event for event, and found one defect (a refused task re-claimed in a loop), fixed in `8afff095`.
> Acceptance met except the clauses Phase 47 owns: the import baseline is 748 (not empty), `status`
> has 16 writers, 40 patches cross modules. The branch is unmerged and unpushed. Phase 47 below is
> planned and waits for the maintainer.

## ◇ PHASE 47 — PLANNED, NOT SCHEDULED — the seams: public surfaces, ports at the edge, a functional core for decisions, the tests

> Opened 2026-10-23 from the Phase 46 cards moved here (P46-10, 12, 13, 14) and the 2026-10-23
> test-suite audit. The reasoning is in [ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md)
> §"After Phase 46"; this section is the executable record. **Measured 2026-10-23 at `74132d2d`**
> (`scripts/maint/refactor/analyze.py --metrics` and `tests/architecture/import_contracts_baseline.txt`):
> 748 import exceptions, 20 function-local imports, largest cycle 35 modules (2 at top level), largest
> module 695 lines, 16 `status` writers, 40 cross-module monkeypatch targets. The 748 exceptions,
> split by the card that removes them: P47-1 615, P47-2 58, P47-3 65, P47-4 7, P47-5 3.
> Re-measure before a card claims a number.

### How a Phase 47 card runs (read before claiming one)

- **One card is one docket task** on the `docket-dev` pod: `docket task add "Do card P47-N of
  TODO.md under its section's 'How a Phase 47 card runs'" --base-ref plan/phase-46-structure --gate "<the card's gate>"`. The Lead loads the card
  with `python3 .agents/skills/docket-roadmap/scripts/card_packet.py P47-N`; the implementer runs on
  the model the card names (a pipeline step `model:`). A card fits one run; a card that does not
  finish parks with what is left rather than growing.
- **Self-contained.** A task worktree has no `internal-docs/` (gitignored). A card needs only
  itself, ADR 0030 and tracked files.
- **The testing budget, the same for every card.** It replaces "the gate after every commit".
  1. Per commit: `uv run ruff check . && uv run mypy src && uv run pytest --co -q` (about 10 s).
     No test runs.
  2. While iterating: only the card's focused tests.
  3. The task gate (`--gate`): `uv run pytest tests/architecture -q` plus the card's focused tests,
     under a minute.
  4. After the merge, once per card, the integrator runs the default suite in parallel
     (`uv run pytest -n auto --dist loadfile -q --tb=line > <file>`, about 50 s), reads only the
     `FAILED` lines, fixes by cause and re-runs `--lf` only. Goldens, the agent lane and the real
     run are once, at the phase close.
  5. **Stop rule:** a check that fails again after one fix stops the card. The task parks with the
     failing line and its hypothesis. No third attempt, no "until green".
- **Baselines only shrink.** A card rewrites `import_contracts_baseline.txt` with `--write` only after
  removing edges, and its diff is deletions only. When two cards both shrink it, the integrator
  regenerates it after the merge and checks the diff against each parent still only deletes.
- **No behaviour change.** HTTP API 6, the CLI goldens and the `docket_runtime` facade stay byte for
  byte. The only behaviour changes are the three named defects (10 and 67 in P47-4, 69 in P47-6).
  A card that finds it needs another one stops and asks.

**Order, by file contention:**

```
P47-6 done · P47-1 partial  ─►  P47-2 ∥ P47-3  ─►  P47-4 ∥ P47-5  ─►  P47-8 (rest of the facades)  ─►  P47-7  ─►  close
```

- P47-1 rewrites imports across `src/`, so no other `src/` card runs beside it; P47-6 touches only
  `tests/` (outside `tests/architecture/`), CI and `pyproject.toml`.
- P47-2 owns `platform/`, `sandbox/`, the adapters and their call sites; P47-3 owns `agent/`,
  `models/adapters/` imports of `agent`, and `packages/docket-runtime/`. Both add bindings to
  `bootstrap.py`, in separate functions, and both edit the import block of
  `models/adapters/openai_http.py` (P47-2 its `governance` and `platform` imports, P47-3 its
  `agent` imports); the integrator merges those two blocks.
- P47-4 owns `tasks/` and `teams/models.py`; P47-5 owns `hops/gates/` and `pipeline/domain/`. Both
  wait for P47-2, which edits `tasks/application/{lifecycle,queue,runs}.py` and `post_hop.py`.
  All 16 `status` writers are in `tasks/application/`, so P47-4 and P47-5 do not meet.
- P47-7 goes last because P47-2..5 rewrite tests inside the files it splits.

### P47-1 — every context has a public surface

**Status:** PARTIAL 2026-10-23. `platform` is done (baseline 748 -> 707, dead-export check in `test_import_contracts.py`, seen failing on a plant). The other 9 contexts are **blocked**: 537 of ~690 cross-context imports are module-style (`from docket.teams import fleet`), and a facade binds names at import time, so the mutual dependencies become real cycles (any one context alone: 42-71 largest cycle, 75-155 modules fail to import; all ten: 99). The `observability` facade was reverted (`47c39a58`): it pulls exporter/projection/spans into the runtime wheel, whose file list is fixed by `hatch_build.py` until P47-3. **Reordered:** the remaining facades run after P47-2..5 as card P47-8; `scripts/maint/facade_oneshot.py` stays until then and is deleted in P47-8's last commit. Patches break when a call site changes from `store.x` to a bound name: patch where the module binds it. · **Size:** M · **Model:** Sonnet · **Kind:** T (a script, then judgment on cycles)

- **Trigger (measured):** 615 of the 748 exceptions are imports of another context's internal
  module, which a facade closes under the contract as written. Every context `__init__.py` is empty, so ADR 0030's "a context talks
  to another only through its `__init__`" has nothing to talk through.
- **Goal:** each context's `__init__.py` (including `platform` and `sandbox`, which are contexts)
  re-exports, with an explicit `__all__`, exactly the names other contexts import today, and every
  importer in `src/` uses `from docket.<context> import name`.
- **How:** a one-shot script under `scripts/maint/` reads the baseline and the AST, writes the
  `__init__.py` files and rewrites the importers; it is deleted in the card's last commit. One
  commit per context, leaves first. A facade that creates a cycle is resolved by judgment (import
  the name where it is defined inside the context, or move a shared type to `kernel`), never by a
  function-local import.
- **Non-goals:** the 133 edges P47-2..5 own, each listed in its card (to `platform.git`,
  `platform.process`, `sandbox.*` or an `adapters/`; out of an adapter, `platform` or `sandbox`;
  from `agent`; from a `domain/`). Tests keep importing internal modules (contracts cover `src/` only). No blind re-export.
- **Files:** every context `__init__.py`; importers in `src/`; `tests/architecture/test_import_contracts.py`
  gains the dead-export check: a name in `__all__` that nothing outside the context imports fails.
- **Acceptance:** the baseline drops by the 615 facade edges (deletions only) and holds only the
  133 the later cards own; the dead-export check passes and was seen to fail on a planted unused
  name; `cycle_largest` ≤ 35 and `local_imports` ≤ 20 (`analyze.py --metrics`).
- **Gate:** `uv run pytest tests/architecture -q && uv run python scripts/maint/refactor/analyze.py --metrics`.

### P47-2 — ports at the edges the tests fake (narrows the old P46-13)

**Status:** TODO (no longer waits for P47-1) · **Size:** M · **Model:** Sonnet · **Kind:** T + M

- **Trigger (measured):** the most patched test targets are the private aliases of three
  boundaries: 113 `monkeypatch.setattr` calls on `_git` (57), `_launch` (22), `_git.subprocess`
  (18) and `_process` (16). The contract keeps 58 edges here:
  - 41 from a context to `platform.git`, `platform.process`, `sandbox.*` or another context's
    `adapters/` (a facade would satisfy the contract, but these are the boundaries tests fake);
  - 2 from a context to its own `adapters/` (`models.provider_lifecycle`, `operator.notify`);
  - 15 out of an adapter, `platform` or `sandbox`: 8 into `platform` (`redirects` 4, and
    `sandbox` into `git`/`process` 4) and 7 into another context
    or `interfaces` (`sandbox.launch` into `governance.secrets`, `governance.security`,
    `models.catalog`, `teams.fleet`; `openai_http` into `governance.secrets`; `platform.fetch` into
    the toolbox; `operator.adapters.telegram` into `interfaces.telegram.client`).
- **Goal:**
  - Git, processes and the sandbox launcher are ports with the idiom `kernel/clock.py` already
    uses: a `Protocol`, a `ContextVar`, `use_<port>()`. `bootstrap.py` binds the real adapter at each
    entry (CLI, HTTP server, runtime), `tests/conftest.py` binds the real one by default, and a test
    swaps in the fake from `tests/support/fakes.py` (`tests/fakes.py` until P47-6 lands).
  - The 6 edges to a context's `adapters/` go through `bootstrap.py`, the only module that names a
    concrete adapter.
  - The 8 into `platform` become `from docket.platform import ...`: `_allowed_adapters` in
    `tests/architecture/test_import_contracts.py` admits `platform`'s `__init__` (ADR 0030 amended
    row), with an accept and a refuse row added to `_BITES`.
  - The 7 into a context or `interfaces` move the shared code to where both can reach it, or
    receive it as a parameter. (The 3 adapter edges into `agent` are P47-3's, which owns `agent/`.)
- **Tests in the same card:** every `monkeypatch.setattr` on `_git`, `_git.subprocess`, `_launch` or
  `_process` becomes a fake bound with `use_<port>()`. Each port has one fake and
  `tests/contracts/test_<port>_contract.py`, run as `[real, fake]`.
- **Non-goals:** a port for the store (`platform.store` is the JSON chokepoint, no test fakes it;
  it goes through P47-1's facade); ports between contexts; a DI framework.
- **Acceptance:** the 58 edges leave the baseline; patches on those four aliases are 0 (from
  113); `monkeypatch_cross_module_targets` drops from 40 and the card records the new
  value; the contract suites pass for real and fake.
- **Gate:** `uv run pytest tests/architecture tests/contracts -q` plus the unit tests of
  `platform/` and `sandbox/`.

### P47-3 — `agent` depends on `kernel` alone, and the runtime ships without a build hook (old P46-10)

**Status:** TODO (no longer waits for P47-1) · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured):** 62 exceptions under "agent imports kernel only" (into `teams` 14,
  `governance` 12, `platform` 9, `tasks` 7, `sandbox` 7, `observability` 6, `hops` 4, `operator` 2,
  `models` 1), plus 3 adapters that import `agent.llm` or `agent.context` for the types they
  implement (`models/adapters/openai_http.py`, `openai_wire.py`); `packages/docket-runtime/hatch_build.py` copies and rewrites a 40-file closure because
  the runtime cannot ship `agent/` alone.
- **Goal:** what `agent` needs from outside becomes a port in `agent/ports.py` (it exists, 237
  lines), bound in `bootstrap.py`; a type `agent` shares moves to `kernel`; the chat types the
  model adapters implement move to `agent/ports.py`, which adapters may import. Then `hatch_build.py` is
  deleted and the distribution includes `docket/agent` and `docket/kernel` directly.
- **Non-goals:** changing the `docket_runtime` facade names or behaviour.
- **Acceptance:** the 65 edges leave the baseline; `hatch_build.py` is gone; the runtime wheel builds
  (`uv build packages/docket-runtime`) and imports its facade in a clean venv;
  `tests/agent/release/test_runtime_package_boundary.py` passes unchanged.
- **Gate:** `uv run pytest tests/architecture tests/unit/agent -q`.

### P47-4 — the task's decisions are a functional core (old P46-12, plus defects 10 and 67)

**Status:** TODO after P47-2 · **Size:** M · **Model:** Sonnet · **Kind:** M + T

- **Trigger (measured):** `status` has 16 writers (12 from the old `dispatch.py`, 4 in
  `tasks/application/answers.py`) and no table of allowed transitions; `tasks/domain/` imports
  `tasks.application.{queue,runs}`, `hops.application.runner`, `hops.workspace.prepare`,
  `governance.policy`, `teams.roles` and `agent.handoff` (7 exceptions), so the domain reads state
  instead of receiving it.
- **Goal (ADR 0030 §"After Phase 46", functional core):**
  - `tasks/domain/state.py`: `Status` and `FailureKind`, the transition table, and a pure
    `decide(status, to, **facts) -> Transition`, which returns the field changes or raises
    `IllegalTransition`. `tasks/application` has one `apply_transition(project, task_id, to, ...)`,
    the only code that writes `status`. A script replaces the 16 sites by AST location.
  - `tasks/domain/` imports only `kernel` and itself: `refs.py`, which resolves references by
    reading the queue and the runs, moves to `application/`; `options.py` receives role names and
    policy checks as data; the type `task.py` takes from `agent.handoff` moves to `kernel` or into
    `tasks/domain`.
  - **Defect 10:** an answer record keeps `kind` and `createdAt`, and `answer_task` clears
    `question`, so `docket_decision_latency_seconds_count` counts answers.
  - **Defect 67:** `budgetUsd` has one writer and one type: a float with `ge=0` on
    `AgentMeta.budget_usd`, the same after provisioning, the flat `--from` and `pod set`.
- **Tests:** one table test generated from the transition table (every allowed pair succeeds and
  sets its fields; every other pair raises), with no disk and no patches; a regression test each
  for defects 10 and 67. `tests/architecture/test_status_writers.py` refuses `["status"] =` outside
  `apply_transition`, at baseline 1.
- **Non-goals:** P46-11's nested task record; any other transition behaviour.
- **Acceptance:** `status_writers` = 1; the 7 `tasks/domain` edges leave the baseline; the three new
  tests pass; operator-api and pod-dispatch tests pass unchanged.
- **Gate:** `uv run pytest tests/architecture tests/unit/tasks -q`.

### P47-5 — the gates decide in pure functions

**Status:** TODO after P47-2, parallel with P47-4 · **Size:** M · **Model:** Sonnet · **Kind:** M + T

- **Trigger (measured):** `hops/gates/post_hop.py` (605 lines) and `pre_hop.py` (382) each mix
  running a command, writing a reasons file, screening text and tracing with the decision itself.
  No test names `post_hop.py` as its `SUBJECT`, and 19 test patches name a gate module.
  `pipeline/domain` imports `teams.roles`, `teams.role_schema` and `sandbox.launch`
  (3 exceptions).
- **Goal:** each gate decision is a pure function over facts in a `domain` module (verify exit code
  and exit map, verdict text, external outcome, token and budget limits, profile requirements,
  resources) that returns a decision. The shell in `hops/gates/` gathers the facts, runs the
  command through the P47-2 port, calls the decision and records it. `pipeline/domain` receives
  role data instead of importing `teams`, and the `sandbox.launch` name it uses moves to `kernel` or
  is passed in.
- **Tests:** a table test per decision, with no disk, process or patch. The patches on gate modules
  drop accordingly, and the card records the count.
- **Non-goals:** purifying LLM calls, git, the store or processes, which stay in the shell; a new
  gate kind; any change to a gate's outcome.
- **Acceptance:** the 3 `pipeline/domain` edges leave the baseline; every decision has a table test;
  the dispatch and lights-out integration tests pass unchanged.
- **Gate:** `uv run pytest tests/architecture tests/unit/hops tests/unit/pipeline -q`.

### P47-6 — the tests: keep what earns its place, one owner per helper (the test audit's A and I, and its deletions)

**Status:** DONE 2026-10-23 (merge `cc86fe35`; ids 5573 -> 5530, helper groups 99 -> 0, guard `test_suite_shape.py`, `no-sandbox` CI job, `slow` deleted). Kept on purpose: `AgentMeta.coerce_paused` and the `queue.py` field fill (live path: `meta_get` returns `str(value)`). Follow-ups: numeric-suffix variants in `support/pods.py` and `support/http.py`, tests importing helpers from other tests, `support/pods.py` 668 lines. · **Size:** M · **Model:** Sonnet; the deletions and the CI job are
Haiku-sized if split · **Kind:** M

- **Trigger (measured, test-suite audit 2026-10-23):** 166 duplicated helpers in 103 groups and 83
  duplicated fixtures (`_hermetic`, one `setenv`, is defined in 69 files); 49 absence or "legacy"
  tests; 9 identical tests; shared infrastructure is 267 lines in three files. **Defect 69:**
  `scripts/maint/pytest-without-sandbox.sh` runs in no CI job, and the `slow` marker is registered
  and used by nothing.
- **Goal:**
  - A test stays only if it pins a `specs/` requirement, pins live-path behaviour nobody would
    notice breaking (security, persistence, wire contracts, gates, audit), or is the regression of a
    defect found by running the product. Otherwise it goes: absence tests for retired names (one
    generic test remains: an unknown command exits 2), legacy readers with their tests and the
    `src/` reader (`TestLegacyQueueLoads`, `test_legacy_string_*` with `AgentMeta.coerce_paused`'s
    string tolerance, legacy role tests, `agent/loop.py`'s "backward compatibility" default), and
    the 9 identical tests. A spec that names a deleted test is amended in the same commit.
  - `tests/support/{home,pods,trace,llm,git,http,cli,fakes}.py`, written by a one-shot script that
    folds each AST-identical helper or fixture group into one owner and rewrites the imports.
    `conftest.py` keeps only autouse isolation (with `DOCKET_SERVICE_MANAGER=none`) and the
    duration ceilings. `tests/fakes.py` and `tests/pods.py` move into `support/`.
  - A guard, `tests/guards/test_suite_shape.py`: no AST-identical helper or fixture in two test files.
  - Defect 69: a CI job runs `scripts/maint/pytest-without-sandbox.sh -q`, and the `slow` marker is
    deleted.
- **Non-goals:** the agent lane's `RETIRE_WHEN` review (the PydanticAI and OpenHands adapters and
  the adoption benchmark are a maintainer decision); the refactor tools (the close deletes them).
- **Acceptance:** duplicated helpers and fixtures 0, with the guard seen to fail on a planted copy;
  the absence, legacy and identical tests gone or each kept with its reason in the commit body;
  the no-sandbox job is green on CI; collected test ids drop only by the deleted tests.
- **Gate:** `uv run pytest tests/guards -q && uv run pytest --co -q`.

### P47-7 — the tests: integration by context, unit is pure (the test audit's C, D, E and F; B is in P47-2)

**Status:** TODO after P47-2..5 · **Size:** L, split by file · **Model:** Sonnet, one docket task per
giant file · **Kind:** M + T

- **Trigger (measured):** `tests/integration/` is one flat folder of 132 files; 38 declare a whole
  package as `SUBJECT`; `test_agent_loop.py` is 3,091 lines, `test_docket_driver.py` 2,246 and
  `test_dispatch.py` 2,088, which is why the parallel suite uses 29 % of 16 CPUs; in `tests/unit/`,
  20 files serve HTTP, 9 spawn processes and 21 use `CliRunner`; 237 `setenv` and 264 prose asserts.
- **Goal:**
  - A script moves each integration file to `integration/<context>/` (by `SUBJECT`, else by the
    context it imports most), fixes `SUBJECT` to the entry module it drives, and renames files
    named after cards or waves.
  - One task per giant file splits it by flow, to at most 800 lines per file.
  - The unit files that do real I/O move to `integration/<context>/`, unless a P47-2 fake
    replaces the I/O in the same commit.
  - Guards in `tests/guards/test_suite_shape.py`: a unit file opens no socket or process and calls
    no `time.sleep`; `SUBJECT` names a module, never a package; a test file is at most 800 lines;
    `setenv` only in the tests that parse the environment (an explicit list), at a shrink-only
    baseline; `in result.output` on a command that has `--json`, at a shrink-only baseline.
- **Non-goals:** rewriting tests' meaning; the duration ceiling (lower it only when a measured
  ranking allows).
- **Acceptance:** no integration file at the root of `tests/integration/`; none over 800 lines; the
  shape guards pass at their baselines; collected test ids equal the pre-card set modulo path; the
  parallel suite's wall time is recorded before and after.
- **Gate:** `uv run pytest tests/guards -q && uv run pytest --co -q`, then the moved files only.

### P47-8 — the facades of the other nine contexts (what P47-1 could not close)

**Status:** TODO after P47-2..5 · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Trigger (measured 2026-10-23, P47-1):** the import baseline holds 707 lines, of which about 574 are facade edges. Applying a facade before the contexts stop depending on each other pairwise multiplies the cycles; P47-2..5 remove the port, agent and domain edges that cause the biggest ones.
- **Goal:** the same as P47-1's, per context, leaves first, using `scripts/maint/facade_oneshot.py` (delete it in the last commit). Re-measure each context alone first: apply a facade only if `cycle_largest` does not grow and every module imports. `observability` goes last-but-one, after P47-3 removed the runtime's file list. A context that still cannot is listed with its blocking edge instead of forced. Underscore names imported across contexts (about 45, mostly from `hops`) become public names or move; `blueprints.load_registry` and `roles.load_registry` need distinct names.
- **Acceptance / gate:** as P47-1; the baseline falls to the edges P47-2..5 left or to a named list of unresolved cycles.

### Phase 47 close (integrator, not a docket task)

- One full run: the default suite in parallel, `pytest-without-sandbox.sh`, the escape matrix, goldens
  9/9, the agent lane, `validate-specs.sh`, `metrics.py --check`, the generated-docs checks.
- The real run on `fab-dev` compared with `internal-docs/baselines/phase-46/after/dispatch`: same hop
  order, event types and transitions.
- Delete the refactor tools: `scripts/maint/refactor/` (`analyze.py`, `move.py`, `hoist_imports.py`,
  `docket-rules.toml`), `scripts/maint/refactor_gate.sh`, `tests/guards/test_refactor_*.py` and
  `tests/guards/fixtures/refactor/`. The architecture tests are the durable record.
- **Phase acceptance:** import baseline empty; local imports 0 or each remaining one a named
  real cycle; `status` writers 1; patches on another module's private alias 0; `docket-runtime`
  without a hook; no integration file over 800 lines; the real run matches.

### Left out of Phase 47's path

- **P46-11, the persisted shapes (nested task record, `pods/<pod>/settings.json`), is not scheduled.**
  It is a redesign and waits for a measured need. Its two real defects (10, 67) are in P47-4.
- **The agent lane's retirements** (PydanticAI and OpenHands adapters, the adoption benchmark) need a
  maintainer decision about whether they are still public claims.
- **The test audit's G** (modules over 200 lines no test names) is answered by the coverage run of
  2026-10-23: 92.4 % of lines, no module of 60 or more statements under 70 %.
- **Test speed** (`time.sleep` to deadlines, shared stub servers): the split in P47-7 removes the
  measured cause (the giant files serialize the run); revisit only if the after-time says otherwise.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phases 43-46 (not cards; triage when a trigger fires)

- **Found in the Phase 46 real run (2026-10-23).**
  - **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in `RESUMABLE_FAILURE_KINDS`, operator-api §6 says so by design), so a task refused for a cause the operator has not fixed writes one refusal to the audit log and trace every tick. The unbounded in-run loop is fixed (`8afff095`); this is the per-tick residue. Trigger: the audit log fills with refusals of one task, or a second operator asks. Then resume only when the cause changed, or back off, and amend operator-api §6.
  - **The gitignored `CLAUDE.md` still describes the `cli/ -> core/ -> edges/` tree.** It is not in git, so no card fixes it: the maintainer rewrites its architecture section from ADR 0030.

> Items a Phase 45 card absorbed moved into that card on 2026-10-19 (the gateway window, the
> measurement gaps, the cut commit subject, the group `failure_kind`, the stale `security-gates`
> paragraph, the `inPlace` key, the apply-without-codebase edge, the team-aware hint, the worker
> packet note, the warm workspace, and "no `node_modules` is pod configuration", which ADR 0029
> reversed).

- **Found in the specs truth pass (2026-10-22).**
  - **Notification dedup is in memory only** (`core/notify.py` ~91-118): restarting `docket
    start` resends each pending notification once (unverified). Trigger: an operator reports a
    repeat after a restart.
  - **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`core/pod.py`
    ~86-90); latent, no turn uses the base key as history. Trigger: a turn that reads it.
- **Found while merging Wave 120 (2026-10-23).** Each comes from a worker report and was checked against its branch.
  - **`setup` without `--fix` writes:** its text report re-seeds `WORKFLOW_AUTO.md`. A check that writes is a defect. Trigger: the next edit of `cli/_setup_check.py`.
  - **The seeds point at `memory/YYYY-MM-DD.md`** (`core/memory.py` and the AGENTS.md seed in `cli/_agents.py`), a path docket never creates. Changing it bumps `CONTRACT_VERSION`, so the maintainer decides.
  - **A canonical document without `kind:` still loads with a deprecation advisory** (W120-9 deleted only the short-form path, as Q3 named). Under D-57 the advisory is a notice; either every canonical fixture gains `kind:` or the advisory goes. Trigger: the next edit of `core/config_docs.py`.
  - **`enqueue_task` is kept beside `enqueue_task_once`**, because about 300 test call sites in 40 files use it. Delete it with a script in stage 3 if the two have the same semantics for a fresh task; otherwise each site is a decision.
  - **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`serve.py::_flush_notify_channels`; serve has no logger). → P46-9.
  - **An answer to a task run with `run --pipeline <file>` is placed against the pod's pipeline**, because the file's spec is not persisted on the task (W120-8 fixed the named-pipeline half of defect 48). → P46-11, which reshapes the task record.
  - **Enabling the `email` channel checks nothing**: with no `to`, `from` or `smtpHost`, every delivery fails into the health record. Trigger: an operator enables it.
  - **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**, so the facade's cache-write sum is 0 for them. Trigger: either adapter reports usage someone reads.
  - **`GET /pods` (the list) was not checked** for the invalid-settings failure that W120-6 fixed on `/pods/<p>`. → P46-9's byte-identity check.
- **Found in the Phase 45 real runs (2026-10-20, two runs of one small task on `fab-dev`).**
  - **The implementer sends 0.65 of what the backend counts** (14 and 13 calls, largest request
    ~7,000 estimated tokens), with no toolchain grant needed (`npm` came from the prepared
    `node_modules`). The Phase 44 trigger below ("still sends over half") therefore **fired**:
    triage, then measure which calls repeat before cutting anything. The reviewer sent 0.62, the
    tester 0.80 and 0.90.
  - **A parked turn is still paid twice**, now on a read: the model's first `bash` carries `$(...)`
    ("not statically analysable"), parks every run, and the resumed hop re-sends the whole
    prompt (4,157 input tokens before the park, 8,181 on the first call after). Two runs, same
    call. Trigger: a third run that parks on the same shape; then weigh resuming the session
    over re-running the hop (operator-loop §2 item 6 keeps this a non-goal today).
  - **A hop refused before any call records an empty model**: `hop_finished.model` is `""` and
    `usage.byModel` gains a `""` key with zeros (seen on the budget-refused reviewer). Trigger: a
    reader of `byModel` that trips on the empty key.
  - **Anthropic advertises dated ids** (`claude-haiku-4-5-20251001`) while the template rows use
    aliases (`claude-haiku-4-5`), so an alias row's limits stay `unknown` though the chat route
    accepts the alias. Trigger: a run on an alias id whose window matters.
  - **The shipped price rows lag the models in use**: the pod's steps run `claude-sonnet-5-5` and
    `claude-opus-5-5`, which no template row prices, so `task show` prints `cost: -`. Trigger: an
    operator asking for the estimate; then add rows or let `provider add` take a price file.
  - **Not examined:** each run's trace carries two `approval_denied` events beside the one park.
  - A worker's test with `monkeypatch.undo()` undid the autouse home isolation and wrote into the
    real `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
- **Found integrating Wave 118 (P45-3, 2026-10-19).**
  - **A file a check reaches only through `make` or `npm run` is protected only through the
    default files it reads** (`Makefile` is not a default; `package.json` is). Stated in
    `security-gates.spec.md`. Trigger: a real gate whose script lives behind a target.
  - **A gitignored file is invisible to the check** (`git status` and `git diff` skip it), so a
    tool configuration the repository ignores can be edited without a park. Trigger: a real
    repository that ignores a file its gate reads.
- **Found integrating Wave 117 (P45-1, 2026-10-19).**
  - **Only `node_modules` is cached.** A `.venv` is not relocatable, so `uv sync`, `poetry
    install` and `cargo fetch` run in each task worktree. Trigger: a measured Python or Rust
    prepare that dominates a task's wall clock.
  - **A tool that writes into `node_modules/.cache` fails with isolation on** (the entry is
    read-only in the jail). Trigger: a real gate failing on it.
  - **Eviction can break a running task's link** when a fourth lockfile of one codebase is
    prepared while an older task still runs; resume detects the broken link and prepares again.
    Trigger: a real run that hits it.
  - **Prepare is not cancellable**, like `verifyCmd`; it is bounded by `PREPARE_TIMEOUT_S` (900 s).
  - **A hop that makes its own `node_modules` symlink to another codebase's cache entry gets that
    entry read-only in its jail** (`core/prepare.py::linked_entries` accepts any entry under the
    cache). Installed packages, not secrets; restrict to the task's codebase when next touched.
- **Found integrating Wave 116 batch A (2026-10-18).**
  - **Shell keywords are classified as binaries when unjailed.** `for t in a; do ...; done` asks
    with `'for' is not on the curated allowlist` (also `do`, `done`, `if`, `then`, `while`).
    Jailed, the allowlist stands down and the loop runs. Pre-existing; the run's parked command
    ends in such a loop, so it still asks without the sandbox. Trigger: an operator running
    without isolation reports it.
- **Found in the 2026-10-18 joint run (Wave 116 evidence).**
  - **A parked turn is paid twice.**
    - The development `red` step spent 100,573 input tokens before parking.
    - Its `approve_task` grant went unused: the re-run hop never re-issued the call.
    - The resume added a compaction call (9,065 in) and a cold first call.
    - Trigger: after W116-1..4, a real run that still parks on a write.
    - Then: weigh resuming the session over re-running the hop (operator-loop §2 item 6 keeps
      this a non-goal today).
  - **Hop language drift.** The resumed Sonnet `red` step wrote its final report in Chinese, and
    that report became the `green` step's handoff. This happened once.
    - Trigger: a second occurrence.
    - Then: a pod `language` setting rendered into the handoff instruction.
- **Found at the Phase 44 close.** The two implementer steps of the real rerun did not send under
  half (0.77, 0.80): every request shrank to a fifth to a third, but the trajectories grew (12 and
  20 calls against 8 and 5), partly from retrying a toolchain the jail could not load (now a grant
  and a 126 message). Trigger: a real implementer run with the needed grants declared that still
  sends over half of its 03:38 counterpart; then measure which calls repeat before cutting
  anything. No grant is declared on this machine's live home (the operator's call). The rerun's
  pod names are in already-pushed history (ADR 0027, the operator API spec, a test); the tree
  no longer carries them, and rewriting public history is the maintainer's call.

- **Found in Wave 115 (Phase 44).** Pending memory entries show in `docket inbox` (text and
  `--json`) but not in `GET /inbox`, MCP `inbox`, notifications or Telegram `/status`: that needs
  an operator-v1 inbox contract bump and `notify.py`/`telegram.py` edits (operator-loop item 7's
  "`GET /inbox` equals `inbox --json`" was already broken by approved-ready tasks).
- **Found in Wave 114 (Phase 44).** `core/telemetry.py` has no structural key for
  `memory_update` (the generic handler serves it); members stamped `POD_TEMPLATE_VERSION` 4 before
  P44-7's method line show stale to `pod update` by text comparison (v4 never shipped);
  `scripts/smoke_workflow.py`'s memory scenario now seeds MEMORY.md directly and needs a live run.
- **Found in Wave 113 (Phase 44).** `_resolve_hop_instructions` still opens "You are the
  Implementer..." (SOUL says it); recipe roles using `${codebaseOrConfigured}` (secure-build
  security-vetter) still render a path; `cli/_agents._create_workspace` (standalone agents)
  still writes HEARTBEAT/promise text; `repo_map.SKIPPED_DIRS` mirrors `toolbox.SKIPPED_DIRS`
  (pinned by an equality test); a condensation notice carries the call's full path; pod read
  routes do not carry `tokenBudget`.
- **Found in Wave 112 (Phase 44).** The prospective budget check compares the whole calibrated
  input estimate plus reserve against the counted budget, so a heavily cached step is refused
  early; discount by the previous call's cache reads if a real run is refused with room left.
  `glob`/`grep` still walk vendored trees before filtering (pathlib cannot prune); measure before
  changing. In an in-place task on an already dirty tree, the first writing hop's `diff` carries
  the operator's own changes once (task worktrees start clean). The bench scales cached tokens by
  the sent ratio; P44-4 may need a cache-aware projection.
- **The Lead plans with the codebase path, the Implementer is rooted in the task worktree**
  (measurement 3: `tool.refused` on `read` of the codebase path, audit seq 6-7 of the throwaway
  home). The Lead's hop should name the task worktree, or the handoff should rewrite the path.
  Reproduce with any local-model dispatch in a worktree pod before scheduling.
- **Parallel tasks in a pod** -- trigger in ADR 0027 point 10. The task record and the claim
  are already per task; a card would add a `maxParallelTasks` pod setting and a bounded pool in
  `dispatch_pod`.
- **A task's `network: none` cuts the agent turn only** (P43-4): `verifyCmd` and `run:` steps keep
  the pod's posture; the spec says so.
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams.
- **`POST /pods/<p>/apply` edge** (P43-8): an all-skip apply writes no `pod.apply` audit entry
  (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
- **Cancel over HTTP reports `cancelled` once the stop is requested** (P43-10): the task stays
  `running` in the store until the executor notices; a consumer polls `GET /tasks/<pod>/<id>`.
  The slow-stub cancel path is not covered by a test (the test seeds a run record).
- **`cli/_task.py::_pod_codebase`** is a second reader of the implementer's codebase beside
  `core/pod_report._codebase` and `core/dispatch.task_diff`; one core helper when next touched.
- **Real-Docker tests over their duration ceiling under load** (`test_network_lockdown.py`,
  `test_sandboxed_exec.py`, `test_escape_matrix.py[docker]`): pass alone, fail when five suites
  run at once. A flake, not a regression; measured 2026-10-14.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump (specs carry no changelog) (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model (D-52, amending D-31):** **`develop`** is the integration branch. Every card
branch or isolated worktree bases on `develop` and is integrated into `develop` without
rewriting history. **`main`** stays the canonical public/default and release lineage: it moves
only by a fast-forward (or a merge) from `develop`, when the maintainer cuts a release or
decides `main` has fallen too far behind. Tags and release jobs still originate from `main`.
`platform` may remain as a synchronized historical ref, but it is not a release source.

---


