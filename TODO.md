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
> **Phase 59 (D-81, [ADR 0038](docs/adr/0038-a-step-budget-is-a-checkpoint-not-a-cliff.md)) is reopened** (decision 5 amended 2026-11-03), eight cards
> below, five done: a step's budget is a checkpoint, not a cliff. Phase 58 (D-80) closed 2026-11-02: what a plan of record needs to follow a team it does
> not run. Its section is archived and what it leaves open is under "Phase 58" in the follow-ups below.
> **Phase 57** (D-79, [ADR 0037](docs/adr/0037-what-docket-gives-a-manager-in-the-plan-of-record.md)) closed 2026-11-01. Before it, Phase 56 (D-77, [ADR 0036](docs/adr/0036-a-pod-works-outward.md) decisions 13-16) closed
> 2026-10-30: an external service is declared, not programmed; a pod keeps records; one judge; one home layout; the
> four team shapes. Its section is archived and what it leaves open is under "Phase 56" in the follow-ups below.
> Decisions 15-16 of the ADR were accepted by the maintainer the same day. Phase 55
> closed 2026-10-30; Phases 52 to 54 closed 2026-10-29. The integration branch is `develop`. A new phase starts from
> a measured trigger or a maintainer request.

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
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane takes about 5 min.
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
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once · XL ≈ two cards'
scope in one pass over the same files, parks at least once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`).
`main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ▶ Phase 59: a step's budget is a checkpoint, not a cliff (D-81) · REOPENED 2026-11-03 (decision 5 amended: a budget, a clock and guards)

**Trigger.**
- *The incident.* The maintainer asked for this on 2026-11-02, from a real run. Task `task-0a050f9c` on
  the app-dev pod (`claude-haiku-5-5`) stopped at `exceeded max_iterations=20`:
  - 20 model calls, 25 tool calls (cap 40), 117 415 of 2 000 000 counted tokens, 77 s;
  - its write came at round 14 and its last edit at round 19;
  - the lint, types and tests its prompt required never ran, and its patch was empty.
- *A retry skips the failed step (reproduced 2026-11-02 with the e2e harness).* Setup: pipeline
  `lead → implementer → reviewer`, `AGENT_LOOP_MAX_ITERATIONS=3`, the Implementer writes `app.txt`
  and stops. Expected after `docket task retry` and `docket run`: the Implementer runs again.
  Actual:
  - the Implementer is never called;
  - the Reviewer runs, and its diff probe commits the Implementer's unverified tree under the
    Reviewer's hop;
  - the task settles `done`.
- *The amendment (2026-11-03, the maintainer's request, before the phase was pushed).* "A cleaner
  design, without infinite variables to configure." After P59-1..P59-5 merged, four bounds were
  declared across up to five layers, and the evidence says two of them are not budgets:
  - the incident stopped on rounds at 6 % of its tokens;
  - the 42-round real run finished about two tool calls under the default cap of 40;
  - `budgetUsd` gates a dollar estimate, and the live home's `claude-haiku-5-5` has no catalog
    price, so the pod's cap there never trips (`pod show` warns "unpriced").
  ADR 0038 decision 5 now separates a budget (tokens: the task's `maxTokens`, the pod's
  `budgetTokens`), a clock (seconds: step, pod, machine) and guards (rounds, tool calls: machine
  constants). Cards P59-6..P59-8 carry it out.
- *A token-budget landing passes as success.* Requirements 51-53 of `agent-loop.spec.md` return the
  finalization answer as `ok=True, final_message`, so an unfinished hop reaches its gate.

[ADR 0038](docs/adr/0038-a-step-budget-is-a-checkpoint-not-a-cliff.md) holds the decisions, the
measurements and the real cases. The local analysis is in
`internal-docs/audits/hop-iteration-limit-2026-11-02.md`.

**Not in this phase:**
- docket continuing a hop on its own (ADR 0038 decision 6);
- a stall detector beyond identical calls;
- default budgets per built-in role;
- the 300 s default hop clock;
- parallel-group resume.

Each waits under "Phase 59" in the follow-ups.

**Waves, by file contention:**

| Wave | Cards | Why this order |
|---|---|---|
| 1 | P59-1 ∥ P59-5 | P59-1 is the correctness fix (`tasks/application/record.py` replay, `hops/application/runner.py`, `pod-dispatch.spec.md`, `operator-api.spec.md`); P59-5 touches only `agent/tools/builtins/toolbox.py`, the Implementer's identity prompt and `agent-loop.spec.md` req. 86 |
| 2 | P59-4 | `agent-loop.spec.md` again (after P59-5); `agent/ports.py`, `driver_support.py`, `runner.py` ~118 (after P59-1), the step, plan and archetype schemas, `teams/settings.py`, `kernel/home.py`, the HTTP dispatch sites |
| 3 | P59-2 | `record.py` after P59-1; `ports.py`, `driver_support.py` and `agent-loop.spec.md` after P59-4; the loop's stop sites |
| 4 | P59-3 | the loop's finalization, `record.py` and `agent-loop.spec.md` again, after P59-2's `budget_exhausted` |
| 5 | P59-6 | the step, plan, short-form and archetype schemas, `budget.py`, `driver_support.py`, `compose.py`, `ports.py`, `kernel/home.py`, `agent-loop.spec.md`: the files P59-4 grew |
| 6 | P59-7 | `teams/` settings and provisioning, the pre-hop gate, the CLI and HTTP pod surfaces, `cost-tracking.spec.md`: no file of P59-6 except `pod-dispatch.spec.md` |
| 7 | P59-8 | `interfaces/cli/commands/pod_config.py` (`cmd_plan`) after P59-6 and P59-7 settle what it prints |

**Phase close (integrator).** Real runs, against `claude-haiku-5-5`. The first three passed on
2026-11-03 before the amendment; the last three run after P59-8:
- the live `app-dev` task `task-0a050f9c`, retried: it continues its step and runs the checks (it
  continued, ran lint and tsc, then parked on an `.env.local.example` edit that was denied);
- a throwaway-home run with a step `maxIterations: 4`: a notice, a landing report, `failureKind: budget`
  with a patch, then a retry that finishes (passed);
- one multi-file task long enough to pass 40 rounds under a declared budget (42 rounds, `done`);
- after the amendment, a task queued with a small `maxTokens`: a notice, a landing, `failureKind:
  budget`, `source: task`;
- the 42-round task again with only a step `timeout` declared: it finishes, no guard near;
- a pod with a small `budgetTokens`: the next task is blocked `pod_budget`, the pod paused, and
  `run --resume` after raising it continues.

Record rounds per hop before and after P59-5, on the same task.

### P59-1 — A retry re-runs the step that failed, and continues it

**Status:** DONE 2026-11-03 (merged; `retryContinues` joins `features`) · **Size:** M · **Model:** Sonnet · **Kind:** fix (wrong outcome) + spec

- **Trigger:** the reproduction in the phase trigger. `replay_pipeline_position`
  (`tasks/application/record.py` ~101-197) ends every non-parked hop with `pi = idx + 1` (~184),
  ok or not. The only exception is a parallel group (`_group_complete` ~87-98 checks `ok`).
  `retry_task` (`tasks/application/lifecycle.py` ~173-189) keeps the hops, so the failed step is
  skipped. Separately, `_run_hop_turn` (`hops/application/runner.py` ~102-210) resends the original
  `message` on an in-place retry, on top of rounds the failed attempt already persisted to the
  step's session (`kernel/ids.py::step_session_key`).
- **Goal:**
  - Replay treats a failed hop (`ok` false, not parked) like a parked one: `pi = idx`, keeping the
    `rework_hop` and the counts that led to it. A failed hop consumed no cycle.
  - A step that runs again while its last hop in this cycle failed, and whose session holds rounds,
    gets a continuation message instead of its prompt. So does an in-place transient retry whose
    failed attempt made the session grow (count the messages before and after the attempt). The
    message is one fixed paragraph built by a pure function in a new `hops/domain/continuation.py`:
    - that the previous turn on this step stopped before it finished, and the error;
    - the hop's summary when it has one (P59-3 makes that the landing report);
    - up to 20 changed paths, from `platform/git.py::git_changed_files` in the step's cwd;
    - "Continue from where you stopped; do not start over; finish as the step asks."
  - Feature name `retryContinues` (`interfaces/http/routes/health.py` `FEATURES`).
- **Non-goals:**
  - No retry mode. Starting over is a new task (`operator-api.spec.md` ~159-164 already says so).
  - No change to `retry_task`'s status move, to the parallel-group resume limit, or to parked hops
    (they keep their consult note path).
- **Change:**
  - `record.py::replay_pipeline_position`, its docstring and the docstring of `retry_task`.
  - `runner.py::_run_hop_turn`: choose the message per attempt. Read the session length through
    `agent.session` (`load_messages`).
  - New `hops/domain/continuation.py`: pure, text only.
  - Specs:
    - `pod-dispatch.spec.md` "Per-hop incremental persistence and crash recovery" (~195): a failed
      hop re-runs its index;
    - `pod-dispatch.spec.md` "Retries and the failure-kind taxonomy" (~551): an in-place retry over
      persisted rounds continues;
    - `operator-api.spec.md` `POST .../retry` (~159): the failed step runs again and continues its
      session.
- **Acceptance (RED first):**
  - `tests/unit/tasks/application/test_record.py`:
    - `[lead ok, implementer failed]` replays to the implementer's index;
    - `[lead ok, implementer ok, reviewer REQUEST-CHANGES (rework to implementer), implementer
      failed]` replays to the implementer's index with `rework_hop` the reviewer's hop and the
      reviewer's count at 1;
    - Oracle: before the change both return the next index.
  - New `tests/e2e/test_retry_continues_the_failed_step.py`, the reproduction made a test.
    - Setup: `AGENT_LOOP_MAX_ITERATIONS=3`; the implementer script is `write_file app.txt`, two
      `bash cat`s, then `say("Done")`.
    - First run: the task is `failed`.
    - Then `docket task retry` and `docket run`. The fourth implementer request happens.
    - Its last user message holds "stopped before it finished" and `app.txt`.
    - Exactly one user message in it carries the task description.
    - The Reviewer runs after it, and the hops read lead ok, implementer failed, implementer ok,
      reviewer ok.
    - The task branch holds `app.txt` as `fixed`, and the Reviewer hop lists no `filesChanged`.
      Before the change the Reviewer's diff probe committed it.
    - Oracle: before the change there is no fourth request and the task is `done`.
  - `tests/integration/tasks/test_retries_and_timeouts.py`: a fake driver whose first attempt
    appends two messages to the step session and returns `daemon_error`. Its second attempt receives
    the continuation. An attempt that fails before persisting anything is retried with the original
    message.
- **Gate:**
  - the three files above, under `timeout 120`;
  - `tests/architecture` (3 s);
  - `tests/e2e -n auto` (42 s: the CLI and HTTP outcome of a retry change).

### P59-2 — Running out of budget is its own outcome, and the work is kept

**Status:** DONE 2026-11-03 (merged; only an Implementer hop that ended `budget_exhausted` is pinned) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P59-1, P59-4

- **Trigger:** in the incident the hop was reported as `invalid_output`, and its three changed
  files were not in the task's patch.
  - Rounds and tool calls stop with `invalid_output` (`agent/loop_budget.py` ~127-158,
    `loop_steps.py` ~107-118).
  - The wall clock stops with `timeout`, which `runner.py::_RETRYABLE_FAILURE_KINDS` retries in
    place.
  - `hop_diff_probe` runs only `if hop_ok` (`tasks/application/record.py` ~348).
  - The task kind `budget` exists only for a `maxTokens` stop (`record.py::_turn_failure_kind`
    ~447-457).
- **Goal (ADR 0038 decisions 1-2):**
  - `agent/ports.py` `FailureKind` gains `budget_exhausted`. The four budget stops
    (`max_iterations`, `max_tool_calls`, the loop's wall clock `timeout`, `token_budget`) carry it.
  - `AgentLoopResult` and `TurnResult` carry a typed `budget_stop` (`bound`: `rounds | toolCalls |
    tokens | time`, `limit`, `used`), copied by `driver_support.py` ~470.
  - The task's `failureKind` is `budget` for any of them. The hop record gains `budget: {bound,
    limit, used, source, treeChanged}`, `source` from P59-4's resolver. The stop message names the
    key that raises the limit (`maxIterations` on step `build`, or `AGENT_LOOP_MAX_ITERATIONS`).
  - A failed Implementer hop with a dirty tree is pinned as an ok one is: commit, `filesChanged`,
    evidence. `treeChanged` says whether the pin made a new commit. The hop stays `ok: false`.
  - Feature name `budgetOutcome`.
- **Non-goals:**
  - `no_progress`, `tool_denials`, `context_fit`, cancellation and approvals keep their kinds.
  - The transport `timeout` (`models/adapters/openai_http.py` ~206-218) stays retryable.
  - No landing yet (P59-3). No pinning for non-Implementer hops beyond what they do today.
- **Change:**
  - `ports.py`, `loop_types.py`, `loop_budget.py`, `loop_steps.py`, `driver_support.py`;
  - `record.py` (`_turn_failure_kind`, the probe gate ~348) and `tasks/domain/task.py` (`HopResult`);
  - specs: `agent-loop.spec.md` "Stop conditions" 7-10 and the interface block (~813);
    `pod-dispatch.spec.md` "Retries and the failure-kind taxonomy" 1-2 (`timeout` is transport
    only); "Implementer diff producer" (~1690); `operator-api.spec.md`, the task shape (`budget` on
    a hop, and what `failureKind: budget` means).
- **Acceptance (RED first):**
  - `tests/unit/agent/test_loop_budget.py`: each of the four bounds, reached with a fake backend,
    returns `failure_kind == "budget_exhausted"` with the bound, the limit and the used figure.
  - `tests/integration/tasks/test_retries_and_timeouts.py`: a loop wall-clock stop is tried once
    (`attempts == 1`); a transport `timeout` is still retried.
  - A new e2e file, `tests/e2e/test_budget_keeps_the_work.py`:
    - `AGENT_LOOP_MAX_ITERATIONS=3`, and the Implementer writes `app.txt` and keeps asking for tools;
    - the task is `failed` with `failureKind: "budget"`;
    - the hop has `budget == {bound: rounds, limit: 3, used: 3, source: default, treeChanged: true}` and
      `artifact.filesChanged == ["app.txt"]`;
    - `docket task diff` shows `fixed`;
    - Oracle: before the change `failureKind` is `hop_failed` and the diff is empty.
  - `tests/fixtures/task-records/` load unchanged.
- **Gate:**
  - the touched unit and integration files, under `timeout 120`;
  - `tests/architecture` (3 s);
  - `tests/e2e -n auto` (42 s).

### P59-3 — One landing for every budget bound, and a notice before it

**Status:** DONE 2026-11-03 (merged; the Reviewer-APPROVE e2e was written after the code, so its RED was not observed) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P59-2

- **Trigger:**
  - In the incident the model never learned its budget. It explored for 13 rounds and spent the
    last one reading a test.
  - The landing that exists (requirements 51-54, `agent/loop.py::prepare_request_or_finalize`
    ~328-420, `loop_request.py::_finalization_messages` ~146) covers tokens only, and it returns
    `ok=True`.
- **Goal (ADR 0038 decision 3):**
  - **One landing.** When any budget bound would stop the turn, the loop makes the finalization
    request once instead. That is: the next round would pass `max_iterations`; a batch would pass
    `max_tool_calls` (that batch is refused and not persisted, as today); the wall clock is spent;
    or the token rule of requirement 51 selects it.
    - The request is the trailing request-only instruction with no tools, and it names the bound.
    - It gets one grace request past the rounds and wall-clock limits, with its own timeout
      `min(request_timeout_s, 60)`.
    - It must still pass the window check (else `context_fit`) and the token budget (else a hard
      `budget_exhausted` stop).
    - Its answer is persisted and returned as `output` with `ok=False`, the bound's stop reason and
      `failure_kind="budget_exhausted"`, never `final_message`.
  - **A notice.** The first time any bound has a quarter or less left (rounds, tool calls, measured
    tokens, wall clock), the loop appends one line to that round's last tool result:
    `[docket] This step's budget is running out: <what is left>. Finish the current change, run the
    checks, leave the tree consistent; when it ends you will be asked for a report.` It also traces
    `budget_warning` with `action: "notice"`. It appears once per turn.
  - `record.py`: a `budget` hop's `artifact.summary` is the report. Its verdict is never parsed and
    no gate runs. P59-1's continuation then carries the report.
- **Non-goals:**
  - No forced `handoff` call (a tool-free report works on every wire and profile).
  - The `forced-on-close` profile path is unchanged.
  - Requirement 56's compaction convergence is unchanged.
- **Change:**
  - `loop.py` (the finalization entry and its triggers), `loop_budget.py` (`check_iteration_bounds`
    returns "land" before "stop"), `loop_steps.py` (the refused batch, the notice),
    `loop_request.py` (the instruction names the bound), `loop_trace.py` (the `notice` action);
  - `record.py` (the summary of a `budget` hop);
  - specs: `agent-loop.spec.md` "Terminal response reservation" 51-54 (all four bounds, the new
    outcome) and "Stop conditions" 7-9.
- **Acceptance (RED first):**
  - `tests/unit/agent/test_loop.py`, with `max_iterations=3` and a backend that always asks for a
    tool:
    - three tool rounds, then a fourth request with no tools whose last message names "rounds";
    - the result is `ok=False`, `stop_reason="max_iterations"`, `failure_kind="budget_exhausted"`,
      and `output` is the backend's text;
    - the session holds that text but not the instruction.
  - The same file, with `max_iterations=8`: the notice line is in round 6's last tool result and in
    no other.
  - `tests/integration/agent/loop/test_terminal_reservation.py`: the token finalization's tool-free
    answer is now `ok=False, budget_exhausted`. This amends requirement 53 first; the existing
    assertions change because the spec changed.
  - Wall clock: a hop `timeout` of 2 s and a `bash sleep 5`. The bash is clamped, one landing
    request follows, and the hop fails with `budget.bound == "time"`.
  - `tests/e2e/test_verdict_contract.py` (or a new e2e file): a verdict-gated Reviewer that runs
    out and answers "APPROVE" in its report. The task fails with `budget`, and the gate is not
    applied.
- **Gate:**
  - `tests/unit/agent/test_loop*.py` and the touched integration files, under `timeout 120`;
  - `tests/architecture` (3 s);
  - `tests/e2e -n auto` (42 s: the tool output and the hop outcome change);
  - `scripts/maint/context_replay.py tests/fixtures/context-replay` (the landing must fit the 32k
    replay).

### P59-4 — Budgets are declared where the work is declared, and the machine only defaults

**Status:** DONE 2026-11-03, amended by P59-6 (its step and role rounds/tool-call keys are deleted; the time chain, the deleted `DISPATCH_*` and the claim refresh stay) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P59-5 (spec file)

- **Trigger:** each per-hop bound is declared somewhere else, under rules that disagree (ADR 0038,
  "What the code and a run say today"):
  - `max_iterations` has no step or role override (`kernel/home.py:135`, `:246`). At 20 it sits
    below the tool-call cap of 40, so it always fires first: in the incident it stopped the hop at
    6 % of its tokens. Measured over 90 real hops, every successful hop used at most 14 rounds,
    all on short tasks. Long work has no way to declare more.
  - Under `docket start`, `DISPATCH_TURN_TIMEOUT_S`/`DISPATCH_VERIFY_TIMEOUT_S` beat the pod's own
    `turnTimeoutS` (`pod-dispatch.spec.md` "Timeouts" 2-3; `interfaces/http/routes/dispatch.py`
    ~58, `sweeps.py` ~66, `server.py` ~102).
  - `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` is never read on the hop path (`driver_support.py::_loop_config`
    always passes the hop's timeout; the live default is the `teams/settings.py::DEFAULT_TIMEOUT`
    constant), while `docs/troubleshooting.md` ~146-154 tells the operator to raise it.
  - No stop says where its limit came from.
- **Goal (ADR 0038 decision 5):**
  - The work declares the size of one attempt on its pipeline step: `maxIterations` (new),
    `maxToolCalls`, `timeout`. A role archetype may declare `maxIterations` and `maxToolCalls`.
    The pod's `turnTimeoutS` stays the pod-wide time default.
  - One pure resolver, `hops/domain/budget.py::resolve_hop_budget`, returns rounds, tool calls and
    seconds, each with its `source` (`step | role | pod | default`). The chain is step > role >
    pod (time only) > machine. The runner (time) and the driver (rounds, tool calls) both use it,
    replacing `_hop_max_tool_calls` and the `node.timeout` branch of `runner.py` ~118. The sources
    reach `LoopConfig`, where P59-2 copies them onto the hop's `budget`.
  - The machine only fills a gap:
    - `DISPATCH_TURN_TIMEOUT_S` and `DISPATCH_VERIFY_TIMEOUT_S` are deleted (no compatibility,
      rg-proven);
    - `resolve_timeout` falls back to `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S`, and `DEFAULT_TIMEOUT` is
      deleted;
    - `AGENT_LOOP_MAX_ITERATIONS` defaults to 60.
  - The claim is refreshed every model round, not only when a process starts (`driver_support.py`
    ~446), so a long declared budget is never swept as a stale claim.
  - What a pod's YAML looks like after the card, on the app's own pipeline:

    ```yaml
    # .docket/teams/app-dev/pod.yaml
    settings: {turnTimeoutS: 600}        # its lint + tsc + tests take minutes
    # .docket/teams/app-dev/pipelines/app-dev-review.yaml
    steps:
      - build: implementer
        maxIterations: 80                # the long step says so itself
        timeout: 1200
      - review: reviewer
        maxIterations: 20
    ```
- **Non-goals:**
  - No per-role defaults in the built-in archetypes (a follow-up).
  - Tokens stay the spender's: the task's `maxTokens`, never a step key.
  - No pod-level `maxIterations`/`maxToolCalls`, no pipeline-wide defaults block, no machine
    ceiling (a follow-up).
  - `verifyTimeoutS` and `verify:` gates keep their own clock; only the `DISPATCH_VERIFY_TIMEOUT_S`
    override goes.
- **Change:**
  - `pipeline/domain/step.py` ~140-166, `plan.py` ~80 and ~203, `short_form.py` ~9-22 and ~252
    (each `maxToolCalls` site gets a `maxIterations` twin);
  - `hops/application/compose.py` ~651; `agent/ports.py` ~126 (`DOCKET_HOP_MAX_ITERATIONS`);
  - new `hops/domain/budget.py`; `hops/application/driver_support.py` ~330-385 and ~446;
    `hops/application/runner.py` ~118; `hops/application/executor.py` ~490-532;
  - `teams/role_schema.py` ~88-127, ~159, ~222; `teams/settings.py` ~13 and ~96-103;
    `tasks/application/lifecycle.py` ~86 (docstring);
  - `kernel/home.py` ~135, ~203-204, ~246, ~282-283;
  - `interfaces/http/routes/dispatch.py` ~58, `interfaces/http/sweeps.py` ~66,
    `interfaces/http/server.py` ~102;
  - `scripts/gen_cli_docs.py` ~505-516, then `docs/commands.md` regenerated;
  - docs: `docs/CONFIGURATION.md` ~323-324 (a short "Budgets" table: the three owners and the
    chain), `docs/troubleshooting.md` ~146-154;
  - specs:
    - `pipeline-format.spec.md` "Steps" (requirement 11's neighbour);
    - `role-archetypes.spec.md` "Tools and calls per hop" 1 and 3;
    - `pod-dispatch.spec.md` "Timeouts" 1-3 and ~224;
    - `agent-loop.spec.md` 104-105, "Tunables" (~912) and the example at ~947.
- **Acceptance (RED first):**
  - `tests/unit/hops/domain/test_budget.py` (new): a table over the chain. Step 5 beats role 9
    (`source: step`). Role 9 with no step value gives `source: role`. Pod `turnTimeoutS` 600 with
    no step `timeout` gives 600 (`source: pod`). Nothing declared gives the machine values,
    60/40/`AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` (`source: default`).
  - `tests/unit/pipeline/domain/test_step__spec.py`: `maxIterations: 0` and `"x"` are refused, 5 is
    kept. `tests/unit/teams/test_role_schema.py`: the same for an archetype.
  - `tests/integration/hops/driver/test_hop_tools.py`, with a model that asks for a tool every
    round:
    - a step with `maxIterations: 2` makes exactly two backend requests, then stops on rounds;
    - with no step value and an archetype value of 4, it makes four;
    - with neither, the stop names `default` as the source.
  - `tests/integration/tasks/test_retries_and_timeouts.py`:
    - with `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S=45` and nothing declared, a hop resolves 45 (oracle:
      300 today);
    - a service-triggered dispatch of a pod with `turnTimeoutS: 900` resolves 900 whatever the
      environment holds;
    - `rg DISPATCH_TURN_TIMEOUT_S src scripts docs specs` is empty.
  - A hop that makes rounds, with no process, for longer than `max(CLAIM_STALE_TIMEOUT, lease)` on a
    fake clock is not failed `stale_claim` by `sweep_stale_claims`. Oracle: today it is. If the
    oracle does not reproduce, record that on the card and drop the refresh.
  - `uv run python scripts/gen_cli_docs.py --check` passes after regeneration.
- **Gate:**
  - the files above, under `timeout 120`;
  - `tests/architecture` (3 s);
  - `tests/e2e -n auto` (42 s: the pipeline format changes).

---
### P59-5 — Fewer wasted rounds: `edit` prints the relative path, the Implementer batches its reads

**Status:** DONE 2026-11-03 (merged 8520e6c9; effect on rounds measured at the phase close) · **Size:** S · **Model:** Sonnet · **Kind:** fix + prompt

- **Trigger:** in the incident, `write` answered `wrote src/lib/safety/bot-check.ts`, but `edit`
  answered `replaced 1 occurrence(s) in /…/.docket/state/workspaces/…/guard.ts`
  (`agent/tools/builtins/toolbox.py` ~220 formats `{target}`, while `write` uses `_display_path`
  ~167). The model spent round 15 checking its checkout. It also read `guard.ts` seven times in
  `sed -n` windows and made 25 tool calls in 20 rounds, although the identity prompt says to
  inspect with `read`.
- **Goal:**
  - `edit` answers `replaced N occurrence(s) in <path>` with the workspace-relative path that
    `write` prints.
  - `templates/prompts/identity/implementer.md` gains two lines under "Role — Implementer": read a
    file whole with `read` (it pages a long file itself) instead of many small windows; and when
    several reads or searches do not depend on each other, ask for them in one reply. Its `version`
    goes to `1.1.0`.
- **Non-goals:** no change to `read`'s window, or to any other role's prompt.
- **Change:** `toolbox.py` ~187-220; the identity prompt; `agent-loop.spec.md` requirement 86
  (extend it to `edit`).
- **Acceptance (RED first):**
  - the unit file that mirrors `toolbox.py` (find it with `rg -l "_display_path|occurrence" tests/`):
    an edit under a root answers the relative path, never the root's absolute prefix;
  - `tests/unit/teams/test_prompts.py` passes with the new version (update a pinned hash only for
    this prompt, never another).
  - The effect on rounds is measured at the phase close, not in this card.
- **Gate:**
  - the two files above, under `timeout 120`;
  - `tests/architecture` (3 s);
  - `tests/e2e -n auto` (42 s: a tool's output changes).

### P59-6 — Rounds and tool calls are guards, not budgets

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec (deletion) · **After:** P59-3

- **Trigger:** the amendment in the phase trigger (an explicit scoped request). A round or a tool call
  is not a cost, and as a declared budget it cut legitimate work: the incident stopped on rounds at
  6 % of its tokens, and the 42-round run finished about two calls under the old default of 40.
- **Goal (ADR 0038 decision 5, amended):**
  - No step, role or task declares rounds or tool calls. Delete the step keys `maxIterations` and
    `maxToolCalls` (`pipeline/domain/step.py` ~140-181, `plan.py` ~87-92 and ~209-210,
    `short_form.py` ~30-31 and ~258-259), the archetype keys (`teams/role_schema.py` ~88-136,
    ~168-171, ~233-234; `teams/config_models.py` ~47-48; `teams/roles.py` ~417-418 and ~467-470), the
    hop coordinates `DOCKET_HOP_MAX_TOOL_CALLS` and `DOCKET_HOP_MAX_ITERATIONS` (`agent/ports.py`
    ~143-148, `hops/application/compose.py` ~666-669) and both role schema copies (regenerate with
    `scripts/gen_config_schemas.py`). `maxToolCalls` on a step and an archetype predates Phase 59;
    it goes too.
  - `hops/domain/budget.py` keeps only the time chain (`resolve_seconds`); `resolve_hop_budget`,
    `HopBudget` and the `role` source are deleted. `driver_support.py` ~352-378 reads rounds and
    tool calls from `Home` with `source: default`.
  - The guards: `AGENT_LOOP_MAX_ITERATIONS` defaults to 200 and `AGENT_LOOP_MAX_TOOL_CALLS` to 400
    (`kernel/home.py` ~135-136 and ~241-242). Both env vars stay, for tests and an emergency.
  - A guard stop keeps its landing and report; its message names the env var, not a YAML key.
  - A pipeline or role that still carries either key is refused by validation, naming the key and
    saying a step declares only its `timeout` (no silent ignore).
- **Non-goals:** the outcome, landing, notice, pin and retry of P59-1..P59-3 are unchanged; the step's
  `tools` allow-list stays; time and tokens are untouched.
- **Docs:** `docs/CONFIGURATION.md` "Budgets" (~330-355) becomes the three-row table (budget, clock,
  guards); `docs/troubleshooting.md` ~146-154; `docs/commands.md` regenerated by `gen_cli_docs.py`.
- **Specs:** `pipeline-format.spec.md` "Steps" (the two keys), `role-archetypes.spec.md` "Tools and
  calls per hop", `agent-loop.spec.md` (requirements 104-105, "Tunables", the example),
  `pod-dispatch.spec.md` where it names the step keys.
- **Outside the repo (integrator, after merge):** `~/.claude/skills/onboard-project/scripts/apply.sh`
  ~14-138 and `references/blueprint-format.md` write `maxIterations` on build steps; they must
  stop. Tack is told.
- **Acceptance (RED first):**
  - `tests/unit/pipeline/domain/test_step__spec.py`: a step with `maxIterations: 5` or
    `maxToolCalls: 5` is refused naming the key. Oracle: today both are kept.
  - `tests/unit/teams/test_role_schema.py`: the same for an archetype.
  - `tests/unit/hops/domain/test_budget.py`: only the time chain remains (step, pod, default).
  - `tests/integration/hops/driver/test_hop_tools.py`: with nothing set, a model that asks for a tool
    every round stops at `AGENT_LOOP_MAX_ITERATIONS` with `source: default`; with the env set to 2
    it makes two requests and the landing.
  - `rg -n "maxIterations|maxToolCalls|DOCKET_HOP_MAX_(ITERATIONS|TOOL_CALLS)|resolve_hop_budget" src
    scripts docs specs --glob '!docs/adr/**' --glob '!docs/cycles-ended/**'` names only the refusal
    and its test.
- **Gate:** the files above under `timeout 120`; `tests/architecture`; `tests/e2e -n auto` (the
  pipeline format changes); `gen_config_schemas.py --check`, `gen_cli_docs.py --check`,
  `validate-specs.sh`.

### P59-7 — A pod's budget is tokens: `budgetTokens` replaces `budgetUsd`

**Status:** TODO · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec (rename by script, then by hand) · **After:** P59-6 (`pod-dispatch.spec.md`)

- **Trigger:** the amendment. `budgetUsd` gates a dollar estimate (`hops/gates/pre_hop.py`
  `pod_gating_cost` ~40-62 prices tokens through the catalog; `DocketDriver` records no cost), and
  with an unpriced model (`claude-haiku-5-5`, the live home's) it never trips.
- **Goal:**
  - The pod setting `budgetTokens` (int > 0; unset or absent = no pod cap) replaces `budgetUsd`
    everywhere: `teams/pod_settings.py` ~61, ~117, ~238; `teams/settings.py::pod_budget` ~37-39;
    `teams/models.py` ~67-73; `teams/member_workspace.py` ~148-215, ~252-274;
    `teams/pod_provisioning.py` ~104 and ~299-437; `teams/blueprints.py` ~84-110 and ~247-274;
    the CLI (`pod.py` ~79-94 and ~342, `pod_settings.py` ~215 and ~296, `agents.py` ~459-468,
    `status.py` ~249-260, `pod_show.py` ~42, `setup_check.py` ~260-267, `setup_check_budget.py`,
    `run.py` ~248); HTTP (`routes/health.py` ~56-70, `routes/pod_create.py` ~56-84).
  - The gate compares the pod's counted tokens (`input - cached + output`, the measure `maxTokens`
    uses) with `budgetTokens`, over the same members and the same window the estimate used;
    `decide_pod_budget` (`hops/domain/gate_decisions.py` ~294-303) takes integers and no
    `estimated` flag. `pod_budget`, the pause, `pausedReason` and `run --resume` are unchanged.
  - The pricing estimate stays where it informs (`docket status`), labelled, and gates nothing. The
    "unpriced" warning on the budget goes.
  - The blueprints set no pod budget (the build, respond and operate defaults of 20, 30 and 15 USD
    go): a pod cap is opt-in, and a task's `maxTokens` and the per-turn default already bound spend.
  - The `frugal` recipe (`templates/recipes/frugal/pod.yaml` ~8, `README.md`) declares a token cap;
    `examples/configs/agents.{yaml,json}` follow.
  - No compatibility: a document or request that still carries `budgetUsd` is refused naming
    `budgetTokens`.
- **Non-goals:** the task's `maxTokens`, the per-turn token budget and the hop's `budget` record are
  unchanged; no new `features` name (the shape of `pod_budget` does not change).
- **Change by script:** the mechanical rename (`budgetUsd` -> `budgetTokens`, `budget_usd` ->
  `budget_tokens`, float -> int) is one throwaway script under the scratchpad, run once, then
  finished by hand (CONTRIBUTING "a script is a means").
- **Specs:** `cost-tracking.spec.md` (the cap and the gate), `pod-dispatch.spec.md` (the pre-hop
  gate), `docket-meta.spec.md`, `pod-blueprints.spec.md`, `cli-json-shapes.spec.md`,
  `specs/acceptance/user-stories.md`. Docs: `CONFIGURATION.md`, `recipes.md`, `troubleshooting.md`,
  `README.md`, `QUICK-START-DOCKET.md`, `commands.md` regenerated.
- **Acceptance (RED first):**
  - `tests/integration/tasks/test_autopause.py`: a pod with `budgetTokens: 1000` whose earlier hops
    counted 1 200 tokens blocks the next task with `pod_budget` and pauses, on a model with no
    catalog price. Oracle: today `budgetUsd` never trips on an unpriced model.
  - `tests/unit/teams/test_pod_settings.py`: `budgetTokens: 0`, `-1` and `"x"` are refused;
    `budgetUsd` is refused naming `budgetTokens`.
  - `tests/integration/interfaces/test_pod_config_settings.py`: `docket pod set budgetTokens 500000`
    then `pod show` lists it with source `set`.
  - `tests/unit/teams/test_blueprints.py`: no blueprint carries a pod budget.
  - `rg -n "budgetUsd|budget_usd|default_budget_usd" src scripts docs specs examples
    --glob '!docs/adr/**' --glob '!docs/cycles-ended/**'` names only the refusal and its test.
- **Gate:** the files above under `timeout 120`; `tests/architecture`; `tests/e2e -n auto` (the HTTP
  pod shape changes); `gen_cli_docs.py --check`, `gen_config_schemas.py --check`, `validate-specs.sh`.

### P59-8 — `pod plan` shows each step's clock and the budget, with their sources

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P59-6, P59-7

- **Trigger:** no command shows a resolved limit before a run; the operator learns it only from a
  stop message. `docs/CONFIGURATION.md` ~357 says `docket pod plan` confirms the limits, and it
  prints only the rework budget and each step's role and gate (seen 2026-11-03 on a throwaway pod).
- **Goal:** `docket pod plan` (`interfaces/cli/commands/pod_config.py::cmd_plan` ~322-360) prints,
  per agent step, its clock with the source (`step`, `pod` or `default`), and once, the guards
  (rounds and tool calls, `default`) and the pod's `budgetTokens` or "none". `--json` carries the
  same. It reads the same resolver the runner uses (`hops/domain/budget.py::resolve_seconds`), never
  a copy of the chain.
- **Non-goals:** no change to `pod show`; no new command; tokens per task are the task's and are
  not shown here.
- **Specs:** the `pod plan` requirement in the spec that owns it (find it with
  `rg -n "pod plan" specs/functional`), `cli-json-shapes.spec.md` for `--json`. Docs:
  `CONFIGURATION.md` ~357.
- **Acceptance (RED first):** the `cmd_plan` test file (`rg -l "Pipeline plan" tests/`): a pipeline
  whose build step declares `timeout: 1200` on a pod with `turnTimeoutS: 600` prints `1200s (step)`
  for build and `600s (pod)` for review, the guards with `default`, and `budgetTokens none`. Oracle:
  today none of these lines exist.
- **Gate:** that file under `timeout 120`; `tests/architecture`; the CLI goldens
  (`bash tests/golden/run.sh verify-all`) if a golden captures `pod plan`; `gen_cli_docs.py --check`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Phase 55 Wave 1 (merged 2026-10-30).** Loose ends, none a card yet; the first two belong to the later cards
that already own the files.
- *Specs that lag.* `trace-store.spec.md` items 30-32 say every `process_*` payload carries `pgid`; MCP events carry
  none. `audit.spec.md` (~line 77) omits `pod.network_widen` / `pod.network_narrow`. P55-12 or the next card that
  edits either spec.
- *Required variables supplied by tasks.* `dispatch_pod`'s up-front check refuses a `required` pipeline variable that
  only tasks supply. P55-9 (routines) meets it first.
- *Smaller.* `docket task cancel` does not kill a `hop` MCP session directly (it closes at hop end); a top-level
  `networkGrant` in `pod.yaml` is an unknown-key error, not a skip (only under `settings`).
- *Flakes under load, seen once each and passing alone:* `test_run.py::TestForegroundApprovalPrompt` (two tests),
  `test_consult_wait.py::TestAnsweredInPlace::test_an_option_answer_goes_back_to_the_model_in_the_same_turn`,
  `test_end_to_end.py` approval-mode tests. A second failure of the same test is its trigger.
- *Phase 55 Wave 2, P55-3.* The `outward` recipe's policy `ask` names one tool, `mcp__outbox__send`
  (`when.tool` matches an exact name), so a send tool of another name is not asked about: a kind predicate or a default
  `ask` for every `send` tool belongs with P55-4. `--kind` stays an operator assertion, not verified against the server.
  A pipeline step that runs a role from the pod's existing registry (not in the applied directory) is not checked by
  the read/act rule.
- *Phase 55 Wave 2, P55-6.* `docket task show` "Waiting on you", the foreground `run` progress view and Telegram
  `/status` do not special-case a `wait`. `serve-read-api.spec.md` (the `kind` label list) and `a2a-binding.spec.md`
  (`escalationKind`) still list five kinds. `docket_escalations_total` counts a probe-resolved wait as `by=person`. A
  `stale_claim` between wake and claim drops the wait, so the next claim parks the step again. A monitor-only `docket
  start` never runs a probe (only a dispatching sweep does). Tack's maintainer is told: `wait` is an additive
  `EscalationKind`, `machine` an additive `EscalationPolicy`, the task is `waiting_input` with a2a state `WORKING`, a
  timed-out wait with no route is `blocked` / `wait_expired`, and `POST /escalations/<id>` `{optionId: "resume"}` ends
  it early. The e2e lane took 344 s once on this host against about 42 s measured before; its slowest tests are 13 s,
  so it was host load, not a test; re-measure if it repeats.
- *Phase 55 Wave 3.*
  - P55-2: the refusal golden is not added. `tests/golden/run.sh` derives the command from the case id and
    `setup model set` validates the model id (it contains `/`) before the role; a CLI unit test in
    `tests/unit/interfaces/cli/commands/test_setup_model.py` plus checking the role first would fix both. The refusal
    hint and `setup model list` name only the ten built-in roles; `known_role_names()` reads every overlay per call.
  - P55-4: `task show --json` carries no `call` (deliberate). The `Authorization` redaction pattern needs a token of
    about 20 characters after "Bearer". `outward` and `call` are additive to `operator-v2`; tell Tack's maintainer.
  - P55-9: `docs/CONFIGURATION.md` and `kernel/layout.py` do not list `docket-routines.json`;
    `pod-blueprints.spec.md` omits `routines/` from the `pod update` list; the recipe summary line does not name
    routines; cron day-of-month and day-of-week are ANDed, as in the existing parser; `tzdata` is not a declared
    dependency; no `--tz`-aware `HH:MM` form. A routine fires only under `docket start --dispatch`.
    A routine skip is traced as `step_skipped` because `EVENT_TYPES` is closed.
- *Phase 55 Wave 4.*
  - P55-10, a gap in the flow: nothing user-facing stores a secret under an arbitrary name such as `crm` (provider add
    and notify write only their own names; `setup_notify.store_secret` is the one writer), so a `secret:crm` reference
    needs `secrets.json` or the keyring edited by hand. Recommended: a `docket setup secret set <name>` command that
    reads the value from stdin or a prompt and never echoes it; needs the maintainer's go as a card. Sessions and the
    model's own reply carry raw tool output (the model sees it); not checked. `setup --fix` (not bare `setup`) carries
    the literal-credential warning; there is no CLI golden for `--secret` (run.sh replays readonly cases only).
  - P55-8: the check and the increment of a quota are not atomic (two concurrent sends in one pod could both pass at
    count-1); an unreadable counter counts as empty; `pod policies` and `check` do not show quotas.
  - A flake, once: `test_consult_wait.py::TestAnsweredInPlace::test_an_answer_by_the_task_goes_through_the_same_record`
    failed in the full run and passed alone (the file's other test is already on the list above).
  - Phase 56 Wave 2 merge run (2026-10-30), both passed alone: `test_consult_wait.py::TestAnsweredInPlace::
    test_a_decline_tells_the_model_to_decide_itself` (a third test of that class, so the class now has three flakes
    under load: that is its trigger), and `tests/integration/product/test_runtime_execution_envelope.py`, 8 setup
    errors from `uv build` exiting 2 in a parallel worker.
- *Declarative external services (became Phase 56, closed 2026-10-30).* The maintainer wants a pod to reach
  an external service from a `kind: service` document or commands (base URL, auth from the secret store, operations as
  read/send tools through `dispatch_tool`), with no program written per service and no more MCP implementation work. It
  reverses ADR 0036's "no native HTTP tool": written as decision 13 in the amendment of
  [ADR 0036](docs/adr/0036-a-pod-works-outward.md) (proposed 2026-10-30, not accepted; no new ADR). Sketch and open
  questions in `internal-docs/design/site-credentials-for-a-pod.md` (Addendum). Scope accepted 2026-10-30: Phase 56.
- *To investigate, important: a pod logging in to a site nobody configured.* Per-service MCP bridges and `secret:<name>`
  are fixed when a server is registered; a task that ends in a `send` at a new site that needs a login has no per-site
  credential the model never sees. Raised by the maintainer 2026-10-30. Analysis, seven open questions and a suggested
  path (ADR first, then `docket setup secret set`, then a per-site grant like the network grant, then a real run with a
  throwaway account) are in `internal-docs/design/site-credentials-for-a-pod.md`. No card yet.
- *Phase 59 merges and real runs (2026-11-03).* Seen while merging or in the first three real runs.
  - The `bash` clamp is `max(1, int(deadline - now))`, so a hop clock of 2 s ends a clamped command at 1 s and
    the clock is not yet spent (`agent/loop_steps.py`). Round it up when a `time` stop is seen to need a
    second request.
  - Only an Implementer hop that ended `budget_exhausted` is pinned (ADR 0038 decision 2 reads wider). Trigger:
    a plan of record that needs the tree of another failed Implementer hop in the patch.
  - `--resume`'s lease still uses the pod's `turnTimeoutS` + `verifyTimeoutS` and ignores a step's `timeout`;
    the per-round claim refresh covers a live claim.
  - A `budget_exhausted` stop for a finalization reply that carried tool calls is a model misbehaviour with
    `stop_reason: token_budget`; it lands as a budget outcome. Trigger: one seen in a real trace.
  - A policy `ask` on `.env.local.example` (a template, no secret) stopped the retried app-dev task. Trigger:
    the operator wants templates exempt from `block-destructive`.
- *Phase 59 planning (2026-11-02).* Left out of the phase by ADR 0038; each waits on its trigger.
  - docket continuing a budget-stopped hop on its own (ADR 0038 decision 6). Trigger: the same task
    retried after a `budget` stop with `treeChanged: true` three times in a week (audit `task.retry`
    plus the hop's `budget`).
  - A stall detector beyond identical calls (rounds that only re-read what the session already
    holds). Trigger: three Implementer `budget` stops with `treeChanged: false` in real runs.
  - The 300 s default hop clock (`AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` after P59-4). Trigger: a `time` budget stop
    whose last `bash` the clamp killed (requirement 98's marker).
  - Parallel-group resume re-runs a group's ok children with their original prompt over their
    sessions (`pod-dispatch.spec.md` "Parallel step groups" item 6). Trigger: a group child re-run
    observed in a real retry.
- *Phase 58 planning (2026-11-01).* Asks from the manager audit that Tack would not read today.
  - `actor` on `POST /tasks/<pod>` and on retry. Enqueue audits no actor (`tasks/application/queue.py`
    ~237), and retry audits neither channel nor actor (`lifecycle.py` ~188). Tack sends `actor: "tack"`
    on resolve and nothing on enqueue. Trigger: Tack links an attempt to the principal that caused it
    and sends that principal.
  - `updatedAt` on a task, stamped beside `rev` in `tasks/application/json_store.py` ~40-49. Tack follows
    changes through `rev` and would show this only for work the board did not start. Trigger: a client
    that has to show when a task last moved.
  - A hop's `output` is not in the task shape of `operator-api.spec.md`. Tack uses `artifact.summary`
    as the reply of a conversation turn. Trigger: a recorded turn whose summary is too terse to serve
    as the reply.
  - Tack's audit found that `conversation.turns` (`len(hops)`, `tasks/domain/task.py` ~315) and
    `_park_turn`'s limit (`executor.py` ~338) would count a hop parked for approval as a turn. This is
    not verified by a run. It is the same trigger as "Turns taken" below.
- *Phase 58 wave 1 (2026-11-02).* Found by the workers of P58-1 to P58-3, none in a card.
  - An escalation's `seq` is issued before its record is written (`platform/store.py::write_escalation`).
    A poller reading between the two can return a later record and move `next` past the missing one.
    Trigger: a poller that reports a missed escalation, or a second writer that opens escalations
    concurrently with a poll.
  - Blocked outcomes other than the pod budget (`_block_on_missing_resources`, the `resources` block)
    carry no `failureKind`. Trigger: a client that has to tell those blocks apart.
  - `docket pod show --json` does not carry `paused`/`pausedReason` (`pod_report` feeds it;
    `cli-json-shapes.spec.md`). Trigger: an operator who reads the pause from the CLI JSON.
- *Phase 58 close (2026-11-02).* Seen once in the real run, not reproduced.
  - `POST /tasks/<pod>/<id>/cancel` sent a few milliseconds after `POST /tasks/<pod>` answered `409
    not_cancellable` ("is running; nothing to cancel"). The spec says a `running` task is cancelled by
    killing its hop's process group, so the claim had likely set `running` before any run or hop was there
    to stop. A client that cancels right after enqueueing gets a refusal for a task that then runs.
    Trigger: a second sighting, or Tack cancelling a task it just queued.
- *Phase 57 close (2026-11-01).* Loose ends of the phase, none a card yet; each waits on its trigger.
  - Park order. `_park_turn` marks the hop parked after it was persisted unparked and opens the `turn` escalation
    while the task is still `running` (`hops/application/executor.py`). A crash between leaves an unparked hop and a
    pending `turn`; replay moves past the step and the record expires unread. The reverse order would leave a
    waiting task nobody can answer, so this is the safer failure; a consult has the same window. Trigger: a
    conversation task found ended after a restart with a `turn` still pending.
  - One `current` slot. A parallel group names the child that started last and the key goes when that child ends
    (`operator-api.spec.md`). Trigger: Tack must show every running child; `current` then becomes a list under a
    new feature name.
  - "Turns taken" is read three ways: `len(hops)` in `_park_turn` and in the task dump, answered hops in the
    budget end. They agree until a final hop fails. Trigger: a `turns` count that disagrees with the hops shown.
  - Names written twice. The `reply` option id is in `answers.py` and in `escalations.py` (`_REPLY`); `tool_queue`
    and `tool_retry` in `mcp.py` repeat one queue dump; an error `code` reaches the wire as `DocketError.code` and
    as `_send_json_error(code=)`; `task_control.py` builds a `Conflict` only to render it. Trigger: the next edit of
    any of them.
  - `decide_task_tokens` is untouched: the budget end of a conversation is decided in the executor
    (`conversation_ends_on_budget`). Trigger: a second consumer of "ended after an answered turn".
  - `rev` shows in the CLI and MCP task dumps because they print the record; Tack reads it over HTTP only.
  - The live service on `:7399` runs the code from before the phase until it is restarted, and the `docket` on
    PATH until `./install.sh` runs again.
  - Flakes under load, each passing alone, seen once: `tests/guards/test_no_removed_cli_names.py` (a 2 s timing
    bound), `test_record_store_conformance.py` (two sqlite tests: the row cut, the CSV header) and
    `test_bash_background.py::TestTheTurnLeavesNoOrphan`. A second failure of the same test is its trigger.
- *Phase 56 close (the real run and the gates, 2026-10-30).*
  - Real evidence: `tests/live/test_hacker_news_live.py` (`DOCKET_RUN_LIVE_HN=1`) ran the `hacker-news` recipe against
    `hn.algolia.com` and the local model; the fourth run passed (see P56-22 in the archive). The write path of a declared
    service (park, approve, one `POST`) against a real model was **not** repeated at this close; the deterministic e2e
    (`tests/e2e/test_declared_service.py`, a scripted model) covers it. A run with the real model is the trigger for
    the first service that sends.
  - The role prompt's "end your reply with `## Memory`" line made a local model run `echo` through `bash`, and the
    gate parked the task for an approval nobody was there to give. The `hacker-news` steps say to run no command; the
    prompt in `builtin_roles.py` is unchanged (trigger: a second pod where a model does the same).
  - P56-10 left: a producer of git evidence for a non-implementer role. The `operate` and `routine` pods are workdir
    pods with no commits, so nothing would read it (trigger: a git-backed pod whose non-implementer step commits what
    a later step needs).
  - Tack's runner sends `"blueprint": "software"` in `POST /pods` and must send `build`.
  - `summarize_recipe` does not count a recipe's `services/`; `gen_recipe_docs._brings` and
    `pod_config_library._brings` are two near-duplicates. The `captured` column of `stories` holds the day a story
    was posted (the model has no clock); the row's `_at` is the capture time.
  - Prose still behind the code: the MCP client text ("workdir blueprint such as research"),
    `README.md` line 11 ("research, content or outward work"), `builtin_roles.py:68` ("forward-compat"), and
    `config-format.spec.md` (~line 115, `load_pipeline(text)`); `_blueprint_pipeline` loads a registry only to call
    `load_pipeline(None, ...)`; `conversations.load` returns an empty registry for an invalid file.
  - Records port (P56-23, merged): a second backend is one adapter module, one line in
    `bootstrap._open_records` and one `BACKENDS` entry in the conformance suite; a remote one needs the ADR
    amendment on `send` first, and S3 is an export destination, not a backend. `teams/records.py` quotes a set name
    in ANSI double quotes (each backend would quote its own); `ReadLimits` serves `read` and `export` though
    `export` honours only `timeout_s` (a possible `ExportLimits`).
  - Live Hacker News on Anthropic: the recipe ran on `claude-haiku-5-5` with Langfuse export (digest 218.9k tokens,
    weekly report 111.1k) and `tests/live` now takes `DOCKET_LIVE_HN_PROVIDER=anthropic`, but that lane was not run
    with a real key (setup only checked with a fake one). A fake key makes the run wait out its timeout instead of
    failing on the 401 at once.
  - Records and services: `pod update` does not check that a `rec__<set>` allow-list entry names a declared set;
    real PostgREST documents carry no `operationId`; `setup service list` shows secret names; the `ask-before-send` custom message is not shown
    for service sends; service results are not screened as untrusted; `pod records --csv` overwrites silently; the
    idempotency key also hashes path and query arguments; `pod-blueprints.spec.md` should list `services/`.
  - Code: `setup_model_credentials._write_credential` duplicates store logic; `config_docs.py` imports itself;
    `_read_until_deadline` is duplicated; `decided_approval` sits in `escalations.py`.
  - Flakes under load, each passes alone: the `test_consult_wait` decline test and the `uv build` in
    `test_runtime_execution_envelope`.
- *Phase 55 close (the repeated real run, 2026-10-30).* `docket run` does not wake a `wait` whose time has passed
  ("No pending tasks"); only the dispatch service's sweep does, as the spec says; a person expecting `run` to finish
  it is surprised (trigger: a second report). In one fresh home `setup provider add local ...` left the roles on
  `anthropic/*` until `setup model preset local` ran; an earlier fresh home applied the preset by itself: reproduce
  before a card. A stdio MCP server under isolation needs its script, interpreter and venv readable, and fails with
  `mcp_client.unavailable: ExceptionGroup` while python's "Permission denied" goes only to stderr (trigger: the next
  operator who meets it). P55-14 keys its note by task and role, not step, and splits the approval's `action` on
  `; call=` rather than reading a typed field; `task show --json` carries no `approval_unused`. P55-13 adds no trace
  line when the surface drops a role-named built-in (the closed event set has none that fits).
- *Live evidence, P55-5 (2026-10-30).* A real Playwright MCP server (0.0.83, headless system Chrome) driven through
  docket's MCP layer against a local page: under `lifetime: hop` navigate, snapshot and click by ref keep one session
  (the click ran, the page title changed); under `call` the snapshot after a navigate is `about:blank` and no ref
  exists. Not a model-driven pod run. That server's click argument is `target`, not `ref`.

**Phase 54 (closed 2026-10-29).** Two items wait for their triggers.
- *Dated model ids.* The native `/models` lists `claude-haiku-4-5-20251001`, and the probe matches ids
  exactly, so `claude-haiku-4-5` never gets an observed output cap and a call without a declared
  `--max-tokens` fails by design. Trigger: a second operator who meets that refusal. Next: the probe
  matches a catalog id to the dated id that starts with it.
- *Names.* `openai_http.py` and `OpenAIChatClient` hold both wires and still carry the first one's name;
  ADR 0011, ADR 0014 and two specs quote them. Trigger: a third dialect or the next edit of either module.

**Outward work (ADR 0036, deferred with triggers; the cards are Phase 55).**

- **HTTP/SSE MCP transport** (`mcp-client.spec.md:50`). Trigger: the first real pod whose connector
  exists only hosted.
- **A per-pod `fetch` allowlist** (`kernel/home.py:278`, one list for the machine). Trigger: two pods
  on one machine that need different hosts.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed the
  previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  critic approved a malformed list.
- **Pod memory with non-path subjects** (`workspace-structure.spec.md:158-169`: a subject is a
  repository path; a workdir pod's "the client prefers a formal tone" has no home). Trigger: a recorded
  workdir run whose Lead repeats a correction a person already made.

**Standard teams and records (deferred from Phase 56, 2026-10-30; analysis in
`internal-docs/strategy/equipos-estandar-empresa-digital-2026-10-30.es.md` §8 and
`capa-de-datos-para-docket-2026-10-30.es.md`).**

- **A pod without a Lead member.** Not a blocker, so not a card: the Lead is the pod's *anchor record*
  (its workspace holds the queue, `teams/settings.py:21-26`, the settings and budget, `:29`,
  `teams/member_workspace.py:214`; `pre_input` is evaluated and session events traced as `"lead"`,
  `tasks/application/queue.py:72`, `governance/approval.py:73`), but no pipeline step has to use it: the
  `outward` recipe's pipeline already runs researcher, writer, critic, actor. Making the pod the subject is
  a persisted-state change (the queue's and settings' location). Trigger: a measured cost of the idle Lead
  member (its workspace, its row in `status`), or a pod whose operator refuses a Lead at all.
- **Measuring the three-role full pod against the four-role one** (P56-15 ships the change on the
  maintainer's request; this is the evidence it did not wait for). Trigger: a maintainer go, since the
  comparison spends hosted-model tokens on `app-dev`: the same tasks under both rosters, measured tokens
  and escaped defects.
- **A port for docket's task store** (`TaskRepository` takes the concrete `JsonTaskStore`,
  `tasks/application/repository.py:48`). Not business data, and a port with one implementation is the
  "unwired machinery" this project refuses. Trigger: a queue the one file cannot carry (measured).

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `app-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P53-4 (which absorbed P52-5) acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-2 (which absorbed P52-8), the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Escalations (left at the Phase 51 close, 2026-10-25; ADR 0032).**

- **Approval, gate and `check_changed` follow-ups still run inside `resolve`** (`approval_grant`
  and the task-grant audit in `tasks/application/escalations.py`), not on the claim path; P51-6
  stopped at PARTIAL because deferring them breaks `approved_ready`, which reads pregrants and
  `gateOverridePipelineIndex`, and P51-9's "Also" list named the move. Trigger: a change to
  `approved_ready` or to the claim path.
- **Settled escalations written before P51-11 stay in the flat `escalations/` directory**; no
  migration is written. A scan of the live directory still opens them (`platform/store.py::list_escalations`
  reads the flat folder for `pending` and unfiltered scans). Trigger: an operator whose pre-P51-11
  records slow the inbox; then move them under `settled/` once.
- **`GET /escalations?since=` reads every settled file** (`operator/inbox.py::escalation_views`
  calls `list_escalations(since_seq=...)` with no state, so `settled/` is scanned on each poll).
  Trigger: a poller whose `settled/` directory is large; then index by `seq` or bound the scan.
- **docket follows an enclosing git repository when a pod path is not itself one**
  (`platform/git.py::git_is_repo` answers `rev-parse --git-dir`, true anywhere inside a work tree),
  so it would prepare and branch the enclosing repository. Only the live-eval and smoke worlds
  refuse that today (`specs/test-framework.md`). Trigger: a pod registered on a subdirectory or
  a nested path that is not a repo.
- **`scripts/render-doc-assets.py:275` prints a made-up approval token** (`token=apr-...`) and the
  `waiting_approval` line, shapes Phase 51 removed. Trigger: the maintainer re-captures the README
  assets (a classifier-refused step); then render the escalation id and `waiting_input`.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **Timing flakes seen once each:**
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.
- **Two contract files set the merge run's floor** (measured 2026-10-28, `--durations=0`):
  `tests/contracts/test_a2a_http.py` 60 s and `test_escalation_http.py` 35 s of the 84 s run. Each
  test's function-scoped `parked` fixture runs a real `docket run` and starts a service (about 3 s
  of setup per test), and `--dist loadfile` keeps a file on one worker. Trigger: the merge run
  passes 120 s, or a card adds a test to either file. Then share one parked world per module for
  the read-only tests.

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

- **A tool deny per team member** (a read-only researcher): `tool_profile` is prose, the only denial is
  the pod-wide `deniedTools`. Trigger: a recipe or pod that needs one member without write tools.
- **Delete the old-layout reader** (`kernel/layout.py::is_legacy` and the legacy branches of `Home`).
  Trigger: the next minor release. First move what still seeds or reads an old-layout home:
  `tests/support/home.py` and `pods.py`, and the old paths named in `scripts/gen_cli_docs.py`,
  `scripts/render-doc-assets.py` and `docs/commands.md`.
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

**Phases 52 and 53 (closed 2026-10-29).** Triaged the same day: the brief redaction, the prompt `tests` file, a role's
unknown tool name, `pod test`'s handoff spec, the live-run key lookup and the stale docs were fixed; what stays waits
for its trigger.

- **P52-12, a wait on a machine is an escalation.** Absorbed by P55-6 (ADR 0036 decision 5): a `wait` step is
  an escalation of kind `wait` the sweep settles on time or on a probe; the wait on a machine is one case of it.
- **P53-4 goal 3, the Lead's locators read into the Implementer's message.** Measured on three recorded smoke tasks
  (two local Qwen, one Haiku, `context_replay.py --repeats`): the Implementer read 1/1, 1/1 and 2/4 files the Lead had
  read, but all except one were files it then edited, whose exact text `edit` needs; "not edited after" was 0, 0 and
  1 file (682 bytes). Trigger: "not edited after" reaching 30 % of the Implementer's reads on recorded tasks of a real
  pod (the smoke repository has three files).
- **The model class comes only from the rank anchors** (`economy` is `cheap`, `standard` and `premium` are `strong`),
  so a non-anchor model such as the local Qwen resolves `any` and no `<name>.<class>.md` variant acts for it. No
  shipped prompt has a variant. Trigger: a variant written for a non-anchor model.
- **Structured `task` intake** exists on `POST /tasks/<pod>` only; the CLI, MCP and Tack's runner do not send it.
  Trigger: Tack adopting it.
- **Decided, not open:** P52-2's bench oracle is "no step worse than the recorded request, and prefix stability not
  worse", met on the fixture (sent 0.25 to 0.66 of the baseline per step; stable 8/10, 3/4, 5/7, 6/7). The "+0.3 %
  to +3 %" was against the pre-P52-2 `condense_history`, which the bench's `phase44` policy now calls live, so it is no
  longer reproducible; the small-result rule stays. The re-ask, finalization and closing texts
  (`hops/application/runner.py`, `agent/loop_request.py`) are the harness's protocol, versioned with the code and the
  agent-loop spec, not role prompts. `smoke_workflow.py` calls an interpreter running a script (`PYTHONPATH=src python3
  x.py`) opaque on purpose: it can read any file, so the private-path check fails closed; `VAR=x` alone is parsed.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
