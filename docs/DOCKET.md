# DOCKET Architecture

**DOCKET = Roles, Autonomy, Context isolation, Knowledge**

Complete technical guide to docket's DOCKET architecture implementation.

> [!WARNING]
> **Beta / early-stage software.** The architecture below is implemented and automated-test-backed,
> but has not been QA-hardened in production. "Validated" in the Implementation Status section
> means *covered by the automated suite*, not field-proven — verify behavior against your own
> OpenClaw install. All cost figures are accounting estimates, not provider bills (see the
> [README's cost limits](../README.md#cost-reporting-and-its-limits)).

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

---

## Overview

DOCKET is an architectural pattern for autonomous agent teams that achieves:
- **Lower token usage** through per-pod context isolation
- **Clean role separation** — Lead orchestrates, Implementer codes, Reviewer/Tester gate
- **Layered, convention-based security** through a read-only reviewer veto + checklist
- **Objective validation** through behavior-only testing

### The Problem (Before DOCKET)

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

### The Solution (After DOCKET)

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
Tester (optional): Runs reproduction steps (behaviour only)
       → PASS
       ↓
Each project's work stays inside its own pod + workspace, so
one project's context never bleeds into another's.
```

---

## System Architecture

> This section is the code-level companion to [Core Principles](#core-principles) below: those
> describe *what* a pod does; this describes how docket's own codebase is put together to make
> that real, safe to extend, and reversible if the underlying runtime ever needed to change.

### Three layers, one direction of dependency

`src/docket/` is organized into three layers, and imports only ever point inward:

```
cli/  ->  core/  ->  edges/
```

- **`cli/`** (Typer + Rich) — argument parsing, the interactive picker, and every line of
  Rich-rendered output. This is the only layer allowed to talk to the user; a command aborts by
  raising `typer.Exit` and renders whatever typed result `core/`/`edges/` handed back (a
  `RestartResult`, a `Drift` list, a `TaskResult`) through `ui.py`'s `info`/`success`/`warn`/
  `error` helpers.
- **`core/`** (Pydantic models + pure services) — the domain: agent/OpenClaw data models,
  role→model policy, dispatch's state machine, sync/security/approval/audit/trace/policy logic.
  `core/` never imports `cli/`, never imports `ui.py`, and never prints — every function returns a
  typed result for `cli/` to render.
- **`edges/`** (the only side-effecting layer) — `edges/store.py` is the single chokepoint for
  every docket-owned JSON read/write (atomic, filelocked, 0600 permissions, `.bak` rotation);
  `edges/adapters/system.py` wraps every shell-out to `systemctl`/`docker`/`git`, degrading
  gracefully when a binary is missing so docket still runs on a systemd-less host.

This is not a style preference — it is enforced by what each layer is allowed to import, and a
couple of the newest modules in the tree exist specifically to keep the boundary from eroding (see
the RuntimeDriver port, below).

### The Anti-Corruption Layer

`edges/adapters/openclaw.py` is the **only** module in the codebase allowed to know what
`openclaw.json`, an auth profile, or a provider config file actually look like on disk. Every
other module — including `core/dispatch.py`'s hop loop and every `cli/` command — reaches
OpenClaw state only through this ACL's typed functions (`get_agent`, `list_agents`, `meta_get`,
`agent_run`, and so on). Shelling out to the `openclaw` binary itself is included in that rule:
`agents add`, `models auth`, `--version`, and `onboard` all go through the ACL, never a direct
`subprocess` call from `core/` or `cli/`.

The payoff: OpenClaw's file formats can change — or OpenClaw itself could in principle be replaced
— by rewriting one module, not by auditing every call site in the tree. This is a *reversibility*
property, not a migration plan: docket wraps OpenClaw decisively (the moat is the control plane,
not the agent loop), and the ACL is what keeps that decision from calcifying into an assumption
smeared across the codebase.

### The RuntimeDriver port (decision D-14)

A mid-2026 audit found that the *execution* slice of that same coupling — parsing an agent turn's
result, reading a session's on-disk JSONL, aggregating token/cost usage — had started leaking
around the ACL rather than being contained by it: session-JSONL parsing had drifted into
`core/utils.py`, and `core/trace.py`'s ingestion bridge decoded the daemon's raw session-record
types itself. `core/runtime_driver.py` is the fix: a single typed `Protocol` — `RuntimeDriver` —
that `core/` and `cli/` program against instead of a concrete driver's on-disk knowledge. It has
six members plus one ingestion helper:

- `run_turn` — one costed agent turn: the hot path `core/dispatch.py`'s pipeline calls for every
  hop, and, per decision D-18, docket's own self-originated LLM calls (memory distillation, see
  [Memory Management](#memory-management))
- `provision` / `teardown` — register/unregister an agent with the backing runtime
- `list_sessions` / `usage` — durable-session enumeration and token/cost aggregation
- `capabilities` — what this driver instance can actually promise (for example, whether the
  daemon reports a real USD cost at all), so a caller never hardcodes an assumption about the one
  shipped driver's quirks
- `read_new_turns` — decodes session records past a caller-held offset into docket's own neutral
  `SessionTurn`/`SessionSlice` vocabulary, feeding `core/trace.py`'s ingestion sweep

`edges/adapters/openclaw.py`'s `OpenClawDriver` is the **one shipped implementation**; a
`FakeDriver` test double (`tests/python/fakes.py`) is the one test double. This is a deliberately
narrow move. docket's architectural principles carry a standing ban on an `AbstractBackend`/plugin
framework, and decision D-14 *revises* that ban rather than repealing it: the port is containment
of coupling that already existed, not speculative generality. **There is one shipped driver.** A
second real driver still needs a real trigger — OpenClaw stalling, repeatedly breaking
compatibility, or a paying user who needs a different runtime — not the existence of the port
itself; adding driver discovery, entry points, or a config-selectable backend ahead of that would
be scope creep, not follow-through.

### Dual-source configuration and drift detection

Every agent's state lives in two places that docket keeps aligned by convention, not by one being
derived from the other:

- **`.docket-meta.json`**, in each workspace — the source of truth for the docket CLI itself
  (kind, role, name, codebase, stack, model, `modelSource`, description, `sessionKey`,
  `projectKey`, and platform-era additions like `blueprint`/`workspaceKind`/`workDir` and a pod's
  allocated `portRangeStart`/`portRangeCount`/`scratchDir`)
- **`~/.openclaw/openclaw.json`** — the source of truth for the OpenClaw daemon (agent
  registration, Telegram bindings, channels, per-agent metadata including the session key, tool
  approval gates, security config)

Every write path that changes agent config goes through the ACL and updates both stores, then
restarts the gateway (`edges/adapters/system.py`'s `restart_gateway()`). Because the two writes
are separate calls rather than one atomic transaction, they can still drift apart — a crash
mid-command, a manual edit, an older docket version. `core/sync.py`'s `check_agent`/`check_all`
are the single implementation that detects that drift, comparing the two stores' `model` and
`sessionKey` fields for every registered agent that has a `.docket-meta.json`. `docket doctor`'s
config-drift check renders `sync.py`'s `Drift` records and drives the interactive `--fix` re-sync
— it does not reimplement the comparison itself.

### Durable state docket owns

OpenClaw's own daemon keeps very little that survives a context reset: its per-agent sqlite file
is a rebuildable RAG index over workspace files, not a transcript, and live conversation context
is lost on reset or compaction. docket fills that gap with a handful of small, docket-owned
stores:

- **`HEARTBEAT.md`'s dispatch ledger** — every pod Lead's `HEARTBEAT.md` carries a delimited,
  docket-owned region inside its `## Active Tasks` list that `core/dispatch.py` upserts
  mechanically at claim, at every persisted hop, and at finalize — not prose an agent is trusted
  to keep current by convention. `docket doctor` flags a task the queue marks `running` with no
  matching ledger entry, or a ledger entry for a task that no longer is, and `--fix` re-syncs the
  ledger to exactly what the queue says. See [Dispatch Internals](#dispatch-internals).
- **The conversation registry** (`core/conversations.py`, `docket-conversations.json`) — one
  record per channel thread docket is tracking (agent, peer, topic, status, a resume pointer),
  seeded on `docket wire` and cleaned up on delete. Dispatch and `serve` keep `last_message`/
  `task_ref` current automatically as a task moves, rather than that being a manual
  `docket conversations set` chore.
- **The audit log** (`core/audit.py`, `$OPENCLAW_DIR/audit.log`, 0600) — one JSON line per
  mutating operation; secret values are never logged. Every line carries a monotonic `seq` and a
  `prev_hash` (the SHA-256 of the previous line's canonical JSON), so `docket audit verify` can
  walk the chain and report the first broken link; a missing file, a pre-chain legacy line, or the
  first entry after a size-triggered rotation are honest chain restarts, not tampering. There is
  no environment kill switch — recording is best-effort (a write failure never raises) but cannot
  be silently disabled.
- **Traces** (`core/trace.py`, `$TRACES_DIR/<project>/<session_id>.jsonl`) — one append-only file
  per session, one line per observable event (hop starts, tool calls, gate outcomes, retries,
  guardrail trips, budget warnings). `docket trace`/`docket metrics` read this store;
  `DOCKET_NO_TRACE=1` disables writes.

None of these four stores goes through `edges/store.py`'s locked read-modify-write path the same
way — audit and trace are exempt by design (line-independent JSONL appends, not a whole-document
read-modify-write), while the conversation registry and the dispatch queue backing the ledger do
use `store.py`.

---

## Core Principles

### 1. Per-Pod Context Isolation

**Each project's context stays inside its own pod.**

- Every pod has its own workspace and per-pod session key
- The Lead reads this pod's workspace contract (`WORKFLOW_AUTO.md`, `MEMORY.md`,
  `HEARTBEAT.md`), not a shared cross-project history
- The Implementer runs inside the project workspace, reading only the files it touches
- The Reviewer reads the diff only, not the entire file
- The Tester reads reproduction steps only, not code

**Result:** no project's context bleeds into another's, so per-agent token counts stay scoped to one project

### 2. Lean Pods by Default

**Don't add workers you don't need.**

`docket add <project>` provisions a lean **Lead + Implementer** pod:
```
Pod size            Members                    When
─────────────────────────────────────────────────────
Lean (default)      Lead + Implementer         most projects
Full (--pod full)   + Reviewer + Tester        higher-stakes code
Custom (--with ...) Lead + Implementer + any   pick the gates you want
```

**Result:** each project runs the smallest pod that does the job

### 3. Linear Pipeline (and it really runs)

**Each role has ONE job. No overlapping work.**

```
Lead → Implementer → Reviewer → Tester
       (implement)   (veto)     (validate)
```

NOT:
```
Implementer ──┐
Reviewer   ───┼→ All work in parallel
Tester     ───┘   (wasteful, redundant)
```

This pipeline is no longer just a convention in the templates — docket **actually executes it**,
one real agent turn per hop. Only the roles a pod has take part (a lean pod runs two hops:
Lead → Implementer):

```bash
docket pod <project> delegate "Fix the null-token login crash"  # queue a task
docket pod <project> queue                                      # see the queue + per-task status/cost
docket pod <project> dispatch                                   # run the pipeline once, now
docket serve --dispatch                                         # background: drive every pod's queue
```

Three guarantees hold on every hop:

- **Budget-gated.** Before each hop docket checks the pod's recorded spend against the Lead's
  budget cap (`docket profile <project>-lead --budget N`). The first hop that would exceed it
  pauses the pod's Lead (`docket profile <id> --resume` clears it) and leaves the task
  **blocked**, not run — every further claim against that pod is refused outright until it's
  resumed.
- **Traced.** Each hop emits a trace event (`docket trace`) on a per-task session
  `agent:<project>:<task_id>` — every run is auditable, no manual Telegram relay.
- **Pod-local.** Dispatch only ever targets the project's own pod members. **There is no
  cross-pod dispatch path** — one pod can never run another pod's agents.

Each hop is a real, costed LLM turn, which is why dispatch is **explicit** (`docket pod …
dispatch`) or **opt-in** (`docket serve --dispatch`) — never silent. Plain `docket serve` is a
read-only monitor and does not dispatch.

This is the outline; the actual state machine also retries a hop that fails on a transient daemon
hiccup, can stop a task at a human approval gate, and generalizes what "Reviewer" and "Tester"
mean past those two hardcoded roles. See [Dispatch Internals](#dispatch-internals) for the full
mechanics.

**Result:** No wasted parallel work — and the hand-off between roles actually executes.

### 4. Behavior-Only Validation

**Tester validates behavior, not code.**

Tester does NOT read:
- The Implementer's implementation
- The Reviewer's analysis
- How the fix was done

Tester ONLY reads:
- Reproduction steps
- Expected behavior
- Acceptance criteria

**Why:** Prevents bias. Tester can't give false positive just because "code looks good."

---

## Performance Results

### Token Usage

The lever DOCKET actually controls is **per-pod context isolation** (see the
[Before/After](#the-problem-before-docket) diagram above) — token reduction is what isolation
controls and what you can measure, not a fixed percentage. Read your **recorded** spend with
`docket cost`; see [Cost Optimization](#cost-optimization) below for the model-selection half of
the story.

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

There are two kinds of agent. **Pod roles** are project-scoped and created per project by
`docket add <project>` (managed with `docket pod <project>`). **Org specialists** are shared
across the whole fleet and created once by `docket install`.

## Pod Roles

Each project is an **isolated pod** with its own workspace and per-pod session key. A pod is a
lean **Lead + Implementer** by default; add a Reviewer and Tester with `--pod full` or
`--with reviewer,tester`.

### Lead

**Role:** Per-pod orchestrator and human interface

**Capabilities:**
- Owns this pod's context, memory, and human (Telegram) comms
- Reads this pod's workspace contract — `WORKFLOW_AUTO.md`, `MEMORY.md`, `HEARTBEAT.md` — not
  a full cross-project history
- Decomposes work and dispatches to the pod's workers — `docket pod <project> dispatch`
  (or `docket serve --dispatch`) really runs the next hop, one costed agent turn at a time
- Holds the per-pod budget cap that gates every dispatch hop
  (`docket profile <project>-lead --budget N`)

**Tools:**
- `read` (memory files only)
- `openclaw message send` (dispatch to pod workers)

**Cannot:**
- **Edit code** (ever)
- Run commands
- Commit
- Make architecture decisions alone

**Model:** cheap class (role policy) (coordination and dispatch, not reasoning-dense code work)

### Implementer

**Role:** Code implementation specialist (replaces the old global "programmer")

**Capabilities:**
- Runs **inside the project workspace**, with full read/write on the project
- Reads the project files it needs directly (it is in the workspace, not handed a tiny brief)
- Implements the requested change
- Its hop's reply is captured directly by dispatch as a typed `HandoffArtifact` — no completion
  file to write or poll for (see [Dispatch Internals](#dispatch-internals))

**Tools:**
- `read`, `write`, `edit`
- `exec` (sandbox only)

**Cannot:**
- Review security (reviewer's job)
- Run validation tests (tester's job)
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

**Tools:**
- `read` (the diff)

**Cannot:**
- Fix code (only reviews)
- Execute tests
- Commit

**Model:** cheap class (role policy) (structural review, not reasoning-dense)

### Tester (optional)

**Role:** Behavior-only validation specialist

**Capabilities:**
- Executes reproduction steps
- Runs test suites
- Binary verdict: PASS or FAIL
- Does NOT read code (stays objective)

**Tools:**
- `exec` (test runners)
- `browser` (UI testing, read-only)

**Cannot:**
- Read implementation code
- Review security
- Fix failing tests
- Commit

**Model:** cheap class (role policy) (validation is mechanical)

## Org Specialists

Shared across all projects, created once by `docket install`. The `manager` is a cross-cutting
coordinator — **not** a router with a classifier, and it does not compress prompts into briefs.
Its own task queue (`docket team`) was retired in Phase 12: per-pod dispatch
(`docket pod <project> delegate/queue/dispatch`) is the only queue now, and the manager role is
transitional, being superseded by per-pod Leads.

### Manager

**Role:** Cross-cutting coordination (transitional)

**Capabilities:**
- Coordinates work that spans more than one pod (advisory/instruction-level; no task-queue
  tooling of its own — see [Portfolio Manager](#portfolio-manager-optional) below for the
  fleet-visibility surface that replaced it)
- Reads memory/snapshots, not full history

**Tools:**
- `read` (memory files only)
- `openclaw message send`

**Cannot:**
- Edit code
- Run commands
- Commit

**Model:** cheap class (role policy) (cross-cutting coordination, not code reasoning)

### Knowledge

**Role:** Pattern extraction and memory distillation

**Capabilities:**
- Extracts reusable patterns from completed tasks
- Updates MEMORY.md with decisions
- Maintains patterns/ library
- Cross-project memory search

**Tools:**
- `read` (all project memory)
- `write` (memory files only)
- `openclaw memory search`

**Cannot:**
- Modify source code
- Run tests
- Commit

**Model:** cheap class (role policy) (distillation is mechanical)

**Cost Target:** <5K tokens/extraction

### Security

**Role:** Deep security audits and HITL gatekeeper

**Capabilities:**
- Deep threat modeling
- HITL gate enforcement
- Compliance audits (GDPR, HIPAA)
- Proactive monitoring

**Tools:**
- `read` (all code)
- `browser` (security testing)
- `openclaw message send` (HITL requests)

**Cannot:**
- Modify code
- Execute suspicious code
- Approve own escalations
- Commit

**Model:** strong class (role policy) (security reasoning required)

**Cost Target:** <10K tokens/audit

### Portfolio Manager (optional)

**Role:** Cross-pod planning and visibility surface (opt-in)

Provisioned only by `docket install --portfolio`, which adds **one** `portfolio-manager`
(`scope: org`). It is a fleet-wide advisory layer, never a pod member.

**Capabilities:**
- Sees fleet **metadata** — which pods exist, their queues, budgets, and health
- Recommends where to focus, rebalance, or pause, in words for a human

**Tools:**
- `read` (fleet metadata — `docket list`/`pod`/`cost`/`doctor` surface)
- `openclaw message send` (advisory reports to the human)

**Cannot:**
- Read or edit **project code** (it sees metadata, not source)
- **Dispatch into pods** (each pod's own Lead owns execution)
- Be a pod member, or run another pod's agents
- Commit

**Model:** cheap class (role policy) (planning/visibility, not reasoning-dense)

---

## Memory Management

### Problem: Large Shared Context

**Before DOCKET:**
```
A shared agent reads:
- Full cross-project conversation history: 100K tokens
- All memory logs: 50K tokens
────────────────────────────────────
Total: 150K+ tokens per turn, growing across projects
```

### Solution: Isolated pods + the workspace contract

**After DOCKET:**
```
The pod's Lead reads:
- this workspace's WORKFLOW_AUTO.md, MEMORY.md, and HEARTBEAT.md
The Implementer reads:
- only the workspace files it touches
────────────────────────────────────
Context stays scoped to one project's pod
```

There is no generated `SNAPSHOT.md`, and `docket context` no longer has `snapshot`/`index`/
`search`/`compress` subcommands — they, and the per-agent index/snapshot artifacts they wrote,
were removed (the openclaw runtime's own memory backend handles semantic search; docket does not
keep a rival index). What actually scopes a pod's context is the **workspace startup contract**
docket provisions on `docket add`/`docket install` and `docket doctor` re-seeds if a workspace is
missing one or has a stale version:

- **`WORKFLOW_AUTO.md`** — the startup protocol. The openclaw runtime forces every agent to
  re-read this file after each context reset, so docket anchors the codebase path and the
  resume/durability rules here — the one place guaranteed to survive compaction even when
  `SOUL.md`/`MEMORY.md` fall out of context.
- **`MEMORY.md`** — long-term curated project facts (what the project is, architecture, current
  state) — written by the agent, seeded with a stub on first run.
- **`HEARTBEAT.md`** — the durable in-flight task ledger. An agent is instructed to write
  multi-step work here *before* starting it; a pod dispatch hop additionally keeps its own
  delimited region in sync mechanically (see [Dispatch Internals](#dispatch-internals)), so the
  ledger reflects real queue state, not only an agent's compliance.

Plus the dated `memory/YYYY-MM-DD.md` logs, read on demand rather than all at once. A fresh
`HEARTBEAT.md` seeds like this:

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

`docket context <id> show` and `docket context <id> project` are read-only renderers over
exactly these files — recent memory-log lines, active tasks parsed from `HEARTBEAT.md`,
`MEMORY.md`'s section headers, and last-activity/log-count stats. They display the contract; they
don't generate a separate summary artifact.

### Memory Commands

```bash
# Read-only dashboard: recent memory logs, active tasks, today's gateway activity
docket context <id> show

# Project quick reference: codebase/stack/model, active tasks, MEMORY.md sections
docket context <id> project

# Summarize pending daily logs into MEMORY.md (see Memory Distillation below)
docket maintain <id> distill

# Re-seed a missing or stale WORKFLOW_AUTO.md / MEMORY.md / HEARTBEAT.md
docket doctor --fix
```

### Memory Distillation

`docket maintain <id> distill` summarizes an agent's pending daily logs into `MEMORY.md` and
archives the originals into `memory/.distilled/<day>/` rather than deleting anything outright.
This is docket's first *self-originated* LLM call (decision D-18): docket asks a pod's own Lead
(or a utility agent) to write the summary, through the same `RuntimeDriver.run_turn` every
dispatch hop uses — no new SDK dependency, no direct provider call.

`docket maintain <id> clean` and `reset` run distillation **first by default** before their own
memory-clearing step (`--no-distill-first` opts back out to the old bare-delete behavior) — so
routine maintenance never quietly throws away undistilled history. The contract fails **closed**:
a driver failure or an empty reply leaves the daily logs exactly where they were, and the
subsequent delete is aborted rather than proceeding over lost content. "Nothing to distill" (no
pending daily logs) is a different, harmless case — there's nothing undistilled to lose, so the
delete proceeds normally.

---

## Security Model

Three automatic layers — instruction-level SOUL.md constraints (never commit/push/delete without
instruction), the Reviewer's 6-point checklist (prompt-injection patterns, hardcoded secrets,
SQL injection/XSS, auth checks, dangerous operations, test coverage) as a read-only veto, and a
final human `git diff` review. Enforced tool-approval gates, a headless approval channel, and
Docker workspace isolation layer on top and are **on by default** for new installs. Full detail,
including the exact reviewer checklist and gate/approval-channel mechanics, lives in
**[SECURITY-SIMPLE.md](SECURITY-SIMPLE.md)** — this section intentionally isn't a second copy.

A declarative policy engine (`docket policies`) adds a fourth layer on the dispatch path itself —
`pre_input`/`pre_output` hooks that can redact, warn, block, or route a task to human approval.
See [The policy engine on the dispatch path](#the-policy-engine-on-the-dispatch-path) for the
mechanics; it does not reach inside a running turn (`pre_tool_call` stays daemon-gated), so it is
a complement to the layers above, not a replacement for daemon-side tool approval.

---

## Cost Optimization

### Model Selection

The role→model policy assigns each role to either the **cheap class** (high-volume / low
reasoning-density) or the **strong class** (reasoning-dense):

| Class  | Roles                                                    | Why                              |
|--------|----------------------------------------------------------|----------------------------------|
| Cheap  | Lead, Manager, Reviewer, Tester, Knowledge, task agents  | High-volume or mechanical work   |
| Strong | Implementer, Security, repo agents                       | Code writing / security reasoning|

Change the policy for a role with `docket models set <role> <provider/model>`, or switch all
roles at once with a provider preset (`docket models preset openai`). Pins set via
`docket profile <id> <model>` are never touched by policy changes.

**Result:** routine orchestration and review runs on the cheap model class with
project-scoped context — fewer tokens at a lower per-token price. (Exact dollar spend depends
on your models and current pricing — read it with `docket cost`.)

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
Tester:      ✓ Behavior-only validation
Knowledge:   ✓ Org specialist (tools + memory management)
Security:    ✓ Org specialist (HITL gates + threat modeling)
Manager:     ✓ Org specialist (cross-cutting coordination, transitional)
```

### Features Implemented ✅

- [x] Memory management system (`docket context show/project`)
- [x] Pod delegation + dispatch (`docket pod <project> delegate/queue/dispatch`) — replaces the
  retired `docket team` queue
- [x] Workspace startup contract generation (`WORKFLOW_AUTO.md`/`MEMORY.md`/`HEARTBEAT.md`) +
  `docket doctor` re-seeding of a missing or stale one
- [x] Per-pod context isolation (workspace + session key)
- [x] Security checklist (6 points)
- [x] Behavior-only validation
- [x] HITL gate protocols
- [x] Cost tracking & optimization
- [x] Declarative role archetypes (`docket roles`) and pod blueprints (`docket add --blueprint`)
- [x] Docket-native pipeline format + executor (`docket pipeline validate/plan/run`), generalized
  mechanical/verdict/approval gates and bounded rework, replacing the retired `docket workflow`
  ("Lobster") dialect
- [x] Typed handoff artifacts between hops + a per-role token-budgeted context compiler
- [x] Run registry and cancellation (`docket runs`)
- [x] Declarative policy engine on the live dispatch path (`docket policies`)
- [x] RuntimeDriver port — one typed protocol, one shipped OpenClaw driver (`core/runtime_driver.py`)
- [x] docket as an MCP server (`docket mcp serve`, optional `[mcp]` extra)
- [x] Memory distillation (`docket maintain distill`, and `clean`/`reset --distill-first`)
- [x] Mechanically-maintained HEARTBEAT.md task ledger + conversation registry auto-population
- [x] Hash-chained, tamper-evident audit log (`docket audit verify`)

### Documentation ✅

- [x] Quick Start Guide
- [x] Agent Teams (Pods) guide
- [x] Workflow Guide
- [x] Security Model (Simple)
- [x] DOCKET Architecture (this doc)
- [x] Commands Reference
- [x] Troubleshooting guide

---

## Dispatch Internals

`docket pod <project> dispatch` (and the opt-in `docket serve --dispatch` loop) drives a pod's
queued tasks through its pipeline, one real, costed agent turn per hop. Earlier drafts of this
document sketched a memory-file signaling protocol (`TASK.md`/`DONE.md`/`APPROVED.md`/
`VALIDATED.md`) with Telegram polling and a fixed 3-retry escalation — that was never what
`core/dispatch.py` implements. This section replaces it with the mechanism as it actually ships,
resolved against a declarative pipeline by `core/orchestrator.py`.

### Task state machine

A queued task moves through six states: `pending` → `running` → `done` | `failed` | `blocked` |
`waiting_approval`.

- **Claiming is locked, not read-then-write.** `pending` → `running` is a single locked
  read-modify-write (`edges/store.py`) that also persists `startedAt`, `claimId`, and
  `claimedAt` — this is what stops two concurrent `dispatch_pod` calls on the same pod from
  double-running the *same* task (they may each claim and run *different* tasks concurrently,
  which is fine).
- **Hops persist as they complete**, not only when the whole task finishes, so a crash mid-task
  loses at most the in-flight hop. A stale `running` claim (one whose `claimedAt` hasn't advanced
  recently) is swept to `failed` with `failureKind: "stale_claim"` and is resumable —
  `dispatch_pod(..., resume=True)` re-claims it and continues from the last persisted hop,
  replaying mid-rework position if needed, rather than restarting at hop 0.
- **`blocked` is never silently rewritten to `pending`.** A budget-blocked task only re-enters the
  queue via `unblock_pod` (a pod-wide budget change) or `retry_task` (one task, explicit).
- **`waiting_approval`** sits outside the normal forward flow: a gated hop stops the task there
  with an approval token and the exact pipeline position it stopped at; `docket approve`/
  `docket deny` (or the HTTP `POST /approvals/<token>` endpoint) resolve it — a grant hands that
  position back to the *next* claim as a single-use gate override, a deny fails the task
  immediately with `failureKind: "approval_denied"`.

### Pipeline resolution and generalized gates

Before the platform work, dispatch hardcoded a four-role Lead → Implementer → Reviewer → Tester
order and its own Reviewer/Tester verdict parsing. Today `core/orchestrator.py`'s `resolve_plan`
takes a `PipelineSpec` (the docket-native YAML format — `docket pipeline validate/plan/run`,
`core/pipeline.py`) plus a pod's live roster and the role-archetype registry (`core/archetypes.py`
— see `docket roles`), and produces a deterministic `ExecutionPlan`: the same spec, roster, and
registry always yield the same step DAG, independent of wall-clock time or dict-iteration order.
A pod with no pipeline file resolves the built-in default pipeline — behaviorally identical to
the old hardcoded order, so a pod created before any of this shipped keeps working unchanged.

Each resolved step's gate is one of three kinds, read from the step's own declaration or — if the
step doesn't declare one — its role archetype's `gateContract`:

- **`mechanical`** — run a command; nonzero exit fails the step. This is the Implementer's
  `verifyCmd` today (`docket pod <project> add --verify "<cmd>"` / `set-verify`), resolved
  against the member's real working tree (worktree → shared codebase → the member's own
  workspace dir).
- **`verdict`** — match the first non-blank line of a hop's output against a configured regex
  set; a match in the gate's `passValues` advances the pipeline. This generalizes the Reviewer's
  APPROVE/REQUEST-CHANGES and the Tester's PASS/FAIL to an arbitrary marker vocabulary for any
  archetype (a `critic`'s SOURCES-VERIFIED/UNVERIFIED, for instance). A verdict gate can carry a
  bounded `rework` edge — a REQUEST-CHANGES re-runs a target step (by default, back to the
  Implementer) up to a configured cycle budget (`maxReworkCycles`, default `1`) before a second
  rejection fails the task terminally. There is no fixed "3 retries then escalate to a human
  Engineer" — the bound is one small integer, and the terminal state is simply `failed`, visible
  via `docket pod <project> queue` / `docket runs`.
- **`approval`** — the step must not proceed until an operator grants it through docket's
  headless approval channels; this is what produces a `waiting_approval` task.

A `parallel` group lets a step fan out into concurrently-run child steps (for example, one per
`--count N` duplicate role member); `core/orchestrator.py`'s `run_group` runs them on a bounded
thread pool and joins before the pipeline advances past that position.

### Retries and timeouts

A hop whose agent turn fails with a *retryable* failure kind (`timeout` or `daemon_error` — a
daemon hiccup, not a real answer; `nonzero_exit`/`invalid_output` are not retried) is retried in
place, up to a per-role retry budget, with linear backoff; the attempt count is persisted per
hop. Every retry refreshes the task's claim timestamp, so a legitimately long retry loop can't be
mistaken for a stale claim by a different concurrent dispatcher. The agent-turn timeout and the
`verifyCmd` timeout are independent, each resolved as: an explicit CLI override
(`docket pod <p> dispatch --timeout`), then the pod Lead's own meta fields, then a built-in
default.

### Structured handoff artifacts and the context compiler

Before the platform work, a hop's prompt was built by concatenating every prior hop's raw text
output, capped only by a process-wide byte budget. Today every hop produces a typed
`HandoffArtifact` (`core/handoff.py`: `summary`, `files_changed`, `diff_ref`, `verdict`, `notes`)
instead of a raw string, persisted alongside its hop record so `--resume` recovers it exactly.
`files_changed` and `diff_ref` are populated for a real Implementer hop via a git probe of its
working tree (uncommitted changes and the current branch name — not a diff against a fixed base
ref); `notes` is reserved in the schema but has no producer yet, honestly documented as such
rather than implied to be populated.

`core/context.py`'s `compile_artifact` fits each prior hop's artifact into the *next* hop's
per-role token budget (`RoleArchetype.token_budget`, declared per archetype rather than one
global constant — 6000 by default). A hop further into the past gets a smaller share of that
budget, the same halving series a byte-budget stopgap originally used, now denominated in tokens.
If an artifact doesn't fit, fields are shed one at a time in a declared order — `notes`, then
`diff_ref`, then `files_changed`, then `verdict` — before `summary` itself is ever touched; only
once every droppable field is gone and it still doesn't fit is `summary` truncated, always with a
visible `[... summary truncated: N bytes omitted ...]` marker, never silently. Token counts are an
honest `chars ÷ 4` approximation — there is no tokenizer dependency, and this number is never used
to bill against, only to bound a prompt deterministically.

### The run registry and cancellation

Every dispatch invocation — from the CLI, the `serve` webhook, a due schedule, the periodic sweep
loop, or an MCP `dispatch` tool call — creates a record in the run registry (`core/runs.py`)
*before* the work starts, and folds it to a terminal state (`succeeded`, `failed`, or `cancelled`)
when it finishes. `docket runs` queries it; this closed a real gap where background dispatch paths
used to swallow every exception and return before anything ran, leaving no run id and no way to
tell "done" from "failed" from "never ran."

`docket runs cancel <id>` kills every pid recorded against that run's process *group* (each hop
subprocess starts its own session, so its pid doubles as its group id) and marks the run
`cancelled` — a state distinct from an ordinary failure. A run can have more than one pid recorded
at once when a `parallel` step has more than one hop genuinely in flight.

### The policy engine on the dispatch path

Declarative policies (`docket policies`, `core/policy.py`) are evaluated at two points on the live
dispatch path, not just in the CLI's own dry-run tester: `pre_input` once, at task enqueue (so the
same task text doesn't re-trip a wildcard-scoped policy at every hop), and `pre_output` on every
hop's real output, before it is embedded in the carried-forward artifact. A `block` verdict on
`pre_input` rejects the task before it is ever queued; a `require_approval` verdict enqueues it
straight into `waiting_approval`. A `block` on `pre_output` fails the hop the same way a failed
agent turn does; `redact` scrubs the text in place; `warn` only logs and feeds `docket metrics`.
In-turn tool calls (`pre_tool_call`) stay daemon-gated — docket is not inside a turn to intercept a
tool call — and this engine never claims to enforce them.

---

## FAQ

### Q: What does DOCKET stand for?

**A:** Roles, Autonomy, Context isolation, Knowledge
- **R**oles: Clean split — Lead orchestrates, Implementer codes, Reviewer/Tester gate
- **A**utonomy: Agents work independently with clear responsibilities
- **C**ontext: Per-pod isolation keeps each project's context scoped to its own pod
- **K**nowledge: Memory management enables fast access

### Q: Is this the same as the original DOCKET.md proposal?

**A:** Similar spirit, adapted for OpenClaw's capabilities:
- ✅ Kept: Distinct agent roles, context discipline, security focus
- ✅ Changed: Coordination is a real dispatch state machine driving costed agent turns
  ([Dispatch Internals](#dispatch-internals)), not RPC and not memory-file signaling
- ✅ Changed: Orchestration is a per-pod Lead, not a global router with a classifier
- ✅ Changed: Security (separate specialist, not merged into Reviewer)

See [Agent Teams (Pods)](AGENT-TEAMS.md) for the full role model details.

### Q: Do I need to change how I use docket?

**A:** No. `docket install` creates the org specialists and `docket add <project>`
provisions each project's pod with the right templates. Everything else works the same.

### Q: Will this break my existing agents?

**A:** No. Templates are generated per-pod by `docket add` and refreshed by
`docket maintain <id> rebuild`:
- Org specialists (manager, knowledge, security) are created once by `docket install`
- Each project pod (lead + implementer, optionally reviewer/tester) is isolated
- Project agents are never touched by another project's setup

### Q: How much will I save?

**A:** See [Cost Optimization](#cost-optimization) above and
[Cost reporting and its limits](../README.md#cost-reporting-and-its-limits) — the short version
is: token reduction from isolation is real but not a fixed percentage, and docket reports
**recorded** spend rather than a savings promise.

---

## Next Steps

1. **If not installed:** `docket install` (creates org specialists)
2. **Add a project pod:** `docket add <project>` (provisions lead + implementer)
3. **Inspect context:** `docket context <project> show` (quick per-project view)
4. **Test workflow:** Assign bug fix, observe token usage
5. **Monitor spend:** `docket cost` (recorded spend)

---

## References

- [Quick Start Guide](QUICK-START-DOCKET.md) - Get started in 5 minutes
- [Workflow Guide](WORKFLOW-GUIDE.md) - Complete examples
- [Security Model](SECURITY-SIMPLE.md) - Layered, convention-based security
- [Commands Reference](commands.md) - All commands
- [Agent Teams (Pods)](AGENT-TEAMS.md) - The canonical team model reference
- [specs/](../specs/) - RFC 2119 functional/API/data specifications; the exact, CI-validated
  behavioral contract for anything summarized in this document

---

**Last Updated:** 2026-07-31
**Status:** Implemented, automated-test-backed — not yet field-hardened (see the beta warning at
the top of this document)
