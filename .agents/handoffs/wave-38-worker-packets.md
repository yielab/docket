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

---

# Wave 38 batch B (opened after batch A merged at `194806b`)

Both cards touch `core/dispatch.py` and `cli/_pod.py` in DIFFERENT functions. Ownership below is
at function level and strict; a conflict is resolved by the integrator keeping both blocks.

## P26-4 — pod settings are typed, validated and writable
- Card: `python3 .agents/skills/docket-roadmap/scripts/card_packet.py P26-4`
- Owns: a new `PodSettings` Pydantic model (put it in `core/pod.py`), the Lead-meta setting
  readers in `core/dispatch.py` ONLY (`pod_budget`, `pod_max_rework_cycles`,
  `_lead_meta_timeout`, `pod_turn_timeout`, `pod_verify_timeout`), a new `config` subcommand in
  `cli/_pod.py` (its own function; also register it in that module's dispatcher and help), the
  `--budget` write in `cli/__init__.py` (store a number, not a string), the `pod` Typer
  docstring + regenerated `docs/commands.md`, `specs/functional/pod-dispatch.spec.md` +
  `cli-json-shapes.spec.md` (config get --json shape) + changelogs, tests.
- Do NOT touch in `core/dispatch.py`: anything below the setting readers — especially
  `dispatch_pod`, `_run_step`, claim/finalize code (P26-19 owns those). Do NOT touch
  `cli/_pod.py::_pod_dispatch`'s pending/resumable filter.
- Keys in scope now: `budgetUsd` (float), `maxReworkCycles` (int >= 0), `turnTimeoutS`
  (int > 0), `verifyTimeoutS` (int > 0). Design the model so later cards can add keys
  (`approvalMode`, `pipeline`, `allowCommands`) without reshaping.
- Behaviour contract: `pod <p> config` (get, default) shows effective values + source
  (set|default); `set <key> <value>` validates and writes through the existing meta writer,
  audited as `pod.config`; `unset <key>` removes it; invalid value at `set` -> exit 1, meta
  untouched; an invalid STORED value makes dispatch refuse with key+reason instead of silently
  defaulting (amend the spec section that today documents the silent fallback). Accept both
  number and numeric-string in stored meta (existing installs have "5").

## P26-19 — a deterministic dispatch refusal settles the claim; orphans are recoverable
- Card: `card_packet.py P26-19`
- Owns in `core/dispatch.py`: the `DispatchError` raise sites reachable INSIDE a claimed task
  (the cross-pod membership refusal near `_run_step`'s top and any sibling deterministic
  refusal) and the claim finalize path they must route through; in `cli/_pod.py`: ONLY the
  pending/resumable computation in `_pod_dispatch` (~lines 542-551). Specs:
  `pod-dispatch.spec.md` (task state machine / claims section) + changelog. Tests: unit
  dispatch tests + one integration test.
- Do NOT touch: the setting readers at the top of dispatch.py (P26-4 owns them), pod_of
  (P26-18 shipped), orchestrator/pipeline files.
- RED reproduction (P26-18 closed the original trigger): a pipeline spec with an
  `agent: <genuinely-alien-member-id>` step still hits the cross-pod refusal mid-task on the
  base — use that, or an equivalent deterministic refusal you find on the claimed path.
  Assert on base: the task stays `running` and a follow-up `pipeline run --resume` reports
  nothing to do. After the fix: the task ends `failed` with the refusal reason persisted, the
  claim is settled, and `--resume` (with `--resume` counting stale-claimed `running` tasks
  too) re-runs it from the last persisted hop without a decoy task or CLAIM_STALE_TIMEOUT
  override. A kill -9 mid-hop must still leave `running` for the stale sweep — pin that.
