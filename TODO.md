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
> ## ▶ ACTIVE BOARD — WAVE 106 (Phase 42's sub-wave C, P42-4 ∥ P42-5; opened 2026-10-13)
>
> **Phase 42** (lights-out profile and external gate, D-61,
> [ADR 0025](docs/adr/0025-lights-out-profile-and-external-gate.md), accepted with amendments)
> opened 2026-10-13; sub-wave A closed in Wave 104, sub-wave B (the external gate) in Wave 105
> (rollup `96e580ad`). **Wave 106** runs sub-wave C: **P42-4** (the `lights-out` profile) and
> **P42-5** (evidence 1.1.0), one Sonnet worker each in an isolated worktree at `96e580ad`,
> function-level ownership of `core/dispatch.py`, merge P42-5 then P42-4; packets in
> [.agents/handoffs/phase-42-worker-packets.md](.agents/handoffs/phase-42-worker-packets.md).
> **Phase 41** (D-60, [ADR 0024](docs/adr/0024-one-execution-envelope.md)) closed 2026-10-13,
> archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
>
> **Wave 97 closed 2026-10-08** (no phase): the live-run triage cards B–E, archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
>
> ## ☑ WAVE 89-90 COMPLETE — closed 2026-10-05 (archived in docs/cycles-ended/)
>
> **Waves 89–90 closed 2026-10-05** (no phase; ROADMAP, ADR 0020 "Closed by Waves 89–90"): every
> item carried out of Phases 36–38 is closed; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). It shipped unjailed MCP
> servers visible per pod, a jail that cannot write a submodule's or a linked worktree's git
> metadata and commits with the operator's identity, a two-stage `serve` stop, `worktrees prune`,
> options in notifications and Telegram `/answer`, a real-docker oracle, `env:` on `run:` steps, the
> parked consult question persisted, `approve_task` across a task's later hops, and a policy `ask`
> on `consult` no longer asking twice. Not pushed. No phase is planned: the next step is triage.
> `kind: autonomy` and per-task credential minting stay deferred to their triggers.
>
> ### Phase 38 closed 2026-10-05
>
> **Phase 38 closed 2026-10-05** (ROADMAP D-55,
> [ADR 0020](docs/adr/0020-the-execution-envelope.md)): eleven cards over Waves 85–88 (nine
> planned, two found while integrating: P38-10 from the live run, P38-11 from a measurement); the
> section is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> It shipped isolation on by default (bwrap first, a jail that can commit, hooks and config
> read-only), an opt-in `network none`, stdio MCP servers in the jail, file tools confined against
> symlinks and `..` selectors, `pre_input` on `fetch` results, docket's credentials stripped from
> task processes, one sweep worker per pod, posture refusals that are not retried, and a bounded
> redaction pattern. Not pushed. No phase is planned: the next step is triage.
>
> **Phase 37 closed 2026-10-04** (ROADMAP D-54,
> [ADR 0019](docs/adr/0019-verification-ready-execution.md)): nine cards over Waves 82–84; the
> section is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> It shipped one git worktree per task (created at claim, recorded on the task, the evidence base),
> `pre_input` on MCP tool results, task coordinates for command steps, a `no_progress` stop,
> recipe-declared pod-scoped MCP servers started in the turn's root, and the `anti-tautology`,
> `mutation`, `spec-writer`, `cross-family-review` and `code-intel` recipes. Not pushed.
>
> **Phase 36 closed 2026-10-04** (ROADMAP D-53,
> [ADR 0018](docs/adr/0018-consultation-packs-and-evidence-v1.md)): eleven cards over Waves 76-81
> (ten P36 cards plus the Phase 35 follow-up P35-12); the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). It shipped operator-v1.1
> (`kind`, `options`, `recommendation`, `optionId`, `reason`/`actor` on grant and deny), approval
> packs with a rationale and three options, the `consult` tool (single turn and pod park), the
> corrections ledger, evidence-v1 behind the CLI, HTTP and the harness result, and escalation
> metrics. Not pushed. Phases 37-38 are planned below and are **not claimable** until their phase
> opens.
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
> `v0.2.0-beta.4` (2026-10-06) is the latest release; the next beta stays a maintainer action.
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


## ◇ PHASE 42 — lights-out profile and external gate (D-61, ADR 0025): opened 2026-10-13, sub-wave A closed in Wave 104, sub-wave B closed in Wave 105, sub-wave C active in Wave 106

> **Opened 2026-10-13.** ADR 0025 was accepted with amendments (its last section): the external
> gate is a command plus an exit map whose four labels route through the existing `on:` map; a
> human is an existing `input` step; the `exec` gate and profile flags, the override pack, risk
> and domain, the corrections export and the attempt ids and digests are cut with named
> triggers. Plan and reasoning: gitignored `internal-docs/adr-0025-plan-2026-10-13.es.md`.
>
> **Sub-waves, by contention on `core/dispatch.py`:** **A** P42-1 ∥ P42-3 · **B** (on A's
> rollup) P42-2 · **C** P42-4 ∥ P42-5 · **D** P42-6 ∥ P42-7. Each worker owns its card's files
> plus its owning spec section; `README.md`, `docs/SECURITY-SIMPLE.md`, `docs/CONFIGURATION.md`,
> CLAUDE.md's limits and this board are the integrator's, rewritten as each card merges (D-37).
> Packets in [.agents/handoffs/phase-42-worker-packets.md](.agents/handoffs/phase-42-worker-packets.md).
>
> **Wave 104 closed sub-wave A (2026-10-13).** Integration findings: P42-3's base-commit view
> lived in a module-global registry keyed by the worktree, and the children of a `parallel` group
> share one worktree on separate threads, so a sibling that ended first cleared the view of one
> still running (reproduced; now a `ContextVar`, `tests/unit/core/test_repo_view.py`). P42-1
> carried a "GATE FAILED" section for a backward route taken on `pass` (now gated on the verify
> label or exit code, one owner `_is_gate_failure_carryover`). Known gap for P42-2: an `input`
> step's answer resumes behind a synthetic operator hop with no `verify`, so the reasons must be
> carried across it.
>
> **Wave 105 closed sub-wave B (2026-10-13).** Integration findings: the gate read its command's
> exit code from a file under the pod cache dir, writable inside the jail, so an agent-written
> test could plant a read-only `0` and pass a failing verifier (reproduced; now
> `system.run_command` returns the process's own status and the file is gone). A short-form
> `input` step dropped an unquoted `on:` (YAML's `True` key), the exact shape of the
> `needs_human` pattern (fixed through `_get_on`). Found for sub-wave C: MCP servers are stdio
> only, so the profile's "no HTTP MCP server" check is dropped; evidence embedded in the harness
> result stays `1.0.0` (a published contract), `1.1.0` is for `task show` and serve.
>
> **Wave 106 closed sub-wave C (2026-10-13).** P42-5 merged first (`44fe0a2e`), then P42-4
> (`30f56be3`); `core/dispatch.py` auto-merged on the function-level split. The integrator added
> the seam test the two cards could not own alone (`6d83f79b`: a dispatched external gate read
> back as evidence 1.1.0's `gate`). P42-4 dropped the HTTP-MCP requirement (stdio only) and
> counts the Implementer's `DOCKET_PORT_*`/`DOCKET_SCRATCH_DIR` and the pod's MCP server env as
> injected variables. The two `setup shell` goldens gained the new `profile` verb, deliberately.

### P42-1 — a backward route carries the gate's output into the rework hop

**Status:** DONE (2026-10-13, merge `5498d4b1`, Wave 104) · **Size:** S · **Model:** Sonnet · **Spec:** pipeline-format.spec.md ("Outcome routing"), pod-dispatch.spec.md ("Bounded hop prompts")

**Trigger (code reading, 2026-10-13, ADR 0025 amendments):** `core/dispatch.py::_run_pipeline`
fills `pending_rework_by_index` only for `kind == "rework"` (a verdict gate's edge). A `routed`
outcome that goes backward (`until: verify`, `on: {fail: {goto: implement, max: N}}`) re-runs its
target with no carryover, and `hop.verify.outputTail` is not in the artifact `_hop_message`
renders, so the Implementer retries without knowing why the gate failed.

**Goal:** when a routed outcome's target is at or before the current step and the routed hop
carries `verify` evidence, the target's next hop gets a `--- GATE FAILED: <step id> ---` section
built from that evidence (the redacted `outputTail`; P42-2 adds reasons), fit to the same
carryover budget and recorded in `_HopComposition` like `REWORK REQUIRED`. A resume (after an
`input` step's answer, or a restart) rebuilds the carryover from the last gated hop the way
`_resolve_resume_state` rebuilds a rework hop.

**Non-goals:** the external gate (P42-2); any change to verdict-gate rework; forward routes.

**Live path:** `core/dispatch.py::_run_pipeline` (the `routed` branch), `_hop_message`,
`_resolve_resume_state`; `core/context.py` only if the section needs its own compile helper.

**Acceptance:** RED on the base: a pod pipeline `implement` (mechanical gate, `until: verify,
max: 2`) whose verify command fails once with a unique marker in its output, then passes; with a
recording fake runner, the second Implementer message contains the marker under `GATE FAILED`;
the task ends `done` with two Implementer hops. A forward route and a pipeline with no route are
byte-identical to today (goldens unchanged). Lane: integration. Oracle: the recorded message.

### P42-3 — repository instructions and skills come from the task's base commit

**Status:** DONE (2026-10-13, merge `a0d58ede`, Wave 104) · **Size:** S · **Model:** Sonnet · **Spec:** agent-loop.spec.md (project instructions, the `project_roots[0]` paragraph), role-archetypes.spec.md (skills scopes)

**Trigger (ADR 0025 evidence row "the project-instructions root is the task worktree"):**
`edges/adapters/docket_runtime.py` passes `roots=(Path(pipeline_worktree),)` and
`core/identity.py::_project_instructions_raw` reads `project_roots[0] / "AGENTS.md"`, so an
Implementer that edits `AGENTS.md` changes what the Reviewer and Tester are told in the same
task. `core/skills.py::discover_skills` reads `<codebase_root>/.docket/skills/` the same way.

**Goal:** when a turn runs in a task worktree with a recorded `baseCommit`, the codebase's
`AGENTS.md`, every `projectInstructions` file and the codebase-scope skills are read from the
blob at `baseCommit` (host-side `git show`/`cat-file` on the git dirs docket recorded, through
`edges/adapters/system.py`), never from the worktree. A file absent at `baseCommit` is absent.
Without a task worktree (`exec` in place, a plain turn) nothing changes. Every run, not only a
profile (ADR 0025 amendments, question 4).

**Non-goals:** pod-scope and global skills; nested `AGENTS.md`; evidence of what applied (P42-5).

**Live path:** `core/identity.py::_project_instructions_raw`/`project_instruction_files`,
`core/skills.py::discover_skills`, the roots passed in `edges/adapters/docket_runtime.py`, a
reader in `edges/adapters/system.py`.

**Acceptance:** RED on the base: a task worktree whose Implementer hop rewrites `AGENTS.md` with
a marker and commits; the next hop's composed system prompt carries the `baseCommit` text and not
the marker. Same for a skill under `.docket/skills/`. The read costs one git call per file per
turn; measure it and record the number in the card's report. Lane: integration. Oracle: the
composed prompt.

### P42-2 — the external gate

**Status:** DONE (2026-10-13, merge `563c6508`, Wave 105) · **Size:** M · **Model:** Sonnet · **Spec:** pipeline-format.spec.md ("Gates", "Outcome routing"), pod-dispatch.spec.md (gate evaluation, "Hop evidence")

**Trigger:** ADR 0025 D1 as amended.

**Goal:** `ExternalGate {type: external, command, timeout?, exitMap?}` in the `Gate` union
(default exit map `{pass: [0], fail: [1], needs_human: [2]}`), short form `gate: {external:
CMD}`, `on:` keys validated against `pass|fail|needs_human|error`, `_default_edge_reachable`
aware of it. `_evaluate_external_gate` shares a helper extracted from `_evaluate_mechanical_gate`
(envelope, fingerprint, redaction, `hop.verify`) and adds only: the exit mapping (`error` for an
unmapped code, a timeout, a jail refusal, a missing command); `DOCKET_GATE_REASONS_FILE` under the
pod cache dir, deleted before the run, read after it (UTF-8 JSON ≤ 64 KiB, `{reasons: [{summary,
...}]}`, else `reasonsInvalid` and the output tail stands in), screened by `pre_input` and
redacted; the reasons in P42-1's `GATE FAILED` section; `hop.verify` gains `label`,
`reasonsInvalid` and the real `exitCode` (mechanical gates keep 0/1). An unrouted `fail`,
`needs_human` or `error` fails the task with failure kinds `gate_failed`, `gate_needs_human`,
`gate_error`. The member's `verifyCmd` is not run by an external gate.

**Non-goals:** `exec` flags, an override, a gate network grant, reading any verdict file.

**Acceptance:** unit: parse, short form, validation errors. Integration with a fake verifier
script exiting 0, 1 (with reasons), 2, 7 and sleeping past its timeout; reasons too large, not
JSON, and pre-existing (deleted before the run, never read). Seam test with real code on both
sides: gate `needs_human` → `on: {needs_human: ask}` → `input` step parks → `answers.answer_task`
`accept` → `answered: {goto: implement, max: 1}` → the Implementer's message carries the reasons.
A pipeline without an external gate is byte-identical (goldens unchanged).

### P42-4 — the `lights-out` profile

**Status:** DONE (2026-10-13, merge `30f56be3`, Wave 106) · **Size:** M · **Model:** Sonnet · **Spec:** security-gates.spec.md (new "Profiles" section), cli-interface.spec.md (`setup profile`), operator-loop.spec.md (doctor/status lines)

**Goal:** `core/profile.py::lights_out_violations(project) -> list[Violation]`, pure, each with
its fix: isolation on with a usable backend; network `none` enforced by the jail (recorded or
pod-level); an `ExternalGate` on every step whose role is an Implementer in the loaded pipeline;
no HTTP MCP server in the pod's effective set; no pod-injected variable named in the secret
store. Recorded globally in the fleet security record (`docket setup profile
lights-out|attended`, audited) and per pod (`PodSettings.profile`, stricter only). One check in
dispatch before a task's first hop (covers `run` and `start --dispatch`): a violation refuses the
task with `profile.refused` audited and nothing run. `doctor` and `status` show the profile and
its violations from the same function.

**Non-goals:** `exec --profile`; risk, domain, `onNeedsHuman`; changing any default (a fresh
install is `attended`, nothing recorded).

**Acceptance:** each requirement has a RED row (profile on, that requirement unmet → refused,
audited, no hop run) and one positive row (all met → the task runs). `attended` and no record
are byte-identical to today (goldens unchanged except the new `setup profile` surface).

### P42-5 — evidence 1.1.0: `gate` and `directives`

**Status:** DONE (2026-10-13, merge `44fe0a2e`, Wave 106) · **Size:** S · **Model:** Sonnet · **Spec:** pod-dispatch.spec.md ("Evidence v1"), cli-json-shapes.spec.md

**Goal:** `core/evidence.py` emits `v: "1.1.0"`: `HopEvidence.gate {label, exitCode,
reasonsInvalid}` only on a hop that ran an external gate; `TaskEvidence.directives [{path,
sha256}]` for the repository files P42-3 composed (recorded on the hop by P42-3's reader, so
evidence reads it, never recomputes it). Schema under `docs/contracts/evidence-v1.1/`. Before
merge, confirm that Tack's evidence parser accepts the new version and fields; if it does not,
the card reports it and the integrator decides.

**Acceptance:** a fixture task with an external-gated hop and an `AGENTS.md` produces both
fields and validates against the new schema; a task without either carries neither field.

### P42-6 — documentation and the live run

**Status:** TODO (sub-wave D, integrator) · **Size:** M · **Model:** integrator

**Goal:** `docs/SECURITY-SIMPLE.md`, `docs/CONFIGURATION.md`, `docs/commands.md` (generated),
the README (D-37: describe what exists); `SECURITY.md` brought to ADR 0024 (it still describes
bwrap, `--no-isolate` and `gates isolate on`); a dated note in ADR 0017 that its "Assay" is the
verifier now called Prill; ADR 0022's `pod <p> corrections` row removed. A live run on the local
endpoint (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`) with a toy verifier that fails once with reasons
and then passes; then `needs_human` answered with `task answer`; then the profile refusing on
this host with isolation off and passing with `setup sandbox on` and network `none`.

### P42-7 — `none` reported where egress is open

**Status:** TODO (sub-wave D) · **Size:** S · **Model:** Sonnet · **Spec:** operator-loop.spec.md / security-gates.spec.md (network)

**Trigger (ADR 0025 question 8):** `core/pod.py::effective_network` returns `none` at scope
`default` when nothing is recorded, and with isolation off egress is open; `doctor`, `status` and
`setup sandbox` may print `none`. **RED first:** reproduce on a fresh home with isolation off; if
every surface already says the network is open or unenforced, close the card as not reproduced.

**Goal:** every surface that prints the network mode says `none (not enforced: isolation off)`
or equivalent when the jail is not on.

## ◇ CARRIED — out of Phase 39 (closed 2026-10-08, archived in docs/cycles-ended/)

Carried out of Phase 39 (ADR 0022 "Closed with, and carried"), maintainer-owned or unscheduled:
- Tack's one string: `"harness", "run"` becomes `"exec"` in
  `objetivosMios/crates/tack-runner/src/harness/docket.rs`, in `docket/probe.rs` (the argv and two
  doc comments) and in the three argv arrays of `docket/tests.rs`, then that crate's harness
  tests. Refused three times by the session's permission classifier; the maintainer applies it.
- The live asset re-capture: done 2026-10-09 (`scripts/maint/capture-doc-journey.sh` on the
  local endpoint, two runs; the gate scene continued with `task answer` in the same throwaway
  home; `scripts/render-doc-assets.py` re-transcribed; `docs/assets/README.md` records it).
- The YieLab landing page (`~/Sites/newPortaflio/content/docket-landing.ts`) after the release
  that ships the names.
- The eighteen locators of the live run (`internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`,
  last section; the six worth a card are in ADR 0022 "Live run"): a triage list, not cards.
- The triage's five cards are closed: A in Wave 96 (`50da5d59`), B–E in Wave 97 (archived).

Deferred to named triggers: `kind: autonomy` (a verifier that emits one) and per-task credential
minting (an issuer a pod needs).
