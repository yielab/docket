# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> *Phase 13 (Close the differentiation gaps, FD-0…FD-7) is **COMPLETE** (2026-07-02).*
> *Phase 14 (Platformization I: runtime truth & dispatch hardening, R-1…R-8) is **COMPLETE**
> (2026-07-30) — its durable record lives in ROADMAP.md's Phase 14 section, including the honest
> "what was narrowed or deferred" list. Its board was cleared per the convention above. The two
> defects R-8 found but left unfixed (a stray merge-conflict marker in `serve.py`'s docstring and a
> backwards precedence comment in `config.py`) were fixed on `platform` in `facc78c`.*
>
> ---
>
> ## Active: PHASES 15 · 16 · 18 — Platformization II/III/V, executed in waves
>
> Executable board for **Phases 15, 16 and 18** in [ROADMAP.md](ROADMAP.md) (read those sections
> first — the defect rationale, the anti-overengineering rules, and each phase's exit criteria; also
> decisions **D-14/D-16/D-18** in §6 and the 2026-07-30 Platformization amendment in §4.5). Source of
> record: `internal-docs/agent-platform-audit-and-build-plan.md` (2026-07-29 four-pass platform audit,
> gitignored local rationale — every defect below was code-verified with file:line evidence and is
> restated self-containedly here).
>
> **Why three phases at once.** ROADMAP marks Phase 18 *"independent of 15–17 except L-5"* and Phase 16
> *"after 14; G-1 for approval steps"*. With Phase 14 green, the genuine blockers are narrow, so cards
> are scheduled by **file contention** rather than by phase number. Phase 17 stays out of this wave:
> C-1 depends on Phase 16's W-5, and C-2/C-3/C-5 all want `core/dispatch.py`, which is spoken for.
>
> **Scheduling rule learned in Phase 14 (keep it):** `core/dispatch.py` is the contention hotspot —
> nine remaining cards touch it. **At most one in-flight card may own `core/dispatch.py` per wave.**
> Phase 14 proved the payoff: cards with disjoint file footprints (R-6, R-7) auto-merged onto the big
> R-1 rewrite with zero code conflicts, while the two cards that both edited `serve.py`'s dispatch
> call sites (R-2, R-3) produced the only genuinely dangerous merge of the phase — each had to be
> hand-reconciled or one card's feature would have been silently dropped.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** ROADMAP.md's section for the card's phase, §2 (Python ground truth), §4.5
   (architectural principles, incl. the 2026-07-30 Platformization amendment), [CLAUDE.md](CLAUDE.md),
   and the task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`
   (JSONL append logs are the one D-12 exemption). Every shell-out goes through `edges/adapters/`.
   `core/`/`edges/` never import `ui.py` or print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · the card's own spec updated with a version bump +
   changelog entry, **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** this program lives on the long-running **`platform`** branch (a deliberate
fork-candidate line — see ROADMAP §8). One short-lived `pc/<card-id>` branch per task → merged into
`platform`, never directly into `main`.

---

## ▶ NEXT SESSION STARTS HERE

**State at hand-off (2026-07-30):** `platform` is at **`8956cca`** ("Merge L-3"), working tree
clean, everything green — **1,403 tests** (1,399 passed / 4 skipped), 18/18 goldens, 20 specs
valid, `ruff` + `ruff format` + `mypy --strict` clean, `metrics.py --check` in sync.

**Wave 3 is fully merged.** Wave 4 was in flight when the session ended; each of its five agents
was told to commit defensively to its own `pc/*` branch. **First action next session:** run
`git log --oneline platform..pc/<card>` for each of `pc/w-2`, `pc/w-3`, `pc/w-7`, `pc/l-6`,
`pc/cl-1` to see what actually landed — an agent may have committed partial or gate-failing work
on purpose, so read each branch's commit body before merging anything. Treat a wave-4 branch as
**unverified** until you re-run the gates on it yourself.

**Merge order for wave 4** (lowest contention first, the rule that worked in Phases 14 and the
wave-3 merge): `pc/cl-1` → `pc/l-6` → `pc/w-3` → `pc/w-7` → `pc/w-2` last (it owns
`core/dispatch.py` and is the largest). Expect conflicts in `specs/README.md`'s index table and
`README.md`'s test count on nearly every merge — both are integrator-owned, resolve centrally.
**Never resolve a golden conflict by picking a side** — regenerate with
`bash tests/golden/run.sh capture <case> <shell>` and confirm the diff is only the expected
addition. That exact trap nearly deleted a shipped command from the completion surface this
session (W-6's `roles` vs L-3's `mcp` — neither side had both).

---

## Wave 3 — ☑ COMPLETE (2026-07-30, all six merged into `platform`)

Six cards, chosen so each owns a distinct file footprint. `G-1` was the wave's single
`core/dispatch.py` owner — and the rule paid off: L-1's driver swap and W-6's `cli/_pod.py`
rewrite both auto-merged onto G-1's much larger rewrite with **zero code conflicts**. Every
conflict in this wave was documentation.

**Shipped:** G-1 (approval-gated dispatch — `approval_create` finally has a production caller) ·
G-5 (`[GATE]` seam spike, answered **no** with a dated evidence trail against a live daemon) ·
W-1 (pipeline format) · W-6 (role archetypes; legacy roles byte-identical) · L-1 (RuntimeDriver
port; session-JSONL parsing out of `core/`) · L-3 (MCP server, 10 tools).

**Tree grew 1,112 → 1,403 tests, 17 → 20 specs, 35 → 37 commands.**

### G-1 — Approval-gated dispatch  *(Phase 15)*

**Status:** IN-PROGRESS · **Size:** M · **Branch:** `pc/g-1` · **Owns:** `core/dispatch.py`

The approval store's **missing producer**. The audit's single most damning finding: `core/approval.py`
is fully built, tested and documented, and `approval_create` has **zero production callers** — docket's
`apr-*` store and the daemon's exec prompt are disconnected systems.

- **Read:** `core/dispatch.py` (R-1's v2 state machine: `_claim_next_task`, `_persist_hop`,
  `_normalize_task`, `_sweep_stale_claims`, `retry_task`, `unblock_pod`, `_replay_pipeline_position`),
  `core/approval.py`, `cli/_approve.py`, `cli/_deny.py`, `serve.py`,
  `specs/functional/pod-dispatch.spec.md` v2.0.0.
- **Build:** a persisted `waiting_approval` state; a `require_approval` gate evaluated **pre-hop** from
  pod-level `requireApprovalRoles`; grant/deny (CLI **and** HTTP) genuinely resume/kill the run; the
  expiry sweep resolves **denied** (fail-closed), not today's read-by-nobody `expired`.
- **Acceptance gate:** [ ] gate fires → `waiting_approval` persisted · [ ] grant resumes at the right
  hop · [ ] deny fails terminally · [ ] expiry ⇒ denied · [ ] a `waiting_approval` task is not
  claimable by a concurrent dispatcher.
- **Out of scope:** policy-engine wiring (G-2 — leave a typed seam); pipeline `approval` steps
  (W-1/W-2 — do not invent a pipeline format).

### W-1 — docket-native pipeline spec  *(Phase 16)*

**Status:** IN-PROGRESS · **Size:** M · **Branch:** `pc/w-1` · **Owns:** new pipeline module

One Pydantic-modeled, **unknown-key-rejecting** YAML replacing the Lobster dialect docket lints but
cannot execute (D-16). Defines a format; **does not** write the executor.

- **Build:** ordered steps (`role|agent`), per-step `retries`/`timeout`/`gate`
  (mechanical-check | verdict | approval), bounded rework edges consistent with R-4's `maxReworkCycles`,
  `parallel` groups, variables. Steps reference W-6 archetypes **by name string** (validate shape, not
  existence, so the two cards compose without ordering).
- **Zero migration:** no pipeline file ⇒ today's built-in order, byte-identical.
- **Acceptance gate:** [ ] valid pipeline round-trips · [ ] unknown key rejected · [ ] each gate type
  validates · [ ] absent file ⇒ built-in order unchanged.
- **Out of scope:** the executor (W-2). Explicitly **do not** build a second pretty-printer — ROADMAP
  requires `workflow plan` to render from the real executor.

### W-6 — Declarative role archetypes  *(Phase 16)*

**Status:** IN-PROGRESS · **Size:** L · **Branch:** `pc/w-6` · **Owns:** `core/pod.py`, `cli/_pod.py`

The operator's explicit requirement: pods must orchestrate **diverse objectives, not just build a web
site**. Today `POD_ROLES` is a closed 4-tuple and every role identity is a hardcoded Python string, so
a research pod, a content pod, an ops pod are *inexpressible*.

- **Build:** versioned YAML archetypes (`name`, `scope`, `modelClass`, `soul`/`agents` templates,
  `gateContract`, `editRights`, `toolProfile`); the four legacy roles as built-ins; starter library
  (`researcher`, `analyst`, `writer`, `critic`, `operator`, `monitor`); `docket roles
  list/show/add/validate`; user overlay following the `docket-models.json` registry pattern;
  `normalize_role`/`member_id`/`POD_ROLE_POLICY` rewritten against the registry.
- **Hard requirement:** legacy roles emit **byte-identical** workspaces and keep their exact ids.
- **Anti-overengineering rule (ROADMAP, verbatim):** *no fifth role ever lands as a hardcoded string;
  archetype prose and rosters are user-extensible, but gate contracts, edit rights, and scope stay
  closed typed sets docket can reason about.*
- **Acceptance gate:** [ ] legacy output byte-identical (goldens) · [ ] user archetype overlays a
  built-in · [ ] unknown gate/right/scope rejected · [ ] legacy ids unchanged.
- **Out of scope:** blueprints (W-7); wiring gates into dispatch (W-8) — define `gateContract` as
  **data** only.

### L-1 — RuntimeDriver port  *(Phase 18, decision D-14)*

**Status:** IN-PROGRESS · **Size:** L · **Branch:** `pc/l-1` · **Owns:** ACL, `core/utils.py` cost slice

Closes the biggest ACL leak: session-JSONL cost parsing sits in `core/utils.py`, `trace_ingest` format
knowledge escapes the adapter, and there are 11 argv shapes for the `openclaw` binary.

- **D-14 constrains this card:** *one typed port, ONE shipped driver.* Containment of coupling that
  already exists — **not** a plugin framework. No driver discovery, no entry points, no
  config-selectable backends, no second real driver.
- **Build:** `run_turn / provision / teardown / list_sessions / usage / capabilities`; move session-JSONL
  and `trace_ingest` knowledge **inside** the OpenClaw driver; extend the ACL guard test to catch
  session-format parsing; a fake driver replacing ad-hoc test shims.
- **Acceptance gate:** [ ] `core/` contains zero OpenClaw on-disk-format knowledge, **guard-tested**
  (the test must genuinely fail if someone parses session JSONL in `core/`).
- **Coordination:** keep the `core/dispatch.py` call-site diff minimal — G-1 owns that file this wave.
  C-2 (later) makes docket's first self-originated LLM call through this driver per D-18.

### L-3 — docket as an MCP server  *(Phase 18)*

**Status:** IN-PROGRESS · **Size:** M · **Branch:** `pc/l-3` · **Owns:** new MCP module

MCP is the ecosystem's tool-interop standard and is **entirely absent** from docket (one repo-wide
mention, a disclaimer in SECURITY.md). Pure docket, no daemon capability needed — hence high leverage.

- **Build:** `docket mcp serve` (stdio, official `mcp` SDK **pinned** and shipped as an optional extra
  following the existing PyYAML optional-dep pattern) exposing `status, pods, queue, delegate,
  dispatch, runs, approvals list/grant/deny, cost`.
- **Critical constraint:** *through* the governance spine, not around it — every call audit-logged into
  G-4's `seq`/`prev_hash` chain, approvals unchanged, **no MCP-side bypass** of any control the CLI
  enforces. `dispatch` costs real money: gate it exactly as the CLI/HTTP paths do.
- **Scope guard (ROADMAP, verbatim):** *a full MCP host (docket executing MCP tools inside agent turns)
  is the standalone-runtime trap — refuse it.* This is a **server**. Agent-side MCP config is L-4.
- **stdio discipline:** stray stdout output corrupts the protocol stream — mind the Rich `ui.py` helpers.
- **Acceptance gate:** [ ] each tool's happy path · [ ] every call writes an audit entry · [ ] missing
  SDK ⇒ actionable hint, suite still green · [ ] no tool bypasses an approval gate.

### G-5 — the `[GATE]` seam spike  *(Phase 15, daemon-gated)*

**Status:** IN-PROGRESS · **Size:** S · **Branch:** `pc/g-5` · **Owns:** docs/spike

**A spike: the deliverable is a truthful answer, not code.** Question: *can the daemon's exec-approval
prompt notify an external hook?* Yes ⇒ bridge daemon prompts into docket approval tokens and the
`security-gates.spec.md` example becomes genuinely true. No ⇒ draft the upstream issue and the example
stays **explicitly labeled future**.

- **Evidence standard:** cite a file path, config key, doc URL or source line. Do not infer a capability
  from a plausible config name. Distinguish *confirmed absent* / *confirmed present* / *could not
  determine*. A well-evidenced "no" is a **success**; an unverified "yes" is the worst outcome.
- **Acceptance gate:** [ ] the spec tells the truth about what is enforced today, keeping the
  *docket-enforced / daemon-enforced / convention* labeling discipline.

---

## Wave 4 — IN FLIGHT when the session ended (check each branch before trusting it)

Five cards were dispatched, then cut short by the session limit. Each agent was told to commit
defensively to its own branch. **Verify each branch's real state before merging** — see the
"NEXT SESSION STARTS HERE" block at the top.

| Card | Branch | Owns | State at hand-off |
| --- | --- | --- | --- |
| **W-2 + W-8** · executor + generalized gates | `pc/w-2` | `core/dispatch.py`, new orchestrator, `cli/_pipeline.py` | **no commit** — research/design only; design captured below |
| **W-3** · Lobster retirement (D-16) | `pc/w-3` | `core/lobster.py`, `cli/_workflow.py`, workflow spec | **committed WIP at `1819695`** — deletions done, gates WILL FAIL; list below |
| **W-7** · pod blueprints + dead-shim removal | `pc/w-7` | `core/pod.py`, `cli/_pod.py`, `cli/_agents.py` | **no commit** — research only; findings below |
| **L-6** · migrate MCP to the current SDK | `pc/l-6` | `cli/_mcp.py`, `pyproject.toml`, mcp spec | **committed WIP at `28f2e10`** — killed by the session limit mid-test-writing; substantial progress, details below |
| **CL-1** · legacy/dead-code sweep | `pc/cl-1` | driver aliases, cost shapes, test doubles | **committed WIP at `9b741e0`** — partial; register mostly not started |

Two agents correctly reported having nothing to commit rather than fabricating an empty commit.
Their research is preserved below — it is genuinely most of the hard thinking for those cards.

### W-3 (`pc/w-3` @ `1819695`) — committed but **deliberately incomplete; gates fail**

Deleted: `core/lobster.py` (182 lines), `cli/_workflow.py` (235 lines),
`tests/python/test_cd7_lobster.py`, `specs/functional/workflow-integration.spec.md`. `docket
workflow`/`wf` now route through `__main__.py`'s `_REMOVED` map (the D-11 `team` pattern).
Verified: no `.py` file imports the deleted modules; the only remaining `lobster` mention is a
deliberate historical note in `core/pipeline.py:290`.

**Known-failing, must finish before merge:**

1. `tests/python/test_m4_wave3b.py` — delete `TestCmdWorkflow` (~lines 171-276) and the
   `["workflow", "x"]` parametrize entry (~line 283). **pytest fails until this is done.**
2. `tests/python/test_r3_runs_cli.py` — docstring references the deleted `test_cd7_lobster.py`.
3. Add `tests/python/test_w3_workflow_removed.py`, mirroring `test_ch4_team_removed.py`.
4. Specs: `specs/README.md` (tree + status table + "Removed so far" note),
   `api/cli-interface.spec.md` (replace the `docket workflow` section using the `docket team`
   precedent; bump to 1.9.0), `functional/pipeline-format.spec.md` (~6 dangling refs — reword as
   retirement notes, and do **not** claim `docket pipeline` exists yet; that is W-2's),
   `functional/agent-lifecycle.spec.md:22`, `functional/model-profiles.spec.md:246`,
   `api/mcp-server.spec.md:~100`.
5. Docs: `README.md` (lines ~233, ~306, ~327), `docs/commands.md` (TOC, the whole
   `## Workflow Management` section ~623-721, the `wf` alias row ~1825, add to Removed Commands),
   `docs/WORKFLOW-GUIDE.md:352` + workspace-tree diagram, `CHANGELOG.md` `[Unreleased] ### Removed`.
6. **Goldens stale** — `help.golden`, `completions_bash.golden`, `completions_zsh.golden` still
   contain `workflow`/`wf`/"Lobster". Recapture; verify the diff is only the removal.

### L-6 (`pc/l-6` @ `28f2e10`) — the SDK question is **answered**, migration mostly done

**The previous card's guess was wrong, and this was verified empirically against the installed
`mcp==2.0.0`, not assumed.** `mcp.server.fastmcp` was removed outright in 2.0 and replaced by
**`mcp.server.MCPServer`**. That is a **rename/relocation, not a redesign** — it keeps FastMCP's
exact ergonomics (`MCPServer(name=, instructions=)`, `add_tool(fn, name=...)`,
`server.run(transport="stdio")`), confirmed by probing the installed package directly and
exercising `list_tools`/`call_tool`/`add_tool`, `structured_content` for dict-returning tools, and
the `isError` path, live via `mcp.Client`'s in-memory transport.

So L-3's defensive `<2.0.0` ceiling was unnecessary. **The pin is now `mcp = ["mcp>=2.0.0"]`** and
the `pyproject.toml` comment has been rewritten to describe the real migration instead of the old
speculation.

**Remaining:** the L-6-specific test file (real 2.0 integration: `isError` path, no-ceiling pin
check) was being written when the session limit killed the agent. Re-run the full suite in **both**
configurations (with and without the `mcp` extra) — that dual-config guarantee is the one thing
most at risk of having silently broken.

### CL-1 (`pc/cl-1` @ `9b741e0`) — partial; read this before continuing it

**Done:** `edges/adapters/openclaw.py`'s `agent_run()` now uses `TurnResult` directly; comment
cleanup in `config.py:73`, `core/utils.py:~118`, `tests/evals/lib/eval-helpers.sh:74`; spec bump
`pod-dispatch.spec.md` 2.1.0 → 2.1.1.

**Two findings that change the card:**

1. **The alias cannot be deleted yet, and the reason is structural.**
   `AgentRunResult = TurnResult` (`edges/adapters/openclaw.py:930`) still has a real consumer:
   `core/dispatch.py:85`'s `Runner = Callable[..., _oc.AgentRunResult]` is a **module-level
   assignment evaluated at import time**, so removing the alias breaks importing `dispatch.py` —
   i.e. almost the whole CLI. `dispatch.py` is W-2's file. **Sequence this after W-2 merges.**
2. **The card's premise was partly wrong about `FailureKind`.** There is no `FailureKind = ...`
   alias in `openclaw.py` at all — only inline string literals. Nothing to collapse. (Grepped
   `_oc\.FailureKind` repo-wide: zero hits. Worth one confirming grep next session.)

**Not started:** ~76 test call sites still construct `_oc.AgentRunResult(...)` positionally
(`test_r2/r4/r5/r6/r7`, `test_cd2`, `test_dispatch`, `test_g1_*`, `test_l1_*`) — mechanical
rename to import `TurnResult` from `core.runtime_driver`. The legacy `CostTotals`/`DayRecord`
translation decision (same `dispatch.py` blocker applies). **The full-tree dead-code register —
the card's biggest ask — is essentially not started.**

**Test-double analysis worth keeping:** `FakeDriver` only does *constant per-role* behavior, so
`test_r2_retries.py`'s `_ScriptedRunner` (needs per-call sequences) and the
unparseable-verdict `_runner` (needs custom per-role output text) **must stay** — those are real
reasons, not inertia. The `_always_timeout` and `test_nonzero_exit_never_retries` closures *are*
drop-in `FakeDriver` replacements.

**Gates on `9b741e0` were NOT fully run** — only `ruff check` and a single-file mypy. Re-run
everything before trusting it.

### W-2 design (no code written — this is the plan to execute)

- **New `core/orchestrator.py`**: pure `resolve_plan(spec, roster) → ExecutionPlan`, used by
  **both** the executor and `docket pipeline plan` — one code path, satisfying ROADMAP's ban on a
  second pretty-printer. `resolve_gate(step, registry)`: the step's own `gate` wins; the
  archetype's `gateContract` is only a fallback when a step omits one. That ordering is what keeps
  `default_pipeline()` byte-identical — every built-in step sets an explicit gate, so the fallback
  never fires for the four legacy roles.
- **Avoiding an import cycle**: `orchestrator` imports `dispatch` at top level (one way);
  `dispatch.dispatch_task`/`dispatch_pod` keep their exact public signatures and call into
  `orchestrator` via a **deferred, in-function import** — the same trick `core/runs.py` already
  uses against `core/trace.py`. `HopResult`/`TaskResult` stay defined in `dispatch.py` for this
  reason; do not move them.
- **Cancellation — the root cause is identified.** `edges/adapters/openclaw.py`'s `agent_run` uses
  blocking `subprocess.run` and **never creates a process group**, which is exactly why
  cancellation has never existed. Fix: `subprocess.Popen(..., start_new_session=True)` (so
  `proc.pid` is also the pgid) plus an optional `on_spawn: Callable[[int], None] | None = None`
  fired immediately after spawn; kill via `os.killpg` on timeout, not `proc.kill()`.
- `core/runs.py`: a `ContextVar` for the current run id (set in `execute()`), `add_hop_pid` /
  `remove_hop_pid` over a **`pids: list[int]`** field (a list, not a scalar — a parallel group has
  several hops in flight), and `cancel_run(run_id)` doing SIGTERM → grace → SIGKILL per process
  group, with a new terminal state `"cancelled"`.
- **Only the production path passes `on_spawn`** (when `runner is None`), so no existing test
  fake needs changing — `FakeDriver`, `_SlowRunner`, `_CrashOnRoleRunner`, `_VerdictAwareRunner`
  all keep working untouched.
- `dispatch_pod`/`dispatch_task` need a new optional `spec: PipelineSpec | None = None` kwarg.
- Threads need `contextvars.copy_context()` propagated — `ThreadPoolExecutor.submit` does not do
  it automatically, and the run-id/pid tracking depends on it.
- **Two tests change purpose deliberately** (call it out in the diff, do not let it look
  incidental): `test_w6_archetypes.py:~146-161` and `test_w1_pipeline_spec.py:~583-628` currently
  assert the archetype regexes byte-match `dispatch.py`'s hardcoded patterns. Once gates unify,
  they become cross-checks against `orchestrator`'s resolved defaults.

**W-2 and W-8 ship as one card** — ROADMAP's hard sequencing rule forbids splitting them ("an
executor that hardcodes roles a second time forces a second migration").

**Integrator decisions already fixed, do not re-litigate:**

- The pipeline CLI surface is **`docket pipeline validate|plan|run`**. W-2 builds it; W-3's
  removed-command notice points at exactly these names.
- `docket pipeline plan` **MUST** render from the real executor — a second pretty-printer is
  explicitly forbidden by ROADMAP.

### Confirmed findings from W-7's research (verified independently — act on these)

1. **LIVE BUG — `docket doctor` flags every pod Lead/Reviewer/Tester as broken.**
   `cli/_doctor.py`'s `_WORKSPACE_FILES` (line 50) requires `TOOLS.md` for *every* project agent,
   but `cli/_pod.py` (line ~223) only writes `TOOLS.md` when
   `member.role == "implementer"` **and** resources or a verify command are set. Verified by
   reading both call sites; W-7 also reproduced it live (`demo-lead` → `✗ missing TOOLS.md`).
   This is pre-existing, affects every software pod **today**, and blocks W-7 besides: the
   `research`/`content`/`ops` blueprints have no implementer at all, so every such pod would be
   permanently "broken" per doctor. **Fix the check to be role-aware.**
2. **Spec drift:** `api/cli-interface.spec.md` still documents a `--type <repo|task>` flag that no
   longer exists, and `data/docket-meta.spec.md` still carries stale `type`-field remnants in its
   field rules and examples. Both predate this wave.
3. The dead `POD_ROLES`/`POD_ROLE_POLICY` PEP 562 shim is at `core/pod.py:293-307`, and
   `tests/python/test_w6_pod_registry.py::TestPodRolesAndPolicyDynamicAttributes` (lines 127-151)
   tests the shim itself — **delete both together**, or the test will fail the removal.
4. `docket add` has **two separate provisioning paths**: interactive `run_add` builds a real pod
   via `_pod.build_pod`, while declarative `--from` (`_cmd_add_declarative`) provisions single
   flat agents via `_provision_agent` and never builds a pod. W-7's card requires extending
   `--from` to understand blueprints — budget for that asymmetry.

---

## Wave 5 — queued

| Card | Phase | Blocked on | Note |
| --- | --- | --- | --- |
| **W-2 · Executor** | 16 | W-1 + W-6 | Runs W-1 specs over R-1's state machine; bounded worker pool, `runs cancel` kills the hop's process group. Renders `workflow plan` from the **real** executor. Wants `core/dispatch.py` — next wave's single owner. |
| **W-8 · Generalized gates** | 16 | W-6 + W-2 | Verdict/mechanical checks detach from tester/implementer and become gate types any step declares. |
| **W-7 · Pod blueprints** | 16 | W-6 | `software` (unchanged default), `research`, `content`, `ops`; restores a non-codebase `workdir` workspace path. |
| **W-3 · Lobster retirement (D-16)** | 16 | W-2 | `docket workflow` → removed-command notice (the D-11 `docket team` pattern); delete `core/lobster.py` + templates. |
| **W-4 · Durable scheduling + event triggers** | 16 | W-2 | Persisted last-run, cron specs, webhook params → pipeline variables, `dispatch --follow`. |
| **W-5 · Structured handoff artifacts** | 16 | W-2 | Typed `{summary, files_changed, diff_ref, verdict, notes}` per hop, replacing raw-text concatenation. **Gates Phase 17's C-1.** |
| **G-2 · Policy engine on the live path** | 15 | G-1 | `install` runs `policies init`; `pre_input` at enqueue, `pre_output` on every hop output; feeds G-1's `require_approval`. Gives `_metrics.py`'s existing reader a producer. |
| **G-3 · High-risk classes enforced** | 15 | G-2 | Wire `resolve_command_action` (today: **no callers**) into every process docket itself launches. |
| **C-2 · Memory distillation** | 17 | L-1 | `maintain distill`; `clean/reset` gain `--distill-first` — never bare-delete. docket's first self-originated LLM call, **through the driver** (D-18). |
| **C-3 · One durable task state** | 17 | dispatch owner | Dispatch writes HEARTBEAT entries mechanically; doctor flags TASK_LIST⇄HEARTBEAT divergence. |
| **C-5 · Conversation registry auto-population** | 17 | dispatch owner | Dispatch/serve update `last_message`/`task_ref`. |
| **C-1 · Context compiler** | 17 | W-5 | (task, role, artifacts, workspace) → hop message under a per-role token budget. Supersedes R-7's stopgap cap. |
| **L-4 · MCP config plumbing** | 18 | daemon capability | Spike; L-3 ships regardless. |
| **L-5 · Wrapped gateway** | 18 | daemon capability | Spike (D-18). Ship only if the daemon tolerates a base-url swap cleanly. Hand-rolled provider clients: **banned**. |

---

## Dead-code register (CL-1, 2026-07-30) — the standing "no legacy code" work list

Produced by a full-tree sweep. **Two entries were fixed and merged** (`ad8e14e`): `cli/_eval.py`'s
duplicate of `config.cli_root()`, and a stale `core/security.py` docstring. Everything below is
**found, verified, and not yet fixed** — mostly because the file belongs to an in-flight card.
Work these once the owning card merges.

### High confidence — fix these

| Finding | Location | Blocked by | Note |
| --- | --- | --- | --- |
| **`core/sync.py` is an entirely dead module** | whole file | W-7 owns `cli/_doctor.py` | `check_agent`/`check_all`/`Drift`/`SYNCED_FIELDS` have **zero** production callers. `cli/_doctor.py:280-334`'s `_check_drift` reimplements the identical model+sessionKey comparison inline without importing it. **Independently verified: zero `import sync` in `src/`.** Note CLAUDE.md describes this module as the thing that "keeps the two config sources in sync" — the docs and the code disagree. Prefer keeping `sync.py` as the single source and pointing doctor at it. `SYNCED_FIELDS` is dead even *within* `check_agent`, which hardcodes the field names instead of iterating it. |
| **`HEARTBEAT_FILE` constant unused; literal hardcoded 8+ times** | `core/memory.py:57` | W-7 | The string `"HEARTBEAT.md"` is repeated across `cli/_agents.py`, `_pod.py`, `_install.py`, `_context.py`, `_doctor.py`, `cli/__init__.py`. Same shape as the `openclaw-gateway.service` duplicate fixed in L-2. |
| **`print()` inside `core/` — a layering violation** | `core/dispatch.py:1118` | W-2 | `print(f"[dispatch] verification skipped...")` breaks the standing rule that `core/`/`edges/` never print; it should return a typed result for `cli/` to render. |
| **Zero-caller ACL functions** | `edges/adapters/openclaw.py:~126, ~172` | W-2 | `meta_write` and `set_agent_project_key` have no callers anywhere, tests included. |

### Medium confidence — verify before acting

| Finding | Location | Note |
| --- | --- | --- |
| `with_lock()` has no production caller | `edges/store.py:49` | `read_modify_write` has its own independent `_acquire` body rather than calling it; only `test_m2_data_layer.py` exercises it. **Re-check after W-2 lands** — W-2 is reworking the claim/locking path and may add a genuine call site. |
| `docker_ps()`, `git_current_branch()` | `edges/adapters/system.py:~166, ~223` | Zero production callers; each has a dedicated unit test. May be forward-looking scaffolding for a future doctor check rather than abandoned code. Genuinely ambiguous. |
| `validate_policy()` never called by the CLI | `core/policy.py:44` | Implemented and tested, but `cli/_policies.py`'s `_list()` does its own generic JSON parse. Either wire a `docket policies validate` command or remove it. |
| `VerifyResult.total_lines` written, never read | `core/audit.py:206` | Populated at 7 construction sites; no renderer or test reads it. |
| `dispatch_all_pods` flagged uncalled | `core/dispatch.py:1684` | Not investigated (W-2's file). |

### Deliberately NOT dead — do not "clean these up"

- `core/security.py`'s `high_risk_bins`/`resolve_command_action`/`match_high_risk`/`is_high_risk` —
  documented in-code **and** in CLAUDE.md as deferred infrastructure for a daemon capability that
  does not exist yet. Intentional, not orphaned.
- `core/pipeline.py`'s `validate_pipeline()` — its own docstring says it awaits W-2's wiring.
- `edges/adapters/openclaw.py` importing `core/models.py`/`oc_models.py`/`runtime_driver.py` — a
  documented schema-only exception (pure typing modules), **not** a layering violation.

### Confirmed false positives (dynamic access — checked, not dead)

`cli/__init__.py`'s ~35 `cmd_*` functions (Typer-registered) · `serve.py`'s
`do_POST`/`do_HEAD`/`log_message` (`BaseHTTPRequestHandler` overrides) ·
`ConversationStatus.waiting`/`.done` (constructed dynamically from `--status`) · every
Pydantic `model_config` · `RuntimeDriver` Protocol members (used via runtime `isinstance`).

**Swept and clean:** `scripts/` (all referenced), `templates/policies/*.json` (all seeded via the
glob copy), no unconditional skips, no vacuous tests.

### Still owed on CL-1's original card

The ~76 `_oc.AgentRunResult(...)` test call sites → `TurnResult`, the ad-hoc-double → `FakeDriver`
sweep, and the legacy `CostTotals`/`DayRecord` decision. **All blocked on W-2** releasing
`core/dispatch.py` and the dispatch-adjacent test families.

---

## Known-open gaps carried forward (do not let these get quietly re-claimed)

From Phase 14's honest record — these are **still true** until the cards above close them:

- Cancellation of an in-flight hop and parallel hop execution are **not implemented** (Phase 16 W-2).
- `docket models set/preset/reset` still write **no audit entry** (G-4 follow-up).
- Enforcement exists **only** in the pod-dispatch lane — spend or actions from a Telegram session or
  direct daemon use are entirely ungated, per D-9's "docket orchestrates hops" boundary.
- Per-argument daemon enforcement for allowlisted bins (`git`, `npm`) still does not exist (G-3 narrows
  this where docket itself launches the process; the daemon-side half remains backlog).
- `maxReworkCycles` has no dedicated CLI setter (set via the internal `meta-set` path).
