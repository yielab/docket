# Agent Teams (Pods) — the heart of docket

> **This is the most important concept in docket.** Everything else — isolation, cost
> guardrails, health checks — exists to keep *teams of agents* running reliably across many
> projects. If you read one guide, read this one.

A single autonomous agent is easy. Getting several agents to ship real software together is
harder: it needs the same separation of duties a human team has — someone who plans and talks to
people, someone who writes the code, someone who reviews it, someone who tests it — with hard
boundaries so one project's work never contaminates another's. docket makes that structure
first-class.

---

## The two axes: scope and role

Every agent docket manages has two independent properties. Conflating them is the mistake that
makes naive multi-agent setups fall apart.

| Axis | Values | Meaning |
|------|--------|---------|
| **scope** | `org` \| `project` | Shared across the whole fleet, or owned by exactly one project |
| **role** | lead, implementer, reviewer, tester, manager, knowledge, security, portfolio-manager, … | What the agent is *for* |

From those two axes fall the two kinds of team member:

- **Org specialists** — `scope: org`, genuinely cross-cutting, **one instance for the whole fleet**.
- **Project pods** — `scope: project`, a self-contained team **per project**, never shared.

The role list above is the everyday roster, not a closed enum — see "Role archetypes" below for
how a role is actually defined and how you add your own.

---

## Project pods — one isolated team per project

`docket init <project>` provisions a **pod**: a small team of project-scoped agents that owns one
codebase (or, for a non-software pod, one shared working directory — see "Pod blueprints" below).
Each member is a distinct registered agent with its **own permission-locked workspace**
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

## Role archetypes — roles are data, not hardcoded branches

Before this was declarative, a pod role was a closed 4-tuple wired into `core/pod.py`, and each
role's identity prose was hand-written string-building in the CLI. Adding a fifth role meant
editing code. Now every role — including the four legacy ones — is a **role archetype**
(`core/archetypes.py`): a versioned, declarative record of its scope, model class, identity
templates, gate contract, edit rights, and tool profile.

```bash
docket roles list                 # every registered archetype: built-in, starter, user
docket roles show reviewer        # one archetype's full definition (YAML/JSON)
docket roles add ./producer.yaml  # register a custom archetype from a YAML file
docket roles validate             # dry-run every archetype's schema + template render
```

Four **built-in** archetypes reproduce the legacy roles byte-identically. A **starter library**
ships six more you can drop into any pod without writing a line of YAML:

| Name | Class | Gate | Edit rights |
|---|---|---|---|
| `lead` *(built-in)* | cheap | none | none |
| `implementer` *(built-in)* | strong | mechanical (`verifyCmd`) | write |
| `reviewer` *(built-in)* | cheap | verdict (APPROVE / REQUEST-CHANGES) | read-only |
| `tester` *(built-in)* | cheap | verdict (PASS / FAIL) | read-only |
| `researcher`, `analyst` *(starter)* | strong | none | write |
| `writer` *(starter)* | cheap | none | write |
| `critic` *(starter)* | cheap | verdict (APPROVE / REJECT) | read-only |
| `operator` *(starter)* | strong | mechanical | write |
| `monitor` *(starter)* | cheap | approval | read-only |

Provisioning a starter role into a live pod works exactly like any other role:
`docket pod <project> add researcher`. A user-authored archetype (a standalone YAML file,
`docket roles add`) can add a brand-new role name or override an existing one — merged into
`~/.docket/docket-roles.json`, "user wins" by name.

Composing several starter roles into one pod shape, in a single command, is a **pod blueprint** —
next section.

---

## Pod blueprints — named pod shapes

`docket add` doesn't have to produce a Lead+Implementer pod against a codebase. A **pod blueprint**
(`core/blueprints.py`) is a named, versioned pod shape: a roster of archetypes, a default
pipeline, a workspace kind, and an optional default budget cap — provisioned in one command.

```bash
docket add my-market-scan --blueprint research
# Provisioning 'research' pod 'my-market-scan' (lead, researcher, analyst, writer, critic)...
```

| Blueprint | Workspace kind | Roster | Default budget | Gated step |
|---|---|---|---|---|
| `software` *(default)* | codebase | lead, implementer | (none) | implementer: mechanical |
| `research` | workdir | lead, researcher, analyst, writer, critic | $20 | critic: verdict, rework -> writer |
| `content` | workdir | lead, writer, critic | $15 | critic: verdict, rework -> writer |
| `ops` | workdir | lead, operator, monitor | $30 | operator: mechanical; monitor: approval |

Omitting `--blueprint` (or passing `--blueprint software` explicitly) is exactly today's
`docket add` — same roster, same files, no behavior change. `research`/`content`/`ops` are
**`workdir`-kind**: no codebase is assumed or auto-detected; the pod gets a shared working
directory instead (auto-provisioned if you don't name one). `--pod full`/`--with` only apply to
the `software` roster — passing them against another blueprint warns and provisions that
blueprint's own fixed roster instead of trying to combine the two.

There's no `docket blueprints add` yet — the four built-ins above are the whole registry. To
compose a custom shape today, provision the closest built-in and add roles by hand with
`docket pod <project> add <role>`.

---

## Org specialists — shared across the fleet

`docket init` creates the cross-cutting specialists once. They are genuinely fleet-wide, so a
per-project copy would be waste:

- **manager** — cross-cutting coordination (transitional; `docket team`'s queue was retired in
  favor of per-pod dispatch — see below — so this role is being superseded by per-pod Leads).
- **knowledge** — documentation, research, pattern extraction across projects.
- **security** — deep security audits and threat modelling.

These three are the **only** org specialists docket provisions. Implementer/Reviewer/Tester (and
any starter or custom role) are pod-scoped — see "Project pods" above — never shared singletons.

### Optional: the org Portfolio Manager

`docket init --portfolio` adds **one** `portfolio-manager` (`scope: org`): a cross-pod
**planning and visibility** surface. It sees fleet *metadata* — which pods exist, their queues,
budgets, and health — **not project code.** It is advisory: it recommends where to focus,
rebalance, or pause, in words for a human. It never edits code and does not dispatch into pods
(each pod's own Lead owns execution). It is opt-in, and it is never a pod member.

---

## Why this structure matters — three defects it fixes

The pod model is not decoration. It exists to fix three concrete failures of the naive
"one agent per project + a few shared workers" setup docket used before Phase 10:

1. **Two doers (no clear owner of completion).** Before Phase 10, a project agent *and* a shared
   `programmer` specialist could both implement, so neither reliably finished a task. In a pod, the
   **Implementer is the single doer** and the **Lead never edits code** — one writer, one owner.
2. **Broken isolation.** That pre-Phase-10 shared `programmer` specialist served every project from
   *one* workspace and *one* memory — so projects leaked into each other. In a pod, **every member
   has its own workspace**; the load-bearing guarantee is *no worker agent ever serves two
   projects.*
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
orchestrator — it invokes each hop through its own turn loop (`core/agent_loop.py`), captures the
result, and threads it to the next role. This is the **real fix for "delegation wasn't real."**

```bash
docket pod myapp delegate "Fix the null-token login crash"   # queue a task
docket pod myapp queue                                        # see the queue + per-task status/cost
docket pod myapp dispatch                                     # run the pipeline once, now
docket serve --dispatch                                       # background: drive every pod's queue each refresh
```

Each hop that isn't the Lead is **gated** before the pipeline advances past it:

- **Implementer → mechanical gate.** If the Implementer has a `verifyCmd` set
  (`docket pod <project> add --verify "<cmd>"` or `docket pod <project> set-verify <member-id>
  "<cmd>"`), dispatch runs it after a successful hop and a nonzero exit fails the task, never
  advancing to Reviewer/Tester. An unset `verifyCmd` is never silently skipped — it's a visible
  "verification skipped" line, so you can always tell "not configured" from "configured and
  passing."
- **Reviewer → verdict gate, with bounded rework.** The first non-blank line of the Reviewer's
  reply is parsed for `APPROVE`/`REQUEST-CHANGES`. A `REQUEST-CHANGES` sends the task back to the
  Implementer with the Reviewer's feedback attached, bounded by a rework budget (`maxReworkCycles`,
  default 1); exhausting it — or a second rejection — fails the task.
- **Tester → verdict gate, hard fail.** The first non-blank line is parsed for `PASS`/`FAIL`.
  Unlike the Reviewer, there is no rework loop here — a `FAIL` or unparseable output fails the
  task outright.

Three guarantees hold on every dispatch:

- **Budget-gated.** Before *each* hop docket checks the pod's token-based dollar estimate against
  the Lead's budget cap (`docket profile <project>-lead --budget N`) — docket's own turn loop
  reports no billed spend, so the gate always runs off this labelled estimate. Over budget → the
  task is left **pending** (blocked), not run.
- **Traced.** Every hop emits a Phase-8 trace event (`docket trace`), on a per-task session
  `agent:<project>:<task_id>` — so a run is fully auditable, with no manual Telegram relay.
- **Pod-local.** Dispatch only ever targets the project's own pod members. **There is no
  cross-pod dispatch path** — one pod can never run another pod's agents.

> Each hop is a real, costed LLM turn. That is why dispatch is explicit (`docket pod … dispatch`)
> or opt-in (`docket serve --dispatch`) — never silent. The read-only `docket serve` monitor does
> not dispatch.

---

## Runtime-resource isolation per pod

Two pods running work at once shouldn't fight over the same port or scratch file. At provisioning,
a pod's Implementer can be allocated a disjoint **port range** and **scratch directory**
(`portRangeStart`/`portRangeCount`, `scratchDir` in `.docket-meta.json`) — disjoint from every
other pod's allocation. This isn't just prose in `TOOLS.md` for the agent to remember: dispatch
injects it into the Implementer's real subprocess environment on every hop —

```
DOCKET_PORT_BASE=<port_range_start>
DOCKET_PORT_COUNT=<port_range_count>
DOCKET_SCRATCH_DIR=<scratch_dir>
```

— layered on top of the parent environment (which is never mutated). Every other hop (Lead,
Reviewer, Tester, or an Implementer with no allocation) gets no override — today's
inherit-the-parent-env behavior.

---

## The durable task ledger

A pod Lead's `HEARTBEAT.md` carries the same resume/durability contract every agent workspace
has: in-flight work is written down before it starts, so a context reset can resume it. That
ledger used to be only as honest as the agent's own compliance. Dispatch now maintains it
**mechanically**: a delimited, docket-owned region inside `## Active Tasks`
(`core/memory.py`'s `sync_dispatch_tasks`) is rewritten from `TASK_LIST.json`'s `running` tasks at
every claim, every hop completion, and every retry — the entry for a task exists before its first
hop ever runs, whether or not the agent would have written it down itself. Everything outside that
region — an agent's own hand-written notes, every other heading in the file — is never touched by
the sync.

`docket doctor` flags any divergence between the two: a task `running` in `TASK_LIST.json` with no
matching ledger entry, or a ledger entry naming a task that is not (or is no longer) running.
`--fix` re-syncs the ledger from `TASK_LIST.json`, which is always the source of truth.

---

## Identity — role first, persona optional

An agent's identity is a pure function of its metadata: **role** (structural — "I am this pod's
Implementer," from `SOUL.md`) plus an optional **persona** (cosmetic — a display name/emoji,
purely a skin docket controls).

```bash
docket persona myapp-lead set "Orion 🔭"   # give the Lead a display name
docket persona myapp-lead show             # see the current persona
docket persona myapp-lead clear            # back to role-only
```

The persona lives in a marked block inside `SOUL.md` (it survives `docket maintain rebuild`) and
never replaces the role itself — a persona-carrying agent is still, structurally, "the
Implementer." Display names (`docket list`/`info`) resolve persona → name → role, never from a
self-authored `IDENTITY.md`. docket also quarantines the base-assistant self-authoring scaffolding
a model may leave behind (`IDENTITY.md`, `BOOTSTRAP.md`) out of managed workspaces — on
provisioning, and again on `docket doctor` — moving any that appear into `.docket-archive/`.
Identity in a docket-managed workspace is docket-owned, never self-written by the agent.

---

## Composing a team — how big should a pod be?

Start lean and grow only when the work earns it:

| Situation | Pod |
|-----------|-----|
| Prototyping, low-risk changes, solo project | **lean** (Lead + Implementer) — the default |
| Code that needs a correctness/security gate before it lands | add a **Reviewer** (`--with reviewer`) |
| Behaviour you want validated independently of the diff | add a **Tester** (`--with tester`) |
| High-stakes or high-blast-radius work | **full** pod (`--pod full`) |
| One Implementer is the bottleneck | `docket pod <p> add implementer` (parallel doers) |
| Non-software work (research, writing, ops) | pick a **blueprint** (`--blueprint research`) instead of building roles up by hand |

The Reviewer and Tester are the difference between "an agent changed the code" and "a change was
reviewed and validated before it landed" — the line between a prototype and a change you can let
into a real codebase.

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
role once and every policy-following agent re-resolves; pin one agent with `docket profile`. A
starter or custom archetype with no dedicated policy-table row falls back to resolving through its
own `modelClass` (`cheap`/`strong`) instead of the global default — see `docket roles show <name>`
for what class a given role carries.

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
docket init <project> [path]              # lean pod (Lead + Implementer)
docket init <project> --pod full          # + Reviewer + Tester
docket init <project> --with reviewer,tester
docket init <project> [path] --blueprint <name>   # software (default) | research | content | ops
docket pod <project>                     # list members
docket pod <project> add <role> [--count N]
docket pod <project> remove <member-id>
docket delete <project>                  # tear down the whole pod

# Role archetypes
docket roles list                        # every registered archetype
docket roles show <name>                 # one archetype's full definition
docket roles add <file.yaml>             # register/override a custom archetype
docket roles validate [file.yaml]        # dry-run schema + template validation

# Run the pipeline
docket pod <project> delegate [--priority high|normal|low] "<task>"
docket pod <project> queue
docket pod <project> dispatch
docket pod <project> add --verify "<cmd>"        # Implementer's mechanical gate
docket pod <project> set-verify <member-id> "<cmd>"
docket serve --dispatch                  # autonomous: drive every pod's queue

# Identity
docket persona <member-id> set "<label>" # optional display persona
docket persona <member-id> clear
docket persona <member-id> show

# Org specialists
docket init                           # manager, knowledge, security
docket init --portfolio               # + the optional org Portfolio Manager (advisory, read-only)
```

> `docket team` (the org manager's own task queue) was **retired** — every project's pod owns
> its own delegate/queue/dispatch now (see above). There is no remaining org-wide queue; the
> optional Portfolio Manager is advisory-only and never dispatches.
