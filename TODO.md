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
> ## ▶ ACTIVE BOARD — WAVE 97 (no phase; the live-run triage cards B–E; opened 2026-10-08)
>
> **Wave 97 opened 2026-10-08**: the four remaining cards of the live-run triage (B–E), one
> worker per card in an isolated worktree under one integrator; the active section is at the end
> of this file, packets in
> [.agents/handoffs/wave-97-worker-packets.md](.agents/handoffs/wave-97-worker-packets.md).
>
> **Phase 39 opened 2026-10-07** (ROADMAP D-57, [ADR 0022](docs/adr/0022-one-cli-surface.md)):
> twenty-six cards over Waves 91–95, the active section at the end of this file. The CLI becomes
> one tree of thirty commands in five groups; the pod is resolved from the directory; every
> redundant or agent-era command, the per-agent model pin, the persona layer and the never-run
> org specialists are deleted outright with no alias or notice. Packets in
> [.agents/handoffs/wave-91-worker-packets.md](.agents/handoffs/wave-91-worker-packets.md).
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


## ▶ WAVE 97 — the live-run triage cards B–E (no phase; opened 2026-10-08)

**Trigger:** the operator asked on 2026-10-08 to close every pending item. The triage of the
eighteen locators of the Phase 39 live run (gitignored `internal-docs/cli-ux-audit-2026-10-07/
triage-2026-10-08.md`; the six worth a card are in ADR 0022 "Live run") proposed five cards; A
closed in Wave 96 (`50da5d59`). B–E are the rest. One Sonnet or Opus worker per card in an
isolated worktree based on the claim commit; the integrator merges in the order C, B, E, D and
owns `CHANGELOG.md`, `specs/README.md`, `docs/commands.md`'s regeneration on `develop`, the
CONTRIBUTING counts and this board. Packets:
[.agents/handoffs/wave-97-worker-packets.md](.agents/handoffs/wave-97-worker-packets.md).

### W97-B — `status` knows a parked question and the sandbox

**Status:** TODO · **Size:** S · **Wave:** 97 · **Spec:** `cli-json-shapes.spec.md`
(`docket status --json`), `cli-interface.spec.md` (`docket status`)

**Today:** `cli/_status.py::_pod_status` counts pending/running/waiting_approval/failed/completed;
a `waiting_input` task (a parked consult or `input` step, operator-loop) counts nowhere and the
pod state stays `ready`, so `docket status` says nothing while `docket inbox` shows a question
waiting (live run, locator #5). The `Isolation:` line is the static string `project workspaces;
dispatch history scoped by step` (locator #14, the audit's P10) and says nothing about the
sandbox posture the operator set with `docket setup sandbox`.

**Goal:** `tasks.waitingInput` in the JSON object and `N waiting input` on the human `Tasks:`
line; a pod with a `waiting_input` task is `waiting` (same bucket as `waiting_approval`, before
`active`); the `Isolation:` line and the JSON `isolation` value report the sandbox state the
`setup sandbox status` reader already computes (`cli/_setup_sandbox.py::sandbox_state`: on/off,
backend, network mode), in one short phrase.

**Non-goals:** a new state name; any change to `inbox`; any write.

**Files:** `cli/_status.py` (`_pod_status`, the human renderer); `tests/unit/cli/test__status.py`;
`tests/golden/cases/readonly/status_--all.golden` (deliberate, explained line by line).

**Acceptance:**
- A pod whose queue holds one `waiting_input` task: `docket status --json` carries
  `tasks.waitingInput == 1` and `status == "waiting"`; the human output's `Tasks:` line contains
  `1 waiting input`.
- A fresh home with isolation off: the `Isolation:` line and JSON `isolation` read the same phrase
  `sandbox_state` implies (off, with the backend found and the network mode); with isolation
  recorded on, the phrase names `on` and the backend.
- Oracle: two RED tests in `tests/unit/cli/test__status.py` fail on the base for exactly those
  reasons; the golden diff shows only the new count and the new line.

**Gates:** ruff, mypy, default lanes, goldens, `validate-specs.sh`, `comment_lint.py --check`,
span check.

### W97-C — help and messages tell the truth

**Status:** TODO · **Size:** S · **Wave:** 97 · **Spec:** `operator-loop.spec.md` (the forecast
line, item 11 area), `pod-dispatch.spec.md` (pod settings, "present-but-invalid")

**Today:** five `Example:` lines in `cli/_task.py` (`approve`, `deny`, `answer`, `retry`,
`cancel`) pass `2026-10-08T10-00`, which is not a task id, short id or run id (locator #10);
`docket pod set budgetUsd notanumber` says `invalid stored value` though nothing was stored
(`core/pod.py::PodSettings._validated` serves the read and the set path with one message,
locator #11); `task add` prints `May ask you: 4 policy` and `task show` lists a policy by its raw
regex (`cli/_task.py` forecast line; `core/interruptions.py::_policy_pattern`, locator #13).

**Goal:** the five examples use `task-04ff` as the other verbs do; the set path says
`<key>: invalid value <v> (<rule>)` and the read path keeps `invalid stored value`; the forecast
line pluralises (`4 policies`, `1 policy`, `2 pipeline gates`); a policy interruption describes
the policy by its id and what it asks on in words (the predicate kind, never the regex text).

**Non-goals:** any behaviour change beyond text; a new interruption kind; validating operands in
the invocation linter.

**Files:** `cli/_task.py` (five docstrings, the forecast line), `core/pod.py::PodSettings`
(`_validated` split or a message parameter), `core/interruptions.py::_policy_pattern`;
`tests/unit/cli/test__task.py`, `tests/unit/core/test_pod.py`,
`tests/unit/core/test_interruptions.py`; `docs/commands.md` regenerated.

**Acceptance:**
- `docket task approve --help` (and the four others) shows `Example: docket task approve
  task-04ff ...`; `scripts/maint/lint_cli_invocations.py --self-check` and the invocation guard
  stay green.
- `PodSettings.coerce("budgetUsd", "notanumber")` raises `PodSettingsError` whose message starts
  `budgetUsd: invalid value 'notanumber'` and does not contain `stored`; `load_for` on a bad
  stored value still says `invalid stored value`.
- A pod with two `require_approval` policies: the forecast line reads `May ask you: 2 policies`;
  `task show` lists each as `policy '<id>' asks on: <words>` with no regex metacharacters.
- Oracle: RED tests in the three unit files fail on the base for those reasons.

**Gates:** ruff, mypy, default lanes, goldens, `validate-specs.sh`, `gen_cli_docs.py --check`
(regenerate `docs/commands.md`), `lint_cli_invocations.py --self-check`, `comment_lint.py
--check`, span check.

### W97-D — `--progress` names the hop

**Status:** TODO · **Size:** M · **Wave:** 97 · **Spec:** `cli-interface.spec.md` ("Foreground
dispatch progress and in-place approval" > "Rendering")

**Today:** `cli/_progress.py::render_event` renders `session_start`/`session_end` as `▶ <role> …`
and `■ <role> finished`; a pod dispatch opens one session per task with role `lead`
(`core/dispatch.py` dispatch session events), so the view prints `▶ lead …` / `■ lead finished`
for the whole run and never names the hop that is running or the one that parked (live run,
locator #1). Spec and code agree, and the output misleads.

**Decision (integrator, 2026-10-08):** the session lines name the task, the hop lines name the
hop, nothing is added to the trace. `session_start` → `▶ <task> …` and `session_end` → `■ <task>
finished — status=<status>`, where `<task>` is the short id (`task-04ff`) of the task the session
id names (`agent:<project>:<task-id>`; fall back to the role when the session id names no task);
dispatch's hop marker (the `tool_call` event whose JSON payload has exactly the keys `hop` and
`agent`, `core/dispatch.py::_run_hop_turn` region) → `  ▶ <hop> …` (two-space indent under the
task line). The approval lines are unchanged. No new trace event type; no core change.

**Goal:** the view above, pinned by `render_event` unit tests and the thread-wiring test; the
"Rendering" section amended (cli-interface 2.1.3; W97-B holds 2.1.2).

**Non-goals:** a hop-end line (no distinguishable event exists without a new type); any change
to `docket exec`; any stdout change (the golden no-change oracle stays).

**Files:** `cli/_progress.py` (`render_event`, `_RENDERABLE_EVENT_TYPES`, a hop-marker
predicate); `tests/unit/cli/test__progress.py`; `specs/api/cli-interface.spec.md`.

**Acceptance:**
- `render_event` on a `session_start` record whose `session_id` is `agent:demo:task-04ff…`
  returns `▶ task-04ff …`; on the matching `session_end` with `{"status":"done"}` returns
  `■ task-04ff finished — status=done`; on a `tool_call` with payload `{"hop":"implementer",
  "agent":"demo-implementer"}` returns `  ▶ implementer …`; on a `tool_call` with any other
  payload returns `None`.
- The thread-wiring test (`TestDispatchWithProgress`) sees the task line, the hop line and the
  approval line in order.
- `bash tests/golden/run.sh verify-all` is byte-identical.
- Oracle: the RED unit tests fail on the base for those reasons.

**Gates:** ruff, mypy, default lanes, goldens, `validate-specs.sh`, `comment_lint.py --check`,
span check.

### W97-E — `setup provider add` records the advertised model

**Status:** TODO · **Size:** S · **Wave:** 97 · **Spec:** `model-profiles.spec.md` ("Provider
readiness" / registration)

**Today:** `docket setup provider add <name> <url>` without `--model` records the row id
`local-model` (`cli/_setup_model.py::_build_spec`), even when the probe the registration runs
(`core/provider.py::register_provider` → `verify_endpoint`) came back 200 with advertised ids,
which it only prints as a warning (`endpoint also advertises: ...`). A hosted endpoint then holds a
model id it never served (live run, locator #8).

**Goal:** when `--model` is absent, the endpoint is custom (no catalog entry) and the probe
advertises at least one id, the registered row is the first advertised id (sorted, as
`verify_endpoint` orders them) and the success line names it; when the probe advertises nothing,
`local-model` stays and the line says so. One probe per `add` (if `register_provider` must probe
before the row is known, pass the probe result through its `probe=` seam rather than probing
twice).

**Non-goals:** changing a catalog entry's rows; refusing a 401/404 (Phase 29's decision stands);
any change to `--model`'s behaviour.

**Files:** `cli/_setup_model.py` (`_build_spec`, `_register`, `add_provider`),
`core/provider.py` only if the probe seam needs a pure helper; `tests/unit/cli/
test__setup_model.py` (+ `tests/unit/core/test_provider.py` if touched).

**Acceptance:**
- A fake probe (`ProbeResult` status 200, `model_ids=("qwen-x","abc")`) and `add custom
  http://127.0.0.1:1/v1` with no `--model`: the saved provider's first row id is `abc`, the
  success output names it, no warning lists it as "also advertises".
- Same with `model_ids=()`: the row is `local-model` and the output says the endpoint advertised
  no model.
- Same with `--model mine`: the row is `mine` whatever the probe advertised.
- Oracle: RED tests in `tests/unit/cli/test__setup_model.py` fail on the base for those reasons;
  `probe_models` is monkeypatched, no real host is called.

**Gates:** ruff, mypy, default lanes, goldens, `validate-specs.sh`, `comment_lint.py --check`,
span check.

---

## ◇ NO ACTIVE WAVE — Phase 39 closed 2026-10-08 (archived above in docs/cycles-ended/)

No phase is planned. The next step is bounded triage or measurement, not a card mined from history.
Carried out of Phase 39 (ADR 0022 "Closed with, and carried"), maintainer-owned or unscheduled:
- Tack's one string: `"harness", "run"` becomes `"exec"` in
  `objetivosMios/crates/tack-runner/src/harness/docket.rs`, in `docket/probe.rs` (the argv and two
  doc comments) and in the three argv arrays of `docket/tests.rs`, then that crate's harness
  tests. Refused three times by the session's permission classifier; the maintainer applies it.
- The live asset re-capture: `scripts/maint/capture-doc-journey.sh` on the local endpoint, then
  `scripts/render-doc-assets.py` re-transcribed from the new transcripts. The committed assets
  show the eleven-command names, but their output lines were rewritten by name, not re-captured.
  Refused by the same classifier, three times.
- The YieLab landing page (`~/Sites/newPortaflio/content/docket-landing.ts`) after the release
  that ships the names.
- The eighteen locators of the live run (`internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`,
  last section; the six worth a card are in ADR 0022 "Live run"): a triage list, not cards.
- The triage's cards B–E: card A closed in Wave 96 (`50da5d59`); B–E are scheduled as Wave 97
  (the section above).

Deferred to named triggers: `kind: autonomy` (a verifier that emits one) and per-task credential
minting (an issuer a pod needs).

