# ADR 0038 (D-81): a step's budget is a checkpoint, not a cliff

**Status:** Accepted (2026-11-02, the maintainer's request). Phase 59 in `TODO.md` carries it out.
The maintainer accepted the decisions, including 5 and 6, and the names they introduce
(`budget_exhausted`, `failureKind: budget`, the hop's `budget`, `source`, `retryContinues`) on
2026-11-03. **Amended 2026-11-03**, before Phase 59 was pushed: decision 5 is rewritten (a budget,
a clock and guards). Rounds and tool calls are guards owned by the machine, not budgets declared on
a step or a role; tokens are the budget, a pod's `budgetTokens` replaces `budgetUsd`, and docket
keeps no dollars at all. The step
and role `maxIterations`/`maxToolCalls` that P59-4 shipped are deleted.

**Question:** A real Implementer hop stopped at `max_iterations=20` with its change written but not
verified. It had used 6 % of its token budget and 77 s. What should a hop's budget be, what must
happen when it runs out, and what must a retry do, so that short tasks, long tasks and confused
models are all handled by one structure?

**Where decided:** 2026-11-02, read on `develop` at `a268257b` and reproduced with the e2e harness
(`tests/support/e2e.py`, `FakeModel`).

## What the code and a run say today

- **The incident.** Task `task-0a050f9c` on an app-dev pod used `claude-haiku-5-5` and made 20 model
  calls and 25 tool calls (cap 40). It counted 117 415 of 2 000 000 tokens and ran for 77 s. The
  write came at round 14 and the last edit at round 19. The task prompt required lint, types and tests
  before finishing, and none of them ran.
- **Measured rounds per hop.** Real traces in the live home and the 2026-10-24 backup hold 90
  finished hops. Successful Implementer hops: n=15, p50 4, p90 12, max 13. Every successful hop of
  any role used at most 14 rounds. All of them were short tasks; no long task has been measured.
- **Five stop bounds, unequal.** Tokens are task-wide (`maxTokens` minus earlier hops,
  `hops/gates/pre_hop.py` ~90-126). Time is per hop (step `timeout` > pod `turnTimeoutS` > 300 s).
  `max_tool_calls` is step > archetype > env (`driver_support.py::_hop_max_tool_calls`).
  `no_progress` catches identical repeated calls. `max_iterations` is env-only
  (`kernel/home.py:135`), and at 20 it is below the tool-call cap, so it is always the bound that fires
  first.
- **Each bound is declared somewhere else, under rules that disagree.**

  | Bound | Step (pipeline YAML) | Role | Pod | Machine (environment) |
  | --- | --- | --- | --- | --- |
  | Rounds | no | no | no | `AGENT_LOOP_MAX_ITERATIONS`, 20 |
  | Tool calls | `maxToolCalls` | `maxToolCalls` | no | `AGENT_LOOP_MAX_TOOL_CALLS`, 40 |
  | Time | `timeout` | no | `turnTimeoutS` | `teams/settings.py::DEFAULT_TIMEOUT`, 300 |
  | Tokens | no | no | no | the task's `maxTokens`, else `AGENT_LOOP_TOKEN_BUDGET` |

  Two of these rules point the wrong way. Under `docket start`, `DISPATCH_TURN_TIMEOUT_S` and
  `DISPATCH_VERIFY_TIMEOUT_S` win over the pod's own setting (`pod-dispatch.spec.md` "Timeouts" 2-3),
  so a machine value beats a declaration. `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` is never read on the hop
  path: `driver_support.py::_loop_config` always passes the hop's resolved timeout. Yet
  `docs/troubleshooting.md` tells the operator to raise that variable. Nothing tells the operator
  where a limit came from: the incident took a reading of `kernel/home.py` to find the 20.
- **Running out is reported as a model error, or as success.**
  - Rounds, tool calls and wall clock stop with `failure_kind="invalid_output"`, or `"timeout"`
    for the wall clock (`agent/loop_budget.py` ~127-158, `loop_steps.py` ~107-118).
  - A wall-clock stop is retried in place as if it were a transport hiccup (`runner.py`
    `_RETRYABLE_FAILURE_KINDS`), and the retry resends the original prompt over the persisted
    session.
  - The token bound already has a landing: requirements 51-54 make one tool-free finalization
    request. Its answer, however, returns `ok=True, final_message`, so an unfinished hop passes to
    its gate as a success.
- **A failed hop's work is invisible.** `hop_diff_probe` runs only when the hop is ok
  (`tasks/application/record.py` ~348). The tree stays dirty and uncommitted, and the task's patch
  is empty.
- **A retry skips the failed step (reproduced).** `replay_pipeline_position` advances past every
  non-parked hop, ok or not (`record.py` ~184). The reproduction used `lead → implementer →
  reviewer` with `AGENT_LOOP_MAX_ITERATIONS=3`. The Implementer wrote `app.txt` and stopped. After
  `docket task retry` and `docket run`, the Implementer was never called again. The Reviewer ran,
  its diff probe committed the Implementer's unverified tree under the Reviewer's hop, and the task
  settled `done`.

## Decisions

1. **Running out of budget is its own outcome.** Four bounds stop a turn this way: rounds, tool
   calls, tokens and wall clock (decision 5 says which are budgets and which are guards). Hitting any of them yields `failure_kind="budget_exhausted"` on the turn
   and `failureKind: "budget"` on the task. The hop record carries `budget: {bound, limit, used,
   treeChanged}`. It is never retried in place. `timeout` now means only a request or transport
   timeout. `no_progress`, the denial ceiling, cancellation and approvals keep their own kinds,
   because they report behaviour, not spend.
2. **Work is never lost.** A failed Implementer hop that leaves a dirty tree is pinned like an ok
   one: a commit on the task branch, `filesChanged` and evidence. It stays `ok: false`, so no gate
   reads it as finished. The patch shows what was done.
3. **One landing for every budget bound.** The token finalization of requirements 51-54 becomes
   the landing for all four bounds:
   - once per turn;
   - a request-only trailing instruction that names the bound, with no tools;
   - the cached prefix stays byte-identical;
   - one grace request past the rounds or wall-clock limit;
   - the request must still fit the window and the token budget, or the stop is hard.

   The answer is the hop's report: what is done, what is left, whether the checks ran. It is
   persisted, but it is never a success. A verdict in it is never parsed, so a Reviewer that runs
   out cannot approve.

   One notice reaches the model when any bound first has a quarter or less left. It trails the
   next request as a user message and is never stored, so the model can verify and leave the tree
   consistent before the end.
4. **A retry re-runs the step that failed, and continues it.**
   - Replay treats a failed hop like a parked one: its index runs again, with the rework state it
     carried.
   - A re-run on a step whose session already holds that hop's rounds gets a continuation message
     (why it stopped, its report, the changed paths) instead of the original prompt. The same
     applies to an in-place transient retry whose failed attempt persisted rounds.
   - "Start over" is not a retry mode. It is a new task, optionally with `baseRef` set to the old
     branch, as `operator-api.spec.md` already says.
5. **A budget, a clock and guards; each has one owner** (amended 2026-11-03). Three questions were
   one word: how much a task may spend, how long a step may take, and when a loop has run away.
   - **The budget is tokens, owned by the spender.** The task's `maxTokens` (the plan of record,
     `docket task add --max-tokens`) bounds one task. A pod's `budgetTokens` bounds the pod's
     counted tokens across tasks; reaching it blocks the task with `pod_budget` and pauses the pod,
     as `budgetUsd` did. `budgetUsd` is deleted: docket records no dollars, so it gated an estimate
     from a price table, and a model with no catalog price was never gated at all. Tokens are
     never a step key, because the same pipeline runs tasks of different worth. **docket keeps no
     dollars** (the maintainer, 2026-11-03): no price in the provider catalog, no cost on a turn,
     a hop or a task, no estimate in `status`, `run`, `task list`, `/metrics` or an export. A
     dollar figure was a catalog price times measured tokens, a second number that went stale and
     did not exist for an unpriced model; whoever pays converts tokens at their own rate.
   - **The clock is seconds per hop, owned by the work.** The step's `timeout`, then the pod's
     `turnTimeoutS` (a repository's slow part, its test suite, belongs to the repository), then
     the machine's `AGENT_LOOP_WALL_CLOCK_TIMEOUT_S`, read by `resolve_timeout` in place of the
     `DEFAULT_TIMEOUT` constant. `docket run --timeout` keeps its place, one person's choice for
     one run, in the pod's slot. `DISPATCH_TURN_TIMEOUT_S` and `DISPATCH_VERIFY_TIMEOUT_S` are
     deleted: a machine value never overrides a declaration.
   - **Rounds, tool calls and identical repeats are guards, owned by the machine.** They catch a
     loop that ran away; they do not size work, so no step, role or task declares them. A round or
     a tool call is not a cost: a cap on them, set as a budget, cut legitimate work (the incident
     stopped at 6 % of its tokens; a 42-round task finished about two calls under the old default
     of 40) and needed four layers of configuration. The guards are `AGENT_LOOP_MAX_ITERATIONS`,
     200, and `AGENT_LOOP_MAX_TOOL_CALLS`, 400, plus `no_progress`. Both numbers are judgments, far
     above every measured hop (short hops at most 14 rounds; the long one 42 rounds and about 38
     calls), so tokens and time stop a costly hop first. A guard stop is still `budget_exhausted`
     with a landing and a report, and its `source` is always `default`.
   - **Every resolved limit says where it came from and what raises it**: `source: task | step |
     pod | default` and `raise`, the one key or machine variable that raises it. Both are typed
     fields of the hop's `budget` (`{bound, limit, used, source, raise, treeChanged}`), so a plan of
     record never parses the stop message, which is built from the same values; and
     `docket pod plan` prints each step's resolved clock and the token budget with their sources.
   - **No other levels.** No per-task budget object, no per-step map of budgets, no
     pipeline-wide defaults block, no machine ceiling over what a repository declares.
   - **A long declared clock must not look like a crash.** Today the claim is refreshed only when
     a process starts (`driver_support.py` ~446) and at a hop's end. The stale-claim sweep
     (`max(CLAIM_STALE_TIMEOUT, lease)`) and `--resume`'s lease (`turnTimeoutS + verifyTimeoutS`)
     could therefore fail a hop that is still making rounds. The claim is refreshed every model
     round (P59-4 reproduced the stale sweep and shipped the refresh).
6. **Continuing is the plan of record's call, not docket's.** docket does not auto-continue a hop
   that ran out. It supplies the facts: the bound, the report, the pinned diff, and whether the tree
   changed. Tack or the operator decides whether another budget is worth spending. Spending
   requires a judgment, and docket stays single-operator with no planner of its own (ADR 0037).
7. **Fewer wasted rounds.**
   - `edit` answers with the workspace-relative path that `write` already prints. The absolute
     path into the home cost the incident one round.
   - The Implementer's identity prompt asks it to read a file whole with `read`, and to batch
     independent calls in one reply.

## Real cases this must hold for

| Case | What happens after Phase 59 |
| --- | --- |
| Short task, slightly over budget (the incident) | Notice at 75 %; landing report; task `failed`/`budget` with the patch; one retry continues and runs the checks |
| Long multi-file feature | The step declares its `timeout`, the task's `maxTokens` sizes its spend, the guards sit far above it; in-turn compaction (requirements 47-56) keeps the context bounded; if it still runs out, the stop is a checkpoint with a report |
| Long test suite | A bash call is clamped to the remaining time; the time bound lands with a report; the hop is not retried in place; `verify:` gates run outside the turn |
| Confused model, re-reading | Tokens and time bound the cost; `no_progress` stops identical repeats; the report and `treeChanged: false` tell the plan of record not to continue |
| Reviewer runs out | The hop fails with `budget`; no verdict is read; the task never passes on a forced answer |
| Local 32k model | The landing request passes the window check or stops `context_fit`; the notice is one line |
| Retry after any failed hop | The failed step runs again; its session continues; the next step never sees unfinished work as finished |
| Crash mid-hop (stale claim) | Unchanged: `--resume` replays from the persisted hops, and a failed hop now re-runs instead of being skipped |

## Not decided here

- These items each wait on a trigger in `TODO.md`'s follow-ups under "Phase 59":
  - automatic continuation inside docket (decision 6);
  - a stall detector beyond identical calls;
  - the 300 s default hop clock.
- Decided against by the 2026-11-03 amendment of decision 5, so no longer waiting: per-role default
  budgets, a per-step budget sent with one task (a task sizes its spend with `maxTokens`), and a
  machine ceiling over what a repository declares.
- Parallel-group resume, which re-runs a group's ok children (`pod-dispatch.spec.md` "Parallel step
  groups" item 6), is a known limit and is not changed here.
