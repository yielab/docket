# Phase 42 worker packets (D-61, ADR 0025)

One packet per card. Each points at its card in `TODO.md`. Load the card with
`python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`; it is not copied here.
Every worker follows `AGENTS.md` (change contract, end-of-work control) and `CONTRIBUTING.md`
"Rules that have cost this project time when ignored".

Common to every worker:
- Work only in your worktree. Run every command with `env -u VIRTUAL_ENV` so you use the
  worktree's own environment, never the main checkout's.
- Use a unique `DOCKET_HOME` and a unique temp dir under your worktree. Never touch `~/.docket`.
- Never `git stash`; set work aside with a WIP commit. Diff from `git merge-base HEAD develop`,
  never from `HEAD` alone.
- Commit subjects are `Type: description`, ASCII only, no AI mention and no Co-Authored-By trailer.
- Spec first, then a failing (RED) test, then the change. Bump the owning spec's version and add
  its changelog line.
- Do not edit `README.md`, `ROADMAP.md`, `TODO.md`, `CHANGELOG.md`, `specs/README.md`,
  `docs/SECURITY-SIMPLE.md`, `docs/CONFIGURATION.md` or any metric count. Report what the
  integrator must change instead.
- Focused gates: your new and neighbouring tests, then `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy src` and
  `scripts/maint/comment_lint.py --check <touched files>`.
- Final gates: `uv run pytest -q`, `bash tests/golden/run.sh verify-all` and
  `bash scripts/validate-specs.sh`. Never regenerate a golden to make it pass.
- Before `mypy`, run `env -u VIRTUAL_ENV uv sync --all-extras` once. Without the `mcp` extra,
  mypy reports three phantom `anyio` errors in `edges/adapters/mcp_client.py` (Wave 104).
- `comment_lint.py --check` counts per file. Compare your files' totals with the same files on
  the base; a new `long-def-doc` (a docstring over three lines) is a finding, and it is yours.
- Any module-level mutable state that a turn writes must be safe when the children of a
  `parallel` group run concurrently in one worktree (`orchestrator.run_group`, one copied
  context per child). Prefer a `ContextVar`. Wave 104 found and fixed a module-global registry
  that a finishing sibling cleared under a running one.
- Return the "Worker return" shape of
  `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`, in 1,500 to 3,000 characters.

## Wave 104: Phase 42 sub-wave A (base `e8774fad`)

The two cards are disjoint:
- **P42-1** owns `core/dispatch.py` and, if needed, `core/context.py`.
- **P42-3** owns `core/identity.py`, `core/skills.py`, `edges/adapters/system.py` (one new reader
  function) and the roots passed in `edges/adapters/docket_runtime.py`.

Neither edits the other's files. They merge in either order; P42-2 (sub-wave B) depends on P42-1.

### P42-1: a backward route carries the gate's output into the rework hop

- **Worktree / branch:** `../rack-cli-wt/p42-1`, `phase-42/p42-1`, at `e8774fad`.
- **Trigger locators:**
  - `core/dispatch.py::_run_pipeline`: the `outcome.kind == "routed"` branch versus
    `kind == "rework"`, which is the only one that sets `pending_rework_by_index`.
  - `_hop_message`: the `rework_hop` section.
  - `_resolve_resume_state`.
  - `_evaluate_mechanical_gate`: `hop.verify`.
- **Allowed:** the functions above in `core/dispatch.py`; `core/context.py` only for a compile
  helper.
- **Spec:**
  - `specs/functional/pipeline-format.spec.md` "Outcome routing".
  - `specs/functional/pod-dispatch.spec.md` "Bounded hop prompts".
- **Neighbouring tests:** `rg -ln "until.*verify|REWORK REQUIRED|_hop_message" tests/`.
- **Design constraints:**
  - The carryover is built from the routed hop's `verify` evidence: the redacted `outputTail`.
    Never use raw output.
  - Give the section a stable header (`--- GATE FAILED: <step id> ---`) so P42-2 can append
    reasons under it. Expose one small function that owns that text, because P42-2 extends it
    and the integrator will test that seam.
  - A forward route, an unrouted gate and a verdict rework must produce byte-identical messages.
- **RED:** an integration test (pod pipeline with
  `implement: {gate: mechanical, until: verify, max: 2}`, a recording fake runner, and a verify
  command that fails once printing a unique marker, then passes). It must fail on the base
  because the marker is absent from the second Implementer message.
- **Mutable state:** none outside your temp `DOCKET_HOME`.

### P42-3: repository instructions and skills come from the task's base commit

- **Worktree / branch:** `../rack-cli-wt/p42-3`, `phase-42/p42-3`, at `e8774fad`.
- **Trigger locators:**
  - `edges/adapters/docket_runtime.py` (`roots=(Path(pipeline_worktree),)`).
  - `core/identity.py::_project_instructions_raw` (`project_roots[0]`) and
    `project_instruction_files`.
  - `core/skills.py::discover_skills` (the `codebase` scope).
  - How dispatch records a task's `baseCommit` and its git dirs: see ADR 0019 decision 1 and
    `rg -n "baseCommit|recorded git dir|trusted" src/docket/core/dispatch.py
    src/docket/edges/adapters/system.py`.
- **Allowed:** those functions, plus one new reader in `edges/adapters/system.py` that reads
  `<rev>:<path>` with host-side git. It must name the git dir docket recorded for the worktree
  (ADR 0024 / P41-8: never read the worktree's `.git` file) and return `None` when the path is
  absent at that rev.
- **Spec:**
  - `specs/functional/agent-loop.spec.md`, the project-instructions paragraph around
    `project_roots[0] / "AGENTS.md"`.
  - `specs/functional/role-archetypes.spec.md`, skills scopes (locate with `rg -n "skills"`).
- **Neighbouring tests:**
  `rg -ln "project_instruction_files|_project_instructions_raw|discover_skills" tests/`.
- **Design constraints:**
  - The change applies on every run that has a task worktree and a recorded base commit, not
    only under a profile.
  - Without a task worktree, behaviour is byte-identical.
  - `core/` must not shell out: the git read lives in `edges/` and reaches `core/` through the
    existing roots parameter or a small injected reader. Keep the inward-only layering.
  - Return each composed repository file's path and the sha256 of the bytes used in a
    structure P42-5 can later put in evidence. Recording it on the hop is enough; do not touch
    `core/evidence.py`.
- **RED:** an integration test with a real git repo and task worktree. The Implementer hop
  (fake runner) rewrites `AGENTS.md` with a marker and commits. The next hop's composed prompt
  must contain the base text and not the marker. Write the same test for a skill under
  `.docket/skills/`. Both fail on the base.
- **Measure:** time one git read on this host and report the number.
- **Mutable state:** temp git repos only.

## Wave 105: Phase 42 sub-wave B (base: the Wave 104 rollup on `develop`)

One card, alone, because it owns the `core/dispatch.py` and `core/pipeline.py` hotspot.

### P42-2: the external gate

- **Worktree / branch:** `../rack-cli-wt/p42-2`, `phase-42/p42-2`, at the base named in the
  spawn prompt.
- **Decision:** read ADR 0025 D1 and its "Accepted with amendments" table. Where they disagree,
  the amendments win.
- **What P42-1 left you:**
  - `core/dispatch.py::_gate_failed_section(step_id, output_tail)` is the one owner of the
    `--- GATE FAILED ---` text. Extend it to take the reasons; do not write a second one.
  - `_is_gate_failure_carryover` already reads `verify.label` when present. Record `label` on
    `hop.verify`, and every backward route out of an external gate that did not pass carries
    automatically.
- **Allowed:**
  - `core/pipeline.py`: `ExternalGate` and the `Gate` union, the short form
    `gate: {external: CMD}` and its export back to the short form, the `on:` key validation
    for an external-gated step (`pass|fail|needs_human|error`), `_default_edge_reachable`.
  - `core/dispatch.py`:
    - a helper extracted from `_evaluate_mechanical_gate` that both gates call (envelope,
      fingerprint, redaction, `hop.verify`);
    - `_evaluate_external_gate`, and the site that picks an evaluator by gate type;
    - `_gate_failed_section`;
    - the failure kinds `gate_failed`, `gate_needs_human` and `gate_error` (see
      `_ROUTE_FAILURE_KINDS`).
  - `core/orchestrator.py`: the plan label (`external(<command>)`), next to `mechanical(...)`.
  - The regenerated `docs/contracts/config-v1/pipeline.schema.json`, via
    `scripts/gen_config_schemas.py`, never edited by hand.
- **Not yours:**
  - `core/archetypes.py::GATE_KINDS`: a role's default gate stays as it is, and the external
    gate is a pipeline-step gate only.
  - `core/answers.py`: the `input` step already routes answers, so do not add a continuation.
  - The `exec` flags.
- **The reasons file:**
  - Its path is `DOCKET_GATE_REASONS_FILE`, under the pod cache dir (see
    `edges/adapters/docket_runtime.py::_pod_cache_dir`; it is a read-write root of the jail
    since P41-5). Pass it through `_run_in_envelope(..., env=)`.
  - Delete it before the command runs. Read it after: UTF-8 JSON of at most 64 KiB, shaped
    `{"reasons": [{"summary": str, ...}]}`.
  - Anything else sets `reasonsInvalid: true`, and the output tail stands in.
  - Reasons are untrusted text: redact them, and screen them the way an MCP result is screened
    (find the existing screen with `rg -n "def screen_tool_result" src/docket/core/tools.py`
    and reuse it, do not write a second one). No reason field drives control flow.
  - When the pod has no cache dir, the gate still runs and the output tail is the reasons.
- **Exit mapping:** `exitMap` defaults to `{pass: [0], fail: [1], needs_human: [2]}`. `error`
  is any of: an unmapped code, a timeout, a jail refusal (`_run_in_envelope` returns its
  `[verify not run: ...]` text), or an empty command. `hop.verify` keeps `cmd`, `durationS`,
  `outputTail` and `touched`, gains `label` and `reasonsInvalid`, and its `exitCode` is the real
  code. A mechanical gate's `exitCode` stays 0 or 1.
- **Spec:**
  - `specs/functional/pipeline-format.spec.md`: "Gates" (the new kind) and "Outcome routing"
    (its four labels).
  - `specs/functional/pod-dispatch.spec.md`: gate evaluation, "Hop evidence" (`verify` fields)
    and the failure kinds.
  - `specs/functional/config-format.spec.md`, if it lists gate kinds.
- **RED:** unit tests for parsing, the short form and its round-trip export, and validation
  errors. Then an integration test with a fake verifier script that exits 0, 1 (writing
  reasons), 2 and 7, and one that sleeps past its timeout. Cover reasons that are too large,
  not JSON, and pre-existing (planted before the run; they must not be read).
- **Seam test (real code on both sides):** a pipeline whose external gate exits 2, with
  `on: {fail: {goto: build, max: 2}, needs_human: ask}`, and `ask` an `input` step with
  `on: {answered: {goto: build, max: 1}, declined: fail}`. Dispatch parks the task
  `waiting_input`. `core.answers.answer_task(..., "accept", ...)` reopens it. Dispatch again:
  the Implementer's message carries the reasons under `GATE FAILED`. If the resume path loses
  the reasons, that is this card's defect to fix.
- **Unchanged:** a pipeline without an external gate is byte-identical (goldens untouched).

## Wave 106: Phase 42 sub-wave C (base: the Wave 105 rollup on `develop`)

There are two cards, scheduled in parallel. Their ownership is set at function level, because
both cards touch `core/dispatch.py`:
- **P42-4** owns one call site in `dispatch_task`, before `_run_pipeline`, where it raises the
  existing `DispatchError`. Look at how a `DispatchError` folds into `failure_kind
  "dispatch_refused"`: it is resumable after the operator fixes the cause. P42-4 also owns the
  new `core/profile.py`, `PodSettings.profile`, the fleet security record's profile field, the
  `setup profile` CLI, and the doctor and status lines.
- **P42-5** owns `HopResult` and its two persistence functions (`_hop_record`,
  `_hop_from_record`), the line where dispatch builds a `HopResult` from the driver's
  `TurnResult` (copy `repo_files`), `core/evidence.py`, and the evidence schema generator.
- Neither card edits a function the other owns. Merge order: P42-5, then P42-4.

### P42-4: the `lights-out` profile

- **Worktree / branch:** `../rack-cli-wt/p42-4`, `phase-42/p42-4`.
- **Decision:** ADR 0025 D2 as amended (the final table) and the card in `TODO.md`.
- **One amendment found at the Wave 105 close:** MCP servers are stdio only
  (`core/mcp_tools.py::McpServerConfig`, "stdio transport only, today"), and a stdio server
  runs in the jail. Drop the "no HTTP MCP server" check entirely, and say so in the spec.
- **Shape:**
  - `core/profile.py` holds the decision as a pure function over a small facts dataclass:
    `lights_out_violations(facts) -> list[Violation]`, where each violation carries its
    requirement and its fix.
  - A separate gatherer builds the facts from the live readers. Reuse what exists:
    - isolation state from `core/fleet.py::get_isolation_enabled` and backend usability, the
      same way `edges/adapters/docket_runtime.py::_resolve_sandbox` decides it;
    - network from `core/pod.py::effective_network`, plus whether the jail will enforce it;
    - the loaded pipeline's steps (an `ExternalGate` on every step whose role is an
      Implementer);
    - pod-injected environment names compared with secret-store names (find where a pod
      injects variables: ADR 0020 decision 8, `rg -n "inject" src/docket`).
  - Do not duplicate any of those decisions; call them.
- **Recording:**
  - Global: `FleetSecurity` gains the profile next to isolation and network, written by
    `docket setup profile lights-out|attended`. Add it to `cli/_setup.py`'s group; look at how
    `cli/_setup_sandbox.py` registers a verb. The write is audited.
  - Per pod: `PodSettings.profile`, written by `pod set profile`. A pod may only move toward
    stricter: `attended` under a global `lights-out` is refused at write time.
  - No record means `attended`. A fresh install changes in nothing (goldens unchanged except
    the deliberate new surface: `setup` help gains one verb, explained line by line).
- **Enforcement:** one check in `dispatch_task` before `_run_pipeline`. On a violation, audit
  `profile.refused` (naming the pod, the task and the requirement), then raise `DispatchError`
  with the requirement and its fix. Nothing runs. `doctor` and `status` show the effective
  profile and its violations, computed by the same function.
- **Spec:**
  - `specs/functional/security-gates.spec.md`: a new "Profiles" section.
  - `specs/api/cli-interface.spec.md`: `setup profile`, `pod set profile`.
  - The doctor and status lines: `specs/functional/operator-loop.spec.md`, or wherever
    `status` lines are specified (`rg -n "sandbox posture" specs`).
- **RED:**
  - One integration row per requirement (profile on, that requirement unmet): refused,
    `profile.refused` audited, no driver call.
  - One positive row: every requirement met (fake the backend probe the way neighbouring
    sandbox tests do), and the task runs.
  - A row for the per-pod stricter-only rule.
  - The suite must also pass under `scripts/maint/pytest-without-sandbox.sh -q`.

### P42-5: evidence 1.1.0, `gate` and `directives`

- **Worktree / branch:** `../rack-cli-wt/p42-5`, `phase-42/p42-5`.
- **Decision:** ADR 0025 D4 as amended. Only `gate` per hop and `directives` per task are
  added; no ids and no digests.
- **Input from Wave 104 and 105:**
  - `TurnResult.repo_files` (`core/runtime_driver.py`) maps repository-relative path to sha256
    for the files a turn composed from the base commit. Dispatch does not copy it yet: persist
    it on the hop as `repoFiles`.
  - `hop.verify` on an external-gated hop carries `label`, `exitCode`, `reasonsInvalid` and
    optionally `reasons`.
- **Shape:**
  - `HopEvidence.gate = {label, exitCode, reasonsInvalid}`, present only when the hop's
    `verify` has a `label`.
  - `TaskEvidence.directives = [{path, sha256}]`, the distinct pairs over the task's hops in
    first-seen order. Absent when empty.
  - `v` is `1.1.0`.
- **The harness result keeps `1.0.0`.** `cli/_harness_recipe.py::_task_evidence` embeds
  evidence in the published harness result. A version bump there changes the bytes of every
  `exec --recipe` run under a contract that must not change. So `task_evidence` takes the
  version, `1.0.0` produces exactly today's document, and only `docket task show --json` and
  serve's evidence route ask for `1.1.0`. Prove it: the harness fixtures under
  `tests/fixtures/harness-contract/` must stay unchanged.
- **Schema:** `docs/contracts/evidence-v1.1/`, generated by `scripts/gen_evidence_schema.py`
  (extend it, keep `v1` byte-identical, keep its `--check` green).
- **Spec:** `specs/functional/pod-dispatch.spec.md` "Evidence v1" (amend it to cover 1.1.0)
  and `specs/data/cli-json-shapes.spec.md`.
- **Before you finish:** check whether Tack parses evidence. Run
  `rg -n "evidence" ~/Sites/objetivosMios/crates --type rust -l` read-only; never edit there.
  Report whether its parser would reject `v: "1.1.0"` or the new fields.
- **RED:**
  - A fixture task with an external-gated hop and a hop carrying `repoFiles` produces both
    fields under 1.1.0 and validates against the new schema.
  - A task with neither carries neither.
  - `task_evidence(..., "1.0.0")` is byte-identical to today's output for the same task.
