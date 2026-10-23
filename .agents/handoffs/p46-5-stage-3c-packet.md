# P46-5 stage 3c: `config.py` leaves, the home's acceptance (2026-10-23)

BASE is the `plan/phase-46-structure` head named in your prompt. Every rule in
`.agents/handoffs/wave-120-worker-packets.md` applies (where you work, what you never touch,
rules, gates, return). Read the P46-5 card, not a W120 card:
`sed -n '/^### P46-5 /,/^## ◇ WAVE 120/p' TODO.md`, and ADR 0030 lines 195-205.

Another session owns the `DocketError` catcher at the CLI entry and in the HTTP handler. Do not
edit `__main__.py`, the `cli/__init__.py` entry, or the `except` blocks and error-to-status
mapping of `serve.py`'s request handler.

## Why

After stage 3b every setting is read through `current_home()`: `measure_kernel_adoption.py` counts
`config-reads 10` (all template lookups) and `config-patches 1` (a patch of `config.templates_dir`).
`config.py` is now a second copy of what `Home.from_environ` reads, kept equal only by
`tests/integration/test_home_parity.py`. ADR 0030: "`config.py` keeps only what is not a setting
(the templates directory lookups) and is renamed into `kernel/`."

## Work

1. **The template lookups move to `src/docket/kernel/templates.py`**: `templates_dir`,
   `policy_templates_dir`, `recipes_dir`, `config_schemas_dir` and the three
   `*_TEMPLATES_DIR` paths. They resolve the `templates/` directory that ships in the wheel
   (`src/docket/templates/`), so the path is computed from the kernel module's own location.
   `user_recipes_dir` and every other function or constant in `config.py` that is not a template
   lookup: if `Home` already carries it, callers use `Home`; if not, it is a `Home` field or
   property now (paths derive from `root`) or, if it is not a setting (for example `META_FILE`,
   `DEFAULT_MODEL`), it moves to the one module that owns its meaning. Say where each landed.
   Add the new kernel file to `packages/docket-runtime/hatch_build.py`'s kernel list; it imports
   nothing from `docket` (`tests/guards/test_kernel_is_a_leaf.py`).
2. **`src/docket/config.py` is deleted**, with every `import docket.config` / `from docket
   import config` in `src/`, `tests/`, `scripts/` and `packages/`. No re-export, no alias.
   `tests/guards/test_config_single_owner.py` names `config.py` as the one owner of the
   environment: make it name `kernel/home.py` (`Home.from_environ`) and keep its claim.
3. **Delete what only existed to keep two sources equal**, with any baseline file and spec text
   that names them: `tests/integration/test_home_parity.py`, `tests/guards/test_partial_repointers.py`
   and its baseline and measurer (`scripts/maint/measure_partial_repointers.py` if that is its
   name), `tests/guards/test_docket_home_repointer.py` (its subject, `repoint_docket_home`, is
   gone). `specs/test-framework.md` (around line 148) describes the repointer guard: rewrite it to
   describe the `use_home` isolation and its guard `tests/guards/test_docket_home_isolation.py`.
4. **The codemod's home rules are spent.** In `scripts/maint/adopt_kernel.py` delete
   `config-reads`, `config-patches` and `repointers` and their helpers that nothing else uses,
   with their toy tests in `tests/guards/test_adopt_kernel.py`. In
   `scripts/maint/measure_kernel_adoption.py` delete the `config-reads`, `config-patches` and
   `repointers` counts and their baseline lines (`tests/guards/kernel_adoption_baseline.txt`):
   with `docket.config` gone, an import of it fails, which is a stronger guard than a count of 0.
   Report the module line counts before and after.
5. **The acceptance test from the card**: a new test runs two `use_home` blocks with different
   roots, in the same process, does real docket work in each that writes files (for example
   enqueue a task and append an audit entry), and asserts that the two sets of files are
   disjoint and each lies under its own root. Put it by lane (`tests/integration/`). RED first is
   not possible for a new property; instead show it fails when one block is replaced by a bare
   call (say how you checked).
6. **CONTRIBUTING, README, docs**: report every line outside `docs/cycles-ended/` and
   `CHANGELOG.md` that still names `config.py`, `docket.config` or `DOCKET_HOME`-derived
   constants. Do not edit CONTRIBUTING/README (integrator-owned); edit `docs/` prose and specs.
   `CHANGELOG.md`: one line under the unreleased section that `docket.config` is gone and settings
   come from `docket.kernel.home`.

7. **Dead code and duplication this stage leaves behind (standing rule for Phase 46: a moved or
   rewritten module keeps no unreferenced definition and no second copy of a helper).**
   - Every `Home` field or property that nothing in `src/` reads once `config.py` is gone is
     deleted, with the environment variable `Home.from_environ` reads for it and every spec or
     doc line that names that variable. A field read only by tests is dead too: delete it and the
     tests that only exercise it. List each one.
   - `Home.from_environ` parses each variable kind (int, float, optional int, path) through one
     helper per kind; `config.py::_optional_int_env` and any copy of it in `home.py` become that
     helper or go. No second parser of the same shape anywhere in `src/` (`rg 'os.environ.get\('`).
   - What the stage 3b rules left in `tests/`: `with MonkeyPatch.context() as mp:` blocks whose
     `mp` is never used (drop the context, keep the body), `monkeypatch` parameters no longer used,
     fixtures in `tests/conftest.py` and per-directory `conftest.py` files that no test requests
     (`rg -w <name> tests`), helpers in `tests/` with no caller. Report the counts.
   - `x._cfg.NAME`/`serve.cfg.NAME` alias chains the rule missed: none may remain.
   Every deletion is justified by an `rg` that shows no caller; do not delete anything reached
   only through a string (Typer command names, `getattr`, entry points) without saying so.

## Done when

- `rg -n 'docket\.config|from docket import config' src tests scripts packages` returns nothing.
- `measure_kernel_adoption.py --check` and `adopt_kernel.py --check` pass.
- Full gates: `ruff check .`, `ruff format --check .`, `mypy src`, `uv run pytest`,
  `uv run pytest tests/agent`, `scripts/maint/pytest-without-sandbox.sh -q`,
  `bash tests/golden/run.sh verify-all`, `bash scripts/validate-specs.sh`,
  `scripts/gen_cli_docs.py --check`, `scripts/maint/comment_lint.py --check` on touched files.
  All with `env -u VIRTUAL_ENV`. The runtime package builds:
  `env -u VIRTUAL_ENV uv build packages/docket-runtime -o "$d"` in a mktemp dir, and its wheel
  contains `docket/kernel/templates.py`.
