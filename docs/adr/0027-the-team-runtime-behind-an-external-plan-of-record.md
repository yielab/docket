# ADR 0027 (D-63): docket is the team runtime behind an external plan of record

**Question:** Tack, the project manager that decides what work is done, with what priority and
budget, and that owns push, pull request, merge and the L3/L4/L5 autonomy setting (Tack ADR
0079), runs docket today through `docket exec --contract 1.2`: one throwaway agent per attempt,
in a checkout Tack owns, with no team, no recipe and no role. That bypasses everything docket is
for -- the pod, the models per role, the pipeline and its gates, the policies, approvals and
consultations. What must docket add so that an external plan of record sends every piece of work
to a long-lived pod, through one harness with no modes, and never has to work around docket?

**Where decided:** 2026-10-14, by the maintainer, as the brief for Phase 43 (docket
0.2.0-beta.6). The measurements and the code reading behind each point are in "Evidence".

## The request, on one screen

1. **One door: HTTP against `docket start --dispatch`, API version 5.** An external plan of
   record enqueues into a pod, follows the pod's trace with the cursor that already exists, and
   reads, cancels, retries and diffs a task over the same routes. `docket exec`, harness
   contracts 1.0 to 1.2, `docket setup harness` and `core/harness.py` are deleted with their
   tests, schemas and fixtures (ROADMAP D-57: nothing is kept for the past). `docket task add` and
   `docket run` remain the foreground path for a person at a terminal.

2. **A task is addressable and self-describing.** `POST /tasks/<pod>` and `docket task add`
   accept, all optional: `externalRef` (a caller label, filterable), `idempotencyKey` (the same
   key returns the same task, `200` instead of `201`), `baseRef` (the branch or commit the task
   worktree starts from, so a rework continues on the previous attempt's branch), `pipeline`
   (a pod-local pipeline or a shipped methodology recipe, so a bug runs `tdd` and a feature
   `dual-review` in the same pod), `gate` (an external gate command added after the last
   implementer step), `maxTokens` (a measured budget for the whole task) and `restrictions`.

3. **A task's restrictions can only narrow.** `restrictions` carries `deniedTools` (unioned
   with the role's and the pod's denials), `network: none` (the hop's jail network is the
   narrower of pod and task) and `policies` (documents whose every rule is `block`; any other
   action is a `422`). Nothing on a task can grant what the pod does not have. This is the
   security condition Tack states as "the agent reaches only what you gave it".

4. **The trace tells the story per hop.** Two typed events, `hop_started` and `hop_finished`
   (task, step, role, member, model, provider, rework cycle, and on finish: ok, verdict, usage,
   duration), join the trace vocabulary; a persisted hop records `model` and `provider`; a
   finished task records `usage` totals by model. `GET /traces/<pod>?since=` delivers them
   exactly once, as it does today. No SSE, no push: the consumer polls a cursor.

5. **The lifecycle is complete over HTTP.** `GET /tasks/<pod>/<id>`, `POST .../cancel`,
   `POST .../retry`, `GET .../diff` (the patch of the task branch against its base commit, plus
   the untracked files while the worktree exists). Cancel moves from `cli/_task.py` into
   `core/`, so CLI and HTTP share one function.

6. **A pod is readable and applicable over HTTP.** `GET /pods`, `GET /pods/<p>` (the report
   `docket pod show --json` builds, moved to `core/`, plus the effective `profile` and its
   violations), `POST /pods` with `ensure: true` (an existing pod answers `200`, nothing changes),
   `POST /pods/<p>/apply` (a directory, `dryRun`, `accept`; the same review rule as ADR 0024 §6,
   HTTP counts as off a terminal), `GET /pods/<p>/corrections?since=`.

7. **A repository may hold several teams.** `.docket/teams/<pod>/` beside `.docket/`, resolved by
   one function for `init --name`, `pod update`, `pod export`, `pod validate` and `docket run`.
   Changing a team is a pull request on that directory.

8. **Lights-out and research coexist as they are.** `fetch` runs in docket's process, outside
   the jail, behind its domain allowlist; a lights-out pod with the jail's network cut still
   reads the web it was allowed. A pod that needs a networked MCP server runs `attended`.
   The profile does not change.

9. **The daemon can be supervised.** `docket start` gains `--bind`; a first stop signal
   finishes the running task and claims no other (today it finishes the whole sweep); the sweep
   resumes a stale claim on restart (today only `docket run --resume` does); a task posted while
   dispatch is on is swept at once; `/health` reports the dispatch loop.

10. **Deferred, each with its trigger.** Parallel tasks inside one pod (trigger: a pod's queue
    waits longer than one hop with a remote provider, measured over a week of real use; the
    task record and the claim already allow it); a warm workspace (measured: `npm ci` 6.5 s and
    the build 15.5 s per worktree; trigger: a pod whose build exceeds two minutes, or the disk
    the retained worktrees take); aggregate statistics (the consumer holds the records and
    computes them); SSE or any push.

11. **Version.** `SERVE_API_VERSION` moves from `4` to `5`; docket `0.2.0-beta.6`. A consumer
    negotiates by reading `apiVersion` from `GET /status.json` and names the version it needs.

## What this does not buy

Multi-tenancy, authentication for external callers beyond the Bearer token, queues, streaming,
per-customer quota, a dashboard, merging, pull requests, a signed verdict or any dollar figure.
Tack merges and counts money; the verifier signs; docket runs the work and records what it did.

## Consequences

- The contract between an external consumer and docket is `specs/api/operator-api.spec.md`,
  version 5. `specs/data/serve-read-api.spec.md` keeps the unchanged read routes.
- ADR 0001 (harness mode), ADR 0016's "Tack polls" paragraph and ADR 0026 are superseded on
  the harness: the capability moved to the pod and the HTTP routes. Their reasoning stays.
- Twelve cards in three waves, `TODO.md` Phase 43; packets in
  `.agents/handoffs/phase-43-worker-packets.md`.

## What the consumer changes

One harness, no modes. Tack designs it in its own repository; what it needs from this side:

- Start and supervise `docket start --dispatch --bind 127.0.0.1 --port <n> --token-file <f>`;
  read `apiVersion` from `GET /status.json`; refuse anything but `"5"` by name.
- Ensure the pod: `POST /pods {"name","location","blueprint":"software","ensure":true}` gives
  the lean default team (lead + implementer); a project with `.docket/teams/<pod>/` gets its
  teams from `docket init --name <pod>` run by the operator, or `POST /pods/<p>/apply`.
- Submit: `POST /tasks/<pod>` with `externalRef` (board item and attempt), `idempotencyKey`,
  `baseRef` (the previous attempt's branch on a rework), `pipeline` per item kind, `gate`
  (its acceptance command), `maxTokens` from its profile, `restrictions` from its permission
  policy, `trusted` as today.
- Follow: `GET /traces/<pod>?since=<cursor>`; answer `approval_required` with
  `POST /approvals/<token>` and a parked question with `POST /tasks/<id>/answer`; read the
  terminal status from `GET /tasks/<pod>/<id>`.
- Collect: `GET .../diff`, `GET .../evidence`, the task's `worktree.branch` and
  `worktree.baseCommit`; push the branch and open the pull request itself.
- Drop: `docket exec`, the contract 1.2 probe, `docket setup harness --json`, the NDJSON
  parser, the generated policy document (now `restrictions`), `--max-tokens` (now `maxTokens`).
- Retro: `GET /pods/<p>/corrections?since=` plus its own hop records; a proposed change is a
  pull request on `.docket/teams/<p>/`, applied after merge by `docket pod update` or
  `POST /pods/<p>/apply`.

## Open questions

Blocking (decide before Wave 111):

1. **Delete `exec` in beta.6, or one release later?** Tack still runs contract 1.2 today. The
   default is deletion in beta.6 with Tack's cutover in the same step: both are one operator's,
   docket has no other user, and a kept command is the shim D-57 forbids.

Not blocking (a default is chosen; say so if it is wrong):

2. **Five pods, one checkout.** Each pod member records the same `codebase`; task worktrees come
   from that one repository; `docket` commands in that directory need `--pod` (the cwd match
   is a tie, as today). Default: share the checkout.
3. **A research pod that needs a networked MCP server.** Default: it runs `attended`; a
   per-server network grant would be new semantics and waits for a measured need.
4. **Apply over HTTP for a directory that runs things.** Default: `accept` is required exactly
   as off a terminal (ADR 0024 §6); nothing is created without it.
5. **Long hops.** A pod's `turnTimeoutS` already exists; nothing per task. Default: none until
   a real run of an evaluation-style task measures the need.

## Evidence

Read on `develop` at `e5c8c784` on 2026-10-14; every live run used a throwaway home, never
`~/.docket`.

**What exists and what is missing**, from the code, not the roadmap:

| Need | Found | Where |
|---|---|---|
| Addressable task | missing: `POST /tasks/<pod>` takes `description`, `priority`, `trusted`, `brief`; the id is always `uuid4` | `serve.py::_handle_post_tasks`, `core/dispatch.py::enqueue_task` |
| Base of the worktree | always the codebase's HEAD | `core/pod_provisioning.py::provision_task_worktree`, `edges/adapters/system.py::git_worktree_add` |
| Pipeline per task | resolved once per pod, before the claim loop | `core/dispatch.py::effective_pipeline`, `dispatch_pod` |
| Restrict per task | missing; `pregrants` is the opposite (it widens) | `serve.py::_handle_post_task_pregrant` |
| Parallel tasks in a pod | one claim at a time per pod; the sweep pool parallelises pods (`DISPATCH_SWEEP_WORKERS`, 4) | `dispatch_pod`'s `while` loop, `serve.py::_submit_pod_sweep` |
| Cancel, retry, diff over HTTP | missing; only `do_GET`/`do_POST` with no such routes. `retry_task` and `cancel_parked_task` exist in core; the live-run cancel lives in `cli/_task.py::_cancel_live_runs` | `serve.py`, `core/dispatch.py`, `core/runs.py::cancel_run` |
| Events with a cursor | present: `GET /traces/<pod>?since=` is exactly-once with a compound cursor (P22-3). Missing: no hop-level typed event; the hop start is a `tool_call` record `{"hop", "agent"}`, the end a `tool_result`/`error` with the output as text | `serve.py::_traces_page`, `core/dispatch.py::_compose_hop`, `_persist_hop_and_trace`, `core/trace.py::EVENT_TYPES` |
| Model and provider per hop | missing on the hop record (`usage`, `costUsd` only); present on every `llm_call` event | `core/dispatch.py::_hop_record` |
| Pod configuration over HTTP | missing; `POST /pods` only provisions and answers `409` when the pod exists; the report exists in `cli/` | `serve.py::_handle_post_pods`, `cli/_pod_show.py::pod_report` |
| Several teams per repo | missing: one `.docket/` per repository at three sites | `cli/_agents.py::_resolve_repo_apply_source`, `cli/_pod_config.py::_repo_docket_dir`, `cli/_run.py` |
| Corrections | present in core, not exposed | `core/corrections.py::read` |
| Lights-out vs research | `fetch` is a built-in handled in docket's process (`edges/adapters/fetch.py::fetch_url`, urllib), never through `jail_launch`; the jail covers `bash`, `verifyCmd`, `run:` steps and stdio MCP servers | `core/profile.py::lights_out_violations`, ADR 0024 |
| Supervision | `/health`, a two-stage `_StopController`, `--token-file` and `bind=` on `run_serve` exist; the CLI exposes `--port` only; the sweep calls `dispatch_pod` without `resume` | `serve.py::_StopController`, `_sweep_one_pod`, `cli/_service.py` |

**Measurement 1, the cost of a fresh worktree** (the Fabulada repository, Next.js, 488 packages):

```
git -C <fabulada checkout> worktree add <scratch>/wt HEAD
/usr/bin/time -f 'npm ci: %e s' npm ci --no-audit --no-fund     # 6.47 s (6.15 s second run)
/usr/bin/time -f 'build: %e s' npm run build                     # 15.45 s
du -sh node_modules                                              # 829M
```

Time is not the cost; disk is. A warm workspace is deferred with the trigger in point 10.

**Measurement 2, one llama.cpp slot under concurrent requests** (`/props`: `total_slots: 1`,
`n_ctx: 32768`; 120 completion tokens each, `temperature: 0`):

| Concurrent requests | Wall time per request (s) |
|---|---|
| 1 | 4.9 |
| 2 | 5.0, 10.6 |
| 3 | 4.6, 9.4, 13.6 |

The server queues; nothing fails. Parallel tasks inside a pod would only wait in line on this
provider, which is why point 10 defers them to a trigger measured with a remote provider.

**Measurement 3, a stop signal mid-hop** (throwaway `HOME`, local model, one pod, one task,
`docket start --dispatch --port 7399`, `kill -TERM` while the implementer hop ran):

- The daemon printed `stopping: waiting for 1 pod sweep(s)` and exited `0` after **91 s**: the
  first signal waits for the whole sweep, which here was the task's remaining two hops. With a
  queue of ten tasks the wait would be the ten tasks. Point 9 bounds it to the running task.
- The task ended `failed` on its own (`implementer hop failed: no progress`, the local model
  repeating `edit`) before the stop took effect, so the restart found nothing to resume. The
  resume path was read instead: `_sweep_one_pod` calls `dispatch_pod` without `resume`, so a
  claim abandoned by the second signal becomes `stale_claim` and stays `failed` until a person
  runs `docket task retry`.
- Observed trace vocabulary for the run: `session_start`, `context_composed`,
  `prompt_composed`, `request_fit`, `llm_call`, `tool_call`, `tool_result`, `process_started`,
  `process_exited`, `session_compaction`, `error`, `session_end`. No hop-level event.
- A side finding, not in this phase: the Lead's plan named the codebase path and the
  Implementer's `read` of that path was refused (`tool.refused`, audit seq 6-7) because its
  roots are the task worktree. Recorded as a follow-up in `TODO.md`.

**The four other projects the design was checked against** (so it is not shaped to one case):
an API + ML project (an evaluation task whose result is a report, a networked eval pod, cheap
local docs), a monorepo (one pod per app on one repository, a feature as two chained tasks),
a SaaS with customer tickets (external ids, untrusted text, an ops pod with approvals) and a
research/content/animation set (no `verifyCmd`, `run:` steps, artifacts outside git). Six needs
appeared in more than one case and are the ones in points 2 to 7; what appeared once is in
point 10.
