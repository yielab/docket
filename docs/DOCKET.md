# DOCKET Architecture

**DOCKET = Roles, Autonomy, Context isolation, Knowledge**

Complete technical guide to docket's DOCKET architecture implementation.

---

## Table of Contents

1. [Overview](#overview)
2. [Core Principles](#core-principles)
3. [Performance Results](#performance-results)
4. [Agent Roles](#agent-roles)
5. [Memory Management](#memory-management)
6. [Security Model](#security-model)
7. [Cost Optimization](#cost-optimization)
8. [Implementation Status](#implementation-status)
9. [Technical Details](#technical-details)

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
    → Reads this project's SNAPSHOT.md (2K tokens)
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

## Core Principles

### 1. Per-Pod Context Isolation

**Each project's context stays inside its own pod.**

- Every pod has its own workspace and per-pod session key
- The Lead reads this pod's SNAPSHOT.md (2K), not a shared cross-project history (100K)
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
  budget cap (`docket profile <project>-lead --budget N`). Over budget → the task is left
  **pending**, not run.
- **Traced.** Each hop emits a Phase-8 trace event (`docket trace`) on a per-task session
  `agent:<project>:<task_id>` — every run is auditable, no manual Telegram relay.
- **Pod-local.** Dispatch only ever targets the project's own pod members. **There is no
  cross-pod dispatch path** — one pod can never run another pod's agents.

Each hop is a real, costed LLM turn, which is why dispatch is **explicit** (`docket pod …
dispatch`) or **opt-in** (`docket serve --dispatch`) — never silent. Plain `docket serve` is a
read-only monitor and does not dispatch.

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

### Token Usage (Before vs After)

The lever DOCKET actually controls is **per-pod context isolation**. When every project
lives in its own pod + workspace with its own session key, each agent only ever reads
*its* project's context instead of one shared, ever-growing cross-project history.

```
Before: every project shares one context window
        → agents read mixed-project history (100K+ tokens) on every turn

After:  each project is an isolated pod
        → the Lead reads this pod's SNAPSHOT.md (~2K tokens)
        → the Implementer reads only the workspace files it touches
        → context never accumulates across projects
```

Token reduction is what isolation controls and what you can measure. We don't quote a fixed
percentage — the real number depends on your projects and usage. Read your **recorded** spend
with `docket cost`; it also depends on your models and current pricing, so we don't project
dollars here.

### Response Time

Isolated pods process less context per turn, so the Lead can answer status/memory queries
quickly (it reads SNAPSHOT.md rather than a full cross-project history), while code changes
still take as long as the Implementer needs to do the work. Measure actuals for your own
workload rather than relying on fixed figures.

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
- Reads this pod's SNAPSHOT.md, not a full cross-project history
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

**Model:** strong class (role policy) (needs reasoning for orchestration)

### Implementer

**Role:** Code implementation specialist (replaces the old global "programmer")

**Capabilities:**
- Runs **inside the project workspace**, with full read/write on the project
- Reads the project files it needs directly (it is in the workspace, not handed a tiny brief)
- Implements the requested change
- Signals completion via DONE.md

**Tools:**
- `read`, `write`, `edit`
- `exec` (sandbox only)

**Cannot:**
- Review security (reviewer's job)
- Run validation tests (tester's job)
- Commit or push

**Model:** cheap class (simple) / strong class (complex), per role policy

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

**Model:** strong class (role policy) (security reasoning required)

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
coordinator and task queue — **not** a router with a classifier, and it does not compress
prompts into briefs.

### Manager

**Role:** Cross-cutting coordination and the shared task queue

**Capabilities:**
- Holds the org-wide task queue (`docket team queue` / `docket team delegate`)
- Coordinates work that spans more than one pod
- Reads memory/snapshots, not full history

**Tools:**
- `read` (memory files only)
- `openclaw message send`

**Cannot:**
- Edit code
- Run commands
- Commit

**Model:** strong class (role policy)

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

### Solution: Isolated pods + SNAPSHOT.md

**After DOCKET:**
```
The pod's Lead reads:
- this project's SNAPSHOT.md: ~2K tokens
The Implementer reads:
- only the workspace files it touches
────────────────────────────────────
Context stays scoped to one project's pod
```

### SNAPSHOT.md Contents

Created by `docket memory snapshot <project>`:

```markdown
# Project Snapshot — 2026-03-06

## Metadata
- Project: mywebsite
- Codebase: ~/Sites/mywebsite
- Stack: Next.js
- Model: strong class (role policy)
- Session Key: agent:mywebsite:main

## Current State
### Active Tasks (from HEARTBEAT.md)
- [ ] Fix authentication bug
- [ ] Add dark mode toggle

## Recent Activity (Last 7 Days)
### 2026-03-06
- Implemented user profile page
- Fixed null pointer in login.js

### 2026-03-05
- Added password reset flow
- Updated dependencies

## Architectural Decisions (from MEMORY.md)
### Auth Strategy
- Using Auth0 for OAuth2
- JWT tokens stored in httpOnly cookies
- Refresh token rotation enabled

## Quick Stats
- Total memory files: 45
- Last activity: 2 hours ago
- Size: 12MB
```

**Agent reads this (2K tokens) instead of full history (100K tokens).**

### Memory Index

Created by `docket memory index <project>`:

```json
{
  "indexed_at": "2026-03-06T14:30:00Z",
  "files": [
    {"path": "memory/2026-03-06.md", "date": "2026-03-06", "entries": 5},
    {"path": "memory/2026-03-05.md", "date": "2026-03-05", "entries": 3}
  ],
  "keywords": {
    "authentication": ["2026-03-06", "2026-03-04"],
    "dark mode": ["2026-03-06"],
    "null pointer": ["2026-03-06", "2026-02-28"]
  },
  "decisions": [
    {"title": "Auth Strategy", "preview": "Using Auth0 for OAuth2..."},
    {"title": "Database Choice", "preview": "PostgreSQL with Prisma..."}
  ]
}
```

**Fast search without reading all files.**

### Memory Commands

```bash
# Create fast-access snapshot
docket memory snapshot <project>

# Index for search
docket memory index <project>

# Search indexed memory
docket memory search <project> "authentication bug"

# Archive old logs (>30 days)
docket memory compress <project>

# Show quick reference
docket memory project <project>
```

---

## Security Model

See [SECURITY-SIMPLE.md](SECURITY-SIMPLE.md) for full details.

### Three Layers (All Automatic)

**Layer 1: Prevention (Agent SOUL.md)**
```markdown
## Safety Constraints (NEVER Violate)
1. NEVER commit to git
2. NEVER push to remote
3. NEVER delete files without instruction
4. NEVER run production commands
5. NEVER store secrets
```

**Layer 2: Detection (Reviewer Checklist)**
- Runs automatically on EVERY code change
- 6-point mandatory checklist
- Veto power (rejects immediately if any fail)

**Layer 3: Audit (Engineer Review)**
- Engineer reviews `git diff` before commit
- Final human check

### Prompt Injection Protection

**Reviewer detects:**
```regex
(ignore|disregard|override).*previous.*(instruction|rule|prompt)
you are now|act as|system:|assistant:
<!--\s*AGENT:.*-->
```

**If found → REJECTED immediately**

### Commit Prevention

**How it works:**
1. Agent SOUL.md says: "NEVER commit"
2. Reviewer checks: "No git commands in code"
3. Engineer commits manually

**Result:** Zero agent commits, full engineer control

---

## Cost Optimization

### Model Selection

```
Economy:  low cost   - Simple tasks
Standard: moderate   - Complex reasoning
Premium:  high cost  - Exceptionally complex (rarely used)
```

**The role→model policy routes high-volume roles to the cheap model class:**
- Implementer (simple changes)
- Tester (validation)
- Knowledge (pattern extraction)

**Result:** routine work runs on the cheap model class with isolated, project-scoped context —
fewer tokens at a lower per-token price. (Exact dollar savings depend on your models and
pricing — read `docket cost`.)

### Context Isolation Rules

```
Each pod is sealed:
❌ No agent reads another project's history or memory
✅ The Lead reads this pod's SNAPSHOT.md; the Implementer reads its own workspace

Per-pod session keys keep context from accumulating across projects.
```

### Why a status query stays cheap

```
Status / memory query:
The Lead reads this pod's SNAPSHOT.md / HEARTBEAT.md (~1-2K tokens)
instead of a full cross-project history — no worker is spawned.
```

---

## Implementation Status

### Validated Components ✅

```
Lead:        ✓ Per-pod orchestrator (owns context/memory, never edits code)
Implementer: ✓ Runs in the project workspace (full read/write)
Reviewer:    ✓ Read-only veto (6-point checklist)
Tester:      ✓ Behavior-only validation
Knowledge:   ✓ Org specialist (tools + memory management)
Security:    ✓ Org specialist (HITL gates + threat modeling)
Manager:     ✓ Org specialist (cross-cutting coordination + task queue)
```

### Features Implemented ✅

- [x] Memory management system (`docket memory`)
- [x] Team management (`docket team`)
- [x] SNAPSHOT.md generation
- [x] Memory indexing & search
- [x] Per-pod context isolation (workspace + session key)
- [x] Security checklist (6 points)
- [x] Behavior-only validation
- [x] Bug-fix pipeline template (Lobster)
- [x] HITL gate protocols
- [x] Cost tracking & optimization

### Documentation ✅

- [x] Quick Start Guide
- [x] Workflow Guide
- [x] Security Model (Simple)
- [x] DOCKET Architecture (this doc)
- [x] Commands Reference
- [x] Agent Validation Report

---

## Technical Details

### Agent Communication

**Before DOCKET (one shared context):**
```
A single agent (or shared pool) drags every project's history
into one window on every turn:
{
  "conversation_history": [...100K tokens, mixed projects...],
  ...
}
```

**After DOCKET (isolated pod):**
```
Lead writes: memory/tasks/T001/TASK.md
─────────────────────────────────────────────
TASK: Fix null pointer exception in the login handler
FILE: src/auth/login.js
ACCEPTANCE:
  • Login succeeds with valid token
  • Returns 401 for null token
─────────────────────────────────────────────

Lead → Implementer (Telegram): "Pick up memory/tasks/T001/TASK.md"

The Implementer is already in the project workspace, so it opens
login.js and whatever else it needs directly — it is NOT limited
to a tiny brief.
```

### Completion Signals

All pod roles signal completion via memory files:

```
memory/tasks/T001/
├── TASK.md           # Lead creates
├── DONE.md           # Implementer signals
├── APPROVED.md       # Reviewer signals (or REJECTED.md)
└── VALIDATED.md      # Tester signals (or FAILED.md)
```

**Polling:** the Lead checks every 30-60s for completion files

### Retry Logic

```
Implementer → DONE.md
           ↓
Reviewer → APPROVED? ──Yes──→ Tester
         ↓
        No → REJECTED.md
           ↓
Implementer (retry 1/3)
           ↓
Reviewer → APPROVED? ──Yes──→ Tester
         ↓
        No → REJECTED.md
           ↓
Implementer (retry 2/3)
           ↓
Reviewer → APPROVED? ──Yes──→ Tester
         ↓
        No → ESCALATE to Engineer
```

**Max 3 retries, then HITL intervention**

---

## Comparison: Before vs After

### Before DOCKET

**Problems:**
- ❌ Agents read 100K+ tokens of mixed-project history
- ❌ One shared context — projects contaminate each other
- ❌ No security gate
- ❌ Tester read code (biased validation)
- ❌ No clean split between orchestration and code-writing
- ❌ Overlapping work between roles

**Token usage:** context grows without bound across projects

### After DOCKET

**Solutions:**
- ✅ Each project is an isolated pod (own workspace + session key)
- ✅ The Lead reads this pod's SNAPSHOT.md (~2K tokens); the Implementer reads its own workspace
- ✅ Mandatory 6-point security checklist (read-only reviewer veto)
- ✅ Behavior-only validation (objective)
- ✅ Lead orchestrates, Implementer codes — never the same agent
- ✅ Linear pipeline (no overlap)

**Token usage:** scoped per pod — measure it with `docket cost`

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
- ✅ Changed: Communication (Telegram + memory files, not RPC)
- ✅ Changed: Orchestration is a per-pod Lead, not a global router with a classifier
- ✅ Changed: Security (separate specialist, not merged into Reviewer)

See [Comparison Table](DOCKET-ANALYSIS.md#comparison-docketmd-vs-current-implementation) for details.

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

**A:** The reliable lever is **token reduction from per-pod context isolation** — each agent
reads only its own project's context instead of one shared, ever-growing cross-project history.
How much that saves depends entirely on your projects and usage, so we don't quote a fixed
percentage.

Dollar savings track tokens *and* which models you run, so they vary with current pricing.
docket reports your **recorded** spend (`docket cost`) rather than promising a percentage —
see [Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

---

## Next Steps

1. **If not installed:** `docket install` (creates org specialists)
2. **Add a project pod:** `docket add <project>` (provisions lead + implementer)
3. **Create snapshots:** `docket memory snapshot <project>` (for all projects)
4. **Test workflow:** Assign bug fix, observe token usage
5. **Monitor spend:** `docket cost` (recorded spend)

---

## References

- [Quick Start Guide](QUICK-START-DOCKET.md) - Get started in 5 minutes
- [Workflow Guide](WORKFLOW-GUIDE.md) - Complete examples
- [Security Model](SECURITY-SIMPLE.md) - Layered, convention-based security
- [Commands Reference](commands.md) - All commands
- [Implementation Report](AGENT-VALIDATION-COMPLETE.md) - Technical validation

---

**Date:** 2026-03-06
**Status:** Implemented; in active use
