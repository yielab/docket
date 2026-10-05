# docket — Roadmap & Implementation Plan

This is the **single source of truth** for docket's roadmap *and* its executable task plan.
(Consolidated 2026-06-22 from the former root `ROADMAP.md` + `internal-docs/IMPLEMENTATION-PLAN.md`,
which duplicated each other at two altitudes — high-level phases vs. detailed tasks. Now one file.)

It takes docket from a polished single-user CLI to a hardened, portable, operable tool — sequenced
so each phase is independently shippable and raises the bar on **security → reliability →
portability → operability → product**. Earlier phases unblock later ones.

---

## ⇢ STATUS AT A GLANCE — every phase, one line each

**Last updated: 2026-09-27.** Every numbered phase 0–26 is complete. **Phase 26 (the configuration contract, D-42) closed 2026-09-26** (Waves 38–40, 20/20 cards): governance fails closed, pod settings are typed and writable (nine `pod config` keys), pipelines and prompt budgets are configurable per pod, and three shipped recipes prove the surface end to end. **Wave 37 closed 2026-09-25** (D-41): a triage that ran the product on six surfaces found twelve defects, fixed by six cards in two batches — the worst stalled every unattended dispatch whose command began with `cd`, and the sixth unwired-machinery instance (the installed console script skipped aliases and removed-command notices) is closed. **Wave 36 closed 2026-09-21** (opened 2026-09-19, D-40): eleven cards for the code-side defects the documentation audit of `v0.2.0-beta.3` found, run as three batches of one-card Sonnet workers under one integrator; the fifth unwired-machinery instance (blueprint pipelines) is wired, `POST /pods` validates project ids, and `--debug` is retired. **Phase 25
(human maintainability, D-36) and Phase 24 (harness mode, D-35) both completed on 2026-09-12**, the
first as Wave 31's thirteen cards and the second as Wave 30's five. **Wave 32 closed the same day** (2026-09-12): a
documentation truth pass over the drift those two phases left, plus the two follow-ups Wave 31
measured and deferred. **Waves 33 and 34 closed 2026-09-13**: an audit of the Wave 32 closure, repository hygiene, a docstring-only comment sweep (558/112 to 372/40 without changing a line of code), then the D-36 function split finished under a new function-span ratchet, two measured fixes, and a read-only audit that found the fourth unwired-machinery instance. **Wave 35 closed the same day**: a second docstring sweep (372/40 to 229/29), the dead `gatesEnabled` flag retired, and the integration lane's `SUBJECT` line given a rule and a guard. **Phase 23 closed 2026-09-14** (D-39): its release evidence is the `v0.2.0-beta.2` publication of
2026-09-07, and the card that would have published a newer beta was removed from the board.
**`v0.2.0-beta.3` was published 2026-09-18** as a maintainer action, the first with harness mode,
after CI on `main` went green again on the dependency floor and on macOS. The next release is
likewise a maintainer action, not a card. **Phase 27 (per-pod configuration and portable teams, D-43) shipped 2026-09-26**, ten cards
over Waves 41–43 (eight planned plus two defects found inside the phase: pod-overlay roles
dropped from the roster, `apply` skipping policies): roles, policies and MCP selection resolve
per pod above a global structural base, an MCP server declares its kind and tools, the Lead's
instruction is data, and the recipe directory is a manifest with `docket pod <p> apply|export`
proven by a round trip; reasoning in
[docs/adr/0009-per-pod-configuration-and-portable-teams.md](docs/adr/0009-per-pod-configuration-and-portable-teams.md).
**Phase 28 (configuration format v1 and the two extension points, D-44) shipped 2026-09-26**,
eight cards over Waves 44–46, one Sonnet worker per card under one integrator: a `kind` envelope
and one `docket validate`, short forms for roles, pipelines and policies over the unchanged
canonical form (each normaliser proven by a round trip), control flow as bounded data (`on`,
`until`, closed `when` predicates, command steps; the executor is `core/dispatch.py`, which the ADR
had mislocated), hashed, operator-applied Python predicate plugins for policies that are never
imported from the codebase, generated JSON Schemas and a short-form `export`; reasoning in
[docs/adr/0010-config-format-v1-and-extension-points.md](docs/adr/0010-config-format-v1-and-extension-points.md).
**Phase 29 (the provider catalog, D-45) shipped 2026-09-27**, seven cards over Waves 47–49, one
Sonnet worker per card under one integrator: model providers are `kind: provider` documents in two
scopes (fourteen built-in in the wheel, global for the operator) from which every provider table
derives, a closed `dialect` field selects the adapter, credentials are referenced by name only
(bearer, a named header, or none, plus static headers), registration verifies *with* the
credential and classifies the answer (only a transport failure refuses), `provider
add/list/show/remove/export` round-trip a document, `Retry-After` is honoured up to a 60 s ceiling,
`docket auth` is a removed command and `keys setup` walks the catalog, and `config explain` names
the provider, its scope and where the credential came from; reasoning in
[docs/adr/0011-provider-catalog.md](docs/adr/0011-provider-catalog.md).
**Phase 30 (the team lives in the repo, D-46) shipped 2026-09-27**, seven cards over Waves
50–51 (four Sonnet workers in parallel, then the integrator): a repository's `.docket/` directory
is the team's configuration of record — `docket init` validates it before provisioning and
applies it after (or `--recipe <name|dir>`; `--no-apply`), `apply`/`export` default to it, the
pod records `configSource`/`configDigest` so `config explain` reports drift, nothing is applied
without an operator command; a pipeline step may name its `model` for that hop only; `editRights`
is retired; running the product for the new assets found that a recipe's role applied into a pod
fell to the compiled-in default model on a local fleet (fixed: the archetype resolves in its
pod's registry, the fallback is the registry default); the three terminal assets were
re-captured from one real run under the `docket` wordmark and the README was rebuilt on the
tagline *agent teams as configuration, your rules, in YAML*, with its prose tests rebuilt from
that README rather than carried forward; reasoning in
[docs/adr/0012-the-team-lives-in-the-repo.md](docs/adr/0012-the-team-lives-in-the-repo.md).
**Phase 31 (recipes as a library, and the repository's standards, D-47) shipped 2026-09-27**, seven
cards over Waves 53–55 (four Sonnet workers in parallel, then two, then the integrator): a recipe's
scope is derived from its directory and shown by `validate`, `apply --dry-run`, `init --recipe` and
the new `docket recipes list|show`; `pod.yaml` gains `description`; `apply` records the source on
every validated apply; a name resolves against a path, `~/.docket/recipes/`, then the shipped
library, now twelve recipes of three kinds (teams, four policy packs on structured predicates,
five methodology pipelines: `tdd`, `spec-first`, `reflexion`, `dual-review`, `frugal`); the
repository's `AGENTS.md` composes by default as screened project instructions; skills follow the
Agent Skills shape in three scopes with a prompt index and one `skill` tool through the chokepoint
(three shipped recipes carry one); `docs/recipes.md` is generated from the recipes and checked in
CI. Running the suite found two unwired seams inside the phase (the `skill` tool's kind missing
from `BUILTIN_TOOL_KINDS`; `core/skills.py` absent from the runtime wheel's file list), both
closed in P31-6; reasoning in
[docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md).
**Phase 32 (observability as configuration, D-48) shipped 2026-09-28**, nine cards over Waves
56–59 (two, three and three Sonnet workers in parallel, then the integrator): the trace gains an
`llm_call` event with measured latency and a spec of its own; a neutral `Span`/`SpanEvent` model
in `core/telemetry.py` projects the existing vocabulary once with deterministic ids; a
destination is a `kind: exporter` document (built-in + global, closed `dialect`, credentials by
name) whose dialect selects the one edge module that knows the wire, v1 = `otlp-http` over stdlib
`urllib`; five ready built-ins (local collector, Jaeger, Langfuse, Honeycomb, Phoenix) that
`docket exporters enable <name>` authenticates and probes; a bounded pipeline that never blocks a
turn, started lazily by `run_turn`; `payload: metadata` by default so repository content never
leaves the host unless the operator says so; `pod.yaml` may name destinations; `config
explain`/`doctor` read the exporter's own health. Verified live 2026-09-28: a real dispatch
against a real `otel/opentelemetry-collector` produced real `gen_ai.chat` spans with measured
token counts, matching `docket trace` and a non-zero `exported` health counter; Langfuse's
round-trip stays open, named in `observability-export.spec.md` §"External verification" as
blocked on the operator's own credentials rather than skipped silently. Three independent cards
across the phase version-bumped the same still-Draft spec from the same base and conflicted on
merge — reconciled by hand each time, a predictable cost of two workers targeting one Draft
file, not a process failure. D-24's cut of the OpenTelemetry SDK stands; reasoning in
[docs/adr/0014-observability-export.md](docs/adr/0014-observability-export.md).
Board archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
**Phase 33 (export privacy levels, D-49) shipped 2026-09-28** (opened and closed the same day), six
cards over Waves 60–63 (one Sonnet worker, then two, two, then the integrator), triggered by the live Langfuse
run: every generation's Input/Output was empty, `payload: full` changed nothing a destination
renders, and the `metadata` denylist already let an approval's command line and run error text
leave the host. What a destination may see becomes a set of content classes (`toolArguments`,
`errors`, `toolResults`, `completions`, `prompts`, `instructions`) chosen per exporter as a level
(`minimal` default, `actions`, `conversation`, `full`) or an explicit `share:` list; an allowlist
where spans are built maps every attribute to one class and filters conversations per message
part; the model call records its content only when an enabled exporter asks; widening is a
confirmed, audited command; the level shows in `list`/`show`/`explain`/`doctor`, on the root
span, and in an offline `docket exporters preview`. Content uses the OTel GenAI `Opt-In`
attribute names, which Langfuse reads natively; reasoning in
[docs/adr/0015-export-privacy-levels.md](docs/adr/0015-export-privacy-levels.md).
Verified live at `minimal`/`actions`/`conversation` against a local collector and Langfuse with
canaries (none at `minimal`); that run found `tool_result` never recording its output and fixed
it. Follow-up recorded, not scheduled: the pipeline's idle flush can emit a session's root span
twice. Board archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
**Phase 34 (the operator loop, D-50) shipped 2026-09-29** (opened 2026-09-28), seventeen cards
over Waves 64–70 (one worker per card, Sonnet or Haiku, in isolated worktrees under one
integrator), triggered by the operator's request and three facts found reading the live path:
the only four real approvals expired unanswered, an in-turn `ask` under `serve --dispatch`
stalls every pod, and the Lead cannot ask anything although its prompt said it owns human
communication. Work that needs a human **parks** (`approvalMode: park`, a new `waiting_input`
state, single-use pre-grants matched by a stable args digest) instead of blocking a thread; the
Lead's intake is an opt-in pipeline pattern (a typed `TaskBrief`, a new `input` step, the
`intake` recipe, a deterministic resource pre-check); one derived inbox (`docket inbox`,
`GET /inbox`, the MCP `inbox` tool, Telegram `/status`) feeds every surface; notifications are
CloudEvents delivered by `kind: channel` documents (console, desktop, webhook signed per
Standard Webhooks, command, ntfy, email, Telegram by amendment of its Command grammar 7 and a new
`/answer` verb); questions and answers take the MCP elicitation shape and task states map one to
one onto A2A 1.0.0. Reasoning in
[docs/adr/0016-operator-loop-and-interop-standards.md](docs/adr/0016-operator-loop-and-interop-standards.md).
**The integrator's close (P34-17) added three seam tests no card owned alone** — the real HTTP
`POST /approvals/<token>` write route threaded into the pre-grant mechanism and a real
re-dispatch; `content: minimal` vs `actions` enforced at a real local `webhook` delivery, not
either card's own unit test; the operator's exact typed answer reaching the Lead's own re-entry
message via `## Operator answers` — and found two real defects by running the product rather
than reading it: the operator-loop scenario's own `eventsDelivered` counter read a
`channels-health.json` key that never existed, always `0` since it was written; `--live-model`
registered its provider after `docket init`, so that path had never actually completed `init`.
sweepBlockedSeconds dropped from the pre-Wave-65 baseline of ~12-13s to under a second
(deterministic, park removing the blocking wait) but measured 138.0s under the real local model —
real per-hop generation latency serialized across one sweep worker, a different cost than the one
`park` targets, named for a maintainer rather than acted on. Both named deferred triggers this
phase carries were evaluated at the close and did not fire: fewer than 10 real parked approvals
exist on this machine to measure the mid-turn-resume trigger against, and the one-worker-per-pod
trigger's scripted-backend condition does not hold (see the ADR's own "Deferred with named
triggers" section for the full reasoning). Board archived in
[docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
[.agents/handoffs/wave-64-worker-packets.md](.agents/handoffs/wave-64-worker-packets.md). Nothing
is parked, except `cli-interface.spec.md` coverage for `docket inbox`/`channels`/`notify`/
`pregrant`/`explain interruptions`, named there for a follow-up card rather than backfilled under
this close's time budget.
**Phase 35 (docket in a harness-agnostic factory, D-51) opened 2026-09-29, closed 2026-10-04**: ten
cards over Waves 71–75. Carried to the next phase: the process-wide approval timeout for a run and
the answer reader's daemon thread (both in the archived Wave 73 block). It was triggered by the maintainer's request to architect docket's part of the
structured-agentic-engineering plan, and by facts read in the consumer:
- Tack runs docket as one of four interchangeable harnesses and no longer polls its HTTP API;
- Tack's U8 is blocked because no `harness-v1.1` exists;
- Tack declares docket's decisions `Unsupported`.

What the phase ships:
- an opt-in harness contract v1.1 carrying exactly Tack's four M3 items: process lifecycle
  events with cancellable process groups, questions on stdout answered on stdin, a written-path
  list, and `--token-file`;
- the caller's limits (`--max-tokens`, `--policy`);
- a recipe pipeline run in place (`--recipe`);
- pod dispatch keeps its evidence (verify output, commit, base, diffstat, `requireVerify`);
- two measured defects fixed (`guardrail_block.action`; pod-scoped `tokenBudget`).

docket executes and records but never certifies its own work; merge readiness and autonomy
belong to an independent verifier. Phases 36–38 (consultation and evidence packs,
verification-ready execution, the L4 envelope) are outlined in `TODO.md` and not claimable.
Reasoning and reversals in
[docs/adr/0017-docket-in-a-harness-agnostic-factory.md](docs/adr/0017-docket-in-a-harness-agnostic-factory.md);
packets in [.agents/handoffs/wave-71-worker-packets.md](.agents/handoffs/wave-71-worker-packets.md).

**Phase 36 (consultation packs and evidence-v1, D-53) opened 2026-10-04, closed 2026-10-04.** Eleven
cards over Waves 76–81: operator-v1.1 (`Question.kind`, `options[]`, `recommendation`, `Answer.optionId`),
`reason`/`actor` on approval grant and deny, approval packs (the model's rationale plus three
options), a `consult` built-in tool for every role capped by `maxConsultationsPerTask`, a per-pod
corrections ledger, evidence-v1 (one document behind the CLI, HTTP and the harness), and escalation
metrics. Wave 76 is a Phase 35 follow-up: the harness `files` list stops reporting verify artifacts
and paths dirty before the run. Carried to the next phase, by name: the parked consult question
crosses to the answering process through an in-process registry (it fails closed out of process);
`approve_task` is scoped to one turn; `question.taskId` in a single-turn harness consult is the
session key; options are not rendered in Telegram or channel notifications. A live run on the local
endpoint called `consult` and showed an approval pack, and a live pod dispatch parked a Lead's
`consult`, took the operator's non-recommended option and finished `done` on it (ADR 0018 "Live
run"). Reasoning in
[docs/adr/0018-consultation-packs-and-evidence-v1.md](docs/adr/0018-consultation-packs-and-evidence-v1.md).

**Phase 37 (verification-ready execution, D-54) opened 2026-10-04, closed 2026-10-04.** Nine
cards over Waves 82–84:
- one git worktree per task, created at claim and recorded on the task, instead of one per
  Implementer, so a task's evidence counts only its own change;
- `pre_input` screening of MCP tool results;
- the task's id and evidence commits as environment for command steps;
- a `no_progress` stop reason;
- recipe-declared, pod-scoped MCP servers, which a turn starts in its own root;
- the `anti-tautology`, `mutation`, `spec-writer`, `cross-family-review` and `code-intel`
  recipes.

Re-verifying the outline found two false claims ("recipes, no core change" and "an MCP pack as
recipes"), which the ADR corrects. A live run on the local endpoint dispatched two tasks back to
back with nothing merged. The second ran in its own worktree, on the new HEAD, and its `diffStat`
counted only its own change.

Carried to the next phase, by name:
- the redaction pattern in `core/trace.py` matches `sk=` inside `task=`;
- finished task worktrees have no retention policy;
- `fetch` results are not screened;
- the check recipes read their overrides from the process environment;
- the four Phase 36 items: the in-process consult registry, the turn scope of `approve_task`,
  the session key as a single-turn consult's `question.taskId`, and options not rendered in
  Telegram or channel notifications.

Reasoning in
[docs/adr/0019-verification-ready-execution.md](docs/adr/0019-verification-ready-execution.md).

**Phase 38 (the execution envelope, D-55) opened 2026-10-05.** Isolation on by default (bwrap
first, with a preflight that names the fix, and a jail in which a task worktree can commit); an
opt-in network lockdown mode; stdio MCP servers in the same jail; file tools that never follow a
symlink out of their roots; `pre_input` on `fetch` results; no docket credential in a task's
processes; one sweep worker per pod; a left boundary on the redaction pattern. Re-verifying the
outline corrected three claims (file tools are not moved into a subprocess, the lockdown does not
change ADR 0004's default, and docket has no issuer to mint per-task credentials from), and
deferred `kind: autonomy` until a verifier produces one. Reasoning in
[docs/adr/0020-the-execution-envelope.md](docs/adr/0020-the-execution-envelope.md).

> **How to read the rest of this file.** Nothing below is a task list; executable cards are in
> `TODO.md`. **The completed phase records (0–25, the Bash→Python migration) and this file's
> decision changelog were moved verbatim to [docs/cycles-ended/](docs/cycles-ended/README.md)** (`roadmap-phases.md`,
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
| 23 | **Product truth and ecosystem proof (D-25)** — first successful turn, trustworthy release, atomic governance, then portable enforcement evidence | ☑ **complete (2026-09-14)** — Waves 26–29. Release evidence is the public `v0.2.0-beta.2` (wheel, sdist, installer archive, checksums, SPDX SBOM, provenance attestation); W29-C7's remaining half, a newer beta, was removed by D-39. Record in `docs/cycles-ended/roadmap-phases.md` |
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
| — | **Wave 29** (not a phase): adoption evidence and public release | ☑ complete (2026-09-14) — C1–C6 shipped; C7 published `v0.2.0-beta.2` on 2026-09-07 and its closing half was removed from the board by D-39 |
| 24 | **Harness mode (D-35)** — docket as a governed, non-interactive execution harness a plan-of-record (Tack) spawns as a subprocess | ☑ **complete (2026-09-12)** — Wave 30, five cards. `docket harness run`/`status` ship with a published, versioned, test-pinned contract; the three seams it needed are wired and proved reached by a real subprocess |
| 25 | **Human maintainability (D-36)** — test lanes with a budgeted agent lane, one unit file per module, zero-archaeology comments ratcheted in CI, generated CLI/API docs, board and roadmap cut to size | ☑ **complete (2026-09-12)** — Wave 31, thirteen cards. The board and roadmap reached their line targets on 2026-09-14, when the Wave 29 and Phase 23 sections archived |
| — | **Wave 31** (not a phase): baseline → lane move → structural guards → comment hygiene → per-module merges → in-process CLI tests → generated docs → board archive → split the three 500-line functions | ☑ complete (2026-09-11 to 2026-09-12) — thirteen cards W31-C0…C10, C8 split in two; C9 and C10 opened by defects the work surfaced |
| — | **Wave 30** (not a phase): in-flight bash cancellation, non-interactive approval outcome, trace subscriber, harness contract + command | ☑ complete (2026-09-12) — five cards W30-C1…C5. C1 merged on a second pass after a pipe-drain regression; C2 and C3 formed a seam that emptied the contract's blocked payload until a round-trip test was added |
| — | **Wave 32** (not a phase): documentation truth pass — four parallel audits over disjoint doc groups, then seven cards splitting the drift Phases 24 and 25 left | ☑ complete (2026-09-12) — removed a script, CI workflow and hook that never existed; swept a repeat of defect W19-5 from the quick start; and found one anti-pattern in three places, a spec index, an env-var table and a blueprint list each checked against retyped rather than derived reference data |
| — | **Wave 33** (not a phase): audit of the Wave 32 closure, repository hygiene, docstring-only comment sweep | ☑ complete (2026-09-13) — the closure held (gates, baselines, metrics all in sync); fifteen merged worktrees, eight merged branches, a spent migration script and two never-running skips retired; thirteen bounded docstring packets merged, each proved AST-identical with docstrings stripped, and the comment baseline ratcheted to 372/40. Found the gitignored CLAUDE.md still calling session compaction unwired two waves after W20-C2 wired it |
| — | **Wave 34** (not a phase): finish the D-36 function split behind a function-span ratchet, two measured fixes, one read-only audit | ☑ complete (2026-09-13) — `tests/guards/test_function_span.py` (150-line ceiling, closures included) listed seven functions; C1 to C4 split `run_agent_turn` (909 lines, twenty closures), `compact_session`, `do_POST` and `_doctor_json` with zero behaviour change, each proved by an unchanged public API and untouched tests, leaving one deliberate entry; C5 made the harness cancellation test deterministic under load; C6 gave the duplicated provider credential table one owner; A1 found the fourth unwired-machinery instance, `docket gates enable/disable` writing a flag nothing on the live path reads while spec, README and command help claimed it changed delivery, and C7 made those claims true (wire or retire stays an open maintainer decision) |
| — | **Wave 35** (not a phase): second docstring sweep, one dead flag, one lane rule | ☑ complete (2026-09-13) — six docstring-only packets (C1 to C6) over twenty-five modules, each proved AST-identical with docstrings stripped, took the comment baseline from 372/40 to 229/29; C7 retired `FleetSecurity.gatesEnabled`, a flag with no live-path reader and no product writer (spec 0.19.2); C8 made every integration test's `SUBJECT` an importable `docket` path, guarded by `test_layout.py` (spec 2.17.0, seen red on seven free-text values). Two things the wave found on the way: `scripts/gen_cli_docs.py --check`, a CI job, had raised ImportError since the Wave 34 credential-table merge because the integrator's batch gates never ran it (fixed, and added to the gates), and the `maintain sessions` banner still said sessions are never compacted (corrected) |
| — | **Wave 36** (not a phase): eleven code-side defects found by the 2026-09-19 documentation audit (D-40) | ☑ complete (2026-09-21) — three batches by file contention, ten code fixes and one prose sweep, all eleven merged with RED tests; C6 proved live on the local endpoint (research pod 5 hops to done, ops pod reaches `waiting_approval`). Batch 1: project-id validation at the core provisioning boundary (C1), `docket mcp servers add` unreachable through Click (C2), MCP approvals that never resume a dispatch task (C4), `maintain rebuild` bare-deleting memory (C5), blueprint pipelines never executed — the fifth unwired-machinery instance (C6), verify-command orphans on timeout (C7). Batch 2: HTTP approval-channel forgery (C3), CLI `--json` types (C8), the inert `--debug` flag and PRICE-override claim (C9), budget warnings that read a cost that is always zero (C10). Batch 3: a docstring and spec sweep (C11). Cards in [TODO.md](TODO.md); worker packets in [.agents/handoffs/wave-36-worker-packets.md](.agents/handoffs/wave-36-worker-packets.md) |
| — | **Wave 37** (not a phase): defects found by running the product (D-41) | ☑ complete (2026-09-25) — opened and closed the same day from a six-surface triage; all six cards merged with RED tests, full gates green, and live evidence on the local endpoint (the journey dispatch reaches `done — 3 hop(s)` with `APPROVE`; a `cd`-prefixed production push still asks). Two batches by file contention: bash allowlist + `policies test` parity (C1), exactly-once trace cursor and HTTP contract gaps (C2), console script bypassing aliases and removed-command notices — sixth unwired-machinery instance — plus `help <command>` (C3), harness-v1 schema references (C4); batch 2: approval conflict vs not-found and the measured flake (C5), `cost <id> --json` and unknown-flag rejection (C6). Archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets in [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md) |
| 26 | **The configuration contract (D-42)** — every operator-facing setting has one writer, is validated at write, has a live consumer on the default path, fails closed (governance) or loud (everything else), is observable with provenance, and survives regeneration | ✅ **complete 2026-09-26** (opened 2026-09-25; Waves 38–40, 20/20 cards, one integrator + Sonnet workers in isolated worktrees). A live E2E connection audit (pod → config → custom-role pipeline run, two tasks to `done`) added P26-18 (membership guessed from the id string breaks hyphenated custom roles), P26-19 (a deterministic refusal orphans the task as `running`) and P26-20 (shipped, CI-validated recipes). Governance first: a malformed `block` policy currently fails **open** (P26-1). Context budgets follow the model window instead of a fixed ~24 KB (P26-2/P26-3). Reasoning: [ADR 0008](docs/adr/0008-configuration-contract.md) |

**Deliberately NOT scheduled**, and not a queue to work down — each is cut or deferred behind a named
trigger (see §4.5's prioritization rule, D-24, and §7):

| Not doing | Why |
| --- | --- |
| Multi-tenancy / the tenant axis | **CUT** (D-22, D-24). Trigger to revisit: docket itself serving more than one end customer from one host. |
| Streaming · browser automation | **CUT** by D-24 — no measured need in *this* system. Use MCP for browser tooling. |
| OpenTelemetry **SDK** | Still cut (D-24). What Phase 32 (D-48) schedules is a projection of docket's own trace vocabulary to OTLP/HTTP behind a `kind: exporter` document, with zero dependencies; the SDK, OTLP metrics/logs, sampling and context propagation stay out. D-25's two-runtime trigger governs anything beyond that. |
| Egress lockdown | Shipped as an opt-in mode in Phase 38 (D-55): `docket gates network none`; the default stays open (D-23), and `fetch` remains the inspectable path. |
| A dashboard of our own | Ruled out since Phase 11 and reaffirmed by 22 — docket feeds one. |
| Build-agent profile · MCP listing cache · Go/Rust rewrite | Deferred behind named triggers. |

Session compaction is no longer in this deferred table: its trigger fired and W20-C2/C2b shipped
the live fail-closed and hierarchical paths. W20-C3 then measured material cross-hop duplication,
and W20-C4 closed it with step-scoped durable histories while preserving typed handoffs.

**Known-true limits live in [README.md](README.md#known-limits)**, not here — they change faster
than this file.

**Release:** `v0.2.0-beta.3`, cut 2026-09-18 and published by `release.yml` with wheel, sdist,
installer archive, checksums, SPDX SBOM and a GitHub provenance attestation. Changes after it
land under `CHANGELOG.md` `[Unreleased]`; cutting the next beta is a maintainer action through
`release.yml`, not a board card. Every release carries a SemVer `-beta.N` suffix until the project is field-hardened enough to
drop it (see README's beta warning).

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
- **Tests are placed by lane, named by module.** `specs/test-framework.md` §"Lanes and placement" is the contract: one unit file per `src/` module, `integration/` for cross-module behaviour, `guards/` for AST invariants (the ≤ 80-line cap was dropped in test-framework 2.15.0; the shrink-only baselines are the bound), `agent/` — outside the default run, ratcheted against a shrink-only baseline, each file declaring `LANE`/`REASON`/`RETIRE_WHEN` — for checks that exist only so an agent does not repeat a recorded mistake. A test that reads prose or builds an artifact is agent-lane by definition.
- **Standing documents only:** `README.md` (front door; the W31-C7 ≤ 150-line target was superseded by the 9a45009 rebuild — it is descriptive per D-37 and pinned by the agent-lane prose tests, not by a line cap), `CONTRIBUTING.md` (working rules), `ROADMAP.md` (direction, decisions index, phase table), a single `TODO.md` (active and planned boards), `CHANGELOG.md` (release notes), `docs/cycles-ended/` (every closed board/phase section and the decision changelog, byte-preserved with a manifest), `docs/adr/` (one file per reasoned decision), `specs/` (current-state contracts), and generated reference under `docs/`. No bespoke document per task; analysis goes to gitignored `internal-docs/`.
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
| D-39 | W29-C7 was the last card on the board: publish a newer beta, verify it on Linux and macOS from public URLs, then close Phase 23. Keep it, or close Phase 23 on the evidence already public? | Phase 23 closure, 2026-09-14 | **Remove the card; close Phase 23 on the published `v0.2.0-beta.2`.** The card's publication half already happened on 2026-09-07: that release carries the root wheel, sdist, versioned installer archive, per-file checksum, `SHA256SUMS`, an SPDX SBOM and a GitHub build-provenance attestation, verified again on 2026-09-14. What remained was a second publication of a tree that has since moved 167 commits, which is a release decision rather than an exit criterion. **What this does not claim:** that the current `main` is released, or that install from the public URLs was re-verified on macOS for beta.2 (Wave 28 verified built artifacts on Ubuntu and macOS; `release.yml` runs on Ubuntu). The next beta is cut by the maintainer through `release.yml` when wanted, and needs no card. |
| D-40 | The 2026-09-19 documentation audit aligned every doc and spec with `v0.2.0-beta.3` and left thirteen places where spec and code disagreed. For each: fix the code, or amend the spec? | Wave 36 | **Fix the code where the spec states a safety, durability or advertised-capability property; amend the spec where it describes something with no measured need.** Code: validate project ids in core (C1), resume dispatch tasks on MCP approvals (C4), never delete memory in `maintain rebuild` (C5), **wire blueprint pipelines into dispatch rather than retire the claim** (C6 — the data is already recorded on the Lead and the change is one function; accepted cost: non-`software` pods run more hops and spend more tokens), kill the verify command's process group on timeout (C7), numeric CLI JSON (C8), budget warnings on the labelled estimate (C10), plus three defects the re-verification found (C2, C3). Spec: `--debug` and the PRICE override are retired, not built (C9); input-validation §2/§4/§5 and the registry-overlay warnings are recorded as deferred or amended to shipped behaviour (C11); `maintain rebuild` refuses pod members instead of gaining a role-aware renderer; verify commands stay uncancellable by `runs cancel`. **Not a defect:** `tack` in `APPROVAL_CHANNELS` is an audit label on the HTTP transport, so "four approval channels" stands. **Not scheduled:** a turn entry point for org specialists — no measured need (§4.5). |
| D-41 | The 2026-09-25 triage (six read-only workers running the product, board clear) found twelve reproducible defects. Three need a design choice: how far to widen the bash allowlist, how to make the trace cursor exactly-once, and whether fixing the harness schema's references is a contract change | Wave 37 | **Allowlist:** add only side-effect-free builtins (`cd`, `pwd`, `echo`, `true`, `false`, `test`, `[`); `export`/`source`/`.`/`eval`/`exec` keep asking because they change what later segments execute; redirection keeps its current classification. `docket policies test` must evaluate through the live gate, not a copy. **Trace cursor:** hold back events from a second that has not closed, keeping the `(ts, n)` wire format, so Tack changes nothing; per-file offsets in the cursor were rejected as more code for the same guarantee. **Harness schema:** hoisting nested `$defs` to the document root changes no field, so it stays `1.0.0` with a changelog line. **Not scheduled:** a CLI writer for `turnTimeoutS`/`verifyTimeoutS` (read live, no measured need for a writer). **Superseded 2026-09-26:** a typed writer for both now exists — see D-42/P26-4. Report: `internal-docs/triage-2026-09-25.md` (gitignored). |
| D-42 | The 2026-09-25 installed-files audit, re-verified at `a592328`, found that customizing agents, pipelines and governance only partly works. Some settings have no live consumer, some have no writer, some fail silently, and one governance path fails open. The request is to make that configuration robust, standard and versatile, and to stop a fixed ~24 KB budget from limiting orchestration. What must the surface guarantee, and what earns a card? | Phase 26 | **Adopt a six-property configuration contract, and schedule only the gaps where a setting breaks it: wiring and validation over existing machinery, not new machinery.** Governance first (P26-1: a broken policy denies instead of allowing). Context budgets become a function of the resolved model window, with protected state and visible, traced truncation (P26-2/P26-3). Pod settings get a typed model and a writer, **reversing D-41's "not scheduled" for a timeout writer**: the silent defaulting of invalid values is the new evidence. Pipeline files become bindable as a pod's default for every trigger (P26-6). Custom roles get hop instructions and `variables` get a consumer (P26-7). A scoped, audited `allowCommands` per pod (P26-8). An operator instruction layer docket never writes, plus `pod sync` (P26-10). `docket config explain` (P26-11). **Shipped recipes** (role+pipeline+policy bundles, CI-validated, applied with existing commands) prove the surface end to end (P26-20). **Deferred with triggers:** a declarative pod manifest, per-agent tool overrides, an on-demand context directory, user blueprints. **Cut:** a bigger budget constant, a second dialect, a plugin system. **Maintainer default:** retire `gates enable/disable` (P26-16). Full reasoning in [docs/adr/0008-configuration-contract.md](docs/adr/0008-configuration-contract.md). |
| D-43 | Phase 26 left roles, policies and MCP servers global per machine, recipes applied by hand in six commands, every MCP tool a write, and the Lead's instruction fixed. The 2026-09-26 request: robust, standard per-pod customization; recipes that apply to any pod; a global layer that is only the structural base; versatile MCP and tool permissions; no overengineering and only the strictly necessary tests. What is the architecture? | Phase 27 | **Three scopes (built-in, global, pod), one resolution rule, one directory per pod, and the recipe directory as the manifest.** Shape (roles, the Lead's instruction) resolves nearest-wins by name, extending today's overlay semantics one level; governance (policies, `deniedTools`) only adds across scopes, reusing the existing most-restrictive-wins evaluation. The MCP catalog stays global and each server *declares* `kind: read|write` and a `tools` allowlist as an audited operator assertion, which lets the existing kind-based narrowing reach read-only roles; a pod selects servers with `mcpServers`. A setting ships only with its reader (P27-4). `docket pod <p> apply [<dir>]` (default `<codebase>/.docket/`) validates a recipe directory plus a three-key `pod.yaml` and writes pod scope only, additively and idempotently; `export` writes the same shape back and the round trip is the proof. **Deferred with triggers:** a pod-local server catalog, model per step, relative `agent:` refs, per-agent overrides, moving the bound pipeline, `blueprints add`. **Cut:** prune/diff reconciliation, auto-apply at `init`, any loader framework. Tests: one RED test per card, a negative case only for governance, no agent-lane or guard additions. Full reasoning in [docs/adr/0009-per-pod-configuration-and-portable-teams.md](docs/adr/0009-per-pod-configuration-and-portable-teams.md). |
| D-44 | Configuration files use two languages, two casings, three vocabularies for one idea and runtime jargon; a verdict gate is a hand-written regex; control flow is one backward edge; policies see rendered text only; and a team with a complex rule has no escape but a fragile regex. The 2026-09-26 request: a standard structure a non-expert can read, clear pipeline and policy languages, and an extension mechanism like Drupal migrate's process plugins. What is the format, and how does code extend it without dissolving the gate? | Phase 28 (after 27) | **One language, one casing, one `kind` envelope; a short form for people over the canonical form the engine already runs; control flow as bounded data; two extension points, never an expression language.** YAML + camelCase everywhere (JSON keeps loading); `load_document` dispatches on four kinds; `docket validate` covers all. Three pure normalisers (role: `cannot`/`verdict`/`instructions.md`; pipeline: `id: role` + `verify|verdict|approval` + `on`; policy: `when`/`then` with `tool`/`path`/`matches`/`branch`/`anyOf`) each proven by a round trip; the engine never sees sugar. `on:` outcome maps with `goto` and a mandatory `max` on backward edges, `until/max`, a closed `when` predicate vocabulary, and command steps (`run:`) as the pipeline escape hatch. Policy escape hatch: Python `@predicate` plugins with a versioned `docket.plugins` API, **loaded only from operator scope** (global or pod, copied with sha256 by `apply`, never imported from the codebase the agent edits), fail-closed and audited per call. **Deferred with triggers:** gate/action plugins, entry-point packaging, `engine: cedar\|rego`, removing the pre-`kind` format. **Cut:** expressions, `not`, unbounded loops, `include`, inheritance, any hook framework. Full reasoning in [docs/adr/0010-config-format-v1-and-extension-points.md](docs/adr/0010-config-format-v1-and-extension-points.md). |
| D-45 | Which providers docket knows lives in seven Python tables with seven populations; the three direct presets (`anthropic`, `openai`, `google`) cannot be activated through the CLI because `provider add` probes `/models` without a credential and reads the host's 401/404 as unreachable; a provider block holds one model and the next `add` replaces it; `api: openai-completions` is written and read by nothing. The 2026-09-26 request: provider selection configurable like roles, policies and pipelines (a YAML document), abstractions that make agnosticism structural, robust and extensible, no overengineering, no legacy left behind. What is the shape? | Phase 29 | **A provider catalog of `kind: provider` documents in two scopes (built-in, global) from which every table derives; a closed `dialect` field with one value that selects the adapter; credentials by name, never by value; registration that verifies with the credential and classifies the answer.** Nearest-wins by name (global over built-in); `fleet.json → providers` ported once into `docket-providers.json`; the document grows one field per reader, never ahead of it (P29-1 core fields, P29-2 presets/prices, P29-4 `auth: header` + `headers`). `client_for` dispatches on `dialect` over a closed dict — a dialect is a file and a release, never a plugin. The `/models` probe moves to `edges/` and its classification stays pure in `core/`: transport failure refuses, every HTTP status registers (401/403/404 with a warning). `provider add <file>`, `list`, `show`, `remove`, `export`; `preset` needs only the credential. `Retry-After` honoured with a 60 s ceiling (the one removable card). `docket auth` retired into the removed-command map; `keys setup` iterates the catalog. **Deferred with triggers:** a second dialect (Anthropic Messages, Bedrock), Azure's `api-version` query, `/models` price discovery, pod-scoped providers, removing `FleetConfig.providers`. **Cut:** automatic model/provider fallback (governance), adapter plugins or entry points, `include`/inheritance/variables. Twelve spec rules amended and listed in the ADR so no two documents disagree; D-18, D-24, D-25 and D-42's "cut: a second dialect" stand. Full reasoning in [docs/adr/0011-provider-catalog.md](docs/adr/0011-provider-catalog.md). |
| D-46 | After Phases 26–29 every layer of a team is a `kind:` document with one loader, schemas, short forms and `pod apply|export`, yet nothing reads a repository's own `.docket/` at `init`, a shipped recipe needs two commands and a wheel path, `export` needs a path, and no record says which directory a pod was configured from; a step cannot name its model and `editRights` is a canonical field nothing applies. The 2026-09-27 repositioning request: the front door is *agent teams as configuration, your rules, in YAML*, and repository configuration files must be handled properly, to standards. What is the shape? | Phase 30 | **The repository's `.docket/` directory is the team's configuration of record.** `docket init` validates it before provisioning and applies it after (or `--recipe <name\|dir>`, mutually exclusive; `--no-apply` to skip); `apply`/`export` default to it; `apply` records `configSource` + `configDigest`, written by nothing else, and `config explain` reports drift; nothing is applied without an operator command (dispatch never re-reads the directory, so an agent editing it changes nothing); repo policies accumulate most-restrictive with the operator's. A pipeline step may declare `model:` (per hop, never persisted, `plan` shows it). `editRights` is accepted and dropped, never written. Assets refreshed from one real run; README rebuilt on the tagline with its prose tests rebuilt from it, not carried forward. **Cut:** auto-apply on dispatch or pull. **Deferred:** multi-pod repositories, top-level `docket apply`, prune/reconcile (trigger: a monorepo with two pods, or prune asked twice); user blueprints (rule of three). Full reasoning in [docs/adr/0012-the-team-lives-in-the-repo.md](docs/adr/0012-the-team-lives-in-the-repo.md). |
| D-47 | A recipe is a directory whose every part is optional, yet nothing derives or prints what one brings, `pod.yaml` has no `description`, the only listing of names is an error message, the three shipped recipes are all whole teams, `apply` records `configSource` only from a directory that changed something, and the recipe policies match prose where `tool`/`path` predicates exist unused; the repository's `AGENTS.md` is read only when an operator names it and the prompt has no skills section. The 2026-09-27 request: recipe handling that is robust, extensible and maintainable; example recipes for the methodologies practised in autonomous-agent orchestration; stronger policy and pipeline recipes; `AGENTS.md` and skills so docket extends under the standards. What is the shape? | Phase 31 | **A recipe's scope is derived from its contents and shown, never declared; the library ships single-concern recipes beside whole teams; the repository's `AGENTS.md` and `.docket/skills/` are read as screened instructions under their standards, while rules from the repository are still applied only by an operator command.** `summarize_recipe` prints one line in `validate`, `apply --dry-run`, `init --recipe` and `recipes show`; `pod.yaml` gains `description`; `apply` records source and digest on every validated apply; three recipe scopes nearest-wins (path, `~/.docket/recipes/`, shipped) and `docket recipes list\|show` (reversing ADR 0012's "no command" on its own rule of three: 3 → 12); four policy packs on structured predicates and five methodology pipelines (`tdd`, `spec-first`, `reflexion`, `dual-review`, `frugal`) over the existing dialect; `AGENTS.md` composes by default as the project-instructions section; skills follow the Agent Skills shape in three scopes with a prompt index and one `skill` tool through the chokepoint; `docs/recipes.md` generated from data. **Cut:** a declared `scope`, recipes shipping MCP servers or credentials, auto-loading a skill by task match, `configSource` as a list. **Deferred with triggers:** nested `AGENTS.md`, a remote recipe source, `skills:` on a role. Full reasoning in [docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md). |
| D-48 | docket records every agent action in a per-session JSONL trace with a closed vocabulary, streams the same records through a subscriber seam for harness mode, measures tokens per exchange and serves Prometheus text, yet none of it can reach an OpenTelemetry collector, Jaeger, Langfuse, Honeycomb or Phoenix; the trace has no event for the model call itself (usage lives in the session record, latency is measured nowhere), telemetry is the last surface configured only by environment variables, and the ingestion bridge bypasses the seam. D-24 cut the OpenTelemetry SDK; D-25's two-runtime trigger has not fired. The 2026-09-27 request: observability and telemetry configurable and adaptable to standards such as OpenTelemetry or Langfuse; solid and maintainable with enough abstraction to add remote destinations simply; destinations as YAML like providers; Langfuse and OpenTelemetry shipped ready, only to be authenticated; without over-sizing. What is the shape? | Phase 32 | **One signal (the trace record, enriched with `llm_call` and a measured latency), one neutral span model in `core/` that projects it with deterministic ids, and destinations as `kind: exporter` documents whose closed `dialect` selects the one edge module that knows the wire; v1 ships one dialect, `otlp-http`, and five dormant built-ins that `docket exporters enable <name>` authenticates and probes.** The local JSONL stays the source of truth; export is a bounded, best-effort mirror that never blocks a turn and sends `payload: metadata` unless the operator chooses `full` (audited); a present key never activates anything; `trace_ingest` notifies the seam; `task_id` rides on the record; `pod.yaml` may name destinations and `apply` only reports their state; `exporters-health.json` feeds `config explain` and `doctor`. **Stands from D-24:** no OpenTelemetry SDK, no OTLP metrics/logs, no sampling, no propagation. **Cut:** exporter plugins from disk, activation by credential presence, streaming spans, exporting `audit.log`. **Deferred with triggers:** an OTLP protobuf dialect (a destination in use rejecting JSON), per-pod exporters (a second operator), monotonic counters (an alert built on `rate()`). Full reasoning in [docs/adr/0014-observability-export.md](docs/adr/0014-observability-export.md). |
| D-49 | Phase 32 exports traces with one knob, `payload: metadata\|full`. Live on Langfuse (2026-09-28) every generation's Input/Output was empty: `full` changes nothing a destination renders (`gen_ai.chat`/`execute_tool` attribute sets are closed and `llm_call` records no content), while `metadata` is a denylist of eight key names, so an approval's `action` and a run's `error` text already leave under the default; nothing shows the operator what leaves. The 2026-09-28 request: privacy levels that are solid and configurable from the exporter's own settings, chosen consciously and evident, so the operator knows what is shared and can turn it off. What is the shape? | Phase 33 | **What leaves the host is a set of named content classes, chosen per exporter as a level (`minimal`/`actions`/`conversation`/`full`) or an explicit `share:` list, enforced where spans are built by an allowlist that maps every attribute to exactly one class, captured upstream only when an enabled exporter asks, and shown before, while and after it is shared.** Every built-in ships `minimal` (including `otel-collector`); defaults and migrations only narrow (a stored `payload` loads as `minimal`); widening is `docket exporters privacy` or `enable --privacy`, confirmed on a TTY or `--yes`, audited with the host; `docket exporters preview` projects a real local session offline; every root span carries `docket.privacy`; conversation content is filtered per message part so a granted class never carries a withheld one; content uses the OTel GenAI `Opt-In` names Langfuse reads natively. **Replaces:** `payload`/`payloadMaxChars`. **Cut:** per-role or per-tool levels, sampling. **Deferred with triggers:** scrubbing beyond `redact` (a secret observed past it), export by reference (a destination refusing span size), a per-pod narrowing cap (a pod needing a stricter level than its exporter). Full reasoning in [docs/adr/0015-export-privacy-levels.md](docs/adr/0015-export-privacy-levels.md). |
| D-50 | An operator assigns several tasks to a pod's Lead and walks away. Nothing tells them that anything needs them: docket never messages first, so the only four real approvals on the development machine expired unanswered. An in-turn `ask` blocks a live thread for 120 s and then denies, and under `serve --dispatch` that stalls every pod, because the sweep walks pods serially. The Lead cannot ask a question, cannot say a task is not ready, and hands the Implementer free prose, while its own prompt says it owns human communication. The 2026-09-28 request: the Lead reasons about a task (missing information or resources, what the Implementer needs); decisions and clarifications are a short conversation with the human; approval is a separate flow; everything reaches the operator in a standard, intuitive way (console, Telegram, email, phone; WhatsApp and Trello named); and assignment, approvals, questions and notifications are usable by a variety of systems in a standard way. What is the shape? | Phase 34 | **One mechanism parks a task for a human, for one of two reasons (a permission or a question); every surface reads one derived inbox; every notification is one CloudEvents contract delivered by a declared `kind: channel`; every answer ends in one of two core functions.** `approvalMode` gains `park`: an in-turn ask records the exact call and parks the task `waiting_approval`; a grant re-enters the hop with a single-use, exact-digest pre-grant. `park` is the default for the `serve` sweep and non-TTY dispatch, `wait` for a TTY, and an explicit pod value wins. Parked approvals expire in 24 h and deny. A new `waiting_input` state and a new `input` pipeline step carry questions in the MCP elicitation shape (`message` plus a flat `requestedSchema`; the answer is `accept`/`decline`/`cancel`). An unanswered question becomes `blocked`, never `failed`. The Lead's intake is an opt-in `intake` recipe: a typed `TaskBrief`, a `READY`/`NEEDS-INPUT`/`REJECT` verdict, deterministic resource checks, and pre-grants for the brief's expected risky actions. Task views carry an A2A 1.0 `a2aState`. `docket inbox` / `GET /inbox` / MCP `inbox` / Telegram `/status` share `core/inbox.py`. Events are CloudEvents 1.0 (`dev.docket.*`), derived from inbox transitions (restart-safe, deduplicated). Webhooks are signed per Standard Webhooks. v1 dialects: `console`, `desktop`, `webhook`, `command`, `ntfy`, `email` (notify only, never decide) and `telegram`, whose Command grammar 7 is amended to allow minimal, selected, non-deciding pushes and a `/answer` verb. **Stands:** fail-closed expiry, D-22/D-24, Tack polls, no public inbound endpoint, no new dependency. **Cut:** a WhatsApp dialect (verified business, templates and a public webhook; reached through `webhook` to an operator gateway), a Trello dialect (a plan of record, not a channel; a bridge consumes `GET /inbox`), deciding buttons in notifications, email that decides, free chat, docket-owned subtasks. **Deferred with triggers:** an A2A binding (a named A2A client), MCP elicitation push (an elicitation-capable client used as the console), Slack/Matrix/GitHub and email converse (daily use through `webhook` plus a request to answer there), mid-turn session resume (re-run misses the granted call in more than 20 % of at least 10 parks), per-pod sweep workers, and `intake` as the `software` default (at least 9 of 10 parseable briefs on the local endpoint). Full reasoning in [docs/adr/0016-operator-loop-and-interop-standards.md](docs/adr/0016-operator-loop-and-interop-standards.md). |
| D-51 | Tack, the plan of record, no longer polls docket: it runs coding agents through four interchangeable harnesses and spawns `docket harness run` as one of them, reading only the final result line. docket is the poorest of the four (decisions `Unsupported`, artifacts and cancel `Advisory`, no policy or budgets passed), and Tack's U8 is blocked because no `harness-v1.1` exists. Pod dispatch discards a passing verify's output, advances without a `verifyCmd`, and records a branch instead of a commit. The 2026-09-29 request: architect docket's part of the structured-agentic-engineering plan (brief, declared loop, structured escalation, merge-readiness evidence, autonomy earned per domain) for parallel Sonnet workers, setting existing ADR limits aside. What does docket become? | Phase 35 (opened 2026-09-29) | **The governed harness of a harness-agnostic factory: it executes, gates and records; it neither plans nor certifies its own work.** An opt-in harness contract v1.1 (process events, stdin answers, written paths, `--token-file`, caller limits, `--recipe` in place); evidence kept on every hop; `requireVerify`; merge readiness and autonomy belong to an independent verifier. Amends ADR 0001 (decision 11; one agent) and corrects ADR 0016 §6. Full reasoning in [docs/adr/0017-docket-in-a-harness-agnostic-factory.md](docs/adr/0017-docket-in-a-harness-agnostic-factory.md). |
| D-52 | D-31 made `main` both the release lineage and the branch every card integrates into, so unreleased phases accumulate on the public default branch. Keep that, or separate integration from release? | 2026-09-29, before Phase 35's first merge | **Separate them: `develop` integrates, `main` releases.** Card branches and worktrees base on and merge into `develop`. `main` moves only by fast-forward (or merge) from `develop` when the maintainer cuts a release or judges `main` too far behind; tags and release jobs still originate from `main`, so D-31's release half stands. The stale `develop` (last moved 2026-07-16, no unique commits) was fast-forwarded to `main` at `6525b52` before this change. |
| D-53 | Phase 35 closed. A gated call still reaches a human as a tool name and an argument digest, with no reason and no choices; only the `intake` Lead can ask a question; and the evidence P35-4 keeps on each hop has no published shape, no per-hop tokens and no trace link, so the independent verifier ADR 0017 §5 names has nothing stable to read. What does docket add? | Phase 36 (opened 2026-10-04) | **Every escalation is a decision with options, and every hop's evidence is a published document.** operator-v1.1 (kind, options, recommendation, optionId; v1 unchanged); `reason`/`actor` on grant and deny; approval packs; a `consult` tool for every role, bounded per task; a per-pod corrections ledger (recorded, never turned into directives by docket); evidence-v1 served identically by CLI, HTTP and harness; escalation metrics in counts and seconds. Full reasoning in [docs/adr/0018-consultation-packs-and-evidence-v1.md](docs/adr/0018-consultation-packs-and-evidence-v1.md). |
| D-54 | Phase 36 closed. A task's evidence can include another task's work (one worktree per Implementer, `baseCommit` a merge-base with nothing merged), MCP tool results reach the model unscreened, a `run:` step cannot name the task's base commit, and a looping agent runs to `max_iterations`. What makes a task's execution checkable by someone other than docket? | Phase 37 (opened 2026-10-04) | **A task runs in its own worktree, and what it brings back is screened and checkable.** One worktree per task created at claim, with the recorded base as `baseCommit`; MCP results pass `pre_input`; command steps get `DOCKET_TASK_ID`/`DOCKET_BASE_COMMIT`/`DOCKET_HEAD_COMMIT`; a `no_progress` stop; recipes may declare pod-scoped MCP servers (live only through `pod apply`); `mutation`, `anti-tautology`, `spec-writer`, `cross-family-review` and `code-intel` recipes. docket runs the checks and never scores them. Full reasoning in [docs/adr/0019-verification-ready-execution.md](docs/adr/0019-verification-ready-execution.md). |
| D-55 | Phase 37 closed. An agent's process runs on the operator's whole machine unless the operator opted into isolation: `bash` inherits the host environment and its credentials, a stdio MCP server starts unjailed, fetched pages reach the model unscreened, no backend cuts the network, and one slow pod stalls every pod's sweep. Measured: under bwrap a task worktree cannot `git commit`, and docker's default image has no `git` or `python3`. What envelope does an agent run in by default? | Phase 38 (opened 2026-10-05) | **Every agent process runs in a jail by default, and nothing docket holds leaks into it.** Isolation on by default with a preflight (bwrap first; the task worktree's git dirs writable); `gates network none` and a pod `network` setting as an opt-in lockdown (the default stays open, ADR 0004); stdio MCP servers jailed unless declared `isolate: false`; file tools confined against symlink walks; `fetch` results pass `pre_input`; docket's credentials stripped from task processes; one sweep worker per pod; the redaction pattern bounded. `kind: autonomy` and credential minting are deferred to named triggers. Full reasoning in [docs/adr/0020-the-execution-envelope.md](docs/adr/0020-the-execution-envelope.md). |

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

`docket` **0.2.0-beta.3** is the current release — every release from this project carries a SemVer
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

**Branch model for this program:** D-31 supersedes the earlier fork-candidate arrangement.
**`main` is the canonical public/default and release lineage**; the completed `platform` history was
fast-forwarded into it without rewriting either branch. `platform` may remain as a synchronized
integration ref during Wave 26 cleanup, but it is not a second release source. Feature/card branches
target `main` (or an explicitly named temporary integration branch that must land before release).
Specs on the release lineage describe the code, not aspirations, and R-8 keeps them that way.

---

