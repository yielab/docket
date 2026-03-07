# RACK Architecture Analysis & Implementation Plan

**Date:** 2026-03-06
**Status:** ✅ Feasible with Modifications
**Recommendation:** Phased Implementation with Existing Tools

---

## Executive Summary

The proposed RACK architecture (from RACK.md) is **technically feasible** but requires **significant modifications** to align with:
1. Current OpenClaw capabilities (v2026.2.23)
2. Existing rack-cli infrastructure
3. Real-world operational constraints

**Key Finding:** The architecture is sound, but the implementation strategy should leverage existing OpenClaw tools rather than building a custom orchestration layer.

---

## Architecture Validation

### ✅ What Works (No Changes Needed)

1. **Agent Roles & Separation of Concerns**
   - Classifier, Investigator, Architect, Programmer, Auditor, Validator — all valid roles
   - Least privilege principle — achievable via SOUL.md tool restrictions
   - No git commits policy — already enforced in current specialist agents

2. **Cost Optimization Strategy**
   - Model tiering (Haiku/Sonnet/Opus) — already implemented in rack-cli
   - Context compression — can be enforced via SOUL.md instructions
   - Short-circuit rules — Manager already does this (confirmed in existing SOUL.md)

3. **Security Principles**
   - Tool approval gates — OpenClaw has `approvals` command
   - Workspace isolation — already exists (700 perms on workspaces)
   - Prompt injection defense — can be added to Auditor's SOUL.md checklist

### ⚠️ What Needs Modification

1. **Specialist Agent Count Reduction**
   - **Proposed:** 7 agents (Manager, Classifier, Investigator, Architect, Programmer, Auditor, Validator)
   - **Current:** 6 agents (manager, programmer, reviewer, tester, knowledge, security)
   - **Issue:** Merging Reviewer→Auditor and Security→Auditor loses granularity
   - **Recommendation:** Keep existing 6, add Classifier as a **lightweight routing function** in Manager

2. **Inter-Agent Communication**
   - **Proposed:** `sessions_spawn`, `session_status`, `message` tools
   - **Reality Check:**
     - ❌ `sessions_spawn` — not a native OpenClaw tool (checked CLI docs)
     - ❌ `session_status` — not found in OpenClaw CLI
     - ✅ `message send` — exists! Can send to Telegram groups
     - ✅ `sessions` — exists for viewing session state
   - **Gap:** No native "spawn sub-agent and wait for response" primitive

3. **Structured Output Formats**
   - **Proposed:** JSON contracts (Output A/B/C from Investigator)
   - **Reality:** Agents output natural language to Telegram
   - **Recommendation:** Use markdown structured formats + memory files instead of JSON

### ❌ What Won't Work (Critical Blockers)

1. **Direct Agent-to-Agent Communication**
   - RACK.md assumes Manager can spawn Investigator, receive typed outputs, then spawn Programmer with compressed brief
   - **OpenClaw Reality:** Agents communicate via:
     - Telegram groups (async, human-visible)
     - Memory files (MEMORY.md, daily logs)
     - NOT via direct RPC/API calls between agents

2. **Synchronous Pipeline Enforcement**
   - Proposed workflow: `Investigator → (Output C) → Programmer → (diff) → Auditor → (approval) → Validator → (PASS/FAIL)`
   - **Issue:** No native pipeline orchestration in OpenClaw
   - **Solution:** Use **Lobster workflows** (already in rack-cli!) with human-in-the-loop gates

3. **Classifier as a Separate Agent**
   - Running Haiku on every message just for routing is wasteful
   - **Better:** Classifier logic goes in Manager's SOUL.md as a decision tree
   - Manager can decide to self-resolve or delegate based on simple heuristics

---

## Technical Feasibility Assessment

### OpenClaw Capabilities (Confirmed)

| Feature | Available? | Tool/Command | Notes |
|---------|-----------|--------------|-------|
| Agent registration | ✅ | `openclaw agents add` | Already used by `rack install` |
| Model per-agent config | ✅ | `--model` flag | Already used (Haiku/Sonnet/Opus) |
| Telegram messaging | ✅ | `openclaw message send` | Can send to groups/DMs |
| Session isolation | ✅ | `--session <key>` | rack uses `agent:<id>:<project>` |
| Tool approval gates | ✅ | `openclaw approvals` | Not yet used by rack-cli |
| Memory search | ✅ | `openclaw memory` | Not yet integrated with rack |
| Workspace isolation | ✅ | Directory perms | Already enforced (700) |
| Browser control | ✅ | `openclaw browser` | For Validator/Investigator |
| Workflow pipelines | ⚠️ | Lobster (external) | Mentioned in rack, not tested |

### Missing Capabilities (Need Workarounds)

| Feature (RACK.md) | OpenClaw Native? | Workaround |
|------------------|------------------|------------|
| `sessions_spawn` | ❌ | Use `openclaw message send` to specialist Telegram groups |
| `session_status` | ❌ | Read `memory/YYYY-MM-DD.md` or use `openclaw sessions --active` |
| Structured JSON outputs | ❌ | Use markdown code blocks + file drops in workspace |
| Pipeline enforcement | ❌ | **Use Lobster workflows** with approval gates |
| Context compression | ❌ | Manual instructions in SOUL.md |

---

## Recommended Implementation Strategy

### Phase 1: Foundation (1-2 weeks)
**Goal:** Upgrade existing specialists to RACK-compatible roles

1. **Rename & Repurpose Agents**
   - `reviewer` → `auditor` (add security checklist from RACK.md)
   - `tester` → `validator` (focus on reproduction, not test writing)
   - `knowledge` → keep as-is (handles memory distillation)
   - Add `investigator` as 7th specialist (Sonnet model)
   - Add `architect` as 8th specialist (Sonnet model, docs-only tools)

2. **Update SOUL.md Files**
   - Add RACK.md checklists (especially Auditor's security checks)
   - Add structured output formats (markdown, not JSON)
   - Add "never commit" constraint to all agents
   - Integrate Classifier logic into Manager's SOUL.md

3. **Tool Restrictions**
   - Auditor: read-only access (already possible via SOUL.md instructions)
   - Validator: only `exec` (test commands) + `browser` (snapshots)
   - Programmer: read/write/edit + sandbox `exec`
   - Manager: read (memory only) + `message send` (delegation)

4. **rack-cli Commands**
   - `rack team update` — regenerate all specialist SOUL.md files with RACK templates
   - `rack team roles` — show agent → role mapping

### Phase 2: Communication Layer (2-3 weeks)
**Goal:** Enable Manager → Specialist → Manager message flow

1. **Delegate via Telegram**
   ```bash
   # Manager sends structured brief to programmer group
   openclaw message send \
     --channel telegram \
     --target "group:ProgrammerTeam" \
     --message "$(cat <<EOF
   TASK: Fix authentication bug in login.js
   FILE: src/auth/login.js
   LINE: 42
   CHANGE: Add null check before token.verify()
   ACCEPTANCE: Login succeeds with valid token, returns 401 for invalid
   EOF
   )"
   ```

2. **Status Tracking via Memory Files**
   - Each specialist writes to `memory/YYYY-MM-DD.md` with task status
   - Manager polls memory files to check completion
   - Use `<promise>DONE</promise>` tag (already in current SOUL.md templates!)

3. **Structured Outputs via File Drops**
   - Investigator writes `OUTPUT_A_reproduction.md`, `OUTPUT_B_rootcause.md`, `OUTPUT_C_fix.md`
   - Programmer reads only `OUTPUT_C_fix.md`
   - Validator reads only `OUTPUT_A_reproduction.md`
   - Files live in `/tmp/rack-briefs/<task-id>/` (ephemeral, secure)

### Phase 3: Pipeline Orchestration (3-4 weeks)
**Goal:** Automated bug report → fix → validation flow

1. **Lobster Workflow Integration**
   - Create `bug-fix-pipeline.lobster.yml` template
   - Steps: Investigator → Programmer → Auditor → Validator
   - Use `approval: required` gates for HITL intervention
   - Notifications via Telegram at each gate

2. **rack-cli Workflow Commands**
   ```bash
   rack workflow manager create bug-fix-pipeline
   rack workflow manager run bug-fix-pipeline --input "Bug: login fails with null token"
   rack workflow manager status bug-fix-pipeline
   ```

3. **HITL Gates**
   - After Auditor review → send approval request to engineer's Telegram
   - Engineer can approve/reject/comment via Telegram buttons
   - Use `openclaw approvals` to manage approval state

### Phase 4: Advanced Features (4-6 weeks)
**Goal:** Cost optimization, security hardening, edge cases

1. **Cost Tracking**
   - Integrate with existing `rack cost` command
   - Track tokens per pipeline step
   - Alert if costs exceed budget thresholds

2. **Security Hardening**
   - Implement Auditor's prompt injection scanner
   - Add sandbox container isolation (OpenClaw has `sandbox` command!)
   - Audit logs for all file writes (`rack logs` integration)

3. **Edge Cases**
   - Investigator can't reproduce → escalate to engineer
   - Validator fails 3 times → pause pipeline, request HITL
   - Manager overload → queue tasks in `TASK_LIST.json` (already exists!)

---

## Comparison: RACK.md vs. Current Implementation

| Feature | RACK.md Proposal | Current rack-cli | Recommendation |
|---------|-----------------|------------------|----------------|
| Agent count | 7 (merged security+reviewer) | 6 specialists | Keep 6, add 2 (investigator, architect) = **8 total** |
| Communication | Direct `sessions_spawn` | Telegram + memory files | **Use Telegram + memory files** |
| Pipelines | Enforced by Manager | Lobster workflows (unused) | **Activate Lobster workflows** |
| Outputs | JSON contracts | Natural language | **Structured markdown + file drops** |
| Cost model | Haiku/Sonnet/Opus tiers | Already implemented | ✅ **No changes needed** |
| Security | Auditor checklist | Security specialist | **Merge checklists, keep separate agents** |
| Classifier | Separate Haiku agent | N/A | **Integrate into Manager SOUL.md** |
| No commits | Enforced | Already in SOUL.md | ✅ **No changes needed** |

---

## Critical Design Decisions

### Decision 1: Classifier as Agent or Function?
- **RACK.md:** Separate Haiku agent runs on every incoming message
- **Cost:** ~1K tokens × $0.80/MTok × 100 msgs/day = **$0.08/day = $29/year** (negligible)
- **Latency:** +2-3 seconds per message
- **Recommendation:** **Embed in Manager** (avoid latency, Manager already has context)

### Decision 2: Keep Security as Separate Agent?
- **RACK.md:** Merge into Auditor
- **Current:** Separate `security` specialist
- **Trade-off:**
  - Merge → simpler, fewer agents, forced review on every change
  - Separate → security can be called ad-hoc, specialized focus
- **Recommendation:** **Keep separate** (security is broader than code review — includes threat modeling, pentesting, compliance)

### Decision 3: How to Handle Context Compression?
- **RACK.md:** Manager manually compresses 50K tokens → 150 tokens before spawning Programmer
- **Reality:** No native compression tool in OpenClaw
- **Recommendation:** **SOUL.md instructions** + file drops
  ```markdown
  ## Context Passing Rules (Manager SOUL.md)
  When delegating to Programmer:
  1. Create brief file: `/tmp/rack-briefs/<task-id>/BRIEF.md`
  2. Include ONLY: file path, line numbers, exact change, acceptance criteria
  3. NEVER include: investigation transcript, conversation history, debug logs
  4. Target: <500 tokens
  ```

### Decision 4: Pipeline Enforcement — Code or Workflow?
- **Option A:** Manager enforces pipeline in code (complex, brittle)
- **Option B:** Lobster workflows with approval gates (declarative, testable)
- **Recommendation:** **Option B (Lobster)** — already in rack-cli, just needs templates

---

## Implementation Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Lobster workflows untested | High | High | **Phase 1:** Test with simple 2-step workflow first |
| Telegram rate limits | Medium | Medium | Batch updates, use file drops instead of long messages |
| Memory file polling overhead | Low | Medium | Use `inotify` or gateway webhooks for completion signals |
| Context leakage between agents | High | Low | Enforce session keys (`agent:<id>:<project>`) rigorously |
| Investigator can't reproduce bug | High | Medium | Add 3-strike rule → escalate to engineer + attach logs |
| Auditor approves buggy code | High | Low | Add mandatory checklist enforcement (all items must be checked) |
| Cost explosion (Sonnet spam) | Medium | Medium | Add token budgets per task, fail-fast if exceeded |
| HITL gates ignored/bypassed | High | Low | Require approval in Lobster workflow, block progression |

---

## Cost Analysis (Estimated)

### Current Setup (No RACK)
- Manager: Sonnet (~10K tokens/day) = **$0.03/day**
- 5 specialists: mostly idle, ~5K tokens/day each = **$0.075/day**
- **Total:** ~$0.10/day = **$36.50/year**

### RACK Implementation (Full Pipeline)
- Manager: Sonnet (~15K tokens/day, more coordination) = **$0.045/day**
- Classifier: embedded in Manager = **$0/day** (no separate agent)
- Investigator: Sonnet (~20K tokens/bug, 2 bugs/day) = **$0.12/day**
- Programmer: Haiku/Sonnet (~30K tokens/day) = **$0.09/day**
- Auditor: Sonnet (~10K tokens/day) = **$0.03/day**
- Validator: Haiku (~5K tokens/day) = **$0.01/day**
- Architect: Sonnet (~5K tokens/week) = **$0.007/day**
- **Total:** ~$0.32/day = **$116.80/year**

**Cost increase:** 3.2x (still extremely cheap for autonomous development team)

### Cost Optimization Wins (if implemented correctly)
- Short-circuit resolution (50% of tasks) → **saves ~$0.08/day**
- Context compression (Investigator → Programmer) → **saves ~$0.04/day**
- Haiku for simple tasks → **saves ~$0.02/day**
- **Net cost:** ~$0.18/day = **$65.70/year** (1.8x increase, acceptable)

---

## Recommended Next Steps

### Immediate (This Week)
1. ✅ **Validate this analysis** with engineer (you!)
2. Create `rack team upgrade` command — applies RACK SOUL.md templates to existing specialists
3. Add `investigator` and `architect` agents to `rack install`
4. Update [lib/commands/install.sh](lib/commands/install.sh) to create 8 specialists instead of 6

### Short-term (Next 2 Weeks)
5. Write Lobster workflow template: `bug-fix-pipeline.lobster.yml`
6. Test workflow with real bug (e.g., "fix login.js null pointer")
7. Document in `docs/RACK-IMPLEMENTATION.md` with examples
8. Update [CLAUDE.md](CLAUDE.md) with RACK architecture overview

### Medium-term (Next Month)
9. Integrate `openclaw approvals` with rack-cli (`rack approve <task-id>`)
10. Build `/tmp/rack-briefs/` system for structured file drops
11. Add `rack team roles` command to show agent responsibilities
12. Add cost tracking per pipeline run (`rack cost --by-pipeline`)

### Long-term (Next Quarter)
13. Build monitoring dashboard (cost, success rate, bottlenecks)
14. Optimize context compression (automated summarization)
15. Add multi-project support (Manager coordinates across projects)
16. Write case studies and share with OpenClaw community

---

## Conclusion

**The RACK architecture is sound and implementable**, but requires adaptation to OpenClaw's communication model:

- ✅ **Agent roles:** Valid, map cleanly to specialist structure
- ✅ **Cost strategy:** Already implemented, just needs enforcement
- ✅ **Security:** Achievable via SOUL.md + approvals
- ⚠️ **Communication:** Use Telegram + memory files, not direct spawns
- ⚠️ **Pipelines:** Use Lobster workflows, not custom orchestration
- ❌ **Classifier:** Embed in Manager, don't create separate agent

**Recommendation:** Proceed with phased implementation, starting with Phase 1 (foundation) and testing thoroughly before adding pipeline orchestration.

**Estimated timeline:** 6-8 weeks for full implementation, 2 weeks for MVP (basic delegation).

**ROI:** Autonomous bug fixing → saves 2-5 hours/week of engineer time → **breakeven in ~2 weeks**.

---

## Appendix: Files to Modify

### rack-cli
- [lib/commands/install.sh](lib/commands/install.sh) — add investigator, architect
- [lib/commands/team.sh](lib/commands/team.sh) — add `team upgrade`, `team roles`
- [lib/commands/workflow.sh](lib/commands/workflow.sh) — add pipeline templates
- [lib/helpers/workspace.sh](lib/helpers/workspace.sh) — add RACK SOUL.md templates
- [docs/RACK-IMPLEMENTATION.md](docs/RACK-IMPLEMENTATION.md) — new file (implementation guide)

### OpenClaw Workspaces
- `~/.openclaw/workspaces/manager/SOUL.md` — add Classifier logic, delegation protocol
- `~/.openclaw/workspaces/programmer/SOUL.md` — add "read BRIEF.md only" constraint
- `~/.openclaw/workspaces/reviewer/SOUL.md` → rename to `auditor`, add security checklist
- `~/.openclaw/workspaces/tester/SOUL.md` → rename to `validator`, add reproduction-only mode
- `~/.openclaw/workspaces/investigator/SOUL.md` — new agent (create workspace)
- `~/.openclaw/workspaces/architect/SOUL.md` — new agent (create workspace)

---

**Document prepared by:** Claude (Sonnet 4.5)
**Review status:** Pending engineer validation
**Last updated:** 2026-03-06 16:45 UTC
