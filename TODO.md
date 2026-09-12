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
> ## ◉ NO ACTIVE WAVE — one card remains claimable
>
> **Wave 32 closed on 2026-09-12.** Seven cards swept the documentation drift Phases 24 and 25
> left behind. It removed a script, a CI workflow and a pre-commit hook that the contributor guide
> documented and that have never existed; a Telegram "conversational dispatch" claim that was found
> in README.md on 2026-08-05, corrected there, and never swept from the quick start one directory
> away; and a paragraph telling readers a shipped isolation control was inert.
>
> **Its most useful finding was one anti-pattern in three places.** The spec index, the generated
> command reference's environment table, and a pod-blueprint list were each checked against
> reference data that was *retyped rather than derived*, so each reported green while being blind
> to anything nobody had remembered to add. All three now derive their reference set, and each was
> proved by planting something the old version could not have seen.
>
> **Two corrections to the record.** The agent lane is not part of `uv run pytest`; it has its own
> CI job, so "all gates green" from the default suite said nothing about it, and it was red on
> `main` from before this wave. And `DOCKET_APPROVAL_MODE` is not an environment variable despite
> the name — it is a key of the dict `run_turn` receives as `env`, so exporting it does nothing.
>
> **Wave 30 closed on 2026-09-12**, completing Phase 24, and is archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). `docket harness run` and
> `status` ship with a published, versioned, test-pinned contract, and the three seams they needed
> are wired and proved reached by a real subprocess rather than by a unit test.
>
> **W29-C7 is the only card left on this board.** It publishes the provenance-complete beta and
> closes Phase 23. Its publication approval from 2026-09-07 still stands and only its ordering ever
> changed. It publishes a public release, which cannot be undone, so it waits on an explicit
> go-ahead rather than on a board gate. Claiming it means marking its section active.
>
> **Wave 31 closed on 2026-09-12** and is archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). Thirteen cards shipped:
> test lanes with a budgeted agent lane, structural guards, a ratcheted comment budget, one unit
> file per module, in-process CLI tests, a generated command reference, the board archive and
> decision ADRs, the three functions over 500 lines split into named phases, and two cards opened
> by defects the work itself surfaced.
>
> **Both things that were waiting on it are now claimable, and nothing chooses between them
> automatically.** W29-C7 publishes the provenance-complete beta and closes Phase 23; its
> publication approval from 2026-09-07 still stands and only its ordering had changed. All of
> Wave 30 (Phase 24, harness mode, D-35) is also unblocked. Whichever is claimed first, mark its
> section active so the board has one marker again.
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

## ◇ WAVE 32 CLOSED (2026-09-12) — documentation truth pass and two deferred follow-ups

All seven cards merged. Four parallel read-only audits measured the drift before anything was
scheduled; the full per-finding record is in the integrator's plan file.

| Card | Shipped | Proved by |
| --- | --- | --- |
| W32-C1 | `SSD-WORKFLOW.md`: removed a script, a CI workflow and a hook that never existed | eight real `ci.yml` job names checked individually |
| W32-C2 | the public spec index derives from disk; three versions, three missing rows corrected | a planted spec file failing the guard by name |
| W32-C3 | the harness contract paths an external consumer reads first | `ls` on both directories |
| W32-C4 | partial-repointer ratchet at 14; six worst converted; dead scaffolding deleted | a planted partial repointer going red |
| W32-C5 | three false capability claims removed from the guides | `isolation.refused` traced to the live adapter |
| W32-C6 | harness mode and the ADRs made discoverable; name collision cross-linked | anchors resolved; harness commands run |
| W32-C7 | env-var table derived: 10 hardcoded rows replaced by 55 scanned; exit codes corrected | a planted env var failing `--check` |

**Three cards corrected their own briefs and were right every time** — on which agent lanes
exist, on `DOCKET_APPROVAL_MODE` not being an environment variable, and on a guard already
existing where the brief said none did. Each correction came from measuring rather than from
reasoning about the instruction.

**The re-measured follow-up had grown** from 16 functions across 13 modules to 20 across 15,
which is why the board rule says a gap list decays and must be re-measured before scheduling.

**Integrator note for the next wave:** a card's gates pass on the card's branch, which proves
nothing about the merge. Merging C2 broke the agent-lane ratchet its own handoff reported green,
and only re-running the gates on the merge result caught it.

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

