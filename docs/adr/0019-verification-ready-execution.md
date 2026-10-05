# ADR 0019 (D-54): verification-ready execution — one worktree per task, screened tool results, honest stops

**Question:** Phase 36 published what a hop keeps (evidence-v1) and made every escalation a
decision with options. An independent verifier (ADR 0017 §5) can now read docket's evidence, but
four gaps keep that evidence from being trustworthy or checkable:
- **The evidence of a task can include another task's work.** A repo Implementer has one git
  worktree for its whole life. `baseCommit` is the merge-base with the codebase's branch, so
  until the operator merges, task 2's `diffStat` also counts task 1's commits.
- **MCP tool results reach the model unscreened.** A remote tool's *description* passes
  `pre_input` before registration. Its *result*, which is just as remote, goes into the context
  as is.
- **A recipe cannot check the work against the base.** A `run:` step gets no task id and no base
  commit, so "new tests must fail on the base" and "mutate only the changed lines" cannot be
  written as recipes, although the Phase 37 outline said "no core change".
- **A looping agent burns its whole budget.** The loop stops on iteration, tool-call, token and
  wall-clock bounds. None of them notices an agent that repeats the same calls with the same
  results. On this machine's 16k endpoint, one of four dispatches on 2026-09-18 ended at
  `max_iterations=20` in the reviewer hop.

What does docket change so that a task's execution can be checked by someone other than docket?

**Where decided:** 2026-10-04, as Phase 37. It is the outline ADR 0017 left in `TODO.md`
("Planned — Phases 37–38"), opened when Phase 36 closed at `9dd871f`. Two outline claims were
false when re-verified (see Evidence), and this ADR corrects them.

**Evidence** (read at `9dd871f`; locators are symbol names, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| One worktree per Implementer, created by `docket add`, on branch `docket/<project>/<member>` | `core/pod_provisioning.py::provision_worktree`, `worktree_branch` |
| `baseCommit` is a merge-base against the codebase's *current* branch, computed per hop | `core/dispatch.py::_implementer_diff_probe` |
| MCP descriptions are screened, results are not | `core/mcp_tools.py::_screen_description`; `_build_tool._handler` returns `call_tool(...)` unchanged |
| No `pre_input` call exists on any tool result in the chokepoint | `core/tools.py::dispatch_tool` |
| A command step runs with the inherited environment and nothing task-specific | `core/dispatch.py::_run_command_step`, `edges/adapters/system.py::run_verify_cmd` |
| A pod's `mcpServers` can only name servers already declared globally | `core/pod.py::_parse_mcp_servers` |
| A recipe document set has no MCP server kind | `core/pod_apply.py` (top-level keys) |
| The loop's stop reasons have no repetition detector | `core/agent_loop.py::StopReason` |

## Decision

1. **One worktree per task.** A repo Implementer no longer gets a worktree when it is added. At
   claim time, dispatch creates `<member workspace>/tasks/<taskId>` on the branch
   `docket/<project>/<taskId>`, from the codebase's HEAD. It records `{dir, branch, baseCommit}`
   on the task. Every hop and every mechanical gate of that task runs there, and the evidence's
   `baseCommit` is the recorded one, not a fresh merge-base. A finished task's worktree and branch
   stay for the operator, who merges them. Removing the member removes its task worktrees, and an
   unmerged branch is reported, as before. In-place pods are unchanged. The per-member worktree is
   deleted outright, with no fallback (the no-shims rule).
2. **MCP results pass `pre_input`.** The MCP adapter screens each result's text as untrusted
   (`trusted=False`) with the calling role, before the result reaches the model:
   - `block`: the result is replaced by a refusal naming the policy, and an audit entry is
     written;
   - `redact`: the redacted text is returned;
   - `warn`: the text passes and an audit entry is written.

   Built-in tools are unchanged: their output comes from the operator's own workspace.
3. **Command steps get the task's coordinates**, as environment variables:
   - `DOCKET_TASK_ID`;
   - `DOCKET_BASE_COMMIT` and `DOCKET_HEAD_COMMIT`, taken from the latest successful Implementer
     hop's evidence and empty when there is none.

   This is the one core change the check recipes need.
4. **A `no_progress` stop reason.** The loop fingerprints each tool round (tool, canonical
   arguments, outcome, result digest). When `N` consecutive rounds bring nothing that was not
   already seen in the turn, it stops with `no_progress`. `N` is `AGENT_LOOP_NO_PROGRESS_ROUNDS`,
   default 3. A repeated failing call, an edit that flips a file back and forth, and a re-read
   loop all match. A check that newly passes is a new result, so it never matches. It is a stop
   condition, like every other bound, and never a retry.
5. **Recipes may declare MCP servers.** A recipe may ship `kind: mcp-server` documents. `docket
   pod <p> apply` installs them pod-scoped, each with its declared read/write capability (the
   document's `access:` field, because `kind:` is the envelope), and the dry-run summary lists
   them. A stdio server spawned for a turn starts in that turn's root, so a server that takes
   `--workspace .` sees the task's worktree. Only the operator's apply command makes them live, as ADR 0012 requires for
   everything that comes from a repository. A pod-scoped server is selectable by that pod's
   `mcpServers` only.
6. **Four check recipes and one code-intelligence pack, as data:**
   - `mutation`: a `run:` step scoped to the lines changed since `DOCKET_BASE_COMMIT`, with a
     threshold;
   - `anti-tautology`: new tests must fail on `DOCKET_BASE_COMMIT`;
   - `spec-writer`: tests written from the brief by a different model before the Implementer;
   - `cross-family-review`: a reviewer step whose `model:` comes from another provider family;
   - `code-intel`: MCP servers for structural search and language intelligence, declared
     `kind: read` only where the server really cannot write.

   docket runs these checks and records their output. It never turns them into a score (ADR 0017
   §5).

## What this reverses or amends

| Earlier decision | Now |
| --- | --- |
| One worktree per Implementer, created by `docket add` | Reversed: one per task, created at claim. |
| `baseCommit` = merge-base with the codebase's branch (P35-4) | Amended: the commit the task's worktree was created from. |
| MCP servers are declared globally and pods select them (ADR 0009) | Amended: a recipe may declare pod-scoped servers, live only through `pod apply`. |
| Phase 37 outline: "Recipes, no core change" | Corrected: command steps needed the task's coordinates (decision 3). |

## Cut and deferred

| Item | Status | Why |
| --- | --- | --- |
| docket merging a task branch | Cut | The plan of record or the operator merges. docket reports the branch. |
| Retention for finished task worktrees | Done (Waves 89–90) | The operator asked: `docket pod <p> worktrees prune`. ADR 0020 "Closed by Waves 89–90". |
| Screening `fetch` results | Deferred | `fetch` is domain-allowlisted by the operator. Trigger: an injection seen through an allowlisted domain. |
| Parallel tasks in one pod | Phase 38 | Per-pod sweep workers; a worktree per task is the precondition this phase supplies. |
| A mutation or tautology score in evidence-v1 | Cut | ADR 0017 §5. The command's output is the evidence. |

## Test discipline

The integrator owns two tests that cross the seams:
- **task worktree → evidence**: two tasks dispatched in a row on one pod, with nothing merged.
  Task 2's evidence `baseCommit` is its own worktree's base, and its `diffStat` does not count
  task 1's files.
- **evidence → command step**: a pipeline whose `run:` step prints `DOCKET_BASE_COMMIT`. It
  equals the Implementer hop's evidence `baseCommit`, read back through `task_evidence`.

Both exist: `tests/integration/test_task_worktrees.py::test_two_tasks_back_to_back_each_get_their_own_branch_and_directory`
and `::test_a_command_step_gets_the_task_id_and_the_evidence_commits`.

**The check recipes run more than the classifier sees.** `anti-tautology` and `mutation` are each
one `python3 -c '...'` command step, which classifies `allow`. The git and test-runner processes it
starts are not classified. That is the classifier's existing rule for an interpreter on the curated
list, not a new hole: the pipeline comes from the operator's own `pod apply`. Each recipe's README
names the commands it runs.

### Live run (2026-10-04)

Run against the local llama.cpp endpoint (`127.0.0.1:8081`, 16k context,
`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`), with a throwaway `HOME` and model `local/local-model`. The pod
was a default `docket init` (Lead, Implementer) on a git repo. Its pipeline was Lead →
Implementer → a `run:` step that printed the task's coordinates and `git diff --stat
"$DOCKET_BASE_COMMIT" HEAD`.

- `docket init` created no worktree: `git worktree list` showed the main checkout only.
- **Task 1** (`square(x)`) finished `done` in 3 hops (1m51s):
  - it ran in `tasks/<taskId>` on `docket/myapp/<taskId>`;
  - the evidence `baseCommit` equalled the recorded one, and the `diffStat` was 1 file, +4;
  - the command step printed the same base and head, and a diff of `calc.py` only.
- The codebase then moved on by one commit, and **task 1 was not merged**.
- **Task 2** (`cube(x)`) finished `done` in 3 hops (1m26s):
  - its worktree was based on the new HEAD;
  - its `diffStat` was 1 file, +4, with `square` absent.

  Before this phase, the base would have been the old merge-base and the stat would have counted
  both tasks.
- An earlier attempt failed on an operator error (the local preset was not selected, so the Lead
  resolved to an unconfigured hosted provider). Its task worktree had already been created at claim
  and stayed.
- Found, not fixed here: `core/trace.py::_REDACT_PATTERNS` turned the printed `task=task-<uuid>`
  into `ta[REDACTED]`. The pattern's `sk|pk|api|key|tok|...` alternation has no left boundary, so
  the `sk=` inside `task=` matches. Narrowing a secret pattern needs its own card.
