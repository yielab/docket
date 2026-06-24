# Agent Teams (Pods) — the heart of docket

> **This is the most important concept in docket.** Everything else — isolation, cost
> guardrails, health checks — exists to keep *teams of agents* running reliably across many
> projects. If you read one guide, read this one.

A single autonomous agent is easy. Building **enterprise-grade software** with agents is not: it
needs the same separation of duties a human team has — someone who plans and talks to people,
someone who writes the code, someone who reviews it, someone who tests it — with hard boundaries
so one project's work never contaminates another's. docket makes that structure first-class.

---

## The two axes: scope and role

Every agent docket manages has two independent properties. Conflating them is the mistake that
makes naive multi-agent setups fall apart.

| Axis | Values | Meaning |
|------|--------|---------|
| **scope** | `org` \| `project` | Shared across the whole fleet, or owned by exactly one project |
| **role** | lead, implementer, reviewer, tester, manager, knowledge, security, portfolio-manager | What the agent is *for* |

From those two axes fall the two kinds of team member:

- **Org specialists** — `scope: org`, genuinely cross-cutting, **one instance for the whole fleet**.
- **Project pods** — `scope: project`, a self-contained team **per project**, never shared.

---

## Project pods — one isolated team per project

`docket add <project>` provisions a **pod**: a small team of project-scoped agents that owns one
codebase. Each member is a distinct registered agent with its **own permission-locked workspace**
(`700`/`600`, with `SOUL.md`, `AGENTS.md`, `HEARTBEAT.md`, `.docket-meta.json`, and a `memory/`
log) — so **no role is ever shared between two projects.**

The default pod is **lean — a Lead and an Implementer.** You add Reviewer, Tester, or extra
Implementers when the work warrants it.

| Pod role | Edits code? | Responsibility | Default model class |
|----------|:-----------:|----------------|---------------------|
| **Lead** | **never** | Orchestrates the pod, owns its context/memory + human (Telegram) comms, decomposes work, dispatches to workers | cheap (coordination) |
| **Implementer** | **yes** | Runs *inside* the project workspace and writes the code | strong (reasoning-dense) |
| **Reviewer** *(optional)* | no (read-only) | Veto on the diff — correctness + security gate | cheap |
| **Tester** *(optional)* | no | Behaviour-only validation: PASS / FAIL | cheap |

Member ids are predictable: `myapp-lead`, `myapp-implementer`, `myapp-implementer-2`,
`myapp-reviewer`, `myapp-tester`. Because each is an ordinary registered agent,
`docket list`/`info`/`cost`/`doctor` see every pod member for free.

```bash
docket add myapp ~/code/myapp        # lean pod: myapp-lead + myapp-implementer
docket add myapp --pod full          # full pod: + reviewer + tester
docket add myapp --with reviewer     # lean pod + a reviewer
docket pod myapp                     # inspect the pod and its roles
docket pod myapp add implementer     # scale out: adds myapp-implementer-2
docket pod myapp add reviewer        # add a role later
docket pod myapp remove myapp-tester # drop a member
docket delete myapp                  # tear down the whole pod
```

A pod has **exactly one Lead** (its single orchestrator); every other role may be duplicated.

---

## Org specialists — shared across the fleet

`docket install` creates the cross-cutting specialists once. They are genuinely fleet-wide, so a
per-project copy would be waste:

- **manager** — cross-cutting coordination and the org task queue (`docket team …`).
- **knowledge** — documentation, research, pattern extraction across projects.
- **security** — deep security audits and threat modelling.

### Optional: the org Portfolio Manager

`docket install --portfolio` adds **one** `portfolio-manager` (`scope: org`): a cross-pod
**planning and visibility** surface. It sees fleet *metadata* — which pods exist, their queues,
budgets, and health — **not project code.** It is advisory: it recommends where to focus,
rebalance, or pause, in words for a human. It never edits code and does not dispatch into pods
(each pod's own Lead owns execution). It is opt-in, and it is never a pod member.

---

## Why this structure matters — three defects it fixes

The pod model is not decoration. It exists to fix three concrete failures of the naive
"one agent per project + a few shared workers" setup:

1. **Two doers (no clear owner of completion).** If a project agent *and* a shared programmer can
   both implement, neither reliably finishes a task. In a pod, the **Implementer is the single
   doer** and the **Lead never edits code** — one writer, one owner.
2. **Broken isolation.** A shared `programmer` specialist serving every project has *one*
   workspace and *one* memory — so projects leak into each other. In a pod, **every member has its
   own workspace**; the load-bearing guarantee is *no worker agent ever serves two projects*.
3. **Delegation that wasn't real.** Previously a Lead's instructions *said* "hand off to the
   Implementer," but nothing actually ran the next agent. docket now **really runs the pipeline**
   (see below) — the hand-off executes.

---

## Real dispatch — the pipeline actually runs

docket can drive a pod's queued work through its pipeline, **one real agent turn per hop**:

```
Lead  →  Implementer  →  Reviewer (if present)  →  Tester (if present)
```

Only the roles a pod actually has take part (a lean pod runs two hops). docket stays the
orchestrator — it invokes each hop via the OpenClaw daemon, captures the result, and threads it to
the next role. This is the **real fix for "delegation wasn't real."**

```bash
docket pod myapp delegate "Fix the null-token login crash"   # queue a task
docket pod myapp queue                                        # see the queue + per-task status/cost
docket pod myapp dispatch                                     # run the pipeline once, now
docket serve --dispatch                                       # background: drive every pod's queue each refresh
```

Three guarantees hold on every dispatch:

- **Budget-gated.** Before *each* hop docket checks the pod's recorded spend against the Lead's
  budget cap (`docket profile <project>-lead --budget N`). Over budget → the task is left
  **pending** (blocked), not run.
- **Traced.** Every hop emits a Phase-8 trace event (`docket trace`), on a per-task session
  `agent:<project>:<task_id>` — so a run is fully auditable, with no manual Telegram relay.
- **Pod-local.** Dispatch only ever targets the project's own pod members. **There is no
  cross-pod dispatch path** — one pod can never run another pod's agents.

> Each hop is a real, costed LLM turn. That is why dispatch is explicit (`docket pod … dispatch`)
> or opt-in (`docket serve --dispatch`) — never silent. The read-only `docket serve` monitor does
> not dispatch.

---

## Composing a team — how big should a pod be?

Start lean and grow only when the work earns it:

| Situation | Pod |
|-----------|-----|
| Prototyping, low-risk changes, solo project | **lean** (Lead + Implementer) — the default |
| Code that needs a correctness/security gate before it lands | add a **Reviewer** (`--with reviewer`) |
| Behaviour you want validated independently of the diff | add a **Tester** (`--with tester`) |
| Production-grade, regulated, or high-blast-radius work | **full** pod (`--pod full`) |
| One Implementer is the bottleneck | `docket pod <p> add implementer` (parallel doers) |

The Reviewer and Tester are the difference between "an agent changed the code" and "a change was
reviewed and validated before it landed" — which is exactly the line between a toy and
**enterprise-grade** delivery.

---

## Session keys & isolation

Pod members share the project's session-key namespace (`agent:<project>:<key>`), which keeps the
pod's conversation context together and **isolated from every other project**. Dispatch runs each
task on its own per-task session (`agent:<project>:<task_id>`) so tasks don't bleed into each
other. Change a pod's scope with `docket scope <member-id> set <key>`. The real isolation
primitive, though, is the **per-member workspace** — session keys isolate conversation; separate
workspaces isolate files, memory, and identity.

---

## Per-role model policy

Each role maps to the **cheapest model adequate for its workload** — coordination and
review/test are cheap-class; the Implementer (and security audits) get the strong class. Change a
role once and every policy-following agent re-resolves; pin one agent with `docket profile`.

| Role | Policy key | Default class |
|------|-----------|---------------|
| Lead | manager | cheap |
| Implementer | programmer | strong |
| Reviewer | reviewer | cheap |
| Tester | tester | cheap |
| Portfolio Manager | portfolio-manager | cheap |

See [Architecture (DOCKET)](DOCKET.md) for the routing internals and
[Command Reference](commands.md) for every flag.

---

## Command reference (teams)

```bash
# Provision / resize a pod
docket add <project> [path]              # lean pod (Lead + Implementer)
docket add <project> --pod full          # + Reviewer + Tester
docket add <project> --with reviewer,tester
docket pod <project>                     # list members
docket pod <project> add <role> [--count N]
docket pod <project> remove <member-id>
docket delete <project>                  # tear down the whole pod

# Run the pipeline
docket pod <project> delegate [--priority high|normal|low] "<task>"
docket pod <project> queue
docket pod <project> dispatch
docket serve --dispatch                  # autonomous: drive every pod's queue

# Org specialists
docket install                           # manager, knowledge, security
docket install --portfolio               # + the optional org Portfolio Manager
docket team delegate "<task>"            # org manager task queue (delegate/queue/start/done/cancel)
```
