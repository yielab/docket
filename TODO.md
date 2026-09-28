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
> ## ▶ ACTIVE BOARD — WAVE 64 (Phase 34, D-50) · opened 2026-09-28
>
> **Seventeen cards over Waves 64–70**, one worker per card (Sonnet, or Haiku where the card
> says so) in an isolated worktree under one integrator. The work covers:
> - work that needs a human **parks** instead of blocking;
> - the Lead's intake asks before it builds;
> - one derived inbox;
> - notifications as CloudEvents through `kind: channel` documents;
> - questions in the MCP elicitation shape, and task states mapped onto A2A.
>
> Decision, standards and verdict table:
> [docs/adr/0016-operator-loop-and-interop-standards.md](docs/adr/0016-operator-loop-and-interop-standards.md).
> Worker packets: [.agents/handoffs/wave-64-worker-packets.md](.agents/handoffs/wave-64-worker-packets.md).
> **Wave 64 (P34-1..P34-4) is ready to claim.** Phase 34 closes when the Wave 70 rollup merges
> green.
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
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---

## ▶ WAVE 64 ACTIVE — Phase 34, the operator loop (D-50), Waves 64–70 (opened 2026-09-28)

**Opened 2026-09-28 at `0197e8b`.** Seventeen cards in seven waves. Decision, standards, cut and
deferred lists: [docs/adr/0016-operator-loop-and-interop-standards.md](docs/adr/0016-operator-loop-and-interop-standards.md).
Worker packets: [.agents/handoffs/wave-64-worker-packets.md](.agents/handoffs/wave-64-worker-packets.md).

**Trigger (explicit request plus facts read on the live path, 2026-09-28).** The operator asked
for five things:
- a Lead that reasons about a task before assigning it;
- clarifications as a short conversation with the human;
- approval as a separate flow;
- standard, intuitive notification (console, Telegram, email, phone; WhatsApp and Trello named);
- all of it usable by a variety of systems in a standard way.

Measured or read at `0197e8b`:
- the only four real approvals (2026-08-05) expired unanswered (`audit.log`,
  `channel=timeout` ×4);
- `serve.py::_run_sweeps` walks pods serially, so an in-turn `ask` stalls every pod for
  `TOOL_APPROVAL_TIMEOUT`;
- the Lead has `GateContract(kind="none")` and its prompt claims "human communication" that no
  path implements.

**Spec ownership rule (Phases 32–33 lesson).**
- A worker adds requirements under **its own new section heading**, numbered from 1 inside that
  section. It never touches `**Version**`, `**Status**`, `**Last Updated**` or the changelog: the
  integrator bumps each spec once per rollup.
- P34-2 creates `specs/functional/operator-loop.spec.md` with **every** later section heading
  already stubbed (`Status: Planned — owned by P34-N`). A later card replaces only its own stub,
  so no two cards append at the end of the same file.

**Standards (ADR 0016 §1), applied by every card.**
- A2A 1.0.0 `TaskState` names for `a2aState`.
- MCP elicitation (2025-06-18) shape for questions and answers.
- CloudEvents 1.0 structured JSON for events.
- Standard Webhooks headers and signing for the `webhook` dialect.
- JSON Schema 2020-12 under `docs/contracts/operator-v1/`.
- Event `type` = `dev.docket.<noun>.<verb>`; schema `$id` base
  `https://docket.dev/schemas/operator-v1/`.

**Test rule.**
- One RED behavioural test per card in the module's `SUBJECT` file.
- A second test only for the card's fail-closed negative case.
- No real model, no real vendor host: every HTTP target is a local `http.server` on port 0.
- Existing tests, goldens and specs are the no-change oracle, except where a card lists the
  change.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 64 | P34-1 ∥ P34-2 ∥ P34-3 ∥ P34-4 | `scripts/smoke_workflow.py` → P34-1; `core/operator_contract.py` (new), `scripts/gen_operator_schemas.py` (new), `docs/contracts/operator-v1/` (new), `specs/functional/operator-loop.spec.md` (new) → P34-2; `core/archetypes.py::_LEAD_BODY`, the Lead row of `docs/AGENT-TEAMS.md`, the two role-parity tests → P34-3; `cli/_pod.py::_pod_dispatch`, `_parse_dispatch_args`, `cli/_progress.py` (new), `specs/api/cli-interface.spec.md` → P34-4 |
| 65 | P34-5 ∥ P34-6 ∥ P34-7 | `core/tools.py::dispatch_tool` (ask branch) + `ToolContext`, `core/approval.py` (new `create_pregrant`, `consume_pregrant`, per-record `expiresAt`), `core/agent_loop.py` (`approval_parked` stop), `edges/adapters/docket_runtime.py` (env pops) → P34-5; `core/inbox.py` (new), `cli/_inbox.py` (new), one `inbox` stub in `cli/__init__.py`, `serve.py::do_GET` `/inbox` branch + metrics line, `cli/_mcp.py::tool_inbox`, `core/telegram.py` `/status` renderer → P34-6; `core/pipeline.py` (`InputSpec`, `Step.input`, validators, short form), `core/orchestrator.py` (plan render + temporary refusal), pipeline schema regen → P34-7 |
| 66 | P34-8 ∥ P34-9 | `core/dispatch.py` (`pod_approval_mode`, `_compose_hop`, `_execute_unit` parked outcome, resume position, `resolve_waiting_approval`, `dispatch_pod` signature), `core/pod.py` (`approvalMode`, `approvalExpiryHours`, `inputExpiryHours`), `serve.py::_run_sweeps` (one argument), `cli/_pod.py::_pod_dispatch` (one argument) → P34-8; `core/channel.py` (new), `templates/channels/` (new), `cli/_channels.py` (new), one `channels` stub in `cli/__init__.py`, `core/config.py` path constant, `core/config_docs.py::KINDS`, `scripts/gen_config_schemas.py::KINDS` → P34-9 |
| 67 | P34-10 ∥ P34-11 | `core/dispatch.py` (input-step execution, `waiting_input`, `_hop_message` answers section), `core/orchestrator.py` (remove the refusal), `core/answers.py` (new), `core/trace.py::EVENT_TYPES` (+2), `core/telemetry.py::_STRUCTURAL_KEYS` (+2), `serve.py::_run_sweeps` (question expiry call) → P34-10; `core/notify.py` (new), `edges/adapters/channels/` (new: `__init__`, `webhook`, `command`, `console`), `cli/_notify.py` (new), one `notify` stub in `cli/__init__.py`, `cli/_channels.py` (`test` subcommand), `serve.py::_run_sweeps` (flush call, after dispatch), `cli/_pod.py::_pod_dispatch` (flush call) → P34-11 |
| 68 | P34-12 ∥ P34-13 ∥ P34-14 | `core/handoff.py` (`TaskBrief` parse/render, `HandoffArtifact.brief`), `core/dispatch.py` (brief to Implementer, question from brief, resource check, `enqueue_task(brief=)`), `core/archetypes.py::_LEAD_BODY`, `templates/recipes/intake/` (new), `docs/recipes.md` regen → P34-12; `cli/_pod.py` (`answer`, `delegate --brief` in the `dispatch` table), `cli/_chat.py` (new), one `chat` stub in `cli/__init__.py`, `serve.py` (`POST /tasks/<id>/answer`, `brief` on `POST /tasks`), `cli/_mcp.py::tool_task_answer` → P34-13; `edges/adapters/channels/{ntfy,desktop,email}.py` (new) + three `sink_for` entries → P34-14 |
| 69 | P34-15 ∥ P34-16 | `core/interruptions.py` (new), `cli/_pod.py` (`explain`, `pregrant` in the `dispatch` table, the `delegate` summary line), `serve.py` (`POST /tasks/<id>/pregrants`), `cli/_mcp.py::tool_task_pregrant` → P34-15; `core/telegram.py` (`/answer` verb), `edges/adapters/channels/telegram.py` (new) + one `sink_for` entry, `tests/integration/test_telegram_channel.py::TestInboundOnly` rewrite, `telegram-integration.spec.md` → P34-16 |
| 70 | P34-17 (integrator) | seam tests, scenario re-run (deterministic and live), docs, CI line, spec bumps, rollups, archive |

`cli/__init__.py::cmd_pod` sits exactly at the 150-line function-span ratchet. **No card adds a
line to it.** Pod subcommands are added to `cli/_pod.py::dispatch`'s table, and the integrator
reconciles the `cmd_pod` help text.

Every card follows the §"How to use this board" definition of done.

### P34-1 — the operator-loop scenario: the phase's measured baseline and oracle

**Status:** TODO · **Size:** M · **Wave:** 64 · **Model:** Sonnet · **Spec:** none (a tool, not
behaviour)

**Trigger:** the phase's claims are about time and loss (a stalled fleet, work lost to a
timeout, nobody told). Nothing measures them today.

**Goal:**
- `scripts/smoke_workflow.py --scenario operator-loop [--live-model] [--report PATH]`.
- Setup:
  - a throwaway `DOCKET_HOME` and two temp git codebases;
  - two pods, `alpha` and `beta`, provisioned through the real CLI;
  - the `prod-approval` recipe applied to `alpha`;
  - `beta`'s Implementer given `verifyCmd false`.
- Four tasks:
  - A1 on `alpha`: the scripted Implementer issues `git push origin main`, so it asks;
  - A2 on `alpha`: a deliberately ambiguous description;
  - B1 on `beta`: plain;
  - B2 on `beta`: verify fails.
- Environment: `TOOL_APPROVAL_TIMEOUT=3` and `APPROVAL_TIMEOUT=10`, so the run is fast.
- Run one real `docket serve --dispatch -i 1` sweep cycle until every task is terminal or
  waiting, then stop it.
- Write one JSON report:

  ```json
  {"scenario": "operator-loop", "mode": "deterministic|live", "sweepBlockedSeconds": 0.0,
   "tasks": {"<id>": {"pod": "", "status": "", "reason": ""}},
   "approvals": {"timeout": 0, "granted": 0, "denied": 0, "pending": 0},
   "eventsDelivered": 0, "leadAsked": false, "elapsedSeconds": 0.0}
  ```

  `sweepBlockedSeconds` = the start of beta's first hop minus the time of alpha's
  `approval_requested`, both read from the traces.
- Separately, find which test or script wrote the 200 `project=proj` approval entries into the
  real audit log on 2026-09-25. Report the root cause; fix it only if the fix is inside `tests/`
  and is a single isolation change.

**Non-goals:** asserting future behaviour; adding the scenario to CI; any change under `src/`.

**Acceptance:**
- The deterministic run finishes in under 90 s and reports the baseline:
  - A1 `failed` with a reason containing `approval timed out`;
  - `sweepBlockedSeconds >= 3`;
  - `leadAsked: false`;
  - `eventsDelivered: 0`.
- Two consecutive deterministic runs produce identical `tasks`.
- The real `$HOME/.docket/audit.log` size and mtime are unchanged by the run (the script
  asserts this).
- `--live-model` runs against `127.0.0.1:8081` with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` and
  writes a report. Its task outcomes may vary; the report is the evidence.

**RED:** before the change, `python scripts/smoke_workflow.py --scenario operator-loop` exits
non-zero with an unknown-scenario error.

**Docs:** return a one-line README/CONTRIBUTING mention for the integrator.

### P34-2 — the `operator-v1` contract: one model set, A2A mapping, elicitation shape, CloudEvents

**Status:** TODO · **Size:** M · **Wave:** 64 · **Model:** Sonnet (Haiku-capable: the packet
lists every field) · **Spec:** `specs/functional/operator-loop.spec.md` (new; creates every
section stub, fills §"Contract")

**Trigger:** ADR 0016 §1. Every later card, and every external consumer, needs one typed
vocabulary before any behaviour exists.

**Goal:**
- `core/operator_contract.py` (new; pure; imports only `pydantic`, `typing`, `hashlib`, `json`,
  `datetime`):
  - `A2A_STATES` and `a2a_state(status, blocked_reason=None, failure_kind=None) -> str`, exactly
    the ADR 0016 §3 table; unknown input raises `ValueError`.
  - `TaskBrief`.
  - `QuestionSchema`: an elicitation `requestedSchema` validator. It accepts a flat
    `{"type": "object", "properties": {...}, "required": [...]}` whose properties are `string`
    (formats `email`, `uri`, `date`, `date-time` only), `number`, `integer`, `boolean`, or a
    string `enum` with optional `enumNames`. It rejects nesting, arrays and any other format.
  - `Question`.
  - `AnswerResult` (`action: Literal["accept", "decline", "cancel"]`, `content: dict | None`)
    and `validate_answer(question, result)`.
  - `ApprovalView`, `TaskView` (carries `a2aState`), `InboxView`.
  - `CloudEvent` (`specversion` fixed `"1.0"`) and
    `make_event(kind, pod, subject, data, *, time) -> CloudEvent`, with a deterministic `id`
    and `datacontenttype: application/json`.
  - `EVENT_TYPES`: the seven ADR 0016 §7 types plus `dev.docket.channel.test`.
  - `canonical_args_digest(tool, args) -> str`: SHA-256 hex of
    `json.dumps({"tool": tool, "args": norm(args)}, sort_keys=True, separators=(",", ":"))`,
    where `norm` collapses runs of whitespace inside string values (`" ".join(s.split())`)
    recursively.
- `scripts/gen_operator_schemas.py [--check]` renders
  `docs/contracts/operator-v1/{task,question,answer,approval,inbox,brief,event}.schema.json`
  (JSON Schema 2020-12, `$id` under `https://docket.dev/schemas/operator-v1/`), modelled on
  `scripts/gen_config_schemas.py`.
- The spec file with the header block and these sections, the later ones stubbed:
  1. Contract (P34-2)
  2. Inbox (P34-6)
  3. Answers (P34-10)
  4. Answer surfaces (P34-13)
  5. Channels (P34-9)
  6. Operator events and delivery (P34-11)
  7. Dialects (P34-11, P34-14)
  8. Telegram as a channel (P34-16)
  9. Interruption forecast (P34-15)

**Non-goals:** any caller; any change to existing modules; CI wiring (the integrator).

**Acceptance:**
- `a2a_state` covers every row of ADR 0016 §3 in a table-driven test.
- A nested `requestedSchema` is rejected.
- `validate_answer` rejects `accept` without a required property and accepts `decline` with no
  content.
- `canonical_args_digest("bash", {"command": "git  push   origin main"})` equals the digest of
  `"git push origin main"`, and argument key order does not matter.
- `make_event` output validates against `event.schema.json`, with `type` beginning `dev.docket.`.
- `gen_operator_schemas.py --check` passes after generation and fails after hand-editing a
  schema.
- `bash scripts/validate-specs.sh` passes with the new spec.

**RED:** `tests/unit/core/test_operator_contract.py` (`SUBJECT = "docket.core.operator_contract"`)
fails on import at the base.

### P34-3 — the Lead stops promising human communication it does not have

**Status:** TODO · **Size:** S · **Wave:** 64 · **Model:** Haiku · **Spec:**
`role-archetypes.spec.md`, only where the Lead body is quoted (`rg -n "human" specs/functional/role-archetypes.spec.md`)

**Trigger:** `core/archetypes.py::_LEAD_BODY` says "You own the pod's context, memory, and
human communication" and "Surface architectural decisions and risky actions to the human
(HITL)"; `docs/AGENT-TEAMS.md`'s roles table says the Lead "owns … human (Telegram) comms". No
path implements either (ADR 0016 evidence). This is the unwired-capability shape: a false
statement to the model and to the reader.

**Goal:**
- In `_LEAD_BODY`, replace exactly those two lines with:

  ```text
  - You own the pod's context and memory. You cannot message the human directly.
  - When a decision or a risky action needs the human, say so at the top of your plan: list every assumption and every open question.
  ```

- In `docs/AGENT-TEAMS.md`, the Lead row's third cell becomes: "Orchestrates the pod, owns its
  context and memory, decomposes work into a plan for the workers".
- Update the expected text in `tests/integration/test_pod_role_workspace_parity.py` and
  `tests/integration/test_legacy_role_parity.py`, and any golden case that embeds a Lead
  `SOUL.md`.
- Explain every changed line: the old string was factually false, the one allowed reason (board
  rule 4).

**Non-goals:** any other role body; the intake wording (P34-12 amends this body again).

**Acceptance:** `rg -n "human communication|human \(Telegram\)" src docs` returns nothing;
parity and golden suites pass with only the listed lines changed.

**RED:** after editing only `_LEAD_BODY`, the parity test fails on exactly the two lines. That
proves it pins the text. Then update the expectation.

### P34-4 — foreground dispatch shows what it waits for, and asks in place on a TTY

**Status:** TODO · **Size:** M · **Wave:** 64 · **Model:** Sonnet · **Spec:**
`specs/api/cli-interface.spec.md` new section "Foreground dispatch progress and in-place
approval"

**Trigger:** `cli/_pod.py::_pod_dispatch` is silent while a hop blocks on an in-turn approval for
`TOOL_APPROVAL_TIMEOUT`. The operator needs a second terminal and must already know the token.

**Goal:**
- When stderr is a TTY (or `--progress`), `_pod_dispatch` runs `dispatch_pod` in a worker
  thread. A `trace.subscribe` sink only enqueues events; the main thread renders one stderr
  line per:
  - `session_start` (`▶ <role> …`);
  - `approval_requested` (`⏸ <role> wants: <action> · token <t> · denies in <n>s ·
    docket approve <t>`);
  - `approval_required` (the hop-level gate);
  - `session_end`.
- When stdin is also a TTY and `--no-prompt` is absent, an `approval_requested` event prompts
  `[a]pprove  [d]eny  [Enter] keep waiting`. `a` calls
  `core.approval.approval_grant(token, channel="cli")` then
  `core.dispatch.resolve_waiting_approval`; `d` denies. The blocked hop's own poll picks up the
  decision.
- The rendering and parsing are pure functions in `cli/_progress.py` (new).
- `docket pipeline run` inherits this: it calls `_pod_dispatch`.

**Non-goals:** a park option in the prompt (P34-8 adds it); any `core/` change; output when
stderr is not a TTY.

**Acceptance:**
- With stdin and stderr faked as TTYs, a scripted backend whose Implementer calls a gated
  `bash` command, and the input `a\n`: the command executes once, and the audit log holds
  `approval.grant … channel=cli`.
- With input `d\n`: the hop reports `approval_denied`.
- Without a TTY: stdout and stderr are byte-identical to the base (goldens unchanged).

**RED:** the TTY-faked test in `tests/unit/cli/test_pod.py` fails at the base (no prompt, the
wait times out).

### P34-5 — the chokepoint parks a call and honours single-use pre-grants

**Status:** TODO · **Size:** M · **Wave:** 65 · **Model:** Sonnet · **Spec:**
`security-gates.spec.md` new section "Parked calls and single-use pre-grants";
`agent-loop.spec.md` new section "The approval_parked stop"

**Trigger:** ADR 0016 §2. A `park` posture needs the chokepoint to record the exact call and end
the turn without waiting. A grant needs a way to let exactly that call through once.

**Goal:**
- `ToolContext.approval_mode: Literal["wait", "park", "refuse"]`.
- `ToolContext.pregrants: tuple[Pregrant, ...] = ()`, where `Pregrant` is `(token, tool,
  args_digest)`.
- `ToolContext.approval_expires_at: str | None = None` (ISO). A parked record carries it as
  `expiresAt` when set.
- In `dispatch_tool`'s `ask` branch, **first**: if a pre-grant matches `(tool.name,
  canonical_args_digest(tool.name, args))` and `core.approval.consume_pregrant(token)` returns
  `True`, allow with reason `pre-granted (token=<t>)`.
- Under `park`:
  - `approval_create(..., context={"tool", "argsDigest", "callId", "parked": True})`;
  - return `decision="deny"`, `denial_kind="approval_parked"`, and the token on the result;
  - no wait.
- `core/approval.py`:
  - `consume_pregrant(token) -> bool`: atomic through `store.read_modify_write`, sets
    `consumedAt`, audits `approval.consume`. A second call returns `False`.
  - `create_pregrant(project, role, tool, args_digest, *, task_id, expires_at, channel, actor)
    -> str`: a record born `granted`, with context `{"kind": "pregrant", ...}`, audited
    `approval.pregrant`.
  - Every record may carry `expiresAt`. The expiry sweep honours it when present and falls back
    to `APPROVAL_TIMEOUT` otherwise.
- `core/agent_loop.py`: the loop stops on `approval_parked` exactly as it stops on
  `approval_unavailable`. Add `approval_parked_error(result) -> str` beside
  `approval_unavailable_error`: one function owns the format (the W30 seam rule).
- `edges/adapters/docket_runtime.py`: pop `DOCKET_PREGRANTS` (JSON list) and
  `DOCKET_APPROVAL_EXPIRES_AT` (ISO) from the tool env dict exactly as `DOCKET_APPROVAL_MODE`
  is popped, into `ToolContext.pregrants` and `ToolContext.approval_expires_at`. Both constants
  are new in `core/runtime_driver.py`.

**Non-goals:** anything in `core/dispatch.py`; the defaults; harness mode (it stays `refuse`).

**Acceptance:**
- Under `park`, a gated call returns in under 1 s (with `TOOL_APPROVAL_TIMEOUT=60`), the handler
  is never called, and exactly one pending record carries the digest.
- With a matching pre-grant, the handler runs once; an identical second call asks again; a call
  with a different argument asks.
- A pre-grant whose `expiresAt` is past is swept to `denied` and never consumed.
- The AST chokepoint test is unchanged and green.

**RED:** the `park` case in `tests/unit/core/test_tools.py` fails at the base (`Literal`
rejects `park`, or the call waits).

### P34-6 — one derived inbox for the whole fleet

**Status:** TODO · **Size:** M · **Wave:** 65 · **Model:** Sonnet · **Spec:** operator-loop
§"Inbox"; `specs/data/serve-read-api.spec.md` new section "GET /inbox";
`specs/api/mcp-server.spec.md` (tool `inbox`); `telegram-integration.spec.md` requirement 3
amended (same scope, new renderer)

**Trigger:** ADR 0016 §6. What needs the operator is spread over four commands, one pod at a
time.

**Goal:**
- `core/inbox.py::build_inbox(*, now, since=None) -> InboxView`. It is pure over:
  - every pod's task list (`core.dispatch.read_tasks` for every provisioned pod, paused
    included);
  - `core.approval.list_pending()`;
  - running runs.

  Sections:
  - `needsYou`: every `waiting_*` status (future-proof: any status starting `waiting_`), every
    `blocked` task, and every pending approval not attached to a task;
  - `failed`;
  - `doneSince`: terminal after `since`;
  - `running`.

  Every item is a `TaskView` or `ApprovalView` with `a2aState`. `next` is the maximum
  timestamp seen.
- `docket inbox [--json] [--since C] [--peek]`: without `--peek`, advances a cursor stored in
  `~/.docket/inbox-cursor.json` through `edges/store.py`.
- `GET /inbox?since=C` (Bearer, like `/approvals`).
- MCP `inbox(since=None)`.
- Telegram `/status` renders from `build_inbox`, filtered to the bound project (requirement 3
  intact).
- `/metrics` gains `docket_inbox_items{section}`.

**Non-goals:** notifications; answering; per-consumer cursors on the server.

**Acceptance:**
- A fixture with two pods (tasks in `pending`, `running`, `waiting_approval`, `blocked`,
  `failed`, `done`, and one status `waiting_input` written by hand) and one pending approval
  yields exactly the expected sections, and each item's `a2aState` matches ADR 0016 §3.
- A second `docket inbox` shows no `doneSince` items.
- `GET /inbox` JSON equals `docket inbox --json` for the same state.
- `/status` output for a bound pod lists only that pod.

**RED:** `tests/unit/core/test_inbox.py` fails on import at the base.

### P34-7 — the pipeline format gains an `input` step (format only)

**Status:** TODO · **Size:** S · **Wave:** 65 · **Model:** Haiku · **Spec:**
`pipeline-format.spec.md` new section "Input steps"

**Trigger:** ADR 0016 §4. A question is a pipeline step, so a team declares when it may be
asked, in YAML.

**Goal:**
- `core/pipeline.py`:
  - `InputSpec(extra="forbid")`: `from_` (alias `from`, required), `message: str = ""`,
    `expiresHours: int | None` (`> 0`).
  - `Step.input: InputSpec | None`, exclusive with `role`, `agent`, `run`, `parallel`, `gate`,
    `retries`, `timeout`, `instructions` and `model`.
  - `PipelineSpec` validates that `from` names an **earlier** step id.
  - An input step's `on` may use only the labels `answered` and `declined`.
  - The short form accepts `- ask: {input: {from: triage}}`.
- `docket pipeline plan` / `validate` render `ask ← asks the operator (from triage)`.
- `core/orchestrator.py`: building an executable plan that contains an input step raises the
  existing error type, with the message `input steps are not executable until P34-10 ships`.
  P34-10 deletes this refusal.
- Regenerate `docs/contracts/config-v1/pipeline.schema.json` (both copies) with
  `scripts/gen_config_schemas.py`.

**Non-goals:** execution; `waiting_input`; any change to `core/dispatch.py`.

**Acceptance:**
- The ADR 0016 §4 YAML validates.
- Each of these is rejected with an error string naming the dotted location: `input` together
  with `role`; a forward `from`; `on: {pass: …}` on an input step.
- `plan` renders the line above.
- `pod dispatch` on such a pipeline fails with the refusal message and leaves no task mutated.

**RED:** the valid-document test in `tests/unit/core/test_pipeline.py` fails at the base
(unknown key `input`).

### P34-8 — dispatch parks: `approvalMode: park`, caller defaults, expiry, re-entry with the pre-grant

**Status:** TODO · **Size:** L (the packet splits the work into two commits on one branch) ·
**Wave:** 66 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` "Unattended approval
posture" amended (item 5's default non-goal removed, `park` added) plus a new section "Parked
approvals"; the pod-settings keys wherever `approvalMode` is specified (`rg -n approvalMode
specs`)

**Trigger:** ADR 0016 §2, and the fleet stall in `serve.py::_run_sweeps`.

**Goal:**
- `core/pod.py`:
  - `approvalMode: Literal["wait", "park", "refuse"]`;
  - new keys `approvalExpiryHours` (int, default 24, `>= 1`) and `inputExpiryHours` (int,
    default 72, `>= 1`; read by P34-10);
  - "unset" is detected from the stored settings (`model_fields_set` or the raw record), never
    by changing a field default. `config explain` shows `approvalMode: (unset → park under
    serve and without a TTY, wait on a TTY)`.
- `core/dispatch.py`:
  - `pod_approval_mode(project, *, caller_default)` returns the pod value when set, else
    `caller_default`.
  - `dispatch_pod(..., approval_default: Literal["wait", "park"] = "wait")`.
  - `serve.py::_run_sweeps` passes `"park"`. `cli/_pod.py::_pod_dispatch` passes `"wait"`
    when `sys.stdin.isatty()`, else `"park"`.
  - `_compose_hop` sets `DOCKET_APPROVAL_MODE=park` as it does for `refuse`, and
    `DOCKET_PREGRANTS` from the task's `pregrants` list.
  - A hop whose turn stopped on `approval_parked` yields the existing `waiting_approval`
    outcome with the token and **its own** pipeline index. The parked hop is persisted with
    `parked: true`.
  - The resume-position builder re-runs a parked index instead of advancing past it.
  - `resolve_waiting_approval` on a grant of a parked record appends
    `{token, tool, argsDigest}` to the task's `pregrants` and returns it to `pending`.
  - `_compose_hop` also sets `DOCKET_APPROVAL_EXPIRES_AT = now + approvalExpiryHours`, so the
    parked record P34-5 creates carries its `expiresAt`.
- P34-4's prompt gains `[p]ark and continue` when the pod resolves to `wait` on a TTY. It
  flips the in-flight wait into a deny with `denial_kind="approval_parked"` through the
  existing cancellation seam, and the task parks.

**Non-goals:** questions; notifications; one worker per pod in the sweep (deferred, ADR 0016).

**Acceptance (scripted backend):**
- Under `park`:
  - the Implementer's gated `git push origin main` leaves the task `waiting_approval` in under
    1 s;
  - `docket approve <t>` then `docket pod <p> dispatch` executes that exact command once and
    reaches `done`;
  - a deny fails the task `approval_denied`;
  - an `expiresAt` in the past plus a sweep also fails it.
- Two pods in one `serve` sweep: pod A parks and pod B's task still runs in the same sweep (the
  P34-1 scenario's `sweepBlockedSeconds` drops below 1).
- A pod with no `approvalMode` dispatched from a TTY still waits, and its goldens are unchanged.

**RED:** the parked-dispatch test in `tests/integration/test_dispatch.py` fails at the base
(`approvalMode` rejects `park`).

### P34-9 — `kind: channel` documents, catalog and CLI

**Status:** TODO · **Size:** M · **Wave:** 66 · **Model:** Sonnet · **Spec:** operator-loop
§"Channels"; `config-format.spec.md` (the `channel` kind)

**Trigger:** ADR 0016 §7. Destinations are configuration, shaped like providers and exporters.

**Goal:**
- `core/channel.py` (new), modelled on `core/exporter.py`.
- `ChannelSpec`:
  - `kind: Literal["channel"]`, `name`, `description`;
  - `dialect: Literal["console", "desktop", "webhook", "command", "ntfy", "email", "telegram"]`;
  - `enabled: bool = False`;
  - `capabilities: list[Literal["notify", "converse", "decide"]]`;
  - `on: list[str]` (the ADR 0016 §7 type suffixes, plus the shorthand `needs_you`);
  - `content: Literal["minimal", "actions", "conversation"] = "minimal"`;
  - `actors: list[str]`;
  - `config: dict[str, str]`;
  - `secret: str | None` (a credential **name**, validated like exporter credential names).
- Validation:
  - `capabilities` ⊆ `DIALECT_MAX[dialect]`: `console` = decide; `telegram` = decide;
    `desktop`, `webhook`, `command`, `ntfy`, `email` = notify;
  - `decide` or `converse` requires non-empty `actors`, except `console`.
- Catalog: built-ins `templates/channels/01-console.yaml` … `07-telegram.yaml` (only `console`
  enabled); global `docket-channels.json` (a new `config.py` path) through `edges/store.py`;
  nearest wins.
- `docket channels list|show|enable [--set k=v]|disable|add <file>|remove|export|content <name>
  <level> [--yes]`. Widening `content` requires a TTY confirmation or `--yes` and is audited
  (`channel.content`), exactly like `docket exporters privacy`.
- `docket validate` accepts `kind: channel`.
- `docs/contracts/config-v1/channel.schema.json` is generated.

**Non-goals:** delivery (P34-11); `channels test` (P34-11); per-pod channel selection
(deferred: a second pod needing a different destination).

**Acceptance:**
- The catalog lists seven built-ins, only `console` enabled.
- An `email` document with `decide` is rejected with an error naming the dialect's maximum.
- A `telegram` document with `decide` and no `actors` is rejected.
- `enable ntfy --set topic=x` persists and `show` reflects it.
- `content ntfy actions` off a TTY without `--yes` exits non-zero and writes nothing.
- `gen_config_schemas.py --check` passes.

**RED:** `tests/unit/core/test_channel.py` fails on import at the base.

### P34-10 — questions execute: `waiting_input`, `answer_task`, expiry to `blocked`

**Status:** TODO · **Size:** L · **Wave:** 67 (after P34-7 and P34-8) · **Model:** Sonnet ·
**Spec:** `pod-dispatch.spec.md` "Task status vocabulary" item 7 plus a new section "Input steps
and waiting_input"; operator-loop §"Answers"; `trace-store.spec.md` (two event types)

**Trigger:** ADR 0016 §3–4. The Lead has no way to ask.

**Goal:**
- `core/dispatch.py::_run_pipeline` gains an input-step branch, and P34-7's refusal is removed.
  - With no unconsumed answer for this step, it builds a `Question`:
    - `message` = the step's `message`, else the `from` step's latest hop output (at most
      2,000 chars);
    - `requestedSchema` = `{"type": "object", "properties": {"answer": {"type": "string",
      "title": "Answer"}}, "required": ["answer"]}`;
    - `expiresAt` from `inputExpiryHours` or the step's `expiresHours`.

    It persists the question on the task, sets `waiting_input` and `pendingInputIndex`, and
    traces `input_requested` with `{task, step, questionId}` only.
  - With an unconsumed answer, it marks the answer consumed and persists a synthetic
    `operator` hop carrying `next_step`, so the route counts survive a resume. It then routes
    `answered` (`accept`) or `declined` (`decline`/`cancel`) through the step's `on`. An
    unrouted `answered` advances; an unrouted `declined` fails with `operator declined`.
- `core/answers.py::answer_task(project, task_id, result, *, channel, actor) -> TaskView`:
  - requires `waiting_input`;
  - calls `validate_answer`;
  - screens every string through the same `pre_input` evaluation `/delegate` uses;
  - appends to `answers[]` and sets the task `pending`;
  - audits `task.answer`;
  - traces `input_answered`.
- `core/answers.py::sweep_expired_questions(now)` turns an expired `waiting_input` into
  `blocked` with `blockedReason: input_expired`. `serve.py::_run_sweeps` calls it next to the
  approval sweep.
- `_hop_message`: the Lead branch and the Implementer branch gain an `## Operator answers`
  section: every Q/A pair, bounded to 4,000 chars with the existing truncation marker.
- `core/trace.py::EVENT_TYPES` += `input_requested`, `input_answered`.
  `core/telemetry.py::_STRUCTURAL_KEYS` gets their structural keys only. Question text never
  becomes a structural attribute.

**Non-goals:** CLI, HTTP and MCP surfaces (P34-13); the brief (P34-12); notifications.

**Acceptance (scripted backend; pipeline `triage: lead` with verdict `[READY, NEEDS-INPUT]`,
`ask: input from triage`, `build: implementer`):**
- The first dispatch leaves `waiting_input`, with the Lead's text as the question.
- `answer_task(accept, {"answer": "per account"})` returns the task to pending. The next
  dispatch's Lead message contains `per account`. The Lead replies `READY`, the Implementer
  runs, and the task reaches `done`.
- With `max: 1` and the Lead asking twice, the task fails `exhausted its routing budget`.
- An expired question becomes `blocked`/`input_expired`, **never** `failed`.
- An answer matching a `pre_input` block policy raises and leaves the task `waiting_input`.

**RED:** the first-dispatch test in `tests/integration/test_dispatch.py` fails at the base
(P34-7's refusal).

### P34-11 — operator events: derived from inbox transitions, delivered by channels (webhook, command)

**Status:** TODO · **Size:** L · **Wave:** 67 · **Model:** Sonnet · **Spec:** operator-loop
§"Operator events and delivery" and §"Dialects" (webhook, command, console)

**Trigger:** ADR 0016 §7. Nobody is told.

**Goal:**
- `core/notify.py`:
  - `diff_events(prev, inbox, now) -> (events, snapshot)` is pure. It emits one CloudEvent per
    new `needsYou`/`failed`/`doneSince` item, plus `approval.expiring` once per approval at 80 %
    of its life. Event ids are deterministic: SHA-256 of type, subject and the item's version
    token.
  - `render_data(item, level)` enforces the content levels:
    - `minimal` = `pod`, `taskId`, `role`, `reasonCode`, `token` or `questionId`, `expiresAt`,
      and `respond: {cli, http}`;
    - `actions` adds `action` (the rendered command);
    - `conversation` adds `question` and `brief`.
  - `render_text(event) -> (title, body)` feeds text dialects.
  - `flush(specs, sink_for, *, now) -> FlushReport`: loads and saves `notify-state.json` and
    `channels-health.json` through `edges/store.py`; delivers to every enabled channel with
    `notify` whose `on` matches; 5 s per delivery, 2 retries; never raises.
- `edges/adapters/channels/`:
  - `sink_for(spec)`;
  - `webhook.py`: POST `application/cloudevents+json` with the Standard Webhooks headers:
    - `webhook-id` = the event id;
    - `webhook-timestamp` = unix seconds;
    - `webhook-signature` = `v1,` + base64(HMAC-SHA256(key, f"{id}.{ts}.{body}")), where `key`
      is the base64-decoded part of a `whsec_…` secret read by name through
      `core.secrets.secret_value`;
  - `command.py`: runs an operator binary with an argv list and the event JSON on stdin, 10 s
    timeout;
  - `console.py`: no-op (the console *is* the inbox).
- Wiring:
  - `serve.py::_run_sweeps` calls `flush` after dispatch;
  - `cli/_pod.py::_pod_dispatch` calls `flush` once at the end;
  - `docket notify flush [--dry-run]` (new) prints what would be sent;
  - `docket channels test <name>` sends one `dev.docket.channel.test` event.

**Non-goals:** ntfy, desktop, email (P34-14); Telegram (P34-16); any receipt of answers.

**Acceptance:**
- Two flushes over the same state deliver once (dedupe).
- A new parked approval yields exactly one `dev.docket.approval.requested`.
- **Canary:** a `minimal` event's JSON contains neither the parked command string nor the
  question text; at `actions` it contains the command.
- A local `http.server` receives the POST. The test recomputes the signature from a known
  `whsec_` secret and it matches; `webhook-id` equals the CloudEvent `id`.
- A dead port records an error in `channels-health.json` and returns within the timeout
  without raising.

**RED:** `tests/unit/core/test_notify.py` fails on import at the base.

### P34-12 — the Lead's intake: `TaskBrief`, the `intake` recipe, resource checks, the brief reaches the Implementer

**Status:** TODO · **Size:** L · **Wave:** 68 (after P34-10) · **Model:** Sonnet · **Spec:**
`pod-dispatch.spec.md` new section "Task brief"; `role-archetypes.spec.md` (Lead body);
`docs/recipes.md` regenerated

**Trigger:** ADR 0016 §4. The Implementer gets free prose; the Lead cannot declare a task not
ready or name what is missing.

**Goal:**
- `core/handoff.py`: `parse_brief(text) -> TaskBrief | None` reads the **last** fenced
  `json` block that validates as `TaskBrief`. `render_brief(brief) -> str` renders the fields
  in a fixed order. `HandoffArtifact.brief: TaskBrief | None`.
- `core/dispatch.py`:
  - a hop whose output carries a brief sets `artifact.brief`;
  - the Implementer's message renders `## Brief` from the latest brief in place of the Lead's
    summary;
  - an input step whose `from` hop has `brief.questions` builds a `requestedSchema` with one
    string property per question (`q1`…`qn`, `title` = the question) and the message `The
    Lead needs answers before starting: <objective>`;
  - after a `READY` verdict carrying a brief, `_check_brief_resources(project, brief)` checks
    `secret:<NAME>` against `core.secrets.secrets_keys()`, `path:<p>` for existence, and
    `verify` for the Implementer's `verifyCmd`. Anything missing ends the task `blocked` with
    `blockedReason: resources` and a reason naming each item, without another turn;
  - `enqueue_task(..., brief: dict | None = None)` validates and stores a pre-brief, which the
    Lead's message then includes.
- `templates/recipes/intake/`:
  - `pipeline.yaml`: the ADR 0016 §4 pipeline, with the Lead step's `instructions` telling it
    to end with one `json` fenced `TaskBrief` and then one marker line `READY`, `NEEDS-INPUT`
    or `REJECT`;
  - `pod.yaml` with `description`;
  - `README.md` in the recipes convention.
- `REJECT` routes to `fail` with `failureKind: rejected` (`a2aState` `REJECTED`).
- `_LEAD_BODY` gains, after P34-3's lines:

  ```text
  - If your pod's pipeline has an intake step, your questions reach the human through it: list them in your brief and end with NEEDS-INPUT.
  ```

  Parity tests are updated with the reason.
- `scripts/gen_recipe_docs.py` regenerates `docs/recipes.md`.

**Non-goals:** making `intake` the `software` default (deferred with trigger); surfaces
(P34-13); pre-grants (P34-15).

**Acceptance (scripted backend, `pod apply intake`):**
- The Lead emits a brief with two questions and `NEEDS-INPUT`: the question has properties `q1`
  and `q2`. After both are answered, the Lead emits `READY`, and the Implementer's message
  contains `## Brief` with the acceptance items and not the Lead's prose preamble.
- A brief naming `secret:MISSING_KEY` blocks with `resources`; the task view shows
  `AUTH_REQUIRED`.
- A reply with no parseable brief but a `READY` marker still advances: the brief is optional,
  and the verdict rule is unchanged.
- `REJECT` fails the task as `rejected`.

**RED:** the brief-reaches-Implementer test in `tests/integration/test_dispatch.py` fails at
the base.

### P34-13 — answer surfaces: CLI, `docket chat`, HTTP, MCP, pre-brief on delegate

**Status:** TODO · **Size:** M · **Wave:** 68 (after P34-10) · **Model:** Sonnet · **Spec:**
operator-loop §"Answer surfaces"; `serve-read-api.spec.md` new section "POST
/tasks/<id>/answer"; `mcp-server.spec.md` (`task_answer`); `cli-interface.spec.md` (`pod
answer`, `chat`, `delegate --brief`)

**Trigger:** ADR 0016 §8. `answer_task` has no caller.

**Goal:**
- `docket pod <p> answer <task> [TEXT] [--field k=v]... [--decline]`. A bare `TEXT` fills the
  single property of a one-property schema.
- `docket chat <task> [--pod p]` shows the question, the brief, earlier answers and any
  `expectedRiskyActions`. On a TTY it prompts for each property and calls `answer_task` with
  `channel="cli"` and `actor=<OS user>`.
- `docket pod <p> delegate --brief FILE.json`.
- `POST /tasks/<id>/answer`, body `{"pod": "...", "action": ..., "content": {...}}` (the
  elicitation result). It returns the `TaskView`; 409 when not `waiting_input`; 422 on schema
  or screen failure.
- `POST /tasks` accepts `brief`.
- MCP `task_answer(project, task_id, action, content)`.

**Non-goals:** Telegram (P34-16); notifications.

**Acceptance:**
- Each surface answers the same fixture task and leaves identical `answers[]` entries except
  `channel`.
- The HTTP 409 and 422 paths leave the task unchanged.
- `delegate --brief` with an invalid brief exits non-zero and enqueues nothing.

**RED:** the HTTP answer test (the pattern in the existing serve tests) returns 404 at the base.

### P34-14 — ntfy, desktop and email dialects

**Status:** TODO · **Size:** S · **Wave:** 68 (after P34-11) · **Model:** Haiku · **Spec:**
operator-loop §"Dialects" (ntfy, desktop, email)

**Trigger:** ADR 0016 §7. The phone, the desktop and the mailbox are where an operator already
looks.

**Goal:** three sinks in `edges/adapters/channels/`, registered in `sink_for`, each built from
`core.notify.render_text`:
- `ntfy.py`: POST the plain-text body to `{config.server or "https://ntfy.sh"}/{config.topic}`
  with headers `Title` and `Priority` (`high` for a needs-you type, else `default`), plus
  `Authorization: Bearer <secret>` when `secret` is set.
- `desktop.py`: `notify-send <title> <body>` on Linux, `osascript -e 'display notification …'`
  on macOS, always with an argv list and never a shell; a missing binary is a silent no-op
  recorded in health.
- `email.py`: `smtplib.SMTP(host, port or 587)` with STARTTLS, login with `config.user` and the
  secret, subject `[docket] <title>`, plain-text body. It never reads mail and can never decide
  (P34-9 already enforces that).

**Non-goals:** IMAP; HTML mail; any inbound path.

**Acceptance:**
- A local `http.server` receives the ntfy POST with the expected headers and body.
- A fake `notify-send` on a temporary `PATH` records its argv.
- A monkeypatched `smtplib.SMTP` records `starttls`, `login` and one `send_message` with the
  subject.
- A `minimal` body contains no command text (canary).

**RED:** `tests/unit/edges/test_channel_dialects.py` fails on import at the base (create the
file; it is named by this card).

### P34-15 — see it coming: `explain interruptions`, and pre-grants from the intake

**Status:** TODO · **Size:** M · **Wave:** 69 · **Model:** Sonnet · **Spec:** operator-loop
§"Interruption forecast"; `pod-dispatch.spec.md` new section "Pre-grants from intake"

**Trigger:** ADR 0016 §10. The operator cannot know before delegating what may stop a task, and
cannot answer an expected approval while already engaged.

**Goal:**
- `core/interruptions.py::forecast(project, *, caller_default) -> list[Interruption]`, derived
  from:
  - effective policies whose action is `require_approval` (with their pattern or predicate);
  - the classifier's high-risk classes;
  - the pipeline's `approval` and `input` steps;
  - `requireApprovalRoles`;
  - the resolved `approvalMode`;
  - both expiries;
  - enabled channels that can notify.
- `docket pod <p> explain interruptions [--json]` prints it. On a pod with nothing that can
  ask, it prints `Nothing in this pod will ask you.`
- `delegate` prints one summary line, `May ask you: …`.
- `docket pod <p> pregrant <task> "<command>" [--tool bash]`, `POST /tasks/<id>/pregrants` and
  MCP `task_pregrant`:
  - call `create_pregrant` with `canonical_args_digest(tool, {"command": command})`, an expiry
    of `approvalExpiryHours`, the channel and the actor;
  - append the pre-grant to the task's `pregrants`.
- `docket chat` prints the suggested `pregrant` command for each of the brief's
  `expectedRiskyActions`.

**Non-goals:** fuzzy matching (the exact-after-whitespace limit is stated in the spec and the
help text).

**Acceptance:**
- With `prod-approval` applied, `explain interruptions` lists its patterns and the park
  posture.
- A pre-granted `git push origin main` executes once during dispatch with no new pending
  record. `git push origin main --force` asks.
- A pre-grant on a task in another pod is refused.

**RED:** the pre-granted-dispatch test fails at the base (no `pregrant` subcommand).

### P34-16 — Telegram becomes a channel: minimal pushes and `/answer` (Command grammar 7 amended)

**Status:** TODO · **Size:** M · **Wave:** 69 · **Model:** Sonnet · **Spec:**
`telegram-integration.spec.md`: requirements 7 and 8 and the Non-goals amended per ADR 0016
§9, plus a new section "As a channel"

**Trigger:** ADR 0016 §9. The operator named Telegram; the bot is already bound and trusted to
decide.

**Goal:**
- `edges/adapters/channels/telegram.py`: a sink that sends `render_text` at the channel's
  content level to every chat bound to an actor in `actors`, through the existing
  `edges/adapters/telegram.py::send_message`.
- `core/telegram.py`: a fifth verb, `/answer <task-id> <text>`. It goes through the same
  `_authorize`, then calls `answer_task(..., channel="telegram", actor=<chat id>)`, whose
  `pre_input` screen applies. The reply is `answered; <task-id> resumes on the next dispatch`.
- `/approve` and `/deny` are unchanged.
- Rewrite `TestInboundOnly` in the same commit, as `TestOutboundOnlyThroughTheChannel`: an AST
  walk over `src/` finds exactly two `send_message` call sites, the reply inside `poll_once`
  and the channel sink.

**Non-goals:** reply-to-message threading (deferred); inline keyboards (cut); free text.

**Acceptance:**
- With a fake `send_message`, a parked approval's flush sends one message to the bound chat
  whose text lacks the command at `minimal` (canary).
- `/answer` from an unbound chat is refused and nothing changes.
- `/answer t-1 per account` resumes a `waiting_input` task.
- The rewritten AST test fails if a third call site is added (proven by a throwaway local edit
  that is not committed).

**RED:** the `/answer` test in `tests/integration/test_telegram_channel.py` fails at the base
(unknown verb).

### P34-17 — integrator: seams, the scenario again, docs, close

**Status:** TODO · **Size:** M · **Wave:** 70 · **Model:** integrator · **Spec:** every
touched spec bumped once, `specs/README.md` index

**Goal:**
- **Seam tests** in `tests/integration/test_operator_loop_seams.py`, using the real producers
  and consumers:
  - park (P34-5/8) → inbox (P34-6) → flush (P34-11) → `POST /approvals` → resume;
  - intake question (P34-10/12) → webhook event (P34-11) → `POST /tasks/<id>/answer` (P34-13)
    → resume;
  - Telegram `/answer` (P34-16) → the same resume.
- **Scenario:** `smoke_workflow.py --scenario operator-loop` re-run deterministic and live,
  extended so A2 runs under the `intake` recipe and a `webhook` channel points at a local
  receiver. Record the P34-1 baseline beside the new numbers in the roadmap changelog:
  `sweepBlockedSeconds` below 1, no task lost to `approval_timeout`, `leadAsked: true`,
  `eventsDelivered` ≥ 3.
- **Deferred triggers:** evaluate the live Lead-brief parse rate (the `intake`-default trigger)
  and the re-run-misses-granted-call rate (the mid-turn resume trigger). Record them; schedule
  nothing.
- **Docs:**
  - README: "The gate and the record" gets park, inbox and channels; the agent-lane prose tests
    are rebuilt from the README;
  - `docs/AGENT-TEAMS.md`: the intake and how the human is asked;
  - `docs/SECURITY-SIMPLE.md`: capability tiers, email never decides, the Telegram amendment;
  - `docs/CONFIGURATION.md`: channel documents and the three pod keys;
  - `docs/QUICK-START-DOCKET.md`: `docket inbox`;
  - `docs/contracts/operator-v1/README.md`: the standards map and the A2A table;
  - `CHANGELOG.md`.
- CI docs job: add `gen_operator_schemas.py --check`. Run `metrics.py --check`. Archive the
  board with `split_board.py`.
