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
- Return the "Worker return" shape of
  `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`, in 1,500 to 3,000 characters.

## Wave 104: Phase 42 sub-wave A (base `BASE_COMMIT`)

The two cards are disjoint:
- **P42-1** owns `core/dispatch.py` and, if needed, `core/context.py`.
- **P42-3** owns `core/identity.py`, `core/skills.py`, `edges/adapters/system.py` (one new reader
  function) and the roots passed in `edges/adapters/docket_runtime.py`.

Neither edits the other's files. They merge in either order; P42-2 (sub-wave B) depends on P42-1.

### P42-1: a backward route carries the gate's output into the rework hop

- **Worktree / branch:** `../rack-cli-wt/p42-1`, `phase-42/p42-1`, at `BASE_COMMIT`.
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

- **Worktree / branch:** `../rack-cli-wt/p42-3`, `phase-42/p42-3`, at `BASE_COMMIT`.
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
