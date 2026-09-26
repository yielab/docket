# Wave 38 worker packets — Phase 26 batch A (D-42)

Coordinator: the session that opened Phase 26. Base commit: `ed965e5` (P26-1 merged).
One card, one Sonnet worker, one isolated worktree each. Merge order: any; no batch-A card
depends on another. Batch B (P26-4, P26-19) starts only after batch A merges (shared
`core/dispatch.py` / `cli/_pod.py` surface).

Rules that have cost this project time (apply to every packet):
- **Never `git stash`.** Set work aside with a WIP commit on your branch instead.
- Run tests and goldens with `env -u VIRTUAL_ENV uv run ...` — a worktree inherits the parent's
  `VIRTUAL_ENV` and it points at the wrong venv.
- For any live/CLI run, set `DOCKET_HOME` to a fresh temp dir; never touch `~/.docket`.
- RED test first: see it fail on the base for the stated reason before implementing.
- Spec-first: update the owning spec section + its changelog (version bump) in your branch.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CONTRIBUTING.md`,
  `specs/README.md` (index rows are integrator-owned), `.agents/`, `internal-docs/`,
  anything under `docs/` except `docs/commands.md` regeneration when your card changes help
  text (`uv run python scripts/gen_cli_docs.py`).
- Commit style: `Type: description`, ASCII subject, detailed body, **no AI/Co-Authored-By
  trailer of any kind**.
- Focused gates while iterating; before handoff: `env -u VIRTUAL_ENV uv run ruff check . &&
  env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src` plus
  your focused tests, `bash scripts/validate-specs.sh`, and
  `env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <touched .py>`.
  The integrator runs the full suite, goldens, agent lane and metrics per batch — a card
  branch failing `scripts/metrics.py --check` is expected (it adds tests).
- Return a compact delta (decision, files+functions changed, tests run with outcomes,
  unresolved risk, follow-ups). No raw logs, no full diffs.

## P26-2 — the system prompt never drops state silently
- Card: `python3 .agents/skills/docket-roadmap/scripts/card_packet.py P26-2`
- Owns: `src/docket/core/identity.py` (`_runtime_workspace_context`, `_visible_truncate`,
  `system_prompt_for_agent` and helpers), the trace call site in `core/agent_loop.py`,
  `specs/functional/agent-loop.spec.md` req. 30 + changelog, `tests/unit/core/test_identity.py`
  (and the agent-loop unit file only if the trace assertion must live there).
- Do NOT touch: `core/dispatch.py`, archetype templates, `CONTEXT_TOKEN_BUDGET` semantics.
- Trace event name: `prompt_composed`, one per composition, payload listing each section with
  bytes and full|truncated|omitted. Protected order: runtime contract, HEARTBEAT state, TOOLS
  are never dropped in favour of SOUL; oversized SOUL is visibly truncated first; every
  omission leaves a one-line marker in the prompt.

## P26-13 — secrets are stored once, where they are read
- Card: `card_packet.py P26-13`
- Owns: `src/docket/cli/_keys.py` (remove the `.env` sync), `edges/adapters/system.py`
  (secret-tool store, if you choose store-support), one new check function in
  `cli/_doctor.py` (+ wiring line in `run_doctor`), `specs/functional/api-keys.spec.md`
  + changelog, `tests/unit/cli/test__keys.py`, doctor test class.
- Decision inside the card: either implement `secret-tool store` for the keyring backend or
  make `keys add` refuse under `DOCKET_SECRETS_BACKEND=keyring` with an honest message —
  pick ONE, say why in the handoff.
- `doctor --fix` removes existing workspace `.env` files.
- Do NOT touch: `core/secrets.py` lookup order, `cli/_doctor.py` functions other than yours.

## P26-16 — lifecycle hygiene, and the gates enable/disable retirement
- Card: `card_packet.py P26-16`
- Owns: `core/pod_provisioning.py` (teardown: merged-branch delete, lock-dir removal),
  the mkdir sites in `cli/_install.py` (0700) and `core/pod_provisioning.py`,
  `cli/_gates.py` (enable/disable -> removed notice), `src/docket/__main__.py` `_REMOVED`,
  the `--no-gates` branch in `cli/_install.py`, owning spec sections in
  `specs/functional/agent-lifecycle.spec.md` and `specs/functional/security-gates.spec.md`
  (+ changelogs), their unit/integration tests, Typer docstrings + regenerated
  `docs/commands.md`.
- Retirement default stands unless the maintainer objects: `docket gates enable|disable`
  becomes a removed-command notice pointing at the future `pod config set approvalMode`
  (P26-5, not yet shipped — word the notice so it does not claim the command exists yet;
  point at `docket doctor` for posture). `gates status`/`isolate`/`classes` stay.
- Branch delete: only when merged into the codebase's current branch; otherwise keep and
  print the manual command. A missing/failed `git` never fails teardown harder than today.
- Do NOT touch: `core/security.py`, `core/tools.py`.

## P26-18 — pod membership from recorded metadata, never id-string guessing
- Card: `card_packet.py P26-18`
- Owns: `core/pod.py::pod_of` (meta-first resolution; keep pure-string fallback for members
  with no meta), the membership refusal at `core/dispatch.py` (~line 1477 only — no other
  dispatch function), `specs/functional/pod-dispatch.spec.md` +
  `specs/functional/role-archetypes.spec.md` changelogs, `tests/unit/core/test_pod.py`,
  one integration test provisioning a custom role named `security-reviewer` (overlay via a
  temp `docket-roles.json`) and dispatching it to done on the fake driver
  (`tests/fakes.py::FakeDriver`).
- Reproduction to pin: `pod_of('proj-security-reviewer')` must return `proj` when that
  member's meta records pod=proj; a genuinely alien id still refuses.
- Do NOT touch: `parse_member_id`/`member_id` grammar, provisioning, `cli/`.
