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
> ## ◆ ACTIVE — Phase 38 opened 2026-10-05 (the execution envelope, D-55)
>
> **Phase 38 opened 2026-10-05** (ROADMAP D-55,
> [ADR 0020](docs/adr/0020-the-execution-envelope.md)): nine cards over Waves 85–88, at the end
> of this file. Wave 85 (six cards) is claimable.
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

## ◆ ACTIVE — Phase 38: the execution envelope (D-55), Waves 85–88 (opened 2026-10-05)

**Opened 2026-10-05** (ROADMAP D-55, [ADR 0020](docs/adr/0020-the-execution-envelope.md)).
Every outline locator was re-verified at `25fe5252`. Three outline claims were corrected and one
item deferred in ADR 0020:
- file tools are not moved into a subprocess jail; a symlink walk is closed instead (P38-8);
- the lockdown does not change ADR 0004's open default (P38-4);
- docket has no credential issuer, so its own credentials are stripped instead (P38-6);
- `kind: autonomy` is deferred until a verifier produces one.

Two facts measured on 2026-10-05 shape P38-3: under bwrap a task worktree cannot `git commit`
(`.git/worktrees/<t>/index.lock: Read-only file system`), and docker's default image `alpine:3.20`
has neither `git` nor `python3`.

Carried, not scheduled here: finished task worktrees have no retention policy; the check recipes
read their overrides from the process environment; the four Phase 36 items (ADR 0018 "Cut and
deferred").

**Workers.** Each card runs in an isolated worktree that is reset to `develop` before editing. The
worker diffs from `git merge-base`, commits on its branch, and never merges, pushes, stashes, or
edits `TODO.md`/`ROADMAP.md`/`CONTRIBUTING.md`/`README.md` counts. The integrator rebases, gates,
merges, and bumps spec versions. **`~/.docket` must not exist**: a test that creates it leaks into
the real home and fails the card. Packets: `.agents/handoffs/wave-85-worker-packets.md`.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 85 | P38-1 ∥ P38-2 ∥ P38-3 ∥ P38-6 ∥ P38-7 ∥ P38-8 | `core/trace.py::_REDACT_PATTERNS`, `trace-store.spec.md` → P38-1; `core/tools.py::_fetch_tool`, `core/mcp_tools.py::_screen_result` (extracted into one shared screening function) → P38-2; `core/fleet.py::FleetSecurity` and its isolation readers/writers, `core/security.py` isolation wrappers, `edges/adapters/docket_runtime.py::_resolve_sandbox`, `edges/adapters/system.py::sandbox_availability`, `bwrap_argv`, `docker_run_argv`, `cli/_gates.py`, `cli/_doctor.py::_check_security_gates` (and its JSON twin), goldens `gates_status`/`help` → P38-3; `edges/adapters/system.py::run_verify_cmd`, `edges/adapters/toolbox.py::run_bash` (the unjailed env only) plus one new env helper → P38-6; `serve.py::_run_sweeps`, `_sweep_loop`, one `config.py` constant → P38-7; `edges/adapters/toolbox.py::resolve_within`, `glob_files`, `grep_files`, `write_file`, `edit_file` → P38-8 |
| 86 | P38-4 | `core/fleet.py` (a `network` flag), `cli/_gates.py` (`gates network`), `core/pod.py` settings (`network`), `system.py::bwrap_argv`/`docker_run_argv` (a network parameter), `docket_runtime.py` (the turn's network mode on `ToolContext`), `toolbox.py::run_bash` (passing it) |
| 87 | P38-5 | `edges/adapters/mcp_client.py::_stdio_params` and its callers, `core/mcp_tools.py::load_mcp_tools` (a launch spec replacing the two `cwd` lambdas), `McpServerConfig.isolate`, `cli` `mcp servers add --no-isolate`, `docket_runtime.py::_load_mcp_tools` |
| 88 | P38-9 (integrator) | seam tests, live run, docs, spec bumps, rollup, archive |

`specs/functional/security-gates.spec.md` is shared by P38-2, P38-3, P38-6 and P38-8 at section
level: each worker edits only its own section and adds one `Unreleased` changelog line; the
integrator merges the changelog lines and bumps the version once. `toolbox.py` is shared in Wave
85 at function level only: P38-6 owns `run_bash`'s environment, P38-8 the file tools. P38-3 owns
the argv builders in Wave 85 and hands them to P38-4 in Wave 86.

Every card follows the §"How to use this board" definition of done.

### P38-1 — the redaction pattern matches only at a word start

**Status:** IN-PROGRESS (Wave 85 worker) · **Size:** S · **Wave:** 85 · **Model:** Haiku · **Spec:** `trace-store.spec.md` (redaction)

**Trigger (measured live, 2026-10-04 and re-run 2026-10-05):** `trace.redact("task=task-<uuid>")`
returns `ta[REDACTED]`; the first `_REDACT_PATTERNS` entry's `sk|pk|api|key|tok|...` alternation
has no left boundary.

**Goal:** give that alternation a left boundary (not preceded by a letter or digit), so a label
matches only where it starts a word. `_` stays a boundary, so `api_key=<20+ chars>` and
`MY_TOKEN=<...>` are still redacted.

**Non-goals:** the other three patterns; the stored-secret pass; any new pattern.

**Acceptance:**
- `redact("task=task-8d627c86-9a63-4379-beee-ee3b2afff6f7")` is unchanged.
- `redact("risk=" + "a" * 24)` is unchanged.
- `redact("api_key=" + "A" * 24)`, `redact("key: " + "A" * 24)`, `redact("Bearer " + "A" * 24)` and
  `redact("token=" + "A" * 24)` each contain `[REDACTED]` and not the value.
- The existing redaction tests stay green unchanged.

### P38-2 — `fetch` results pass `pre_input`

**Status:** IN-PROGRESS (Wave 85 worker) · **Size:** S · **Wave:** 85 · **Model:** Haiku · **Spec:** `security-gates.spec.md` (fetch section), `mcp-client.spec.md` (result screening, a pointer only)

**Trigger:** `core/tools.py::_fetch_tool` returns the page text as is, while
`core/mcp_tools.py::_screen_result` screens MCP results (ADR 0019 cut `fetch`; ADR 0020 §7).

**Goal:** extract `_screen_result` into one function that both the MCP handler and `_fetch_tool`
call, with the source named in the audit entry. `fetch` audits under `fetch.result_blocked` /
`fetch.result_warn`; the MCP audit actions are unchanged.

**Non-goals:** built-in tools other than `fetch`; the fetch allowlist; description screening.

**Acceptance:**
- With a real baseline `pre_input` policy and a fake HTTP response carrying an injection phrase, a
  live `dispatch_tool("fetch", ...)` returns `ok=False` naming the policy, plus one audit entry
  naming the URL's host.
- A clean page passes byte-identical; a redact policy returns the redacted text.
- The P37-1 MCP result tests stay green unchanged (one function, two callers).

### P38-3 — isolation on by default, bwrap first, a jail that can commit

**Status:** IN-PROGRESS (Wave 85 worker) · **Size:** L · **Wave:** 85 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` ("Workspace isolation" and its live-wiring and CLI sections), `cli-interface.spec.md` (gates/doctor lines)

**Trigger:** `FleetSecurity.isolation_enabled` defaults to `False`. Measured 2026-10-05: under
bwrap, `git commit` in a task worktree fails (`index.lock: Read-only file system`), and the docker
default image has no `git`/`python3`.

**Goal (ADR 0020 §1–3):**
- A `DOCKET_HOME` with no recorded choice is isolated. `gates isolate off` records an explicit,
  audited off; `isolate on` records on. The display shows `on (default)`, `on` or `off`.
- `sandbox_availability` tries bwrap first, then docker; `DOCKET_SANDBOX_BACKEND` still forces.
- `gates isolate on` and `doctor` probe `sandbox_availability` (no `shutil.which("docker")`).
  `doctor` reports the backend that a turn would use, or the refusal and its two fixes.
- The turn refusal (`isolation.refused`) names both fixes.
- `bwrap_argv` (and the docker `-v` mounts) add the git dir and common dir of every root that is a
  git worktree or repository, read-write.

**Non-goals:** the network (P38-4); MCP servers (P38-5); `run:`/`verifyCmd` (cut, ADR 0020).

**Acceptance:**
- With no `fleet.json`, a `DocketDriver` turn's `ctx.sandbox` is not `"off"` (the inverse of
  `test_isolation_off_leaves_ctx_sandbox_off`, which now writes an explicit off).
- With `DOCKET_SANDBOX_BACKEND=none` and no recorded choice, a turn is refused before any model call
  and the error names `bubblewrap` and `docket gates isolate off`.
- **Real bwrap** (skip with a reason when absent): `run_bash` jailed in a real git worktree runs
  `git add` + `git commit` successfully, and a write to a host path outside the roots fails.
- `sandbox_availability()` with both backends faked available returns `bwrap`.
- Every test that wants no jail says so in its own fixture; no autouse switch.
- Goldens `gates_status`/`help` regenerated only where the CLI text changed, each line explained.

### P38-4 — a network lockdown mode

**Status:** TODO · **Size:** M · **Wave:** 86 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (the D-23/D-24 egress section), `pod-dispatch.spec.md` (pod settings), `cli-interface.spec.md`

**Trigger:** neither backend cuts the network (`--share-net`, docker's bridge); ADR 0004 deferred
the mechanism. ADR 0020 §4.

**Goal:** `docket gates network none|open` (global, audited) and the pod setting `network`
(`none` only narrows a global `open`). Under `none`, `bwrap_argv` omits `--share-net` and
`docker_run_argv` adds `--network none`. `network none` with isolation off refuses the turn before
any model call. `fetch` is untouched. `gates status`, `doctor` and `config explain` show the mode
and its scope.

**Acceptance:**
- **Real bwrap:** under `none`, a jailed `python3 -c` socket connect to `1.1.1.1:53` fails, and the
  same call under `open` gets past socket creation. (No connection to a real host is required: a
  failed `socket.socket()` or `ENETUNREACH` is the oracle.)
- A pod with `network: none` under a global `open` gets `none`; a pod `open` under a global `none`
  stays `none`.
- `network none` + `isolate off` → the turn is refused, naming both settings.

### P38-5 — stdio MCP servers start in the jail

**Status:** TODO · **Size:** M · **Wave:** 87 · **Model:** Sonnet · **Spec:** `mcp-client.spec.md`

**Trigger:** `mcp_client.py::_stdio_params` spawns the server on the host; `load_mcp_tools` threads
`cwd` through two `type: ignore` lambdas (carried from Phase 37). ADR 0020 §5.

**Goal:** a stdio server's `command`/`args` are wrapped by the turn's backend (roots, git dirs,
network mode) when isolation is on. A server declared `isolate: false` (`mcp servers add
--no-isolate`, audited, shown by `doctor`) starts unjailed. `load_mcp_tools` takes one launch value
(`cwd`, backend, network, roots) instead of the `cwd` lambdas, and the `type: ignore`s go.

**Acceptance:**
- **Real bwrap:** a stdio test server that writes outside the roots fails to; the same server
  declared `isolate: false` succeeds.
- Under `network none`, a jailed test server cannot open a socket.
- Isolation off: the argv is the server's own, byte-identical to before.

### P38-6 — a task's processes never see docket's credentials

**Status:** IN-PROGRESS (Wave 85 worker) · **Size:** S · **Wave:** 85 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (a "Credentials in task processes" section)

**Trigger:** `run_verify_cmd` passes `{**os.environ, **env}`; `run_bash` with `sandbox="off"`
inherits `os.environ`; both carry provider keys when the operator exported them. ADR 0020 §8.

**Goal:** one helper returns the host environment minus `DOCKET_LLM_API_KEY`, every credential
name the provider catalog declares, `TELEGRAM_BOT_TOKEN` and every name in the secret store. Both
call sites use it; the explicit `env` overlay still wins.

**Acceptance:**
- With `OPENAI_API_KEY`, `DOCKET_LLM_API_KEY` and a stored secret's name exported, a real
  `run_verify_cmd("env", ...)` output contains none of them, and still contains `PATH` and a
  harmless exported variable.
- An unjailed `run_bash("env")` gives the same result.
- `DOCKET_TASK_ID` passed through `env=` still arrives.

### P38-7 — one sweep worker per pod

**Status:** IN-PROGRESS (Wave 85 worker) · **Size:** M · **Wave:** 85 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (the serve sweep), `serve-read-api.spec.md` only if a route's output changes

**Trigger:** `serve.py::_run_sweeps` loops over `dispatchable_pods()` and runs each synchronously;
its own comment records that one blocking hop stalls the other pods. ADR 0020 §9.

**Goal:** each pod is swept in a worker; a pod with a sweep in flight is skipped until it ends;
at most `DISPATCH_SWEEP_WORKERS` (default 4) run at once. Run records, audit and trace stay what
they are per pod. `stop` ends the loop and waits for in-flight sweeps.

**Acceptance:**
- Two pods, one whose fake dispatch blocks on an event: the other pod's task reaches `done`
  while the first is still blocked.
- A second tick while pod A's sweep is in flight does not start a second sweep of A.
- With `DISPATCH_SWEEP_WORKERS=1`, sweeps are serial again.
- `stop` returns only after the in-flight sweeps end.

### P38-8 — file tools never follow a symlink out of their roots

**Status:** IN-PROGRESS (Wave 85 worker) · **Size:** S · **Wave:** 85 · **Model:** Haiku · **Spec:** `security-gates.spec.md` (file-tool containment)

**Trigger:** `resolve_within` checks the requested path; `glob_files` and `grep_files` walk a root
and may meet a symlink to a host path. Not yet measured either way: the card's first step is the
RED test. ADR 0020 §6.

**Goal:** a path yielded by `glob`, or searched by `grep`, resolves inside the roots, or it is
skipped. `write`/`edit` refuse a target whose final component is a symlink that resolves outside.

**Acceptance:**
- A root containing `link -> /etc` (or a tmp dir outside the root): `glob("**/*")` lists no file
  under the target, and `grep("root")` returns no match from it.
- `write("link/x", ...)` is refused with `PathEscapeError`.
- A symlink that stays inside the root still works.
- If the RED tests pass before any change, the card closes as verified with the tests kept, and
  says so.

### P38-9 — integrate and close Phase 38

**Status:** TODO · **Size:** M · **Wave:** 88 · **Model:** integrator

Seam tests owned by the integrator (ADR 0020 "Test discipline"): a default-on dispatch commits in
its task worktree; a jailed MCP server under `network none` cannot connect out; one screening
function, two callers. A live run on the local endpoint with isolation on by default (bwrap) and a
second under `network none`. Docs that say isolation is opt-in are rewritten (README,
`docs/SECURITY-SIMPLE.md`, `docs/QUICK-START-DOCKET.md`, the security-gates spec status line).
Spec bumps, CHANGELOG, metrics, board rollup and archive.
