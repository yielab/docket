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
> ## ▶ ACTIVE BOARD — WAVE 50 (opened 2026-09-27): Phase 30, the team lives in the repo (D-46)
>
> Wave 50 runs P30-1, P30-2, P30-3 and P30-4 in parallel (disjoint functions; merge order
> P30-2, P30-1, P30-3, P30-4), one Sonnet worker per card in an isolated worktree under one
> integrator; packets in
> [.agents/handoffs/wave-50-worker-packets.md](.agents/handoffs/wave-50-worker-packets.md).
> Wave 51 (P30-5 assets, then P30-6 README) is integrator-only and opens after the Wave 50
> rollup merges green.
>
> **☑ Phase 29 complete (2026-09-27).**
>
> **Phase 29 closed 2026-09-27** (ROADMAP D-45, [ADR 0011](docs/adr/0011-provider-catalog.md)):
> seven cards over Waves 47–49, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> What shipped: providers as `kind: provider` documents in two scopes with every table derived
> from them, verified registration and a CLI round trip, header auth and static headers,
> `Retry-After` with a ceiling, `config explain`/`doctor` coverage, `docket auth` retired.
>
> Waves 47 (P29-1, `0be9812`) and 48 (P29-5 `7bfbbe2`, P29-7 `04a0ffd`, P29-2 `d9e05f8`)
> merged 2026-09-27 with rollups after each. Wave 49 runs P29-4 and P29-3 in parallel (merge
> order P29-4, P29-3), then P29-6 once both are in; one Sonnet worker per card in an isolated
> worktree under one integrator; packets in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> Phase 29 closes when the Wave 49 rollup merges green.
>
> **☑ Phase 28 complete (2026-09-26).**
>
> **Phase 28 closed 2026-09-26** (ROADMAP D-44, [ADR 0010](docs/adr/0010-config-format-v1-and-extension-points.md)):
> eight cards over Waves 44–46, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> What shipped: the `kind` envelope and `docket validate`, short forms for policies, pipelines
> and roles over the unchanged canonical form, structured policy predicates, `on:` outcome
> routing with bounded loops, `when` skips and command steps, operator-scoped hashed predicate
> plugins, generated schemas and short-form export.
>
> Waves 44 and 45 (P28-1..P28-6) merged 2026-09-26 (rollups `ea9e354`, Wave 45 rollup after
> `5622d13`). Wave 46 runs P28-7 (predicate plugins) and P28-8 (schemas, short-form export, docs)
> in parallel; packets (Wave 46 section) in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> Phase 28 closes when the Wave 46 rollup merges green.
>
> **☑ Phase 27 complete (2026-09-26).**
>
> **Phase 27 closed 2026-09-26** (ROADMAP D-43, [ADR 0009](docs/adr/0009-per-pod-configuration-and-portable-teams.md)):
> ten cards over Waves 41–43, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-41-worker-packets.md](.agents/handoffs/wave-41-worker-packets.md).
> What shipped: pod role overlays and pod policies (`--pod`), MCP servers that declare `kind`
> and `tools`, pod `mcpServers`/`deniedTools` with live readers, the Lead's instruction as
> archetype data, `docket pod <p> apply|export` with a round-trip proof, scope labels in
> `config explain`/`doctor`. Two defects found and fixed inside the phase: pod-overlay roles were
> dropped from the roster (P27-9) and `apply` skipped policies (P27-10).
>
> **◇ WAVE 37 CLOSED (2026-09-25) — no card claimed.**
>
> **Wave 37 closed 2026-09-25** (ROADMAP D-41). A bounded triage ran the product on six surfaces
> and found twelve reproducible defects; six cards fixed them in two batches of one-card Sonnet
> workers under one integrator, archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
> [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md). Live
> evidence on the local endpoint: the journey's dispatch scene reaches `done — 3 hop(s)` with the
> reviewer's `APPROVE`, and a `cd`-prefixed production push still asks.
>
> **◇ PHASE 26 CLOSED (2026-09-26) — the configuration contract (D-42).**
>
> **Phase 26 closed 2026-09-26**, 20/20 cards over Waves 38–40, one integrator + one Sonnet
> worker per card in isolated worktrees; the full board section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-38-worker-packets.md](.agents/handoffs/wave-38-worker-packets.md).
> What shipped: fail-closed policies, visible prompt truncation with window-scaled budgets,
> `docket pod <p> config` (nine typed keys), bindable pipelines, step instructions with
> `--var`, `docket config explain`, one default model of record, registry retention,
> `INSTRUCTIONS.md` + `pod sync`, `projectInstructions`, loud doctor config errors, and three
> shipped recipes. Reasoning: [ADR 0008](docs/adr/0008-configuration-contract.md); user guide:
> [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
>
> **Follow-ups parked with named triggers** (small, none scheduled): serve.py's webhook does not
> catch a bound-pipeline `DispatchError`; `cli/_agents.py`/`cli/_install.py` carry their own copy
> of the retired HEARTBEAT-write instruction; `doctor --json` lacks the new checks; pod
> subcommand completions omit `set-verify`/`sync`; `cli-interface.spec.md` prose for
> `runs prune`/`conversations prune`.
>
> `v0.2.0-beta.3` (2026-09-18) is the latest release; the next beta stays a maintainer action.
> A card becomes claimable only when the integrator opens a planned section below and confirms its
> batching from function-level contention.
>
> **Measured, not scheduled:** `tee` is on the bash allowlist, so `echo x | tee f` writes a file
> without asking (pre-existing, not introduced by W37-C1); `docket help <command>` renders through
> `typer.testing.CliRunner`; `turnTimeoutS`/`verifyTimeoutS` gained their typed writer in
> Phase 26 (P26-4), superseding the earlier "no dedicated writer" note here. A new wave starts from bounded triage, not from this note.
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

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
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---



## ▶ WAVE 50 — ACTIVE (opened 2026-09-27): Phase 30, the team lives in the repo (D-46)

**Opened 2026-09-27 (Wave 50 active; Wave 51 queued in this section).** Six cards in two waves.
Decision, the directory, the seven best-practice rules, the amended spec rules and the verdict
table are in [docs/adr/0012-the-team-lives-in-the-repo.md](docs/adr/0012-the-team-lives-in-the-repo.md).
Worker packets: [.agents/handoffs/wave-50-worker-packets.md](.agents/handoffs/wave-50-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 29 closed at `8154676`; batching confirmed from the
function-level ownership below; the packets file records the base commit.

**Trigger (explicit request, 2026-09-27):** the front door becomes *agent teams as configuration,
your rules, in YAML*, and repository configuration files must be handled properly, to standards
and best practices. Measured on `b75a258`: `<codebase>/.docket/` is already `apply`'s and
`validate`'s default, yet `docket init` never reads it, a shipped recipe needs `init` then
`apply <wheel path>` (`config.recipes_dir()` has no consumer), `export` demands a path, nothing
records which directory a pod was configured from, a step cannot name its model, and `editRights`
is written by `to_wire` and read only by a display column.

**Test rule (ADR 0012):** one RED behavioural test per card in the module's `SUBJECT` file or the
integration file the card names; a negative case only for a fail-closed property (P30-1, P30-2);
existing tests, goldens and specs are the no-change oracle; no agent-lane tests, no guards;
goldens change only where a card lists the lines.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 50 | P30-1 ∥ P30-2 ∥ P30-3 ∥ P30-4 | `cli/_agents.py::run_init` + `_parse_add_args`, `core/pod_apply.py::resolve_recipe` (new) → P30-1; `core/pod.py::PodSettings` (two fields), `core/pod_apply.py::apply` + `::directory_digest` (new), `cli/_pod.py::_pod_export_cmd`, `cli/_config.py` → P30-2; `core/pipeline.py::Step` + `normalize_pipeline`, `core/orchestrator.py::PlannedUnit`, `core/dispatch.py::_run_hop_turn`, `core/runtime_driver.py::RuntimeDriver.run_turn`, `edges/adapters/docket_runtime.py::run_turn`, `cli/_pipeline.py` → P30-3; `core/archetypes.py`, `cli/_roles.py`, `cli/__init__.py` (roles help line), `core/config_docs.py::_load_role`, schemas → P30-4 |
| 51 | P30-5, then P30-6 | integrator: `scripts/render-doc-assets.py`, `scripts/maint/capture-doc-journey.sh`, `docs/assets/`; then `README.md`, `tests/agent/{truth,release}`, `pyproject.toml`, `mkdocs.yml`, `docs/CONFIGURATION.md`, `docs/QUICK-START-DOCKET.md` |

Every card follows the §"How to use this board" definition of done.

### P30-1 — `docket init` reads the team from the repo, or from a recipe

**Status:** IN-PROGRESS (@sonnet-p30-1) · **Size:** M · **Wave:** 50 · **Spec:** `pod-blueprints.spec.md` → 1.11.0 ("Pod manifests: apply" gains the `init` paragraph), `cli-interface.spec.md` → 1.45.0 (`docket init --recipe <name|dir>`, `--no-apply`)

**Trigger:** `cli/_agents.py::run_init` provisions from a blueprint and stops; `<codebase>/.docket/`
is read only by a later `docket pod <p> apply`; `config.recipes_dir()` has no consumer, so a
shipped recipe is two commands and a path into the wheel.

**Goal:**
- `docket init` with a present `<codebase>/.docket/`: validate every document there
  (`core.config_docs.validate_directory`) **before** provisioning; any error prints as `docket
  validate` does, exits 1, provisions nothing. After `build_pod_from_blueprint` succeeds, plan and
  apply the directory through `core.pod_apply.plan_apply`/`apply`, print the plan lines the way
  `docket pod <p> apply` does (shared renderer, never a second loop), and let `apply`'s own
  `pod.apply` audit entry stand.
- `docket init --recipe <name|dir>`: `core/pod_apply.py::resolve_recipe(name_or_dir) -> Path`
  (a directory as given, else `config.recipes_dir()/<name>`; unknown → `PodApplyError` naming
  the shipped names), then the same validate/provision/apply sequence. `--recipe` with a present
  `.docket/` exits 1 naming both sources, before provisioning. `--no-apply` provisions only and
  prints the `docket pod <p> apply` command that would apply the directory.
- The readiness rule (a callable endpoint before the first pod) is unchanged and runs first.

**Non-goals:** recording the source/digest (P30-2); `export` (P30-2); reading `.docket/` anywhere
but `init` and `apply` (ADR 0012 rule 1); multi-pod repositories.

**Owns:** `cli/_agents.py::_parse_add_args` + `::run_init`, `core/pod_apply.py::resolve_recipe`
(new function only), the two specs, `docs/commands.md` regeneration. **Forbidden:**
`core/pod_apply.py::apply`/`export_pod`, `cli/_pod.py`, `core/pod.py`.

**Acceptance:**
- Fixture: a fresh `DOCKET_HOME`, a fake endpoint, a codebase directory holding `.docket/pod.yaml`
  with `members: [reviewer]`. Action: `docket init` from that directory. Result: exit 0, the pod's
  roster (`core.dispatch.pod_full_roster`) has `reviewer`, one `pod.apply` audit entry. Oracle:
  the roster and the audit log, not the printed text.
- Negative: the same codebase with `.docket/roles/bad.yaml` carrying an unknown key. Action:
  `docket init`. Result: exit 1 naming the file and field; no pod member exists; no audit entry.
- `docket init --recipe secure-build` in a codebase without `.docket/` provisions the pod and
  applies the recipe (roster has `security-vetter`); `--recipe x` with a `.docket/` present exits
  1 before provisioning.

**RED test:** `tests/integration/test_pod_provisioning.py` (or the file that drives `run_init`
with a fake endpoint; `rg -n "run_init" tests/`): one positive, one negative as above; both fail
on the base because `run_init` never reads the directory.

**Gates:** worker gates (§0 of the packets); `init` help golden lines listed.

### P30-2 — the pod records its configuration of record; `export` defaults to it

**Status:** IN-PROGRESS (@sonnet-p30-2) · **Size:** M · **Wave:** 50 · **Spec:** `pod-blueprints.spec.md` → 1.12.0 ("apply" 6 records source and digest; "export" 1 and 3 default `<dir>`), `cli-interface.spec.md` → 1.46.0 (`pod <p> export [<dir>]`; `config explain` reports `configSource`, `configDigest`, `drift`)

**Trigger:** `core/pod.py::PodSettings` records a bound pipeline by sha256 (verified on every
dispatch) but nothing records the directory a pod was configured from; `cli/_pod.py::
_pod_export_cmd` requires a path while `apply` already defaults to `<codebase>/.docket/`.

**Goal:**
- `PodSettings.config_source` (alias `configSource`, absolute directory) and `config_digest`
  (`configDigest`, `^(|[0-9a-f]{64})$`), written only by `core.pod_apply.apply` after a plan that
  wrote at least one item; `docket pod <p> config set` refuses both keys with "written by apply".
- `core/pod_apply.py::directory_digest(directory) -> str`: sha256 over the sorted relative paths
  and bytes of the files `discover_config_paths` returns plus `plugins/*.py`; `.schemas/` excluded.
- `docket pod <p> export [<dir>]`: default `<codebase>/.docket/`; a non-empty target still refuses
  without `--force`.
- `docket config explain <agent>` (`cli/_config.py`): `configSource`, `configDigest` and `drift`
  (`yes` when the directory's digest differs, `no` when equal, `""` when no source) in `--json` and
  one line in the human view.

**Non-goals:** any reader of the digest on the dispatch path (nothing is applied without an
operator command); reconciliation or prune; `init` (P30-1).

**Owns:** `core/pod.py::PodSettings` (the two fields and the `config set` refusal), `core/
pod_apply.py::apply` + `::directory_digest` (new), `cli/_pod.py::_pod_export_cmd`, `cli/_config.py`,
the two specs. **Forbidden:** `cli/_agents.py`, `core/pod_apply.py::plan_apply` internals.

**Acceptance:**
- Fixture: a pod in a fresh `DOCKET_HOME`, a recipe directory. Action: `docket pod <p> apply
  <dir>`. Result: the pod's settings carry `configSource == <dir>` and `configDigest ==
  directory_digest(<dir>)`. Then edit one policy file in `<dir>`; `docket config explain <lead>
  --json` reports `drift: yes`. Oracle: the settings file and the JSON.
- Negative: `<codebase>/.docket/` non-empty; `docket pod <p> export` (no argument) exits 1 and
  writes nothing; with `--force` it writes and `apply` of the result plans every item `skip`.

**RED test:** `tests/integration/test_pod_apply.py` (`rg -n "export_pod" tests/`): the
apply/drift case and the export-default negative; both fail on the base because the fields do
not exist and `export` rejects a missing argument.

**Gates:** worker gates; `pod` help golden line for `export [<dir>]` listed.

### P30-3 — a pipeline step names its model

**Status:** IN-PROGRESS (@sonnet-p30-3) · **Size:** S · **Wave:** 50 · **Spec:** `pipeline-format.spec.md` → 2.10.0 ("Steps" + "Short form" gain `model`), `pod-dispatch.spec.md` → 6.22.0 (hop execution honours a step `model` for that hop only), `model-profiles.spec.md` → 2.16.0 (resolution: a step override sits above pin and policy, per hop, never persisted)

**Trigger:** `core/pipeline.py::Step` carries `retries`/`timeout`/`instructions` overrides but no
`model`; `core/dispatch.py::_run_hop_turn` always runs the member's meta model, so a team cannot
say "the review step uses the strong model" in the file that defines the team.

**Goal:**
- `Step.model: str | None` — `cheap`, `strong`, or `<provider>/<id>`; `normalize_pipeline`
  carries it through like `timeout`; `PlannedUnit.model`; `plan` prints `model=<x>` on such a step.
- `RuntimeDriver.run_turn` gains keyword-only `model: str | None = None`; the production driver
  (`edges/adapters/docket_runtime.py::run_turn`) resolves the endpoint for that model and reports
  it in the trace; `_run_hop_turn` resolves `cheap`/`strong` through `core.models_policy`'s rank
  anchors and passes a literal id as is — for that hop only, never written to `.docket-meta.json`.
- An unresolvable literal (provider absent from the catalog) is a `validate`/`plan` error naming
  the step, like an unresolvable role.

**Non-goals:** persisting the override; changing `docket profile` or `config explain` (they show
the persisted model); the 5-arg `ctx.run` test-double shape.

**Owns:** `core/pipeline.py::Step` + `normalize_pipeline`, `core/orchestrator.py::PlannedUnit`,
`core/dispatch.py::_run_hop_turn`, `core/runtime_driver.py::RuntimeDriver.run_turn`,
`edges/adapters/docket_runtime.py::run_turn`, `cli/_pipeline.py` (plan render), the three specs,
`docs/contracts/config-v1/pipeline.schema.json` regeneration. **Forbidden:** `core/agent_loop.py`,
`core/tools.py`, `core/pod.py`.

**Acceptance:**
- Fixture: a pod with a bound pipeline whose implementer step says `model: strong`, the fake HTTP
  server from `tests/integration/test_docket_driver.py`. Action: one dispatch through the
  production driver. Result: the request body's `model` is the `strong` rank anchor; afterwards
  the member's `.docket-meta.json` `model` is unchanged. Oracle: the captured request and the meta.
- `docket pipeline plan` on that file prints `model=` on the step; `validate` on `model:
  nope/x` fails naming the step.

**RED test:** `tests/unit/core/test_pipeline.py` (field + short form) and the driver case above;
both fail on the base because `Step` forbids the key (`extra="forbid"`).

**Gates:** worker gates; no golden expected to change (say so).

### P30-4 — one field says it: `editRights` retired

**Status:** IN-PROGRESS (@sonnet-p30-4) · **Size:** S · **Wave:** 50 · **Spec:** `role-archetypes.spec.md` → 1.19.0 (wire format: `editRights` accepted and dropped, never written; `deniedTools` is the only capability statement), `cli-interface.spec.md` → 1.47.0 (`roles list` columns)

**Trigger:** `core/archetypes.py::RoleArchetype.edit_rights` is validated and written by
`to_wire`, read only by `cli/_roles.py`'s list column; the registry is narrowed by `deniedTools`
alone, so two fields describe one capability and only one is applied.

**Goal:**
- Remove `edit_rights`, `EDIT_RIGHTS`, its validator and the `to_wire` key; `from_wire` pops
  `editRights` when present so every existing overlay loads. Built-ins and starter templates stop
  declaring it. `core/config_docs.py::_load_role` emits one `note:` for a file that carries it
  (the no-`kind:` deprecation mechanism). `roles list` drops the column; the `roles` help line
  and `core/blueprints.py`'s comment are reworded. Regenerate `role.schema.json` and
  `docs/commands.md`.

**Non-goals:** any other role field; the short form (already has no such key).

**Owns:** `core/archetypes.py`, `core/config_docs.py::_load_role`, `cli/_roles.py`,
`cli/__init__.py` (the `roles` help lines only), `core/blueprints.py` (comment only), the two
specs, schema + docs regeneration. **Forbidden:** `core/pod_apply.py`, `cli/_agents.py`,
`cli/_pod.py`.

**Acceptance:**
- Fixture: a wire document with `editRights: write`. Action: `from_wire` then `to_wire`. Result:
  loads; the output has no `editRights`; `docket roles add --pod p` writes an overlay without it.
  Oracle: the overlay file.
- `docket validate` on a role file carrying the key prints `ok` plus one `note:` line.

**RED test:** `tests/unit/core/test_archetypes.py`: fails on the base because `to_wire` writes
the key.

**Gates:** worker gates; `roles list`/`roles show` golden lines listed if any change.

### P30-5 — the assets show the team from the repo

**Status:** TODO · **Size:** M · **Wave:** 51 · **Spec:** none (docs assets; `docs/assets/README.md` records the capture)

**Trigger:** `docs/assets/hero.gif` was captured 2026-09-18 before Phases 26–30: its four
frames show `init`, `dispatch`, the gate and harness mode, none shows a team defined in files,
and its title reads "govern agent work".

**Goal:** one real run against the local endpoint (`scripts/maint/capture-doc-journey.sh`, new
scenes: `docket init --recipe secure-build`, `docket validate`, `docket pipeline plan`, `docket
pod <p> dispatch` to `done`, `docket audit verify`), transcribed into `scripts/render-doc-assets.py`
with a `docket` wordmark title; `hero.gif` four clean frames (recipe applied → plan → dispatch →
record), `governance.png` and `isolation.png` from the same run; `--check` passes; scene text is
what the run printed, elided with `⋯`, never reworded.

**Owns (integrator):** the renderer, the capture script, `docs/assets/`. **Acceptance:** the three
outputs regenerate reproducibly (`render-doc-assets.py --check` exit 0) and every frame is
readable at 820 px; the capture root renders as `~`.

**RED test:** none new; `tests/agent/release/test_public_release_truth.py`'s asset checks are the
oracle.

### P30-6 — README v3 on the tagline; prose tests rebuilt from it

**Status:** TODO · **Size:** M · **Wave:** 51 · **Spec:** none (D-37: the README is descriptive)

**Trigger:** the README of `b75a258` leads with governance; the maintainer's tagline is *agent
teams as configuration, your rules, in YAML* and the pitch is versatility, recipes, YAML + CLI,
open source, governance as the closing property.

**Goal:** README with H1 + tagline, one paragraph, three heroes in this order — *The team you
define* (recipe → `init`/`apply`, role and pipeline short forms, `validate`, `explain`), *The run*
(queue, dispatch, verify by exit code, verdicts, bounded rework, triggers), *The gate and the
record* — each with its asset, its limit beside it and its proving commands; quick start; "Use
something else if"; the configuration table; Known limits; Documentation. The three agent-lane
prose tests are deleted and rewritten from this README's own rules; `pyproject.toml`, the package
docstring and `mkdocs.yml` carry the tagline's short form; `docs/CONFIGURATION.md` gains "The team
lives in the repo" and the quick start starts from `.docket/`.

**Owns (integrator):** `README.md`, `tests/agent/truth/test_docs_positioning.py`,
`tests/agent/release/test_public_release_truth.py`,
`tests/agent/release/test_runtime_adapter_public_truth.py`, `pyproject.toml`, `mkdocs.yml`,
`src/docket/__init__.py`, `docs/CONFIGURATION.md`, `docs/QUICK-START-DOCKET.md`, `CHANGELOG.md`.

**Acceptance:** `pytest tests/agent` exit 0; each rebuilt test fails on the previous README;
`scripts/metrics.py --check` in sync; README under the rebuilt ratchet.
