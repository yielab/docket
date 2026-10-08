# Agent Teams (Pods) — the heart of docket

> **This is the most important concept in docket.** docket gives a repository a team of coding
> agents and governs what they may do; the team is YAML in `.docket/`. This guide explains the
> roles, pods and gates that YAML describes. If you read one guide, read this one.

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
| **scope** | `project` | Owned by exactly one project; no agent is shared between pods |
| **role** | lead, implementer, reviewer, tester, … | What the agent is *for* |

Every team member lives in a **project pod** — `scope: project`, a self-contained team **per project**, never shared.

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
| **Lead** | **never** | Orchestrates the pod, owns its context and memory, decomposes work, dispatches to workers; surfaces architectural decisions and risky actions at the top of the plan with assumptions and open questions listed | cheap (coordination) |
| **Implementer** | **yes** | Runs *inside* the project workspace and writes the code | strong (reasoning-dense) |
| **Reviewer** *(optional)* | no (read-only) | Veto on the diff — correctness + security gate | cheap |
| **Tester** *(optional)* | no | Behaviour-only validation: PASS / FAIL | cheap |

Member ids are predictable: `myapp-lead`, `myapp-implementer`, `myapp-implementer-2`,
`myapp-reviewer`, `myapp-tester`. Because each is an ordinary registered agent,
`docket status --all`/`info`/`cost`/`doctor` see every pod member for free.

```bash
docket init myapp ~/code/myapp       # lean pod: myapp-lead + myapp-implementer
docket init myapp ~/code/myapp --pod full        # full pod: + reviewer + tester
docket init myapp ~/code/myapp --with reviewer   # lean pod + a reviewer
cd ~/code/myapp && docket init       # same lean pod, id/path/stack derived from the cwd;
                                     # a committed .docket/ is validated and applied
docket init --recipe secure-build    # lean pod + a shipped recipe (or a directory of your own)
docket pod show                      # inspect the pod and its roles
docket pod add reviewer              # add a role to an existing pod (never creates one)
docket pod add implementer           # scale out: adds another implementer
docket pod add reviewer              # add a role later
docket pod remove <member-id>        # drop a member
docket pod delete                    # tear down the whole pod
```

A pod has **exactly one Lead** (its single orchestrator); every other role may be duplicated.

---

## Role archetypes — roles are data, not hardcoded branches

Before this was declarative, a pod role was a closed 4-tuple wired into `core/pod.py`, and each
role's identity prose was hand-written string-building in the CLI. Adding a fifth role meant
editing code. Now every role — including the four legacy ones — is a **role archetype**
(`core/archetypes.py`): a versioned, declarative record of its scope, model class, identity
templates, gate contract, denied tools, and tool profile.

```bash
docket pod roles                 # every registered archetype: built-in, starter, user
docket pod roles reviewer        # one archetype's full definition (YAML/JSON)
docket pod apply ./producer.yaml  # register a custom archetype from a YAML file
docket pod validate ./producer.yaml   # dry-run the schema + template render
```

Four **built-in** archetypes reproduce the legacy roles byte-identically. A **starter library**
ships six more you can drop into any pod without writing a line of YAML:

| Name | Class | Gate | Denied tools |
|---|---|---|---|
| `lead` *(built-in)* | cheap | none | write, edit, bash |
| `implementer` *(built-in)* | strong | mechanical (`verifyCmd`) | none |
| `reviewer` *(built-in)* | cheap | verdict (APPROVE / REQUEST-CHANGES) | write, edit, bash |
| `tester` *(built-in)* | cheap | verdict (PASS / FAIL) | write, edit |
| `researcher`, `analyst` *(starter)* | strong | none | none |
| `writer` *(starter)* | cheap | none | none |
| `critic` *(starter)* | cheap | verdict (APPROVE / REJECT) | write, edit, bash |
| `operator` *(starter)* | strong | mechanical | none |
| `monitor` *(starter)* | cheap | approval | write, edit, bash |

Provisioning a starter role into a live pod works exactly like any other role:
`docket pod add researcher`. A user-authored archetype (a standalone YAML file,
`docket pod apply`) can add a brand-new role name or override an existing one — merged into
`~/.docket/docket-roles.json`, "user wins" by name; `--pod <p>` scopes it to one pod. A denied tool
is absent from that role's turn, not merely discouraged: it is the only capability statement a role
carries (`cannot:` in the short form), and denying a tool denies every tool of its kind, MCP tools
included.

A custom role's hop message is also data: an archetype can declare its own `hopInstruction` text;
if it doesn't, one is generated from its `gateContract` (a verdict role, for example, is told its
exact `APPROVE`/`REJECT`-style marker convention). Either way, a pipeline step's own `instructions`
(when set) overrides it for that one hop — see [Pipelines](WORKFLOW-GUIDE.md#pipelines-the-one-dialect-docket-runs)
in the Workflow Guide.

Composing several starter roles into one pod shape, in a single command, is a **pod blueprint** —
next section.

---

## Pod blueprints — named pod shapes

`docket pod add` doesn't have to produce a Lead+Implementer pod against a codebase. A **pod blueprint**
(`core/blueprints.py`) is a named, versioned pod shape: a roster of archetypes, a default
pipeline, a workspace kind, and an optional default budget cap — provisioned in one command.

```bash
docket init my-market-scan --blueprint research
# Provisioning 'research' pod 'my-market-scan' (lead, researcher, analyst, writer, critic)...
```

| Blueprint | Workspace kind | Roster | Default budget | Gated step |
|---|---|---|---|---|
| `software` *(default)* | codebase | lead, implementer | (none) | implementer: mechanical |
| `research` | workdir | lead, researcher, analyst, writer, critic | $20 | critic: verdict, rework -> writer |
| `content` | workdir | lead, writer, critic | $15 | critic: verdict, rework -> writer |
| `ops` | workdir | lead, operator, monitor | $30 | operator: mechanical; monitor: approval |
| `agentic-product` | codebase | lead, implementer, reviewer, tester | (none) | implementer: mechanical; reviewer: verdict, rework -> implementer; tester: verdict, hard fail |

Omitting `--blueprint` (or passing `--blueprint software` explicitly) is exactly a plain
`docket init` — same roster, same files, no behavior change. `research`/`content`/`ops` are
**`workdir`-kind**: no codebase is assumed or auto-detected; the pod gets a shared working
directory instead (auto-provisioned if you don't name one). `agentic-product` is `codebase`-kind
like `software`, but its roster is the full Lead+Implementer+Reviewer+Tester set, so both gated
steps actually reach a hop at dispatch time instead of going unreached behind `software`'s lean
default roster — the intended shape for a pod that ships its own agent to end users, where the
review + test gate is warranted by default rather than opt-in. `--pod full`/`--with` only apply to
the `software` roster — passing them against another blueprint warns and provisions that
blueprint's own fixed roster instead of trying to combine the two.

The five built-ins above are the whole blueprint registry. To
compose a custom shape today, provision the closest built-in and add roles by hand with
`docket pod add <role>`. For a pre-built shape instead of composing by hand, use a
**recipe**. Eighteen ship with docket: teams (`secure-build`, `research-review`,
`ops-approval`, `intake`), policy packs that change no roster (`git-safety`, `no-egress`,
`secrets-guard`, `prod-approval`), methodology pipelines that are the practice (`tdd`,
`spec-first`, `spec-writer`, `reflexion`, `dual-review`, `cross-family-review`, `frugal`), checks
that fail a task whose tests prove nothing (`anti-tautology`, `mutation`), and a tool pack
(`code-intel`). `docket pod recipes` shows what each brings, derived from
its files; `docket init --recipe tdd` starts a new pod from one, `docket pod apply
git-safety` applies one onto a pod that already exists, and a directory under
`~/.docket/recipes/<name>/` is addressable the same way. A recipe is the same directory shape as
a repository's own `.docket/`, which plain `docket init` discovers, validates and applies when it
is committed next to the code — see [the recipe library](recipes.md),
[CONFIGURATION.md §3.10](CONFIGURATION.md#310-start-from-a-recipe) and
[§3.11](CONFIGURATION.md#311-keep-the-team-in-the-repo).

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

The `docket run` command drives a pod's queued work through its pipeline, **one real agent turn per hop**:

```
Lead  →  Implementer  →  Reviewer (if present)  →  Tester (if present)
```

That is the built-in order when no pipeline is bound; a `kind: pipeline` in `.docket/` (or a
recipe) sets the order, the gates and the rework instead. Only the roles a pod actually has take
part (a lean pod runs two hops). docket stays the
orchestrator — it invokes each hop through its own turn loop (`core/agent_loop.py`), captures the
result, and threads it to the next role. This is the **real fix for "delegation wasn't real."**

```bash
docket task add "Fix the null-token login crash"   # queue a task
docket task list                                        # see the queue + per-task status/cost
docket run                                     # run the pipeline once, now
docket start --dispatch                                       # background: drive every pod's queue each refresh
```

Each hop that isn't the Lead is **gated** before the pipeline advances past it:

- **Implementer → mechanical gate.** If the Implementer has a `verifyCmd` set
  (`docket pod add implementer --verify "<cmd>"` or
  `docket pod set verify "<cmd>" --member <member-id>`), dispatch runs it after a successful hop and a nonzero exit fails the task, never
  advancing to Reviewer/Tester. An unset `verifyCmd` is never silently skipped — it's a visible
  "verification skipped" line, so you can always tell "not configured" from "configured and
  passing."
- **Reviewer → verdict gate, with bounded rework.** The Reviewer's reply must carry exactly one
  of `APPROVE`/`REQUEST-CHANGES` at the start of a line (two different markers are unparseable). A `REQUEST-CHANGES` sends the task back to the
  Implementer with the Reviewer's feedback attached, bounded by a rework budget (`maxReworkCycles`,
  default 1); exhausting it — or a second rejection — fails the task.
- **Tester → verdict gate, hard fail.** The reply must carry exactly one of `PASS`/`FAIL` at the start of a line.
  Unlike the Reviewer, there is no rework loop here — a `FAIL` or unparseable output fails the
  task outright.

Three guarantees hold on every dispatch:

- **Budget-gated.** Before *each* hop docket checks the pod's token-based dollar estimate against
  the Lead's budget cap (`docket pod set budgetUsd N`) — docket's own turn loop
  reports no billed spend, so the gate always runs off this labelled estimate. Over budget → the
  task is left **blocked** (not run) and the pod's Lead is paused until you raise its cap or run
  `docket run --resume`.
- **Traced.** Every hop emits a Phase-8 trace event (`docket task trace`), on a per-task session
  `agent:<project>:<task_id>` — so a run is fully auditable, with no manual Telegram relay.
  An enabled trace exporter sends the same session to OpenTelemetry or Langfuse, at the privacy
  level you set for it (`docket setup export`).
- **Pod-local.** Dispatch only ever targets the project's own pod members. **There is no
  cross-pod dispatch path** — one pod can never run another pod's agents.

> Each hop is a real, costed LLM turn. That is why dispatch is explicit (`docket run`)
> or opt-in (`docket start --dispatch`) — never silent. The read-only `docket start` monitor does
> not dispatch.

**A hop that needs a human doesn't stall the other pods.** A pipeline `approval` step, a
`requireApprovalRoles` gate, or a tool call an Implementer's own turn wants to `ask` about all
move the task to `waiting_approval` rather than failing it. Under `serve --dispatch`'s sweep or a
non-interactive `dispatch`, that `ask` **parks** — it records the exact call and moves on to the
next pod in the same sweep, instead of blocking a thread for up to two minutes. Everything that
needs you, across every pod, shows up in one place (`docket inbox`), and a notification channel you
enable (`docket setup notify enable desktop`, `ntfy` or `telegram`; the default `console` sends
nothing, and `docket setup` says so) can push it to you instead of waiting for you to look. Answer it the same way you'd answer any approval (`docket task approve`/
`docket task deny`, or a channel that can `decide`) and the exact hop that parked re-runs, carrying a
single-use pre-grant so the model's identical next call passes without asking twice. A pipeline
can also pause a task to ask a genuine *question* rather than a permission — an `input` step, or
the Lead's own typed intake brief when it decides it's missing something — which is `docket task answer
<task-id>` or `docket task answer`'s job, not `docket task approve`'s. See
[SECURITY-SIMPLE.md](SECURITY-SIMPLE.md)'s "operator loop" section for the full mechanism.

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

`docket setup` flags any divergence between the two: a task `running` in `TASK_LIST.json` with no
matching ledger entry, or a ledger entry naming a task that is not (or is no longer) running.
`--fix` re-syncs the ledger from `TASK_LIST.json`, which is always the source of truth.

---

## Identity — role first

An agent's identity is a pure function of its metadata: its **role** (structural — "I am this pod's
Implementer," from `SOUL.md`). Display names resolve from role; docket-managed workspaces never read
self-authored `IDENTITY.md`. Identity in a docket-managed workspace is docket-owned, never self-written by the agent.

A turn's prompt is composed from three instruction layers, in order: docket's own **generated**
templates (`SOUL.md`, `AGENTS.md`, `TOOLS.md`, re-rendered by `docket pod apply` when
they drift from the current archetype), the **operator-owned** `INSTRUCTIONS.md` right after
`SOUL.md` (docket never writes it, so it survives a `sync`/rebuild), and a
`projectInstructions` section — the repository's `AGENTS.md` by default, or the codebase files
named with `docket pod set projectInstructions <path,...>`, screened through the same
`pre_input` policy hook as any other input and restricted to relative paths that can't escape the
codebase root. See [CONFIGURATION.md](CONFIGURATION.md) for the full reference.

---

## Composing a team — how big should a pod be?

Start lean and grow only when the work earns it:

| Situation | Pod |
|-----------|-----|
| Prototyping, low-risk changes, solo project | **lean** (Lead + Implementer) — the default |
| Code that needs a correctness/security gate before it lands | add a **Reviewer** (`--with reviewer`) |
| Behaviour you want validated independently of the diff | add a **Tester** (`--with tester`) |
| High-stakes or high-blast-radius work | **full** pod (`--pod full`) |
| One Implementer is the bottleneck | `docket pod add implementer` (parallel doers) |
| Non-software work (research, writing, ops) | pick a **blueprint** (`--blueprint research`) instead of building roles up by hand |

The Reviewer and Tester are the difference between "an agent changed the code" and "a change was
reviewed and validated before it landed" — the line between a prototype and a change you can let
into a real codebase.

---

## Session keys & isolation

Pod members share the project's session-key namespace (`agent:<project>:<key>`), which keeps the
pod's conversation context together and **isolated from every other project**. Dispatch runs each
task on its own per-task session (`agent:<project>:<task_id>`) so tasks don't bleed into each
other. The real isolation
primitive, though, is the **per-member workspace** — session keys isolate conversation; separate
workspaces isolate files, memory, and identity.

---

## Per-role model policy

Each role maps to the **cheapest model adequate for its workload** — coordination and
review/test are cheap-class; the Implementer (and security audits) get the strong class. Change a
role once and every policy-following agent re-resolves; override per-pod with a role overlay or set per step (`model:` in the pipeline). A
starter or custom archetype with no dedicated policy-table row falls back to resolving through its
own `modelClass` (`cheap`/`strong`) instead of the global default — see `docket pod roles <name>`
for what class a given role carries.

| Role | Policy key | Default class |
|------|-----------|---------------|
| Lead | manager | cheap |
| Implementer | programmer | strong |
| Reviewer | reviewer | cheap |
| Tester | tester | cheap |

See [Architecture (DOCKET)](DOCKET.md) for the routing internals and
[Command Reference](commands.md) for every flag.

---

## Command reference (teams)

```bash
# Provision / resize a pod
docket init                               # lean pod for the cwd (id, path, stack derived from it)
docket init <project> [path]              # lean pod (Lead + Implementer)
docket init <project> [path] --pod full   # + Reviewer + Tester
docket init <project> [path] --with reviewer,tester
docket init <project> [path] --blueprint <name>   # software (default) | research | content | ops
                                                   # | agentic-product
docket pod recipes                      # the eighteen shipped recipes and your own, what each brings
docket init --recipe <name|dir>          # + a recipe (a team, a policy pack, a methodology) or
                                         #   your own directory; a committed .docket/ is applied
                                         #   by plain `docket init`
docket pod apply <name|dir>    # apply a recipe name or a directory such as .docket
docket pod export [<dir>]      # write the pod's own scope back to .docket/
docket pod validate [<dir|file>]       # check every kind: document before applying
docket pod show                         # list members
docket pod add <role> [--count N]
docket pod add <role> [--pod <name>] [--count N]  # same, from outside the repo
docket pod remove <member-id>
docket pod delete                      # tear down the whole pod

# Role archetypes
docket pod roles                        # every registered archetype
docket pod roles <name>                 # one archetype's full definition
docket pod apply <file.yaml>             # register/override a custom archetype
docket pod validate [file.yaml]        # dry-run schema + template validation

# Run the pipeline
docket task add [--priority high|normal|low] [--brief FILE.json] "<task>"
docket task list
docket run
docket pod add implementer --verify "<cmd>"   # Implementer's mechanical gate
docket pod set verify "<cmd>" --member <member-id>
docket start --dispatch                  # autonomous: drive every pod's queue

# The operator loop: what needs you, and answering it
docket inbox [--json] [--since <iso>] [--peek]           # everything across every pod that needs you
docket task answer <task-id> [--pod <project>]                  # see + answer one task's parked question
docket task answer <task-id> [text]                   # answer, non-interactively
docket task approve <task-id> --for "<command>"         # pre-approve one exact call
docket setup notify list                                # who gets notified, and how much they see
docket setup notify flush                               # push pending notifications now

```

> Every project's pod owns its own delegate/queue/dispatch (see above). There is no org-wide
> queue.
