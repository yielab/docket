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
- Sets budget caps and watches measured token usage

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

- **manager** — cross-cutting coordination (transitional; `docket team`'s own task queue was
  retired — per-pod dispatch is the only queue now — so this role is being superseded by
  per-pod Leads).
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
   per-project │ pod pipeline      cross-cutting│ advisory only
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
docket profile myapp-lead --budget 5     # cap pod spend at $5 (token-based estimate)
```

Before *each* hop, docket compares the pod's token-based dollar estimate to this cap — docket's
own turn loop reports real, measured token counts but no billed dollar figure, so the gate always
runs off the labelled estimate (`core/dispatch.py`'s `pod_gating_cost`), never a claimed "recorded
spend". Over budget → the task stays **pending** (blocked), never silently run.

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

docket stays the orchestrator: it invokes each hop through its own turn loop
(`core/agent_loop.py`), captures the result, and threads it to the next role. The Lead plans,
the Implementer is the **single writer**, the Reviewer can **veto** the diff, the Tester gives
an independent PASS/FAIL.

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
docket pod myapp queue     # per-task status + estimated cost, vs the cap
docket cost                # measured token usage across the whole fleet
docket cost myapp-implementer   # one agent's measured tokens + a labelled estimate
```

Token counts are real and measured. Dollar figures are **not** — docket's own turn loop reports
no billed spend, so `docket cost` shows a clearly labelled estimate rather than a number claimed
as recorded. (The bundled pricing table only powers that estimate and `docket models`' comparative
display — docket never projects dollar *savings*.) See
[Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

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
(`~/.docket/workspaces/projects/myapp-lead/memory/YYYY-MM-DD.md`).

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
> dispatch — an over-budget pod's tasks are set to `blocked` (not `pending`) and the pod's Lead
> is paused. A blocked task does **not** resume on its own when the cap changes: clear it with
> `docket profile <lead-id> --resume`, which unpauses the Lead and unblocks the pod's
> budget-blocked tasks, or requeue one with `docket pod <project> queue --retry <task-id>`.
> Leaving them blocked is deliberate — rewriting them straight back to `pending` was the bug that
> let a budget-capped task retry forever on every sweep.

---

## Pipelines: the one dialect docket runs

Everything in Step 6 above — Lead → Implementer → Reviewer → Tester, one hop per role — is
docket's **built-in pipeline**. It is not hardcoded prose; it is a real, typed pipeline document
(`core/pipeline.py`) that `docket pod <project> dispatch` runs whenever a pod has no pipeline
file of its own. Writing a pipeline file lets you change the step order, add a parallel fan-out,
or swap in a different gate — without touching pod membership at all.

> **`docket workflow` is gone.** An older Lobster YAML dialect (`docket workflow validate|plan`)
> used to live here; its own validator silently ignored constructs its own template emitted, so
> docket was linting a format it could not fully run. It was retired outright (ROADMAP decision
> D-16) rather than migrated — running it now prints a removed-command notice:
>
> ```text
> $ docket workflow validate myflow
> docket workflow was retired — one pipeline dialect now, not two (the Lobster YAML validator
> ignored four constructs its own template emitted; ROADMAP D-16).
> Use: docket pipeline validate   (was: workflow <id> validate <name>)
> Use: docket pipeline plan       (was: workflow <id> plan/dry-run <name>)
> Use: docket pipeline run        to actually execute a pipeline
> Any existing workflows/*.lobster.yml files are left on disk untouched, but no longer read by docket.
> ```
>
> Any old `.lobster.yml` files are left on disk untouched; docket just never reads them again.
> `docket pipeline` below is the one dialect docket actually executes.

### Zero migration: nothing changes until you opt in

A pod with no pipeline file behaves **exactly** like `core/dispatch.py`'s hardcoded pipeline
always has: Lead (no gate) → Implementer (mechanical check against its own `verifyCmd`) →
Reviewer (APPROVE/REQUEST-CHANGES, bounded rework back to the Implementer) → Tester
(PASS/FAIL, hard gate, no rework). A lean pod without a Reviewer/Tester simply never reaches
those steps — same skip-absent-roles behavior `docket pod <project> dispatch` always had.
Installing this feature changes nothing about an existing pod until you write a file and pass
`--file`.

### `docket pipeline validate` — check a file before you point a pod at it

Pure structural validation, no project or pod involved. Every level of the document rejects an
unrecognized key — a typo fails loudly instead of being silently ignored (the exact defect that
got Lobster retired):

```bash
$ docket pipeline validate workflows/release.yml
✓ Pipeline 'workflows/release.yml' is valid

$ docket pipeline validate workflows/broken.yml
✗ Error: Pipeline 'workflows/broken.yml' is invalid:
  ✗ steps.0.verifyCommand: Extra inputs are not permitted
```

### `docket pipeline plan` — see what would actually run, without running it

`plan` renders straight from the real executor (`core.orchestrator.resolve_plan`/`render_plan`)
— never a second, drift-prone pretty-printer, and never a token spent:

```bash
$ docket pipeline plan myapp

Pipeline plan — myapp

Pipeline: default
  [lead] role=lead -> myapp-lead [gate: none]
  [implementer] role=implementer -> myapp-implementer [gate: mechanical(verifyCmd)]
  [reviewer] role=reviewer -> myapp-reviewer [gate: verdict(approve, rework->implementer)]
  [tester] role=tester -> myapp-tester [gate: verdict(pass)]
```

A lean pod (no Reviewer/Tester) shows those two lines marked `(skipped — role not in pod)`
instead of a resolved member id — `plan` always renders every step the spec declares, it just
tells you honestly which ones this pod's current roster can run.

### A custom pipeline: parallel fan-out, bounded rework, a human sign-off

You already scaled myapp's Implementer for parallel work (`docket pod myapp add implementer`
→ `myapp-implementer-2`, mentioned above). A pipeline file is how you actually put both
implementers to work on one task, then require a human OK before the fix ships instead of an
automated PASS/FAIL:

```yaml
# ~/code/myapp/workflows/release.yml
name: release
description: Fan the fix out across both implementers, then require a human OK before it ships.

steps:
  - id: plan
    role: lead

  - id: fanout
    parallel:
      - id: impl-a
        agent: myapp-implementer
      - id: impl-b
        agent: myapp-implementer-2

  - id: review
    role: reviewer
    gate:
      type: verdict
      pattern: "^(APPROVE|REQUEST-CHANGES)\\b"
      passValues: [approve]
      rework:
        to: fanout
        when: [request-changes]
        maxCycles: 2

  - id: ship
    role: tester
    gate:
      type: approval
      message: "Tests passed — ready to deploy?"
```

```bash
$ docket pipeline plan myapp --file workflows/release.yml

Pipeline plan — myapp

Pipeline: release
  [plan] role=lead -> myapp-lead [gate: none]
  [fanout] parallel:
    - myapp-implementer -> myapp-implementer [gate: none]
    - myapp-implementer-2 -> myapp-implementer-2 [gate: none]
  [review] role=reviewer -> myapp-reviewer [gate: verdict(approve, rework->fanout)]
  [ship] role=tester -> myapp-tester [gate: approval]

$ docket pipeline run myapp --file workflows/release.yml
```

`run` dispatches through `cli._pod._pod_dispatch` — the exact same rendering, run-registry
recording, budget/approval gating, retries, and crash resume `docket pod myapp dispatch` uses.
`--file` only swaps which `PipelineSpec` is walked; nothing else about how a hop runs changes.

Three gate kinds, and what a failure does to the task:

| Gate | Where it shows up | On failure |
|---|---|---|
| `mechanical` | Implementer's `verifyCmd` by default (or a `command` you set) | Task → **failed**, a `verification_failed` trace event, no advance to the next step. An unset command is never silently skipped — it prints `verification skipped — verifyCmd not set for <id>` and emits its own trace event |
| `verdict` | Reviewer's APPROVE/REQUEST-CHANGES (bounded rework), Tester's PASS/FAIL (hard gate) | A rejected/unparseable verdict past the rework budget → task **failed**. Rework re-runs the named earlier step, up to `maxCycles` |
| `approval` | A pipeline `approval` step, or a pod-level `requireApprovalRoles` list | Task → **waiting_approval** — the hop doesn't run at all until a human decides. See [SECURITY-SIMPLE.md](SECURITY-SIMPLE.md) for the approval channels |

### Declared variables — real, but only wired to one trigger today

A pipeline can declare `variables` (defaults, descriptions, `required`), but this format defines
**no interpolation engine** — declaring one never substitutes a value into a hop's prompt or
environment anywhere. The one place a declared variable's value is actually resolved today is the
`docket serve` webhook (next section); `docket pipeline plan`/`run` from the CLI never look at
`variables` at all — a `required` variable with no default does not block a CLI-triggered run.
Treat `variables` today as metadata a webhook caller can supply and a later `docket runs show`
can report, not a general parameterization mechanism yet.

---

## The run registry, `--follow`, and cancellation

Every dispatch invocation — CLI, the serve webhook, a due schedule, the `--dispatch` sweep loop,
or an MCP client — writes one record to a persisted run registry, so "is it done, did it fail, or
did it never run" has an answer instead of vanishing behind a fire-and-forget thread:

```bash
$ docket runs list
Dispatch runs
┌──────────────────────┬─────────┬─────────┬───────────┬───────┬─────────────────────┬───────┐
│ ID                    │ SOURCE  │ PROJECT │ STATE     │ TASKS │ CREATED             │ ERROR │
├──────────────────────┼─────────┼─────────┼───────────┼───────┼─────────────────────┼───────┤
│ run-3f2a1c9e-...      │ cli     │ myapp   │ succeeded │ 1     │ 2026-07-29T10:02:00 │       │
└──────────────────────┴─────────┴─────────┴───────────┴───────┴─────────────────────┴───────┘

$ docket runs show run-3f2a1c9e-... --json
$ docket runs list --project myapp --json     # for scripting/dashboards
```

`--follow` on `docket pipeline run` tails the same durable trace store a hop already writes to,
so you see hop-by-hop progress live instead of only the final summary:

```bash
$ docket pipeline run myapp --follow
→ Following dispatch for 'myapp' (Ctrl-C stops watching, not the dispatch)

  2026-07-29T10:02:00  tool_call                  (lead)
  2026-07-29T10:02:05  tool_result                (lead)
  2026-07-29T10:02:05  tool_call                  (implementer)
  ...
```

Ctrl-C stops *watching only* — the dispatch keeps running and recording in the background,
exactly like closing a `tail -f` window doesn't kill the process being tailed.

A run stuck mid-hop can be killed outright:

```bash
$ docket runs cancel run-3f2a1c9e-...
✓ cancelled run run-3f2a1c9e-... (1 process group(s) killed)
```

`cancel` kills the in-flight hop's **whole process group**, not just the immediate child (it may
have shelled out further), and marks the run terminally `cancelled` — the killed hop surfaces as
an ordinary hop failure through the same state machine, no new task-status vocabulary. A genuine
cancellation writes a `runs.cancel` audit entry naming the run, its project, its pre-cancel state,
and how many process groups were killed. Cancelling an already-terminal (or unknown) run changes
nothing and writes no audit entry — but it still exits `1`, printed as an error
(`run <id> is already <state>`), not a silent success; "no-op" describes its side effects, not
its exit code.

---

## Scheduling and webhooks (unattended dispatch)

Two ways to trigger a pod's pipeline without a human typing `dispatch`:

### Schedules — cron, a daily time, or a fixed interval

Schedules live in `~/.docket/docket-schedules.json` — there is no CLI writer for this file yet,
so you edit it directly:

```json
{
  "schedules": {
    "myapp": "@every 30m",
    "otherapp": "09:00",
    "athird": "*/15 9-17 * * 1-5"
  }
}
```

Three formats: `@every <N>s|m|h`, a daily `HH:MM` (UTC), or a standard 5-field cron expression
(`minute hour dom month dow`, UTC, numeric only — no `MON`/`JAN` name aliases). A schedule is
checked at most once per matching minute and **only while `docket serve --dispatch` is running**
— plain read-only `docket serve`, or no `docket serve` at all, never fires one. Each due project
gets its own run record (`source: "schedule"`), so a scheduled dispatch is exactly as inspectable
via `docket runs` as a manual one.

### Webhooks — trigger from CI or any external system

`docket serve` always exposes `POST /dispatch/<project>` (bearer-token authenticated), independent
of `--dispatch` — a webhook call is an explicit request, not part of the passive monitor loop:

```bash
TOKEN=...   # printed at `docket serve` startup, or $DOCKET_SERVE_TOKEN

curl -s -H "Authorization: Bearer $TOKEN" -X POST \
  -H "Content-Type: application/json" -d '{"env": "staging"}' \
  http://127.0.0.1:7331/dispatch/myapp
# {"ok": true, "run": "run-3f2a1c9e-...", "project": "myapp", "status": "dispatched"}

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7331/runs/run-3f2a1c9e-... | jq .
```

The JSON body is resolved against the pod's own configured/default pipeline's declared
`variables` **before** a run record is even created — this is the one path where a pipeline's
declared `variables` actually do something (see the note above): a missing `required` variable
is rejected with `400` and no run record is created at all; the resolved namespace is persisted
on the run record
(`docket runs show <id>` shows it) purely so you can answer "what did this dispatch actually see"
— it is still never interpolated into a hop's prompt. The webhook always uses the pod's own
pipeline; it has no way to supply a `--file` of its own, only variable *values*.

---

## There is now one queue: per-pod dispatch

`docket team` (the org manager's own delegate/queue/start/done/cancel task queue) was
**retired** — the old manager queue was never dispatched, so it added ceremony without running
anything. **Per-pod dispatch is the only queue now:**

| | **Per-pod dispatch** |
|---|---|
| Command | `docket pod <project> delegate / queue / dispatch` |
| Scope | one project's pod (`scope: project`) |
| Runs code? | yes — Implementer writes inside the project workspace |
| Isolation | pod-local; no cross-pod path |

Use it for "do this work in *this* codebase":

```bash
docket pod myapp delegate "Add a contact form to the homepage"
docket pod myapp dispatch
```

For genuinely cross-cutting *planning* (not code) — "what should the fleet focus on this
week" — there is no queue at all, only the advisory Portfolio Manager described next: it reads
fleet metadata and recommends in words; you act on its advice by delegating into the pods it
names.

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
~/.docket/workspaces/projects/myapp-implementer/
├── SOUL.md              # identity + scope + session key
├── AGENTS.md            # session protocol, role boundaries
├── TOOLS.md             # project-specific commands
├── HEARTBEAT.md         # active tasks/decisions
├── .docket-meta.json    # docket metadata (role, codebase, model, sessionKey, projectKey)
└── memory/
    └── 2026-06-24.md    # daily log
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
docket cost                     # measured token usage across the fleet
docket doctor                   # any alerts?
```

---

## Token & cost notes

These are **token** estimates — the thing docket's routing actually controls. For dollars, read
the **labelled estimate** with `docket cost`; it depends on your models and current pricing, so we
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

Pod/dispatch, scope, and Telegram issues (including "pod not running a delegated task,"
"pipeline stops after the Implementer," and leftover pre-pods global roles) are all covered in
**[troubleshooting.md](troubleshooting.md)**'s "Pods & Dispatch" and "Agents Not Responding in
Telegram" sections — kept in one place rather than duplicated here.

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
- `docket team` (the old org task queue) was retired — per-pod dispatch is the only queue now;
  the portfolio-manager is advisory-only and never dispatches or touches a project's code.

**Engineer:**
- Sets budget caps, delegates and dispatches, reviews diffs, commits, approves HITL gates.

```
delegate → dispatch → Lead → Implementer → (Reviewer) → (Tester) → you review + commit
```

**Pipelines** (`docket pipeline validate/plan/run`, `docket runs list/show/cancel`):
- `docket workflow`/Lobster is retired (D-16) — the docket-native pipeline is the one dialect
  docket executes, and a pod with no pipeline file runs the built-in one unchanged.
- Every dispatch — CLI, `--follow`, a schedule, a webhook, or the sweep loop — lands one record
  in the run registry; `docket runs cancel` kills an in-flight hop's process group for real.

**Key guarantees:**
- One owner of completion (Lead) and one doer (Implementer) — no two-doer ambiguity.
- Per-member workspaces — no worker agent ever serves two projects.
- Real hand-off — the pipeline actually runs; every hop is costed, budget-gated, and traced.
- No cross-pod dispatch — one pod can never run another pod's agents.

---

**Next:** Read [Agent Teams (Pods)](AGENT-TEAMS.md) for the canonical model, or
[QUICK-START-DOCKET.md](QUICK-START-DOCKET.md) to run your first pod.
