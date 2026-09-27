# Wave 50–51 worker packets — Phase 30, the team lives in the repo (D-46)

Coordinator: the session that planned Phase 30 on 2026-09-27 and activated it the same day.
**Base commit for Wave 50: the commit that opened it on `main`**
(`git log -1 --format=%h -- .agents/handoffs/wave-50-worker-packets.md`; Phase 29 closed at
`8154676`, the README rewrite landed at `b75a258`). Wave 51 is integrator-only. One card, one
Sonnet worker, one isolated worktree each. Decision, the directory, the seven best-practice rules,
the amended spec rules and the verdict table:
[docs/adr/0012-the-team-lives-in-the-repo.md](../../docs/adr/0012-the-team-lives-in-the-repo.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P30-<N>`) is the
contract; this file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 50 | P30-1, P30-2, P30-3, P30-4 | P30-2, P30-1, P30-3, P30-4 |
| 51 | P30-5, then P30-6 (integrator) | — |

## 0. Rules for every worker

- **Isolation.** One branch `p30-<N>-<slug>` in your own worktree. Never touch `~/.docket`: every
  CLI run sets `export W=$(mktemp -d) DOCKET_HOME=$W/.docket` (**never override `HOME`**: it
  breaks uv's cache). pytest isolates `DOCKET_HOME` through the autouse fixture in
  `tests/conftest.py` (`_DOCKET_HOME_PATHS`). **Never call a real model endpoint and never probe
  a real vendor host**; the fake driver in `tests/integration/test_recipes.py` and the HTTP fakes
  in `tests/integration/test_llm_port.py` are the pattern.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`; run `env -u VIRTUAL_ENV uv sync --extra mcp`
  once in your worktree first (`scripts/gen_cli_docs.py` imports `click`).
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend the
  spec requirement text and add the pre-assigned version + changelog line. 3. Write the RED test
  and see it fail on the base for the stated reason. 4. Smallest implementation. 5. Gates.
- **Test rule (ADR 0012).** One RED behavioural test in the module's existing `SUBJECT` file (or
  the integration file the card names); a second only for the card's fail-closed negative case.
  Existing tests, goldens and specs are the no-change oracle. No agent-lane tests, no guards, no
  new test files unless the card names one. Docstrings at most three lines; no card ids or dates
  in any `.py` file (`scripts/maint/comment_lint.py --check` refuses them).
- **Nothing is applied without an operator command.** Dispatch, serve, schedules and the harness
  never read `.docket/` (ADR 0012 §2 rule 1). A card that finds it needs to is out of scope: stop
  and report.
- **A credential value never enters a document, a fixture or an error message.**
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints, never opens a socket. Docket-owned JSON only through `edges/store.py`. Every tool call
  through `core/tools.py::dispatch_tool`.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `docs/` except `docs/commands.md` and
  `docs/contracts/config-v1/*.schema.json` regeneration (`scripts/gen_cli_docs.py`,
  `scripts/gen_config_schemas.py`). Return the README/CHANGELOG/CONFIGURATION line you would add
  instead of writing it. Never edit `scripts/metrics.py` or `scripts/validate-specs.sh`. Never
  touch `core/tools.py`, `core/agent_loop.py`, `core/policy.py`, `core/security.py`.
- **Goldens.** `bash tests/golden/run.sh verify-all` stays byte-identical unless your packet
  names a case; then regenerate only that case and list every changed line with its reason.
- **Worker gates** before returning:

  ```bash
  env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
  env -u VIRTUAL_ENV uv run pytest -q
  env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
  bash scripts/validate-specs.sh
  env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check
  env -u VIRTUAL_ENV uv run python scripts/gen_config_schemas.py --check
  env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
  ```

  `scripts/metrics.py --check` is expected to fail on a branch that adds tests; say so.
- **Commit.** One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Docs:`), ASCII,
  body says what was false and what is now true. **No AI mention, no `Co-Authored-By` trailer of
  any kind.** Before committing: `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail|sk-'`
  prints nothing. Do not push, do not merge into `main`.
- **Return** a delta of 1,500–3,000 characters, no logs: card / branch / commit; outcome;
  user-visible behaviour; changed paths and owned functions; spec sections + one changelog line
  per spec; README/CHANGELOG/CONFIGURATION lines for the integrator; RED evidence (test id, base
  failure reason); focused tests -> result; worker gates -> pass or first failing gate; goldens
  changed; missing/failed; pending in this card; later follow-ups (locators only); contention note.

Symbols below were located at `b75a258` and drift; re-locate every one with `rg -n` before editing.

## P30-1 — `docket init` reads the team from the repo, or from a recipe

Branch `p30-1-init-reads-the-repo`. Specs: `pod-blueprints.spec.md` -> 1.11.0 ("Pod manifests:
apply" gains the `init` paragraph: validate-before-provision, apply-after, `--recipe`, `--no-apply`,
mutual exclusion); `cli-interface.spec.md` -> 1.45.0 (`docket init` options `--recipe`,
`--no-apply`; the readiness rule stands).

- **Where.** `src/docket/cli/_agents.py::_parse_add_args` (two flags) and `::run_init` (after
  `build_pod_from_blueprint` succeeds: plan + apply through `core.pod_apply.plan_apply`/`apply`,
  printing the plan lines the way `cli/_pod.py::_pod_apply_cmd` does — call that module's
  renderer if it is a function, otherwise extract one; never duplicate the plan loop twice). The
  validation step *before* provisioning is `core.config_docs.validate_directory(dir)`: any error
  -> print each as `docket validate` does, exit 1, nothing provisioned. `core/pod_apply.py` gains
  one new function `resolve_recipe(name_or_dir: str) -> Path` (a directory path as given, else
  `config.recipes_dir()/<name>`; unknown -> `PodApplyError` naming the shipped recipe names).
  `--recipe` together with a present `<codebase>/.docket/` -> exit 1 naming both sources, before
  provisioning. `--from` stays mutually exclusive with everything (unchanged).
- **RED** (`tests/integration/test_pod_provisioning.py` or the file that already drives
  `run_init` with a fake endpoint — find it with `rg -n "run_init"`): a codebase with a valid
  `.docket/` (a `pod.yaml` with `members: [reviewer]`) -> after `docket init`, the pod's roster
  has a reviewer and one `pod.apply` audit entry exists. **Negative:** an invalid `.docket/`
  (a role with an unknown key) -> exit 1, no pod directory, no audit entry.
- **Goldens.** `init` help changes (`help` case and completions if they list flags): list lines.
- **Do not touch:** `core/pod_apply.py::apply`/`export_pod` (P30-2), `cli/_pod.py` (P30-2).

## P30-2 — the pod records its configuration of record; `export` defaults to it

Branch `p30-2-config-of-record`. Specs: `pod-blueprints.spec.md` -> 1.12.0 ("apply" 6 gains the
`configSource`/`configDigest` record; "export" 1 and 3: default `<dir>`); `cli-interface.spec.md`
-> 1.46.0 (`pod <p> export [<dir>]`; `config explain` prints `configSource`, `configDigest`,
`drift`).

- **Where.** `src/docket/core/pod.py::PodSettings`: `config_source: str = Field("",
  alias="configSource")`, `config_digest: str = Field("", alias="configDigest",
  pattern=r"^(|[0-9a-f]{64})$")`; both refused by `docket pod <p> config set` (find the settable
  key set next to `pipeline`'s handling and exclude them the same way, with a message "written by
  apply"). `src/docket/core/pod_apply.py`: new `directory_digest(directory: Path) -> str` (sha256
  over sorted relative paths + file bytes of the files `discover_config_paths` returns plus
  `plugins/*.py`; `.schemas/` excluded); `apply()` writes both fields after a plan that wrote at
  least one item. `src/docket/cli/_pod.py::_pod_export_cmd`: `<dir>` optional, default
  `_pod_apply_default_dir(project)`; the non-empty refusal stands. `src/docket/cli/_config.py`:
  the explain report gains `configSource`, `configDigest`, `drift` (`"yes"`/`"no"`/`""` when no
  source), human view one line under the pod settings.
- **RED** (`tests/integration/test_pod_apply.py` or the round-trip file, `rg -n "export_pod"`):
  apply a directory -> `PodSettings` carries the source and the digest of that directory; edit
  one policy file in it -> `config explain --json` says `drift: yes`. **Negative:** `docket pod
  <p> export` with no argument and a non-empty `<codebase>/.docket/` exits 1 without `--force`.
- **Goldens.** `pod` help line for `export [<dir>]`: list lines.
- **Do not touch:** `cli/_agents.py` (P30-1), `core/pod_apply.py::plan_apply` internals beyond
  what recording needs.

## P30-3 — a pipeline step names its model

Branch `p30-3-model-per-step`. Specs: `pipeline-format.spec.md` -> 2.10.0 ("Steps" gains
`model: str | None` — `cheap`, `strong`, or `<provider>/<id>`; "Short form" carries it through);
`pod-dispatch.spec.md` -> 6.22.0 (hop execution: a step `model` is resolved through
`core.models_policy` — `cheap`/`strong` via the rank anchors, a literal id as is — and passed to
the driver for that hop only; never written to `.docket-meta.json`); `model-profiles.spec.md` ->
2.16.0 (resolution: step override, per hop, above pin and policy; `docket profile` and `config
explain` keep showing the persisted model).

- **Where.** `src/docket/core/pipeline.py::Step.model` (+ `normalize_pipeline` passthrough, same
  as `timeout`); `src/docket/core/orchestrator.py::PlannedUnit.model`; `src/docket/core/
  runtime_driver.py::RuntimeDriver.run_turn` gains a keyword-only `model: str | None = None`;
  `src/docket/edges/adapters/docket_runtime.py::run_turn` honours it (the model it resolves the
  endpoint for and reports in the trace); `src/docket/core/dispatch.py::_run_hop_turn` resolves
  and passes it (production branch; the 5-arg `ctx.run` test-double shape stays untouched);
  `cli/_pipeline.py` `plan` prints `model=<x>` on a step that has one. An unresolvable literal
  (`provider/id` whose provider is not in the catalog) is a `plan`/`validate` error naming the
  step, exactly like an unresolvable role.
- **RED** (`tests/unit/core/test_pipeline.py` for the field + short form; `tests/integration/
  test_docket_driver.py` for the hop): a pipeline whose implementer step says `model: strong`
  dispatched through the production driver against the fake HTTP server -> the request's
  `model` is the strong anchor while the member's meta model is unchanged afterwards.
- **Goldens.** `pipeline plan` output only if a golden case carries a step with `model`: none
  expected; say so.
- **Do not touch:** `core/agent_loop.py`, `core/tools.py`.

## P30-4 — one field says it: `editRights` retired

Branch `p30-4-retire-edit-rights`. Specs: `role-archetypes.spec.md` -> 1.19.0 (wire format: the
key is accepted and dropped on read, never written; `deniedTools` is the only capability
statement); `cli-interface.spec.md` -> 1.47.0 (`roles list` columns).

- **Where.** `src/docket/core/archetypes.py`: remove `RoleArchetype.edit_rights`, `EDIT_RIGHTS`,
  the validator and the `to_wire` key; `from_wire` pops `editRights` if present. The five
  built-ins and the starter templates stop declaring it. `src/docket/core/config_docs.py::
  _load_role`: a document carrying `editRights` loads with one `note:` line (the same mechanism
  the no-`kind:` deprecation uses). `src/docket/cli/_roles.py`: drop the column; `cli/__init__.py`
  roles help line. Regenerate `docs/contracts/config-v1/role.schema.json` and `docs/commands.md`.
  `core/blueprints.py`'s comment that mentions `editRights` is reworded.
- **RED** (`tests/unit/core/test_archetypes.py`): a wire document with `editRights: write` loads,
  `to_wire()` has no `editRights`, and the pod overlay written by `roles add --pod` carries none.
- **Goldens.** `roles list`/`roles show` cases if any print the column: list lines.
- **Do not touch:** `core/pod_apply.py`, `cli/_agents.py`, `cli/_pod.py`.
