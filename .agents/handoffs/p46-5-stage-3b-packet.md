# P46-5 stage 3b: the single codemod pass and the hand conversion (2026-10-23)

BASE is the `plan/phase-46-structure` head named in your prompt. Every rule in
`.agents/handoffs/wave-120-worker-packets.md` applies (where you work, what you never touch,
rules, gates, return). Read the P46-5 card, not a W120 card:
`sed -n '/^### P46-5 /,/^## ◇ WAVE 120/p' TODO.md`. Stage 3a is merged; its interim test helpers
are `tests/conftest.py::point_home_at` and `patch_home`.

Another session owns the `DocketError` catcher at the CLI entry and in the HTTP handler. Do not
edit `__main__.py`, the `cli/__init__.py` entry, or the `except` blocks and error-to-status
mapping of `serve.py`'s request handler. Do not edit `scripts/maint/adopt_kernel.py`,
`scripts/maint/measure_kernel_adoption.py` or their tests: if a rule is wrong, convert the site by
hand and report the rule defect.

## Why

Every reader of a `Home` value must read `current_home()`, and every test that wants its own home
must say so with `use_home`. Today `config.py` constants and `current_home()` are two sources of
the same values, kept equal by `test_home_parity.py` and by `repoint_docket_home` patching both.
This stage removes the first source from every reader, so stage 3c can move `config.py` into the
kernel with only its template lookups.

## Work, in this order, one commit per step

1. **The pass.** In your worktree only:
   `env -u VIRTUAL_ENV uv run python scripts/maint/adopt_kernel.py --write config-reads config-patches repointers`.
   It runs the three rules as three passes in that order. Commit the result alone
   (`Refactor: ...`), with the per-rule site counts in the body. The suite is expected to be red
   after this commit; do not fix anything in it.
2. **The fixtures in `tests/conftest.py`.** The autouse `_isolate_docket_home`,
   `_isolate_fleet_file` and `_isolate_audit_log` become one yield fixture that runs the test in
   `use_home(Home(tmp_path / "_autouse_docket_home"))` (keep the leaf names they use today so no
   test that names a path breaks). `repoint_docket_home`, `point_home_at` and `patch_home` are
   deleted; every caller becomes a `use_home` block or a yield fixture. `_DOCKET_HOME_PATHS` goes
   with them. A test that needs a field on top of its home uses
   `use_home(dataclasses.replace(current_home(), field=v))`.
3. **The refusals the pass left**, listed by
   `adopt_kernel.py --check --unmappable config-reads config-patches repointers`:
   - a helper whose repoint or patch outlives it (`_seed_pod`, `_seed`, `_home`, ...): make it a
     context manager or a fixture, and make its callers enter it;
   - a function that starts threads: the threads must be started with
     `docket.kernel.threads.start_thread`/`submit` (a bare `threading.Thread` in a test does not
     see the home);
   - a patch of a derived property (`audit_log`, `projects_dir`, `model_registry_file`,
     `inbox_cursor_file`, `conversations_file`, `prepare_cache_dir`, `trace_retention_s`): set the
     `_override` field if there is one, otherwise the root or the field it derives from;
   - a fixture that builds a server before the test repoints its home (`live_server`,
     `dispatching_server` in the serve tests): repoint first, then build the server, because the
     server serves the home it was built in;
   - a read inside an f-string, a name imported by name, the config module handed on as a value:
     convert by hand.
   The template lookups (`recipes_dir`, `policy_templates_dir`, `PROVIDER_TEMPLATES_DIR`,
   `EXPORTER_TEMPLATES_DIR`, `CHANNEL_TEMPLATES_DIR`, `config_schemas_dir`, `config.__file__`)
   stay on `config` and are not refusals to fix.
4. **Tests that `setenv` a `DOCKET_*` tunable and expect it to take effect** (for example
   `DOCKET_TOOL_MAX_OUTPUT_CHARS` in `test_task_restrictions`, `test_serve_task_lifecycle`,
   `test_hop_handoff_diff`): the default `Home` is built once from the environment, so either the
   test sets the field through `use_home`, or it tests `Home.from_environ` directly. Decide per
   test by what it claims, and list them.
5. **Counts.** `measure_kernel_adoption.py --write`, then report every count. Target: `config-reads
   0`, `config-patches 0`, `repointers 0`. If one cannot reach 0, list each remaining site and why.
   `tests/guards/test_partial_repointers.py` and its baseline: if the guard now counts 0, say so;
   do not delete it (stage 3c does).

## Not in this stage

Moving `config.py` into the kernel, deleting `test_home_parity.py` and the partial-repointer
guard, and the two-`use_home` disjointness test are stage 3c.

## Done when

- The full default suite, `tests/agent`, `scripts/maint/pytest-without-sandbox.sh -q` and the
  golden suite pass. A test is never deleted or weakened to pass: if a test's claim is no longer
  true, say which and why in the report.
- `measure_kernel_adoption.py --check` passes; the counts are in the report.
- Gates: `ruff check .`, `ruff format --check .`, `mypy src`, `bash scripts/validate-specs.sh`,
  `scripts/maint/comment_lint.py --check` on touched files. All with `env -u VIRTUAL_ENV`.
