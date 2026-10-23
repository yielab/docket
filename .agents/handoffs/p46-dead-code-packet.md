# P46 lane D: measure dead code and duplication, delete the spent scripts (2026-10-23)

BASE is the `plan/phase-46-structure` head named in your prompt. Every rule in
`.agents/handoffs/wave-120-worker-packets.md` applies (where you work, what you never touch,
rules, gates, return).

A parallel worker (P46-5 stage 3c) is deleting `src/docket/config.py` and touches about 50 files
in `src/` and `tests/`, plus `scripts/maint/adopt_kernel.py`, `scripts/maint/measure_kernel_adoption.py`,
`scripts/maint/measure_partial_repointers.py` and their tests and baselines. **Do not edit any
file under `src/`, `tests/` (except the new guard and baseline below), those scripts, `TODO.md`,
`ROADMAP.md`, `README.md`, `CONTRIBUTING.md` or `specs/README.md`.** Another session owns the
`DocketError` catcher; it does not concern this lane.

## Why

The maintainer's rule for the rest of Phase 46: a refactor this deep is the moment to delete
dead code and keep the tree strictly DRY. ADR 0030 deferred "dead code by fan-in (−300 to −500)"
to Phase 47; it now happens during Phase 46, card by card, so each card needs a measure that
says what in the modules it touches is dead or duplicated, and a ratchet that keeps it from
coming back. Measuring is a script (AGENTS.md: mechanical steps are scripts, not model reads).

## Work

1. **`scripts/maint/measure_dead_code.py`**, in the style of `measure_function_spans.py` and
   `measure_kernel_adoption.py` (stdlib `ast` only; `--check` against a baseline, `--write`,
   and a per-site listing flag). Two counts, each per `src/docket` module:
   - **unreferenced:** a top-level function, class, or module-level constant, or a method of a
     class, whose name appears nowhere else in `src/`, `tests/`, `scripts/`, `packages/` as an
     identifier (an `ast.Name`/`ast.Attribute`/import alias), and not as a string literal either
     (Typer `name=`, `getattr`, entry points in `pyproject.toml` and `hatch_build.py`). Exclude
     dunders, `@app.command`/Typer-registered functions, `@pytest.fixture`, names in `__all__`,
     Pydantic validators, protocol methods of a `Protocol` class, and overrides of a base-class
     method (`do_GET`, `process_request_thread`, `run`, ...). Split it into `dead` (no reference
     at all) and `test-only` (referenced only from `tests/`). Name-based matching overcounts
     live code that shares a name, so a site is dead only when *no* file names it; say this in
     the docstring.
   - **duplicate bodies:** functions in `src/` whose body, normalised (`ast.dump` with
     identifiers of locals and arguments renamed positionally, docstring dropped), is identical
     to another function's and is at least 4 statements. Group them; count groups.
   Baseline `tests/guards/dead_code_baseline.txt`, guard `tests/guards/test_dead_code.py`
   (shrink-only, like `test_function_span.py`): a count above the baseline fails, a count below
   asks for `--write`. A guard is not evidence until you have seen it fail: show it failing on a
   toy (add toy tests in the style of `tests/guards/test_kernel_adoption.py`, on a temp tree,
   never the real one).
2. **Run it on BASE and write the listing to the report, not a file in the repo**: every `dead`
   and `test-only` site and every duplicate group, `path:line name`. Check by hand five `dead`
   sites and two duplicate groups and say whether each is real (that measures the false-positive
   rate). Do not delete anything in `src/` or `tests/`; the deletions are the next lane, after
   stage 3c merges.
3. **Delete the spent one-off scripts** under `scripts/maint/` that no CI job, guard, test,
   spec or live doc calls (`git ls-files | xargs rg -l <name>`, ignoring `docs/cycles-ended/`,
   `CHANGELOG.md`, `.agents/handoffs/`): at least `remove_harness_mode.py`,
   `split_cli_registry.py`, `move_pod_report.py`, `strip_spec_changelogs.py`; check every other
   script in `scripts/` the same way and list what you kept and why (for example
   `live-dispatch-baseline.sh` is the P46-15 before/after run). One line in `CHANGELOG.md` under
   the unreleased section. `rewrite_cli_names.py` is named by two guards: keep it unless those
   guards only exist to test it.
4. **`specs/test-framework.md`**: one sentence where the other shrink-only guards are listed,
   naming the new guard and what it counts. No version bump (the integrator bumps).

## Done when

- `measure_dead_code.py --check` passes on BASE with the baseline you wrote; the guard's toy
  tests pass and one of them shows a count above the baseline failing.
- The report has every count, the listing, the hand-checked false-positive sample, and the list
  of deleted and kept scripts.
- Gates, with `env -u VIRTUAL_ENV`: `ruff check .`, `ruff format --check .`, `mypy src`,
  `uv run pytest tests/guards`, `uv run pytest` (full default), `bash scripts/validate-specs.sh`,
  `scripts/maint/comment_lint.py --check` on touched files.
