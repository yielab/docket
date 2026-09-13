# docket — Roadmap & Implementation Plan

This is the **single source of truth** for docket's roadmap *and* its executable task plan.
(Consolidated 2026-06-22 from the former root `ROADMAP.md` + `internal-docs/IMPLEMENTATION-PLAN.md`,
which duplicated each other at two altitudes — high-level phases vs. detailed tasks. Now one file.)

It takes docket from a polished single-user CLI to a hardened, portable, operable tool — sequenced
so each phase is independently shippable and raises the bar on **security → reliability →
portability → operability → product**. Earlier phases unblock later ones.

---

## ⇢ STATUS AT A GLANCE — every phase, one line each

**Last updated: 2026-09-13.** Every numbered phase 0–22 and Waves 24–28 are complete. **Phase 25
(human maintainability, D-36) and Phase 24 (harness mode, D-35) both completed on 2026-09-12**, the
first as Wave 31's thirteen cards and the second as Wave 30's five. **Wave 32 closed the same day** (2026-09-12): a
documentation truth pass over the drift those two phases left, plus the two follow-ups Wave 31
measured and deferred. **Waves 33 and 34 closed 2026-09-13**: an audit of the Wave 32 closure, repository hygiene, a docstring-only comment sweep (558/112 to 372/40 without changing a line of code), then the D-36 function split finished under a new function-span ratchet, two measured fixes, and a read-only audit that found the fourth unwired-machinery instance. **Wave 35 closed the same day**: a second docstring sweep (372/40 to 229/29), the dead `gatesEnabled` flag retired, and the integration lane's `SUBJECT` line given a rule and a guard. **No program is active.** Phase 23 remains paused with one card left, W29-C7, which publishes the
provenance-complete beta; note that everything since 2026-09-07 has changed what that would
publish, so its recorded approval covers a tree that no longer exists. Executable cards live in
[TODO.md](TODO.md).

> **How to read the rest of this file.** Nothing below is a task list. The planned programs
> (Phases 23–25) hold their own wave tables; executable cards are in `TODO.md`. **The completed
> phase records (0–22, the Bash→Python migration) and this file's decision changelog were moved
> verbatim to [docs/cycles-ended/](docs/cycles-ended/README.md)** (`roadmap-phases.md`,
> `roadmap-changelog.md`, SHA-256 manifest). **This table is the authority; a phase heading is not.**

| Phase | What it was | Status |
| --- | --- | --- |
| 0–4 | Truth & correctness, cost enforcement, consolidation, park experiments, strengthen | ☑ done |
| 5 | Channel portability + system snapshot | ☑ done |
| 6 / 6b | Model & provider agnosticism · tier-less role→model policy | ☑ done |
| 7 | *Renumbered away* — the former "Product & community"; folded into 11–13 | — n/a |
| 8 | Agent observability, guardrails & drift (HITL) | ☑ done |
| 9 | Contract integrity: spec↔runtime gap | ☑ done |
| 10 | Agent architecture: project pods | ☑ done |
| 11 | Competitive differentiation | ☑ done (2026-06-25) |
| 12 | Consolidation & hardening | ☑ done (2026-07-02) |
| 13 | Close the differentiation gaps | ☑ done (2026-07-02) |
| 14–18 | **Platformization I–V** — dispatch hardening, wired governance, declarative orchestration, context/memory, runtime-driver port + MCP | ☑ done (38 cards, 7 waves, closed 2026-07-31) |
| 19 | **docket takes the runtime (D-19)** — owns the loop, registry, all three policy hooks, approvals, audit, sessions. No daemon. | ☑ done (13 cards, waves 8–11) — **record in `docs/cycles-ended/todo-waves.md` + §Changelog; this file has no Phase 19 section** |
| 20 | Fleet observability | ☑ done **at cut scope** — D-24 cut ~half; P20-2 shipped, P20-4 was a phantom card |
| 21 | The product substrate (`packages/docket-runtime/`) | ☑ done **at cut scope** — P21-1, P21-5 shipped; rest cut by D-24 |
| 22 | Control-plane write API for an external plan-of-record | ☑ done (6 cards, wave 16, 2026-08-04) |
| 23 | **Product truth and ecosystem proof (D-25)** — first successful turn, trustworthy release, atomic governance, then portable enforcement evidence | ⏸ paused 2026-09-11 (C1–C6 shipped; W29-C7 deferred behind Phase 25) — — Wave 29 adoption evidence/public release activated |
| — | **Waves 17–18** (not phases): MCP-tools-in-a-turn, config single-owner, audit chain across rotation, isolation actually wired | ☑ done (2026-08-05) |
| — | **Wave 19** (not a phase): the defects a *real* dispatch on a *real* small-context endpoint found — worktree members told an unreachable root, tool-output ceiling unreachable from config | ☑ done (2026-08-05) — its remaining session-compaction finding was carried into and closed by Wave 20 |
| — | **Wave 20** (not a phase): bounded contributor harness + live-turn context efficiency | ☑ done (2026-08-19) — repo skills/hooks, MCP output parity, live fail-closed and hierarchical compaction, measured cross-hop redundancy, and step-scoped durable history shipped |
| — | **Wave 21** (not a phase): daemon-free current-state truth pass | ☑ done (2026-08-19) — current contracts, docs, source prose, and hermetic fixtures now describe only Docket-owned runtime/state; explicit migration history preserved |
| — | **Wave 22** (not a phase): observable whole-product workflow proof | ☑ done (2026-08-19) — one hermetic command crosses CLI subprocesses, loopback HTTP, the runtime/tool/gate path, approval resume, and durable observability state |
| — | **Wave 23** (not a phase): real local-model workflow + reachable startup state | ☑ done (2026-08-19) — an opt-in Qwen canary crosses the full workflow; bounded HEARTBEAT/AGENTS/TOOLS/MEMORY context now reaches every live turn without widening tool roots |
| — | **Wave 24** (not a phase): realistic memory-backed Git maintenance | ☑ done (2026-08-19) — exact durable memory fails closed on corruption; real worktree code continuity reaches Reviewer/Tester; public plus hidden acceptance passes on the local model |
| — | **Wave 25** (not a phase): live-model request and outcome truth | ☑ done (2026-08-30) — all 11 cards and the live private-boundary canary passed; integrated at `6b925f0` with full commit-level gates green |
| — | **Wave 26** (not a phase): first-use, release, atomic-governance, cancellation, and public truth | ☑ done (2026-08-31) — all cards through C11 shipped; artifact journeys, public docs, and full closure gates pass |
| — | **Wave 27** (not a phase): dependency safety and public front door | ☑ done (2026-09-01) — advisory closed and reproducible public assets/README shipped |
| — | **Wave 28** (not a phase): portable governance proof | ☑ done (2026-09-02) — installed-artifact parity, scoped public truth, and Linux/macOS closure evidence pass |
| — | **Wave 29** (not a phase): adoption evidence and public release | ◇ unblocked (2026-09-12) — C1–C6 done and archived; C7 was deferred behind Wave 31 and is claimable now, its publication approval still standing |
| 24 | **Harness mode (D-35)** — docket as a governed, non-interactive execution harness a plan-of-record (Tack) spawns as a subprocess | ☑ **complete (2026-09-12)** — Wave 30, five cards. `docket harness run`/`status` ship with a published, versioned, test-pinned contract; the three seams it needed are wired and proved reached by a real subprocess |
| 25 | **Human maintainability (D-36)** — test lanes with a budgeted agent lane, one unit file per module, zero-archaeology comments ratcheted in CI, generated CLI/API docs, board and roadmap cut to size | ☑ **complete (2026-09-12)** — Wave 31, thirteen cards. The board and roadmap reach their line targets only when Waves 29 and 30 close and their sections archive; their planned cards are what those waves are executed from |
| — | **Wave 31** (not a phase): baseline → lane move → structural guards → comment hygiene → per-module merges → in-process CLI tests → generated docs → board archive → split the three 500-line functions | ☑ complete (2026-09-11 to 2026-09-12) — thirteen cards W31-C0…C10, C8 split in two; C9 and C10 opened by defects the work surfaced |
| — | **Wave 30** (not a phase): in-flight bash cancellation, non-interactive approval outcome, trace subscriber, harness contract + command | ☑ complete (2026-09-12) — five cards W30-C1…C5. C1 merged on a second pass after a pipe-drain regression; C2 and C3 formed a seam that emptied the contract's blocked payload until a round-trip test was added |
| — | **Wave 32** (not a phase): documentation truth pass — four parallel audits over disjoint doc groups, then seven cards splitting the drift Phases 24 and 25 left | ☑ complete (2026-09-12) — removed a script, CI workflow and hook that never existed; swept a repeat of defect W19-5 from the quick start; and found one anti-pattern in three places, a spec index, an env-var table and a blueprint list each checked against retyped rather than derived reference data |
| — | **Wave 33** (not a phase): audit of the Wave 32 closure, repository hygiene, docstring-only comment sweep | ☑ complete (2026-09-13) — the closure held (gates, baselines, metrics all in sync); fifteen merged worktrees, eight merged branches, a spent migration script and two never-running skips retired; thirteen bounded docstring packets merged, each proved AST-identical with docstrings stripped, and the comment baseline ratcheted to 372/40. Found the gitignored CLAUDE.md still calling session compaction unwired two waves after W20-C2 wired it |
| — | **Wave 34** (not a phase): finish the D-36 function split behind a function-span ratchet, two measured fixes, one read-only audit | ☑ complete (2026-09-13) — `tests/guards/test_function_span.py` (150-line ceiling, closures included) listed seven functions; C1 to C4 split `run_agent_turn` (909 lines, twenty closures), `compact_session`, `do_POST` and `_doctor_json` with zero behaviour change, each proved by an unchanged public API and untouched tests, leaving one deliberate entry; C5 made the harness cancellation test deterministic under load; C6 gave the duplicated provider credential table one owner; A1 found the fourth unwired-machinery instance, `docket gates enable/disable` writing a flag nothing on the live path reads while spec, README and command help claimed it changed delivery, and C7 made those claims true (wire or retire stays an open maintainer decision) |
| — | **Wave 35** (not a phase): second docstring sweep, one dead flag, one lane rule | ☑ complete (2026-09-13) — six docstring-only packets (C1 to C6) over twenty-five modules, each proved AST-identical with docstrings stripped, took the comment baseline from 372/40 to 229/29; C7 retired `FleetSecurity.gatesEnabled`, a flag with no live-path reader and no product writer (spec 0.19.2); C8 made every integration test's `SUBJECT` an importable `docket` path, guarded by `test_layout.py` (spec 2.17.0, seen red on seven free-text values). Two things the wave found on the way: `scripts/gen_cli_docs.py --check`, a CI job, had raised ImportError since the Wave 34 credential-table merge because the integrator's batch gates never ran it (fixed, and added to the gates), and the `maintain sessions` banner still said sessions are never compacted (corrected) |

**Deliberately NOT scheduled**, and not a queue to work down — each is cut or deferred behind a named
trigger (see §4.5's prioritization rule, D-24, and §7):

| Not doing | Why |
| --- | --- |
| Multi-tenancy / the tenant axis | **CUT** (D-22, D-24). Trigger to revisit: docket itself serving more than one end customer from one host. |
| Streaming · browser automation | **CUT** by D-24 — no measured need in *this* system. Use MCP for browser tooling. |
| OpenTelemetry export | Still unscheduled. D-25 permits a bounded adapter-era card only if two-runtime evidence shows JSONL cannot preserve cross-runtime trace identity. |
| Egress lockdown | Deferred (D-23). `fetch` is the inspectable path, not the only one. |
| A dashboard of our own | Ruled out since Phase 11 and reaffirmed by 22 — docket feeds one. |
| Build-agent profile · MCP listing cache · Go/Rust rewrite | Deferred behind named triggers. |

Session compaction is no longer in this deferred table: its trigger fired and W20-C2/C2b shipped
the live fail-closed and hierarchical paths. W20-C3 then measured material cross-hop duplication,
and W20-C4 closed it with step-scoped durable histories while preserving typed handoffs.

**Known-true limits live in [CLAUDE.md](CLAUDE.md)**, not here — they change faster than this file.

**Release:** `0.2.0-beta.2` is in approved publication preflight. Every release carries a SemVer
`-beta.N` suffix until the project is field-hardened enough to drop it (see README's beta warning).

Status legend used in the older sections below: ✅ / ☑ done · 🟡 planned-next · 🟠 audit-driven,
planned · 🚧 in progress · 🗓️ planned / deferred

> **Consolidation note (2026-06-23):** this file is now the **single roadmap**. The former
> `ARCHITECTURE-AUDIT.md`, `MIGRATION-PLAN-PYTHON.md`, and `MIGRATION-TASKS.md` were folded in
> here and removed — their durable content lives in `docs/cycles-ended/roadmap-phases.md` (completed migration) and §4.5
> (architectural principles); their executable task boards are spent (the migration shipped).
> Git history retains the originals.

## Tracked decisions (not yet scheduled)

- 🗓️ **Project rename (deferred).** "docket" collides with Ruby Docket, is a generic word, and is
  hard to search. The decision is to **keep "docket" as an independent product name for now** and
  revisit a searchable, namespace-clean rename (candidate: `docketctl`) before any wide public
  launch. Do not anchor positioning to the retired runtime: D-19 made Docket own the loop and
  removed that compatibility relationship. Touch points a rename must update: binary
  name, `install.sh`/`uninstall.sh` paths, Homebrew `Formula/`, docs, and the metrics script.
- ☑ **Version-pinned CI for the retired daemon — CUT (2026-08-19).** Superseded by D-19's clean
  break: Docket has no daemon binary, adapter, shared schema, package dependency, or compatibility
  layer to test. Current compatibility is the OpenAI-compatible model endpoint plus optional MCP,
  as recorded in [COMPATIBILITY.md](COMPATIBILITY.md). Installing an unrelated runtime weekly would
  add a false signal rather than protect a live contract.
- ☑ **Telegram conversation memory (TC-1…TC-7, shipped 2026-07-20).** A live investigation
  (triggered by the docket Telegram group dropping an accepted task across a context reset) found
  three gaps *beyond* the memory-durability fix (WORKFLOW_AUTO `CONTRACT_VERSION` v3): split
  identity from leftover external-runtime scaffolding, no durable conversation persistence, and no
  registry. **Delivered:** docket-owned identity — optional `Persona` on `AgentMeta` rendered into
  `SOUL.md`, `docket persona`, and `docket doctor` quarantine of `IDENTITY.md`/`BOOTSTRAP.md`
  (`core/identity.py`); a docket-owned **conversation registry** (`core/conversations.py`,
  `docket conversations list/show/resume/set`, seeded at `docket wire`); and a doctor advisory on
  the memory index. TC-3 established the retired runtime's per-agent sqlite as a rebuildable RAG
  index (not a transcript), so durability is docket-owned by design. Full record:
  [internal-docs/telegram-conversation-memory.md](internal-docs/telegram-conversation-memory.md)
  and [agent-structure-analysis.md §6](internal-docs/agent-structure-analysis.md). Deferred:
  `--persona` at `docket add` time; auto-populating `last_message`/`task_ref` from dispatch/serve.
- ☑ **External "opencode" audits evaluated + dismissed (2026-07-20).** Two agent-generated audits
  (`DESIGN-PATTERN-AUDIT.md`, `SECURITY-AUDIT-REPORT.md`) were reviewed against the code and
  **deleted** as net-negative: they fabricated non-existent functions (`_create_agent_meta`,
  `exec_in_workspace`), flagged a dispatch "layer violation" that doesn't exist (`core/dispatch.py`
  delegates execution through the runtime driver and system adapter, no raw subprocess), cited a stale
  `_install.py` size, and otherwise recommended cargo-cult OOP against the deliberate
  functional style. The **one** actionable idea — a boundary guard — was implemented as the true
  invariant: `tests/guards/test_no_subprocess_in_core.py` (core/ must be process-free),
  a sibling of the CH-3 no-UI-in-core test. Its optional adapter-split suggestion became moot when
  D-19 deleted the external-runtime adapter outright.

> Read §1–§4.5 once for mission, ground truth, conventions and principles; then take work only
> from `TODO.md`. Completed phase records are in `docs/cycles-ended/roadmap-phases.md`.

---

## Paused program — PHASE 23: product truth and ecosystem proof

**Status:** ⏸ PAUSED (2026-09-11; active 2026-08-30) · **Decision:** D-25 · **Executable detail:** Wave 29 in
[TODO.md](TODO.md) · **Resumable coordinator packet:**
[`docs/cycles-ended/handoffs/phase-23-productization.md`](docs/cycles-ended/handoffs/phase-23-productization.md) (Wave 26 closure packet; Waves 27–29 are recorded below)

### Why this phase is scheduled

The 2026-08-30 read-only audit inspected the live `platform` tree, its release surfaces, 24
current-state specs, 2,374 collected tests, and current open-source peers. The core governed loop,
durable pipeline, role-narrowed registry, typed handoffs, and one `dispatch_tool` policy chokepoint
are valuable. Adoption is nevertheless blocked before those strengths are reached:

- the default `anthropic/claude-sonnet-4-6` onboarding path stores a key but resolves no built-in
  endpoint, while only OpenRouter and Vercel have built-in compatible URLs;
- the recommended Homebrew formula has an all-zero SHA and the wrong license, the installer reads
  mutable `main`, the root wheel exposes `docket-py` rather than the documented `docket`, and the
  release workflow publishes no installable Python artifacts;
- `docket-runtime` and the full distribution install overlapping `docket/*` files;
- audit append, approval resolution, and port/conversation allocation contain unlocked
  read-modify-write transitions reachable from parallel dispatch or the threaded API;
- verdict gates depend on marker placement in free-form model prose, and shipped in-process
  cancellation changes state without interrupting the active turn.

These are deterministic findings from this repository, not generic market-feature requests. They
fire D-24's measured-need rule. The user explicitly requested the resulting productization and
ecosystem plan on 2026-08-30.

### Product boundary and exit contract

Phase 23 ships in this order:

1. **Trustworthy first use:** a clean install reaches one deterministic governed tool turn using a
   provider configuration the onboarding path can actually resolve.
2. **Truthful local governance:** concurrent decisions preserve one audit chain and one state
   transition; verdict and cancellation outcomes match what actually happened.
3. **Hardened single-host operation:** isolation, recovery, secrets, provider compatibility, MCP,
   and parameterized pipelines are improved only from measured Wave 26 evidence.
4. **Portable enforcement proof:** two external runtimes demonstrate the same policy, approval,
   budget, trace identity, and handoff contract before Docket claims framework neutrality.
5. **Adoption evidence:** reproducible releases, a starter integration, failure/chaos cases, and
   published completion/cost/safety/recovery measurements.

Phase 23 is complete only when those claims have executable evidence. It does not add a tenant
axis, hosted scheduler, Docket-owned dashboard, no-code workflow builder, provider-SDK zoo, or a
second orchestration graph language.

### Activation gate — satisfied 2026-08-30

Wave 25's 45 attributed paths landed in `6b925f0` after W25-C7's single authorized live acceptance.
The integrated commit passed 2,377 tests with five contract-labelled skips, Ruff, format, strict
mypy, 24 specs, 18 goldens, metrics, and deterministic smoke. The active-board marker changed once;
Wave 26 then completed on 2026-08-31. Central files (`ROADMAP.md`, `TODO.md`, `README.md`,
`specs/README.md`) remain integrator-owned.

### Wave 26 — first-use and governance truth (complete 2026-08-31)

Wave 26 contains independently shippable cards rather than one release-sized branch. Its initial
ready pool after activation is W26-C1, C2, and C6–C10; C0 is an integrator/maintainer decision, C3
depends on C0+C2, C4 depends on C1–C3, C5 depends on C2, and C11 is the final truth/release
integrator. The detailed trigger, non-goals, live paths, RED cases, acceptance oracles, gates, and
contention boundaries live once in `TODO.md`.

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W26-C0 | One public release source/commit lineage | Done; `main` is canonical and synchronized without history rewrite |
| W26-C1 | Clean configuration reaches the first governed turn | Done; resolvable provider/onboarding path proven |
| W26-C2 | Canonical installable `docket` wheel/sdist | Done; root artifact owns the documented CLI distribution |
| W26-C3 | Immutable, checksummed release artifacts | Done (`0251972`, `5bb106a`); tagged package assets are verified before install/publish |
| W26-C4 | Clean-install-to-first-turn CI release oracle | Done (`f8f897e`, `6c52df7`); exact wheel reaches a governed turn on Ubuntu/macOS |
| W26-C5 | Non-overlapping, documented runtime distribution | Done; artifact boundary and ownership checks pass |
| W26-C6 | Atomic, durable audit append | Done; concurrent append/rotation preserves the chain |
| W26-C7 | Compare-and-set approval resolution | Done; contradictory concurrent winners are rejected |
| W26-C8 | Collision-free pod resource allocation | Done; allocation and rollback remain isolated |
| W26-C9 | Lost-update-free conversation mutation | Done; concurrent hop mutation preserves updates |
| W26-C10 | Cancellation scope split only | Planning-complete; superseded by C10a → C10b → C10c |
| W26-C10a | Persisted cancellation request/observe/stop lifecycle | Done (`0d24f7a`, `dc69142`); typed cross-process signal and atomic terminal winner |
| W26-C10b | Cooperative driver/loop/approval/tool checkpoints | Done (`3244fb2`, `d6eca09`); typed safe-boundary stop with atomic tool history |
| W26-C10c | Durable task/run reconciliation and truthful public surfaces | Done; whole-path oracle and cancellation wording agree |
| W26-C11 | Public branch, quickstart, installer, and claims match shipped behavior | Done (`dcce5b2`, `f9a4086`); Wave 26 closure truth and gates pass |

### Wave 27 — bounded post-W26 hardening and public front door (complete 2026-09-01)

Post-W26 triage activated exactly two independent cards. W27-C1 follows GitHub's high-severity
CVE-2026-69247 alert from the supported optional MCP graph to `cryptography` 49.0.0 and requires a
patched lock plus MCP compatibility evidence. W27-C2 follows the maintainer's explicit 2026-09-01
request and the measured 773-line README/stale-asset audit to a smaller public front door and one
reproducible current visual set. Detailed acceptance and ownership live in `TODO.md`.

Both cards closed on 2026-09-01. The lock now excludes the reported advisory range, and the public
front door is a compact, tested README backed by one reproducible three-asset terminal visual set.

The remaining Wave 27 candidate measurements are still unscheduled: an isolated coding profile and
scoped egress/secrets without silently changing D-23; recovery from corrupt or old persisted state;
real pipeline-variable injection; provider structured-output/streaming needs; MCP transport/cache/
capability metadata; and a supported local service/TLS-proxy/backup profile. Each needs a
representative fixture and a measured failure or explicit request. A built-in dashboard and tenant
model remain out of scope.

### Wave 28 — portable governance proof (complete 2026-09-02)

The bounded pass selected the standard OpenHands SDK `Agent` as the coding runtime and PydanticAI as
the general Python framework. OpenHands ACP is excluded from the proof because the ACP subprocess
owns its tools, context, approvals, and execution; Docket could delegate to it but could not prove
that every relevant action crossed Docket's chokepoint. PydanticAI's custom toolset seam is selected
over LangGraph's second graph language and Agno's broader hook/concurrency surface. Decisions D-32
and D-33 record the selection and evidence contract; detailed executable cards live once in
`TODO.md`.

Both adapters consume one artifact-installed governed-execution envelope and one scenario table.
The proof uses deterministic, credential-free models: a loopback OpenAI-compatible fake for
OpenHands and PydanticAI `FunctionModel`. It covers exclusive tool registration, native-bypass
absence, policy deny, approval deny/grant, Docket-owned reported-token/tool-call budgeting before
mutation, paired trace identity, existing audit semantics, and a typed terminal handoff. The base
runtime stays Python 3.11 compatible and dependency-light; the isolated OpenHands fixture uses
Python 3.12 because that SDK requires it. Port 8081 remains an optional local-model canary, never a
closure gate.

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W28-C1 | Shared public execution envelope + common fixture contract | Done (`9f6a79c`, `d2e1b33`, `2e37361`); bounded facade and shared oracle shipped |
| W28-C2 | Standard OpenHands SDK adapter and coding fixture | Done (`071a744`, `c7d6a59`, `fbb4084`); nine Python 3.12 artifact cases pass |
| W28-C3 | PydanticAI custom-toolset adapter and general fixture | Done (`648dec5`, `a6c9197`); seven Python 3.11 artifact cases pass |
| W28-C4 | Cross-adapter installed-artifact parity, public truth, closure | Done (`3294f58`, `b1c9f44`, `739b1ca`); 37 focused tests, 2,490 collected tests, scoped claims, and Ubuntu/macOS artifact journeys pass |

No A2A card is activated because the selected coding proof is in-process and needs no remote task
discovery/state/cancellation. No OTLP card is activated because the fixture is explicitly required
to first prove whether the existing JSONL trace identity is sufficient. No plugin framework
precedes the two concrete callers.

### Wave 29 — adoption evidence and public release (active 2026-09-02)

The bounded activation at exact commit `de08206` found zero extractable starter directories and zero
benchmark/baseline files. It reproduced a concrete recovery defect: `edges.store.write_json`
created a valid `.bak`, but corrupting the primary still made `read_json` raise `JSONDecodeError`.
Thirty-one existing policy-template, crash-resume, and release-contract tests passed, proving the
underlying mechanics should be reused rather than rewritten. `SECURITY.md` has a main-only security
support statement, but there is no deprecation, governance, or succession policy; CODEOWNERS and the
90-day Git history resolve to one human owner. Finally, current workflow code already builds wheel,
sdist, checksums, SPDX SBOM, and provenance, while the public `v0.2.0-beta.1` release predates it and
contains only a tarball plus checksum. Decision D-34 freezes these measurements and the activation
boundary.

Wave 29 therefore ships: safe JSON backup recovery; one copied-outside-checkout, credential-free
ten-minute starter; a deterministic and redacted benchmark schema/runner; adversarial plus
crash/recovery journeys using existing governance; truthful support/deprecation/governance/
succession policy; and one reproducible published baseline. The final current beta publication is
separate and explicit-approval-gated. It verifies existing supply-chain machinery rather than
building it again.

| Card | Outcome | Dependency / parallel boundary |
| --- | --- | --- |
| W29-C1 | Corrupt-primary/valid-backup recovery at the JSON-store chokepoint | Done (`4b796de`, `b673645`); 11 focused recovery/atomicity cases pass |
| W29-C2 | Extractable artifact-installed ten-minute starter | Done (`b138f25`, `16ef7bc`); copied artifact-installed public CLI journey passes |
| W29-C3 | Adoption benchmark schema and deterministic runner | Done (`a556fdc`, `2bf46a5`); 11 deterministic schema/runner cases pass |
| W29-C4 | Adversarial governance and crash/recovery benchmark scenarios | Done (`fcdff9a`, `0c8dac7`); 21 isolated C3-valid journeys pass |
| W29-C5 | Support, deprecation, governance, and succession truth | Done (`ac05dc3`, `c480e97`); 8 policy truth/counterexample cases pass |
| W29-C6 | Reproducible baseline and scoped public interpretation | Done (`82a3239`, `033bb4b`, `f789bc6`); exact hash and hosted closure pass in run `33812881329` |
| W29-C7 | Provenance-complete public beta and Phase 23 closure | **Deferred 2026-09-11 behind Wave 31.** Publication approval for `v0.2.0-beta.2` stands; only release-state owner |

No live provider or subscription is a gate; port 8081 stays optional. Deterministic results prove
contracts, not model quality. Dollar values are estimates with versioned assumptions or remain
`null`; failed attempts stay in the denominator. There is no leaderboard, competitor ranking,
savings claim, telemetry/A2A work, new adapter, or feature-count exit criterion.

---

## 1. Mission (do not lose this)

> **Rewritten 2026-08-04.** The original mission ("docket is a thin opinionated wrapper around the
> OpenClaw gateway") was authored in Phase 0 and was true until **D-19**, which took the runtime.
> It is preserved in git history; leaving it here would have told every new agent to protect a
> boundary that no longer exists. The *honesty* half of it is the part that survived, and it is
> restated below unchanged in spirit.

**docket runs teams of autonomous coding agents across multiple projects, and governs what they are
allowed to do.** Trustworthy and honest before any new capability: correct state, real cost control,
and **zero features that lie about what they do.**

**The approach in one sentence:**
> **Own the loop, rent the protocols.** docket owns the turn loop, the tool registry, all three
> policy hooks, approvals, audit and sessions — because whoever owns the loop owns the interception
> points. It rents only protocols: an OpenAI-compatible HTTP endpoint, MCP for pluggable tool
> servers, containers for isolation.

**The three honesty rules that have the most teeth**, because each was earned by catching a false
claim already in the tree:

1. **Token counts are measured; dollars are estimated.** `core.llm.TokenUsage` is real. There is no
   recorded dollar spend — `DocketDriver` reports `cost_usd = 0.0` by design. Never relabel an
   estimate as spend, and never project dollar savings.
2. **Context budgets use a characters-per-token approximation.** Never claim exact token counts
   from them.
3. **A capability is what the code does, not what the docs say.** The known-true limits are listed
   in [CLAUDE.md](CLAUDE.md) and must not be overclaimed — most recently, both README and
   `docs/commands.md` claimed MCP tools were callable inside a live turn while
   `DocketDriver.registry_factory` still defaulted to `builtin_registry`. **The spec had it right;
   the marketing prose did not.**

**Out of scope (do NOT do these now):** anything in the hosted-SaaS half — multi-tenancy, authn for
external callers, queues/workers, streaming, per-customer quota (see D-20 and D-22). Also: a
dashboard of docket's own (Phase 11 ruling, reaffirmed by Phase 22), and rewriting in another
language. If tempted, stop and add it to §7 "Backlog" instead.

---

## 2. Ground truth about the system (read once)

> **Re-trued 2026-08-04, post-D-19.** Phases 0–9 were authored against the **Bash** codebase; their
> file paths (`lib/**/*.sh`) refer to the pre-cutover tree, now deleted. Phases 10–18 were authored
> against a Python core that still wrapped an external daemon behind an Anti-Corruption Layer —
> **that layer is also gone.** Both are retained verbatim below as completed-work record. **For any
> new work the ground truth is what this section describes**, and the canonical source is
> [CLAUDE.md](CLAUDE.md). Where a historical phase contradicts this section, this section wins.

- **Language/stack:** Python 3.11+ (`docket` package under `src/docket/`), Typer + Rich + Pydantic + pydantic-settings + filelock. Installed via `uv`/pip; `bin/docket` is a thin Bash launcher that execs `python -m docket "$@"`. Gated by `ruff` + `mypy --strict` + `pytest`. **There is no daemon and no `systemctl` dependency.**
- **Three layers, dependencies point inward only** — `cli/` → `core/` → `edges/`. A CLI command may call core and edges; core never imports cli, never imports `ui.py`, and never prints.
  - `cli/` ([src/docket/cli/](src/docket/cli/)) — Typer commands; the only layer that talks to the user. `__main__.py` maps aliases/removed-commands then hands to the Typer `app` in `cli/__init__.py`. Larger groups split out (`_install.py`, `_doctor.py`, `_gates.py`, `_trace.py`, `_pod.py`, …).
  - `core/` ([src/docket/core/](src/docket/core/)) — Pydantic models + pure services. The load-bearing ones: `agent_loop.py` (**the turn loop**), `tools.py` (**the chokepoint**), `llm.py` (the chat port), `session.py`, `dispatch.py` (the pod state machine), `fleet.py`, `policy.py`/`security.py`/`approval.py`/`audit.py`/`trace.py`, `archetypes.py`/`blueprints.py`/`pod.py`, `handoff.py`/`context.py`, `runtime_driver.py`.
  - `edges/` ([src/docket/edges/](src/docket/edges/)) — the only side-effecting layer: `store.py` (atomic, filelocked, 0600 JSON I/O — the single chokepoint for docket-owned JSON) and `adapters/` (`llm.py` — the only module that knows the OpenAI-compatible wire format; `toolbox.py` — the built-in tool handlers, deliberately holding **no** policy; `docket_runtime.py`, `telegram.py`, `fetch.py`, `mcp_client.py`, `system.py`).
- **One state root, one writer per file.** Everything docket owns lives under `~/.docket/` (`DOCKET_HOME`): `fleet.json`, `secrets.json`, the `docket-*.json` registries, `audit.log`, `traces/`, `sessions/`, `approvals/`, `policies/`, `workspaces/`. Per-agent facts live in `.docket-meta.json` in each workspace. **These are not duplicated** — unlike the pre-Phase-19 dual-source world there is no drift to detect, and no sync step.
- **The two invariants that replaced the ACL invariant**, both machine-enforced:
  - **Every tool call goes through `core/tools.py`'s dispatcher**, where `pre_input`, `pre_tool_call` and `pre_output` all evaluate. A second execution path is a hole. Enforced by an AST test (`tests/unit/core/test_tools.py::test_only_the_chokepoint_imports_the_handler_module`).
  - **Docket-owned JSON goes through `edges/store.py`.** Append-only JSONL (`core/trace.py`, `core/audit.py`) writes directly, per the documented **D-12** exemption.
- **Tests** (`tests/`) — the counts here drift; `uv run python scripts/metrics.py --check` is the guard that fails CI when a README or doc number stops matching the tree. **Fix the claim, never the guard.**
  - `tests/unit/`, `tests/integration/`, `tests/guards/` — the default pytest suite (`uv run pytest`). `tests/agent/` is the budgeted agent lane and runs in its own CI job (`uv run pytest tests/agent`). Files are named by **subject**, not by card id.
  - `tests/golden/` — byte-parity golden suite (`bash tests/golden/run.sh verify-all`) — the net that catches a behaviour change. **Never regenerate a golden to hide one.**
  - `scripts/validate-specs.sh` — the spec suite, CI-blocking. CI also runs a `floors` job that resolves the **lowest** versions `pyproject.toml` permits: two of six advertised bounds were false when first measured, so do not move a floor without re-measuring.

---

## 3. Conventions (follow exactly)

> Current conventions. The Bash-era and ACL-era rules are preserved inside the historical phases;
> do not apply them to new work.

- **Typed, gated:** `ruff check .`, `ruff format --check .`, `mypy src` must all pass. No new `# type: ignore` without a reason.
- **Never write JSON by hand** — docket-owned JSON goes through [edges/store.py](src/docket/edges/store.py) (atomic, filelocked, 0600). Append-only JSONL logs (`core/trace.py`, `core/audit.py`) write directly; that is the **D-12** exemption and the only one.
- **Respect the layer rule:** `cli/` → `core/` → `edges/`, inward only. `core/` has no Typer, no subprocess, no `ui.py`, no `print`.
- **Shell-out invariant scope (D-13):** every `git`/`docker`/`bwrap`/`systemctl` shell-out funnels through [edges/adapters/system.py](src/docket/edges/adapters/system.py) — no other module invokes those binaries directly, and it degrades gracefully when one is missing. The sandboxed `bash` tool is not an exception: it reaches the same module through the chokepoint. Remaining CLI-only one-offs (`tail -f` in `cli/_trace.py`, `$EDITOR` in `cli/__init__.py`'s `cmd_edit`, `python --version` in `cli/_install.py`) are out of scope and stay where they are.
- User-facing status goes through the Rich helpers in [ui.py](src/docket/ui.py) (`info/success/warn/error`); a command aborts by raising `typer.Exit`. Never raw `print` for status.
- **Removed commands get a notice, not an unknown-command error** — `__main__.py`'s `_REMOVED` map. Precedent: `docket workflow` (D-16), `docket team` (D-11), `docket eval` (2026-08-04).
- Permissions: workspace dirs `700`, files `600`.
- Commit style: `Type: description` (`Add:`/`Fix:`/`Docs:`/`Feat:`/`Refactor:`/`Chore:`/`Test:`/`Merge:`/`Remove:`), detailed body. One task ≈ one commit. **No AI/assistant attribution trailers of any kind; ASCII only.** **Public repo** — scrub real client names, `/home/<user>` paths, and usernames before committing.
- **Every code task adds or updates a test** (pytest; add a golden case when output changes).
- **Comments: keep rationale, delete archaeology.** Delete card ids, phase numbers, dates, provenance, and narration of what a deleted thing used to do — git history and this file hold all of it. Keep any sentence whose loss would let someone introduce a bug. **When in doubt, keep.** A comment answers "why is it shaped this way"; a docstring is one line unless it states a contract. `scripts/maint/comment_lint.py --check src tests` is the reader of this rule (ratcheted in CI from W31-C3).
- **Tests are placed by lane, named by module.** `specs/test-framework.md` §"Lanes and placement" is the contract: one unit file per `src/` module, `integration/` for cross-module behaviour, `guards/` for AST invariants (≤ 80 lines), `agent/` — outside the default run, ratcheted against a shrink-only baseline, each file declaring `LANE`/`REASON`/`RETIRE_WHEN` — for checks that exist only so an agent does not repeat a recorded mistake. A test that reads prose or builds an artifact is agent-lane by definition.
- **Standing documents only:** `README.md` (front door, ≤ 150 lines after W31-C7), `CONTRIBUTING.md` (working rules), `ROADMAP.md` (direction, decisions index, phase table), a single `TODO.md` (active and planned boards), `CHANGELOG.md` (release notes), `docs/cycles-ended/` (every closed board/phase section and the decision changelog, byte-preserved with a manifest), `docs/adr/` (one file per reasoned decision), `specs/` (current-state contracts), and generated reference under `docs/`. No bespoke document per task; analysis goes to gitignored `internal-docs/`.
- **A guard is not evidence until you have seen it fail.** Plant the drift, watch it go red, restore, watch it go green. Guards that verified the wrong set have shipped here more than once.

---

## 4. Definition of Done (per task)

A task is done when:

1. Acceptance criteria all pass, and a pytest covers the change.
2. `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` is green.
3. `bash tests/golden/run.sh verify-all` is byte-identical — **or** the card deliberately changed CLI surface and the regenerated diff is explained line by line.
4. `bash scripts/validate-specs.sh` is green and the card's own spec carries a version bump, a changelog entry, and a **Status line matching what actually shipped**.
5. `uv run python scripts/metrics.py --check` is in sync.
6. Committed with a conventional message, privacy-scrubbed.

Two rules that override any of the above when they conflict:

- **Never edit `scripts/metrics.py` or `scripts/validate-specs.sh` counting logic to make numbers agree.** Fix the claim, never the guard.
- **Prove "pre-existing" before claiming it.** Check out the base commit in a clean worktree — a `git stash` does not restore deleted files or a changed environment, so it is not a baseline. In an agent worktree run `uv sync --all-extras` **first**: a missing `anyio` produces three phantom mypy errors in `mcp_client.py` that are not real, and five agents have now reported them as pre-existing failures.

---

## 4.5 Architectural principles (durable — read before any structural change)

> Folded from the removed audit/migration docs. These outlive any single phase; a PR that violates
> one needs an explicit decision entry in §6, not a silent exception.

### Build vs. wrap: ~~docket wraps OpenClaw, decisively~~ — **REVERSED by D-19**

> **Read this box before the section it introduces.** D-19 (2026-07-31) **took the runtime**. docket
> now owns the turn loop, the tool registry, all three policy hooks, approvals, audit and sessions,
> and rents protocols only. The ACL is gone; so is the daemon. The section below is kept **because
> the reasoning was sound and the trigger it named is exactly what fired** — not as live guidance.
>
> **What actually forced the reversal, and it is the durable lesson:** docket shipped four
> `pre_tool_call` policy templates that had **never once been evaluated**, because the daemon owned
> the inside of a turn. The wrap boundary was not merely limiting the roadmap; it was making the
> product's central claim false. *Whoever owns the loop owns the interception points* — which is
> also why agent frameworks (LangGraph/CrewAI/AutoGen) are rejected on principle: they own the loop,
> and therefore the gates.
>
> **What survived the reversal, unchanged:** the "one typed port, one shipped driver" discipline
> (`core/runtime_driver.py`, `DocketDriver` — **not** a plugin framework), no DI/ORM/event-bus,
> boring typed Python, and the rule that a *second* driver needs a named trigger. The
> anti-overengineering table below still governs, with its "one backend (OpenClaw)" row read as
> "one runtime, ours".

- **The moat is the control plane, not the engine.** OpenClaw owns the *execution plane* (the agent
  loop, LLM/provider calls + model routing, tool execution + sandbox, the gateway, session/channel
  plumbing, approval-hook enforcement) — large, security-critical, changing *weekly*. docket owns the
  *control plane* (provisioning, multi-project isolation, cost guardrails, opinionated UX,
  Telegram-first ops, fleet health). That control plane is the product's differentiator; none of it
  requires owning the agent loop.
- **Why not rebuild the runtime:** velocity/treadmill risk (LLM runtimes churn; wrapping inherits
  provider support for free), security surface (sandbox + isolation + gates are the most expensive
  things to get right), and time-to-value. "No direct OpenClaw CLI or JSON editing" is itself the
  sellable proposition.
- **The boundary makes it reversible:** the ACL ([edges/adapters/openclaw.py](src/docket/edges/adapters/openclaw.py))
  is the single place OpenClaw's shape lives, so build-vs-wrap stays a *reversible* bet, not a
  load-bearing assumption smeared across the codebase. **Do not build a plugin/`AbstractBackend`
  framework** — there is exactly one runtime; one concrete ACL behind a thin boundary is enough.
- **When standalone *would* become right (triggers, not dates):** OpenClaw stalls / repeatedly breaks
  compatibility / changes license or direction; the roadmap needs runtime-level capabilities upstream
  consistently refuses; or the ACL ends up working *around* OpenClaw more than *with* it. Even then,
  prefer absorbing a thin slice behind the existing ACL port over a full rebuild.
- **Critical consequence for every phase** *(revised 2026-07-30 per D-15)*: **docket orchestrates
  hops; the daemon executes every tool call inside a turn.** Since AA-7's real dispatch, docket *is*
  in the execution path for the dispatch lane and is accountable for its queue/state/retry
  correctness — the old "docket is not in the agent execution path" phrasing is retired. What
  survives unchanged is the split every feature must still declare: *pure-docket* (config,
  provisioning, metadata, templates, policy authoring, hop orchestration — ships first, fully
  testable) vs *daemon-gated* (anything that intercepts **inside** a turn — isolated behind a spike,
  never overclaimed). Phases 8, 10, and 14–18 are all shaped by this split.

> **Platformization amendment (2026-07-30, decisions D-14…D-18):** the Phases 14–18 program revises
> two lines above, deliberately and narrowly. (1) The `AbstractBackend` ban becomes "one typed
> **RuntimeDriver port**, one shipped driver" — formalizing the execution slice the ACL already
> half-owns, because the 2026-07-29 audit found that coupling leaking around it (session-JSONL cost
> parsing in `core/`, 11 argv shapes) rather than contained by it. A *second* driver still needs a
> trigger from the list above. (2) "Not in the execution path" is rewritten per D-15. Everything
> else in this section — wrap-don't-rebuild, no DI/ORM/event-bus, boring typed Python — stands and
> governs Phases 14–18 too.

### Anti-overengineering guardrails (the "we will NOT" list)

| We will NOT | Because |
|---|---|
| Add a DI/IoC framework | Plain constructor/function args suffice at this size |
| Build a plugin system / `AbstractBackend` | One backend (OpenClaw); one concrete ACL behind a thin boundary — no speculative generality |
| Use FastAPI/async for `serve` | 3 endpoints; stdlib `http.server` + `prometheus_client`, synchronous |
| Add an ORM / database | JSON files modeled by Pydantic *are* the store (the filesystem is the trace/policy store too) |
| Event sourcing / message bus / CQRS | It's a CLI that edits two JSON files |
| Deep package nesting / DDD ceremony | Keep it flat: `cli/ core/ edges/`. Split a module only when it actually hurts |
| Abstract before the second caller exists | Rule of three. Make it work, then generalize |

The target is **boring, typed, obvious Python.** "Scale" here is not throughput (single-host CLI) —
it's more *commands*, more *agents*, more *contributors*; the three-layer split + types + tests
address exactly those.

---

## 6. Open decisions (resolve before the dependent task)

> Decisions D-1…D-24 were taken during phases whose records now live in
> `docs/cycles-ended/roadmap-phases.md`; the rows stay here because a decision outlives its phase.

| ID | Decision | Needed before | Default if unanswered |
| -- | -------- | ------------- | --------------------- |
| D-1 | Smart routing: implement real (A) or cut (B)? | P2-3 | **B (cut)** — it's placebo today; cutting is safe and honest |
| D-2 | Deprecated commands: hard-remove or keep warning shims one release? | P2-2 | Keep shims one release, then remove |
| D-3 | Budget pause mechanism: native OpenClaw pause vs model-sentinel fallback? | P1-2 | Research native first; fallback to sentinel |
| D-4 | If the daemon can't reach local endpoints (Ollama), what is the "free" preset? | MA-4 | OpenRouter free-tier models, labeled honestly (MA-1 decides) |
| D-5 | Concrete model IDs per preset (openai/google/openrouter/local tiers)? | MA-4 | Pick current cheapest/standard/best per provider from MA-1's verified table; pin in `config.sh` |
| D-6 | Do aborted sessions count against role success rate? (spec Q1) | OBS-11 | **Count them** — O5 already coerces a timed-out trace to `aborted`; excluding them hides the silent-hang failure G4 exists to catch. terminal = success+failure+aborted. |
| D-7 | Where is the trusted/untrusted input boundary marked? (spec Q2) | OBS-7 | A `source` field on queued tasks (`operator` trusted; `telegram\|api\|fetched` untrusted → pre_input/injection policies apply, GR9). |
| D-8 | Does the manager-coordination layer get its own metrics role? (spec Q3) | OBS-4 | **No (v1)** — observe it through the agents it dispatches; manager emits session_start/end for its own planning runs, dispatched work is attributed to the executing agent. Add a `manager` rollup only if delegation overhead becomes a question. |
| D-9 | Per agent field: `synced` to openclaw.json or `local`-only? | CDD-1/CDD-3 | Record per field in the schema table. Proposed: `model`/`sessionKey`/`projectKey` = synced (daemon needs them); `budgetUsd`/`paused`/`pausedReason`/`modelSource`/`templateVersion` = local (docket-only policy/state) — but document them as local so no one expects sync. Revisit if the daemon ever reads a budget/pause. |
| D-10 | `--json` envelope: adopt the spec's `{data,…}` wrapper (A) or delete it and document actual shapes (B)? | CDD-4 | **B (delete + document reality)** — no command emits the wrapper today and external scripts already parse the bare shapes; retrofitting a wrapper is a breaking change for zero benefit. Pin the real shapes in `specs/data/` instead. |
| D-11 | `docket team` (legacy manager queue): retire into pods, or give it real dispatch? | CH-4 | **Retire** — it is a second, manual task queue (`workspaces/manager/TASK_LIST.json`) with **no dispatcher**; pods own delegation (`docket pod <p> delegate/queue/dispatch`, real execution via `core/dispatch.py`) and the opt-in Portfolio Manager owns the cross-pod view. Replace with a removed-command notice mapping each subcommand to its pod equivalent. |
| D-12 | Docket-owned JSON writes: single `store.py` chokepoint, or per-module writers? | CH-1 | **Single chokepoint** — every docket-owned JSON write goes through `edges/store.py` (append-only JSONL logs in `trace.py`/`audit.py` are the one documented exemption, named in the store.py docstring). Removes 8+ hand-rolled atomic-write copies with inconsistent locking. |
| D-13 | The audit also flagged non-`openclaw` shell-outs (`_eval.py` bash, `_trace.py` tail, `$EDITOR`, `_install.py` python-version): fold them behind `edges/adapters/system.py` too, or scope the shell-out invariant narrower? | CH-2 | **Scope narrower** — the ACL/`system.py` invariant covers `openclaw`/`git`/`docker`/`systemctl` only (§3). The remaining four are CLI-only, one-off, and not OpenClaw/daemon coupling; wrapping them would add indirection with no coupling to remove. Revisit only if one of them grows a second call site. |
| D-14 | §4.5 bans an `AbstractBackend`, but the 2026-07-29 platform audit found the execution slice already leaks past the ACL (session-JSONL cost parsing in `core/utils.py`, 11 argv shapes, duplicated unit name). Formalize a **RuntimeDriver port**, or keep the ban? | Phase 18 L-1 | **One typed port, ONE shipped driver.** *(Row corrected 2026-09-11 by D-35's audit: as decided in Phase 18 the driver was the retired external-runtime adapter; since D-19 it is `edges.adapters.docket_runtime.DocketDriver`, and `FakeDriver` in `tests/fakes.py` is the one test double.)* This *revises* §4.5's ban: the port is containment of coupling that already exists, not speculative generality. A second driver still requires a §4.5 trigger (upstream stall/breakage) or a paying user — the "no plugin framework" spirit stands. |
| D-15 | §4.5 says "docket is not in the agent execution path" — false since AA-7's real dispatch. Rewrite the principle or keep pretending? | Phase 14 | **Rewrite** — the principle becomes: *docket orchestrates hops (and is accountable for queue/state/retry correctness); the daemon executes every tool call inside a turn.* The pure-docket vs daemon-gated split stays; the denial goes. |
| D-16 | Lobster workflow surface: docket lints YAML it cannot run (validator ignores 4 constructs its own template emits). Retire into the docket-native pipeline spec, or keep as a second dialect? | Phase 16 W-3 | **Retire (A)** — one workflow dialect docket actually executes (W-1/W-2). `docket workflow` becomes a removed-command notice mapping to the pipeline commands, same pattern as `docket team` (D-11). Keeping two dialects repeats the dual-queue mistake. |
| D-17 | `serve` job model: bare fire-and-forget daemon threads (no ids, errors suppressed) vs a persistent run registry + bounded worker pool? | Phase 14 R-3 | **Run registry + worker pool, stdlib only** — keep §4.5's no-FastAPI/no-async stance; drop the fire-and-forget. Every dispatch gets a run id, persisted state, and queryable outcome; `contextlib.suppress(Exception)` around dispatch is banned. |
| D-18 | Where do docket's own LLM calls (memory distillation C-2, judge steps) come from: provider SDKs, a wrapped gateway, or the driver? | Phase 17 C-2 | **Through the driver** (`agent_run` on a pod Lead / utility agent) — zero new SDK deps. A LiteLLM-class sidecar gateway is a Phase 18 L-5 *spike*, opt-in, and only if the daemon tolerates a base-url swap; hand-rolled per-vendor clients are banned permanently. |
| D-19 | Drop the OpenClaw daemon so docket owns every layer, reusing libraries only where they do not take control? | Phase 19, 2026-07-31 | **Yes -- own the loop, rent the protocols**, with a clean break and no compatibility layer. Full reasoning in [docs/adr/0002-own-the-loop-rent-the-protocols.md](docs/adr/0002-own-the-loop-rent-the-protocols.md). |
| D-20 | **The company will ship agentic products, and wants docket as its main orchestrator. Is docket (a) the factory that builds those products, (b) the runtime the products themselves ship on, or both?** | Phase 20/21 (blocks their scope) | **Both, in a stated order: the factory first, then the embeddable substrate** -- and explicitly not the hosted-SaaS half. Full reasoning in [docs/adr/0003-factory-first-then-embeddable-substrate.md](docs/adr/0003-factory-first-then-embeddable-substrate.md). |
| D-21 | Split the package into an embeddable `docket-runtime` library plus the `docket` control plane built on it? | Phase 21 P21-1 (D-20 answered, so this is live) | **YES — confirmed 2026-07-31 once D-20 resolved.** Every agentic product the company ships then inherits the same gated tool chokepoint, policy engine, approval store and hash-chained audit, instead of each product team reinventing guardrails badly. That is the company-level asset neither LangGraph nor CrewAI offers, because their guardrails are opt-in callbacks rather than the only execution path. Cost is packaging + a public API contract, **not** a rewrite: `core/`/`edges/` are already CLI-free (verified). **Two hard constraints.** (1) Do **not** do this before Phase 19's removal wave — extracting a library that still reaches for `openclaw.json` would freeze the coupling into a published contract. (2) **Packaging only.** P21-1 draws a boundary around code that already exists and pins it with a test; it does not design new API surface, add extension points, or "generalise" anything. A package split that grows features is how this becomes the overengineering it was meant to avoid. |
| D-22 | Multi-tenancy model: stay project-scoped (`agent:<id>:<project>`), or add an end-user/tenant axis? | — (no longer scheduled) | **CUT 2026-07-31 — stay project-scoped; build nothing.** D-20's answer scopes the substrate to an *embedded library*, and an embedding product owns its own tenant model, so docket does not need one. The decision stays **on the record, not deleted**, because the original warning is still true: session keys, workspaces, budgets, traces, audit entries and approval records are all keyed on *project*, and retrofitting a tenant key is expensive. **Re-open only on a concrete trigger** — docket itself serving more than one end customer from one host. Until then, writing the tenant axis is speculative generality of the exact kind §4.5 bans. |
| D-23 | Network egress for agent tool calls: open by default, or closed with an allowlisted `fetch` tool? | Phase 19 P19-11 | **Open by default, lockdown opt-in**, with a domain-allowlisted `fetch` as the inspectable path and the escape hatches named honestly rather than papered over. Full reasoning in [docs/adr/0004-network-egress-open-by-default.md](docs/adr/0004-network-egress-open-by-default.md). |
| D-24 | Phases 20/21 were drafted as "best practice for an agent platform". Under the answered goal (a factory for agentic products, D-20), which of those items are genuinely viable and which are overengineering? | Phases 20/21, before either starts | **Cut roughly half of Phases 20/21**, the integrator's own recommendations included, on the test of whether a measured need in this system asks for it. Full reasoning in [docs/adr/0005-prioritization-ruling-viable-vs-overengineering.md](docs/adr/0005-prioritization-ruling-viable-vs-overengineering.md). |
| D-25 | After the 2026-08-30 CTO/OSS audit, should Docket compete as a broad agent framework or productize its governed coding-agent runtime and only then prove portable enforcement? | Phase 23 | **Productize the narrow wedge first; prove portability second.** The explicit request is to make Docket useful in the AI-orchestration ecosystem, but the audit found that the immediate blockers are a default first run that cannot resolve its advertised Anthropic endpoint, invalid release/install metadata, overlapping runtime wheel contents, non-atomic governance transitions, brittle free-text verdicts, and cancellation that does not interrupt the owned loop. Wave 26 fixes those truths before adding ecosystem surface. Docket does **not** compete on graph/pattern count and does not claim framework neutrality while it owns only `DocketDriver`. A later interoperability wave may add the smallest stable execution envelope and exactly two evidence-producing adapters—one coding runtime and one general agent framework—without surrendering `dispatch_tool` as the enforcement chokepoint. This decision does **not** reopen multi-tenancy, hosted queues/workers, a Docket dashboard, generic streaming, or default-closed egress. D-23 still governs egress. OpenTelemetry/A2A become schedulable only when the two-runtime proof names a concrete trace/remote-task requirement that existing JSONL/MCP cannot satisfy. |
| D-26 | What is the release-blocking adoption journey? | Wave 26 | **One immutable source commit → built artifact → clean install → supported provider configuration → initialized pod → first successful governed tool turn → public trace/run inspection.** Every boundary is exercised outside the checkout by deterministic CI. No new orchestration feature outranks a failure in this journey, and external publication remains approval-gated. |
| D-27 | When may Docket claim that it governs an external runtime? | Wave 28 | **Only when every relevant mutation/exec action in the reference fixture is forced through a Docket-owned execution envelope and the same policy, approval, budget, trace, and audit semantics are observed.** Merely launching, importing, coordinating, or offering Docket tools beside an external runtime is not governance if native bypass tools remain. Prove one coding runtime and one general framework before making a neutrality claim; do not build a plugin framework before the second caller exists. |
| D-28 | Does D-21's packaging-only ruling permit correcting the overlapping `docket-runtime` wheel and adding a facade? | W26-C5 | **Yes, narrowly.** Two independently installable distributions may not own the same files. A non-overlapping package topology, wheel+sdist support, and the smallest versioned facade needed by a real embedding example are correctness fixes to the package split, not speculative runtime features. Internal modules remain private unless the facade exports them; adapters and new extension APIs still need real callers under D-27. |
| D-29 | How is Phase 23 delivered by simultaneous agents without duplicating context or corrupting central state? | Phase 23 execution | **One coordinator plus as many non-contending worker lanes as the environment supports.** Each card has one owner, isolated worktree, unique `DOCKET_HOME`/temp/ports, exact allowed paths/functions, and a delta-only evidence handoff. `ROADMAP.md`, `TODO.md`, `README.md`, `specs/README.md`, release rollups, and mutable live endpoints are integrator-owned. Workers load the snapshot, one extracted card, one named decision, the owning spec section/tests, and the live callers—never the planning corpus or another worker's raw conversation. |
| D-30 | What does `cancelled` mean for an in-process run that a separate CLI process can request but cannot forcibly interrupt? | W26-C10a–C10c | **Cancellation is a persisted lifecycle, not a process-local event or an immediate stop claim.** The run id is the signal identity and its additive record distinguishes `requestedAt`, `observedAt`, and `stoppedAt`. A queued request is fully stopped atomically because no body ran. A running request remains visibly in flight until the owned executor observes it and reaches a safe stop; if the request wins the registry CAS, later success/failure cannot overwrite cancellation. Checkpoints prevent every not-yet-started model request, approval continuation, and tool handler. A cooperatively stopped task uses the additive status `cancelled`, never ordinary `failed`. An HTTP request or tool handler already executing may finish because Python threads are not killed; its result is either discarded before any next side effect or retained only as a complete assistant/tool-result unit, then the run stops. The existing CLI is the mutation surface; Wave 26 adds no POST cancellation API, event bus, async runtime, or unsafe thread kill. |
| D-31 | Which branch is Docket's public release lineage after Wave 26? | W26-C0 | **`main` is the canonical public/default release lineage.** The maintainer authorized the current `platform` lineage to fast-forward `main`; GitHub already names `main` as the default branch, and the preflight showed `platform` exactly 300 commits ahead with no `main`-only commits. The update is fast-forward-only and both branch names remain recoverable and synchronized. Tags and protected release jobs originate from `main`; feature/work branches are never release sources merely because they are newer. C3 owns replacing the remaining mutable installer/formula inputs with immutable tagged artifacts. |
| D-32 | Which two external runtimes are the bounded Wave 28 proof, and which advertised OpenHands path actually qualifies? | Wave 28 triage | **Select the standard OpenHands SDK `Agent` with an explicit Docket-only tool list, and PydanticAI with a custom Docket-owned toolset. Reject OpenHands `ACPAgent` for this proof:** its subprocess owns tools, context, approvals, and execution, so Docket can delegate to it but cannot force its native actions through `dispatch_tool`. The standard SDK exposes explicit ToolDefinitions and custom Action/Observation/Executor code; its resolved tool map must contain no default/MCP/plugin/bash/file-editor bypass. PydanticAI exposes custom `AbstractToolset.get_tools/call_tool`, run usage, sequential execution, and a procedural `FunctionModel`, giving the smallest credential-free general-framework fixture. LangGraph is feasible but adds the second graph language D-25 excludes; Agno is feasible but its general hook and default concurrent async surface is broader than needed. Pin the exact tested upstream versions in isolated fixture locks. Keep `docket-runtime` base dependencies unchanged; preserve Python 3.11 base/Pydantic support and run the OpenHands proof on its required Python 3.12+. |
| D-33 | What execution envelope and fixture evidence are sufficient for the D-27 portable-governance claim? | Wave 28 triage | **One Docket-owned per-execution envelope shared by both adapters**, proven by a common artifact-installed fixture, and permitting only a configuration-scoped claim. Full reasoning in [docs/adr/0006-portable-governance-execution-envelope.md](docs/adr/0006-portable-governance-execution-envelope.md). |
| D-34 | What measured evidence activates Wave 29, and what counts as adoption proof rather than marketing? | Wave 29 triage | **Activate only the missing executable evidence, and reuse shipped mechanics.** Exact `main` commit `de08206` has no extractable starter and no benchmark/result schema; a corrupt owned JSON primary raises despite a valid `.bak`; no complete support/deprecation/governance/succession policy exists; and the latest public beta has only two legacy assets. Existing policy, crash-resume, release-workflow, SBOM, checksum, and provenance machinery is already test-backed, so Wave 29 does not rebuild it. One versioned, redacted schema records every attempt and its provenance: completion, provider-reported tokens, estimate-labelled or unavailable dollars, prevented violations, approval latency, crash/restart recovery, and handoff failures. Deterministic fake results prove contracts, never model quality; failures remain in the denominator; no rankings or savings claims. C1/C2/C3/C5 are disjoint ready lanes, C4 consumes C1+C3, C6 is the public-result fan-in, and C7 alone may version/tag/publish after explicit approval. A current public wheel/sdist/SBOM/checksum/provenance set is Phase 23's final release evidence, not permission to publish silently. |
| D-35 | Should docket expose a non-interactive, single-agent execution entry point that an external plan-of-record (Tack) can spawn as a subprocess, and what may that contract promise? | Phase 24 / Wave 30 — **decided and shipped 2026-09-12** | **Yes -- `docket harness run`, a CLI subcommand over existing `core/` behaviour, with a published, versioned, test-pinned contract.** Full reasoning in [docs/adr/0001-harness-mode.md](docs/adr/0001-harness-mode.md). |
| D-36 | How should the test suite, comments and documentation be shaped so that a person who did not write docket can maintain it in ordinary time, and where do the checks that exist only for the agent's benefit live? | Phase 25 / Wave 31 | **Lanes with a budgeted agent lane, one unit file per module, a ratcheted comment linter and generated reference docs**, with nothing that reads prose left in the default suite. Full reasoning in [docs/adr/0007-human-maintainability-lanes-comments-docs.md](docs/adr/0007-human-maintainability-lanes-comments-docs.md). |
| D-37 | Does a sentence in `README.md` get a vote in which tests exist? | Wave 31 / W31-C2 | **No. The README is descriptive, not a requirements document.** It exists to tell a reader which features are there. Requirements live in `specs/`, which is what a test answers to; a README sentence is downstream of the tree and is rewritten to match it, never the other way round. So the shape of the suite is decided on its own terms -- structured, maintainable, correct, inside the agent-lane budget -- and the README is then updated to describe what is true. Applied at 2026-09-11: the harness-script file and the two third-party adapter parity files were retired to bring the lane under 4,000 lines, and the sentence claiming installed-artifact coverage for those adapter configurations left with them, in the same commit. That sentence was describing test coverage rather than a feature, which is not what the README is for. **What this does not license:** deleting a test to dodge a failure, or dropping a requirement from `specs/` because a test was inconvenient. A spec requirement is changed by amending the spec, deliberately, never by deleting its test. |
| D-38 | The agent lane came in at 5,730 lines against D-36's 4,000-line cap. Cut to the number, or change the number? | Wave 31 / W31-C2 | **Change the number: the cap becomes a shrink-only ratchet.** The 4,000 came from the plan before the classification settled and had no measurement behind it. Checked file by file, 17 of the lane's 18 files back a requirement in `specs/` or cover shipped code -- the third-party adapter configurations in `specs/api/runtime-library.spec.md` and the adoption evidence schema among them -- so reaching 4,000 meant amending specs to make the arithmetic work, which is the back door D-37 closes. Only `test_development_harness.py` answered to nothing but the agent's own hook scripts; it was retired, leaving 5,157. That number is now the baseline and may only fall. **The lane shrinks by its own mechanism:** every file declares `RETIRE_WHEN`, and it is deleted when that condition fires. If a smaller lane is wanted sooner, the question to answer is which requirements docket stops making -- a product decision, taken in the spec, not a line-count exercise. |

---

## 7. Backlog (deferred indefinitely)

> **Re-trued 2026-08-04.** Three entries here deferred work *to a daemon docket no longer has*, and
> one deferred the read API that Phase 11 promised and Phase 22 is now finishing. Corrected below;
> the originals are in git history.

- **New channel auth flows (Discord OAuth, Slack app install)** — docket owns its channels now
  (`core/telegram.py` is docket's own approval channel, not a daemon's prompt), so this is real work
  rather than someone else's. **Trigger:** an operator who will not use Telegram. One channel that
  audit-logs honestly beats three that half-work.
- **Rewrite in Go/Rust as a single binary** — reserved, not planned. Revisit **only** if
  zero-runtime-deps single-artifact distribution becomes a hard product requirement. Python is the
  destination until then (see `docs/cycles-ended/roadmap-phases.md`, completed initiatives).
- **Multi-tenancy** — **CUT, not deferred** (D-22, reaffirmed by D-24 and by Phase 22). The bet is
  that docket serves *products*, and each product serves its own customers; the substrate is a
  library a product embeds, and the product owns its serving layer. **Trigger if the bet is wrong:**
  docket itself serving more than one end customer from one host. Retrofitting the tenant key is
  expensive — this is a genuine bet, not a free cut.
- ~~**A full web UI / dashboard of our own**~~ — **the ruling stands; the consumer arrived.** docket
  competes on the *write/governance* side and **feeds** a dashboard rather than building a worse one.
  Phase 11 shipped the read half (CD-8); **Phase 22 ships the write half** for an external
  plan-of-record. docket still renders nothing.
- **microVM / gVisor workspace isolation** (deferred from Phase 11) — competitors running *untrusted*
  code use Firecracker (E2B/Vercel) or gVisor (Modal); docket's optional Docker/bwrap shares the host
  kernel. **Trigger:** docket targeting untrusted-code execution. Large lift.
- **Multi-host / remote provisioning** (deferred from Phase 11) — manage agents across more than one
  host. The ceiling on the "fleet" claim; defer until single-host value is saturated.
- **A second `RuntimeDriver`** (supersedes the old "cross-runtime adapters" entry) — the port exists
  and is typed (`core/runtime_driver.py`), with exactly **one** shipped driver by design. It is a
  port, **not** a plugin framework, and a second driver needs a named trigger — not a hypothetical
  about breadth.

---

## 8. How to start

> The decision changelog that used to end this file is `docs/cycles-ended/roadmap-changelog.md`;
> new entries go there.

> **Status lives in one place — the table at the top of this file.** This section is *how to work*,
> not *what is left*. Duplicating status here is what let it drift for three phases.

`docket` **0.2.0-beta.1** is cut and tagged — every release from this project carries a SemVer
`-beta.N` pre-release suffix (not a bare version) for as long as the project stays beta/early-stage
per README's warning banner; `v0.1.0` predates this convention and stays as-is.

**The goal, stated 2026-07-31 and unchanged: a factory for agentic products** — in three parts, in
order. (1) The factory: docket itself, exists. (2) The embeddable substrate:
`packages/docket-runtime/`, shipped by P21-1 — *if every product is agentic, the runtime is the
common part of every product*. (3) The control-plane write API: Phase 22. That framing answered
**D-20**, confirmed **D-21** (packaging only), **cut D-22** (no tenant axis), re-scoped **D-23**
(ship `fetch`, defer the lockdown), and produced **D-24**. **What the goal explicitly does not buy:**
the hosted-SaaS half — multi-tenancy, authn for external callers, queues/workers, streaming,
per-customer quota. Conflating "embeddable library" with "hosted product runtime" is the failure
mode D-20 exists to prevent.

### Execution model: waves scheduled by file contention, not by phase number

Four scheduling rules, each earned by a merge that went badly before it went well:

1. **At most one in-flight card may own a hot file per wave** (Phase 14). `core/dispatch.py` was
   that phase's hotspot; cards with disjoint footprints merged cleanly, while the two that both
   edited `serve.py`'s dispatch call sites produced the phase's only dangerous merge.
2. **When a file is hot, state ownership at *function* level** (Phase 19). `core/tools.py` was that
   phase's hotspot; wave 9 ran three cards against it by giving P19-9 only `ToolContext` plus the
   `bash` registration, forbidding P19-10 the file entirely, and letting P19-5 import it unchanged —
   **zero code conflicts.** Wave 16 applies the same rule to `serve.py`, splitting ownership by HTTP
   **method** (`do_GET` vs `do_POST`) across concurrent cards.
3. **An index or roll-up table that several branches edit in parallel cannot be merged by picking a
   side** (waves 3–4), because no side holds every branch's change. `specs/README.md`'s status
   table, README's metric counts, a golden's command list: **regenerate from ground truth** — the
   spec headers, the real CLI, the actual suite — and verify the diff. This caught real regressions
   on three consecutive merges.
4. **Resolve an append-only conflict by keeping both sides and then importing the module** to assert
   nothing was lost (Phase 19's one real conflict: `config.py`, two cards each appending a constants
   block). Do not read the diff and assume.

Central files — `ROADMAP.md`, `TODO.md`, `README.md` and their metric counts — are **integrator-owned**.
Card branches report what they shipped instead of editing the board; Phase 14 lost time to roll-up
checkboxes and README test counts conflicting on nearly every merge.

**A second scheduling rule, learned in waves 3–4 (keep it):** an index or roll-up table that several
branches edit in parallel — `specs/README.md`'s status table, README's metric counts, a golden's
command list — **cannot be merged by picking a side**, because no side holds every branch's change.
Regenerate it from ground truth (the spec headers, the real CLI, the actual suite) and verify the
diff. This caught real regressions on three consecutive merges.

**Branch model for this program:** D-31 supersedes the earlier fork-candidate arrangement.
**`main` is the canonical public/default and release lineage**; the completed `platform` history was
fast-forwarded into it without rewriting either branch. `platform` may remain as a synchronized
integration ref during Wave 26 cleanup, but it is not a second release source. Feature/card branches
target `main` (or an explicitly named temporary integration branch that must land before release).
Specs on the release lineage describe the code, not aspirations, and R-8 keeps them that way.

---

