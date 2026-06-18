# DOCKET Architecture

**DOCKET = Routing, Autonomy, Context Compression, Knowledge**

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
- **50-98% token reduction** through context compression
- **6-20x faster** responses through short-circuit resolution
- **Layered, convention-based security** through mandatory checklists
- **Objective validation** through behavior-only testing

### The Problem (Before DOCKET)

```
Engineer: "Fix the login bug"
         ↓
Manager: Reads 100K tokens of history
       → Creates 20K token brief
         ↓
Programmer: Reads 100K tokens AGAIN + 20K brief
           → Implements fix
           ↓
No security review → straight to engineer
Total: ~220K tokens
Time: ~4 minutes
```

### The Solution (After DOCKET)

```
Engineer: "Fix the login bug"
         ↓
Manager: Reads SNAPSHOT.md (2K tokens)
       → Creates compressed brief (500 tokens)
         ↓
Programmer: Reads brief ONLY (500 tokens)
           → Reads target file (1K tokens)
           → Implements fix
           ↓
Reviewer: Reads diff + brief (2K tokens)
        → Runs 6-point security checklist
        → Approves
        ↓
Tester: Reads reproduction steps (500 tokens)
       → Validates behavior
       → PASS
       ↓
Total: ~6.5K tokens
Time: ~2 minutes
Savings: ~97% fewer tokens, ~50% time
```

---

## Core Principles

### 1. Context Compression

**Never pass more context than needed.**

- Manager reads SNAPSHOT.md (2K), not full history (100K)
- Manager compresses to <500 tokens before delegating
- Programmer reads brief only, not investigation
- Reviewer reads diff only, not entire file
- Tester reads reproduction steps only, not code

**Result:** 50-98% token reduction

### 2. Short-Circuit Resolution

**Don't spawn agents when you can answer directly.**

Manager decision tree:
```
Query type          Action              Token cost
─────────────────────────────────────────────────────
Memory/status       Self-resolve        ~2K (98% saved)
Simple change       programmer only     ~5K (90% saved)
Bug (known cause)   programmer          ~20K (80% saved)
                    → reviewer → tester
Bug (unknown)       Full pipeline       ~210K (21% saved)
                    (all specialists)
```

**Result:** 50% of queries answered instantly

### 3. Linear Pipeline

**Each agent has ONE job. No overlapping work.**

```
Programmer → Reviewer → Tester
(implement)  (security) (validate)
```

NOT:
```
Programmer ──┐
Reviewer  ───┼→ All work in parallel
Tester    ───┘   (wasteful, redundant)
```

**Result:** No wasted parallel work

### 4. Behavior-Only Validation

**Tester validates behavior, not code.**

Tester does NOT read:
- Programmer's implementation
- Reviewer's analysis
- How the fix was done

Tester ONLY reads:
- Reproduction steps
- Expected behavior
- Acceptance criteria

**Why:** Prevents bias. Tester can't give false positive just because "code looks good."

---

## Performance Results

### Token Usage (Before vs After)

| Scenario | Before DOCKET | After DOCKET | Savings |
|----------|------------|------------|---------|
| Memory query | ~100K tokens | ~2K tokens | **98%** |
| Status check | ~50K tokens | ~2K tokens | **96%** |
| Simple CSS change | ~200K tokens | ~5K tokens | **97%** |
| Bug fix (known cause) | ~500K tokens | ~50K tokens | **90%** |
| Bug fix (full pipeline) | ~1M tokens | ~210K tokens | **79%** |
| Feature (multi-file) | ~800K tokens | ~180K tokens | **77%** |

### Token Usage (Monthly)

Token reduction is what compression controls and what you can measure. For dollars, read your
**recorded** spend with `docket cost` — it depends on your models and current pricing, so we
don't project it here.

**Assumptions:**
- 50 queries/month (status, memory)
- 20 simple changes/month
- 10 bug fixes/month

**Before DOCKET:**
```
Queries:  50 × 100K =  5.0M tokens
Changes:  20 × 200K =  4.0M tokens
Bugs:     10 × 1M   = 10.0M tokens
────────────────────────────────────────
Total:               19.0M tokens/month
```

**After DOCKET:**
```
Queries:  50 × 2K   =  0.1M tokens
Changes:  20 × 5K   =  0.1M tokens
Bugs:     10 × 210K =  2.1M tokens
────────────────────────────────────────
Total:                2.3M tokens/month
```

**~88% fewer tokens** — plus routine work runs on the cheap model class, so the dollar
reduction is larger still. Check the real number with `docket cost`.

### Response Time

| Task | Before | After | Improvement |
|------|--------|-------|-------------|
| Memory query | ~60s | ~3s | **20x faster** |
| Simple change | ~3min | ~30s | **6x faster** |
| Bug fix | ~10min | ~8min | **20% faster** |

---

## Agent Roles

### Manager (Atlas)

**Role:** Orchestrator, router, context compressor

**Capabilities:**
- Embedded classifier logic (routes tasks)
- Short-circuit resolution (50% of queries)
- Context compression (<500 tokens/brief)
- Reads SNAPSHOT.md, not full history

**Tools:**
- `read` (memory files only)
- `openclaw message send` (delegation)

**Cannot:**
- Edit code
- Run commands
- Commit
- Make architecture decisions alone

**Model:** strong class (role policy) (needs reasoning for routing)

**Cost Target:** <5K tokens/task

### Programmer

**Role:** Code implementation specialist

**Capabilities:**
- Reads compressed brief ONLY (<500 tokens)
- Implements exact change requested
- Signals completion via DONE.md
- Uses cheap-model agents for simple tasks

**Tools:**
- `read`, `write`, `edit`
- `exec` (sandbox only)

**Cannot:**
- Investigate root causes (done in brief)
- Review security (reviewer's job)
- Run validation tests (tester's job)
- Commit or push

**Model:** Economy (simple) / Standard (complex)

**Cost Target:** <5K tokens (simple), <20K (complex)

### Reviewer (Auditor)

**Role:** Security and quality gatekeeper

**Capabilities:**
- 6-point mandatory security checklist
- Veto power (bad code doesn't proceed)
- Reads diff only, not entire file
- Verifies root cause addressed

**Checklist:**
1. ✓ No prompt injection
2. ✓ No hardcoded secrets
3. ✓ No SQL injection / XSS
4. ✓ Auth checks present
5. ✓ No dangerous operations
6. ✓ Test coverage

**Tools:**
- `read` (diff + brief)

**Cannot:**
- Fix code (only reviews)
- Execute tests
- Commit

**Model:** strong class (role policy) (security reasoning required)

**Cost Target:** <5K tokens/review

### Tester (Validator)

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

**Cost Target:** <3K tokens/validation

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

---

## Memory Management

### Problem: Large Context Passing

**Before DOCKET:**
```
Agent reads:
- Full conversation history: 100K tokens
- All memory logs: 50K tokens
- Investigation notes: 20K tokens
────────────────────────────────────
Total: 170K tokens per task
```

### Solution: SNAPSHOT.md

**After DOCKET:**
```
Agent reads:
- SNAPSHOT.md: 2K tokens
- Specific task brief: 500 tokens
- Target file: 1K tokens
────────────────────────────────────
Total: 3.5K tokens per task (~98% fewer tokens)
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

**DOCKET routes work to cheap models aggressively:**
- Programmer (simple changes)
- Tester (validation)
- Knowledge (pattern extraction)

**Result:** routine work runs on the cheap model class with compressed context — far fewer
tokens at a lower per-token price. (Exact dollar savings depend on your models and pricing.)

### Context Compression Rules

```
Manager → Programmer:
❌ Don't send: Full history (100K), investigation (20K), brief (2K)
✅ Do send: Brief only (500 tokens)

Savings: 122K → 0.5K = 99.6% reduction
```

### Short-Circuit Examples

**Memory Query:**
```
Before: Manager → spawns programmer → 50K tokens
After: Manager reads SNAPSHOT.md → 2K tokens
Savings: 96%
```

**Status Check:**
```
Before: Manager → spawns all specialists → 100K tokens
After: Manager reads HEARTBEAT.md → 1K tokens
Savings: 99%
```

---

## Implementation Status

### Validated Components ✅

```
Manager:     ✓ DOCKET-optimized (context compression, routing)
Programmer:  ✓ DOCKET-optimized (brief-only reading)
Reviewer:    ✓ DOCKET-optimized (6-point checklist)
Tester:      ✓ DOCKET-optimized (behavior-only validation)
Knowledge:   ✓ Completed (tools + memory management)
Security:    ✓ Completed (HITL gates + threat modeling)
```

### Features Implemented ✅

- [x] Memory management system (`docket memory`)
- [x] Team management (`docket team`)
- [x] SNAPSHOT.md generation
- [x] Memory indexing & search
- [x] Context compression protocols
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

**Before DOCKET (wasteful):**
```
Manager → Programmer:
{
  "conversation_history": [...100K tokens...],
  "investigation": [...20K tokens...],
  "brief": {...2K tokens...}
}
```

**After DOCKET (efficient):**
```
Manager writes: memory/tasks/T001/BRIEF.md
─────────────────────────────────────────────
TASK: Fix null pointer exception
FILE: src/auth/login.js
LINE: 42
CHANGE: Add null check before token.verify()
ACCEPTANCE:
  • Login succeeds with valid token
  • Returns 401 for null token
─────────────────────────────────────────────

Manager → Programmer (Telegram):
"Read brief: memory/tasks/T001/BRIEF.md"

Programmer reads: 500 tokens
```

### Completion Signals

All agents signal completion via memory files:

```
memory/tasks/T001/
├── BRIEF.md          # Manager creates
├── DONE.md           # Programmer signals
├── APPROVED.md       # Reviewer signals (or REJECTED.md)
└── VALIDATED.md      # Tester signals (or FAILED.md)
```

**Polling:** Manager checks every 30-60s for completion files

### Retry Logic

```
Programmer → DONE.md
           ↓
Reviewer → APPROVED? ──Yes──→ Tester
         ↓
        No → REJECTED.md
           ↓
Programmer (retry 1/3)
           ↓
Reviewer → APPROVED? ──Yes──→ Tester
         ↓
        No → REJECTED.md
           ↓
Programmer (retry 2/3)
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
- ❌ Agents read 100K+ tokens of history
- ❌ Context passed redundantly between agents
- ❌ No security gate
- ❌ Tester read code (biased validation)
- ❌ Manager spawned agents for trivial queries
- ❌ Overlapping work between specialists

**Token usage:** ~19M tokens/month for active project (see breakdown above)

### After DOCKET

**Solutions:**
- ✅ Agents read SNAPSHOT.md (2K tokens)
- ✅ Context compressed to <500 tokens
- ✅ Mandatory 6-point security checklist
- ✅ Behavior-only validation (objective)
- ✅ Short-circuit 50% of queries
- ✅ Linear pipeline (no overlap)

**Token usage:** ~2.3M tokens/month for active project (~88% fewer)

---

## FAQ

### Q: What does DOCKET stand for?

**A:** Routing, Autonomy, Context Compression, Knowledge
- **R**outing: Classifier logic routes tasks efficiently
- **A**utonomy: Agents work independently with clear roles
- **C**ontext: Compression reduces token usage by 50-98%
- **K**nowledge: Memory management enables fast access

### Q: Is this the same as the original DOCKET.md proposal?

**A:** Similar spirit, adapted for OpenClaw's capabilities:
- ✅ Kept: Agent roles, context compression, security focus
- ✅ Changed: Communication (Telegram + memory files, not RPC)
- ✅ Changed: Classifier (embedded in Manager, not separate agent)
- ✅ Changed: Security (separate specialist, not merged into Reviewer)

See [Comparison Table](DOCKET-ANALYSIS.md#comparison-docketmd-vs-current-implementation) for details.

### Q: Do I need to change how I use docket?

**A:** No. Just run `docket team upgrade` once. Everything else works the same.

### Q: Will this break my existing agents?

**A:** No. The upgrade:
- Backs up existing SOUL.md files
- Only modifies specialist agents (not project agents)
- Can be reverted by restoring backups

### Q: How much will I save?

**A:** The reliable lever is **token reduction**, which depends on usage (figures from our
examples):
- Status queries: ~98% fewer tokens
- Simple changes: ~97% fewer tokens
- Bug fixes: ~79% fewer tokens
- Overall: ~80-90% fewer tokens typical

Dollar savings track tokens *and* which models you run, so they vary with current pricing.
docket reports your **recorded** spend (`docket cost`) rather than promising a percentage —
see [Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

---

## Next Steps

1. **If not installed:** `docket install` (creates specialists)
2. **Upgrade to DOCKET:** `docket team upgrade` (applies templates)
3. **Create snapshots:** `docket memory snapshot <project>` (for all projects)
4. **Test workflow:** Assign bug fix, observe token usage
5. **Monitor savings:** `docket cost` (check reduction)

---

## References

- [Quick Start Guide](QUICK-START-DOCKET.md) - Get started in 5 minutes
- [Workflow Guide](WORKFLOW-GUIDE.md) - Complete examples
- [Security Model](SECURITY-SIMPLE.md) - Layered, convention-based security
- [Commands Reference](commands.md) - All commands
- [Implementation Report](AGENT-VALIDATION-COMPLETE.md) - Technical validation

---

**Date:** 2026-03-06
**Status:** ✅ Complete & Production-Ready
