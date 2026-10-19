# Wave 118 worker packet — Phase 45, P45-3 (D-65, ADR 0029 point 3)

Coordinator: the session that ran Wave 117 on 2026-10-19. **Base commit: the commit that opened
Wave 118 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-118-worker-packets.md`),
which carries the Wave 117 rollup (P45-1 prepare, P45-4 approvals as a set). One card, one
worker, one worktree (`../rack-cli-wt/w118-p45-3`, branch `w118-p45-3`). The card (`python3
.agents/skills/docket-roadmap/scripts/card_packet.py P45-3`) is the contract; this file is the
map. Symbols were located at the base and drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bumps |
| --- | --- | --- |
| P45-3 | Sonnet | `pod-dispatch.spec.md` 6.60.0, `operator-api.spec.md` 6.1.0, `operator-loop.spec.md` 1.11.0, `pod-blueprints.spec.md` 1.36.0, `security-gates.spec.md` 0.65.0 |

P45-2 (limits from `/models`) may run beside you later; it owns `edges/adapters/llm.py`,
`core/provider.py`, `core/agent_loop.py`, `templates/providers/`, `cli/_provider.py`. Do not edit
those.

## 0. Rules

**Exactly §0 of [wave-117-worker-packets.md](wave-117-worker-packets.md)** (which applies §0 of
wave-98 with its substitutions), with `w118` in place of `w117`.

**One more rule: never write the word `prill` anywhere** (code, spec, test, commit). The card's
default list names `prill.yaml`; that is a private project's file and stays out of the defaults.
Leave it out; a team adds it with `protects:`. Mention the omission in your return.

## P45-3 — a change that edits its own check goes to a person (Sonnet)

- New module `core/protected_paths.py`: the default patterns (lockfiles from
  `core/prepare.py::LOCKFILES`, `package.json`, `pyproject.toml`, `Cargo.toml`, lint/type/test
  configuration such as `.eslintrc*`, `eslint.config.*`, `tsconfig*.json`, `vitest.config.*`,
  `jest.config.*`, `ruff.toml`, `setup.cfg`, `tox.ini`, `pytest.ini`, `mypy.ini`, `.docket/**`,
  `.github/workflows/**`; state the exact list in `security-gates.spec.md`), the team's `protects:`
  (a list in `pod.yaml`, adds only, applied as a pod setting the same way P45-1's `prepare` is:
  follow `rg -n prepare src/docket/core/pod.py src/docket/core/pod_apply.py`), and every tracked
  file a reviewed command names (a path-like token of a `RunItem.runs` that is a tracked file at
  the codebase root; pure function over the items and `git ls-files`).
- Check: in `core/dispatch.py::_run_pipeline`, on the path that ends a task `done` (re-locate
  where `result.status = "done"` is set), run `git diff --name-only <baseCommit>..<branch>` in the
  task worktree (the worktree record carries both; use an existing git helper in
  `edges/adapters/system.py` or add one there). Any protected match parks the task
  `waiting_approval` with an approval of kind `check_changed` and `task["checkChanged"] = [paths]`,
  whatever the profile, lights-out included. Reuse the existing approval machinery
  (`core/approval.py`, `resolve_waiting_approval_detail`): grant -> `done`, deny -> `failed`
  with `failureKind: "check_changed"`. Both `docket task approve|deny` and the HTTP approval routes
  must work; audit entries carry their channel as they already do. Inbox and notify show it as
  they show any pending approval (check `core/inbox.py` renders the paths, else add them there).
- Digest: `core/reviewed_repos.py::_digest` includes the blob id (`git rev-parse HEAD:<path>` or
  `git hash-object`) of each file a command names, so `pod update` and `docket run` ask again after
  such a file changes. `_digest` must stay a function of the items plus the codebase; update its
  callers (`review_code`, `is_reviewed`, `remember`) without changing the P45-4 per-pod shape.
  Every existing approval is asked once more (D-57; say so in your CHANGELOG line).
- Rides along: `_pin_hop_tree` cuts the commit subject at a word boundary; `_run_group_node`
  keeps the inner `failure_kind` (a budget stop in a group says `budget`); delete the dead
  `inPlace` key read in `_ensure_task_worktree` (and any writer or test of it, D-57);
  `security-gates.spec.md`'s stale `.env\b.*write` paragraph is corrected to what the code does.
- `SERVE_API_VERSION` stays `"6"` (unreleased; `checkChanged` and the new `failureKind` are
  additive to it). Say so in `operator-api.spec.md` 6.1.0.
- Tests (use a real temp git repo for the diff; stub the model with the existing fake drivers in
  `tests/unit/core/test_dispatch*`; find one that runs a pipeline to `done` with
  `rg -n 'status == "done"' tests/unit/core`): RED is the lights-out task that edits
  `package.json` ending `done`. Oracles: task record (`status`, `checkChanged`, `failureKind`),
  the approval record's kind, the audit entries with channel; a task editing `scripts/check.sh`
  behind gate `bash scripts/check.sh` parks; a task editing only `src/` ends `done`; the digest
  changes when the named file's content changes and not otherwise.
- Gates: §0, including `tests/integration/test_escape_matrix.py` and goldens.
