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
> ## ◆ ACTIVE — Waves 89–90 (no phase), opened 2026-10-05: close the carried items
>
> Every item carried out of Phases 36–38 has a card at the end of this file (W89-1..10).
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


## ◆ ACTIVE — Waves 89–90 (no phase): close the carried items (opened 2026-10-05)

**Trigger:** the operator asked on 2026-10-05 to close every item carried out of Phases 36–38. For
the two items deferred to a trigger (task-worktree retention, options in channels) that request is
the trigger: an operator asking. `kind: autonomy` and per-task credential minting stay deferred,
because nothing in the system produces an autonomy verdict or issues credentials. Scoping read
the live code paths (three read-only passes, 2026-10-05) and found one more jail escape: a linked
worktree's `.git` file and its admin files are writable from the jail.

Packets: [.agents/handoffs/wave-89-worker-packets.md](.agents/handoffs/wave-89-worker-packets.md).
Wave 89 (W89-1..5) runs in parallel; Wave 90 (W89-6..9) starts after Wave 89 is merged; W89-10
integrates and closes.

### W89-1 — `doctor`, `config explain` and `recipes show --json` show unjailed MCP servers

**Status:** DONE `2c3a7601` + integrator `35f022df` (one doctor helper; unit test instead of a layout-baseline entry) · **Size:** S · **Wave:** 89 · **Model:** Haiku · **Spec:** `mcp-client.spec.md` (Requirement 40, and the stale line saying the document has no `isolate`), `cli-json-shapes.spec.md` (`doctor --json`, `config explain` `tools.mcpServers`, `recipes show --json`), `cli-interface.spec.md` (`docket doctor` checks)

**Today:** `cli/_doctor.py` builds its unjailed list from `load_mcp_servers()` (the global registry)
and only in the human path; a pod's `isolate: false` server (from a recipe) is not listed and
`doctor --json` has no field. `cli/_config.py::_mcp_servers_report` emits name/kind/scope only;
`cli/_recipes.py::_info_dict` emits server names without `RecipeSummary.unjailed_mcp_servers`.

**Goal:** `doctor` (human and `--json`) lists every unjailed server, global and per pod (`name (pod
X)`), whenever isolation is not off; `config explain` (both renders) carries `isolate` per server;
`recipes show --json` and `recipes list --json` carry `unjailed_mcp_servers`.

**Acceptance:**
- A pod with a recipe-applied `isolate: false` server: `doctor --json` names it with its pod.
- `config explain <member> --json` shows `isolate: false` for that server and `true` for a jailed one.
- `recipes show code-intel --json` has `unjailed_mcp_servers == ["ast-grep"]`.

### W89-2 — the jail cannot rewrite git metadata the host later runs

**Status:** DONE `38988783` + integrator `908a13ac` (an absent `hooks/` or `info/attributes` is created empty, then bound read-only) · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (Workspace isolation, Requirement 4, and its example)

**Today:** `edges/adapters/system.py::_mount_dirs` re-binds read-only only the git dir's and common
dir's `hooks`, `config` and `config.worktree`. Still writable from the jail:
- a submodule's git dir (`modules/<name>/{hooks,config}`, nested `modules/a/modules/b`), so a hook
  or `core.hooksPath` there runs on the host's next git command in the submodule;
- in a linked worktree (every task worktree since Phase 37), the root's `.git` *file*: rewritten to
  `gitdir: <root>/evil`, it points the host's next git command at attacker hooks and config;
- the worktree admin files `<common>/worktrees/<wt>/{gitdir,commondir}`;
- `info/attributes` (selects filter/diff drivers; only live if a host config defines one).

**Goal:** `_mount_dirs` adds, read-only and only when present: every submodule git dir's `hooks`,
`config`, `config.worktree` (found by walking `modules/` for directories holding `HEAD`, without
running git in them); the root's `.git` when it is a file; the linked worktree's `gitdir` and
`commondir` admin files; `info/attributes`. A jailed `git add`/`git commit` in a linked task
worktree still works (objects, refs, index, logs stay writable). Both backends share `_mount_dirs`.
A submodule added inside the jail after it starts is out of scope; the spec says so.

**Acceptance (real bwrap, skip with a reason when absent):**
- A super-repo with a submodule (`-c protocol.file.allow=always`): from the jail, writing
  `modules/sub/hooks/post-commit` and `git -C sub config core.hooksPath /x` both fail; the host
  files are unchanged.
- In a linked worktree, rewriting `<root>/.git` from the jail fails and the host's `git -C <root>
  rev-parse --git-dir` still names the real git dir.
- The existing jailed-commit test still commits.

### W89-3 — a second stop signal makes `docket serve` abandon in-flight sweeps

**Status:** DONE `936b8a43` · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (Sweep workers, and the "stop waits for in-flight sweeps" line), `serve-read-api.spec.md` (cancellation lifecycle note)

**Today:** `serve.py::run_serve` catches `KeyboardInterrupt` around `serve_forever`, then the
`finally` joins the sweeper, whose `_drain_sweeps` waits with no timeout. A second Ctrl-C raises
inside the join (a traceback) and the pool's threads still block exit; SIGTERM is not handled.

**Goal:** SIGINT and SIGTERM (main thread) drive a two-stage stop: the first stops accepting
work, prints one line (`stopping: waiting for N pod sweep(s); signal again to abandon`) and waits;
the second requests cancellation of every in-flight sweep run (`core/runs.py` cancel, recorded
per pod in `_sweep_one_pod`), cancels queued futures, waits a bounded few seconds for the runs to
settle, and exits 130 (SIGINT) or 143 (SIGTERM). Extract the logic into a small testable
controller. Read how dispatch handles a cancelled task (requeued or `cancelled`) and state it in
the spec; do not change it.

**Acceptance:**
- Unit: the controller's first signal sets stop only; the second sets abandon and requests
  cancellation of each recorded run id.
- Subprocess: a serve whose sweep blocks survives one SIGINT for a second, exits non-zero within a
  few seconds of the second, and the run record shows the cancellation request.

### W89-4 — `docket pod <p> worktrees prune` removes finished, merged task worktrees

**Status:** DONE `57b3d509` + integrator `d818f581` (a resumable failed task keeps its worktree; `git_branch_merged` reads the `+` marker) · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (Task worktrees, new requirement), `cli-interface.spec.md` (the verb)

**Today:** a task's worktree (`<member>/tasks/<taskId>`, branch `docket/<project>/<taskId>`) is
removed only when its member is removed (`core/pod_provisioning.py::teardown_member`).

**Goal:** `core/pod_provisioning.py::prune_task_worktrees(project, *, force=False, dry_run=False)`
and `docket pod <p> worktrees prune [--dry-run] [--force]` (check how `docket pod <p> <verb>`
sub-commands are registered and follow that). It considers tasks in a terminal status with a
recorded `worktree.dir`; never a pending, running or waiting task. Default: remove the worktree
and delete the branch only when the branch is merged into the codebase's current branch and the
worktree has no uncommitted change; report every kept one with its reason. `--force` removes
unmerged/dirty ones and writes an audit entry. The `worktree.dir` must resolve inside the
member's task-worktrees dir before anything is removed. The task record gains
`worktree.prunedAt` via `edges/store.py`. Reuse the existing `system.py` git helpers; do **not**
edit `edges/adapters/system.py` (W89-2 owns it this wave); if a helper is missing, compose from
existing ones in `core/`.

**Acceptance (real git):** two finished tasks, one merged: prune removes the merged one's dir and
branch and records `prunedAt`, keeps and names the unmerged one; a running task is untouched;
`--dry-run` changes nothing; `--force` removes the unmerged one and audits it.

### W89-5 — options reach channel notifications, and Telegram `/answer` can pick one

**Status:** DONE `398b96fd` + integrator `d7dac7f6` (the inbox `TaskView` never carried `question`/`brief`: a sixth unwired-machinery instance, now wired) · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (Notifications), `telegram-integration.spec.md` (`/answer`)

**Today:** `core/operator_contract.py::TaskView.question` is the base `Question`, so v1.1
`options`/`recommendation` are dropped before `core/notify.py::render_data`/`render_text` run;
Telegram `/answer <task> <text>` (`core/telegram.py::_handle_answer`) fills the question's single
schema property from free text, never `optionId`.

**Goal:** the view keeps the v1.1 question; at the `conversation` level (never `minimal`, since
labels are question content) `render_data` adds `options` (`id`, `label`) and `recommendation`
(`optionId` only) and `render_text` adds one line per option (`<id> - <label>`, `(recommended)`
on one) and `reply: /answer <task> <id>`. Labels are model text: strip control characters and
truncate. In Telegram, when the pending question has options and the answer text exactly equals an
option id, `/answer` sends `{"optionId": <id>}` through the existing `answer_task` path (same chat
authorisation, same `pre_input` screen); any other text keeps today's behaviour. Telegram stays
inbound-only: no new outbound call site in `core/telegram.py`.

**Acceptance:**
- `render_data`/`render_text` at `conversation` carry both options and the recommendation; at
  `minimal` neither appears.
- Telegram `/answer t1 iterative` on a consult question records `optionId=iterative`; a non-id text
  behaves as today.

### W89-6 — the docker jail is proven for real: commit and `network none`

**Status:** DONE `16f11fad` (real docker: commit with a git image, `network none` against a bridge listener; doctor probes the image) · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (Requirement 4 note on the docker image), `cli-interface.spec.md` (`doctor` check)

**Today:** `config.SANDBOX_DOCKER_IMAGE` defaults to `alpine:3.20` (busybox: no `git`, no `python3`),
so only bwrap is proven to commit, and docker `--network none` is proven by argv only
(`TestRealDockerJail` covers uid, env and timeout).

**Goal:** keep the default image (docket ships no image); document that the docker jail is only as
capable as `DOCKET_SANDBOX_IMAGE`, which needs `git` to commit. `docket doctor`, when the backend
in use is docker, probes the image once (`command -v git`) and warns with the fix. Real-docker
tests (skip with a reason when the daemon or the image build is unavailable): build a tiny test
image `FROM alpine:3.20` + `apk add --no-cache git` once per session; monkeypatch the image
constant (read at import); prove (i) a jailed `bash` commits in a linked task worktree and the
host sees the commit, (ii) with `network=False` a busybox `nc` connect fails, and (iii) as a
positive control it succeeds against a host-side listener with the network open.

### W89-7 — a `run:` step can carry `env:`; the check recipes use it

**Status:** DONE `4496818f` · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `pipeline-format.spec.md` (Steps, command steps), `pod-dispatch.spec.md` (command-step environment), `pod-blueprints.spec.md` (anti-tautology, mutation)

**Today:** command steps get only `DOCKET_TASK_ID`/`DOCKET_BASE_COMMIT`/`DOCKET_HEAD_COMMIT` over the
serve process environment (`core/dispatch.py::_task_command_env`, `_run_command_step`), so the
`anti-tautology` (`ANTI_TAUTOLOGY_GLOB`, `ANTI_TAUTOLOGY_RUNNER`) and `mutation`
(`MUTATION_THRESHOLD`, `MUTATION_CMD`) overrides can only be set in the process that runs serve.

**Goal:** `Step.env: dict[str, str]` (`core/pipeline.py`), allowed only on `run` steps, keys
`^[A-Z][A-Z0-9_]*$`, refused for `PATH`, `LD_*`, `PYTHON*`, `BASH_ENV`, `ENV`, `DOCKET_*` and any
name `system.task_environment` strips as a credential. Carried through short form, planning and
export. Merged under the task coordinates (coordinates win). Values never reach the trace. The two
recipes declare their overrides as `env:` defaults and their READMEs say a pod overrides them by
editing the step. Regenerate config schemas and recipe docs.

**Acceptance:** a `run` step with `env: {FOO: bar}` sees `bar`; one declaring `DOCKET_BASE_COMMIT`
is refused at validation; `env` on a role step is refused; an export round-trips `env`.

### W89-8 — a parked consult's question travels with the denial; a harness consult names its run

**Status:** DONE `421d457b` + integrator `dfa77259` (the question is persisted 0600 under `consult-parked/`, not base64 in the token, which reached hop errors and the trace past redaction) · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (Consult), `harness-mode.spec.md` (consult `question.taskId`)

**Today:** `core/consult.py` keeps parked questions in the in-process `_PARKED` registry;
`core/dispatch.py::_parked_consult_question` takes it while persisting the hop. When it is not
there (another process, a restart) the task goes `waiting_approval` on a `consult:` token that no
approval record can resolve: stuck. In a single-turn harness consult `question.taskId` is the
session key (`build_question`: `ctx.session_key or ctx.agent_id`).

**Goal:** `ConsultParked` carries the question; the denial result carries it to dispatch, which
reads it from the hop result; `_PARKED` and `take_parked` are deleted (no shim). A `consult:` token
with no question fails the task with a named reason instead of parking it as an approval.
`ToolContext.task_id` is set by the driver from the env route used for `DOCKET_APPROVAL_MODE`;
pod dispatch passes the task id, the harness passes its run token (or the caller's task id if the
harness accepts one); `build_question` uses `task_id`, falling back to the session key only when
neither exists. Operator schemas unchanged; regenerate if a description changes.

**Acceptance:** a dispatch whose turn parks a consult in a separate interpreter state (registry not
shared) ends `waiting_input` with the question; a harness consult's `question.taskId` equals the
run token, not `agent:...`; pod dispatch still sees the task id.

### W89-9 — `approve_task` grants the same call for the rest of the task

**Status:** DONE `83202b77` + integrator `e29b9de1` (a task grant reaches only hops of the role that asked) and `06474729` (HTTP and MCP channels) · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (approval pack options, pre-grants), `pod-dispatch.spec.md` (task record), `harness-mode.spec.md` (scope wording), `telegram-integration.spec.md` (`/approve`)

**Today:** choosing `approve_task` takes effect only inside one turn's `ToolContext`; in pod
dispatch `resolve_waiting_approval` ignores `context.optionId`, so the next identical call in a
later hop of the same task parks again.

**Goal:** granting a parked approval with `approve_task` (CLI `docket approve ... --option
approve_task` or however the CLI names it today, and Telegram `/approve <token> task`) appends a
task-scoped grant `{tool, argsDigest, token, grantedAt, actor, channel}` to the task record;
`_compose_hop` mints one single-use pre-grant per entry for each later hop (existing
`create_pregrant`, bound to project and role), so every use is audited as today. Exact match on
`(tool, argsDigest)`, only on the `ask` path (never widens `deny`), at most 20 per task, dropped
when the task reaches a terminal status, never inherited by another task.

**Acceptance:** a task parks on a call, the grant uses `approve_task`, a later hop of the same task
runs the identical call without a new approval and the audit shows the use; another task with the
same call still parks; a different argument digest still parks.

### W89-10 — integrate, run it for real, refresh the screenshots and the README

**Status:** TODO · **Size:** M · **Wave:** 90 · **Model:** integrator

Cherry-pick each card, full gates per batch (also with `DOCKET_SANDBOX_BACKEND=none`), spec bumps,
CHANGELOG. Live runs on the local endpoint: a default-isolated dispatch with a submodule and the
`.git` rewrite attempt; a consult answered from Telegram-less `pod answer` with an option id and an
`approve_task` grant reused by a later hop; `worktrees prune`; a two-stage serve stop. Re-capture
the doc journey (`scripts/maint/capture-doc-journey.sh`), transcribe it into
`scripts/render-doc-assets.py` and regenerate the three assets; correct the README and the
guides where the run shows they are wrong, keeping the README at most 270 lines. Record the close
in ADR 0020, the deferral tables of ADRs 0018/0019 and ROADMAP.
