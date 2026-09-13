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
> ## ◉ ACTIVE BOARD — WAVE 35 (2026-09-13): second docstring sweep, one dead flag, one lane rule
>
> **Wave 35 is the active section below.** Six docstring-only cards take the function-docstring
> ratchet from 372 towards about 110 (`core/dispatch.py` alone holds 50), one card retires the
> `gatesEnabled` fleet flag that the Wave 34 audit showed has no reader and no writer outside a
> hidden debug verb, and one card gives the integration lane's `SUBJECT` line a rule and a guard.
> All eight are one-worker cards with disjoint file ownership; the board, ROADMAP, README and
> CONTRIBUTING counts stay integrator-owned.
>
> **Waves 33 and 34 closed on 2026-09-13** and are archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md): the Wave 32 audit and a
> first docstring sweep (558/112 to 372/40), then the D-36 function split under a function-span
> ratchet, two measured fixes, and the fourth unwired-machinery instance (`docket gates
> enable/disable`, claims corrected; wire or retire is an open maintainer decision recorded in
> `specs/functional/security-gates.spec.md`).
>
> **W29-C7 stays claimable but unclaimed.** It publishes the provenance-complete beta and
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

## ◉ WAVE 35 ACTIVE (2026-09-13) — second docstring sweep, one dead flag, one lane rule

**Measured at `a6ce41e` (all gates green, main pushed).** `scripts/maint/comment_lint.py` with
the enforced budget (module 12 lines, def 3 lines) over `src/` and `tests/` counts 372
over-budget function docstrings and 40 over-budget module docstrings, the shrink-only baseline
`scripts/maint/comment-baseline.json` left by Wave 33. The per-file tally is steep at the top
and flat below: `core/dispatch.py` 50, then twenty files at 6 to 11 each, then a long tail
under 6. The Wave 34 audit classified `FleetSecurity.gates_enabled` as cli-only: `rg -n
'gates_enabled|gatesEnabled' src/` finds the field, two accessors in `core/fleet.py`, and the
hidden `_json gates-get`/`gates-set` verbs in `cli/__init__.py`; no live-path reader, no
product writer, no documentation. The integration lane declares `SUBJECT` on every file with
no rule behind it: seven values are free text (`"edit snapshot"`, `"logs command"`), six name
a module the file does not exercise (`test_agent_loop.py` says `docket.core.llm`), and
`tests/guards/test_layout.py` checks only the unit lane.

**Rules for every docstring card (C1 to C6).** Only docstrings change: the integrator strips
docstrings from both revisions and compares `ast.dump`; any code difference rejects the branch
whole. Every invariant, "why", fail-closed, limit, ordering or "never" sentence survives,
compressed if needed; a docstring may stay over budget when its rationale lives nowhere else.
History, card ids, dates, signature restatement and step narration go. A paragraph that already
lives in a spec becomes one line citing the spec path. Typer command docstrings are user help
and stay byte-identical. No `#` comments added, no other file touched.

**Contention.** The six docstring packets, C7 and C8 own disjoint files. C7 owns
`tests/integration/test_data_layer.py`; C8 therefore leaves that file's `SUBJECT` line alone
and the integrator sets it at merge. Merge order: C7 and C8 first (they change tests), then
C1 to C6 in any order, with the comment baseline lowered by the integrator after each batch.

| Card | Owns | Over-budget def docstrings at open |
| --- | --- | --- |
| W35-C1 | `src/docket/core/dispatch.py` | 50 |
| W35-C2 | `src/docket/cli/_install.py`, `_mcp.py`, `_pod.py`, `_agents.py` | 11, 11, 11, 10 |
| W35-C3 | `src/docket/core/approval.py`, `llm.py`, `memory.py`, `pod.py` | 11, 11, 11, 10 |
| W35-C4 | `src/docket/core/telegram.py`, `models_policy.py`, `runs.py`, `trace.py` | 10, 9, 9, 9 |
| W35-C5 | `src/docket/core/archetypes.py`, `identity.py`, `models.py`, `orchestrator.py`, `runtime_driver.py`, `tools.py` | 8 each |
| W35-C6 | `src/docket/core/security.py`, `edges/adapters/toolbox.py`, `serve.py`, `cli/_doctor.py`, `core/mcp_tools.py`, `core/policy.py` | 7, 7, 7, 6, 6, 6 |

### W35-C1 — trim docstrings in `core/dispatch.py`

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** 50 of the 372 over-budget function docstrings sit in one 2,247-line
module, the dispatch state machine.

**Goal:** bring every function, method and class docstring in the file to three lines or fewer
where its content allows, keeping every invariant sentence (claim/hop/finalize ordering, the
docket-owned `HEARTBEAT.md` region, verify-gate and reviewer-gate semantics, rework bounds,
cancellation checkpoints). The module docstring is in budget and stays.

**Owns:** `src/docket/core/dispatch.py` only.

**Acceptance / oracle:** `uv run python scripts/maint/comment_lint.py --module-max 12 --def-max 3 src/docket/core/dispatch.py`
reports a lower `long-def-doc` count than 50, with each remaining entry justified in the
handoff; `--check` reports zero archaeology; the integrator's docstring-stripped AST comparison
reports `SAME`; `uv run pytest -q tests/unit/core/test_dispatch.py tests/integration/test_dispatch.py` unchanged and green.

**RED:** the lint command above lists 50 findings on the base commit.

**Focused validation:** the lint command, then `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`.

### W35-C2 — trim docstrings in the `cli/` packet

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** 43 over-budget function docstrings across `cli/_install.py`, `cli/_mcp.py`,
`cli/_pod.py` and `cli/_agents.py`.

**Goal:** as C1, for the four files. Typer `@app.command`/`@app.callback` docstrings are
rendered as user help and into `docs/commands.md`; they are not touched, so the golden suite
and the generated reference stay byte-identical.

**Owns:** the four files only.

**Acceptance / oracle:** as C1 over the four files; additionally `bash tests/golden/run.sh verify-all`
green and `./scripts/gen_cli_docs.py --check` (or the repository's drift check) reports no
change to `docs/commands.md`.

**RED:** the lint command lists 43 findings on the base commit.

**Focused validation:** lint, `bash tests/golden/run.sh verify-all`, then the full python gates.

### W35-C3 — trim docstrings in `core/` packet A

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** 43 over-budget function docstrings across `core/approval.py`, `core/llm.py`,
`core/memory.py` and `core/pod.py`.

**Goal:** as C1, for the four files. `core/llm.py` carries the `TokenUsage` "measured, never
estimated" distinction and `core/memory.py` the `CONTRACT_VERSION` resume rules; both survive.

**Owns:** the four files only.

**Acceptance / oracle:** as C1 over the four files.

**RED:** the lint command lists 43 findings on the base commit.

**Focused validation:** lint, then the full python gates.

### W35-C4 — trim docstrings in `core/` packet B

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** 37 over-budget function docstrings across `core/telegram.py`,
`core/models_policy.py`, `core/runs.py` and `core/trace.py`.

**Goal:** as C1, for the four files. `core/telegram.py`'s inbound-only and four-verb sentences,
`core/runs.py`'s cancellation lifecycle (D-30) and `core/trace.py`'s retention and redaction
bounds survive.

**Owns:** the four files only.

**Acceptance / oracle:** as C1 over the four files.

**RED:** the lint command lists 37 findings on the base commit.

**Focused validation:** lint, then the full python gates.

### W35-C5 — trim docstrings in `core/` packet C

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** 48 over-budget function docstrings, eight in each of `core/archetypes.py`,
`core/identity.py`, `core/models.py`, `core/orchestrator.py`, `core/runtime_driver.py` and
`core/tools.py`.

**Goal:** as C1, for the six files. `core/tools.py` is the chokepoint: every sentence about the
three policy hooks, capability-based denial and the single execution path survives.
`core/runtime_driver.py`'s one-driver-not-a-framework sentence survives.

**Owns:** the six files only.

**Acceptance / oracle:** as C1 over the six files; `tests/unit/core/test_tools.py` unchanged and
green.

**RED:** the lint command lists 48 findings on the base commit.

**Focused validation:** lint, then the full python gates.

### W35-C6 — trim docstrings in the mixed packet

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** 39 over-budget function docstrings across `core/security.py`,
`edges/adapters/toolbox.py`, `serve.py`, `cli/_doctor.py`, `core/mcp_tools.py` and
`core/policy.py`.

**Goal:** as C1, for the six files. `edges/adapters/toolbox.py` "holds no policy" and
`core/mcp_tools.py` "every adapted tool is `kind="write"`" survive. `cli/_doctor.py` has Typer
command docstrings that stay byte-identical.

**Owns:** the six files only.

**Acceptance / oracle:** as C1 over the six files; `bash tests/golden/run.sh verify-all` green.

**RED:** the lint command lists 39 findings on the base commit.

**Focused validation:** lint, golden, then the full python gates.

### W35-C7 — retire the `gatesEnabled` fleet flag

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger (W34-A1, verified by the integrator at `a6ce41e`):** `rg -n 'gates_enabled|gatesEnabled' src/ docs/ specs/ README.md`
finds `FleetSecurity.gates_enabled` (`core/fleet.py:71`), `get_gates_enabled`/`set_gates_enabled`
(`core/fleet.py:282-289`), and the hidden `_json gates-get`/`gates-set` verbs in
`cli/__init__.py` (about line 2636). Nothing on the live path reads it; no product command
writes it (`docket init --no-gates` and `docket gates enable/disable` write
`approvalRoutingState`, per `specs/functional/security-gates.spec.md` requirement 2); no spec,
doc or golden mentions it. Twelve test fixtures seed `"gatesEnabled": false` into `fleet.json`
and `FleetSecurity` is lenient, so an existing `fleet.json` carrying the key keeps loading.

**Goal:** remove the field, the two accessors and the two verbs, and the three tests in
`tests/integration/test_data_layer.py` that exist only to exercise them (`test_security_gates`,
`test_gates_get_false`, `test_gates_set_true`, plus the `gates_enabled` assertion in the
fixture-loading test). Keep the `test_extra_fields_survive` case: an old `fleet.json` with the
key must still load, which is now the property that test proves. Record the removal in the
security-gates spec changelog (version 0.19.2) as the retirement of a flag that had no reader.

**Non-goals:** no change to `approvalRoutingState`/`isolationEnabled` or their commands; no
fixture edits outside the owned test file (the seeded key is legitimate "unknown key survives"
data); no golden regeneration (`tests/golden/fixtures/seed.sh` keeps its key for the same
reason).

**Owns:** `src/docket/core/fleet.py` (the field and the two accessors only),
`src/docket/cli/__init__.py` (the two `_json` verbs only), `tests/integration/test_data_layer.py`,
`specs/functional/security-gates.spec.md` (version line, changelog entry, and the one sentence
near line 678 if it lists the field), the `Security Gates` row in `specs/README.md`.

**Acceptance / oracle:** the `rg` above finds nothing in `src/`; a `fleet.json` containing
`"security": {"gatesEnabled": false}` still validates (the kept test); `uv run pytest -q`,
`bash tests/golden/run.sh verify-all`, `bash scripts/validate-specs.sh` green.

**RED:** the `rg` above lists the field, accessors and verbs on the base commit.

**Focused validation:** `uv run pytest -q tests/integration/test_data_layer.py tests/guards`, golden, specs, then the full python gates.

### W35-C8 — give the integration lane's `SUBJECT` a rule and a guard

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** every file under `tests/integration/` declares `SUBJECT`, but
`specs/test-framework.md` requirement 2 and `tests/guards/test_layout.py` cover only
`tests/unit/`. Measured at `a6ce41e`: seven integration values are free text
(`test_auth_context_maintain_keys_add.py`, `test_edit_snapshot.py`,
`test_list_info_cost_commands.py`, `test_logs_command.py`, `test_models_audit.py`,
`test_profile_scope_models.py`, `test_runtime_execution_envelope.py`) and at least six name a
module the file does not exercise (`test_agent_loop.py`, `test_cooperative_run_cancellation.py`,
`test_role_tools_and_identity.py`, `test_runtime_driver.py`, `test_trace_audit.py` all say
`docket.core.llm`; `test_dispatch_run_records.py` says `docket.serve`).

**Goal:** amend requirement 2 so that every `integration/` file's `SUBJECT` names an importable
`docket` module or package (dotted path, the most specific one the file exercises; a
cross-module file may name a package); extend `tests/guards/test_layout.py` to check
importability for the integration lane (a mismatch with the file name is not an error there);
see the guard fail on the free-text values before fixing them; then set every wrong or free-text
`SUBJECT` to the module the file's imports and docstring say it exercises.

**Non-goals:** no test body changes, no file renames, no change to the unit-lane rule or the
exemption table, no edit to `tests/integration/test_data_layer.py` (C7 owns it; the integrator
sets its `SUBJECT` at merge).

**Owns:** `specs/test-framework.md` (requirement 2, enforcement-status sentence, version 2.17.0
and changelog), the `Test Framework` row in `specs/README.md`, `tests/guards/test_layout.py`, and
the `SUBJECT` line only of every file under `tests/integration/` except `test_data_layer.py`.

**Acceptance / oracle:** the new guard is red on the base commit's seven free-text values (say
so in the handoff with the failure text) and green after; `uv run pytest -q tests/guards`,
`uv run pytest -q`, `bash scripts/validate-specs.sh` green; a scan of every integration
`SUBJECT` shows an importable `docket` path.

**RED:** the extended guard fails on the base commit.

**Focused validation:** `uv run pytest -q tests/guards/test_layout.py`, then the full python gates and `bash scripts/validate-specs.sh`.

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

