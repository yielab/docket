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

## ▶ ACTIVE BOARD — Wave 110 COMPLETE 2026-10-17 (Phase 43); Wave 111 next

Wave 109 (P43-1..5) merged from base `1ee0d907` (rollup `f102abce`). Wave 110 (P43-6..9)
merged into `develop` from base `299863be`: merges `2cb1079e`, `9b008806`, `2f7a84f8`,
`d3f6dcc2`, the seam fix `cc5c08dc` (both defaults on `repo_config_dir`), then the rollup.
Wave 111 (P43-10..12) is claimable: open it with this banner and a new base commit.

## ◆ PHASE 43 — the team runtime behind an external plan of record (D-63, ADR 0027) — IN PROGRESS (Waves 109-110 complete, Wave 111 next) 2026-10-14

Brief: [ADR 0027](docs/adr/0027-the-team-runtime-behind-an-external-plan-of-record.md). Contract:
[specs/api/operator-api.spec.md](specs/api/operator-api.spec.md) (5.0.0, planned). Packets:
`.agents/handoffs/phase-43-worker-packets.md`. Target `0.2.0-beta.6`, `SERVE_API_VERSION` 5.

Three waves, scheduled by file contention. **Wave 109** (the task: P43-1..5) and **Wave 110** (the
pod: P43-6..9) are independent of each other and may run at the same time; **Wave 111** (the
daemon and the command: P43-10..12) starts after both merge. Inside a wave, `core/dispatch.py` is
the hotspot: each card names the functions it owns and the integrator merges in card order.
`Model` is the worker the packet assumes (Sonnet for a card with a design seam, Haiku for one that
is mechanical with an exact locator); the integrator may upgrade, never downgrade.

Every card: spec first (version bump + changelog + requirement text), RED test recorded, smallest
change, the full gates of "Definition of done" above, no board/README/CHANGELOG edits (report the
line). Every manual run uses `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket`, never
`~/.docket`. Deferred with named triggers, not cards: parallel tasks in a pod, a warm workspace,
SSE, aggregate statistics (ADR 0027 point 10).

### Wave 109 — the task

### P43-1 — an addressable task over HTTP and CLI

- **Status:** DONE 2026-10-14 (`aa5e5355`) · **Size:** M · **Model:** Sonnet
- **Trigger:** ADR 0027 evidence table rows 1 and 2: `POST /tasks/<pod>` takes four fields and
  every id is `uuid4`; an external plan of record cannot retry safely or find its task.
- **Goal:** `enqueue_task` accepts `external_ref`, `idempotency_key`, `base_ref`, `pipeline`,
  `gate`, `max_tokens`, `restrictions` (validated here, stored on the task record verbatim);
  the same `idempotency_key` in the queue returns the existing task and enqueues nothing;
  `POST /tasks/<pod>` threads every field and answers `201`/`200` with `created`;
  `GET /tasks/<pod>?externalRef=&status=` filters; `GET /tasks/<pod>/<id>` returns one record
  (`404` otherwise); `docket task add` gains the six flags (`--gate` takes the command string).
- **Non-goals:** acting on any field at claim or hop time (P43-2, P43-3, P43-4); the CLI's
  `--restrictions` (HTTP only; a person uses `pod set deniedTools`).
- **Files/functions:** `core/dispatch.py::enqueue_task`, `_normalize_task`, a new
  `validate_task_options(...) -> TaskOptions` (Pydantic, in `core/dispatch.py` or
  `core/task_options.py`); `serve.py::_handle_post_tasks`, the `GET /tasks/` branch of `do_GET`;
  `cli/_task.py` `task add`. Forbidden: `_claim_next_task`, `dispatch_task`, `_compose_hop`.
- **Acceptance:** a seeded pod in a temp home; `POST` twice with the same `idempotencyKey` →
  one task in `TASK_LIST.json`, answers `201` then `200`, both naming the same id; `POST` with
  `restrictions.network: "open"` → `422`, nothing enqueued; `GET /tasks/<pod>/<id>` carries every
  field as sent; audit has one `task.enqueue`. Oracle: the queue file and the status codes.
- **RED test:** `tests/integration/test_serve_tasks_endpoint.py::test_same_idempotency_key_returns_the_existing_task`
  fails today with `201` twice and two tasks.
- **Spec:** `operator-api.spec.md` (status of the route → Implemented), `pod-dispatch.spec.md`
  6.46.0 (task record fields), `cli-json-shapes.spec.md` 1.33.0, `cli-interface.spec.md` 2.8.0
  (`task add` flags; goldens for `task add --help` regenerated and explained).

### P43-2 — the task worktree starts from `baseRef`

- **Status:** DONE 2026-10-14 (`3456acc1`) · **Size:** S · **Model:** Sonnet
- **Trigger:** `provision_task_worktree` always branches from the codebase's HEAD
  (`core/pod_provisioning.py`), so a rework cannot continue on the previous attempt's branch.
- **Goal:** `git_worktree_add(repo, path, branch, start_point="")` passes the start point;
  `provision_task_worktree(..., base_ref="")` records `baseRef` (as given) and `baseCommit`
  (resolved); `_ensure_task_worktree` passes `task["baseRef"]`; an unresolvable ref fails the
  task before any hop with `failureKind: "base_ref"` and a trace `dispatch_refused` payload
  naming the ref.
- **Non-goals:** fetching a remote ref; deleting old branches.
- **Files/functions:** `edges/adapters/system.py::git_worktree_add`,
  `core/pod_provisioning.py::provision_task_worktree`, `core/dispatch.py::_ensure_task_worktree`
  and the claim-time failure in `dispatch_pod`'s loop (one new helper, `_refuse_claimed_task`).
  Forbidden: `enqueue_task`, `_compose_hop`.
- **Acceptance:** a repo with branch `prev` one commit ahead of `main`; a task with
  `baseRef: "prev"` claimed → the worktree's HEAD is `prev`'s commit and `worktree.baseCommit`
  equals it; `baseRef: "nope"` → task `failed`, `failureKind == "base_ref"`, no hop record, no
  worktree directory left behind.
- **RED test:** `tests/unit/core/test_pod_provisioning.py::test_task_worktree_starts_from_base_ref`.
- **Spec:** `pod-dispatch.spec.md` 6.47.0 ("Task worktrees").

### P43-3 — pipeline and gate per task

- **Status:** DONE 2026-10-14 (`131e36f1`) · **Size:** M · **Model:** Sonnet
- **Trigger:** `dispatch_pod` resolves `effective_spec` once before the claim loop; a bug and a
  feature in the same pod cannot run different methodologies; the task's acceptance command has
  nowhere to go.
- **Goal:** `_task_pipeline(project, task, default_spec) -> (spec, source)`: `task["pipeline"]`
  resolves a pod-local `pipelines/<name>.yaml` (pod config dir, Phase 27) then a shipped
  methodology recipe's `pipeline.yaml` (`pod_apply.resolve_recipe`), else the default; an unknown
  name fails the task before any hop (`failureKind: "pipeline"`). `task["gate"]` becomes an
  `ExternalGate` appended after the last implementer step's own gate (a second gate on the same
  step, routed by the same `on:` labels), never replacing one. The pipeline source and the
  gate are recorded on the task (`pipelineSource`, `gateApplied`).
- **Non-goals:** per-step model overrides (Phase 30 `model:` already exists); persisting
  anything to the pod.
- **Files/functions:** `core/dispatch.py::dispatch_pod` (loop body: resolve per claimed task),
  `dispatch_task` (takes the resolved spec), new `_task_pipeline`, `_task_gate`;
  `core/pipeline.py` only if a step needs a `gates: [...]` list (prefer wrapping in dispatch).
  Forbidden: `enqueue_task`, `_ensure_task_worktree`, `_compose_hop`'s registry narrowing.
- **Acceptance:** a pod with a one-step pipeline and a pod-local `pipelines/two.yaml`; a task
  with `pipeline: "two"` runs two hops (stub server), `pipelineSource == "pod:two"`; a task with
  `pipeline: "tdd"` resolves the shipped recipe; `pipeline: "nope"` → `failed`,
  `failureKind == "pipeline"`, zero hops; a task with `gate: {"command": "false"}` on a pipeline
  whose implementer gate is `verifyCmd` → the implementer hop passes verify, then the task gate
  fails and routes as `fail` (trace `gate_result` or the existing gate event names the task gate).
- **RED test:** `tests/unit/core/test_dispatch.py::test_task_pipeline_name_selects_a_pod_local_pipeline`.
- **Spec:** `pod-dispatch.spec.md` 6.48.0 ("Pipeline per task", "Gate per task"),
  `pod-blueprints.spec.md` 1.28.0 (pod-local `pipelines/` directory, exported by `pod export`).

### P43-4 — restrictions and `maxTokens` reach the live hop

- **Status:** DONE 2026-10-14 (`887ab82c`) · **Size:** M · **Model:** Sonnet
- **Trigger:** security condition in ADR 0027 point 3; today nothing on a task can narrow a hop.
- **Goal:** at `_compose_hop`: `deniedTools` is unioned into the role narrowing
  (`registry_for_role` denials + pod `deniedTools` + task); `network: "none"` is the hop's jail
  network whatever the pod records (the `min` lives in one function,
  `_hop_network(project, task)`); `policies` load for the task's session after the pod's, as
  `on: tool` policies whose rules are all `block` (validated in P43-1, re-checked here, refused
  before the hop otherwise); refusals carry `policy_id == "task-restriction"` in the audit entry.
  `maxTokens`: each hop's `token_budget` is `maxTokens - sum(hop usage so far)`; a hop that
  would start at `<= 0` fails the task with `failureKind: "budget"`.
- **Non-goals:** widening anything; per-task `allowCommands`; dollar budgets.
- **Files/functions:** `core/dispatch.py::_compose_hop` (the registry/narrowing and jail-spec
  lines only; locate with `rg -n "denied_tools|registry_for_role|network" src/docket/core/dispatch.py`),
  new `_hop_network`, `_task_token_budget`; `core/policy.py` only to accept extra documents
  for a session (`load_policies(project, extra=...)`); the driver call that carries
  `token_budget` (`core/runtime_driver.py` key, read `cli/_exec.py::_execute_turn` for how
  `--max-tokens` is threaded today, before P43-12 deletes it). Forbidden: `enqueue_task`,
  `dispatch_pod`'s loop, `_task_pipeline`.
- **Acceptance:** the escape-style test of `operator-api.spec.md` "Validation": a pod whose
  implementer may `write`, a task with `deniedTools: ["write"]`, the stub server answers one
  `write` tool call → the call is refused, audit `tool.refused ... policy_id='task-restriction'`,
  the hop continues; a task with `maxTokens: 10` → `failed`, `failureKind == "budget"`, exactly
  one `llm_call` at most. Isolation off is recorded (`record_isolation_off`) so the network
  assertion is on the computed jail spec, not a live jail.
- **RED test:** `tests/integration/test_task_restrictions.py::test_a_task_denied_tool_is_refused_in_a_hop`.
- **Spec:** `security-gates.spec.md` 0.56.0 ("Task restrictions"), `pod-dispatch.spec.md`
  6.49.0 (`maxTokens`), `agent-loop.spec.md` only if `token_budget` semantics change (they
  should not).

### P43-5 — `hop_started` / `hop_finished`, model and provider on the hop

- **Status:** DONE 2026-10-14 (`bf68cefd + 9309097c`) · **Size:** S · **Model:** Haiku
- **Trigger:** measurement 3 in ADR 0027: a full run's trace has no hop-level event; the hop
  record has `usage` but no `model`/`provider`.
- **Goal:** `EVENT_TYPES` gains `hop_started`, `hop_finished` with the payloads of
  `operator-api.spec.md` "Trace events"; `_compose_hop` writes `hop_started` beside the existing
  `tool_call` marker; `_persist_hop_and_trace` writes `hop_finished` after the closing record;
  `HopResult` and `_hop_record`/`_hop_from_record` carry `model` and `provider` (from the
  `TurnResult`'s served model, the provider from `models_policy`/the provider catalog by prefix);
  `_finalize_task` writes `task["usage"] = {input, output, byModel}` summed over hops.
- **Non-goals:** changing `tool_call`/`tool_result`; telemetry spans; cost.
- **Files/functions:** `core/trace.py::EVENT_TYPES`; `core/dispatch.py::HopResult`,
  `_hop_record`, `_hop_from_record`, `_compose_hop` (two `_trace_locked` calls, nothing else),
  `_persist_hop_and_trace` (one call), `_finalize_task`. Forbidden: everything else in
  `dispatch.py`.
- **Acceptance:** a two-hop dispatch against the stub server → the task session's trace has
  exactly two `hop_started` and two `hop_finished`, payload keys equal to the spec example's;
  each persisted hop has `model` and `provider`; `task["usage"]["byModel"]` sums the hops;
  `_hop_from_record(_hop_record(h))` round-trips the new fields; an old record without them
  loads with `""`.
- **RED test:** `tests/unit/core/test_trace.py::test_hop_events_are_known_types` and
  `tests/unit/core/test_dispatch.py::test_hop_record_round_trips_model_and_provider`.
- **Spec:** `trace-store.spec.md` 1.8.0, `pod-dispatch.spec.md` 6.50.0 ("Hop evidence"),
  `evidence` contract untouched (the hop `model` is additive; say so in the spec).

### Wave 110 — the pod

### P43-6 — a pod is readable over HTTP; `POST /pods` ensures

- **Status:** DONE 2026-10-17 (`1a5ccfe4`) · **Size:** M · **Model:** Sonnet
- **Trigger:** the report exists only in `cli/_pod_show.py::pod_report`; `POST /pods` answers
  `409` to a consumer that only wants the pod to exist.
- **Goal:** move `pod_report`, `member_report` and their helpers to `core/pod_report.py` (the
  CLI renders, `serve.py` serialises; no behaviour change, `pod show --json` byte-identical);
  `GET /pods` lists `dispatchable_pods()` with name, codebase, member count, effective profile
  and queue counts; `GET /pods/<p>` returns the report plus `profile` (`profile.as_json(
  project_violations(p))`, `{"name": "attended", "violations": []}` when attended),
  `pipelineSource` (`effective_pipeline_source`) and `repoConfigDir` (P43-7's function; until it
  merges, `<codebase>/.docket`); `POST /pods` with `ensure: true` answers `200`
  `created: false` on an existing pod, touching nothing.
- **Non-goals:** writing settings over HTTP (`pod set` stays CLI); members' secrets or tokens in
  the report (none today; keep it so).
- **Files/functions:** new `core/pod_report.py` (moved code, a maint script does the move:
  `scripts/maint/move_pod_report.py`), `cli/_pod_show.py` (imports), `serve.py::do_GET` (`/pods`
  branches), `_handle_post_pods`, `core/profile.py` unchanged. Forbidden: `core/pod_apply.py`,
  `cli/_agents.py`.
- **Acceptance:** seeded pod; `GET /pods/<p>` key set ⊇ `pod show --json`'s and carries
  `profile`, `pipelineSource`, `repoConfigDir`; `GET /pods/nope` → `404`; `POST /pods` twice
  with `ensure` → `201` then `200`, fleet unchanged between (compare `fleet.json` bytes);
  `tests/golden` `pod show --json` case unchanged; the guard
  `tests/guards` layout test still passes (`cli/` → `core/` import direction).
- **RED test:** `tests/integration/test_serve_pods_endpoint.py::test_ensure_returns_the_existing_pod_unchanged`.
- **Spec:** `operator-api.spec.md` route rows → Implemented; `cli-json-shapes.spec.md` 1.34.0
  (note the move, same shape); `serve-read-api.spec.md` 3.7.0 (`POST /pods` `ensure`).

### P43-7 — `.docket/teams/<pod>/`: several teams in one repository

- **Status:** DONE 2026-10-17 (`d1bdf91f`) · **Size:** M · **Model:** Sonnet
- **Trigger:** three sites hard-code `<codebase>/.docket`; a repository with five pods has no
  place to keep five teams.
- **Goal:** `core/pod_apply.py::repo_config_dir(codebase, project) -> Path`: returns
  `<codebase>/.docket/teams/<project>` when that directory exists, else `<codebase>/.docket`;
  used by `cli/_agents.py::_resolve_repo_apply_source` (`docket init --name <pod>` in a repo with
  `teams/<pod>/`), `cli/_pod_config.py::_repo_docket_dir` (`pod update`/`export`/`validate`
  defaults), `cli/_run.py` (change pickup), and `pod_apply.repo_changes`. `pod export` into a
  repo that already has `.docket/teams/` writes `teams/<pod>/`. `init` in a repo whose
  `.docket/` has only `teams/` and no `pod.yaml` applies nothing and says which teams exist
  (`--name` picks one; without it, exit 2 naming them).
- **Non-goals:** changing the recipe format; a `teams/` index file; resolving the pod from cwd
  by team (a tie still needs `--pod`, ADR 0027 question 2).
- **Files/functions:** as named; a maint-free change (no file moves). Forbidden: `serve.py`,
  `core/pod_report.py`.
- **Acceptance:** a repo with `.docket/teams/a/pod.yaml` and `.docket/teams/b/pod.yaml`;
  `docket init --name a` applies `a` and records `configSource` ending in `teams/a`;
  `docket init` without `--name` exits 2 listing `a, b`; `docket pod export --pod a` rewrites
  `teams/a/` and leaves `teams/b/` byte-identical; `docket run --pod a` picks up a change under
  `teams/a/` only.
- **RED test:** `tests/unit/core/test_pod_apply.py::test_repo_config_dir_prefers_the_pods_team_dir`.
- **Spec:** `pod-blueprints.spec.md` 1.29.0 ("Configuration of record" gains `teams/`),
  `cli-interface.spec.md` 2.9.0 (`init` exit 2 message); `docs/CONFIGURATION.md` sentence.

### P43-8 — `POST /pods/<p>/apply`

- **Status:** DONE 2026-10-17 (`a1b4053c`) · **Size:** M · **Model:** Sonnet
- **Trigger:** applying a reviewed directory needs a terminal; a plan of record that merged a
  PR on `.docket/teams/<p>/` cannot apply it.
- **Goal:** the route of `operator-api.spec.md`: `directory` (absolute, or P43-7's default),
  `dryRun`, `accept`; the review rule of ADR 0024 §6 exactly as off a terminal (a directory
  that runs things without the matching code → `409` with `reviewCode` and `runs`, nothing
  created); on success the `ApplyResult` JSON of `pod update --json`. The review-code
  computation and the "off a terminal" branch move from `cli/_agents.py` into `core/pod_apply.py`
  if they are not there already (locate with `rg -n "accept" src/docket/cli/_agents.py
  src/docket/core/pod_apply.py`); the CLI calls the same function.
- **Non-goals:** uploading a directory over HTTP (the directory is on this machine);
  applying on dispatch (ADR 0012: nothing applies without an operator command; this route is
  one).
- **Files/functions:** `serve.py::do_POST` (`/pods/<p>/apply` branch, new
  `_handle_post_pod_apply`), `core/pod_apply.py` (`review_code`, `apply_reviewed` or the
  existing names), `cli/_agents.py`, `cli/_pod_config.py::_apply_directory` (call sites only).
  Forbidden: `_handle_post_pods`, `core/pod_report.py`.
- **Acceptance:** a pod and a directory adding one role → `200`, the member exists,
  `configSource` recorded, audit `pod.apply ... channel=http`; `dryRun` → `200` and nothing
  written; a directory with `allowCommands` without `accept` → `409` body with `reviewCode`,
  nothing written; with the code → `200`; a wrong code → `409`.
- **RED test:** `tests/integration/test_serve_pods_config.py::test_apply_over_http_needs_the_review_code_for_run_items`.
- **Spec:** `operator-api.spec.md` row → Implemented; `pod-blueprints.spec.md` 1.30.0 (HTTP is
  off a terminal); `cli-json-shapes.spec.md` only if `ApplyResult` gains `dryRun`.

### P43-9 — `GET /pods/<p>/corrections`

- **Status:** DONE 2026-10-17 (`d80b72a3`, `a81ee3b1`) · **Size:** S · **Model:** Haiku
- **Trigger:** `core/corrections.py::read` exists and nothing exposes it (ADR 0027 point 6).
- **Goal:** `GET /pods/<p>/corrections?since=<iso>` → `{"corrections": [...], "next": <last ts
  or the given since>}`, records with `ts > since` in append order, `[]` for a pod with no
  ledger, `404` for no pod, `400` for a bad `since`.
- **Non-goals:** aggregation, pagination beyond `since`, writing.
- **Files/functions:** `serve.py::do_GET` (one branch), `core/corrections.py::read(project,
  since="")` (filter in core, so the CLI can reuse it). Forbidden: everything else.
- **Acceptance:** three records written with `corrections.record`; `since` equal to the second's
  `ts` returns the third only and `next` equals its `ts`; no `since` returns all three.
- **RED test:** `tests/integration/test_serve_pods_config.py::test_corrections_since_filters_by_timestamp`.
- **Spec:** `operator-api.spec.md` row → Implemented; `operator-loop.spec.md` or the spec that
  owns corrections (locate with `rg -ln corrections specs/`) gets one line.

### Wave 111 — the daemon and the command

### P43-10 — cancel, retry and diff over HTTP

- **Status:** TODO · **Size:** M · **Model:** Sonnet
- **Trigger:** the live-run cancel lives in `cli/_task.py::_cancel_live_runs`; no HTTP route
  cancels, retries or diffs.
- **Goal:** `core/dispatch.py::cancel_task(project, task_id, *, channel, actor, reason="")`
  owns both halves (live runs through `runs.cancel_run`, parked through `cancel_parked_task`);
  `cli/_task.py` calls it; `POST /tasks/<pod>/<id>/cancel` and `.../retry` (`retry_task`) answer
  as the spec says; `GET .../diff` builds `{branch, baseCommit, head, patch, untracked,
  worktreePresent}` through two new `edges/adapters/system.py` helpers (`git_diff_range(repo,
  base, ref)`, `git_untracked(worktree)`), `409` for an in-place task. `docket task diff <id>`
  prints the patch (CLI symmetry).
- **Non-goals:** applying or pushing anything; diffs of tasks whose branch was deleted
  (`404` with a sentence).
- **Files/functions:** `core/dispatch.py::cancel_task` (new), `retry_task` (unchanged),
  `task_diff` (new); `cli/_task.py` (cancel call site, new `diff` verb); `serve.py::do_POST`
  (`/tasks/<pod>/<id>/cancel|retry`), `do_GET` (`/diff`); `edges/adapters/system.py` (two
  helpers). Forbidden: `_compose_hop`, `enqueue_task`, `serve.py::_handle_post_pods`.
- **Acceptance:** a task whose implementer committed one file on its branch → `diff` carries the
  patch with that file, `untracked` lists a file written but not added, `head` is the branch
  tip; after `provision_pod`'s worktree removal `worktreePresent` is `false` and `patch` is the
  same; `cancel` on a `running` task (stub server, slow response) → `cancelled`, audit
  `task.cancel ... channel=http`; `retry` on `done` → `409`.
- **RED test:** `tests/integration/test_serve_task_lifecycle.py::test_diff_reports_the_task_branch_against_its_base`.
- **Spec:** `operator-api.spec.md` rows → Implemented; `pod-dispatch.spec.md` 6.51.0
  (`cancel_task`); `cli-interface.spec.md` 2.10.0 (`task diff`; goldens for `task --help`
  regenerated and explained).

### P43-11 — a daemon a supervisor can run

- **Status:** TODO · **Size:** M · **Model:** Sonnet
- **Trigger:** measurement 3 (ADR 0027): the first stop signal waited 91 s for a whole sweep;
  the sweep never passes `resume`; `--bind` is not a CLI flag; a posted task waits for the next
  refresh.
- **Goal:** `dispatch_pod(..., stop: Callable[[], bool] | None)` checks `stop()` between tasks
  (never mid-hop); the sweep passes the controller's `stop.is_set` and `resume=True`
  (`reclaim_stale_running` on every sweep, so a claim abandoned by the second signal resumes
  from its last persisted hop on the next sweep); `POST /tasks/<pod>` with dispatch on calls
  `_submit_pod_sweep(pod)` after the enqueue; `docket start --bind <addr>` reaches
  `run_serve(bind=)`; `/health` gains the `dispatch` block of the spec. Each change is its own
  commit.
- **Non-goals:** a socket file; systemd units; changing the abandon stage.
- **Files/functions:** `core/dispatch.py::dispatch_pod` (the loop condition only);
  `serve.py::_sweep_one_pod`, `_StopController` (expose `stopping`), `_handle_post_tasks` (one
  call), `render_health`; `cli/_service.py` (`--bind`). Forbidden: `_claim_next_task`,
  `reclaim_stale_running`'s body.
- **Acceptance:** a queue of three tasks on the stub server; stop set after the first claim →
  exactly one task reaches a terminal state, two stay `pending`, the sweep returns within one
  hop; a `running` task whose `claimPid` is dead → the next sweep flips it `failed/stale_claim`
  and then claims it again, continuing from hop 2 (hops 1 retained); `POST /tasks` with dispatch
  on → `_submit_pod_sweep` called once (monkeypatched); `start --bind 127.0.0.2 --port N` →
  `/health` on that address; `/health` carries `dispatch.on`, `inflight`, `stopping`, `workers`.
- **RED test:** `tests/unit/core/test_dispatch.py::test_dispatch_pod_stops_between_tasks_when_asked`
  and `tests/integration/test_serve_stop_signals.py::test_first_signal_finishes_only_the_running_task`.
- **Spec:** `pod-dispatch.spec.md` 6.52.0 ("Stop and resume under the daemon"),
  `serve-read-api.spec.md` 3.8.0 (`/health` dispatch block, `--bind`), `cli-interface.spec.md`
  2.11.0 (`start --bind`; golden for `start --help` regenerated and explained).

### P43-12 — one door: delete `exec` and harness mode, API version 5, beta.6

- **Status:** TODO · **Size:** M · **Model:** Sonnet (the deletion list is a script; the prose
  sweep is the judgment part). Maintainer's decision 2026-10-14: delete in beta.6, nothing kept
  for compatibility, no alias, hint, notice or migration anywhere.
- **Trigger:** ADR 0027 point 1 and ROADMAP D-57: with the task routes live, `docket exec` is a
  second door kept for the past.
- **Goal:** `scripts/maint/remove_harness_mode.py` deletes, with `git rm`: `cli/_exec.py`,
  `cli/_harness_answers.py`, `cli/_harness_recipe.py`, `cli/_setup_harness.py`,
  `core/harness.py`, `core/setup_home.py`, `core/harness_pipeline.py` (the in-place ephemeral
  pod exists only for `exec --recipe`), `scripts/harness_schema.py`,
  `docs/contracts/harness-v1*`, `tests/fixtures/harness-contract/`, `tests/unit/cli/test__exec.py`,
  `tests/unit/core/test_harness.py`, `tests/unit/core/test_setup_home.py` and
  `test_harness_pipeline.py` if present, `tests/integration/test_harness_*.py`,
  `tests/integration/test_sandboxed_exec.py` (after moving its stub OpenAI server and its jail
  fixtures into `tests/integration/conftest.py` -- P43-4 and P43-10 depend on that stub),
  `specs/api/harness-mode.spec.md`, `docs/DEVELOPMENT-HARNESS.md` (deleted; the HTTP walkthrough
  is `operator-api.spec.md`), scene `6-harness` of `scripts/maint/capture-doc-journey.sh` and
  its transcription in `scripts/render-doc-assets.py` and `docs/assets/README.md`; removes
  `exec` from `cli/__init__.py`'s registry and `setup harness` from `cli/_setup.py`; `exec`
  joins `scripts/maint/rewrite_cli_names.py`'s removed names and the pairs in
  `tests/guards/test_no_removed_cli_names.py` that name it as a destination are dropped;
  `cli/_exec.py` leaves `tests/guards/test_dispatch_never_rereads_the_repository.py::_UNREAD`;
  the `docket exec: run` entry leaves `scripts/maint/lint_cli_invocations.py`; the exit-code
  row in `scripts/gen_cli_docs.py` loses the `exec` clause. **Anything that only the harness
  used goes too, proven by `rg`** (`core/operator_contract.py::QuestionV11`, `DOCKET_SETUP_HOME`,
  the `refuse` approval default in `edges/adapters/docket_runtime.py`, any `harness`-named
  branch in `core/agent_loop.py`, `core/tools.py`, `core/dispatch.py`, `core/consult.py`,
  `core/escalation.py`, `core/evidence.py`, `core/memory.py`, `core/trace.py`); what a pod also
  uses stays (`approvalMode: refuse` is a pod setting in `core/pod.py` and stays). Then the
  prose: the files `rg -ln 'docket exec|harness contract|harness mode' docs/*.md README.md
  CONTRIBUTING.md specs/*/*.md` lists lose the claims (ADR files and `docs/cycles-ended/` are
  history and are not edited; the integrator adds the superseded line to ADR 0001/0026);
  `docs/commands.md` regenerated; `tests/agent` prose tests rebuilt from the README; ten CLI
  commands (`docket --help` golden regenerated and explained). Finally `SERVE_API_VERSION =
  "5"`, `serve-read-api.spec.md` `API version` line → 5 (3.9.0, naming `operator-api.spec.md`
  as the owner of the write and lifecycle routes), `operator-api.spec.md` status → Implemented,
  `VERSION`/`pyproject.toml` `0.2.0-beta.6`, `CHANGELOG.md` (integrator).
- **Non-goals:** keeping an alias, a notice or an exit-2 hint for `exec`; touching
  `docket run`/`task add`.
- **Files/functions:** as listed; the registry `cli/__init__.py`; `serve.py::SERVE_API_VERSION`.
  Forbidden: any `core/dispatch.py` function.
- **Acceptance:** `docket exec` → exit 2 as an unknown command, no hint, no mention in any
  error text; `docket --help` lists ten commands; `uv run pytest` default lanes green with the
  stub server reachable from `tests/integration/conftest.py`; `scripts/metrics.py --check`
  re-measured by the integrator; `GET /status.json` → `apiVersion == "5"`;
  `rg -n 'docket exec|harness contract|harness mode|HARNESS_|setup_home|harness_pipeline|DOCKET_SETUP_HOME'
  src scripts tests docs/*.md specs README.md CONTRIBUTING.md` prints nothing (the adoption
  benchmark's own `benchmarks/harness.py` and CI's "test harness" wording are a different word
  and stay); the escape matrix still runs (it used `exec` for some scenes: port them to
  `docket run` on a seeded pod or to the task route); `capture-doc-journey.sh` runs scenes
  1 to 5 and no sixth.
- **RED test:** `tests/unit/cli/test_registry.py::test_exec_is_an_unknown_command` (exit 2, no
  hint) and `tests/integration/test_serve_status.py::test_api_version_is_5`.
- **Spec:** as in Goal; ADR 0001/0026 get a one-line "superseded on the harness by ADR 0027"
  header note (integrator).

### Follow-ups found while planning (not cards; triage when a trigger fires)

- **The Lead plans with the codebase path, the Implementer is rooted in the task worktree**
  (measurement 3: `tool.refused` on `read` of the codebase path, audit seq 6-7 of the throwaway
  home). The Lead's hop should name the task worktree, or the handoff should rewrite the path.
  Reproduce with any local-model dispatch in a worktree pod before scheduling.
- **Parallel tasks in a pod** -- trigger in ADR 0027 point 10. The task record and the claim
  are already per task; a card would add a `maxParallelTasks` pod setting and a bounded pool in
  `dispatch_pod`.
- **Warm workspace** -- trigger in ADR 0027 point 10 (measured 6.5 s + 15.5 s, 829 MB).
- **`pod apply`/`pod export` do not carry `config/pipelines/`** (P43-3): a pod-local pipeline is
  read at claim but cannot be shipped in `.docket/`. Natural home: P43-7 or P43-8.
- **A task's `network: none` cuts the agent turn only** (P43-4): `verifyCmd` and `run:` steps keep
  the pod's posture; the spec says so. A parallel group's merge in `_run_group_node` drops
  `_UnitOutcome.failure_kind`, so a budget stop inside a group loses `budget`.
- **Two enqueue entry points** (P43-1): `enqueue_task` returns the task, `enqueue_task_once`
  returns `(task, created)`; fold into one when the remaining callers (`telegram.py`, `_mcp.py`)
  are next touched. A raced duplicate `idempotencyKey` under `require_approval` can leave an
  orphan approval token.
- **`trace-store.spec.md` requirement 6 says "exactly"** but the code's `EVENT_TYPES` has members
  the list never named (found by P43-2); re-derive the list from the frozenset.
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams, and the `docket pod update .docket` hint in `cli/_agents.py::_changed_since_review` is
  not team-aware.
- **Queue counts twice** (P43-6): `core/pod_report.py::task_counts` and the inline Counter in
  `cli/_status.py` (~lines 138-164) compute the same mapping; point `status` at `task_counts`.
  `pod_report._caller_default` reads `sys.stdin.isatty()`, so under `docket start` the report's
  approval default depends on the daemon's stdin.
- **`POST /pods/<p>/apply` edges** (P43-8): a pod with no recorded codebase reviews against
  `directory.parent`; an all-skip apply writes no `pod.apply` audit entry (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
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
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
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


