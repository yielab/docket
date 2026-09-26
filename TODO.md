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
> ## ◇ WAVE 37 CLOSED (2026-09-25) — no card claimed
>
> **Wave 37 closed 2026-09-25** (ROADMAP D-41). A bounded triage ran the product on six surfaces
> and found twelve reproducible defects; six cards fixed them in two batches of one-card Sonnet
> workers under one integrator, archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
> [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md). Live
> evidence on the local endpoint: the journey's dispatch scene reaches `done — 3 hop(s)` with the
> reviewer's `APPROVE`, and a `cd`-prefixed production push still asks.
>
> `v0.2.0-beta.3` (2026-09-18) is the latest release; the next beta stays a maintainer action.
> A card becomes claimable only when the integrator opens a planned section below and confirms its
> batching from function-level contention.
>
> **Measured, not scheduled:** `tee` is on the bash allowlist, so `echo x | tee f` writes a file
> without asking (pre-existing, not introduced by W37-C1); `docket help <command>` renders through
> `typer.testing.CliRunner`; `turnTimeoutS`/`verifyTimeoutS` are read on the live dispatch path
> but have no dedicated writer. A new wave starts from bounded triage, not from this note.
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

## ◆ PHASE 26 — ACTIVE (opened 2026-09-25): the configuration contract (D-42)

**Opened 2026-09-25, immediately after Wave 37 closed (`3089a00`) removed the file-contention
blocks (W37-C5 on `core/approval.py`, W37-C6 on `cli/_policies.py`/`cli/_keys.py`).** Twenty
cards. **Wave 38 batch A closed 2026-09-25**: P26-1, P26-2, P26-13, P26-16, P26-18 merged (P26-1 by the coordinator, the rest by one Sonnet worker each in isolated worktrees); **Batch B closed 2026-09-26** (P26-4 `acf471f`, P26-19 `1781c73`; both Sonnet workers, integrator-resolved conflicts). **Wave 39 closed 2026-09-26**: P26-3, P26-5 (`971cb4c`), P26-6 (`c12dae5`), P26-7 (`3d63caa`), P26-8 (`1184eb8`) — five Sonnet workers in parallel from base `2087e0b`; the integrator re-versioned two silent same-day spec collisions (security-gates 0.24.0, pod-dispatch 6.12.0, pipeline-format 2.4.0). **Wave 40 open**: P26-9→P26-10→P26-17 serial, plus P26-11, P26-12, P26-14, P26-15, P26-20. Decision, verdict table and the
six-property contract: [docs/adr/0008-configuration-contract.md](docs/adr/0008-configuration-contract.md).
The user-facing map of every installed file is [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
Each closing card deletes its own bullet from that guide's §5 "Sharp edges" in the same commit.

**Trigger (explicit request + reproductions):** the 2026-09-25 request to make agent, pipeline and
governance configuration robust, standard and versatile, to stop a fixed ~24 KB budget from
limiting orchestration, and to ship recipes that are robust for real use yet easily configurable.
The reproductions are quoted per card, at `a592328`. A same-day E2E connection audit (pod →
config changes → custom-role pipeline run on the local endpoint) added P26-18/P26-19/P26-20; its
positive results are in `docs/adr/0008-configuration-contract.md` ("What the E2E run proved").

**Proposed batching:** the integrator confirms it when the phase opens, from function-level
contention.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 38 | P26-1, P26-2, P26-4, P26-13, P26-16, P26-18, P26-19 | `identity.py::_runtime_workspace_context` → P26-2 only; `dispatch.py` pod-setting readers → P26-4 only, claim/refusal lifecycle → P26-19 only; `core/pod.py` membership → P26-18 only; `cli/_doctor.py`: each card adds its **own** check function |
| 39 | P26-3, P26-5, P26-6, P26-7, P26-8 | `dispatch.py`: P26-5 the hop env builder, P26-6 `effective_pipeline`/`_blueprint_pipeline`, P26-7 the hop-message builder; `tools.py`/`security.py` → P26-8 only; `identity.py` → P26-3 only |
| 40 | P26-9 → P26-10 → P26-17, with P26-11, P26-12, P26-14, P26-15, P26-20 alongside | P26-9, P26-10 and P26-17 all touch templates or `identity.py`, so they run serially; P26-11 is read-only over merged code; P26-20 is data + tests over P26-6/P26-7/P26-18's merged behaviour |

Every card follows the §"How to use this board" definition of done.

### P26-1 — a broken policy fails closed, never open

**Status:** DONE (2026-09-25, `ed965e5`) · **Size:** S · **Wave:** 38 · **Spec:** `security-gates.spec.md`

**Trigger:**
- Base: a `pre_tool_call` policy with `match.pattern: "make\\s+deploy"` and `action: block` makes
  `docket policies test pre_tool_call implementer 'make deploy'` return `deny`.
- One extra `(` in the pattern → `allow`, and `docket policies validate` prints "valid".
- An invalid JSON escape in the file → `allow`.
- Cause: `core/policy.py:109-110,132-133` `continue` silently; `validate_policy` never compiles the
  regex.
- Related dry-run gap: `policies test pre_tool_call implementer 'write path="main.py"'` reports
  `ask` ("'write' is not on the curated allowlist") — the W37-C1 parity change runs the bash
  classifier on every text, but the live gate classifies `kind=exec` tools only, so a policy on a
  `write`/`edit` render cannot be tested truthfully.

**Goal:**
- An unloadable policy file, uncompilable pattern or unknown action makes every call on that
  file's hook (all hooks, when the JSON cannot be parsed) resolve to `deny`, naming the file.
  This covers the live gate, `pre_input`, `pre_output` and `policies test`.
- `policies validate` compiles regexes.
- `docket doctor` reports broken policies as errors.
- A trace event names each skipped file.
- Fix the stale `validate_policy` docstring and the `programmer` role in the `policies init` hint.
- `policies test pre_tool_call` accepts `--tool <name>` (default `bash`) and only applies the
  command classifier when the named tool's kind is `exec`, matching `evaluate_tool_call`.

**Non-goals:** policy schema changes; loosening; per-file enable/disable.

**Owns:** `core/policy.py` (evaluation plus `validate_policy`), `cli/_policies.py` validate, a new
doctor check function, and the policy section of `security-gates.spec.md`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| valid block | `deny` |
| bad regex | `deny`, with a reason naming the file |
| bad JSON | `deny` |
| unknown action | `deny` |
| `policies validate` on the bad regex | exit 1 |
| doctor on the bad regex | reports it |
| `policies test --tool write 'write path="main.py"'` with the warn fixture | `allow`, policy hit reported, no classifier verdict |
| a valid store | every existing test and golden unchanged |

**RED:** the bad-regex and bad-JSON cases return `allow` on the base.

### P26-2 — the system prompt never drops state silently

**Status:** DONE (2026-09-25, merged 7b6544a) · **Size:** S · **Wave:** 38 · **Spec:** `agent-loop.spec.md` req. 30

**Trigger:**
- A `SOUL.md` of 21.9 KB → `MEMORY.md` truncated.
- A `SOUL.md` of 24.4 KB → `HEARTBEAT`, `AGENTS`, `TOOLS` and `MEMORY` all absent from
  `system_prompt_for_agent`, with **no marker** (`identity.py:_runtime_workspace_context` returns
  `""` when the header does not fit, and `break`s after the first truncation).
- This violates req. 30 ("mark any truncation/omission visibly").

**Goal:**
- Protected order: the runtime contract, then `HEARTBEAT` state, then `TOOLS`, are never dropped
  in favour of `SOUL`.
- An oversized `SOUL` is truncated visibly first.
- Every omitted section gets a one-line marker naming it and its size.
- Each composition emits a `prompt_composed` trace event: per section, the bytes included and
  whether it was full, truncated or omitted.

**Non-goals:** changing the budget size (P26-3); new sections.

**Owns:** `core/identity.py` composition helpers, the trace call site in `core/agent_loop.py`, and
spec req. 30.

**Acceptance / oracle:**
- With the 24.4 KB fixture, the prompt contains the TOOLS verify-gate line and the HEARTBEAT ledger
  region, a `SOUL` truncation marker, and an omission marker for anything dropped.
- The trace event lists all four sections.
- A small workspace composes byte-identically to the base.

**RED:** the 24.4 KB fixture lacks `## TOOLS.md` and any marker.

### P26-3 — context budgets follow the resolved model window

**Status:** DONE (merged, worker commit `9f3926f`; dispatch hop-carryover and compaction budgets deliberately left on the fixed default — wiring them is a measured follow-up, not scheduled) · **Size:** M · **Wave:** 39 (after P26-2) · **Spec:** `agent-loop.spec.md` 1.20.0,
`session-history.spec.md` 1.5.0

**Trigger:**
- `identity.py:263` budgets state as `CONTEXT_TOKEN_BUDGET` × 4 bytes ≈ 24 KB for every model,
  16k and 200k windows alike.
- The hop handoff budget is the archetype `tokenBudget` (6000) whatever the window (`context.py`).
- The registered `contextWindow`/`maxTokens` are already read (`edges/adapters/llm.py:469-470`) and
  preflighted.

**Goal:**
- Default both budgets to documented shares of the resolved window, after the output reserve and
  tool schemas.
- `CONTEXT_TOKEN_BUDGET` and an archetype `tokenBudget` stay **explicit overrides** when set.
- `docket maintain check` and the `prompt_composed` event report the effective budget and its
  source.
- On an unregistered window, keep today's constants and say so.

**Non-goals:** changing `AGENT_LOOP_TOKEN_BUDGET` (a cost stop, not a context budget); compaction
changes.

**Owns:** the budget resolution in `core/identity.py` and `core/context.py`, and the window
plumbing from `DocketDriver` into `LoopConfig`/`ToolContext`.

**Acceptance / oracle:**
- A 200k-window provider fits the 24.4 KB `SOUL` fixture with every section full.
- A 16k window keeps today's behaviour, via P26-2's protected order.
- The request preflight still passes on the local endpoint.
- A live dispatch on the 16k endpoint reaches the same terminal state as the base.

**RED:** the 200k fixture still drops sections on the base.

### P26-4 — pod settings are typed, validated and writable

**Status:** DONE (2026-09-26, merged acf471f) · **Size:** M · **Wave:** 38 · **Spec:** `pod-dispatch.spec.md`,
`cli-json-shapes.spec.md`

**Trigger:**
- `maxReworkCycles`, `turnTimeoutS` and `verifyTimeoutS` are writable only by hand-edit or the
  hidden `_json meta-set`.
- Invalid values silently become defaults (`dispatch.py:434-463`).
- `profile --budget` stores `budgetUsd` as the raw string (`cli/__init__.py:934`).
- This **reverses D-41's "not scheduled"** for a timeout writer (see D-42 for what changed).

**Goal:**
- One Pydantic `PodSettings` model over the Lead-meta keys.
- `docket pod <p> config [get|set|unset] [<key> [<value>]]`, with `--json` on `get`. Values are
  validated at write and audited (`pod.config`).
- Dispatch reads the model. An invalid stored value **refuses** dispatch with the key and the
  reason, instead of defaulting.
- Doctor flags it.
- `profile --budget` writes a number.

**Non-goals:** new setting semantics. Later cards add their keys (`approvalMode`, `pipeline`,
`allowCommands`) to this model.

**Owns:** the new model in `core/pod.py`, the `dispatch.py` pod-setting readers, `cli/_pod.py`
config, and the `profile --budget` write.

**Acceptance / oracle:**
- `set maxReworkCycles 2` → `pipeline plan` shows 2.
- `set turnTimeoutS abc` → exit 1, and the meta is unchanged.
- A hand-written `"turnTimeoutS": "abc"` → dispatch refuses, naming the key.
- `budgetUsd` is persisted as a number.
- Goldens change only for the new help text, with every diff line explained.

**RED:** `pod <p> config` does not exist, and an invalid stored timeout dispatches.

### P26-5 — unattended turns can refuse instead of waiting on nobody

**Status:** DONE (merged `971cb4c`, worker commit `25186d3`) · **Size:** S · **Wave:** 39 (after P26-4) · **Spec:** `pod-dispatch.spec.md` 6.11.0,
`security-gates.spec.md` 0.23.0

**Trigger:**
- On the 2026-09-25 real dispatch, the tester hop failed on 3 × `approval_timeout`, having waited
  120 s each with no channel able to answer.
- Only harness mode can refuse (`DOCKET_APPROVAL_MODE=refuse`, set at `cli/_harness.py:185`).
  Serve, schedules, webhooks and MCP always wait (`docket_runtime.py:201-204`).

**Goal:**
- A pod setting `approvalMode: wait|refuse` (default `wait`, today's behaviour) is threaded into the
  hop's tool env.
- `refuse` ends the call at once with the existing `approval_unavailable` shape naming the tool,
  call and policy.
- The task fails with that reason, recorded in the run and the trace.

**Non-goals:** channel-liveness detection; changing the default.

**Owns:** the hop tool-env builder in `core/dispatch.py`, plus the `PodSettings` key.

**Acceptance / oracle:**
- With `refuse`, an asking call ends the hop well under one approval timeout, with a named reason.
- With `wait`, behaviour is identical to the base.

**RED:** there is no pod-level refuse, and the hop waits the full timeout.

### P26-6 — a pipeline file can be a pod's default for every trigger

**Status:** DONE (merged `c12dae5`, worker commit `e06a401`; follow-up noted: serve.py webhook calls `effective_pipeline` without catching the new bound-pipeline `DispatchError`) · **Size:** M · **Wave:** 39 (after P26-4) · **Spec:** `pipeline-format.spec.md` 2.3.0,
`pod-dispatch.spec.md` 6.12.0 (re-versioned from the worker's 6.11.0 — collided with P26-5)

**Trigger:** only `cli/_pod.py:575` and `cli/_pipeline.py:167,205` pass `spec=`. `serve.py:453,503,1064`
(sweep, schedule, webhook) and `cli/_mcp.py:127` always run the blueprint default, so a declared
pipeline can never run unattended. This is the unwired-machinery shape.

**Goal:**
- `docket pod <p> config set pipeline <file>` validates the file, plans it against the roster, and
  stores a docket-owned copy plus its hash in the Lead workspace.
- `effective_pipeline(project, None)` resolves that pipeline before the blueprint, for every
  trigger.
- `unset` restores the blueprint default.
- `pipeline plan <p>` names the source.
- The spec states `maxReworkCycles` precedence.

**Non-goals:** new dialect features; multiple pipelines per pod.

**Owns:** `core/dispatch.py::effective_pipeline` and `_blueprint_pipeline`, plus the `PodSettings`
key.

**Acceptance / oracle:**
- With a bound pipeline, a serve sweep and an MCP dispatch execute its steps (trace step ids).
- An unbound pod is unchanged.
- A roster missing a step's role is refused at `set`, not at run.

**RED:** a serve-sweep dispatch ignores the bound file.

### P26-7 — custom roles and steps carry their own hop instructions; `variables` get a consumer

**Status:** DONE (merged `3d63caa`, worker commit `b096fdf`) · **Size:** M · **Wave:** 39 · **Spec:** `role-archetypes.spec.md` 1.8.0,
`pipeline-format.spec.md` 2.4.0 (re-versioned from the worker's 2.3.0 — collided with P26-6)

**Trigger:**
- `dispatch.py:571-572,639`: any role outside lead, implementer, reviewer and tester gets
  `instructions = ""`, so a custom verdict-gated role is never told its marker.
- `resolve_variables` only stores values on the run record (`runs.py:285`).

**Goal:**
- An archetype field `hopInstruction`. A gated role without one gets an instruction generated
  from its `gateContract`.
- An optional pipeline step field `instructions` overrides the role's.
- `${var}` in step instructions is interpolated from the run's resolved variables, which today
  arrive by webhook. Add `--var k=v` to `pipeline run`.
- An unresolved variable refuses the run.

**Non-goals:** variables anywhere else (env, commands).

**Owns:** the hop-message builder in `core/dispatch.py`, the archetype field in
`core/archetypes.py`, the step field in `core/pipeline.py`.

**Acceptance / oracle:**
- The §3.4 `security-reviewer` role's hop message contains its marker instruction.
- A step `instructions: "Focus on ${area}"` with `--var area=auth` renders "Focus on auth".
- The four built-in roles are byte-identical to the base.

**RED:** the custom role's hop message has no instruction.

### P26-8 — a pod can allow its own tool binaries, scoped and audited

**Status:** DONE (merged `1184eb8`, worker commit `1fe5428`) · **Size:** S · **Wave:** 39 (after P26-4) · **Spec:** `security-gates.spec.md` 0.24.0 (re-versioned from the worker's 0.23.0 — collided with P26-5)

**Trigger:**
- `classify_command('pytest -q')`, `('uv run pytest')` and `('python -m pytest')` → `ask`.
- W37-C1 added builtins only, so an unattended tester or implementer on a `uv`/`pytest` project
  must ask, or be told to use `python3 -m`.

**Goal:**
- A pod setting `allowCommands` holds exact binary basenames. Validation rejects paths, shell
  metacharacters, the opaque builtins (`eval`, `exec`, `source`, `.`) and anything that names a
  high-risk class.
- It is carried on `ToolContext` for that pod's turns and merged into the allowlist check only.
- Opaque markers, high-risk classes and policies still apply, most-restrictive-wins.
- `set` is audited.

**Non-goals:** a global allowlist edit; argument patterns; per-agent scope.

**Owns:** `core/security.py::classify_command` (an extra-bins parameter), the `ToolContext` field
and its single use in `core/tools.py::evaluate_tool_call`, and the driver plumbing.

**Acceptance / oracle:**

| Command, in a pod with `allowCommands: [pytest, uv]` | Result |
| --- | --- |
| `pytest -q` | allow |
| `uv run pytest` | allow |
| `uv run pytest && git push origin main` | still asks |
| a `block` policy on `pytest` | still denies |
| `pytest -q` in another pod | still asks |

**RED:** `pytest -q` asks with the setting present.

### P26-9 — generated instructions agree with the runtime contract

**Status:** DONE (merged, worker commit `17c41c9`; known gap recorded in the spec: `cli/_agents.py`/`cli/_install.py` carry their own copy of the same HEARTBEAT-write contradiction for standalone agents and org specialists — small follow-up card) · **Size:** S · **Wave:** 40 · **Spec:** `workspace-structure.spec.md` 1.10.0,
`role-archetypes.spec.md` 1.9.0

**Trigger:**
- The AGENTS red line "Before starting multi-step work, write it to HEARTBEAT.md"
  (`archetypes.py:330,452`) reaches the model, while the runtime contract says private state is
  read-only (`identity.py:178`).
- `WORKFLOW_AUTO.md` tells agents to `cd` and to write `memory/` (`memory.py:114-171`), but is
  never sent.

**Goal:**
- Rewrite the built-in role templates so nothing sent to the model asks for a private write or a
  `cd`.
- Keep `WORKFLOW_AUTO.md` only as the manual-path contract, with a header saying so.
- Bump `POD_TEMPLATE_VERSION`.

**Non-goals:** new template content beyond removing the contradictions.

**Owns:** the built-in template strings in `core/archetypes.py`, `core/memory.py::seed_contract`
text, and the pod template version.

**Acceptance / oracle:**
- A grep-free structural test composes each built-in role's prompt and finds no instruction to
  write `HEARTBEAT.md`/`memory/`.
- Workspace goldens are regenerated, with each line explained.

**RED:** the implementer's composed prompt contains the HEARTBEAT write instruction.

### P26-10 — operator instructions survive regeneration, and roles can be re-rendered

**Status:** TODO · **Size:** M · **Wave:** 40 (after P26-9) · **Spec:** `workspace-structure.spec.md`,
`agent-loop.spec.md` req. 30

**Trigger:**
- `pod set-verify` rewrites `TOOLS.md` wholesale (`cli/_pod.py:374-399`).
- An archetype change never reaches existing members (templates render once at provisioning).
- `POD_TEMPLATE_VERSION` is never compared (`pod_provisioning.py:37,336`; doctor skips pod members
  at `_doctor.py:372,738`).

**Goal:**
- An operator-owned `INSTRUCTIONS.md` per member that docket never writes, composed right after
  `SOUL.md` and inside P26-2/P26-3's budget.
- `docket pod <p> sync [--dry-run]` re-renders `SOUL`, `AGENTS` and `TOOLS` from the current
  archetype and meta for members whose template or archetype version is stale, and shows a diff.
- Doctor flags stale pod members.

**Non-goals:** merging operator edits made inside generated files (they move to
`INSTRUCTIONS.md`).

**Owns:** the overlay read in `core/identity.py`, a re-render function in
`core/pod_provisioning.py`, `cli/_pod.py` sync, and a doctor check.

**Acceptance / oracle:**
- `INSTRUCTIONS.md` text reaches the prompt and survives `set-verify` and `sync`.
- After editing an overlay role, `sync --dry-run` shows the diff and `sync` applies it.
- An untouched pod is a no-op.

**RED:** `set-verify` destroys an operator line in `TOOLS.md`, and `sync` does not exist.

### P26-11 — `docket config explain <agent>`: the effective configuration with provenance

**Status:** TODO · **Size:** M · **Wave:** 40 (after P26-3, P26-4, P26-6, P26-8) · **Spec:**
`cli-json-shapes.spec.md`

**Trigger:** there is no command that answers "what will this agent see and be allowed to do". The
2026-09-25 guide needed two code-tracing audits to find out.

**Goal:** a read-only command, with `--json`, that composes existing functions only. It prints, each
with the source that set it (meta/policy/pin, pod setting, env, default):
- the resolved model and endpoint;
- each prompt section with its bytes and fit status (from P26-2's composer);
- tools after denials, including MCP;
- the policies that apply to the role;
- the effective pipeline and its source;
- budgets, timeouts, `approvalMode` and `allowCommands`.

**Non-goals:** writing anything; a second composer.

**Owns:** a new `cli/_config.py`, and a golden for its help.

**Acceptance / oracle:** for the §3.4 fixture pod, every value matches what a real dispatch uses
(asserted against the trace of a run on the fake driver). A pinned model shows `pinned`.

**RED:** the command does not exist.

### P26-12 — configuration errors are loud; schedules get a writer

**Status:** TODO · **Size:** S · **Wave:** 40 · **Spec:** `pod-dispatch.spec.md`,
`model-profiles.spec.md`, `role-archetypes.spec.md`

**Trigger:** silent skips at:
- `schedule.py:189,196` (a bad spec is never due; a bad file is `{}`);
- `models_policy.py:256-285` (malformed entries ignored);
- `archetypes.py:664` (overlay role skipped).

`docket-schedules.json` has no writer, and `record_last_run` drops unknown keys.

**Goal:**
- Doctor reports each of these with file, key and reason.
- `docket pod <p> config set schedule "<spec>"` validates and writes through `edges/store.py`;
  `unset` removes it.
- Serve logs a skipped spec once per sweep.

**Non-goals:** new schedule formats.

**Owns:** the doctor check functions, the schedule write path in `core/schedule.py`, and the
`PodSettings` routing for `schedule`.

**Acceptance / oracle:**
- `set schedule "@every 3x"` → exit 1.
- A hand-broken models entry → doctor error naming it.
- A valid schedule set by the command fires under `serve --dispatch`.

**RED:** doctor is silent on all three fixtures.

### P26-13 — secrets are stored once, where they are read

**Status:** DONE (2026-09-25, merged 7ea025a) · **Size:** S · **Wave:** 38 · **Spec:** `api-keys.spec.md`

**Trigger:**
- `cli/_keys.py:95-122` writes every stored key as plaintext into each project workspace's `.env`
  (`write_text` and then `chmod`, so the file briefly carries umask permissions), and nothing
  reads it.
- `DOCKET_SECRETS_BACKEND=keyring` never stores: `edges/adapters/system.py` has lookup only.

**Goal:**
- Stop writing `.env`. `doctor --fix` removes existing copies.
- The keyring backend stores through `secret-tool store`, or `keys add` refuses under `keyring`
  with an honest message. Choose one in the card.

**Non-goals:** new backends; rotation policy.

**Owns:** `cli/_keys.py`, `edges/adapters/system.py` (secret-tool), and a doctor check.

**Acceptance / oracle:**
- After `keys add`, no workspace contains `.env`.
- Turn key resolution is unchanged (the existing endpoint tests pass).
- Under `keyring`, the value is not in `secrets.json`.

**RED:** `keys add` creates `.env` files.

### P26-14 — one default model of record; provider fields that mean something

**Status:** TODO · **Size:** S · **Wave:** 40 · **Spec:** `model-profiles.spec.md`

**Trigger:**
- `fleet.json` `defaults.model` is read only by the hidden `_json default-model-get`
  (`cli/__init__.py:2680`), and it diverges from `docket-models.json` `default` on a fresh install.
- The provider `name` defaults to the literal "Qwen3 30B-A3B (local)" (`provider.py:31`) even with
  `--model qwen`.
- `name`, `cost`, `reasoning`, `input` and `api` are never read.
- `rankAnchors` is live (it maps `modelClass` cheap/strong) but is documented as private.

**Goal:**
- `docket-models.json` `default` is the only default. The fleet key is migrated away and ignored.
- The label derives from `--model`.
- Unread provider fields are dropped or documented as display-only.
- The spec and `CONFIGURATION.md` describe `rankAnchors` truthfully.

**Non-goals:** pricing.

**Owns:** `core/provider.py`, the default-model read and write in `core/fleet.py`/`cli/_install.py`,
and `model-profiles.spec.md`.

**Acceptance / oracle:** after init plus `preset local`, one default exists and matches what agents
resolve. `provider add x url --model m` labels the entry `m`.

**RED:** the two defaults differ after a fresh init.

### P26-15 — registries stay bounded; traces are filed where an operator looks

**Status:** TODO · **Size:** M · **Wave:** 40 · **Spec:** `pod-dispatch.spec.md`, `audit.spec.md`
(retention wording), the trace spec section

**Trigger:**
- This machine: `~/.docket/docket-runs.json` is 9.45 MB with 23,925 runs, rewritten together with a
  same-size `.bak` on every update.
- `approvals/` and `docket-conversations.json` are never pruned either.
- Approval trace events are filed under the agent id (`docket_runtime.py:215` →
  `approval.py:158-160`).
- The `config.py:41-44` audit-rotation comment is stale.
- (Withdrawn 2026-09-25: `guardrail_block` carrying the policy id as `payload.action` is
  **contractual** — security-gates.spec.md req. 4, `cli/_metrics.py` keys its tally on it.)

**Goal:**
- Terminal runs, resolved approvals and closed conversations older than a retention knob (default
  as `TRACE_RETENTION_DAYS`) are removed by the same sweep that expires traces, and by a command.
- Live and pending records are never touched.
- Approval events are filed under the pod.
- Fix the comment.

**Non-goals:** changing audit-log retention (a separate, non-lossy record).

**Owns:** the prune functions in `core/runs.py`, `core/approval.py` and `core/conversations.py`,
the serve sweep call, the `ToolContext.project` value in the driver, and `dispatch.py:260,1181`.

**Acceptance / oracle:**
- A fixture of 10,000 old terminal runs plus 1 running run → after the sweep only the running run
  and the recent ones remain.
- The approval trace lands in `traces/<pod>/`.

**RED:** nothing prunes, and the approval trace sits in `traces/<agent-id>/`.

### P26-16 — lifecycle hygiene, and the `gates enable/disable` decision

**Status:** DONE (2026-09-25, merged 38f6764) · **Size:** S · **Wave:** 38 · **Spec:** `agent-lifecycle.spec.md`,
`security-gates.spec.md`

**Trigger:**
- `docket delete` removes the worktree but never the `docket/<pod>/<member>` branch
  (`pod_provisioning.py:530-548`).
- `.pod-provision-locks/<hex>` is never removed (`:433-434`).
- `workspaces/`, `pods/<p>` and the lock directories are created 0775 (`_install.py:433-435`,
  `pod_provisioning.py:434,454`).
- `gates enable/disable` writes a flag nothing on the live path reads (W34-A1).
- `init --no-gates` prints "recorded as off" and writes nothing (`_install.py:120-122`).

**Goal:**
- `delete` removes the branch when it is merged into the codebase's current branch, and otherwise
  keeps it and prints how to delete it.
- Lock directories are removed with the pod.
- Directories are created 0700.
- **Default unless the maintainer answers otherwise:** retire `gates enable/disable` into a
  removed-command notice that points at `pod <p> config set approvalMode` (P26-5), and make
  `--no-gates` print nothing false.

**Non-goals:** changing isolation (`gates isolate`), which is wired.

**Owns:** teardown in `core/pod_provisioning.py`, the mkdir sites, `cli/_gates.py`, `__main__.py`
`_REMOVED`, and the `--no-gates` branch.

**Acceptance / oracle:**
- A merged branch is gone after `delete`; an unmerged one survives with a message.
- The new directories are 0700.
- `docket gates enable` prints the notice.

**RED:** the branch survives a merged `delete`, and the directories are 0775.

### P26-17 — opt-in project instructions from the codebase (the AGENTS.md convention)

**Status:** TODO · **Size:** S · **Wave:** 40 (after P26-10) · **Spec:** `agent-loop.spec.md`
req. 30

**Trigger:**
- A repository states its conventions in `AGENTS.md`/`CLAUDE.md` at its root. This repository and
  the `docket-dev` pod's codebase do.
- A docket agent sees them only if it chooses to `read` them, and the explicit request asks for
  standard configuration.

**Goal:**
- A pod setting `projectInstructions` holds relative paths inside the codebase root (default
  unset, so nothing changes).
- Those files are composed after `INSTRUCTIONS.md`, inside the budget, with the P26-2 markers.
- Each file is screened by `pre_input` as untrusted input on every composition.
- A missing file is a visible marker, not an error.

**Non-goals:** auto-discovery without opt-in; recursive includes.

**Owns:** one section source in `core/identity.py`, plus the `PodSettings` key.

**Acceptance / oracle:**
- With `projectInstructions: [AGENTS.md]`, the fixture repo's line reaches the prompt.
- A path escaping the root is refused at `set`.
- An injection-pattern line trips the `pre_input` policy.

**RED:** the line is absent with the setting present.

### P26-18 — pod membership is read from recorded metadata, never guessed from the id string

**Status:** DONE (2026-09-25, merged c326796) · **Size:** S · **Wave:** 38 · **Spec:** `pod-dispatch.spec.md`,
`role-archetypes.spec.md`

**Trigger (deterministic, live 2026-09-25):** a custom role `security-reviewer` passes
`roles add`, `pod proj add security-reviewer` (workspace provisioned, meta records
`"pod": "proj"`) and `pipeline plan --file` — then `pipeline run --file` fails its step with
`DispatchError: refusing cross-pod dispatch: 'proj-security-reviewer' is not in pod 'proj'`.
Cause: `core/pod.py::pod_of` rpartitions the id; the tail `reviewer` is a registered role, so it
answers pod `proj-security`. Any custom role whose name ends in a registered role name is
provisionable but not dispatchable. The authoritative facts (`pod`, `role`) already sit in
`.docket-meta.json` and `pod_of` never reads them.

**Goal:** membership and role resolution on the dispatch path read the member's recorded meta
(`pod`, `role`) first, falling back to id parsing only for a member with no meta; `pod add`
refuses a role name that the id grammar cannot round-trip **only if** the meta-first resolution
cannot cover it (goal is to cover it); a regression test provisions a `<x>-reviewer`-named custom
role and dispatches through it.

**Non-goals:** changing the member-id naming scheme; migrating existing ids.

**Owns:** `core/pod.py::pod_of` (and its callers' expectations), the dispatch membership check at
`core/dispatch.py:1477-1480`, their unit tests.

**Acceptance / oracle:** the exact live reproduction (custom role `security-reviewer`, fake
driver) dispatches to `done`; `pod_of('proj-security-reviewer')` returns `proj` when that member's
meta exists; a genuinely cross-pod member id is still refused; `members_of`/`next_index` behaviour
for built-in roles is byte-identical.

**RED:** the reproduction raises the cross-pod refusal on the base.

### P26-19 — a deterministic dispatch refusal settles the claim; an orphaned task is recoverable

**Status:** DONE (2026-09-26, merged 1781c73) · **Size:** S · **Wave:** 38 · **Spec:** `pod-dispatch.spec.md`

**Trigger (live 2026-09-25):** the P26-18 refusal raised out of `dispatch_pod` after the build
hop. The claim was never settled, so the task sat `running` with no process. Recovery deadlock:
`cli/_pod.py` refuses to start a dispatch when nothing is `pending` or `failed`+`stale_claim`, so
the in-dispatch stale sweep that would fail the orphan can never run until a *new* task is
queued. `--resume` does not see a `running` task, and `queue --retry` only moves `blocked` ones.

**Goal:** a deterministic refusal inside a claimed task (membership, config validation, unknown
member) fails **that task** with a named reason and settles its claim instead of raising out of
the whole dispatch; the CLI's "anything to do?" gate also counts stale-claimed `running` tasks
when `--resume` is passed, so recovery needs no decoy task.

**Non-goals:** changing crash semantics (the stale sweep stays the recovery for real crashes);
retrying deterministic refusals.

**Owns:** the claim/refusal lifecycle in `core/dispatch.py` (the `DispatchError` raise sites
inside a claimed task and the finalize path), the resumable filter in `cli/_pod.py:542-551`.

**Acceptance / oracle:** with the P26-18 reproduction on the base pipeline (before its fix), the
task ends `failed` with the refusal as its reason, the queue shows it, and `--resume` after fixing
the pipeline file re-runs it from the last persisted hop — no `CLAIM_STALE_TIMEOUT` override, no
decoy task. A mid-hop kill -9 still leaves `running` and is swept as today.

**RED:** on the base, the task stays `running` and `pipeline run --resume` answers "No pending
tasks".

### P26-20 — shipped recipes: role + pipeline + policy bundles that are tested, real and configurable

**Status:** TODO · **Size:** M · **Wave:** 40 (after P26-6, P26-7, P26-18) · **Spec:**
`pipeline-format.spec.md`, `role-archetypes.spec.md`, `workspace-structure.spec.md` (shipped-data
section)

**Trigger (explicit request, 2026-09-25):** configuring the pipeline, guardrails and policies is
to be a principal, reviewed feature, and the templates/recipes the repo ships must be robust for
real use yet easily configurable. Today the wheel ships only `templates/policies/` (6 files);
there is no shipped pipeline or role, and the E2E audit showed a first recipe attempt trips
P26-18 at dispatch.

**Goal:** a `templates/recipes/<name>/` tree shipped in the wheel, each recipe holding role
YAML(s), a pipeline YAML, an optional policy pack and a README that states what it is for and the
exact commands to apply it (`docket roles add`, `docket pod <p> add <role>`,
`docket pod <p> config set pipeline`, copy policies). Ship at least three: `secure-build`
(implementer + security vetter, verdict gate, one rework cycle), `research-review` (over the
research blueprint, critic verdict), `ops-approval` (operator + human approval gate). CI
validates every recipe: `roles validate`, `pipeline validate`, `policies validate`, and a
`pipeline plan` against a fixture pod; one integration test dispatches `secure-build` end to end
on the fake driver. `docs/CONFIGURATION.md` §3 points at them.

**Non-goals:** a `docket recipes` command or any new CLI surface (applying uses existing
commands; revisit only if three real applications show the manual steps are the friction — rule
of three); auto-applying policies on `init`.

**Owns:** `templates/recipes/` (new, data only), the packaging include in `pyproject.toml`, the
validation tests (default lane: they read data the wheel ships, not prose), a
`docs/CONFIGURATION.md` §3 pointer.

**Acceptance / oracle:** a fresh fixture pod applies `secure-build` using only documented
commands and dispatches to `done` on the fake driver, with the vetter's verdict gate observed in
the trace; every recipe file passes its validator in CI; the wheel contains the recipes
(`python -m build` + unzip listing, or the existing wheel-content test extends).

**RED:** `templates/recipes/` does not exist and no test validates any shipped pipeline.
