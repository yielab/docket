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
> ## ▶ ACTIVE BOARD — WAVE 53 (Phase 31, D-47) · Phase 30 complete 2026-09-27
>
> **Phase 30 closed 2026-09-27** (ROADMAP D-46, [ADR 0012](docs/adr/0012-the-team-lives-in-the-repo.md)):
> seven cards over Waves 50–51, four Sonnet workers in parallel then the integrator; the section
> is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and
> packets stay in [.agents/handoffs/wave-50-worker-packets.md](.agents/handoffs/wave-50-worker-packets.md).
> What shipped: `docket init` validates and applies a repository's `.docket/` (or `--recipe`),
> `apply` records the configuration of record and `config explain` reports drift, `export`
> defaults to the repo, a pipeline step names its model, `editRights` is retired, the assets were
> re-captured from one real run, the README leads with "agent teams as configuration, your rules,
> in YAML" with its prose tests rebuilt from it, and the real run's defect (a recipe's role
> resolving to the compiled-in default on a local fleet) is fixed.
>
> Phase 31 (D-47, [ADR 0013](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md))
> opened 2026-09-27 on an explicit request; its cards are the active section below. The two follow-ups parked at the close (`load_role_file`'s `is_short` heuristic and
> `docket init`'s member count) were closed 2026-09-27 in Wave 52, together with
> `docket pod <p> apply <name>` and the newcomer docs pass (see the roadmap changelog). Nothing
> is parked.
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

## ▶ WAVE 53 — ACTIVE (opened 2026-09-27): Phase 31, recipes as a library and the repository's standards (D-47)

**Opened 2026-09-27.** Seven cards in three waves. Decision, the library, the three-scope rule,
the amended spec rules and the verdict table are in
[docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md).
Worker packets: [.agents/handoffs/wave-53-worker-packets.md](.agents/handoffs/wave-53-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 30 and Wave 52 closed at `e3a765b`; batching confirmed
from the function-level ownership below; the packets file records the base commit.

**Trigger (explicit request, 2026-09-27):** recipe handling that is robust, extensible and
maintainable; example recipes for the methodologies practised in autonomous-agent orchestration;
stronger policy and pipeline recipes; `AGENTS.md` and skills so the product extends under the
standards. Measured on `e3a765b`: every recipe part is already optional in
`core/pod_apply.py::plan_apply`, yet nothing derives or prints what a directory brings, `pod.yaml`
has no `description`, the only listing of names is `resolve_recipe`'s error text, the three
shipped recipes are all whole teams, `apply` records `configSource` only from a directory that
changed something, the recipe policies match prose where `tool`/`path` predicates exist unused,
`AGENTS.md` is read only when an operator names it, and the prompt has no skills section.

**Test rule (ADR 0013):** one RED behavioural test per card in the module's `SUBJECT` file or the
integration file the card names; a negative case only for a fail-closed property (P31-1, P31-5,
P31-6); existing tests, goldens and specs are the no-change oracle; no agent-lane tests, no
guards; goldens change only where a card lists the lines.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 53 | P31-1 ∥ P31-5 ∥ P31-3 ∥ P31-4 | `core/pod_apply.py::summarize_recipe` (new) + `::apply` (record on every validated apply) + `::_export_manifest` + `_MANIFEST_KEYS`, `core/config_docs.py::PodDocument`, schemas, `cli/_validate.py`, `cli/_pod.py::_pod_apply_cmd`, `cli/_agents.py::_apply_repo_config` → P31-1; `core/identity.py::_project_instructions_raw`, `cli/_config.py::_explain` → P31-5; `templates/recipes/{git-safety,no-egress,secrets-guard,prod-approval}/`, the two existing policy files, `tests/integration/test_recipes.py` → P31-3; `templates/recipes/{tdd,spec-first,reflexion,dual-review,frugal}/`, `tests/integration/test_recipe_methodologies.py` (new) → P31-4 |
| 54 | P31-2 ∥ P31-6 | `core/pod_apply.py::resolve_recipe` + `::list_recipes` (new), `config.py::user_recipes_dir` (new), `cli/_recipes.py` (new), `cli/__init__.py` (one command), `completions` golden → P31-2; `core/skills.py` (new), `core/identity.py` (skills section), `core/tools.py` (one `skill` registration), `core/pod_apply.py::_plan_skills`/`_export_skills`/`directory_digest`/`summarize_recipe` (skills count), `config.py::SKILLS_DIR`, `cli/_config.py` (skills line), `templates/recipes/secure-build/skills/` → P31-6 |
| 55 | P31-7 | integrator: `scripts/gen_recipe_docs.py`, `docs/recipes.md`, `.github/workflows/ci.yml`, `templates/recipes/{tdd,spec-first}/skills/`, `docs/CONFIGURATION.md`, `docs/AGENT-TEAMS.md`, `docs/QUICK-START-DOCKET.md`, `docs/README.md`, `mkdocs.yml`, `README.md`, `tests/agent/{truth,release}`, `CHANGELOG.md`, rollups |

Every card follows the §"How to use this board" definition of done.

### P31-1 — a recipe says what it brings

**Status:** TODO · **Size:** M · **Wave:** 53 · **Spec:** `pod-blueprints.spec.md` → 1.14.0 ("Pod manifests: apply" req 1 key set gains `description`; req 6 records source and digest on every validated apply; new req 9 "Recipe summary"), `config-format.spec.md` → 1.3.0 (manifest key set), `cli-interface.spec.md` → 1.49.0 (`validate` summary line; `apply`/`init --recipe` header)

**Trigger:** `core/pod_apply.py::plan_apply` accepts a directory with only `policies/`, only
`roles/` or only `pipeline.yaml`, but nothing derives or prints what a directory contains;
`_MANIFEST_KEYS` has no `description`; `apply` writes `configSource`/`configDigest` only under
`if plan.has_changes()`, so a second, all-`skip` apply of an identical directory at another path
leaves the record pointing at the first.

**Goal:**
- `core/pod_apply.py::summarize_recipe(directory: Path) -> RecipeSummary` (frozen dataclass:
  `roles`, `policies`, `plugins`, `skills`, `members`, `settings` as `int`; `pipeline` as
  `str` — the pipeline document's `name`, or `""`; `description: str`), pure, reads only; `skills`
  counts `skills/*/SKILL.md` directories so P31-6 changes no signature. `RecipeSummary.render()`
  returns one line: `roles 1 · policies 1 · members 1 · pipeline secure-build · plugins 0 · skills 0 · settings 0`
  (every count always shown, in that order).
- `pod.yaml` accepts `description` (string; any other type refused naming the key); `_MANIFEST_KEYS`
  gains it; `core/config_docs.py::PodDocument.description: str | None`; both schema copies
  regenerated; `_export_manifest` writes it when set. A `scope:` key stays refused as unknown.
- `apply` records `configSource`/`configDigest` after every plan `plan_apply` validated, all-`skip`
  included; the `pod.apply` audit entry keeps its "only when something changed" rule.
- `docket validate <dir>` prints, after the per-file lines, `summary: <render()>` (and the
  description on its own line when set); a file target prints no summary.
- `docket pod <p> apply [<name|dir>]` and `docket init --recipe` print the same header before the
  plan (`Apply plan — <p> <- <dir>` then the description line when set, then `  <render()>`),
  through one shared renderer (`cli/_pod.py`; `cli/_agents.py::_apply_repo_config` calls it —
  this closes the parked "own loop" follow-up).

**Non-goals:** listing recipes (P31-2); the operator scope (P31-2); skills content (P31-6);
any reader of `description` on the dispatch path.

**Owns:** `core/pod_apply.py::summarize_recipe` (new), `::plan_apply` (the `description`
key), `::apply` (the record), `::_export_manifest`, `_MANIFEST_KEYS`; `core/config_docs.py::
PodDocument`; `docs/contracts/config-v1/pod.schema.json` + `src/docket/templates/schemas/
pod.schema.json` (regenerated); `cli/_validate.py`; `cli/_pod.py::_pod_apply_cmd` (+ the
extracted renderer); `cli/_agents.py::_apply_repo_config`; the three specs. **Forbidden:**
`cli/__init__.py` (`cmd_pod` sits at the span limit), `core/pod_apply.py::resolve_recipe`,
`core/identity.py`, `templates/recipes/`.

**Acceptance:**
- Fixture: a directory holding only `policies/one.yaml` (a valid short-form policy). Action:
  `summarize_recipe(dir)`. Result: `policies == 1`, every other count `0`, `pipeline == ""`;
  `render()` is the exact line above with those numbers. Oracle: the dataclass.
- Fixture: a pod in a fresh `DOCKET_HOME`; directory A applied (writes); directory B, byte-identical
  content at another path. Action: `apply(plan_apply(p, B))`. Result: every item `skip`, no new
  `pod.apply` audit line, and `PodSettings.load_for(p).config_source == str(B.resolve())`.
  Oracle: the settings file and `read_audit`.
- Negative: `pod.yaml` with `scope: policies` — `plan_apply` raises `PodApplyError` naming
  `scope`, nothing written.
- `docket validate <recipe dir>` output ends with the `summary:` line; `docket pod <p> apply
  secure-build --dry-run` prints the header, the description line and the summary before
  `[add] role: security-vetter`.

**RED test:** `tests/unit/core/test_pod_apply.py` (the summary case; fails on the base:
`summarize_recipe` does not exist) and `tests/integration/test_pod_apply.py` (`rg -n
"config_source" tests/integration/`; the all-skip record case fails on the base because the
record stays at A). The negative rides in the unit file.

**Gates:** worker gates; no golden changes expected (`validate`/`apply` output is not a golden
case; confirm with `rg -n "Apply plan" tests/golden/`).

### P31-2 — `docket recipes list|show`, and the operator's own recipes directory

**Status:** TODO · **Size:** M · **Wave:** 54 (after P31-1) · **Spec:** `pod-blueprints.spec.md` → 1.17.0 ("apply" req 8 resolution order gains the operator scope; new "Recipe listing" requirement), `cli-interface.spec.md` → 1.51.0 (`docket recipes list [--json]`, `docket recipes show <name|dir> [--json]`), `workspace-structure.spec.md` → 1.13.0 (`~/.docket/recipes/`)

**Trigger:** `core/pod_apply.py::resolve_recipe` knows two places (a path, the wheel); the only
enumeration of names is its error text; ADR 0013 §1 rule 5 records why a listing is now due.

**Goal:**
- `config.py::user_recipes_dir() -> Path` (`DOCKET_HOME / "recipes"`); `resolve_recipe` order: a
  directory path as given, else `user_recipes_dir()/<name>`, else `recipes_dir()/<name>`; the
  error names both scopes' names (`operator: a, b; shipped: ...`).
- `core/pod_apply.py::list_recipes() -> list[RecipeInfo]` (`name`, `scope` in `operator|shipped`,
  `directory`, `summary: RecipeSummary`), nearest-wins by name, sorted by name.
- New `cli/_recipes.py::run_recipes(args) -> int`: `list` (table: NAME, SCOPE, KIND derived —
  `team` when members and a pipeline, `policies` when only policies, `pipeline` when a pipeline and
  no policies, else `mixed` — plus DESCRIPTION; `--json` a list of objects with the summary fields),
  `show <name|dir>` (description, scope, directory, summary, the README body when present);
  unknown name exits 1 with the resolution error. Registered in `cli/__init__.py` exactly as
  `plugins` is (one `@app.command` block); `completions` golden gains the command; `docs/commands.md`
  regenerated.

**Non-goals:** installing, removing or fetching recipes; `docs/recipes.md` (P31-7); any change to
`apply`'s plan or record.

**Owns:** `config.py::user_recipes_dir` (new), `core/pod_apply.py::resolve_recipe` + `::list_recipes`
(new) + `RecipeInfo` (new), `cli/_recipes.py` (new), `cli/__init__.py` (one new command block only),
`tests/golden/cases/completions*` (the one line), `docs/commands.md`, the three specs. **Forbidden:**
`core/pod_apply.py::plan_apply`/`apply`/`summarize_recipe` internals, `cli/_pod.py`,
`core/identity.py`, `core/skills.py`.

**Acceptance:**
- Fixture: fresh `DOCKET_HOME` with `recipes/mine/policies/x.yaml` (valid) and no `pod.yaml`. Action:
  `list_recipes()`. Result: an entry `mine` with scope `operator`, `summary.policies == 1`; every
  shipped recipe present with scope `shipped`. Then `docket pod <p> apply mine --dry-run` plans
  `[add] policy: x.yaml`. Oracle: the list and the CLI output.
- Negative: `docket recipes show nope` exits 1; the message names `operator:` and `shipped:` lists.

**RED test:** `tests/integration/test_recipes.py` (the operator-scope case; fails on the base:
`list_recipes` does not exist and `apply mine` reports an unknown recipe).

**Gates:** worker gates; `completions` golden: the one added line listed.

### P31-3 — policy packs: four single-concern recipes, and the two existing policies on structured predicates

**Status:** TODO · **Size:** M · **Wave:** 53 · **Spec:** `pod-blueprints.spec.md` → 1.15.0 (new section "The recipe library": kinds and the twelve names; this card writes the section with the policy-pack rows and the three team rows, P31-4 adds the methodology rows)

**Trigger:** `core/policy.py::_predicate_matches` evaluates `tool`, `path`, `branch` and `anyOf`
over the call, yet `secure-build/policies/require-approval-secret-writes.yaml` matches the prose
`write.*\.env` and `ops-approval/policies/ops-approval-high-risk.yaml` matches text only; no
shipped recipe is a policy pack, so a reader cannot see that one can be.

**Goal:** four recipes under `templates/recipes/`, each `pod.yaml` (`kind: pod`, `name`,
`description`), `policies/*.yaml` in the short form, and a README that opens with what the pack
adds, its threat model in three sentences, the `docket policies test` command that shows it
firing, and "Undo":
- `git-safety`: block `git push --force|-f`, `git reset --hard`, `git clean -f*`, `git branch -D`,
  `git checkout -- .`, `git config --global`; ask on `git push` to `main|master|production|prod`
  (branch-aware where the `branch` predicate applies); every role that can run `bash`.
- `no-egress`: ask on `bash` calls naming `curl|wget|nc|ncat|ssh|scp|rsync|ftp`; ask on
  `pip install|pipx|uv add|uv pip install|npm install|npx|pnpm add|yarn add|cargo add|go get`;
  ask on `tool: fetch`. README states that this pack closes by policy what `bash` leaves open
  (security-gates D-23), and what it does not close (interpreters).
- `secrets-guard`: block `write`/`edit` whose `path` matches `**/.env*`, `**/*.pem`, `**/*.key`,
  `**/id_rsa*`, `**/*.p12` (one `anyOf`); block text carrying a private-key header, an AWS access
  key id shape or a `sk[-_]` bearer shape on `toolCall`; `redact` the same shapes `on: output`.
  Every pod role.
- `prod-approval`: the existing ops policy generalised to `implementer` and `operator` — ask on
  `kubectl apply|delete|replace|rollout`, `helm upgrade|install`, `terraform apply|destroy`,
  `docker push`, `npm publish`, `fly deploy`, `vercel --prod`, `heroku promote`, `git push` to a
  production-shaped branch.
- `secure-build`'s policy: `anyOf` of `{tool: write, path: '**/.env*'}`, `{tool: edit, path:
  '**/.env*'}`, `{matches: <private-key header>}` — ask; `ops-approval`'s policy: keep `matches`
  but add `tool: bash`. Both READMEs updated to say why.
- `tests/integration/test_recipes.py`: `test_every_recipe_has_a_pipeline_and_a_readme` becomes
  "a README and at least one of pipeline / roles / policies / members"; the parametrised
  validation cases already cover the new files; new RED: applying `git-safety` onto a lean
  fixture pod plans only `policy` items, and after `apply`, `core.policy.policy_test`
  (`rg -n "def policy_test" src/`) on `pre_tool_call` for `implementer` with
  `git push --force origin main` returns `block`; `secrets-guard` on a `write` to `.env` returns
  `block` and on a plain `write` to `README.md` returns `allow`.

**Non-goals:** any change to `core/policy.py`; new predicate keys; pipelines (P31-4); the
`pre_output` redaction engine (use what `then: redact` already does; if `on: output` with
`redact` is refused by `validate_policy`, drop that rule and say so in the return).

**Owns:** the four new recipe directories, the two existing policy files and their READMEs,
`tests/integration/test_recipes.py`, `pod-blueprints.spec.md` (the new section only).
**Forbidden:** `core/policy.py`, `core/pod_apply.py`, every other recipe directory,
`tests/integration/test_recipe_methodologies.py`.

**Acceptance:** the fixture/action/result triples above; every new policy file passes
`validate_policy` (`test_recipe_policy_validates` parametrises over it); `docket policies test
pre_tool_call implementer 'git push --force origin main'` prints `block` after `apply git-safety`
on a throwaway `DOCKET_HOME`.

**RED test:** the three new cases in `tests/integration/test_recipes.py`; they fail on the base
because the directories do not exist.

**Gates:** worker gates; no goldens.

### P31-4 — methodology recipes: five pipelines that are the practice

**Status:** TODO · **Size:** M · **Wave:** 53 · **Spec:** `pod-blueprints.spec.md` → 1.16.0 ("The recipe library" gains the five methodology rows; if P31-3 has not merged, write the section with your rows and the integrator merges)

**Trigger:** the pipeline dialect carries `verify`, `verdict`, `on:` with `max`, `parallel`,
`run:`, `model:` and `settings`, and the built-in and starter roles cover reviewer, tester,
critic and writer; the only shipped pipelines are three whole teams, so the practices operators
ask for (test-first, spec-first, bounded self-critique, independent double review, a spend cap)
have no example.

**Goal:** five recipes, each `pod.yaml` (`kind: pod`, `name`, `description`, `members` limited to
the roles the pipeline needs from `docket roles list`), `pipeline.yaml` in the short form, a README
that names the practice, its source idea (one line, no citation needed), what docket's gates make
structural, and "Undo":
- `tdd`: `red: implementer` (step `instructions`: write one failing test for the task, change
  nothing else), `check-red: {run: <the verify command>}` routed `on: {pass: fail, fail: green}`
  if `validate` accepts an `on:` map on a command step (read pipeline-format "Conditional steps
  and command steps" and pod-dispatch "command step"; if not accepted, `check-red` is dropped and
  the README says why), `green: implementer` with `verify: true`, `test: tester` verdict
  `[PASS, FAIL]`. `members: [tester]`. If `run:` cannot reference the pod's own verify command, the
  literal is `python3 -m pytest -q` and the README says to edit it.
- `spec-first`: `spec: writer` (instructions: write the specification file), `approve-spec:
  critic` verdict `[APPROVE, REJECT]` with `on: {REJECT: {goto: spec, max: 1}}`, `build:
  implementer` `verify: true`, `review: reviewer` verdict `[APPROVE, REQUEST-CHANGES]` with a
  bounded route back to `build`. `members: [writer, critic, reviewer]`.
- `reflexion`: `build: implementer` `verify: true`, `critique: critic` verdict
  `[APPROVE, REQUEST-CHANGES]` with `on: {REQUEST-CHANGES: {goto: build, max: 2}}`, `test: tester`
  verdict `[PASS, FAIL]`. `members: [critic, tester]`.
- `dual-review`: `build: implementer` `verify: true`, then a `parallel` group of `review-code:
  reviewer` and `review-risk: critic`, each with its verdict gate (read "Parallel groups" for what
  a child may carry). `members: [reviewer, critic]`.
- `frugal`: `settings: {budgetUsd: 2, maxReworkCycles: 1, turnTimeoutS: 600}`; `plan: lead` with
  `model: cheap`, `build: implementer` `verify: true`, `review: reviewer` `model: cheap` verdict.
  `members: [reviewer]`.
- New `tests/integration/test_recipe_methodologies.py` (`SUBJECT = "docket.config"`, the
  `_seed_fixture_pod` pattern copied from `test_recipes.py` — import it if it is importable,
  otherwise a local copy): parametrised over the five: `plan_apply` + `apply` on a lean pod then
  `resolve_plan` leaves no step skipped; `dual-review`'s plan has one `PlannedGroup`; `frugal`'s
  plan carries three `setting` items; `tdd`'s spec routes `check-red` as declared (or has no such
  step, per the README); one `FakeDriver` dispatch of `reflexion` (the pattern at the bottom of
  `test_recipes.py`) whose critic answers `REQUEST-CHANGES` once then `APPROVE` reaches `done`
  with the rework counted.

**Non-goals:** new dialect features; changes to `core/dispatch.py`, `core/pipeline.py`,
`core/orchestrator.py`; skills (P31-7 adds them to `tdd`/`spec-first`); policy packs (P31-3).

**Owns:** the five recipe directories, `tests/integration/test_recipe_methodologies.py` (new),
`pod-blueprints.spec.md` (the five rows). **Forbidden:** every other recipe directory,
`tests/integration/test_recipes.py`, every `core/` module.

**Acceptance:** the parametrised triples above; `docket pipeline validate` and `pipeline plan`
succeed for each recipe on a throwaway `DOCKET_HOME` after `init --recipe <name>` against a
fake endpoint (`rg -n "FakeDriver\|fake endpoint" tests/integration/test_pod_provisioning.py`
shows how `init` runs hermetically).

**RED test:** the new file; every case fails on the base because the directories do not exist.

**Gates:** worker gates; no goldens.

### P31-5 — `AGENTS.md` is read by default

**Status:** TODO · **Size:** S · **Wave:** 53 · **Spec:** `agent-loop.spec.md` → 1.23.0 ("System prompt composition" req 30: the default), `cli-interface.spec.md` → 1.50.0 (`config explain` reports the project-instructions source), `cli-json-shapes.spec.md` → 1.13.0 (`projectInstructions: {files: [...], source: "set"|"default"|""}`)

**Trigger:** `core/identity.py::_project_instructions_raw` returns `""` when
`PodSettings.project_instructions` is empty, so the `AGENTS.md` a repository already keeps for
Codex, Copilot, Cursor and Claude Code reaches a docket agent only if an operator repeats its
name in a pod setting.

**Goal:**
- When the setting is unset and `project_roots[0] / "AGENTS.md"` is a file, compose it exactly as
  an explicitly named file is composed today: screened through `pre_input` as untrusted, the same
  `## AGENTS.md` heading, the same cap and `projectInstructions` report. An explicit setting
  replaces the default entirely. No root, no file, or a set list without it: byte-identical to
  today.
- `core/identity.py::project_instruction_files(settings, root) -> tuple[tuple[str, ...], str]`
  (the files and `"set"|"default"|""`), used by composition and by `cli/_config.py::_explain`,
  which gains `projectInstructions` in `--json` and one human line
  (`Project instr.:   AGENTS.md (default)` / `(set)` / `none`).

**Non-goals:** nested `AGENTS.md`; `CLAUDE.md` or any second default name; changing the cap or
the screening; the workspace's own docket-written `AGENTS.md` (a different file, unchanged).

**Owns:** `core/identity.py::_project_instructions_raw` + `::project_instruction_files` (new),
`cli/_config.py::_explain` + its human renderer, the three specs. **Forbidden:** `core/pod.py`,
`core/tools.py`, `core/skills.py`, `core/pod_apply.py`.

**Acceptance:**
- Fixture: a pod in a fresh `DOCKET_HOME`, `projectInstructions` unset, a codebase root holding
  `AGENTS.md` with a sentinel line. Action: `compose_agent_prompt(lead_id, project_roots=(root,))`.
  Result: the text carries `## AGENTS.md` and the sentinel, and the sections report names
  `projectInstructions`. Oracle: the composition.
- Negative: the same root plus `projectInstructions: CONTRIBUTING.md`. Result: the sentinel is
  absent; `## CONTRIBUTING.md` present. Oracle: the composition.
- `docket config explain <lead> --json` carries `{"files": ["AGENTS.md"], "source": "default"}`.

**RED test:** `tests/unit/core/test_identity.py` (the default case; fails on the base: the
section is empty). The negative rides in the same class.

**Gates:** worker gates; goldens unchanged (confirm `config explain` is not a golden case).

### P31-6 — skills: the Agent Skills shape, three scopes, one `skill` tool

**Status:** TODO · **Size:** L · **Wave:** 54 (after P31-1 and P31-5) · **Spec:** `agent-loop.spec.md` → 1.24.0 (req 30 gains the `skills` section; "Per-role tool narrowing" names `skill` in the built-in set), `pod-blueprints.spec.md` → 1.18.0 (`skills/` planned, applied, exported, digested, counted), `workspace-structure.spec.md` → 1.14.0 (`~/.docket/skills/`, the pod's `config/skills/`), `cli-interface.spec.md` → 1.52.0 (`config explain` skills line), `cli-json-shapes.spec.md` → 1.14.0 (`skills: [{name, scope}]`)

**Trigger:** `core/identity.py::compose_agent_prompt` composes identity, instructions, project
instructions, contract and workspace state; there is no place for a reusable, on-demand
instruction module, and `core/tools.py::build_default_registry` offers no way to read one that
lives outside the project roots. The Agent Skills shape (`skills/<name>/SKILL.md`, frontmatter
`name` + `description`, body on demand) is what the ecosystem already writes.

**Goal:**
- New `core/skills.py`: `SkillMeta(name, description, directory, scope)`;
  `parse_skill_file(path) -> SkillMeta` (YAML frontmatter between `---` lines; `name` required,
  1–64 chars `[a-z0-9-]`, equal to the directory name; `description` required, ≤1024 chars; other
  keys ignored; a violation raises `SkillError` naming the file and field);
  `discover_skills(project, codebase_root) -> dict[str, SkillMeta]` over
  `<codebase_root>/.docket/skills/`, `config.pod_config_dir(project)/skills/`, `config.SKILLS_DIR`
  (`DOCKET_HOME/skills`), nearest wins by name in that order; an invalid skill is skipped and
  audited once (`skills.invalid`), never raised into a turn.
- `core/identity.py`: after project instructions and before the runtime contract, a section
  `# Skills` listing `- <name>: <description>` per discovered skill (descriptions screened through
  `pre_input` as untrusted, the section capped to half the remaining budget and reported as
  `skills`, like `projectInstructions`), ending with one line telling the model to call the
  `skill` tool with a name for the full instructions. No skills, no section, byte-identical.
- `core/tools.py`: one new built-in `skill` (`kind="read"`, parameters `name` required, `path`
  optional) whose handler resolves the name through `core.skills.discover_skills(ctx.project,
  ctx.roots[0] if ctx.roots else None)` and returns `toolbox.read_file((skill.directory,),
  path or "SKILL.md")` — containment to the skill's own directory, output truncated like every
  tool; an unknown name is a failed call naming the known names. Denied like any tool
  (`deniedTools: [skill]`).
- `core/pod_apply.py`: `_plan_skills` (a recipe's `skills/<name>/` copied whole into the pod's
  `config/skills/<name>/`, compared by a sha256 over the directory's sorted relative paths and
  bytes: add/replace/skip), `apply` writes it (mode 0700/0600), `_export_skills` writes it back,
  `directory_digest` includes `skills/**`, `summarize_recipe` counts it.
- `secure-build` gains `skills/security-review/SKILL.md` (a review checklist the vetter can pull;
  frontmatter per the shape) so the round trip is proven on shipped data.
- `cli/_config.py::_explain`: `skills` in `--json` (`[{name, scope}]`) and one human line.

**Non-goals:** auto-loading a body by task match; `skills:` on a role; `allowed-tools`
enforcement; a `docket skills` command; reading `scripts/` for execution (a skill's script runs
only if the model runs it through `bash`, gated as ever).

**Owns:** `core/skills.py` (new) + `tests/unit/core/test_skills.py` (new, `SUBJECT =
"docket.core.skills"`), `core/identity.py` (the skills section only; P31-5's function is merged
before you start), `core/tools.py` (one `registry.register` block for `skill`; the AST test
`test_only_the_chokepoint_imports_the_handler_module` must stay green — `core/skills.py` never
imports `edges/`), `core/pod_apply.py::_plan_skills`/`_export_skills` (new) + `directory_digest`
+ `summarize_recipe` (the count) + `apply`/`export_pod` (the two calls), `config.py::SKILLS_DIR`,
`cli/_config.py` (the skills line), `templates/recipes/secure-build/skills/`, the five specs.
**Forbidden:** `core/agent_loop.py`, `core/policy.py`, `edges/adapters/toolbox.py`,
`core/pod_apply.py::resolve_recipe`/`list_recipes` (P31-2), every other recipe directory.

**Acceptance:**
- Fixture: fresh `DOCKET_HOME`, a pod, `config/skills/security-review/SKILL.md` (valid). Action:
  `compose_agent_prompt(vetter_id, project_roots=(root,))`. Result: the text carries
  `- security-review: <description>` under `# Skills` and the section report `skills`. Then
  `dispatch_tool(ToolCall("skill", {"name": "security-review"}), ctx, registry)` returns
  `ok` with the body. Oracle: the composition and the `ToolResult`.
- Fixture: the same, plus the vetter's archetype `deniedTools: [skill]`. Action: the same call
  after per-role narrowing (the pattern in `tests/unit/core/test_tools.py` for a denied tool).
  Result: a typed denial, not executed. Oracle: `ToolResult.executed is False`.
- Round trip: `apply` of `secure-build` plans `[add] skill: security-review`; `export` writes
  `skills/security-review/SKILL.md`; `apply` of the export plans `skip`; `summarize_recipe`
  reports `skills 1`.
- Negative: a `SKILL.md` whose `name` differs from its directory is skipped with one
  `skills.invalid` audit line and the prompt has no section.

**RED test:** `tests/unit/core/test_skills.py` (parse + discover), `tests/unit/core/
test_identity.py` (the section), `tests/unit/core/test_tools.py` (the tool and its denial),
`tests/integration/test_pod_apply.py` (the round trip). Each fails on the base: the module, the
section and the tool do not exist.

**Gates:** worker gates; goldens unchanged unless the tool list appears in one (`rg -n
'"fetch"' tests/golden/`); if it does, list the line.

### P31-7 — the library is documented from data; the docs and README carry the standards

**Status:** TODO · **Size:** M · **Wave:** 55 (integrator, after 54) · **Spec:** none (D-37: README and docs are descriptive); `test-framework.md` only if the generator gains a CI check the spec must name

**Trigger:** twelve recipes, two kinds of repository standard and a new tool with no page that is
generated from what ships; `docs/CONFIGURATION.md` §3.10 still describes three whole-team recipes.

**Goal:** `scripts/gen_recipe_docs.py` renders `docs/recipes.md` (one section per recipe: name,
kind, description, derived summary, apply commands, the README body) with `--check`, run in the
CI docs job beside `gen_cli_docs.py`; `tdd` and `spec-first` gain a skill each
(`skills/test-first/SKILL.md`, `skills/writing-a-spec/SKILL.md`); `docs/CONFIGURATION.md` §3.10
rewritten around the three kinds, composition and the operator scope, new §3.12 `AGENTS.md`
and §3.13 skills; `docs/AGENT-TEAMS.md`, the quick start §6, `docs/README.md` and `mkdocs.yml`
gain the page and the two standards; `README.md` gains one feature line each for the library,
`AGENTS.md` and skills, with the agent-lane prose tests rebuilt from the README; `CHANGELOG.md`
Unreleased; CONTRIBUTING gates list; the board and roadmap closed and archived.

**Owns:** everything in the Wave 55 row. **Forbidden:** `src/` except the two skills directories.

**Acceptance:** `gen_recipe_docs.py --check` passes in CI and fails when a README line is edited
without regenerating; `mkdocs build --strict` passes; the agent lane passes; the smoke on a
throwaway `DOCKET_HOME` runs `init --recipe tdd`, `recipes list`, `config explain` showing
`AGENTS.md (default)`, and a `skill` tool call in one fake-driver turn.

**RED test:** none in the default suite (docs); the agent-lane files are rebuilt.

**Gates:** the full integrator gate list (CONTRIBUTING).

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



