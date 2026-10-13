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
> ## ◇ NO ACTIVE WAVE — Wave 102 closed 2026-10-13: Phase 41 sub-wave C done; sub-wave D (P41-8) next
>
> **Phase 40** (ROADMAP D-58, [ADR 0023](docs/adr/0023-harden-the-agent-boundary.md)) closed
> 2026-10-12 over Waves 98–100, archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). **Phase 41** (one execution
> envelope, D-60, [ADR 0024](docs/adr/0024-one-execution-envelope.md)) closed sub-waves A–C in
> Waves 100–102. Sub-wave D (**P41-8**, the escape matrix) is ready on the Wave 102 rollup and now
> carries a measured escape: the Landlock jail grants the whole git dir read-write (packet in
> [.agents/handoffs/phase-41-worker-packets.md](.agents/handoffs/phase-41-worker-packets.md)).
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


## ◇ PHASE 41 — one execution envelope (D-60, ADR 0024): sub-waves A–C closed (Waves 100–102); sub-wave D (P41-8) next

> **Opened 2026-10-12; sub-waves A (P41-1, P41-6), B (P41-5, P41-4, P41-2) and C (P41-3,
> P41-7) closed in Waves 100–102.** `system.jail_launch` is the one jail builder (`bash`, verify,
> `run:`) and takes the pod cache dir as a rw root. bwrap and `isolate` are gone; Docker only when
> chosen (`setup sandbox backend docker`). **Open, measured at the Wave 102 close:** with bwrap
> gone, the Landlock jail is Linux's only automatic backend and it grants the whole git dir
> read-write (`_mount_dirs`), so an isolated agent can write `.git/hooks`/`config`; P41-8 owns
> the RED row and the fix. `docket exec` has no pod, so its jailed commands get no cache dir.
> The maintainer's 2026-10-12 decisions (ADR 0024): one jail for
> everything the project runs, Landlock + seccomp on Linux, Seatbelt on macOS, Docker when
> chosen, bwrap and `isolate: false` deleted, the gate lenient inside the envelope and strict
> outside, sandbox off by default and visible, network `none` by default. A coordinator activates
> each sub-wave with the `ACTIVE BOARD` banner and a base commit.
>
> **Sub-waves, by contention on `edges/adapters/system.py`:** **A** P41-1 ∥ P41-6 ·
> **B** (on A's rollup) P41-2 ∥ P41-4 ∥ P41-5 · **C** P41-3 ∥ P41-7 · **D** P41-8. Each worker
> owns its card's files plus its owning spec section; `README.md`, `docs/SECURITY-SIMPLE.md`,
> the quick start, CLAUDE.md's limits and this board are the integrator's, rewritten as each
> card merges (D-37).

### P41-1 — a Landlock + seccomp jail for Linux

**Status:** DONE (2026-10-12, merge `65857797`) · **Size:** L · **Model:** Sonnet · **Spec:** security-gates.spec.md ("Exec sandbox")

**Trigger (D-60):** bwrap is a system package that needs user namespaces (absent in most CI
containers) and its profile `--ro-bind / /` lets the agent read the whole disk.

**Goal:** `src/docket/jail.py`, an entry run as `python -m docket.jail --rw <dir>... --ro
<dir>... --net none|open -- <argv...>`: sets `PR_SET_NO_NEW_PRIVS`, builds a Landlock ruleset
(ABI probed; rw: the given roots and `$TMPDIR`; ro: `/usr`, `/lib`, `/lib64`, `/bin`, `/sbin`,
`/etc`, `/opt`, `sys.prefix`, `/dev/null|zero|urandom|tty`; nothing else, so the home is
denied), adds Landlock TCP rules when ABI >= 4, installs a seccomp BPF filter (via `prctl`,
no libseccomp) that denies `socket(AF_INET|AF_INET6)` when `--net none`, then `execvp`s.
`edges/adapters/landlock.py` holds the `ctypes` layer (`landlock_create_ruleset`,
`landlock_add_rule` with `O_PATH` fds, `landlock_restrict_self`, the BPF program).
`edges/adapters/system.py` gains `landlock_available()` (ABI version probe) and
`landlock_argv(roots, command, network)`; `sandbox_availability` prefers `landlock` over
`bwrap` and `docker`; `DOCKET_SANDBOX_BACKEND=landlock` is accepted. bwrap stays until P41-3.

**Non-goals:** deleting bwrap (P41-3); jailing verify/`run:` (P41-4); the cache dir (P41-5);
macOS (P41-2).

**Acceptance:** RED (integration, real kernel, skip when ABI < 1) — on the base a subprocess
under the only Linux backend reads a seeded file under a fake home. GREEN — under
`python -m docket.jail --rw <root> --net none -- python3 -c ...`: reading that file raises
`PermissionError`, writing outside the root raises, writing inside works, `socket.connect` to a
local listener fails; `--net open` connects. Unit: argv and ruleset construction, no syscalls.
Oracle: the child's exit code and captured errors. Note: this host runs kernel 6.14.

### P41-2 — a Seatbelt backend for macOS

**Status:** DONE (2026-10-13, merge `9dfca1e3`) · **Size:** M · **Model:** Sonnet · **Spec:** security-gates.spec.md ("Exec sandbox")

**Trigger (D-60):** on macOS the only backend is Docker Desktop, which most operators do not
run; Claude Code and Codex use the OS's `sandbox-exec`.

**Goal:** `system.py::seatbelt_available()` (darwin and `/usr/bin/sandbox-exec` exists) and
`seatbelt_argv(roots, command, network)`: `sandbox-exec -p <profile> /bin/sh -c <command>` with
one fixed profile template: `(version 1) (deny default) (allow process-exec* process-fork
sysctl-read mach-lookup ...)`, `(allow file-read* (subpath "/usr") ...)` for the system paths
P41-1 lists, `(allow file-read* file-write* (subpath "<root>"))` per root and `$TMPDIR`,
`(deny network*)` or `(allow network*)`. `sandbox_availability` prefers it on darwin. The
deprecation of `sandbox-exec` is noted in the module docstring.

**Acceptance:** unit — the profile text for two roots and both network modes, byte-exact; the
backend order on a monkeypatched darwin platform. The live run is P41-8's macOS CI job; this
card cannot run it on Linux and says so.

### P41-3 — delete bwrap and `isolate: false`; Docker is a chosen backend

**Status:** DONE (2026-10-13, merge `e3a2ae7d`) · **Size:** S · **Model:** Haiku · **Spec:** mcp-client.spec.md (requirement 40 deleted), security-gates.spec.md

**Goal:** delete `_bwrap_prefix`, `bwrap_argv`, `bwrap_available`, the `bwrap` backend value
and its tests; delete the `isolate` field from `kind: mcp-server` documents (schema regenerated
by `scripts/gen_operator_schemas.py`, `code-intel`'s `ast-grep.yaml` and README, recipe docs
regenerated), its loader branch in `core/mcp_tools.py` and `mcp_client.py`; Docker is used only
when `docket setup sandbox backend docker` was set (fleet.json key read by
`sandbox_availability`; `auto` means landlock/seatbelt). `scripts/maint/pytest-without-sandbox.sh`
exports `DOCKET_SANDBOX_PROBE=none`, a variable only the availability probe reads and no
fixture touches, instead of stripping binaries from `PATH`. `CHANGELOG.md` line in the return.

**Acceptance:** `rg -n 'bwrap|isolate' src tests docs specs` finds only the CHANGELOG and
`docs/cycles-ended/`; the no-backend script passes; with `backend docker` unset and Docker
running, a turn uses landlock.

### P41-4 — verify, `run:` steps and MCP servers run inside the envelope

**Status:** DONE (2026-10-13, merge `e51fabd2`) · **Size:** M · **Model:** Sonnet · **Spec:** pod-dispatch.spec.md (verify gate), security-gates.spec.md ("Credentials in task processes")

**Trigger (D-60, measured 2026-10-12):** `core/dispatch.py` calls `system.run_verify_cmd` on
the host, so a test file the agent writes runs with the operator's rights even with the sandbox
on; `run:` steps and stdio MCP servers likewise.

**Goal:** `run_verify_cmd` and the `run:` executor take the same jail decision `toolbox.run_bash`
takes (`sandbox_availability` + the isolation flag + the pod's network) and wrap the command with
the backend argv, cwd the task worktree; stdio MCP servers always start jailed. With the sandbox
off: unchanged. The classification of the verify command (`classify_command` fail-closed) stays.

**Acceptance:** RED — with `DOCKET_SANDBOX_BACKEND=landlock` and isolation on, a `verifyCmd`
that writes a file outside the worktree succeeds on the base. GREEN — it fails and the task
ends `verification_failed`; a `run:` step the same; a verify that writes inside passes; sandbox
off still runs on the host. Oracle: the file outside not existing, the task record, in an
isolated home (integration lane).

### P41-5 — a per-pod cache directory and a hidden home

**Status:** DONE (2026-10-13, merge `81e6cc41`) · **Size:** S · **Model:** Sonnet · **Spec:** pod-dispatch.spec.md (task environment)

**Trigger (D-60):** `isolate: false` existed because `uv`'s cache under the home was read-only
in the jail; with the home denied, every tool that writes `~/.cache`, `~/.npm` breaks.

**Goal:** provisioning creates `<lead workspace>/cache/` (0700); `system.task_environment` sets,
for a jailed command, `HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `UV_CACHE_DIR`,
`PIP_CACHE_DIR`, `npm_config_cache` to it, and the jail gets that directory as a rw root.
Git identity keeps coming from the `GIT_*` variables dispatch already sets (the existing
"commits with the operator's identity" tests must stay green).

**Acceptance:** RED — a jailed `uv --version`-style command that writes its cache fails on the
base with the home denied. GREEN — it writes under the pod cache; the env carries the six
variables; the cache dir is 0700. Oracle: files under the cache dir, `oct(mode)`.

### P41-6 — the gate rule: allowed inside the envelope, the allowlist outside; network `none`

**Status:** DONE (2026-10-12, merge `0a238f7a`) · **Size:** M · **Model:** Sonnet · **Spec:** security-gates.spec.md (Tool-approval gates item 1, Network egress)

**Trigger (D-60 §2):** inside a jail the allowlist only produces approval noise (`bash -c`,
`curl`), while high-risk classes are the real question; and `network: open` by default lets a
jailed agent exfiltrate the repository's own secrets.

**Goal:** `classify_command(..., jailed: bool = False)`: when jailed, a binary off the allowlist
is `allow` unless a high-risk class matches (still `ask`) or the command is not statically
analysable (still `ask`); `core/tools.py::evaluate_tool_call` passes `jailed` from the turn's
sandbox decision. `core/pod.py` network default and `fleet.get_network_mode` default become
`none`; `effective_network` unchanged (narrowing only). `docket setup sandbox` prints the
network mode's new default.

**Acceptance:** RED — `curl https://x` jailed is `ask` on the base; a fresh home reports
`network open`. GREEN — jailed `curl` is `allow`, unjailed `ask`, jailed `git push origin
production` `ask`, jailed `$(...)` `ask`; a fresh home reports `network none`. Goldens that
print the network mode recaptured with the diff explained. Oracle: `classify_command` verdicts;
`setup sandbox --json`.

### P41-7 — the sandbox is visible: probe, platform lines, backend choice

**Status:** DONE (2026-10-13, merge `b90a03b5`) · **Size:** M · **Model:** Sonnet · **Spec:** cli-interface.spec.md (`init`, `status`, `setup sandbox`), cli-json-shapes.spec.md (`status --json` if a field changes)

**Trigger (D-60 §4-5):** `docket init` says nothing about the sandbox; only `status` has an
`Isolation:` line; nobody installing learns whether a backend exists or what to install.

**Goal:** `docket setup sandbox` (and `--json`) reports per platform: backend found (`landlock
(kernel 6.14)`, `seatbelt`, `docker`), or what is missing (`Linux: a kernel with Landlock
(>= 5.13)`; `Windows: use WSL2; native runs without a sandbox`); `docket setup sandbox backend
auto|docker`; `init` ends with a `This machine / Sandbox` line (`off. The agent's commands run
with your user's permissions. Turn it on: docket setup sandbox on`, or `on (landlock)`), `status`
opens with it, `doctor` counts a home with pods and no backend as an issue; `install.sh` prints
the probe's one line. Copy per ADR 0024 §4-5.

**Acceptance:** RED — `init` output on the base has no sandbox line. GREEN — the line in each
state (monkeypatched availability); `setup sandbox backend docker` persists and the probe
honours it; goldens (`status`, `setup sandbox`) recaptured with the diff explained. Oracle:
captured output, fleet.json.

### P41-8 — the escape matrix as a release gate

**Status:** TODO (sub-wave D) · **Size:** M · **Model:** Sonnet · **Spec:** security-gates.spec.md (Validation)

**Goal:** `tests/integration/test_escape_matrix.py` (SUBJECT `docket.jail`), parametrized over
the backends available on the host (landlock; docker when the daemon answers; seatbelt on
darwin): read a seeded `~/.ssh/id` under a fake home, write outside the roots, write
`.git/hooks/pre-commit` in the worktree, connect to a local listener under `network none`, read
`/proc/<ppid>/environ` with a seeded key, a `verifyCmd` that writes outside the worktree; every
row must fail, and one positive row (write inside the root) proves the jail was on. The macOS
CI job (`release-journey`, macos-latest) runs it; `ci.yml` is in this card's files.

**Acceptance:** the matrix passes on this host (landlock, docker) and in the macOS job;
security-gates "Validation" lists the rows. Oracle: pytest on each backend.

**Added at the Wave 100 close (P41-1's finding):** Landlock cannot make a sub-path of a writable
root read-only, so the jail has no `.git/hooks`/`config` overlay. In a task worktree `.git` is a
*file* pointing at the gitdir, and the hooks live outside the root; but the agent can rewrite that
file to point at a gitdir it controls (with `core.hooksPath` set), and docket runs `git` on the
host in that worktree after the hop. Add the row "replace the worktree's `.git` file, then let
dispatch's host-side git run": it must not execute anything the agent wrote. If it fails, the fix
is in this card: host-side git calls in a task worktree pass the gitdir docket recorded
(`--git-dir`/`--work-tree`) and never read the worktree's `.git` file.

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
