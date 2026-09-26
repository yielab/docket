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
> ## ▶ ACTIVE BOARD — WAVE 42 (opened 2026-09-26): Phase 27, per-pod configuration (D-43)
>
> Wave 41 (P27-1, P27-2, P27-3) merged green into `main` with rollup `40d6b78` on 2026-09-26.
> Wave 42 runs P27-4 and P27-5 in parallel, one Sonnet worker per card in an isolated worktree
> under one integrator; packets in
> [.agents/handoffs/wave-41-worker-packets.md](.agents/handoffs/wave-41-worker-packets.md).
> Wave 43 opens only after this wave's rollup merges green.
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


## ▶ WAVE 42 — ACTIVE (opened 2026-09-26): Phase 27, per-pod configuration and portable teams (D-43)

**Opened 2026-09-26 (Wave 41 done; Wave 42 active; Wave 43 queued in this section).** Eight cards in three waves. Decision, the three
scopes, the resolution rule, the verdict table and the pre-assigned spec versions are in
[docs/adr/0009-per-pod-configuration-and-portable-teams.md](docs/adr/0009-per-pod-configuration-and-portable-teams.md);
this section holds only the executable cards. **Activation gate:** the integrator confirms the
batching below from function-level contention, writes `.agents/handoffs/wave-41-worker-packets.md`
with the base commit, and puts a `## ▶ ACTIVE BOARD — WAVE 41` banner as this file's first H2
(with a matching `## ▶ WAVE 41 ...` heading over the wave's cards) so
`context_snapshot.py` resolves the board; only then are cards claimable.

**Trigger (explicit request, 2026-09-26 + a fired deferral):** each pod must carry robust, standard
customization; recipes must apply to any pod; global is only the structural base; configuration is
per pod; MCP and tool permissions must be versatile. ADR 0008 deferred the pod manifest with the
trigger "a pod reproduced on a second machine"; the request is that case. Evidence locators are
in the ADR's evidence table.

**Test rule for every card (ADR 0009 §"Test discipline"):** one RED behavioural test in the
module's existing `SUBJECT` file; a second only for a fail-closed/most-restrictive negative case;
the existing suite, goldens and specs are the no-change oracle; no agent-lane tests, no guards.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 41 | P27-1, P27-2, P27-3 | `core/archetypes.py` → P27-1 only; `core/policy.py` → P27-2 only; `core/tools.py` → P27-2 owns only the `policy_eval_detail` call inside `evaluate_tool_call`; `core/mcp_tools.py` + `cli/_mcp.py` → P27-3 only; `edges/adapters/docket_runtime.py`: P27-1 the project plumbing into `run_agent_turn`, P27-2 the `ToolContext(...)` construction |
| 42 | P27-4, P27-5 | `core/pod.py` + `cli/_pod.py` config key table → P27-4; `core/archetypes.py`: P27-4 owns `registry_for_role`, P27-5 owns the built-in `lead` literal + `resolve_hop_instruction`; `core/dispatch.py` hop-message builder + `core/blueprints.py` → P27-5; `docket_runtime.py::_load_mcp_tools` → P27-4 |
| 43 | P27-6 ∥ P27-8, then P27-7 | new `core/pod_apply.py` + `cli/_pod.py` `apply` → P27-6; `export` in the same module → P27-7 after P27-6 merges; `cli/_config.py`, `cli/_doctor.py` (own check function), `docs/CONFIGURATION.md` → P27-8 |

Every card follows the §"How to use this board" definition of done.

### P27-1 — a pod has its own role overlay, resolved nearest-wins

**Status:** DONE (2026-09-26, e12b567, merged in Wave 41) · **Size:** M · **Wave:** 41 · **Spec:** `role-archetypes.spec.md` → 1.12.0 ("User registry overlay"), `cli-interface.spec.md` → 1.30.0

**Trigger:**
- `core/archetypes.py::load_registry` reads one overlay, `ARCHETYPE_REGISTRY_FILE`; two pods
  cannot hold different `security-vetter` definitions.
- `registry_for_role(base, role)` and every lookup (`agent_loop.run_agent_turn`,
  `pod_provisioning.py` member lookups, `cli/_pod.py` `add` and pipeline plan, the
  `dispatch.py` hop-message builder) take no project.

**Goal:**
- `config.py::pod_config_dir(project)` = `PODS_DIR/<p>/config/`, created 0700 on first write.
- `load_registry(project="")` merges `pod_config_dir/roles.json` **above** the global overlay,
  above built-ins; `project=""` is byte-identical to today.
- `registry_for_role(base, role, project="")` and the lookups above pass the pod (the driver
  reads it from meta; provisioning and the CLI already hold it).
- `docket roles add <file> --pod <p>` writes the pod overlay; `roles list` gains a `source`
  value `pod:<p>` when `--pod <p>` is given; `roles show <name> --pod <p>` resolves the same way.
- `find_overlay_problems(project)` covers the pod file so doctor (P27-8) can report it.

**Non-goals:** pod-level tool denials (P27-4); doctor output (P27-8); any change to built-ins.

**Owns:** `core/archetypes.py` (`load_registry`, `registry_for_role`, `find_overlay_problems`,
`add_user_archetype`), `config.py::pod_config_dir`, `cli/_roles.py`, the `project` plumbing at
the four lookup sites (read-only edits: add the argument, nothing else).

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| pod overlay defines `vetter` with `deniedTools: [write]`, global overlay defines `vetter` with `[]` | `registry_for_role(base, "vetter", project=p)` lacks `write`; with `project=""` it keeps `write` |
| `roles add v.yaml --pod p` then `roles list --pod p` | shows `vetter` with source `pod:p`; `roles list` without `--pod` does not show it |
| a pod member of role `vetter` runs a turn on the fake driver | the trace's `tool_registry` (or the denial) proves the pod definition applied |
| no pod overlay present | every existing test, golden and spec unchanged |

**RED:** `tests/unit/core/test_archetypes.py`: the first row returns a registry that still holds
`write` on the base (no `project` parameter exists).

### P27-2 — a pod has its own policies, and they only add

**Status:** DONE (2026-09-26, ae8c3ac, merged in Wave 41) · **Size:** S · **Wave:** 41 · **Spec:** `security-gates.spec.md` → 0.25.0 (policy store section), `cli-interface.spec.md` → 1.31.0

**Trigger:**
- `core/policy.py::policy_files` globs `POLICIES_DIR` only; `policy_eval_detail(role, hook, text)`
  takes no project.
- `core/tools.py::ToolContext.project` exists and is not passed to the policy evaluation.
- A pod that needs "always ask before touching `.env`" has to install a fleet-wide file.

**Goal:**
- `policy_files(project="")` returns global files plus `pod_config_dir(project)/policies/*.json`;
  `policy_eval_detail`/`policy_eval`/`policy_test` take `project=""`.
- The existing most-restrictive-wins evaluation across files is the whole mechanism: a pod
  `block` adds to a global `allow`; a pod file can never override a global `block` or
  `require_approval`.
- A malformed pod policy fails closed exactly as P26-1 made global ones (same code path).
- `evaluate_tool_call` passes `ctx.project`; `DocketDriver` sets `ToolContext.project` from meta
  if it does not already.
- `docket policies validate|test|list --pod <p>` include the pod directory.

**Non-goals:** new policy actions or schema; scoping `SAFE_BINS` or high-risk classes.

**Owns:** `core/policy.py`, `cli/_policies.py`, the `policy_eval_detail` call in
`core/tools.py::evaluate_tool_call` (that call only), the `ToolContext(...)` construction in
`edges/adapters/docket_runtime.py::run_turn`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| global: none; pod p: `block` on `make deploy` | `policy_eval("implementer","pre_tool_call","make deploy", project="p")` → `deny`; `project="q"` → `allow` |
| global `block` on X; pod p: `allow`-shaped file on X | still `deny` (negative case, the second permitted test) |
| pod file with a bad regex | `deny` naming the file, via the existing P26-1 path |
| `policies test pre_tool_call implementer 'make deploy' --pod p` | `deny`, hit names the pod file |
| no pod directory | every existing policy test and `policies_list.golden` unchanged |

**RED:** `tests/unit/core/test_policy.py`: the first row returns `allow` on the base.

### P27-3 — an MCP server declares its kind and its exposed tools

**Status:** DONE (2026-09-26, f775166, merged in Wave 41) · **Size:** S · **Wave:** 41 · **Spec:** `mcp-client.spec.md` → 1.5.0 ("Configuration", "Enumeration and adaptation"), `cli-interface.spec.md` → 1.32.0

**Trigger:**
- `core/mcp_tools.py::_build_tool` registers every remote tool `kind="write"`; README limit 1
  ("a read-only role gets no MCP tools at all") follows from it.
- A read-only `researcher` with a search server configured gets nothing.

**Goal:**
- `McpServerConfig` gains `kind: Literal["read","write"] = "write"` and
  `tools: list[str] = []` (empty = all). Both are operator assertions, validated at write.
- `docket mcp servers add <name> --kind read --tools search,fetch -- <cmd>`; `servers list`
  shows both; an existing file without the keys loads as before.
- `load_mcp_tools` registers each tool with the server's declared kind and skips (with a
  `McpToolSkip` reason) every tool not in a non-empty `tools` list.
- Because `registry_for_role` already removes by kind, a `kind: read` server reaches a role that
  denies `write` with no change to `core/archetypes.py`.
- The audit entry `mcp_client.load` (or the existing report) names the declared kind.

**Non-goals:** per-tool kinds; proving a remote tool is read-only; pod selection (P27-4).

**Owns:** `core/mcp_tools.py` (`McpServerConfig`, `_build_tool`, `load_mcp_tools`, the add
function), `cli/_mcp.py`, the mcp-client spec sections named.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fake server declared `kind: read`, role with `deniedTools: [write, edit, bash]` | `registry_for_role(registry, role)` keeps the server's tools |
| same server declared `kind: write` (or undeclared) | tools removed — today's behaviour, the negative case |
| `tools: [search]` on a server listing `search` and `delete` | only `mcp__<s>__search` registered; `delete` in `skipped` with the reason |
| `mcp servers add x --kind bogus -- cmd` | exit 1 naming the field |
| existing `docket-mcp-servers.json` without the keys | loads, every existing MCP test unchanged |

**RED:** `tests/unit/core/test_mcp_tools.py`: the first row loses the tools on the base.

### P27-4 — pod settings `mcpServers` and `deniedTools`, each with its live reader

**Status:** IN-PROGRESS (@sonnet-p27-4) · **Size:** M · **Wave:** 42 (after P27-1 and P27-3) · **Spec:** `pod-dispatch.spec.md` → 6.16.0 (pod settings), `mcp-client.spec.md` → 1.6.0 (live-turn wiring), `role-archetypes.spec.md` → 1.13.0 (per-role tool sets)

**Trigger:**
- `DocketDriver._load_mcp_tools` loads every catalog server into every pod's turns; a pod cannot
  say "only `search`" or "none".
- Denials are per role only (`docs/CONFIGURATION.md` §5): a pod cannot say "nobody here uses
  `fetch`".
- Contract property 3 (ADR 0008): a setting ships with its consumer, so both keys and both readers
  are one card.

**Goal:**
- `PodSettings` gains `mcp_servers: tuple[str, ...] | None` (alias `mcpServers`; `None` = all,
  today's behaviour) and `denied_tools: tuple[str, ...]` (alias `deniedTools`), both in the
  `docket pod <p> config get|set|unset` key table with the same validation and `pod.config` audit.
- `mcpServers` reader: `_load_mcp_tools(registry, role, project)` filters `load_mcp_servers()` by
  the pod's selection; a selected name absent from the catalog refuses the dispatch naming it
  (`DispatchError`), never silently loads nothing.
- `deniedTools` reader: `registry_for_role(base, role, project)` removes the union of the role's
  and the pod's names, then applies the existing kind-based removal to the union.
- `config explain` (P27-8) will label both; this card only makes the values reachable through
  the existing `PodSettings.load_for`.

**Non-goals:** per-agent overrides (deferred, D-42 trigger); a pod-local server catalog.

**Owns:** `core/pod.py` (`PodSettings`, `_SETTING_FIELD_BY_ALIAS`, validation), the key table in
`cli/_pod.py` config handler, `core/archetypes.py::registry_for_role` (this function only),
`edges/adapters/docket_runtime.py::_load_mcp_tools` and its call in `run_turn`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| catalog `a`,`b`; `pod config set mcpServers a` | a fake-driver turn registers `mcp__a__*` only |
| `mcpServers` unset | both load — byte-identical to today |
| `pod config set mcpServers zzz` | write refused naming `zzz` (validated against the catalog at write) |
| `pod config set deniedTools fetch`, role `implementer` | its registry lacks `fetch` and still lacks nothing else; role `reviewer` lacks `fetch` too |
| `deniedTools` names a high-risk-class or unknown tool | unknown: refused at write; known: removed (negative case) |

**RED:** `tests/unit/core/test_pod.py`: `PodSettings.load_for` rejects `mcpServers` as an unknown
key on the base.

### P27-5 — the Lead's instruction is data, and step instructions reach it

**Status:** IN-PROGRESS (@sonnet-p27-5) · **Size:** S · **Wave:** 42 · **Spec:** `pod-dispatch.spec.md` → 6.17.0 (hop message), `pipeline-format.spec.md` → 2.6.0 (step `instructions`), `pod-blueprints.spec.md` → 1.5.0, `role-archetypes.spec.md` → 1.14.0 (hop instructions)

**Trigger:**
- `core/dispatch.py` hop-message builder, `role == "lead"` branch: "Decompose this task into a
  concrete plan for the Implementer (you never edit code yourself)" for every pipeline, and the
  docstring states step `instructions` are not applied to the Lead.
- A research or ops pod's Lead is told to plan for an Implementer it does not have.

**Goal:**
- The built-in text becomes the `lead` archetype's `hop_instruction`; the builder's Lead branch
  reads it through `resolve_hop_instruction` like any custom role, so a pod or global overlay of
  `lead` changes it.
- A step's `instructions` (already interpolated) override the Lead's line too; the docstring's
  scope boundary is removed.
- The research, content and ops blueprint pipelines carry a Lead `instructions` line naming
  their own next role ("plan for the Researcher" / "Writer" / "Operator").
- The software and agentic-product pipelines and the default Lead line stay byte-identical, so a
  software pod's first hop message does not change.

**Non-goals:** changing the Lead's tools or gate; per-step models.

**Owns:** the hop-message builder in `core/dispatch.py` (Lead branch only), the built-in `lead`
literal and `resolve_hop_instruction` in `core/archetypes.py`, the three pipeline literals in
`core/blueprints.py`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| research pod, blueprint pipeline, fake driver | the Lead's hop message names the Researcher and not the Implementer |
| software pod, no overlay | the Lead's hop message is byte-identical to the base (capture it in the test from the base first) |
| pipeline step `{id: plan, role: lead, instructions: "Plan in three bullets"}` | the Lead's message carries that text |
| `roles show lead` | prints the `hopInstruction` |

**RED:** `tests/unit/core/test_dispatch.py`: the research-pod message contains "Implementer" on
the base.

### P27-6 — `docket pod <p> apply <dir>`: a recipe applies to any pod in one command

**Status:** TODO · **Size:** M · **Wave:** 43 (after Wave 42 merges) · **Spec:** `pod-blueprints.spec.md` → 1.6.0 (new section "Pod manifests: apply"), `role-archetypes.spec.md` → 1.15.0 ("Shipped recipes"), `cli-interface.spec.md` → 1.33.0

**Trigger:**
- Each shipped recipe README lists six commands; every teammate repeats them per machine.
- ADR 0008 deferred "declarative pod manifest (apply)" with the trigger "a pod reproduced on a
  second machine"; the 2026-09-26 request fires it.

**Goal:**
- `core/pod_apply.py`: `plan_apply(project, dir) -> ApplyPlan` (pure: reads `roles/*.yaml`,
  `policies/*.json`, `pipeline.yaml`, `pod.yaml` with `members`, `settings`, `pipeline`;
  validates roles, policies, settings and the pipeline **against the roster as it will be after
  `members`**; returns per-item `add | replace | skip` with reasons) and
  `apply(plan) -> ApplyResult` (writes pod scope only, through the existing writers:
  `add_user_archetype(..., project)`, the pod policy directory, `provision member`, the bind
  function behind `config set pipeline`, `PodSettings` setter). Any validation error returns
  before any write.
- `docket pod <p> apply [<dir>] [--dry-run] [--json]`; `<dir>` defaults to
  `<codebase>/.docket/` (Lead meta `codebase`), exit 1 naming the path when absent.
- Idempotent: a second run is all `skip`. Audited once as `pod.apply` with the item list.
- The three recipe READMEs' "Apply it" becomes the one command; each recipe gains a minimal
  `pod.yaml` (`members`; `secure-build` keeps its policy as an optional file the README names).
- `tests/integration/test_recipes.py` switches its fixture to `plan_apply`/`apply` and keeps the
  `secure-build` dispatch-to-`done` case — no parallel test file.

**Non-goals:** removal/prune/diff; auto-apply at `init`; a new file format beyond `pod.yaml`'s
three keys; `export` (P27-7).

**Owns:** new `core/pod_apply.py`, the `apply` subcommand in `cli/_pod.py`,
`src/docket/templates/recipes/*` (READMEs and `pod.yaml`), `tests/integration/test_recipes.py`.
Adds CLI surface: regenerate `completions_bash`/`completions_zsh` goldens and `docs/commands.md`,
listing the added lines.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fresh pod `p` (lead+implementer), `apply templates/recipes/secure-build` | plan lists role add, member add, pipeline bind; afterwards `pipeline plan p` prints `Source: bound`, `roles list --pod p` shows `security-vetter`, `.docket-meta.json` of the new member exists |
| second `apply` | every item `skip`, no audit entry beyond the first, files byte-identical |
| `pod.yaml` with `settings: {mcpServers: [zzz]}` | exit 1 naming `zzz`, **nothing written** (side-effect check: the pod overlay and policy dir do not exist) |
| `--dry-run` | prints the plan, writes nothing |
| `apply` with no dir and no `<codebase>/.docket` | exit 1 naming the path |
| `secure-build` after apply on the fake driver | dispatches to `done` with the verdict gate in the trace (existing case, now through apply) |

**RED:** `tests/integration/test_recipes.py`: `from docket.core import pod_apply` fails on the base.

### P27-7 — `docket pod <p> export <dir>`, and the round trip is the proof

**Status:** TODO · **Size:** S · **Wave:** 43 (serially after P27-6) · **Spec:** `pod-blueprints.spec.md` → 1.7.0 ("Pod manifests: export"), `cli-interface.spec.md` → 1.34.0

**Trigger:** the deferred manifest's own trigger, "a pod reproduced on a second machine", needs
the write direction; `roles show` already emits the YAML wire format, the bound pipeline copy and
pod policy files are plain files, and `PodSettings` serializes.

**Goal:**
- `core/pod_apply.py::export_pod(project, dir)` writes `roles/*.yaml` (pod overlay only, via
  `to_wire`), `policies/*.json` (pod directory only), `pipeline.yaml` (the bound copy, if any) and
  `pod.yaml` (`members`: the pod's non-lead roles; `settings`: every non-default pod setting).
  Global scope is never exported — it is the operator's, not the team's.
- `docket pod <p> export <dir>` refuses a non-empty directory unless `--force`.
- Round trip: `export p → fresh DOCKET_HOME → init q → apply q <dir>` gives a
  `config explain q --json` equal to `config explain p --json` after normalising ids and paths.

**Non-goals:** exporting global overlays, secrets, sessions, traces or the task queue.

**Owns:** `export_pod` in `core/pod_apply.py`, the `export` subcommand in `cli/_pod.py`.
Adds CLI surface: completions goldens and `docs/commands.md`, listed line by line.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| pod with a pod-scoped role, one pod policy, a bound pipeline, `approvalMode refuse` | the four files exist with exactly those contents; nothing from `~/.docket/policies/` appears |
| round trip into a second home | `config explain --json` equal after normalisation (the phase's one integration proof) |
| export into a non-empty dir | exit 1 without `--force`; overwrites with it |

**RED:** `tests/integration/test_recipes.py` (or `test_pod_apply.py` if P27-6 created it): the
round-trip test fails on the base because `export_pod` does not exist.

### P27-8 — every resolved value says which scope it came from

**Status:** TODO · **Size:** S · **Wave:** 43 (parallel with P27-6) · **Spec:** `cli-interface.spec.md` → 1.35.0 (`config explain`, `doctor`)

**Trigger:** contract property 5 (ADR 0008): after P27-1…P27-5 a role, policy, server or denial
can come from three places and `config explain` names none; `docket doctor` reports malformed
global overlay entries and policies but not pod ones.

**Goal:**
- `docket config explain <agent>` labels the resolved role archetype, each applicable policy
  file, each loaded MCP server (with declared kind and the pod's selection) and each denied tool
  with `built-in | global | pod`; `--json` carries a `scope` field per item.
- `docket doctor` gains one check function that reports a malformed pod overlay entry
  (`find_overlay_problems(project)`) and an invalid pod policy file for every pod, and re-uses the
  P26-era fix path where one exists.
- `docs/CONFIGURATION.md`: the ownership map gains a scope column and the pod config directory;
  §3.10 becomes "apply a recipe in one command"; §5 loses "Tool denials are per role only".

**Non-goals:** new explain sections; changing what explain resolves.

**Owns:** `cli/_config.py` (explain renderer and JSON), one new check function in
`cli/_doctor.py`, `docs/CONFIGURATION.md`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| pod overlay shadows `reviewer`; global policy + pod policy; server declared `read` selected by the pod; pod `deniedTools: [fetch]` | `config explain <p>-reviewer --json` shows `scope: pod` for the role, both policies with their scopes, the server with `kind: read` and `scope: pod` selection, `fetch` with `scope: pod` |
| no pod scope at all | explain output byte-identical to the base (capture in the test) |
| a pod `roles.json` with a bad entry | `doctor` names pod, role and reason |

**RED:** `tests/unit/cli/test_config.py` (the file that declares `SUBJECT` for `cli/_config.py`):
the JSON has no `scope` key on the base.

## ◆ PHASE 28 — PLANNED (2026-09-26): configuration format v1 and the two extension points (D-44)

**Planned 2026-09-26.** Eight cards in three waves. Decision, the format, the control-flow rule,
the plugin trust boundary and the verdict table are in
[docs/adr/0010-config-format-v1-and-extension-points.md](docs/adr/0010-config-format-v1-and-extension-points.md).
**Activation gate:** Phase 27 closes (its `apply`/`export` and pod scope are what P28-7 and P28-8
build on); then the same integrator steps as Phase 27 (batching, packets file, the `▶ ACTIVE
BOARD — WAVE 44` banner).

**Trigger (explicit request, 2026-09-26):** every configuration file must have a standard
structure a non-expert can read; pipelines and policies must use a clear language; complex
customization needs an extension mechanism in code, like Drupal migrate's process plugins. The
evidence table in the ADR names the current formats' inconsistencies by locator.

**Test rule:** one RED test per card; each normaliser proven by one round trip; P28-7 carries
the two negative cases (a codebase-only plugin is not loaded; a raising plugin denies); no
agent-lane tests, no guards.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 44 | P28-1, P28-2, P28-3, P28-4 | new `core/config_docs.py` → P28-1; `core/policy.py` + the `policy_eval_detail` call in `core/tools.py::evaluate_tool_call` → P28-2; `core/pipeline.py` normaliser → P28-3; `core/archetypes.py::from_wire`/`parse_yaml_file` → P28-4 |
| 45 | P28-5, P28-6 | `core/orchestrator.py`: P28-5 outcome routing + termination/reachability, P28-6 step skipping + command-step executor; `core/pipeline.py`: P28-5 `on`/`until`, P28-6 `when`/`run` |
| 46 | P28-7 ∥ P28-8 | new `core/plugins.py` + `cli/_plugins.py` + the predicate hook in `core/policy.py` → P28-7; schemas, `export`, docs, recipes → P28-8 |

### P28-1 — every configuration file says what it is, and one command validates them all

**Status:** TODO · **Size:** S · **Wave:** 44 · **Spec:** new `specs/functional/config-format.spec.md` 1.0.0, `cli-interface.spec.md` → 1.36.0

**Trigger:** no configuration file carries a `kind`; roles, pipelines, policies and the Phase 27
manifest are told apart by directory and by the caller's choice of parser; policies are JSON
while everything else is YAML.

**Goal:**
- `core/config_docs.py::load_document(path) -> Document` reads YAML (JSON included), requires
  `kind` in `{role, pipeline, policy, pod}` and `name`, and dispatches to the existing parser of
  that kind. A file without `kind` loads through today's parser and returns a deprecation note
  the CLI prints once per command.
- `docket validate [dir]` (default `<cwd>/.docket`, or one file) validates every document and
  the manifest, printing `file:line field: message (valid: a, b, c; did you mean "b"?)`, exit 1 on
  the first invalid file after listing all.
- The Phase 27 `apply` planner and every `roles|pipeline|policies validate` path call
  `load_document` so there is one parse path.

**Non-goals:** short forms (P28-2..4); schemas (P28-8); removing the old format.

**Owns:** new `core/config_docs.py`, new `cli/_validate.py`, the call-site swaps in
`cli/_roles.py`, `cli/_pipeline.py`, `cli/_policies.py`, `core/pod_apply.py` (one line each).
Adds CLI surface: completions goldens and `docs/commands.md`, listed line by line.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `kind: policy` YAML with `then: require_approval` | `validate` exits 1 naming line, field, valid values and suggests `ask` |
| a recipe directory with one bad file | every file listed, the bad one first with its reason, exit 1 |
| today's role YAML without `kind` | loads, one deprecation line, byte-identical result |
| `kind: banana` | exit 1 naming the four kinds |

**RED:** `tests/unit/core/test_config_docs.py` (new `SUBJECT` file): `from docket.core import
config_docs` fails on the base.

### P28-2 — policies read as "when this, then that", with predicates over the tool and its arguments

**Status:** TODO · **Size:** M · **Wave:** 44 · **Spec:** `security-gates.spec.md` → 0.26.0 (policy format)

**Trigger:**
- `core/policy.py` documents `{id, applies_to, hook, match{type,pattern}, action}`: runtime
  vocabulary, snake_case, JSON.
- `core/tools.py::evaluate_tool_call` passes only `render_tool_call(tool.name, args)`; a policy
  cannot say "the `write` tool under `.github/`" without a regex over rendered text.

**Goal:**
- Short form: `kind: policy`, `appliesTo`, `on: input|toolCall|output` (default `toolCall`),
  `when: {tool, path, matches, branch, anyOf: [...]}` (implicit AND, `anyOf` for OR, no `not`),
  `then: allow|warn|ask|block|redact`, `message`. `normalize_policy(short) -> canonical` is a pure
  function; the canonical dict is today's shape plus an optional structured `when`.
- The engine receives the tool name, its arguments and the worktree branch beside the rendered
  text (`policy_eval_detail(..., call=ToolCallFacts | None)`); `path` is a glob over the call's
  path argument, `branch` a glob over the current branch. Text-only callers (`pre_input`,
  `pre_output`, `policies test` for text) pass `None` and behave as today.
- `policy_files` also globs `*.yaml`/`*.yml`; the six shipped templates are rewritten in short
  form (their behaviour unchanged, proven by the existing policy tests).
- Most-restrictive-wins and fail-closed are untouched.

**Non-goals:** plugins (P28-7); new actions; removing the JSON form.

**Owns:** `core/policy.py` (`normalize_policy`, predicate evaluation, file globbing), the one
call in `core/tools.py::evaluate_tool_call`, `templates/policies/*`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| short-form file `{tool: write, path: ".github/**", then: ask}`; `write path=.github/x.yml` | `ask`; `write path=src/x.py` → `allow` |
| the same rule as a JSON regex policy | identical verdicts for both renderings (the round trip) |
| `anyOf: [{branch: main}, {branch: "release/*"}]` with `git push` on `feature/x` | `allow`; on `main` → `ask` |
| every shipped template rewritten | existing `test_policy.py` and `policies_list.golden` unchanged except the file extension column, listed |

**RED:** `tests/unit/core/test_policy.py`: `normalize_policy` does not exist on the base.

### P28-3 — a pipeline step reads as "who, what is checked, where it goes"

**Status:** TODO · **Size:** S · **Wave:** 44 · **Spec:** `pipeline-format.spec.md` → 2.7.0 (short form)

**Trigger:** every shipped recipe repeats `pattern: '^\s*(APPROVE|REQUEST-CHANGES)\b'`,
`passValues: [approve]` and `rework: {to, when, maxCycles}` to say "verdict gate, one rework".

**Goal:**
- Short form: a step is `- <id>: <role or agent id>` plus optional `verify: true|<command>`,
  `verdict: [PASS, FAIL]`, `approval: <message>`, `instructions`, `timeout`, `retries`, and
  `on: {<label>: {goto: <step>, max: N} | fail | stop | <step>}` where a backward `goto` requires
  `max`. `normalize_pipeline(short) -> PipelineSpec` is a pure function producing today's
  canonical models (`VerdictGate` with the derived pattern and `pass_values`, `rework` from the
  one backward edge). A step with no gate key inherits its role's gate contract, as today.
- Canonical long form stays valid and is what `plan` prints.
- `on:` beyond the single backward edge is **stored** canonically here and **executed** by P28-5;
  this card refuses at `validate` any `on:` shape P28-5 has not shipped ("outcome routing is not
  available yet"), so no file silently means less than it says.

**Non-goals:** executor changes (P28-5/P28-6); `when`, `until`, `run`.

**Owns:** `core/pipeline.py::normalize_pipeline` and the short-form parsing in `load_pipeline`;
`cli/_pipeline.py` help text; the three recipe `pipeline.yaml` files rewritten in short form.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `secure-build` in short form | `normalize_pipeline(short) == load_pipeline(long).spec` (the round trip) |
| `verdict: [APPROVE, REQUEST-CHANGES]` | `pass_values == ["approve"]`, pattern matches exactly the two markers at line start |
| backward `goto` without `max` | `validate` exit 1 naming the step |
| `plan` on each recipe | byte-identical to the base |

**RED:** `tests/unit/core/test_pipeline.py`: `normalize_pipeline` does not exist on the base.

### P28-4 — a role file carries only what is enforced, and its prose lives in Markdown

**Status:** TODO · **Size:** S · **Wave:** 44 · **Spec:** `role-archetypes.spec.md` → 1.16.0 (wire format)

**Trigger:** `RoleArchetype.edit_rights` is "descriptive only" beside `denied_tools`; `gateContract:
{kind, regexes}` duplicates the pipeline's verdict vocabulary; `soulTemplate` and `agentsTemplate`
are long block scalars a non-expert edits badly.

**Goal:**
- Short form: `kind: role`, `name`, `description`, `model: cheap|strong|<id>`, `cannot: [...]`,
  one of `verdict: [...] | verify: true | approval: true`, `instructions: <file.md>` (default: the
  `.md` beside the YAML; the Markdown renders with the same `${variables}` into `SOUL.md`, and
  `AGENTS.md` keeps the built-in red lines unless the Markdown has an `## AGENTS` section).
- `normalize_role(short, base_dir) -> canonical dict` is pure; `editRights` is derived
  (`cannot` contains `write` → `read-only`) and no longer written by `export`.
- `docket roles show` prints the short form when the archetype came from a short-form file.

**Non-goals:** changing built-ins; the pod overlay (Phase 27).

**Owns:** `core/archetypes.py::from_wire` (accept both), new `normalize_role`, `parse_yaml_file`;
`templates/recipes/*/roles/*` rewritten with a `.md` beside each.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `security-vetter` short form + `.md` | `normalize_role(short) == from_wire(long)` (the round trip); the rendered `SOUL.md` is byte-identical to the base's |
| `cannot: [write]` and no gate key | `deniedTools == ["write"]`, `gateContract.kind == "none"` |
| both `verdict` and `verify` | `validate` exit 1 |

**RED:** `tests/unit/core/test_archetypes.py`: `normalize_role` does not exist on the base.

### P28-5 — outcomes route the pipeline, and every loop has a bound

**Status:** TODO · **Size:** M · **Wave:** 45 (after P28-3) · **Spec:** `pipeline-format.spec.md` → 2.8.0 (control flow), `pod-dispatch.spec.md` → 6.18.0

**Trigger:** `core/orchestrator.py` routes only through a `VerdictGate.rework` edge to an earlier
step; a verdict cannot send the task to a later step, escalate to an approval step, or stop; a
mechanical gate cannot retry its own step.

**Goal:**
- Executor: after a step's gate resolves to an outcome label (a verdict value, `pass`/`fail` for
  mechanical, `approved`/`denied` for approval), `on:` picks the next step: `goto` (forward or
  backward, backward counting against `max`), `fail`, `stop` (task `done` with a trace note), or
  the default next step. Today's `rework` is exactly `on: {request-changes: {goto: <step>, max}}`
  and stays byte-identical.
- `until: verify` + `max`: sugar for `on: {fail: {goto: <self>, max}}`.
- `validate`/`plan`: a backward edge without `max` and an unreachable step are errors; `plan`
  prints each step's routes.
- Every routing decision is a trace event naming step, outcome and target.

**Non-goals:** `when` and command steps (P28-6); parallel changes.

**Owns:** `core/orchestrator.py` outcome routing (one function) and the two checks;
`core/pipeline.py` `on`/`until` model fields (P28-3 parsed them; this card lifts the "not
available yet" refusal).

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `vet` with `on: {REQUEST-CHANGES: {goto: build, max: 1}}` on the fake driver | identical hop sequence and trace to the base's `rework` form |
| `on: {FAIL: escalate}` where `escalate` is a later approval step | the task reaches `waiting_approval` at `escalate` |
| `until: verify, max: 2` with a verify that fails twice then passes | three implementer hops, then advance; a third failure → task `failed` |
| unreachable step | `validate` exit 1 naming it |

**RED:** `tests/unit/core/test_orchestrator.py`: the forward `goto` case advances to the next
sequential step on the base.

### P28-6 — a step can be skipped on a closed predicate, and a step can be a command

**Status:** TODO · **Size:** S · **Wave:** 45 · **Spec:** `pipeline-format.spec.md` → 2.9.0, `cli-interface.spec.md` → 1.37.0

**Trigger:** a Tester step cannot be skipped when nothing under `src/` changed; a lint or report
step needs an agent turn even when a command would do; the only code escape for a pipeline is a
verify command attached to an agent.

**Goal:**
- `when:` with exactly three predicates implemented in code and listed by `validate`:
  `changed: <glob>` (against the implementer worktree's diff from the task's base), `var: <name>,
  is: <value>`, `memberPresent: <role>`. A false predicate skips the step with a `step_skipped`
  trace event and routes to the default next step.
- Command step: `- lint: {run: "ruff check ."}` runs the command in the pod's worktree through
  `edges/adapters/system.py` (no agent, no model tokens), bounded by `timeout`; exit code 0 →
  outcome `pass`, otherwise `fail`; the last stdout line, if it is a single uppercase token, is
  the outcome label for `on:`. Output is captured into the run's hop record and the trace, redacted.
  It is subject to `allowCommands`/the command classifier like a verify command.
- `plan` prints `[lint] run ... [gate: exit code]` and `when` on each step.

**Non-goals:** more predicates (a new one is a card with a test); Python step plugins (deferred).

**Owns:** step skipping and the command-step executor in `core/orchestrator.py` (its own
function), `core/pipeline.py` `when`/`run` fields, the `plan` renderer lines.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `when: {changed: "src/**"}` with a diff only under `docs/` | step skipped, trace event, next step ran |
| `run: "false"` | outcome `fail`, task `failed`, no model call recorded |
| `run: "printf 'ok\\nPASS\\n'"` with `on: {PASS: ship}` | routes to `ship` |
| `run: "git push origin production"` | classified high-risk: asks, or refuses under `approvalMode refuse` |

**RED:** `tests/unit/core/test_orchestrator.py`: a `run:` step is rejected as an unknown key on
the base.

### P28-7 — a policy can call a Python predicate the operator applied, never one the agent wrote

**Status:** TODO · **Size:** M · **Wave:** 46 (after Phase 27's `apply`) · **Spec:** `security-gates.spec.md` → 0.27.0 (predicate plugins), `cli-interface.spec.md` → 1.38.0

**Trigger:** the predicate vocabulary is closed by design; a team with a genuinely complex rule
("ask when a migration file is touched outside the migrations/ tree of the app that owns it") has
no path but a fragile regex. The Drupal-migrate precedent: named plugins in YAML, custom plugins in
code. The trust boundary: the agent edits the repository the plugin would live in.

**Goal:**
- `docket.plugins` public API: `PLUGIN_API_VERSION = "1.0.0"`, `@predicate(name)`, typed
  `ToolCall` (tool, args, rendered) and `PolicyContext` (role, project, branch, worktree root);
  a predicate returns `bool`.
- Discovery: `~/.docket/plugins/*.py` (global) and `pod_config_dir/plugins/*.py` (pod), imported
  with `importlib.util.spec_from_file_location`; a duplicate name across files is an error;
  `docket plugins list` prints name, scope, file and sha256. **Nothing is imported from the
  codebase.** `docket pod <p> apply` copies a recipe's `plugins/*.py` into pod scope with its hash
  (the bound-pipeline rule), so a codebase edit changes nothing until an operator applies again.
- YAML: `when: {plugin: <name>, with: {...}}`; `then:` decides as always.
- Fail closed: an unknown name at load, a raising plugin, a non-bool return or a plugin over a
  fixed wall-clock budget (default 250 ms, measured per call) → `deny` naming the plugin; every
  invocation is audited (`policy.plugin`) with name, scope, hash and verdict.
- `docket policies test` runs plugins the same way.

**Non-goals:** action or gate plugins, entry-point packaging, `engine: cedar|rego` (all deferred
with triggers in the ADR); sandboxing plugin code (it is operator code, and the ADR says so).

**Owns:** new `core/plugins.py`, new `cli/_plugins.py`, the `plugin` predicate branch in
`core/policy.py`, the `plugins/` copy step in `core/pod_apply.py`. Adds CLI surface: completions
goldens and `docs/commands.md`, listed.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| global plugin `touches_migrations`; policy `when: {plugin: touches_migrations}, then: ask`; `write path=app/migrations/0002.py` | `ask`, audit entry names plugin, scope `global`, hash |
| the same `.py` present only under `<codebase>/.docket/plugins/`, not applied | `docket plugins list` does not show it; the policy load fails closed (`deny` naming the unknown plugin) — negative case 1 |
| a plugin that raises | `deny` naming it — negative case 2 |
| `apply` a recipe with `plugins/x.py`, then edit the codebase copy | the pod-scope hash is unchanged and the old code runs until re-apply |

**RED:** `tests/unit/core/test_plugins.py` (new `SUBJECT` file): `from docket.core import plugins`
fails on the base.

### P28-8 — schemas editors can use, export in the short form, and docs that show only v1

**Status:** TODO · **Size:** S · **Wave:** 46 · **Spec:** `config-format.spec.md` → 1.1.0, `pod-blueprints.spec.md` → 1.8.0 (export), `cli-interface.spec.md` → 1.39.0

**Trigger:** contract property 5 and the request's "easy to interpret for a non-expert": a file
format without a schema has no autocomplete and no inline errors in an editor; `export` (P27-7)
would otherwise write the long form.

**Goal:**
- `docs/contracts/config-v1/{role,pipeline,policy,pod}.schema.json` generated from the short-form
  models and pinned byte-for-byte by one test, the harness-v1 pattern.
- `export` writes the short form with a first line `# yaml-language-server: $schema=<relative
  path>`; `apply` of an export is a no-op (round trip through P27-7's test, extended by one
  assertion).
- `docs/CONFIGURATION.md` §3.4–3.6 and the recipe READMEs show only the short form; the long
  form moves to the spec's "canonical form" section.

**Non-goals:** new fields; a docs site page.

**Owns:** `scripts/gen_config_schemas.py` (mechanical), `docs/contracts/config-v1/`, the export
writer in `core/pod_apply.py`, `docs/CONFIGURATION.md` §3, recipe READMEs.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| regenerate the four schemas | byte-identical to the committed files (the pin) |
| a short-form recipe validated by a standard JSON Schema validator against its schema | valid; a `then: bogus` policy invalid at the right path |
| `export` then `apply` | every item `skip` |

**RED:** the schema pin test fails on the base because the directory does not exist.
