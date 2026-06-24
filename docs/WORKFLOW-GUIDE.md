# Complete Workflow Guide: Pods, Dispatch, and the Org Team

**Status:** Production Guide

> **See also:** [Agent Teams (Pods)](AGENT-TEAMS.md) is the canonical reference for docket's
> agent-team model (scope vs. role, the pipeline, isolation). This guide shows that model in
> **end-to-end use** — provisioning a pod, growing it, queueing work, and running the real
> dispatch loop. Read Agent Teams first; read this for the worked examples.

---

## The Three Actors

### 1. Engineer (You)
The human who:
- Creates projects (each becomes a **pod**)
- Sends tasks (CLI `docket pod … delegate`, or Telegram to a pod's Lead)
- Reviews diffs and commits the code
- Makes architectural decisions and approves any HITL gates
- Sets budget caps and watches recorded spend

### 2. Project Pods
One **pod per project/codebase**, created with `docket add`. A pod is a small team of
project-scoped agents (`scope: project`) that owns exactly one codebase — never shared with
another project:

- **Lead** (`<project>-lead`) — orchestrates the pod, owns its memory + human (Telegram) comms,
  decomposes work and dispatches it. **Never edits code.**
- **Implementer** (`<project>-implementer`) — runs *inside* the project workspace and writes the code.
- **Reviewer** *(optional)* — read-only veto on the diff (correctness + security gate).
- **Tester** *(optional)* — behaviour-only PASS / FAIL validation.

The default pod is **lean** (Lead + Implementer). Add Reviewer/Tester when the work warrants it.

### 3. Org Specialists
A **shared team** created once by `docket install` — genuinely cross-cutting, one instance for
the whole fleet (`scope: org`):

- **manager** — cross-cutting coordination and the org task queue (`docket team …`).
- **knowledge** — documentation, research, pattern extraction across projects.
- **security** — deep security audits and threat modelling.
- **portfolio-manager** *(optional, `docket install --portfolio`)* — advisory cross-pod
  planner over fleet *metadata* (which pods exist, their queues, budgets, health). Never a pod
  member, never edits code, never dispatches into pods.

> The old "shared `programmer`/`reviewer`/`tester` workers" are **gone**. Implement/review/test
> are now per-pod roles, each with its own isolated workspace, so no worker agent ever serves
> two projects. `docket doctor` flags any leftover global worker from a pre-pods install.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      ENGINEER (You)                          │
│  • delegate tasks (CLI or Telegram)   • review diffs + commit│
│  • set budget caps                    • approve HITL gates    │
└──────────────┬───────────────────────────────┬──────────────┘
               │                                │
   per-project │ pod pipeline      cross-cutting│ org queue
               ▼                                ▼
┌──────────────────────────┐        ┌──────────────────────────┐
│  Pod: myapp              │        │  Org specialists (shared)│
│  ┌────────────────────┐  │        │  manager · knowledge ·   │
│  │ lead  (never edits)│  │        │  security · portfolio-mgr│
│  └─────────┬──────────┘  │        │  (advisory, no code)     │
│            ▼             │        └──────────────────────────┘
│  implementer → reviewer? │
│            → tester?     │  ← `docket pod myapp dispatch`
└──────────────────────────┘     one real agent turn per hop
```

Each pod is isolated: its own per-member workspaces (`700`/`600`), its own session-key
namespace (`agent:<project>:…`), its own queue. **There is no cross-pod dispatch path.**

---

## End-to-End: a pod from `add` to committed code

This is the headline workflow — provision a pod, grow it when the work earns it, queue a task,
**dispatch the real pipeline**, then inspect the trace, queue, and cost.

### Step 1 — Provision a lean pod

```bash
docket add myapp ~/code/myapp
# creates two project-scoped agents:
#   myapp-lead          (orchestrator, never edits code)
#   myapp-implementer   (writes code inside ~/code/myapp)

docket pod myapp            # inspect the pod and its roles
docket list                 # every pod member shows up like any other agent
```

A lean pod is the right default for prototyping and low-risk changes: one owner of completion
(the Lead) and one doer (the Implementer).

### Step 2 — Set a budget cap on the Lead

Dispatch is budget-gated against the **Lead's** cap, so set it before you run work:

```bash
docket profile myapp-lead --budget 5     # cap pod spend at $5 (recorded spend)
```

Before *each* hop, docket compares the pod's recorded spend to this cap. Over budget → the task
stays **pending** (blocked), never silently run.

### Step 3 — Grow the pod when the work warrants it

A login bug touching auth deserves a correctness/security gate and independent validation, so
add a Reviewer and a Tester:

```bash
docket pod myapp add reviewer     # adds myapp-reviewer (read-only veto on the diff)
docket pod myapp add tester       # adds myapp-tester  (behaviour-only PASS/FAIL)

docket pod myapp                  # now: lead, implementer, reviewer, tester
```

> You could have provisioned this up front with `docket add myapp ~/code/myapp --pod full` or
> `--with reviewer,tester`. The pod also scales doers: `docket pod myapp add implementer` adds
> `myapp-implementer-2` for parallel work. A pod always has **exactly one Lead.**

### Step 4 — Delegate a task to the pod

```bash
docket pod myapp delegate "Fix the null-token login crash"
docket pod myapp delegate --priority high "Patch the open-redirect on /auth/callback"
```

The task lands on the pod's own queue (owned by the Lead). Nothing runs yet — delegation only
queues. Each task gets its own per-task session (`agent:myapp:<task_id>`) so tasks never bleed
into each other.

### Step 5 — Inspect the queue

```bash
docket pod myapp queue
```

```
Pod: myapp                         budget: $5.00 cap · $0.00 spent
┌──────┬──────────┬──────────────────────────────────────┬─────────┬────────┐
│ id   │ priority │ task                                 │ status  │  cost  │
├──────┼──────────┼──────────────────────────────────────┼─────────┼────────┤
│ t-02 │ high     │ Patch the open-redirect on /auth/... │ pending │  $0.00 │
│ t-01 │ normal   │ Fix the null-token login crash       │ pending │  $0.00 │
└──────┴──────────┴──────────────────────────────────────┴─────────┴────────┘
```

### Step 6 — Dispatch the pipeline (the real hand-off)

```bash
docket pod myapp dispatch
```

docket drives the highest-priority pending task through the pod's pipeline, **one real,
costed agent turn per hop** — and only through the roles this pod actually has:

```
Lead  →  Implementer  →  Reviewer  →  Tester
```

```
▶ dispatch  myapp  ·  t-02  "Patch the open-redirect on /auth/callback"
  budget ok ($0.00 / $5.00)
  → lead          plan + decompose ........... done   $0.04
  budget ok ($0.04 / $5.00)
  → implementer   edit ~/code/myapp ........... done   $0.31
  budget ok ($0.35 / $5.00)
  → reviewer      veto on diff ............... APPROVED $0.05
  budget ok ($0.40 / $5.00)
  → tester        PASS/FAIL .................. PASS    $0.03
  ✓ t-02 complete   pod spend now $0.43 / $5.00
```

docket stays the orchestrator: it invokes each hop via the OpenClaw daemon, captures the
result, and threads it to the next role. The Lead plans, the Implementer is the **single
writer**, the Reviewer can **veto** the diff, the Tester gives an independent PASS/FAIL.

### Step 7 — Budget gating in action

Say `t-01` runs while the pod is near its cap:

```bash
docket pod myapp dispatch
```

```
▶ dispatch  myapp  ·  t-01  "Fix the null-token login crash"
  → lead          plan + decompose ........... done   $0.04
  budget EXCEEDED ($5.02 / $5.00) before implementer hop
  ✗ t-01 left PENDING — raise the cap to continue
```

Over-budget tasks are blocked **between hops**, not abandoned mid-write. Raise the cap and
re-dispatch:

```bash
docket profile myapp-lead --budget 10
docket pod myapp dispatch
```

### Step 8 — Inspect the trace

Every hop emits a trace event on the per-task session, so a run is fully auditable with no
manual Telegram relay:

```bash
docket trace                          # recent dispatch activity across pods
docket trace --session agent:myapp:t-02   # just this task's pipeline
```

```
agent:myapp:t-02
  12:01:04  lead         dispatch.hop  start
  12:01:09  lead         dispatch.hop  done       $0.04
  12:01:09  implementer  dispatch.hop  start
  12:01:38  implementer  dispatch.hop  done       $0.31   (3 files changed)
  12:01:38  reviewer     dispatch.hop  APPROVED   $0.05
  12:01:41  tester       dispatch.hop  PASS       $0.03
```

### Step 9 — Check the cost

```bash
docket pod myapp queue     # per-task status + recorded cost, vs the cap
docket cost                # recorded spend across the whole fleet
docket cost myapp-implementer   # one agent's recorded spend
```

Dollar figures are the daemon's **recorded** spend, not a projection. (The bundled pricing
table only powers comparative model estimates — docket never projects dollar *savings*.)

### Step 10 — Review and commit

docket leaves the commit to you — the Implementer wrote the code, but you own the merge:

```bash
cd ~/code/myapp
git diff                  # review the Implementer's changes
git add -p
git commit -m "Fix open-redirect on /auth/callback"
git push
```

The Lead records the outcome in the pod's memory log
(`~/.openclaw/workspaces/projects/myapp-lead/memory/YYYY-MM-DD.md`).

---

## Autonomous dispatch (opt-in)

`docket pod <project> dispatch` is a one-shot, run-it-now command. To let docket drain every
pod's queue continuously, run the background loop with the dispatch flag:

```bash
docket serve --dispatch    # background: drive every pod's queue on each refresh
```

```bash
docket serve               # READ-ONLY monitor — health checks only, never dispatches
```

> Because every hop is a real, costed LLM turn, dispatch is **never silent**: it is either
> explicit (`docket pod … dispatch`) or opt-in (`docket serve --dispatch`). Plain `docket serve`
> only watches health. Budget caps gate the autonomous loop exactly as they gate a manual
> dispatch — an over-budget pod's tasks stay pending until you raise the cap.

---

## The org queue vs. per-pod dispatch

There are **two distinct queues**, and they don't overlap:

| | **Per-pod dispatch** | **Org manager queue** |
|---|---|---|
| Command | `docket pod <project> delegate / queue / dispatch` | `docket team delegate / queue / start / done / cancel` |
| Scope | one project's pod (`scope: project`) | cross-cutting org work (`scope: org`) |
| Runs code? | yes — Implementer writes inside the project workspace | no — coordination/planning only |
| Isolation | pod-local; no cross-pod path | fleet-wide |

Use **per-pod dispatch** for "do this work in *this* codebase." Use the **org queue**
(`docket team …`) for genuinely cross-cutting coordination that isn't a single project's code —
e.g. "draft a fleet-wide security-audit plan," handled by the shared `manager`.

```bash
# Per-pod (writes code in one project):
docket pod myapp delegate "Add a contact form to the homepage"
docket pod myapp dispatch

# Org-level (cross-cutting coordination, no code):
docket team delegate "Plan an auth-hardening pass across the fleet"
docket team queue
```

### Cross-pod planning, the honest way

There is **no command that runs one pod's work from another pod.** When you need a cross-pod
*plan* (where to focus, what to rebalance or pause), use the advisory
**Portfolio Manager** (`docket install --portfolio`). It reads fleet *metadata* and recommends —
in words, for you — which pods to prioritise. **You** then `delegate` into the chosen pods and
`dispatch` each one. The Portfolio Manager never dispatches and never touches code.

```bash
docket install --portfolio          # add the optional advisory planner (one-time)
# ask it (via Telegram or its workspace) which pods need attention this week,
# then act on its advice:
docket pod myapp dispatch
docket pod mywebsite dispatch
```

---

## Composing a team — how big should a pod be?

Start lean; grow only when the work earns it.

| Situation | Pod |
|-----------|-----|
| Prototyping, low-risk changes, solo project | **lean** (Lead + Implementer) — the default |
| Code that needs a correctness/security gate before it lands | add a **Reviewer** (`--with reviewer`) |
| Behaviour you want validated independently of the diff | add a **Tester** (`--with tester`) |
| Production-grade, regulated, or high-blast-radius work | **full** pod (`--pod full`) |
| One Implementer is the bottleneck | `docket pod <p> add implementer` (parallel doers) |

The Reviewer and Tester are the line between "an agent changed the code" and "a change was
reviewed and validated before it landed."

---

## Pod configuration

### What makes a pod member

Each member is an ordinary registered agent with its **own** permission-locked workspace, so
`docket list` / `info` / `cost` / `doctor` see every member for free.

```
~/.openclaw/workspaces/projects/myapp-implementer/
├── SOUL.md              # identity + scope + session key
├── AGENTS.md            # session protocol, role boundaries
├── TOOLS.md             # project-specific commands
├── HEARTBEAT.md         # active tasks/decisions
├── .docket-meta.json    # docket metadata (role, codebase, model, sessionKey, projectKey)
├── memory/
│   └── 2026-06-24.md    # daily log
└── workflows/           # Lobster pipelines (optional, deterministic execution)
```

### Session keys & isolation

Pod members share the project's session-key namespace (`agent:myapp:<key>`), which keeps the
pod's conversation context together and **isolated from every other project**. Dispatch runs
each task on its own per-task session (`agent:myapp:<task_id>`). Change a member's scope with:

```bash
docket scope myapp-implementer set myapp-staging
```

The load-bearing isolation primitive is the **per-member workspace** — session keys isolate
conversation; separate workspaces isolate files, memory, and identity.

### Per-role model policy

Each role maps to the **cheapest model adequate for its workload**. Change a role once and every
policy-following agent re-resolves; pin one agent with `docket profile`.

| Role | Policy key | Default class |
|------|-----------|---------------|
| Lead | manager | cheap (coordination) |
| Implementer | programmer | strong (reasoning-dense) |
| Reviewer | reviewer | cheap |
| Tester | tester | cheap |
| Portfolio Manager | portfolio-manager | cheap |

```bash
docket models                                   # show the role→model policy
docket models set programmer anthropic/claude-… # re-resolves every policy-following Implementer
docket profile myapp-implementer anthropic/…    # pin ONE agent
docket profile myapp-implementer default        # re-attach it to the role policy
```

Agents record intent in `modelSource`: `policy` (follow the role) or `pinned` (explicit choice).
`docket models set …` never touches pins.

---

## Engineer's daily workflow

### Morning

```bash
docket list                     # every pod member + org specialist
docket doctor                   # health + auto-fix; flags legacy global workers
```

### Assign and run work

```bash
# Queue and run a single project's work:
docket pod myapp delegate "Add contact form to homepage"
docket pod myapp dispatch

# Or let the background loop drain every pod's queue:
docket serve --dispatch
```

You can also drive a pod's Lead from Telegram — wire it once with `docket wire myapp-lead` and
send tasks to its group; the Lead queues them on the same pod queue.

### Monitor

```bash
docket pod myapp queue          # this pod's queue + per-task status/cost
docket trace                    # recent dispatch hops across pods
docket logs myapp-lead          # the Lead's activity
```

### Review and commit

```bash
cd ~/code/myapp
git diff
git add -p && git commit -m "Feature: contact form" && git push
```

### End of day

```bash
docket cost                     # recorded spend across the fleet
docket doctor                   # any alerts?
```

---

## Token & cost notes

These are **token** estimates — the thing docket's routing actually controls. For dollars, read
your **recorded** spend with `docket cost`; it depends on your models and current pricing, so we
don't project it here. See
[Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

A dispatched task is the sum of its hops, each a real costed turn:

```
Simple change (lean pod, 2 hops):
  lead         ~2K   (plan + decompose, cheap model)
  implementer  ~2K   (small edit, strong model)
  ── total    ~4K · ~2 min

Feature (full pod, 4 hops):
  lead         ~5K
  implementer ~20K   (multi-step logic, strong model)
  reviewer     ~5K   (veto on diff)
  tester       ~3K   (PASS/FAIL)
  ── total   ~33K · ~10 min

Refactor (full pod, high blast radius):
  lead        ~10K
  implementer ~50K   (multi-file)
  reviewer    ~10K   (security-critical)
  tester       ~5K
  ── total   ~75K · ~20 min
```

To bound the dollar cost of any of these, set a per-pod cap on the Lead
(`docket profile <project>-lead --budget <usd>`) and watch actual spend with `docket cost`. The
cap is enforced between hops on every dispatch.

---

## Troubleshooting

### Pod not running a delegated task?

1. **Confirm the pod and its members exist and are healthy:**
   ```bash
   docket pod myapp
   docket doctor
   ```
2. **Check the queue — is the task pending because of budget?**
   ```bash
   docket pod myapp queue        # look at status + the budget header
   ```
3. **If over budget, raise the cap and re-dispatch:**
   ```bash
   docket profile myapp-lead --budget 10
   docket pod myapp dispatch
   ```
4. **Did you actually dispatch?** `delegate` only queues — `dispatch` runs the pipeline (or
   start the background loop with `docket serve --dispatch`).

### Pipeline stops after the Implementer?

That's expected for a **lean** pod — it only has two hops. Add the gate roles if you want them:

```bash
docket pod myapp add reviewer
docket pod myapp add tester
```

### Implementer touching the wrong project?

1. **Check its session key / scope:**
   ```bash
   docket scope myapp-implementer show
   ```
2. **Reset if needed:**
   ```bash
   docket scope myapp-implementer reset
   ```
3. **Verify the workspace identity:**
   ```bash
   grep "Session Key" ~/.openclaw/workspaces/projects/myapp-implementer/SOUL.md
   ```

### Leftover global `programmer`/`reviewer`/`tester`?

A pre-pods install may have left a shared worker workspace. `docket doctor` flags it and
backfills `scope` on legacy metadata — run it and follow its advice:

```bash
docket doctor
```

### Gateway / Telegram issues

```bash
docket list                                   # shows wire status per agent
docket wire myapp-lead                         # (re)wire a Lead to Telegram
systemctl --user status openclaw-gateway.service
```

---

## Summary

**Project pods** (`scope: project`, one per codebase):
- Lead orchestrates and owns comms — **never edits code**.
- Implementer is the **single writer**, inside the project workspace.
- Reviewer/Tester are optional gates you add when the work warrants it.
- `docket pod <p> delegate` queues; `docket pod <p> dispatch` runs the real pipeline,
  one costed turn per hop, **budget-gated, traced, and pod-local**.

**Org specialists** (`scope: org`, shared once):
- manager / knowledge / security; optional advisory portfolio-manager.
- The org queue (`docket team …`) is for cross-cutting coordination, **not** a project's code.

**Engineer:**
- Sets budget caps, delegates and dispatches, reviews diffs, commits, approves HITL gates.

```
delegate → dispatch → Lead → Implementer → (Reviewer) → (Tester) → you review + commit
```

**Key guarantees:**
- One owner of completion (Lead) and one doer (Implementer) — no two-doer ambiguity.
- Per-member workspaces — no worker agent ever serves two projects.
- Real hand-off — the pipeline actually runs; every hop is costed, budget-gated, and traced.
- No cross-pod dispatch — one pod can never run another pod's agents.

---

**Next:** Read [Agent Teams (Pods)](AGENT-TEAMS.md) for the canonical model, or
[QUICK-START-DOCKET.md](QUICK-START-DOCKET.md) to run your first pod.
