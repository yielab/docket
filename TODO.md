# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> ---
>
> ## Active: PHASE 10 — Agent architecture (project pods)
>
> Executable board for **PHASE 10** in [ROADMAP.md](ROADMAP.md) (read that section first — it has the
> problem statement, the pod model, and the exit criteria). Each task here is **self-contained** so a
> separate agent can claim and complete it independently. Rationale long-form:
> `internal-docs/agent-structure-analysis.md`.
>
> **What we're fixing (one paragraph):** docket's agent model flattens three independent dimensions —
> **role** (what it does), **scope** (whose data it sees), **lifecycle** (persistent vs per-task) — into
> one flat "agent type". That produces three defects: (A) the project agent and the shared `programmer`
> specialist are *both* doers, neither complete; (B) shared specialist **singletons** break the
> session-key isolation guarantee (one programmer serves every project in the same session); (C)
> "delegation" is markdown only — no runtime routing. The fix: make **scope** first-class, turn
> programmer/reviewer/tester into **project-scoped pod roles**, keep only genuinely cross-cutting roles
> (security, knowledge, optional Portfolio Manager) shared, and provision each project as an isolated
> **pod** sharing one session key.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** ROADMAP.md §2 (Python ground truth), §4.5 (architectural principles —
   esp. *docket is not in the execution path*), the Phase 10 section, [CLAUDE.md](CLAUDE.md), and the
   task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`.
4. **Honesty rule:** docket does not execute agents. Anything with a runtime aspect is *daemon-gated* —
   spike it (AA-0), isolate it (AA-7), and never overclaim runtime behaviour in docs.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add a golden case if
   output changes) · `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
   pytest` green · `bash tests/golden/run.sh verify-all` green · committed `Type: description` (no
   Claude/Co-Authored-By trailer) · public-repo privacy scrubbed.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs AA-x)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** one short-lived `pc/aa-<id>` branch per task → PR into the working branch (`python-core`).

---

## Dependency map (what unblocks what)

```text
AA-0  (spike: daemon capabilities)         ← BLOCKING, do first; decides AA-7 path
  │
AA-1  (scope axis on AgentMeta)            ← the root fix; unblocks everything below
  │
  ├─ AA-2 (reclassify specialists: org vs project-role)
  │     │
  │     ├─ AA-3 (pod provisioning in `docket add`)  ──┐
  │     │     └─ AA-4 (project-scoped role templates) │  AA-4 needs AA-3's pod shape
  │     │     └─ AA-5 (Lead role = manager+project)   │
  │     └─ AA-6 (org Portfolio Manager, optional)     │
  │                                                    │
AA-7 (real dispatch — DAEMON-gated, needs AA-0 + AA-3/4/5) 
AA-8 (list/doctor taxonomy + migration — needs AA-1, AA-2)
AA-9 (docs truth pass — last; needs AA-1..AA-6 landed)
```

Order to ship value fastest: **AA-0 → AA-1 → AA-2 → AA-3 → AA-4 → AA-5** lands the isolation fix
(Defects A+B). AA-6 is optional. AA-7 closes Defect C if the daemon allows. AA-8/AA-9 finish.

---

### AA-0 — Spike: daemon capabilities for pods & ephemeral workers
- **Depends on:** — · **Parallel-safe with:** AA-1 (AA-1 doesn't need the spike result)
- **Read:** `openclaw --help`, live `~/.openclaw/openclaw.json`, <https://docs.openclaw.ai/>, `edges/adapters/openclaw.py` (what docket can already drive), ROADMAP §4.5 (execution-path constraint).
- **Do:** Answer with evidence, recording each as supported / not-supported / unknown + the exact config/CLI:
  1. Can the daemon **spawn a sub-agent / ephemeral agent** on demand, or are all agents statically registered?
  2. Can one agent **dispatch work / send a message** to another *through the daemon* (not just Telegram), programmable from docket?
  3. Can **one registered role run multiple concurrent isolated sessions** keyed by different session keys (the "shared programmer serves N projects safely" question), or is session state per-agent-singleton?
  4. How is a **per-task session** created and torn down?
  Then make the call for AA-7: **real daemon dispatch** vs **operator-driven queue**. Prove ≥1 claim against the live daemon (e.g. a second session key accepted on one role, or shown impossible).
- **Out of scope:** any code change to docket; building dispatch (that's AA-7).
- **Deliverables:** `internal-docs/POD-DAEMON-NOTES.md` (capability table + AA-7 verdict). Not shipped in the wheel.
- **Acceptance gate:** [ ] capability table with evidence; [ ] explicit AA-7 verdict line; [ ] ≥1 claim proven against the live daemon.
- **Size:** M · **Status:** TODO

---

### AA-1 — Add the `scope` axis to the taxonomy (root fix)
- **Depends on:** — · **Parallel-safe with:** AA-0
- **Read:** `src/docket/core/models.py` (`AgentKind`@14, `ModelSource`@24, `AgentMeta`@29 — the precedent for an enum + aliased field), `specs/data/docket-meta.spec.md`, ROADMAP Phase 9 (CDD-1 spec↔model sync rule).
- **Do:** Add `AgentScope` StrEnum (`org`, `project`) and a `scope: AgentScope` field on `AgentMeta` (default `project`, alias-preserving like `modelSource`/`sessionKey`). Validation rejects unknown values. Add a backfill rule used on read + by `doctor` (AA-8): `kind==specialist` → look up the role in AA-2's org/project split (`security`/`knowledge` → `org`, `programmer`/`reviewer`/`tester` → `project`, `manager` → `org` for now); `kind==project` → `project`. Document `scope` as `local` sync-class in `docket-meta.spec.md`. **Do not** remove or repurpose `kind`/`role` — scope is orthogonal.
- **Out of scope:** changing install/add behaviour (AA-2/AA-3); migrating existing workspaces.
- **Deliverables:** edited `core/models.py`, updated `specs/data/docket-meta.spec.md`, pytest.
- **Acceptance gate:** [ ] new meta carries a valid `scope`; [ ] bad `scope` rejected at the model boundary; [ ] meta without `scope` resolves correctly on read; [ ] spec↔model field-set test (CDD-1) still green.
- **Size:** S–M · **Status:** TODO

---

### AA-2 — Reclassify the six specialists: org vs project-role
- **Depends on:** AA-1 · **Parallel-safe with:** AA-6
- **Read:** `src/docket/config.py` (`SPECIALIST_ROLES`@45, `SPECIALIST_ORDER`@54, WHY/display tables @65-77), `src/docket/cli/_install.py` (`_provision_specialists`@288, writes `kind: specialist`@317).
- **Do:** Split the role taxonomy in `config.py`: `ORG_ROLES = {security, knowledge}` (+ Portfolio Manager via AA-6) and `PROJECT_ROLES = {programmer, reviewer, tester}`; `manager` is handled by AA-5 (per-pod Lead). `docket install` provisions **only** org-scoped agents as shared singleton workspaces (`scope: org`). programmer/reviewer/tester are **no longer installed as global workspaces**. **Migration safety:** an existing install with the old global specialists must keep working — do not delete live workspaces; instead `doctor` (AA-8) flags the legacy project-role singletons with re-scope guidance. Keep the role→model policy mapping intact for every role regardless of scope.
- **Out of scope:** pod creation (AA-3); template rewrites (AA-4).
- **Deliverables:** edited `config.py` + `_install.py`, pytest + an integration test for clean-install vs existing-install.
- **Acceptance gate:** [ ] clean `docket install` registers org roles only (`scope: org`); [ ] no global programmer/reviewer/tester singleton on a clean install; [ ] `docket list --all` shows org roles with scope; [ ] existing-install migration doesn't delete workspaces.
- **Size:** M · **Status:** TODO

---

### AA-3 — Pod provisioning in `docket add`
- **Depends on:** AA-1, AA-2 (and read AA-0's verdict for the registration shape) · **Parallel-safe with:** AA-6
- **Read:** `src/docket/cli/__init__.py` (`cmd_add`/`_create_workspace` ~516-770; session key `agent:{id}:{project}`@702; meta write incl. `sessionKey`@716; `_oc.add_agent`/`sync_session_key`@760-763), `src/docket/core/sync.py`, `edges/adapters/openclaw.py`.
- **Do:** `docket add <project>` provisions an isolated **pod**: the **Lead** (AA-5) + the project-scoped roles (AA-4) programmer/reviewer/tester — **all sharing `agent:<id>:<project>`**, each with `scope: project`, `kind: project`, `role: <name>`. Register each through the ACL with that session key. The exact shape (N distinct registered agents sharing a key, vs one Lead that the daemon spawns workers under) follows AA-0's finding — provision to match. One `system.restart_gateway()` at the end. `docket delete <project>` tears down the whole pod (both config sources clean).
- **Out of scope:** template content (AA-4); the Lead's instruction text (AA-5).
- **Deliverables:** edited `cli/__init__.py` (add/delete), `core/sync.py` if needed, integration tests.
- **Acceptance gate:** [ ] `docket add demo` → every pod member shares `agent:demo:default`, correct scope/role; [ ] exactly one gateway restart; [ ] `docket delete demo` removes all members + bindings from both sources.
- **Size:** L (split add/delete if needed) · **Status:** TODO

---

### AA-4 — Project-scoped role templates (Implementer knows the code)
- **Depends on:** AA-3 · **Parallel-safe with:** AA-5
- **Read:** `src/docket/templates/docket-programmer.md`, `docket-reviewer.md`, `docket-tester.md`; the workspace-emission path in `_create_workspace`; current session-key substitution.
- **Do:** Re-author the three templates as **pod members** bound to the project + pod session key (inherit the workspace `SOUL.md` context — **not** a <500-token compressed brief). The **Implementer** (was programmer) has read/write/edit on the project codebase because it runs *in* the workspace (this is the Defect-A fix), plus the agreed git posture. Reviewer stays read-only veto on the diff; Tester stays behaviour-only PASS/FAIL. **Remove** all "shared specialist" / `specialist:<role>:…` hardcoded-key / sandbox-only-no-context language. Bump the template version so `doctor` flags existing agents for `maintain rebuild`.
- **Out of scope:** the Lead template (AA-5); org-role templates.
- **Deliverables:** rewritten templates, template-version bump, pytest rendering each into a pod.
- **Acceptance gate:** [ ] rendered pod role files reference the project + pod session key; [ ] **zero** "shared specialist"/hardcoded-`specialist:` phrasing; [ ] Implementer template grants in-workspace code access; [ ] grep on a fresh pod confirms no singleton language.
- **Size:** M · **Status:** TODO

---

### AA-5 — The Lead role (merge project-agent + manager)
- **Depends on:** AA-3 · **Parallel-safe with:** AA-4
- **Read:** `src/docket/templates/docket-manager.md` (no-edit/HITL constraints — keep them); project repo/task SOUL/AGENTS emission at `cli/__init__.py:533-643`.
- **Do:** Rework the manager template into a **per-pod Lead**: the persistent, project-scoped orchestrator that owns the pod's context/memory + human comms, decomposes work, dispatches to pod workers, and **never edits code** (preserve the manager's no-edit + HITL + context-compression discipline). It replaces the old "project agent that may implement OR delegate" — implementation is always a worker's job. `role: lead`, `scope: project`, shares the pod session key; `type` (repo/task) stays as the policy role for model resolution. Remove the "delegate → global programmer" instruction from the project SOUL.
- **Out of scope:** worker templates (AA-4); the org Portfolio Manager (AA-6).
- **Deliverables:** reworked Lead template, edited project SOUL/AGENTS emission, pytest + integration.
- **Acceptance gate:** [ ] added pod has exactly one `role: lead` member with the no-edit constraint + pod session key; [ ] old "delegate to global programmer" text gone from project SOUL.
- **Size:** M · **Status:** TODO

---

### AA-6 — Org Portfolio Manager (optional, single)
- **Depends on:** AA-1, AA-2 · **Parallel-safe with:** AA-3/AA-4/AA-5
- **Read:** `src/docket/cli/_install.py`, `src/docket/config.py`.
- **Do:** Optionally provision **one** `scope: org`, `role: portfolio-manager` agent that sees fleet metadata/queue/budgets (not project code) — the cross-pod planning/visibility surface, distinct from per-pod Leads. It does **not** dispatch into pods at runtime in v1 (that's AA-7). Gate behind an install flag (opt-in). Never appears as a pod member.
- **Out of scope:** runtime dispatch (AA-7); per-pod Leads (AA-5).
- **Deliverables:** edited `_install.py`/`config.py`, integration test.
- **Acceptance gate:** [ ] flag on → one `portfolio-manager` (`scope: org`) in `docket list --all`; [ ] flag off → none, pods still function; [ ] never listed as a pod member.
- **Size:** S–M · **Status:** TODO

---

### AA-7 — Real dispatch (DAEMON-gated; decision from AA-0)
- **Depends on:** AA-0 (verdict), AA-3, AA-4, AA-5
- **Read:** AA-0's `POD-DAEMON-NOTES.md`, `src/docket/serve.py` (background loop), `src/docket/cli/__init__.py` (`team`/`TASK_LIST.json`), `src/docket/core/trace.py` (Phase 8 trace events — reuse).
- **Do:** **If AA-0 = yes:** the `docket serve` loop reads a pod's `TASK_LIST.json`, dispatches each task to the right pod worker via the daemon (Lead → Implementer → Reviewer → Tester), collects completion markers, and emits a trace event per hop. **If AA-0 = no:** keep the queue + Lead as the operator-driven surface, file an upstream daemon-hook request, and **document** (help/README) that runtime routing is operator-mediated — no overclaiming (Phase 8 honesty rule). Either way, dispatch happens **within a pod** (shared session key), never across pods.
- **Out of scope:** cross-pod dispatch; reintroducing prompt-level SMART-ROUTING (cut in Phase 2).
- **Deliverables:** (yes) edited `serve.py` + trace wiring + integration test with a faked daemon; (no) docs + an upstream-request note + a docs grep-audit test.
- **Acceptance gate:** [ ] (yes) a queued pod task dispatches + traces end-to-end without manual relay; [ ] (no) docs state dispatch is operator-driven and the queue is the contract; [ ] no cross-pod dispatch path exists.
- **Size:** L (yes-path) / S (no-path) · **Status:** BLOCKED (needs AA-0)

---

### AA-8 — `docket list` / `doctor` taxonomy view + migration
- **Depends on:** AA-1, AA-2 · **Parallel-safe with:** AA-5/AA-6
- **Read:** `src/docket/cli/__init__.py` (`list`), `src/docket/cli/_doctor.py`, ROADMAP Phase 9 drift-check pattern.
- **Do:** `docket list --all` gains **SCOPE** and **POD** columns (org agents listed once; pod members grouped under their project). `doctor` backfills `scope` for pre-Phase-10 metas (AA-1 rule), flags legacy global programmer/reviewer/tester singletons with the AA-2 re-scope guidance, and verifies pod members share one session key (drift check). `--fix` performs the safe backfills.
- **Out of scope:** auto-migrating legacy singletons into pods (flag + guide only; the operator re-adds).
- **Deliverables:** edited `list` + `_doctor.py`, integration tests.
- **Acceptance gate:** [ ] pre-Phase-10 install → `doctor` backfills scope + flags legacy singletons; [ ] `list --all` renders org/pod taxonomy; [ ] pod session-key drift is detected.
- **Size:** M · **Status:** TODO

---

### AA-9 — Docs / help / CLAUDE.md truth pass
- **Depends on:** AA-1..AA-6 landed · **Do last**
- **Read:** `CLAUDE.md` (Agent Types + architecture), `README.md`, `docs/WORKFLOW-GUIDE.md`, `docs/DOCKET.md`, `src/docket/cli/_help.py`.
- **Do:** Rewrite the agent-type narrative to the **pod model**: org-scoped shared agents (security, knowledge, optional Portfolio Manager) vs per-product pods (Lead + project-scoped Implementer/Reviewer/Tester sharing one session key). State plainly what's enforced by provisioning/isolation vs what's daemon-gated (AA-7). Remove "specialists are shared resources that work across all projects" for the project-roles. Keep all claims honest (no dollar-savings; no overclaimed runtime routing).
- **Out of scope:** new feature docs.
- **Deliverables:** edited docs + help, a docs grep-audit test.
- **Acceptance gate:** [ ] `grep -ri "shared resource" CLAUDE.md docs/` no longer describes programmer/reviewer/tester as global; [ ] docs describe pods + the daemon caveat; [ ] `uv run pytest` green.
- **Size:** M · **Status:** TODO

---

## Roll-up checklist (Phase 10 definition of done)
- [ ] AA-0 spike landed; AA-7 path decided and recorded.
- [ ] `scope` is a validated first-class axis on every agent (AA-1).
- [ ] Clean install creates only org-scoped shared agents; no global programmer/reviewer/tester singleton (AA-2).
- [ ] `docket add` provisions an isolated pod sharing one session key; the Implementer runs in the workspace (AA-3, AA-4).
- [ ] The single global Atlas manager is replaced by per-pod Leads (+ optional org Portfolio Manager) (AA-5, AA-6).
- [ ] Runtime dispatch is real-via-daemon **or** documented as operator-driven — never overclaimed (AA-7).
- [ ] `docket list`/`doctor` show and migrate the org/pod taxonomy (AA-8).
- [ ] Docs teach the pod model honestly (AA-9).
- [ ] Full suite green: ruff + mypy + pytest + goldens.
