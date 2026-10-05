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
| Retention for finished task worktrees | Deferred | Trigger: a disk that fills, or an operator asking twice. Removing the member already cleans them up. |
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
