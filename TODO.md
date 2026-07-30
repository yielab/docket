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

## Wave 3 — in flight

Six cards, chosen so each owns a distinct file footprint. `G-1` is the wave's single
`core/dispatch.py` owner.

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

## Wave 4 — queued (blocked on wave 3)

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

## Known-open gaps carried forward (do not let these get quietly re-claimed)

From Phase 14's honest record — these are **still true** until the cards above close them:

- Cancellation of an in-flight hop and parallel hop execution are **not implemented** (Phase 16 W-2).
- `docket models set/preset/reset` still write **no audit entry** (G-4 follow-up).
- Enforcement exists **only** in the pod-dispatch lane — spend or actions from a Telegram session or
  direct daemon use are entirely ungated, per D-9's "docket orchestrates hops" boundary.
- Per-argument daemon enforcement for allowlisted bins (`git`, `npm`) still does not exist (G-3 narrows
  this where docket itself launches the process; the daemon-side half remains backlog).
- `maxReworkCycles` has no dedicated CLI setter (set via the internal `meta-set` path).
