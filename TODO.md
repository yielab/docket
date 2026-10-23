# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## ◇ Phase 45 closed 2026-10-20

> Phase 45 (a prepared checkout, models from the provider, and a check the change cannot define,
> D-65, [ADR 0029](docs/adr/0029-a-prepared-checkout-models-from-the-provider-and-a-check-the-change-cannot-define.md))
> closed 2026-10-20: five cards over Waves 117-119 and two small real runs on the operator's home
> without Tack, archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> Acceptance met except one clause: the worktree is prepared from the lockfile (22.4 s, then a
> cache hit in 0 s), the project's eslint, tsc and vitest run as the gate, `setup provider show`
> names every limit's source or says `unknown`, approvals are kept per (codebase, pod); no run
> parked on `check_changed` because neither touched a protected path (the unit and seam tests are
> the evidence for that clause). The runs found three defects, all fixed the same day
> (`3e9c3d9f`, `0a0bff6c`, `f9a5cec4`). Operator items left: `~/.docket/provider-models.json.bak`
> still holds a worker test's junk rows (`m`, window 9) and the maintainer deletes it; the two
> task branches `docket/fab-dev/task-b1e95477…` and `…task-b5e39e26…` in the Fabulada repository
> carry the new tests and are the maintainer's to merge or drop. Phase 46 (D-66, ADR 0030) is
> active on branch `plan/phase-46-structure` since 2026-10-22.

## ◇ PHASE 46 — ACTIVE — organize by context, refactor by tool (D-66, [ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md); planned 2026-10-20, started 2026-10-22 on `plan/phase-46-structure`)

> **Evidence.** Measured 2026-10-20 at `c74a224e` (ADR 0030 "Evidence"): 31 of 63 `core` modules
> import `edges`; 206 function-local imports hide a 38-module cycle; `core/dispatch.py` is 4,727
> lines, 168 definitions, 20 % of all `src/` commits in 90 days; `status` is written in 16 places;
> 1,191 `monkeypatch` uses, 72 on `dispatch`; the runtime wheel is a 40-file build-hook copy.
>
> **Shape.** The ADR is the step-by-step guide; each card below is one of its steps. **Zero
> behaviour change** is the contract: the HTTP API 6, the CLI goldens and the `docket_runtime`
> facade are the oracle; every internal shape (module paths, persisted JSON, test locations) is
> free to change (D-57: no users, no data to migrate). Every card ends with
> `scripts/maint/refactor_gate.sh` exit 0 (nine checks, ADR 0030 "The step-by-step guide"); a
> card that fails the gate is reverted and its mapping corrected, never patched until green.
>
> **Who does what.** Tool-only cards (T) run a script; a model writes code only in P46-2, P46-3,
> P46-4 (tools with their own tests) and P46-12, P46-13 (bounded judgment with generated input).
> Review cards (R) are one human read of a generated artifact. The integrator owns `refactor/`
> (mapping, analysis, retired list), the board, ROADMAP, CHANGELOG and every rollup.
>
> **Ordering.** A: P46-1 → P46-2 ∥ P46-3 → P46-4 → P46-5. B: P46-6 → P46-7 → P46-8 → P46-9 →
> P46-10 → P46-11. C: P46-12 (after P46-7), P46-13 (after P46-8). D: P46-14 → P46-15. Baseline
> live run recorded before P46-6. **Freeze:** no other card touches `src/` from P46-6 to P46-15.
>
> **Dev dependencies added:** `libcst`, `import-linter`. Runtime dependencies unchanged.
>
> **Phase acceptance** (ADR 0030 "Phase acceptance"): architecture tests at target (ignore list
> empty, local imports 0, largest module ≤ 700, `status` writers 1, every patch on its defining
> module, every test at its mirror path); runtime installs without a hook; API/goldens/facade
> tests unchanged; before/after live traces identical modulo ids and timestamps; no `cli/`,
> `core/`, `edges/`, `serve.py`, `config.py` left.

### Progress and execution plan (2026-10-22)

**Done on the branch.**

- **Specs truth pass** (`3c533a9c`, `2ed1cce5`). Every one of the 32 specs now states today's code, carries no history, and names a path only in its last `## Implementation` section, the only text P46-3 rewrites. The pass did not apply Phase 46 ahead of time: each amendment is listed on its card below.
- **The pass found 87 code defects.** None was fixed, because the specs state the code as it is. They are scheduled in Wave 120 below, or folded into the Phase 46 card that rewrites that code anyway.
- **P46-5 step 1**, out of the planned order. It does not depend on P46-2..4. Commits `8325268f` and `cd04b643`:
  - `kernel/` holds `home`, `clock`, `ids`, `errors` and `text`, with their unit tests, the leaf guard and the shrink-only adoption guard.
  - `scripts/maint/adopt_kernel.py` rewrites call sites and `scripts/maint/measure_kernel_adoption.py` counts what remains.
  - Ids, text and clock are adopted (counts 0, 3 and 0), and 13 wrappers are deleted.

**How work is split: volume decides script or model.** A rewrite that is the same at every site is done by a script, even when a model could do one site faster: the script is written once, runs again in seconds on whatever tree it meets, and does not drift at site 300. A model takes the work where each site is a decision. Measured on the working tree on 2026-10-22:

| Work | Volume | Who | Why |
| --- | --- | --- | --- |
| `config.*` reads → `current_home()` | 415 sites, 61 files | script (P46-5 step 3) | same rewrite everywhere |
| `repoint_docket_home` → `use_home` in tests | 190 sites, 132 files | script (P46-5 step 3) | same rewrite everywhere |
| `raise ValueError` → `InvalidInput` | 148 sites | script (P46-5 step 2) | `InvalidInput` is a `ValueError`, every `except` still catches |
| 36 error classes → a kind | 36 classes | Opus writes the table, then the script applies it | the judgment is in the table, not in the edit |
| `os.environ` outside `config.py` | 34 sites (61 more go away with `config.py`) | Sonnet, from the measurer's list | each site needs a decision |
| module moves (P46-7..9) | about 100 modules | `move.py` | as ADR 0030 |
| the 87 defects | about 75 after folding and duplicates, in 13 cards | Sonnet, one card per group of files | each needs a RED test and a decision |
| stale text and dead code | 9 items with exact locations | Haiku | no judgment |
| spec versions, the index, goldens | per batch | `bump.sh`, `check_spec_index.py`, `run.sh` | already scripts |

Opus is the integrator only. It writes the error-kind table, reviews W120-1 and W120-2 (security), merges, bumps specs and owns every rollup. Haiku takes only edits whose exact locations are known.

**Stages.** Merge in the order shown inside a batch. Each stage starts when the previous one is merged.

| Stage | In parallel | Agents |
| --- | --- | --- |
| 1 | Wave 120 batch A (W120-1..7) and the rules of P46-5 step 3 | 8 Sonnet |
| 2 | Wave 120 batch B (W120-8..12), P46-5 step 2's catcher and table, P46-1, P46-2, P46-3 | 9 Sonnet |
| 3 | W120-13; the integrator then runs P46-5 steps 2 and 3 over the final tree (scripts last, once) and closes P46-5 | 1 Haiku |
| 4 | P46-4 (needs P46-2, P46-3 and P46-5) | 1 Sonnet |
| 5 | Baseline live run (integrator), then P46-6 → P46-15 as planned, with the freeze | per card |

The scripts run last because the Wave 120 branches touch the same files the codemods touch. A script run once over the merged tree meets no conflict. A worker whose new test raises the `repointers`, `config-reads`, `environ` or `error-raises` count writes the new baseline with `measure_kernel_adoption.py --write` and reports the change; the step 2 and step 3 run brings the counts down. The `clock`, `ids` and `text` counts stay where they are: use `kernel.clock`, `kernel.ids` and `kernel.text`.

**Progress 2026-10-23.** Stage 1 and the code half of stage 2 are merged: Wave 120 batches A and B (W120-1..12), P46-1, P46-2, P46-3, the P46-5 step 2 errors rule and its run (`36867d97`, the other session), and the P46-5 step 3 rules (`cf96f6cf`). Spec versions are bumped per batch (`86a5b4b5`, `e57c32bd`). Q1-Q6 were applied at their defaults. W120-13 merged the same day. Next: stage 3.

**Decisions for the maintainer.** Each card applies the default below unless the maintainer answers otherwise before its batch starts.

| # | Question | Default (D-57 unless stated) | Card |
| --- | --- | --- | --- |
| Q1 | analyst and critic have opposite model classes in `models_policy.ROLE_CLASS` and `archetypes.STARTER_ARCHETYPES` (defect 6) | keep the value the live path resolves today, and delete the other table's entry | W120-9 |
| Q2 | `requireApprovalRoles` is read and never written (defect 7); `_policy_requires_approval` always returns False (defect 46) | delete both; one source of `require_approval` fewer | W120-8 |
| Q3 | the role scope `org` and the global `docket-roles.json` have no writer (defect 24); `kind:`-less short forms are a compatibility layer (defect 66) | delete both | W120-9 |
| Q4 | Telegram `/approve` and `/deny` accept a token from any pod (defect 65) | refuse a token from a pod other than the chat's bound pod | W120-10 |
| Q5 | the `docket init --from` path without a blueprint (defects 36, 37, 84, 86, including a path traversal) | delete it: an entry without `blueprint` is refused, and the four defects go with it | W120-2 |
| Q6 | the adoption evidence comes from the harness writing records itself (defect 80) | keep the benchmark, and make the doc say what it proves | W120-7 |

### P46-1 — the rules the documents state

**Status:** DONE 2026-10-23 (`a00dfdef`) · **Size:** S · **Model:** Sonnet writes, integrator reviews · **Kind:** R

- **Trigger:** ADR 0030 points 1-2 and 5 replace the layer rule `cli -> core -> edges`.
- **Goal:** `CONTRIBUTING.md` "Package layout" describes the context packages, the two-level rule,
  the dependency table and the 700-line ceiling; `AGENTS.md` change contract item 4 names the
  import contracts instead of the three layers; `specs/test-framework.md` "Lanes and placement"
  (2.21.0) describes mirror placement, markers as lanes, `tests/fixtures/`, `contracts/`, `e2e/`,
  `architecture/`, `release/`, and the end of `SUBJECT`; CLAUDE.md "Architecture" points to the ADR.
  ADR 0030, the ROADMAP rows and the §4.5 amendment landed with the plan (2026-10-20).
- **Non-goals:** moving any code.
- **Acceptance:** the three documents agree with the ADR's dependency table word for word where
  they cite it; `validate-specs.sh` and the agent-lane prose tests pass.
- **Gates:** `validate-specs.sh`, `tests/release` prose tests, `gen_cli_docs --check`.

### P46-2 — `analyze.py`: the measurements and the first mapping

**Status:** DONE 2026-10-23 (`be324579`) · **Size:** M · **Model:** Sonnet · **Kind:** T (tool with tests)

- **Goal:** `scripts/maint/refactor/analyze.py` writes `refactor/analysis.json` + markdown: import
  graph and SCCs (top-level and with local imports, via `grimp`); every function-local `docket`
  import (file, line); call-graph groups for `core/dispatch.py`, `serve.py`,
  `edges/adapters/system.py` (definitions, line ranges, external callers); every `["status"] =`
  site with the fields set in the same block and its caller; every
  monkeypatch target with the module that defines the patched object; fan-in per task-record key;
  whether `runs.json` duplicates `task["hops"]`. `--metrics` prints the nine gate numbers.
  `--draft-map` emits `refactor/target-map.toml` from the groups and ADR 0030 "Target layout".
- **Non-goals:** changing any file under `src/` or `tests/`; counting `config.*` reads (that is
  `measure_kernel_adoption.py config-reads`, already a guard).
- **Acceptance:** on its base commit the metrics equal an independent count (`rg`/`ast`) of local
  imports, largest cycle, `status` writers and largest module; the 2026-10-20 numbers (206, 38,
  16, 4727) no longer hold after P46-5 and Wave 120; on `tests/architecture/fixtures/toy/` the groups and
  SCCs match the fixture's expected JSON. Oracle: the tool's own tests.
- **RED test:** the toy fixture's expected JSON before the tool exists.
- **Gates:** ruff, mypy on the script, its tests; `comment_lint`.

### P46-3 — `move.py` and `refactor_gate.sh`

**Status:** DONE 2026-10-23 (`84a332b1`, `85efef83`) · **Size:** L · **Model:** Sonnet · **Kind:** T (tool with tests)

- **Goal:** `scripts/maint/refactor/move.py` (libcst) executes `target-map.toml`: `git mv` whole
  modules; move named definitions with leading comments and decorators in mapping order; rewrite
  `import`/`from … import` in `src/`, `tests/`, `benchmarks/`, `scripts/`, `examples/` and
  `packages/` (code outside `src/` imports `docket.*`; missing one fails only the docs job);
  in `specs/` only the `## Implementation` sections name paths; rewrite `"docket.a.b"` string targets and
  `SUBJECT`; move each test file to its `SUBJECT` module's mirror path, splitting a file by
  symbol when its tests import two destinations; rewrite code paths in `specs/`, `docs/` (not
  `cycles-ended/`, not `adr/`), `CONTRIBUTING.md`, `AGENTS.md`, `.agents/skills/`; `ruff --fix`;
  maintain `refactor/retired.txt`. Flags `--dry-run`, `--check`; idempotent.
  `scripts/maint/refactor_gate.sh` runs the nine checks of ADR 0030 and exits non-zero on the
  first failure, printing which.
- **Non-goals:** running the mapping on the real tree (that is P46-7 onwards).
- **Acceptance:** on the toy fixture, three mappings (whole module, split by definition, test
  split by symbol) produce the expected trees byte for byte and `--check` passes afterwards;
  `--dry-run` on the real tree with the P46-2 draft lists only mapped files and changes nothing.
- **RED test:** the expected trees before the tool exists.
- **Gates:** ruff, mypy on the scripts, their tests.

### P46-4 — `tests/architecture/`, the ratchets and the markers

**Status:** TODO · stage 4, after P46-2, P46-3 and P46-5 · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Folded defect 69** (truth pass): `pytest-without-sandbox.sh` runs in no CI job (CI gets a
  `-m "not sandbox"` job on a runner with `DOCKET_SANDBOX_PROBE=none`); the `slow` marker is
  registered and used by nothing (use it or drop it); 15 test files exceed 800 lines with no guard
  (`test_module_size.py` covers `tests/` with its own ceiling).
- **Goal:** move every guard (27, the two `kernel` guards included) to `tests/architecture/` and the 18 agent-lane files to
  `tests/release/` (by `move.py`). Add `test_import_contracts.py` (import-linter, ADR 0030
  dependency table, current violations in a baseline ignore list), `test_no_local_imports.py`
  (baseline 206), `test_module_size.py` (ceiling = current largest, target 700),
  `test_status_writers.py` (baseline 16, target 1), `test_ids.py` (`test_ids.txt` manifest; a
  missing id needs a `retired:` line in the commit), and the autouse fixture in `tests/conftest.py`
  wrapping `monkeypatch.setattr`: an original whose `__module__` is not the patched module fails
  with `patch the defining module: <module>`. Register markers `unit integration sandbox e2e slow
  release evals`; a codemod adds `pytestmark` by current directory; CI selects by `-m`;
  `testpaths = ["tests"]`; `tests/evals/README.md` states the lane is empty and never in CI.
- **Acceptance:** the gate passes with every baseline at its measured value; in a scratch branch
  one added local import, one `status` write and one patch on a re-exporting module each fail the
  gate (seen to fail, reverted); `-m "not sandbox"` collects what `pytest-without-sandbox.sh` did.
- **Gates:** `refactor_gate.sh`.

### P46-5 — `kernel/` and `Home`

**Status:** IN-PROGRESS · step 1 DONE 2026-10-22, steps 2-3 in stages 1-3 · **Size:** L · **Model:** per step · **Kind:** T + R

- **Step 1: DONE (2026-10-22).**
  - `kernel/home.py::Home` was written by hand, not generated. `tests/integration/test_home_parity.py` pins that it equals `config.py`, name for name and default for default.
  - Beside it: `current_home()`, `use_home()`, `kernel/clock.py` (`use_clock`), `kernel/ids.py`, `kernel/errors.py` (`DocketError` and the kinds `InvalidInput`, `NotFound`, `Conflict`, `Refused`, `Unavailable`, `DocumentError`) and `kernel/text.py` (`cut_chars`, `cut_output`, `ellipsize`, `one_line`).
  - `tests/guards/test_kernel_is_a_leaf.py` checks that kernel imports nothing from docket.
  - `tests/guards/test_kernel_adoption.py` with its baseline is a strict-equality ratchet: a count may neither rise nor fall without the baseline changing.
  - `adopt_kernel.py` has the rules `ids`, `text`, `clock` and `wrappers`. It rewrote 9 id sites, the text sites, 62 clock sites and 74 wrapper calls, and deleted 13 wrappers.
  - The runtime build hook lists the kernel files.
  - A `ContextVar` does not reach a thread docket spawns: a threaded test re-enters `use_clock` in the thread.
- **Step 2, errors: rule and run DONE (`36867d97`); the `DocketError` catcher at the CLI entry and the HTTP handler is still open.**
  - Opus writes the table that sends each of the 36 builtin-derived classes to a kind.
  - A Sonnet worker adds the rule `errors` to `adopt_kernel.py` (re-parent per the table; `raise ValueError(x)` → `raise InvalidInput(x)`; refuse a raise with more than one argument) and its toy tests.
  - The same worker adds one catcher of `DocketError` at the CLI entry and one in the HTTP handler. It first checks the `except ValueError` sites in `serve.py` (~219, ~991, ~1162).
  - The 2 `RuntimeError` raises are migrated by hand.
- **Step 3, home (stage 1 writes the rules, stage 3 runs them).**
  - A Sonnet worker adds the rules `config-reads` (`config.NAME` → `current_home().name`) and `repointers` (→ `use_home(Home(tmp_path))`) with toy tests. Today the codemod has no tests of its own.
  - `config-reads` refuses a read at import time and lists it, because a module-level read freezes the default home.
  - The same worker handles the 34 `environ` sites outside `config.py` from the measurer's list: each becomes a `Home` field or stays at an entry point.
  - Then `config.py` keeps only template lookups and moves to `kernel/`. `test_home_parity.py`, `tests/guards/test_partial_repointers.py` and its baseline are deleted.
- **Step 3 rules: DONE (`cf96f6cf`), measured with `--check` on 2026-10-23.**
  - `config-reads` rewrites 799 sites (373 in src, 426 in tests) and refuses 297. Of the refusals, 216 are tests that monkeypatch one config constant; they need a third rule (`monkeypatch.setattr(config, NAME, v)` → a `Home` override). 16 are import-time reads in src, and 56 are names with no `Home` field.
  - `repointers` rewrites 123 of 190 sites. 57 helpers whose repoint outlives them and 10 thread-starting functions are converted by hand.
  - Run `config-reads` before `repointers`.
  - `Home` needs `secrets_file` and `secrets_meta_file`. `secrets_backend_requested`, `no_trace` and `no_export` still need a landing place.
  - The environ table is in `.agents/handoffs/p46-5-environ-decisions.md` (34 sites to 25).
  - **Decision (integrator): a thread docket starts runs in its spawner's context.** A `ContextVar` home does not reach `ThreadingHTTPServer` handler threads: 39 serve tests fail after the rules. One kernel helper starts a thread in `contextvars.copy_context()`, and the HTTP server runs each request in the context captured when it starts. That is also the product's behaviour: the server serves the home it started with.
- **Stage 3 lanes: DONE (2026-10-23).** Packets in `.agents/handoffs/p46-5-stage-3-packets.md`.
  - Lane B, the rule `config-patches` (merge `b64f4b6d`). It rewrites `monkeypatch.setattr(config, NAME, v)` to `with use_home(dataclasses.replace(current_home(), <field>=v)):`. The real count is 197 patch sites, not 216: 138 rewritten, 59 refused (29 derived properties with no field, 14 in thread functions, 11 helpers whose patch outlives them, 2 in the `conftest` `_DOCKET_HOME_PATHS` loop, 3 others). The order is `config-reads`, `config-patches`, `repointers`; `--write` with no rule names runs them as three passes in that order.
  - Lane A, `kernel/threads.py` (merge `70a12775`): `start_thread`, `new_thread`, `submit` and `ContextHTTPServer`; every thread in `src/` goes through it, pinned by `tests/guards/test_threads_carry_context.py`. With the rules applied and `repoint_docket_home` converted by hand, serve-test failures go from 78 to 8; the 8 are fixed by the single pass (fixtures that build the server before they repoint, `_cfg` aliases, one bare thread in a test).
- **Stage 3a: `src/` before the single pass.** Packet `.agents/handoffs/p46-5-stage-3a-packet.md`: `Home.secrets_file`/`secrets_meta_file`, landing places for `secrets_backend_requested`, `no_trace`, `no_export` and `mkdir_private`, the import-time reads, the environ table.
- **Then the single pass:** the three rules once over the tree, then by hand 57 helper repointers, 24 thread functions, 11 helper patches, 29 derived-property patches and the `conftest` fixtures.
- **Text, settled.**
  - `approval._audit_field` caps at 513 characters while the audit spec says 512: it becomes `ellipsize(x, 512)`.
  - `…[+N chars]` (`cli/_setup_export.py`) and `[diff truncated …]` (`system.py`) keep their own format, one user each.
  - `_cut_at_word` stays in dispatch, because only one context uses it.
- **Acceptance.**
  - A new test runs two `use_home` blocks and asserts their files are disjoint.
  - Adoption counts are `clock 0`, `ids 0`, `text 0`, `error-classes 0`, `error-raises 0`, `config-reads 0` and `repointers 0`. `environ` keeps only the entry-point sites step 3 listed.
  - The partial-repointer guard is gone, and `adopt_kernel.py --check` reports 0 sites.
  - The full suite and the goldens pass unchanged.
- **Gates:** CLAUDE.md "Running tests", plus `refactor_gate.sh` once P46-3 lands.

## ◇ WAVE 120 — the defects the specs truth pass found (before P46-6; stages 1-3 above)

> **Trigger.** The truth pass of 2026-10-22 checked every spec against the code and recorded 87
> code defects with file:line evidence. The specs state today's behaviour, defects included. The
> numbers below are the pass's defect numbers; the log is the gitignored
> `internal-docs/audits/specs-truth-pass-2026-10-22.md`. Each card names the file and the
> behaviour, so a worker does not need the log.
>
> **Folded into other cards, not here:**
>
> - 8, 51, 56 → P46-12
> - 10, 67 → P46-11
> - 14 → P46-9
> - 62 → P46-10
> - 69 → P46-4, plus the golden count in CLAUDE.md, which the integrator fixes
> - 27 and the first half of 74 → follow-ups
>
> **Duplicates:** 83 is the same defect as 30, and 87 as 60.
>
> **Why this wave runs before P46-6:**
>
> - The freeze forbids `src/` edits from P46-6 to P46-15.
> - The baseline live run must include the fixes, so that before and after compare the same
>   behaviour.
> - P46-9 requires byte-identical HTTP responses, so every byte change lands now.
>
> A fix made in the old layout costs nothing extra: the codemod moves it.
>
> **Rules for every W120 card.**
>
> - **The owning spec changes with the code.** The worker rewrites the requirement it changes and
>   no other. The integrator bumps versions (`bump.sh`) once per spec per batch.
> - **RED first.** A defect marked *unverified* is first reproduced by the RED test. If it does
>   not reproduce, the worker drops it and says so.
> - **Ownership is by function.** A card edits only the functions it names. Shared files are
>   noted per card, and the card order is the merge order inside a batch.
> - **P46-5 rules.**
>   - New raises use the kinds in `kernel.errors`.
>   - Clock, id and text reads go through `kernel.clock`, `kernel.ids` and `kernel.text`.
>   - A rise in `repointers`, `config-reads`, `environ` or `error-raises` is written with
>     `measure_kernel_adoption.py --write` and reported.
> - **Probes** follow the rule in `.agents/handoffs/specs-truth-pass-worker-packets.md`:
>   - Run in a throwaway home: `d=$(mktemp -d)`, then `cd "$d"`.
>   - Remove it with `rm -rf "$d"`.
>   - Never touch `~/.docket` and never call a hosted service.
> - **Gates.**
>   - `ruff`, `ruff format --check`, `mypy src` and the tests you touched.
>   - Then `uv run pytest`.
>   - Then `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all`. A golden changes only when
>     the card says its output changes, and the diff is explained.
>   - `validate-specs.sh`, `gen_cli_docs.py --check`, and `comment_lint.py --check` on the files
>     you touched.

### W120-1 — a pod's own rules apply on every screen

**Status:** DONE 2026-10-23 (`a11594c8`, Opus review passed) · **Size:** M · **Model:** Sonnet, Opus review · **Kind:** fix (security)

- **Defect 39.** `policy_eval_detail` is called without `project`, so a pod-only policy is
  skipped, at these sites:
  - enqueue `pre_input`: `core/dispatch.py` ~328
  - a hop's `pre_output`: ~2077
  - Telegram `/delegate`: `core/telegram.py` ~291
  - approval reasons: `core/approval.py` ~67, ~381, ~416
  - answers: `core/answers.py` ~123

  `tools.py`, `identity.py`, `pod_memory.py` and `mcp_tools.py` already pass it.
- **Defect 20.** Dispatch and `docket run` resolve the plan with `load_registry()` without a
  project, so the `gateContract` of a role defined only in the pod is lost and its step runs
  ungated. Sites: `dispatch.py` ~2981, `cli/_run.py` ~228 and ~365, `cli/_pod_config.py` ~395.
- **Defect 40.** `docket pod check` ignores the pod's `allowCommands` (`cli/_pod_config.py`
  ~437), so the dry run asks where the gate allows.
- **Owns** exactly those call sites. Shared files:
  - `dispatch.py` with W120-8 and W120-12
  - `telegram.py` with W120-10
  - `_run.py` with W120-11
  - `_pod_config.py` with W120-9
- **RED tests**, each using a pod-only policy or role:
  - enqueue is refused
  - a hop's output is blocked
  - `/delegate` is refused
  - the gate contract gates the step
  - `pod check` reports what the live gate decides
- **Specs:** security-gates, role-archetypes.

### W120-2 — `docket init` and provisioning leave alone what they did not create

**Status:** DONE 2026-10-23 (`346ec94c`, `1d8ac5c7`, Opus review passed) · **Size:** L · **Model:** Sonnet, Opus review · **Kind:** fix, security items first

- **Security defects.**
  - 60/87: provisioning runs `chmod 700` on a workdir it did not create, the cwd included
    (`core/pod_provisioning.py` ~848). The repo ended at mode 700 during the pass.
  - 82: removing the last implementer deletes all of `pods/<pod>/` (`remove_member` →
    `free_pod_resources` → `shutil.rmtree`). That loses `memory.json`, `config/` and the cache.
  - Q5: delete the `--from` path for entries without a blueprint (`cli/_agents.py` ~463-673).
    Defects 36, 37, 84 and 86 go with it; 36 is a path traversal (`{"id": "../escaped"}` creates
    `workspaces/escaped`).
  - 70: `init` run from a directory that holds `.docket/` (for example `~` with the default home)
    applies that directory as a team configuration. *Unverified.*
- **UX defects.**
  - 30/83: an empty slug answers "already exists".
  - 31: a name longer than 64 characters ends in a traceback.
  - 32: a relative or missing codebase is stored as given.
  - 58: `init --json` prints text on `code_mismatch` and on `refused`.
  - 85: Rich eats `[a-z0-9]` in the invalid-id message.
  - 74, second half: a standalone `SOUL.md` writes `agent:<id>:default` while the meta keeps
    another `projectKey`.
- **Owns** `cli/_agents.py`, `core/pod_provisioning.py`, and only the repository-config
  discovery in `core/pod_apply.py`, which it shares with W120-9.
- **RED tests:**
  - a pre-existing workdir keeps its mode
  - removing the last implementer keeps `pods/<pod>/memory.json`
  - a `--from` entry without a blueprint is refused
  - `init` from a directory holding the home applies nothing
  - one refusal per UX defect, with exit 2 and `--json` output that parses
- **Specs:** agent-lifecycle, cli-interface, input-validation, workspace-structure,
  session-scoping.

### W120-3 — the trace and the exporters tell the truth

**Status:** DONE 2026-10-23 (`ddd475d8`) · **Size:** M · **Model:** Sonnet · **Kind:** fix and deletion

- **Defects.**
  - 2: `terminal_outcomes` picks the "latest" sessions by file name (`task-<uuid4>`), so `status`
    shows random ones. The test passes only because it names its sessions `a` and `b`.
  - 3: `sweep_all`'s synthetic `session_end` reaches no subscriber and ignores
    `DOCKET_NO_TRACE`.
  - 12: a JSON line that is not an object breaks `export_lines` and `GET /traces`.
    *Unverified.*
  - 18: `enable_exporter --privacy` over a stored `share`, or the reverse, writes an invalid
    entry. The load drops it in silence, yet `exporter.enabled` is audited.
  - 19: `set_privacy(content_max_chars=0)` writes an invalid entry the same way.
  - The fix for 18 and 19: both writers validate before they write and refuse with
    `InvalidInput`; the audit entry is written only on success.
- **Deletions.**
  - 1: `trace_ingest` has no production caller and imports `edges` from `core`.
  - 4: `drift_alert` is in `EVENT_TYPES` and the telemetry map, and nothing emits it.
- **Reproduce or drop.** 5: `run_bash` on an exception other than `TimeoutExpired` (`toolbox.py`
  ~441).
- **Owns** `core/trace.py`, `core/exporter.py`, the `EVENT_TYPES` map in `core/telemetry.py`, and
  `run_bash`.
- **Specs:** trace-store, observability-export.

### W120-4 — the pipeline loader refuses what it cannot run

**Status:** DONE 2026-10-23 (`33fbf1d3`, `ae459abc`) · **Size:** M · **Model:** Sonnet · **Kind:** fix

- **Defect 53.** The loader accepts each of these in silence:
  - `run`, `input`, `when` or `archetype` on a `parallel` group
  - a step that has both `run` and `input`
  - an invalid `max` on a forward route
  - an unvalidated `on` on a parallel child, where YAML's `on` → `True` is not corrected either
  - the `from` of a child `input`

  The places are `Step._check_shape`, `PipelineSpec._check` and `_fix_on_key`.
- **Defect 54.** `test_validate_pipeline_wrapper_matches_load` compares a value with itself.
  Delete it, or make it compare against `load`.
- **Owns** `core/pipeline.py` and its tests.
- **RED tests:** one per shape. `docket pod validate` names the field and exits non-zero, and
  every shipped recipe still loads.
- **Spec:** pipeline-format.

### W120-5 — providers and secrets fail loudly and store nothing on failure

**Status:** DONE 2026-10-23 (`5eb6fd9d`) · **Size:** M · **Model:** Sonnet · **Kind:** fix

- **Defect 44.** A global document with empty `presets` makes `load_registry()` raise
  `KeyError: 'economy'`. Instead, raise a `DocumentError` that names the missing anchor, both at
  load and at `provider add`.
- **Defect 43.** `setup provider add <catalog> --ctx N` with neither a URL nor `--model` ignores
  `--ctx` and `--max-tokens`. With a URL or `--model` over a built-in, it replaces `models[]` with
  one unpriced row. Fix: apply the flag or refuse it, and keep the inherited rows. *Unverified
  live.*
- **Defect 78.** When the probe fails on transport, the credential is stored anyway and the
  output says "Nothing was registered". Fix: store only after the probe.
- **Defect 79.** With `DOCKET_SECRETS_BACKEND=keyring` and no `secret-tool`, secrets are written
  as plain text in silence. Fix: refuse, with a hint.
- **Defect 38.** `credential_add`, `prompt_and_store` and the `_KEY_NAME` grammar have no caller.
  Apply the grammar where a person types a credential name, or delete all three if no such path
  exists.
- **Owns** the loading in `core/models_policy.py`, `cli/_setup_model.py`, `core/secrets.py`, and
  the registration path in `core/provider.py`.
- **Specs:** model-profiles, api-keys, input-validation.

### W120-6 — the HTTP server's own answers

**Status:** DONE 2026-10-23 (`f5d081b0`) · **Size:** S · **Model:** Sonnet · **Kind:** fix (byte changes, before P46-9)

- **Defects.**
  - 11: `/metrics` emits `docket_agent_turns_total` without HELP or TYPE and interleaves it with
    `docket_agent_cost_usd`. With two or more agents the output breaks the 0.0.4 text format.
  - 72: `GET /pods/<p>` does not catch `PodSettingsError`; it must answer with the JSON error
    envelope. `POST /pods/<p>/apply` parses the body before it checks that the pod exists.
  - 13: a run cancelled by the server's second signal records `source: "cli"` (`core/runs.py`
    ~79, ~576). *Unverified.*
  - 33: the `docket start --telegram` hint names `setup provider add TELEGRAM_BOT_TOKEN`; it
    should name `setup notify enable telegram`.
- **Owns** those handlers in `serve.py` and the cancel source in `core/runs.py`.
- **RED tests:** `/metrics` with two agents parses under the exposition rules; a pod with invalid
  settings gets a JSON error body.
- **Specs:** serve-read-api, operator-api.

### W120-7 — the adoption evidence says what it proves

**Status:** DONE 2026-10-23 (`841d86fb`, `8266ae01`) · **Size:** S · **Model:** Sonnet · **Kind:** doc and fix

- **Defect 80 (Q6).** `benchmarks/run.py` writes the run, task, session and trace records
  itself, including a fabricated `guardrail_block`. It calls the CLI only for `run --dry-run`,
  `task approve`, `task deny` and `task show`. `docs/ADOPTION-EVIDENCE.md` and the benchmark
  README must say exactly that, and no sentence may present it as a product run.
- **Defect 81.** `regenerate.py --source-commit` must refuse a dirty tree, and it must replace
  the JSONL and the aggregate together, through a temp file and a rename.
- **Owns** `benchmarks/` and `docs/ADOPTION-EVIDENCE.md`.
- **Spec:** adoption-benchmark. The agent-lane prose tests that read the doc must pass.

### W120-8 — dispatch, answers and the budget unblock

**Status:** DONE 2026-10-23 (`cb3a21c8`) · **Size:** M · **Model:** Sonnet · **Kind:** fix and deletion

- **Deletions (Q2).**
  - 7: the `requireApprovalRoles` reader (`core/interruptions.py` ~85, `dispatch.py` ~1490)
  - 46: the `_policy_requires_approval` stub (~1505)
  - 52: `dispatch_pod(approval_timeout=)`, which has no caller
- **Defects.**
  - 48: `answer_task` places the parked step against the pod's effective pipeline, not the
    task's own pipeline or the one given by `run --pipeline` (`core/answers.py` ~286).
    *Unverified.*
  - 49: `pod set budgetUsd 0` and `pod unset budgetUsd` requeue the blocked tasks but leave the
    Lead paused, so each one is refused at claim.
  - 52: "Unblocked N budget-blocked task(s)" counts every blocked task that `unblock_pod`
    requeues, not only the budget-blocked ones.
  - 50: `dispatch_pod` stops on any `blocked`, including a brief's `resources` block (~4691).
- **Owns** those functions and the unblock in `cli/_pod.py`. It shares `dispatch.py` with
  W120-1, which merges first, and with W120-12.
- **Specs:** pod-dispatch, operator-loop.

### W120-9 — roles and configuration documents follow one rule each

**Status:** DONE 2026-10-23 (`495a11a0`) · **Size:** M · **Model:** Sonnet · **Kind:** fix and deletion

- **Defects.**
  - 21: denying `fetch` in a pod removes every built-in of kind `read` (read, glob, grep, skill,
    consult), because the denial goes by kind. The test only checks that `fetch` is gone. Fix: a
    built-in denial removes that built-in alone; MCP tools keep the capability rule (CLAUDE.md
    limit 1).
  - 22: `pod validate` never dry-runs the role templates (`validate_archetype_dict` has no
    caller), so a `${typo}` passes validation and fails at provisioning.
  - 23: the short-form `model:` error sends the user to `docket setup model set <role>`, which
    refuses any role outside the ten named ones.
  - 59: `roles/*.yml` and `roles/*.json` are validated and counted, but `_plan_roles` applies
    only `*.yaml`. Fix: one glob for all three.
  - 34: `pod recipes --json` emits `mcp_servers` and omits `exporters`.
  - 6 (Q1): the analyst/critic model class, per the decision table.
- **Deletions (Q3).**
  - 24: the `org` scope and the reader of the global `docket-roles.json`
  - 66: the `kind:`-less path (`config_docs.py` ~177-197). A document without `kind:` gets its
    parser's real error or the `kind` error.
- **Owns** `core/archetypes.py`, `core/config_docs.py`, `_plan_roles` in `core/pod_apply.py`,
  `ROLE_CLASS`, and the recipes and scope functions in `cli/_pod_config.py`.
- **Specs:** role-archetypes, model-profiles, config-format, pod-blueprints, cli-json-shapes.

### W120-10 — channels and Telegram deliver and refuse correctly

**Status:** DONE 2026-10-23 (`efda73d2`, `573a9385`) · **Size:** M · **Model:** Sonnet · **Kind:** fix

- **Defects.**
  - 25: the shipped `email` channel never delivers. The template sets `to`, `from` and
    `smtpHost`; the dialect reads `host`, `user` and `to`, and always demands a secret. Fix: one
    set of keys, and a secret only when auth is set. RED against a local SMTP stub.
  - 26: `notify.flush` says "never raises" but guards neither `build_inbox` nor the store reads,
    and `docket run` calls it unguarded. *Unverified.*
  - 63: with the keyring backend the bot reads `""` from `secrets.json`. Fix: read the token
    through the secrets backend. *Unverified.*
  - 64: `_DELEGATE_RE` has no word boundary, so `/delegatefoo bar` enqueues "foo bar".
  - 65 (Q4): `/approve` and `/deny` accept another pod's token, per the decision table.
- **Folded follow-up: two enqueue entry points.** Its trigger was the next edit of
  `telegram.py`. Keep one enqueue function and move its callers in `telegram.py` and
  `cli/_mcp.py` to it.
- **Owns** `edges/adapters/channels/email.py`, `templates/channels/06-email.yaml`,
  `core/notify.py`, `core/telegram.py` except the `/delegate` screen that W120-1 changes, and
  `cli/_setup_notify.py`.
- **Specs:** operator-loop, telegram-integration.

### W120-11 — the CLI's own output is honest

**Status:** DONE 2026-10-23 (`202c28fe`) · **Size:** M · **Model:** Sonnet · **Kind:** fix

- **Defects.**
  - 75: the `docket run` header prints `spent $0.00` next to the real cap, but recorded spend is
    always 0. Show the labelled estimate and the cap only.
  - 76: no command shows `paused` or `pausedReason`. `status` shows both, in text and in
    `--json`.
  - 55: `setup --fix --json` prints `ok Installed N baseline policies` before the JSON. That line
    goes to stderr.
  - 35: `docket log abc` exits 2 with "No such command". Print a usage message naming the
    argument, and drop `scope` from the empty-log message.
  - 41: the approval prompt in `docket run` catches only `ApprovalNoop`, so an
    `ApprovalConflict` escapes the progress loop (`cli/_progress.py` ~139). *Unverified.*
  - 71: the help of `setup --fix` claims repairs it does not make. It also requires `TOOLS.md`
    from every Implementer, though provisioning does not always write it, and the seeds point to
    a daily-log path that does not exist.
  - 57: `cli/_mcp.py` keeps its own copy of `cost_snapshot`. Keep one function.
- **Folded follow-up: queue counts twice.** `status` uses `pod_report.task_counts`.
- **Owns** `cli/_log.py`, `cli/_setup.py`, `cli/_setup_check.py`, `cli/_status.py`,
  `cli/_progress.py`, the header in `cli/_run.py`, and the cost function in `cli/_mcp.py`.
- **Specs:** cli-interface, cli-json-shapes, cost-tracking, workspace-structure.

### W120-12 — the runtime facade counts tokens as the loop does

**Status:** DONE 2026-10-23 (`7e14b128`) · **Size:** M · **Model:** Sonnet · **Kind:** fix (the facade's output changes, so it lands before the baseline)

- **Defects.**
  - 61: the `docket_runtime` envelope counts `total_tokens` (input + output), while the loop
    counts `counted_tokens` (input − cache + output). Cache writes are never summed
    (`_execution.py` ~57).
  - 15: the `RuntimeDriver.run_turn` port has no `trace_task_id`, although both drivers take
    one, and dispatch calls `default_driver()` around the port (`runtime_driver.py` ~241,
    `dispatch.py` ~2008).
  - 16: `consult_park` is chosen on `trace_task_id is not None` instead of a non-empty value.
    *Unverified.*
  - 17: a composition that holds only the runtime contract sends a system prompt but emits no
    `prompt_composed` (`agent_loop.py` ~929). *Unverified.*
- **Owns** those functions; mypy proves the port.
- **Specs:** runtime-library, agent-loop.

### W120-13 — stale text and dead code

**Status:** DONE 2026-10-23 (`97bb82c2`, `cfcbed86`) · **Size:** S · **Model:** Haiku · **Kind:** text, and deletions with a zero-caller proof

- **Text.**
  - 9: the `mcp_client._stdio_params` docstring names an opt-out that does not exist, and
    `mcp_tools.py` ~439 says "will call once wired" about a path that is already wired.
  - 29: `cli/_setup_sandbox.py` ~362 names "doctor". Name the real command, as `--help` shows it.
  - 45: "Model intent per agent" in `models_policy.py` ~266, `pipeline.py` ~258,
    `test_models_policy.py` ~93 and `pipeline-format.spec.md` ~220; `MODEL_PRICING` in the
    comments at `cli/_mcp.py` ~265 and `docket_runtime.py` ~801.
  - 68: `pyproject.toml` ~74, ~86 and ~134 name `docket mcp serve`; the `test_all_ten_tools_*`
    tests check 13 tools; the `queue` and `load_session` docstrings are wrong.
  - 77: `examples/starter/README.md` ~54-62 says the starter runs `docket task list`, but it only
    prints that line.
- **Dead code.** Delete each item with its tests, after `rg` shows no caller:
  - 28: `cli/_flags.py::find_unknown_flag`
  - 42: `system.register_credential_name`
  - 47: `HandoffArtifact.notes`, its `render` branch and its `DROP_ORDER` entry
  - 73: `store.read_json_readonly`
  - Folded follow-up, dead since the harness was deleted:
    - `verify["touched"]`
    - `git_worktree_fingerprint`, if nothing else uses it
    - evidence 1.0.0: `EVIDENCE_V1`, `docs/contracts/evidence-v1`,
      `scripts/gen_evidence_schema.py` and its CI step
- **Stop rule:** if a caller turns up, stop and report. A model does not decide a deletion.

### P46-6 — `bootstrap.py`, the composition root

**Status:** TODO after P46-5 · **Size:** M · **Model:** Sonnet · **Kind:** T + R

- **Goal:** plain functions `build_store`, `build_sandbox`, `build_driver`, `build_channels`,
  `build_app` (CLI), `build_server` (HTTP), each taking a `Home`; the CLI entry and `serve` call
  them once. No registry, no framework. Import-linter contract: only `bootstrap` and `interfaces`
  import `*/adapters` (added to the ignore-list ratchet).
- **Before this card the integrator records the baseline live run** (ADR 0030 P46-15):
  `capture-doc-journey.sh` on the local model plus one HTTP dispatch, trace files kept under
  `refactor/baseline/`.
- **Acceptance:** the gate; `docket --help` golden unchanged; `serve` starts from `build_server`.
- **Gates:** `refactor_gate.sh`.

### P46-7 — split `core/dispatch.py`

**Status:** TODO after P46-6 · **Size:** L · **Model:** codemod · **Kind:** T + R

- **The draft map does not apply yet** (`move.py --dry-run` on 2026-10-23: 203 file moves and 2208 test-id changes, then rc 2). Two mapping problems:
  - `_store` clashes in `docket.hops.workspace.prepare`. Rename one of the two before the move.
  - `global _sweep_stop` is split across serve, sweep and the HTTP server. Give that state one owner, as an object or a setter.
- **The map's end state has four top-level import cycles**: about 24 modules across agent/hops/governance, 6 across platform/sandbox, 3 in interfaces.http and 2 between tasks lifecycle and sweep. Each P46 move commit applies a leaf-first slice of the map, never the whole file.
- **analyze.py prints nine metrics the worker chose**; the ADR names five. Before P46-4 records the baseline, reconcile that list with `refactor_gate.sh` check 9.

- **Goal:** the reviewed mapping assigns the 168 definitions to `tasks/application/` (`queue`,
  `lifecycle`, `actions`, `approvals`, `sweep`), `tasks/domain/task.py` (shared types),
  `pipeline/application/executor.py`, `hops/application/` (`compose`, `runner`, `record`),
  `hops/gates/` (`pre_hop`, `post_hop`), `hops/workspace/*`, `teams/settings.py` (the `pod_*`
  readers). One commit per destination, leaf-first. The six externally used private names become
  public in their module; the 24 importers are rewritten in the same commit (no re-export, D-57).
  `HopResult`/`TaskResult` become frozen with `with_*` methods; the four mutators return values.
- **Non-goals:** changing any transition (P46-12), any persisted shape (P46-11).
- **Spec amendment (truth pass):** `DispatchError` is raised from the agent layer through a lazy
  import of `core.dispatch`, the agent→tasks edge the ADR forbids; it moves to `tasks/domain` and
  the agent side raises a `kernel.errors` kind (agent-loop, mcp-client `## Implementation`).
- **Acceptance:** `core/dispatch.py` does not exist; largest resulting module ≤ 700; the 72
  `dispatch` patches are on their defining modules (the P46-4 fixture proves it); manifest ids
  unchanged under new paths; the gate passes after every commit.
- **Gates:** `refactor_gate.sh` per commit.

### P46-8 — every remaining module to its context

**Status:** TODO after P46-7 · **Size:** L · **Model:** codemod · **Kind:** T

- **Goal:** one commit per context, leaf-first: `platform`, `models`, `observability`,
  `operator`, `sandbox`, `governance`, `teams`, `agent`, `tasks`, `pipeline`, `hops`,
  `interfaces` (cli commands, mcp, telegram entry). `edges/adapters/system.py` splits into
  `platform/process.py`, `platform/git.py`, `sandbox/launch.py` by the P46-2 groups; `jail.py` and
  `plugins.py` leave the package root. Mirror tests, specs and live docs rewritten per commit.
  `python -m docket.jail` and `docket.plugins` / `REGISTRY` are public names (security-gates):
  they keep working at the same names.
- **Acceptance:** `src/docket/cli`, `core` and `edges` do not exist; the import-linter ignore
  list is exactly the remaining domain→adapter edges (printed by `analyze.py`); the gate passes
  per commit.
- **Gates:** `refactor_gate.sh` per commit.

### P46-9 — split `serve.py`

**Status:** TODO after P46-8 · **Size:** M · **Model:** codemod · **Kind:** T + R

- **Goal:** a codemod lifts each path branch of `do_GET`/`do_POST` into
  `interfaces/http/routes/<resource>.py` (tasks, pods, approvals, inbox, traces, health, metrics,
  dispatch) and generates the `(method, pattern) -> handler` table; `interfaces/http/auth.py`
  holds the bearer check once; `interfaces/http/server.py` holds the handler class, threads and
  stop controller.
- **Folded defect 14:** the `docket start` "Endpoints:" banner lists 6 of 21 routes; it prints
  from the generated route table.
- **Spec amendment:** serve-read-api and operator-api both describe `/health`, `ensure`, the
  `POST /tasks` table and the `GET /tasks` filters; one spec owns each, the other links.
- **Acceptance:** `SERVE_API_VERSION` and every response byte-identical (the serve tests move
  beside their route and pass unchanged); `serve.py` does not exist.
- **Gates:** `refactor_gate.sh`.

### P46-10 — the runtime is a package, not a build hook

**Status:** TODO after P46-8 · **Size:** M · **Model:** Sonnet · **Kind:** T

- **Goal:** with the contract "`agent` imports `kernel` only" green, delete
  `packages/docket-runtime/hatch_build.py` and its 40-file closure; the distribution includes
  `docket/agent` and `docket/kernel`; `docket_runtime/__init__.py` re-exports the same facade names.
- **Folded defect 62:** the hook's copied closure is not closed: several copied modules
  (`docket_runtime`, `exporter`, `telemetry`, `llm`, …) fail to import in a clean venv while the
  facade imports; deleting the hook closes it.
- **Acceptance:** `uv build` in a clean venv, `import docket_runtime` exposes the same names and
  every module in the distribution imports;
  `tests/release/test_runtime_package_boundary.py` passes with the hook gone.
- **Gates:** `refactor_gate.sh`, `tests/release`.

### P46-11 — persisted shapes the structure wants (D-57)

**Status:** TODO after P46-9 · **Size:** M · **Model:** Sonnet · **Kind:** T + R

- **Goal:** the task record is written nested (`spec`, `lifecycle`, `execution`, `pending`) with
  the same camelCase field names inside (the API serializer flattens, so responses are
  unchanged); pod settings move from the Lead's `.docket-meta.json` to `pods/<pod>/settings.json`;
  `TASK_LIST.json` stays one document per pod. Old-shape readers are deleted, not kept.
- **Non-goals:** one file per task (measured trigger); any API change.
- **Folded defects:** 10 — `answer_task` clears `question` and the answer record keeps neither
  `kind` nor `createdAt`, so every answer counts as `clarification` and
  `docket_decision_latency_seconds_count` stays 0 (the test seeds a shape the writer never
  produces): the nested `pending` keeps both; 67 — `budgetUsd` is a string after provisioning
  and the flat `--from`, a float after `pod set`, and `AgentMeta.budget_usd` has no `ge=0`: one
  number type, `>= 0`, in `settings.json`.
- **Spec amendments** (from the truth pass, each spec states today's shape): agent-loop req 18
  and 30 (`mcpServers`, `projectInstructions`, `worktree.*`), operator-loop (Lead settings
  `requireApprovalRoles` if Q2 keeps it, `approvalMode`, `approvalExpiryHours`; flat task fields
  `taskGrants`, `pregrants`, `answers[]`, `question`, `consultations`), cli-interface
  (`TASK_LIST.json` location, `worktree.prunedAt`, `approvalToken`), mcp-client (`mcpServers`),
  security-gates (profile, `readOnly`, `network`; `failureKind`, `approvalToken`,
  `worktree.gitDir`), pod-dispatch (~25 sections), serve-read-api (the task field set),
  agent-lifecycle and user-stories (`paused`, `budgetUsd` on the Lead's meta).
- **Acceptance:** operator-api and serve-read-api tests unchanged; the gate; the operator wipes
  and re-initializes the live `~/.docket` after it lands (no users, no migration) and one
  dispatch on the local model runs to `done`.
- **Gates:** `refactor_gate.sh`.

### P46-12 — one owner of the task's state

**Status:** TODO after P46-7 · **Size:** M · **Model:** Sonnet (one attempt) · **Kind:** M + T

- **Input:** the P46-2 table of 16 sites (from, to, fields, caller).
- **Goal:** `tasks/domain/state.py`: `Status`, `FailureKind` enums, the allowed-transition table,
  `transition(record, to, *, reason="", failure_kind=None, ...)` setting exactly each
  transition's fields (`completedAt`, `claimId=None`, `pending=None` on a terminal state). A
  codemod replaces the 16 sites by AST location. A test **generated from the table**: each allowed
  transition sets its fields; each other pair raises `IllegalTransition`.
  `test_status_writers.py` ratchets to 1.
- **Non-goals:** adding or removing a transition that exists today.
- **Folded defects:** 8 — `in_progress` is in `TASK_STATUSES` and nothing writes it (not a
  `Status` member); 56 — `status` sums `counts["completed"]`, a state nothing writes; 51 — a task
  gate with no step is left `dispatch_refused` (resumable), claimed by `--resume` and refused
  again, while every other impossible gate ends `pipeline`: the table gives both one state.
- **Spec amendments:** pod-dispatch (~20 sections), operator-loop (`answer_task`, expiry,
  grant/deny transitions), security-gates (the direct `waiting_approval` write).
- **Acceptance:** no behavioural test changes; the generated test passes; the gate passes.
- **Gates:** `refactor_gate.sh`.

### P46-13 — ports for what the ignore list still holds

**Status:** TODO after P46-8 · **Size:** L · **Model:** Sonnet where a signature is unclean · **Kind:** T + M

- **Goal:** for each remaining domain→adapter import, `analyze.py --emit-port` generates a
  `Protocol` from the signatures the domain uses; `bootstrap.py` binds the real adapter; the
  domain receives the port as a parameter or from `current_home()`. A model handles only
  signatures that mix effects, one card per unclean port if more than one.
  `tests/fixtures/fakes/<port>.py` and `tests/contracts/test_<port>_contract.py` (parametrized
  `[real, fake]`) per port.
- **Acceptance:** import-linter ignore list empty; local imports 0; largest SCC 1; every fake
  passes its contract suite; the gate.
- **Gates:** `refactor_gate.sh`.

### P46-14 — the tests only the new structure allows

**Status:** TODO after P46-13 · **Size:** L · **Model:** Sonnet · **Kind:** T + M

- **Goal:** `tests/fixtures/`: `home.py`, `repo.py` (temp git repo with lockfile and commits),
  `builders.py` (`make_task`, `make_pod`, `make_hop`), `fakes/chat.py` (`ScriptedChat`: turns
  with text and tool calls, fails when the script runs out) replacing the 7 LLM stubs.
  `tests/e2e/`: 8-12 named flows extracted from `integration/` (software pod to done, rework
  cycle, check_changed park + grant/deny, prepare from lockfile + cache hit, HTTP lifecycle as
  Tack drives it, resume after restart, lights-out profile, Telegram approval). The flat
  `tests/integration/` directory disappears (mirror path, `e2e/` or `contracts/`); each retired
  test named in `retired:`. `SUBJECT` deleted everywhere; the layout guard checks the mirror path.
- **Acceptance:** no file outside `tests/architecture/` mentions a module path; `analyze.py`
  reports monkeypatch targets only on `kernel.clock` and `os.environ`; the gate.
- **Gates:** `refactor_gate.sh`.

### P46-15 — the live run, before and after, and the close

**Status:** TODO after P46-14 · **Size:** M · **Model:** integrator · **Kind:** R

- **Goal:** repeat the P46-6 baseline runs; compare traces event by event (names, gate outcomes,
  transitions; ids and timestamps masked) and the HTTP responses. Rewrite CLAUDE.md, AGENTS.md,
  the `docket-*` skills and CONTRIBUTING for the new layout (paths by the tool, prose by hand).
  CHANGELOG "Changed (internal)". Delete `refactor/`; the architecture tests are the record.
  ROADMAP row 46 dated; board archived with `split_board.py archive`.
- **Acceptance:** the trace diff is empty; the Phase 46 acceptance above, with numbers.
- **Gates:** every gate in CLAUDE.md "Running tests", in a clean worktree.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phases 43-45 (not cards; triage when a trigger fires)

> Items a Phase 45 card absorbed moved into that card on 2026-10-19 (the gateway window, the
> measurement gaps, the cut commit subject, the group `failure_kind`, the stale `security-gates`
> paragraph, the `inPlace` key, the apply-without-codebase edge, the team-aware hint, the worker
> packet note, the warm workspace, and "no `node_modules` is pod configuration", which ADR 0029
> reversed).

- **Found in the specs truth pass (2026-10-22).**
  - **Notification dedup is in memory only** (`core/notify.py` ~91-118): restarting `docket
    start` resends each pending notification once (unverified). Trigger: an operator reports a
    repeat after a restart.
  - **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`core/pod.py`
    ~86-90); latent, no turn uses the base key as history. Trigger: a turn that reads it.
- **Found while merging Wave 120 (2026-10-23).** Each comes from a worker report and was checked against its branch.
  - **`setup` without `--fix` writes:** its text report re-seeds `WORKFLOW_AUTO.md`. A check that writes is a defect. Trigger: the next edit of `cli/_setup_check.py`.
  - **The seeds point at `memory/YYYY-MM-DD.md`** (`core/memory.py` and the AGENTS.md seed in `cli/_agents.py`), a path docket never creates. Changing it bumps `CONTRACT_VERSION`, so the maintainer decides.
  - **A canonical document without `kind:` still loads with a deprecation advisory** (W120-9 deleted only the short-form path, as Q3 named). Under D-57 the advisory is a notice; either every canonical fixture gains `kind:` or the advisory goes. Trigger: the next edit of `core/config_docs.py`.
  - **`enqueue_task` is kept beside `enqueue_task_once`**, because about 300 test call sites in 40 files use it. Delete it with a script in stage 3 if the two have the same semantics for a fresh task; otherwise each site is a decision.
  - **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`serve.py::_flush_notify_channels`; serve has no logger). → P46-9.
  - **An answer to a task run with `run --pipeline <file>` is placed against the pod's pipeline**, because the file's spec is not persisted on the task (W120-8 fixed the named-pipeline half of defect 48). → P46-11, which reshapes the task record.
  - **Enabling the `email` channel checks nothing**: with no `to`, `from` or `smtpHost`, every delivery fails into the health record. Trigger: an operator enables it.
  - **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**, so the facade's cache-write sum is 0 for them. Trigger: either adapter reports usage someone reads.
  - **`GET /pods` (the list) was not checked** for the invalid-settings failure that W120-6 fixed on `/pods/<p>`. → P46-9's byte-identity check.
- **Found in the Phase 45 real runs (2026-10-20, two runs of one small task on `fab-dev`).**
  - **The implementer sends 0.65 of what the backend counts** (14 and 13 calls, largest request
    ~7,000 estimated tokens), with no toolchain grant needed (`npm` came from the prepared
    `node_modules`). The Phase 44 trigger below ("still sends over half") therefore **fired**:
    triage, then measure which calls repeat before cutting anything. The reviewer sent 0.62, the
    tester 0.80 and 0.90.
  - **A parked turn is still paid twice**, now on a read: the model's first `bash` carries `$(...)`
    ("not statically analysable"), parks every run, and the resumed hop re-sends the whole
    prompt (4,157 input tokens before the park, 8,181 on the first call after). Two runs, same
    call. Trigger: a third run that parks on the same shape; then weigh resuming the session
    over re-running the hop (operator-loop §2 item 6 keeps this a non-goal today).
  - **A hop refused before any call records an empty model**: `hop_finished.model` is `""` and
    `usage.byModel` gains a `""` key with zeros (seen on the budget-refused reviewer). Trigger: a
    reader of `byModel` that trips on the empty key.
  - **Anthropic advertises dated ids** (`claude-haiku-4-5-20251001`) while the template rows use
    aliases (`claude-haiku-4-5`), so an alias row's limits stay `unknown` though the chat route
    accepts the alias. Trigger: a run on an alias id whose window matters.
  - **The shipped price rows lag the models in use**: the pod's steps run `claude-sonnet-5-5` and
    `claude-opus-5-5`, which no template row prices, so `task show` prints `cost: -`. Trigger: an
    operator asking for the estimate; then add rows or let `provider add` take a price file.
  - **Not examined:** each run's trace carries two `approval_denied` events beside the one park.
  - A worker's test with `monkeypatch.undo()` undid the autouse home isolation and wrote into the
    real `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
- **Found integrating Wave 118 (P45-3, 2026-10-19).**
  - **A file a check reaches only through `make` or `npm run` is protected only through the
    default files it reads** (`Makefile` is not a default; `package.json` is). Stated in
    `security-gates.spec.md`. Trigger: a real gate whose script lives behind a target.
  - **A gitignored file is invisible to the check** (`git status` and `git diff` skip it), so a
    tool configuration the repository ignores can be edited without a park. Trigger: a real
    repository that ignores a file its gate reads.
- **Found integrating Wave 117 (P45-1, 2026-10-19).**
  - **Only `node_modules` is cached.** A `.venv` is not relocatable, so `uv sync`, `poetry
    install` and `cargo fetch` run in each task worktree. Trigger: a measured Python or Rust
    prepare that dominates a task's wall clock.
  - **A tool that writes into `node_modules/.cache` fails with isolation on** (the entry is
    read-only in the jail). Trigger: a real gate failing on it.
  - **Eviction can break a running task's link** when a fourth lockfile of one codebase is
    prepared while an older task still runs; resume detects the broken link and prepares again.
    Trigger: a real run that hits it.
  - **Prepare is not cancellable**, like `verifyCmd`; it is bounded by `PREPARE_TIMEOUT_S` (900 s).
  - **A hop that makes its own `node_modules` symlink to another codebase's cache entry gets that
    entry read-only in its jail** (`core/prepare.py::linked_entries` accepts any entry under the
    cache). Installed packages, not secrets; restrict to the task's codebase when next touched.
- **Found integrating Wave 116 batch A (2026-10-18).**
  - **Shell keywords are classified as binaries when unjailed.** `for t in a; do ...; done` asks
    with `'for' is not on the curated allowlist` (also `do`, `done`, `if`, `then`, `while`).
    Jailed, the allowlist stands down and the loop runs. Pre-existing; the run's parked command
    ends in such a loop, so it still asks without the sandbox. Trigger: an operator running
    without isolation reports it.
- **Found in the 2026-10-18 joint run (Wave 116 evidence).**
  - **A parked turn is paid twice.**
    - The development `red` step spent 100,573 input tokens before parking.
    - Its `approve_task` grant went unused: the re-run hop never re-issued the call.
    - The resume added a compaction call (9,065 in) and a cold first call.
    - Trigger: after W116-1..4, a real run that still parks on a write.
    - Then: weigh resuming the session over re-running the hop (operator-loop §2 item 6 keeps
      this a non-goal today).
  - **Hop language drift.** The resumed Sonnet `red` step wrote its final report in Chinese, and
    that report became the `green` step's handoff. This happened once.
    - Trigger: a second occurrence.
    - Then: a pod `language` setting rendered into the handoff instruction.
- **Found at the Phase 44 close.** The two implementer steps of the real rerun did not send under
  half (0.77, 0.80): every request shrank to a fifth to a third, but the trajectories grew (12 and
  20 calls against 8 and 5), partly from retrying a toolchain the jail could not load (now a grant
  and a 126 message). Trigger: a real implementer run with the needed grants declared that still
  sends over half of its 03:38 counterpart; then measure which calls repeat before cutting
  anything. No grant is declared on this machine's live home (the operator's call). The rerun's
  pod names are in already-pushed history (ADR 0027, the operator API spec, a test); the tree
  no longer carries them, and rewriting public history is the maintainer's call.

- **Found in Wave 115 (Phase 44).** Pending memory entries show in `docket inbox` (text and
  `--json`) but not in `GET /inbox`, MCP `inbox`, notifications or Telegram `/status`: that needs
  an operator-v1 inbox contract bump and `notify.py`/`telegram.py` edits (operator-loop item 7's
  "`GET /inbox` equals `inbox --json`" was already broken by approved-ready tasks).
- **Found in Wave 114 (Phase 44).** `core/telemetry.py` has no structural key for
  `memory_update` (the generic handler serves it); members stamped `POD_TEMPLATE_VERSION` 4 before
  P44-7's method line show stale to `pod update` by text comparison (v4 never shipped);
  `scripts/smoke_workflow.py`'s memory scenario now seeds MEMORY.md directly and needs a live run.
- **Found in Wave 113 (Phase 44).** `_resolve_hop_instructions` still opens "You are the
  Implementer..." (SOUL says it); recipe roles using `${codebaseOrConfigured}` (secure-build
  security-vetter) still render a path; `cli/_agents._create_workspace` (standalone agents)
  still writes HEARTBEAT/promise text; `repo_map.SKIPPED_DIRS` mirrors `toolbox.SKIPPED_DIRS`
  (pinned by an equality test); a condensation notice carries the call's full path; pod read
  routes do not carry `tokenBudget`.
- **Found in Wave 112 (Phase 44).** The prospective budget check compares the whole calibrated
  input estimate plus reserve against the counted budget, so a heavily cached step is refused
  early; discount by the previous call's cache reads if a real run is refused with room left.
  `glob`/`grep` still walk vendored trees before filtering (pathlib cannot prune); measure before
  changing. In an in-place task on an already dirty tree, the first writing hop's `diff` carries
  the operator's own changes once (task worktrees start clean). The bench scales cached tokens by
  the sent ratio; P44-4 may need a cache-aware projection.
- **The Lead plans with the codebase path, the Implementer is rooted in the task worktree**
  (measurement 3: `tool.refused` on `read` of the codebase path, audit seq 6-7 of the throwaway
  home). The Lead's hop should name the task worktree, or the handoff should rewrite the path.
  Reproduce with any local-model dispatch in a worktree pod before scheduling.
- **Parallel tasks in a pod** -- trigger in ADR 0027 point 10. The task record and the claim
  are already per task; a card would add a `maxParallelTasks` pod setting and a bounded pool in
  `dispatch_pod`.
- **A task's `network: none` cuts the agent turn only** (P43-4): `verifyCmd` and `run:` steps keep
  the pod's posture; the spec says so.
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams.
- **`POST /pods/<p>/apply` edge** (P43-8): an all-skip apply writes no `pod.apply` audit entry
  (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
- **Cancel over HTTP reports `cancelled` once the stop is requested** (P43-10): the task stays
  `running` in the store until the executor notices; a consumer polls `GET /tasks/<pod>/<id>`.
  The slow-stub cancel path is not covered by a test (the test seeds a run record).
- **`cli/_task.py::_pod_codebase`** is a second reader of the implementer's codebase beside
  `core/pod_report._codebase` and `core/dispatch.task_diff`; one core helper when next touched.
- **Real-Docker tests over their duration ceiling under load** (`test_network_lockdown.py`,
  `test_sandboxed_exec.py`, `test_escape_matrix.py[docker]`): pass alone, fail when five suites
  run at once. A flake, not a regression; measured 2026-10-14.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump (specs carry no changelog) (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model (D-52, amending D-31):** **`develop`** is the integration branch. Every card
branch or isolated worktree bases on `develop` and is integrated into `develop` without
rewriting history. **`main`** stays the canonical public/default and release lineage: it moves
only by a fast-forward (or a merge) from `develop`, when the maintainer cuts a release or
decides `main` has fallen too far behind. Tags and release jobs still originate from `main`.
`platform` may remain as a synchronized historical ref, but it is not a release source.

---


