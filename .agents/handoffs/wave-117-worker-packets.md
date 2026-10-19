# Wave 117 worker packets — Phase 45 (D-65, ADR 0029)

Coordinator: the session that planned Phase 45 on 2026-10-19. **Base commit: the commit that
opened Wave 117 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-117-worker-packets.md`).
One card, one worker, one worktree each; merge order P45-4, then P45-1. P45-2 waits on the
maintainer's prices decision and is not in this batch. The card (`python3
.agents/skills/docket-roadmap/scripts/card_packet.py P45-<N>`) is the contract; this file is the
map. Symbols were located at the base and drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bumps | Shared-file note |
| --- | --- | --- | --- |
| P45-4 | Haiku | `pod-blueprints.spec.md` 1.34.0, `operator-api.spec.md` 5.10.0, `cli-interface.spec.md` 2.16.0 | `serve.py`: the `POST /pods/<p>/apply` handler only; `core/pod_apply.py`: `review_decision`, `apply_directory` only |
| P45-1 | Sonnet | `pod-dispatch.spec.md` 6.59.0, `operator-api.spec.md` 6.0.0, `pod-blueprints.spec.md` 1.35.0, `trace-store.spec.md` 1.12.0, `security-gates.spec.md` 0.64.0 | `serve.py`: the task field map and `SERVE_API_VERSION` only; `core/pod_apply.py`: a new function plus the one call that adds its RunItem to `plan_apply`'s runs |

Both cards bump `operator-api` and `pod-blueprints`; the integrator merges P45-4 first and orders
the changelogs. Write your own version and changelog entry as if you were alone.

## 0. Rules for every worker

**Exactly §0 of [wave-98-worker-packets.md](wave-98-worker-packets.md)**, with `w117` in place of
`w98` in the worktree and branch names (`../rack-cli-wt/w117-p45-<n>`, branch `w117-p45-<n>`),
the base commit above, last-updated 2026-10-19 on every spec you bump, and these changes:

- mypy is `env -u VIRTUAL_ENV uv run --extra mcp mypy src`, and the CLI docs check is
  `env -u VIRTUAL_ENV uv run --extra mcp python scripts/gen_cli_docs.py --check` (without the
  extra the worktree lacks `click`/`anyio`; every Wave 116 worker hit it).
- pytest prints no summary line in this repo: the exit code is the evidence. Also run
  `scripts/maint/pytest-without-sandbox.sh -q` (the suite must pass on a host with no backend).
- D-57: nothing is kept for the past. A persisted shape you change is read in the new shape only;
  no migration, alias or fallback reader. Put the CHANGELOG line in your return.
- Never touch `TODO.md`, `ROADMAP.md`, `CHANGELOG.md`, `README.md`, `specs/README.md`,
  `docs/adr/`, or `.agents/`.

## P45-4 — approvals per codebase and team, as a set (Haiku)

- Persisted shape: `reviewed-repos.json` becomes `{"repos": {"<resolved root>": {"<pod>":
  [{"digest", "code", "date", "items"}, ...]}}}`. A file in the old one-entry shape is simply not
  found (the operator is asked once); no migration.
- Live path: `core/reviewed_repos.py` (`_key`, `lookup`, `is_reviewed`, `remember`; `_digest`
  is P45-3's in Wave 118, do not change it). Every function gains the pod. `lookup` returns the
  pair's latest approval (what `code_mismatch` diffs against); `is_reviewed` is true for any
  approved digest of the pair; `remember` appends (a digest already in the set is not duplicated)
  and audits `repo.allow` with `pod=`.
- Callers to update (re-locate with `rg -n 'reviewed_repos|_reviewed\.' src/docket`):
  `core/pod_apply.py::review_decision` and `apply_directory`, `cli/_status.py`,
  `cli/_run.py::_pick_up_repository`, `cli/_agents.py` (`run_init` path and
  `_changed_since_review`). Ride-alongs: `serve.py`'s `POST /pods/<p>/apply` handler refuses
  (400, a clear message) when the pod has no recorded codebase instead of reviewing against
  `directory.parent`; `_changed_since_review`'s hint names `teams/<pod>/` when the repository
  keeps teams (find how `repo_config_dir` decides that).
- Tests: `tests/unit/core/test_reviewed_repos.py` (or the existing file; `rg -n reviewed_repos
  tests`), the apply route tests in `tests/unit/test_serve*`, the init/review CLI tests. RED: two
  pods on one codebase approved in turn; the first pod's `review_decision` is no longer `go`.
- Oracles: `review_decision(...).status` for pod A and pod B after both approvals (`go`/`go`);
  returning to an earlier approved set is `go`; a third set is `needs_code` and its diff lists
  only the changed items; the JSON file holds both pods' lists; the audit line carries `pod=`.

## P45-1 — docket prepares the worktree it makes (Sonnet)

- New module `core/prepare.py` owns resolution, the cache and the run. Order: the task's
  `prepare` (from `POST /tasks/<pod>`), else `pod.yaml` `prepare:` (as applied into the pod's
  settings; find where applied `pod.yaml` keys land with `rg -n 'verifyCmd' src/docket/core/pod_apply.py`),
  else the lockfile table on the card. `""` / `prepare: none` turns it off.
- Call site: `core/dispatch.py::dispatch_pod`'s claim loop, after the `claimRefusal` check and
  `_resolve_task_run`, before the first hop; a failure goes through `_refuse_claimed_task(project,
  task, "prepare", <output tail>)` so no hop runs and no tokens are spent. Do **not** edit
  `_ensure_task_worktree`, `_run_pipeline`, `_finalize_task`, `_pin_hop_tree` or
  `_run_group_node` (P45-3 owns them in Wave 118). A resumed task whose worktree is already
  prepared for the same lockfile hash does not prepare again (record the hash on the task).
- Execution: isolation on -> `edges/adapters/system.py::jail_launch(roots, command, backend,
  network=True, ...)` with the worktree writable; isolation off -> the host, the same way
  `verifyCmd` runs (find it with `rg -n verifyCmd src/docket/core/dispatch.py`). The hops keep
  the pod's network setting; only the prepare launch opens it.
- Cache: `DOCKET_HOME/cache/prepare/<codebase key>/<lockfile hash>/`, built under a file lock
  (`filelock`, as `edges/store.py` uses it), linked into the worktree (symlink of the install dir,
  e.g. `node_modules`, `.venv`, `target`; state which in the spec), three entries kept per
  codebase (oldest removed). Inside the hops' jail the cache is a read-only root; add the
  escape-matrix rows the card names (`tests/integration/test_escape_matrix.py`).
- Review: a team's `prepare:` and a derived lockfile command are a `RunItem(kind="prepare", ...)`
  in `plan_apply`'s runs through one new function in `core/pod_apply.py`; do not change
  `review_decision` or `apply_directory` (P45-4 owns them). A task's own `prepare` is validated
  in `core/task_options.py` and stored on the task record before it runs.
- Wire: `serve.py` task field map gains `prepare`; `SERVE_API_VERSION = "6"`; failureKind
  `prepare` in `operator-api.spec.md`; `pod.schema.json` gains `prepare` (both copies:
  `docs/contracts/config-v1/` and `src/docket/templates/schemas/`; check whether one is
  generated from the other before editing both). Trace: one `prepare` event (command, source,
  cacheHit, seconds, exit) via `core/trace.py::trace_event`.
- Tests: a fixture repo with `package-lock.json`. Never run a real `npm ci` against the network:
  monkeypatch the launch in unit tests, and in the integration test use a fixture whose command
  is a local script that writes the install dir (record that the lockfile table maps to the real
  command in a unit test). RED: after claim the fixture worktree has no install dir. Oracles:
  task record (`failureKind`, recorded hash), the `prepare` trace event, the implementer hop
  seeing the install dir, a second task's `cacheHit: true`, `prepare: ""` skipping it, the
  jailed hop failing to write the cache.
- Gates: §0 plus `env -u VIRTUAL_ENV uv run pytest -q tests/integration/test_escape_matrix.py`
  and `bash tests/golden/run.sh verify-all`.
