# P46 lane E: delete the dead code and the copies lane D measured (2026-10-23)

BASE is the `plan/phase-46-structure` head named in your prompt, after P46-5 stage 3c merged
(`src/docket/config.py` no longer exists). Every rule in `.agents/handoffs/wave-120-worker-packets.md`
applies. Another session owns the `DocketError` catcher at the CLI entry and in `serve.py`'s
request handler; do not edit those.

## Why

The maintainer's standing rule for Phase 46: the refactor deletes what is dead and keeps the tree
strictly DRY. `scripts/maint/measure_dead_code.py` (lane D) lists it; this lane drives its three
counts as low as the evidence allows and lowers the baseline.

## Work, one commit per item

1. **Dead definitions.** `env -u VIRTUAL_ENV uv run python scripts/maint/measure_dead_code.py --list`.
   For each `dead` site, confirm with `git grep -w <name>` over the whole repo, then delete it.
   A spec or `refactor/target-map.toml` line that names it is amended in the same commit
   (known: `latest_trace_file` in the trace-store spec; `KEYRING_SERVICE`, `SANDBOX_DOCKER_IMAGE`,
   `REVIEWED_REPOS_FILE` in specs if they survived 3c; `keyring_secret` in the target map).
   Keep, and say why: `PLUGIN_API_VERSION` (public plugin API, security-gates spec, ADR 0010).
   The `landlock.py` ABI flag table: delete the unused flags unless a used flag's value is
   computed from them.
2. **Test-only definitions.** A definition only tests name is dead product code kept alive by
   its tests. For each: if production should call it (the test pins a real requirement whose
   live path calls a copy instead), make the live path call it and delete the copy; otherwise
   delete it and the tests that only exercise it, and say which requirement, if any, those tests
   stood for (a `specs/` requirement is amended, never silently dropped). Decide per site; list
   each decision. Expected cases: `cli/_pod.py` `_worktree_branch`/`_provision_task_worktree`/
   `build_pod`, `core/runs.py::finish_run`, `core/fleet.py::meta_read`,
   `cli/_contract.py::require_value`, `core/dispatch.py::enqueue_task` (about 300 test sites use
   it beside `enqueue_task_once`: if they mean the same thing for a fresh task, rewrite the call
   sites with a script under `scripts/maint/` run once and deleted in the same lane, then delete
   `enqueue_task`; otherwise report). Test seams the kernel owns on purpose
   (`kernel/clock.py::use_clock`, `kernel/home.py::reset_default`) stay: say so.
3. **Duplicate groups.** One owner per helper, in the lowest layer every caller may import
   (`kernel/` when it is a pure helper with no docket import, for example ISO-timestamp parsing):
   `_pod_name` (`cli/_pod.py`, `cli/_task.py`); `_epoch`/`_epoch_from_iso` (`cli/_progress.py`,
   `core/conversations.py`, `core/runs.py`, `core/trace.py`); `_parse_iso` (`core/dispatch.py`,
   `core/inbox.py`, `core/notify.py`); `_no_reserved_headers` (`core/exporter.py`,
   `core/provider.py`). Look for near-copies the measure cannot see (same body with one constant
   different): `rg` the ISO parsing and timestamp helpers across `src/` and fold them too.
   `use_clock`/`use_home` are structurally alike but set different ContextVars: fold them only
   if one generic kernel helper makes both shorter; otherwise leave them and say so.
4. **Leftovers kept for the past (D-57).** A canonical document without `kind:` still loads with
   a deprecation advisory (`core/config_docs.py`): the advisory goes, and a document without
   `kind:` is refused or every canonical fixture gains `kind:`, whichever the config-format spec
   says; amend the spec if it says neither. Report any other deprecation notice, alias or
   "legacy"/"compat"/"backward" branch in `src/` (`rg -i 'deprecat|legacy|compat|backward|old '
   src`) and delete each one that keeps a removed shape working.
5. **Baseline.** `measure_dead_code.py --write`; report each count before and after, and the
   module line count total before and after (`scripts/metrics.py` output).

## Done when

- Every remaining `dead`/`test-only` site and duplicate group is listed with the reason it stays.
- Full gates, with `env -u VIRTUAL_ENV`: `ruff check .`, `ruff format --check .`, `mypy src`,
  `uv run pytest`, `uv run pytest tests/agent`, `scripts/maint/pytest-without-sandbox.sh -q`,
  `bash tests/golden/run.sh verify-all`, `bash scripts/validate-specs.sh`,
  `scripts/gen_cli_docs.py --check`, `measure_dead_code.py --check`,
  `measure_kernel_adoption.py --check`, `scripts/maint/comment_lint.py --check` on touched files.
  No test weakened to pass; a golden changes only if it printed something false, explained line
  by line.
