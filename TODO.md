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
> ## ▶ ACTIVE BOARD — WAVE 76 (Phase 36, D-53) · opened 2026-10-04
>
> **Eleven cards over Waves 76–81**, one worker per card (Sonnet, or Haiku where the card says so)
> in an isolated worktree under one integrator. Every escalation becomes a decision with options,
> and every hop's evidence a published document:
> - operator-v1.1 (kind, options, recommendation, optionId), `reason`/`actor` on grant and deny;
> - approval packs, and a `consult` tool for every role bounded per task;
> - a per-pod corrections ledger, evidence-v1 behind the CLI, HTTP and harness, and escalation
>   metrics.
>
> Wave 76 also carries P35-12, a Phase 35 follow-up: harness `files` stops reporting verify
> artifacts. Decision: [docs/adr/0018-consultation-packs-and-evidence-v1.md](docs/adr/0018-consultation-packs-and-evidence-v1.md).
> Not pushed. Phases 37–38 are planned below and are **not claimable** until their phase opens.
>
> **Phase 35 closed 2026-10-04** (ROADMAP D-51,
> [ADR 0017](docs/adr/0017-docket-in-a-harness-agnostic-factory.md)): ten cards over Waves 71–75
> plus P35-11; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). It shipped the opt-in harness
> contract v1.1 (process events, stdin answers, written paths, `--token-file`, caller limits,
> `--recipe` in place, typed `approvals`) and evidence kept on every pod hop.
>
> **Phase 34 closed 2026-09-29** (ROADMAP D-50,
> [ADR 0016](docs/adr/0016-operator-loop-and-interop-standards.md)): seventeen cards over Waves
> 64–70, one worker per card (Sonnet, or Haiku where the card said so) in isolated worktrees
> under one integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-64-worker-packets.md](.agents/handoffs/wave-64-worker-packets.md).
> What shipped: an unattended pod **parks** instead of blocking (`approvalMode: park`, a
> single-use pre-grant on the re-entered hop); the Lead's typed `TaskBrief` intake asks before it
> builds, with a deterministic resource pre-check and the `intake` recipe; one derived inbox
> (`docket inbox`, `GET /inbox`, the MCP `inbox` tool, Telegram `/status`); notifications as
> CloudEvents over every v1 `kind: channel` dialect (console, webhook, command, ntfy, desktop,
> email, Telegram); questions in the MCP elicitation shape and every task state mapped onto A2A
> 1.0.0; answer surfaces on CLI, `docket chat`, HTTP, MCP and Telegram's new `/answer` verb;
> interruption forecasting (`docket pod <p> explain interruptions`) and pre-grants from intake.
> The integrator's close (P34-17) added three real seam tests (HTTP-driven park→pregrant→
> redispatch, channel content-level enforcement at actual delivery, and the operator's answer
> text reaching the Lead's own re-entry message) and found two real defects by running the
> product rather than reading it: the operator-loop scenario's own `eventsDelivered` counter read
> a health-file key that never existed (always `0`); `--live-model` registered its provider after
> `docket init`, so that path had never actually completed `init`. A third, unrelated regression
> the starter's own persisted-shape check caught: `HandoffArtifact` gained a `brief` field with no
> update to the starter's asserted shape or its own spec. Both deferred triggers this phase left
> behind were evaluated at the close and did not fire (recorded in the ADR, not acted on): fewer
> than 10 real parked approvals exist to measure the pre-grant re-issue rate against, and the
> scripted-backend scenario shows `park` removing the blocking wait it targets — a live model's
> own serial per-hop generation latency is a separate, real cost worth a maintainer's attention,
> not this trigger's condition. `docket inbox`/`channels`/`notify`/`pregrant`/`explain
> interruptions` still lack coverage in `cli-interface.spec.md`, flagged there for a follow-up
> card rather than backfilled under this pass's time budget. Nothing else is parked.
>
> **Phase 33 closed 2026-09-28** (ROADMAP D-49, [ADR 0015](docs/adr/0015-export-privacy-levels.md)):
> six cards over Waves 60–63, one Sonnet worker, then two, then two, then the integrator; the
> section is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md)
> and packets stay in [.agents/handoffs/wave-60-worker-packets.md](.agents/handoffs/wave-60-worker-packets.md).
> What shipped: an exporter document declares what it shares beyond structure (`privacy:
> minimal|actions|conversation|full` or `share:`; `minimal` for every built-in; `payload`
> retired and loaded as `minimal`); an allowlist projection maps each attribute to one class and
> filters conversations per message part; `llm_call` and `tool_result` capture content only
> while an exporter grants it; `docket exporters privacy` widens only after naming what leaves
> and to which host (TTY confirmation or `--yes`, audited); `docket exporters preview` shows the
> exact spans offline; `SHARES`, "Leaves this host", `docket.privacy` on every root span.
> Verified live at three levels with canaries against a local collector and Langfuse, none at
> `minimal`. Lessons: the seam test between two green cards found a real gap twice (the
> per-exporter bound skipped `response`/`arguments`; the live loop never wrote tool output) —
> the second only showed on a real run, because every earlier test fed synthetic records that
> already had the field. Follow-up recorded, not scheduled: the idle flush can emit a session's
> root span twice (`observability-export.spec.md` §"Privacy levels").
>
> **Phase 32 closed 2026-09-28** (ROADMAP D-48, [ADR 0014](docs/adr/0014-observability-export.md)):
> nine cards over Waves 56–59, one Sonnet worker per card in an isolated worktree then the
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-56-worker-packets.md](.agents/handoffs/wave-56-worker-packets.md).
> What shipped: every backend chat-completions exchange is a durable `llm_call` trace event;
> `core/telemetry.py` deterministically projects the trace into a neutral `Span`/`SpanEvent`
> model with `metadata`/`full` payload reduction; a destination is a `kind: exporter` YAML
> document (five ready-made, disabled-by-default: `otel-collector`, `jaeger`, `langfuse`,
> `honeycomb`, `phoenix`) speaking one hand-rolled `otlp-http` wire dialect, no SDK dependency
> (D-24 stands); a bounded queue/background-sender `Pipeline` is wired into every turn;
> `docket exporters list|show|enable|disable|test|add|remove|export` turns a destination on by
> authenticating; a pod names its destinations in `pod.yaml`'s `exporters:`, reported, never
> itself activating. Verified live 2026-09-28 against a real dispatch and a real
> `otel/opentelemetry-collector`; the live Langfuse round-trip was confirmed the
> same day once the operator stored `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`. Two
> recurring integration lessons: independent cards that version-bump the same still-Draft spec
> from the same base conflict on merge, predictably (happened three times, reconciled by hand
> each time); a card's own literal acceptance text can be stale relative to already-shipped code
> from an earlier card in the same phase (P32-8, P32-9) — implement against the verified live
> behavior and record the discrepancy, per AGENTS.md's rule, rather than choosing the convenient
> reading.
>
> **Phase 31 closed 2026-09-27** — see the record below.
>
> **Phase 31 closed 2026-09-27** (ROADMAP D-47, [ADR 0013](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md)):
> seven cards over Waves 53–55, four Sonnet workers in parallel, then two, then the integrator;
> the section is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md)
> and packets stay in [.agents/handoffs/wave-53-worker-packets.md](.agents/handoffs/wave-53-worker-packets.md).
> What shipped: a recipe's scope derived from its directory and shown everywhere (`validate`,
> `apply --dry-run`, `init --recipe`, `docket recipes list|show`), `pod.yaml` `description`, the
> configuration of record written on every validated apply, three recipe scopes with the
> operator's own `~/.docket/recipes/`, twelve shipped recipes of three kinds (teams, policy packs
> on structured predicates, methodology pipelines), `AGENTS.md` read by default as screened
> project instructions, skills in the Agent Skills shape with a prompt index and one `skill` tool
> through the chokepoint, and `docs/recipes.md` generated from the recipes and checked in CI.
> Nothing is parked.
>
>
> **Phase 30 closed 2026-09-27** (ROADMAP D-46, [ADR 0012](docs/adr/0012-the-team-lives-in-the-repo.md)):
> seven cards over Waves 50–51, four Sonnet workers in parallel then the integrator; the section
> is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and
> packets stay in [.agents/handoffs/wave-50-worker-packets.md](.agents/handoffs/wave-50-worker-packets.md).
> What shipped: `docket init` validates and applies a repository's `.docket/` (or `--recipe`),
> `apply` records the configuration of record and `config explain` reports drift, `export`
> defaults to the repo, a pipeline step names its model, `editRights` is retired, the assets were
> re-captured from one real run, the README leads with "agent teams as configuration, your rules,
> in YAML" with its prose tests rebuilt from it, and the real run's defect (a recipe's role
> resolving to the compiled-in default on a local fleet) is fixed.
>
> No phase is planned. The next card comes from a measured trigger (ROADMAP §4.5), not from
> this file. The two follow-ups parked at the close (`load_role_file`'s `is_short` heuristic and
> `docket init`'s member count) were closed 2026-09-27 in Wave 52, together with
> `docket pod <p> apply <name>` and the newcomer docs pass (see the roadmap changelog). Nothing
> is parked.
>
> **☑ Phase 29 complete (2026-09-27).**
>
> **Phase 29 closed 2026-09-27** (ROADMAP D-45, [ADR 0011](docs/adr/0011-provider-catalog.md)):
> seven cards over Waves 47–49, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> What shipped: providers as `kind: provider` documents in two scopes with every table derived
> from them, verified registration and a CLI round trip, header auth and static headers,
> `Retry-After` with a ceiling, `config explain`/`doctor` coverage, `docket auth` retired.
>
> Waves 47 (P29-1, `0be9812`) and 48 (P29-5 `7bfbbe2`, P29-7 `04a0ffd`, P29-2 `d9e05f8`)
> merged 2026-09-27 with rollups after each. Wave 49 runs P29-4 and P29-3 in parallel (merge
> order P29-4, P29-3), then P29-6 once both are in; one Sonnet worker per card in an isolated
> worktree under one integrator; packets in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> Phase 29 closes when the Wave 49 rollup merges green.
>
> **☑ Phase 28 complete (2026-09-26).**
>
> **Phase 28 closed 2026-09-26** (ROADMAP D-44, [ADR 0010](docs/adr/0010-config-format-v1-and-extension-points.md)):
> eight cards over Waves 44–46, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> What shipped: the `kind` envelope and `docket validate`, short forms for policies, pipelines
> and roles over the unchanged canonical form, structured policy predicates, `on:` outcome
> routing with bounded loops, `when` skips and command steps, operator-scoped hashed predicate
> plugins, generated schemas and short-form export.
>
> Waves 44 and 45 (P28-1..P28-6) merged 2026-09-26 (rollups `ea9e354`, Wave 45 rollup after
> `5622d13`). Wave 46 runs P28-7 (predicate plugins) and P28-8 (schemas, short-form export, docs)
> in parallel; packets (Wave 46 section) in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> Phase 28 closes when the Wave 46 rollup merges green.
>
> **☑ Phase 27 complete (2026-09-26).**
>
> **Phase 27 closed 2026-09-26** (ROADMAP D-43, [ADR 0009](docs/adr/0009-per-pod-configuration-and-portable-teams.md)):
> ten cards over Waves 41–43, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-41-worker-packets.md](.agents/handoffs/wave-41-worker-packets.md).
> What shipped: pod role overlays and pod policies (`--pod`), MCP servers that declare `kind`
> and `tools`, pod `mcpServers`/`deniedTools` with live readers, the Lead's instruction as
> archetype data, `docket pod <p> apply|export` with a round-trip proof, scope labels in
> `config explain`/`doctor`. Two defects found and fixed inside the phase: pod-overlay roles were
> dropped from the roster (P27-9) and `apply` skipped policies (P27-10).
>
> **◇ WAVE 37 CLOSED (2026-09-25) — no card claimed.**
>
> **Wave 37 closed 2026-09-25** (ROADMAP D-41). A bounded triage ran the product on six surfaces
> and found twelve reproducible defects; six cards fixed them in two batches of one-card Sonnet
> workers under one integrator, archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
> [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md). Live
> evidence on the local endpoint: the journey's dispatch scene reaches `done — 3 hop(s)` with the
> reviewer's `APPROVE`, and a `cd`-prefixed production push still asks.
>
> **◇ PHASE 26 CLOSED (2026-09-26) — the configuration contract (D-42).**
>
> **Phase 26 closed 2026-09-26**, 20/20 cards over Waves 38–40, one integrator + one Sonnet
> worker per card in isolated worktrees; the full board section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-38-worker-packets.md](.agents/handoffs/wave-38-worker-packets.md).
> What shipped: fail-closed policies, visible prompt truncation with window-scaled budgets,
> `docket pod <p> config` (nine typed keys), bindable pipelines, step instructions with
> `--var`, `docket config explain`, one default model of record, registry retention,
> `INSTRUCTIONS.md` + `pod sync`, `projectInstructions`, loud doctor config errors, and three
> shipped recipes. Reasoning: [ADR 0008](docs/adr/0008-configuration-contract.md); user guide:
> [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
>
> **Follow-ups parked with named triggers** (small, none scheduled): serve.py's webhook does not
> catch a bound-pipeline `DispatchError`; `cli/_agents.py`/`cli/_install.py` carry their own copy
> of the retired HEARTBEAT-write instruction; `doctor --json` lacks the new checks; pod
> subcommand completions omit `set-verify`/`sync`; `cli-interface.spec.md` prose for
> `runs prune`/`conversations prune`.
>
> `v0.2.0-beta.3` (2026-09-18) is the latest release; the next beta stays a maintainer action.
> A card becomes claimable only when the integrator opens a planned section below and confirms its
> batching from function-level contention.
>
> **Measured, not scheduled:** `tee` is on the bash allowlist, so `echo x | tee f` writes a file
> without asking (pre-existing, not introduced by W37-C1); `docket help <command>` renders through
> `typer.testing.CliRunner`; `turnTimeoutS`/`verifyTimeoutS` gained their typed writer in
> Phase 26 (P26-4), superseding the earlier "no dedicated writer" note here. A new wave starts from bounded triage, not from this note.
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
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
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

## ▶ WAVE 76 ACTIVE — Phase 36, consultation packs and evidence-v1 (D-53), Waves 76–81 (opened 2026-10-04)

Reasoning in [docs/adr/0018-consultation-packs-and-evidence-v1.md](docs/adr/0018-consultation-packs-and-evidence-v1.md).
Phase 35 closed at `184e02e` (archived in `docs/cycles-ended/todo-waves.md`). Not pushed.

**Contract rule (the W30 seam lesson, as in Phase 35).** P36-1 owns every operator-v1.1 model,
and P36-3 owns every evidence-v1 model. Later cards build values through those models, never
through a hand-built dict. When a card adds a field to a published contract (operator, harness or
evidence), it regenerates that contract's schema with its generator script, never by hand, and
v1 bytes stay the same.

**Workers.** Each card runs in an isolated worktree that is reset to `develop` before editing. The
worker diffs from `git merge-base`, commits on its branch, and never merges, pushes, stashes, or
edits `TODO.md`/`ROADMAP.md`/`CONTRIBUTING.md`. The integrator rebases, gates, merges, and bumps
spec versions.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 76 | P35-12 ∥ P36-1 ∥ P36-2 | `cli/_harness.py::_touched_files` and its callers' snapshot, `core/dispatch.py::_evaluate_mechanical_gate` (verify fingerprint only), `edges/adapters/system.py` (status fingerprint) → P35-12; `core/operator_contract.py` (all v1.1 models), `scripts/gen_operator_schemas.py`, `docs/contracts/operator-v1.1/` (new), `operator-loop.spec.md` new section → P36-1; `core/approval.py::approval_grant`/`approval_deny`, `cli` approve/deny `--reason`, `serve.py` approval POST body (`reason` only), `security-gates.spec.md` → P36-2 |
| 77 | P36-3 | `core/evidence.py` (new), `core/dispatch.py::HopResult`/`_hop_record`/`_hop_from_record` and the hop's usage capture, `scripts/gen_evidence_schema.py` (new), `docs/contracts/evidence-v1/` (new), `pod-dispatch.spec.md` |
| 78 | P36-4 ∥ P36-5 ∥ P36-6 | `cli/_pod.py` (`evidence` branch), `serve.py` (the evidence GET route), `cli/_harness_recipe.py::_hop_view` → P36-4; `core/corrections.py` (new), one call each in `approval_deny`, `core/answers.py` decline, the Reviewer `REQUEST-CHANGES` site in `core/dispatch.py`, `cli/_pod.py` (`corrections` branch) → P36-5; `core/tools.py` (the approval request path), `core/agent_loop.py` (the rationale hand-off), `core/approval.py::approval_create`, the harness `approval_requested` payload → P36-6 |
| 79 | P36-7 ∥ P36-9 | `core/tools.py` (`_consult_tool`), `core/archetypes.py::BUILTIN_TOOL_KINDS`, `core/pod.py` (`maxConsultationsPerTask`), `cli/_harness.py`/`_harness_answers.py` (consult questions) → P36-7; `serve.py::render_metrics`, `cli` `metrics --escalation` → P36-9 |
| 80 | P36-8 | `core/dispatch.py` (consult park and re-entry), `core/answers.py` (consult answers) |
| 81 | P36-10 (integrator) | seam tests, live run, docs, spec bumps, rollup, archive |

`cli/_pod.py` is shared by P36-4 and P36-5 in Wave 78. Each adds exactly one `elif` branch and
its own `_pod_<verb>` function, and the integrator resolves the adjacent-line conflict.

Every card follows the §"How to use this board" definition of done.

### P35-12 — `files` stops reporting verify artifacts and pre-existing dirt (Phase 35 follow-up)

**Status:** IN-PROGRESS (worker, Wave 76) · **Size:** S · **Model:** Sonnet · **Spec:**
`harness-mode.spec.md` §4

**Trigger:** the P35-10 live run (ADR 0017 "Live run"): `files` listed `__pycache__/*.pyc`
produced by `--verify "python3 -m compileall -q ."`.

**Goal:** `files` means "what this run changed":
- paths dirty before the run and unchanged at the end are dropped;
- paths that appeared or changed only during a verify command are dropped;
- in both cases the model's own traced write/edit wins.

The mechanism is a snapshot (fingerprints), not a name list. Paths the model wrote with `bash`
still appear.

**Acceptance:**
- A verify artifact is absent from `files`, and the seam test asserts it.
- A pre-existing dirty file the run did not touch is absent.
- A pre-existing dirty file the run edited is present.
- The P35-6 bash-untracked test still passes.

### P36-1 — operator-v1.1: kind, options, recommendation, optionId

**Status:** TODO · **Size:** M · **Wave:** 76 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md`
new section "Contract 1.1"

**Goal:** in `core/operator_contract.py`:
- `QuestionKind` = `approval|clarification|decision`;
- `Option{id, label, description, risks: list[str], estimatedTokens: int|None}`;
- `Recommendation{optionId, rationale, evidenceRefs: list[str]}`;
- `QuestionV11` = `Question` plus `kind`, `options`, `recommendation`. A validator checks that
  the recommendation's `optionId` names an option and that option ids are unique;
- `AnswerResultV11` = `AnswerResult` plus `optionId`. With `action: accept` and options present,
  `optionId` is required and must name an option.

`scripts/gen_operator_schemas.py` also writes `docs/contracts/operator-v1.1/`.

**Non-goals:** any producer or consumer of the new models (P36-6, P36-7, P36-8); changing v1.

**Acceptance:**
- v1 schema files are byte-identical.
- The v1.1 schemas are generated, and the generator's `--check` mode covers them.
- Unit tests cover each validator: unknown `optionId`, duplicate ids, `accept` without
  `optionId`.

### P36-2 — approval grant and deny gain `reason` and `actor`

**Status:** TODO · **Size:** S · **Wave:** 76 · **Model:** Haiku · **Spec:** `security-gates.spec.md`

**Goal:**
- `approval_grant(token, channel="unknown", *, actor="", reason="")` and the same for
  `approval_deny`.
- A non-empty `reason` is screened with `core.policy.policy_eval_detail("lead", "pre_input",
  reason, trusted=False)`. A blocked reason raises the module's existing error, and nothing is
  resolved.
- The audit detail gains `actor=` and `reason=` (redacted like every audit field), and the trace
  payload gains `actor` and `reason` when non-empty.
- Surfaces:
  - `docket approve|deny <token> --reason TEXT`, where the actor is the OS user;
  - the HTTP approval POST accepts an optional `reason` (the actor is the channel);
  - the harness stdin answer passes `content.reason` when it is a string.

**Non-goals:** Telegram/MCP reason syntax; storing reasons anywhere else (P36-5).

**Acceptance:**
- A CLI deny with `--reason` writes an audit line carrying the reason and actor.
- A reason that trips a `pre_input` block leaves the approval pending.
- With no reason, the audit line and trace payload are byte-identical to today.

### P36-3 — evidence-v1: the model, per-hop tokens and trace link, the schema

**Status:** TODO · **Size:** M · **Wave:** 77 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md`
new section "Evidence v1"

**Goal:**
- `core/evidence.py` holds the Pydantic models: `HopEvidence{role, stepId, ok, verdict, verify,
  commit, baseCommit, diffStat, usage{input, output}, trace{project, session, firstTs, lastTs}}`
  and `TaskEvidence{v: "1.0.0", pod, taskId, status, hops[]}`.
- `task_evidence(project, task_id) -> TaskEvidence` is the one builder, reading the persisted
  task record.
- Dispatch records each hop's measured `TokenUsage` (from the turn result, never estimated) and
  the trace session id plus first and last event timestamps on the hop record. That is the
  identifier `GET /traces` and `docket trace` accept, so verify it.
- `scripts/gen_evidence_schema.py` (with `--check`) writes `docs/contracts/evidence-v1/schema.json`.

**Non-goals:** surfaces (P36-4); scores or verdicts about the evidence (ADR 0017 §5); dollars.

**Acceptance:**
- A scripted 3-hop dispatch yields `task_evidence` with three hops and non-zero measured usage
  on each.
- The trace link resolves to that hop's events through the existing trace reader.
- The schema `--check` passes in CI's docs job.
- Old task records without the new fields still build (fields null).

### P36-4 — evidence-v1 surfaces: CLI, HTTP, harness

**Status:** TODO · **Size:** M · **Wave:** 78 · **Model:** Sonnet · **Spec:** `serve-read-api.spec.md`,
`cli-interface.spec.md`, `harness-mode.spec.md` §6

**Goal:**
- `docket pod <p> evidence <task> [--json]` (`--json` prints `task_evidence(...).model_dump_json`).
- `GET /tasks/<p>/<id>/evidence`, Bearer-authenticated like `/tasks/<p>`, 404 for an unknown
  task.
- The harness v1.1 recipe result's `task.evidence` is the same document.

All three call `core.evidence.task_evidence`.

**Acceptance:**
- One task's evidence through the CLI `--json`, HTTP and the harness compares equal.
- An unauthenticated GET returns 401.
- `gen_cli_docs --check` passes after the docs are regenerated.

### P36-5 — the corrections ledger

**Status:** TODO · **Size:** M · **Wave:** 78 · **Model:** Haiku · **Spec:** `operator-loop.spec.md`
new section "Corrections"

**Goal:**
- `core/corrections.py::record(project, kind, *, task_id, role, text, source)`, where kind is
  `deny_reason|request_changes|declined_answer`. It appends one JSON line to
  `$DOCKET_HOME/corrections/<project>.jsonl` (D-12 exemption, file mode 0600, the text redacted
  like trace payloads), and `read(project) -> list[dict]`.
- Writers, one call each:
  - `approval_deny` when a reason is given;
  - `core/answers.py` on `decline`;
  - the Reviewer hop when its verdict is `REQUEST-CHANGES` (the hop output text, tail-bounded).
- `docket pod <p> corrections [--json]`.

**Non-goals:** deriving directives (cut by ADR 0018); a deny without a project (skip it).

**Acceptance:**
- Each of the three writers produces one line.
- The file is 0600.
- `corrections --json` round-trips.
- A failed write never fails the deny, answer or hop (log it to stderr through the existing
  helper).

### P36-6 — approval packs: rationale and three options

**Status:** TODO · **Size:** M · **Wave:** 78 · **Model:** Sonnet · **Spec:** `security-gates.spec.md`,
`harness-mode.spec.md` §5

**Goal:**
- The assistant text content of the message that made a gated call becomes its `rationale`:
  screened with `pre_input` as untrusted (a blocked rationale becomes `""` and is traced), then
  truncated to `APPROVAL_RATIONALE_MAX_CHARS = 500`.
- `approval_create` stores `rationale` and `options` (three `operator_contract` v1.1 `Option`s:
  `approve_once`, `approve_task`, `deny`) on the approval record and on the `approval_requested`
  payload.
- The harness v1.1 stdin answer accepts `content.optionId`:
  - `approve_task` grants and records a single-task pre-grant through the existing pre-grant
    path;
  - `deny` uses `content.reason` (P36-2).

  Regenerate the harness v1.1 schema if a model changes.

**Non-goals:** rendering options in Telegram or notifications (deferred by ADR 0018).

**Acceptance:**
- A scripted turn whose message says "need to run the tests" before a gated `bash` call shows
  that rationale on `approval_requested`.
- A 2,000-char rationale is truncated.
- An injection-shaped rationale is blanked.
- `approve_task` pre-grants a second identical call in the same task.
- The v1.0 harness stream is byte-identical.

### P36-7 — the `consult` tool: single turn, harness stdio, refuse, the cap

**Status:** TODO · **Size:** M · **Wave:** 79 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md`
"Consult", `harness-mode.spec.md` §5

**Goal:**
- A built-in `consult` tool, kind `read`, in `BUILTIN_TOOL_KINDS`. Its arguments are `kind`
  (`clarification|decision`), `message`, `options[]` (at least two) and `recommendation`, and
  they are validated through P36-1's `QuestionV11`. An invalid call is an error result.
- Under harness `--answers stdin`: the `question_asked` event (or the existing question event
  name, if one exists in `EVENT_TYPES`) carries the question. The stdin reader routes a
  `questionId` answer to the waiting call, and the tool result is the chosen option and content.
  `--answer-timeout` bounds the wait, and on timeout it returns "no answer, decide yourself".
- Under `refuse`: the turn ends `blocked`, and the question pack is in the v1.1 result.
- Pod setting `maxConsultationsPerTask` (default 3): past the cap the tool returns an error
  result without asking.

**Non-goals:** park and re-entry in pod dispatch (P36-8).

**Acceptance:**
- A scripted turn that consults and gets an answer line receives the chosen `optionId`.
- A consult without a recommendation is refused.
- The fourth consult in a task is refused without a question event.
- A Reviewer can consult.
- The result validates against the committed harness v1.1 schema.

### P36-8 — `consult` parks in pod dispatch and re-enters

**Status:** TODO · **Size:** M · **Wave:** 80 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md`
"Consult"

**Goal:**
- Under `park` (and pod dispatch generally), a consult ends the hop with the task
  `waiting_input`. The question (P36-1 model, `kind`, options) goes on the task the way
  `_run_input_step` mints one.
- `answer_task` resumes **the same role's step**, with the answer in its next message.
- The inbox shows it under `needsYou`.
- The recipe-mode harness (`P35-9`'s answer source) answers it unchanged.

**Acceptance:**
- An Implementer consult parks the task.
- `docket pod <p> answer` with an `optionId` resumes the Implementer, and the answer is in its
  message.
- A declined answer resumes it with "declined", and P36-5 records it.
- `intake` behaviour is unchanged.

### P36-9 — escalation metrics

**Status:** TODO · **Size:** S · **Wave:** 79 · **Model:** Haiku · **Spec:** `serve-read-api.spec.md`
metrics section

**Goal:** in `serve.py::render_metrics`:
- `docket_tasks_started_total` (dispatch claims, from the trace);
- `docket_questions_total{kind,outcome}` (from task `answers[]` and approval resolutions);
- `docket_decision_latency_seconds` as a summary (`_sum`, `_count`) from question `createdAt` to
  `answeredAt`.

`docket metrics --escalation` prints the same numbers as a table. These are lifetime-of-storage
counts, as CLAUDE.md limit 4 says.

**Acceptance:** a fixture home with two answered questions and one approval produces the
expected lines, and the metric names pass the existing name-format test.

### P36-10 — integrator: seams, live run, docs, close

**Status:** TODO · **Size:** M · **Wave:** 81 · **Model:** the integrating session

**Goal:**
- **Seam tests:**
  - consult over the real `docket harness run --contract 1.1` subprocess, every line validated
    against the committed harness v1.1 and operator-v1.1 schemas;
  - evidence equality across CLI, HTTP and harness.

  Prove each red once by reverting one card's piece.
- **Live run** on `127.0.0.1:8081`: one consult and one approval pack.
- **Close:** docs (D-37), CHANGELOG, spec bumps, `metrics.py --check`, and the board archived
  with `scripts/maint/split_board.py`.

## ◇ PLANNED — Phases 37–38 (D-51 follow-on; not claimable)

These are outlines, not cards. The integrator writes each phase's cards when it opens and
re-verifies every locator against the tree at that moment, because a gap list decays. Each
phase opens only after the previous one closes. The phase that reverses an earlier ADR records
that in its own ADR (ADR 0017 "What this reverses" lists them as not decided yet).

**Phase 37 — verification-ready execution.** Opens after Phase 36.
- `pre_input` screening of **MCP tool results** (today only descriptions are screened).
- A worktree per task instead of per member.
- **Recipes, no core change:**
  - `mutation`: a `run:` step with a threshold, scoped to changed lines;
  - `cross-family-review`: a reviewer with a `model:` from another provider family;
  - `spec-writer`: tests derived from the brief by a different model, before the Implementer;
  - `anti-tautology`: new tests must fail on `baseCommit`.
- A `no_progress` stop reason in the loop: no new passing check or an oscillating diff over N
  iterations.
- An AEE MCP pack as recipes (ast-grep, an LSP server, a semantic index), declared `kind: read`
  where true.

**Phase 38 — the L4 execution envelope.** Opens after Phase 37.
- Isolation on by default, with a preflight. File tools and MCP servers jailed, not only `bash`.
- An egress lockdown mode (`--network none` plus the `fetch` allowlist). This reverses ADR 0004's
  default for autonomy-granted domains.
- Per-pod sweep workers (parallel dispatch across pods).
- Ephemeral per-task credentials.
- A `kind: autonomy` document consumed from the external verifier: domain → required recipe,
  models, checks and authority. docket enforces it; it never computes it (ADR 0017 §5).
