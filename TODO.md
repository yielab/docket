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
> ## ◉ ACTIVE BOARD — WAVE 31 (2026-09-11) — human maintainability (Phase 25, D-36)
>
> Nine cards W31-C0…C8, scoped in the first section below. The measured triggers are an 8 min 12 s
> default suite whose 15 slowest tests are all release/evidence checks, 35 test files that verify
> prose or the agent's own hook scripts, `serve` tested across 19 files, 89 archaeology hits in
> comments, and three functions over 500 lines. Decision D-36 in ROADMAP.md owns the ruling;
> `specs/test-framework.md` §"Lanes and placement" is the contract.
>
> **W31-C0–C3 run first and sequentially.** C1 moves every test file, so no other card may own a
> test path while it is open. C4 onward fan out by module.
>
> **Deferred behind this wave, by maintainer decision on 2026-09-11:** W29-C7 (publish the
> provenance-complete beta, close Phase 23) and all of Wave 30 (Phase 24, harness mode, D-35).
> Neither is claimable until Wave 31 closes. The repository is made maintainable before it is
> published further.
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

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
   `bash scripts/validate-specs.sh` green · the card's own spec updated with a version bump +
   changelog entry, **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---

## ◉ WAVE 31 ACTIVE (2026-09-11) — human maintainability: test lanes, comment budget, generated docs (Phase 25, D-36)

**Active since 2026-09-11.** W29-C7 was deferred behind this wave by the maintainer so the
repository is made maintainable before any further publication; Wave 30 waits behind it too.
**W31-C0–C3 run first and sequentially**: C1 moves every test file, so any card that owns a test
path while C1 is open would merge against a moved tree. After C3 merges, W31-C4+ fan out and
W30-C1+ becomes claimable, scheduled by file contention like any other lanes. Decision D-36 and the measured triggers live in ROADMAP
"Planned program — PHASE 25"; the audit and the phase-by-phase plan are
`internal-docs/maintainability-audit-2026-09-11.md` and
`internal-docs/plan-tests-comments-docs-2026-09-11.md` (gitignored; read at `main` `0d3720a`).
The contract every card here implements is `specs/test-framework.md` §"Lanes and placement"
(2.13.0). Two analysis scripts already exist uncommitted in `scripts/maint/` and C0 commits them.

**Activation measurement (2026-09-11, working tree at `0d3720a`, `uv run pytest -q --durations=15`):**

| Metric | Locator | Observed | Threshold |
| --- | --- | --- | --- |
| Default suite wall time | `uv run pytest` | 8 min 12 s (2,377 passed, 5 skipped) | < 90 s after C5; < 5 min after C1 alone |
| Share of wall time in the 15 slowest tests | `--durations=15` | ~257 s, every one a release/evidence/adapter test | those tests out of the default suite |
| Test files that assert on prose, release artifacts, or the agent's own hook scripts | `scripts/maint/test_inventory.py` | 35 files, 8,313 lines, 227 tests (18% of test lines) | in `tests/agent/`, ≤ 4,000 lines total, guarded |
| Test files touching one subject | `rg -l` over `tests/python` | `serve` in 19 files, `runs` in 17, `tools` in 12 | one unit file per `src/` module, guarded |
| Archaeology in comments/docstrings | `scripts/maint/comment_lint.py src tests` | 20 hits in `src/`, 69 in `tests/` | 0, ratcheted |
| `subprocess` call sites in tests | `rg -c 'subprocess\.(run\|Popen\|check_output)'` | 91 sites in 40 files | 0 in `unit/`; only process-boundary tests elsewhere |
| Board and roadmap volume | `wc -l TODO.md ROADMAP.md` | 4,628 + 3,541 lines; active wave began at line 1642 between closed waves (archive shipped 2026-09-11: ~1,100 + ~810 remain, all of it active or planned) | TODO ≤ 200 once W30/W31 close, ROADMAP ≤ 500, history in `docs/cycles-ended/` |
| Hand-written CLI reference | `docs/commands.md` | 2,247 lines, no drift check | generated from Typer, `--check` in CI |
| Functions over 500 lines | `src/docket/core/agent_loop.py::run_agent_turn` 789, `core/dispatch.py::dispatch_task` 703, `::_execute_unit` 501 | 3 | 0 (C8) |

**Execution graph / contention:** C0 → C1 → C2 → C3 strictly sequential (each rewrites paths or
headers across the whole test tree). C4 and C5 are per-module packets and may run in parallel with
each other and with W30 when they do not share a test file. C6 and C7 touch only docs/board/scripts
and are parallel-safe with everything except W30-C5 (central rollups). C8 is one module per branch,
last. **Every card runs with an isolated `DOCKET_HOME`** and snapshots the real `~/.docket` before
and after its focused run.

### W31-C0 — commit the baseline and the two analysis scripts

**Status:** TODO · **Size:** S · **Owner:** —

**Trigger:** the activation table above is a working-tree measurement; the board contract requires
a locator a later card can re-run. `scripts/maint/test_inventory.py` and
`scripts/maint/comment_lint.py` exist uncommitted and pass `ruff`.

**Goal:** commit both scripts unchanged; add `.maint/` (gitignored) and write
`inventory.json`, `moves.tsv`, `comment-baseline.txt`, and `durations-0.txt` there from the exact
commands in the plan's Phase 0; record the four numbers in the commit body.

**Non-goals:** no test moves, no fixes, no CI change.

**Owns:** `scripts/maint/`, `.gitignore` (one line). **Forbidden:** everything else.

**Acceptance / oracles:** `uv run python scripts/maint/test_inventory.py` prints six lanes whose
line totals sum to the `tests/python` total; `comment_lint.py src tests --summary` ends with the
totals line matching the table; both scripts pass `ruff check`/`ruff format --check`.

**Validation:** ruff; no pytest change expected. **Handoff:** the four artefact paths and numbers.

### W31-C1 — move the suite into lanes and take the agent lane out of the default run

**Status:** TODO · **Size:** M · **Owner:** — · **Depends on:** C0

**Deterministic trigger:** at `0d3720a`, `pyproject.toml` `testpaths = ["tests/python"]` collects
every file, including the 18 the inventory classifies as `agent/*`; the 15 slowest tests (257 s of
492 s) are all in that set. Reproduction: `uv run pytest --collect-only -q | tail -1` shows one
flat directory; `--durations=15` names only release/evidence/adapter tests.

**Goal:** review `.maint/inv/moves.tsv` by hand (correct lane and destination per row; suffix
`__<aspect>` where several files target one unit module — C4 merges them); write
`scripts/maint/apply_moves.sh` (git mv per row; `sed` of every old path to its new path across
`src/ specs/ docs/ *.md .agents/ tests/ scripts/ .github/`; move `conftest.py` and `fakes.py` to
`tests/`; delete `tests/python/__init__.py`); set `testpaths = ["tests/unit", "tests/integration",
"tests/guards"]`, `addopts = "-ra -q --import-mode=importlib"`, marker `slow`; add the CI job
`agent-lane` running `uv run pytest tests/agent` with a path filter; update
`test_docket_home_isolation.py`'s path to `tests/conftest.py`; update `tests/run-all-tests.sh`.
`scripts/metrics.py --check` will report the smaller default-suite count: **fix the CONTRIBUTING
claim, not the script**, and say in the commit body that the count now excludes the agent lane.

**Non-goals:** no test content edits, no merges, no deletions, no new guards (C2), no docstring or
comment edits (C3).

**Owns:** `tests/**` (moves only), `pyproject.toml` pytest block, `.github/workflows/ci.yml`,
`scripts/maint/apply_moves.sh`, path strings in `src/` docstrings, `specs/`, `docs/`, `TODO.md`
(paths only — including the W30 cards), `CONTRIBUTING.md` paths and count. **Forbidden:** test
bodies; `scripts/metrics.py`; README.

**RED tests / oracles:** (1) before the move, `uv run pytest tests/agent --collect-only` fails
(no such directory); after, it collects exactly the reviewed `agent/*` rows and the default run
collects none of them. (2) `uv run pytest -q --durations=0` wall time < 5 min and no `agent/*`
node in the default durations. (3) `rg -n 'tests/python' --glob '!.maint/**' --glob '!internal-docs/**'`
returns only `CHANGELOG.md` history lines. (4) `bash tests/golden/run.sh verify-all` byte-identical.
(5) `~/.docket` snapshot byte-identical before and after the full run.

**Validation:** full default suite, `uv run pytest tests/agent`, goldens, ruff/format, mypy,
`validate-specs.sh`, `metrics.py --check` after the claim fix. **Handoff:** the wall time before/
after, the final lane counts, and every TSV row changed from the script's proposal and why.

### W31-C2 — structural guards, lane headers, and one test for removed commands

**Status:** TODO · **Size:** M · **Owner:** — · **Depends on:** C1

**Deterministic trigger:** at `0d3720a`, four files (`test_tier_shims_removed.py`,
`test_eval_command_removed.py`, `test_team_command_removed.py`, `test_workflow_command_removed.py`;
639 lines, 32 tests) verify that `__main__._REMOVED` entries print a notice — one file per
removal. Nothing enforces that a unit test file names an existing module, that `tests/agent/` stays
bounded, or that `unit/` stays subprocess-free.

**Goal:** `tests/guards/test_removed_commands.py`, one parametrized test over `_REMOVED`
(≤ 60 lines) replacing the four files; `tests/guards/test_layout.py` (every `unit/**/test_X.py`
maps to an existing `src/docket/**/X.py`, `SUBJECT` matches, every `src/` module > 150 lines has a
unit file); `test_lane_headers.py` (`LANE`/`REASON`/`RETIRE_WHEN` present in every `tests/agent/**`
file; no `subprocess` import in `tests/unit/**`, AST); `test_agent_lane_budget.py` (sum of
`tests/agent/**` lines ≤ 4,000); a duration guard in `tests/conftest.py` failing the session when
a `unit/`/`guards/` test exceeds 2 s or an `integration/` test exceeds 10 s. Add `SUBJECT` to every
unit file and the three header constants to every agent-lane file (script writes the skeleton,
the human fills 18 `REASON` lines). To meet the 4,000-line budget, cut ~1,650 lines from the agent
lane: `test_workflow_smoke.py` (1,121 lines testing `scripts/smoke_workflow.py`) and
`test_adoption_benchmark.py` (666) are the named candidates; the human decides which public claims
keep a test and records each retirement in `RETIRE_WHEN` terms in the commit body.

**Non-goals:** no changes to product behaviour; no golden change; no merges of behavioural files
(C4); the existing seven AST guards move unchanged.

**Owns:** `tests/guards/**`, `tests/conftest.py` (duration hook only), `tests/agent/**` headers and
the named cuts, `SUBJECT` lines in `tests/unit/**`, `tests/integration/**` `SUBJECT` lines.
**Forbidden:** `src/`, `specs/` other than `test-framework.md`'s enforcement status, central files.

**RED tests:** each of the five guards must be **seen to fail** before the commit: plant a unit
file with a non-existent subject, a `tests/agent` file without headers, a `subprocess` import in
`unit/`, a 4,001-line total, and a `time.sleep(3)` in a unit test; record each red/green pair in
the commit body. The removed-commands test must fail when one `_REMOVED` key is deleted.

**Acceptance / oracles:** guard failures reproduce as described; the default suite passes; the
agent lane passes at ≤ 4,000 lines; `python -m docket tier` and the other removed verbs still
print their notice (golden or CLI oracle).

**Validation:** full gates plus `uv run pytest tests/agent`. **Handoff:** the five red/green
records, the agent-lane line count, and the list of retired agent-lane tests with their reasons.

### W31-C3 — zero archaeology in comments and docstrings, ratcheted

**Status:** TODO · **Size:** S · **Owner:** — · **Depends on:** C2

**Deterministic trigger:** at `0d3720a`, `scripts/maint/comment_lint.py src tests --summary`
reports `archaeology=20` in `src/` and `69` in `tests/`, plus 45 (`src`) and 68 (`tests`) module
docstrings over budget; ROADMAP §3 states the rule but nothing in CI reads it. Reproduction: the
totals line of that command.

**Goal:** run `comment_lint.py src tests --fix` (removes only whole-line comments that carry no
rationale word — 3 lines in `src/`); process the remaining hits one file per packet, rewriting only
the flagged lines and keeping every rationale; shorten test module docstrings to ≤ 6 lines and
test docstrings to one line; commit `scripts/maint/comment-baseline.json` (per-kind counts) and
`tests/guards/test_comment_hygiene.py`, which runs the linter and fails if any count rises above
the baseline. `def-max` for `src/` starts at 12; tests at 3.

**Non-goals:** no rewriting of `src/` docstrings that document contracts; no behaviour change; no
changes to the linter's detection rules beyond documented false positives ("used to <verb>").

**Owns:** comment and docstring lines the linter names in `src/**` and `tests/**`;
`scripts/maint/comment_lint.py` (baseline support only); `tests/guards/test_comment_hygiene.py`;
`CONTRIBUTING.md` comment-policy section (already written; verify). **Forbidden:** code lines.

**RED tests:** the hygiene guard fails when a `# W17-1` comment is planted in `src/`; passes after
removal. `git diff --stat` shows only comment/docstring hunks — reviewer confirms with
`git diff -w | rg '^[+-]\s*[^#"'"'"' ]'` returning nothing outside docstrings.

**Acceptance / oracles:** linter totals `archaeology=0` for both trees; module-docstring counts
at or below baseline; full suite unchanged in pass count.

**Validation:** full gates. **Handoff:** the before/after totals and the per-file list of
rationale lines deliberately kept.

### W31-C4 — one unit file per module: merge history-named and fragmented test files

**Status:** TODO · **Size:** M (split per module before claiming) · **Owner:** — · **Depends on:** C3

**Deterministic trigger:** at `0d3720a` the inventory shows six unit destinations fed by several
files (`test_serve.py` ← 8, `core/test_memory.py` ← 3, `core/test_archetypes.py` ← 3,
`core/test_tools.py` ← 2, `core/test_llm.py` ← 2, `core/test_pipeline.py` ← 2) and files named for
events rather than modules (`test_audit_v2`, `test_mcp_sdk_v2_migration`, `test_deferred_gaps`,
`test_legacy_role_parity`, `test_hop_carryover`); 33 test names are duplicated across files.

**Goal:** one packet per destination module, in this order: `serve` → `core/runs` →
`core/memory` → `core/archetypes` → `core/tools` → `core/pipeline` → the history-named files.
Packet input is the module's signatures (`rg -n '^def |^class ' src/docket/<m>.py`) plus the N
test files; output is one file ≤ 800 lines (or `__<aspect>` files), every test function preserved
unless its assertions are an exact duplicate, docstrings one line, no archaeology.

**Non-goals:** no assertion changes; no fixture redesign; no `subprocess` conversion (C5).

**Owns:** the listed test files only. **Forbidden:** `src/`, guards, agent lane.

**RED tests / oracles:** per packet, `rg -c 'def test_'` before and after differ only by the
listed exact duplicates; `uv run pytest tests/unit/<destination>` green; `test_layout.py` green
(no orphan file remains). Whole-suite pass count at the end equals the start minus documented
duplicates.

**Validation:** focused per packet; full gates at the end of the card. **Handoff:** per module,
the function counts before/after and the duplicate list.

### W31-C5 — in-process CLI tests: `subprocess` only where the process boundary is the subject

**Status:** TODO · **Size:** M (split per file) · **Owner:** — · **Depends on:** C1; parallel with C4 on disjoint files

**Deterministic trigger:** at `0d3720a`, 91 `subprocess` call sites in 40 test files spawn
`python -m docket` (≈ 0.5–1 s each) to assert output text the golden suite already pins.

**Goal:** convert every non-boundary file to `typer.testing.CliRunner` in-process; exact user
text assertions become golden cases or JSON-shape assertions. Exclusion list (process boundary is
the subject): `sandboxed_exec`, `run_cancellation`, `cooperative_run_cancellation`,
`implementer_worktree_isolation`, `diff_probe`, `system_adapter`, and any file whose `SUBJECT`
is `docket.edges.adapters.system`.

**Non-goals:** no change to what is asserted, only how; no golden regenerated to hide a diff.

**Owns:** the listed test files; new golden cases when text moves there. **Forbidden:** `src/`.

**RED tests / oracles:** `test_lane_headers.py`'s no-subprocess-in-unit check passes; default
suite wall time < 90 s on the CI runner and locally (record both); pass count unchanged.

**Validation:** full gates. **Handoff:** wall time before/after and the files left on the
exclusion list with the reason each stays.

### W31-C6 — generated CLI reference and strict docs build

**Status:** TODO · **Size:** M · **Owner:** — · **Depends on:** C0; **runs in parallel with C1**
(disjoint: C1 owns `tests/**`, `pyproject.toml`, `.github/workflows/ci.yml` and the `tests/python`
path strings in `src/`, `specs/`, `docs/DEVELOPMENT-HARNESS.md`; this card owns the CLI-reference
generator and `docs/commands.md`, which carry no such path string)

**Deterministic trigger:** at `0d3720a`, `docs/commands.md` is 2,247 hand-written lines with no
drift check, while `count_commands()` in `scripts/metrics.py` already introspects the Typer app
live; `test_public_release_truth.py` checks Markdown links by hand because no docs build does.

**Goal:** `scripts/gen_cli_docs.py` renders `docs/commands.md` from the Typer registry (groups,
options, help strings, arguments) and supports `--check`, which exits non-zero when the file on
disk differs from what the registry produces; content present in the old file but absent from a
help string moves **into the help string**, so nothing is lost and the source of truth is the code.
`mkdocs.yml` declares a fixed nav: the four guides, the generated CLI reference, the
`docket-runtime` API via mkdocstrings, the spec index, `docs/adr/`, `docs/cycles-ended/`, and the
changelog.

**Non-goals:** no published site until the maintainer enables Pages; no README rewrite (C7); **no
edit to `.github/workflows/ci.yml` or `pyproject.toml`** — C1 owns both this wave, so return the
exact `docs` extra block and the `docs` CI job as text in the handoff and the integrator applies
them; no folding or moving of other docs (follow-up C6b); no retirement of agent-lane tests
(follow-up, after the strict build is wired).

**Owns:** `scripts/gen_cli_docs.py` (new), `docs/commands.md` (regenerated), `mkdocs.yml` (new),
and help strings in `src/docket/cli/**` **only** where content moves out of the old hand-written
reference. **Forbidden:** `tests/**`, `pyproject.toml`, `.github/workflows/**`, `README.md`,
`specs/**`, every other file under `docs/`, and all `core/`/`edges/` code.

**RED tests / oracles:** (1) `uv run python scripts/gen_cli_docs.py --check` exits non-zero
against the current hand-written `docs/commands.md` **before** regeneration, and zero after;
(2) after editing one help string in `src/`, `--check` exits non-zero again until regenerated;
(3) every one of the 37 live commands from `scripts/metrics.py::count_commands` appears in the
generated file, and no retired command does; (4) `uvx --with mkdocs-material --with
'mkdocstrings[python]' mkdocs build --strict` succeeds, and fails when a dead link is planted.
Run (4) with `uvx` so no dependency is added to the tree.

**Validation:** the four oracles above; `uv run ruff check . && uv run ruff format --check .`;
`uv run mypy src`; `uv run pytest -q tests/agent/release/test_public_release_truth.py
tests/integration/test_completions_eval_metrics_help.py`; `uv run python scripts/metrics.py --check`;
`bash tests/golden/run.sh verify-all` (help strings are golden-pinned — if a `help` golden changes
because content moved into a help string, regenerate it and explain the diff line by line).
**Handoff:** the dropped-paragraph list with where each went, the nav, and the exact `docs` extra
and CI job text for the integrator to apply.

### W31-C7 — board and roadmap to size: active wave only, history in CHANGELOG, decisions as ADRs

**Status:** TODO · **Size:** M · **Owner:** integrator · **Depends on:** C0; runs when no other card is open

**Deterministic trigger:** at `0d3720a`, `TODO.md` has 131 headings across 4,628 lines and the
active wave starts at line 1642 between closed waves 27 and 28; `ROADMAP.md` is 3,541 lines with
its changelog embedded; the roadmap hook (`context_snapshot.py`) exists because neither fits a
context window, and 569 lines of tests cover that hook.

**Goal:** `scripts/maint/split_board.py` moves every `## ☑ WAVE N COMPLETE`/closed phase
section from `TODO.md` into `docs/cycles-ended/todo-waves.md` and every embedded ROADMAP phase
record and changelog likewise — **done 2026-09-11** (49 sections, byte-verified by
`docs/cycles-ended/manifest.json`; TODO.md 4,946 → ~1,100 lines, ROADMAP.md 3,637 → ~810). What
remains for this card: `TODO.md` keeps the usage rules, the active
section and planned sections (≤ 200 lines after this wave closes); `ROADMAP.md` keeps mission,
conventions, DoD, §4.5, the decision index and the phase table (≤ 500 lines); each decision whose
row exceeds ~15 lines of reasoning becomes `docs/adr/NNNN-<slug>.md` with the row shortened to a
sentence and a link. `README.md` ≤ 150 lines; `CONTRIBUTING.md` carries the six "Working here"
rules and the comment policy; local `CLAUDE.md` shrinks to what `AGENTS.md` and CONTRIBUTING do not
say.

**Non-goals:** no history deleted — every moved section is byte-preserved in `docs/cycles-ended/`; no
decision re-litigated; no change to `context_snapshot.py` parsing rules (they must still work on
the smaller file).

**Owns:** `TODO.md`, `ROADMAP.md`, `docs/cycles-ended/**`, `docs/adr/**`, `README.md`,
`CONTRIBUTING.md`, `scripts/maint/split_board.py`. **Forbidden:** everything else.

**RED tests / oracles:** `split_board.py --check` proves every H2 removed from `TODO.md`/
`ROADMAP.md` appears verbatim in `docs/cycles-ended/` (hash per section — shipped); `context_snapshot.py` still
prints the active marker; `card_packet.py W30-C1` still resolves; `wc -l` targets met;
`metrics.py --check` and `tests/agent/truth` green.

**Validation:** full gates, agent lane, both roadmap scripts. **Handoff:** line counts before/
after and the list of new ADRs.

### W31-C8 — split the three functions over 500 lines into named phases

**Status:** TODO · **Size:** L — split into three cards (one per function) before claiming ·
**Owner:** — · **Depends on:** C4 (each function has one unit file)

**Deterministic trigger:** at `0d3720a`, `core/agent_loop.py::run_agent_turn` is 789 lines,
`core/dispatch.py::dispatch_task` 703 and `::_execute_unit` 501; 42 functions exceed 80 lines.
The two largest test files (`test_agent_loop.py` 2,462 lines, `test_docket_driver.py` 1,688)
exist because those functions can only be exercised end to end.

**Goal:** per function, extract phases with names (`_prepare_request`, `_run_round`,
`_apply_stop_conditions`, …) with zero behaviour change, proven by the existing suite and goldens;
then unit tests per phase in the module's unit file and retirement of end-to-end tests made
redundant. One function per branch.

**Non-goals:** no semantic change; no new stop conditions, budgets or trace events; no change to
the `dispatch_tool` chokepoint (AST guard stays green).

**Owns:** the named function and its unit/integration files. **Forbidden:** other modules.

**RED tests / oracles:** the existing suite and goldens are the regression oracle and must be
byte-identical; new phase-level tests fail on the unextracted code (they import a name that does
not exist yet) and pass after; `test_tool_registry.py` chokepoint guard green.

**Validation:** full gates per branch. **Handoff:** function length before/after, tests retired
with the phase test that replaces each.

---

## ◇ WAVE 29 DEFERRED (2026-09-02, paused 2026-09-11) — adoption evidence and public release

**Paused, one card left.** C1–C6 are merged and closed. W29-C7 (publish the provenance-complete
beta and close Phase 23) is deferred behind Wave 31 by maintainer decision on 2026-09-11: the
repository is made maintainable first, then published. Do not claim W29-C7 until Wave 31 closes.

**Activation measurement:** bounded inspection used exact `main` commit `de08206`, the current
public GitHub release/API state on 2026-09-02, the Phase 23 exit contract, and only the live
starter/metrics/store/release/governance paths. The measurement did not infer demand from stars or
feature counts and did not reopen telemetry, A2A, a dashboard, multi-tenancy, or more adapters.

| Candidate | Source / threshold | Observed value | Disposition |
| --- | --- | --- | --- |
| Extractable ten-minute starter | `examples/`; at least one artifact-installed, copied-outside-checkout starter with a bounded end-to-end test | zero starter directories; `examples/runtime_embed.py` is a single consumer file and fails from the root environment when `docket-runtime` is not installed | **activate C2** |
| Machine-readable adoption benchmark | repository paths and `docket metrics`; at least one versioned schema/result covering all Phase 23 measures | zero benchmark/baseline files; current metrics omit one comparative record for measured tokens, estimate provenance, approval latency, recovery, and handoff failure | **activate C3** |
| Persisted-state recovery | `edges/store.py::{read_json,_atomic_write}`; a corrupt primary with a valid owned backup must have one safe recovery path | second write creates `.bak`, but corrupting the primary makes `read_json` raise `JSONDecodeError`; recovery paths: zero | **activate C1**, then prove it in C4 |
| Adversarial/crash evidence | policy, dispatch, and release focused tests; at least one public-journey scenario/report, not helper-only coverage | 31 focused policy-template, crash-resume, and release-contract tests pass; whole-journey benchmark scenarios/results: zero | **activate C4 after C1+C3**; reuse behavior rather than rebuilding it |
| Release supply chain | current workflow plus latest public beta; wheel, sdist, checksums, SPDX SBOM, and provenance must be publicly verifiable | workflow code and six release-contract tests already cover the machinery; public `v0.2.0-beta.1` has only tarball + checksum and predates it | **no duplicate implementation**; C7 performs approval-gated publication/verification |
| Support and succession policy | `SECURITY.md`, `COMPATIBILITY.md`, `.github/CODEOWNERS`, 90-day Git history; one truthful support/deprecation policy and one governance/succession path | main-only security support exists; no deprecation policy or governance document; one CODEOWNER and one underlying human author identity | **activate C5** |

**Execution graph / contention:** C1 through C6 are closed. C7 is the only remaining card and the
only release/version/tag owner; it may not publish without a fresh explicit approval. `ROADMAP.md`,
`TODO.md`, `README.md`, `CHANGELOG.md`, `COMPATIBILITY.md`, `SECURITY.md`, `specs/README.md`,
metrics, tags, and release state remain coordinator-owned unless a card below explicitly assigns
them.

### W29-C1 — recover a corrupt Docket JSON primary from its valid backup

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex-w29-c1

**Measured trigger:** at `de08206`, two `edges.store.write_json` calls create a valid
`state.json.bak`; replacing `state.json` with `{broken` leaves the backup present, but
`edges.store.read_json` raises `JSONDecodeError`. Threshold: one deterministic, concurrency-safe
recovery path for a representative Docket-owned registry. Observed: zero.

**Goal:** make the store chokepoint recover a malformed primary from a parseable owned backup under
the existing per-directory lock, quarantine the malformed bytes for diagnosis, and return the
recovered document without allowing two readers/writers to perform competing restores.

**Non-goals:** no generic filesystem backup service, JSONL audit/trace recovery, remote backup,
schema migration, silent reset to `{}`, repair of a missing primary, or change to the persisted JSON
shape. Do not route around `edges/store.py` or add a second writer.

**Owns:** `src/docket/edges/store.py::{read_json,read_modify_write,_atomic_write}` plus the smallest
private recovery helpers; new `tests/integration/test_store_recovery.py`; new
`specs/data/docket-store.spec.md`. `specs/README.md`, public docs, and central rollups are forbidden.

**Acceptance / RED oracle:** start with a temporary registry produced by two real `write_json`
calls. Corrupt only the primary, retain its valid `.bak`, then read through the public store API and
through one real CLI consumer such as `docket runs list`. Both must recover the prior complete
document; the restored primary must be valid JSON with mode `0600`; the malformed bytes must remain
in one bounded quarantine file; and no invented empty state may appear. A valid primary must win
without changing any byte even when its backup is stale or malformed. Missing/corrupt backup must
raise one typed actionable error and preserve every input byte. A barrier race between recovery and
a writer must serialize, retain one complete generation, leave no `.tmp`, and never replace a valid
backup with malformed bytes. The pre-change test must fail specifically at the recovery assertion.

**Focused validation:** new recovery tests repeated (`--count=20` when the plugin is available, or
an explicit in-test barrier loop); neighboring `test_store_writer.py`, `test_run_registry.py`, and
the selected CLI consumer tests; owning spec validation; Ruff/format and strict mypy. Final gates:
full pytest, 18 goldens, ShellCheck, metrics, deterministic smoke, diff/privacy/clean checks.

**Handoff:** report the corruption fixture, quarantine naming/retention rule, lock boundary, byte
identity for no-op/error cases, focused results, and any registry whose caller bypasses the store.

**Shipped evidence:** RED `4b796de` and GREEN `b673645` recover a corrupt primary from a valid
backup under the directory lock, preserve exact malformed bytes in one bounded `.corrupt`, restore
mode `0600`, retain valid-primary and unusable-backup byte identity, and preserve existing
`JSONDecodeError` caller compatibility through typed `StoreRecoveryError`. All 11 focused cases,
including 20-repetition reader/writer barriers, pass on merged `main`.

### W29-C2 — ship an extractable, artifact-installed ten-minute starter

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex-w29-c2

**Measured trigger:** `examples/` contains configurations, pipelines, and two single Python files,
but no starter directory, dependency lock, self-contained instructions, or copied-outside-checkout
journey. `examples/runtime_embed.py` cannot run in the root environment because `docket-runtime` is
not installed. Threshold: one credential-free starter that a new user can copy, install from exact
artifacts, run, and inspect within a 600-second test timeout. Observed: zero.

**Goal:** create a small extractable starter that uses the installed `docket` CLI to show one
governed tool mutation, an approval pause and grant, a persisted typed terminal handoff, paired
trace identity, run-registry inspection, and audit verification against a deterministic loopback
model.

**Non-goals:** no hosted provider, subscription, port 8081, runtime-adapter dependency, framework
template zoo, package-index publication, web UI, Docker requirement, or duplication of the full
smoke harness. The starter teaches the installed CLI journey; it does not claim that the narrower
`docket-runtime` facade owns Docket's run registry or arbitrary framework governance.

**Owns:** `examples/starter/**`, new `tests/agent/release/test_starter_journey.py`, and new
`specs/acceptance/starter-journey.spec.md`. It may import existing fixture utilities only when they
are part of an installed public package; it must not import `tests/` or the source checkout.
README/docs indexes and central metrics are forbidden until C6.

**Acceptance / RED oracle:** build the exact root wheel and sdist once, copy only
`examples/starter/` to a fresh directory outside the checkout, install one exact root artifact into
a fresh Python 3.11 environment, and invoke one documented starter command with a fresh
`DOCKET_HOME`. Within 600 seconds it must mutate exactly one declared workspace file after one
approval, persist a typed terminal handoff, and let the installed public CLI inspect the matching
run (`docket runs list/show`), paired trace (`docket trace export`), and valid audit chain
(`docket audit verify`). Pre-approval and denial runs must leave the target bytes unchanged. The
journey must work with network disabled after artifact installation and with no API key. The
pre-change test fails because the extractable starter path does not exist.

**Focused validation:** starter contract and artifact journey on Python 3.11/Linux, plus the
existing release journey, release-artifact, run-registry/CLI, trace, audit, and public link/example
tests; owning spec; Ruff/format/mypy. Final gates match C1 and include the deterministic smoke.

**Handoff:** report cold/warm elapsed time separately, exact artifacts and Python version, public
command, resulting state/trace/audit locators, network/credential posture, and cleanup performed.

**Shipped evidence:** RED `b138f25` and GREEN `16ef7bc` add the extractable
`examples/starter/` journey. Its Python 3.11 test copies outside the checkout, builds and installs
the exact root artifact, runs without provider credentials or post-install network, proves denial
and approval/grant mutation boundaries, persists a typed handoff and paired trace, and verifies the
public run registry and audit chain. The merged artifact journey passes in 18.6 seconds.

### W29-C3 — define the adoption benchmark schema and deterministic runner

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex-w29-c3

**Measured trigger:** repository search finds zero benchmark/baseline files. `docket metrics` reports
session success, duration, estimated cost, and guardrail trips independently, but there is no
versioned scenario result tying completion, provider-reported tokens, estimate basis, prevented
violations, approval latency, crash/restart recovery, and handoff failure to the same run. Threshold:
one deterministic machine-readable schema plus runner and invalid-input oracle. Observed: zero.

**Goal:** add a dependency-light benchmark runner that consumes fixed scenarios and durable Docket
records, emits canonical per-attempt JSONL plus a deterministic aggregate JSON document, and keeps
measurement provenance explicit enough for review or reproduction.

**Non-goals:** no telemetry backend, hosted benchmark service, leaderboard, competitor ranking,
price synchronization, model-quality claim, new product metrics subsystem, or claim that fake-model
completion predicts real-model quality.

**Owns:** `benchmarks/harness.py`, `benchmarks/schema.json`, `benchmarks/README.md`, base scenario
fixtures under `benchmarks/fixtures/`, new `tests/agent/release/test_adoption_benchmark.py`, and new
`specs/validation/adoption-benchmark.spec.md`. Product runtime files and public/central docs are
forbidden. C4 may extend the spec and scenario directory only after C3 merges.

**Acceptance / RED oracle:** a fixed scenario/seed must emit stable identifiers and normalized
fields for scenario version, source commit/artifact hash, runtime/configuration, deterministic vs
live measurement class, attempts/completions, provider-reported input/output/total tokens,
tool-call count, prevented policy violations, approval latency, crash/restart recovery, handoff
failures, stop reason, and trace/audit locators. Every dollar value must carry `estimate=true` and a
versioned pricing source/assumption; unknown pricing must be `null`, never fabricated zero. Raw
prompts, secrets, home paths, approval tokens, and unredacted tool arguments must be absent. Invalid,
partial, duplicate, or mismatched records fail closed without overwriting a prior result. The
aggregate must be reproducible from JSONL alone. The pre-change test fails because no schema/runner
exists.

**Focused validation:** schema unit/property cases, two identical deterministic runs compared after
normalizing measured elapsed time, malformed/redaction cases, and metrics/trace/run fixture parity;
owning spec; Ruff/format/mypy. Final gates match C1.

**Handoff:** report schema version, field provenance map, normalization boundary, estimate labeling,
redaction scan, repeatability result, and exact command needed by C4.

**Shipped evidence:** RED `a556fdc` and GREEN `2bf46a5` add schema version `1.0.0`, a
dependency-light runner, documentation, and a minimal public-artifact fixture. All 11 focused cases
prove deterministic identifiers/serialization, strict task/session/trace/audit joins, explicit
estimate provenance, redaction, failure atomicity, and byte-identical JSONL-only aggregation.

### W29-C4 — add adversarial governance and crash/recovery benchmark scenarios

**Status:** DONE (2026-09-03) · **Size:** M · **Owner:** @codex-w29-c4

**Measured trigger:** 31 focused release, crash-resume, and policy-template tests pass, but zero
whole-journey scenario emits the Wave 29 benchmark record. Unit behavior exists; adoption evidence
does not. C4 is deliberately fixture-first and must not reimplement policy, approval, audit, or
resume logic.

**Goal:** drive the C3 runner through representative allowed, policy-denied, approval-denied,
approval-granted, malformed-handoff, hard-crash/resume, and corrupt-primary/backup-recovery journeys
using public actions and durable state, then emit comparable records.

**Non-goals:** no prompt-injection detector claim beyond the configured policy fixture, destructive
real command, live provider, chaos platform, arbitrary fault injection, new retry semantics, or
product fix hidden inside a benchmark scenario.

**Owns after dependencies merge:** `benchmarks/scenarios/**`,
`tests/agent/release/test_adoption_adversarial_recovery.py`, and an additive C4 section/version bump in
`specs/validation/adoption-benchmark.spec.md`. Product code is forbidden. If a scenario exposes a
new product defect beyond C1, stop and split a named defect card with its own spec/RED evidence.

**Acceptance / RED oracle:** each scenario starts from a fresh home/workspace and names its intended
side effect. Policy/approval denial must record one prevented violation and preserve target bytes;
grant must mutate exactly once; the crash case must persist completed hops, resume only unfinished
hops, and reach one terminal run; corrupted primary with valid backup must recover through C1 and
retain the quarantined evidence; malformed handoff must become a counted failure rather than a
completion. Repeat the table at least three times with unique state/ports and no cross-run leakage.
Every result must validate under C3 and reference verifiable trace/audit state.

**Focused validation:** C3 harness tests plus all new scenarios, `TestCrashRecovery`, policy-template,
approval, store-recovery, audit-chain, and handoff tests; owning spec; Ruff/format/mypy. Final gates
match C1.

**Handoff:** report the scenario table, public action, observable outcome, mutation/no-mutation
hashes, restart boundary, record locators, repetitions, and any split defect card.

**Shipped evidence:** RED `fcdff9a` and GREEN `0c8dac7` add seven versioned case definitions and a
credential-free scenario driver. Twenty-one isolated journeys prove allowed/granted/crash
single-write behavior; policy/approval denial byte identity; counted malformed handoff; retained-hop
crash resume; public `runs list` recovery with exact quarantine bytes; C3 schema validity; and
byte-identical normalized output across three repetitions. The merged 184-case C4/C5 focused suite,
Ruff/format/strict mypy, and all 27 specifications pass; no product defect was split.

### W29-C5 — publish truthful support, deprecation, governance, and succession policy

**Status:** DONE (2026-09-03) · **Size:** S · **Owner:** @codex-w29-c5

**Measured trigger:** `SECURITY.md` supports only `main` and rejects older tags;
`COMPATIBILITY.md` describes Python/platform support; neither defines a release-support or
deprecation window. There is no governance document. `.github/CODEOWNERS` names one account and the
90-day Git history resolves to one underlying human author identity. Threshold: one truthful policy
for support/deprecation and one maintainership/succession path. Observed: zero complete policies.

**Goal:** state who decides and releases, how contributors become maintainers, how breaking changes
and deprecations are announced during beta, which versions receive security fixes, and what happens
if the sole maintainer becomes unavailable—without inventing a committee or promised staffing.

**Non-goals:** no legal entity claim, foundation, CLA, paid support SLA, fake maintainer roster,
branch-protection mutation, release publication, or claim that beta has LTS support.

**Owns:** new `GOVERNANCE.md`, new `SUPPORT.md`, and new
`tests/agent/truth/test_project_policy_truth.py`. Existing `SECURITY.md`, `COMPATIBILITY.md`, README,
CODEOWNERS, and central indexes are read-only inputs; C6 owns their links/summary alignment.

**Acceptance / RED oracle:** public policy must explicitly name current single-maintainer reality,
decision and release authority, contributor-to-maintainer criteria, conflict/security escalation,
support matrix, pre-1.0 breaking-change/deprecation notice rule, succession/transfer-or-archive
procedure, and inactivity trigger. It must link only real channels and files, never promise an
unverified response time beyond `SECURITY.md`, and never name a successor who has not accepted.
Repository-relative links must resolve. Counterexample fixtures reject claims of multiple active
maintainers, LTS branches, guaranteed compatibility, or a governing foundation. Pre-change RED:
both policy files are absent.

**Focused validation:** new truth/link tests plus existing public-doc, security-boundary, and
positioning tests; Ruff/format. Final gates match C1.

**Handoff:** report the exact maintainer/support truth, deprecation window, succession trigger,
rejected overclaims, link test, and any item requiring owner consent rather than code.

**Shipped evidence:** RED `ac05dc3` and GREEN `c480e97` publish the current one-maintainer authority,
an evidence-based contributor-to-maintainer path, conflict/security escalation, main-only support,
one-published-beta deprecation notice, and a 90-day transfer-or-archive succession trigger. Eight
policy cases pass, every repository-relative link resolves, and counterexamples reject invented
multiple maintainers, LTS, compatibility guarantees, or foundation governance.

### W29-C6 — generate and publish the reproducible adoption baseline

**Status:** DONE (2026-09-03) · **Size:** M · **Owner:** @codex-w29-c6

**Measured trigger:** Phase 23 requires published completion/cost/safety/recovery evidence; C2 and
C4 produce the first reproducible inputs, while current public prose has no versioned result.

**Goal:** run the starter and scenario matrix from exact artifacts, commit the canonical raw and
aggregate result with provenance, and publish a compact interpretation that distinguishes measured
facts, deterministic-fixture evidence, estimates, failures, and unsupported conclusions.

**Non-goals:** no competitor ranking, dollar-savings promise, benchmark cherry-picking, live-model
requirement, hidden failed trials, regenerated numbers by hand, telemetry/A2A, or feature expansion.

**Owns after dependencies merge:** `benchmarks/results/**`, `docs/ADOPTION-EVIDENCE.md`, relevant
public links/limits in `README.md`, `COMPATIBILITY.md`, `SECURITY.md`, `docs/README.md`, spec indexes,
CHANGELOG entry, and metrics synchronization. It does not own VERSION, Formula, tags, or GitHub
release state.

**Acceptance / oracle:** one command on clean exact artifacts must regenerate byte-identical
normalized records and aggregate for the native starter plus every C4 scenario; elapsed/approval
latency may use a separately identified tolerance field and must never be represented as a stable
byte. The report must include attempts and failures, completion rate, measured tokens, explicitly
estimated or unavailable dollars, prevented violations, approval latency, crash/restart recovery,
and handoff failures. Every claim links to raw data/schema/commit and states that deterministic fake
results are contract evidence, not model-quality evidence. Public truth tests reject rankings,
unlabeled estimates, savings claims, secrets/private paths, and missing failed attempts.

**Focused validation:** complete C2–C4 matrix with two regenerations; schema/redaction/public-link
tests; all specs; metrics; Ruff/format/mypy. Closure gates: full pytest, 18 goldens, ShellCheck,
deterministic smoke, Linux/macOS artifact journeys, diff/privacy/clean checks.

**Handoff:** report artifact/source hashes, scenario/result counts, all failed attempts, normalization
and tolerance rules, published claims/non-claims, metrics delta, and whether C7 may request release
approval.

**Integrated closure evidence (2026-09-03):** `main` contains RED `82a3239` and GREEN `033bb4b`.
The baseline binds source `82a3239980bbda3673fdd8030751f1342bcab132` to wheel SHA-256
`0fe67120737c4d09da3229c1182d8bf5474e96f7077476f997c98f7c67667fce`: eight scenario groups,
nine attempts, five completions, and the four retained failures (`starter`, `policy-denied`,
`approval-denied`, `malformed-handoff`). Only approval-latency and wall-clock fields use the
manifest's 5,000 ms comparison tolerance. Public prose labels this deterministic contract evidence,
keeps dollars unavailable, and rejects model-quality, ranking, savings, or production-rate claims.
The test metric moves 2,522 → 2,536, including the CI-history, floor-harness, and canonical-builder
regressions. Local commit-level gates at `03693a3` pass: 2,528 tests with five expected
skips, 18 goldens, 27 specs, Ruff/format, strict mypy, ShellCheck, metrics, reproducible documentation
assets, deterministic smoke, Linux exact-wheel journey, diff, and privacy. GitHub run `33764191509`
passed both Linux and macOS release-journey jobs, while its
three full-suite jobs exposed two distinct CI defects: depth-one checkout cannot resolve pinned
source `82a3239`, and the floor environment cannot collect the benchmark tests because `jsonschema`
is absent. Commit `c817955` makes the Python, floor, and macOS jobs fetch complete history and adds a
passing regression test. Commit `ca45e38` declares the schema oracle as a test-only dependency,
installs it explicitly in the floor harness without changing runtime floors, and pins that boundary
with a second regression. GitHub run `33788650508` confirms that both defects are fixed, then exposes
one shared exact-artifact defect: its Python 3.11 builder produces wheel SHA-256 `9283d326…256b4`
instead of the published `0fe67120…67fce`, even though the extracted wheel trees are identical.
Commit `f789bc6` preserves the published baseline and makes raw wheel identity independent of the
ambient interpreter: it pins uv-managed CPython 3.14.3 and the complete Hatchling closure, then
recompresses with checksum-verified zlib-ng 2.3.3 at canonical Deflate level 6. Two isolated
regenerations inheriting different `UV_PYTHON` values now reproduce `0fe67120…67fce`; the full suite
passes 2,531 tests with five expected skips, and the complete Python 3.11 dependency-floor suite is
green. Hosted CI run [`33812881329`](https://github.com/yielab/docket/actions/runs/33812881329)
at `37e91a8` closes the remaining gate: its overall conclusion is success; Python, dependency
floors, ShellCheck/spec validation, 18 goldens, metrics, and both Ubuntu/macOS artifact-installed
release journeys pass. The exact-artifact publication oracle therefore reproduces the unchanged
`0fe67120…67fce` wheel in clean Python and floor environments without accepting drift. The advisory
macOS full-suite lane completes with 2,514 passes, 14 skips, and eight separate portability failures
(three Bash-3.2 assumptions, four OpenHands fixture timeouts, and one Linux-only `/proc` path); no
C6 baseline or artifact-journey check fails there. C6 is closed, and C7 may now request the explicit
version/tag publication approval required by its own boundary.

### W29-C7 — publish a current provenance-complete beta and close Phase 23

**Status:** DEFERRED behind Wave 31 (2026-09-11; publication was approved 2026-09-07 and that
approval still stands — only the ordering changed) · **Size:** M · **Owner:** integrator

**Measured trigger:** public release `v0.2.0-beta.1` (published 2026-07-03) has two assets—the legacy
tarball and checksum—and predates the current wheel/sdist/SBOM/provenance workflow. Static release
machinery and its six focused tests already pass, so publication/verification is the remaining gap.

**Goal:** choose an approved next beta version, align every version surface, run canonical release
rehearsal and cross-platform artifact journeys, create one signed/immutable tag through the protected
workflow, verify every public asset and attestation, then close Wave 29 and Phase 23 from evidence.

**Non-goals:** no silent tag, force push, mutable release replacement, package-index publication
unless separately approved, stable/LTS claim, Homebrew tap mutation beyond the repository formula,
or release while any required C1–C6 gate is red.

**Owns after approval:** `VERSION`, root/runtime package versions, `Formula/docket-cli.rb`, installer
default, CHANGELOG release section, release-truth tests, final ROADMAP/TODO/spec/metrics rollups, the
new Git tag, and GitHub release verification. `.github/workflows/release.yml` changes only if the
rehearsal proves its current contract false.

**Acceptance / oracle:** before any external mutation, print the proposed version, exact commit,
asset manifest, and approval boundary. Version/tag/package/formula/installer must agree. Both wheel
and sdist must install outside checkout and pass the release journey on Linux and macOS. The public
release must contain wheel, canonical sdist/versioned installer asset, individual checksum,
`SHA256SUMS`, SPDX JSON, and a GitHub-verifiable provenance attestation bound to exact digests.
Tampered bytes must fail verification. Fresh Homebrew/versioned-installer paths must resolve to the
new immutable assets. Only after public verification may Wave 29/Phase 23 become complete.

**Focused validation:** version/release/public-truth tests, local artifact manifest and tamper check,
release journey, and workflow syntax before approval. Post-publication: query GitHub release assets
and attestation, install from public URLs on both OS jobs, then run full canonical closure gates and
snapshot a clean synchronized `main`.

**Handoff:** report approval text/time, tag/commit, release/run/attestation URLs, asset names/digests,
cross-platform install evidence, failures, cleanup, and the final board/phase status. External
publication is never implied by claiming the card.

---

## ◇ WAVE 30 PLANNED (2026-09-11) — harness mode seams and contract (Phase 24, D-35)

**Not active.** Deferred behind Wave 31 on 2026-09-11. This board section exists so the work is
scoped once and is claimable when Wave 31 closes; it must not be claimed before that, because one
integrator owns one active marker at a time and W31-C1 moves every test file this wave would own. Decision D-35 and its corrected reasoning live in
[docs/adr/0001-harness-mode.md](docs/adr/0001-harness-mode.md); the audit that produced these cards
is `internal-docs/harness-mode-audit.md` (read at `main` `4032133`). ROADMAP's "Planned program —
PHASE 24" section holds the measured-gap table and the exit contract; this section holds the cards.

**Activation measurement (2026-09-11, `4032133`):** five deterministic gaps, each with a locator and
an expected/actual reproduction — not a demand estimate.

| Gap | Locator | Actual | Expected |
| --- | --- | --- | --- |
| In-flight `bash` ignores cancellation | `edges/adapters/toolbox.py::run_bash` (`communicate(timeout)`, `start_new_session=True`); `core/tools.py` `bash` handler lambda passes no callback; `DocketDriver` reports no pid so `runs.cancel_run` kills nothing | cancel at 0.2 s into `sleep 30` → returns at 30 s / tool timeout | returns < 2 s, child group gone |
| Gated call waits, then loop continues | `core/tools.py::dispatch_tool` `ask` branch → `wait_for_approval` (`TOOL_APPROVAL_TIMEOUT`=120 s); `core/agent_loop.py` denial accounting (`max_consecutive_tool_denials`=3) | ≥120 s wait; terminal `tool_denials` only after 3; no `policyId` in `tool_result` trace | 0 s; terminal on first gated call; result names tool/callId/policyId/reason |
| No trace subscriber | `core/trace.py::trace_event` | append-only | one synchronous seam; zero-subscriber path byte-identical |
| No published contract | `docs/contracts/` absent; no versioned shapes/fixtures | zero | generated schema pinned by test; NDJSON fixtures |
| No non-interactive entry point | `cli/`; `POST /dispatch/` returns before the work | zero | `docket harness run` / `status` |

**Execution graph / contention:** C1, C2 and C3 are independent and start together. `core/tools.py`
is the one hot file: C1 owns **only** the `bash` handler lambda; C2 owns `ToolContext`,
`ToolResult`, `ToolDenialKind` and the `ask` branch of `dispatch_tool`; nobody else touches it.
C4 starts after C1+C2+C3 land on `main`. C5 is integrator closure. **Nobody edits** `core/runs.py`,
`core/approval.py`, `core/dispatch.py`, `serve.py`, or the runtime facade, and
`edges/adapters/docket_runtime.py` changes only by C4's one env-coordinate pop: the design's whole
point is that they are consumed unchanged. Central files stay
integrator-owned. Every card runs with an isolated `DOCKET_HOME`; the real `~/.docket` must be
byte-identical before and after each focused run (snapshot it — this suite has leaked three times).

### W30-C1 — make cancellation reach an in-flight bash command

**Status:** TODO · **Size:** S · **Owner:** —

**Deterministic trigger:** at `4032133`, `edges/adapters/toolbox.py::run_bash` starts every command
with `start_new_session=True` (each child is its own session, outside any caller's group) and blocks
in `proc.communicate(timeout=timeout)`; the `bash` registration in `core/tools.py` passes roots,
timeout, env and sandbox but not `ctx.cancellation_check`. Reproduction: a `ToolContext` whose
callback flips true 0.2 s into `bash sleep 30` still returns after 30 s (or after the tool timeout,
which defaults to the whole turn's wall clock). Separately, `DocketDriver.run_turn` ignores
`on_spawn`, so `pids` is always `[]` and `docket runs cancel` "kills nothing in flight" for every
docket-native hop. D-30 deliberately let "an already-running handler finish" because a Python thread
cannot be killed safely; a subprocess can, and D-35 decision 9 amends D-30 for this handler only.

**Goal:** `run_bash` accepts an optional `cancelled: Callable[[], bool] | None = None`, waits with a
short bounded poll (`proc.wait(timeout=<poll>)` in a loop that also enforces the existing overall
timeout), and on a true callback kills exactly the way the timeout path already does —
`system.docker_kill` under the docker backend, then `_kill_group` — returning a complete
`ToolOutcome(ok=False, error="cancelled before completion" + sandbox tag)`. The `bash` handler lambda
passes `ctx.cancellation_check`. Nothing else changes.

**Non-goals:** no interruption of HTTP requests or Python tool handlers (D-30 stands there); no
change to `runs.py`'s pid registry or `DocketDriver.on_spawn`; no new `StopReason`,
`ToolDenialKind` or trace event; no CLI/serve/docs change; no change in behaviour or timing when
no callback is given (today's callers stay byte-identical, including the timeout message); no
sandbox-mode change.

**Owns:** `edges/adapters/toolbox.py::run_bash` plus one private poll constant; the `bash`
`handler=` lambda in `core/tools.py::builtin_registry` and nothing else in that file; tests in
`tests/integration/test_sandboxed_exec.py` and `tests/integration/test_cooperative_run_cancellation.py` (or a
new `test_bash_cancellation.py`); the `bash`/exec clauses of `specs/functional/security-gates.spec.md`
and requirement 66's "does not attempt to interrupt a running handler" clause in
`specs/functional/agent-loop.spec.md`, narrowed to non-`bash` handlers, with version bump and
changelog. **Forbidden:** `agent_loop.py`, `approval.py`, `runs.py`, `dispatch.py`,
`docket_runtime.py`, `ToolContext`/`ToolResult`, central files.

**RED tests:** (1) `run_bash(roots, "sleep 30", timeout=60, cancelled=flips_at_0_2s)` returns
`ok=False` within 2 s, the error names cancellation and carries the sandbox tag, and
`os.killpg(pgid, 0)` on the recorded child group raises `ProcessLookupError`; record wall time and
the child pgid. (2) The same command through `run_agent_turn` with a recording backend that
requests one `bash` call and a `ToolContext(cancellation_check=...)` that flips during the call:
the session holds one complete assistant/tool unit whose tool output is the cancelled outcome, the
loop returns `stop_reason="run_cancelled"`, and the backend was called exactly once. (3) With
`cancelled=None`, `sleep 30` under `timeout=1` produces today's exact timeout message and kills the
group (regression guard on the existing path). (4) A bwrap variant of (1), skip-labelled when the
backend is absent. Before implementation, (1) and (2) must fail at the wall-time assertion, not at
setup.

**Acceptance / oracles:** wall time, child-group liveness, session unit atomicity, backend call
count, and byte-identity of the no-callback outcomes are the oracles. `docket runs cancel` against
a run whose hop is inside `bash sleep 30` (through the production driver, isolated home) must
terminalize the run as `cancelled` within 3 s of the request with `observedAt`/`stoppedAt` set —
this is the whole-path proof that the amendment reaches the public CLI without new code.

**Validation:** focused nodes repeated 20× (barrier-timed tests are flaky by construction if
under-bounded); then `test_agent_loop.py`, `test_tool_registry.py` (the only-the-chokepoint-imports-
toolbox AST guard), `test_run_cancellation.py`, `test_runtime_adapter_fixture_contract.py` (runtime
closure still CLI-free); Ruff/format, strict mypy, both owning specs; full pytest, 18 goldens,
specs, metrics.

**Handoff:** report measured wall times before/after, the poll constant and why its value, the
D-30 sentence that changed and the one that did not, and the `docket runs cancel` whole-path result.

### W30-C2 — give a non-interactive caller a typed, immediate, terminal approval outcome

**Status:** TODO · **Size:** M · **Owner:** —

**Deterministic trigger:** at `4032133`, `core/tools.py::dispatch_tool`'s `ask` branch creates an
approval record and blocks in `wait_for_approval` (default `TOOL_APPROVAL_TIMEOUT`=120 s), resolves
to `approval_timeout`, and hands the model a denial; `core/agent_loop.py` ends the turn only after
`max_consecutive_tool_denials` (3) with `stop_reason="tool_denials"`, `failure_kind="invalid_output"`
and an error string that names denial kinds but no policy. `_trace_tool_result` emits `tool`,
`callId`, `decision`, `ok`, `executed`, `denialKind` — no `policyId`. Reproduction: a
`require_approval` template (`block-destructive`) plus a recording backend that requests
`bash rm -rf build` → 120 s per call, up to three calls, and a result that cannot say which rule
fired. Lowering the denial limit to 1 is not a fix: it would also make a recoverable `invalid_call`
terminal. D-35 decision 11.

**Goal:** `ToolContext.approval_mode: Literal["wait", "refuse"] = "wait"`. Under `"refuse"`, the
`ask` branch audits `tool.ask` exactly as today, creates **no** approval record, waits **zero**
seconds, and returns `decision="deny"`, `denial_kind="approval_unavailable"` (new
`ToolDenialKind`), `reason=<verdict reason>`, `policy_id=<verdict.policy_id>` (new `ToolResult`
field, populated on every non-allow verdict). `_trace_tool_result` adds `policyId` and `reason`
when present. After persisting the batch's complete unit, the loop returns
`_done(ok=False, stop_reason="approval_unavailable", failure_kind="invalid_output", error=...)`
where the error names tool, call id, policy id and reason; `StopReason` gains the literal.
`DocketDriver` passes it through unchanged (`invalid_output` is already non-retryable).

**Non-goals:** no change under `"wait"` (record creation, wait, timeout semantics all
byte-identical); no new approval channel or record state; no `max_consecutive_tool_denials`
change; no CLI flag; no policy template change; no `toolbox.py`; no runtime facade API beyond the
optional field; no attempt to make `gate_denied` or `invalid_call` terminal.

**Owns:** in `core/tools.py`: `ToolContext`, `ToolResult`, `ToolDenialKind`, and the `ask` branch of
`dispatch_tool` (not the `bash` lambda — C1's); in `core/agent_loop.py`: `StopReason`,
`_trace_tool_result`, and the post-batch denial accounting; `specs/functional/agent-loop.spec.md`
(requirement 61's payload list, the `StopReason` enumeration, a new requirement for the refuse
path) and `specs/functional/security-gates.spec.md` (approval-mode clause), each with version bump
and changelog; tests in `test_agent_loop.py`, `test_approval_gated_dispatch.py`,
`test_trace_audit.py`. **Forbidden:** `toolbox.py`, `approval.py`, `runs.py`, `cli/`, docs, central
files.

**RED tests:** (1) `dispatch_tool` with the shipped `block-destructive` template loaded into an
isolated `POLICIES_DIR`, `approval_mode="refuse"`, call `bash rm -rf build`: returns within 100 ms,
`denial_kind="approval_unavailable"`, `policy_id="block-destructive"`, `APPROVALS_DIR` contains no
record, the audit log has one `tool.ask` entry. (2) The same call under `"wait"` with a
monkeypatched clock still creates the record and resolves as `approval_timeout` (unchanged path).
(3) `run_agent_turn` with a backend that requests that call: `stop_reason="approval_unavailable"`,
`ok=False`, backend call count 1, the session's last unit is the assistant call plus a tool message
whose text carries `REFUSED [approval_unavailable]`, and no second request was made. (4) The
`tool_result` trace record for (3) carries `policyId` and `reason`. (5) Under `"refuse"`, a
`gate_denied` (deny template) and an `invalid_call` still continue and are still bounded by the
existing limit — the specificity proof. (1), (3) and (4) must fail at the assertion, not at setup.

**Acceptance / oracles:** elapsed time, approval-store contents, audit entry, `StopReason`, backend
call count, persisted session bytes, and trace payload fields. `FakeDriver`/`DocketDriver` parity:
the driver's `TurnResult.error` contains the policy id verbatim.

**Validation:** focused nodes; `test_docket_driver.py`, `test_tool_registry.py`,
`test_runtime_adapter_fixture_contract.py` (the field must not add a CLI import to the runtime
closure); Ruff/format, strict mypy, both owning specs; full pytest, goldens, specs, metrics.

**Handoff:** report the new field/literals, the exact spec requirement numbers touched, elapsed
times, and confirmation that the `"wait"` tests ran unmodified.

### W30-C3 — add the trace subscriber seam and publish the harness contract before the command

**Status:** TODO · **Size:** M · **Owner:** —

**Explicit request / trigger:** Tack ADR 0066 decision 4 (2026-09-08) builds no adapter until docket
publishes a versioned non-interactive contract; `docs/contracts/` does not exist; `core/trace.py::
trace_event` has no subscriber, so nothing can stream the redacted event record to a caller without
tailing docket's own file. D-35 decisions 4 and 5.

**Goal:** (a) `core/trace.py::subscribe(sink) -> ContextManager` backed by a module-level list; every
sink is called synchronously with the exact record `trace_event` is about to append, after
redaction and before the write; a raising sink is suppressed (mirrors `_emit_trace`'s best-effort
rule) and never changes `trace_event`'s return; with zero sinks the function is byte-identical.
(b) New `core/harness.py`, pure: `HARNESS_CONTRACT_VERSION = "1.0.0"`; Pydantic `HarnessEvent`
(envelope `v`, `token`, `seq`, `ts`, `event` = the trace record), `HarnessResult` (`v`, `token`,
`status ∈ {ok, failed, blocked, cancelled, refused}`, `stop_reason`, `error`, `blocked` = `{tool,
call_id, denial_kind, policy_id, reason} | null`, `model = {requested, served}`, `usage =
{input_tokens, output_tokens, cached_tokens, turns}`, `cost_usd: None`, `run_state`),
`HarnessStatus` (`live | finished | unknown`); `preflight(environ, home_default) -> Refusal | None`
(unset `DOCKET_HOME`; equals the default home after resolution; missing `DOCKET_LLM_BASE_URL`;
`DOCKET_NO_TRACE=1`; workspace not a directory); `agent_meta_for(agent_id, workspace, model, role)`
returning an `AgentMeta` (`kind=project`, `codebase=workspace`, `role` default `implementer` — the
built-in role with `denied_tools=()`; a role whose denials include `write` is a usage error);
`result_from(turn: TurnResult, usage: UsageReport, run: dict) -> HarnessResult` (ok → `ok`;
`failure_kind="run_cancelled"` → `cancelled`; error carrying `approval_unavailable` → `blocked`
with the parsed rule; else `failed`; `served = turn.raw.get("model")`). (c)
`scripts/harness_schema.py` writes `docs/contracts/harness-v1/schema.json` from
`model_json_schema()`; a test regenerates into memory and asserts byte equality with the committed
file. (d) `tests/fixtures/harness-contract/v1/{ok,blocked,cancelled,refused}.ndjson`, hand-authored
from the models, validated line by line; the last line of each is a `result`; a fixture with
`v="0.9.0"` must fail closed. (e) New `specs/api/harness-mode.spec.md` v1.0.0 with Status
"Contract defined and test-pinned; `docket harness` ships in W30-C4" — the honest status, not
"Implemented".

**Non-goals:** no CLI, no stdout writing, no signal handling, no `EVENT_TYPES` change, no
hand-edited schema, no `jsonschema` dependency (Pydantic validates; the schema is a published
artifact), no `specs/README.md` row (integrator, C5), no `docket-runtime` packaging change.

**Owns:** `core/trace.py` (`subscribe` and the sink call inside `trace_event` only), new
`core/harness.py`, new `scripts/harness_schema.py`, new `docs/contracts/harness-v1/`, new
`tests/fixtures/harness-contract/`, new `tests/integration/test_harness_contract.py`, new
`specs/api/harness-mode.spec.md`. **Forbidden:** `tools.py`, `agent_loop.py`, `toolbox.py`, `cli/`,
`config.py` (no new home-derived constant is needed; if one appears, it goes into
`_DOCKET_HOME_PATHS` in `conftest.py` in the same commit), central files.

**RED tests:** (1) subscribe: a list sink receives, in order and on the calling thread, records
equal to what `read_trace` later returns from the file; after the context exits it receives
nothing; under `DOCKET_NO_TRACE=1` it receives nothing and the return is `"suppressed"`; a sink
that raises leaves the file write and return value unchanged; a zero-sink `trace_event` produces
a record byte-identical to a pre-change capture. (2) schema pin, (3) every fixture validates and
the unknown-version fixture fails closed, (4) preflight table — one case per refusal reason plus
one acceptance, (5) `result_from` mapping table, (6) `agent_meta_for` round-trips through
`AgentMeta.model_validate` and rejects a write-denied role. (1) must fail before the seam exists;
(2)–(6) fail on missing module/files.

**Acceptance / oracles:** sink-versus-file record equality, byte-identity of the committed schema,
fixture validity, typed refusal reasons, and the mapping table are the oracles. `validate-specs.sh`
passes with the new spec's Status naming C4 as the shipping card.

**Validation:** focused tests; `test_trace_audit.py`, `test_trace_retention.py`,
`test_serve_traces_cursor.py` (the read side must not see a shape change); the
runtime-closure artifact test (the new module must stay CLI-free if included, or be excluded
deliberately and said so); Ruff/format, strict mypy, `validate-specs.sh`; full pytest, goldens,
metrics.

**Handoff:** report the schema path and its digest, the fixture list, the exact sink call site,
and whether `core/harness.py` is inside or outside the runtime closure and why.

### W30-C4 — ship `docket harness run` and `docket harness status`

**Status:** TODO · **Size:** M · **Owner:** — · **Depends on:** C1, C2, C3 merged to `main`

**Deterministic trigger:** after C1–C3, the seams and the contract exist and nothing calls them —
the repository's recorded "unwired machinery" shape. `docs/contracts/harness-v1/schema.json` has no
producer; Tack ADR 0066 needs a binary to probe. D-35 decisions 1, 3, 7, 8, 9, 10, 12.

**Goal:** `cli/_harness.py` with `run --workspace DIR (--task TEXT | --task-file PATH) --model
PROVIDER/ID [--role implementer] [--timeout S] [--agent-id ID]` and `status TOKEN`; one
`@app.command("harness", ...)` block in `cli/__init__.py` following `cmd_runs`. Sequence, all
synchronous on the main thread: `harness.preflight` (exit 2 + one `result{status: refused}` on
stdout) → write the meta through `edges/store.py` → `runs.create_run("cli", agent_id)` → emit
`harness_start{token, pid, requested model, workspace}` as event seq 0 → install a `SIGTERM`
handler whose only action is `runs.cancel_run(token)` → `with trace.subscribe(emit)` →
`runs.execute(token, lambda: [driver.run_turn(agent_id, session_key, task, timeout, env,
trace_project=agent_id)])` with `ToolContext.approval_mode="refuse"` reaching the driver
through the existing internal env-coordinate precedent: a `DOCKET_APPROVAL_MODE` constant beside
`PIPELINE_WORKTREE_ENV` in `core/runtime_driver.py`, passed in `run_turn`'s `env`, popped by
`DocketDriver.run_turn` before the tool env is built and mapped onto `ToolContext.approval_mode`
(exactly how `DOCKET_PIPELINE_WORKTREE` already travels) — no Protocol change, no new keyword
→ `driver.usage(agent_id)` → `harness.result_from` → one `result` line → exit 0/1. stdout is
line-buffered (`sys.stdout.reconfigure(line_buffering=True)`) and carries **only** NDJSON; every
log goes to stderr via `ui`'s stderr console; `ui.info/success/warn` (stdout) are forbidden in this
module. `status TOKEN` maps `runs.get_run` to `HarnessStatus` plus the terminal `result` when
finished.

**Non-goals:** no interactive approvals (decision 11), no pod/team, no server, no provisioning of
worktrees or clones, no second driver, no `on_spawn`/pid registration of the harness itself in
`pids`, no README claim (C5), no `docket-runtime` change, no new `config.py` constant.

**Owns:** new `cli/_harness.py`; one command block in `cli/__init__.py`; the smallest addition in
`core/harness.py` the sequence needs; the `DOCKET_APPROVAL_MODE` constant in `core/runtime_driver.py`
and its pop in `edges/adapters/docket_runtime.py::run_turn`; `specs/api/harness-mode.spec.md` Status → "Implemented" with
version bump; a `docket harness` section in `docs/commands.md`; new `tests/integration/test_harness_cli.py`;
`tests/golden/cases/help.golden` regenerated **because a new command appears in `docket help`** —
diff explained line by line in the commit. **Forbidden:** `agent_loop.py`, `tools.py`, `toolbox.py`,
`runs.py`, `approval.py`, `docket_runtime.py` beyond the one env-coordinate pop in `run_turn`,
`specs/README.md`, README, central files.

**RED tests (all against an isolated `DOCKET_HOME` and the loopback OpenAI-compatible
`ThreadingHTTPServer` stub pattern from `test_approval_gated_dispatch.py`, driving the real
`python -m docket` subprocess):** (a) **ok:** stub scripts one `write` call then a final message;
stdout parses line by line, seq is contiguous, the order is `harness_start`, `session_start`, …,
`tool_call`/`tool_result` pair, `session_end`, `result`; every line carries `v="1.0.0"` and the
token; `result.status="ok"`, `model.served` equals the `model` the stub put in its body (deliberately
different from the requested id), `usage` equals the stub's summed `usage` fields, `cost_usd` is
null; exit 0; the run record is `succeeded`; the workspace contains exactly the tool's write;
stderr is non-empty and stdout has no non-JSON byte. (b) **blocked:** `block-destructive` template
in the isolated `POLICIES_DIR`, stub requests `bash rm -rf build` → `result.status="blocked"`,
`blocked.policy_id="block-destructive"`, exit 1, no approval record, run `failed`, one backend
request. (c) **cancelled:** stub requests `bash sleep 30`; the test sends `SIGTERM` to the
subprocess 0.5 s after the `tool_call` event arrives → `result.status="cancelled"` within 3 s, exit 1,
the child pgid recorded in the event stream is gone, the run record is `cancelled` with
`requestedAt`/`observedAt`/`stoppedAt`. (d) **refused ×5:** unset home, default home, missing base
URL, `DOCKET_NO_TRACE=1`, missing workspace → exit 2, exactly one stdout line, no run record, no
meta written. (e) **status:** `live` while (c) is inside its tool call, `finished` with the result
afterwards, `unknown` for a random token. (f) **isolation:** the developer's real `~/.docket`
byte-identical before and after (a)–(e) — assert with a snapshot, do not assume the conftest guard
covers a subprocess. (a)–(c) must fail on the missing command; (d) on the missing preflight.

**Acceptance / oracles:** parsed NDJSON, exit codes, run-record state, approval-store contents,
child-group liveness, workspace diff, home snapshot. **Live oracle (handoff evidence, not a
fixture):** one run against llama.cpp `127.0.0.1:8081` with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`, a
temporary home and a throwaway workspace; report the transcript's event count, served model, token
totals and exit code.

**Validation:** focused tests; `test_runs_cli.py`, `test_cli_json_shapes`-family (no existing shape
changed), `test_docket_driver.py`; Ruff/format, strict mypy, `validate-specs.sh`; full pytest;
**goldens regenerated for `help` only**, every other case byte-identical; metrics.

**Handoff:** report the exact route by which `approval_mode` reaches `ToolContext`, the exit-code
table, the golden diff, the live-run figures, and any refusal reason the preflight table lacks.

### W30-C5 — close Phase 24 truthfully and hand the contract to the consumer

**Status:** TODO · **Size:** S · **Owner:** integrator · **Depends on:** C4 merged

**Trigger:** the board contract requires closure to match what shipped, and Tack ADR 0066
decision 4 needs a path, a version and a commit to pin against.

**Goal:** date D-35 in ROADMAP §6 and mark Phase 24 / Wave 30 done in the status table; move this
section to the completed record; add the `harness-mode.spec.md` row to `specs/README.md`; record
the three-exit-code exception in `specs/api/cli-interface.spec.md`'s Return Code Convention (version
bump, changelog); one README sentence scoped to "one agent, one workspace, non-interactive,
caller-owned home" with `scripts/metrics.py --check` green; `CHANGELOG.md` entry; a consumer
handoff packet in `.agents/handoffs/` naming `docs/contracts/harness-v1/schema.json`, the fixture
directory, `HARNESS_CONTRACT_VERSION`, the exact commit, the exit-code table and the two amendments
(D-30 for `bash`; `approval_mode`) so ADR 0066 can proceed.

**Non-goals:** no new behaviour, no claim that decisions/artifacts are supported on the Tack side
(that is Tack's probe to prove), no dollar figures, no "tamper-proof"/"cancel-guaranteed" wording
beyond what C1 measured.

**Acceptance / oracles:** `validate-specs.sh`, `metrics.py --check`, full gates green on the closing
commit; the status table, §6, this board, the spec index and README agree; the handoff packet
resolves every path it names.

---
