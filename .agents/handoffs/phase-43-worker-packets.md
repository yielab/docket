# Phase 43 worker packets — the team runtime behind an external plan of record (ADR 0027)

Coordinator: the session that planned Phase 43 on 2026-10-14. **Base commit: the commit that
opened Phase 43 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/phase-43-worker-packets.md`).
One card, one worker, one isolated worktree each. The card
(`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P43-<n>`) is the contract; this
file is the map. **Read §0 and your own packet only.** Symbols were located on `develop` at
`e5c8c784` and drift; re-locate every one with `rg -n` before editing.

Three waves. Waves 109 and 110 are independent and may run at once; Wave 111 starts after both
merge. Merge order inside a wave is the card order below.

| Wave | Card | Worker | Owns in `core/dispatch.py` | Owning spec bump |
| --- | --- | --- | --- | --- |
| 109 | P43-1 | Sonnet | `enqueue_task`, `_normalize_task`, new `validate_task_options` | pod-dispatch 6.46.0, cli-json-shapes 1.33.0, cli-interface 2.8.0 |
| 109 | P43-2 | Sonnet | `_ensure_task_worktree`, new `_refuse_claimed_task` | pod-dispatch 6.47.0 |
| 109 | P43-3 | Sonnet | `dispatch_pod` loop body, `dispatch_task` signature, new `_task_pipeline`, `_task_gate` | pod-dispatch 6.48.0, pod-blueprints 1.28.0 |
| 109 | P43-4 | Sonnet | `_compose_hop` narrowing/jail lines, new `_hop_network`, `_task_token_budget` | security-gates 0.56.0, pod-dispatch 6.49.0 |
| 109 | P43-5 | Haiku | `HopResult`, `_hop_record`, `_hop_from_record`, two trace calls in `_compose_hop`, one in `_persist_hop_and_trace`, `_finalize_task` | trace-store 1.8.0, pod-dispatch 6.50.0 |
| 110 | P43-6 | Sonnet | none (`dispatchable_pods` read only) | cli-json-shapes 1.34.0, serve-read-api 3.7.0 |
| 110 | P43-7 | Sonnet | none | pod-blueprints 1.29.0, cli-interface 2.9.0 |
| 110 | P43-8 | Sonnet | none | pod-blueprints 1.30.0 |
| 110 | P43-9 | Haiku | none | operator-loop (one line) |
| 111 | P43-10 | Sonnet | new `cancel_task`, `task_diff`; `retry_task` read only | pod-dispatch 6.51.0, cli-interface 2.10.0 |
| 111 | P43-11 | Sonnet | `dispatch_pod` loop condition (`stop`) | pod-dispatch 6.52.0, serve-read-api 3.8.0, cli-interface 2.11.0 |
| 111 | P43-12 | Sonnet | none | serve-read-api 3.9.0, operator-api → Implemented |

The integrator orders the `pod-dispatch.spec.md` changelog (five cards bump it in Wave 109: each
worker writes its entry under its own version; the integrator renumbers on merge) and owns
`operator-api.spec.md`'s route-status table, `CHANGELOG.md`, `TODO.md`, `ROADMAP.md`, `README.md`.

## 0. Rules for every worker

- **Isolation.** You are in your own worktree on branch `p43-<n>-<slug>`, based on the claim
  commit (verify with `git merge-base HEAD develop`; if it is older than that commit, stop and
  report). Never touch `~/.docket`: every manual CLI run sets `export W=$(mktemp -d); export
  DOCKET_HOME=$W/.docket` (two statements; **never override `HOME`**). pytest isolates
  `DOCKET_HOME` through the autouse fixture in `tests/conftest.py`. **Never call a real model
  endpoint and never probe a real vendor host.** A hop in a test runs against the stub
  OpenAI-compatible server on loopback: until P43-12 moves it, it lives in
  `tests/integration/test_harness_cli.py` (locate with `rg -n "class .*Server|def .*stub"
  tests/integration/test_harness_cli.py`); import it from there, do not copy it. The keyless
  provider document is `tests/conftest.py::register_local_provider`.
- **Commands.** `env -u VIRTUAL_ENV uv run ...` for everything (a worktree inherits a stale
  `VIRTUAL_ENV`). `grep` is ripgrep here; use `command grep` for literal greps over the diff.
- **Never `git stash`.** Set work aside with a WIP commit if you must.
- **Spec first, test first.** Patch the owning spec (version, last-updated date, changelog
  entry, the requirement text), write the RED test, run it and record the failure reason, then
  implement the smallest change. One-line test docstrings; no card ids or dates in test files.
- **Layers.** `cli/ -> core/ -> edges/`, inward only. `core/` never prints and never imports
  `ui.py`. `serve.py` imports `core/`, never `cli/`. Every shell-out goes through
  `edges/adapters/system.py`. Docket-owned JSON goes through `edges/store.py`.
- **Ownership.** Edit only the files your card names plus the owning spec and its unit tests.
  Inside `core/dispatch.py` edit only the functions the table above gives you; a change you
  need in another function is a locator in "Later follow-ups", not an edit. `CHANGELOG.md`,
  `specs/README.md`, `TODO.md`, `ROADMAP.md`, `README.md`, `CONTRIBUTING.md`, `docs/adr/` are the
  integrator's; put the CHANGELOG line you would have written in your return.
- **Comments.** Docstrings at most three lines; no narrative comments. Run
  `env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <touched files>` and
  `env -u VIRTUAL_ENV uv run python scripts/maint/measure_function_spans.py --check`.
- **Goldens.** `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` must pass. Only P43-1,
  P43-10, P43-11 and P43-12 recapture a golden (named on the card) and explain every changed
  line in the return.
- **Gates before the return:** `env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv
  run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src`; `env -u VIRTUAL_ENV uv run
  pytest -q -p no:cacheprovider`; the goldens; `bash scripts/validate-specs.sh`; `env -u
  VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check` (a card that changes help text
  regenerates `docs/commands.md` with the same script, no `--check`); `env -u VIRTUAL_ENV uv run
  python scripts/maint/lint_cli_invocations.py --self-check`. `scripts/metrics.py --check` is the
  integrator's (it fails on a branch that adds tests). A card that touches the jail or
  `_compose_hop` (P43-4) also runs `scripts/maint/pytest-without-sandbox.sh -q`.
- **Commit** on your branch with `git -c core.hooksPath=/dev/null commit`, subject `Type:
  description` (Fix:/Add:/Docs:/Remove:), ASCII, **no AI mention and no Co-Authored-By
  trailer**, a body that names the spec version and the RED reason. Before committing: `git diff
  --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-'` must print nothing. Do not merge,
  do not push, do not touch `develop`.
- **Return** the delta shape from `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`
  "Worker return" (card, commit, outcome, user-visible behaviour, changed paths, spec version,
  oracles, focused tests, full gates, missing, follow-ups, CHANGELOG line). No logs.

## Wave 109 — the task

### P43-1 — an addressable task (Sonnet)

- Live path: `serve.py::_handle_post_tasks` reads the body and calls
  `core/dispatch.py::enqueue_task(project, description, priority, channel=, trusted=, brief=)`;
  the task dict is built in `enqueue_task` (keys `id`, `description`, `priority`, `status`,
  `created`, `startedAt`, `completedAt`, `source`, `channel`, `hops`, `reason`, `costUsd`,
  `claimId`, `claimedAt`, optional `brief`); `_normalize_task` fills defaults on read.
- Add a Pydantic `TaskOptions` (`externalRef`, `idempotencyKey`, `baseRef`, `pipeline`, `gate`,
  `maxTokens`, `restrictions`) with the rules of `operator-api.spec.md` "Arguments"; validate in
  `enqueue_task` (raise `DispatchError`, which the route maps to `400`/`422`: a widening
  restriction is `422`, a wrong shape `400`; add one exception subclass so the route can tell).
  Store the fields on the task verbatim (`None`s omitted). Idempotency: inside the same
  `read_modify_write` that appends, look for `idempotencyKey` first and return the existing
  record with a flag the route turns into `200`/`created: false` (return a `(task, created)`
  tuple or a `task["_created"]` the route strips; prefer the tuple and update the three
  callers: `cli/_task.py`, `serve.py`, `core/telegram.py` -- locate with `rg -n "enqueue_task\("`).
- `GET /tasks/<pod>` filter: the `do_GET` branch `elif path.startswith("/tasks/")` (after the
  `/evidence` branch); parse the query with `urllib.parse.parse_qs`. `GET /tasks/<pod>/<id>`:
  a new branch before the list branch, matching `/tasks/<pod>/<id>` with no further segment.
- CLI: `cli/_task.py` `task add` gains `--external-ref`, `--idempotency-key`, `--base-ref`,
  `--pipeline`, `--gate` (the command string; `timeoutS` not exposed), `--max-tokens`; the
  second `add` with the same key prints the existing id with `ok already queued`.
- Tests: extend `tests/integration/test_serve_tasks_endpoint.py` (fixtures `_seed_pod`,
  `live_server` are there); `tests/unit/core/test_dispatch.py` for `TaskOptions`;
  `tests/unit/cli/test__task.py` for the flags. Golden: `task add --help` (locate with `ls
  tests/golden/cases/*/ | rg task`).
- Forbidden: `_claim_next_task`, `dispatch_task`, `_compose_hop`, `pod_provisioning.py`.

### P43-2 — `baseRef` at claim (Sonnet)

- Live path: `_claim_next_task` -> `_ensure_task_worktree(project, claimed)` ->
  `core/pod_provisioning.py::provision_task_worktree(member_id, project, task_id, codebase)` ->
  `edges/adapters/system.py::git_worktree_add(repo_dir, worktree_path, branch)` (`git -C repo
  worktree add -b branch path`); `baseCommit` is `git_head_sha(wt_path)` afterwards.
- `git_worktree_add(..., start_point: str = "")` appends `start_point` to the argv when set.
  `provision_task_worktree(..., base_ref: str = "")` passes it and records `baseRef` in the
  returned record. `_ensure_task_worktree` reads `claimed.get("baseRef")`. A failed `worktree
  add` today records `fallbackReason` and runs in place: **with a `baseRef` set that fallback is
  wrong** (the caller asked for a base); return the reason to the loop, where
  `_refuse_claimed_task(project, task, failure_kind, reason)` flips the task to `failed` with
  `failureKind`, writes `dispatch_refused`, and the loop `continue`s. P43-3 reuses that helper
  for `"pipeline"`; write it generic.
- Tests: `tests/unit/core/test_pod_provisioning.py` (a real temp git repo; `git` is available
  in CI), `tests/unit/edges/test_system.py` for the argv (monkeypatch `subprocess.run`),
  `tests/unit/core/test_dispatch.py` for the refusal (no hop, `failureKind`).
- Forbidden: `enqueue_task`, `_compose_hop`, `dispatch_task`.

### P43-3 — pipeline and gate per task (Sonnet)

- Live path: `dispatch_pod` computes `effective_spec = effective_pipeline(project, spec)` and
  `resolve_variables` once, then loops `_claim_next_task` -> `dispatch_task(project, task,
  runner=..., spec=effective_spec, ...)`. Read `dispatch_task`'s signature first
  (`sed -n 3033,3080p` at the base commit) and `_run_pipeline` for how the spec's steps become
  planned units (`core/orchestrator.py`); the external gate type is
  `core/pipeline.py::ExternalGate` and its runner `core/dispatch.py` (`rg -n "ExternalGate"`).
- Pod-local pipelines: the pod config dir is `core/pod.py::pod_config_dir(project)` (Phase 27);
  Phase 28 pipelines load through `core/config_docs.py::load_document` /
  `core/pipeline.py` (`rg -n "def load_pipeline|parse_pipeline" src/docket/core`). Shipped
  methodology recipes: `core/pod_apply.py::resolve_recipe(name)` then `_recipe_pipeline_file`.
  Resolution order and failure in `_task_pipeline`; resolve the pipeline's variables per task
  as `dispatch_pod` does today for the default.
- Task gate: build an `ExternalGate` from `task["gate"]` and attach it after the last
  implementer unit's own gate. If a step can hold one gate only, wrap: run the step's gate,
  then the task's, and route on the first non-pass label; keep the trace shape the existing
  gate emits and add `"source": "task"` to its payload. Record `pipelineSource` and
  `gateApplied` on the task at claim (`read_modify_write` on the queue, as
  `_ensure_task_worktree` does).
- Tests: `tests/unit/core/test_dispatch.py` (a scripted runner; see existing tests that pass
  `runner=`), `tests/integration/test_pipeline_per_task.py` for the two-hop run on the stub
  server, `tests/unit/core/test_pod_apply.py` only if `resolve_recipe` changes (it should not).
- Forbidden: `enqueue_task`, `_ensure_task_worktree`, `_compose_hop`, `core/pod_apply.py`.

### P43-4 — restrictions and `maxTokens` on the live hop (Sonnet)

- Live path: `_compose_hop(ctx, role, member_id, ...)` narrows the registry per role
  (`core/archetypes.py::registry_for_role`, pod `deniedTools` from `PodSettings`), builds the
  jail spec for the hop (`rg -n "jail|network|sandbox" src/docket/core/dispatch.py` around
  `_compose_hop`; the network comes from `core/pod.py::effective_network(project)`), and calls
  the driver with the env and limits. The driver's limits come as a dict `run_turn` receives
  (`core/runtime_driver.py` top: `DOCKET_APPROVAL_MODE` and the token-budget key are documented
  there; `cli/_exec.py::_execute_turn` shows `max_tokens` threaded into it -- read it before
  P43-12 deletes it).
- Union, never replace: `denied = role_denied | pod_denied | task_denied`. Network: a pure
  `_hop_network(pod_mode, task_mode) -> "none" | "open"` returning `"none"` if either is.
  Policies: `core/policy.py` loads global + pod policies for a project; add an `extra:
  list[PolicySpec]` parameter on the loader the hop uses, evaluated after the pod's, each rule
  re-checked `action == "block"`; the policy id of a task document is `task-restriction` (set it
  on load so audit carries it). `maxTokens`: `_task_token_budget(task) -> int | None` =
  `maxTokens - sum(h.usage.input + h.usage.output for persisted hops)`; `<= 0` refuses the hop
  through the same terminal shape a failed gate uses, `failureKind: "budget"`.
- Tests: `tests/integration/test_task_restrictions.py` on the stub server with a scripted
  `write` tool call (how the stub scripts tool calls: read `test_harness_cli.py`'s fixtures);
  `tests/unit/core/test_dispatch.py` for `_hop_network` and `_task_token_budget`;
  `tests/unit/core/test_policy.py` for `extra`. Run `scripts/maint/pytest-without-sandbox.sh -q`
  too.
- Forbidden: `enqueue_task`, `dispatch_pod`'s loop, `_task_pipeline`, `core/tools.py`.

### P43-5 — hop events and model/provider (Haiku)

- Exact sites: `core/trace.py::EVENT_TYPES` (a frozenset with one comment per entry; add
  `hop_started`, `hop_finished` in the dispatch group). `core/dispatch.py::_compose_hop`: the
  marker `_trace_locked(ctx.project, ctx.session_id, role, "tool_call", _json.dumps({"hop":
  role, "agent": member_id}))` -- write `hop_started` right after it with the spec payload
  (`cycle` is the rework cycle the context already tracks: `rg -n "rework|cycle" src/docket/core/dispatch.py`
  near `_compose_hop`; `attempt` is the retry attempt). `_persist_hop_and_trace`: after the
  `tool_result`/`error` record and the optional `cost_charged`, write `hop_finished`
  (`durationMs` from `hop.trace["firstTs"]`/`lastTs`, `verdict` from `hop.artifact.verdict`,
  `gate` from `hop.verify` if present else `None`). `HopResult` gains `model: str = ""`,
  `provider: str = ""`; fill them where the `TurnResult` is turned into a `HopResult`
  (`rg -n "HopResult\(" src/docket/core/dispatch.py`; the served model is on the result or the
  driver's response -- locate `served` with `rg -n "served" src/docket/core src/docket/edges/adapters/docket_runtime.py`),
  provider = the prefix before `/`. `_hop_record` / `_hop_from_record` carry both (default
  `""`). `_finalize_task`: compute `usage` as the spec shows.
- Tests: `tests/unit/core/test_trace.py`, `tests/unit/core/test_dispatch.py` (round trip and
  a scripted two-hop run asserting the four events), `tests/integration/test_evidence.py` or
  the evidence unit test only to prove the evidence document is unchanged.
- Forbidden: every other function of `dispatch.py`; `serve.py`; `core/telemetry.py`.

## Wave 110 — the pod

### P43-6 — readable pod, `ensure` (Sonnet)

- Move: `cli/_pod_show.py` holds `pod_report`, `member_report` and the `_*_report` helpers
  (pure readers over fleet/meta/settings) plus `render_pod`/`render_member` (Rich). Write
  `scripts/maint/move_pod_report.py` that moves every non-rendering symbol to
  `core/pod_report.py` and rewrites the imports in `cli/_pod_show.py` and `cli/_pod.py`
  (locate call sites with `rg -n "_pod_show\." src/docket`). The golden `pod show --json`
  case must stay byte-identical; `tests/guards` has an import-direction guard, keep it green.
- Routes: `do_GET` gains `/pods` and `/pods/<p>` branches (auth first, then
  `_reject_bad_project_id`); `/pods/<p>` body = `pod_report(p)` + `profile` (`core/profile.py::
  effective_profile`, `project_violations`, `as_json`) + `pipelineSource`
  (`dispatch.effective_pipeline_source`) + `repoConfigDir` (until P43-7 merges:
  `<codebase>/.docket`; the integrator switches it to `repo_config_dir` at the Wave 110 merge).
  `_handle_post_pods`: read `ensure`; on `PodAlreadyExistsError` with `ensure` answer `200`
  `{"ok": true, "created": false, "project": p}`; the success body gains `"created": true`.
- Tests: `tests/integration/test_serve_pods_endpoint.py` (fixtures exist), new
  `tests/unit/core/test_pod_report.py` (moved tests from `tests/unit/cli/test__pod_show.py`;
  move the readers' tests, keep the render tests in `cli`).
- Forbidden: `core/pod_apply.py`, `cli/_agents.py`, `core/dispatch.py`.

### P43-7 — `.docket/teams/<pod>/` (Sonnet)

- Sites: `cli/_agents.py::_resolve_repo_apply_source(loc_path, cli_recipe)` (`docket_dir =
  loc_path / ".docket"`), `cli/_pod_config.py::_repo_docket_dir(project)` and the `validate`
  default (`Path.cwd() / ".docket"`), `cli/_run.py` line ~34 (`Path(codebase) / ".docket"`),
  `core/pod_apply.py::repo_changes(project, repo_dir)`. One function,
  `core/pod_apply.py::repo_config_dir(codebase: Path, project: str) -> Path`; every site calls
  it. `InitRequest.name` is the pod name `init` was given; `init` without `--name` in a repo
  whose `.docket/` has `teams/` and no `pod.yaml` exits 2 naming the teams (`ui.error`, the
  pattern of the `--recipe` conflict in `_resolve_repo_apply_source`). `export_pod(project,
  directory)` default directory = `repo_config_dir`; when the repository already has
  `.docket/teams/` and the pod has no directory yet, export creates `teams/<pod>/`.
- Tests: `tests/unit/core/test_pod_apply.py`, `tests/unit/cli/test__agents.py` (init
  resolution; its fixtures build a temp repo), `tests/unit/cli/test__pod_config.py`.
  `docs/CONFIGURATION.md`: one paragraph under the configuration-of-record section.
- Forbidden: `serve.py`, `core/pod_report.py`, `core/dispatch.py`.

### P43-8 — `POST /pods/<p>/apply` (Sonnet)

- Core today: `pod_apply.plan_apply(project, directory) -> ApplyPlan`,
  `classify_directory(directory) -> PlanReview` (what runs on this machine),
  `apply(plan) -> ApplyResult`. The review code and the off-terminal refusal: `rg -n
  "accept|review_code|reviewed-repos" src/docket/cli/_agents.py src/docket/core/pod_apply.py`
  -- if the code is computed in `cli/`, move the computation to `core/pod_apply.py` (a pure
  function of the directory digest) and leave the terminal prompt in `cli/`. `apply` records
  `configSource`/`configDigest` already.
- Route: `do_POST` branch `/pods/<p>/apply` before the bare `/pods` match;
  `_handle_post_pod_apply(project)`; `directory` must be absolute and existing (`400`
  otherwise), default `repo_config_dir` (P43-7; until it merges, `<codebase>/.docket`);
  `dryRun` returns the plan as `pod update --dry-run --json` prints it; a `PlanReview` with run
  items and no matching `accept` → `409` body of the spec; success → `ApplyResult` JSON +
  `dryRun`. Audit `pod.apply` with `channel=http` (find the audit action `pod update` writes
  and reuse it).
- Tests: new `tests/integration/test_serve_pods_config.py` (seed a pod, write a directory with
  `roles/x.yaml`, another with `pod.yaml` `allowCommands`); `tests/unit/core/test_pod_apply.py`
  for the moved review code.
- Forbidden: `_handle_post_pods`, `core/pod_report.py`, `core/dispatch.py`.

### P43-9 — corrections route (Haiku)

- Exact sites: `core/corrections.py::read(project)` -- add `since: str = ""` and filter
  `rec["ts"] > since` (string compare on ISO-8601 Z timestamps is correct here; say so in the
  docstring). `serve.py::do_GET`: one branch for `/pods/<p>/corrections` placed **before** the
  `/pods/<p>` branch P43-6 adds (if P43-6 is not merged yet, place it after the `/traces/`
  branches; the integrator orders them). `since` parsed from the query; a value that is not
  ISO-8601 (`datetime.fromisoformat` after replacing `Z`) → `400`. Body: `{"corrections":
  [...], "next": last ts or the given since or ""}`.
- Tests: `tests/unit/core/test_corrections.py` (`since`), `tests/integration/test_serve_pods_config.py`
  (one test; create the file if P43-8 has not).
- Forbidden: everything else.

## Wave 111 — the daemon and the command

### P43-10 — cancel, retry, diff (Sonnet)

- Cancel today: `cli/_task.py::_cancel_live_runs(found, status)` loops the task's live run ids
  and calls `core/runs.py::cancel_run(run_id)`; then `_dispatch.cancel_parked_task(project,
  task_id, channel="cli")` for a parked task. Move the whole decision into
  `core/dispatch.py::cancel_task(project, task_id, *, channel, actor="", reason="") ->
  CancelOutcome` (which run ids belong to the task: read how `_cancel_live_runs` finds them);
  the CLI keeps only rendering. Audit `task.cancel` with the channel.
- Diff: `edges/adapters/system.py::git_diff_range(repo_dir, base, ref) -> tuple[bool, str]`
  (`git -C repo diff base..ref`, capped output size through the existing tool-output cap or a
  stated constant) and `git_untracked(worktree) -> list[str]` (`git status --porcelain`, `??`
  lines). `core/dispatch.py::task_diff(project, task_id) -> dict` reads the task's `worktree`
  record (`branch`, `baseCommit`, `dir`), the codebase from the implementer's meta, and builds
  the spec's object; an in-place task (no `worktree.branch`) raises a `DispatchError` the route
  maps to `409`.
- Routes: `do_POST` branches `/tasks/<pod>/<id>/cancel|retry` (place before the
  `/answer`/`/pregrants` suffix checks in `_handle_post_tasks` or beside them -- they split on
  the suffix), `do_GET` `/diff` beside `/evidence`. CLI: `task diff <id>` prints `patch`
  (`--json` the object).
- Tests: new `tests/integration/test_serve_task_lifecycle.py` (a temp git repo as codebase, a
  task run on the stub server whose implementer writes one file and the pinning commit
  `_pin_implementer_tree` makes), `tests/unit/core/test_dispatch.py` (`cancel_task` with
  monkeypatched `cancel_run`), `tests/unit/edges/test_system.py` (argv). Golden: `task --help`.
- Forbidden: `_compose_hop`, `enqueue_task`, `serve.py::_handle_post_pods`.

### P43-11 — a supervised daemon (Sonnet)

- `dispatch_pod(...)`: add `stop: Callable[[], bool] | None = None`; the `while` condition
  gains `and not (stop and stop())`, checked before each `_claim_next_task` (never inside a
  task). `serve.py::_sweep_one_pod` passes `stop=controller.stop.is_set` (thread the
  controller or the event into the sweep: `_submit_pod_sweep` is called from `_run_sweeps`, which
  `run_serve` drives; the `stop` event already exists in `run_serve`) and `resume=True`.
  `reclaim_stale_running` is then on every sweep: confirm it is idempotent on a healthy queue
  (`_claim_stale_reason` checks `claimPid` liveness and the lease) and that the trace/audit
  stays quiet when nothing is stale. `_handle_post_tasks`: after a successful enqueue, when the
  server runs with dispatch on (`run_serve` knows; expose a module flag or pass it to the
  handler class the way the token is), call `_submit_pod_sweep(project)`. `cli/_service.py`:
  `--bind` passed to `run_serve(bind=)`; the startup line already prints `Bind:`.
  `render_health`: add `apiVersion` and the `dispatch` block (`on`, `inflight` from
  `_sweep_inflight`, `stopping` from the controller, `workers` from `cfg.DISPATCH_SWEEP_WORKERS`).
- Tests: `tests/unit/core/test_dispatch.py` (a scripted runner and a `stop` that flips after
  the first claim), `tests/integration/test_serve_stop_signals.py` (fixtures for the
  controller are there), `tests/integration/test_serve_tasks_endpoint.py` (monkeypatch
  `_submit_pod_sweep`), `tests/unit/cli/test__service.py` (`--bind`). Golden: `start --help`.
- Forbidden: `_claim_next_task`, the body of `reclaim_stale_running`, `_compose_hop`.

### P43-12 — delete harness mode, version 5, beta.6 (Sonnet; approved 2026-10-14, nothing kept)

- Script first: `scripts/maint/remove_harness_mode.py` with the exact list the card gives,
  `--check` (prints what it would remove) and the removal (`git rm`). Before running it, move
  the stub OpenAI-compatible server and any jail fixture other tests import from
  `tests/integration/test_harness_cli.py` / `test_sandboxed_exec.py` into
  `tests/integration/conftest.py` (grep every importer: `rg -n "test_harness_cli|test_sandboxed_exec" tests`).
  The escape matrix (`tests/integration/test_escape_matrix.py`) may drive `docket exec`: port
  those scenes to `docket run` on a seeded pod (same jail, same chokepoint) and prove with the
  matrix's own assertions that nothing weakened.
- Registry: `cli/__init__.py` (the 177-line registry, `scripts/maint/split_cli_registry.py`
  wrote it; edit the registry, not the script, and keep the guard
  `tests/guards/test_cli_registry*.py` green). `cli/_setup.py`: drop `setup harness`.
- Only-the-harness-used-it rule: for every symbol the card lists under "proven by `rg`", run
  `rg -n <symbol> src tests scripts` after the deletions; zero remaining users means the
  symbol goes in this card (its test too), one remaining user means it stays untouched. Say
  which way each went in the return. `core/setup_home.py` and `core/harness_pipeline.py` are
  expected to go; `approvalMode: refuse` in `core/pod.py` and `core/tools.py` is expected to
  stay (a pod setting). The `refuse` default in `edges/adapters/docket_runtime.py` was the
  harness's: the driver's default becomes the pod's (`wait`), with the dispatch call sites
  unchanged because they pass the mode explicitly (verify with `rg -n "approval_mode" src`).
- No trace: no alias, no "did you mean", no notice in `--help`, no `CHANGELOG` "deprecated"
  wording (it says removed), no `# removed` comment, no skipped test, no empty module.
- Prose: for each file in `rg -ln 'docket exec|harness' docs/*.md README.md specs/*/*.md`,
  remove or rewrite the sentence; `docs/DEVELOPMENT-HARNESS.md` becomes the HTTP walkthrough
  of `operator-api.spec.md` or is deleted (say which in the return). `tests/agent` README
  prose tests: rebuild from the README, never carry an old assertion. `docs/commands.md`
  regenerated. ADR 0001/0026 headers: the integrator adds the superseded line.
- Version: `serve.py::SERVE_API_VERSION = "5"`; `serve-read-api.spec.md` `API version` line and
  3.9.0 changelog naming `operator-api.spec.md`; `operator-api.spec.md` status → Implemented,
  5.0.0 changelog entry dated; `VERSION` and `pyproject.toml` → `0.2.0-beta.6`. The integrator
  writes `CHANGELOG.md`.
- Tests: `tests/unit/cli/test_registry.py` (exit 2, no hint), `tests/integration/test_serve_status.py`
  (`apiVersion == "5"`). Goldens: `docket --help` and `setup --help` recaptured and explained.
- Forbidden: `core/dispatch.py`; any alias, notice or hint for `exec`.
