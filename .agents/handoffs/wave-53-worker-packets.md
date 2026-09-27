# Wave 53–54 worker packets — Phase 31, recipes as a library and the repository's standards (D-47)

Coordinator: the session that planned Phase 31 on 2026-09-27 and activated it the same day.
**Base commit for Wave 53: the commit that opened it on `main`**
(`git log -1 --format=%h -- .agents/handoffs/wave-53-worker-packets.md`; Phase 30 and Wave 52
closed at `e3a765b`). Wave 54 bases on the Wave 53 rollup; Wave 55 is integrator-only. One card,
one Sonnet worker, one isolated worktree each. Decision, the library, the three-scope rule, the
amended spec rules and the verdict table:
[docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md](../../docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P31-<N>`) is the
contract; this file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 53 | P31-1, P31-5, P31-3, P31-4 | P31-1, P31-5, P31-3, P31-4 |
| 54 | P31-2, P31-6 | P31-2, P31-6 |
| 55 | P31-7 (integrator) | — |

## 0. Rules for every worker

- **Isolation.** One branch `p31-<N>-<slug>` in your own worktree. Never touch `~/.docket`: every
  CLI run sets `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket` (two statements: in one
  `export`, `$W` is still empty; **never override `HOME`**: it breaks uv's cache). pytest isolates
  `DOCKET_HOME` through the autouse fixture in `tests/conftest.py`. **Never call a real model
  endpoint and never probe a real vendor host**; the fake driver in
  `tests/integration/test_recipes.py` and the hermetic `init` in
  `tests/integration/test_pod_provisioning.py` are the patterns.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`; run `env -u VIRTUAL_ENV uv sync --extra mcp`
  once in your worktree first (`scripts/gen_cli_docs.py` imports `click`).
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend the
  spec requirement text and add the pre-assigned version + changelog line (newest first). 3. Write
  the RED test and see it fail on the base for the stated reason. 4. Smallest implementation.
  5. Gates.
- **Test rule (ADR 0013).** One RED behavioural test in the module's existing `SUBJECT` file (or
  the file the card names); a second only for the card's fail-closed negative case. Existing
  tests, goldens and specs are the no-change oracle. No agent-lane tests, no guards, no new test
  files unless the card names one. Docstrings at most three lines; no card ids or dates in any
  `.py` file (`scripts/maint/comment_lint.py --check` refuses them). Recipe README files and
  YAML documents carry no card ids either.
- **Rules from the repository are applied only by an operator command** (ADR 0012 rule 1, ADR
  0013 §3 rule 9). Instructions (`AGENTS.md`, skills) may be read live, screened. A card that
  finds it needs dispatch to read `.docket/` roles, policies or pipelines is out of scope: stop
  and report.
- **A credential value never enters a document, a fixture, a policy pattern or an error
  message.** A secret-shaped regex in a policy must not itself contain the literal `sk-`
  (write `sk[-_]`): the scrub step greps for it.
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints, never opens a socket, never imports `edges/adapters/toolbox.py` (only `core/tools.py`
  does; an AST test pins it). Docket-owned JSON only through `edges/store.py`. Every tool call
  through `core/tools.py::dispatch_tool`.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `docs/` except `docs/commands.md` and
  `docs/contracts/config-v1/*.schema.json` regeneration (`scripts/gen_cli_docs.py`,
  `scripts/gen_config_schemas.py`). Return the README/CHANGELOG/CONFIGURATION line you would add
  instead of writing it. Never edit `scripts/metrics.py` or `scripts/validate-specs.sh`. Never
  touch `core/agent_loop.py`, `core/policy.py`, `core/security.py`, `core/dispatch.py`,
  `core/pipeline.py`, `core/orchestrator.py`; `core/tools.py` only for P31-6's one block.
- **Goldens.** `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` stays byte-identical
  unless your packet names a case; then regenerate only that case and list every changed line
  with its reason.
- **Worker gates** before returning:

  ```bash
  env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
  env -u VIRTUAL_ENV uv run pytest -q
  env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
  bash scripts/validate-specs.sh
  env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check
  env -u VIRTUAL_ENV uv run python scripts/gen_config_schemas.py --check
  env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
  env -u VIRTUAL_ENV uv run pytest -q tests/guards
  ```

  `scripts/metrics.py --check` is expected to fail on a branch that adds tests; say so. The
  function-span ratchet (`tests/guards/test_function_span.py`, 150 lines) refuses a new function
  over the limit and `cli/__init__.py::cmd_pod` already sits exactly at it: never add a line there.
- **Commit.** One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Docs:`), ASCII,
  body says what was false and what is now true. **No AI mention, no `Co-Authored-By` trailer of
  any kind.** Before committing: `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-'`
  prints nothing (`task-`/`risk-` are false positives for `sk-`; a real `sk-` is not). Do not
  push, do not merge into `main`.
- **Return** a delta of 1,500–3,000 characters, no logs: card / branch / commit; outcome;
  user-visible behaviour; changed paths and owned functions; spec sections + one changelog line
  per spec; README/CHANGELOG/CONFIGURATION lines for the integrator; RED evidence (test id, base
  failure reason); focused tests -> result; worker gates -> pass or first failing gate; goldens
  changed; missing/failed; pending in this card; later follow-ups (locators only); contention note.

Symbols below were located at `e3a765b` and drift; re-locate every one with `rg -n` before editing.

## P31-1 — a recipe says what it brings

Branch `p31-1-recipe-summary`. Specs: `pod-blueprints.spec.md` -> 1.14.0, `config-format.spec.md`
-> 1.3.0, `cli-interface.spec.md` -> 1.49.0 (exact rule text in the card).

- **Where.** `core/pod_apply.py`: `summarize_recipe`/`RecipeSummary` new (place them right after
  `resolve_recipe`; count `roles/*.yaml|yml|json`, `policies/*.yaml|yml|json`, `plugins/*.py`,
  `skills/*/SKILL.md`, `pod.yaml` `members`/`settings` lengths, the `pipeline.yaml` (or the
  manifest's `pipeline` file) document `name` via `core.pipeline.load_pipeline`, `description`);
  `plan_apply` (`_MANIFEST_KEYS` + a type check for `description`); `apply` (move the two
  `_fleet.meta_set` calls out of the `if plan.has_changes():` block; the audit line stays
  inside); `_export_manifest` (write `description` when the Lead's meta or settings carry
  one — decide where `description` is stored: the simplest true answer is *nowhere on the pod*,
  in which case `export` cannot write it and you say so in the return; do not invent a new
  `PodSettings` key). `core/config_docs.py::PodDocument` gains `description: str | None = None`;
  run `scripts/gen_config_schemas.py` (both copies). `cli/_validate.py::run_validate`: for a
  directory target append the summary line(s). `cli/_pod.py`: extract `render_apply_header(project,
  directory, summary)` + reuse the existing plan-line loop as `render_apply_plan(plan)` if it is not
  a function yet; `cli/_agents.py::_apply_repo_config` calls both. Keep `cmd_pod` in
  `cli/__init__.py` untouched.
- **RED.** `tests/unit/core/test_pod_apply.py` (`SUBJECT` is `docket.core.pod_apply`): a class
  `TestSummarizeRecipe` with the policies-only case and the `scope:` negative;
  `tests/integration/test_pod_apply.py` (`rg -n "config_source" tests/integration/`): the all-skip
  record case.
- **Contention.** P31-5 owns `core/identity.py` and `cli/_config.py`; P31-3/P31-4 own
  `templates/recipes/`; nothing else in Wave 53 touches your files.

## P31-5 — `AGENTS.md` is read by default

Branch `p31-5-agents-md-default`. Specs: `agent-loop.spec.md` -> 1.23.0, `cli-interface.spec.md`
-> 1.50.0, `cli-json-shapes.spec.md` -> 1.13.0.

- **Where.** `core/identity.py::_project_instructions_raw` (the default branch) and a new
  `project_instruction_files(settings, root) -> tuple[tuple[str, ...], str]`;
  `cli/_config.py::_explain` (the JSON key) and the human renderer beside the `Config source:`
  line (`rg -n "Config source" src/docket/cli/_config.py`).
- **RED.** `tests/unit/core/test_identity.py`: a new class `TestProjectInstructionsDefault`
  (the default case; the explicit-list negative). Build the pod the way
  `TestComposeAgentPromptIsWindowAware` builds its fixture.
- **Contention.** P31-1 owns `cli/_pod.py`, `cli/_validate.py`, `cli/_agents.py`,
  `core/pod_apply.py`; do not touch them. `core/pod.py` is forbidden (the setting's parser is
  unchanged).

## P31-3 — policy packs

Branch `p31-3-policy-packs`. Spec: `pod-blueprints.spec.md` -> 1.15.0 (new section "The recipe
library" placed after "Pod manifests: export"; write the three team rows and your four rows; P31-4
adds its five rows in the same table — the integrator merges).

- **Where.** `src/docket/templates/recipes/{git-safety,no-egress,secrets-guard,prod-approval}/`
  (`pod.yaml` with `kind: pod`, `name`, `description` — P31-1 adds the key in the same wave, so
  `docket validate` on your branch may print an unknown-key error for `description` until the
  merge: keep it and say so; `policies/*.yaml` short form; `README.md`). The short-form policy
  fields are in `core/config_docs.py::PolicyDocument`/`PolicyWhen` and the predicate semantics in
  `core/policy.py::_predicate_matches` (`path` is `fnmatch` over the call's `path`/`file`
  argument). `appliesTo` takes role names; check `core/policy.py::normalize_policy` for whether
  a wildcard exists before assuming one, and list every pod role otherwise.
- **RED.** `tests/integration/test_recipes.py`: the three cases in the card; `policy_test` is in
  `core/policy.py`.
- **Contention.** P31-4 owns the five methodology directories and its own test file; P31-1 owns
  `core/pod_apply.py`. Do not touch `secure-build/roles/` or `pipeline.yaml` in any recipe.

## P31-4 — methodology recipes

Branch `p31-4-methodology-recipes`. Spec: `pod-blueprints.spec.md` -> 1.16.0 (the five rows in
"The recipe library"; if P31-3's section is not on your base, write the section header and
your rows).

- **Where.** `src/docket/templates/recipes/{tdd,spec-first,reflexion,dual-review,frugal}/`;
  `tests/integration/test_recipe_methodologies.py` (new). Read `pipeline-format.spec.md` "Short
  form", "Outcome routing", "Parallel groups", "Conditional steps and command steps" and
  `pod-dispatch.spec.md` "command step" before writing a pipeline; verify each with
  `core.pipeline.validate_pipeline` first. Step `instructions:` is a short-form key
  (`rg -n "instructions" src/docket/core/pipeline.py`).
- **RED.** The new file; the `FakeDriver` dispatch pattern is at the bottom of
  `tests/integration/test_recipes.py`.
- **Contention.** P31-3 owns the four policy packs and `test_recipes.py`; P31-1 owns
  `core/pod_apply.py`. Do not edit any existing recipe.

## P31-2 — `docket recipes list|show` (Wave 54)

Branch `p31-2-recipes-command`. Base: the Wave 53 rollup. Specs: `pod-blueprints.spec.md` ->
1.17.0, `cli-interface.spec.md` -> 1.51.0, `workspace-structure.spec.md` -> 1.13.0. Where and
RED in the card; register the command exactly as `cli/__init__.py::cmd_plugins` is registered;
the `completions` golden case is under `tests/golden/cases/` (`rg -ln "plugins" tests/golden/cases`).

## P31-6 — skills (Wave 54)

Branch `p31-6-skills`. Base: the Wave 53 rollup. Specs in the card. `core/tools.py`: exactly one
`registry.register(Tool(name="skill", ...))` block after `fetch`; `core/skills.py` imports
nothing from `edges/`. The prompt section goes through the same cap/report helpers
`projectInstructions` uses (`_cap_leading_section`). Audit through `core.audit.audit_log`.
