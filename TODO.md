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
> ## ▶ ACTIVE BOARD — WAVE 71 (Phase 35, D-51) · opened 2026-09-29
>
> **Ten cards over Waves 71–75**, one worker per card (Sonnet, or Haiku where the card says so)
> in an isolated worktree under one integrator. docket becomes the governed harness of a
> harness-agnostic factory:
> - an opt-in harness contract v1.1: process events, questions answered on stdin, written
>   paths, `--token-file`, the caller's limits, and a recipe pipeline run in place;
> - pod dispatch keeps its evidence (verify output, commit SHA, `requireVerify`);
> - two measured defects fixed.
>
> Decision, reversals and verdict table:
> [docs/adr/0017-docket-in-a-harness-agnostic-factory.md](docs/adr/0017-docket-in-a-harness-agnostic-factory.md).
> Worker packets: [.agents/handoffs/wave-71-worker-packets.md](.agents/handoffs/wave-71-worker-packets.md).
> **Wave 71 (P35-1..P35-4) is ready to claim.** Phase 35 closes when the Wave 75 rollup merges
> green. Phases 36–38 are planned below and are **not claimable** until their phase opens.
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

## ▶ WAVE 71 ACTIVE — Phase 35, docket in a harness-agnostic factory (D-51), Waves 71–75 (opened 2026-09-29)

**Opened 2026-09-29 at `6525b52`.** Ten cards in five waves. Decision, reversals, cut and
deferred lists: [docs/adr/0017-docket-in-a-harness-agnostic-factory.md](docs/adr/0017-docket-in-a-harness-agnostic-factory.md).
Worker packets: [.agents/handoffs/wave-71-worker-packets.md](.agents/handoffs/wave-71-worker-packets.md).

**Trigger (explicit request plus facts read on the live path and in the consumer, 2026-09-29).**
The maintainer asked for docket's part of the structured-agentic-engineering plan to be
architected into the roadmap for parallel Sonnet workers, setting existing ADR limits aside
(each reversal is recorded in ADR 0017). Read at `6525b52` and in Tack at `7718420`:
- Tack's U8 is blocked because docket ships no `harness-v1.1` (Tack `docs/plans/phase-65.md`,
  M3 "done 2026-09-20: absent"). It needs four items: a process-group event, a stdout question
  answered on stdin, a written-path list, and the token on stderr or `--token-file`.
- Tack declares docket `decisions: Unsupported`, `artifacts: Advisory`, `cancel: Advisory` and
  passes it no policy or budgets (Tack `crates/tack-runner/src/harness/docket.rs::capabilities`).
- A passing verify's output is discarded and a missing `verifyCmd` advances
  (`core/dispatch.py::_evaluate_mechanical_gate`); `diff_ref` is a branch, not a commit
  (`_implementer_diff_probe`).
- Two defects: `guardrail_block` writes the policy id into `action`
  (`_enqueue_pre_input_gate`, `_apply_output_guardrails`); `budget_for_role` ignores
  pod-scoped roles (`core/context.py`).

**Spec ownership rule (Phases 32–34 lesson).**
- A worker adds requirements under **its own new section heading**, numbered from 1 inside that
  section, and never touches `**Version**`, `**Status**`, `**Last Updated**` or a changelog. The
  integrator bumps each spec once per rollup.
- P35-2 adds a "Contract 1.1" section to `specs/api/harness-mode.spec.md` with **every** later
  harness subsection already stubbed (`Status: Planned — owned by P35-N`). A later card
  replaces only its own stub.

**Contract rule (the W30 seam lesson).** P35-2 owns every v1.1 model in `core/harness.py`.
Every later card builds its wire values through those models and never hand-builds a second
dict. `--contract 1.0` (the default) stays byte-identical: the four v1 fixtures and the v1
schema are the no-change oracle for every card.

**Test rule.**
- One RED behavioural test per card, in the module's `SUBJECT` file.
- A second test only for the card's fail-closed negative case.
- No real model and no real vendor host: every HTTP target is a local `http.server` on port 0.
  The only exception is P35-10's live run, and only against `127.0.0.1:8081`.
- Existing tests, goldens and specs are the no-change oracle, except where a card names the
  change.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 71 | P35-1 ∥ P35-2 ∥ P35-3 ∥ P35-4 | `core/dispatch.py::_enqueue_pre_input_gate`, `_apply_output_guardrails`, `_hop_message` (the one `budget_for_role` call), `core/context.py::budget_for_role`, `core/session.py` (the one `budget_for_role` call), `role-archetypes.spec.md` → P35-1; `core/harness.py` (all v1.1 models, `HARNESS_CONTRACT_VERSIONS`), `scripts/harness_schema.py`, `docs/contracts/harness-v1.1/` (new), `tests/fixtures/harness-contract/v1.1/` (new), `cli/_harness.py::_flag`/`_usage_error` and the version selection in `_run`, `harness-mode.spec.md` "Contract 1.1" → P35-2; `edges/adapters/toolbox.py::run_bash`, `core/tools.py::ToolContext` (one field) and the `bash` handler lambda only, `core/trace.py::EVENT_TYPES` (+2), `core/telemetry.py::_STRUCTURAL_KEYS` (+2), `edges/adapters/docket_runtime.py` (the `ToolContext` construction), `trace-store.spec.md` → P35-3; `core/dispatch.py::_evaluate_mechanical_gate`, `_implementer_diff_probe`, `HopResult`, `_hop_record`, `_hop_from_record`, `edges/adapters/system.py` (new `git_head_sha`, `git_merge_base`, `git_diff_stat`), `pod-dispatch.spec.md` → P35-4 |
| 72 | P35-5 ∥ P35-7 ∥ P35-8 | `cli/_harness.py::_run` (answer wiring only), `cli/_harness_answers.py` (new), `core/approval.py::approval_create` (trace payload only) → P35-5; `core/harness_pipeline.py` (new), `core/pod_provisioning.py` (an in-place member path, no worktree) → P35-7; `core/pod.py::PodSettings` (`requireVerify`), `core/dispatch.py::_evaluate_mechanical_gate` (the `not verify_cmd` branch only), `pod-dispatch.spec.md` new section → P35-8 |
| 73 | P35-6 | `cli/_harness.py::_run` (pre-turn token file, limits, policies; post-turn files), `core/harness.py::result_from` (the `files` argument), `edges/adapters/docket_runtime.py` (pop `DOCKET_TURN_TOKEN_BUDGET`), `core/runtime_driver.py` (one constant) |
| 74 | P35-9 | `cli/_harness.py::_run` (the `--recipe` branch), `core/harness.py` (`task` block builder) |
| 75 | P35-10 (integrator) | seam test, live run, docs corrections, spec bumps, rollups, archive |

`cli/_harness.py::_run` is owned by exactly one card per wave (P35-2, P35-5, P35-6, P35-9 in
that order). No other card edits it.

Every card follows the §"How to use this board" definition of done.

### P35-1 — two measured defects: `guardrail_block.action` and pod-scoped role token budgets

**Status:** TODO · **Size:** S · **Wave:** 71 · **Model:** Haiku · **Spec:**
`role-archetypes.spec.md` new section "Pod-scoped token budgets"

**Trigger:** deterministic defects read at `6525b52`.
- `core/dispatch.py::_enqueue_pre_input_gate` and `_apply_output_guardrails` write
  `"action": hit.policy_id` into the `guardrail_block` payload. Expected: `hit.action`. The
  `guardrail_check` line just above each writes it correctly.
- `core/context.py::budget_for_role` calls `_arch.load_registry()` with no project. A
  `tokenBudget` declared on a pod-scoped role (written by `pod apply` through
  `core/archetypes.py`) is never read at `core/dispatch.py::_hop_message` or in
  `core/session.py`. This is the same shape as the Phase 30 `resolve_role_model(..., project=)`
  defect.

**Goal:**
- Both `guardrail_block` payloads carry `"action": hit.action`.
- `budget_for_role(role, *, project: str = "", context_window_tokens=..., max_output_tokens=...)`
  resolves `load_registry(project)` when a project is given, and the global registry otherwise.
- Both callers pass their project.

**Non-goals:** any other trace payload; changing budget defaults.

**Acceptance:**
- A pod whose applied role `implementer` declares `tokenBudget: 1234` gets `1234` from
  `budget_for_role("implementer", project=<pod>)`. The global call still returns the built-in
  value.
- A `pre_input` block and a `pre_output` block each write a `guardrail_block` record whose
  `action` equals the policy's action (`block`), not its id.

**RED:** the pod-scoped budget test in `tests/unit/core/test_context.py` fails at the base
(returns the built-in budget).

### P35-2 — the harness contract v1.1: models, schema, fixtures, `--contract`

**Status:** TODO · **Size:** M · **Wave:** 71 · **Model:** Sonnet · **Spec:**
`harness-mode.spec.md` new section "Contract 1.1", with stubs for P35-3, P35-5, P35-6, P35-9

**Trigger:** ADR 0017 §1–2; Tack M3.

**Goal:**
- `core/harness.py`:
  - `HARNESS_CONTRACT_VERSIONS = ("1.0.0", "1.1.0")`; `HARNESS_CONTRACT_VERSION` stays
    `"1.0.0"`.
  - `HarnessEvent` and `HarnessResult` validate `v` exactly against the version they were built
    for. Keep the v1.0 classes unchanged; add `HarnessEventV11` and `HarnessResultV11`, or a
    version-parameterised validator, whichever keeps the v1.0 schema byte-identical.
  - New v1.1 models:
    - `FileChange{path, op: "write"|"edit"|"delete"|"unknown"}`;
    - `AnswerLine{v, token, answer: {approvalToken: str|None, questionId: str|None, action:
      "accept"|"decline"|"cancel", content: dict|None}}`, where exactly one of
      `approvalToken`/`questionId` is set;
    - `HarnessTask{status, hops: list[dict], evidence: dict|None}`;
    - `HarnessResultV11` = v1.0 fields + `files: list[FileChange] = []` + `task: HarnessTask |
      None = None` + `limits: {maxTokens: int|None}`.
- `scripts/harness_schema.py` writes both `docs/contracts/harness-v1/schema.json` (unchanged)
  and `docs/contracts/harness-v1.1/schema.json`, including `AnswerLine`.
- Fixtures at `tests/fixtures/harness-contract/v1.1/`: `ok-files.ndjson`,
  `asked-answered.ndjson` (an `approval_requested` event, then an ok result),
  `cancelled-process.ndjson` (`process_started`/`process_exited` with `signal`),
  `recipe-ok.ndjson` (a result with a `task` block), `answer-lines.ndjson` (stdin lines). Each
  line validates against the committed v1.1 schema.
- `cli/_harness.py`: `--contract 1.0|1.1` (default `1.0`). An unknown value is refused (exit 2).
  The chosen version is stamped on every emitted line. No other v1.1 behaviour yet.

**Non-goals:** process events, stdin, files, recipe execution (later cards fill their stubs).

**Acceptance:**
- `docket harness run --contract 1.1 ...` against the fake endpoint emits lines with `"v":
  "1.1.0"` that validate against the v1.1 schema.
- The same run without `--contract` is byte-identical to the base on the four v1 fixtures'
  scenarios.
- `--contract 2.0` → exit 2, one refused result.
- The v1 and v1.1 schema pins both hold.

**RED:** the v1.1 schema-pin test fails at the base (the file does not exist).

### P35-3 — process lifecycle events and cancellable process groups

**Status:** TODO · **Size:** M · **Wave:** 71 · **Model:** Sonnet · **Spec:**
`trace-store.spec.md` new section "Process lifecycle events"; the P35-3 stub in
`harness-mode.spec.md` after P35-2 merges (integrator reconciles if needed)

**Trigger:** ADR 0017 §2; Tack M3 item 1 ("an event per child process group started").

**Goal:**
- `edges/adapters/toolbox.py::run_bash` accepts `on_process: Callable[[str, dict], None] | None
  = None`. After `Popen` it calls `on_process("started", {"pgid": proc.pid})`. On every exit
  path (normal, non-zero, timeout, cancellation) it calls `on_process("exited", {"pgid",
  "exitCode" | "signal"})`, exactly once per start.
- `core/tools.py::ToolContext.on_process` (one field, default `None`). The `bash` handler
  lambda passes it, closing over `tool` and `callId`. No other change in `core/tools.py`.
- `core/trace.py::EVENT_TYPES` gains `process_started` and `process_exited`.
  `core/telemetry.py::_STRUCTURAL_KEYS` gains their structural keys (`pgid`, `tool`, `callId`,
  `exitCode`, `signal`).
- `edges/adapters/docket_runtime.py` builds `ToolContext.on_process` to:
  - emit the trace event;
  - call `core/runs.py::add_hop_pid(current_run_id(), pgid)` on start and `remove_hop_pid` on
    exit, when a run is current.

  `docket runs cancel` and harness SIGTERM then reach a live tool's process group.

**Non-goals:** harness-specific output (the trace already streams to stdout); MCP server
processes (Phase 38).

**Acceptance:**
- A turn whose `bash` call runs `sleep 30` under a run emits `process_started` with a live pgid.
- `docket runs cancel <run>` kills that group within the grace period and a `process_exited`
  with `signal` follows.
- A normal command emits one started/exited pair with `exitCode: 0`.
- No `bash` call → no process events (byte-identical trace otherwise).

**RED:** the start/exit pair test in a new `tests/unit/edges/adapters/test_toolbox.py`
(`SUBJECT = "docket.edges.adapters.toolbox"`) fails at the base (no callback parameter). The
cancel-kills-the-group case belongs beside `tests/integration/test_bash_cancellation.py`.

### P35-4 — pod dispatch keeps its evidence: verify output, commit, base, diffstat

**Status:** TODO · **Size:** M · **Wave:** 71 · **Model:** Sonnet · **Spec:**
`pod-dispatch.spec.md` new section "Hop evidence"

**Trigger:** ADR 0017 §4. `_evaluate_mechanical_gate` discards a passing verify's output;
`_implementer_diff_probe` records a branch name only.

**Goal:**
- `HopResult.verify: dict | None`, set by `_evaluate_mechanical_gate` on pass **and** fail:
  - `cmd`, `exitCode`, `durationS`;
  - `outputTail`: the last `VERIFY_EVIDENCE_TAIL_CHARS = 4000` characters, after
    `trace.redact`.

  The `verification_failed` trace event is unchanged.
- `_implementer_diff_probe` also returns:
  - `commit`: `git rev-parse HEAD` in the member's checkout;
  - `baseCommit`: merge-base of HEAD with the codebase's current branch;
  - `diffStat`: `{files, insertions, deletions}`.

  Each is `None` when not a repository. New `edges/adapters/system.py` helpers: `git_head_sha`,
  `git_merge_base`, `git_diff_stat`, which degrade to `None` like the existing git helpers.
- `_hop_record` persists `verify` and `evidence: {commit, baseCommit, diffStat}`;
  `_hop_from_record` round-trips them, and a legacy record without them loads unchanged.

**Non-goals:** committing on the agent's behalf; any CLI renderer (Phase 36); `requireVerify`
(P35-8).

**Acceptance:**
- A dispatched task with `verifyCmd: "echo ok"` persists a hop whose `verify.exitCode == 0` and
  whose `verify.outputTail` contains `ok`.
- A failing verify persists `exitCode != 0` and its redacted tail, and a stored secret value
  never appears in it (canary).
- In a git codebase the Implementer hop persists a 40-hex `commit`; outside git all three
  evidence fields are `None`.
- A hop record written at the base still loads.

**RED:** the passing-verify evidence test in `tests/integration/test_dispatch.py` fails at the
base (no `verify` key).

### P35-5 — questions on stdout, answers on stdin (`--answers stdin`)

**Status:** TODO · **Size:** M · **Wave:** 72 · **Model:** Sonnet · **Spec:** the P35-5 stub in
`harness-mode.spec.md`; `security-gates.spec.md` new section "The harness answer channel"

**Trigger:** ADR 0017 §2; Tack M3 item 2 and U8 `decisions: Supported`.

**Goal:**
- `--answers stdin` (v1.1 only; with `--contract 1.0` → exit 2):
  - sets `DOCKET_APPROVAL_MODE=wait` in `run_turn`'s env instead of `refuse`;
  - `--answer-timeout S` (default `TOOL_APPROVAL_TIMEOUT`) bounds each wait.
- Refused (exit 2) when the task comes from stdin: `--task-file` naming `-`, `/dev/stdin`, or
  `/proc/self/fd/0`.
- `cli/_harness_answers.py` (new): a daemon reader thread started around the turn.
  - It parses each stdin line as `core.harness.AnswerLine` and rejects a wrong `v`/`token`
    with one stderr line, ignoring the answer.
  - For an `approvalToken`: `content` (if any) passes `core.policy.policy_eval_detail("lead",
    "pre_input", text, trusted=False)`, then `accept` → `core.approval.approval_grant(t,
    channel="harness")` and `decline`/`cancel` → `approval_deny(t, channel="harness")`.
  - A `questionId` answer is accepted by the model and answered with a stderr "unsupported
    until a recipe run" line (P35-9 wires it).
  - It stops when the turn ends.
- `core/approval.py::approval_create`: the `approval_requested` trace payload adds `tool` and
  `callId` when the context has them. Nothing else changes.

**Non-goals:** a question tool for agents (Phase 36); HTTP; `park` in harness.

**Acceptance:**
- A scripted turn whose `bash` call needs approval emits `approval_requested` with `token`,
  `tool` and `callId`. Writing an `accept` line for that token runs the command and ends `ok`.
- A `decline` line denies it.
- No line within `--answer-timeout 1` denies (fail closed) and the run ends `blocked` or
  `failed` per the existing mapping.
- An answer whose content trips a `pre_input` block policy is refused and the approval stays
  pending until timeout.
- Every resolution writes an audit entry with `channel=harness`.

**RED:** the accept-line test in `tests/integration/test_harness_cli.py` fails at the base
(`--answers` unknown → exit 2).

### P35-6 — written paths, `--token-file`, and the caller's limits

**Status:** TODO · **Size:** M · **Wave:** 73 · **Model:** Sonnet · **Spec:** the P35-6 stub in
`harness-mode.spec.md`

**Trigger:** ADR 0017 §2; Tack M3 items 3–4; Tack `additional: Unsupported` (policy and budgets
not passed).

**Goal (v1.1 only; each flag with `--contract 1.0` → exit 2):**
- **`files`:** the harness collects every `tool_call` record for `write`/`edit` from its own
  trace subscription (path from the arguments). When the workspace is a git repository it
  merges `git status --porcelain` (through `edges/adapters/system.py`). The result is
  deduplicated, relative to the workspace, and passed to `core/harness.py::result_from(...,
  files=)`.
- **`--token-file PATH`:** written atomically with mode 0600 **before** the turn starts. It
  contains `{"v","token","pid"}`. The stderr line `docket harness: run <token> agent=...` is
  pinned in the spec as the stable format.
- **`--max-tokens N`:** `run_turn` env key `DOCKET_TURN_TOKEN_BUDGET` (new constant in
  `core/runtime_driver.py`), popped in `edges/adapters/docket_runtime.py` into the loop's
  measured-token bound. The result echoes `limits.maxTokens`.
- **`--policy FILE`** (repeatable):
  - each file is validated with `core.policy.validate_policy`;
  - an invalid file → exit 2 before any run;
  - valid files are copied into the caller's `DOCKET_HOME` policies directory and are active
    for the turn.

**Non-goals:** diff content (the caller captures it); dollar budgets.

**Acceptance:**
- A scripted turn that writes `a.txt` and edits `b.txt` returns `files` with both.
- A git workspace with an untracked file written by `bash` also lists it.
- The token file exists, with mode 0600, before the first model request (assert from the fake
  endpoint's first request handler).
- `--max-tokens 10` stops the turn on the token bound.
- A `--policy` denying `bash` blocks a `bash` call; a malformed policy file exits 2 with no run
  created.

**RED:** the `files` test in `tests/integration/test_harness_cli.py` fails at the base.

### P35-7 — the in-place recipe runner (core)

**Status:** TODO · **Size:** M · **Wave:** 72 · **Model:** Sonnet · **Spec:**
`pod-dispatch.spec.md` new section "In-place ephemeral pods"

**Trigger:** ADR 0017 §3. Harness mode must run a pipeline without a second executor.

**Goal:** `core/harness_pipeline.py::run_recipe_task(workspace: Path, recipe: str, task: str, *,
model: str, approval_mode: str, timeout: int, env: dict) -> RecipeRun`, which does the
following in the current `DOCKET_HOME`:
- provisions an ephemeral pod `h-<run-token-prefix>` with `codebase = workspace`, whose members
  work **in place**. Add the smallest parameter to `core/pod_provisioning.py` so an Implementer
  skips `provision_worktree` and its `cwd` resolves to the codebase;
- sets every role's model to `model`;
- applies the recipe through `core/pod_apply.py::resolve_recipe` / `plan_apply` and the
  existing apply path;
- enqueues one task (`enqueue_task`);
- runs `dispatch_task` synchronously with the pod's `approvalMode` set to `approval_mode`;
- returns `RecipeRun{task: dict, hops: list[dict]}` from the persisted task record.

**Non-goals:** the CLI flag (P35-9); worktrees; tearing down the ephemeral pod (it lives in the
caller's disposable home).

**Acceptance:**
- With the scripted backend, `run_recipe_task(tmp_repo, "tdd", ...)` runs the recipe's steps in
  order.
- The Implementer's `bash`/`write` calls land inside `tmp_repo` itself (a file appears there,
  and no worktree directory is created).
- The returned hops match the persisted task.
- An unknown recipe raises the existing `resolve_recipe` error before any pod is provisioned.

**RED:** the in-place write test in `tests/integration/test_harness_pipeline.py` (new) fails at
the base (module missing).

### P35-8 — `requireVerify`: a missing verify command fails instead of advancing

**Status:** TODO · **Size:** S · **Wave:** 72 · **Model:** Haiku · **Spec:**
`pod-dispatch.spec.md` new section "Required verification"

**Trigger:** ADR 0017 §4. `_evaluate_mechanical_gate` advances when `verifyCmd` is empty.

**Goal:**
- `core/pod.py::PodSettings.require_verify: bool = Field(False, alias="requireVerify")`, added
  to `KEYS` so `docket pod <p> config set requireVerify true` writes it.
- In `_evaluate_mechanical_gate`'s `not verify_cmd` branch, when the pod's setting is true:
  - trace `verification_failed` with `{"reason": "verification_missing", "member"}`;
  - return a `failed` outcome with reason `verifyCmd required but not set`.
- Otherwise the branch is unchanged.

**Non-goals:** changing the default; the harness flag (P35-9 sets the setting in recipe mode).

**Acceptance:**
- With `requireVerify: true` and no `verifyCmd`, dispatch ends the task `failed` with that
  reason and no Reviewer hop runs.
- With `false`, the base behaviour (`verification_skipped`) is byte-identical.
- `docket pod <p> config explain` shows the key.

**RED:** the required-verify test in `tests/integration/test_dispatch.py` fails at the base
(task advances).

### P35-9 — `harness run --recipe`: a pipeline for an external caller

**Status:** TODO · **Size:** M · **Wave:** 74 · **Model:** Sonnet · **Spec:** the P35-9 stub in
`harness-mode.spec.md`

**Trigger:** ADR 0017 §3; the verdict table's "multi-role loop" row.

**Goal (v1.1 only):**
- **Arguments:** `--recipe NAME|DIR` is mutually exclusive with `--role`. With `--contract 1.0`
  it exits 2.
- **Execution:** `cli/_harness.py::_run` calls `core/harness_pipeline.py::run_recipe_task` with:
  - `approval_mode`: `wait` under `--answers stdin`, else `refuse`;
  - `requireVerify` set true on the ephemeral pod.
- **Result:** built through the P35-2 models:
  - `task` block: `status`, `hops` (role, stepId, ok, verdict, `verify`, `evidence`), `brief`;
  - `files` as in P35-6;
  - status mapping: task `done` → `ok`; `failed` → `failed`; a refused approval →
    `blocked`; `waiting_input` with no answer channel → `blocked`.
- **Answers:** `questionId` lines from P35-5's reader now route to
  `core.answers.answer_task` for the ephemeral pod's task.

**Non-goals:** new pipeline semantics; a second executor.

**Acceptance:**
- `docket harness run --contract 1.1 --recipe tdd --task-file t.md ...` against the scripted
  backend streams hop events and ends with a `task` block whose hops follow the recipe.
- A failing verify ends `failed` with that hop's `verify.exitCode`.
- The `intake` recipe's question, answered with a `questionId` line, reaches the Lead's re-entry.
- The emitted result validates against the v1.1 schema.

**RED:** the `--recipe` run test in `tests/integration/test_harness_cli.py` fails at the base.

### P35-10 — integrator: the consumer seam, a live run, doc corrections, close

**Status:** TODO · **Size:** M · **Wave:** 75 · **Model:** the integrating session · **Spec:**
every Phase 35 spec: version, status and changelog bumps

**Goal:**
- **Seam test:** `tests/integration/test_harness_v11_consumer.py` drives the real `docket
  harness run --contract 1.1` subprocess the way Tack does. Task from a file, then:
  - read `process_started`;
  - answer an approval on stdin;
  - read `files`;
  - run `--recipe`;
  - cancel with SIGTERM and see `process_exited`.

  Every line is validated against the **committed** v1.1 schema file.
- **Live run** against `127.0.0.1:8081` (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`): one `--recipe
  software` run and one `--answers stdin` run. Record the result lines in the ADR.
- **Doc corrections:**
  - ADR 0016 §6 (Tack does not poll);
  - `docs/SECURITY-SIMPLE.md` (notifications exist since Phase 34; only `bash` is jailed);
  - the stale comment in `core/orchestrator.py`;
  - `docs/DEVELOPMENT-HARNESS.md` and the harness section of `docs/DOCKET.md`;
  - `CHANGELOG.md`; the README sentence on harness mode (D-37: describe what is now true).
- **Handoff note** for Tack's M3: each of the four items `present`, with its commit.
- Spec bumps, rollups, `scripts/metrics.py --check`, board archive.

**Acceptance:** all gates green; the seam test fails when any one card's piece is reverted
(prove it once for the answer line and once for `files`).

## ◇ PLANNED — Phases 36–38 (D-51 follow-on; not claimable)

These are outlines, not cards. The integrator writes each phase's cards when it opens and
re-verifies every locator against the tree at that moment, because a gap list decays. Each
phase opens only after the previous one closes. The phase that reverses an earlier ADR records
that in its own ADR (ADR 0017 "What this reverses" lists them as not decided yet).

**Phase 36 — consultation and evidence packs (CRP v1, evidence-v1).** Opens after Phase 35.
- **operator-v1.1 contract.** `Question.kind` (`approval|clarification|decision`); `options[]`
  (`id`, `label`, `description`, `risks`, `estimatedTokens`); `recommendation` (`optionId`,
  `rationale`, `evidenceRefs[]`); `Answer.optionId`. Approval grant and deny gain `reason` and
  `actor` (closes the ADR 0016 §8 drift). JSON Schema under `docs/contracts/operator-v1.1/`.
- **A `consult` built-in tool for every role** (not only the Lead under `intake`). It requires
  options and a recommendation. Outcome by posture: `park` → `waiting_input`; harness
  `--answers stdin` → stdio; `refuse` → `blocked` with the pack in the result. Capped by
  `maxConsultationsPerTask` (the attention budget).
- **Approval packs.** A gated call carries the model's stated rationale (screened, truncated)
  and three options: approve once, approve for this task (a pre-grant), deny with reason.
- **A corrections ledger.** Deny reasons, `REQUEST-CHANGES` texts and declined answers go
  append-only to a per-pod `corrections.jsonl` (D-12 exemption shape); `docket pod <p>
  corrections`. This is the input for an external verifier's directive proposals.
- **evidence-v1.** A published schema of what P35-4 persists, plus per-hop measured tokens and
  trace ids. `docket pod <p> evidence <task> [--json]`; `GET /tasks/<p>/<id>/evidence`; the same
  block in harness v1.1 results.
- **Escalation metrics.** `docket_tasks_started_total`; `docket_questions_total{kind,outcome}`;
  `docket_decision_latency_seconds` from inbox transitions; `docket metrics --escalation`. Kept
  in measured tokens and seconds, never dollars.

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
