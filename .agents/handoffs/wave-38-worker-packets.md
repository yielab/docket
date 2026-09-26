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

---

# Wave 39 worker packets (opened after batch B merged; base is the commit your worktree starts on — verify with `git log --oneline -1` and `git merge --ff-only <base>` if the coordinator's prompt names a newer one)

Five cards, five Sonnet workers, strict function-level ownership. Three cards each add ONE field
to `core/pod.py::PodSettings` (P26-5 `approvalMode`, P26-6 `pipeline`, P26-8 `allowCommands`):
add only your field, its validation and its `_SETTING_FIELD_BY_ALIAS` entry, appended at the end
of the existing blocks — never reorder or reformat the class; the integrator resolves the
overlapping one-line conflicts. Same shared rules as Wave 38 (top of this file): never stash,
`env -u VIRTUAL_ENV`, temp DOCKET_HOME, RED-first, spec-first, COMMIT your branch, no AI
trailers, forbidden central files, docstrings <= 3 lines, run `tests/guards` before handoff.

## P26-3 — context budgets follow the resolved model window
- Card: `card_packet.py P26-3`. Depends on P26-2 (merged): identity.py already has
  PromptComposition/section reports.
- Owns: budget resolution in `core/identity.py` (window-aware default; explicit
  `CONTEXT_TOKEN_BUDGET` env stays an override) and `core/context.py` (`tokenBudget` default as
  a window share when unset), the window plumbing from `edges/adapters/docket_runtime.py` into
  the loop/ToolContext ONLY as needed to hand identity/context the resolved
  `contextWindow`/`maxTokens` (see how `resolve_endpoint` already reads them at
  `edges/adapters/llm.py:469`), `docket maintain check`'s report line, `agent-loop.spec.md` and
  `session-history.spec.md` sections + changelogs, tests.
- Do NOT touch: `AGENT_LOOP_TOKEN_BUDGET` semantics, compaction, `core/dispatch.py`,
  `core/security.py`, PodSettings.
- Contract: documented shares of (window - output reserve - tool schemas); unregistered window
  -> today's constants, stated in the report; `prompt_composed` + `maintain check` name the
  effective budget and its source (env|window|default). A 16k window keeps today's behaviour;
  a 200k window fits the P26-2 oversized-SOUL fixture with every section full.

## P26-5 — unattended turns can refuse instead of waiting on nobody
- Card: `card_packet.py P26-5`.
- Owns: `PodSettings.approvalMode` (`wait`|`refuse`, default wait), the hop tool-env builder in
  `core/dispatch.py` (the function that assembles the env dict handed to the driver — it already
  carries `PIPELINE_WORKTREE_ENV`; thread `DOCKET_APPROVAL_MODE=refuse` the same internal-env
  way `cli/_harness.py:185` does), task failure reason on `approval_unavailable`,
  `pod-dispatch.spec.md` + `security-gates.spec.md` sections + changelogs, tests.
- Do NOT touch: `core/approval.py`, `core/tools.py`, harness code, other dispatch functions.
- Oracle: with refuse, an asking call ends the hop well under one TOOL_APPROVAL_TIMEOUT with the
  approval_unavailable shape naming tool/call/policy recorded on the task and trace; with wait
  (default), byte-identical behaviour to base, pinned.

## P26-6 — a pipeline file can be a pod's default for every trigger
- Card: `card_packet.py P26-6`.
- Owns: `PodSettings.pipeline` (stored docket-owned copy + hash in the Lead workspace —
  `pod config set pipeline <file>` validates via `core/pipeline.py::load_pipeline` and plans
  against the roster before accepting), `core/dispatch.py::effective_pipeline` and
  `_blueprint_pipeline` ONLY, `pipeline plan` source labelling in `cli/_pipeline.py`,
  `pipeline-format.spec.md` + `pod-dispatch.spec.md` sections + changelogs, tests (incl. one
  proving a serve-sweep-shaped call — `dispatch_pod(project, spec=None)` — executes the bound
  file's step ids, and an MCP-path call sees the same).
- Do NOT touch: the pipeline dialect itself, orchestrator, serve.py, the hop-message builder.
- `unset pipeline` restores the blueprint default; a bound file whose roles leave the roster
  refuses at dispatch with a named reason (fail loud, not skip).

## P26-7 — custom roles and steps carry their own hop instructions; variables get a consumer
- Card: `card_packet.py P26-7`.
- Owns: the hop-message builder in `core/dispatch.py` (~the function around lines 526-644 that
  sets `instructions = ""` for non-built-in roles), archetype field `hopInstruction`
  (`core/archetypes.py`: wire schema, from_wire, validate; generated fallback from
  `gateContract` for gated roles without one), pipeline step field `instructions` +
  `${var}` interpolation from the run's resolved variables (`core/pipeline.py`,
  `resolve_variables` currently only stored on the run record — thread them into dispatch),
  `--var k=v` on `pipeline run` (`cli/_pipeline.py`), unresolved variable -> refuse the run,
  `role-archetypes.spec.md` + `pipeline-format.spec.md` + changelogs, tests.
- Do NOT touch: effective_pipeline/_blueprint_pipeline (P26-6), the tool-env builder (P26-5),
  identity/prompt composition.
- Oracle: the four built-in roles' hop messages byte-identical to base (pinned); a custom
  verdict-gated role's message contains its marker instruction; `--var area=auth` renders
  "Focus on auth"; missing var refuses before any hop.

## P26-8 — a pod can allow its own tool binaries, scoped and audited
- Card: `card_packet.py P26-8`.
- Owns: `PodSettings.allowCommands` (list of exact binary basenames; validation rejects
  paths, shell metacharacters, `eval`/`exec`/`source`/`.`/`export`, and any name matching a
  high-risk class pattern), `core/security.py::classify_command` gains an optional
  `extra_bins` parameter (default empty — zero behaviour change without it),
  `core/tools.py::ToolContext` gains the field and `evaluate_tool_call` passes it (the ONLY
  edit in tools.py), the driver plumbing that fills it from the pod setting
  (`edges/adapters/docket_runtime.py` + the dispatch env/context path that already carries
  pod facts), audited at `pod config set`, `security-gates.spec.md` + changelog, tests.
- Do NOT touch: SAFE_BINS itself, high-risk patterns, policies, dispatch_tool.
- Oracle (from the card): `pytest -q` and `uv run pytest` allow in the configured pod;
  `uv run pytest && git push origin main` still asks; a block policy on pytest still denies;
  another pod still asks. Opaque markers and redirect handling unchanged, pinned.

# Wave 40 worker packets — Phase 26 final wave (D-42)

Base commit: `dbfee35` (Wave 39 closed; all five cards merged, gates green). Six parallel
workers: P26-9, P26-11, P26-12, P26-14, P26-15, P26-20. P26-10 starts only after P26-9
merges; P26-17 only after P26-10. All Wave 38/39 shared rules above apply unchanged,
plus two learned this phase:
- **COMMIT your worktree on its branch before handing off.** An uncommitted worktree
  cannot be merged; two workers cost the integrator this in Wave 38.
- **Spec versions are PRE-ASSIGNED below.** Two same-day bumps to the same version
  auto-merge with no conflict and corrupt the header silently — three times in Waves
  38/39. Claim exactly the version your packet names, even though the current header
  looks like it leaves the next patch free.

## P26-9 — generated instructions agree with the runtime contract
- Card: full text in `TODO.md` §P26-9 (read only that section).
- Owns: built-in template strings in `core/archetypes.py`, `core/memory.py::seed_contract`
  text, `POD_TEMPLATE_VERSION`, owning sections in `specs/functional/workspace-structure.spec.md`
  (claim **1.10.0**) and `specs/functional/role-archetypes.spec.md` (claim **1.9.0**),
  structural tests, workspace goldens (regenerate, explain every changed line in the handoff).
- Do NOT touch: `core/identity.py`, `cli/`, any other spec.

## P26-11 — docket config explain <agent>
- Card: `TODO.md` §P26-11. Read-only command composing EXISTING functions only
  (P26-2 composer, P26-3 budget source, P26-4 PodSettings, P26-6 effective_pipeline_source,
  P26-8 allowCommands, models/policy readers). No second composer, writes nothing.
- Owns: new `src/docket/cli/_config.py`, its registration in `cli/__init__.py`, a help
  golden (new golden case is allowed: explain the addition), `specs/data/cli-json-shapes.spec.md`
  (claim **1.10.0**), unit + integration tests, `docs/commands.md` regeneration.
- Do NOT touch: `core/` (add nothing there; if a value is unreachable read-only, report it
  as a finding instead of adding core surface).

## P26-12 — configuration errors are loud; schedules get a writer
- Card: `TODO.md` §P26-12.
- Owns: doctor check functions (your own, + wiring lines), the schedule write path in
  `core/schedule.py`, `PodSettings` routing for `schedule` (one field append, same
  coordination rule as Wave 39), loud-skip logging in serve sweep call path,
  `specs/functional/pod-dispatch.spec.md` (claim **6.13.0**),
  `specs/functional/model-profiles.spec.md` (claim **2.9.0**),
  `specs/functional/role-archetypes.spec.md` (claim **1.10.0**).
- Do NOT touch: `core/provider.py`/`core/fleet.py` default-model surface (P26-14 owns it),
  prune/retention surface (P26-15 owns it), template strings (P26-9 owns them).

## P26-14 — one default model of record
- Card: `TODO.md` §P26-14.
- Owns: `core/provider.py`, the default-model read/write in `core/fleet.py` +
  `cli/_install.py`, migration of the fleet key, `specs/functional/model-profiles.spec.md`
  (claim **2.10.0** — P26-12 takes 2.9.0; keep both changelog entries when you rebase/merge),
  tests. Report the `rankAnchors`/display-only prose wording for `docs/CONFIGURATION.md` in
  your handoff — the integrator applies it (docs/ is forbidden to card branches).
- Do NOT touch: `core/models_policy.py` loader validation (P26-12 owns the loud-skip there).

## P26-15 — registries stay bounded; traces filed under the pod
- Card: `TODO.md` §P26-15. Withdrawn item: leave `guardrail_block` action=policy-id alone
  (contractual, security-gates req. 4).
- Owns: prune functions in `core/runs.py` / `core/approval.py` / `core/conversations.py`,
  the serve sweep call, `ToolContext.project` in `edges/adapters/docket_runtime.py`,
  `dispatch.py:260,1181` trace-path call sites, the stale `config.py:41-44` comment,
  `specs/functional/pod-dispatch.spec.md` (claim **6.14.0** — P26-12 takes 6.13.0),
  `specs/functional/audit.spec.md` retention wording (claim **2.10.0**), trace spec section.
- Do NOT touch: audit-log rotation behaviour itself; `PodSettings`.

## P26-20 — shipped recipes: role + pipeline + policy bundles
- Card: `TODO.md` §P26-20.
- Owns: `templates/recipes/` (new, data only: secure-build, research-review, ops-approval),
  packaging include in `pyproject.toml`, validation tests (default lane) + one end-to-end
  secure-build dispatch on the fake driver, wheel-content assertion,
  `specs/functional/pipeline-format.spec.md` shipped-data wording (claim **2.5.0**),
  `specs/functional/role-archetypes.spec.md` (claim **1.11.0** — P26-9 takes 1.9.0 and
  P26-12 takes 1.10.0), `specs/functional/workspace-structure.spec.md` shipped-data section
  (claim **1.11.0** — P26-9 takes 1.10.0).
- Report the `docs/CONFIGURATION.md` §3 pointer text in your handoff; the integrator adds it.
- Do NOT touch: any CLI surface (applying a recipe uses existing commands only).

## P26-10 — operator instructions survive regeneration; roles can be re-rendered
- Starts after P26-9's merge. Base: the commit your dispatch prompt names.
- Card: `TODO.md` §P26-10.
- Owns: the `INSTRUCTIONS.md` overlay read + composition slot in `core/identity.py`
  (right after SOUL, inside the P26-2/P26-3 budget/fit machinery — a new
  PromptSectionReport entry, never a second composer), a re-render function in
  `core/pod_provisioning.py` (compares `POD_TEMPLATE_VERSION` + archetype content),
  `cli/_pod.py` `sync [--dry-run]`, your own doctor check function + wiring line,
  `specs/functional/workspace-structure.spec.md` (claim **1.12.0** — P26-20 holds 1.11.0)
  and `specs/functional/agent-loop.spec.md` req. 30 (claim **1.21.0**), tests,
  `docs/commands.md` regeneration (`uv run --extra mcp`).
- Do NOT touch: template STRINGS in `core/archetypes.py` (P26-9 just changed them),
  `core/memory.py`, `core/dispatch.py`, recipes/provider/prune surfaces (sibling cards).
- `INSTRUCTIONS.md` is operator-owned: docket NEVER writes it, `sync` never touches it,
  doctor never quarantines it.
