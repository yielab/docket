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
> ## ▶ ACTIVE BOARD — WAVE 63-64 · Phases 63 and 64 on three shared waves (D-85, D-86, accepted 2026-11-03)
>
> **Two phases run on one calendar**, scheduled by file contention: Phase 63 (Tack's four asks: the pod's
> contract, the role check at claim, the shape and the folder apply, the budget window and the resume
> route) and Phase 64 (the pod's memory works for every pod; two §7.1 housekeeping cards). The wave table
> is under Phase 63; `FEATURES` and its test are the integrator's; the full suite runs once per wave.
> Wave 1 is P63-1, P63-3, P63-4, P64-1, P64-2 and P64-6, all `TODO`, no file in common.
> Before them, Phases 60 (D-82), 61 (D-83) and 62 (D-84) closed 2026-11-03: a transient failure costs a request, a pod says what it can reach, and `fetch` keeps the perimeter. Their sections are archived and what they leave open is in the follow-ups below. Phase 59 (D-81, [ADR 0038](docs/adr/0038-a-step-budget-is-a-checkpoint-not-a-cliff.md)) closed 2026-11-03
> (decision 5 amended before the push): a step's budget is a checkpoint, not a cliff, and docket keeps no dollars. Its
> section is archived and what it leaves open is under "Phase 59" in the follow-ups below. Phase 58 (D-80) closed 2026-11-02: what a plan of record needs to follow a team it does
> not run. Its section is archived and what it leaves open is under "Phase 58" in the follow-ups below.
> **Phase 57** (D-79, [ADR 0037](docs/adr/0037-what-docket-gives-a-manager-in-the-plan-of-record.md)) closed 2026-11-01. Before it, Phase 56 (D-77, [ADR 0036](docs/adr/0036-a-pod-works-outward.md) decisions 13-16) closed
> 2026-10-30: an external service is declared, not programmed; a pod keeps records; one judge; one home layout; the
> four team shapes. Its section is archived and what it leaves open is under "Phase 56" in the follow-ups below.
> Decisions 15-16 of the ADR were accepted by the maintainer the same day. Phase 55
> closed 2026-10-30; Phases 52 to 54 closed 2026-10-29. The integration branch is `develop`. A new phase starts from
> a measured trigger or a maintainer request.

## How to use this board (read before claiming a card)

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

## ▶ PHASE 63 ACTIVE — WAVE 63-64 (three waves shared with Phase 64) · a plan of record reads a pod's contract and applies to any shape (D-85, accepted 2026-11-03)

> From Tack's orchestration audit of 2026-11-03 (its `develop` 301b40fa against docket's adf584a6; every
> line reference re-checked at a5432e9e, where all hold): four additive asks on API 6, each announced in
> `features`, in the order that helps Tack most: the contract (`podContract`), the role check
> (`pipelineChecked`), the shape and the folder apply (`podShape`), the budget window and the resume
> route (`podResume`). Tack's cards D, F and G (`docs/plans/phase-89.md` in its repository) probe them.
> API stays 6. Not asked, and not planned: subtasks or a DAG in docket (D-20), cross-pod dispatch, a
> fifth blueprint, an authored blueprint format, dollars anywhere.
>
> **Decisions the plan takes (accepted by the maintainer 2026-11-03):**
> 1. A task-named pipeline the roster cannot staff fails with the existing `failureKind: "pipeline"`, the
>    kind an unknown pipeline already has; the reason names the pipeline, each role and its step.
>    `capability_missing` stays a turn's stop on a tool the role could have held (ADR 0032 decision 7).
>    The closed set of kinds does not grow.
> 2. The `needs` a recipe declares are kept on the pod at apply (a recorded Lead key, like `configSource`,
>    the union of every applied directory's list) and their readiness is computed per request. The
>    2026-11-03 follow-up "`pod export` drops a recipe's `needs`" stands: export still omits them.
> 3. The budget window counts from real per-day usage kept in the session record, which also closes the
>    documented gap "`--history` is always empty" (`cost-tracking.spec.md`). Window starts are UTC: `day`
>    is 00:00 today, `week` is Monday 00:00. A turn's tokens land in the day it ends.
> 4. Over HTTP, a folder pod's apply needs `directory` (there is no repository to default to) and the
>    review memory's root is the pod's `workDir`, as `docket pod update` already does on a terminal.
> 5. One writer clears a pause (`tasks/application/lifecycle.py`), used by `docket run --resume`, `docket
>    pod set budgetTokens` and the new route; the two copies in `interfaces/cli` go.
>
> **Waves (by file; the calendar is shared with Phase 64, Sonnet workers in parallel, one integrator;
> plan: `internal-docs/plans/fases-63-64-consolidadas-2026-11-03.es.md`):**
>
> | Wave | Cards | File contention resolved |
> | --- | --- | --- |
> | 1 | P63-1 ∥ P63-3 ∥ P63-4 ∥ P64-1 ∥ P64-2 ∥ P64-6 | `pod_settings.py` is P63-1's (P63-5 waits); `apply/write,needs` (P63-1) and `apply/plan,recipes` (P63-4) are different files |
> | 2 | P63-2 ∥ P63-5 ∥ P64-3 ∥ P64-4 | `report.py` and `steps.py` are P63-2's; `memory_decide.py` is P64-3's, `memory.py` P64-4's |
> | 3 | P63-6 ∥ P64-5 ∥ P64-7 | `routes/pods.py`, `report.py`, `cli/pod_settings.py` are P63-6's; P64-5 is the integrator's real run |
>
> **`FEATURES` (`interfaces/http/routes/health.py` ~21) and its exact-list test
> (`tests/unit/interfaces/http/routes/test_health.py`) are integrator-owned for the three waves:** a
> worker names the feature it announces in its packet and does not open either file; the integrator adds
> the names when merging the wave (1: `pipelineChecked`, `podShape` · 2: `podContract` · 3: `podResume`,
> `memoryStatus`). P63-5 announces nothing: `podResume` covers the window and lands with P63-6. The
> integrator runs the full suite once per wave, not per card.

### P63-1 — The pod keeps what its recipes said their work needs

**Status:** DONE (wave 1, 2026-11-04) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** —

- **Trigger:** Tack's D2 (2026-11-03): `needs[]` on `GET /pods/<p>`, "what Phase 62 computes at apply,
  kept and reported". Today `teams/apply/needs.py::readiness` is called once, by
  `interfaces/cli/render/apply.py` ~100, and nothing records the list; a pod made by `POST /pods` and
  applied over HTTP never shows it.
- **Goal:**
  - `teams/apply/write.py::apply` (~339-348, where `configSource` is recorded) also records `needs` on
    the Lead: the union, in first-seen order, of the pod's recorded list and `recipe_needs(plan.directory)`.
    A directory that declares none leaves the key as it was.
  - `needs` joins `PodSettings.RECORDED_KEYS` (`teams/pod_settings.py` ~317): `docket pod set needs` and
    a `pod.yaml` `settings.needs` are refused like `configSource`; stored comma-joined like `protects`.
  - `NeedLine` (`teams/apply/needs.py` ~24) becomes the wire shape: `kind` (`fetch-hosts`, `search-host`,
    `isolation`), `name` (equal to `kind` today; the field exists so a need can later be named per host),
    `fix` (the command, `""` when ready), `satisfied` (bool); `render()` keeps today's text, so P62-2's
    output is byte-identical. `readiness(project, needs)` keeps its signature.
  - `docket pod show --json` carries `needs: [{kind, name, fix, satisfied}]` (`[]` when none is
    recorded); `pod show` prints one line per need, in `render()`'s words.
- **Non-goals:** `GET /pods/<p>` (P63-2); new kinds of need; `pod export` writing `needs`.
- **Change:** `teams/apply/write.py`, `teams/apply/needs.py`, `teams/pod_settings.py`,
  `hops/application/report.py` (`pod_report` ~397-433: one `needs` key), the `pod show` renderer in
  `interfaces/cli/commands/pod_config.py` (locate with `rg -n "settings" src/docket/interfaces/cli/commands/pod_config.py`),
  tests `tests/integration/teams/test_recipe_needs.py`, `tests/unit/hops/application/test_report.py`.
  Specs: `docket-meta.spec.md` (the `needs` row, writer: apply), `pod-blueprints.spec.md` "Pod
  manifests: apply" requirement 16 (recorded), `cli-json-shapes.spec.md` "`docket pod show --json`".
- **Acceptance (RED first):**
  - Integration: a fresh home, isolation off, `docket init --recipe web-research`, then `pod show
    --json`: `needs` has three entries, `satisfied: false` on each, each `fix` the command P62-2 prints.
    Oracle: today `needs` is absent.
  - Integration: `pod set fetchDomains 'html.duckduckgo.com'`, then `pod show --json`: `fetch-hosts` and
    `search-host` are `satisfied: true` with `fix: ""`; the recorded list did not change.
  - Integration: applying a second directory with no `needs` keeps the three; one with `needs:
    [isolation]` keeps three (union, no duplicate).
  - Unit: `docket pod set needs x` and a `pod.yaml` with `settings: {needs: [...]}` are refused naming
    the key, as `configSource` is.
  - `render()` on each line equals its 2026-11-03 text (the P62-2 test passes unchanged).
- **Gate:** the two test files; `tests/unit/teams/apply/`; `tests/architecture`; `validate-specs.sh`;
  `gen_cli_docs.py --check` if `pod show`'s help text moved.

### P63-2 — `GET /pods/<p>` carries the pod's contract: what it delivers, the methods a task may name, what it still needs

**Status:** TODO (after P63-1 and P63-3) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P63-1 (it serves the recorded `needs`), P63-3 (both edit `hops/application/steps.py`)

- **Trigger:** Tack's D2. Its card D fits a profile to a team from `delivers`, `methods` and `needs` and
  refuses a run before any `POST /tasks` when the fit fails; today it infers the first from
  `workspaceKind`, has no list of the pipelines a task may name, and learns of a skipped step only by
  reading hops.
- **Goal:** `hops/application/report.py::pod_report` (~397-433; `pod_detail` ~558 inherits it, so
  `GET /pods/<p>` and `docket pod show --json` carry the same keys):
  - `delivers`: a list, `["branch"]` for a `codebase` pod, `["report"]` for a `workdir` pod, plus
    `"records"` when `teams/records.py::pod_record_sets(project)[0]` is non-empty. A list, so a third
    kind is additive.
  - `methods`: one entry per pipeline a task may name for this pod, from the same resolution
    `_task_pipeline_file` uses (`hops/application/steps.py` 134-147): the pod overlay, the operator's
    `config/pipelines`, every recipe (the operator's before the shipped ones) carrying a
    `pipeline.yaml`; the first scope holding a name wins, as at claim. Refactor `_task_pipeline_file`
    to iterate one new `task_pipeline_files(project) -> list[(name, path, source)]`, so the report and
    the claim can never disagree. Each entry `{name, source, missingRoles, default}`: `source` the
    claim's label (`pod:<n>`, `operator:<n>`, `shipped:<n>`, `recipe:<n>`); `missingRoles` the roles of
    its unit steps `resolve_plan` marks `skipped` against `pod_full_roster(project)`
    (`pipeline/domain/plan.py` 188-199), in step order, deduplicated; `default: true` on the entry whose
    file's sha256 equals `PodSettings.pipeline` (the bound copy's digest), else `false` everywhere. A
    file that does not load is listed with `missingRoles: []` and an `error` string, never dropped: the
    method exists, and a task naming it fails at claim with that text.
  - `needs`: P63-1's list, each `{kind, name, fix, satisfied}`, computed now.
  - `features` gains `podContract`.
- **Non-goals:** listing the blueprint's default pipeline as a method (it has no name a task can give;
  `pipeline.source` already says what runs); the A2A agent card (follow-up); a method's steps.
- **Change:** `hops/application/report.py`, `hops/application/steps.py`, tests
  `tests/unit/hops/application/test_report.py`, `tests/unit/hops/application/test_steps.py`,
  `tests/integration/interfaces/test_serve_pods_endpoint.py` (`FEATURES` and `test_health.py` are the
  integrator's: name `podContract` in the packet), fixture
  `tests/fixtures/operator-v2/pod-contract.json` (a `respond` pod with one overlay method missing a role
  and two needs). Specs: `operator-api.spec.md` "Pod answers" (the three keys and the feature),
  `cli-json-shapes.spec.md` "`docket pod show --json`".
- **Acceptance (RED first):**
  - Integration (HTTP): a `build` pod with no record sets: `delivers == ["branch"]`; a `respond` pod
    with the `records` recipe applied: `["report", "records"]`.
  - Integration: a pod with `pipelines/tdd.yaml` in its overlay and the shipped recipes present:
    `methods` holds `tdd` with `source: "pod:tdd"`, then every shipped recipe carrying a
    `pipeline.yaml`, each with the `missingRoles` the roster cannot fill (a `respond` roster lacks
    `implementer`: every build-shaped method names it). Oracle: a task naming a method with
    `missingRoles: []` runs every step (P63-3's test is the other half of this seam).
  - Integration: after `pod set pipeline <file>` whose bytes equal `pipelines/tdd.yaml`, `tdd` has
    `default: true` and no other entry does.
  - Unit: `task_pipeline_files` lists `pod` before `operator` before `shipped` before `recipe` for one
    name, and `_task_pipeline_file` returns that first entry (the existing `test_steps.py` cases pass).
  - `status.json` `features` contains `podContract` once the integrator adds it at the wave merge.
- **Gate:** the three test files; `tests/architecture`; `tests/e2e -n auto` (42 s, the HTTP API
  changed); `validate-specs.sh`.

### P63-3 — A task that names a pipeline the pod cannot staff is refused at claim, not run with holes

**Status:** DONE (wave 1, 2026-11-04) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** —

- **Trigger:** Tack's D3. `apply` and `pod set pipeline` refuse a step whose role the roster lacks
  (`teams/apply/recipes.py` 19-33, `unresolvable_pipeline_steps`), but a task that names a pipeline
  (`{"pipeline": "tdd"}`, the only path Tack uses) runs with the role-less steps dropped
  (`pipeline/domain/plan.py` 194; `ExecutionPlan.runnable_nodes` 129-133). A step Tack's profile counts
  on is skipped in silence.
- **Goal:**
  - In `hops/application/steps.py::_task_pipeline` (160-186), once the named pipeline loads, plan it
    against `pod_full_roster(project)` and the pod's registry (as `_plan_pipeline` does in
    `teams/apply/plan.py` ~344-370) and raise `TaskRunRefusal` when `unresolvable_pipeline_steps(plan,
    project)` is non-empty: `pipeline 'tdd' (recipe:tdd) names roles this pod does not have: reviewer
    (step review)`. The sweep already turns a `TaskRunRefusal` into `refuse_claimed_task(project, task,
    "pipeline", ...)` (`hops/application/sweep.py` ~136): the task settles `failed`, `failureKind:
    "pipeline"`, the reason verbatim, before any hop, re-queued by `docket task retry` once the pod
    has the role.
  - Only a task-named pipeline is checked. The pod's bound pipeline, a blueprint's default and `docket
    run --pipeline <file>` keep the skip rule (pod-dispatch "Pipeline order and participation"
    requirement 1: a lean `build` pod runs two hops).
  - `features` gains `pipelineChecked`.
- **Non-goals:** a new failure kind; refusing at `POST /tasks` (the pod can change between enqueue and
  claim, and the claim is where every other pipeline refusal lives); a kept `pipelineSpec` (it was
  planned when it was kept).
- **Change:** `hops/application/steps.py`, tests `tests/unit/hops/application/test_steps.py`,
  `tests/integration/tasks/dispatch/test_pipeline_and_hops.py` (`FEATURES` and `test_health.py` are the
  integrator's: name `pipelineChecked` in the packet), fixture
  `tests/fixtures/operator-v2/task-pipeline-refused.json` (the failed task record). Specs:
  `pod-dispatch.spec.md` "Pipeline order and participation" requirement 1 (the task-named exception)
  and the unknown-pipeline rule (`rg -n "unknown pipeline" specs/`), `operator-api.spec.md` "Task
  answers" (`failureKind` paragraph ~292-304: the role case under `pipeline`; the feature).
- **Acceptance (RED first):**
  - Integration: a lean `build` pod (Lead + Implementer) and a task `{"pipeline": "tdd"}` where `tdd`
    has a `reviewer` step: the task is `failed`, `failureKind: "pipeline"`, the reason names `tdd`,
    `reviewer` and the step id, `hops == []`, and the trace has `dispatch_refused`. Oracle: today the
    task runs two hops and settles `done`.
  - Integration: the same pod and task with no `pipeline`: two hops, `done` (the default pipeline's
    skip rule is untouched).
  - Integration: after `docket pod add reviewer`, `docket task retry` runs all three steps.
  - Unit: the refusal text lists each missing role once with its step, in step order.
  - Integration (a check, not a fix): the task refused at claim stays `failed` across two further sweep
    ticks and the trace holds one `dispatch_refused` for it, not one per tick (`refuse_claimed_task` writes
    trace only, no audit entry; `dispatch_refused` is in
    `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; the follow-up "A refused task is resumed on every
    30 s sweep tick"). If this fails, it is its own card: report it, do not widen this one.
- **Gate:** the three test files; `tests/architecture`; `validate-specs.sh`.

### P63-4 — `pod.yaml` names its shape, and apply reaches a folder pod over HTTP

**Status:** DONE (wave 1, 2026-11-04) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** —

- **Trigger:** Tack's D1. `PodDocument` (`teams/config_models.py` 121-134, `extra="forbid"`) and
  `_MANIFEST_KEYS` (`teams/config_docs.py` ~540) take no shape, so a recipe cannot say which blueprint
  it is for and Tack's import preview guesses the `docket init --blueprint` it prints.
  `POST /pods/<p>/apply` answers 400 when the Lead has no `codebase`
  (`interfaces/http/routes/pod_apply.py` 28-35), and every `respond`, `operate` and `routine` pod is
  provisioned with `codebase=""` (`teams/pod_provisioning.py` 429-432), so the recipes meant for
  those pods (`outward`, `ops-approval`, `records`, `web-research`) cannot be applied over HTTP; on a
  terminal `docket pod update` already can (`interfaces/cli/commands/pod_config.py` ~133-141 passes
  `workdir=`).
- **Goal:**
  - `shape: build|respond|operate|routine` is the eleventh `pod.yaml` key (`PodDocument`,
    `_MANIFEST_KEYS`), the closed set `POST /pods` takes as `blueprint` (`teams/blueprints.py`
    `BUILTIN_BLUEPRINTS`). `plan_apply` (`teams/apply/plan.py` ~481-520) refuses, before any other item
    is planned, a `shape` that differs from the Lead's `blueprint` meta (`_plan_members` ~305 reads
    it): `pod.yaml: shape 'respond' but pod 'x' was provisioned 'build'`; a pod with no recorded
    blueprint accepts any shape. `summarize_recipe` (`teams/apply/recipes.py`) reports the shape so
    `docket pod update`'s header prints it.
  - `post_pod_apply`: for a `workdir` pod (`_review.is_workdir`), `directory` is required (400:
    `directory is required: pod 'x' works in a folder and has no repository to read .docket/ from`),
    absolute as today, and the review root passed to `apply_directory` is the Lead's `workDir`. The
    `reviewCode` flow is unchanged: a directory that runs things on this machine still answers 409 with
    the code.
  - Shipped recipes whose `members` exist in one blueprint's roster only (check against
    `teams/blueprints.py` 239-266) declare their `shape`; a recipe any shape can take declares none.
  - `features` gains `podShape`.
- **Non-goals:** a shape on `docket init` other than `--blueprint`; converting a pod from one shape to
  another; relative directories; a shape in `pod export` beyond what the pod records.
- **Change:** `teams/config_models.py`, `teams/config_docs.py`, `teams/apply/plan.py`,
  `teams/apply/recipes.py`, `interfaces/http/routes/pod_apply.py`,
  the shipped `pod.yaml` files that take a shape, tests `tests/unit/teams/apply/test_plan.py`,
  `tests/integration/interfaces/test_serve_pods_config.py` (`FEATURES` and `test_health.py` are the
  integrator's: name `podShape` in the packet). Specs: `pod-blueprints.spec.md` "Pod manifests:
  apply" requirement 1 (eleven keys, the shape rule), `operator-api.spec.md` "`POST /pods/<p>/apply`"
  (the folder-pod rule), `config-format.spec.md` if it lists `PodDocument`'s keys
  (`rg -n "protects" specs/functional/config-format.spec.md`).
- **Acceptance (RED first):**
  - Unit: `plan_apply` on a `build` pod with `shape: respond` raises naming both shapes and plans
    nothing; `shape: build` plans as before; `shape: fleet` is refused as not one of the four.
  - Integration (HTTP): `POST /pods {name, blueprint: "respond"}` then `POST /pods/<p>/apply
    {directory: <absolute copy of the shipped outward recipe>}`: 200 with the plan's items, and the
    roster gains the recipe's members. Oracle: today 400 "has no recorded codebase".
  - Integration (HTTP): the same with no `directory`: 400 naming `directory`; with a directory holding
    a `run:` step: 409 with `reviewCode`, then 200 with `accept`.
  - Integration: `docket pod update` on the same folder pod still works (`test_recipes.py`).
  - Integration (HTTP, folded follow-up): an apply whose every item is skipped writes one `pod.apply`
    audit entry with `channel=http` and the counts, as an apply that changes something does (today it
    writes none; same file `routes/pod_apply.py`).
- **Gate:** the three test files; `tests/integration/teams/test_recipes.py`; `tests/architecture`;
  `tests/e2e -n auto` (the HTTP API changed); `validate-specs.sh`; `gen_cli_docs.py --check` if the
  update header text is documented.

### P63-5 — The pod budget gets a window, counted from the day the tokens were spent

**Status:** TODO (wave 2) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P63-1 merged (both edit `teams/pod_settings.py`; no other dependency)

- **Trigger:** Tack's D4. `budgetTokens` is compared with `pod_counted_tokens`
  (`hops/application/usage.py` 45-54), a lifetime sum over every member and session, so `frugal`'s
  1M pauses a healthy pod for ever. The session record keeps one running total (`agent/session.py`
  `MeasuredUsage`, `_add_usage` ~117, `SessionRecord.usage` ~137), which is why
  `DocketDriver.usage().by_day` is always empty (`hops/application/driver.py` 357-369;
  `cost-tracking.spec.md` "Known gap: `--history` is always empty").
- **Goal:**
  - `SessionRecord` gains `usageByDay: {"YYYY-MM-DD": MeasuredUsage}` (UTC day of the append);
    `append_messages` (~207-229) adds the delta to the total and to the day. A record without the key
    reads as `{}`. `DocketDriver.usage` fills `by_day` from it, so `docket status --history` stops being
    empty: the known-gap section is deleted.
  - `PodSettings.budget_window: Literal["none", "day", "week"]` (alias `budgetWindow`, default `none`,
    in `_SETTING_FIELD_BY_ALIAS` ~99 and `KEYS`). `window_start(window, now) -> datetime | None`, a pure
    function in `hops/domain/gate_decisions.py`: `none` is `None`; `day` 00:00 UTC today; `week` Monday
    00:00 UTC.
  - `pod_counted_tokens(project, since=None)`: with `since`, sums each member's `by_day` buckets whose
    day is on or after `since`'s date; without it, today's total. Both pre-hop readers
    (`hops/gates/pre_hop.py` ~104 the ceiling, ~123 the gate) pass the window's start.
    `budget_exceeded`'s detail gains `window` and `windowStart` (`"none"` and `null` without a window).
  - `docket pod set budgetWindow <day|week|none>` validates through `coerce`; a `set` or `unset` of
    `budgetWindow` clears the pause and unblocks, as `budgetTokens` does
    (`interfaces/cli/commands/pod_settings.py` ~96, ~221, ~339: extend the key check, never copy the
    block). `pod.yaml` `settings.budgetWindow` applies through the same validator.
- **Non-goals:** the resume route and the `budget` report object (P63-6); a rolling window; a per-day
  count for a session written before this card (its tokens count toward `none` only); a budget per
  member.
- **Change:** `agent/session.py`, `hops/application/driver.py`, `hops/application/usage.py`,
  `hops/domain/gate_decisions.py`, `hops/gates/pre_hop.py`, `teams/pod_settings.py`,
  `interfaces/cli/commands/pod_settings.py`, tests `tests/unit/agent/test_session.py`,
  `tests/integration/tasks/test_autopause.py` (`test_cap_breach_pauses_lead_and_blocks_task` ~130 gets
  a windowed sibling). Nine files: the seam between the day bucket and the gate stays in one card so
  no two green cards break it. Specs: `session-history.spec.md` (the record's `usageByDay`),
  `cost-tracking.spec.md` ("Budget caps" the window, "Enforcement" the count, the known gap deleted),
  `pod-dispatch.spec.md` "Pod dispatch settings" `KEYS` and "Budget gate and auto-pause" requirement
  1, `docket-meta.spec.md` (`budgetWindow` row; `paused` writers).
- **Acceptance (RED first):**
  - Unit (`test_session.py`): two appends on different UTC days give two buckets whose sum equals the
    total; a record without `usageByDay` loads with `{}`.
  - Unit: `window_start("week", a Wednesday 15:00 UTC)` is that week's Monday 00:00 UTC; `"day"` is
    that day's 00:00; `"none"` is `None`.
  - Integration (`test_autopause.py`): a pod with `budgetTokens 1000`, `budgetWindow day` and sessions
    holding 2000 tokens dated yesterday and 100 today: the hop runs and the pod is not paused. Oracle:
    with `budgetWindow none` (and on today's code) it pauses. With 1000 today it pauses, and
    `budget_exceeded` carries `window: "day"` and the start.
  - Integration: `docket pod set budgetWindow week` on a paused pod clears `paused` and re-queues its
    blocked tasks; `budgetWindow month` is refused naming the three values.
  - `docket status --history` on a home with two days of sessions prints two rows (a test that pins the
    empty history is rewritten, not deleted).
- **Gate:** the two test files; `tests/unit/hops/`; `tests/architecture`; `validate-specs.sh`;
  `gen_cli_docs.py --check` (`pod set`'s key list is documented).

### P63-6 — `POST /pods/<p>/resume` clears a pause, and every pod answer says its budget

**Status:** TODO (after P63-5) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P63-5 (the `window` and `windowStart` it reports; the clearing writer it shares); P64-4 merged (the memory entry's wire shape it lists)

- **Trigger:** Tack's D4: the pause clears only from the CLI (`docket run --resume`,
  `interfaces/cli/commands/run.py` ~163; `docket pod set budgetTokens`,
  `interfaces/cli/commands/pod_settings.py` ~96), two copies of the same two `meta_set` calls;
  `operator-api.spec.md` "Pod answers" ~418 says "There is no route to clear a pause". Tack's card F
  puts a **Resume team** button on the team row and a Limits fold on the run card.
- **Goal:**
  - One writer: `tasks/application/lifecycle.py::resume_pod(project) -> bool` clears
    `paused`/`pausedReason` on the Lead, calls `unblock_pod`, audits `run.resume` when the Lead was
    paused (cost-tracking requirement 7's entry, its name unchanged) and returns whether it was. `run
    --resume` and `pod set`/`unset` of `budgetTokens` and `budgetWindow` call it; the two copies are
    deleted, no shim.
  - `POST /pods/<p>/resume` (`interfaces/http/routes/pods.py`; `routes/table.py` ~59 beside apply;
    bearer token like every write): no body; a paused pod answers 200 with the pod report
    (`pod_detail`) plus `resumed: true`; one that is not paused answers 200 with the report and
    `resumed: false`, nothing written; an unknown pod 404. Audited with `channel=http`, as apply is.
  - `budget: {tokens, used, window, windowStart}` on every `GET /pods` row (`pod_summary` ~530) and on
    `GET /pods/<p>` (`pod_report`): `tokens` the cap or `null`; `used` the count the gate would compare
    now (`pod_counted_tokens` with the window's start); `window` one of `none|day|week`; `windowStart`
    the ISO-8601 UTC instant, `null` for `none`. One `_budget_fields(project, settings)` in `report.py`,
    called from both.
  - `GET /pods/<p>/memory?status=accepted|pending|refused` (`interfaces/http/routes/pods.py` ~59-66,
    `get_pod_memory`): the entries in that status, oldest first, the wire shape P64-4 defines; no
    `status` keeps today's answer (accepted only); another value is 400 naming the three. This is how a
    plan of record sees what waits for `docket pod memory approve` until the inbox contract is bumped
    (follow-up under "Channels, inbox and the HTTP API").
  - `GET /pods` (the list, `pod_summary`) is checked for the invalid-settings failure fixed on `/pods/<p>`
    (folded follow-up): a pod whose settings fail validation is listed with its error, the route answers
    200.
  - `features` gains `podResume` and `memoryStatus` (the integrator adds both).
- **Non-goals:** resuming one task (`POST /tasks/<pod>/<id>/retry` exists); a body that changes the
  budget; a `pausedUntil`; dollars; a route that approves a memory entry (CLI only; a follow-up if Tack asks).
- **Change:** `tasks/application/lifecycle.py`, `interfaces/cli/commands/run.py`,
  `interfaces/cli/commands/pod_settings.py`, `interfaces/http/routes/pods.py`,
  `interfaces/http/routes/table.py`, `hops/application/report.py`,
  tests `tests/integration/interfaces/test_serve_pods_pause.py`
  (`test_a_budget_pause_shows_on_both_routes_until_resume_clears_it` ~36 grows the route),
  `tests/unit/hops/application/test_report.py`, `tests/integration/interfaces/test_serve_pod_memory.py`
  (the `status` query), fixture `tests/fixtures/operator-v2/pod-budget.json`. Specs: `operator-api.spec.md`
  "Pod answers" (the `budget` object; the pause paragraph's last sentences replaced by the route), its
  "Syntax" route table and "Arguments" (`POST /pods/<p>/resume`; `GET /pods/<p>/memory` and `status`),
  `cost-tracking.spec.md` requirement 7 (the writers), `docket-meta.spec.md` `paused`/`pausedReason`
  writers. `FEATURES` and `test_health.py` are the integrator's.
- **Acceptance (RED first):**
  - Integration (HTTP): a pod paused by the gate: the `GET /pods` row has `paused: true` and
    `budget.used >= budget.tokens`; `POST /pods/<p>/resume` is 200, `resumed: true`, `paused: false` in
    the same body; the blocked task is `pending`; the audit log has `run.resume` with `channel=http`. A
    second `POST` is 200, `resumed: false`, no new audit row. Oracle: today the route is 404.
  - Integration: a pod with no cap: `budget == {tokens: null, used: <n>, window: "none", windowStart:
    null}` on both routes; with `budgetWindow day`, `windowStart` is today's 00:00Z and `used` counts
    today only (P63-5's bucket).
  - Unit: `resume_pod` on an unpaused pod returns `False` and writes no audit row; `rg` proves
    `"paused", False` is written in one module.
  - `docket run --resume` behaves as before (`tests/unit/interfaces/cli/commands/test_run.py` passes
    unchanged).
  - Integration (HTTP): a pod with one accepted and two pending entries: `GET /pods/<p>/memory` returns
    one; `?status=pending` returns two, each with `reason` and `provenance.task`; `?status=stale` is 400
    naming `accepted`, `pending`, `refused`. Oracle: today the query is ignored.
  - Integration (HTTP): with one pod whose Lead carries an invalid setting, `GET /pods` is 200 and that
    row names the error (the `/pods/<p>` fix of 2026-11-03 has a list-side test).
- **Gate:** the four test files; `tests/unit/interfaces/cli/commands/test_run.py`;
  `tests/architecture`; `tests/e2e -n auto` (the HTTP API changed); `validate-specs.sh`.

## ▶ PHASE 64 ACTIVE — WAVE 63-64 (three waves shared with Phase 63) · the pod's memory works for every pod (D-86, accepted 2026-11-03)

> From the memory audit of 2026-11-03 (`internal-docs/audits/memoria-de-pod-2026-11-03.es.md`; plan
> `internal-docs/plans/memoria-de-pod-plan-2026-11-03.es.md`, consolidated in
> `fases-63-64-consolidadas-2026-11-03.es.md`): 22 entries written by the four live pods, 0 accepted, 0
> rendered into a prompt, 0 operator decisions. The verifier knew a git commit and a `bash` exit; three
> of the four pods work in a folder with MCP, service and `fetch` tools. The design stays (docket
> decides, one writer, audited, untrusted frame last, operator approval for `pitfall`/`convention`);
> its sources of truth, its grammar and its screen are recalibrated, and the dead workspace memory goes.
>
> **Decisions (accepted 2026-11-03):** memory is for every pod; `tool` replaces `command` and is verified
> by a `tool_call` of that tool with its `tool_result` in the trace (arguments are not matched: the model's
> rendering of them is free text); a folder pod's `generated` path is verified under its `workDir`; a
> `pitfall`/`convention` subject is a label of at most 60 characters and the id is the hash of kind,
> subject and normalized note; a note is NFKC-normalized and refused with Unicode format characters or a
> heading; instruction-like text is held `pending`, the imperative-word list goes; a gone path is `stale`
> and evicted first; the wire emits `subject`, `stale`, `evidence {ok}`/`{exit}`, no `path`/`command`/`exit`
> keys; `memory.json` has no schema version, so entries of the old kinds are dropped at the first write
> (no users; said in the commit body). Not taken: embeddings or retrieval, model-driven consolidation,
> `supersededBy`, an episodic digest, memory per member, a change to `HEARTBEAT.md`, the inbox contract
> bump. ADR 0028 decision 7's last bullet is amended in P64-1; no new ADR.
>
> **Waves:** see Phase 63's table. P64-2 (wave 1) creates the modules and splits the test file that P64-3
> and P64-4 (wave 2, parallel, disjoint files) then own. P64-5 is the integrator's real run after wave 2.
> P64-6 and P64-7 are the two §7.1 decisions, fillers for waves 1 and 3.

### P64-1 — The workspace loses `memory/`, and `MEMORY.md` is the operator's

**Status:** DONE (wave 1, 2026-11-04) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + ADR amendment · **After:** —

- **Trigger:** audit 2026-11-03: 17 of 17 live `MEMORY.md` are the template (543-557 bytes), so
  `teams/identity.py::memory_has_content` (~199) is false and nothing is composed; `memory/` is created
  (`teams/member_workspace.py` ~152; `teams/agent_memory.py` ~289), chmod-walked (`member_workspace.py`
  ~230-235), named in `_PRIVATE_FILE_NAMES` (`identity.py` ~85) and read or written by nothing
  (`agent_memory.py` 9, 41-42). ADR 0028 decision 7 says the "Fill on first run" template goes;
  `_memory_md_seed` (`agent_memory.py` ~222-255) still seeds it, and `_workflow_auto_text` (~121-126)
  still tells a manual-path agent to fill it.
- **Goal:**
  - `memory_dir`, the two `mkdir` calls and the chmod branch are deleted; `_PRIVATE_FILE_NAMES` drops
    `memory/`.
  - `_memory_md_seed` is a header only: the title and one italic line, "Operator notes. docket composes
    this file into every prompt of this member when it holds text beyond this line; docket never writes
    it." No sections, no placeholder to fill. `memory_has_content` is unchanged (headings and `_italic_`
    lines are template).
  - `_workflow_auto_text` and `_workflow_auto_text_workdir`: the "Answering" section says to answer from
    `MEMORY.md` when the operator filled it, else from the codebase `README` (or the working directory's
    notes), and drops "fill it in". `CONTRACT_VERSION` 6, so `docket setup --fix` re-seeds a v5
    `WORKFLOW_AUTO.md`; `MEMORY.md` is never rewritten (`seed_contract` keeps `if not mem_md.exists()`).
  - ADR 0028 decision 7, last bullet: "`MEMORY.md` is the operator's notes; docket seeds a header and
    never writes it; the `memory/` directory is gone." Spec req. 9 drops `memory/`; the file list
    (~358-377) drops `memory/`.
- **Non-goals:** `HEARTBEAT.md`; pod memory (`teams/memory.py`); the runtime contract projection
  (`identity.py` ~165-179).
- **Change:** `teams/agent_memory.py`, `teams/member_workspace.py`, `teams/identity.py` (~85 only),
  `docs/adr/0028-context-in-layers-and-a-budget-that-counts-new-tokens.md`,
  `specs/functional/workspace-structure.spec.md`, tests `tests/unit/teams/test_agent_memory.py`,
  `tests/integration/teams/test_pod_role_workspace_parity.py`.
- **Acceptance (RED first):**
  - Integration: a fresh home, `docket init`: no member workspace has `memory/`; each `MEMORY.md` is
    the two-line header; `compose_agent_prompt` composes no runtime context for it. Oracle: today
    `memory/` exists and `MEMORY.md` is 543 bytes.
  - Integration: a workspace with the v5 marker and an operator-edited `MEMORY.md`: `docket setup
    --fix` rewrites `WORKFLOW_AUTO.md` to v6 and leaves `MEMORY.md` byte-identical; the manual-path
    text no longer contains "fill".
  - `rg -n '"memory"|memory_dir|memory/' src/docket/teams` returns nothing.
- **Gate:** the two test files; `tests/architecture`; `validate-specs.sh`.

### P64-2 — `teams/memory.py` splits into parse, decide and store; the grammar takes `tool`, a free subject and a normalized note

**Status:** DONE (wave 1, 2026-11-04) · **Size:** M · **Model:** Sonnet · **Kind:** pure move (commit 1) + behaviour + spec (commit 2) · **After:** —

- **Trigger:** `teams/memory.py` is 691 lines holding the grammar (32-214), the verifier (220-444) and
  the store (447-690); P64-3 and P64-4 add to the middle and the end and would open one file from two
  workers and pass D-78's 1,000 lines. Measured on the live home: 3 subjects refused "not a
  repository-relative path" because req. 2 ties `pitfall`/`convention` to a path (`fetch tool`,
  `consult tool`, a URL); `command` is `bash`-only (`_traced_exit` ~308-326) while three of four pods
  call MCP and service tools; a note's Unicode is unchecked (`_safe_path` ~264 rejects control
  characters in the path only; `_vet` ~401-405 measures the note and runs the regex).
- **Goal:**
  - Commit 1, a pure move with no new test: `teams/memory_parse.py` takes `KINDS`, `MEMORY_HEADING`,
    the regexes and word lists, `ParsedLine`, `parse_memory_section`, `_safe_path`,
    `_reads_as_instruction`, `_vet`; `teams/memory_decide.py` takes `HopLike`, `TaskLike`, `_TaskFacts`,
    `_session_events` through `_decide_command`; `memory.py` keeps `MemoryEntry`, `entry_id`, the store,
    the operator API and the render, importing the two. `tests/integration/teams/test_pod_memory_rules.py`
    splits the same way: `TestDecide` and `TestCommandEntries` stay; `TestStore`, `TestOperatorApi` and
    `TestRender` move to `tests/integration/teams/test_pod_memory_store.py`. `SUBJECT` of
    `tests/unit/teams/test_memory.py` becomes `docket.teams.memory_parse`.
  - Commit 2, in `memory_parse.py`: `KINDS = ("generated", "tool", "pitfall", "convention")`; a
    `pitfall`/`convention` subject is a label of at most 60 characters with no URL and no control
    character (`_safe_path` applies to `generated` only); a `tool` subject is the invocation as written,
    at most 200 characters, no URL (what `command` required); the note is NFKC-normalized, then refused
    when any character is Unicode category `Cf` or any line starts with `#`. `_reads_as_instruction`
    keeps returning its label; what the label means is P64-3's.
- **Non-goals:** any status `_decide` assigns (P64-3); the store, id, render (P64-4); the prompt line in
  `builtin_roles.py` (P64-3).
- **Change:** `teams/memory.py`, `teams/memory_parse.py` (new), `teams/memory_decide.py` (new),
  `specs/functional/workspace-structure.spec.md` req. 1, 2, 4 (kinds, subjects, the note), tests
  `tests/unit/teams/test_memory.py`, `tests/integration/teams/test_pod_memory_rules.py`,
  `tests/integration/teams/test_pod_memory_store.py` (new, by move).
- **Acceptance (RED first, commit 2):**
  - `- pitfall: fetch tool -- returns cached summaries for a URL seen earlier` parses with subject
    `fetch tool` and no refusal. Oracle: the same line with `js // comments` as the subject, which `_vet`
    refuses today ("not a repository-relative path"); `fetch tool` is not refused on the base.
  - `- tool: rec__query SELECT 1 -- one row` parses with kind `tool`; `- command: pytest -- ok` is a
    `ParsedLine` refusal naming an unknown kind.
  - A note with `U+200D`, one with `U+202E`, and one with a line starting `#` are each refused
    "contains formatting characters or a heading"; the same notes without them pass `_vet`.
  - A 61-character `pitfall` subject is refused "subject over 60 characters"; 60 passes.
  - Commit 1's check: `uv run pytest --co -q` and `tests/architecture` green; the moved tests pass
    unchanged.
- **Gate:** `tests/unit/teams/test_memory.py`; `tests/integration/teams/test_pod_memory_rules.py`;
  `tests/integration/teams/test_pod_memory_store.py`; `tests/architecture`;
  `scripts/maint/comment_lint.py --check` on the three modules; `validate-specs.sh`.

### P64-3 — docket verifies a `tool` call and a folder pod's path, and holds instruction-like text for the operator

**Status:** TODO (after P64-2) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P64-2 (the modules, the grammar)

- **Trigger:** live home 2026-11-03: 5 `generated` entries of folder pods pending "no task commit to
  check the path against"; 3 `command` entries naming `svc__hn__search` and `rec__query` refused "no
  exit status for this command in the task's trace" while the trace holds their `tool_call` and
  `tool_result` (`agent/loop_trace.py` ~188-250: `tool`, `callId`, `arguments`; `ok`, `executed`);
  2 notes refused "starts with an imperative verb" whose first word is a tool name used as the
  sentence's subject ("`curl` a dominios externos devuelve 000", "fetch returns HTTP 200"), while
  Spanish imperatives ("ejecutarlos por separado", "deben") pass the English list.
- **Goal** (`teams/memory_decide.py`):
  - `_task_facts.root`: the pod's `workDir` when `teams/pod_settings.py::workspace_kind(project)` is
    `WorkspaceKind.workdir`, else the codebase as today (`_pod_codebase` stays where it is).
  - `generated`: accepted when the path exists at the task's commit (codebase pod, as today) or
    `os.path.lexists(root/path)` at task end (folder pod), reason "path present under the work dir";
    `provenance` carries `root` instead of `commit` for a folder pod; "no task commit" stays a codebase
    pod's pending reason only.
  - `tool`: the subject's first token is the tool name; accepted when the trace holds a `tool_call` of
    that tool with a `tool_result` for its `callId`, reason "tool call found in the task's trace",
    evidence `{ok}` from the last such result; for `bash`, `{exit}` from `process_exited`, a
    `command_step` or the verify gate (today's `_traced_exit`, kept). A tool nobody called is refused.
  - `_decide`: a note `_reads_as_instruction` labels is `pending` with that label as reason, never
    refused; `refused` stays for a URL in the note, a `block`/`require_approval`/`redact` verdict and a
    bad shape. `_IMPERATIVE_FIRST_WORDS` and its branch are deleted (`memory_parse.py`). A
    `pitfall`/`convention` that also reads as an instruction carries one reason: "reads as an
    instruction; awaits operator approval".
  - `teams/builtin_roles.py` ~25 and ~36 name the kinds `generated, tool, pitfall, convention`.
  - Spec req. 4 rewritten for the three verifiers and the pending rule; a sentence that a `convention`
    is the operator's judgement, not the regex's.
- **Non-goals:** the store, id, `stale`, render (P64-4); matching a tool's arguments; reading
  `tool_result.text`; the one-codebase-reader follow-up (its helper would have to live in `teams`;
  separate card when touched).
- **Change:** `teams/memory_decide.py`, `teams/memory_parse.py` (the deletion only),
  `teams/builtin_roles.py`, `specs/functional/workspace-structure.spec.md` req. 4, tests
  `tests/integration/teams/test_pod_memory_rules.py` (`TestDecide`; `TestCommandEntries` becomes
  `TestToolEntries`), `tests/integration/teams/test_pod_memory.py` (the seam), `tests/unit/teams/test_role_schema.py`
  if it pins the method text, fixture `tests/fixtures/pod-memory/live-notes-2026-11-03.json` (the 22
  live notes with pod and client names scrubbed, each with the status this card expects).
- **Acceptance (RED first):**
  - Integration: a folder pod, a hop ok that wrote `report.md` and ends `- generated: report.md -- ...`:
    `accepted`, reason "path present under the work dir", `provenance.root` set. Oracle: today
    `pending`, "no task commit". A path not under the work dir: `refused`. A codebase pod: unchanged.
  - Integration: a trace with `tool_call {tool: "rec__query"}` and `tool_result {ok: true, executed:
    true}` and `- tool: rec__query SELECT ... -- returns the full set`: `accepted`, evidence `{ok:
    true}`; the same line with no such call: `refused`; a `bash` call with `process_exited 1`: evidence
    `{exit: 1}`.
  - Fixture replay: none of the 22 notes is refused with "imperative"; "`curl` a dominios externos
    devuelve 000" is not refused; "do not reuse it in this pod's output" is `pending` "reads as an
    instruction"; a note with a URL is `refused`; the file records the count accepted/pending/refused.
  - Seam (`test_pod_memory.py`): the folder pod's accepted entry is in the next turn's system prompt
    under `POD_MEMORY_FRAME`, rendered as `- generated report.md: ...`.
- **Gate:** the three test files; `tests/architecture`; `validate-specs.sh`.

### P64-4 — One id per fact, `stale` on a gone path, an eviction order, and `tool` rendered

**Status:** TODO (after P64-2) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec · **After:** P64-2; parallel with P64-3 (disjoint files)

- **Trigger:** `entry_id` is `hash(kind, subject)` (`teams/memory.py` ~177-179) and `_merge` skips an
  id already present (~553-556): one `convention: .` per repository, a second fact about one file
  dropped with no trace. `_trim` (~456-466) drops the oldest accepted while a `generated` whose path is
  gone stays accepted and counted (`render_entries` ~678-680 omits it from the prompt only).
- **Goal** (`teams/memory.py`):
  - `entry_id(kind, subject, note)`: the note casefolded with whitespace collapsed. Exact repeats
    still store once; a refusal is still not reopened.
  - `MemoryEntry.stale: bool = False` and `evidence: dict[str, int | bool]` replacing `exit`
    (`{exit: n}` or `{ok: bool}`); `to_dict` emits `subject` for every kind, `stale` and `evidence`, and
    no `path`, `command` or `exit` key; `_entry_from_dict` reads only this shape (old entries drop at
    the first write; no reader for the old keys).
  - `record_task_memory`, before merging the task's entries, re-checks every accepted `generated` of the
    pod against the task's commit or root (the P64-3 verifiers, called through `memory_decide`) and
    flips `stale`; one `memory_update` with `action: "stale"` or `"fresh"` per flip, audited like a
    decision.
  - `_trim` evicts, within the two caps, refused oldest, then stale, then pending oldest, then accepted
    oldest. `render_entries` skips `stale` and renders a `tool` as `` - tool `<subject>` (ok|error|exit N): note ``.
  - Spec req. 1 (the shape), 5 (id, caps, order), 6 (stale, the tool line), 7 (the two actions);
    `operator-api.spec.md` "`GET /pods/<p>/memory`" lists the shape.
- **Non-goals:** deciding (P64-3); the `status` query (P63-6); `supersededBy`; a schema version.
- **Change:** `teams/memory.py`, `specs/functional/workspace-structure.spec.md` req. 1, 5, 6, 7,
  `specs/api/operator-api.spec.md` (the memory shape), tests
  `tests/integration/teams/test_pod_memory_store.py` (from P64-2's split),
  `tests/integration/interfaces/test_serve_pod_memory.py` (the shape; P63-6 adds the query in wave 3),
  fixture under `tests/fixtures/operator-v2/` if one holds a memory entry
  (`rg -l '"kind": "command"' tests/fixtures`).
- **Acceptance (RED first):**
  - Two `pitfall` entries with one subject and different notes: two entries, two ids; the same note twice:
    one. Oracle: today the second is skipped.
  - An accepted `generated` whose path is deleted before the next task ends: `stale: true`, absent from
    `render_entries`, present in the file, one `memory_update` `action: "stale"`; the path restored at a
    later task: `stale: false`, `action: "fresh"`.
  - 41 accepted entries with one stale: the stale one goes, the oldest live accepted stays.
  - `GET /pods/<p>/memory` rows carry `subject`, `stale`, `evidence` and no `path`, `command`, `exit`.
  - A `tool` entry with `{ok: true}` renders `(ok)`; with `{exit: 1}` renders `(exit 1)`.
- **Gate:** the two test files; `tests/architecture`; `validate-specs.sh`.

### P64-5 — The real run: a folder pod remembers, and the next task reads it

**Status:** TODO (after wave 2) · **Size:** M · **Model:** Opus (integrator) · **Kind:** real run + observability fix · **After:** P64-3, P64-4 merged

- **Trigger:** 18 live tasks, 0 renders; `prompt_composed` (`agent/loop_trace.py` ~369-384) appears in
  no live trace, so the `podMemory` section report the spec names (req. 6) is unobservable in
  production.
- **Goal:** find why `prompt_composed` is absent from the trace store (capture class, exporter-only
  path, or never emitted) and make the section report reach the trace or `docket log`; `./install.sh`;
  one task on `hn-live` or `web-research` (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` against the local
  endpoint) whose reply ends with a `## Memory` section; then a second task of the same pod. Record
  before/after under `internal-docs/baselines/phase-64/` with the fixture replay of P64-3.
- **Acceptance:** `docket pod memory list --pod <p>` shows at least one `accepted` entry with
  `evidence`; the second task's trace shows the `podMemory` section with `status: full`; the fixture
  replay reads n/22 accepted or pending-for-approval, none pending for an impossible check.
- **Gate:** the phase-close gates (`CLAUDE.md` "Testing budget"); ROADMAP "Status", this section's
  archive, `CHANGELOG.md` by the integrator.

### P64-6 — The PydanticAI and OpenHands adapters go (§7.1 decision)

**Status:** DONE (wave 1, 2026-11-04) · **Size:** S · **Model:** Sonnet · **Kind:** deletion · **After:** — (wave 1 filler; no file in common with any other card)

- **Trigger:** ROADMAP §7.1: no consumer, last changed 2026-09-01, the maintainer decided 2026-11-03.
  The follow-up "the adapters never pass `cache_write_tokens`" closes with them.
- **Goal:** delete `packages/docket-runtime/src/docket_runtime/adapters/openhands.py` and
  `pydantic_ai.py` (and the package if empty), `examples/runtime_adapters.py`,
  `tests/support/runtime_adapters.py`, `tests/agent/release/test_pydantic_ai_adapter.py`,
  `test_runtime_openhands_adapter.py`, `test_runtime_adapter_parity.py`,
  `test_runtime_adapter_public_truth.py`, `tests/unit/test_runtime_adapter_fixture_contract.py`,
  `tests/fixtures/runtime_adapters/`; the optional extras naming them in
  `packages/docket-runtime/pyproject.toml`; the sentences claiming them in
  `specs/api/runtime-library.spec.md`, `COMPATIBILITY.md` and any README; one `Removed` line in
  `CHANGELOG.md` (integrator). `docket-runtime` itself stays.
- **Acceptance:** `rg -n "pydantic_ai|openhands" --glob '!internal-docs/**' --glob '!docs/cycles-ended/**' --glob '!CHANGELOG.md' .`
  returns nothing; `uv run pytest --co -q` collects; `tests/guards/suite_shape_baseline.txt` shrinks by
  deletions only.
- **Gate:** `uv run pytest --co -q`; `tests/architecture`; `tests/guards`; `validate-specs.sh`.

### P64-7 — The live smoke runs jailed by default (§7.1 decision)

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** scripts · **After:** — (wave 3 filler)

- **Trigger:** ROADMAP §7.1: `scripts/smoke_workflow.py` ~1519 (`sandbox: str = "off"`) and ~1676
  (the flag), `scripts/maint/live_eval.py` ~356 default to `off`, while `docket init` turns the jail on
  where the machine can (D-67), so the default smoke runs a configuration users do not. Decided
  2026-11-03.
- **Goal:** both default to `on`; a machine without a backend gets the existing refusal
  (`_sandbox_refusal` ~1743) naming `--sandbox off` as the opt-out and exits non-zero; the usage line
  (`live_eval.py` ~12) reads `[--sandbox on|off] (default on)`.
- **Acceptance:** `--help` of both scripts shows the default `on`; a run with no flag on this machine
  prints `Sandbox: on`; `--sandbox off` prints `off`. Scripts carry no tests; the next live smoke is the
  check.
- **Gate:** `uv run ruff check scripts/`; `uv run ruff format --check scripts/`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Phases 60-62 (2026-11-03).** Left out of the cards on purpose, or found while merging:
- *`NOT_ENFORCED` wording.* "isolation off" is also what a machine with isolation on and no backend prints
  (`teams/network_posture.py`); changing it moves a golden and security-gates requirement 14. `pod_summary`
  probes the backend per row. Trigger: an operator misreads the line, or a pod list slower than 50 ms.
- *The fetch refusal for a host off the pod's list does not name the pod command.* `platform/fetch.py` ~279 says
  "add it to FETCH_ALLOWED_DOMAINS, or to the pod's fetchDomains"; P61-3's card wanted the exact `docket pod set`
  command. `platform` does not know the pod. Trigger: a hop that stops on this refusal and a person asks how.
- *`capability_missing` for a tool is "a name the role could hold".* P61-3 chose that over "a tool another member
  holds" so a deliberate `deniedTools` is not a gap. A Reviewer calling a record write it may not use now fails
  the task `capability_missing` (`tests/e2e/test_workdir_pod.py` follows).
- *PDF reading, after P62-1.* `setup check` has no line for the PDF reader (whether isolation is on is the
  only fact it needs; the recipe readiness block already says it); an encrypted PDF is refused (only the empty
  password is tried and AES needs `cryptography`); `pypdf` decodes about 30 MB/s, so a real stream bomb ends by the
  1 GiB memory limit or the deadline after ~30 s of CPU. The jail runs a copy of `pdf_extract.py` beside `in.pdf`
  because `-m docket...` fails when docket is editable. Trigger: a PDF a user needs that these refuse.
- *`pod export` drops a recipe's `needs`* (`teams/apply/write.py` ~191, the manifest built there), by design: `needs` is
  a recipe declaration, not pod state. The "search service" check is a heuristic (a declared service whose name or an
  operation name contains "search"), and the known search hosts are a constant in `teams/apply/needs.py`. Trigger: a
  recipe that needs a fact these do not cover, or a search host that is not on the list.
- *Streaming with an idle timeout.* A stall is only seen after `AGENT_LOOP_REQUEST_TIMEOUT_S`
  because a non-streamed reply sends nothing until it ends. Trigger: after P60-1, more than one
  `request_retry` per 50 requests over a week of the live home, or a turn that ends `timeout` after
  its retries.
- *A cache breakpoint at the condensed boundary.* Replayed: with P60-2's sizes, a miss would re-send
  69 % of what it re-sends without one. Trigger: after P60-2, `messages_changed` on more than 20 % of
  a real task's requests.
- *A missing workdir folder.* Not seen: `web-research`'s exists, and Tack's `workdir: null` was the
  absent field (P61-1). Trigger: a dispatch whose recorded `workDir` is gone; then the docket-owned
  default is recreated, and a declared location becomes a profile violation and a `POST /tasks` 422.
- *A network failure inside `bash`.* No deterministic signal; P61-5 states the posture. Trigger: a
  recorded hop that tried the network after its message said `none`.
- *Approvals for shell idioms.* 7 of the live home's 9 failed hops (2026-10-24..11-03, mostly before
  Phase 59) parked on `$(`, `${` or a redirect to `/tmp`. Trigger: a week after Phase 59 in which
  approvals park more than one Implementer hop in five.

**Phase 63 (planned 2026-11-03).**
- *The A2A agent card says only "Runs tasks in the X pod"* (`interfaces/http/routes/a2a.py` ~263). Trigger:
  P63-2 lands; then the card's skill reads the pod's `description`, `blueprint` and `delivers` from `pod_report`.
  One line, not a card.

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
- *Phase 59 merges and real runs (2026-11-03).* Seen while merging or in the six real runs.
  - The `bash` clamp is `max(1, int(deadline - now))`, so a hop clock of 2 s ends a clamped command at 1 s and
    the clock is not yet spent (`agent/loop_steps.py`). Round it up when a `time` stop is seen to need a
    second request.
  - Only an Implementer hop that ended `budget_exhausted` is pinned (ADR 0038 decision 2 reads wider). Trigger:
    a plan of record that needs the tree of another failed Implementer hop in the patch.
  - `--resume`'s lease still uses the pod's `turnTimeoutS` + `verifyTimeoutS` and ignores a step's `timeout`;
    the per-round claim refresh covers a live claim.
  - A `budget_exhausted` stop for a finalization reply that carried tool calls is a model misbehaviour with
    `stop_reason: token_budget`; it lands as a budget outcome. Trigger: one seen in a real trace.
  - A budget stop that entered its landing keeps the pre-landing reason: "cannot start tool-enabled task
    completion within token_budget=N ... no backend call made" (`agent/loop_budget.py`
    `prospective_budget_error`), though the landing call was made. It reads as a refusal with no call and
    quotes the 128000-token output reserve of a model with no registered cap. Trigger: an operator misreads
    one, or Tack shows the `reason` text.
  - The CLI cannot see why a task stopped: `docket task show` and `task list --json` print neither
    `failureKind` nor the hop's `budget`; they are in the HTTP task and `TASK_LIST.json`. Trigger: an
    operator asks for the limit that stopped a task from the terminal.
  - Tack's live run (2026-11-03) never reached a clean `time` stop: its request clock ran out first, as a
    transport timeout, while the loop was in its own landing. Unverified on docket's side (the landing's share of
    the clock, and whether a client's request timeout should exceed the step `timeout`). Trigger: a plan of record
    reports a `time` stop that arrived as a transport timeout, or a real run where the landing outlives its step
    clock.
  - A second implementation of a port can sit outside `src/` (the `docket-runtime` package's `Tracer`).
    Trigger: the next port-signature change sweeps `packages/` too (`rg` the method name there).
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
  Telegram `/status`.** Needs an operator-v1 inbox contract bump. Interim: `GET /pods/<p>/memory?status=pending`
  (P63-6). Trigger for an HTTP approve route: Tack asks for one.
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.

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
