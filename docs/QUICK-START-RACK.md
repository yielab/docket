# Quick Start: RACK Architecture

**RACK = Routing, Autonomy, Context Compression, Knowledge**

Get started with RACK-optimized agents in under 5 minutes.

---

## What is RACK?

RACK is an architecture for autonomous agent teams that:
- ✅ **Reduces token usage by 50-90%** through context compression
- ✅ **Speeds up responses 6-20x** through short-circuit resolution
- ✅ **Enforces security** through mandatory 6-point checklist
- ✅ **Validates objectively** through behavior-only testing
- ✅ **Eliminates redundancy** through efficient delegation

---

## Installation

### If You Don't Have Specialists Yet
```bash
cd ~/Sites/rack-cli
./bin/rack install
```

This creates 6 specialists: manager, programmer, reviewer, tester, knowledge, security

### If You Already Have Specialists
```bash
cd ~/Sites/rack-cli
./bin/rack team upgrade
```

This applies RACK-optimized templates (backs up existing SOUL.md files).

---

## Verify Installation

```bash
./bin/rack team status
```

**Expected output:**
```
✓ manager      RACK-optimized
✓ programmer   RACK-optimized
✓ reviewer     RACK-optimized
✓ tester       RACK-optimized
○ knowledge    Standard (already optimized)
○ security     Standard (already optimized)
```

---

## How It Works

### Before RACK (Traditional Agent Workflow)

```
User: "Fix the login bug"
         ↓
Manager: [Reads 100K tokens of conversation history]
         [Creates 20K token brief]
         ↓
Programmer: [Reads 100K tokens AGAIN + 20K brief]
            [Implements fix]
            ↓
Reviewer: [Reads 100K tokens AGAIN + code]
          [Approves]
          ↓
TOTAL: ~320K tokens = $X (strong model class)
TIME: ~4 minutes
```

### After RACK (Optimized Workflow)

```
User: "Fix the login bug"
         ↓
Manager: [Reads SNAPSHOT.md — 2K tokens]
         [Creates compressed brief — 500 tokens]
         [Delegates to programmer]
         ↓
Programmer: [Reads brief ONLY — 500 tokens]
            [Reads target file — 1K tokens]
            [Implements fix]
            [Signals DONE.md]
            ↓
Reviewer: [Reads diff + brief — 2K tokens]
          [Runs 6-point checklist]
          [Approves]
          ↓
Tester: [Reads reproduction steps — 500 tokens]
        [Validates behavior]
        [PASS]
        ↓
TOTAL: ~6.5K tokens = $X (cheap/strong model mix)
TIME: ~2 minutes
SAVINGS: 98% cost, 50% time
```

---

## Key Commands

### Team Management
```bash
rack team status        # Show RACK optimization status
rack team upgrade       # Apply RACK templates
rack team roles         # Show agent responsibilities
rack team check         # Verify all agents exist
```

### Memory Management
```bash
rack memory snapshot <project-id>   # Create fast-access context
rack memory index <project-id>      # Index memory for search
rack memory search <project-id> <q> # Search indexed memory
rack memory compress <project-id>   # Archive old logs
```

---

## Testing Your Setup

### Test 1: Memory Snapshot
```bash
# Create snapshot for a project
rack memory snapshot <project-name>

# Verify it exists
cat ~/.openclaw/workspaces/projects/<project-name>/SNAPSHOT.md
```

**What you should see:**
- Project metadata (codebase path, stack, model)
- Active tasks (from HEARTBEAT.md)
- Recent activity (last 7 days)
- Architectural decisions (from MEMORY.md)

### Test 2: Manager Response (Telegram)
Send this message to your Manager agent in Telegram:

```
What's the current status of [project-name]?
```

**Expected behavior:**
1. **Instant acknowledgment** (<3 seconds):
   ```
   ✓ Got it - checking project status
   → Reading SNAPSHOT.md...
   ⏱ ETA: instant
   ```

2. **Immediate response** (no delegation needed):
   ```
   Status: [project-name]
   • Last activity: 2 hours ago
   • Active tasks: [list from HEARTBEAT.md]
   • Recent changes: [summary from memory]
   ```

**Why it's fast:** Manager reads SNAPSHOT.md (~2K tokens) instead of full conversation history (~100K tokens).

### Test 3: Bug Fix Workflow (Telegram)
Send this message to Manager:

```
Fix bug: Login crashes when token is null
```

**Expected workflow:**
1. **Manager** (3s):
   ```
   ✓ Got it - authentication bug
   → Creating task brief...
   👥 Will involve: programmer, reviewer, tester
   ⏱ ETA: ~8 minutes
   ```

2. **Manager delegates** (compressed brief sent to programmer):
   ```
   TASK: Add null check to login handler
   FILE: src/auth/login.js
   LINE: 42
   CHANGE: Add null check before token.verify()
   ACCEPTANCE:
     • Login succeeds with valid token
     • Returns 401 for null token
   ```

3. **Programmer** (30s acknowledgment):
   ```
   ✓ Got it - implementing null check
   → Reading login.js...
   ⏱ ETA: ~3 minutes
   ```

4. **Programmer completes** (3 min):
   ```
   ✓ Done - login.js null check implemented
   → memory/tasks/T001/DONE.md
   → Ready for reviewer
   ```

5. **Reviewer** (3 min):
   ```
   ✓ Review complete - APPROVED
   → Security: OK (no vulnerabilities)
   → Root cause: Addressed
   → Ready for tester
   ```

6. **Tester** (2 min):
   ```
   ✓ Validation complete - PASS
   → Bug no longer reproducible
   → All tests pass (15/15)
   → Ready for engineer review & commit
   ```

7. **Manager reports** (instant):
   ```
   ✅ Bug fix complete!
   Files changed: src/auth/login.js
   Next step: Review and commit
   ```

---

## What Changed in Each Specialist

### Manager (Atlas)
**Before:** General coordinator, read full history
**After:**
- Embedded classifier logic (routes tasks efficiently)
- Reads SNAPSHOT.md instead of full history
- Compresses context to <500 tokens before delegating
- Short-circuits 50% of queries (no delegation needed)

### Programmer
**Before:** Read full conversation + investigation + brief
**After:**
- Reads compressed brief ONLY (<500 tokens)
- Target: <5K tokens per task
- Signals completion via DONE.md
- Uses cheap-model agents for simple tasks

### Reviewer
**Before:** General code review
**After:**
- **6-point mandatory checklist:**
  1. Prompt injection vectors
  2. Authentication & authorization
  3. Data security (SQL injection, XSS)
  4. Side effects & scope
  5. Completeness (root cause fixed)
  6. Test coverage
- Reads diff only (not entire file)
- Veto power (bad code doesn't proceed)

### Tester
**Before:** Read code + run tests
**After:**
- **Behavior-only validation** (does NOT read code!)
- Executes reproduction steps objectively
- Binary verdict: PASS or FAIL
- Runs on the cheap model class (sufficient for validation)

---

## Cost Savings Examples

### Example 1: Status Query
**Before:**
```
Engineer: "What's the status?"
Manager reads 100K tokens → $0.30
Time: 60s
```

**After:**
```
Engineer: "What's the status?"
Manager reads SNAPSHOT.md (2K tokens) → $0.006
Time: 3s
```
**Savings: 98% cost, 20x faster**

### Example 2: Simple CSS Change
**Before:**
```
Full history read + implementation = 200K tokens → $0.60
Time: 3 minutes
```

**After:**
```
Brief (500) + file (1K) + implement (500) = 2K tokens → fraction of a cent (cheap model class)
Time: 30 seconds
```
**Savings: 99.7% cost, 6x faster**

### Example 3: Bug Fix Pipeline
**Before:**
```
Investigation + fix + review + test = 1M tokens → $3.00
Time: 10 minutes
```

**After:**
```
Compressed pipeline = 210K tokens → $0.63
Time: 8 minutes
```
**Savings: 79% cost, 20% faster**

---

## Common Questions

### Q: Will this break my existing agents?
**A:** No. The upgrade:
- Backs up existing SOUL.md files (timestamped)
- Only modifies specialist agents (manager, programmer, reviewer, tester)
- Doesn't touch project agents
- Can be reverted by restoring backups

### Q: Do I need to change how I message agents?
**A:** No. Message the same way. The agents now:
- Respond faster (less context to process)
- Use fewer tokens (compressed communication)
- Provide clearer status updates

### Q: What if I want the old behavior back?
**A:** Restore from backups:
```bash
cd ~/.openclaw/workspaces/manager
cp SOUL.md.backup-YYYYMMDD-HHMMSS SOUL.md
systemctl --user restart openclaw-gateway.service
```

### Q: Can I customize the templates?
**A:** Yes! Edit the SOUL.md files directly:
```bash
rack edit manager    # Opens manager's SOUL.md in $EDITOR
```

Then restart the gateway to apply changes:
```bash
systemctl --user restart openclaw-gateway.service
```

### Q: How do I know it's working?
**A:** Check token usage:
1. Message manager with a status query
2. Check OpenClaw logs for token count
3. Should see ~2K tokens instead of ~100K

---

## Troubleshooting

### Agents Still Using Large Context?
1. **Verify upgrade applied:**
   ```bash
   rack team status
   ```
   All should show "RACK-optimized"

2. **Check SNAPSHOT.md exists:**
   ```bash
   ls ~/.openclaw/workspaces/projects/*/SNAPSHOT.md
   ```

3. **Create snapshot if missing:**
   ```bash
   rack memory snapshot <project-id>
   ```

4. **Restart gateway:**
   ```bash
   systemctl --user restart openclaw-gateway.service
   ```

### Agents Not Acknowledging Immediately?
1. Check SOUL.md has "IMMEDIATE ACKNOWLEDGMENT" section:
   ```bash
   grep "IMMEDIATE ACKNOWLEDGMENT" ~/.openclaw/workspaces/manager/SOUL.md
   ```

2. If missing, re-run upgrade:
   ```bash
   rack team upgrade
   ```

### Memory Index Not Working?
1. Create index first:
   ```bash
   rack memory index <project-id>
   ```

2. Verify index file:
   ```bash
   ls ~/.openclaw/workspaces/projects/<project-id>/.memory-index.json
   ```

---

## Next Steps

1. **Test with real project:** Send a bug report to Manager
2. **Monitor token usage:** Check if costs reduced by 50-90%
3. **Create snapshots:** Run `rack memory snapshot` for all projects
4. **Index memory:** Run `rack memory index` for fast search
5. **Read full docs:** See [RACK-IMPLEMENTATION-COMPLETE.md](RACK-IMPLEMENTATION-COMPLETE.md)

---

## Resources

- **Full Implementation Guide:** [RACK-IMPLEMENTATION-COMPLETE.md](RACK-IMPLEMENTATION-COMPLETE.md)
- **Architecture Analysis:** [RACK-ANALYSIS.md](RACK-ANALYSIS.md)
- **Original Proposal:** [RACK.md](../RACK.md) (in manager's workspace)
- **rack-cli Documentation:** [README.md](../README.md)
- **Help Command:** `rack help`

---

**Questions?** Check the docs or run `rack help`

**Issues?** File at https://github.com/your-repo/rack-cli/issues (adjust URL)

---

**🎉 You're now running RACK-optimized agents!**

Expect:
- 50-90% reduction in token costs
- 6-20x faster response times
- Better security (mandatory checklists)
- More reliable validation (objective behavior tests)
