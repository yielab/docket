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
> ## ▶ ACTIVE BOARD — Wave 82–84 (Phase 37, verification-ready execution)
>
> **Phase 37 opened 2026-10-04** (ROADMAP D-54,
> [ADR 0019](docs/adr/0019-verification-ready-execution.md)): eight cards over Waves 82–84, below
> the usage guide. One worktree per task, screened MCP results, task coordinates for command
> steps, a `no_progress` stop, recipe-declared MCP servers, four check recipes and a
> code-intelligence pack.
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

## ▶ ACTIVE — Wave 82–84, Phase 37: verification-ready execution

**Opened 2026-10-04** (ROADMAP D-54, [ADR 0019](docs/adr/0019-verification-ready-execution.md)).
Every outline locator was re-verified at `9dd871f`. Two outline claims were false and are
corrected in ADR 0019:
- "recipes, no core change": a `run:` step gets no task id or base commit (P37-3);
- "an MCP pack as recipes": a recipe cannot declare an MCP server (P37-7).

Carried out of Phase 36, not scheduled here: the in-process consult registry, `approve_task`
scoped to one turn, the session key as `question.taskId` in a single-turn consult, and options
not rendered in Telegram or channel notifications (ADR 0018 "Cut and deferred").

**Workers.** Each card runs in an isolated worktree that is reset to `develop` before editing. The
worker diffs from `git merge-base`, commits on its branch, and never merges, pushes, stashes, or
edits `TODO.md`/`ROADMAP.md`/`CONTRIBUTING.md`/`README.md` counts. The integrator rebases, gates,
merges, and bumps spec versions. **`~/.docket` was wiped on 2026-10-04 and must not reappear**:
a test that creates it leaks into the real home and fails the card.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 82 | P37-1 ∥ P37-2 ∥ P37-3 ∥ P37-4 | `core/mcp_tools.py::_build_tool` (the handler), `mcp-client.spec.md` → P37-1; `core/pod_provisioning.py` (worktree provisioning and teardown), `core/pod.py::resolve_member_cwd`, `core/dispatch.py` claim, finalize, `_implementer_diff_probe`, `_prior_implementer_worktree`, `_when_cwd`, `workspace-structure.spec.md`, `pod-dispatch.spec.md` "Hop evidence" → P37-2; `core/dispatch.py::_run_command_step` plus one new helper, `edges/adapters/system.py::run_verify_cmd` (an `env` parameter), `pod-dispatch.spec.md` command-step section → P37-3; `core/agent_loop.py` (`StopReason`, `_TurnState`), `config.py` (one constant), `agent-loop.spec.md` → P37-4 |
| 83 | P37-5 ∥ P37-6 ∥ P37-7 | `templates/recipes/mutation/`, `templates/recipes/anti-tautology/` → P37-5; `templates/recipes/spec-writer/`, `templates/recipes/cross-family-review/` → P37-6; `core/pod_apply.py` (the `mcp-server` kind), `core/mcp_tools.py::load_mcp_servers` (pod scope), `core/pod.py::_parse_mcp_servers`, `templates/recipes/code-intel/`, `config-format.spec.md`, `mcp-client.spec.md` → P37-7 |
| 84 | P37-8 (integrator) | seam tests, live run, docs, spec bumps, rollup, archive |

`core/dispatch.py` is shared in Wave 82 at function level only: P37-2 must not touch
`_run_command_step`, and P37-3 reads the base commit from the prior hops' recorded evidence, never
from a worktree path. `docs/recipes.md` is regenerated by the integrator after Wave 83
(`scripts/gen_recipe_docs.py`).

Every card follows the §"How to use this board" definition of done.

### P37-1 — MCP tool results pass `pre_input`

**Status:** DONE `33377867` (audit `mcp_client.tool_result_blocked`/`_warn`; a failed call's error text is screened too) · **Size:** S · **Wave:** 82 · **Model:** Sonnet · **Spec:** `mcp-client.spec.md`

**Trigger:** `core/mcp_tools.py::_build_tool._handler` returns `call_tool(...)` unchanged, while
the same server's descriptions are screened (`_screen_description`).

**Goal:** the adapted tool's handler screens the result text with
`policy_eval_detail(ctx.role, "pre_input", text, trusted=False)`:
- `block`: `ToolOutcome(ok=False)` whose error names the policy and server, plus one audit entry;
- `redact`: the redacted text;
- `warn`: the text unchanged, plus one audit entry.

A result with no text passes as is.

**Non-goals:** built-in tool results; `fetch` (deferred in ADR 0019); description screening
(unchanged).

**Acceptance:**
- With a real baseline `pre_input` policy and a fake `call_tool` whose result carries an
  injection phrase, a live `dispatch_tool` call returns `ok=False` naming the policy.
- An audit entry names the server and tool.
- A clean result passes byte-identical.
- A redact policy returns the redacted text.

### P37-2 — one worktree per task

**Status:** DONE `f97380b0` (Lead stays on the codebase; in-place Implementers carry `inPlace`; the live smoke and doc-journey scripts still name the member `worktree/` -- P37-8) · **Size:** L · **Wave:** 82 · **Model:** Sonnet · **Spec:**
`workspace-structure.spec.md`, `pod-dispatch.spec.md` "Hop evidence"

**Trigger:** `_implementer_diff_probe` computes `baseCommit` as a merge-base with the codebase's
current branch, on a worktree that lives as long as the member. With nothing merged between
tasks, task 2's `diffStat` includes task 1's commits.

**Goal (ADR 0019 §1):**
- `docket add` no longer creates a worktree for a repo Implementer. The per-member worktree code
  path is deleted, with no fallback.
- At claim, dispatch creates `<member workspace>/tasks/<taskId>` on the branch
  `docket/<project>/<taskId>` from the codebase's HEAD. It records
  `task["worktree"] = {dir, branch, baseCommit}` through the existing task-list writer.
- Every hop, verify gate and `when`/command cwd of that task resolves to that directory. The
  re-entry of a parked task reuses it.
- Evidence `baseCommit` is the recorded commit, and `diffStat` is taken against it.
- Member removal removes its task worktrees and reports unmerged branches
  (`_teardown_worktree_branch`).
- When git is missing or `worktree add` fails, the task runs in place with a recorded reason, as
  the current fallback does.

**Non-goals:** merging branches; retention of finished worktrees; parallel tasks; harness
`--recipe` (in place by design, ADR 0017).

**Acceptance:**
- A real git repo and a scripted driver run two tasks back to back with nothing merged. Each task
  has its own branch and directory.
- Task 2's evidence `baseCommit` is its own creation commit, and its `diffStat` lists only task
  2's file.
- A parked-then-answered task resumes in the same worktree.
- `docket pod <p> remove <member>` leaves no worktree in `git worktree list`.
- Goldens are regenerated only where `add` output changes, with the diff explained line by line.

### P37-3 — command steps get the task's coordinates

**Status:** IN-PROGRESS (Haiku worker) · **Size:** S · **Wave:** 82 · **Model:** Haiku · **Spec:** `pod-dispatch.spec.md`
(the command-step section)

**Trigger:** `_run_command_step` calls `run_verify_cmd(cmd, cwd, timeout)` with the inherited
environment only, so a recipe cannot name the base commit (ADR 0019 §3).

**Goal:**
- `run_verify_cmd` gains an optional `env: dict[str, str] | None`, merged over `os.environ`.
- `_run_command_step` passes `DOCKET_TASK_ID`, plus `DOCKET_BASE_COMMIT` and
  `DOCKET_HEAD_COMMIT` from the latest `ok` Implementer hop in `prior`
  (`evidence["baseCommit"]`/`["commit"]`, empty string when absent).

**Non-goals:** the Implementer's verify gate; any worktree logic (P37-2).

**Acceptance:**
- A pipeline Implementer → `run: 'printenv DOCKET_BASE_COMMIT'`, driven by the existing scripted
  dispatch test helpers, records the Implementer hop's `baseCommit` in the command hop's output.
- With no Implementer hop, the variables are empty strings.
- `run_verify_cmd` without `env` behaves byte-identically.

### P37-4 — a `no_progress` stop reason

**Status:** DONE `b0ed9ef3` (`failure_kind=invalid_output`; the harness passes `failure_kind`, so no schema change) · **Size:** M · **Wave:** 82 · **Model:** Sonnet · **Spec:** `agent-loop.spec.md`

**Trigger:** one of four dispatches on 2026-09-18 ended `exceeded max_iterations=20` on the
16k endpoint. No bound notices repeated, unproductive rounds.

**Goal (ADR 0019 §4):**
- A round's fingerprint is the set of `(tool, canonical args, ok, result digest)` for its tool
  calls.
- When `AGENT_LOOP_NO_PROGRESS_ROUNDS` (default 3, `config.py`, an env override like its
  neighbours) consecutive rounds each have a fingerprint already seen in the turn, the turn stops
  with `stop_reason="no_progress"` and `ok=False`, and the error names the repeated tool.
- `LoopConfig` carries the value, and `0` disables it.
- Any surface that enumerates stop reasons (harness schema, dispatch failure text) is updated
  through its generator.

**Non-goals:** retrying, nudging the model, or cross-turn detection.

**Acceptance:**
- A fake chat port that repeats the same read call stops after exactly N+1 rounds with
  `no_progress`.
- An edit that flips a file A→B→A→B stops.
- A sequence whose results differ every round runs to `final_message`.
- `0` disables the check.
- The harness schema `--check` passes after regeneration.

### P37-5 — `mutation` and `anti-tautology` recipes

**Status:** TODO · **Size:** M · **Wave:** 83 (after P37-3) · **Model:** Sonnet · **Spec:**
`config-format.spec.md` (recipes)

**Goal:** two pipeline recipes under `templates/recipes/`, data only, built on P37-3's variables.
- `anti-tautology`: after the Implementer, a `run:` step fails when a test file added or changed
  since `DOCKET_BASE_COMMIT` passes on `DOCKET_BASE_COMMIT`.
- `mutation`: a `run:` step that mutates only the lines changed since `DOCKET_BASE_COMMIT` and
  fails below a stated threshold, using a mutation tool the recipe names. Its `description` says
  the tool must be installed.

Each command must classify `allow` under `core/security.py::classify_command`, or the recipe
documents the approval it asks for. **If a check cannot be written as a `run:` command without new
core code, stop and report the contention. Do not add core code.**

**Acceptance:**
- `docket validate` and `docket recipes show` accept both.
- A scripted dispatch over a real git repo fails `anti-tautology` on a test that passes on the
  base, and passes it on a test that fails there.
- The `mutation` recipe's command is exercised on a tiny repo when the tool is installed, and is
  otherwise marked skip with the reason.

### P37-6 — `spec-writer` and `cross-family-review` recipes

**Status:** IN-PROGRESS (Haiku worker) · **Size:** S · **Wave:** 83 · **Model:** Haiku · **Spec:** `config-format.spec.md`
(recipes)

**Goal:** two pipeline recipes under `templates/recipes/`, data only:
- `spec-writer`: a test-writing step with its own `model:` runs before the Implementer and is
  briefed to write tests from the brief alone.
- `cross-family-review`: a Reviewer step whose `model:` names a provider other than the
  Implementer's.

Both descriptions say the operator must have the named providers configured. Model names come
from built-in provider presets (`templates/providers/`), never invented.

**Acceptance:**
- `docket validate` and `docket recipes show` accept both, and the derived summary
  (`summarize_recipe`) names the pipeline.
- `docket pod <p> apply <name> --dry-run` lists the steps and their models.

### P37-7 — recipe-declared MCP servers and the `code-intel` pack

**Status:** IN-PROGRESS (Sonnet worker) · **Size:** M · **Wave:** 83 (after P37-1) · **Model:** Sonnet · **Spec:**
`config-format.spec.md`, `mcp-client.spec.md`

**Goal (ADR 0019 §5–6):**
- A recipe may ship `kind: mcp-server` documents (the global server fields, including `kind:
  read|write` and `tools`).
- `docket pod <p> apply` installs them pod-scoped, the dry-run summary lists them, and
  `summarize_recipe` names them.
- `load_mcp_servers(project)` returns global plus that pod's servers. A pod's `mcpServers` may
  name its own servers, and another pod's may not.
- `templates/recipes/code-intel/` declares structural-search and language-server MCP servers by
  **real, verifiable package or binary names**. A server that cannot be verified is left out and
  named in the card report. Each is declared `kind: read` only where it truly cannot write.

**Non-goals:** auto-applying anything (ADR 0012); installing the servers' binaries.

**Acceptance:**
- Applying a recipe with one fake stdio server makes its tools reach a live turn for that pod
  only.
- A second pod cannot select it.
- `apply --dry-run` lists it without installing it.
- `pod export` round-trips it.

### P37-8 — integrate and close Phase 37

**Status:** TODO · **Size:** M · **Wave:** 84 · **Model:** integrator

**Goal:**
- The two ADR 0019 seam tests (task worktree → evidence, evidence → command step).
- A live dispatch on the local endpoint: two tasks back to back on one pod, with evidence showing
  separate bases.
- Spec bumps, regenerated docs, README/CHANGELOG sentences, metrics, and the ROADMAP close; the
  section is archived.

## ◇ PLANNED — Phase 38 (D-51 follow-on; not claimable)

This is an outline, not cards. The integrator writes the phase's cards when it opens and
re-verifies every locator against the tree at that moment, because a gap list decays. Each
phase opens only after the previous one closes. The phase that reverses an earlier ADR records
that in its own ADR (ADR 0017 "What this reverses" lists them as not decided yet).

**Phase 38 — the L4 execution envelope.** Opens after Phase 37.
- Isolation on by default, with a preflight. File tools and MCP servers jailed, not only `bash`.
- An egress lockdown mode (`--network none` plus the `fetch` allowlist). This reverses ADR 0004's
  default for autonomy-granted domains.
- Per-pod sweep workers (parallel dispatch across pods).
- Ephemeral per-task credentials.
- A `kind: autonomy` document consumed from the external verifier: domain → required recipe,
  models, checks and authority. docket enforces it; it never computes it (ADR 0017 §5).
