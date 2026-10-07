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
> ## ▶ ACTIVE BOARD — WAVE 93a (Phase 39, one CLI surface, D-57; opened 2026-10-07)
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


## ▶ WAVE 93a ACTIVE — Phase 39, one CLI surface (D-57), Waves 91–95 (opened 2026-10-07)

**Decision:** ROADMAP D-57, [ADR 0022](docs/adr/0022-one-cli-surface.md). Read the ADR's
"Decision" section once; it is the contract every card below answers to. **Trigger (explicit
scoped request, 2026-10-07):** the maintainer asked for the CLI audit's recommendations to be
confirmed and applied in their strict form: every command that is not needed or is redundant is
removed outright, with no alias, no retirement notice and no memory of the old name; what remains
must say what it does and nest under what owns it; and the no-compatibility rule written into the
repository's rules. The result is eleven top-level commands (`init status inbox task run pod log
setup start stop exec`); the noun `pod` stays; `setup` with no verb is the guided first run;
every command speaks with one voice (ADR 0022 decisions 9 and 10). The audit's evidence is in the gitignored
`internal-docs/cli-ux-audit-2026-10-07/`; the facts a card needs are restated in the ADR's
evidence table and in the card itself.

**Shape of the work.** Twenty-four cards over five waves. Wave 91 is the foundation (no rename,
six parallel lanes). Wave 92 is one mechanical card that splits `cli/__init__.py` so every later
card owns one module. Wave 93 builds the tree, one group or sub-group per card. Wave 94 is help,
guards, documentation and assets. Wave 95 is the measurement that closes the phase. **One worker
per card in an isolated worktree based on `develop`; one integrator owns the rollups.** Packets:
[.agents/handoffs/wave-91-worker-packets.md](.agents/handoffs/wave-91-worker-packets.md).
Models: `Sonnet` for code and spec cards, `Haiku` for the documentation sweeps after the
mechanical rename script exists, `Integrator` for rollups, goldens, assets and the live run.

**Rules every card follows (in addition to the board rules above).**
- A removed name is deleted everywhere in the same commit: code, tests, spec text, `docs/`,
  `templates/`, `scripts/`, completions. No alias, no notice, no hidden command, no "was".
  `CHANGELOG.md` lines are returned to the integrator, not written by the card.
- A command with more than one operation is a Typer sub-app (`typer.Typer()` registered with
  `app.add_typer`), with Typer-declared arguments and options only; `ctx.args` parsing is gone
  from the module the card owns. A bare group prints its help (`no_args_is_help`). Every leaf's
  help ends with one `Example:` line.
- Pod-scoped commands take the pod from `cli/_target.py::resolve_pod` (P39-1); confirmations,
  `--json` emission, the non-TTY rule and hints come from `cli/_contract.py` (P39-2). No card
  hand-rolls a second copy of either.
- The card amends its owning spec section first (version bump + changelog line, pre-assigned in
  the packet), writes the RED test, implements, then runs the gates. One unit file per module
  (`tests/unit/cli/test_<module>.py`, `CliRunner`, in-process); exact text goes to the golden
  suite. Goldens are regenerated only for the cases the packet names, with every changed line
  explained in the return.
- The `exec` contract (events, result, exit codes), the HTTP routes, the MCP tool names and the
  Telegram verbs are frozen. `core/tools.py`, `core/agent_loop.py`, `core/policy.py`,
  `core/security.py` are not touched by any card in this phase.

**Wave map**

| Wave | Cards (parallel inside the wave) | Merge order | Contention notes |
| --- | --- | --- | --- |
| 91 | P39-1, P39-2, P39-3, P39-4, P39-5, P39-6 | 4, 6, 3, 5, 1, 2 | P39-4 owns `core/models_policy.py` wholesale and removes its specialist references, so P39-6 never touches it. P39-5 and P39-6 share `cli/_doctor.py` at function level (P39-6: the specialist check only). P39-1 and P39-6 share `cli/_agents.py` at function level. |
| 92 | P39-7 | — | Alone: it moves every command body out of `cli/__init__.py`. |
| 93a | P39-12, P39-13, P39-14, P39-15, P39-16 | 12, 13, 14, 15, 16 | Disjoint modules (`setup`, `log`/`start`/`stop`/`exec`, `run`/`status`/`inbox`, removals). P39-15 owns the dispatch functions of `cli/_pod.py`. |
| 93b | P39-8, P39-9, P39-10, P39-11 | 8, 9, 10, 11 | All take functions out of `cli/_pod.py` or build onto it; ownership is per function, named in each packet. Based on the 93a rollup. |
| 94 | P39-17, P39-18 first; then P39-19, P39-20, P39-21, P39-22; then P39-23 | 17, 18, 19–22, 23 | P39-18's script runs before any Haiku doc card. P39-19 (README) is Sonnet. |
| 95 | P39-24 | — | Integrator, live endpoint. |

**Wave 91 closed 2026-10-07** (six merges `5cbcac79`..`54bb3977` plus the integrator rollup). Follow-ups the workers returned are recorded in the packets file under "Wave 91 returns"; Wave 92 (P39-7) based on the rollup commit.

**Wave 92 closed 2026-10-07** (one merge `a99e0344` plus the integrator rollup): `cli/__init__.py` is a 177-line registry; the worker's return is under "Wave 92 returns" in the packets file. Wave 93a (P39-12, P39-13, P39-14, P39-15, P39-16) is next and bases on the Wave 92 rollup commit.

### P39-1 — one pod resolver: `--pod`, `DOCKET_POD`, then the directory you stand in

**Status:** DONE (merged to `develop` 2026-10-07, `847c637c`) · **Size:** S · **Wave:** 91 · **Model:** Sonnet · **Spec:** `cli-interface.spec.md` (new section "Pod targeting" under "Global Command Structure")

**Trigger (ADR 0022 evidence):** the pod is named seven ways; only `status` and `add` infer it
from the cwd through `cli/_agents.py::_pod_for_directory`; `docket pod dispatch` inside the repo
answers `No pod found for 'dispatch'. Create one with: docket init dispatch` (exit 0).

**Goal:** one function, `cli/_target.py::resolve_pod(explicit: str | None, *, env: Mapping,
cwd: Path) -> str`, used by every pod-scoped command from Wave 93 on and by `status`/`add` now.
Order: explicit `--pod/-p` > `DOCKET_POD` > the registered pod whose codebase contains `cwd`,
deeper match wins. No match raises `TargetError` whose message names the lookup, the flag and the
fix: `No pod for <cwd> (looked for a registered codebase containing it). Run 'docket init'
here, or pass --pod <name>.` Two matches at the same depth name both. `cli/_target.py` also
exports `pod_option()` (one Typer option factory, `--pod/-p`, help text fixed) so every command
declares it identically. `_pod_for_directory` moves into `_target.py`; `cli/_agents.py` and
`cli/_status.py` import it from there.

**Non-goals:** touching any command beyond `status` and `add`; `--project` removal (Wave 93).

**Acceptance:** a home with pods `a` (codebase `/x`) and `b` (codebase `/x/sub`): from `/x/sub/deep`
→ `b`; from `/x` → `a`; `DOCKET_POD=a` from `/x/sub` → `a`; `--pod b` from `/` → `b`; from `/tmp`
with no env → `TargetError` with the exact message above; `docket status` from `/tmp` prints it,
exit 1. Oracle: the resolver's return value and the printed message; `fleet.json` untouched.

**RED:** `tests/unit/cli/test__target.py` (new, `SUBJECT = "docket.cli._target"`), the five cases
above, fails on the base with `ModuleNotFoundError`.

### P39-2 — one interaction contract and one console voice; bare `gates isolate` and bare `notify` stop writing

**Status:** DONE (merged to `develop` 2026-10-07, `54bb3977`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `cli-interface.spec.md` ("Interactive Features", "Output Formats" rewritten as "The console voice", "Return Code Convention"), `security-gates.spec.md` (bare `gates isolate`), `operator-loop.spec.md` (bare `notify`)

**Trigger (ADR 0022 evidence):** three different off-TTY policies for destructive commands
(`delete <pod>` proceeds silently, `maintain` refuses, `exporters privacy` needs `--yes`); bare
`docket gates isolate` turns isolation on; bare `docket notify` delivers; `inbox --bogus` exits 0;
four taglines; `help` and `metrics` print raw ANSI when piped; tables truncate mid-word
(`require_approv`); every module writes its own `[green]`/`[red]` markup; `init`'s next steps
leave out the actual next thing to do.

**Goal (a): the contract.** `cli/_contract.py` with four functions and nothing else: `confirm(action,
*, yes, typed=None)` (TTY: y/N, or the typed name when `typed` is given; no TTY: refuse with exit 1
naming `--yes` or `--confirm <name>`); `emit_json(obj)` (plain `json.dumps` to stdout, never
Rich); `require_value(name, value, flag)` (no TTY and no value: exit 1 naming the flag; never a
picker); `next_step(command)` (one `→ Next: docket ...` line on stderr; silent under
`DOCKET_NO_HINTS=1`). `sys.stdin.isatty()` is probed in one module function tests can patch.

**Goal (b): the voice (ADR 0022 decision 9).** `ui.py` becomes the only place that knows
symbols, colours and layout: five symbols (`✓` done, `✗` failed or refused, `⚠` attention, `→`
next step, `·` detail), five colour roles (`success`, `error`, `warn`, `accent` for names and
ids and commands, `dim`), `header(noun, name)` rendering `docket · pod myapp`, `section(title)`
for the shared section names (`Needs you`, `Running`, `Done`, `Failed`), `table(rows, columns)`
that wraps cells and never cuts a word, `error(what, do)` rendering `✗ <what>. <do>` on stderr,
and plain output (no colour, no boxes, no symbols beyond ASCII `ok`/`x`/`!`/`->`) when stdout is
not a TTY or `NO_COLOR` is set. One tagline constant, `TAGLINE = "docket runs teams of coding
agents and governs what they may do"`, read by the bare greeting, `--help` and `pyproject`. A
shrink-only guard (`tests/guards/test_console_voice.py`, baseline committed) counts Rich markup
literals (`[green]`, `[bold]`, …) outside `ui.py`; every Wave 93 card lowers it for the modules it
rewrites. The copy rule for every later card, pinned in the spec: a command that changes state
ends with exactly one `→ Next:` line; a read command ends with none; an error is one line that
says what happened and what to do.

**Goal (c): two blockers now, one line each.** `cli/_gates.py::run_gates` defaults `want` to
`None` and bare `isolate` prints the status plus `Usage: docket gates isolate on|off`, exit 2,
nothing written, nothing audited; `cli/_notify.py::run_notify` treats `""` as unknown (usage,
exit 2); only `flush` flushes.

**Acceptance:** with stdin not a TTY, `confirm("delete pod x", yes=False)` exits 1 naming
`--yes`; with `typed="x"` it names `--confirm x`; `yes=True` returns. Piped stdout → `ui.success`
writes `ok ...` with no escape codes; a table with a 40-character cell in a 20-column width
wraps and every word survives. Fresh home → `docket gates isolate` → `fleet.json` and `audit.log`
byte-identical, exit 2; `docket notify` with one enabled channel and one pending event → the sink
receives nothing, exit 2. The voice guard is seen red by planting one `[green]` in a module
outside `ui.py`. Oracle: file bytes, the sink file, `json.loads`/regex over captured stdout.

**RED:** `tests/unit/cli/test__contract.py` (new), `tests/unit/test_ui.py` (new or existing
`SUBJECT = "docket.ui"`), one test each in `test__gates.py` and `test__notify.py` (new) for the
two bare commands; the gates and notify tests fail on the base with a written file / a delivered
event.

### P39-3 — one task id everywhere

**Status:** DONE (merged to `develop` 2026-10-07, `5cae754f`) · **Size:** S · **Wave:** 91 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (new requirement "Task references")

**Trigger (ADR 0022 evidence, live run C6):** `pod queue` prints `task-04ff2ff5-7be8`; `chat`
rejects it; `trace` wants `agent:<p>:<task>`, which no command lists; `trace list` errors.

**Goal:** `core/task_ref.py::resolve_task(project: str | None, ref: str) -> TaskRef` resolves a
full id, the short id `task list` prints, or any unambiguous prefix, across one pod or (when
`project` is `None`) every pod; `TaskRef` carries `task_id`, `project`, `session_key`,
`run_ids` and the worktree path when one exists; a harness run id (what `harness status` took)
resolves to the `TaskRef` of the run record, so `task show <run-id>` can replace that command. An ambiguous prefix raises `TaskRefError`
listing every candidate with its pod; an unknown one raises it naming what was searched.
`core/dispatch.py` is read through its existing `read_tasks`; nothing there changes.

**Non-goals:** wiring the resolver into commands (Wave 93 cards P39-8, P39-9 and P39-15 do that).

**Acceptance:** two pods each with a task whose id starts `task-04ff`: `resolve_task(None,
"task-04ff")` raises listing both with pods; `resolve_task("a", "task-04ff")` returns `a`'s;
the short form and the full id resolve to the same `TaskRef`; `session_key` equals what
`core/dispatch.py::step_session_key` produces for the Lead hop. Oracle: equality with the task
record `read_tasks` returns.

**RED:** `tests/unit/core/test_task_ref.py` (new), fails on the base with `ModuleNotFoundError`.

### P39-4 — one role vocabulary: the model policy speaks archetype names

**Status:** DONE (merged to `develop` 2026-10-07, `5cbcac79`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `model-profiles.spec.md` (roles and classes), `role-archetypes.spec.md` (`policy_role` removed), `cli-json-shapes.spec.md` (`models` output)

**Trigger (ADR 0022 evidence, live run C10):** `docket models` lists `manager`/`programmer`/
`reviewer`/`tester`/`knowledge`/`security`/`repo`; pods use `lead`/`implementer`/...;
`core/archetypes.py::RoleArchetype.policy_role` maps one to the other; after `models provider
add` the printed hint `docket profile programmer` fails.

**Goal:** `core/models_policy.py::ALL_ROLES` is the archetype name set (built-in plus starter:
`lead`, `implementer`, `reviewer`, `tester`, `researcher`, `analyst`, `writer`, `critic`,
`operator`, `monitor`, and any pod-scoped archetype resolves by its own name); `ROLE_CLASS` is
keyed the same way (`lead`, `reviewer`, `tester`, `monitor`, `analyst`, `writer` cheap;
`implementer`, `critic`, `operator`, `researcher` strong). `policy_role` and
`resolved_policy_role` are deleted from `core/archetypes.py` and from the role document shape
(`policyRole` is an unknown key, refused by `load_role_file`). `docket-models.json` `roles:`
keys are archetype names; a key that is not an archetype is reported by `doctor` and ignored
(no migration). The `is_specialist` branch and the `ORG_SPECIALIST_ORDER` loop in
`core/models_policy.py` are deleted here (P39-6 deletes the constants). `docket models` prints
the archetype names and `preset` writes them.

**Non-goals:** the per-agent pin (`profile`, `modelSource`), which P39-10 removes; the `models`
command's conversion to `setup model` (P39-12).

**Acceptance:** `resolve_role_model("implementer")` reads the `implementer` row; a pod-scoped
archetype `security-vetter` with no row resolves to the registry default (unchanged rule); a
`roles add` file with `policyRole:` is refused naming the key; `docket models` output contains
`implementer` and not `programmer`. Oracle: the resolved model string and the refusal message.

**RED:** `tests/unit/core/test_models_policy.py` (existing): `resolve_role_model("implementer")`
fails on the base because the row is `programmer`.

### P39-5 — the record decides: run state, exit codes, doctor, counts

**Status:** DONE (merged to `develop` 2026-10-07, `315dc23c`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (run states, retry of a failed task, stale lease reclaim), `cli-interface.spec.md` (`runs show` exit code, `doctor` summary)

**Trigger (ADR 0022 evidence, live run C9, C11, C12):** a dispatch that parked `waiting_input`
is listed `succeeded`; `runs show <failed>` prints ✗ and exits 0; `metrics` counts 0/0/0 after
three terminal tasks; `doctor` says "1 critical issue" with none marked ✗ and hints `docket
maintain  check` (fails); `queue --retry <failed>` refuses ("not a blocked task"); a killed
dispatch leaves its task `running` forever (`runs cancel`: nothing in flight; `dispatch --resume`:
no-op, exit 0).

**Goal:** (a) `core/runs.py` records `waiting_input`/`waiting_approval` as the run's terminal
state when a hop parks, never `succeeded`; `cli/_runs.py` show exits 1 when the run or any
returned task failed. (b) `core/dispatch.py`: a `failed` task is retryable (status back to
`pending`, attempt counter kept, audited `task.retry`); a `running` task whose claim's process is
gone (`os.kill(pid, 0)` through `edges/adapters/system.py`) or whose lease is older than the
pod's `turnTimeoutS` plus `verifyTimeoutS` is stale, and `--resume` reclaims it (audited
`task.reclaimed`). (c) `cli/_doctor.py`: the summary counts only lines marked ✗ as critical, and
the fix hint names a command that exists (`docket doctor --fix`); the success/failure/aborted
counts in `cli/_metrics.py` come from the trace's terminal task events, not sessions.

**Non-goals:** the run banner (P39-15), `status --all` counts (P39-15), `pod show`'s
approvalMode source (P39-10), the `task retry` verb (P39-9 wires this core change).

**Acceptance:** a scripted dispatch whose Lead hop parks → `runs list` shows `waiting_input`;
a run with one failed task → `runs show` exit 1; a task record `running` with a dead pid →
`dispatch --resume` reclaims it and the audit has `task.reclaimed`; a `failed` task → the retry
function re-queues it, audit `task.retry`; a home with one ⚠ and no ✗ → `doctor` exit 0, no
"critical". Oracle: the run record and the audit log, never a renderer.

**RED:** `tests/unit/core/test_runs.py` (parked run state), `tests/unit/core/test_dispatch.py`
(stale reclaim and retry), `tests/unit/cli/test__doctor.py` (critical count); each fails on the
base for the measured reason.

### P39-6 — remove the org specialists and the portfolio manager (seventh unwired instance)

**Status:** DONE (merged to `develop` 2026-10-07, `798bd56c`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `agent-lifecycle.spec.md`, `workspace-structure.spec.md`, `docket-meta.spec.md` (`scope: org`), `serve-read-api.spec.md` (`/status.json` agents), `cli-interface.spec.md` (`init --portfolio`)

**Trigger (ADR 0022 evidence):** `manager`, `knowledge` and `security` are provisioned by the
first `docket init` (`cli/_install.py`), listed by `list`/`snapshot`, reported by `doctor` and
`/status.json`, resolved by the model policy, and **no reader in `core/dispatch.py`,
`core/orchestrator.py`, `core/pipeline.py`, `serve.py` or the driver ever runs one**. The same
holds for the opt-in portfolio manager (`init --portfolio`). Machinery with a writer and no
consumer on the live path.

**Goal:** delete them: `config.py` (`ORG_ROLES`, `ORG_SPECIALIST_ORDER`, `ORG_DISPLAY_ORDER`,
`PORTFOLIO_MANAGER_ROLE`, `is_specialist`, the specialist branch of `workspace_dir`);
`cli/_install.py` (specialist provisioning, `_specialist_*`, `_provision_portfolio_manager`,
`--portfolio`); `serve.py::_SPECIALISTS` and the `kind="specialist"` records (bump
`SERVE_API_VERSION`); `cli/_doctor.py` (the specialist check only); `cli/__init__.py` (the two
`ORG_*` loops in `list` and `snapshot`, minimal edit: P39-16 and P39-15 delete the commands); the
`_cfg.is_specialist(aid)` branch in `cli/_agents.py`; `core/telegram.py`'s "org specialist"
sentence; `tests/integration/test_portfolio_manager.py`; the six specialist workspaces in
`tests/golden/fixtures/seed.sh`; `docs/AGENT-TEAMS.md` "Org specialists" section and the
`scope: org` prose in `docs/DOCKET.md`. The `security` and `knowledge` *archetypes*, if any pod
role carries those names, are untouched: this card removes shared agents, not role names.

**Acceptance:** fresh home → `docket init` → `workspaces/` holds only the pod's members;
`fleet.json` has no `manager`/`knowledge`/`security` entry; `docket init --portfolio` is an
unknown option (exit 2); `/status.json` lists pod agents only; `doctor` on a home that still has
a `workspaces/manager/` directory from before says nothing about it. Oracle: the directory
listing and `fleet.json`.

**RED:** `tests/unit/cli/test__install.py` (new, `SUBJECT = "docket.cli._install"`): after
`init`, no specialist directory exists; fails on the base with three directories.

### P39-7 — split `cli/__init__.py` into one module per group, mechanically

**Status:** DONE (merged to `develop` 2026-10-07, `a99e0344`) · **Size:** M · **Wave:** 92 · **Model:** Sonnet (integrator reviews the script before it runs) · **Spec:** `test-framework.md` (lanes: one unit file per module)

**Trigger:** `cli/__init__.py` is 2,842 lines holding 46 command bodies; every Wave 93 card
would edit it, so nothing in Wave 93 could run in parallel.

**Goal:** `scripts/maint/split_cli_registry.py` moves every `cmd_*` function and its private
helpers out of `cli/__init__.py` into the module that will own it in Wave 93, **unchanged**
(AST-located, text moved byte for byte, imports hoisted), and leaves `cli/__init__.py` as the
registry: `app`, the callback, and one `app.command(...)(module.cmd_x)` or `app.add_typer`
line per command. Target modules: `_run.py` (dispatch, pipeline run; new), `_task.py` (approve, deny, chat; new),
`_pod.py` (add, info, delete, maintain, profile join it), `_pod_config.py` (config, validate,
pipeline, roles, policies, plugins, recipes; new), `_status.py` (cost, metrics, snapshot join
it), `_inbox.py`, `_agents.py` (init only), `_log.py` (audit; new), `_setup.py` (doctor,
completions; new), `_setup_model.py` (models, keys; new; `_provider.py` joins it),
`_setup_notify.py` (channels, wire, unwire, notify, conversations; new), `_setup_export.py`
(exporters; new), `_setup_sandbox.py` (gates; new), `_setup_mcp.py` (mcp; new), `_service.py`
(serve; new), `_exec.py` (harness; new), `_remove.py` (list, context, logs, edit, scope,
persona, help; new, for P39-16 to delete). The script has `--check` (every `cmd_*` is in exactly one module and
`cli/__init__.py` has no function longer than ten lines) and `--dry-run`.

**Non-goals:** any behaviour or text change. Goldens, `docs/commands.md`, help output and the
full suite are the no-change oracle.

**Acceptance:** `bash tests/golden/run.sh verify-all` byte-identical; `gen_cli_docs.py --check`
green without regeneration; `uv run pytest` green; `tests/guards/test_layout.py` green with
new unit files only where the moved module exceeds 150 lines (empty `SUBJECT` files are
allowed for this card alone). Oracle: the goldens and the docs check.

**RED:** `tests/guards/test_layout.py` gains the rule "no function in `cli/__init__.py` longer
than ten lines"; it fails on the base with forty-six.

### P39-8 — the `task` group: add, list, show, diff, trace, prune

**Status:** TODO · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (task views, worktree prune, the queue), `trace-store.spec.md` (`task trace`), `cli-json-shapes.spec.md` (`task list|show --json` with `worktree`), `cli-interface.spec.md` (`delegate`, `pod delegate|queue|evidence|corrections|explain|worktrees`, `runs list|show|prune`, `trace` removed)

**Trigger (ADR 0022 evidence, live run B3, C6, P7):** a task reported `done` changes nothing the
operator can see; the fix sits uncommitted in the task worktree and no surface prints the path,
branch or diff; `pod queue` prints a short id that `chat` rejects; `trace` wants an internal
session key no command lists; `trace tail` on a finished session dumps raw JSONL.

**Goal:** `cli/_task.py` defines `task_app` and these verbs: `task add "<text>" [--priority]
[--brief FILE] [--pod]` (what `delegate` did; prints the `docket run` hint), `task list [--json]
[--pod]` (the queue with status, cost and the worktree path when one exists), `task show <ref>
[--json]` (status, hops, evidence, corrections, the interruption forecast, the runs, and for a
task with a worktree: path, branch, base commit and the exact `git -C <path> diff <base>` and
merge commands; a harness run id resolves too, replacing `harness status`), `task diff <ref>`
(runs that diff through `edges/adapters/system.py`), `task trace <ref> [--tail] [--export]
[--json]` (tool names on tool_call lines; `--tail` ends when the session ends), `task prune
[--dry-run] [--force] [--traces --days N] [--pod]` (what `pod worktrees prune` and `trace
expire`/`runs prune` did). Every ref goes through `core/task_ref.py`. The `pod` actions
`delegate`, `queue`, `explain`, `evidence`, `corrections`, `worktrees` leave `cli/_pod.py`;
`cli/_runs.py` (`list`, `show`, `prune`) and `cli/_trace.py` are deleted.

**Non-goals:** `approve|deny|answer|retry|cancel` (P39-9).

**Acceptance:** after a scripted `done` task with an uncommitted change → `task show` prints a
path that exists and `git -C <path> diff <base>` is non-empty; `task list --json` parses and each
item has `worktree` (path or null); `task show task-04ff` with two matches lists both and exits 1;
`task add "x"` from inside the repo queues without a pod name; `docket runs`, `docket trace`,
`docket delegate` are unknown commands (exit 2). Oracle: the filesystem and `TASK_LIST.json`.

**RED:** `tests/unit/cli/test__task.py` (new): `task show` prints the worktree path; fails on
the base (no command).

### P39-9 — `task approve|deny|answer|retry|cancel`

**Status:** TODO · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (answer surfaces: `task answer` absorbs `chat`; pre-grant through `task approve --for`; the "approved, ready" state and the `run` hint), `pod-dispatch.spec.md` (`task retry` uses the core retry; `task cancel`), `cli-interface.spec.md` (`approve`, `deny`, `chat`, `pod answer|pregrant`, `runs cancel` removed)

**Trigger (ADR 0022 evidence, live run C5, C6, C11, C12):** `approve` says "may now proceed"
while nothing proceeds and `inbox` says "Nothing needs you"; `chat` rejects the short id; a failed
task cannot be retried; a killed dispatch leaves its task `running` forever.

**Goal:** registered onto `task_app` from `cli/_task.py` (P39-8 defines the app; this card adds
five verbs in the same module, functions `_task_approve`, `_task_deny`, `_task_answer`,
`_task_retry`, `_task_cancel`): `task approve <ref> [--reason] [--once|--task] [--for "<cmd>"
[--tool bash]]` resolves the task's pending approval (the `apr-…` token leaves the surface;
`--for` is what `pod pregrant` did) and prints the `docket run` hint, or "docket is running and
will pick it up" when the sweep holds the pod lock; `task deny <ref> [--reason]`; `task answer
<ref> [text] [--option ID] [--field k=v]... [--decline]` (on a TTY with no text or option it
prompts through the options as `chat` did; off a TTY it fails naming `--option`); `task retry
<ref>` (P39-5's core retry: failed or blocked); `task cancel <ref>` (the in-flight run plus the
stale reclaim). `cli/_approve.py`, `cli/_deny.py`, `cli/_chat.py` and `_pod_answer`,
`_pod_pregrant` in `cli/_pod.py` are deleted.

**Acceptance:** a parked task with options → `task answer <short-id> --option x` records the
answer and prints the run hint; after `task approve <id>` the inbox JSON item carries
`state: "approved_ready"` (P39-15 renders it); `task approve <id> --for "git push origin main"`
writes the same pre-grant `pod pregrant` wrote (compare the approvals directory); `task retry
<failed>` re-queues (audit `task.retry`); `docket approve` is an unknown command. Oracle: the
approvals directory and the audit log.

**RED:** `tests/unit/cli/test__task.py`: `task approve <id>` resolves the task's token; fails on
the base.

### P39-10 — the `pod` group, roster half: show, add, remove, reset, set, unset, delete

**Status:** TODO · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `agent-lifecycle.spec.md` -> 2.0.0 (member lifecycle; Lead removal refused; `reset` distills first, fails closed; pod deletion by typed name, never a picker), `model-profiles.spec.md` (per-agent pin removed), `docket-meta.spec.md` (`modelSource` removed), `pod-blueprints.spec.md` (`pod set|unset` over every `PodSettings` key), `cli-interface.spec.md` (`add`, `info`, `delete`, `maintain`, `profile`, `pod <p> list|add|remove|set-verify|config`, `config explain` removed)

**Trigger (ADR 0022 evidence, live run B2, B5, C9, C13, F6, F7):** `set-verify <m> --clear`
stores the literal `--clear`; `pod add wizard` prints a traceback; `pod remove <lead>` has no
confirmation; `delete <pod>` off a TTY deletes silently; the verify command that decided two
outcomes is shown by nothing; `explain interruptions` says `park` while `pod config` says `wait`;
a per-agent model pin is a fourth model layer with no measured need.

**Goal:** `cli/_pod.py` becomes `pod_app`: `pod show [MEMBER] [--json]` (members with role,
model and its source among policy / pod overlay / step, workspace path, verifyCmd; the pod's
settings with their source; the approvalMode `core/dispatch.py` will actually use, pinned by a
test that drives both; `configSource`/`configDigest`/`drift`: this is `config explain` and `pod
config get` in one), `pod add <role> [--count N] [--verify CMD]` (unknown role: one line, exit
1), `pod remove <id> [--yes]` (confirms; the Lead is refused with "delete the pod instead"), `pod
reset <id> [--yes]` (rebuilds the workspace files from metadata, distilling memory first, aborting
if distillation fails), `pod set <key> <value> [--member ID]` (every `PodSettings` key;
`budgetUsd` included; `verify` with `--member` writes a member's verifyCmd), `pod unset <key>
[--member ID]`, `pod delete [--confirm NAME]` (TTY: name typed; off a TTY: `--confirm` or exit 1;
an agent id is refused). Deleted: `add`, `info`, `delete`, `maintain` (all modes), `profile`
(`--resume` becomes part of `run --resume` in P39-15), `config explain`, `pod config`,
`modelSource` in `.docket-meta.json` and the pin branch of `core/models_policy.py::
resolve_role_model`. `cli/_agents.py` keeps `run_init` only.

**Acceptance:** `pod remove <lead>` → refused, pod unchanged; piped stdin → `pod remove <impl>`
→ exit 1 naming `--yes`; `pod unset verify --member <impl>` → meta has no `verifyCmd`; `pod add
wizard` → one line, exit 1; piped `pod delete` → exit 1 naming `--confirm`; `pod delete
--confirm demo` → every member gone, audit `pod.delete`; `pod show` names the implementer's
verifyCmd and the dispatcher's resolved approvalMode; a meta written with `modelSource` is read
without it. Oracle: `.docket-meta.json`, `fleet.json`, the workspaces directory.

**RED:** `tests/unit/cli/test__pod.py` (existing): Lead removal refused and piped deletion
refused; both fail on the base.

### P39-11 — the `pod` group, configuration half: apply, export, validate, plan, check, recipes, roles, policies

**Status:** TODO · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `config-format.spec.md` (one validator: `pod validate [PATH]` for any `kind:` document or directory), `pod-blueprints.spec.md` (`pod apply|export`; `apply` with no argument re-syncs instructions; `apply <file>` installs one document), `pipeline-format.spec.md` (`pod plan`), `security-gates.spec.md` (`pod check`), `role-archetypes.spec.md` (`pod roles`), `cli-interface.spec.md` (`validate`, `roles`, `policies`, `recipes`, `plugins`, `pipeline validate|plan`, `pod <p> apply|export|sync` removed)

**Trigger (ADR 0022 evidence, inventory C6):** four validators and a fifth check; two installers;
`roles`/`policies` unknown actions exit 0; `plugins` is a one-verb command; `policies test` is
the useful one and is hidden among them.

**Goal:** `cli/_pod_config.py` registers onto `pod_app` (imported from `cli/_pod.py`): `pod
apply [NAME|DIR|FILE] [--dry-run] [--json]` (recipe by name, directory, or a single `kind:`
document, which is what `roles add`/`policies add` did; no argument re-syncs instructions as
`pod sync` did), `pod export [DIR] [--force]`, `pod validate [PATH]` (the one validator), `pod
plan [--pipeline FILE]` (what `pipeline plan` did, from the real executor), `pod check "<text>"
--role R [--hook pre_tool_call] [--tool bash]` (what `policies test` did: would the pod's rules
allow this), `pod recipes [NAME] [--json]`, `pod roles [NAME] [--json]`, `pod policies [ID]
[--json] [--plugins]` (list without a name, show with one; plugins as a section). The `pod`
actions `config`, `apply`, `export`, `sync` leave `cli/_pod.py`; `cli/_config.py`,
`cli/_validate.py`, `cli/_pipeline.py`, `cli/_roles.py`, `cli/_policies.py`, `cli/_recipes.py`,
`cli/_plugins.py` are deleted (their bodies moved by P39-7 into `_pod_config.py`).

**Acceptance:** `pod validate .docket/` on an invalid role exits 1 with the message `validate`
printed; `pod apply roles/critic.yaml` installs the role `roles add` installed (compare the
pod's `config/roles.json`); `pod check "git push origin production" --role implementer` prints
the same verdict `policies test` printed; `docket validate`, `docket pipeline`, `docket roles`,
`docket policies`, `docket recipes`, `docket plugins` are unknown commands. Oracle: the pod's
config directory and the printed verdict.

**RED:** `tests/unit/cli/test__pod_config.py` (new): `pod check` verdict; fails on the base (no
command).

### P39-12 — `setup` is the first-run flow: the report, then only what is missing; `provider`, `model`, `sandbox`, `shell`

**Status:** TODO · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `cli-interface.spec.md` (the `setup` group; `doctor`, `models`, `models provider`, `keys`, `gates`, `completions` removed), `model-profiles.spec.md` (`setup model`; `provider add` applies the preset), `api-keys.spec.md` (credentials under `setup provider`; `remove` confirmation), `security-gates.spec.md` (`setup sandbox`; bare is a read), `agent-lifecycle.spec.md` (first run: `init` no longer bootstraps silently; it points at `setup`)

**Trigger (ADR 0022 evidence and decision 10):** the first run is four fragments of a wizard
and no wizard: `init` bootstraps the home without saying so and offers desktop notifications on
a TTY; `keys setup` walks the provider catalog; `models preset` reports readiness; `doctor`
checks health with one warning per agent and a hint to a command that fails. "Use Anthropic" is
three commands (`provider add`, `keys add`, `models preset`); the local preset is one, which is
why the quick start works and the hosted path does not. The only thing a task needs is a
reachable endpoint with a model per role; nothing says so.

**Goal.** `cli/_setup.py` defines `setup_app`. **`setup` with no verb is the flow**, idempotent,
two modes by TTY (the contract's rule). It always starts with the report, one line per piece
with its state and the exact command: model endpoint (required: a provider, its credential, and
`lead`/`implementer` resolving to a model), notifications (`console only (nobody is told)` is a
warning), sandbox (state and whether bwrap or docker was found), shell completion, the
background service. On a TTY it continues by asking only for what is missing, required first:
choose a provider (the catalog's built-ins plus `local`), the credential (stored 0600, never
echoed), probe `/models`, apply the preset, confirm the two roles resolve; then the optional
pieces, each default `N`: desktop notifications when a desktop session exists, Telegram (one
step, P39-13), the sandbox when a backend exists, shell completion. It prints every command it
runs (`ran: docket setup provider add anthropic --credential`) and ends with
`Ready. → Next: cd into a repo and run docket init`. Off a TTY it prints the report with the
commands and exits 1 when the required piece is missing, 0 otherwise; `--json` emits the report;
`--fix` repairs what `doctor --fix` repaired (the P39-5 critical count; hints name commands that
exist). The wizard has no logic of its own: it calls the same functions the verbs call.
`setup shell bash|zsh` prints the completion script (regenerated from the tree by P39-17).
`cli/_setup_model.py`: `setup provider add <name> [url] [--credential] [--model] [--ctx]
[--no-preset]` does the whole intent (store the credential, prompt on a TTY or take the flag/env
off it, probe, apply the provider's preset unless `--no-preset`, print which role resolves to
what), plus `list | show | remove [--yes] | export | rotate`; `setup model list [--json] | set
<role> <model> | preset [NAME] | reset [--yes]` stays for overrides and listing.
`cli/_setup_sandbox.py`: `setup sandbox status [--json] | on | off | network none|open | classes`
(bare is the status). `init` no longer provisions the home silently: with no endpoint
configured it still builds the team and ends with `⚠ No model endpoint yet → Next: docket
setup`; `run` refuses with the same line (P39-15 renders it; this card exposes
`setup.readiness()` for both). `cli/_doctor.py`, `cli/_keys.py`, `cli/_gates.py`,
`cli/_completions.py` are deleted after their bodies move (P39-7 put them in these modules).

**Non-goals:** `setup notify|export|mcp` (P39-13); the bare `docket` greeting (P39-17).

**Acceptance:** fresh home, piped stdin → `docket setup` → the report names `Model endpoint
missing` with `docket setup provider add ...`, exit 1, nothing written; a scripted TTY (stdin
feed) answering `local` → `docket-providers.json` has the provider, `docket-models.json` the
preset rows, the output contains `ran: docket setup provider add local`, exit 0; a second run
prints `Ready` and asks nothing; `setup provider add anthropic --credential sk-x` against a fake
`/models` → preset applied, `lead` resolves; `setup provider add x --no-preset` → no model rows;
`setup sandbox` writes nothing (`fleet.json` byte-identical); piped `setup provider remove X` →
exit 1 naming `--yes`; `docket doctor`, `docket models`, `docket keys`, `docket gates`,
`docket completions` are unknown commands. Oracle: the three JSON stores and captured stdout.

**RED:** `tests/unit/cli/test__setup.py` (new): piped `setup` on a fresh home exits 1 naming the
provider command and writes nothing; fails on the base (no command).

### P39-13 — `setup notify` (Telegram in one step), `setup export`, `setup mcp`

**Status:** TODO · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `telegram-integration.spec.md` (connecting Telegram is one operation writing the secret, the actors and every Lead's binding; the inbound-only AST pins on `core/telegram.py` are untouched), `operator-loop.spec.md` (`setup notify flush`), `observability-export.spec.md` (`setup export` verbs), `mcp-client.spec.md` (`setup mcp` verbs), `cli-interface.spec.md` (`channels`, `wire`, `unwire`, `notify`, `conversations`, `exporters`, `mcp servers` removed)

**Trigger (ADR 0022 evidence, inventory C3):** connecting Telegram is three commands over two
stores (`keys add TELEGRAM_BOT_TOKEN`, `channels enable telegram --set actors=<chat>`, which
refuses while `actors` is empty, and `wire <lead>` for the inbound binding), and the two setups
store different ids in different files; five commands cover notifications; bare `channels` exits 1.

**Goal:** `cli/_setup_notify.py` registers onto `setup_app`: `setup notify list [--json] | show
<name> [--json] | enable <name> [--set k=v] [--chat ID] | disable <name> | add <file> | remove
<name> [--yes] | export <name> [FILE] | privacy <name> [LEVEL] [--yes] | test <name> | bind
<member> [--channel telegram] | unbind <member> | flush [--dry-run]`. **`setup notify enable
telegram --chat <id>` is the one step:** it stores the bot token (prompted on a TTY, `--token`
or the env off it, through the same 0600 store), sets `actors`, binds every pod's Lead (what
`wire` did, for each pod), sends one test message only if `--test` is passed (the inbound-only
rule stands: nothing is sent unasked), and prints what it wrote in each store; `bind`/`unbind`
remain for the per-pod exception. `show telegram` lists the bindings and the open conversations
the registry holds. The `setup` wizard (P39-12) calls this one function for its Telegram step.
`cli/_setup_export.py`: `setup export` with the verbs `exporters` had. `cli/_setup_mcp.py`:
`setup mcp list | add <name> [...] -- cmd | remove <name>` (what `mcp servers` did; `mcp serve`
moves to `start --mcp` in P39-14). `cli/_channels.py`, `cli/_notify.py`,
`cli/_conversations.py`, `cli/_exporters.py`, `cli/_exporters_preview.py` (its body joins
`_setup_export.py`), `cli/_mcp.py`'s servers half are deleted after their bodies move;
`core/conversations.py` stays (dispatch and the service read it).

**Acceptance:** a home with two pods → `setup notify enable telegram --chat 42 --token t` →
`secrets.json` holds the token, the telegram channel document has `actors: ["42"]` and is
enabled, both Leads have a binding in `fleet.json`, nothing was sent (the fake sink is empty);
`setup notify bind demo-lead` writes the binding `wire` wrote; `docket wire`, `docket notify`,
`docket conversations`, `docket channels`, `docket exporters` are unknown commands; `setup
notify flush --dry-run` delivers nothing; `setup mcp list` prints what `mcp servers list`
printed. Oracle: `secrets.json`, the channel catalog, `fleet.json`, the sink,
`docket-mcp-servers.json`.

**RED:** `tests/unit/cli/test__setup_notify.py` (new): `enable telegram --chat` writes the three
stores; fails on the base (no command).

### P39-14 — `log`, `start`, `stop`, `exec`

**Status:** TODO · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `audit.spec.md` (`log`, `log verify`), `serve-read-api.spec.md` (`start|stop`; routes unchanged), `harness-mode.spec.md` (the command is `exec`; contract 1.0/1.1 unchanged; `harness status` replaced by `task show <run-id>`), `mcp-server.spec.md` (`start --mcp`), `cli-interface.spec.md` (`audit`, `serve`, `harness`, `mcp serve` removed)

**Trigger (ADR 0022 decisions 1 and 5):** "audit" names the mechanism, "serve" does not say what
is served, "harness run" is two words describing an architecture, and Tack calls it by name.

**Goal:** `cli/_log.py`: `log [N] [--json]` (what `audit` printed; `audit bogus` exited 0, an
unknown verb now exits 2) and `log verify`. `cli/_service.py`: `start [--port] [--interval]
[--http/--no-http] [--telegram] [--dispatch/--no-dispatch] [--mcp] [--token-file]` (what `serve`
did plus `mcp serve` behind `--mcp`; the help says what runs in the background) and `stop`
(the two-stage stop that exists; `status` reports whether it is running). `cli/_exec.py`: `exec`
with every option `harness run` had, the same NDJSON events, result line and exit codes 0/1/2;
`tests/fixtures/harness-contract/v1/` and `docs/contracts/harness-v1/` are untouched except the
command name in prose; `harness status` is deleted (`task show <run-id>` resolves the record
through `core/task_ref.py`). `cli/_audit.py`, `cli/_harness.py` (renamed to `_exec.py` by
`git mv`, with `_harness_answers.py`/`_harness_recipe.py` kept as they are), `cli/_mcp.py`'s
serve half deleted.

**Acceptance:** the harness contract tests (`tests/integration/test_harness_*`) pass with the
command name replaced and nothing else; `docket harness`, `docket serve`, `docket audit` are
unknown commands; `log verify` on a tampered line exits 1 as `audit verify` did; `start --mcp`
serves the MCP tool set `mcp serve` served (pin by the existing MCP server test). Oracle: the
fixture files and the existing tests.

**RED:** `tests/unit/cli/test__exec.py` (renamed from `test__harness.py` by `git mv`): invoke
`exec`; fails on the base (no command). Return the one-line change Tack needs in
`tack-runner/src/harness/docket/probe.rs` for the integrator; do not edit Tack.

### P39-15 — `run`, `status`, `inbox`

**Status:** TODO · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (`run`: `--dry-run` starts nothing; the banner lists the effective pipeline after roster filtering; `--resume` reclaims stale claims and budget pauses), `pipeline-format.spec.md` (`run --pipeline FILE`), `cost-tracking.spec.md` (cost and counts in `status`), `cli-json-shapes.spec.md` (`status --all --json` carries what `snapshot` carried; `inbox` items carry `state`), `operator-loop.spec.md` (`inbox` prints `docket task approve <id>` lines; "approved, ready"), `cli-interface.spec.md` (`dispatch`, `pod dispatch`, `pipeline run`, `cost`, `metrics`, `snapshot` removed)

**Trigger (ADR 0022 evidence, live run B1, C5, C7, C8, C9, P1):** `pod dispatch --dry-run`
runs; the banner names reviewer and tester for a two-member pod; `inbox --bogus` exits 0 and
truncates the command being approved; `metrics` prints raw ANSI when piped and counts sessions;
cost appears in five places, none per pod; `status --all` hides failed tasks.

**Goal:** `cli/_run.py`: `run [--resume] [--timeout S] [--progress] [--no-prompt] [--pipeline
FILE] [--var k=v]... [--dry-run] [--pod]` (what `pod dispatch` and `pipeline run` did; `--dry-run`
prints the plan the real executor renders and starts nothing; `--resume` also clears a budget
auto-pause, what `profile --resume` did; the banner lists the effective pipeline's steps after
roster filtering; the summary line `✓ 1 done · 0 failed · 2.1k tokens (~$0.00 est.)` and one
`→ Next:` line; with no model endpoint configured it refuses with `✗ No model endpoint yet. Run
docket setup` through `setup.readiness()` from P39-12). `cli/_status.py`: `status [--all] [--json] [--history]
[--days N]` shows the pod's tokens, the labelled estimate and the success/failure/aborted counts
and latency P39-5 moved to trace events (what `cost` and `metrics` did, per pod), failed counts
under `--all`, the last run, "approved, ready" tasks, whether `docket start` is running;
`status --all --json` is the inventory `snapshot` printed. `cli/_inbox.py`: the sub-app `inbox
[--json] [--since] [--peek]`, unknown flags exit 2, full held command (wrap, never cut), each
item printed with its exact `docket task approve|deny|answer <id>` line, `approved_ready` state.
`_pod_dispatch*`, `_parse_dispatch_args` (deleted: Typer parses), `_flush_notify_after_dispatch`
leave `cli/_pod.py`; `cli/_cost.py`, `cli/_metrics.py` deleted after their counting moves (a pure
trace reader may land in `core/trace.py`, one function).

**Acceptance:** inside the repo → `run --dry-run` prints the plan, no run record, no trace event,
no task status change; a home with no provider → `run` exits 1 naming `docket setup`; `run --bogus` exit 2 naming the flag; a two-member pod's banner names two
hops; `status --all` shows `2 failed`; a scripted trace with 1 done, 2 failed → `status` prints
`1 / 2 / 0`; `inbox --json` parses with no escape codes and each item has `command`; `docket
dispatch`, `docket cost`, `docket metrics` are unknown commands. Oracle: `docket-runs.json`, the
trace directory, `TASK_LIST.json`, `json.loads` on stdout.

**RED:** `tests/unit/cli/test__run.py` (new): `--dry-run` leaves `docket-runs.json` unchanged;
fails on the base (no command).

### P39-16 — remove: `list`, `context`, `logs`, `edit`, `scope`, `persona`, `help`

**Status:** TODO · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `session-scoping.spec.md` -> 3.0.0 (operator-set scope removed; the derived key stands), `workspace-structure.spec.md` (persona block removed from `SOUL.md`), `cli-json-shapes.spec.md` (`list`, `info` shapes removed), `cli-interface.spec.md` (the seven removed)

**Trigger (ADR 0022 decision 5):** read views over files the operator can open, an operator-set
session key with no reader on the live path, a cosmetic persona with one writer, and a `help`
command whose four examples all fail.

**Goal:** delete the seven commands, `cli/_remove.py` (P39-7's holding module), `cli/_help.py`,
`cli/_context.py`, the persona layer (`core/identity.py` persona rendering and parsing, the
`persona` field of `AgentMeta`, the block in `SOUL.md`), `core/utils.py::aggregate_cost`/
`last_activity` if `list`/`snapshot` were their last callers (P39-15 may keep one), the `scope
set|reset` writers (the `sessionKey` in meta stays as the derived value provisioning writes).
`tests/integration/test_completions_eval_metrics_help.py` loses its `help` cases. The bare
`docket` guide names the eleven commands (P39-17 owns its final text; this card only removes the
`docket help` line).

**Acceptance:** each of the seven names is an unknown command (exit 2); a meta written with
`persona` is read without it and `SOUL.md` renders without the block; `status --all --json`
still carries the member inventory `list --json` carried. Oracle: the exit codes and the
rendered `SOUL.md`.

**RED:** `tests/integration/test_console_script_entry_point.py` (existing): the retired-name
test is parametrized over these seven; fails on the base (exit 0).

### P39-17 — grouped help, one tagline, the bare guide, completions and the three guards

**Status:** TODO · **Size:** M · **Wave:** 94 · **Model:** Integrator · **Spec:** `cli-interface.spec.md` ("Help" rewritten: the eleven commands in three panels, examples, exit codes), `test-framework.md` (the guards)

**Trigger (ADR 0022 decisions 1 and 6):** `docket --help` lists 46 commands in registration
order; four taglines; 0 of 21 actions show their own help; the completion script offers agent ids
after `pod`.

**Goal:** three `rich_help_panel` groups (Daily: `init status inbox task run`; The pod: `pod log`;
Machine: `setup start stop exec`); one tagline ("docket runs teams of coding agents and governs
what they may do") in `--help`, the bare `docket` greeting (the tagline, the five daily commands, and `Not set up yet? docket
setup`, rendered through `ui.py`'s voice) and `pyproject.toml`; `setup shell` regenerated from the tree (every group's verbs, pod ids after
`--pod`, task ids after `task <verb>`); `scripts/gen_cli_docs.py` `GROUPS` replaced by the panels
and `docs/commands.md` regenerated; `-h` accepted. Three guards in `tests/guards/`: every leaf
reachable from the registry prints its own `--help` containing `Example:`; every `list`, `show`,
`status`, `inbox` and `log` parses as JSON under `--json`; every prompt site reached with stdin
closed exits 1 naming a flag. Each guard is seen red by planting one defect before it counts.
Goldens regenerated for every case the Wave 93 cards changed, with the line-by-line explanation
in the rollup commit; the golden runner's `cases_dir()` read-only list rewritten for the new
names.

**Acceptance:** `docket --help` shows three panels and eleven commands; `docket task show --help`
shows one example; `docket dispatch` → "did you mean `run`?", `docket delegate x` → usage with a
suggestion, exit 2; the three guards fail when a planted leaf loses its example / its JSON / its
flag. Oracle: the guards themselves, after they have been seen red.

### P39-18 — the mechanical rename script

**Status:** TODO · **Size:** S · **Wave:** 94 · **Model:** Sonnet · **Spec:** none (tooling)

**Trigger:** about 357 doc lines, 142 source lines, 42 test lines and 17 script lines invoke
`docket pod ...`; the templates carry `docket pod <project> config unset pipeline` thirteen
times. A model rewriting those by reading whole files is the failure mode CLAUDE.md names.

**Goal:** `scripts/maint/rewrite_cli_names.py` with one table (old invocation pattern → new
invocation, from ADR 0022 decision 5) applied over `docs/`, `src/docket/templates/`, `scripts/`,
`specs/`, `tests/agent/`, `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md` `[Unreleased]` only;
`--check` fails naming every surviving invocation of a removed name (the fourth guard of ADR
0022, wired as `tests/guards/test_no_removed_cli_names.py` calling the script's check); `--dry-run`
prints the diff. Patterns that cannot map one to one (`docket info <agent>` where the pod is
meant, `docket help`, `conversations`, `scope`, `persona`, `logs`, `edit`, `context`) are listed
by the script for the doc cards, not rewritten.

**Acceptance:** `--check` on the base lists hundreds; after `--write`, an `rg` for every removed
top-level name over `docs`, `src/docket/templates`, `scripts`, `specs`, `tests/agent` and
`README.md` prints only the lines the script listed as unmappable. Oracle: the rg.

### P39-19 — README and quick start on the new surface

**Status:** TODO · **Size:** M · **Wave:** 94 · **Model:** Sonnet · **Spec:** none (README is descriptive, D-37); agent-lane prose tests rebuilt

**Goal:** after P39-18, rewrite `README.md` ("Quick start", "Your first team", "The run", "The
gate and the record", "Make it yours", "Everything is configuration", "Also shipped", "Known
limits") and `docs/QUICK-START-DOCKET.md` so every command shown exists, the newcomer path never
types the pod name, the sentence defining `pod` from ADR 0022 decision 3 appears where the first
`docket pod` command does, and the sentences the prose tests pin are rebuilt from this README
(`tests/agent/truth/test_docs_positioning.py`, `test_public_release_truth.py`): no assertion
carried from the old README. The "Known limits" entry on org specialists goes. The transcripts
and images stay as they are (P39-23 re-captures them).

**Acceptance:** `uv run pytest tests/agent` green; `scripts/maint/rewrite_cli_names.py --check`
green on both files; every `docket ...` line in both files runs under a throwaway home (the
integrator spot-checks six). Oracle: the agent lane and the check.

### P39-20 — the guides: AGENT-TEAMS, DOCKET, WORKFLOW-GUIDE

**Status:** TODO · **Size:** M · **Wave:** 94 · **Model:** Haiku · **Spec:** none

**Goal:** after P39-18's mechanical pass, the three guides read as one surface: every remaining
unmappable line (listed by the script) is rewritten by hand, the "Org specialists" section of
`docs/AGENT-TEAMS.md` and every `scope: org` sentence are removed (P39-6 already cut the
section; this card removes the cross-references), the `pod <p> ...` prose becomes "from inside
the repo" prose, and no sentence describes a removed command, a pin, a persona or a specialist.
The script's `--check` is the gate; a Haiku worker edits only the lines the script lists plus
the sentences that reference them.

**Acceptance:** `rewrite_cli_names.py --check` green on the three files; an `rg` for
`specialist|persona|modelSource|docket help|harness run` over the three files is empty. Oracle:
the two commands.

### P39-21 — the reference docs: CONFIGURATION, SECURITY-SIMPLE, troubleshooting, MODEL-GATEWAYS, docs index, contracts

**Status:** TODO · **Size:** S · **Wave:** 94 · **Model:** Haiku · **Spec:** none

**Goal:** same method as P39-20 over `docs/CONFIGURATION.md`, `docs/SECURITY-SIMPLE.md`
(`gates` → `setup sandbox` throughout; the opt-in section keeps its content),
`docs/troubleshooting.md` (61 invocations; every remedy names a command that exists),
`docs/MODEL-GATEWAYS.md`, `docs/README.md` (the start-here order), `docs/contracts/harness-v1/`
prose (`harness run` → `exec`; the schema is untouched). `docs/recipes.md` is regenerated by
`scripts/gen_recipe_docs.py` after P39-22, not edited.

**Acceptance:** `rewrite_cli_names.py --check` green on the files; an `rg` for `docket gates|
docket profile|docket maintain|harness run` over `docs/` is empty. Oracle: the two commands.

### P39-22 — recipe READMEs, templates and the specs' prose

**Status:** TODO · **Size:** S · **Wave:** 94 · **Model:** Haiku · **Spec:** every spec that names a CLI command in prose (26 files, listed in the packet); versions bumped patch-level with one changelog line each: "command names follow ADR 0022"

**Goal:** after the script: the eighteen recipe `README.md` files under `src/docket/templates/
recipes/` (thirteen say `docket pod <project> config unset pipeline`; they now say `docket pod
unset pipeline`), the Lead instruction and workspace templates that print a next command, and
the prose of every spec outside `cli-interface.spec.md` that names a removed invocation. A
spec's *requirements* are not changed by this card: if a requirement itself names a removed
command, the card returns the locator and the Wave 93 card that owns it is reopened.
`scripts/gen_recipe_docs.py` regenerates `docs/recipes.md`.

**Acceptance:** `rewrite_cli_names.py --check` green over `specs/` and `src/docket/templates/`;
`bash scripts/validate-specs.sh` green; `gen_recipe_docs.py --check` green. Oracle: the three
checks.

### P39-23 — assets, CHANGELOG, spec close, Tack's one line, board archive

**Status:** TODO · **Size:** M · **Wave:** 94 · **Model:** Integrator · **Spec:** `cli-interface.spec.md` 2.0.0 (status, the registry rewritten as the eleven commands; a `#### docket <cmd>` section per top-level command, each with its verbs)

**Goal:** `scripts/maint/capture-doc-journey.sh` re-run on the local endpoint and
`scripts/render-doc-assets.py` re-transcribed so the hero GIF and both PNGs show commands that
exist; `CHANGELOG.md` `[Unreleased]` gains a "Removed" list (every name in ADR 0022 decision 5,
one line each, with the replacement) and a "Changed" entry for the tree, the pod resolver, the
contract and the role vocabulary; `cli-interface.spec.md` cut to the eleven commands at 2.0.0
with the removed sections gone (not struck through); `specs/README.md` row updated;
`scripts/metrics.py --check` re-measured (`commands=11`); the one-line change in
`objetivosMios/crates/tack-runner/src/harness/docket/probe.rs` (`"harness", "run"` → `"exec"`)
applied in that repo and its harness tests run there; the YieLab landing page
(`~/Sites/newPortaflio/content/docket-landing.ts`) is updated after the release that ships the
names, recorded as the one follow-up.

**Acceptance:** every gate in the board rules green on `develop`; `docs/commands.md` lists eleven
commands; the three new guards and the removed-name guard green; `git grep -n 'docket pod '`
finds only `docket pod <verb>` forms outside `docs/cycles-ended/` and `CHANGELOG.md`; Tack's
docket harness tests pass against `exec`. Oracle: the gates.

### P39-24 — the measurement: six journeys re-run, checklist re-scored

**Status:** TODO · **Size:** S · **Wave:** 95 · **Model:** Integrator · **Spec:** ADR 0022 gains a "Live run" section

**Goal:** the six journeys of the audit's live run (first run, daily loop, the gate, make it
yours, ops, errors) re-run against the Wave 94 rollup under the same throwaway `HOME` and the
local endpoint with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`; the 20-rule checklist re-scored; every
defect of the audit's table checked for reproduction; the result recorded in ADR 0022 "Live run"
with the score, the two named exceptions and any new defect as a locator for triage (not fixed
in this card unless one line).

**Acceptance (ADR 0022 "How done is measured"):** zero of the sixteen defects reproduces; the
newcomer path never types the pod name; every `--help` at every level has an example; the four
guessed commands work or suggest correctly; checklist 18/20 or better. Oracle: the transcript
saved under `internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`.
