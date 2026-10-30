# docket architecture

**docket — agent teams as configuration. Your rules, in YAML.**

The complete technical guide to how docket runs a repository's team of agents: roles, dispatch,
memory, security and cost.

> [!WARNING]
> **Beta / early-stage software.** The architecture below is implemented and automated-test-backed,
> but has not been QA-hardened in production. "Validated" in the Implementation Status section
> means *covered by the automated suite*, not field-proven — verify behavior against your own
> install. All cost figures are accounting estimates, not provider bills (see the
> [cost limits](README.md#known-limits)).

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Core Principles](#core-principles)
4. [Performance Results](#performance-results)
5. [Agent Roles](#agent-roles)
6. [Dispatch Internals](#dispatch-internals)
7. [Memory Management](#memory-management)
8. [Security Model](#security-model)
9. [Cost Optimization](#cost-optimization)
10. [Implementation Status](#implementation-status)
11. [Embedding docket-runtime](#embedding-docket-runtime)

---

## Overview

docket's design for a team of autonomous agents aims at:
- **Lower token usage** through per-pod context isolation
- **Clean role separation** — Lead orchestrates, Implementer codes, a Reviewer gates
- **Layered, convention-based security** through a read-only reviewer veto + checklist
- **Objective validation** through the Implementer's own verify command

### The Problem (Before docket)

```
Engineer: "Fix the login bug"
         ↓
One shared context (or a shared agent pool) carries every
project's history at once:
       → Reads 100K+ tokens of mixed-project history
       → Implements fix, reviews its own work
         ↓
No isolation → projects contaminate each other's context
Total: ~220K tokens in one bloated window
```

### The Solution (After docket)

```
Engineer: "Fix the login bug"   (to the <project> pod's Lead)
         ↓
Lead: Owns this pod's context/memory + human comms
    → Reads this pod's workspace contract (WORKFLOW_AUTO.md + MEMORY.md + HEARTBEAT.md)
    → Decomposes the work, dispatches to the Implementer
    → NEVER edits code
         ↓
Implementer: Runs INSIDE the project workspace
           → Reads the project files it needs (full read/write)
           → Implements fix
           ↓
Reviewer (optional): Read-only veto on the diff
        → Runs 6-point security checklist
        → Approves
        ↓
Each project's work stays inside its own pod + workspace, so
one project's context never bleeds into another's.
```

---

## System Architecture

> This section is the code-level companion to [Core Principles](#core-principles) below: those
> describe *what* a pod does; this describes how docket's own codebase is put together to make
> that real, safe to extend, and reversible if the underlying runtime ever needed to change.

### One package per context, one direction of dependency

`src/docket/` is organized as one package per business context (`kernel`, `tasks`, `pipeline`,
`hops`, `agent`, `governance`, `sandbox`, `teams`, `models`, `observability`, `operator`,
`platform`), the `interfaces/` that talk to the outside world (`cli`, `http`, `mcp`, `telegram`)
and one `bootstrap.py` that wires them together. Inside a context there are at most two levels
(`domain/`, `application/`, `adapters/`), and imports only point the way the ADR 0030 table allows:

- **`interfaces/cli/`** (Typer + Rich) — argument parsing, the interactive picker, and every line
  of Rich-rendered output. This is the only layer allowed to talk to the user; a command aborts by
  raising `typer.Exit` and renders whatever typed result a context handed back (a `TaskResult`, a
  `VerifyResult`, a `CompactionResult`) through `interfaces/cli/render/ui.py`'s
  `info`/`success`/`warn`/`error` helpers.
- **A context's `domain/` and `application/`** (Pydantic models + pure services) — the domain:
  agent data models, role→model policy, dispatch's state machine, security/approval/audit/trace/
  policy logic. A context never imports `interfaces/`, never prints, and every function returns a
  typed result for the interface to render.
- **`adapters/`, `platform/` and `sandbox/`** (the side-effecting code) — `platform/store.py` is
  the single chokepoint for every docket-owned JSON read/write (atomic, filelocked, 0600
  permissions, `.bak` rotation); `platform/git.py` and `platform/process.py` wrap the shell-outs
  to `git` and the host and `sandbox/` owns the jail and the `docker` backend, each degrading
  gracefully when a binary is missing.

This is not a style preference — it is enforced by import-linter contracts in
`tests/architecture/`, and a couple of the newest modules in the tree exist specifically to keep
the boundary from eroding (see the RuntimeDriver port, below). The table and the full tree are
in [ADR 0030](adr/0030-organize-by-context-and-refactor-by-tool.md).

### No external daemon — docket owns the loop

Through Phase 18, Docket was a control plane wrapped around a separate agent daemon. An
Anti-Corruption Layer owned that daemon's state shape, every agent turn ran in its process, and
config changes restarted its gateway. **Phase 19 (decision D-19) removed that architecture
outright, not incrementally.** There is no external agent binary, shared daemon config,
auth-profile store, ACL module, or gateway service to restart. docket runs the agent turn itself
(`agent/loop.py`) and talks through one non-streaming OpenAI-compatible chat-completions
adapter; built-in gateways or explicitly registered compatible endpoints supply the base URL
(`models/adapters/openai_http.py`, stdlib `urllib`, no vendor SDK).

This was a scope ruling, not a migration: **no compatibility layer, no migration steps** — a
pre-Phase-19 install's files at retired daemon-relative paths are simply not read again; the first
`docket init` creates a docket-native home from scratch under `~/.docket/` (`DOCKET_HOME`).

### The RuntimeDriver port (decision D-14)

Before the daemon was removed, a mid-2026 audit found that the *execution* slice of docket's
coupling to it — parsing an agent turn's result, reading a session's on-disk JSONL, aggregating
token/cost usage — had started leaking around the ACL rather than being contained by it.
`agent/ports.py` is the fix that outlived the daemon it was first built for: a single
typed `Protocol` — `RuntimeDriver` — that the contexts and `interfaces/` program against instead of a concrete
driver's on-disk knowledge. It has four members:

- `run_turn` — one costed agent turn: the hot path `hops/application/runner.py` calls for every
  hop, and, per decision D-18, docket's own self-originated LLM calls (session compaction)
- `list_sessions` / `usage` — durable-session enumeration and token/cost aggregation
- `capabilities` — what this driver instance can actually promise (for example, whether it
  reports a real USD cost at all), so a caller never hardcodes an assumption about the one
  shipped driver's quirks

`hops/application/driver.py`'s `DocketDriver` — docket's own turn loop, running directly
against a configured model endpoint — is the **one shipped implementation** since Phase 19
P19-7b replaced the daemon-facing driver this port originally shipped with; a `FakeDriver` test
double (`tests/support/fakes.py`) is the one test double. This is a deliberately narrow move.
docket's architectural principles carry a standing ban on an `AbstractBackend`/plugin framework,
and decision D-14 *revises* that ban rather than repealing it: the port is containment of coupling
that already existed, not speculative generality. **There is one shipped driver.** A second real
driver still needs a real trigger (a paying user who needs a different runtime), not the existence
of the port itself; adding driver discovery, entry points, or a config-selectable backend ahead of
that would be scope creep, not follow-through. One consequence worth stating plainly: `DocketDriver`
never populates a real USD cost — `usage().totals.cost_usd` is always `0.0` — see
[Cost Optimization](#cost-optimization) and the [cost limits](README.md#known-limits).

### One door for a program

A program that plans work (a project manager, a CI job, an operator's script) does not spawn
docket. It talks to a running `docket start --dispatch` over HTTP: it enqueues an addressable
task on a pod, follows its hops, cancels, retries and diffs it, reads and applies the pod's
configuration, and reads the corrections ledger. Those routes (`interfaces/http/routes/`) call the same context functions the
CLI uses, behind the same Bearer token, policy hooks and audit entries, and the program negotiates
the version it needs from `apiVersion` in `GET /status.json`. The contract is
[`specs/api/operator-api.spec.md`](../specs/api/operator-api.spec.md) and the read shapes are in
[`specs/data/serve-read-api.spec.md`](../specs/data/serve-read-api.spec.md). `docket task add` and
`docket run` are the same path for a person at a terminal.

### Configuration — one owner, one writer

Every agent's state lives in two docket-owned files, split by who reads them and written **only**
by docket, through `platform/store.py`:

- **`.docket-meta.json`**, in each workspace — per-agent facts: kind, role, name, codebase, stack,
  model, description, `sessionKey`, `projectKey`, budget, and platform-era
  additions like `blueprint`/`workspaceKind`/`workDir` and a pod's allocated
  `portRangeStart`/`portRangeCount`/`scratchDir`
- **`~/.docket/fleet.json`** (`teams/fleet.py`) — agent registration, channel bindings, gate/
  isolation flags. Provider endpoints live in `docket-providers.json` (`models/catalog.py`,
  the catalog of `kind: provider` documents) since Phase 29

The org-wide default model lives in `~/.docket/docket-models.json`'s `default` field, not
`fleet.json`, so `docket-models.json` is the single source of record.

This is a narrower split than it looks: `fleet.json` deliberately does **not** duplicate `model`/
`sessionKey`/`projectKey` — those stay `.docket-meta.json`'s job alone. Before Phase 19, the
second store was owned by an external daemon that could mutate it independently of Docket (or be
hand-edited, or touched by its own CLI) — which is exactly what
the retired `sync` module's drift check used to exist to catch. With both files now written only by docket
through one code path, "a different program touched this file" is no longer possible, and that
drift-detection machinery (the ACL, the `sync` module, `docket setup`'s session-key-sync check) is
retired along with the daemon rather than kept around for a problem that no longer exists.

### Durable state docket owns

A model's context window is lost on reset, so docket keeps a handful of small, docket-owned
stores, all under `~/.docket/`:

- **Session history** (`agent/session.py`, `$SESSIONS_DIR`, default `~/.docket/sessions/`) —
  durable per-session message history, loaded by `agent/loop.py` before each turn and
  appended after it. Once a session outgrows the role's budget it is compacted on the live turn
  path: older messages are summarised, and an assistant tool call is never separated from its
  tool results.
- **`HEARTBEAT.md`'s dispatch ledger** — every pod Lead's `HEARTBEAT.md` carries a delimited,
  docket-owned region inside its `## Active Tasks` list that `tasks/application/record.py` upserts
  (through `teams/agent_memory.py`'s `sync_dispatch_tasks`)
  mechanically at claim, at every persisted hop, and at finalize — not prose an agent is trusted
  to keep current by convention. `docket setup` flags a task the queue marks `running` with no
  matching ledger entry, or a ledger entry for a task that no longer is, and `--fix` re-syncs the
  ledger to exactly what the queue says. See [Dispatch Internals](#dispatch-internals).
- **The conversation registry** (`teams/conversations.py`, `docket-conversations.json`) — one
  record per channel thread docket is tracking (agent, peer, topic, status, a resume pointer),
  seeded on `docket setup notify bind` and cleaned up on `docket pod delete`. Dispatch and `docket start` keep `last_message`/
  `task_ref` current automatically as a task moves, tracked by the notification system.
- **Escalations** (`platform/store.py`, `~/.docket/escalations/`) — one 0600 record per pause (an
  approval, a consult, an `input` question, a gate, a changed check). A pending one lives in
  `escalations/`; once settled (resolved, expired or decided) it moves to `escalations/settled/`, so
  `docket inbox` and Tack's poll scan only the live pauses. The `docket start` sweep deletes settled records
  after `TRACE_RETENTION_DAYS`, the knob that bounds traces; a resolved record whose answer the task
  has not applied yet is kept. `_seq.json` numbers them and is never reset.
- **The audit log** (`governance/audit.py`, `~/.docket/audit.log`, 0600) — one JSON line per
  mutating operation; secret values are never logged. Every line carries a monotonic `seq` and a
  `prev_hash` (the SHA-256 of the previous line's canonical JSON), so `docket log verify` can
  walk the chain and report the first broken link; a missing file is an honest chain start, not
  tampering, and a line without `seq`/`prev_hash` is reported as a break. Rotation does **not** restart the chain: the first entry
  after a size-triggered rotation names the generation it continues, checked against the single
  backup (`audit.log.1`), and an unsubstantiated claim is reported as a break. That makes erasure
  *evident*, not impossible — deleting `audit.log` and `audit.log.1` together still looks like a
  fresh install, and only one rotation back is verifiable. There is
  no environment kill switch — recording is best-effort (a write failure never raises) but cannot
  be silently disabled.
- **Traces** (`observability/trace.py`, `$TRACES_DIR/<project>/<session_id>.jsonl`) — one append-only file
  per session, one line per observable event (hop starts, tool calls, gate outcomes, retries,
  guardrail trips, budget warnings). `docket task trace`/`docket status` read this store;
  `DOCKET_NO_TRACE=1` disables writes. The same records, as they are written, are also the only
  input to trace export (`observability/telemetry.py`): an enabled `kind: exporter` receives them as
  OpenTelemetry spans, filtered by its privacy level, so a destination such as Langfuse shows a
  projection of this store, never a second source of truth. Conversation content (prompts,
  replies, tool output) enters this store only while some enabled exporter grants it. See
  [Configuration §3.14](CONFIGURATION.md#314-export-traces-to-opentelemetry-or-langfuse).

These stores do not all go through `platform/store.py`'s locked read-modify-write path — audit and
trace are exempt by design (line-independent JSONL appends, not a whole-document
read-modify-write), while session history, the conversation registry and the dispatch queue
backing the ledger do use `store.py`.

---

## Core Principles

### 1. Per-Pod Context Isolation

**Each project's context stays inside its own pod.**

- Every pod has its own workspace and per-pod session key
- The Lead reads this pod's workspace contract (`WORKFLOW_AUTO.md`, `MEMORY.md`,
  `HEARTBEAT.md`), not a shared cross-project history
- The Implementer runs inside the project workspace, reading only the files it touches
- The Reviewer reads the diff only, not the entire file

**Result:** no project's context bleeds into another's, so per-agent token counts stay scoped to one project

### 2. Lean Pods by Default

**Don't add workers you don't need.**

`docket init` provisions a lean **Lead + Implementer** pod:
```
Pod size            Members                    When
─────────────────────────────────────────────────────
Lean (default)      Lead + Implementer         most projects
Full (--pod full)   + Reviewer                 higher-stakes code
Custom (--with ...) Lead + Implementer + any   pick the gates you want
```

**Result:** each project runs the smallest pod that does the job

### 3. Linear Pipeline (and it really runs)

**Each role has ONE job. No overlapping work.**

```
Lead → Implementer → Reviewer
       (implement)   (veto)
```

NOT:
```
Implementer ──┐
Reviewer   ───┴→ All work in parallel (wasteful, redundant)
```

This pipeline is no longer just a convention in the templates — docket **actually executes it**,
one real agent turn per hop. Only the roles a pod has take part (a lean pod runs two hops:
Lead → Implementer):

```bash
docket task add "Fix the null-token login crash"  # queue a task
docket task list                                      # see the queue + per-task status/cost
docket run                                   # run the pipeline once, now
docket start --dispatch                                         # background: drive every pod's queue
```

Three guarantees hold on every hop:

- **Budget-gated.** Before each hop docket checks the pod's token-based dollar estimate against
  the Lead's budget cap (`docket pod set budgetUsd N`). The first hop that would
  exceed it
  pauses the pod's Lead (`docket run --resume` clears it) and leaves the task
  **blocked**, not run — every further claim against that pod is refused outright until it's
  resumed.
- **Traced.** Each hop emits a trace event (`docket task trace`) on a per-task session
  `agent:<project>:<task_id>` — every run is auditable, no manual Telegram relay.
- **Pod-local.** Dispatch only ever targets the project's own pod members. **There is no
  cross-pod dispatch path** — one pod can never run another pod's agents.

Each hop is a real, costed LLM turn, which is why dispatch is **explicit** (`docket run`) or **opt-in** (`docket start --dispatch`) — never silent. Plain `docket start` is a
read-only monitor and does not dispatch. Stopping `docket start` (or `docket stop`) takes two signals when work is in flight:
the first (Ctrl-C or SIGTERM) stops new work and waits for the pod sweeps already running; a second
requests cancellation of each sweep run, so its task ends `cancelled`, and exits 130 or 143.

This is the outline; the actual state machine also retries a hop that fails on a transient hiccup
(a timeout or the model endpoint erroring — `TurnResult.failure_kind`'s `timeout`/`daemon_error`,
a name that predates Phase 19 and now just means "the turn itself didn't complete cleanly," not a
live external process), can stop a task at a human approval gate, and generalizes what "Reviewer"
means past that one hardcoded role. See [Dispatch Internals](#dispatch-internals)
for the full mechanics.

**Result:** No wasted parallel work — and the hand-off between roles actually executes.

---

## Performance Results

### Token Usage

The lever docket actually controls is **per-pod context isolation** (see the
[Before/After](#the-problem-before-docket) diagram above) — token reduction is what isolation
controls and what you can measure, not a fixed percentage. Read your measured token counts with
`docket status` (it records no dollar spend; the budget gate uses a labelled token-based estimate,
and `docket setup model` shows comparative pricing); see
[Cost Optimization](#cost-optimization) below for the model-selection half of the story.

### Response Time

Isolated pods process less context per turn, so the Lead can answer status/memory queries
quickly (it reads its own workspace contract — `MEMORY.md`/`HEARTBEAT.md` — rather than a full
cross-project history), while code changes still take as long as the Implementer needs to do the
work. Measure actuals for your own workload rather than relying on fixed figures.

---

## Agent Roles

> **Concepts live in [Agent Teams (Pods)](AGENT-TEAMS.md)** — the canonical reference for the
> pod model (scope vs role, why pods exist, how to compose one). This document is the *technical*
> deep-dive: routing, context isolation, dispatch internals, and per-role wiring.

Every agent is a **pod role**: project-scoped and created per project by
`docket init` (managed with `docket pod`).

## Pod Roles

Each project is an **isolated pod** with its own workspace and per-pod session key. A pod is a
lean **Lead + Implementer** by default; add a Reviewer with `--pod full` or
`--with reviewer`.

### Lead

**Role:** Per-pod orchestrator and human interface

**Capabilities:**
- Owns this pod's context, memory, and human (Telegram) comms
- Reads this pod's workspace contract — `WORKFLOW_AUTO.md`, `MEMORY.md`, `HEARTBEAT.md` — not
  a full cross-project history
- Decomposes work and dispatches to the pod's workers — `docket run`
  (or `docket start --dispatch`) really runs the next hop, one costed agent turn at a time
- Holds the per-pod budget cap that gates every dispatch hop
  (`docket pod set budgetUsd N`)

**Tools:** `read`, `glob`, `grep`, `fetch`, `skill`, `consult` — `write`/`edit`/`bash` are
structurally absent from its tool registry (`teams/roles.py`'s `lead` archetype declares `denied_tools=("write",
"edit", "bash")`, applied via `ToolRegistry.without()` every turn). This is a genuine tool-registry
removal, not an instruction the Lead is merely told to follow: a call to `write`/`edit`/`bash`
comes back as a tool-not-found denial before it ever reaches the gate. Dispatch to pod workers
happens structurally (docket's own dispatch pipeline invokes the next hop), not through a tool
call the Lead makes.

**Cannot:**
- **Edit code** (ever — structurally, not just by instruction)
- Run commands
- Commit
- Make architecture decisions alone

**Model:** cheap class (role policy) (coordination and dispatch, not reasoning-dense code work)

### Implementer

**Role:** Code implementation specialist

**Capabilities:**
- Runs **inside the project workspace**, with full read/write on the project
- Reads the project files it needs directly (it is in the workspace, not handed a tiny brief)
- Implements the requested change
- Its hop's reply is captured directly by dispatch as a typed `HandoffArtifact` — no completion
  file to write or poll for (see [Dispatch Internals](#dispatch-internals))

**Tools:** the full built-in set — `read`, `write`, `edit`, `glob`, `grep`, `bash`, `fetch`,
`skill`, `consult`. The
`implementer` archetype declares no `denied_tools`: "full-repo" means no built-in tool is off
limits. `bash` still passes through the same argument-aware high-risk classifier and approval
gate as every other tool call (see [Security Model](#security-model)) — an unrestricted tool
registry is not the same thing as an unrestricted gate.

**Cannot (by convention, not tool removal):**
- Review security (reviewer's job)
- Commit or push

**Model:** strong class (role policy) (code writing is reasoning-dense)

### Reviewer (optional)

**Role:** Security and quality gatekeeper

**Capabilities:**
- Read-only veto on the diff (bad code doesn't proceed)
- 6-point mandatory security checklist
- Reads the diff only, not the entire file
- Verifies root cause addressed

**Checklist:**
1. ✓ No prompt injection
2. ✓ No hardcoded secrets
3. ✓ No SQL injection / XSS
4. ✓ Auth checks present
5. ✓ No dangerous operations
6. ✓ Test coverage

**Tools:** `read`, `glob`, `grep`, `fetch`, `skill`, `consult` — `write`/`edit`/`bash` are
structurally absent (`denied_tools=("write", "edit", "bash")`), so "read-only" is a genuine registry restriction, not
a SOUL.md-only instruction: a Reviewer that tries to call `edit` gets a tool-not-found denial.

**Cannot (structurally):**
- Fix code (only reviews)
- Execute tests
- Commit

**Model:** strong class (role policy) (a judge is not weaker than the worker it judges)

**MCP tools.** Tools from configured external MCP servers (`docket setup mcp`) reach a live turn
through the same chokepoint, namespaced `mcp__<server>__<tool>`. Denials apply by capability, not
by name. Every MCP server is write-capable unless the operator declares it `--kind read` (an
operator assertion, not something docket verifies). A role that denies `write` (Lead, Reviewer) gets no tools from a server left at the default and all the tools of a `--kind read`
server; the Implementer gets both.

## Memory Management

### Problem: Large Shared Context

**Before docket:**
```
A shared agent reads:
- Full cross-project conversation history: 100K tokens
- All memory logs: 50K tokens
────────────────────────────────────
Total: 150K+ tokens per turn, growing across projects
```

### Solution: Isolated pods + the workspace contract

**After docket:**
```
The pod's Lead reads:
- its system prompt: SOUL.md, operator instructions, AGENTS.md, the live runtime contract,
  the repository's instructions and skills, and the pod's accepted memory
- its hop message: the shipped or overridden `prompts/hop/lead.md` and the task
The Implementer reads:
- only the workspace files it touches
────────────────────────────────────
Context stays scoped to one project's pod
```

There is no generated `SNAPSHOT.md`. There is no separate semantic memory index —
docket's own turn loop has no `memory_search` tool of its own; an agent searches its memory files
the same way it reads any other file, with `read`/`grep`. What actually scopes a pod's context is
the **workspace startup contract** docket provisions on `docket pod add`/`docket init` and
`docket setup` re-seeds if a workspace is missing one or has a stale version:

- **`WORKFLOW_AUTO.md`** — the startup and resume protocol for an agent that opens the workspace
  by hand. A docket turn does not send it: its system prompt carries a short live runtime contract
  in its place, and the hop message says where the tools start (at the repository root, no
  absolute path).
- **`MEMORY.md`** — long-term curated project facts (what the project is, architecture, current
  state) — written by the agent, seeded with a stub on first run.
- **`HEARTBEAT.md`** — the durable in-flight task ledger. An agent is instructed to write
  multi-step work here *before* starting it; a pod dispatch hop additionally keeps its own
  delimited region in sync mechanically (see [Dispatch Internals](#dispatch-internals)), so the
  ledger reflects real queue state, not only an agent's compliance.

A fresh `HEARTBEAT.md` seeds like this:

```markdown
# HEARTBEAT.md — mywebsite-lead

_Your durable task ledger. It survives context resets; your working memory does not._
_The moment you accept multi-step work, record it here **before** you start. Read it first
every session — unchecked items mean you were interrupted, so resume them instead of greeting
as if idle._

## Active Tasks
_none yet_

## Pending Decisions
_none_

## Notes
_none_
```

These files are the contract: recent memory-log lines, active tasks parsed from `HEARTBEAT.md`,
and `MEMORY.md`'s section headers. docket generates no separate summary artifact.

### Memory Commands

```bash
# Reset a member's workspace (distils memory, clears, and rebuilds)
docket pod reset <member-id>

# Re-seed a missing or stale WORKFLOW_AUTO.md / MEMORY.md / HEARTBEAT.md
docket setup --fix
```

### Pod Memory

What a pod learns about its repository lives in one `memory.json` per pod. A step's reply may end
with a `## Memory` section of `- <kind>: <path or command> -- <fact>` lines; when the task ends,
docket decides each entry itself. A generated path present at the task's commit and a command with
an exit status in the task's trace are accepted automatically; a pitfall or convention waits for the
operator; anything that reads as an instruction, or comes from a task that called `fetch`, is
refused or held. Accepted entries reach every member's prompt last, behind an untrusted frame, never
in docket's voice. `docket pod reset` no longer distills anything: it resets a member's ledger and
rebuilds its files. See `specs/functional/workspace-structure.spec.md`, "Pod memory".

---

## Security Model

Three automatic layers — instruction-level SOUL.md constraints (never commit/push/delete without
instruction), the Reviewer's 6-point checklist (prompt-injection patterns, hardcoded secrets,
SQL injection/XSS, auth checks, dangerous operations, test coverage) as a read-only veto, and a
final human `git diff` review. The enforced tool-call gate (policy engine plus argument-aware
high-risk command classifier) is always active and cannot be turned off, and an `ask` verdict can
be answered from any of four approval channels (CLI, HTTP, MCP, Telegram). Workspace
isolation is **opt-in** (`docket setup sandbox on`: Landlock on Linux, seatbelt on macOS, Docker when chosen;
`docket setup sandbox network none` then cuts the jail's network). Since Phase 34 (D-50), an unattended pod's
in-turn `ask` **parks** the task (`waiting_approval`) rather than blocking the turn, and a
separate, opt-in notification layer (`docket setup notify`, off by default except `console`) is what
tells a human one is waiting — the approval mechanism and its four channels are unchanged. Full
detail, including the exact reviewer checklist, gate/approval-channel mechanics and the operator
loop, lives in
**[SECURITY-SIMPLE.md](SECURITY-SIMPLE.md)** — this section intentionally isn't a second copy.

A declarative policy engine (`docket pod policies`) adds a fourth layer on the dispatch path itself —
`pre_input`/`pre_output` hooks that can redact, warn, block, or route a task to human approval.
See [The policy engine on the dispatch path](#the-policy-engine-on-the-dispatch-path) for the
mechanics. Since Phase 19, this is no longer the whole in-turn story either: `pre_tool_call` —
the third policy hook, evaluated inside `agent/tools/registry.py`'s `dispatch_tool` chokepoint alongside the
high-risk command classifier — is now **live** on every tool call docket's own turn loop makes,
closing the gap where docket's policy templates existed but nothing inside a running turn ever
evaluated them.

What leaves the machine is governed separately, and closed by default: every trace exporter
ships disabled and at `privacy: minimal` (structure only), sharing more is a confirmed command
recorded in the audit log, and the span projection is an allowlist, so an attribute nobody has
classified never leaves. SECURITY-SIMPLE.md's Layer 6 has the detail.

---

## Cost Optimization

### Model Selection

The role→model policy assigns each role to either the **cheap class** (high-volume / low
reasoning-density) or the **strong class** (reasoning-dense):

| Class  | Roles                                                    | Why                              |
|--------|----------------------------------------------------------|----------------------------------|
| Cheap  | Lead                                                     | High-volume or mechanical work |
| Strong | Implementer, Reviewer                                    | Code writing and judging it      |

Change the policy for a role with `docket setup model set <role> <provider/model>`, or switch all
roles at once with a provider preset (`docket setup model preset openai`). Override per-pod with a role overlay
or per-step with `model:` in the pipeline.

**Result:** routine orchestration and review runs on the cheap model class with
project-scoped context — fewer tokens at a lower per-token price. (docket records measured
tokens, not dollar spend; dollar figures are estimates — `docket setup model` for comparative pricing,
the budget gate for the per-pod estimate.)

### Context Isolation Rules

```
Each pod is sealed:
❌ No agent reads another project's history or memory
✅ The Lead reads this pod's workspace contract; the Implementer reads its own workspace

Per-pod session keys keep context from accumulating across projects.
```

### Why a status query stays cheap

```
Status / memory query:
The Lead reads this pod's MEMORY.md / HEARTBEAT.md
instead of a full cross-project history — no worker is spawned.
```

---

## Implementation Status

### Implemented Components ✅ *(automated-test-backed, not yet field-hardened)*

```
Lead:        ✓ Per-pod orchestrator (owns context/memory, never edits code)
Implementer: ✓ Runs in the project workspace (full read/write)
Reviewer:    ✓ Read-only veto (6-point checklist)
```

### Features Implemented ✅

- [x] Pod memory: governed, verified entries shared by the pod (`memory.json`)
- [x] Pod delegation + dispatch (`docket task add`, `docket task list`, `docket run`)
- [x] Workspace startup contract generation (`WORKFLOW_AUTO.md`/`MEMORY.md`/`HEARTBEAT.md`) +
  `docket setup` re-seeding of a missing or stale one
- [x] Per-pod context isolation (workspace + session key)
- [x] Security checklist (6 points)
- [x] HITL gate protocols
- [x] Cost tracking & optimization
- [x] Declarative role archetypes (`docket pod roles`) and pod blueprints (`docket init --blueprint <name>`)
- [x] Docket-native pipeline format + executor (`docket pod validate`, `docket pod plan`, `docket run`), generalized
  mechanical/verdict/approval gates and bounded rework
- [x] Typed handoff artifacts between hops + a per-role token-budgeted context compiler
- [x] Run registry and cancellation (`docket task list`)
- [x] Declarative policy engine on the live dispatch path (`docket pod policies`)
- [x] RuntimeDriver port — one typed protocol, one shipped driver (`agent/ports.py`,
  `hops/application/driver.py`'s `DocketDriver`)
- [x] docket as an MCP server (`docket start --mcp`, optional `[mcp]` extra)
- [x] Mechanically-maintained HEARTBEAT.md task ledger + conversation registry auto-population
- [x] Hash-chained, tamper-evident audit log (`docket log verify`)
- [x] The operator API: addressable tasks and pod routes over HTTP for an external plan of record
  (see [One door for a program](#one-door-for-a-program) above)
- [x] The configuration contract: `docket pod show` names each effective value and the
  scope it came from (built-in, global, pod), and `docket setup` names every entry a loader
  skipped; per-pod `roles/` and `policies/` resolve above the global layer (`--pod`)
- [x] Configuration format v1: every YAML document declares `kind:`, `docket pod validate` checks it,
  short forms normalize to the canonical one, pipelines route with `on:` and skip with `when`
- [x] The provider catalog: model endpoints are `kind: provider` documents, fourteen built in
  (`docket setup provider add|list|show|remove|export`)
- [x] The team in the repository: `.docket/` is the pod's configuration of record
  (`docket pod update|export`, `docket init` applies it), with drift reported by
  `docket pod show`
- [x] Recipes, project instructions and skills: seventeen shipped recipes (`docket pod recipes`), the
  codebase's `AGENTS.md` composed by default, `skills/<name>/SKILL.md` read on demand
- [x] Trace export: `kind: exporter` documents over a zero-dependency OTLP/HTTP projection
  (`docket setup export`), five destinations built in, all off
- [x] Export privacy levels (`minimal`/`actions`/`conversation`/`full`, or an exact `share:`
  list), shown before sharing (`docket setup export show|preview`) and widened only by a confirmed,
  audited command (`docket setup export privacy`)
- [x] The operator loop: an unattended `ask` parks (`waiting_approval`) instead of blocking a
  sweep, a typed Lead intake brief with a deterministic resource pre-check, an `input` pipeline
  step for a question rather than a permission (`waiting_input`), one derived inbox
  (`docket inbox`) every surface renders from, `kind: channel` notifications delivered as
  CloudEvents (`docket setup notify`, seven dialects, only `console` on by
  default, and it sends nothing, so `docket setup` warns until a delivering one is on), and answer surfaces (`docket task answer`, HTTP, MCP, Telegram) that all
  resolve through one `resolve` function

### Documentation ✅

- [x] Quick Start Guide
- [x] Agent Teams (Pods) guide
- [x] Configuration guide (every file, what reads it, and trace export)
- [x] Workflow Guide
- [x] Recipe library (generated from the shipped recipes)
- [x] Models, gateways and harnesses
- [x] Security Model (Simple)
- [x] docket architecture (this doc)
- [x] Commands Reference
- [x] Troubleshooting guide

---

## Dispatch Internals

`docket run` (and the opt-in `docket start --dispatch` loop) drives a pod's
queued tasks through its pipeline, one real, costed agent turn per hop. Earlier drafts of this
document sketched a memory-file signaling protocol (`TASK.md`/`DONE.md`/`APPROVED.md`/
`VALIDATED.md`) with Telegram polling and a fixed 3-retry escalation — that was never what
dispatch (`hops/application/executor.py`, `hops/`, `tasks/`) implements. This section replaces it with the mechanism as it actually ships,
resolved against a declarative pipeline by `pipeline/domain/plan.py`.

### Task state machine

A queued task moves through `pending` → `running` → `done` | `failed` | `blocked` |
`waiting_approval` | `waiting_input` (plus `cancelled` via the run registry, below).

- **Claiming is locked, not read-then-write.** `pending` → `running` is a single locked
  read-modify-write (`platform/store.py`) that also persists `startedAt`, `claimedAt`, and
  `claimPid` — this is what stops two concurrent `dispatch_pod` calls on the same pod from
  double-running the *same* task (they may each claim and run *different* tasks concurrently,
  which is fine).
- **Hops persist as they complete**, not only when the whole task finishes, so a crash mid-task
  loses at most the in-flight hop. A stale `running` claim (one whose `claimedAt` hasn't advanced
  recently) is swept to `failed` with `failureKind: "stale_claim"` and is resumable —
  `dispatch_pod(..., resume=True)` re-claims it and continues from the last persisted hop,
  replaying mid-rework position if needed, rather than restarting at hop 0.
- **`blocked` is never silently rewritten to `pending`.** A budget-blocked task only re-enters the
  queue via `unblock_pod` (a pod-wide budget change) or `retry_task` (one task, explicit); the
  same is true of a task `blocked` on `blockedReason: "input_expired"` (an unanswered question
  past its deadline) or `"resources"` (a Lead intake brief naming a resource its own
  deterministic pre-check couldn't find, before any hop ever ran).
- **`waiting_approval`** sits outside the normal forward flow, for either of two triggers: a
  pre-hop `approval` gate (unchanged), or — since Phase 34 (D-50, ADR 0016) — an in-turn tool-call
  `ask` that would otherwise block the running hop. Which posture an unattended pod gets is
  resolved, not fixed: `approvalMode: wait` blocks the call as before (the default for an
  interactive TTY dispatch); `park` — the resolved default for `docket start --dispatch`'s sweep and a
  non-interactive `docket run` — records the exact call and ends the turn instead of blocking it,
  so one stuck hop can no longer stall an entire sweep. `docket task answer <escalation-id> --option
  approve_once|approve_task|deny` (the id `docket inbox` prints) resolves either trigger; so do HTTP
  `POST /escalations/<id>`, the MCP `resolve` tool and Telegram `/answer <escalation-id> <option>`
  reach the same result. A grant on a
  pre-hop gate hands the position back to the *next* claim as a single-use gate override; a grant
  on a parked call instead re-runs that *same* hop, carrying a single-use pre-grant matched by a
  stable argument digest so the model's identical next call passes once without asking again. A
  deny fails the task immediately with `failureKind: "approval_denied"`, and a parked approval
  left untouched past the pod's `approvalExpiryHours` (24h by default) expires the same way, via
  the same fail-closed sweep a pre-hop gate's pending approval already used.
- **A2A.** A client that speaks A2A reaches the same records through `POST /a2a` (JSON-RPC:
  `message/send`, `tasks/get`, `tasks/cancel`, push-config set and get) and the agent card at
  `GET /.well-known/agent.json`, both behind the Bearer token. The facade keeps no state of its
  own: a task in `INPUT_REQUIRED` carries its pending escalation, and a `message/send` with
  `{action: accept|decline|cancel, content: {optionId}}` calls `resolve`
  (`specs/api/a2a-binding.spec.md`).
- **`waiting_input`** is for a question, not a permission: a pipeline `input` step
  (`- ask: {input: {from: <step>}}`, or the richer per-question schema a Lead's typed intake
  brief supplies) mints an MCP-elicitation-shaped question instead of running a hop. `docket task answer
  <escalation-id> --option <id>` (or `<task-id>`), `POST /escalations/<id>`, the MCP `resolve`
  tool and Telegram `/answer`
  all resolve it through one `resolve` function, which records the answer and reopens the task
  `pending`; the next claim routes the step's own `on:` outcome (`answered`/`declined`). An unanswered question
  past its own deadline moves the task to `blocked` (`blockedReason: "input_expired"`), never
  `failed`.

### Notifications: the derived inbox and channels

Nothing above pushes anything on its own. `docket inbox` (also `GET /inbox`, the MCP `inbox`
tool, and Telegram's `/status`, each scoped to the caller's own pod) is read-only, computed live
from the task list and the approval store rather than stored anywhere: every provisioned pod is
enumerated and each task sorted into `needsYou` (any `waiting_*` status, plus `blocked`),
`failed`, `doneSince` or `running`, with a pending escalation added to `needsYou` unless its task
already carries it. A separate `kind: channel` document (`docket setup notify`) is what turns a
transition in that inbox into an actual push: seven dialects ship (`console`, `desktop`,
`webhook`, `command`, `ntfy`, `email`, `telegram`), only `console` enabled by default (and it sends nothing: `docket setup` warns until a
delivering channel is on), each
declaring what it may do (`notify`/`converse`/`decide`, capped per dialect — only `console` and
`telegram` may ever `decide`) and how much of an event it carries (`minimal` by default, widened
the same confirmed, audited way `docket setup export privacy` widens a trace). `docket setup notify flush`
computes the diff against the last flush and delivers it — deduplicated, at-most-once, retried
twice per destination — and both the `docket start` sweep and a foreground `docket run` call it after their
own work. `interfaces/telegram/bot.py`'s inbound bot is unchanged by any of this: it still only ever
replies to a message it received; a bound chat's push notification, when the `telegram` channel
is enabled and that chat id is explicitly listed in its `actors`, is this separate, opt-in
mechanism, never the bot module sending on its own initiative (see SECURITY-SIMPLE.md and
telegram-integration.spec.md).

### Consultation, approval packs, evidence and escalation metrics

An agent that needs a human decision has two ways to ask. A gated tool call becomes an approval
whose pack carries the model's own preceding sentence as a `rationale` (screened, truncated to 500
characters, and a claim by the model rather than a fact) and three options: `approve_once`,
`approve_task` (the identical call for the rest of the task: within the turn, and in a pod for every
later hop of the role that asked, at most 20 per task) and `deny`. Choose it with `docket task answer
<escalation-id> --option approve_task`, Telegram `/answer <escalation-id> approve_task`, the HTTP
POST's `optionId` or the MCP `resolve` `option_id`. `docket task answer <task-id> --option deny --reason TEXT`, the HTTP POST's
`content.reason` record why, with an `actor`, in the audit entry.
The `consult` built-in (kind `read`) asks a typed question with options and an optional
recommendation. In a pod hop it parks the task `waiting_input` and, once answered, the next claim re-runs the same
role with the answer in its message, bounded per task by `maxConsultationsPerTask`. A pod set to
`consultMode decide` does not park: the call returns the model's own recommendation at once and
the audit log records `consult.decided`. The parked
question is persisted (0600, `consult-parked/`) until dispatch stores it on the task, so any process
can answer it. A channel at the `conversation` level lists the options and the recommended id, and
`docket task answer <escalation-id> --option <id>` or Telegram `/answer <escalation-id> <option id>` (the older `/answer <task> <option id>` works too) picks one.

`docket task show <task-id> [--json]` (also `GET /tasks/<p>/<id>/evidence`) includes the
evidence-v1 document: per-hop measured token usage (null when the endpoint reports zero)
and a trace link made of the session key and a one-second window. A corrections ledger at
`<DOCKET_HOME>/corrections/<project>.jsonl` collects deny reasons, Reviewer `REQUEST-CHANGES` texts
and declined answers.
Metrics expose `docket_tasks_started_total`, `docket_escalations_total{kind,outcome,by}` (settled
pauses, with a pod's own decision told apart from a person's) and
`docket_escalation_wait_seconds{kind}` on `/metrics`, folded from the `escalation_*` trace events.
Like the other counters they are lifetime-of-current-storage counts and must not be alerted on as
monotonic.

### Pipeline resolution and generalized gates

Before the platform work, dispatch hardcoded a three-role Lead → Implementer → Reviewer
order and its own Reviewer verdict parsing. Today `pipeline/domain/plan.py`'s `resolve_plan`
takes a `PipelineSpec` (the docket-native YAML format — `docket pod validate`/`pod plan`/`run`,
`pipeline/domain/spec.py`) plus a pod's live roster and the role-archetype registry (`teams/roles.py`
— see `docket pod roles`), and produces a deterministic `ExecutionPlan`: the same spec, roster, and
registry always yield the same step DAG, independent of wall-clock time or dict-iteration order.
A pod with no pipeline file resolves the built-in default pipeline — behaviorally identical to
the old hardcoded order, so a pod created before any of this shipped keeps working unchanged.

Each resolved step's gate is one of three kinds, read from the step's own declaration or — if the
step doesn't declare one — its role archetype's `gateContract`:

- **`mechanical`** — run a command; nonzero exit fails the step. This is the Implementer's
  `verifyCmd` today (`docket pod add implementer --verify "<cmd>"` / `docket pod set verify "<cmd>" --member <id>`), resolved
  against the member's real working tree (worktree → shared codebase → the member's own
  workspace dir).
- **`verdict`** — match the configured regex at the start of every non-blank line of a hop's
  output; exactly one distinct marker value is the verdict (zero or conflicting markers are
  unparseable); a match in the gate's `passValues` advances the pipeline. This generalizes the Reviewer's
  APPROVE/REQUEST-CHANGES to an arbitrary marker vocabulary for any
  archetype (a custom vetter's SHIP/HOLD, for instance). A verdict gate can carry a
  bounded `rework` edge — a REQUEST-CHANGES re-runs a target step (by default, back to the
  Implementer) up to a configured cycle budget (`maxReworkCycles`, default `1`) before a second
  rejection fails the task terminally. There is no fixed "3 retries then escalate to a human
  Engineer" — the bound is one small integer, and the terminal state is simply `failed`, visible
  via `docket task list`.
- **`approval`** — the step must not proceed until an operator grants it through docket's
  headless approval channels; this is what produces a `waiting_approval` task.

A `parallel` group lets a step fan out into concurrently-run child steps (for example, one per
`--count N` duplicate role member); `pipeline/domain/plan.py`'s `run_group` runs them on a bounded
thread pool and joins before the pipeline advances past that position.

A `wait` step parks a task on a time or on a probe command instead of on a person. Dispatch runs no
agent turn for it; it opens a `wait` escalation that asks nobody, and the periodic sweep of
`docket start --dispatch` wakes the task when its due time passes or its probe exits 0. A task
waiting that way is not listed under what needs you. A `kind: routine` document is the other
time-based path: the sweep enqueues one task per due slot, under an idempotency key naming the
routine and the slot. Routines fire only under `docket start --dispatch`, and `docket pod routine
list` shows each one's next and last slot. There is still no external daemon: both paths run in the
process you start.

A pod whose workspace kind is `workdir` has no repository. Its members share one working directory,
its hop prompts speak of that directory rather than of code or git, and a task that names a
`baseRef` fails before any hop, because there is no repository to branch from.

### Retries and timeouts

A hop whose agent turn fails with a *retryable* failure kind (`timeout` or `daemon_error` — the
model endpoint erroring transiently, a legacy name since there is no daemon; `nonzero_exit`/`invalid_output` are not retried) is retried in
place, up to a per-role retry budget, with linear backoff; the attempt count is persisted per
hop. Every retry refreshes the task's claim timestamp, so a legitimately long retry loop can't be
mistaken for a stale claim by a different concurrent dispatcher. The agent-turn timeout and the
`verifyCmd` timeout are independent, each resolved as: an explicit CLI override
(`docket run --timeout`), then the pod Lead's own meta fields, then a built-in
default.

### Structured handoff artifacts and the context compiler

Before the platform work, a hop's prompt was built by concatenating every prior hop's raw text
output, capped only by a process-wide byte budget. Today every hop produces a typed
`HandoffArtifact` (`kernel/handoff.py`: `summary`, `files_changed`, `diff_ref`, `diff`, `verdict`,
`notes`) instead of a raw string, persisted alongside its hop record so `--resume` recovers it
exactly. Every hop that changed the tree fills `files_changed` and `diff` (tracked changes plus
the content of new files, capped at `HANDOFF_DIFF_MAX_CHARS` with a marker), so the next hop reads
what was written instead of re-reading it with tools; `diff_ref` (the branch name) stays
Implementer-only; `notes` is reserved in the schema but has no producer yet, honestly documented as such
rather than implied to be populated.

`agent/context.py`'s `compile_artifact` fits each prior hop's artifact into the *next* hop's
per-role token budget (`RoleArchetype.token_budget`, declared per archetype rather than one
global constant — 6000 by default). A hop further into the past gets a smaller share of that
budget, the same halving series a byte-budget stopgap originally used, now denominated in tokens.
If an artifact doesn't fit, fields are shed one at a time in a declared order — `diff`, then `notes`, then
`diff_ref`, then `files_changed`, then `verdict` — before `summary` itself is ever touched; only
once every droppable field is gone and it still doesn't fit is `summary` truncated, always with a
visible `[... summary truncated: N bytes omitted ...]` marker, never silently. Token counts are an
honest UTF-8-bytes ÷ `CONTEXT_BYTES_PER_TOKEN` (default 4) approximation — there is no tokenizer dependency, and this number is never used
to bill against, only to bound a prompt deterministically.

### The run registry and cancellation

Every dispatch invocation — from the CLI, the `POST /dispatch/<project>` route, a due schedule, the periodic sweep
loop, or an MCP `dispatch` tool call — creates a record in the run registry (`tasks/application/runs.py`)
*before* the work starts, and folds it to a terminal state (`succeeded`, `failed`, or `cancelled`)
when it finishes. `docket task list` queries it; this closed a real gap where background dispatch paths
used to swallow every exception and return before anything ran, leaving no run id and no way to
tell "done" from "failed" from "never ran."

`docket task cancel <id>` persists one cancellation request and kills every pid recorded against
that run's process *group* (each hop subprocess starts its own session, so its pid doubles as its
group id). Queued work becomes `cancelled` atomically. Running work remains nonterminal and visibly
requested until the executor observes the signal and fully stops; then both the task and run become
`cancelled`, distinct from ordinary failure. An already-running in-process backend call returns to
the next safe checkpoint, where its response is discarded before any later tool or hop can start.
A run can have more than one pid recorded at once when a `parallel` step has multiple hops in flight.

### The policy engine on the dispatch path

Declarative policies (`docket pod policies`, `governance/policy.py`) are evaluated at two points on the live
dispatch path, not just in the CLI's own dry-run check: `pre_input` once, at task enqueue (so the
same task text doesn't re-trip a wildcard-scoped policy at every hop), and `pre_output` on every
hop's real output, before it is embedded in the carried-forward artifact. A `block` verdict on
`pre_input` rejects the task before it is ever queued; a `require_approval` verdict enqueues it
straight into `waiting_approval`. A `block` on `pre_output` fails the hop the same way a failed
agent turn does; `redact` scrubs the text in place; `warn` only logs and feeds `docket status`.
In-turn tool calls have their own separate hook — `pre_tool_call`, evaluated by `agent/tools/registry.py`'s
`dispatch_tool` on every call docket's own turn loop makes (Phase 19 P19-3) — which this
dispatch-level engine does not duplicate; `docket pod check "<text>" --role <role>`
dry-runs that hook specifically, against `bash` by default. Pass `--tool <name>` to test a
non-`bash` tool instead, so it is evaluated on its own terms rather than misclassified against the
shell command allowlist.

---

## FAQ

### Q: Is docket an acronym?

**A:** No, it is a name. The design rests on four ideas: **roles** (the Lead orchestrates, the
Implementer codes, a Reviewer gates), **autonomy** within clear responsibilities,
**context isolation** per pod, and durable **knowledge** in each workspace's memory files.

### Q: Is this the same as the original DOCKET.md proposal?

**A:** Similar spirit, adapted for what docket's own agent runtime can do:
- ✅ Kept: Distinct agent roles, context discipline, security focus
- ✅ Changed: Coordination is a real dispatch state machine driving costed agent turns
  ([Dispatch Internals](#dispatch-internals)), not RPC and not memory-file signaling
- ✅ Changed: Orchestration is a per-pod Lead, not a global router with a classifier

See [Agent Teams (Pods)](AGENT-TEAMS.md) for the full role model details.

### Q: Do I need to change how I use docket?

**A:** No. Every `docket init` (run in the project directory) provisions
that project's pod with the right templates. Everything else works the same.

### Q: Will this break my existing agents?

**A:** No. Templates are generated per-pod by `docket init` (and per member by `docket pod add`) and
refreshed by `docket setup --fix`. A member's isolation:
- Each project pod (lead + implementer, optionally a reviewer) is isolated
- Project agents are never touched by another project's setup (use `docket pod reset <member-id>` to rebuild a workspace)

### Q: How much will I save?

**A:** See [Cost Optimization](#cost-optimization) above and
[Cost reporting and its limits](README.md#known-limits) — the short version
is: token reduction from isolation is real and measured, but docket reports **measured tokens;
dollar figures are labelled estimates, never recorded spend**, and never a savings promise.

---

## Embedding docket-runtime

The standalone **`docket-runtime`** package (`packages/docket-runtime/`) builds from the same
source as the CLI and ships a narrow, versioned `docket_runtime` facade. An embedding application
registers and dispatches tools through docket's policy, approval, trace, and audit chokepoint
without adopting the CLI or the full agent loop. It is **not published to any index** — build it
from a checkout of this repository and start from
[examples/runtime_embed.py](../examples/runtime_embed.py).

Two optional adapter configurations have installed-artifact coverage:

| Adapter | Tested configuration | Boundary |
| --- | --- | --- |
| OpenHands SDK | `openhands-sdk==1.44.1`, Python 3.12 | Standard agent with defaults, native tools, plugins, skills, and MCP disabled |
| PydanticAI | `pydantic-ai==2.37.0`, Python 3.11 | One sequential Docket toolset with no native or additional toolsets |

These claims apply when relevant tools are exclusively Docket-backed. ACP, native/provider tools,
plugins/MCP added beside an adapter, and arbitrary framework configurations are outside the proof;
this is not framework-neutral compatibility. The adapters use neither A2A nor OTLP: both run in
process, and Docket's JSONL trace already preserves the identity fields the matrix tests. Trace
export (Configuration §3.14) is a separate, operator-enabled projection of that trace from
docket's own driver, and is not part of the adapter proof.
Inspect the boundary or copy the lazy constructors from
[examples/runtime_adapters.py](../examples/runtime_adapters.py).

---

## Next Steps

1. **First project:** `docket init` in the project directory (the pod is a lead + implementer)
2. **Add another project pod:** `docket init` in that project's directory
3. **Inspect an agent:** `docket pod show` (view members and roles)
4. **Test workflow:** Assign bug fix, observe token usage
5. **Monitor spend:** `docket status` (measured tokens; no recorded dollar spend)

---

## References

- [Quick Start Guide](QUICK-START-DOCKET.md) - Get started in 5 minutes
- [Workflow Guide](WORKFLOW-GUIDE.md) - Complete examples
- [Security Model](SECURITY-SIMPLE.md) - Layered, convention-based security
- [Commands Reference](commands.md) - All commands
- [Agent Teams (Pods)](AGENT-TEAMS.md) - The canonical team model reference
- [Decision records](adr/) - One reasoned architectural decision per file
- [specs/](../specs/) - RFC 2119 functional/API/data specifications; the exact, CI-validated
  behavioral contract for anything summarized in this document

---

**Last Updated:** 2026-09-18
**Status:** Implemented, automated-test-backed — not yet field-hardened (see the beta warning at
the top of this document)
