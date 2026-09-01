# docket — Roadmap & Implementation Plan

This is the **single source of truth** for docket's roadmap *and* its executable task plan.
(Consolidated 2026-06-22 from the former root `ROADMAP.md` + `internal-docs/IMPLEMENTATION-PLAN.md`,
which duplicated each other at two altitudes — high-level phases vs. detailed tasks. Now one file.)

It takes docket from a polished single-user CLI to a hardened, portable, operable tool — sequenced
so each phase is independently shippable and raises the bar on **security → reliability →
portability → operability → product**. Earlier phases unblock later ones.

---

## ⇢ STATUS AT A GLANCE — every phase, one line each

**Last updated: 2026-09-01.** **Every numbered phase 0–22 and Waves 24–26 are complete. Phase 23
continues through active Wave 27 with two bounded, measured cards: one high-severity transitive
dependency remediation and one explicit public-front-door refresh.** Executable cards live in
[TODO.md](TODO.md).

> **How to read the rest of this file.** Everything below §4.5 is a **historical record**, not a plan.
> Phase sections are written in the present tense of when they were authored, and several still carry
> the status marker they were born with. **This table is the authority; a phase heading is not.**

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
| 19 | **docket takes the runtime (D-19)** — owns the loop, registry, all three policy hooks, approvals, audit, sessions. No daemon. | ☑ done (13 cards, waves 8–11) — **record in TODO.md + §Changelog; this file has no Phase 19 section** |
| 20 | Fleet observability | ☑ done **at cut scope** — D-24 cut ~half; P20-2 shipped, P20-4 was a phantom card |
| 21 | The product substrate (`packages/docket-runtime/`) | ☑ done **at cut scope** — P21-1, P21-5 shipped; rest cut by D-24 |
| 22 | Control-plane write API for an external plan-of-record | ☑ done (6 cards, wave 16, 2026-08-04) |
| 23 | **Product truth and ecosystem proof (D-25)** — first successful turn, trustworthy release, atomic governance, then portable enforcement evidence | ◉ active — Wave 27 C1 dependency remediation in progress; C2 public-front-door refresh ready |
| — | **Waves 17–18** (not phases): MCP-tools-in-a-turn, config single-owner, audit chain across rotation, isolation actually wired | ☑ done (2026-08-05) |
| — | **Wave 19** (not a phase): the defects a *real* dispatch on a *real* small-context endpoint found — worktree members told an unreachable root, tool-output ceiling unreachable from config | ☑ done (2026-08-05) — its remaining session-compaction finding was carried into and closed by Wave 20 |
| — | **Wave 20** (not a phase): bounded contributor harness + live-turn context efficiency | ☑ done (2026-08-19) — repo skills/hooks, MCP output parity, live fail-closed and hierarchical compaction, measured cross-hop redundancy, and step-scoped durable history shipped |
| — | **Wave 21** (not a phase): daemon-free current-state truth pass | ☑ done (2026-08-19) — current contracts, docs, source prose, and hermetic fixtures now describe only Docket-owned runtime/state; explicit migration history preserved |
| — | **Wave 22** (not a phase): observable whole-product workflow proof | ☑ done (2026-08-19) — one hermetic command crosses CLI subprocesses, loopback HTTP, the runtime/tool/gate path, approval resume, and durable observability state |
| — | **Wave 23** (not a phase): real local-model workflow + reachable startup state | ☑ done (2026-08-19) — an opt-in Qwen canary crosses the full workflow; bounded HEARTBEAT/AGENTS/TOOLS/MEMORY context now reaches every live turn without widening tool roots |
| — | **Wave 24** (not a phase): realistic memory-backed Git maintenance | ☑ done (2026-08-19) — exact durable memory fails closed on corruption; real worktree code continuity reaches Reviewer/Tester; public plus hidden acceptance passes on the local model |
| — | **Wave 25** (not a phase): live-model request and outcome truth | ☑ done (2026-08-30) — all 11 cards and the live private-boundary canary passed; integrated at `6b925f0` with full commit-level gates green |
| — | **Wave 26** (not a phase): first-use, release, atomic-governance, cancellation, and public truth | ☑ done (2026-08-31) — all cards through C11 shipped; artifact journeys, public docs, and full closure gates pass |

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

**Release:** `0.2.0-beta.1`, cut and tagged. Every release carries a SemVer `-beta.N` suffix until
the project is field-hardened enough to drop it (see README's beta warning).

Status legend used in the older sections below: ✅ / ☑ done · 🟡 planned-next · 🟠 audit-driven,
planned · 🚧 in progress · 🗓️ planned / deferred

> **Consolidation note (2026-06-23):** this file is now the **single roadmap**. The former
> `ARCHITECTURE-AUDIT.md`, `MIGRATION-PLAN-PYTHON.md`, and `MIGRATION-TASKS.md` were folded in
> here and removed — their durable content lives in §0 (completed migration) and §4.5
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
  invariant: `tests/python/test_no_subprocess_in_core.py` (core/ must be process-free),
  a sibling of the CH-3 no-UI-in-core test. Its optional adapter-split suggestion became moot when
  D-19 deleted the external-runtime adapter outright.

> This document is self-contained. A developer or AI agent should be able to start from
> here **without reading anything else first** and not lose scope. Read §1–§4 once, then
> work the tasks in §5 top to bottom. Every task has: goal, exact files, technical
> requirements, acceptance criteria, and tests. Do not skip the acceptance criteria.

---

## Current planned program — PHASE 23: product truth and ecosystem proof

**Status:** ◉ ACTIVE (2026-08-30) · **Decision:** D-25 · **Executable detail:** Wave 26 in
[TODO.md](TODO.md) · **Resumable coordinator packet:**
[`.agents/handoffs/phase-23-productization.md`](.agents/handoffs/phase-23-productization.md)

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

### Wave 27 — bounded post-W26 hardening and public front door (active 2026-09-01)

Post-W26 triage activated exactly two independent cards. W27-C1 follows GitHub's high-severity
CVE-2026-69247 alert from the supported optional MCP graph to `cryptography` 49.0.0 and requires a
patched lock plus MCP compatibility evidence. W27-C2 follows the maintainer's explicit 2026-09-01
request and the measured 773-line README/stale-asset audit to a smaller public front door and one
reproducible current visual set. Detailed acceptance and ownership live in `TODO.md`.

The remaining Wave 27 candidate measurements are still unscheduled: an isolated coding profile and
scoped egress/secrets without silently changing D-23; recovery from corrupt or old persisted state;
real pipeline-variable injection; provider structured-output/streaming needs; MCP transport/cache/
capability metadata; and a supported local service/TLS-proxy/backup profile. Each needs a
representative fixture and a measured failure or explicit request. A built-in dashboard and tenant
model remain out of scope.

### Wave 28 — portable governance proof (blocked on Wave 27 evidence)

Define the smallest stable execution envelope only after the local governance contract is reliable.
Prove it with exactly two adapters: one coding-agent runtime (prefer OpenHands/ACP) and one general
Python framework (choose PydanticAI, LangGraph, or Agno from a bounded spike). Both must traverse
the same Docket policy/approval/budget/audit boundary; an adapter that only imports or launches a
foreign runtime is not evidence. A2A is added only if the coding adapter needs remote task
discovery/state/cancellation. OTLP export is added only if cross-runtime trace identity cannot be
preserved through the existing trace contract. No plugin framework precedes the second real
caller.

### Wave 29 — adoption and comparative evidence (blocked on Wave 28)

Publish a ten-minute starter repository and a benchmark harness that records completion rate,
measured tokens, estimated dollars labeled as estimates, policy violations prevented, approval
latency, crash/restart recovery, and handoff failures. Add adversarial tool-policy and persisted
state recovery cases, artifact signing/SBOM/provenance, supported-version/deprecation policy, and a
small governance/succession document. Stars and feature counts are not exit criteria; executable
outcomes are.

---

## 0. Completed initiatives (historical record)

> Folded in from the now-removed `ARCHITECTURE-AUDIT.md` + `MIGRATION-PLAN-PYTHON.md` +
> `MIGRATION-TASKS.md`. Kept short — the durable *principles* are in §4.5; this is just the record.

### Bash → Python core migration (M0–M6) — ✅ complete

- **Why it happened:** an architecture audit found docket had outgrown Bash — ~14.7K lines of shell
  with **135 embedded `python3` heredocs** forming a "Bash + inline Python" seam with a stringly-typed
  boundary; `serve`/metrics, dual-source sync, schema validation and budgets were app logic Bash was
  fighting. Verdict: the lowest-risk real-language target was **Python** (already a hard dependency),
  not Go/Rust. The migration was executed as a strangler-fig with a golden-parity net.
- **What shipped:** the three-layer `cli/ → core/ → edges/` package (§2), the single **Anti-Corruption
  Layer** for all OpenClaw formats, Pydantic models replacing the hand-rolled schema, `store.py`
  (atomic + filelocked), `serve.py` on stdlib `http.server`, and `ruff`/`mypy`/`pytest`/golden gates.
  M6 deleted the entire Bash `lib/` tree and collapsed `bin/docket` to a launcher.
- **Result:** 416 pytest tests + 17 golden parity cases; OpenClaw knowledge confined to one module.
- **Reserved (not done, by design):** a Go/Rust single-binary rewrite — revisit **only** if zero-runtime-deps
  single-artifact distribution becomes a hard product requirement (see §4.5). Python is the destination
  until then.

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
  - **Every tool call goes through `core/tools.py`'s dispatcher**, where `pre_input`, `pre_tool_call` and `pre_output` all evaluate. A second execution path is a hole. Enforced by an AST test (`tests/python/test_tool_registry.py::test_only_the_chokepoint_imports_the_handler_module`).
  - **Docket-owned JSON goes through `edges/store.py`.** Append-only JSONL (`core/trace.py`, `core/audit.py`) writes directly, per the documented **D-12** exemption.
- **Tests** (`tests/`) — the counts here drift; `uv run python scripts/metrics.py --check` is the guard that fails CI when a README or doc number stops matching the tree. **Fix the claim, never the guard.**
  - `tests/python/` — the pytest suite. `uv run pytest`. Files are named by **subject**, not by card id.
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
- **Comments: keep rationale, delete archaeology.** Delete card ids, phase numbers, dates, provenance, and narration of what a deleted thing used to do — git history and this file hold all of it. Keep any sentence whose loss would let someone introduce a bug. **When in doubt, keep.**
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

## 5. Phase records (historical — every phase below is COMPLETE)

> **This is not a task list.** It was one, once; the name "The TODO" survived long after the work
> did. **Nothing in this section is outstanding** — see the status table at the top of the file.
>
> Each phase is preserved as written, in the present tense of its own moment, because the
> *reasoning* is the durable part: why a thing was built, what was deliberately narrowed, and which
> assumptions turned out wrong. Two conventions to read it with:
>
> - **Phases 0–9 were authored against the Bash codebase.** Their `lib/**/*.sh` paths refer to a tree
>   deleted in M6. Inline `(pre-migration Bash; now …)` notes point at the Python successor.
> - **Phases 10–18 predate D-19**, so they describe a Python core that still wrapped an external
>   daemon behind an Anti-Corruption Layer. That layer is gone too. **Where a phase below contradicts
>   §2, §2 wins.**

### PHASE 0 — Truth & correctness  *(☑ COMPLETE — blocking at the time; nothing else shipped first)*

#### ☑ P0-1 — Fix the `agents.list` vs `agents.registered` key bug

- **Why:** Live config uses `agents.list`. Code that reads `agents.registered` silently sees zero agents.
- **Files & lines:**
  - `lib/commands/install.sh:41` — `agents.registered` → `agents.list` (pre-migration Bash; now `src/docket/cli/_install.py`)
  - `lib/commands/smart.sh:139` — `config.get('agents', {}).get('registered', [])` → `...get('list', [])` (pre-migration Bash; smart routing later removed)
  - `lib/commands/doctor.sh:177` — `for agent in config.get('agents', {}).get('registered', [])` → `...get('list', [])` (pre-migration Bash; now `src/docket/cli/_doctor.py`)
  - Grep the whole repo: `grep -rn "registered" lib/` and fix every agent-list usage. (Leave unrelated uses of the word alone.)
- **Requirements:** Standardize on `agents.list`. Each agent object is `{"id": str, "model": str, ...}`.
- **Acceptance:**
  - `grep -rn "agents'\?\s*\]*.*registered\|get('registered'" lib/` returns nothing agent-list-related.
  - `docket smart status` shows the real agent count (not 0) when agents exist.
  - `docket install` Step "already configured" path prints a correct agent count, not `unknown`.
- **Test:** Add `tests/unit/test-config-keys.sh` (or extend test-helpers.sh) that builds a tmp config with `agents.list=[{id:a},{id:b}]` and asserts a small helper `count_agents()` returns `2`. Wire it into `run-all-tests.sh`.

#### ☑ P0-2 — Add config **drift detection** to `docket doctor`

- **Why:** `.docket-meta.json` and `openclaw.json` can disagree silently (e.g. model changed in one only).
- **File:** `lib/commands/doctor.sh` — add a new check section (after the per-project block, ~line 112). (pre-migration Bash; now `src/docket/cli/_doctor.py`)
- **Requirements:** For each project id, compare:
  - `meta_get id model` vs the agent's `model` in `openclaw.json` `agents.list`.
  - `meta_get id sessionKey` presence vs gateway metadata (best-effort; warn if absent).
  - TG binding in meta (if tracked) vs `get_tg_binding id`.
  - On mismatch: `fail "  <id>: drift — model meta=<x> openclaw=<y>"` and increment `issues`. Print hint: `Fix with: docket doctor --fix`.
- **Acceptance:** Manually set a different model in one source → `docket doctor` reports the drift and exits non-zero. Aligned config → no drift reported.
- **Test:** Integration case (pre-migration `tests/test-lifecycle.sh`; now pytest under `tests/python/`): create agent, mutate `.docket-meta.json` model, assert `docket doctor` output contains `drift` and exit code `1`.

#### ☑ P0-3 — Single audited config write path

- **Why:** Config writes are scattered inline python heredocs with no verification; root cause of drift and the P0-1 bug.
- **File:** new helper functions in `lib/helpers/json.sh` (pre-migration Bash; docket-owned JSON I/O now in `src/docket/edges/store.py`).
- **Requirements:** Implement and document:
  - `oc_get <jsonpath> [default]` — read a dotted path from `openclaw.json`.
  - `oc_set <jsonpath> <json-value>` — write a dotted path; **always** `json.dump(indent=2)`; validate the file parses *after* writing (re-open + `json.load`); on parse failure, restore from a `.bak` and `error`.
  - `set_agent_model <id> <model>` — convenience that updates BOTH `openclaw.json` `agents.list[].model` AND `.docket-meta.json` via `meta_set`, then returns 0 only if both succeeded.
  - Backup rule: before mutating `openclaw.json`, copy to `${CONFIG_FILE}.bak` (single rolling backup).
- **Acceptance:** Refactor `profile.sh`/`model.sh` to call `set_agent_model`; both sources end up equal. Corrupt-write simulation restores from `.bak`.
- **Test:** Unit test `oc_set`/`oc_get` round-trip on a tmp file; assert indent=2 preserved and invalid value rejected.

#### ☑ P0-4 — Batch gateway restarts (de-couple `restart_gateway`)

- **Why:** Multi-step ops restart the systemd unit repeatedly.
- **Files:** `lib/helpers/service.sh` and callers (pre-migration Bash; service/gateway control now in `src/docket/edges/adapters/system.py`).
- **Requirements:** Introduce a "dirty" flag pattern: helpers that mutate config set `DOCKET_GATEWAY_DIRTY=1` instead of restarting inline; `restart_gateway` is called **once** at the end of a command if dirty. Provide `mark_gateway_dirty` and `restart_gateway_if_dirty`. Update commands that currently call `restart_gateway` mid-flow.
- **Acceptance:** A command that changes 3 config values restarts the gateway exactly once (verify via a log/echo in a dry-run env var `DOCKET_NO_RESTART=1` that prints instead of restarting).
- **Test:** Unit test asserts `restart_gateway_if_dirty` is a no-op when not dirty and prints exactly one restart line when dirty (use `DOCKET_NO_RESTART=1`).

#### ☑ P0-5 — CI pipeline

- **Why:** Nothing currently guards regressions.
- **File:** new `.github/workflows/ci.yml`.
- **Requirements:** On push + PR: checkout, install `python3` + `bash` (ubuntu-latest has them), run `./scripts/validate-specs.sh` (non-blocking warn ok), then `./tests/run-all-tests.sh` (blocking). Cache nothing fancy. Add a status badge to README.
- **Acceptance:** CI runs and is green on a clean branch; a deliberately failing test makes CI red.
- **Test:** N/A (this *is* the test harness) — verify by pushing a branch.

#### ☑ P0-6 — Honest spec/coverage status

- **Why:** [specs/README.md](specs/README.md) claims coverage numbers (e.g. "100%") that aren't measured.
- **Files:** `specs/README.md`, run `./scripts/spec-coverage.sh`.
- **Requirements:** Run the coverage script; update the status table to reflect reality, or mark numbers as "unverified" until a real measurement exists. No fabricated 100%s.
- **Acceptance:** Status table matches `spec-coverage.sh` output (or says "manual estimate").

**Phase 0 exit criteria:** `docket doctor` detects drift and never miscounts agents; all config writes go through `oc_set`/`set_agent_model`; gateway restarts at most once per command; CI green on main; no fabricated coverage claims.

---

### PHASE 1 — Cost enforcement  *(☑ COMPLETE — the real differentiator at the time)*

> Context: there have already been billing incidents (a recorded billing error and a runaway-session analysis). Today docket only *reports* cost (`_aggregate_cost`). We need *enforcement*.

#### ☑ P1-1 — Per-agent budget field

- **Files:** `lib/commands/profile.sh`, `.docket-meta.json` schema, `json.sh` (pre-migration Bash; now `src/docket/cli/` + `core/`/`edges/`).
- **Requirements:** Add `docket profile <id> --budget <USD>` storing `budgetUsd` in `.docket-meta.json` (via `meta_set`). `0`/unset = no cap. Show budget in `docket info` and `docket cost`.
- **Acceptance:** `docket profile x --budget 5` then `docket info x` shows `Budget: $5.00`.
- **Test:** Unit: set budget, `meta_get x budgetUsd` returns `5`.

#### ☑ P1-2 — Budget check + auto-pause

- **Files:** new helper `lib/helpers/budget.sh`; hook into `cost.sh` (pre-migration Bash; budget logic now in `src/docket/core/`, cost in `src/docket/cli/`).
- **Requirements:** `check_budget <id>` compares `_aggregate_cost` total vs `budgetUsd`. At ≥100%: pause the agent (preferred: an OpenClaw gateway mechanism — research `openclaw agents` subcommands for disable/pause; fallback: set the agent's model to a sentinel/disabled state and `warn` loudly) and record a flag in meta (`pausedReason=budget`). At ≥80%: `warn`. Must be idempotent.
- **Acceptance:** Simulated usage over cap flips the agent to paused exactly once and reports it; under cap does nothing.
- **Test:** Integration with a fake sessions dir producing a known cost; assert pause triggers at the threshold.

#### ☑ P1-3 — Runaway-session detection

- **Files:** `lib/commands/cost.sh` (or `maintain`), reuse session JSONL parsing from `_aggregate_cost` (pre-migration Bash; now `src/docket/cli/`).
- **Requirements:** Detect burn anomalies: e.g. turns growing past a threshold (the docs mention a 258-turn / ~$28 bloat) or cost-per-hour spike. Surface in `docket doctor` and `docket cost`. Document thresholds as constants in `config.sh`.
- **Acceptance:** A session JSONL with >N turns triggers a warning naming the agent and turn count.
- **Test:** Unit on the parser with a crafted JSONL.

**Phase 1 exit:** an agent hitting its cap is auto-paused and reported; runaway detection fires before the $ threshold; both visible in `doctor` and `cost`.

---

### PHASE 2 — Finish consolidation & resolve "smart routing"  *(☑ COMPLETE)*

> Context: `router.sh` (pre-migration Bash dispatch; now the alias/removed-command map in `src/docket/__main__.py`) deprecates 10 commands in favor of `maintain, mode, context, cost, profile, doctor`, but ships both. "Smart routing" (`smart.sh`) injects prose into SOUL.md and does not actually change the model — it's placebo.

#### ☑ P2-1 — Complete the new verbs

- **Files:** `maintain.sh`, `mode.sh`, `context.sh`.
- **Requirements:** Ensure every capability of the deprecated commands (`reset, repair, cleanup, model, billing, monitor, memory, browser`) is fully covered by its replacement verb. Make a mapping table (old → new) and verify each path.
- **Acceptance:** Each deprecated command's behavior is reachable through the new verb with parity.

#### ☑ P2-2 — Delete deprecated aliases + dead code

- **Files:** `router.sh` (remove deprecated `case` arms after a deprecation window), delete now-unused command files.
- **Requirements:** Remove only after P2-1 parity is proven and tests updated. Update `help.sh`, README, `bin/docket` header comments.
- **Acceptance:** `docket <oldcmd>` prints a clean "renamed to \<new\>" (or is gone, per decision); no orphaned `cmd_*` files sourced.
- **Test:** Update integration tests to the new verbs; remove tests for deleted paths.

#### ☑ P2-3 — Resolve smart routing (decision required — see §6)

- **Option A (implement real routing):** Move model selection to the gateway/runtime. Requirements: research whether OpenClaw supports per-task model selection / fallback chains in `openclaw.json` (keys like `models`, `agents.defaults.model`); if yes, configure it there instead of SOUL.md prose. Build a **minimal eval harness**: `tests/evals/` with golden tasks per agent role and a script that runs cheap vs premium and scores output; routing ships only if no regression.
- **Option B (cut):** Remove `cmd_smart`, the SOUL.md injection, and all "smart routing" claims from README/help/templates. Keep only the *context/compaction* config IF it maps to real OpenClaw keys (verify against OpenClaw docs); otherwise remove that too.
- **Acceptance:** Either routing demonstrably changes the model used (proven in logs) with eval pass, OR every "smart routing" claim is gone and `docket smart` no longer exists.

#### ☑ P2-4 — Stop reinventing OpenClaw context features

- **Files:** `smart.sh`/`mode.sh` context bits.
- **Requirements:** docket must not write `contextPruning`/`compaction` shapes that disagree with OpenClaw's real schema. Verify the real keys against [docs.openclaw.ai](https://docs.openclaw.ai/); make docket a **thin pass-through** to OpenClaw's native settings or remove the feature.
- **Acceptance:** Any context/compaction value docket writes is read back correctly by `openclaw` and by docket's own status command (read/write schemas match).

**Phase 2 exit:** one command surface; "smart routing" is either real-with-evals or fully removed; no schema drift against OpenClaw.

---

### PHASE 3 — Park experiments & finish the edges  *(☑ COMPLETE)*

#### ☑ P3-1 — Move `terminal` (584 LOC) and `browser` (260 LOC) to `experimental/`

- **Requirements:** Create `lib/commands/experimental/`; move files; gate behind `DOCKET_EXPERIMENTAL=1` or a clear "experimental" warning. Fold browser *health* into `doctor` (it already partly is, doctor.sh:114-133). (pre-migration Bash paths; commands now live under `src/docket/cli/`)
- **Acceptance:** Core help no longer lists experimental commands as first-class; they still work when explicitly enabled.

#### ☑ P3-2 — Telegram: finish or document-as-manual

- **Requirements:** Either complete group auto-creation or update docs to "manual wire only" and make `wire` the single supported path. No 🚧 left in README.
- **Acceptance:** README status table has zero 🚧.

**Phase 3 exit:** zero half-features in the main path; README honest.

---

### PHASE 4 — Strengthen & extend  *(☑ COMPLETE)*

#### ☑ P4-0 — Remove dead adapter

- **What:** Moved `lib/adapters/claude-terminal.sh` → `lib/commands/experimental/claude-terminal-adapter.sh`. Removed empty `lib/adapters/` directory. The adapter was never sourced or used.

#### ☑ P4-1 — Fix integration tests for renamed commands

- **What:** `tests/test-lifecycle.sh` TEST 4 (`docket repair`) → `docket maintain check`; TEST 5 (`docket reset`) → `docket maintain clean`. Both were calling deprecated router arms that exit 1.

#### ☑ P4-2 — Basic team delegation (manager task queue)

- **Files:** `lib/commands/team.sh` — added `_team_delegate`, `_team_queue`, `_team_done`, `_task_list_path`, `_ensure_task_list`. (pre-migration Bash; team commands now in `src/docket/cli/`)
- **Interface:** `docket team delegate "<task>"`, `docket team delegate --priority high "<task>"`, `docket team queue`, `docket team done <task-id>`.
- **Storage:** Writes to `~/.openclaw/workspaces/manager/TASK_LIST.json` (per-object array, `{id, description, priority, created, status}`).
- **Acceptance:** delegate → queue shows the task, sorted by priority; `done` marks it complete; idempotent on empty queue.
- **Tests:** 5 unit tests in P4-2 section of `test-helpers.sh` (all passing).

#### ☑ P4-3 — Eval harness skeleton

- **Why:** Prerequisite for any real model routing work; creates the test surface before a single eval exists.
- **Files:** new `tests/evals/` directory; `tests/evals/run-evals.sh` (discovers and runs `*.eval.sh`); one golden eval per specialist role as `*.eval.sh` stubs.
- **Requirements:** `run-evals.sh` exits 0 if all passing, 1 if any fail. Each eval stub contains: inputs, expected output shape, scoring function (grep/python). Stubs may all SKIP initially — the harness must exist and run cleanly.
- **Acceptance:** `./tests/evals/run-evals.sh` runs without error; CI step added to `run-all-tests.sh` (non-blocking warn on failure).

**Phase 4 exit:** delegation round-trip is working; integration tests call only current commands; eval harness exists (even if all stubs skip).

---

## 6. Open decisions (resolve before the dependent task)

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
| D-14 | §4.5 bans an `AbstractBackend`, but the 2026-07-29 platform audit found the execution slice already leaks past the ACL (session-JSONL cost parsing in `core/utils.py`, 11 argv shapes, duplicated unit name). Formalize a **RuntimeDriver port**, or keep the ban? | Phase 18 L-1 | **One typed port, ONE shipped driver (OpenClaw).** This *revises* §4.5's ban: the port is containment of coupling that already exists, not speculative generality. A second driver still requires a §4.5 trigger (upstream stall/breakage) or a paying user — the "no plugin framework" spirit stands. |
| D-15 | §4.5 says "docket is not in the agent execution path" — false since AA-7's real dispatch. Rewrite the principle or keep pretending? | Phase 14 | **Rewrite** — the principle becomes: *docket orchestrates hops (and is accountable for queue/state/retry correctness); the daemon executes every tool call inside a turn.* The pure-docket vs daemon-gated split stays; the denial goes. |
| D-16 | Lobster workflow surface: docket lints YAML it cannot run (validator ignores 4 constructs its own template emits). Retire into the docket-native pipeline spec, or keep as a second dialect? | Phase 16 W-3 | **Retire (A)** — one workflow dialect docket actually executes (W-1/W-2). `docket workflow` becomes a removed-command notice mapping to the pipeline commands, same pattern as `docket team` (D-11). Keeping two dialects repeats the dual-queue mistake. |
| D-17 | `serve` job model: bare fire-and-forget daemon threads (no ids, errors suppressed) vs a persistent run registry + bounded worker pool? | Phase 14 R-3 | **Run registry + worker pool, stdlib only** — keep §4.5's no-FastAPI/no-async stance; drop the fire-and-forget. Every dispatch gets a run id, persisted state, and queryable outcome; `contextlib.suppress(Exception)` around dispatch is banned. |
| D-18 | Where do docket's own LLM calls (memory distillation C-2, judge steps) come from: provider SDKs, a wrapped gateway, or the driver? | Phase 17 C-2 | **Through the driver** (`agent_run` on a pod Lead / utility agent) — zero new SDK deps. A LiteLLM-class sidecar gateway is a Phase 18 L-5 *spike*, opt-in, and only if the daemon tolerates a base-url swap; hand-rolled per-vendor clients are banned permanently. |
| D-19 | Drop the OpenClaw daemon so docket owns every layer, reusing libraries only where they do not take control? | Phase 19, 2026-07-31 | **Yes — own the loop, rent the protocols.** Superseded an earlier same-day reading that recommended keeping the daemon for tool-using hops; the deciding evidence is that docket ships **four** policy templates hooked on `pre_tool_call` (`block-destructive`, `high-risk-credentials`, `high-risk-deploy`, `high-risk-payment`) and **none has ever been evaluated**, because the daemon owns the turn. The governance stack docket already built — policy engine, approval store with three channels, high-risk classifier, hash-chained audit, traces, worktree/port isolation — is enforceable only at the boundary of a turn it does not control. Owning the loop is what makes the guardrails real; it is not scope creep, it is the missing half of work already done. **The line:** docket owns the loop, the tool registry, tool dispatch and every gate; libraries are reused strictly at **protocol** level (OpenAI-compatible chat completions for inference, MCP for pluggable tool servers, containers for exec isolation). **Agent frameworks (LangGraph/CrewAI/AutoGen) are rejected** — they own the loop and therefore the interception points, which would relocate docket's guardrails into a third party's callback API: the same dependency being escaped, with a new vendor. **Amended same day, by the user: clean break, no compatibility layer.** docket is pre-1.0 with no external installs to protect, so the phase adds no second runtime beside the daemon and ships no migration path — the driver, the ACL (82 functions), `openclaw.json` and every shell-out to the `openclaw` binary are deleted, `docket install` is reimplemented to provision a docket-native home, and local installs are re-created rather than upgraded. This also unblocks channels: with no daemon to fall back on, docket owns the Telegram bot, which is what finally makes Telegram a real docket approval channel instead of the caveat it has been since G-5. |
| D-20 | **The company will ship agentic products, and wants docket as its main orchestrator. Is docket (a) the factory that builds those products, (b) the runtime the products themselves ship on, or both?** | Phase 20/21 (blocks their scope) | **ANSWERED 2026-07-31 — both, in a stated order, by the user's goal statement: "a factory for agentic products."** The reasoning is short and load-bearing: *if every product is agentic, the runtime is the common part of every product*, so the factory's highest-value output is not agent-written code, it is a **reusable substrate**. Order: **(a) factory first** — it exists today and Phase 19 finishes it; **(b) substrate second** — Phase 21 packaging (D-21), which each product *embeds as a library*. **What this answer explicitly does NOT buy:** the hosted-SaaS half of (b). Multi-tenancy, authn/authz for external callers, queues/workers, streaming and per-customer quota stay **out of scope** — an embedding product owns its own serving layer, and docket owns the gated loop inside it. That distinction is what keeps this answer cheap; conflating "embeddable library" with "hosted product runtime" is the failure mode this decision exists to prevent, and it is why D-22 and P21-2/P21-3 are cut rather than unblocked. Measured fact that makes the packaging cheap: the whole runtime slice (`core/llm`, `core/tools`, `core/session`, `core/agent_loop`, `core/policy`, `core/approval`, `core/security`, `core/audit`, `core/trace`, their adapters and `edges/store`) imports exactly **two** third-party packages, `pydantic` and `filelock` — no typer, no rich, no `ui`. The layering discipline already paid for the extraction. |
| D-21 | Split the package into an embeddable `docket-runtime` library plus the `docket` control plane built on it? | Phase 21 P21-1 (D-20 answered, so this is live) | **YES — confirmed 2026-07-31 once D-20 resolved.** Every agentic product the company ships then inherits the same gated tool chokepoint, policy engine, approval store and hash-chained audit, instead of each product team reinventing guardrails badly. That is the company-level asset neither LangGraph nor CrewAI offers, because their guardrails are opt-in callbacks rather than the only execution path. Cost is packaging + a public API contract, **not** a rewrite: `core/`/`edges/` are already CLI-free (verified). **Two hard constraints.** (1) Do **not** do this before Phase 19's removal wave — extracting a library that still reaches for `openclaw.json` would freeze the coupling into a published contract. (2) **Packaging only.** P21-1 draws a boundary around code that already exists and pins it with a test; it does not design new API surface, add extension points, or "generalise" anything. A package split that grows features is how this becomes the overengineering it was meant to avoid. |
| D-22 | Multi-tenancy model: stay project-scoped (`agent:<id>:<project>`), or add an end-user/tenant axis? | — (no longer scheduled) | **CUT 2026-07-31 — stay project-scoped; build nothing.** D-20's answer scopes the substrate to an *embedded library*, and an embedding product owns its own tenant model, so docket does not need one. The decision stays **on the record, not deleted**, because the original warning is still true: session keys, workspaces, budgets, traces, audit entries and approval records are all keyed on *project*, and retrofitting a tenant key is expensive. **Re-open only on a concrete trigger** — docket itself serving more than one end customer from one host. Until then, writing the tenant axis is speculative generality of the exact kind §4.5 bans. |
| D-23 | Network egress for agent tool calls: open by default, or closed with an allowlisted `fetch` tool? | Phase 19 P19-11 | **Open by default, lockdown opt-in** (integrator's call, reversible config; say so if you disagree). Measured 2026-07-31: `curl`/`wget` correctly ask, but `python3 -c "import urllib..."`, `node`, and `git clone <url>` are all **allowed unattended** — `python3` and `node` are universal escape hatches on the curated allowlist, so **network egress is effectively ungated today**, and P19-9's sandbox does not close it either (both backends leave the network reachable). Closing egress by default breaks `npm install`, `pip` and `git clone`, which is why the default stays open; P19-11 ships an always-available, domain-allowlisted `fetch` tool so there is an inspectable path that does not require the escape hatch. **Re-scoped 2026-07-31 (prioritization ruling, §5 Phase 19):** P19-11 ships **the `fetch` tool only**. The opt-in lockdown mechanism (`--network none` / `--unshare-net`) is **deferred** — it is a knob that is off by default, that breaks the three commands agents use most when turned on, and that no measured need has asked for. It buys a *config option*, not a guarantee. **Say the true thing in the docs instead**: egress is open, `fetch` is the inspectable path, and the escape hatches are known and named. An honestly-open gate beats a gate that reads as closed. Re-open when a product needs an actually-network-isolated agent. |
| D-24 | Phases 20/21 were drafted as "best practice for an agent platform". Under the answered goal (a factory for agentic products, D-20), which of those items are genuinely viable and which are overengineering? | Phases 20/21, before either starts | **Ruling 2026-07-31 — cut roughly half, and the cuts include the integrator's own earlier recommendations.** Full verdict table in §5 under *"Prioritization ruling"*. Headline: **OpenTelemetry (P20-1) is CUT**, having been proposed the same day as "the industry standard" — correct at platform scale, wrong at **one host and one operator** with JSONL traces and six Prometheus metrics already shipped. Also cut: **streaming (P21-2)** and the **tenant axis (P21-3)**, both of which only existed to serve the hosted-runtime reading D-20 rejected. Deferred: fleet trace query (P20-3), egress lockdown (D-23), build-agent profile (P21-4). Kept: the removal wave, per-role tool sets, the MCP CLI, the `fetch` tool, the package split, guardrail metrics, the `runs cancel` audit entry, and one new **XS** card — an `agentic-product` pod blueprint, which is *data in an existing registry*, not code. **The principle being applied is already written down** (§4.5, "we will NOT"): the test is not "is this best practice for someone", it is *"does a measured need in **this** system ask for it"*. It applies to the integrator's proposals exactly as it applies to a card's. |
| D-25 | After the 2026-08-30 CTO/OSS audit, should Docket compete as a broad agent framework or productize its governed coding-agent runtime and only then prove portable enforcement? | Phase 23 | **Productize the narrow wedge first; prove portability second.** The explicit request is to make Docket useful in the AI-orchestration ecosystem, but the audit found that the immediate blockers are a default first run that cannot resolve its advertised Anthropic endpoint, invalid release/install metadata, overlapping runtime wheel contents, non-atomic governance transitions, brittle free-text verdicts, and cancellation that does not interrupt the owned loop. Wave 26 fixes those truths before adding ecosystem surface. Docket does **not** compete on graph/pattern count and does not claim framework neutrality while it owns only `DocketDriver`. A later interoperability wave may add the smallest stable execution envelope and exactly two evidence-producing adapters—one coding runtime and one general agent framework—without surrendering `dispatch_tool` as the enforcement chokepoint. This decision does **not** reopen multi-tenancy, hosted queues/workers, a Docket dashboard, generic streaming, or default-closed egress. D-23 still governs egress. OpenTelemetry/A2A become schedulable only when the two-runtime proof names a concrete trace/remote-task requirement that existing JSONL/MCP cannot satisfy. |
| D-26 | What is the release-blocking adoption journey? | Wave 26 | **One immutable source commit → built artifact → clean install → supported provider configuration → initialized pod → first successful governed tool turn → public trace/run inspection.** Every boundary is exercised outside the checkout by deterministic CI. No new orchestration feature outranks a failure in this journey, and external publication remains approval-gated. |
| D-27 | When may Docket claim that it governs an external runtime? | Wave 28 | **Only when every relevant mutation/exec action in the reference fixture is forced through a Docket-owned execution envelope and the same policy, approval, budget, trace, and audit semantics are observed.** Merely launching, importing, coordinating, or offering Docket tools beside an external runtime is not governance if native bypass tools remain. Prove one coding runtime and one general framework before making a neutrality claim; do not build a plugin framework before the second caller exists. |
| D-28 | Does D-21's packaging-only ruling permit correcting the overlapping `docket-runtime` wheel and adding a facade? | W26-C5 | **Yes, narrowly.** Two independently installable distributions may not own the same files. A non-overlapping package topology, wheel+sdist support, and the smallest versioned facade needed by a real embedding example are correctness fixes to the package split, not speculative runtime features. Internal modules remain private unless the facade exports them; adapters and new extension APIs still need real callers under D-27. |
| D-29 | How is Phase 23 delivered by simultaneous agents without duplicating context or corrupting central state? | Phase 23 execution | **One coordinator plus as many non-contending worker lanes as the environment supports.** Each card has one owner, isolated worktree, unique `DOCKET_HOME`/temp/ports, exact allowed paths/functions, and a delta-only evidence handoff. `ROADMAP.md`, `TODO.md`, `README.md`, `specs/README.md`, release rollups, and mutable live endpoints are integrator-owned. Workers load the snapshot, one extracted card, one named decision, the owning spec section/tests, and the live callers—never the planning corpus or another worker's raw conversation. |
| D-30 | What does `cancelled` mean for an in-process run that a separate CLI process can request but cannot forcibly interrupt? | W26-C10a–C10c | **Cancellation is a persisted lifecycle, not a process-local event or an immediate stop claim.** The run id is the signal identity and its additive record distinguishes `requestedAt`, `observedAt`, and `stoppedAt`. A queued request is fully stopped atomically because no body ran. A running request remains visibly in flight until the owned executor observes it and reaches a safe stop; if the request wins the registry CAS, later success/failure cannot overwrite cancellation. Checkpoints prevent every not-yet-started model request, approval continuation, and tool handler. A cooperatively stopped task uses the additive status `cancelled`, never ordinary `failed`. An HTTP request or tool handler already executing may finish because Python threads are not killed; its result is either discarded before any next side effect or retained only as a complete assistant/tool-result unit, then the run stops. The existing CLI is the mutation surface; Wave 26 adds no POST cancellation API, event bus, async runtime, or unsafe thread kill. |
| D-31 | Which branch is Docket's public release lineage after Wave 26? | W26-C0 | **`main` is the canonical public/default release lineage.** The maintainer authorized the current `platform` lineage to fast-forward `main`; GitHub already names `main` as the default branch, and the preflight showed `platform` exactly 300 commits ahead with no `main`-only commits. The update is fast-forward-only and both branch names remain recoverable and synchronized. Tags and protected release jobs originate from `main`; feature/work branches are never release sources merely because they are newer. C3 owns replacing the remaining mutable installer/formula inputs with immutable tagged artifacts. |

---

### PHASE 5 — Channel portability + system snapshot  *(☑ COMPLETE)*

#### ☑ P5-1 — Channel-aware wire/unwire

- **Why:** `upsert_binding` hardcodes `"channel": "telegram"` and `get_tg_binding` only reads Telegram bindings. OpenClaw supports 50+ channels; docket should not be Telegram-only at the binding layer.
- **Files:** `lib/helpers/json.sh` (generalize `upsert_binding`, add `get_channel_binding`, keep `get_tg_binding` as alias); `lib/helpers/workspace.sh` (`_wire_group` gains `channel` arg); `lib/commands/wire.sh` (detect channels via `openclaw channels list`, offer picker when >1); `lib/commands/unwire.sh` (`--channel` flag). (pre-migration Bash; bindings now go through the ACL `src/docket/edges/adapters/openclaw.py`, commands in `src/docket/cli/`)
- **Requirements:** For Telegram: existing group discovery flow unchanged. For non-Telegram: prompt for peer ID manually (no log-based discovery). `get_tg_binding` remains as a thin wrapper over `get_channel_binding` for backwards compat.
- **Acceptance:** `docket wire myproject` with only Telegram configured behaves identically to today. Adding a second channel (e.g. Discord) would offer a channel picker before the group selection.
- **Tests:** 3 unit tests — `upsert_binding` with explicit channel arg; `get_channel_binding` retrieves correct peer; `get_tg_binding` still works as alias.

#### ☑ P5-2 — `docket snapshot` command

- **Why:** No machine-readable export of system state exists. Teams need to pipe agent status into dashboards, CI artifacts, or monitoring scripts without installing docket.
- **Files:** new `lib/commands/snapshot.sh` (`cmd_snapshot()`); wire into `lib/core/router.sh` and `lib/commands/help.sh`. (pre-migration Bash; now `src/docket/cli/` + the `src/docket/__main__.py` command map)
- **Interface:** `docket snapshot` → JSON to stdout. `docket snapshot --output <file>` → write to file.
- **JSON shape:** `{timestamp, gateway, channels[], agents:[{id,name,type,model,bindings,lastActivity,costUsd}], totalCostUsd}`.
- **Acceptance:** `docket snapshot | python3 -m json.tool` exits 0 (valid JSON). All project + specialist agents appear in the output.
- **Tests:** 1 unit test — snapshot output is valid JSON containing at least one agent.

#### ☑ P5-3 — `docket serve` command

- **Why:** Closes the "multi-user" backlog item with a minimal server that shares live agent state without requiring docket on every machine.
- **Files:** new `lib/commands/serve.sh` (`cmd_serve()`); wire into router and help. (pre-migration Bash; now `src/docket/serve.py`)
- **Interface:** `docket serve [--port 7331] [--interval 30]`. Starts Python built-in HTTP server; refreshes snapshot JSON every `--interval` seconds; Ctrl-C stops cleanly.
- **Requirements:** Uses `python3 -m http.server` in a temp dir. Background loop rewrites `status.json` every interval. `GET /status.json` returns fresh snapshot.
- **Acceptance:** `docket serve` starts without error; `curl localhost:7331/status.json` returns valid JSON; Ctrl-C exits without leaving background processes.
- **Tests:** none (runtime HTTP behaviour, not unit-testable in Bash).

**Phase 5 exit:** bindings are channel-agnostic; system state is exportable as JSON; a team-visible HTTP endpoint exists.

---

### PHASE 6 — Model & provider agnosticism  *(☑ COMPLETE)*

> **Why this is critical:** docket currently has a hard dependency on the Claude API.
> A pricing change, outage, regional block, account suspension, or ToS change at one vendor
> breaks every docket deployment. The fix is to make docket **model-agnostic**: any provider the
> OpenClaw daemon supports — **local/free** (Ollama, llama.cpp, LM Studio) or **remote/paid**
> (Anthropic, OpenAI, Google) or **mixed** (OpenRouter, which has free-tier models) — must
> work, and the model in use must be **explicit and visible** in every command output,
> instruction template, README, and help text. Anthropic stays the *default* (it works today),
> but it must become *one option among several*, clearly labeled.
>
> **Where the Claude dependency lives today (verified against source, 2026-06-11; pre-migration Bash paths — the model layer now lives in `src/docket/core/` `models_policy.py`/`policy.py`/`provider.py`, install in `src/docket/cli/_install.py`, list/keys in `src/docket/cli/`):**
>
> | Layer | File / lines | Problem |
> | ----- | ------------ | ------- |
> | Hard whitelist | `lib/helpers/models.sh:5-9` `VALID_MODELS` | `validate_model()` **errors on any non-Anthropic model** — the single hardest blocker |
> | Fallback chain | `lib/helpers/models.sh:55-69` `get_fallback_model` | hardcoded opus→sonnet→haiku IDs |
> | Alias/fix table | `lib/helpers/models.sh:12-22`, `fix_invalid_models()` py heredoc | Claude-only aliases duplicated in bash + python |
> | Default model | `lib/core/config.sh:11` `DEFAULT_MODEL="anthropic/claude-sonnet-4-6"` | fine as a default, but not overridable per install |
> | Tier mapping | `lib/core/config.sh:41-45` `MODEL_PROFILES` | economy/standard/premium → Claude only |
> | Pricing | `lib/core/config.sh:48-54` `MODEL_PRICING` | Claude-only; unknown model silently costs $0 |
> | Install | `lib/commands/install.sh:175-181` `specialist_models` | 6 specialists hardcoded to Claude IDs |
> | Display | `lib/commands/list.sh:158`, `list.sh:219-224` | strips only the `anthropic/claude-` prefix |
> | Key sync | `lib/commands/keys.sh` `PROVIDER_KEYS` (~line 391), `_agent_provider` (~309) | **already half-agnostic** (anthropic/openai/google/openrouter) — extend, don't rewrite |
> | Templates | `lib/templates/SMART-ROUTING.md`, `docket-programmer.md`, `docket-tester.md`, `status-awareness.md`, `SOUL-error-handling.md` | prompts say "haiku/sonnet/opus", link `console.anthropic.com` |
> | Docs | `README.md` (~216-218), `docs/commands.md`, `docs/troubleshooting.md`, `CLAUDE.md`, `lib/commands/help.sh` (now `src/docket/cli/_help.py`) | profile tables and examples are Claude-only; never states other providers work |
>
> **Design rules for this phase (do not violate):**
>
> 1. The **tier abstraction stays** (economy/standard/premium) — users think in tiers; the
>    tier→model mapping becomes data, not code.
> 2. docket **validates format, the daemon validates the model.** A well-formed `provider/model`
>    docket doesn't recognize gets a `warn` (no pricing data, unknown provider key), never an `error`.
> 3. **No silent cost lies.** Unknown pricing → `n/a`, local → `$0 (local)`. Never $0.00 for an
>    unpriced remote model.
> 4. **Anthropic remains the out-of-box default.** This phase adds choice + clarity; it does not
>    change behavior for an existing install that does nothing.
> 5. Every config write goes through the existing audited path (`json_atomic_write` /
>    `oc_set` / `meta_set`); registry writes are no exception.

#### ✅ MA-1 — Spike: verify the OpenClaw daemon's provider contract  *(blocking; do first)*

- **Goal:** Establish ground truth on what model strings/providers the daemon actually accepts, so MA-2…MA-8 build on facts, not guesses.
- **Files:** a scratch findings doc during the spike (not retained in-repo).
- **Requirements:**
  - Check `openclaw --help`, `openclaw models --help` (if it exists), and <https://docs.openclaw.ai/> for: supported providers; model-ID format (`provider/model`?); how a **local / OpenAI-compatible endpoint** (Ollama at `http://localhost:11434`, llama.cpp, LM Studio) is configured (base-URL override? a `models` section in `openclaw.json`? per-agent?); which env var each provider's key uses; fallback-chain support.
  - Inspect the live `~/.openclaw/openclaw.json` `models` top-level key (it exists — see §2) and document its real schema.
  - Record per provider: id prefix, key env var (or "none — local"), free/paid, config snippet docket would need to write.
  - Explicitly answer: **can the daemon talk to an Ollama-style local endpoint, and what exact config enables it?** If the daemon cannot, document the limitation and scope MA-4's `local` preset to whatever the daemon *can* do (e.g. OpenRouter free-tier models as the "free" path) — do not fake it.
- **Acceptance:** `MODEL-AGNOSTIC-NOTES.md` exists with a verified provider table + at least one working non-Anthropic model string proven against the daemon (e.g. set on a test agent, daemon accepts it / responds).
- **Test:** N/A (research). The doc is the deliverable; later tasks cite it.

#### ✅ MA-2 — Data-driven model registry (kill the whitelist)

- **Goal:** Replace hardcoded `VALID_MODELS` / `MODEL_PROFILES` / `MODEL_PRICING` / `DEFAULT_MODEL` with built-in defaults + a user-editable registry file.
- **Files:** `lib/core/config.sh`, `lib/helpers/models.sh`, new registry file `$OPENCLAW_DIR/docket-models.json` (created on first write, not by install). (pre-migration Bash; model layer now `src/docket/core/models_policy.py`/`policy.py`/`provider.py`)
- **Requirements:**
  - Registry schema (all keys optional; absent → built-in default):

    ```json
    {
      "default": "anthropic/claude-sonnet-4-6",
      "profiles": {"economy": "...", "standard": "...", "premium": "..."},
      "pricing": {"<provider>/<model>": {"input": 3.0, "output": 15.0, "cacheWrite": 0.3, "cacheRead": 3.75}},
      "localProviders": ["ollama", "local", "lmstudio"]
    }
    ```

  - Add `load_model_registry()` in `config.sh`, called once at startup after the built-in arrays are declared: if `docket-models.json` exists and parses, overlay it onto `DEFAULT_MODEL`, `MODEL_PROFILES`, `MODEL_PRICING` (one python pass emitting `key=value` lines; same pattern as existing helpers). Corrupt file → `warn` + keep built-ins (loud-on-corruption convention, Phase 1).
  - Rewrite `validate_model()`: well-formed = matches `^[a-z0-9_-]+/[A-Za-z0-9._:-]+$` (verify against MA-1 findings). Known model → pass. Well-formed unknown → `warn "model not in docket's registry — accepted, but no pricing data (cost will show n/a)"` and **return it** (exit 0). Malformed (no `provider/` prefix and not a known alias/tier) → `error` listing current tiers + example IDs from the live registry, not a hardcoded Claude list.
  - Rewrite `get_fallback_model()` to walk the **tier chain** (premium→standard→economy) using the live `MODEL_PROFILES`; a model not in any tier falls back to the economy tier's model.
  - Keep `MODEL_ALIASES` (typo healing) but make `fix_invalid_models()` read the same alias table (generate the python dict from the bash array, or move the table into the registry file) — no more duplicated tables.
- **Acceptance:**
  - `docket profile <id> openrouter/some-model` (or any well-formed non-Anthropic ID) is accepted with a warning, lands in both `.docket-meta.json` and `openclaw.json`.
  - With no `docket-models.json`, every existing command behaves byte-identically to today (defaults unchanged).
  - A `docket-models.json` overriding `profiles.economy` changes what `resolve_model economy` returns.
- **Test:** Unit (extend `tests/unit/test-helpers.sh` or new `test-models-registry.sh` wired into `run-all-tests.sh`): (1) registry overlay changes `resolve_model`; (2) corrupt registry → built-ins survive + warning on stderr; (3) `validate_model` accepts well-formed unknown, rejects malformed; (4) fallback walks tiers from live mapping.

#### ✅ MA-3 — `docket models` command (make the mapping visible and editable)

- **Goal:** One place to see and change which models docket uses — no more silent defaults buried in source.
- **Files:** new `lib/commands/models.sh` (`cmd_models()`); wire into `lib/core/router.sh` and `lib/commands/help.sh`. (pre-migration Bash; now `src/docket/cli/`, the `src/docket/__main__.py` command map, and `src/docket/cli/_help.py`)
- **Interface:**
  - `docket models` / `docket models list` — table: TIER | MODEL | PROVIDER | PRICE (in/out per MTok, or `free/local`, or `n/a`) | SOURCE (`builtin` | `user`). Plus the default model and the registry file path.
  - `docket models set <economy|standard|premium|default> <provider/model>` — validates via `validate_model`, writes `docket-models.json` via `json_atomic_write`, audit-logs (`models.set`), prints the new effective mapping. Note in output: existing agents keep their current model; affects new agents and future `docket profile <tier>` calls.
  - `docket models reset` — delete user overrides (confirm first), back to built-ins.
- **Requirements:** no gateway restart needed (mapping is docket-side; agents change only via `docket profile`). Follow output.sh helpers; never raw echo for status.
- **Acceptance:** `docket models set economy ollama/qwen2.5-coder` → `docket models list` shows it with SOURCE=user and PRICE=free/local; `docket profile <agent> economy` now assigns that model; `docket models reset` restores Claude defaults.
- **Test:** Unit: set → list contains new mapping; reset → restored; audit.log has a `models.set` line; invalid tier name errors.

#### ✅ MA-4 — Provider presets, including a free/local path

- **Goal:** One command to switch the whole tier mapping to a provider, with **free vs paid clearly labeled** at the moment of choice.
- **Files:** `lib/commands/models.sh` (extend), `lib/core/config.sh` (preset tables). (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/`)
- **Requirements:**
  - `docket models preset` (no arg) lists presets with cost class, e.g.:
    - `anthropic` — paid, API key required *(default)*
    - `openai` — paid, API key required
    - `google` — paid, API key required
    - `openrouter` — paid + free-tier models, API key required
    - `local` — **free**, no API key, requires a local runtime (Ollama) — exact mechanics per MA-1 findings; if the daemon can't do local endpoints, this preset maps to the verified free alternative from MA-1 and says so honestly
  - `docket models preset <name>` writes all three tiers + default to that provider's models (concrete model IDs chosen during implementation from MA-1's verified table; pin them in `config.sh` preset arrays with pricing entries where known).
  - Print a post-switch checklist: which key (if any) to add via `docket keys add`, and for `local`: how to verify the runtime is up. If the needed provider key is missing, `warn` immediately.
- **Acceptance:** `docket models preset local` → `docket models list` shows all tiers free/local; `docket models preset anthropic` restores the default mapping; preset with a missing key warns and names the exact `docket keys add <KEY>` command.
- **Test:** Unit: each preset round-trips through the registry file; `local` preset + `docket keys sync` produces no missing-key warning (see MA-6); unknown preset name errors listing valid presets.

#### ✅ MA-5 — Cost honesty for unknown and local models

- **Goal:** Never report a made-up $0.00 for a model docket can't price.
- **Files:** `lib/helpers/workspace.sh` (`_aggregate_cost`, `_estimate_cost`), `lib/commands/cost.sh`, `lib/commands/list.sh`, `lib/helpers/budget.sh`. (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/`)
- **Requirements:**
  - Model in `MODEL_PRICING` → price as today. Model whose provider is in `localProviders` → `$0 (local)`. Otherwise → display `n/a (no pricing data)`; in `--json` output emit `"costUsd": null, "pricingKnown": false` (not `0`).
  - Budget enforcement (`check_budget`): if an agent's model is unpriced and a budget is set, `warn` once that the budget **cannot be enforced** for that agent (and say why) instead of silently never triggering.
  - Display code in `list.sh` stops assuming the `anthropic/claude-` prefix: show `provider/short-name` generically (strip provider for width, keep it in `info`/`--json`).
- **Acceptance:** An agent on an unpriced model shows `n/a` in `docket cost` and `null` in `docket cost --json`; a local-provider agent shows `$0 (local)`; budget + unpriced model produces the explicit warning.
- **Test:** Unit on the pricing resolution function with: priced, local, unknown. Integration: fake sessions dir + unpriced model → `cost --json` has `pricingKnown: false`.

#### ✅ MA-6 — Provider-agnostic key plumbing & doctor checks

- **Goal:** Scoped key sync and health checks work for every registry provider; local providers don't nag about keys.
- **Files:** `lib/commands/keys.sh` (`PROVIDER_KEYS` py dict ~line 391, `_agent_provider`, help text ~44-51), `lib/commands/doctor.sh`, `lib/commands/install.sh`. (pre-migration Bash; now `src/docket/cli/` + `src/docket/cli/_doctor.py`/`_install.py`)
- **Requirements:**
  - Single source of truth for provider→key-env mapping (extend per MA-1 findings; at minimum anthropic, openai, google, openrouter + the local set needing none). Generate the python `PROVIDER_KEYS` dict from it rather than a second hardcoded copy, or document why the duplication stays.
  - `docket keys sync`: agent on a local provider gets no provider key and **no warning**. Agent on provider X with no X key stored → one clear `warn` naming `docket keys add <KEY>`.
  - `docket doctor`: per-agent check "model `<provider>/…` but `<PROVIDER>_API_KEY` not stored" (skip local providers). Also surface the active default model + tier mapping in doctor's summary so the model in use is visible during diagnosis.
  - `docket install`: stop implying only `ANTHROPIC_API_KEY` matters — prompt/hint based on the active preset's provider.
- **Acceptance:** Agent on `openrouter/...` with no OpenRouter key → doctor flags it precisely; agent on `ollama/...` → no key warnings anywhere; keys help lists all supported providers + where to get each key.
- **Test:** Unit: provider→key resolution for each provider incl. local→none; doctor check fires/skips correctly (extend the existing doctor drift test pattern).

#### ✅ MA-7 — Neutralize Claude-isms in agent templates

- **Goal:** Agent instruction prompts speak in **tiers**, not Claude model names, and don't hardcode Anthropic URLs — so a fleet on any provider gets correct instructions.
- **Files:** `lib/templates/SMART-ROUTING.md`, `lib/templates/docket-programmer.md`, `lib/templates/docket-tester.md`, `lib/templates/status-awareness.md`, `lib/templates/SOUL-error-handling.md`; `lib/helpers/workspace.sh` (`_create_workspace`); `lib/core/config.sh` (`TEMPLATE_VERSION`). (pre-migration Bash; templates now ship under `src/docket/templates/`, provisioning in `src/docket/cli/`/`core/`)
- **Requirements:**
  - Replace literal `haiku-4-5`/`sonnet-4-6`/`opus-4-6` and their prices with placeholders rendered at workspace-creation time from the live registry: `{{MODEL_ECONOMY}}`, `{{MODEL_STANDARD}}`, `{{MODEL_PREMIUM}}`, `{{PRICE_…}}` (render via the existing template-emission path in `_create_workspace`; portable sed or the python pass). Prose should say "the economy tier (currently {{MODEL_ECONOMY}})".
  - `console.anthropic.com` links become provider-resolved: a small provider→billing/console URL table; unknown provider → generic "check your provider's billing console".
  - Bump `TEMPLATE_VERSION` so `docket doctor` flags every existing agent for `docket maintain <id> rebuild` (this is exactly what the drift mechanism is for).
- **Acceptance:** `docket add` on a `local`-preset install produces SOUL/AGENTS/instruction files that mention the actual configured models and **zero** Claude model names; `grep -ri "sonnet\|haiku\|opus\|console.anthropic" ~/.openclaw/workspaces/projects/<new-agent>/` returns nothing on a non-Anthropic preset.
- **Test:** Unit: render a template with a non-default registry → placeholders substituted, no `{{` left; integration: new agent's SOUL.md contains the mapped economy model string.

#### ✅ MA-8 — Docs, help & README truth pass

- **Goal:** A new user reading any entry point learns within one screen: docket is model-agnostic, what the default is, what the free option is, and how to switch.
- **Files:** `README.md`, `docs/QUICK-START-DOCKET.md`, `docs/commands.md`, `docs/troubleshooting.md`, `docs/DOCKET.md`, `CLAUDE.md`, `lib/commands/help.sh` (now `src/docket/cli/_help.py`).
- **Requirements:**
  - README gains a **"Model support"** section near the top: explicit statement that docket works with any OpenClaw-supported provider — local/free (per MA-1/MA-4 reality) or remote/paid; the default mapping table gains a PROVIDER column and a row/callout for the free option; `docket models` + `docket models preset` documented with copy-paste examples.
  - The existing profile table (README ~216-218) is regenerated from the *current* built-in registry and labeled "default (Anthropic) — change with `docket models`".
  - `help.sh`: add `models` to command list; the profile/cost help text stops naming Claude models as the only options.
  - `CLAUDE.md`: update "Model profiles" bullet + architecture notes to describe the registry and `docket models`.
  - Every doc claiming or implying "requires Anthropic API key" is corrected to "requires the API key for your configured provider (none for local)".
- **Acceptance:**
  - `grep -rn "claude" README.md docs/` shows Claude only as *one labeled option/default*, never as a requirement.
  - README status/feature tables contain no 🚧 introduced by this phase; all examples runnable as written.
- **Test:** Docs task — acceptance is the grep audit above + `./tests/run-all-tests.sh` still green (help.sh changes are exercised by integration tests).

**Phase 6 exit criteria:** a user can run a whole fleet on a non-Anthropic provider (including the verified free/local path) using only documented `docket` commands; no command errors on a well-formed non-Claude model; cost output never invents $0 for unpriced models; templates/docs/help name the *configured* models, not Claude unconditionally; Anthropic defaults unchanged for users who do nothing.

### PHASE 6b — Tier-less role→model policy: unified agent/model architecture  *(✅ complete 2026-06-12)*

> **Why:** Phase 6 made the tier→model layer agnostic, but **model assignment still bypasses it**
> in three places, and the agent taxonomy is implicit:
>
> | Gap | Where | Symptom |
> | --- | ----- | ------- |
> | Specialists hardcode literal Anthropic IDs | `lib/commands/install.sh:175-182` (now `src/docket/cli/_install.py`) | `docket models preset openai` then `docket install` → specialists still get Claude models |
> | `docket add` ignores agent type | `lib/commands/add.sh:139`, `add.sh:247-248` (now `src/docket/cli/`) | `repo` and `task` agents both get `$DEFAULT_MODEL`; no per-kind default |
> | Agents store a resolved model, not an intent | `.docket-meta.json` `model` field; `models.sh` "existing agents keep their current model" notices | Remapping silently strands every existing agent on the old model (drift) |
> | Specialists outside the meta system | no `.docket-meta.json` under `~/.openclaw/workspaces/<spec>/` | `docket list`/`profile`/`doctor` don't see them; two tooling paths |
>
> **Root design flaws:** (a) agents remember a *model* when they should remember an *intent*
> (follow my role's policy), resolved through the registry at apply time; (b) the
> economy/standard/premium **tier ladder is a price abstraction, not a workload one** — it
> forces every provider catalog into 3 symmetric rungs and can't say *why* an agent gets a
> model (a manager on the cheap model isn't "economy", it's "high-volume/low-reasoning work").
>
> **Decided architecture (2026-06-11, with user): tiers are removed from the UX.**
>
> 1. **Role is the only user-facing model concept.** Resolution chain (highest wins):
>    `explicit pin (raw model ID)` → `role policy (role→model)` → `DEFAULT_MODEL`.
> 2. **Role policy is global-only** — one `roles:` map (role → model ID); built-in defaults
>    in `config.sh` (`ROLE_MODELS`), user-overridable in `docket-models.json` via the existing
>    overlay pattern. No per-project policy (per-agent pins cover exceptions).
>    Built-in defaults chosen for **token efficiency** (cheapest adequate model per workload),
>    anthropic preset: manager→haiku (chatty coordination, shallow reasoning),
>    reviewer→haiku (triage), tester→haiku (run+report), knowledge→haiku (retrieve/summarize),
>    programmer→sonnet (generation), security→sonnet (audit depth),
>    repo→sonnet, task→haiku (project-agent type defaults). Opus is an explicit per-agent
>    pin, not a standing rung.
> 3. **Presets become role→model tables** per provider (each preset picks its own
>    efficient mapping; no forced 3-rung symmetry). Tier names economy/standard/premium
>    survive only as **deprecated aliases** (warn + resolve via a hidden per-preset rank
>    list) so existing commands/scripts don't break during migration.
> 4. **Auto re-resolve on policy change** — `docket models set <role> <model>` /
>    `docket models preset <name>` re-resolves every policy-following agent (updates both
>    config sources, one gateway restart, per-agent change summary, audit-logged);
>    pinned agents are never touched. Policy is live, not a creation-time template.
> 5. **Specialists unify into the meta system** — `.docket-meta.json` with `kind: specialist`,
>    `role: <name>`; project agents get `kind: project` (existing `type` repo/task stays,
>    doubling as their policy role). One taxonomy visible in `docket list`, one tooling path.
> 6. **Fallback** becomes a per-preset ranked model list (walk down to next-cheaper);
>    replaces the premium→standard→economy tier walk in `get_fallback_model`.
>
> **Explicitly deferred (decided 2026-06-11):**
>
> - `docket models optimize` — data-driven right-sizing per role (join Phase 5 cost history ×
>   eval-harness pass/fail → "reviewer passes evals on a cheaper model, −$X/mo" suggestions,
>   never auto-applied). **Later phase**, after the role policy has accumulated usage history.
> - **Per-task dynamic routing** (manager escalates/downgrades model per task at runtime).
>   Blocked on a spike: does the OpenClaw daemon support per-session model override?
>   (Extend MODEL-AGNOSTIC-NOTES.md.) Do **not** reintroduce prompt-level SMART-ROUTING
>   (cut in Phase 2) as a substitute.

#### ✅ MA-9 — Role→model policy map (taxonomy + policy data, tiers out)

- **Goal:** A single data structure answers "what model should this kind of agent run on, and why", replacing every hardcoded per-agent model choice *and* the tier ladder.
- **Files:** `lib/core/config.sh` (`ROLE_MODELS` replaces `MODEL_PROFILES`; registry overlay), `lib/commands/models.sh` (presets become role→model tables; deprecated tier aliases), `lib/helpers/models.sh` (`validate_model`, `get_fallback_model`), `lib/commands/install.sh` (kill `specialist_models` array), `lib/commands/add.sh` (default by type), `lib/commands/profile.sh`, templates touched by MA-7 (`{{MODEL_ECONOMY}}`-style placeholders → role-based). (pre-migration Bash; model layer now `src/docket/core/models_policy.py`/`policy.py`, commands in `src/docket/cli/`, templates under `src/docket/templates/`)
- **Requirements:**
  - `declare -A ROLE_MODELS` in config.sh with the built-in defaults above + a short WHY string per role (shown in `docket models`); `docket-models.json` `roles:` key (role → model ID) overlaid by `load_model_registry` (same validation as today; unknown role names ignored with a warn). Old `profiles:` key still read → migrated to nearest roles with a deprecation warn.
  - `resolve_role_model <role>` helper: policy → model; unknown role → `DEFAULT_MODEL`.
  - Tier names (economy/standard/premium) accepted everywhere a model is accepted, but **deprecated**: warn + resolve through a hidden per-preset rank list (cheapest…strongest). `get_fallback_model` walks that rank list instead of tier IDs.
  - install.sh: delete the parallel arrays; each specialist resolves through `resolve_role_model`. Preset switched before install → specialists install on that provider.
  - add.sh: default model for a new agent = `resolve_role_model <type>` (repo/task); interactive prompt shows role default + resolved model.
  - `docket models` lists ROLE | MODEL | PRICE | WHY | SOURCE (builtin/user); `docket models set <role> <model>` replaces `set <tier>`.
  - MA-7 template placeholders: `{{MODEL_ECONOMY}}` etc. replaced by role-resolved placeholders (e.g. `{{MODEL_SELF}}`, `{{MODEL_PROGRAMMER}}`…); bump `TEMPLATE_VERSION` so doctor flags drift.
- **Acceptance:** `docket models preset openai && docket install` on a clean system registers all six specialists with OpenAI models; `docket add` of a task agent defaults to a cheaper model than a repo agent; `grep -n "anthropic/claude" lib/commands/install.sh` returns nothing (pre-migration Bash check; now `src/docket/cli/_install.py`); `docket profile <id> economy` still works but prints a deprecation warning.
- **Test:** Unit: `resolve_role_model` per built-in role + unknown + user-overridden; tier-alias resolution warns and resolves; fallback walks the rank list. Integration: repo vs task agents get different default models.

#### ✅ MA-10 — Policy-following agents + auto re-resolve

- **Goal:** Agents record *intent* — follow role policy or an explicit pin — and re-resolve when policy changes; drift becomes impossible by construction.
- **Files:** `lib/helpers/json.sh` / meta schema, `lib/commands/profile.sh`, `lib/commands/models.sh` (`_models_set`, `_models_preset`), `lib/commands/add.sh`, migration in `lib/commands/doctor.sh` or `maintain check`. (pre-migration Bash; meta schema now `src/docket/core/models.py`, commands in `src/docket/cli/`/`_doctor.py`)
- **Requirements:**
  - `.docket-meta.json` gains `modelSource` (`policy` | `pinned`); `model` stays as the resolved cache. `docket profile <id> <provider/model>` → pin; `docket profile <id> default` → back to policy; bare `docket profile <id>` shows role, model, source, budget.
  - `docket models set/preset` after writing the registry: iterate all agents (specialist + project), re-resolve every `modelSource: policy` agent via `set_agent_model`, single `restart_gateway()` at the end; per-agent change summary; `audit_log` each change. Pinned agents untouched.
  - Migration: agents without `modelSource` get one inferred — model equals their role's policy model → `policy`; else `pinned`. Lazy on read + a `doctor` fix.
  - Eval harness recommendations rephrase to "change role X's model" / "pin agent Y" (no tier vocabulary).
- **Acceptance:** `docket models preset google` updates every policy-following agent in both `openclaw.json` and `.docket-meta.json` with one gateway restart; a pinned agent survives untouched; `docket profile <id>` displays source (policy/pinned).
- **Test:** Unit: `modelSource` inference both ways; integration: 2 agents (policy + pinned) → `docket models set repo <other-model>` → first updated, second untouched, audit entries present.

#### ✅ MA-11 — Specialists join the meta system (one taxonomy)

- **Goal:** `docket list`/`profile`/`doctor` manage specialists and project agents through the same metadata, making "what kinds of agents exist and what type" answerable from one command.
- **Files:** `lib/commands/install.sh` (write meta at creation), `lib/commands/list.sh`, `lib/commands/profile.sh`, `lib/commands/doctor.sh` (backfill), `lib/helpers/workspace.sh`. (pre-migration Bash; now `src/docket/cli/`/`_install.py`/`_doctor.py` + `src/docket/core/`)
- **Requirements:**
  - Specialist workspaces get `.docket-meta.json` with `kind: specialist`, `role`, `modelSource`, `model`, `sessionKey`; written by `docket install`, backfilled by `docket doctor` for existing installs.
  - Project agent meta gains `kind: project` (backfilled the same way); `type` (repo/task) unchanged and doubles as the policy role.
  - `docket list --all` (or a `KIND` column) shows: kind, role/type, model, source (policy/pinned). Specialists excluded from project-only flows (delete, wire) with a clear error.
  - `docket profile <specialist> …` works — pinning one specialist (e.g. reviewer → a stronger model) without touching the global policy.
- **Acceptance:** on an existing install, `docket doctor` backfills meta for all six specialists; `docket list --all` shows the complete taxonomy; `docket profile reviewer anthropic/claude-opus-4-6` changes only the reviewer.
- **Test:** Integration: fresh install → list shows 6 specialists with policy-derived models; doctor on a meta-less specialist workspace creates valid meta; delete/wire on a specialist errors.

**Phase 6b exit criteria:** no hardcoded model ID outside `config.sh`/`models.sh` data tables; no tier vocabulary in UX except deprecation warnings; switching provider preset retargets the whole fleet (minus pins) in one command; `docket list --all` answers "what agents exist, what kind, what model, why" at a glance; per-role defaults are the cheapest adequate model, with the WHY visible in `docket models`.

---

### PHASE 8 — Agent observability, guardrails & drift (HITL)  *(☑ COMPLETE)*

> **Source spec — goals:** every agent action leaves a durable, queryable trace (G1); destructive
> actions are gated behind explicit human approval (G2); untrusted input is guard-railed before it
> reaches an agent (G3); role success-rate degradation surfaces without manual inspection (G4) —
> all in docket's idiom (Bash + python-for-JSON, flat JSONL, systemctl, Telegram), **no new runtime
> services** (G5).
>
> **Non-goals (hold the line — reject PRs that cross these):** no external observability stack
> (no OTel collector / Prometheus / Grafana); no trace database (the filesystem **is** the store,
> queried with jq/python); no ML detection in v1 (prompt-injection & PII are heuristic/regex —
> a classifier is a deferred MAY); single-operator (no multi-tenant RBAC); no new real-time
> transport ("live" = `tail -f` + the existing Telegram channel).
>
> **The one constraint that shapes this phase:** docket is a provisioning/config CLI — it does
> **not** sit in the agent execution path. The OpenClaw daemon executes every tool call (verified:
> `workflow.sh` shells to `lobster run`; the security-gates spec already states the daemon must own
> the approval hook). So the spec splits cleanly:
>
> | Spec goal | Pure-docket? | How |
> | --------- | ------------ | --- |
> | G1 traces · G4 drift · O7 metrics | ✅ yes | docket already reads daemon `~/.openclaw/agents/<id>/sessions/*.jsonl` for cost (`_aggregate_cost`); project those into the trace format and append docket-mediated events. No daemon change. |
> | G2 destructive gate | ⚠ partly | the enforcement hook already exists, opt-in: `exec-approvals.json` + `approvals.exec` routing (`docket gates`, `security.sh`). docket owns policy/config; the **daemon owns the block**. |
> | G3 untrusted-input guard (inline) | ❌ daemon | inline `pre_input`/`pre_output` interception of a live agent needs the daemon. docket enforces at the **one ingress it owns** (the manager task queue) and files a daemon-hook request for the rest. |
>
> Work order de-risks that daemon dependency: foundations → observability (zero behavior change,
> ships first) → policy engine (pure, fully testable) → enforcement+HITL (the only hard daemon
> dependency, isolated so the rest is not held hostage) → drift (needs only traces). **Reuse, do
> not reinvent:** `audit_log`'s append + never-log-secrets idiom (`lib/helpers/audit.sh`; now `src/docket/core/audit.py`) → `trace_event`;
> `json_atomic_write` / `with_docket_lock` (`lib/helpers/json.sh`; now `src/docket/edges/store.py`); `_aggregate_cost` / `check_budget` for
> cost→trace; the `exec-approvals.json` gate (`lib/helpers/security.sh`; now `src/docket/core/security.py`) for G2; `get_tg_binding` /
> `upsert_binding` for routing; the `docket serve` background loop (`lib/commands/serve.sh`; now `src/docket/serve.py`) for the
> timeout watcher — **no new service** (G5).
>
> **Collision decisions (the spec's CLI clashes with shipped commands — resolved):**
>
> 1. **`docket audit` already exists** (renders the operator-mutation log, Phase 4). The spec's
>    "export raw trace JSONL" becomes **`docket trace export <project> [--since DATE]`**. Keep the
>    split: `audit` = "what the *operator* changed"; `trace`/`metrics` = "what the *agents* did".
> 2. **`$DOCKET_HOME` is undefined** (base is `OPENCLAW_DIR`) → add `DOCKET_HOME="${DOCKET_HOME:-$OPENCLAW_DIR}"`
>    alias so spec paths read literally. Traces at `$DOCKET_HOME/traces/<project>/<session_id>.jsonl`,
>    policies at `$DOCKET_HOME/policies/<name>.json`.
> 3. **No per-run `session_id` exists** (only the persistent session *key* `agent:<id>:<project>`)
>    → OBS-0 spike decides the derivation (deterministic from the daemon session file; docket-minted
>    fallback).
>
> Spec open questions resolved in §6 (D-6…D-8). Spec tests T1–T6 map to the OBS task `Test` fields.

#### Sub-phase 8.0 — Foundations *(no user-visible behavior)*

#### ✅ OBS-0 — `session_id` spike + base wiring

- **Why:** Everything keys off a per-run `session_id` that does not exist yet (O2/O5).
- **Files:** `lib/core/config.sh` (pre-migration Bash; config now `src/docket/config.py`).
- **Requirements:** Inspect a live `~/.openclaw/agents/<id>/sessions/` dir; confirm whether one file == one bounded run. Decide `session_id` = `s_<sha1(agent,project,basename)>` derived from the session file (no daemon change) if so; docket-minted id at dispatch/workflow-run if not. Add to `config.sh`: `DOCKET_HOME`, `TRACES_DIR`, `POLICIES_DIR` and the knobs with defaults — `SESSION_TIMEOUT`, `APPROVAL_TIMEOUT=900` (15 m, H5), `METRICS_WINDOW=50` (O8), `BASELINE_WINDOW=100`, `DRIFT_THRESHOLD=15`, `DRIFT_COOLDOWN=86400` (D1–D3). All env-overridable (CI hermeticity).
- **Acceptance:** notes doc records the verified session→run mapping + chosen `session_id` rule; new config vars resolve and are overridable.
- **Test:** Unit: each new config var has its documented default and honors an env override.

#### ✅ OBS-1 — `redact` + `trace_event` helpers

- **Why:** Single source of truth for the O3 event shape and GR8 redaction; sibling to `audit_log`.
- **Files:** new `lib/helpers/redact.sh`, new `lib/helpers/trace.sh`; source both in `bin/docket`. (pre-migration Bash; redact/trace now in `src/docket/core/trace.py`)
- **Requirements:** `redact <text>` — strip API-key/token shapes, emails, and every value in the `docket keys` registry; pure, no I/O. `trace_event <project> <session_id> <agent_role> <event_type> <payload-json> [cost_usd] [duration_ms]` — build the O3 record (UTC `ts`, all required fields), run `payload` through `redact`, validate `event_type` against the O4 closed set (`session_start, tool_call, tool_result, guardrail_check, guardrail_block, approval_requested, approval_granted, approval_denied, cost_charged, budget_warning, budget_exceeded, drift_alert, error, session_end`), append one line to `$TRACES_DIR/<project>/<session_id>.jsonl` (mkdir -p, 0600, `DOCKET_NO_TRACE=1` escape hatch). One file per session = atomic vs concurrent sessions (O1).
- **Acceptance:** event is valid one-line JSON with all required fields; unknown `event_type` rejected; a secret in `payload` is redacted on disk.
- **Test:** Unit (seeds T4): each assertion above; `redact` positive per pattern + negative on clean text.

#### Sub-phase 8.1 — Observability §5 *(G1, G5; data for G4 — ships first, zero behavior change)*

#### ✅ OBS-2 — Session lifecycle + cost folded into traces (O5, O6)

- **Why:** A trace must open with `session_start` and close with a terminal `session_end`; cost stops being a parallel system.
- **Files:** `lib/commands/team.sh` (dispatch), `lib/helpers/budget.sh`, `lib/commands/cost.sh`. (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/`)
- **Requirements:** Where docket initiates a bounded run it owns (`docket team delegate` dispatch, `docket workflow … run` if invoked through docket), emit `session_start` (first line) and `session_end` carrying `status: success|failure|aborted` (O5). In the cost path emit `cost_charged` per accounted turn (O6); in `check_budget` emit `budget_warning` (≥80%) and `budget_exceeded` (≥100%) **into the trace** instead of only flipping `paused`. Offset-track per session file (reuse `.cost-index.json` discipline) so re-runs don't double-emit.
- **Acceptance:** a run produces `session_start`…`session_end`; a costed session emits `cost_charged`; crossing the cap emits exactly one `budget_exceeded`.
- **Test:** Integration: fake sessions dir → expected event sequence; cap crossing emits one `budget_exceeded`.

#### ✅ OBS-3 — Ingestion bridge + timeout sweep (O5)

- **Why:** Most runs are started by the daemon, not docket — G1 must cover them without a daemon change.
- **Files:** `lib/helpers/trace.sh` (`trace_ingest <project>`), `lib/commands/serve.sh` (sweep in the existing loop). (pre-migration Bash; now `src/docket/core/trace.py` + `src/docket/serve.py`)
- **Requirements:** `trace_ingest` reads the project's agents' `sessions/*.jsonl`, projects each into trace events (`tool_call`/`tool_result` where the daemon log distinguishes them, else a coarse `tool_call` per turn), idempotently (offset-tracked), redacted. Document the fidelity ceiling (reconstructed from logs; richer events are a daemon enhancement). The `docket serve` loop marks any trace with no `session_end` after `SESSION_TIMEOUT` as `status: aborted` (synthetic `session_end`) — no new service (G5).
- **Acceptance:** ingesting a sample sessions dir yields a valid trace per session; a stale open trace is coerced to `aborted` by the sweep.
- **Test:** Unit: ingestion is idempotent (second run adds nothing); sweep writes exactly one synthetic `session_end`.

#### ✅ OBS-4 — `docket trace` + `docket metrics` (O7, O8, O9)

- **Why:** The CLI surface that makes traces queryable and metrics derivable from traces alone (NG1/NG2).
- **Files:** new `lib/commands/trace.sh` (`cmd_trace`), new `lib/commands/metrics.sh` (`cmd_metrics`); wire both into `lib/core/router.sh`, `bin/docket` (explicit `source`, not a glob), `lib/commands/help.sh`. (pre-migration Bash; now `src/docket/cli/_trace.py`/`_metrics.py`, the `src/docket/__main__.py` command map, and `src/docket/cli/_help.py`)
- **Requirements:** `docket trace <session_id>` renders one trace human-readable (ts · event_type · summary · cost/duration, colorized via `output.sh`); `docket trace tail <project>` follows the most-recent session (`tail -f`); `docket trace export <project> [--since DATE]` is raw JSONL passthrough filtered by `ts` (the §2.1 accountability artifact). `docket metrics [--role R] [--project P] [--window N]` computes over the rolling window (default `METRICS_WINDOW=50` terminal sessions): success rate (`session_end{success}` / terminal), mean & p95 `duration_ms`, total & mean `cost_usd`, guardrail trip count by action — pure python-over-JSONL, no store.
- **Acceptance:** `docket trace <id>` renders; `trace tail` follows live; `trace export --since` filters; `docket metrics` returns correct numbers on a synthetic trace set; `scripts/metrics.sh --check` passes (README command count bumped).
- **Test:** Unit: synthetic traces → known success rate, p95, cost, trip counts (T-style).

**Sub-phase 8.1 exit:** full agent-action visibility from flat JSONL; `trace`/`metrics`/`trace export` ship; cost lives in the trace. Zero behavior change. Flip the new spec file's Status → Implemented (Phase 1). **Shippable.**

#### Sub-phase 8.2a — Policy engine §6 *(G2/G3 logic, no enforcement — pure docket, fully testable)*

#### ✅ OBS-5 — Policy schema, loader & most-restrictive-wins evaluator (GR1–GR6)

- **Why:** Guardrails must be declarative flat files, not hardcoded (GR1); the evaluator is pure and testable before any daemon work.
- **Files:** new `lib/helpers/policy.sh` (pre-migration Bash; now `src/docket/core/policy.py`/`security.py`).
- **Requirements:** Load `$POLICIES_DIR/*.json`; each policy = `id`, `applies_to[]` (roles + `*`, GR2), `hook` ∈ {pre_input,pre_tool_call,pre_output} (GR3), `match` ({type:"regex",pattern} — leave `type` open for a future `classifier`, F1), `action` ∈ {allow,warn,redact,require_approval,block} (GR4), `message`. Validate on load (bad policy = loud error, not silent skip). `policy_eval <role> <hook> <text>` returns the single winning action by `block > require_approval > redact > warn > allow` (GR5). Every eval emits `guardrail_check`; any non-allow additionally emits the matching event (`guardrail_block`/`approval_requested`/…) via `trace_event` (GR6).
- **Acceptance:** overlapping policies resolve to the most restrictive; every eval leaves a `guardrail_check` in the trace.
- **Test:** Unit — overlapping-policy resolution (**T2**); malformed policy errors on load.

#### ✅ OBS-6 — Baseline policies + `docket policies` command (GR7, GR9)

- **Why:** Ship the required default policy set and a way to author/inspect/dry-run it.
- **Files:** new `lib/templates/policies/*.json` (baselines), new `lib/commands/policies.sh` (`cmd_policies`); wire into router/bin/help; install via `docket policies init` (and optionally `docket install`). (pre-migration Bash; now `src/docket/templates/` + `src/docket/cli/_policies.py`)
- **Requirements:** Baselines — `block-destructive.json` (pre_tool_call, require_approval: `rm -rf`, `git push --force`, `DROP|TRUNCATE`, `systemctl stop|disable`, mass deletion, credential-file writes — aligned with the `_GATES_SAFE_BINS` exclusions); `prompt-injection.json` (pre_input, warn by default / block configurable: instruction-override + exfiltration phrasings) — **untrusted inputs only (GR9)**; `secret-pii-redact.json` (pre_output, redact: keys, tokens, emails, key-registry values — wired to `redact`, GR8). `docket policies`: `list`, `show <id>`, `init` (install baselines), `test <hook> <role> "<text>"` (dry-run the evaluator).
- **Acceptance:** each baseline trips on a positive case and passes a negative; `policies test` dry-runs without side effects.
- **Test:** Unit per baseline — positive trips, negative passes (**T1**).

#### ✅ OBS-7 — Trust boundary on the task queue (GR9; answers spec Q2 / D-7)

- **Why:** Injection heuristics must run on untrusted input only; the queue is the ingress docket owns.
- **Files:** `lib/commands/team.sh` (TASK_LIST.json schema). (pre-migration Bash; now `src/docket/cli/`)
- **Requirements:** Add `source` ∈ {operator,telegram,api,fetched} to each task. `operator` = trusted → pre_input/injection policies skip it; everything else = untrusted → they run. `docket team delegate` defaults `source=operator`; the field is settable for ingested tasks.
- **Acceptance:** an `operator` task bypasses injection policies; a `fetched` task is evaluated.
- **Test:** Unit: schema accepts `source`; evaluator gating honors trusted vs untrusted.

#### Sub-phase 8.2b — Enforcement + HITL §6/§7 *(G2, G3 ingress — ⚠ the only hard daemon dependency)*

#### ✅ OBS-8 — pre_input enforcement at the queue + DAEMON gate binding

- **Why:** Deliver G3 at the ingress docket controls now; map G2 onto the daemon hook that already exists.
- **Files:** `lib/commands/team.sh`, `lib/helpers/security.sh` (translate policy → `exec-approvals.json`). Record what is native vs pending inline in this task. (pre-migration Bash; now `src/docket/cli/` + `src/docket/core/security.py`)
- **Requirements:** In `docket team delegate`, for untrusted `source` run `policy_eval <role> pre_input <task-text>`: `block` → reject; `warn` → annotate; `require_approval` → HITL (OBS-10). **DAEMON:** translate the `block-destructive` policy into `apply_exec_approval_gates` allowlist/deny + `approvals.exec` routing (reuse the opt-in mechanism). Where exec-approval is too coarse (regex on full command; pre_output redaction), file an upstream daemon-hook request and document the gap. Do **not** claim inline `pre_output` redaction until the daemon supports it — until then pre_output redaction applies to docket-written traces + outbound Telegram only (still satisfies GR8 for those sinks).
- **Acceptance:** an untrusted task matching a `block` policy is rejected before dispatch; a destructive command maps to the daemon gate; the feasibility doc states precisely what is enforced natively vs pending.
- **Test:** Unit: queue rejects a `block` match; integration: gate config written matches the policy.

#### ✅ OBS-9 — Approval store + Telegram send (H1, H2; GR8)

- **Why:** HITL needs a durable pending-approval record and an outbound channel — docket has no send function today.
- **Files:** new `lib/helpers/approval.sh`, new `lib/helpers/telegram.sh`. (pre-migration Bash; approval now `src/docket/core/approval.py`, Telegram routing via the ACL `src/docket/edges/adapters/openclaw.py`)
- **Requirements:** `approval_create <project> <role> <action>` mints an opaque `approval_token`, persists `{token,project,role,action,state:pending,created}` to `$DOCKET_HOME/approvals/<token>.json` (atomic, 0600), emits `approval_requested` + a pause marker (H1/H2). `tg_send <agent_id> <text>` resolves `get_tg_binding`, POSTs via bot `sendMessage` (curl), **always `redact` first** (GR8); message carries project, role, redacted action, token. If no send capability is configured, degrade to CLI-only approval — never hard-fail.
- **Acceptance:** an approval persists with state `pending` and an opaque token; the Telegram message contains no secret; missing bot config degrades gracefully.
- **Test:** Unit: token minted + persisted; **T4** — secret reaches neither the trace nor a captured `tg_send` payload.

#### ✅ OBS-10 — Grant/deny + fail-safe timeout (H3, H4, H5)

- **Why:** Approvals must be grantable two ways, and silence must never authorize.
- **Files:** new `lib/commands/approve.sh` + `lib/commands/deny.sh` (wire into router/bin/help), `lib/commands/serve.sh` (timeout watcher). (pre-migration Bash; now `src/docket/cli/_approve.py`/`_deny.py` + `src/docket/serve.py`)
- **Requirements:** CLI (authoritative): `docket approve <token>` / `docket deny <token>` → validate, transition state, emit `approval_granted` / `approval_denied` (H4), write resume/abort marker. Telegram reply `approve <token>`/`deny <token>` is **DAEMON**-routed — until the daemon routes replies to docket, document Telegram as notify-only and CLI as the grant path. Fail-safe: the `docket serve` watcher expires any `pending` approval older than `APPROVAL_TIMEOUT` → state `expired`, treated as **denied** (emit `approval_denied`) (H5; G5 — reuse serve loop).
- **Acceptance:** granted resumes; denied aborts; a pending approval past timeout becomes denied.
- **Test:** Integration — granted / denied / timeout-defaults-to-denied (**T3**).

#### Sub-phase 8.3 — Drift §8 *(G4 — needs only traces)*

#### ✅ OBS-11 — Baseline tracker, drift alert & cooldown (D1–D3)

- **Why:** Role degradation must self-surface, computed from traces with no extra store (NG2).
- **Files:** new `lib/helpers/drift.sh`; hooked from wherever `session_end` is written (OBS-2 + serve sweep); surfaced in `lib/commands/metrics.sh` and `serve` `/status.json`. (pre-migration Bash; now `src/docket/core/` + `src/docket/cli/_metrics.py` + `src/docket/serve.py`)
- **Requirements:** Per `agent_role`, baseline success rate over the trailing `BASELINE_WINDOW=100` terminal sessions (D1). After each `session_end`, compare the current rolling window (O8) to baseline; if current < baseline − `DRIFT_THRESHOLD` (15 pp), emit `drift_alert` (naming the role + before/after rates) and `tg_send` a notification (D2). Rate-limit to ≤1 alert per role per `DRIFT_COOLDOWN=24h` (D3; persist last-alert ts per role). Aborted sessions **count** against success rate (D-6).
- **Acceptance:** synthetic traces crossing the threshold emit exactly one alert; a second within cooldown is suppressed.
- **Test:** Integration — threshold crossing → one alert + cooldown suppression (**T5**).

#### ✅ OBS-12 — Spec, CI suite & docs (T6, G5 truth pass)

- **Why:** The repo gates on spec coverage + metrics counts + ShellCheck; the work isn't done until CI proves it.
- **Files:** new `specs/functional/observability-guardrails.spec.md`, [tests/run-all-tests.sh](tests/run-all-tests.sh), [.github/workflows/ci.yml](.github/workflows/ci.yml), `scripts/metrics.sh`, README + `docs/` + `lib/commands/help.sh` (now `src/docket/cli/_help.py`) + [CLAUDE.md](CLAUDE.md).
- **Requirements:** Commit the spec (hard gate — `scripts/validate-specs.sh` blocks on missing coverage), Status flipped per sub-phase. Add the guardrail + observability suites to `run-all-tests.sh`; CI runs them on every push/PR (**T6**); keep `-S warning` ShellCheck clean. Update `scripts/metrics.sh` expected counts + README for the new commands (`trace`, `metrics`, `policies`, `approve`, `deny`). Document the new commands honestly, including the daemon-dependency caveat for inline pre_tool_call/pre_output and Telegram reply-routing.
- **Acceptance:** CI green with the new suites; `validate-specs.sh` + `metrics.sh --check` pass; docs name what is enforced natively vs pending daemon support.
- **Test:** the CI run itself (**T6**); `grep` audit that docs don't overclaim inline enforcement.

**Phase 8 exit criteria:** every agent action docket can observe leaves a queryable JSONL trace; `docket trace`/`metrics`/`trace export` work over the filesystem store (no DB, no collector); destructive commands route through the opt-in daemon gate and `require_approval` policies pause behind a token that fails closed on timeout; untrusted task input is guard-railed at the queue; role success-rate drift self-surfaces with cooldowned alerts; the daemon-dependent items (inline pre_tool_call/pre_output, Telegram reply-routing) are documented as such, not overclaimed; full suite green in CI.

---

### PHASE 9 — Contract integrity: close the spec↔runtime gap (de-ceremony)  *(☑ COMPLETE)*

> **Audit verdict (blunt):** docket's contract discipline is **partly ceremonial**. The `specs/`
> tree is well-authored and CI runs `validate-specs.sh` + `spec-coverage.sh` on every push — but
> those tools validate *markdown structure and file presence*, not *that the running code matches
> the contract*. The real schema in this project — the dual-source agent config — is **hand-
> duplicated across 6+ command files with no single definition and almost no drift detection**.
> Several spec promises are already lies the toolchain can't catch. This phase makes the contracts
> load-bearing or strips the parts that only perform rigor.
>
> **Scope correction (what the generic CDD/SDD audit asked vs. what docket is):** docket is a pure
> Bash CLI. There is **no** OpenAPI/Swagger/AsyncAPI file, **no** code-generation toolchain
> (datamodel-codegen / openapi-generator / stainless), and **no** database or migrations
> (Alembic/Flyway/Knex/Liquibase) — verified by `git ls-files`. So the audit's "dead codegen loop"
> (§1) and "migration rigor" (§3) pillars are **N/A by construction** — there is nothing to be
> hollow. The audit's *spirit* maps onto docket's three actual contracts: (a) the markdown specs
> under `specs/`, (b) the dual-source config that "must stay in sync" — each agent's
> `.docket-meta.json` ↔ the daemon's `openclaw.json`, and (c) the `--json` / HTTP output shapes.
> Findings below are against those.
>
> **Verified findings (file:line):**
>
> | # | Finding | Evidence |
> | - | ------- | -------- |
> | F1 | **`--json` wrapper the spec promises is emitted by zero commands.** The spec defines a `{success, data, error, timestamp, version}` envelope; no `cmd_*` ever produces it — each hand-assembles its own ad-hoc shape inline in a python heredoc. | promised: [specs/api/cli-interface.spec.md:340-350](specs/api/cli-interface.spec.md#L340); `grep -rn '"success"' lib/commands/` → **0 hits** (pre-migration Bash; commands now `src/docket/cli/`) |
> | F2 | **Drift detection covers one field.** `docket doctor` compares only `model` (meta vs openclaw). `budgetUsd`, `paused`, `pausedReason`, `modelSource`, `name`, `stack` can diverge silently. | `doctor.sh:187-197` (json path), `doctor.sh:515-526` (human path) (pre-migration Bash; now `src/docket/cli/_doctor.py`) |
> | F3 | **No schema; no validation on write.** `_meta_set` writes `data[field]=value` with zero type/enum checks — `meta_set <id> budgetUsd "not-a-number"` succeeds and is later swallowed by a `try/float()` with no error. The field list lives only in prose. | `lib/helpers/json.sh` `_meta_set` (now `src/docket/edges/store.py` + `src/docket/core/models.py`); schema prose only in [specs/data/docket-meta.spec.md](specs/data/docket-meta.spec.md) |
> | F4 | **Coverage % is cosmetic.** `spec-coverage.sh` scores a command "covered" if a markdown heading mentions it or a same-named file exists — it never checks args/flags/return codes against the code. | [scripts/spec-coverage.sh:19-45](scripts/spec-coverage.sh#L19) |
> | F5 | **Spec registry is stale & incomplete.** `gates`, `audit`, `eval`, `models`, `completions` are routed but absent from the spec's command registry; `input-validation.spec.md` still lists removed `reset`/`repair` as live; `profile` spec documents `economy/standard/premium` as args though tiers are deprecated. Nothing cross-checks `router.sh` against the spec. | router arms in `lib/core/router.sh` (now the command map in `src/docket/__main__.py`) vs [specs/api/cli-interface.spec.md](specs/api/cli-interface.spec.md); [specs/validation/input-validation.spec.md:19](specs/validation/input-validation.spec.md#L19) |
>
> **Principle for this phase:** every fix either makes a contract *mechanically enforced* (CI fails
> on divergence, or the runtime refuses bad data) or *deletes the ceremony* (fix the spec to match
> reality, drop a misleading metric). No new prose that code can ignore.

#### ✅ CDD-1 — Single source of truth for the agent schema (kills the hand-duplication)

- **Why:** F2/F3 — the `.docket-meta.json` field set is redefined implicitly in every command that touches it; nothing declares it once.
- **Files:** new `lib/core/schema.sh` (or a `declare -A AGENT_FIELDS` block in `lib/core/config.sh`); consumed by `lib/helpers/json.sh`, `lib/commands/doctor.sh`; cross-checked against [specs/data/docket-meta.spec.md](specs/data/docket-meta.spec.md). (pre-migration Bash; the schema now lives in `src/docket/core/models.py`, consumed by `src/docket/edges/store.py` + `src/docket/cli/_doctor.py`)
- **Requirements:** Declare each field once with: name, type (`string|number|enum|bool`), enum values (e.g. `modelSource ∈ {policy,pinned}`, `kind ∈ {project,specialist}`), and a **sync class** — `synced` (mirrored to `openclaw.json`) vs `local` (docket-only). This table is the authority `validate_model`/`meta_set`/`doctor` all read. A CI test asserts the table and the `## Schema` section of `docket-meta.spec.md` list the same fields (spec can't drift from the table).
- **Acceptance:** adding a field to the spec but not the table (or vice-versa) fails a unit test; `doctor` and `meta_set` enumerate fields from the table, not from inline literals.
- **Test:** Unit: table↔spec field-set equality; type/enum/sync-class present for every field.

#### ✅ CDD-2 — Validated `meta_set` (reject bad writes at the boundary)

- **Why:** F3 — silent acceptance of malformed values is the kind of "looks fine until it isn't" bug specs are supposed to prevent.
- **Files:** `lib/helpers/json.sh` (`_meta_set`). (pre-migration Bash; now `src/docket/edges/store.py` + `src/docket/core/models.py` validation)
- **Requirements:** Before writing, look the field up in the CDD-1 table: unknown field → `error` (typo guard); type mismatch (`budgetUsd` non-numeric or negative, `paused` non-bool, `modelSource` outside its enum) → `error` naming the field and the rule. Keep `DOCKET_NO_*` escape hatches consistent with existing helpers. Do **not** loosen the atomic-write/lock path.
- **Acceptance:** `meta_set x budgetUsd not-a-number` and `meta_set x bugdetUsd 5` (typo) both fail loudly; valid writes unchanged.
- **Test:** Unit: each invalid type/enum/unknown-field rejected; valid round-trips.

#### ✅ CDD-3 — Sync completeness + full-field drift in `doctor`

- **Why:** F2 — drift detection that checks 1 of ~12 fields gives false confidence; the spec implies more is synced than is.
- **Files:** `lib/commands/doctor.sh`, `lib/helpers/session.sh`/`lib/helpers/json.sh` (sync writers), [specs/data/docket-meta.spec.md](specs/data/docket-meta.spec.md). (pre-migration Bash; now `src/docket/cli/_doctor.py` + `src/docket/core/sync.py` + `src/docket/edges/store.py`)
- **Requirements:** Using CDD-1's sync class: `doctor` compares **every `synced` field** (meta ↔ openclaw), not just `model`, and reports each divergence; `local` fields are explicitly documented as docket-only in the spec (so no one expects them in `openclaw.json`). Decide and record per field whether it should be `synced` or `local` (D-9). `--fix` re-syncs from the documented source of truth.
- **Acceptance:** mutating any `synced` field in one source surfaces in `docket doctor`; `local` fields are labeled and not flagged.
- **Test:** Integration: extend the existing drift test (P0-2 pattern) to a non-`model` synced field.

#### ✅ CDD-4 — Resolve the `--json` output contract (F1)

- **Why:** A documented envelope that nothing emits is a lie in the API spec; consumers parse undocumented ad-hoc shapes.
- **Files:** [specs/api/cli-interface.spec.md](specs/api/cli-interface.spec.md), the `--json` emitters (`list.sh`, `cost.sh`, `info.sh`, `doctor.sh`, `snapshot.sh` — pre-migration Bash; now `src/docket/cli/`), `lib/commands/serve.sh` (`/status.json`, `/metrics`, `/health`; now `src/docket/serve.py`).
- **Requirements:** Pick one (D-10): **(A)** adopt the `{data, …}` envelope across all read commands, or **(B)** delete the unused envelope from the spec and instead document each command's *actual* shape in `specs/data/`. Either way: pin every output shape in a spec, enforce key-name consistency (`costUsd`/`budgetUsd` camelCase everywhere — no `cost_usd` in JSON), and add a test that each `--json` command's keys match its documented shape.
- **Acceptance:** spec and emitted JSON agree for every read command; a renamed field breaks a test.
- **Test:** Unit/integration: `<cmd> --json | jq` keys equal the documented set; naming-consistency assertion across commands.

#### ✅ CDD-5 — Mechanical spec↔code linter (replace the cosmetic coverage %)

- **Why:** F4/F5 — CI should fail when the command surface and the spec disagree, not report a misleading 92–100%.
- **Files:** rewrite/extend [scripts/spec-coverage.sh](scripts/spec-coverage.sh); wire as a **blocking** step in [.github/workflows/ci.yml](.github/workflows/ci.yml).
- **Requirements:** Extract the real command set from `router.sh` `case` arms (+ `cmd_*` functions); extract the documented command set from `specs/api/cli-interface.spec.md`. Fail on either-way mismatch: a routed command with no spec entry (catches `gates`/`audit`/`eval`/`models`/`completions`), or a spec'd command not routed (catches stale `reset`/`repair`). Drop the percentage; emit a concrete diff. (Optional stretch: assert documented flags exist in the handler.)
- **Acceptance:** today's repo makes this linter **red** (it surfaces the 5 missing + the stale refs); after CDD-6 it's green; adding a command without a spec turns it red again.
- **Test:** the linter is the test; a fixture proves it fails on an injected mismatch.

#### ✅ CDD-6 — De-stale the specs (one-time truth pass)

- **Why:** F5 — make the specs match the shipped CLI so CDD-5 can go green and stay green.
- **Files:** [specs/api/cli-interface.spec.md](specs/api/cli-interface.spec.md) (add `gates`, `audit`, `eval`, `models`, `completions`; correct `profile` args to model-id/`default`, drop tier-as-arg), [specs/validation/input-validation.spec.md](specs/validation/input-validation.spec.md) (remove `reset`/`repair` from "Used By"), any functional spec describing removed behavior.
- **Acceptance:** `grep` audit shows no removed command described as live; CDD-5 linter passes; `validate-specs.sh` stays green.
- **Test:** CDD-5 linter green; spec-section structure intact.

**Phase 9 exit criteria:** the `.docket-meta.json` schema is declared **once** and drives validation + drift; `meta_set` refuses malformed/unknown fields; `docket doctor` detects drift on every synced field (and the spec is honest about local-only ones); every `--json`/HTTP shape is documented and test-pinned with consistent naming; CI **fails** when `router.sh` and the spec registry disagree (no more cosmetic coverage %); no spec describes a removed command as live. Net: the contracts that remain are enforced; the ones that only performed rigor are gone.

---

### PHASE 10 — Agent architecture: project pods (scope ≠ role ≠ lifecycle)  *(☑ COMPLETE)*

> **Executable task board:** [TODO.md](TODO.md) (self-contained
> cards, claimable by separate agents). **Rationale long-form:** `internal-docs/agent-structure-analysis.md`.
> This section is the authoritative plan; the task board is the how/claim/status surface.
>
> **The problem (three structural defects in today's agent model).** docket has two agent kinds that
> overlap and contradict:
>
> - **Project agents** (`docket add`) — one per codebase, persistent, full read/write/edit on their
>   own repo. Template says it "knows this project deeply" **and** "Delegate: implementation → programmer."
> - **Specialist agents** (`docket install`) — manager, programmer, reviewer, tester, knowledge,
>   security ([config.py:45-46](src/docket/config.py#L45-L46)) — single **shared** instances at
>   `~/.openclaw/workspaces/<role>/`, used by every project.
>
> | # | Defect | Evidence |
> | - | ------ | -------- |
> | A | **Two doers, neither complete.** The repo project agent has write access + deep context but is told to delegate; the shared programmer "implements an exact <500-tok brief" in a sandbox with **no git** and "does NOT investigate or design." The knower can't build; the builder doesn't know. | `templates/docket-programmer.md`; repo SOUL at [cli/__init__.py:533-563](src/docket/cli/__init__.py#L533) |
> | B | **Shared specialists break the core isolation guarantee.** docket's headline is context isolation via session keys (`agent:<id>:<project>`, [cli/__init__.py:702](src/docket/cli/__init__.py#L702)). But specialists are **singletons with hardcoded keys** (`specialist:<role>:…`, `manager:atlas:coordination`). One programmer instance serves project A and B in the *same* session — the exact cross-project contamination the product exists to prevent. | `_provision_specialists` writes one shared workspace per role ([cli/_install.py:288-325](src/docket/cli/_install.py#L288)) |
> | C | **"Delegation" is instruction-only; no runtime exists.** `TASK_LIST.json` is written *only* by CLI commands; no code makes the manager read it, route work, or message specialists. The "team" is markdown hoping agents talk over Telegram. | `team delegate/queue/done` are the only `TASK_LIST.json` writers ([cli/__init__.py](src/docket/cli/__init__.py)); `grep TASK_LIST templates/` → nothing |
>
> **Root cause:** the design flattens **three independent dimensions** into one "agent type" —
> **role** (what it does) · **scope** (whose data it may see) · **lifecycle** (persistent vs per-task).
> "Programmer" is modeled as a global persistent singleton when it is really a *role* that should be
> instantiated *per project, per task*. The role *definitions* are good; their *deployment* is wrong.
>
> **Target structure — pods (one team per product, roles inside, a small shared platform layer):**
>
> ```text
> ORG layer — shared by design, persistent, FEW (read-only / advisory)
>   • Portfolio Manager  — cross-project queue/budgets/priorities (sees metadata, not code)   [optional]
>   • Security Auditor    — cross-cutting, read-only; WANTS the global view
>   • Knowledge/Librarian — shared standards, templates, post-mortems
>
> PER PRODUCT — one isolated pod, session-scoped to agent:<id>:<project>
>   • Lead / Orchestrator (persistent, 1)  — owns context+memory+human comms; decomposes & dispatches; NEVER edits code
>   └ Workers (EPHEMERAL — spawned per task, inherit the pod's session key)
>       • Implementer (was: programmer) — runs INSIDE the product workspace, so it knows the code
>       • Reviewer    — read-only veto, scoped to the diff
>       • Tester      — behaviour-only PASS/FAIL
> ```
>
> **Mapping from today's six specialists:** security + knowledge → stay **org-scoped persistent**
> (cross-cutting is correct); programmer/reviewer/tester → **project-scoped ephemeral roles** (same
> templates, different deployment); manager → splits into a **per-product Lead** (the common case) +
> an optional single **org Portfolio Manager**.
>
> **The constraint that shapes this phase (same as Phase 8):** docket is **not in the agent execution
> path** — the daemon spawns and runs agents. So the work splits:
>
> | Capability | Pure-docket? | How |
> | ---------- | ------------ | --- |
> | Scope axis on the taxonomy (org vs project) | ✅ yes | `AgentMeta` field + install/add provisioning + `list`/`doctor` |
> | Project-scoped role workers inherit the pod session key | ✅ yes | workspace provisioning + templates → **fixes Defect B** |
> | Lead merges manager; Implementer runs in the workspace | ✅ yes | templates + provisioning → **fixes Defect A** |
> | Ephemeral per-task spawning + runtime dispatch | ❌ daemon | needs OpenClaw sub-agent spawn / per-task session override → spike (AA-0), gated (AA-7) → **Defect C** |
>
> Work order de-risks the daemon dependency: **spike → taxonomy → provisioning (ships the isolation
> fix) → Lead/Implementer roles → org agents → dispatch (daemon-gated, isolated last) → list/doctor →
> docs.** Reuse, don't reinvent: the `AgentMeta`/`AgentKind` model, the `kind`/`role`/`modelSource`
> precedent, `core/sync.py`, `_create_workspace`, the role→model policy, and the Phase-8 trace for
> dispatch events.

#### 🟡 AA-0 — Spike: daemon capabilities for pods & ephemeral workers  *(blocking; do first)*

- **Why:** AA-7 (real dispatch) and the ephemeral-worker model hinge on what the OpenClaw daemon can do; everything else must not assume a capability that isn't there (the Defect-C trap that produced today's instruction-only "delegation").
- **Files:** scratch findings doc `internal-docs/POD-DAEMON-NOTES.md` (not shipped in the wheel).
- **Requirements:** Against `openclaw --help`, the live `~/.openclaw/openclaw.json`, and <https://docs.openclaw.ai/>, answer with evidence: (a) can the daemon **spawn a sub-agent / ephemeral agent** on demand, or are all agents statically registered? (b) can one agent **send a message / dispatch work** to another through the daemon (not just Telegram), and is that programmable from docket? (c) can a single registered role run **multiple concurrent isolated sessions** keyed by different session keys (the multi-tenant programmer question), or is session state per-agent-singleton? (d) how is a **per-task session** created/torn down? Record each as supported / not-supported / unknown, with the exact config or CLI that enables it. Explicitly decide the AA-7 path: **real daemon dispatch** vs **operator-driven queue** (documented honestly).
- **Acceptance:** `POD-DAEMON-NOTES.md` exists with a verified capability table and a one-line AA-7 verdict; at least one claim proven against the live daemon (e.g. a second session key on one role accepted, or shown impossible).
- **Test:** N/A (research). The doc is the deliverable; AA-2…AA-7 cite it.

#### 🟡 AA-1 — Add the `scope` axis to the taxonomy (the root fix)

- **Why:** Defect root cause — scope is conflated with role/kind. Make scope a first-class, validated field so "shared vs project-isolated" is data, not convention.
- **Files:** [src/docket/core/models.py](src/docket/core/models.py) (`AgentScope` enum + `scope` field on `AgentMeta`, alias-preserving; `AgentKind`/`ModelSource` are the precedent at lines 14/24/29), [src/docket/cli/_install.py](src/docket/cli/_install.py) + [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (write it at creation), `specs/data/docket-meta.spec.md` (schema doc — keep spec↔model in sync per Phase 9 CDD-1).
- **Requirements:** `scope ∈ {org, project}` (default `project` for project agents; `org` for shared specialists). Validation rejects unknown values. Backfill rule for existing installs (lazy on read + a `doctor` fix): `kind==specialist` → derive from the role table in AA-2; `kind==project` → `project`. Document the field as `local` (docket-only) sync-class. Do **not** remove `kind`/`role` — `scope` is orthogonal to both.
- **Acceptance:** a new agent's `.docket-meta.json` carries a valid `scope`; an unknown `scope` is rejected at the boundary; existing metas without `scope` resolve to a correct value on read.
- **Test:** pytest: model round-trip + validation error for bad scope; backfill inference both ways.

#### 🟡 AA-2 — Reclassify the six specialists: org vs project-role

- **Why:** Fix Defect B at the source — only genuinely cross-cutting roles stay shared singletons.
- **Files:** [src/docket/config.py](src/docket/config.py) (`SPECIALIST_ROLES`/`SPECIALIST_ORDER` at lines 45-77 → split into `ORG_ROLES = {security, knowledge}` + `PROJECT_ROLES = {programmer, reviewer, tester}`; `manager` handled by AA-5/AA-6), [src/docket/cli/_install.py](src/docket/cli/_install.py) (`_provision_specialists` installs only the org set as shared workspaces).
- **Requirements:** `docket install` provisions **only** org-scoped agents (security, knowledge, + optional Portfolio Manager per AA-6) as shared singletons with `scope: org`. programmer/reviewer/tester are **no longer installed as global workspaces** — they become per-pod role templates instantiated by AA-3/AA-4. Migration: an existing install keeps its old specialist workspaces working (don't break running fleets) but `doctor` flags the project-roles as "to be re-scoped into pods" with guidance. Preserve the role→model policy mapping for every role regardless of scope.
- **Acceptance:** fresh `docket install` registers the org set only; `docket list --all` shows them with `scope: org`; no global `programmer`/`reviewer`/`tester` singleton is created on a clean install.
- **Test:** pytest/integration: clean install → org roles present, project-roles absent as singletons; existing-install migration path doesn't delete live workspaces.

#### 🟡 AA-3 — Pod provisioning in `docket add` + a configurable pod (decided 2026-06-23)

- **Why:** A project must come up as an isolated pod, not a lone agent told to delegate to a global singleton. But a full 4-agent pod is overkill (and over-cost) for many projects — so the pod is **configurable with a lean default**.
- **Pod composition (the options, made explicit):**
  - **Default (`docket add <project>`):** a **2-agent lean pod** — **Lead + Implementer**. The Lead orchestrates; the Implementer runs *in* the project workspace and writes code. This is enough to be useful and cheap.
  - **Extend later (`docket pod <project> add <role> [--count N]`):** add **Reviewer**, **Tester**, or **another Implementer** to an existing pod with one clear command. Roles may be **duplicated** — e.g. two Implementers — provisioned as indexed agent ids (`<project>-implementer`, `<project>-implementer-2`).
  - **Inspect (`docket pod <project>`):** show the pod's members, roles, models, scope.
  - **Opt-in full pod:** `docket add <project> --pod full` (or `--with reviewer,tester`) provisions the 4-role pod up front for those who want it.
- **Files:** [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (`cmd_add` / `_create_workspace`, ~516-770; new `pod` command group), [src/docket/edges/adapters/openclaw.py](src/docket/edges/adapters/openclaw.py) (provision/teardown via `openclaw agents add --workspace` / `agents delete`), [src/docket/core/sync.py](src/docket/core/sync.py).
- **Requirements:** Per the AA-0 verdict, provision each pod member as a **distinct registered agent** (own workspace — the real isolation primitive), id `<project>-<role>[-N]`, `kind: project`, `scope: project`, `role: <lead|implementer|reviewer|tester>`, model from the role→model policy, session key in the `agent:<project>:…` namespace. The load-bearing guarantee: **no worker agent serves two projects.** One gateway restart per command. `docket delete <project>` tears down **every** pod member; `docket pod <project> remove <member-id>` removes one. Adding a role requires its template (AA-4/AA-5) to exist — refuse with a clear message otherwise.
- **Acceptance:** `docket add demo` yields a 2-member pod (`demo-lead`, `demo-implementer`), each `scope: project`, own workspace; `docket pod demo add implementer` creates `demo-implementer-2`; `docket pod demo add reviewer` adds a reviewer; `docket pod demo` lists them; `docket delete demo` removes all, both config sources clean.
- **Test:** integration: default add → 2 members with correct ids/scope/role + distinct workspaces; `pod add` (incl. duplicate implementer → indexed id); `pod remove`; delete → none remain, no orphan bindings.

#### 🟡 AA-4 — Project-scoped role templates (Implementer knows the code)

- **Why:** Fix Defect A — the role that implements must run *in* the project workspace with real context, not from a 500-token brief in a sandbox.
- **Files:** `src/docket/templates/docket-programmer.md` → an in-pod **Implementer** template; `docket-reviewer.md`, `docket-tester.md` re-scoped; the workspace-emission path in `_create_workspace`.
- **Requirements:** Re-author the three role templates as **pod members**: identity bound to the project + pod session key (inherit the workspace's `SOUL.md` context, not a compressed brief); the Implementer has read/write/edit on the project codebase (it *is* in the workspace) and the agreed git posture; Reviewer stays read-only veto on the diff; Tester stays behaviour-only PASS/FAIL. Remove the "shared specialist / `specialist:<role>:…` key" language and the sandbox-only/no-context framing. Bump the template version so `doctor` flags existing agents for `maintain rebuild`.
- **Acceptance:** a freshly added pod's role files reference the project + pod session key and contain **zero** "shared specialist" / hardcoded-`specialist:` language; the Implementer template grants in-workspace code access.
- **Test:** pytest: render each role template into a pod → asserts session-key/scope substitution and absence of the old singleton phrasing.

#### 🟡 AA-5 — The Lead role (merge project-agent + manager)

- **Why:** Collapse the "two doers" into one clear orchestrator per pod; the global Atlas manager becomes a per-product Lead.
- **Files:** `src/docket/templates/docket-manager.md` → reworked into a per-pod **Lead** template; project repo/task SOUL/AGENTS emission in [cli/__init__.py:533-643](src/docket/cli/__init__.py#L533).
- **Requirements:** The Lead is the persistent, project-scoped orchestrator: owns the pod's context/memory and human comms, decomposes work, dispatches to pod workers, and **never edits code** (keep the manager's no-edit/HITL constraints). It replaces the standalone "project agent that may implement OR delegate" — implementation is always a worker's job. The Lead's `role: lead`, `scope: project`, shares the pod session key. Keep `type` (repo/task) as the policy role for model resolution.
- **Acceptance:** an added pod has exactly one Lead with the no-edit constraint and the pod session key; the old "delegate → global programmer" instruction is gone from the project SOUL.
- **Test:** pytest: Lead template renders with no-edit constraint + pod session key; integration: added pod has one `role: lead` member.

#### 🟡 AA-6 — Org Portfolio Manager (optional, single)

- **Why:** Cross-product prioritization/budget needs *one* org view — but it must not be the per-pod bottleneck the single global Atlas is today.
- **Files:** [src/docket/cli/_install.py](src/docket/cli/_install.py), [src/docket/config.py](src/docket/config.py).
- **Requirements:** Optionally provision **one** `scope: org`, `role: portfolio-manager` agent that sees fleet metadata/queue/budgets (not project code). It does **not** dispatch into pods at runtime in v1 (that's AA-7/daemon); it's the cross-pod planning/visibility surface. Gate behind an install flag if you want it opt-in. Keep it distinct from per-pod Leads.
- **Acceptance:** with the flag, install creates one org Portfolio Manager visible in `docket list --all` with `scope: org`; without it, none exists and pods still function.
- **Test:** integration: flag on → one portfolio-manager; flag off → none; it never appears as a pod member.

#### 🟡 AA-7 — Real dispatch (DAEMON-gated; decision from AA-0)

- **Why:** Turn Defect C's instruction-only delegation into something reliable — *if* the daemon supports it; otherwise document the ceiling honestly instead of overclaiming.
- **Files:** [src/docket/serve.py](src/docket/serve.py) (dispatch loop), [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (`team`/`TASK_LIST.json`), [src/docket/core/trace.py](src/docket/core/trace.py) (emit dispatch events, reuse Phase 8).
- **Requirements:** **If AA-0 says yes:** the `docket serve` loop reads the pod's `TASK_LIST.json`, dispatches each task to the right pod worker via the daemon (Lead → Implementer → Reviewer → Tester pipeline), collects completion markers, and emits trace events at each hop. **If AA-0 says no:** keep the queue + Lead as the operator-driven surface, file an upstream daemon-hook request, and **document** in help/README that runtime routing is operator-mediated (the Phase 8 honesty rule — no overclaiming inline enforcement). Either way, dispatch happens **within a pod** (shared session key), never across pods.
- **Acceptance:** (yes-path) a queued pod task is dispatched and traced end-to-end without manual Telegram relay; (no-path) docs state precisely that dispatch is operator-driven and the queue is the contract.
- **Test:** (yes) integration with a faked daemon dispatch → trace shows the pipeline; (no) docs grep audit asserts no "automatic routing" overclaim.

#### 🟡 AA-8 — `docket list` / `doctor` taxonomy view + migration

- **Why:** "What agents exist, what scope, what role, in which pod" must be answerable at a glance, and existing installs must migrate safely.
- **Files:** [src/docket/cli/__init__.py](src/docket/cli/__init__.py) (`list`), [src/docket/cli/_doctor.py](src/docket/cli/_doctor.py).
- **Requirements:** `docket list --all` gains SCOPE and POD columns (org agents listed once; pod members grouped under their project). `doctor` backfills `scope` for pre-Phase-10 metas (AA-1 rule), flags legacy global programmer/reviewer/tester singletons with the re-scope guidance from AA-2, and verifies pod members share one session key (drift check, reuse the Phase 9 pattern). `--fix` performs the safe backfills.
- **Acceptance:** on a pre-Phase-10 install, `doctor` backfills scope and flags legacy singletons; `list --all` renders the org/pod taxonomy correctly.
- **Test:** integration: meta-less-scope install → doctor backfills + flags; list groups pods.

#### 🟡 AA-9 — Docs / help / CLAUDE.md truth pass

- **Why:** The current docs describe the flawed shared-specialist model; they must teach the pod model and stay honest about pure-docket vs daemon-gated.
- **Files:** `CLAUDE.md` ("Agent Types" + architecture), `README.md`, `docs/` (WORKFLOW-GUIDE, DOCKET), [src/docket/cli/_help.py](src/docket/cli/_help.py).
- **Requirements:** Rewrite the agent-type narrative to **pods**: org-scoped shared agents (security, knowledge, optional Portfolio Manager) vs per-product pods (Lead + project-scoped Implementer/Reviewer/Tester). State plainly what's enforced by provisioning/isolation (scope, session-key inheritance) vs what's daemon-gated (runtime dispatch, per AA-7). Remove "specialists are shared resources that work across all projects" for the project-roles. Keep claims honest (no dollar-savings, no overclaimed runtime routing).
- **Acceptance:** `grep -ri "shared resource" CLAUDE.md docs/` no longer describes programmer/reviewer/tester as global; docs describe pods + the daemon caveat; tests green.
- **Test:** docs grep audit + `uv run pytest` green.

**Phase 10 exit criteria:** scope is a validated first-class axis on every agent; a clean install creates only org-scoped shared agents; `docket add` provisions an isolated pod whose Lead + Implementer/Reviewer/Tester share one session key (no shared singleton serves two projects); the Implementer runs in the project workspace (knower == builder); the single global Atlas manager is replaced by per-pod Leads + an optional org Portfolio Manager; runtime dispatch is either real-via-daemon or documented as operator-driven (never overclaimed); `docket list`/`doctor` show and migrate the org/pod taxonomy; docs teach the pod model honestly.

---

### PHASE 11 — Competitive differentiation (OpenClaw fleet-management space)  *(☑ COMPLETE 2026-06-25)*

> Source of record: `internal-docs/competitive-analysis.md` (deep-research pass + a
> GitHub-verified competitor sweep, 2026-06-25). Read it before claiming a CD-task — it has the
> full competitor map, the verified star counts, and the per-axis gap analysis. Executable board:
> [TODO.md](TODO.md).

**Why this phase.** A verified sweep of the OpenClaw-native ecosystem shows it is **crowded but
bifurcated**: monitoring *dashboards* (read side — `builderz-labs/mission-control` ~5.4k★,
`abhi1693/openclaw-mission-control` ~4.1k★, plus several `openclaw-dashboard`s) and one-shot *setup
scripts* (`shenhao-stu/openclaw-agents` ~445★). The **only** true CLI lifecycle+governance peer is
`oguzhnatly/fleet` — and it's ~13★, written in Bash, with no pods / role→model cost policy /
workspace isolation. The broader category (OpenHands, Cursor, Codex, E2B/Modal, Conductor, Bernstein)
confirms three things the field treats as **unsolved**: (1) runtime-resource isolation between
parallel agents (ports, scratch DBs, caches), (2) anti-fragile *shared* context for multi-agent work
(Cognition's "Don't Build Multi-Agents"), (3) a real HITL/audit/approval spine. docket already owns
(2) via Lead-owned context + session scoping, and has the bones of (3). This phase doubles down on
the trio no inner- or outer-ring competitor integrates, and closes the two most visible gaps
(no dashboard-feed API; gates are opt-in / Telegram-only).

**The bet (one line):** docket is the *governed, coordinated, isolated* control plane on the **write
side** — it should **feed** the dashboards, not try to out-UI them, and lead on **pod-level resource
isolation (CD-1), a real verification gate (CD-2), and on-by-default governance (CD-3/CD-4)**.

**Cards (detail + acceptance in [TODO.md](TODO.md)):**
- **CD-0** — Confirm the live `openclaw agent --json` result schema (esp. cost) and tighten
  `agent_run` parsing. *(carried-forward AA-0 follow-up; unblocks honest cost in CD-1/CD-2.)*
- **CD-1** — **Pod-level runtime-resource isolation** (allocated port range + scratch data dir per
  pod, injected into the Implementer's env). *Flagship — attacks the field's acknowledged unsolved
  problem; pure provisioning, no daemon change.*
- **CD-2** — **Deterministic pre-merge verification gate** (run the project's lint/type/test command
  via the system adapter; hard-fail the hop on non-zero). Turns "Tester agent says ok" into "tests
  passed." Matches Bernstein's Janitor bar.
- **CD-3** — **High-risk action classes** in the policy engine (money / prod-deploy / secret-access
  → *always* route to approval, regardless of allowlist).
- **CD-4** — **Headless approval channel** (web/CLI/webhook) so gates can finally be recommended
  on-by-default for non-Telegram operators (unblocks the long-deferred "Phase 0 gates default-on").
- **CD-5** — **Git-worktree-native Implementer isolation** for repo pods (the convergent industry
  pattern; composes with CD-1). *Daemon-path sensitive — validate first.*
- **CD-6** — **Scheduled & webhook-triggered dispatch** in `serve` (cron + inbound webhook →
  OpenHands Automation-Server parity; turns the poller into an event-driven control plane).
- **CD-7** — **Lobster workflow validate + dry-run/plan** (narrow the gap to Conductor without
  claiming docket executes the workflow).
- **CD-8** — **Stable read API + minimal status surface** so docket *feeds* the dashboard cluster
  rather than competing on UI (harden `serve`'s `/status.json`/`/metrics`, document the contract,
  optional single-file HTML).
- **CD-9** — **Positioning/docs truth pass**: lead with coordinated-context + isolation; add
  "ops layer, not a framework" (vs CrewAI/LangGraph) and "governed fleet, not a solo assistant"
  (vs raw openclaw) lines; keep the no-dollar-savings discipline as a *trust* differentiator.

**Phase 11 exit criteria:** a pod gets isolated runtime resources (CD-1); a pod task cannot be marked
done unless a mechanical verification gate passes (CD-2); high-risk actions always require approval
and there is at least one headless approval channel so gates can ship on-by-default (CD-3/CD-4);
`serve` can be triggered on a schedule/webhook and exposes a documented read API a dashboard can
consume (CD-6/CD-8); public docs lead with the verified differentiators and make no unfalsifiable
claims (CD-9). Out of scope (→ §7 Backlog): a full web UI of our own, microVM/gVisor isolation,
multi-host/remote provisioning, cross-runtime (non-OpenClaw) adapters.

> **☑ Phase 11 shipped 2026-06-25 — all cards CD-0…CD-9 DONE, full suite green (693 passed).**
> Every exit criterion above was met: disjoint per-pod runtime resources with reclaim (CD-1),
> git-worktree Implementer isolation with documented fallback (CD-5), the `verifyCmd` mechanical
> gate blocking task-done on failure (CD-2), always-approve high-risk policy classes (CD-3), the
> headless `serve` approval channel unblocking gates-default-on (CD-4), scheduled + webhook
> dispatch (CD-6), Lobster `validate`/`plan` without execution overclaim (CD-7), the versioned
> read API pinned by `specs/data/serve-read-api.spec.md` (CD-8), and the positioning truth pass
> (CD-9). The TODO board was cleared per convention; this note is the durable record.

---

### PHASE 12 — Consolidation & hardening  *(☑ COMPLETE 2026-07-02)*

> **Source of record:** `internal-docs/architecture-audit.md` (2026-07-02 full-repo audit — four
> parallel passes over architecture invariants, docs↔code sync, feature value, and dead
> code/hardcoded data; every finding carries file:line evidence). Read it before claiming a
> CH-card. Executable board: [TODO.md](TODO.md).

**Why this phase.** Eleven phases of feature work landed with the architecture *mostly* honest:
the audit confirmed the cli→core→edges direction holds (nothing in core/edges imports cli) and
the ACL really is the only OpenClaw-format parser. But it also found (a) **invariant breaches** —
`.docket-meta.json`/registry writes bypassing `store.py` with the atomic-write dance hand-copied
8+ times, raw `openclaw` shell-outs outside the ACL, `core/provider.py` printing Rich UI from the
domain layer; (b) **a 4,194-line `cli/__init__.py`** (32% of the codebase); (c) **carried features
that no longer earn their keep** — `core/drift.py` (one caller, feeds an unimplemented
notification), the legacy `team` manual queue (no dispatcher; pods own delegation), hand-written
completions already drifted, overdue tier/`profiles:` deprecation shims, three dead template
files; (d) **docs/specs drifted from the CLI** — 8 commands missing from the command reference,
wrong extensions/exit codes/state names in specs, contradictory test counts, a changelog missing
Phases 10–11; and (e) **broken Bash-era scripts still wired into CI** (`spec-coverage.sh`,
`metrics.sh` count the deleted `lib/` tree — which is why the README drift-guard went blind).

**The bet (one line):** before any new capability, make the codebase *match its own documentation
and principles* — one JSON chokepoint, one OpenClaw boundary, one delegation system, specs that
are current-state contracts rather than historical patches, and a re-armed drift guard so it
stays that way.

**Cards (detail + acceptance in [TODO.md](TODO.md)):** CH-0 quick truth/dead-file sweep · CH-1
store.py single-writer rule (D-12) · CH-2 `openclaw` shell-outs behind the ACL · CH-3 core/edges
UI-printing violations · CH-4 retire `team` (D-11) · CH-5 delete `core/drift.py` · CH-6 remove
tier/`profiles:` shims (D-2 exit) · CH-7 split `cli/__init__.py` · CH-8 drift-proof completions ·
CH-9 fix/retire Bash-era scripts + re-arm the CI drift guard · CH-10 spec (SDD) truth pass ·
CH-11 docs completeness pass · CH-12 changelog backfill + 0.2.0 prep · CH-13 local test-harness
hygiene.

**Explicit keeps (audited, do NOT cut):** the ACL + `store.py` + dual-source `sync.py` (documented
architecture); the audit log, approval store, and opt-in gates (substrate of CD-3/CD-4); the
`serve` read API incl. `/metrics` and scheduled/webhook dispatch (CD-6/CD-8 differentiators,
spec-pinned); Lobster `validate`/`plan` (CD-7); `resources.py` (small, CD-1 substrate); the
`policy.py`/`models_policy.py`/`provider.py` trio (distinct concerns — naming, not duplication).

**Phase 12 exit criteria:** zero docket-owned JSON writes outside `store.py` (except the named
JSONL exemption, D-12); zero `openclaw` shell-outs outside the ACL; zero `ui` imports in
`core/`/`edges/`; no module over ~1,500 lines in `cli/`; `team`, `drift.py`, tier/`profiles:`
shims and the three dead templates gone (with removed-command notices where user-facing);
`docs/commands.md` covers every live command and flag; every spec's Status line and contract
matches code (extension, exit codes, state strings); CHANGELOG documents Phases 10–11 and cuts
0.2.0; the README-numbers drift guard runs green in CI against the Python tree; full suite +
goldens green throughout.

> **☑ Phase 12 shipped 2026-07-02 — all 14 cards CH-0…CH-13 DONE, full suite green.** Every
> exit criterion above was met, with one negotiated deviation: `cli/__init__.py` landed at
> **1,702 lines**, not ≤1,500 — the CH-7 card's own Do-list named 5 extraction targets
> (`_keys.py`, `_context.py`, `_workflow.py`, `_cost.py`, `_agents.py`) and none of the
> remaining commands, so no 6th stage was invented purely to force the number under the target.
> `docket` **0.2.0** was drafted in CHANGELOG/`VERSION`/`pyproject.toml`/`uv.lock`/`__version__`
> at this point, but not yet tagged — Phase 13 landed on top before the tag was cut, and the
> release actually shipped as **`0.2.0-beta.1`** (see the Phase 13 completion note and §8) once
> the operator clarified every release from this project carries a SemVer `-beta.N` suffix. The
> TODO board was cleared per convention; this note is the durable record. Full findings:
> `internal-docs/architecture-audit.md`; execution trail: TODO.md's CH-0…CH-13 cards (kept, per
> this phase's own convention, until the next phase overwrites them).

---

### PHASE 13 — Close the differentiation gaps  *(☑ COMPLETE 2026-07-02)*

> **Source of record:** `internal-docs/competitive-analysis.md` (2026-06-25 research pass) named
> three "Tier 1 — Now" bets as docket's highest-leverage, no-daemon-change differentiators: **P1**
> pod-level runtime-resource isolation, **O2** a deterministic pre-merge verification gate, **S1**
> high-risk action classes + a headless approval channel. A 2026-07-02 grounding pass (three
> parallel code investigations, file:line-cited) found the framing had gone stale: **Phase 11's
> own CD-1/CD-2/CD-3/CD-4 cards already built most of this** the same week the analysis was
> written. Executable board: [TODO.md](TODO.md).

**Why this phase.** Re-checking the three bets against the current tree:

- **P1** — `AgentMeta` already has `port_range_start/count`, `scratch_dir` (`core/models.py:75-77`);
  `core/resources.py` allocates ports/scratch dirs per pod; `_pod.py` documents them into TOOLS.md.
  What's missing: none of it reaches the implementer's actual **process environment** —
  `edges/adapters/openclaw.py`'s `agent_run` (~L971-976) shells out with no `env=` override, so an
  implementer can only *read about* its port range/scratch dir as prose in TOOLS.md, never rely on
  it being set. The disposable DB/cache "namespace" is a naming convention only (`_pod.py:116-117`),
  no real provisioning — that stays out of scope (no DB engine assumption; see keeps below).
- **O2** — this *is* CD-2, already shipped 2026-06-25: `dispatch.py` runs `verifyCmd` via
  `edges/adapters/system.py`'s `run_verify_cmd` after the implementer hop and hard-fails on
  non-zero. Two real gaps remain: (a) there is no way to **set** `verifyCmd` short of the internal
  `meta-set` debug command — no TOOLS.md field, no public `docket pod add --verify` flag, despite
  `specs/data/docket-meta.spec.md:74` already (incorrectly) documenting one; (b) the Tester hop's
  PASS/FAIL is prose the pipeline never parses — only adapter-level `run_res.ok` gates it, so a
  Tester agent that writes "FAIL" in its response can still advance the pipeline.
- **S1** — `docket approve`/`docket deny` (CLI channel) and `serve.py`'s `POST /approvals/<token>`
  (HTTP channel) both already work end-to-end (`cli/_approve.py`, `serve.py` ~L321-368). The
  headless approval routing that `specs/functional/security-gates.spec.md` says gates-default-on
  is blocked on already exists in code — the spec just hasn't caught up. Two real gaps remain:
  (a) no "high-risk action class" concept exists anywhere — `core/security.py` is a flat binary
  allowlist, no always-route category for money/prod-deploy/secret-access actions; (b) approval
  grants/denials only emit trace events, never `audit_log()` — so an approval channel other than
  Telegram leaves no audit trail.

**The bet (one line):** don't build three features from scratch — close the five specific,
file:line-identified gaps that stand between "the substrate exists" and "the differentiation claim
is true," then flip gates-default-on now that its own spec's blocking condition is actually met.

**Cards (detail + acceptance in [TODO.md](TODO.md)):** FD-0 inject pod resources into the
implementer's process env (completes P1) · FD-1 TOOLS.md verify-command field + public
`--verify` flag (completes O2a) · FD-2 structural Tester PASS/FAIL gate in dispatch (completes O2b)
· FD-3 high-risk action-class always-approve policy (completes S1a) · FD-4 audit-log parity for
approval grant/deny across all channels (completes S1b) · FD-5 security-gates.spec.md truth pass +
flip gates-default-on · FD-6 spec/data truth pass for the fields touched above · FD-7
docs/positioning pass — claim the closed gaps, correct the stale competitive-analysis framing.

**Explicit keeps (do NOT build in this phase):** a real disposable DB/cache namespace (stays a
naming convention — no docket-owned DB engine to provision against); microVM/gVisor isolation,
multi-host provisioning, cross-runtime adapters (all still §7 Backlog, deferred); the existing
CLI/HTTP approval channels themselves (already correct — this phase documents and hardens them,
does not rebuild them).

**Phase 13 exit criteria:** an implementer subprocess's real environment contains its allocated
port range + scratch dir (test-verified, not just TOOLS.md prose); `verifyCmd` is settable via a
public CLI flag and documented in TOOLS.md; a Tester hop reporting FAIL (or an unparseable result)
blocks pipeline advancement; a defined high-risk action-class list always routes to approval
regardless of the allowlist; every approval grant/deny (any channel) writes an audit-log entry;
`security-gates.spec.md` reflects the real channel set and states the on-by-default condition is
met; `docket install`'s gates default flips; full suite + goldens green throughout.

> **☑ Phase 13 shipped 2026-07-02 — all 8 cards FD-0…FD-7 DONE, full suite green (795 tests).**
> Every exit criterion above was met, with one honest narrowing: the high-risk action-class
> policy (FD-3) is **fully enforced only for money-movement and secret-access** (their bins were
> never in the curated allowlist); prod-deploy's `git`/`npm` overlap is documented policy, not
> daemon-enforced — an initial implementation that excluded `git`/`npm` wholesale was rejected
> during review because the daemon's exec-allowlist gates by binary path only, and would have
> forced every benign invocation (`git status`, `npm test`) to also require approval. Per-argument
> enforcement for allowlisted bins is now a tracked backlog item, not silently claimed as shipped.
> `internal-docs/competitive-analysis.md` (gitignored, local-only) was corrected with per-bet
> status notes so its Tier-1 framing — which had already gone stale by the time this phase started,
> since Phase 11's CD-1…CD-4 had built most of the substrate the same week it was written — doesn't
> mislead a future planning pass the same way. Full findings: this section above; execution trail:
> TODO.md's FD-0…FD-7 cards (kept until the next phase overwrites them, per convention).

---

### PHASE 14 — Platformization I: runtime truth & dispatch hardening  *(☑ COMPLETE 2026-07-30)*

> **Source of record:** `internal-docs/agent-platform-audit-and-build-plan.md` (2026-07-29, four
> parallel code-grounded audit passes, file:line-cited; gitignored local rationale — this section is
> self-contained). The audit measured docket against eight agent-platform pillars (runtime driver,
> workflow engine, MCP, gateway, context/memory, governance, orchestration, role diversity) and found
> a disciplined config layer over a dispatch lane that is **not crash-safe, not race-free, and not
> honest about three of its own specs**. Phases 15–18 all execute through this lane — it hardens
> first. Executable board: [TODO.md](TODO.md).

**Why this phase (code-verified defects, the audit's §8 register):** the pod task queue has an
unlocked read-modify-write — the serve webhook, scheduler, and sweeper threads can all dispatch the
same pod concurrently and double-run a task (`dispatch.py` read→write vs `store.py`'s write-only
lock). There is no persisted `running` state, so a crash mid-task re-runs every hop from the lead.
A budget-`blocked` task is rewritten to `pending` and retries forever. No retries, no cancellation,
no per-task timeout (one hardcoded 300s constant shared with verify commands). The serve dispatch
lane swallows every exception (`contextlib.suppress`) and the webhook returns 200 before any work,
with no run id. The Reviewer role is mechanically decorative (its APPROVE/REQUEST-CHANGES is never
parsed; only the Tester gate is real). Auto-pause at budget cap **does not exist** — no code writes
`paused=True` (the Phase 1 claim was Bash-era; the port dropped it), and display code compares the
flag as a string while writers use a bool. `verifyCmd` runs in `codebase` instead of the member's
`worktreeDir`, `shell=True`, with no independent timeout. `_hop_message` concatenates every prior
hop's full output unbounded. And the spec surface overclaims: `audit.spec.md` is "Complete" at ~1/6
coverage; `security-gates.spec.md`'s `[GATE] → docket approve` worked example cannot happen today.

**Cards (detail + acceptance in [TODO.md](TODO.md)):** R-1 task state machine v2 — persisted
`running`, locked claims, retries with `attempts`, per-task timeout, uuid task ids, crash sweep +
resume-from-hop; kill the `blocked→pending` rewrite · R-2 retries + configurable timeouts (turn vs
verify decoupled) · R-3 run registry + job API (`docket runs`, `GET /runs/<id>`), ban
`suppress(Exception)` in the dispatch lane (D-17) · R-4 Reviewer verdict gate + bounded rework loop
back to the implementer · R-5 budget honesty — implement auto-pause for real, fix the string/bool
bug, token-based *estimate* (clearly labeled, never "recorded spend") when the daemon writes no cost
· R-6 verifyCmd correctness (worktree cwd, bounded shell surface, audit on set-verify) · R-7 bounded
hop prompts (cap + truncation marker — stopgap until Phase 17's compiler) · R-8 spec/docs truth pass
(audit.spec.md re-status, security-gates `[GATE]` example marked daemon-gated, `_provider.py`
guidance bugs, eval-harness schema drift, durable scheduler last-run state).

**Explicit keeps (do NOT build here):** no asyncio rewrite, no FastAPI, no message bus (threads +
filelock + persisted claims only, per §4.5); no new pillars (workflow spec, archetypes, MCP, driver
port all wait for 15–18); no daemon changes.

**Phase 14 exit criteria:** two concurrent dispatchers cannot double-run a task (thread-race test);
a killed-mid-task dispatch resumes from the last completed hop without re-paying earlier hops; a
budget-capped agent is actually `paused` and dispatch refuses it; REQUEST-CHANGES from a Reviewer
blocks (and one bounded rework cycle runs); every serve-lane dispatch has a queryable run id and no
silenced exceptions; every spec Status line matches the code; full suite + goldens green.

> **☑ Phase 14 shipped 2026-07-30 — all 8 cards R-1…R-8 DONE, full suite green (1,112 tests, 18
> goldens).** Every exit criterion above was verified against the shipped code and its tests,
> not just claimed:
>
> - Two concurrent `dispatch_pod` calls cannot double-run a task — `edges/store.py`'s new
>   `with_lock`/`read_modify_write` makes the claim (`pending`→`running`, `startedAt`/`claimId`/
>   `claimedAt` persisted) one locked read-modify-write; test-pinned
>   (`TestConcurrentDispatch.test_two_concurrent_dispatch_pod_calls_never_double_run_a_task`,
>   `tests/python/test_dispatch.py`).
> - A killed-mid-task dispatch resumes from the last completed hop, not hop 0 — hops persist
>   incrementally (`_persist_hop`); a stale `running` claim is swept to `failed`
>   (`failureKind: "stale_claim"`) and only `--resume` reclaims it, replaying pipeline position
>   (including mid-rework) via `_replay_pipeline_position`; test-pinned
>   (`test_resume_skips_already_completed_hops`, `test_stale_claim_sweep_emits_trace_event`).
> - A budget-capped agent is genuinely `paused` and dispatch refuses it — `_pause_lead_for_budget`
>   writes `paused=true, pausedReason="budget"` on the pod's Lead the first time the cap is
>   reached; `_claim_next_task` refuses every further claim for that pod outright (a
>   `paused_refused` trace event); `docket profile <id> --resume` clears it; test-pinned
>   (`tests/python/test_autopause.py`, 26 cases).
> - REQUEST-CHANGES from a Reviewer blocks and drives one bounded rework cycle (default
>   `maxReworkCycles=1`) before a second rejection fails the task — test-pinned
>   (`tests/python/test_reviewer_gate.py`, 25 cases, incl. `TestReviewerReworkResume` for the
>   resume-mid-rework case).
> - Every serve-lane dispatch (CLI, webhook, schedule, sweep) has a queryable run id via
>   `core/runs.py`/`docket runs`, and the four `contextlib.suppress(Exception)` sites around
>   dispatch that used to swallow every exception are gone — grep-pinned
>   (`tests/python/test_no_suppressed_dispatch.py`).
> - Every spec Status line matches the code: R-8's sweep rewrote `pod-dispatch.spec.md` to
>   v2.0.0 (the full state machine) and trued up `docket-meta.spec.md`, `serve-read-api.spec.md`,
>   `cli-json-shapes.spec.md`, `audit.spec.md`, and `cli-interface.spec.md` — see TODO.md's R-8
>   card for the exact per-file diffs, several of which were pre-existing drift unrelated to R-1…
>   R-7 caught along the way (a stale `apiVersion` example, a phantom `type` JSON field, two
>   missing audit action families). `specs/README.md`'s status table now mirrors every spec's
>   real header.
> - Full suite + goldens green throughout: 1,112 pytest cases, 18 golden-parity cases,
>   `scripts/validate-specs.sh`, `uv run python scripts/metrics.py --check`.
>
> **What was narrowed or deferred (stated here so it isn't quietly re-claimed later):**
> cancellation of an in-flight hop and parallel hop execution are **not implemented** — both stay
> Phase 16 W-2, same as before this phase; `maxReworkCycles` has no dedicated CLI setter yet
> (set via the internal `meta-set` debug path), noted in R-4's own card and in
> `docket-meta.spec.md`; the Reviewer/Tester verdict gates and the budget/pause mechanism remain
> scoped to the pod-dispatch lane only — an agent's spend outside dispatch (a raw Telegram
> session, direct daemon use) is still entirely unenforced, per D-9's "docket orchestrates hops"
> boundary; the governance gaps this phase was never meant to close are unchanged and explicitly
> still open — docket's approval store still has no production producer (Phase 15 G-1/G-5),
> `docket models set/preset/reset` still write no audit entry (Phase 15 G-4 follow-up), and
> enforcement outside the dispatch lane (e.g. per-argument high-risk matching for allowlisted
> bins) still does not exist (Phase 15 G-3). One card (R-6) had shipped correctly but its own
> TODO.md status line and acceptance boxes were left at `TODO` through an oversight in an earlier
> merge — corrected as part of this phase's board-truth pass, not a late functional change.
> Execution trail: TODO.md's R-1…R-8 cards (kept until the next phase overwrites them, per
> convention).

---

### PHASE 15 — Platformization II: deterministic governance, wired  *(☑ COMPLETE — all 6 cards G-1…G-6 shipped; G-3 closed it 2026-07-31)*

> **The audit's single most damning pattern:** three governance organs are fully built, tested, and
> documented — and connected to nothing. `approval_create` has **zero** production callers (the
> daemon's exec prompt and docket's `apr-*` store are disconnected systems); the policy engine's
> only caller is its own dry-run printer (`docket policies test`), and `docket install` never even
> installs the six shipped policy templates; `resolve_command_action` — the one function implementing
> "high-risk always asks" — has no caller. Meanwhile the audit log covers ~1/6 of its spec (keys/
> profile/scope/agent-lifecycle mutations write nothing), has no tamper evidence, and
> `DOCKET_NO_AUDIT=1` is an unauthenticated kill switch whose suppression looks identical to success.

**Cards:**

- **G-1 · Approval-gated dispatch** *(the approval store's missing producer — pure docket)*: a
  `require_approval` gate evaluated pre-hop (from policy match, pod `requireApprovalRoles`, or a
  pipeline `approval` step). Task enters persisted `waiting_approval`; `docket approve/deny` and the
  HTTP endpoint genuinely resume/kill the run; the timeout sweep resolves to **denied** (matching the
  spec's fail-closed language, not today's read-by-nobody `expired`).
- **G-2 · Policy engine on the live path**: `install` runs `policies init`; `pre_input` evaluated at
  enqueue, `pre_output` (redact/warn/block) on every hop output before carry-forward/storage;
  `require_approval` action feeds G-1; emit `guardrail_check`/`guardrail_block` trace events (giving
  `_metrics.py`'s existing reader a producer). In-turn `pre_tool_call` stays **daemon-gated** —
  documented, never claimed.
- **G-3 · High-risk classes enforced where docket can**: wire `resolve_command_action` into every
  process docket itself launches (verifyCmd, future pipeline `shell` steps) and G-2's pre-output
  scan. Per-argument daemon enforcement stays the tracked backlog item (Phase 13's honest narrowing).
- **G-4 · Audit v2** *(DONE — pulled forward on `pc/g-4`, no Phase 14 dependency)*: coverage to
  spec (`keys.* profile.* scope.* agent.add/delete pod.* persona.*`); per-line `seq` +
  `prev_hash` chain + `docket audit verify`; ms timestamps; size-capped rotation
  (`AUDIT_LOG_MAX_BYTES`); `DOCKET_NO_AUDIT` removed entirely (not TTY-gated — would force
  interactive I/O into `core/`); suppressed trace writes return a distinct status (never a fake
  `True`). `runs.cancel` stays a tracked gap — no run registry exists yet (Phase 14 R-3 /
  Phase 16 W-2); `models.*` (role→model policy changes) also stays out of scope. See
  audit.spec.md v2.0.0.
- **G-5 · [daemon-gated spike] the `[GATE]` seam**: can the daemon's exec-approval prompt notify an
  external hook? Yes → bridge daemon prompts into docket approval tokens (the spec's example becomes
  true). No → file upstream, spec example stays labeled future.
- **G-6 · Serve auth hardening** *(DONE — pulled forward on `pc/l-2`, no Phase 14 dependency)*:
  `secrets.compare_digest` (timing-safe Bearer-token comparison, `serve.py`'s `_check_auth`),
  a `--token-file`/`token_file=` option to write the approval/dispatch token to a 0600 file
  instead of stdout, and documented bind rules (loopback-only by default, an explicit warning
  printed for any non-loopback bind). Landed in the same merge as L-2 below. See
  `tests/python/test_serve_auth.py`.

**Exit criteria:** every control in the audit's "enforced vs documented" table is either on a live
path or explicitly labeled *convention* in SECURITY docs; a `require_approval` policy visibly pauses
a real dispatched task until granted; `docket audit verify` detects a tampered line; suite green.

---

### PHASE 16 — Platformization III: declarative orchestration & diverse role archetypes  *(☑ COMPLETE — all 8 cards W-1…W-8 shipped 2026-07-30)*

> **Why:** the pipeline is a hardcoded constant and the role system knows exactly one objective —
> shipping code. `POD_ROLES` is a closed 4-tuple (`core/pod.py:21`), every role identity is a
> hardcoded Python string (`_pod.py:44-97`), gates are code-shaped (verify-cmd → implementer only,
> PASS/FAIL → tester only), and since the task-agent type was deleted, every agent is assumed to
> have a codebase. A research pod, a content pod, an ops pod are **inexpressible**. The operator's
> explicit requirement: pods must orchestrate *diverse objectives, not just build a web site* —
> with roles and scope declared as data. Scope itself (org vs project, per-pod isolation substrate:
> session keys, port ranges, scratch dirs, worktrees) already generalizes and is reused untouched.

**Cards:**

- **W-1 · docket-native pipeline spec**: one Pydantic-modeled, unknown-key-rejecting YAML — ordered
  steps (`role|agent`), per-step `retries/timeout/gate` (mechanical-check | verdict | approval),
  bounded rework edges, `parallel` groups (finally using `--count N` members), variables. Steps
  reference W-6 archetypes. No pipeline file ⇒ today's built-in order (zero migration).
- **W-2 · Executor**: `core/orchestrator` runs W-1 specs over R-1's state machine — bounded worker
  pool (threads; hops are subprocess-bound), join semantics, per-step trace spans, `docket runs
  cancel` kills the in-flight hop's process group. `docket workflow plan` renders the plan **from
  the real executor** (no drift-prone second pretty-printer). Determinism contract: same spec +
  same queue ⇒ same step DAG.
- **W-3 · Lobster retirement (D-16)**: `docket workflow` → removed-command notice mapping to the
  pipeline commands (the D-11 `docket team` pattern); `core/lobster.py` + templates deleted.
- **W-4 · Durable scheduling + event triggers**: persisted last-run (no restart re-fires), cron
  specs, webhook params → pipeline variables, `dispatch --follow` streaming from the trace.
- **W-5 · Structured handoff artifacts**: steps exchange a typed record (`{summary, files_changed,
  diff_ref, verdict, notes}`) persisted per hop — replaces raw-text concatenation between hops.
- **W-6 · Declarative role archetypes**: a role becomes a versioned YAML definition — `name`,
  `scope` (org|pod), `modelClass` (cheap|strong, slotting into the existing role→model policy),
  `soulTemplate`/`agentsTemplate` (variables: project, objective, codebase?, workDir),
  `gateContract` (`none|verdict(regexes)|mechanical(cmd)|approval`), `editRights`, `toolProfile`.
  Today's four roles ship as built-in archetypes with **byte-identical output** (golden-tested);
  starter library: `researcher`, `analyst`, `writer`, `critic`, `operator`, `monitor`. `docket
  roles list/show/add/validate`; user archetypes overlay built-ins (the `docket-models.json`
  registry pattern). `normalize_role`/`member_id`/`POD_ROLE_POLICY` rewritten against the registry —
  the closed set opens without changing a single existing id.
- **W-7 · Pod blueprints — objective-scoped provisioning**: blueprint = archetype roster + default
  pipeline + workspace kind (`codebase|workdir`) + org-vs-pod scope per role + default gates/
  budgets. Built-ins: `software` (today's pod, unchanged default), `research`, `content`, `ops`.
  `docket add <p> --blueprint <name>` + extended `--from spec.yaml`; restores a non-codebase
  workspace path for `workdir` blueprints.
- **W-8 · Generalized gates**: verdict parsing and mechanical checks detach from tester/implementer
  and become gate types any step declares (per-archetype verdict regex sets — PASS/FAIL,
  APPROVE/REQUEST-CHANGES, SOURCES-VERIFIED/UNVERIFIED…); cwd resolves from workspace kind.

**Hard sequencing rule:** W-6/7/8 land **with** the executor, not after — an executor that hardcodes
roles a second time forces a second migration. **Anti-overengineering rule (new "we will NOT" row):**
no fifth role ever lands as a hardcoded string; archetype *prose and rosters* are user-extensible,
but gate contracts, edit rights, and scope stay closed typed sets docket can reason about.

**Exit criteria:** a `research` blueprint pod provisions, dispatches through a custom pipeline, and
**blocks on an unverified-sources verdict exactly the way a software pod blocks on failing tests**;
the four legacy roles produce byte-identical workspaces (goldens); `docket workflow` prints the
removed-command notice; suite green.

> **☑ Wave 7 shipped 2026-07-31 — the last 3 branches, and the Platformization program is
> COMPLETE.** Phases 14–18 all closed. `platform` green: **1,735 tests** (`pytest` exit 0, zero
> FAILED/ERROR), 18/18 goldens, 21 specs / 0 warnings, 37 commands, ~22,880 lines, `ruff` +
> `ruff format` + `mypy --strict` (62 files) clean, `metrics.py --check` in sync across all five
> claims. Merge order `c-3-c-5 → g-3 → cl-3`.
>
> **C-3 + C-5 · one durable task state, and a self-maintaining conversation registry** (Phase 17,
> closes it). Shipped as **one branch, not two** — the queued board offered "one dispatch owner or
> a function-level carve-out" and neither fit: these two write from the *same five* lifecycle
> functions (`_claim_next_task`, `_persist_hop`, `_touch_claim`, `_finalize_task`,
> `_apply_result`), so a carve-out between them was not available and splitting them would have
> manufactured a conflict in the file that cost the most to merge all program. `HEARTBEAT.md` was
> the documented durable ledger that only an agent's own compliance ever wrote to; dispatch now
> maintains a delimited docket-owned region inside it, and `docket doctor` flags TASK_LIST⇄ledger
> divergence and re-syncs under `--fix`. The delimiters are the point: writes only ever replace
> text between them, so the file stays co-authored and the agent's prose survives — pinned by
> tests, not by convention. `serve.py` needed **zero** changes, verified rather than assumed: all
> three of its dispatch triggers funnel through `_persist_hop`.
>
> **G-3 · high-risk classes on real paths** (Phase 15, closes it) — and a lesson about what
> "wire the unused function" can mean. The card said to wire `resolve_command_action`. Wiring it
> proved it was the *wrong* function: it resolves `ask` vs `allow` for a command string, and that
> decision belongs to the daemon's exec gate (D-15), which keys on binary path and has no hook to
> consult docket — it could never have had a caller. `match_high_risk` was the one that could, and
> it now guards `run_verify_cmd` (the single docket-launched subprocess built from free-form
> operator text through a real shell — a match refuses outright, since a synchronous dispatch hop
> has no approver reachable to answer an "ask") and dispatch's `pre_output` scan. **The other three
> helpers were deleted on merge** rather than left beside the wired one: keeping a never-called
> ask/allow resolver one function away from the code that fixed exactly that defect would have
> been the wrong lesson to leave in the tree. What stays advisory is unchanged and stated plainly:
> the daemon's allowlist still gates by binary path, so a live agent's `git push origin production`
> is still not daemon-blocked.
>
> **CL-3 · post-program dead-code sweep** — 97 new symbols across ~4,100 inserted lines examined,
> **4 deleted** (`step_id_of`, `BlueprintRegistry.__contains__`/`.items()`,
> `BUILTIN_BLUEPRINT_ORDER`). The restraint is the result: `handoff.notes` (reserved schema),
> `from_legacy_output` (2 real callers) and `build_pod` (not superseded — its replacement calls it)
> were all correctly kept. Findings inside sibling-owned files were **deferred to the register
> rather than edited across the line**, and both were then resolved by the integrator:
> `DistillResult.failure_kind` gained its consumer (a blocked delete now says *why* it was
> blocked), and `CancelOutcome.killed_pids` was kept with a dated reason.
>
> **Two guard defects found by chasing numbers that did not match**, both the same shape as
> Phase 14's vacuous `metrics.py --check`: (1) **the dependency floors were false** — `typer>=0.12`
> fails 216 tests against a modern click, `pydantic>=2` fails 56 test modules at import; corrected
> to `>=0.13`/`>=2.1` and now held by a new `floors` CI job that resolves `--resolution
> lowest-direct` and runs the suite. (2) **`metrics.py` and `validate-specs.sh` disagreed on how
> many specs exist** — the validator globs `specs/acceptance/*.md`, the metrics script used an
> `*.spec.md` suffix filter and structurally could not see `user-stories.md`, so README published
> 20 where the blocking gate counted 21. The two are now pinned against each other by a test that
> shells out to the validator.
>
> **☑ Wave 6 shipped 2026-07-30 — 5 cards. Phase 18 closed, Phase 17 opened and is 3 of 5,
> Phase 15 down to one open card.** `platform` green: **1,684 tests** (`pytest` exit 0, zero
> FAILED/ERROR), 18/18 goldens, 20 specs, 37 commands, `ruff` + `mypy --strict` clean,
> `metrics.py --check` in sync.
>
> **G-2 · Policy engine on the live path** — closes the audit's built-but-disconnected defect,
> the same shape G-1 fixed for the approval store. `install` seeds the baseline policies,
> `pre_input` evaluates once at enqueue, `pre_output` on every hop output, and a hit can route to
> G-1's real `approval_create`. **The existing `cli/_metrics.py` reader needed no changes** — the
> producer was built to fit it rather than orphaning it. G-2 also *declined a stale instruction*:
> `_policy_requires_approval`'s docstring claimed it was the place to change, which would have
> re-tripped a `"*"`-scoped policy once per role instead of once per task.
>
> **C-1 · Context compiler** — per-role token budgets (`RoleArchetype.token_budget`) via
> `core/context.py`, retiring R-7's blind head+tail byte cap rather than layering on it. Reused
> the existing `config.CONTEXT_BYTES_PER_TOKEN` instead of introducing a second tunable ratio for
> the same quantity; the approximation is documented as an approximation.
>
> **C-2 · Memory distillation** — `maintain distill`, and `clean`/`reset` distill first by
> default so memory is never bare-deleted. docket's **first self-originated LLM call**, through
> the driver per D-18 with **zero new dependencies** (verified: the branch's `pyproject.toml`/
> `uv.lock` diff is empty). **Fails closed** — a driver timeout, daemon error or empty reply
> aborts before anything is unlinked, proven by a hermetic test running the real driver with
> `PATH=/nonexistent`, not a mock.
>
> **W-5b · Artifact diff producer** — closes the seam W-5 declared honestly. `git_current_branch`,
> which CL-2 kept a wave earlier with a dated "the primitive a near-term feature will need" note,
> turned out to be exactly that caller. All four degrade paths (non-Implementer, `workdir` pod,
> non-repo codebase, missing `git`) are pinned end-to-end through real `dispatch_task` calls.
>
> **L-5 · Wrapped gateway spike** — answered **yes**, and better: docket already ships the
> mechanism. `docket models provider add` writes an arbitrary `models.providers.<name>` block, and
> the "local" framing is cosmetic (`127.0.0.1:8080` is only `DEFAULT_BASE_URL`). No code needed.
> Recorded honestly alongside it: per-call USD metering does **not** come free — this daemon
> reports token counts only, so a sidecar's spend API is a separate integration.
>
> **Integrator cleanup done on merge, not deferred:** C-1's carve-out forbade it from deleting
> R-7's now-dead `_hop_carryover_budget`/`_truncate_carryover` helpers, so it correctly left them
> and flagged them. Since that dead code existed only as an artifact of the rule, the integrator
> removed them, `HOP_CARRYOVER_BYTES`, and the two test classes pinning them, on merge. One
> truncation mechanism now exists in the tree.
>
> **The carve-out worked, and the one conflict it did produce was the dangerous kind.**
> `core/dispatch.py` took edits from three branches; C-1 (`_hop_message` only) and W-5b (one new
> function plus one call site) auto-merged with zero conflicts. G-2 conflicted at the artifact
> construction site, and **neither side was correct**: G-2 introduced `hop_ok`/`hop_output` (the
> post-policy values) while W-5b's side still read `run_res.ok`/`run_res.output`. Taking W-5b's
> side verbatim would have sourced the artifact summary from raw subprocess output and **silently
> undone `pre_output`'s redaction** — a leak, not a style difference. Resolved to `hop_output` for
> the summary and `hop_ok` for both the verdict and the diff probe, with the reasoning left as
> comments at the call site.
>
> **The completions goldens were the exact case the standing rule exists for:** C-2 added
> `distill`, G-2 added `validate`, and no side held both. Git auto-merged them — which is not
> evidence of correctness — so `verify-all` was re-run against the real CLI and both additions
> confirmed present.
>
> **What was narrowed or deferred:** `pre_tool_call` (in-turn interception) stays daemon-gated —
> docket orchestrates *between* hops and is not inside a turn to intercept a tool call; G-3 (the
> high-risk action classes wired into docket-launched processes) is still open and is Phase 15's
> last card; `HandoffArtifact.notes` still has no producer and is now documented as reserved;
> the **dependency floors remain unverified** for lack of network access. G-2 also found real
> test-hygiene damage: two install fixtures left `DOCKET_HOME`/`POLICIES_DIR` at their real
> unpatched defaults — harmless until something in `run_install` touched them, at which point a
> test run would have written into the real environment.

> **☑ Wave 5 shipped 2026-07-30 — 5 cards, and Phase 16 is COMPLETE.** `platform` green at each
> merge: **1,600 tests**, 18/18 goldens, 20 specs, 37 commands, `ruff` + `ruff format` +
> `mypy --strict` clean, `metrics.py --check` in sync.
>
> **W-5 · Structured handoff artifacts** — hops exchange a typed `HandoffArtifact`
> (`core/handoff.py`) instead of concatenated raw text. The shape is the deliverable because Phase
> 17's C-1 must budget tokens against it: `summary` is required and `DROP_ORDER` gives a
> size-constrained consumer a typed shedding order, with `summary` deliberately excluded so it can
> never be dropped. `render()` returns exactly `summary` when nothing else is set, so the common
> case is byte-identical to the old behaviour, and `from_legacy_output()` degrades a pre-W-5 or
> malformed hop record instead of failing a resume. **This unblocks C-1**, and with it Phase 17.
> `pod-dispatch.spec.md` → 4.0.0: the persisted hop record format changed, with a documented
> degrade path.
>
> **W-4 · Durable scheduling + event triggers** — stdlib-only cron parser, webhook payload bound
> into pipeline variables (rejected with 400 *before* a run record exists), `pipeline run --follow`
> tailing the durable trace, and the `runs.cancel` audit entry. Its first deliverable needed **no
> code**: Phase 14's R-3 had already shipped and test-pinned persisted last-run, and the card
> verified that rather than rebuilding it.
>
> **G-4b · `models.*` audit coverage** — closes the gap G-4 named two waves earlier. `set` writes
> one entry; `preset`/`reset` can rewrite every role at once and each write a single entry naming
> every role's before→after pair. Both values are read around the write, so a repeated change logs
> the real prior value rather than a constant.
>
> **CL-2 · Dead-code register, non-dispatch half** — `core/sync.py` kept as the single
> implementation with `cli/_doctor.py` pointed at it (rather than deleting a module whose logic
> belongs in `core/`); `read_modify_write` rebuilt on `with_lock`; `HEARTBEAT_FILE` used across all
> nine files; two zero-caller ACL functions deleted. **Three rows were deliberately kept** with
> dated in-code reasons — notably `validate_policy()`, where wiring a command would have changed
> the completions goldens this card had to keep byte-identical, and deleting it would have dropped
> schema coverage two test files already get by calling it directly.
>
> **L-4 · Daemon MCP registry spike** — answered **yes upstream, absent here**: the `mcp.servers`
> registry and its CLI family are real and were exercised live against `openclaw@2026.7.1`, but the
> daemon this fleet targets (`2026.2.23`, independently confirmed) predates them. No production
> code, per the card's own rule. Its isolated probe had a **real side effect on the host** — a
> one-time upstream state migration escaped the scratch state dir and renamed
> `~/.openclaw/exec-approvals.json`; restored, with the sandboxing lesson recorded in the spec.
>
> **Dead code cleared this wave:** the `AgentRunResult` alias and all ~76 call sites across ten
> test families, `dispatch_all_pods` (deleted, not wired — R-3 had already replaced its only call
> site and pins that removal), the last `print()` in `core/`, `meta_write`,
> `set_agent_project_key`, and `core/sync.py`'s dead-module status. An AST-based test now pins that
> **no `print(` call exists anywhere in `core/` or `edges/`**.
>
> **What was narrowed or deferred:** `files_changed`/`diff_ref` ship as real artifact fields with
> **no producer** — populating them needs a git probe through `edges/adapters/system.py`, which
> CL-2 owned this wave; declared as an explicit seam in both the module docstring and the spec, not
> quietly claimed. `notes` likewise has no producer. G-2 and G-3 did not run (G-2 needs the
> dispatch file W-5 owned), so the policy engine still has no live-path producer. The
> **dependency floors in `pyproject.toml` remain unverified** — CI only ever resolves the locked
> versions, and testing the floors needs network access this environment lacks.
>
> **A fourth neither-side-is-correct conflict** appeared in `audit.spec.md`: G-4b's draft said
> `models.*` shipped and `runs.cancel` was the open gap; W-4's said the reverse. Both shipped in the
> same wave, so neither card could see the other's merge, and either side alone would have published
> a spec claiming a shipped feature was missing. The index cross-check separately caught **four**
> stale rows after W-4 alone.

> **☑ Waves 3–4 shipped 2026-07-30 — 11 cards across Phases 15/16/18, plus one standing cleanup
> card. `platform` at `7fc6233`: 1,512 tests (1,509 passed / 3 skipped), 18/18 goldens, 20 specs,
> 37 commands, `ruff` + `ruff format` + `mypy --strict` clean, `metrics.py --check` in sync.**
>
> **Wave 3** (six cards, merged in contention order): G-1 approval-gated dispatch — `approval_create`
> finally has a production caller · G-5 the `[GATE]` seam spike, answered **no** with a dated
> evidence trail against a live daemon · W-1 pipeline format · W-6 declarative role archetypes,
> legacy roles byte-identical · L-1 RuntimeDriver port (D-14) · L-3 MCP server, 10 tools.
>
> **Wave 4** (five cards, merged `cl-1 → l-6 → w-3 → w-7 → w-2`): CL-1 dead-code sweep (register
> below) · L-6 `mcp` SDK 1.x→2.x migration, pin now `mcp>=2.0.0` · W-3 Lobster retirement (D-16) —
> `core/lobster.py`, `cli/_workflow.py`, `test_cd7_lobster.py` and `workflow-integration.spec.md`
> **deleted**, `docket workflow` is a removed-command notice · W-7 pod blueprints (four built-ins,
> `workdir` workspace kind restored) · W-2 + W-8 the executor and generalized gates.
>
> **Phase 16 exit criteria: met.** A `research` blueprint pod provisions, dispatches through a
> custom pipeline, and blocks on an unverified-sources verdict by the same executor path a software
> pod blocks on failing tests — because after W-8 the executor branches on the resolved gate's
> **type**, never on a role name (four hardcoded verdict helpers deleted). The four legacy roles
> stayed byte-identical throughout (goldens). Two cards remain open (**W-4**, **W-5**) — they extend
> the phase rather than gate its criteria.
>
> **W-2 found and fixed cancellation's real root cause** rather than working around it: `agent_run`
> used a blocking `subprocess.run` and never created a process group, so there was nothing to kill —
> which is why cancellation had never existed. It is now `Popen(start_new_session=True)` with
> process-group SIGTERM → grace → SIGKILL, proven against a real spawned subprocess rather than a mock.
>
> **What was narrowed or deferred (stated here so it isn't quietly re-claimed later):**
> `runs.cancel` writes **no audit entry** (W-4's card now owns it) · resuming a task that crashed
> mid-parallel-group **re-runs the whole group**, not just the incomplete members · approval gates
> are **rejected inside a parallel group** as a configuration error, not supported · W-4 (durable
> scheduling, event triggers, `dispatch --follow`) and W-5 (structured handoff artifacts) are not
> started, so hops still exchange concatenated raw text and Phase 17's C-1 stays blocked ·
> `maxReworkCycles` still has no dedicated CLI setter · every Phase 14 carried-forward gap in
> TODO.md's "Known-open gaps" list is still true unless named above.
>
> **Two integration defects were caught by cross-checking, not by the gates**, and both would have
> shipped silently: a golden conflict whose either-side resolution deletes a shipped command from
> the completion surface (twice — `roles`/`mcp`, then `pipeline`/`workflow`; no single side ever had
> the right set, so the golden must be **regenerated**, never picked), and `specs/README.md`'s index
> table taking a stale side that downgraded three spec versions and dropped a row. Both are now
> standing integrator checks in TODO.md.
>
> **A CI-blocking guard was found failing open.** `scripts/metrics.py --check` combined comma-blind
> `(\d+)` claim regexes with a silent skip for unmatched claims, so once the suite crossed 1,000
> tests it verified **nothing** while still reporting success — and an earlier README cleanup had
> removed 3 of its 4 claims from the prose. Every "metrics in sync" line reported during Phase 14 was
> therefore meaningless (the test counts themselves came from pytest and were accurate). Fixed:
> claims accept thousands separators, and a README stating **none** of the tracked metrics is now a
> hard failure rather than a silent pass. The repaired guard immediately caught real drift.

---

### PHASE 17 — Platformization IV: context engineering & memory management  *(☑ COMPLETE — all 5 cards C-1…C-5 shipped; C-3/C-5 closed it 2026-07-31)*

> **Why:** the audit found no tokenizer, no retrieval, no summarization anywhere — context is
> markdown written once plus prose contracts the *daemon's* forced-read enforces, and the only
> prompt docket composes grows unbounded. Memory lifecycle ops are destructive deletes. Durable task
> state is split-brained: `TASK_LIST.json` (machine-read) vs `HEARTBEAT.md` (what the reset contract
> points the model at) — disjoint, never reconciled. Org specialists get no contract files at all
> and doctor never heals them.

**Cards:** **C-1 · context compiler** — pure function (task, role, artifacts, workspace) → hop
message under a per-role token budget; priority order, deterministic truncation, chars/4 estimator
(tokenizer optional extra); composition logged per hop · **C-2 · memory distillation** — `maintain
distill` summarizes daily logs into MEMORY.md and archives originals; `clean/reset` gain
`--distill-first` (default on) — never bare-delete; the summarization turn runs **through the
driver** (D-18), docket's first self-originated LLM use, zero new SDK deps · **C-3 · one durable
task state** — dispatch writes HEARTBEAT entries mechanically at enqueue/start/finish; doctor flags
TASK_LIST⇄HEARTBEAT divergence; the durability contract stops being pure prose · **C-4 ·
specialists join the contract** *(DONE — pulled forward on `pc/c-4`, no Phase 14 dependency)* —
org specialists (security, knowledge, manager, and the opt-in Portfolio Manager) now get the
same full workspace contract (HEARTBEAT.md, WORKFLOW_AUTO.md, memory/) as project agents, and
`docket doctor` heals a specialist workspace left bare by a pre-C-4 install, closing the
projects-only healer gap; see `workspace-structure.spec.md` v1.2.0's own changelog · **C-5 ·
conversation registry auto-population** — dispatch/serve update `last_message`/`task_ref` (the
deferred TC item).

**Exit criteria:** no dispatch prompt exceeds its configured budget (test-pinned); `maintain reset`
on a workspace with content produces a distilled MEMORY.md + archive, not a void; a mid-task
context reset finds the task in HEARTBEAT because docket wrote it there; doctor heals a specialist
workspace; suite green.

---

### PHASE 18 — Platformization V: runtime-driver port, LLM agnosticism & MCP  *(☑ COMPLETE — L-1/L-2/L-3/L-6 shipped; L-4 and L-5 both answered as spikes, 2026-07-30)*

> **Why:** provider-agnosticism was declared complete (Phase 6) but the audit found Anthropic
> hardcoded in the rank anchors (non-overridable), the auth commands, and the preset/pricing gaps —
> and the runtime coupling half-escapes the ACL. MCP is entirely absent while it has become the
> ecosystem's tool-interop standard. Decisions D-14/D-18 govern this phase.

**Cards:**

- **L-1 · RuntimeDriver port (D-14)**: typed protocol — `run_turn / provision / teardown /
  list_sessions / usage / capabilities`. Session-JSONL/`trace_ingest` format knowledge moves
  **inside** the OpenClaw driver (closing the biggest ACL leak); the ACL guard test extends to
  session-format parsing; a fake driver replaces ad-hoc test shims. **One shipped driver.**
- **L-2 · Finish provider agnosticism** *(DONE — pulled forward on `pc/l-2`, no Phase 14
  dependency)*: registry-overridable rank anchors; `--provider` on auth commands; `local`/
  `ollama` presets; OpenRouter/local pricing rows or an explicit `n/a` row type; deleted the
  dead-end guidance strings (`cli/_provider.py`'s `models set task` reference and its raw-
  openclaw instruction) and single-sourced the duplicated `openclaw-gateway.service` constant
  (`core/utils.py` now forwards to `edges/adapters/system.py`'s `GATEWAY_UNIT`); reconciled the
  eval harness's daemon-JSON parser (`tests/evals/lib/eval-helpers.sh`) to the ACL's real
  `result.payloads[0].text`/`result.meta.agentMeta.usage` shape. See
  `tests/python/test_provider_agnosticism.py`; `model-profiles.spec.md` v2.3.0 and
  `cli-interface.spec.md` v1.6.0 already carry this card's spec updates.
- **L-3 · docket as an MCP server** *(pure docket, high leverage)*: `docket mcp serve` (stdio,
  official `mcp` SDK pinned) exposing the control plane as tools — `status, pods, queue, delegate,
  dispatch, runs, approvals list/grant/deny, cost` — every call audit-logged, approvals unchanged.
  Claude Code/Codex/any MCP client can drive docket *through* its governance spine, not around it.
- **L-4 · [daemon-gated spike] MCP config plumbing for agents**: if the daemon consumes MCP server
  config, `docket mcp add <agent> <server>` writes it via the driver + doctor checks it; if not,
  file upstream (L-3 ships regardless).
- **L-5 · [spike] wrapped gateway (D-18)**: evaluate a LiteLLM-class sidecar the daemon's provider
  config points at — central keys (ending plaintext `.env` fan-out), per-call metering (fixing cost
  observability at the root), failover, caching. Ship only if the daemon tolerates a base-url swap
  cleanly; otherwise metering stays L-1 `usage()` + R-5 estimates. Hand-rolled provider clients:
  banned (D-18).

**Exit criteria:** `core/` contains zero OpenClaw on-disk-format knowledge (guard-tested); an MCP
client can list pods, delegate a task, and approve a gated action end-to-end with audit entries for
each; `docket models` shows no hardcoded-Anthropic residue for a non-Anthropic fleet; suite green.

**Full-program scope guard (all five phases):** a full MCP *host* (docket executing MCP tools inside
agent turns) is the standalone-runtime trap — refuse it; microVM/multi-host/dashboards stay §7
Backlog; every control keeps its one-word label (*docket-enforced / daemon-enforced / convention*).

---

---

## Prioritization ruling — viable vs overengineering (2026-07-31, decision D-24)

**Context.** The goal was stated as **a factory for agentic products** (D-20). Phases 20 and 21 had
been drafted the same day from a generic "what a good agent platform has" reading. They were
re-scored against the answered goal and against §4.5's anti-overengineering test — *not* "is this
best practice for someone", but **"does a measured need in this system ask for it"**.

**Roughly half was cut, including items the integrator had recommended hours earlier.** That is the
point of writing the rule down: it has to bind the person applying it.

| Item | Verdict | Reason |
| --- | --- | --- |
| **P19-6 / P19-7** removal wave | **DO — first, nothing else counts until it lands** | The daemon still resolves `OpenClawDriver`. Every runtime claim is theoretical until this flips, and D-21 is explicitly forbidden before it |
| **P21-1** runtime package split | **DO — this *is* the factory's product line** | If every product is agentic, the runtime is the common part of every product. Packaging only (D-21 constraint 2) |
| **P19-12** per-role tool sets + identity | **DO** | Converts an *instruction* ("Reviewer, don't edit code") into a *guarantee* (the tool is absent). That distinction is the thing docket sells |
| **P19-13** `docket mcp servers` CLI | **DO — S** | ~30 lines of CLI over library functions P19-10 already shipped and tested. Makes browser + web search **configuration, not code** |
| **P19-11** `fetch` tool | **DO** | Table stakes for an agentic-product runtime, and the inspectable egress path |
| **P21-5** `agentic-product` blueprint | **DO — XS** | A row in `BUILTIN_BLUEPRINTS`. The scaffolding primitive a factory needs **already exists**; this is data, not machinery |
| **P20-4** `runs cancel` audit entry | ~~**DO — XS**~~ **ALREADY SHIPPED** | The gap it was written against had already been closed by W-4. Nothing to do; see the card below |
| **P20-2** guardrail + loop metrics | ☑ **SHIPPED** (2026-08-04) | Denial rate and approval wait are the two numbers an operator would actually open |
| **D-23** egress lockdown | **DEFER** | Off by default, breaks `npm`/`pip`/`git` when on, no measured need. Buys a config option, not a guarantee |
| **P20-3** fleet trace query + retention | **DEFER** | `grep` over JSONL is adequate at this fleet size. Retention returns when a disk fills, which is a fact, not a forecast |
| **P20-1 OpenTelemetry** | **CUT** | **Reversing the integrator's own recommendation.** Correct at platform scale; this is one host and one operator, with JSONL traces and six Prometheus metrics already shipped. Importing a platform-team solution into a one-operator system is textbook overengineering. Revisit at a second operator or a real dashboard |
| **P21-2** streaming | **CUT until a product asks** | Only served the hosted-runtime reading D-20 rejected. Agentic *backends* do not stream |
| **P21-3** tenant axis | **CUT — see D-22** | Same. An embedding product owns its own tenant model |
| **P21-4** build-agent profile | **DEFER** | Real the moment an Android/Unity product exists. Pre-building for a hypothetical product is the definition of speculative |
| Browser automation tooling | **NEVER BUILD** | Point MCP at Playwright. This is what "rent the protocol" was for |

**The single biggest overengineering risk in the plan as drafted** was Phase 21 read as a bundle —
packaging *plus* streaming *plus* a tenant axis. Packaging is the asset; the other two are a hosted
product nobody asked for.

---

## PHASE 19 — docket takes the runtime (D-19)  *(☑ COMPLETE — all 13 cards, waves 8–11, closed 2026-08-03)*

> **This section was written retroactively on 2026-08-05**, because the phase that changed docket
> most had no section at all — only scattered references and a record in TODO.md. The per-card
> detail lives in TODO.md's wave 8–11 blocks and in §Changelog; this is the durable summary.

**The decision (D-19): own the loop, rent the protocols.** A clean break — no daemon compatibility
layer, no migration path. docket now owns the turn loop, the tool registry, all three policy hooks,
approvals, audit and sessions. It rents only protocols: an OpenAI-compatible HTTP endpoint (stdlib
`urllib`, zero new deps), MCP for pluggable tool servers, and containers for isolation.

**Why it had to happen, and this is the durable lesson.** docket shipped four `pre_tool_call` policy
templates that had **never once been evaluated**, because the external daemon owned the inside of a
turn. The wrap boundary was not merely limiting the roadmap — it was making the product's central
claim false. *Whoever owns the loop owns the interception points.* That is also why agent frameworks
(LangGraph/CrewAI/AutoGen) are rejected on principle: they own the loop, and therefore the gates.
See §4.5's build-vs-wrap box, which records the reversal rather than deleting the old reasoning.

**The 13 cards:**

| Card | What it delivered |
| --- | --- |
| P19-1 | `core/llm.py` chat port + `edges/adapters/llm.py` — the only module that knows the wire format |
| P19-2 | `core/tools.py` — **the gated tool registry and the single chokepoint** |
| P19-3 | Turned on `pre_tool_call` — the hook whose templates had never run |
| P19-4 | `core/session.py` — durable turn history + compaction that never splits a tool-call/result pair |
| P19-5 | `core/agent_loop.py` + `DocketDriver` — the bounded turn loop |
| P19-6 | docket-native home (`~/.docket`) + fleet registry, single writer |
| P19-7a/b | **The runtime cutover** — the removal spine; `restart_gateway()` and ~15 ceremonial call sites deleted |
| P19-8 | **docket-owned Telegram** — a real approval channel, writing `channel="telegram"` to the audit chain |
| P19-9 | Sandboxed exec for `bash` (docker/bwrap argv) |
| P19-10 | MCP client — pluggable tool servers, gated like a built-in |
| P19-11 | `fetch` tool — domain-allowlisted, **deny-by-default** (D-23 re-scoped: ship `fetch`, defer the lockdown) |
| P19-12 | Per-role tool sets + identity composition — `denied_tools` as **data**, making a Reviewer *unable* to write |
| P19-13 | `docket mcp servers` CLI |

**Acceptance test for the whole phase:** `command grep -ril openclaw src/` returns only comments and
docstrings narrating the removal — zero live string literals.

**What the phase made true:** the four never-evaluated policy templates are live, and Telegram became
a real approval channel — reversing a caveat carried since Phase 15.

**Two of its cards left wires unfinished, and both were closed later** — recorded here because the
pattern repeated: **P19-10 shipped `load_mcp_tools` as a tested but never-called library** (closed by
W17-1, 2026-08-05), and P19-9's sandbox was likewise reachable only if something set
`ToolContext.sandbox`, which nothing did (closed by W18-3, same day). *Machinery implemented, tested,
and not wired to the default path* is this phase's characteristic failure mode — see CLAUDE.md's
review heuristic.

---

## PHASE 20 — Fleet observability  *(☑ COMPLETE at cut scope — D-24 cut ~half; P20-2 shipped, P20-4 was a phantom card)*

**Why after, not before.** Instrumenting code that P19-7 is about to delete is waste. Phase 20
starts once the daemon is gone and the shapes are final.

**Scope after D-24: two small cards, not four.** P20-1 (OpenTelemetry) is **cut** and P20-3 (fleet
trace query + retention) is **deferred**; what remains is P20-2 and P20-4, both S-or-smaller. The
gap list below is kept in full because the gaps are real — being deferred is not the same as being
untrue, and a future trigger should find the measurement already written down.

**What already exists** (do not rebuild it): per-project/session JSONL traces with hop *and*
per-tool-call events (`docket trace`), a hash-chained tamper-evident audit log (`docket audit
verify`), a dispatch run registry with cancellation (`docket runs`), six Prometheus metrics and a
versioned read API (`/status.json`, `/health`, `/runs`, `/runs/<id>`, `/approvals`), token/cost
reporting (`docket cost`), session success-rate metrics (`docket metrics`), and fleet diagnostics
(`docket doctor`). That is a stronger base than either LangGraph or CrewAI ships by default, because
it was built for unattended operation.

**The measured gaps:**

1. **No fleet-wide view.** Traces are per-project files; there is no "every denied tool call across
   all pods this week".
2. **No OpenTelemetry.** The industry standard is absent, so nothing feeds Grafana/Jaeger/Honeycomb
   without docket building a UI it would then have to maintain.
3. ~~**The P19-5 loop is not in the metrics.**~~ — **closed by P20-2** (wave 13): tool-call rate,
   denial rate, approvals by channel and policy-hit counts by id are all exported.
4. **No latency anywhere.** No p50/p95 per role — a slow model and a stuck agent look identical.
   **Partly closed by P20-2**, which exports `docket_turn_duration_seconds` as a `_sum`/`_count`
   summary. Percentiles are still absent, and deliberately so: only `session_start`/`session_end`
   brackets exist, so a p95 would be invented rather than measured. Real percentiles need a
   per-turn timestamp that nothing records yet.
5. ~~`docket runs cancel` still writes **no audit entry**~~ — **already closed by W-4** (`7e9ddab`,
   2026-07-30), which shipped the entry, four tests and the spec bump on the *same day* this gap
   list was written. Recorded as open here, and again as card P20-4 below, because neither was
   re-trued afterwards. The gap was never real; see P20-4.
6. **No trace retention policy.** JSONL grows without bound.
7. **No agent-quality regression detection** — the eval harness is non-blocking spot checks.

**The design rule for this phase: emit spans, do not build a dashboard.** Model one turn as
`turn -> iteration -> tool_call` with the gate decision as a span attribute, export OTLP, and every
existing observability tool works. **Keep telemetry and the audit log separate** — telemetry is
sampled and lossy by design, an audit log must be neither. Conflating them is a common and serious
mistake.

**Golden signals for an agent fleet** (what the metrics cards must cover): turn latency, tool-call
rate, **denial rate**, **approval wait time**, token burn rate, and **cost per completed task** —
per *task*, not per agent, because that is the number that means something.

### Cards

**P20-1 · OpenTelemetry spans + OTLP export** — *❌ CUT (D-24)*
Was: a `turn -> iteration -> tool_call` span tree with the gate decision as an attribute, exported
OTLP. **Cut, reversing the same-day recommendation that proposed it.** The design advice behind it
stays correct — *emit spans, do not build a dashboard* — but it is advice for a fleet with more than
one operator and somewhere to send the spans. docket has JSONL traces carrying hop **and** per-tool-call
events, plus six Prometheus metrics and a versioned read API. **Trigger to re-open:** a second
operator, or a real Grafana/Jaeger/Honeycomb backend that someone will actually watch. Not "it is
the industry standard".

**P20-2 · Guardrail + loop metrics** — *☑ SHIPPED (2026-08-04, wave 13) · S*
Denial rate, approvals granted/denied/timed-out **by channel**, policy-hit counts by policy id,
tool-call rate, turn latency. Extends the existing Prometheus surface; **no new endpoint** and no new
dependency. These are the numbers an operator opens after an incident, which is why this survived the
cut that removed OTel: it is the *signal*, without the *transport project*.

Shipped as four families — `docket_tool_calls_total{decision}`, `docket_policy_hits_total{policy_id,
hook,action}`, `docket_approvals_total{channel,outcome}`, and `docket_turn_duration_seconds` (a
summary with **no** quantiles; there is no per-turn timestamp to build honest percentiles from, only
`session_start`/`session_end` brackets).

**The design call worth keeping:** every number is recomputed from durable records at scrape time —
trace JSONL for tool calls, policy hits and session brackets; the audit log for approvals by channel.
`docket serve` is not a long-lived process holding counters, so an in-memory store would silently
zero on restart and a persisted one would be a second source of truth free to drift from what is on
disk. Deriving means every metric is traceable back to a record an operator can `grep`. Telemetry
still never writes *through* the audit log — it only reads it.

**One `core/tools.py` change, scoped exactly:** `_audit_tool_decision` now takes `policy_id`/
`policy_action` as structured keyword fields instead of burying the hit in free text, so `/metrics`
can attribute a policy hit by id without parsing prose. `evaluate_tool_call` — the gate itself — is
untouched: no decision changes, no second execution path, no reordering of the classifier/policy
sequence, and `audit_log` stays best-effort and never-raising, so recording cannot affect whether a
tool runs.

**Two limits documented rather than implied.** (1) `audit.log` rotates at `AUDIT_LOG_MAX_BYTES` to a
single-generation backup and `read_audit` sees only the current file, so `docket_approvals_total` and
the `pre_tool_call` slice of `docket_policy_hits_total` **lose history on rotation** — and a counter
dropping to a *partial* value is misread by `rate()` as a reset plus real traffic. Fixing that is
retention design, which is P20-3's deferred scope. (2) Scrape cost was **measured, not asserted**: a
927KB / 10,000-event trace corpus plus an audit log at the 5MB ceiling renders in ~60ms. Fine today,
`O(trace + audit bytes)`, no cache added, threshold named.

**P20-3 · Fleet trace query + retention** — *⏸ DEFERRED (D-24)*
Cross-project query (`docket trace --fleet --json`) plus a documented retention/rotation policy, the
way `AUDIT_LOG_MAX_BYTES` already handles the audit log. Both gaps are real; neither is felt yet at
this fleet size, where `grep` over per-project JSONL answers the question. **Trigger:** a disk that
actually fills, or a cross-pod question asked twice.

**P20-4 · `runs cancel` audit entry** — *☑ NO-OP (2026-08-03) · the gap was already closed*
Was: closes the W-4 gap — a cancellation is a human decision that killed running work, so it belongs
in the audit log.

**It was already there.** Dispatched in wave 13 and the agent found the work shipped: `core/runs.py`'s
`cancel_run` has written `audit_log("runs.cancel", run=… project=… was=… killed=…)` since **W-4**
(`7e9ddab`, merged 2026-07-30), with four tests in `test_runs_cli.py::TestRunsCancelAuditEntry`
(entry on success · none on unknown id · none on already-terminal · chain still verifies) and the
change recorded in `audit.spec.md`'s own 2.3.0 changelog. **Zero commits on `pc/p20-4`.**

**Why the board was wrong, which is the part worth keeping.** W-4 closed the gap on 2026-07-30 —
the same day Phase 20's gap list was written recording it as open. The gap list was never re-read
against the tree afterwards, so the false entry was promoted into a card, survived D-24's
prioritization pass (where it was *kept* over OpenTelemetry on the strength of a premise nobody
re-checked), and was scheduled into a wave. **A gap list is a claim about the tree and decays like
any other; re-verify one before you schedule work against it, not after.** The card cost one agent
dispatch to disprove — cheap, but only because the agent checked instead of building a second
`audit_log` call next to the first.

Two design points the agent settled while proving it, both correct as shipped: `cancel_run` is the
single chokepoint (`grep` confirms exactly one caller, `cli/_runs.py:152` — no HTTP, MCP or serve
path cancels), and the entry carries **no** `channel` field, unlike `approval_grant`/`approval_deny`.
With one caller and one possible value, threading a channel today would be speculative generality;
adding an HTTP or MCP cancel path is the trigger, not before.

---

## PHASE 21 — The product substrate  *(☑ COMPLETE at cut scope — P21-1 + P21-5 shipped; the rest cut by D-24)*

**D-20 is answered: a factory for agentic products, so both — factory first, substrate second.**
Phase 21 is therefore live, and **two cards wide, not four**.

**The thesis, now committed:** split into an embeddable `docket-runtime` library plus the `docket`
control plane built on top of it. Every agentic product the company ships then inherits one gated
tool chokepoint, one policy engine, one approval store and one audit chain — rather than each product
team reinventing guardrails badly. Verified 2026-07-31: the runtime slice imports only `pydantic` and
`filelock`, and `core/`/`edges/` contain no CLI dependency at all, so this is packaging and a public
API contract, **not** a rewrite.

**Two sequencing constraints, both hard:**

1. **After Phase 19's removal wave, never before.** Publishing a library that still reaches for
   `openclaw.json` would freeze that coupling into a public contract.
2. **Packaging only.** P21-1 draws a boundary around code that exists and pins it with a test. It
   does **not** design new API surface, add extension points, or generalise anything. A package split
   that grows features is exactly how this becomes the overengineering D-24 cut everything else to
   avoid.

### Cards (Phase 21)

**P21-1 · Package split** — *TODO (unblocked) · M*
`docket-runtime` (library) + `docket` (control plane). Public API contract, versioning policy, and a
test proving the library imports nothing from `cli/` — the same shape as the existing
`test_no_subprocess_in_core.py` boundary guard, and it must be **seen to fail** on a planted
import before it counts as evidence.

**P21-5 · `agentic-product` pod blueprint** — *TODO · XS*
The factory's scaffolding primitive **already exists**: `core/blueprints.py` ships `software`,
`research`, `content` and `ops` as declarative data (`BUILTIN_BLUEPRINTS`, `WORKSPACE_KINDS =
{codebase, workdir}`, `DEFAULT_BLUEPRINT = software`). A product that *ships an agent* is a fifth
row, not new machinery — a pod shape whose scaffolded repo embeds `docket-runtime` and inherits the
gated chokepoint from day one. **Deliberately XS**: if this card starts growing code, it has stopped
being a blueprint and should be stopped. Depends on P21-1 for the embed target.

**P21-2 · Streaming** — *❌ CUT (D-24)*
Was: streaming `ChatBackend.complete` for user-facing agent UX. It only ever earned its place under
the hosted-runtime reading of D-20, which the answered goal rejects — agentic *backends* do not
stream, and an embedding product owns its own serving layer. `ChatBackend.complete` stays
deliberately non-streaming (P19-1). **Trigger to re-open:** a real product with a human watching
tokens arrive.

**P21-3 · Tenant axis** — *❌ CUT (D-22, D-24)*
Was: an end-user/tenant key alongside `project`, threaded through session storage, traces, audit
entries, approval records and budget accounting. Cut for the same reason as P21-2. **The original
warning stays on the record and stays true** — retrofitting the key is expensive, so this is a
genuine bet, not a free cut: the bet is that docket serves *products*, and each product serves its
own customers. **Trigger:** docket itself serving more than one end customer from one host.

**P21-4 · Build-agent profile** — *⏸ DEFERRED (D-24) · M*
Real the moment an Android or Unity product exists, and the measurement behind it is worth keeping:
today's tools are tuned for editing text — `read`/`write`/`edit` are **text-only** so binary assets
are invisible, `bash` defaults to a 120s timeout that a Gradle or Unity build blows straight through,
and tool output caps at 30k characters. A build agent is a different animal from a code-editing agent
(long timeouts, artifact handling, binary-safe file ops, no browser). **Trigger:** a real build to
run. Pre-building it for a hypothetical product is speculative by definition.

### Honest input on product mix (record it; it affects planning, not code)

Agent leverage is **not** uniform across the product types named:

| Product type | Agent leverage | Why |
| --- | --- | --- |
| B2B SaaS backends, APIs, integrations | **High** | Text in, text out, verifiable by tests |
| Web frontends | Medium | Verifiable, but visual judgment is weak |
| **Android / video games** | **Low** | Game feel, art and device QA are not text problems; no emulator or visual QA exists |

Plan capacity accordingly. Expecting the same leverage on a game as on an API backend is the kind of
assumption that quietly wrecks a roadmap.

---

## PHASE 22 — Control-plane write API for an external plan-of-record  *(☑ COMPLETE — all 6 cards, wave 16, 2026-08-04)*

**What triggered this.** The backlog has said since Phase 11 that docket **does not build a
dashboard of its own** — it "competes on the *write/governance* side and **feeds** them via a read
API". That consumer now exists and is ours: **Tack** (a sibling repository, the single-binary
Rust/SolidJS project manager) is adding an agent-factory control center — Phases 33–38 in its
roadmap, with executable cards in its `TODO.md`. Tack holds the plan of record (roadmap, board,
sprints, dependency DAG, per-project vocabulary); docket executes. A reconciler on Tack's side
polls docket and folds runs, approvals, traces and metrics back onto the board.

This phase is docket's half of that contract. It is deliberately **five small cards**, and it is
scored against §4.5 and D-24 the same way everything else is: *does a measured need in this system
ask for it* — here, yes, because a real consumer is blocked on each card, by name, today.

**What already exists and must not be rebuilt.** The read side is essentially complete:
`/status.json`, `/health`, `/metrics`, `/runs`, `/runs/<id>`, `/approvals`, plus
`POST /dispatch/<project>` and `POST /approvals/<token>`. Tack's Phases 33, 34 (partly), 36 and 38
consume that surface **unchanged** and ship without any docket change at all. What follows is only
the asymmetry: things reachable from the CLI or MCP but not over HTTP.

**The design rule for this phase: expose what `core/` already does, add no new behaviour.** Every
card below is a `serve.py` route over an existing `core/` function, with the same Bearer auth, the
same policy hooks and the same audit entries the CLI path produces. A card that starts designing new
semantics has stopped being this phase.

### Cards (Phase 22)

**P22-1 · `POST /tasks/<project>` — enqueue over HTTP** — *TODO · S · **blocks Tack Phase 35***
The gap that matters most: **there is no HTTP way to enqueue a task.** `POST /dispatch/<project>`
dispatches an *existing* queue (`effective_pipeline` → `resolve_variables` → `dispatch_pod`);
creation lives only in `core/dispatch.py::enqueue_task`, reachable from the CLI (`docket pod X
delegate`) and the MCP `delegate` tool. Body `{description, priority, trusted}` → `enqueue_task` →
`{taskId}`. Must honour the `pre_input` policy gate exactly as the CLI path does: a `block` verdict
returns 4xx naming the policy id, and a `require_approval` verdict returns the task in
`waiting_approval` with its token — not a 200 that pretends the task is queued.

**P22-2 · `GET /tasks/<project>` — the pod queue as JSON** — *TODO · XS*
`read_tasks(project)` already returns exactly the normalized shape. A route over it, Bearer-gated.
Tack shows queue depth per pod in its fleet view; today that number is only reachable by shelling
out.

**P22-3 · `GET /traces/<project>?since=<cursor>` — cursor'd trace read** — *TODO · S*
**This is P20-3's trigger firing, and it should be recorded as such rather than quietly
re-litigated.** P20-3 (fleet trace query) was deferred by D-24 on the reasoning that "`grep` over
JSONL is adequate at this fleet size" — which was true for a human operator and is false for a
programmatic consumer that needs to resume from where it stopped. Cursor-based, returning the JSONL
events verbatim. Do **not** build the fleet-wide query UI P20-3 described; one project, one cursor,
raw events out. Tack does the aggregation, which is the whole point of feeding a consumer instead of
building a dashboard.

**P22-4 · `channel="tack"` on approval decisions** — *TODO · XS*
`POST /approvals/<token>` hardcodes `channel="http"`. Accept an optional channel label from a
recognised set and record it. Without this, every approval granted from Tack's board is
indistinguishable in the audit chain from a CI job's — and the audit chain's whole value is that its
provenance is honest. Approvals are already the one place docket tags the channel; this keeps that
true as a fifth surface appears.

**P22-5 · `POST /pods` — provisioning over HTTP** — *TODO · M · **blocks Tack Phase 37***
`docket add` is CLI-only. Tack's "one click creates a product" flow needs `{project, path,
blueprint, pod, budget, verifyCmd}` → the pod roster. **This is the one card here that can grow, and
it should be watched:** provisioning touches workspace creation, port-range and scratch allocation,
git worktrees and the startup contract. Constraint — it calls the same `core/` provisioning path
`cli/_agents.py` calls, and adds no options that the CLI does not already have. If it starts
growing its own flags, stop and reconsider. A partial failure must leave nothing behind; Tack rolls
back its own project on a non-2xx, and cannot roll back a half-created pod for us.

**P22-6 · Trace retention** — *TODO · S*
Un-defers the retention half of P20-3, and the reasoning has genuinely changed rather than merely
been re-argued: once Tack durably ingests trace events (P22-3), docket's JSONL becomes a cache
rather than the only copy, which makes deleting it **safe** rather than lossy. Bounded by age, with
the audit log explicitly out of scope — telemetry is sampled and lossy by design, an audit log must
be neither, and conflating them is the mistake Phase 20's design rule already names.

**P22-7 · MCP tools in a live turn** — *not new scope; recorded for its consequence*
The known defect (CL-wave record: `load_mcp_tools` is never called, `DocketDriver.registry_factory`
defaults to `builtin_registry`) means **docket's agents cannot call Tack's MCP server from inside a
turn**, so they cannot self-report progress onto the board. Tack's design deliberately does not
depend on this — its reporting comes from the dispatch lifecycle (runs + traces), and its
`orch_tasks` link table makes agent self-reporting a drop-in the day the wire lands. Recorded here
so the dependency is visible, not to re-card work that is already tracked.

**P22-8 · `pipeline validate` over HTTP** — *TODO · S · found by Tack card D3 (2026-08-05)*
`docket pipeline validate <file>` (`cli/_pipeline.py::_validate`) is a thin CLI wrapper over
`core.pipeline.validate_pipeline(text) -> list[str]` — pure, already UI-free, already the single
source of truth for "is this a valid docket pipeline." `serve.py` exposes no route for it (checked
every `do_GET`/`do_POST` branch directly; the closest existing thing, `POST /dispatch/<project>`,
*runs* a pipeline, it doesn't just check one). Tack wants to validate a template's stored pipeline
YAML at save time (its "pipeline library," task 37.3) without maintaining a second, drift-prone copy
of `PipelineSpec`'s schema in Rust — exactly the mistake P20-3-style client reimplementation already
cost this project once (Tack's own B2/R1 history). Today Tack can only check that stored YAML
*parses*, not that it's a valid pipeline, and says so explicitly rather than claiming a stronger
guarantee it can't back up.

A route is a small, low-risk addition: `POST /pipeline/validate` (or a query-string variant of an
existing path), body = raw YAML text, `{ok: bool, errors: [str]}` — no project, no pod, no auth
even, mirroring `validate_pipeline`'s own signature exactly (it takes no project argument today).
Unlike P22-5, this one genuinely cannot grow: `validate_pipeline` already exists, already takes
exactly one argument, and already returns exactly the list Tack wants to show the operator. The
route is a `do_POST` branch and nothing else.

**Acceptance:** `POST /pipeline/validate` with a well-formed pipeline body returns `{ok: true,
errors: []}`; a body with a duplicate step id, an unknown rework target, or invalid YAML returns
`{ok: false, errors: [...]}` with `core.pipeline.validate_pipeline`'s own messages, unchanged. Tack's
card D3 should switch its template save-time check from a bare `serde_yaml` parse to this route the
day it ships (see TODO.md's Tack repo, §6 "D3" handoff, for the client-side half of this gap).

### What this phase does *not* do

- **No dashboard.** Unchanged from the Phase 11 backlog ruling. Tack renders; docket serves data.
- **No push/webhook to Tack.** Tack polls. Pull survives docket restarts, missed deliveries and Tack
  downtime with no queue and no replay logic on either side. Revisit only if a measured latency
  complaint appears — one poll interval (10s default) has not produced one.
- **No auth model change.** Same single Bearer token, same 0600 token file. Tack stores it
  write-only, the way it already stores its S3 secret.
- **No tenant axis.** D-22/D-24 stand. Tack is one operator's control center, not a tenant.

**Definition of done:** Tack's Phase 35 sprint dispatch drives a real pod through Lead → Implementer
→ Reviewer → Tester and the card lands in Done by itself; a Tack-granted approval shows up in
`docket audit verify` tagged `channel="tack"`; `docket list` and Tack's fleet view agree after a
wizard-provisioned product.

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
  destination until then (see §0).
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

### Changelog

- **2026-08-31 (Wave 26 C11 accepted / Wave 26 closed) — the public release story now matches the
  executable product from immutable artifact to governed turn.** RED commit `dcce5b2` locks the
  install, provider, first-turn, runtime-embedding, known-limit, and stale-claim contracts; GREEN
  commit `f9a4086` reconciles the landing page, quickstart, provider, command, compatibility,
  security, installation, example, and spec-index surfaces. The artifact-only route and runtime
  example pass without checkout imports. Closure passes the 2,451-test collection (2,446 passed,
  five contract-labelled skips), Ruff/format, strict mypy over 74 source files, ShellCheck, 24
  specs, 18 goldens, synchronized metrics, dependency-floor artifact checks, deterministic smoke,
  and the exact-wheel release journey. The active board is clear; Wave 27 remains trigger-driven
  triage, not executable work.

- **2026-08-31 (Wave 26 C4 accepted) — the exact installable artifact now reaches a governed first
  turn on Linux and macOS.** RED commit `f8f897e` defines three artifact-installed release-journey
  contracts; implementation commit `6c52df7` builds and installs the exact wheel in an isolated
  venv outside the checkout, rejects source leakage, configures the public provider, initializes a
  project, executes one governed tool effect, and verifies measured usage plus durable
  task/run/session/trace/audit evidence. The blocking GitHub Actions matrix passes on Ubuntu and
  macOS, alongside 2,445 tests with five contract-labelled skips, Ruff/format, strict mypy over 74
  source files, workflow YAML, dependency-floor artifacts, 24 specs, 18 goldens, metrics, and
  deterministic smoke. C11 is now the sole ready, integrator-only Wave 26 truth pass.

- **2026-08-31 (Wave 26 C3 accepted) — tagged release artifacts are immutable and verified before
  installation or publication.** The release workflow builds and clean-installs the exact wheel and
  sdist, emits SHA-256 verification data and an SPDX SBOM, requests build provenance, and separates
  protected publication from artifact construction (`0251972`, `5bb106a`). The remote installer
  rejects tampered bytes before extraction, while Homebrew uses the same versioned asset with a real
  checksum and Apache-2.0 metadata. Preserved diagnosis showed the earlier smoke failure was caused
  by invoking `.venv/bin/python` without adding that venv to child `PATH`; the documented canonical
  `uv run python` command completes the approval/resume workflow. Commit-level closure passes 2,442 tests with five
  contract-labelled skips, Ruff/format, strict mypy over 74 source files, ShellCheck, workflow YAML,
  24 specs, 18 goldens, metrics, clean dependency-floor artifact installs, tamper rejection, and
  canonical deterministic smoke. C4 is now ready; C11 waits only on C4.

- **2026-08-31 (Wave 26 C0 accepted) — `main` is now the single public/default release
  lineage.** The maintainer authorized promotion of the current `platform` history. GitHub already
  identified `main` as default; the preflight proved `platform` was a strict 300-commit
  fast-forward with no `main`-only commits. Both refs were synchronized without force push or
  history rewrite. D-31 records that tags/releases originate from `main`; C3 now owns immutable
  tagged artifacts and the remaining mutable installer/formula inputs.

- **2026-08-31 (Wave 26 C10b accepted) — owned runs now stop cooperatively at every unstarted
  model, approval-continuation, and tool-handler boundary.** The persisted C10a signal now reaches
  `DocketDriver`, `run_agent_turn`, approval waits, and `dispatch_tool` (`3244fb2`, `d6eca09`). A
  response already in flight may finish, but cancellation discards it before the next side effect;
  an already-running handler completes its atomic unit while the unstarted batch remainder receives
  explicit `run_cancelled` results. Concurrent approval winners are preserved and cancellation is
  terminal/non-retryable. The four barrier races pass 50/50 repetitions; the committed closure
  passes 2,429 tests with five contract-labelled skips, Ruff/format, strict mypy over 74 source
  files, 24 specs, 18 goldens, metrics, the standalone runtime artifact boundary, and deterministic
  smoke. C10c is now ready.

- **2026-08-31 (Wave 26 C10a accepted) — cancellation requests are persisted truthfully across
  processes before an executor claims full stop.** The run id now identifies a typed signal whose
  additive lifecycle distinguishes request, observation, and stop; queued work stops atomically,
  running work stays nonterminal until `execute` returns, and one conditional registry transition
  resolves cancellation against terminal completion (`0d24f7a`, `dc69142`). Repeated requests do
  not re-signal or re-audit, malformed data fails closed, and unknown/legacy fields survive. The
  committed closure passes 2,424 tests with five contract-labelled skips, Ruff/format, strict mypy
  over 74 source files, 24 specs, 18 goldens, metrics, and deterministic smoke. C10b is now ready.

- **2026-08-31 (Wave 26 C5/C7/C9 accepted) — runtime distribution ownership and the remaining
  approval/conversation transitions are atomic.** `docket-runtime` now owns only
  `docket_runtime/`, rebuilds wheel and sdist outside the checkout, survives either coexistence
  uninstall direction, and exposes one versioned gated-tool facade (`cabad9e`, `55ef80b`). Approval
  resolution conditionally changes pending state once before the sole winner emits trace/audit
  (`7babf67`). Conversation writers and hop touches share one validated locked mutation boundary
  without schema growth or fabricated records (`790f578`). The committed-tree closure passes 2,416
  tests with five contract-labelled skips, Ruff/format, strict mypy over 74 source files, 24 specs,
  18 goldens, metrics, artifact ownership/floor checks, and deterministic smoke.

- **2026-08-30 (Wave 26 C2/C6/C8 accepted) — three isolated Terra lanes landed canonical
  packaging and atomic audit/resource transitions.** The root wheel and sdist now install the
  canonical `docket` executable from outside the checkout with aligned metadata and clean uninstall
  behavior (`2d3e713`). Audit rotation, head lookup, append/flush/close/permissions, and readers are
  one bounded inter-process transition with typed best-effort results and failure rollback
  (`4493874`, `6e6cfd3`). Pod provisioning serializes same-project attempts, allocates different
  projects atomically, and removes only attempt-owned rollback state (`f9c9fd5`). Integrated gates
  pass with 2,404 tests and five contract-labelled skips, Ruff/format, strict mypy, 24 specs, and
  18 goldens. C3 now waits only on C0, C4 waits only on C3, and C5 is ready under D-28.

- **2026-08-30 (Wave 26 W26-C1 accepted) — clean setup now reaches a governed turn through a
  resolvable provider.** Provider registration is fail-closed, unresolved presets cannot persist,
  first-project bootstrap validates the selected endpoint/model without exposing credentials, and
  coding-tool subscriptions are not treated as runtime API credentials. A provider-only fleet no
  longer bypasses foundation setup. The preserved keyless `127.0.0.1:8081` canary at
  `/tmp/docket-w26-c1-live-smoke-pa9AyI` completed the five-hop workflow, gated write, approval
  pause/resume, verification, and clean 11-record audit chain at zero cost. The deterministic
  closure gates pass with 2,391 tests and five contract-labelled skips, Ruff/format, strict mypy,
  24 specs, 18 goldens, metrics, and smoke. W26-C4 now waits only on C2 and C3.

- **2026-08-30 (Wave 25 integrated and closed) — the complete attributed tree landed at `6b925f0`
  and Phase 23 / Wave 26 activated.** The integration commit owns all 45 runtime, spec, test,
  documentation, skill, and handoff paths. Its closure gates passed with 2,377 tests and five
  contract-labelled skips, Ruff, format, strict mypy, 24 specs, 18 goldens, metrics, and the
  deterministic five-hop smoke. The active marker changed once; W26-C1, C2, and C6–C10 are ready,
  while C0 and dependency-bound cards remain blocked. The transition also added a focused snapshot
  regression so a completed prior wave cannot hide the newly active ready pool.

- **2026-08-30 (Wave 25 W25-C7 accepted) — the un-scripted memory-maintenance canary completed
  without violating the private-context boundary.** The preserved world
  `/tmp/docket-w25-c7-live-L8nkOm` distilled private decisions, repaired the isolated Git worktree,
  passed public and hidden acceptance, persisted five typed hops with `approve`/`pass`, exercised
  three in-turn approvals plus pipeline approval, and passed the durable trace/session privacy
  oracle and audit verification. Post-canary full deterministic gates pass. Wave 25 now has only
  dirty-tree integration and commit-level revalidation remaining before Phase 23 activation.

- **2026-08-30 (Wave 25 W25-C11) — configured verdict markers are placement-tolerant but
  ambiguity-intolerant.** The generic executor scans complete output line-by-line, accepts one
  distinct normalized marker wherever it appears, collapses identical repeats, and fails closed on
  absence, conflicts, or prose-only mentions. The normalized artifact verdict is reused on crash
  resume instead of reinterpreting model prose. Pipeline Format 2.2.0, Pod Dispatch 6.5.0, the full
  suite, and deterministic smoke pass; W25-C7 is ready for exactly one fresh serial live acceptance.

- **2026-08-30 (planning, no product code) — the CTO/OSS audit became Phase 23 rather than a generic
  feature backlog.** D-25 positions Docket as a governed single-host coding-agent runtime first and
  requires two enforcement-equivalent adapters before any framework-neutral claim. D-26 makes
  clean-install-to-first-governed-turn the release blocker; D-27 defines external-runtime
  governance as removal of native bypasses; D-28 permits the narrow runtime-package correction
  D-21 needs; D-29 records isolated multi-agent delivery and compact handoffs. W25-C11 owns the
  measured Reviewer-marker defect blocking W25-C7. Wave 26 is fully scoped but blocked behind Wave
  25/dirty-tree reconciliation; Waves 27–29 remain trigger-gated in the durable plan.

- **2026-08-19 (wave 24) — a realistic memory-backed Git canary found and closed three product
  defects hidden by the one-line/flat-workspace smoke.** The live scenario starts from two
  intentional checkout regressions in a committed repository, distills superseding private
  decisions, repairs the Implementer's isolated worktree, and validates four public regressions
  plus hidden behavioral/AST acceptance. Preserved failed runs exposed private-state completion
  ambiguity and opaque approvals, a model-corrupted `10_000`→`1_000` invariant, and Tester reading
  the untouched origin. Runtime context now releases completed turns; approvals show the redacted
  call; sparse `- [exact]` records validate normative literals fail-closed; downstream roots are
  accepted only from a registered same-pod Implementer. The final run
  `/tmp/docket-live-memory-w24-k` passed every gate without raised limits or scripted replies.

- **2026-08-19 (wave 23) — the full workflow now runs against the real local model, and the
  repeated run fixed what the deterministic proof could not see.**
  `scripts/smoke_workflow.py --live-model` discovers and registers the Qwen served at
  `127.0.0.1:8081`, uses no credential or
  scripted reply, preserves normal production guardrails, and completed the five-role tool/gate/
  approval/resume workflow in multiple fresh temporary worlds. A second pre-fix run exposed a real
  context defect: the Lead exhausted 20 iterations searching for HEARTBEAT/MEMORY because the
  injected startup contract required those files while the model neither received them nor could
  safely read the private workspace through project tools. `system_prompt_for_agent` now injects
  fresh HEARTBEAT/AGENTS/TOOLS/MEMORY by priority under `CONTEXT_TOKEN_BUDGET`, marks truncation,
  and closes with an explicit already-loaded/read-only handoff; roots remain unchanged and system
  context is not persisted. The final canary reduced the Lead from 16 turns/45,639 input tokens to
  7 turns/18,395 tokens (about 60% less measured input) without raising a limit. The opt-in live
  pytest, ordinary 2,233-test suite (5 expected skips), 18 goldens, 24 specs, Ruff, format, mypy
  and metrics passed.

- **2026-08-19 (wave 22) — one command now proves the product composes end to end.**
  `uv run python scripts/smoke_workflow.py` provisions a full agentic-product pod and drives a
  real CLI → OpenAI-compatible loopback HTTP → `DocketDriver` → agent loop → governed `write`
  tool path. Its five-step custom pipeline exercises mechanical and Reviewer/Tester verdict gates,
  deliberately pauses at a human approval, grants it through the CLI, and proves exact-position
  resume to `done`. It validates the artifact plus typed handoffs, five isolated step histories,
  atomic tool-call/result persistence, endpoint-measured usage, traces, audit-chain verification,
  and two successful run records. The endpoint is deterministic and local; no real credential or
  non-loopback network is used. A pytest subprocess wrapper makes the composition proof part of the
  2,230-test suite; all static/spec/golden/metrics gates passed.

- **2026-08-19 (wave 21) — the clean runtime break is now reflected in every current contract.**
  Product source, ordinary docs/tests, golden fixtures, and normative spec sections no longer
  teach a deleted daemon, adapter, binary, or home directory as a live boundary. The golden suite
  now seeds `.docket`; JSON/API documentation was checked against live producers (including a
  corrected `doctor --json` `modelConfig.invalid` shape); and a source-tree guard keeps retired
  coupling out of `src/docket`. Explicit names remain only where they are evidence: durable
  changelogs, roadmap/TODO history, and older spec changelog entries. All 2,229 tests passed with
  four environment skips; Ruff, format, mypy, 18 goldens, 24-spec validation, and metrics passed.

- **2026-08-05 (wave 19) — running a real pod against a real endpoint found three defects in one
  session, and 2,209 tests had caught none of them.** The local environment gained a llama.cpp
  endpoint (`127.0.0.1:8081`, 16k context) and a second real pod, **Adapta**. The first dispatch
  failed, and the reason was not the model. **(1)** An Implementer with a git worktree is gated
  against that worktree *alone*, but `SOUL.md` — its system prompt — and `WORKFLOW_AUTO.md` — the
  contract it re-reads after every context reset — both named the **origin checkout**, while
  `TOOLS.md` named the worktree. Every read came back `resolves outside the allowed roots`, the
  model retried other spellings, and the turn died on the token budget having executed **zero**
  tool calls. Nothing raised, so nothing went red. Fixed at the single point all three files are
  written, with a new test that pins the *property* (the advertised path is inside
  `_resolve_roots()`) rather than any path string, and with `docket doctor`'s contract heal — the
  same defect's second writer — fixed alongside. **(2)** The tool-output ceiling was a bare
  `30_000` literal in `toolbox.py`. It is a *context* bound, so its usable value is a function of
  the endpoint, and docket had no way to express that: at 30k, two results alone overflow a 16k
  window. Now `config.py`-owned and resolved per call. **(3) — found, not fixed:**
  `plan_compaction`/`compact_session` exist, are tested, are documented as automatic, and are
  **called from nowhere in `src/`**. Every hop of a dispatch shares one session key, so the reviewer
  hop receives the lead's and implementer's full raw history on top of the compiled
  `HandoffArtifact` — the handoff budget bounds the message, not the history — and the endpoint
  refuses the prompt at 19,827 tokens.

  **A fifth, found by using the product rather than reading it:** the README advertised
  "conversational dispatch — message the Lead directly" over Telegram. No such path exists; prose
  is refused with an "unrecognized command" reply. Two neighbouring claims were also false (a gated
  action "pings the wired group" — nothing is ever pushed; and a setup snippet using `docket serve`
  when the poll loop needs `--telegram`). **The functional spec was correct throughout**, requiring
  "exactly four verbs" and that anything else be treated as unrecognized — so unlike the
  unwired-machinery family this was *prose drifting from a right spec*, and nothing compares the
  two. Corrected across README/commands/quick-start; the inbound-only property and
  `/delegate`-returns-a-task-id are now spec requirements pinned by an AST guard rather than
  implicit.

  **A fourth, found while documenting the Tack integration:** `GET /traces/<project>?since=` —
  the route an external plan-of-record polls — replayed on any project with more than one session.
  `export_lines` concatenates session files in sorted *filename* order and a session id is a uuid,
  so the stream is not chronological, while the cursor anchored on the page's last line and counted
  a trailing same-second run. On the real `adapta` project a resume replayed 36 of 47 events. The
  page is now sorted by ts before anchoring: resume returns 0, and events arrive in time order
  across sessions. Wave 16's "no replay" check had been correct but not general — that project had
  one session file at the time. **A verification is a claim about the state it ran against**;
  re-running it against a richer state is what made the general case visible.

  **This is the third instance of one shape** (MCP tools, W17-1; sandbox, W18-3; now compaction):
  built, tested, never wired to the default path, with documentation asserting it works. Both false
  claims were corrected the same day rather than held pending a fix, moving the `docket help` golden
  by exactly one line. The lesson worth keeping is narrower than "test more": **all three were
  invisible to unit tests and immediately visible to one real run.** A small-context endpoint is a
  better integration test than a large one, because it makes context bugs fail loudly instead of
  silently costing tokens.

- **2026-08-05 — the local environment was rebuilt, and the suite leak was worse than assumed.**
  `docket` on PATH is an editable install resolving to `src/docket`, so the installed CLI already
  follows this branch. But `~/.docket` held **no real state at all** — 67 registered agents, every
  one a test fixture name, and two workspace directories that were both empty. `docket doctor`
  reported 14 pods "in sync" while `docket list` reported none; that mismatch is what exposed it.
  **This is the third recorded occurrence of the suite leaking into the developer's real
  `DOCKET_HOME`**, and the first where it had displaced the entire environment rather than adding to
  it. Backed up, wiped, rebuilt: org specialists + a real `docket-dev` pod on this repo, isolation
  enabled (and now actually consulted, per W18-3), all three isolation layers verified as real
  artifacts rather than declarations. Phase 22's routes were exercised end to end against a live
  `docket serve` — including the `pre_input` gate firing on the HTTP path and a cursor poll
  returning exactly one new event with no replay. **The single remaining gap is a model endpoint**:
  no key, no local runtime, so a dispatch cannot complete — it fails cleanly naming the missing
  credential, which `docket doctor` reports as its only critical issues.
- **2026-08-05 (wave 18) — two security claims were false; both are now true.** Opened against one
  *reproduced* defect: the audit log's hash chain restarted at `seq=1` on rotation with a single
  backup generation, so flooding past two rotations erased history while `docket audit verify`
  still reported a clean chain. Rotation now carries the prior generation's final `seq`+hash forward
  as a continuation claim, so a predecessor that cannot be produced is reported as a break.
  **The wave's larger find came from the card running alongside it.** A claims audit against the
  tree found `docket gates isolate on` did *nothing to a live turn*: the flag persisted, the
  bwrap/docker path was implemented and tested, and `run_turn` never set `ToolContext.sandbox`, so
  every tool call ran unsandboxed regardless of the setting — **the same shape as the MCP gap wave 17
  closed, but in a security control the README advertised three times.** Now wired, failing closed as
  a **turn-level refusal** (audited) rather than the per-call downgrade that would have re-created
  the original silence. **Process note worth keeping:** the README was corrected to admit the
  capability did not work *before* the fix landed, then corrected again after — a false security
  claim gets fixed the day it is found, not the day the code catches up. Also corrected: `--no-gates`
  never disabled the tool-call gate; it skips approval *routing* only.
- **2026-08-05 (wave 17) — the MCP wire, docket's oldest recorded limit, closed.** Two cards. The
  wire itself was one injection seam; **making it safe was the card.** Role narrowing removes
  literal `denied_tools` names, and a namespaced `mcp__<server>__<tool>` can never match one — so a
  naive load hands a Reviewer `mcp__fs__write_file` and silently voids the "structurally unable to
  write" guarantee the README leads with, **with no test failing.** Denials are now enforced by
  *capability*: `core/mcp_tools.py` already registered every adapted tool `kind="write"` (nothing can
  prove a remote tool read-only), so `registry_for_role` strips the kinds a role's denied names
  imply. **The integrator found the answer's own hole**: the kind set was derived by looking each
  denied name up *in the registry being narrowed*, which makes the denial conditional on that
  built-in being present — and `registry_factory` exists to inject narrower registries. Latent, not
  live, but the same failure mode through a different door; fixed with a static map so the denial
  depends only on the role's data. **The generalizable rule: when a capability can arrive under a
  name you do not control, deny the capability, never the name.** Honest residue: a read-only role
  gets zero MCP tools rather than a narrowed subset, and there is no listing cache (~0.6s per
  configured stdio server per turn, measured; zero servers ~0.004ms). Card 2 gave every config
  constant one owner — `config.py`'s `METRICS_WINDOW` turned out to have **no reader at all**.
- **2026-08-04 (wave 16) — Phase 22 shipped: the control-plane write API.** Six cards, two rounds,
  four agents. `POST /tasks/<project>` (enqueue, honouring the `pre_input` gate exactly as the CLI
  does), `GET /tasks/<project>`, `GET /traces/<project>?since=` (cursor'd), the approval `channel`
  label validated against a closed set `core/approval.py` owns, `POST /pods`, and trace retention.
  **Scheduling:** five of six cards touched `serve.py`, so ownership was split by HTTP *method* —
  zero code conflicts, and the single conflict was the spec changelog the roll-up rule already
  predicts, resolved by keeping both entries rather than picking one.
  **Four defects were found in review rather than by the suite**, and the pattern in each is worth
  more than the fix: a cursor that split on the last colon *of a timestamp* (safe for minted
  cursors, broken for the hand-supplied form the docstring advertised — the existing test covered
  only the variant that worked); a wiring comment that was **false when written**, caught because
  the comment was tested rather than trusted (`sweep_all`'s synthetic `session_end` carries a fresh
  timestamp, so terminating a trace *resets* its age, which means retention runs from session end,
  not last activity); a `/metrics` durability caveat that a card in the *same wave* made false
  (trace-derived counters had no history gap only because traces were never deleted); and a doc
  pointer left behind by the P22-5 refactor. Full per-card record in TODO.md.
- **2026-08-04 (wave 15) — the last legacy sweep, and one real bug.** Four cards; full per-card
  record in TODO.md. **The bug: `TELEGRAM_REQUEST_TIMEOUT_S` was documented, env-overridable and
  wired to nothing.** The adapter fell back to a hardcoded 35s socket timeout, so the env var did
  nothing — and raising `TELEGRAM_POLL_TIMEOUT_S` above 35, which Telegram permits, would put the
  socket timeout *below* the poll wait and make every empty long-poll read as a local failure. That
  is precisely what the constant's own comment warned about: **the invariant was written down and
  never enforced.** Now resolved in `core/` and threaded through, clamping to poll + 10s with a
  warning on violation (following `MCP_CLIENT_MAX_TIMEOUT_S`'s precedent, since this is not a
  security decision), proven red before green.
  **`docket eval` and `tests/evals/` removed outright, no replacement — record this alongside D-11
  and D-16.** The harness could not run: it shelled out to the deleted daemon and **skipped silently**
  rather than failing, so it read as coverage while doing nothing, and CONTRIBUTING and README both
  cited it as a real gate. Repair was rejected on evidence, not preference: no CLI entry point runs a
  single agent turn (`run_turn` is reached only from pod dispatch and distillation), so repointing it
  meant inventing surface against a private port; and three of the six scripts assume the
  pre-Phase-10 global `programmer`/`reviewer`/`tester` roles that `doctor` now flags as legacy debt.
  Removed coherently — module, command, doctor advisory, spec (per the retire-by-deletion
  convention), every doc/CI reference — with a removed-command notice exiting 1, matching
  `workflow`/`team`. **Commands 37 -> 36 and specs 25 -> 24 as a result; both counts falling is the
  work landing, not drift.**
  **The test suite is now named for what it tests**, not which card built it: 94 of 104 files
  renamed via `git mv` (`test_m4_wave1.py` -> `test_profile_scope_models.py`, and so on), with the
  29 references outside `tests/` repointed from the rename map git itself recorded.
  **Two guards proved themselves on unrelated work**, which is the useful kind of evidence:
  `test_no_openclaw_references.py` failed CL-J's first draft of the removed-command notice (a live
  string, not a comment), and CL-G found `test_store_writer.py` silently exempting `core/drift.py`, a
  module deleted long ago — its own docstring had said to remove the entry once that happened.
  Also reported and deliberately not fixed: `METRICS_WINDOW` is declared in `config.py` while
  `cli/_metrics.py` keeps an independent `os.environ.get` copy — a drift risk rather than a silent
  failure. Housekeeping: 52 stale agent worktrees pruned, 114 fully-merged card branches deleted.
- **2026-08-04 (wave 14) — the cleanup wave.** Six cards in two rounds re-trued every document,
  deleted the dead code the Phase 19 removal left behind, and stripped the changelog that had grown
  inside the source comments. Net ~2,900 lines removed. Full per-card record in TODO.md.
  **The largest deletion was ceremony:** `restart_gateway()` had been a documented no-op since
  P19-7b, and ~15 call sites across `cli/` still called it and rendered a result for a restart that
  never happened. **The most valuable half was not the archaeology** (`Phase 1X` 204→3, `P19-`
  163→1, `D-1X` 57→0 in `src/`) but the comments that had become **false** — four modules still
  claimed `pre_tool_call` "stays daemon-gated" and that "docket is not inside a turn to intercept a
  tool call", which is precisely the belief Phase 19 existed to falsify.
  **Three real defects surfaced.** (1) **MCP tools are not reachable in a live turn**:
  `load_mcp_tools` is never called and `DocketDriver.registry_factory` defaults to
  `builtin_registry`. Configuring a server registers and gates it; the last wire is absent. README
  and `docs/commands.md` overclaimed it — `mcp-client.spec.md` had it right all along, so the docs
  were the outlier. Note the consequence for planning: *"browser support is just an MCP config"* has
  been used more than once here to justify **not** building something, and it is only true once that
  wire exists. (2) `NOTICE` declared the project MIT-licensed while LICENSE, the CHANGELOG relicense
  entry and the README badge all say Apache 2.0. (3) All four `examples/configs/*-agent-meta.json`
  failed `AgentMeta` validation outright, and `agents.yaml` silently dropped two of its three entries
  through `docket add --from` — silent partial success being the worst failure mode an example has.
  **A refusal worth recording:** CL-C was briefed to standardise the version on `0.2.0-beta.17` and
  **declined**, having verified that value exists nowhere in the tree or the tags — the integrator's
  premise was wrong, and the agent checked rather than complied. Two other AST-flagged "dead"
  functions were likewise kept after being identified as pydantic `model_validator`s.
  **Deliberately left, not carded:** `tests/evals/` is entirely coupled to the deleted daemon
  (`$HOME/.openclaw/workspaces/<role>`, `openclaw agent --local --json`) and survives only because
  it **skips silently** when the binary is absent. Re-pointing it at docket's own driver is a
  redesign; decide whether the harness is worth keeping first.
- **2026-08-04 (wave 13) — THE BOARD IS CLEAR.** Phases 19, 20 and 21 are all closed; nothing is
  scheduled. **P20-2 shipped** the guardrail + loop metrics: four families on the existing Prometheus
  surface (`docket_tool_calls_total{decision}`, `docket_policy_hits_total{policy_id,hook,action}`,
  `docket_approvals_total{channel,outcome}`, `docket_turn_duration_seconds` as a quantile-less
  summary), **no new endpoint and no new dependency**. Every number is recomputed from durable
  records at scrape time rather than held in a counter store — `docket serve` is not long-lived, so
  in-memory counters would zero on restart and a persisted set would be a second source of truth free
  to drift from disk. Its one `core/tools.py` change is confined to how the audit *detail* is
  formatted (`policy_id`/`policy_action` as structured fields instead of free text); the gate itself
  is untouched. Two limits are documented rather than implied: audit-log rotation costs the
  approval/policy counters their history (P20-3's deferred retention scope), and scrape cost was
  **measured** at ~60ms against a 5MB audit log plus a 927KB trace corpus, not asserted.
  **P20-4 was a phantom card** — dispatched, and the agent found the gap already closed by W-4
  (`7e9ddab`, 2026-07-30) with tests and a spec entry; zero commits. It had been recorded as open in
  Phase 20's gap list *the same day* W-4 closed it, then promoted into a card, then **kept over
  OpenTelemetry in D-24's prioritization pass on a premise nobody re-checked**. The lesson is on the
  card: a gap list is a claim about the tree and decays like any other — re-verify one before
  scheduling work against it. Tree at close: **2,081 tests**, 18/18 goldens, 25 specs / 0 warnings,
  37 commands, ~26,700 lines, `ruff` + `mypy --strict` (73 files) clean.
  Separately, the **README was re-trued** for the post-daemon world (it still described docket as a
  wrapper around an external OpenClaw daemon, with an ACL, `openclaw.json`, a daemon-owned approval
  prompt docket could not audit, and "recorded dollar spend"); `docs/commands.md`,
  `COMPATIBILITY.md`, `CONTRIBUTING.md` and four `docs/` files carry the same debt and are **not yet
  carded**.
- **2026-07-31 (planning, no code)** — **The goal was stated — *a factory for agentic products* — and
  it settled four open decisions and opened a fifth.** **D-20 ANSWERED: both, in an order** — factory
  first, embeddable substrate second, on the reasoning that *if every product is agentic, the runtime
  is the common part of every product*, so the factory's highest-value output is a reusable substrate
  rather than agent-written code. The answer explicitly **excludes the hosted-SaaS half** (multi-tenancy,
  authn for external callers, queues, streaming, per-customer quota): the substrate is a **library a
  product embeds**, and the product owns its serving layer. **D-21 confirmed YES** but constrained to
  *packaging only*. **D-22 CUT** — stay project-scoped; the tenant axis is a real bet, not a free cut,
  and the expensive-to-retrofit warning stays on the record. **D-23 re-scoped** — ship the `fetch`
  tool, defer the egress lockdown, and **say the true thing in the docs**: egress is open, `fetch` is
  the inspectable path, the `python3`/`node`/`git clone` escape hatches are named. **D-24 NEW — the
  prioritization ruling**, which re-scored Phases 20 and 21 against §4.5's test (*does a measured need
  in **this** system ask for it*, not *is this best practice for someone*) and **cut roughly half,
  including the integrator's own recommendations from hours earlier**: **OpenTelemetry (P20-1) CUT** —
  correct at platform scale, wrong at one host and one operator with JSONL traces and six Prometheus
  metrics already shipped; **streaming (P21-2) and the tenant axis (P21-3) CUT** — both only served
  the hosted-runtime reading D-20 rejected; fleet trace query (P20-3), egress lockdown and the
  build-agent profile (P21-4) **deferred with named triggers**; browser automation **never to be
  built** (it is an MCP config). Added one **XS** card, **P21-5**, after verifying that the factory's
  scaffolding primitive **already exists** — `core/blueprints.py` ships `software`/`research`/
  `content`/`ops` as declarative data, so an `agentic-product` pod shape is a **row in a registry, not
  new machinery**. Waves re-sequenced: **P19-6 pulled forward into wave 10** (four cards in parallel
  with a function-level ownership map), wave 11 is the removal spine P19-7 -> P19-8, wave 12 is the
  substrate P21-1 -> P21-5, wave 13 is what survives of Phase 20. Docs only — no code changed;
  `metrics.py --check` and `validate-specs.sh` re-run green (2,026 tests, 24 specs).
- **2026-07-30 (wave 5)** — **PHASE 16 COMPLETE** (W-1…W-8) and 5 more cards merged, taking the
  tree to **1,600 tests**. W-5 replaced raw-text hop concatenation with a typed `HandoffArtifact`,
  which **unblocks Phase 17's C-1** and therefore opens Phase 17. W-4 shipped cron scheduling,
  webhook→pipeline variables, `--follow`, and the `runs.cancel` audit entry; G-4b closed the
  `models.*` audit gap G-4 named two waves earlier; CL-2 closed the dead-code register's
  non-dispatch half; L-4 answered its spike with dated evidence and no code. **The register's
  remaining rows are now closed**: the `AgentRunResult` alias and its ~76 call sites,
  `dispatch_all_pods`, the last `print()` in `core/`, two zero-caller ACL functions, and
  `core/sync.py`'s dead-module status — with an AST test pinning that no `print(` survives in
  `core/` or `edges/`. Deliberately kept rows carry dated in-code reasons rather than silent
  decisions. Full record, including what was narrowed: the `☑ Wave 5 shipped` block in the Phase 16
  section.
- **2026-07-30 (waves 3–4)** — **11 Platformization cards merged onto `platform`**, taking the tree
  from 1,112 → **1,512 tests**, 18 → 20 specs, 35 → 37 commands. Phase 16's exit criteria are met
  (W-1/W-2/W-3/W-6/W-7/W-8); Phase 18 is done but for its two daemon-gated spikes (L-1/L-2/L-3/L-6);
  Phase 15 is 4 of 6 (G-1/G-4/G-5/G-6). **D-16 executed:** `core/lobster.py`, `cli/_workflow.py`,
  their tests and `workflow-integration.spec.md` are deleted — `docket workflow` is a removed-command
  notice, and docket now lints only the one pipeline dialect it actually executes. **D-14 executed:**
  the RuntimeDriver port ships with exactly one driver, per the decision. Cancellation works for the
  first time because W-2 fixed its root cause (`agent_run` had no process group to kill). Full
  record, including what was narrowed: the `☑ Waves 3–4 shipped` block in the Phase 16 section.
  Two process lessons are recorded in §8: an index/roll-up table edited by parallel branches must be
  **regenerated from ground truth, never side-picked**, and `scripts/metrics.py --check` was found
  **failing open** — a CI-blocking guard that reported success while verifying nothing.
- **2026-07-30 (later same day)** — **PHASE 14 COMPLETE.** All 8 cards R-1…R-8 landed on
  `platform` (1,112 tests, 18 goldens, full suite green). R-8 (the spec/docs truth pass) rewrote
  `pod-dispatch.spec.md` to v2.0.0 for the full v2 state machine (locked claims, crash resume,
  retries, independent timeouts, bounded Reviewer rework, real budget auto-pause, bounded hop
  prompts) and trued up five more specs it touched along the way — `docket-meta.spec.md`,
  `serve-read-api.spec.md`, `cli-json-shapes.spec.md`, `audit.spec.md`, `cli-interface.spec.md` —
  several of which had drift unrelated to R-1…R-7 (a stale `apiVersion` example, a phantom `type`
  JSON field, a mis-shaped `docket snapshot`/`/metrics` schema, two missing audit action
  families) caught and fixed while reconciling `specs/README.md`'s status table against every
  spec's real header. Also corrected TODO.md's own board: R-6 had shipped correctly (worktree cwd
  resolution, verify-command validation, `pod.set-verify` audit logging — all test-covered) but
  its card's status line and acceptance boxes had been left at `TODO` since an earlier merge,
  contradicted by the roll-up checklist's own (also duplicated) entries; de-duplicated that
  checklist and reconciled it to one honest set of DONE marks. Verified — and did **not**
  re-touch — three guidance/docs bugs the R-8 card listed as candidates, confirmed already fixed
  by earlier cards: `cli/_provider.py`'s two dead-end strings and the eval-harness JSON-shape
  drift (both Phase 18 L-2), and the duplicated `openclaw-gateway.service` constant (also L-2).
  Two issues found but explicitly **not fixed** (outside this card's docs/specs/tests-only
  scope, reported instead): a leftover git merge-conflict marker inside `serve.py`'s module
  docstring from the R-3 merge (cosmetic, no behavior effect), and a precedence-order mismatch in
  `config.py`'s comment describing how the serve-wide dispatch timeout knobs interact with a
  pod's own Lead-meta timeouts. While reconciling the Status line above, also added "DONE —
  pulled forward" notes to three cards from later phases that had already shipped on `platform`
  with no Phase 14 dependency (Phase 15's G-6, Phase 17's C-4, Phase 18's L-2) alongside Phase
  15's G-4, which already carried one — none of the four are new work, only overdue
  bookkeeping so this document stops contradicting the tree. Full record: the Phase 14 section's
  `☑ Phase 14 shipped` block above; execution trail: TODO.md's R-1…R-8 cards (kept until Phase
  15's board overwrites them, per convention).
- **2026-07-30** — **Platformization program added (Phases 14–18) on the new `platform` branch.**
  Driven by the 2026-07-29 agent-platform audit (`internal-docs/agent-platform-audit-and-build-plan.md`,
  four parallel code-grounded passes): docket measured against eight agent-platform pillars scored
  0–2/5 each — no MCP, no gateway, lint-only workflows, a dispatch lane with a queue race / no
  `running` state / no retries, three governance organs built but unwired (approval store, policy
  engine, `resolve_command_action`), auto-pause never ported from Bash, and a closed 4-role
  software-only pod archetype. Added: Phase 14 (dispatch hardening, ACTIVE, board in TODO.md),
  Phase 15 (governance wired), Phase 16 (declarative orchestration + role archetypes/blueprints for
  diverse objectives), Phase 17 (context compiler + memory distillation), Phase 18 (RuntimeDriver
  port + MCP + wrapped-gateway spike); decisions D-14…D-18; §4.5 amended per D-14/D-15 (RuntimeDriver
  port supersedes the AbstractBackend ban's letter, "not in the execution path" retired). Specs
  restructured the same day: statuses trued to code, retired/legacy content cleaned (see the spec
  refactor commit on `platform`).
- **2026-07-30** — **Phase 15 G-4 (Audit v2) shipped, pulled forward on `pc/g-4`** — the one
  governance card with no Phase 14 dispatch-lane dependency. Recording coverage went from ~1/6
  of the spec to the full list minus `models.*`/`runs.cancel` (keys/profile/scope/agent/pod/
  persona all now audit-logged); added a `seq`+`prev_hash` SHA-256 hash chain and `docket audit
  verify`; timestamps moved to millisecond resolution; added size-capped rotation
  (`AUDIT_LOG_MAX_BYTES`, single-generation `audit.log.1`); removed the `DOCKET_NO_AUDIT` kill
  switch entirely (chose removal over a TTY-confirm gate to keep `core/audit.py` process-free);
  `core/trace.py`'s suppressed-write honesty bug fixed (`trace_event` now returns
  `"written"/"rejected"/"suppressed"` instead of a dishonest `True`). See audit.spec.md v2.0.0.
- **2026-07-03** — **Cut and tagged `v0.2.0-beta.1`** — folded Phase 13 (FD-0…FD-7) into
  CHANGELOG's previously-blank-since-drafting 0.2.0 entry; trimmed README.md (492→361 lines:
  cut the redundant Command Reference and Engineering sections down to short pointers at
  `docs/commands.md`/`CONTRIBUTING.md`, pulled two screenshots — `gates.png`/`doctor.png` — that
  showed pre-0.2.0 "gates inactive" output contradicting the new gates-on-by-default default);
  consolidated repeated before/after + token-savings narrative across `docs/DOCKET.md`
  (821→731 lines) and `docs/QUICK-START-DOCKET.md` (454→307 lines); merged three separate
  troubleshooting sections (`WORKFLOW-GUIDE.md`, `QUICK-START-DOCKET.md`, and
  `docs/troubleshooting.md` itself) into one canonical `troubleshooting.md`. **Versioning
  correction:** the operator clarified every release from this project must carry a SemVer
  `-beta.N` pre-release suffix while it stays beta software — corrected the in-flight plain
  `0.2.0` cut to `0.2.0-beta.1` (VERSION, `pyproject.toml`, `__version__`, `uv.lock`, CHANGELOG
  header + compare links) rather than reusing `0.1.0-beta.*`, since `v0.1.0` is already tagged
  and a `0.1.0-beta.N` would sort *before* it in SemVer precedence. `.github/workflows/release.yml`
  updated to mark the GitHub Release as a pre-release whenever the tag contains a `-` (so this
  and future beta tags don't show as "Latest release").
- **2026-07-02 (later same day)** — **PHASE 13 COMPLETE.** All 8 FD-cards landed and merged into
  `develop` (795 tests green). Execution: FD-0…FD-4 ran as a first parallel wave of 5
  worktree-isolated agents; FD-5/FD-6 ran as a second wave of 2 once the first wave landed; FD-7
  was done directly (solo, small docs-only card). Two real merge conflicts resolved by hand: test
  fixtures in `core/dispatch.py` needed widening to FD-0's 5-arg `Runner` signature after FD-2
  merged first; `security-gates.spec.md` had a genuine content conflict between FD-5 and FD-6
  (both independently wrote a "High-risk action classes" section) — resolved by keeping the more
  detailed version and combining both Changelog entries. One design correction made mid-phase,
  before merging: FD-3's first implementation excluded `git`/`npm` entirely from the exec
  allowlist to force high-risk invocations to always ask; caught during review that the daemon's
  binary-only gating would have also blocked benign invocations (`git status`, `npm test`) —
  presented to the operator as a real tradeoff, who chose to narrow the fix rather than accept the
  full exclusion. Per-argument enforcement for prod-deploy's `git`/`npm` overlap is now an
  explicit, tracked backlog item. TODO.md's board is now spent and awaiting the next phase.
- **2026-07-02 (later same day)** — **Added PHASE 13 — Close the differentiation gaps** (FD-0…FD-7),
  scoped after the operator chose "Tier-1 competitive bets" from `internal-docs/competitive-analysis.md`.
  A grounding pass (three parallel code investigations) found the analysis's framing had gone stale:
  Phase 11's own CD-1 (port/scratch allocation), CD-2 (verify-cmd gate), and CD-3/CD-4 (approval
  store + CLI/HTTP channels) already built most of what P1/O2/S1 asked for, the same week the
  analysis was written. Rescoped to the five real residual gaps instead of rebuilding: env-injection
  for pod resources (FD-0), a public way to set `verifyCmd` (FD-1), a structural Tester PASS/FAIL
  gate (FD-2), a high-risk action-class always-approve policy (FD-3), audit-log parity for approval
  channels (FD-4), plus the spec truth pass and gates-default-on flip those unblock (FD-5) and a
  docs/positioning pass (FD-7). Board in TODO.md.
- **2026-07-02** — **Marked PHASE 11 complete** (CD-0…CD-9 all DONE 2026-06-25, suite green at 693;
  durable record added to the Phase 11 section, TODO board cleared per convention) and **added
  PHASE 12 — Consolidation & hardening** (CH-0…CH-13), driven by `internal-docs/architecture-audit.md`
  (2026-07-02: four parallel audit passes — architecture invariants, docs↔code sync, feature value,
  dead code/hardcoded data). Verified findings baked into the plan: store.py bypassed by
  `.docket-meta.json`/registry writes (atomic-write logic hand-copied 8+×), raw `openclaw` shell-outs
  outside the ACL, `core/provider.py` printing UI from the domain layer, `cli/__init__.py` at 4,194
  lines, `core/drift.py` with one caller feeding an unimplemented notification, the legacy `team`
  queue duplicating pod dispatch with no dispatcher, drifted hand-written completions, overdue D-2
  deprecation shims, 3 dead templates, 8 commands missing from docs/commands.md, spec/code mismatches
  (workflow extension + exit codes, team done-state), contradictory test counts (416/694 vs actual
  688), and the Bash-era `scripts/spec-coverage.sh`/`metrics.sh` still in CI while counting the
  deleted `lib/` tree. Decisions D-11 (retire `team` → pods) and D-12 (store.py single-writer rule,
  JSONL logs exempt) added. Explicit keeps recorded so the phase doesn't over-cut: the CD-6/7/8
  differentiators, ACL/store/sync, audit+approval, `resources.py`, and the policy/models_policy/
  provider trio (naming collision, not duplication).
- **2026-07-02 (later same day)** — **PHASE 12 COMPLETE.** All 14 CH-cards landed and merged
  into `develop`; `docket` 0.2.0 cut (CHANGELOG + VERSION + pyproject.toml + uv.lock +
  `__version__`; not tagged — operator step). Execution notes: 9 cards ran via parallel
  worktree-isolated agents on the first pass; a second wave (CH-7/CH-8/CH-10) was interrupted
  by an infrastructure session-limit error before any commits landed (cleanly recovered — CH-10
  was then done directly, CH-7/CH-8 re-ran successfully once the limit reset); CH-11 landed
  solo; CH-12 was done directly. Three real merge conflicts resolved by hand (`cli/__init__.py`
  together with `core/provider.py` on CH-4; a store-import alias in `core/models_policy.py` on
  CH-6). The
  README-numbers drift guard (re-armed by CH-9) caught real drift three times as later cards
  added tests/files — confirming it works. One negotiated deviation from the original exit
  criteria: `cli/__init__.py` landed at 1,702 lines (target ≤1,500) — CH-7's Do-list named 5
  extraction targets and no more; no 6th stage was invented to force the number down further.
  `CLAUDE.md` (gitignored/untracked) was synced directly on the local checkout throughout,
  since no git branch could carry an edit to it. TODO.md's board is now spent and awaiting the
  next phase.
- **2026-06-25** — **Added PHASE 11 — Competitive differentiation**, and marked Phase 10 complete in
  the status header. Driven by `internal-docs/competitive-analysis.md`: a deep-research pass (12
  sources, load-bearing claims re-fetched and confirmed verbatim) + a **GitHub-verified** sweep of the
  OpenClaw-native ecosystem. Findings: the space is bifurcated into monitoring dashboards
  (`builderz-labs/mission-control` ~5.4k★, `abhi1693/openclaw-mission-control` ~4.1k★, several
  `openclaw-dashboard`s) and setup scripts (`shenhao-stu/openclaw-agents` ~445★); the only true CLI
  lifecycle+governance peer is `oguzhnatly/fleet` (~13★, Bash, no pods/cost-policy/isolation). The
  broader field treats three things as unsolved — runtime-resource isolation, anti-fragile shared
  context, and a real HITL/audit spine — and docket already owns the second. Phase 11 cards CD-0…CD-9
  double down on the trio and close the two visible gaps (no dashboard-feed API; gates opt-in /
  Telegram-only). Backlog gained explicit deferrals: own web UI, microVM/gVisor isolation, multi-host,
  cross-runtime adapters. The deferred "Phase 0 gates default-on flip" is now sequenced under CD-4.
- **2026-06-24** — **Repointed stale `lib/` references to the Python layout.** Converted the
  now-dead clickable `lib/commands/*.sh`, `lib/helpers/*.sh`, `lib/core/*.sh`, and
  `tests/test-lifecycle.sh` markdown links (deleted in the M6 Bash→Python cutover) to plain text
  and annotated each with its current `src/docket/` location (`cli/` Typer commands, `core/`
  domain, `edges/` I/O incl. the ACL + `store.py`; tests now pytest under `tests/python/` + the
  golden suite). Historical phase content and plan meaning unchanged — only file pointers corrected.
- **2026-06-23** — **Consolidation + PHASE 10 added.** Folded the three standalone planning docs into
  this roadmap and removed them: `ARCHITECTURE-AUDIT.md` (language verdict — *migrate to Python* —
  executed by M6; build-vs-wrap + the language reasoning survive in §4.5/§0), `MIGRATION-PLAN-PYTHON.md`
  and `MIGRATION-TASKS.md` (the Bash→Python strangler-fig plan + task board — fully shipped; recorded in
  §0). Refreshed the stale Bash ground-truth (§2) and conventions (§3) to the Python three-layer/ACL
  reality; added §0 (completed migration) and §4.5 (durable architectural principles + anti-overengineering
  guardrails). **Added PHASE 10 — Agent architecture (pods)** (AA-0 … AA-9): fixes the three structural
  defects in the agent model — (A) "two doers" split between project agent and shared programmer, (B)
  shared specialist singletons break the session-key isolation guarantee, (C) "delegation" is instruction-only
  with no runtime. Plan: make **scope** a first-class axis (org vs project), reclassify the six specialists
  (security/knowledge → org; programmer/reviewer/tester → project-scoped pod roles; manager → per-pod Lead +
  optional org Portfolio Manager), provision each project as an isolated **pod** sharing one session key, and
  gate runtime dispatch behind a daemon-capability spike (AA-0). Executable cards in
  [TODO.md](TODO.md); rationale in `internal-docs/agent-structure-analysis.md`.
- **2026-06-22** — **PHASE 9 complete** (CDD-1 … CDD-6) *(pre-migration Bash paths below; the schema/validation/doctor logic now lives in `src/docket/core/` + `src/docket/cli/`)*: `lib/core/schema.sh` declares the full
  `.docket-meta.json` field set once (name/type/enum/sync-class); `meta_set` validates every write
  against it (unknown field → error, type mismatch → error, enum violation → error); `docket doctor`
  now diffs all `synced` fields (model + sessionKey) not just model, and `--fix` re-syncs from
  `.docket-meta.json`; phantom `{success,data,error,version}` envelope removed from spec, real per-
  command shapes documented in `specs/data/cli-json-shapes.spec.md`; `scripts/spec-coverage.sh`
  rewritten as a mechanical linter (router.sh case arms vs cli-interface.spec.md headings, exits 1
  on mismatch); spec de-staled — gates/audit/eval/models/completions/telegram/trace/metrics/
  policies/approve/deny added, profile tier-as-arg corrected to model-id/`default`, reset/repair
  stale "Used By" entries removed. 17 new unit tests; 325 total, all green.
- **2026-06-22** — Added **PHASE 9 — Contract integrity / de-ceremony** (CDD-1 … CDD-6), from a
  Contract-/Schema-Driven-Development audit. Scope-corrected the generic web-CDD brief to docket's
  reality: no OpenAPI/DB/codegen exist (so the "dead codegen loop" and "migration rigor" pillars
  are N/A by construction), so the audit targets docket's three real contracts — the markdown
  specs, the dual-source `.docket-meta.json` ↔ `openclaw.json` config, and the `--json`/HTTP
  shapes. Verified findings: the spec's `{success,data,error,version}` JSON envelope is emitted by
  **zero** commands (cli-interface.spec.md:340 vs no `"success"` in lib/commands/); `docket doctor`
  drift checks **only** `model` (doctor.sh:187-197/515-526) so budget/paused/modelSource drift
  silently; `_meta_set` does no type/enum validation; `spec-coverage.sh` scores presence not
  contract conformance; `gates`/`audit`/`eval`/`models`/`completions` are missing from the spec
  registry and `reset`/`repair` linger as live in input-validation.spec.md. Decisions D-9/D-10
  added. (This consolidated doc is now the roadmap.)
- **2026-06-22** — Added **PHASE 8 — Agent observability, guardrails & drift (HITL)** (OBS-0 …
  OBS-12), derived from the durable-trace / gated-destructive-action / guardrailed-untrusted-input /
  self-surfacing-drift spec (goals G1–G5) and an audit of the current cost, gates, Telegram, serve,
  task-queue and test subsystems. Key finding baked into the plan: **docket is not in the agent
  execution path** (the OpenClaw daemon executes tool calls), so the phase is sequenced
  observability (pure docket, ships first) → policy engine (pure, testable) → enforcement+HITL
  (the only hard daemon dependency, isolated) → drift. Collisions resolved: spec's `docket audit`
  → `docket trace export` (existing `audit` = operator-mutation log kept); `$DOCKET_HOME` aliased
  to `OPENCLAW_DIR`; per-run `session_id` derivation deferred to the OBS-0 spike. Spec open
  questions Q1–Q3 resolved as decisions D-6…D-8. Non-goals (no OTel/Prometheus/DB, no ML v1, no
  RBAC, filesystem-is-the-store) recorded as hard guardrails.
- **2026-06-12** — **PHASE 6b complete** (MA-9 ✅ MA-10 ✅ MA-11 ✅): `ROLE_MODELS`/`ROLE_WHY`
  policy in config.sh with registry `roles:` overlay (legacy `profiles:` still re-derives);
  `docket models` shows ROLE|MODEL|PRICE|SOURCE|WHY and `set <role>` / presets / reset all
  auto re-resolve policy-followers (`reapply_role_policy`, pins untouched, one restart,
  audit-logged); `.docket-meta.json` gains `kind` + `modelSource` (policy|pinned) with lazy
  inference for pre-existing agents (model ≠ policy → pinned, so nothing silently
  downgrades); `docket profile` is now pin/`default` semantics and covers specialists;
  install.sh resolves specialists through the policy and stamps their meta; doctor
  backfills taxonomy metadata; delete guards specialists; tier names everywhere are
  deprecated aliases with warnings; templates tier-neutral (TEMPLATE_VERSION=3); eval
  recommendations rephrased to role-policy actions; README/CLAUDE.md/docs/commands.md
  (incl. new `### models` section)/QUICK-START/DOCKET.md/WORKFLOW-GUIDE updated.
  Tests: 241 unit (18 new MA-9/MA-10) + 63 integration, all green.
- **2026-06-11** — Added PHASE 6b — Tier-less role→model policy (MA-9 … MA-11): unified
  agent/model architecture decided with user — tiers removed from UX (deprecated aliases
  only); global-only role→model policy map with per-role WHY, defaults picked for token
  efficiency (manager/reviewer/tester/knowledge/task on the cheap class, programmer/
  security/repo on the strong class, opus-class = explicit pin); agents store intent
  (`modelSource: policy|pinned`) and `docket models set/preset` auto re-resolves
  policy-followers; specialists join the `.docket-meta.json` system (`kind`/`role`, one
  taxonomy in `docket list`). Deferred: `docket models optimize` (eval × cost-history
  right-sizing, later phase) and per-task dynamic routing (needs daemon spike). Closes
  the install.sh hardcoded-specialist-models and model-drift gaps left open by Phase 6.
- **2026-06-11** — Added PHASE 6 — Model & provider agnosticism (MA-1 … MA-8, 🔴 critical):
  remove the hard Claude-API dependency; model registry, `docket models` command, provider
  presets incl. free/local, cost honesty, key plumbing, template + docs neutralization.
  (Phase 6 of this roadmap; the former "Product & community" is Phase 7.)
  Claude-dependency inventory verified against source this date.
- **2026-06-08** — Initial executable plan derived from the v2 product plan and source review. `agents.list` confirmed against live `~/.openclaw/openclaw.json`.
