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
> ## ◉ ACTIVE BOARD — WAVE 34 (2026-09-13): finish the D-36 function split, two measured fixes, one audit
>
> **Wave 33 closed on 2026-09-13** and is archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). It audited the Wave 32
> closure (it held), retired stale worktrees, branches, a spent script and two never-running
> skips, and merged thirteen docstring-only packets that cut the comment ratchet from 558/112 to
> 372/40 with every file proved code-identical.
>
> **Wave 34 opens from one measurement.** ADR 0007 records the three 500-line functions as split
> into named phases. Measured with nested closures included (`scripts/maint/measure_function_spans.py`
> at `633ef91`), `run_agent_turn` still spans 909 lines through twenty closures, `compact_session`
> 225, `do_POST` 175 and `_doctor_json` 168. A new shrink-only ratchet
> (`tests/guards/test_function_span.py`, ceiling 150) lists seven functions; cards C1 to C4 split
> the four worst and the integrator lowers the file after each merge. C5 fixes a test that failed
> once under parallel load, C6 gives two identical credential tables one owner, and A1 is a
> read-only audit for the fourth unwired-machinery instance the record says to assume exists.
>
> **W29-C7 is the only card left on this board.** It publishes the provenance-complete beta and
> closes Phase 23. Its publication approval from 2026-09-07 still stands and only its ordering ever
> changed. It publishes a public release, which cannot be undone, so it waits on an explicit
> go-ahead rather than on a board gate. Claiming it means marking its section active.
>
> **Two of this file's size targets are still gated.** `TODO.md` reaches 200 lines and `ROADMAP.md`
> reaches 500 once Waves 29 and 30 close and their sections archive. Their planned cards and
> measured triggers are what those waves are executed from, so they were deliberately left in place
> rather than trimmed early.
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

## ◉ WAVE 34 ACTIVE (2026-09-13) — finish the D-36 function split, two measured fixes, one audit

**Measured before scheduling (integrator, 2026-09-13, `633ef91`):** `scripts/maint/measure_function_spans.py`
reports seven functions over 150 lines, nested closures included: `run_agent_turn` 909 (20 nested
closures, own body 87 lines), `compact_session` 225 (`_mutate` 172 inside it), `run_agent_turn._fit_task_request`
184, `builtin_registry` 180, `_DocketHandler.do_POST` 175, `_doctor_json` 168. `builtin_registry` is a
flat registration table and is left in the baseline on purpose. One W33 agent saw
`test_sigterm_after_the_tool_call_event_cancels_within_three_seconds` fail once under parallel load
and pass in isolation and on the base commit. `core/provider.py:35` and `edges/adapters/llm.py:57`
hold byte-identical five-entry credential tables.

**Shared rules for every card.** One worktree, one branch, base `main` at the wave's opening commit.
Workers never edit `tests/guards/function_span_baseline.txt`, `TODO.md`, `ROADMAP.md`, `README.md`,
`CONTRIBUTING.md`, `specs/README.md` or any counting script; the integrator regenerates the baseline
after each merge. A split card is behaviour-preserving: no public signature changes, no new modules,
no test edited or deleted (a split that needs a test change has changed behaviour: stop and report).
Full gates: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`,
plus `bash tests/golden/run.sh verify-all` for anything under `src/docket/cli/`. Commit subjects
`Type: description`, ASCII, no attribution trailer.

**Contention graph.** C1 owns `core/agent_loop.py`; C2 owns `core/session.py` and must keep every
name `agent_loop.py` imports (`CompactionResult`, `append_messages`, `compact_session`, `load_messages`)
with the same signature; C3 owns `serve.py`; C4 owns `cli/_doctor.py`; C5 owns
`tests/integration/test_harness_cli.py`; C6 owns `core/provider.py`, `edges/adapters/llm.py` and one new
unit test. No two cards share a file. Merge order: C6, C5, C4, C3, C2, C1 (smallest blast radius first).

### W34-C1 — split `run_agent_turn` into module-level phases

**Status:** READY · **Size:** L · **Owner:** one worker

**Measured trigger:** `src/docket/core/agent_loop.py::run_agent_turn` spans 909 lines (lines 514 to
1422) with 20 nested closures; `_fit_task_request` alone is 184. ADR 0007 says this function was split.

**Goal:** hoist the nested closures into module-level private functions (or methods on one private
turn-state class) so that no function in the file exceeds 150 lines and `run_agent_turn` reads as a
sequence of named phases. Behaviour identical.

**Non-goals:** no change to `LoopConfig`, `run_agent_turn`'s signature, `approval_unavailable_error`,
stop reasons, trace events, the harness NDJSON contract or session compaction semantics; no new module.

**Owns:** `src/docket/core/agent_loop.py` only.

**Acceptance / oracle:** `uv run python scripts/maint/measure_function_spans.py src/docket/core/agent_loop.py`
prints nothing (no function over 150). `uv run pytest -q` passes unchanged, including
`tests/unit/core/test_agent_loop*.py`, `tests/integration/test_agent_loop.py`,
`tests/integration/test_harness_cli.py` and the byte-pinned fixtures under
`tests/fixtures/harness-contract/v1/`. `git diff --stat` touches one file. The integrator additionally
compares the module's public names and signatures before and after with an AST script.

**RED:** `uv run python scripts/maint/measure_function_spans.py src/docket/core/agent_loop.py` lists
two entries before the split.

**Focused validation:** `uv run pytest -q tests/unit/core/test_agent_loop.py tests/integration/test_agent_loop.py tests/integration/test_harness_cli.py`.

### W34-C2 — split `compact_session` into named phases

**Status:** READY · **Size:** M · **Owner:** one worker

**Measured trigger:** `src/docket/core/session.py::compact_session` spans 225 lines with the 172-line
`_mutate` closure inside it.

**Goal:** split planning, summarisation, atomic-unit validation and the locked write into
module-level private functions; no function in the file over 150 lines. Behaviour identical, including
the fail-closed contract (a failed summarisation leaves the stored history untouched) and the
atomic tool-call/tool-result unit guarantee.

**Non-goals:** no signature change to `compact_session`, `plan_compaction`, `CompactionResult`,
`append_messages`, `load_messages`; no new module.

**Owns:** `src/docket/core/session.py` only.

**Acceptance / oracle:** `measure_function_spans.py src/docket/core/session.py` prints nothing;
`uv run pytest -q` passes unchanged, including `tests/unit/core/test_session*.py` and the compaction
tests under `tests/integration/test_agent_loop.py`; one file in the diff.

**RED:** the measuring script lists two entries for the file before the split.

**Focused validation:** `uv run pytest -q tests/unit/core/ -k session tests/integration/test_agent_loop.py -k compact`.

### W34-C3 — route `do_POST` through per-route handlers

**Status:** READY · **Size:** M · **Owner:** one worker

**Measured trigger:** `src/docket/serve.py::_DocketHandler.do_POST` spans 175 lines; `_handle_post_pods`
already shows the per-route shape.

**Goal:** one private handler per POST route, `do_POST` reduced to auth, routing and error framing; no
function in the file over 150 lines. Byte-identical responses, status codes, audit entries and the
`docket runs` records each route produces.

**Non-goals:** no route added or removed, no auth change, no change to
`specs/data/serve-read-api.spec.md`.

**Owns:** `src/docket/serve.py` only.

**Acceptance / oracle:** `measure_function_spans.py src/docket/serve.py` prints nothing;
`uv run pytest -q` passes unchanged, including `tests/unit/test_serve__*.py`,
`tests/integration/test_serve_*.py` and `tests/integration/test_approval_gated_dispatch.py`; one file in the diff.

**RED:** the measuring script lists one entry for the file before the split.

**Focused validation:** `uv run pytest -q tests/unit -k serve tests/integration -k serve`.

### W34-C4 — split `_doctor_json`

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** `src/docket/cli/_doctor.py::_doctor_json` spans 168 lines.

**Goal:** split the JSON report assembly into per-section helpers; no function in the file over 150
lines; `docket doctor --json` output byte-identical.

**Non-goals:** no check added, removed or reordered; no change to the human-readable output.

**Owns:** `src/docket/cli/_doctor.py` only.

**Acceptance / oracle:** `measure_function_spans.py src/docket/cli/_doctor.py` prints nothing;
`uv run pytest -q` passes unchanged including `tests/unit/cli/test__doctor.py`;
`bash tests/golden/run.sh verify-all` passes 18/18 without regenerating anything; one file in the diff.

**RED:** the measuring script lists one entry for the file before the split.

**Focused validation:** `uv run pytest -q tests/unit/cli/test__doctor.py && bash tests/golden/run.sh verify-all`.

### W34-C5 — make the harness cancellation test deterministic under load

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** on 2026-09-13 a full-suite run alongside twelve other suites saw
`tests/integration/test_harness_cli.py::TestCancelledRun::test_sigterm_after_the_tool_call_event_cancels_within_three_seconds`
fail once and pass on re-run, in isolation, and on the base commit. The test looks up the sleeping
child once, immediately after the `tool_call` event, but that event is emitted before the bash
handler has spawned the child, so under load the single lookup races the spawn.

**Goal:** wait for the child process to appear (bounded poll, deadline of a few seconds) before
asserting it exists, without loosening the three-second cancellation bound, which is the contract
under test.

**Non-goals:** no change under `src/`; no change to the three-second bound; no skip or retry marker.

**Owns:** `tests/integration/test_harness_cli.py` only.

**Acceptance / oracle:** the test passes 20 times in a row locally while `uv run pytest -q -n 0` runs
in another shell (or under `stress`-like CPU load); one file in the diff; the assertion message still
names the missing child on a genuine failure.

**RED:** reproduce the race by inserting a `time.sleep(0.3)` before the bash handler spawns (locally,
not committed) or by running the suite under load; the single lookup fails with
"the sleeping child process was never found".

**Focused validation:** `for i in $(seq 20); do uv run pytest -q tests/integration/test_harness_cli.py -k cancels_within || break; done`.

### W34-C6 — one owner for the provider credential table

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** `src/docket/core/provider.py:35` (`_PROVIDER_CREDENTIALS`) and
`src/docket/edges/adapters/llm.py:57` (`_PROVIDER_CREDENTIAL_NAMES`) are byte-identical five-entry
dicts with separate readers (`provider.py:129`, `llm.py:447`). A provider added to one and not the
other makes `docket models`/provider checks and the adapter's request path disagree silently.

**Goal:** a single definition in `core/provider.py` (public name `PROVIDER_CREDENTIAL_NAMES`), imported
by `edges/adapters/llm.py` (edges may import core), with one unit test asserting the adapter reads the
same object and an import-cycle check (`python -c "import docket.edges.adapters.llm, docket.core.provider"`).

**Non-goals:** no change to the table's contents or to how either reader resolves a credential.

**Owns:** `src/docket/core/provider.py`, `src/docket/edges/adapters/llm.py`, and one new test in
`tests/unit/core/test_provider.py` (create it with `SUBJECT = "docket.core.provider"` if absent, or add to it).

**Acceptance / oracle:** `rg -n 'ANTHROPIC_API_KEY' src/` finds exactly one dict literal; the new test
fails on the base commit (two objects) and passes after; `uv run pytest -q` passes; `mypy src` passes.

**RED:** the new unit test on the base commit.

**Focused validation:** `uv run pytest -q tests/unit/core/test_provider.py tests/unit/edges/adapters/test_llm.py tests/integration/test_provider_agnosticism.py`.

### W34-A1 — read-only audit: the fourth unwired-machinery instance

**Status:** READY · **Size:** S · **Owner:** one read-only worker (no commits)

**Measured trigger:** three recorded instances of "implemented, tested, never wired to the default
path" (W17-1, W18-3, W19-3). The record says to assume a fourth exists; nobody has scanned for it.

**Goal:** for every setting docket persists under `DOCKET_HOME` with a writer in `cli/` (fleet gate and
isolation flags, model policy, retention, schedules, MCP servers, policies, secrets, budgets), name the
reader on the live path (`core/agent_loop.py`, `core/tools.py`, `core/dispatch.py`,
`edges/adapters/docket_runtime.py`, `serve.py` loops). Report every setting whose only reader is in
`cli/` or tests, with file:line evidence for writer and reader.

**Non-goals:** no code change, no doc change, no card creation; the report is the deliverable.

**Acceptance / oracle:** a table of settings with writer, live-path reader (or "none found"), and the
`rg` command that proves it; each "none found" row re-checked once by grepping the setting's key
across `src/`.

---

## ◇ WAVE 29 UNBLOCKED (2026-09-02, paused 2026-09-11, released 2026-09-12) — adoption evidence and public release

**One card left, and its gate has passed.** C1–C6 are merged, closed and archived in
`docs/cycles-ended/todo-waves.md`. W29-C7 (publish the provenance-complete beta and close Phase
23) was deferred behind Wave 31 by maintainer decision on 2026-09-11 so the repository would be
made maintainable before it was published further. Wave 31 closed on 2026-09-12, so W29-C7 is
claimable. Its publication approval from 2026-09-07 still stands; only its ordering had changed.
Claiming it means marking this section active.

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

### W29-C7 — publish a current provenance-complete beta and close Phase 23

**Status:** CLAIMABLE since 2026-09-12, when Wave 31 closed and released the hold placed on
2026-09-11; publication was approved 2026-09-07 and that approval still stands, only the ordering
had changed · **Size:** M · **Owner:** integrator

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

