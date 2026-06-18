# Smart Model Routing & Context Management

## Concept

**NO manual model selection.** Every agent uses intelligent routing:

1. **Task Complexity Analysis** → Automatic model selection
2. **Smart Context Management** → Only necessary context included
3. **Rolling Memory** → Conversation never exceeds optimal size
4. **Cost Optimization** → 90% of tasks use cheap models automatically

---

## Model Routing Rules

### Economy tier — 90% of tasks
- ✅ Simple Q&A and clarifications
- ✅ Code review (reading existing code)
- ✅ Running tests
- ✅ Reading documentation
- ✅ Git operations
- ✅ File navigation
- ✅ Error triage
- ✅ Status updates
- ✅ Most debugging

### Standard tier — 9% of tasks
- ✅ Writing new code (functions, classes)
- ✅ Refactoring existing code
- ✅ Complex debugging (multi-file)
- ✅ API design
- ✅ Database schema design
- ✅ Configuration changes

### Premium tier — 1% of tasks
- ✅ Architecture decisions
- ✅ Security-critical code
- ✅ Performance optimization (algorithms)
- ✅ Complex system design
- ✅ Critical bug fixes in production

---

## Detection Logic (Built into Agent SOUL.md)

```markdown
## Smart Model Selection (Automatic)

Before every response, I classify the task:

### Complexity Signals

**CHEAP (economy tier):**
- User asks "what is...", "where is...", "show me..."
- Read-only operations
- Single-file changes
- Test execution
- No architectural decisions

**STANDARD (standard tier):**
- "Write a function to..."
- "Refactor this to..."
- "Fix the bug in..."
- Multi-file changes
- Design decisions

**PREMIUM (premium tier):**
- "Design a system for..."
- "Optimize performance of..."
- "Security review of..."
- "Critical production issue..."
- System-wide changes

### Override Detection

If I start with economy tier and realize complexity is higher:
- Switch to standard tier mid-conversation
- Log: "Upgrading to standard tier for [reason]"

If task is simpler than expected:
- Downgrade to economy tier
- Log: "Using economy tier (sufficient for this task)"
```

---

## Smart Context Management

### Problem
OpenClaw caches entire conversation → 258 turns = 21M tokens = $6.35

### Solution: Rolling Window + Smart Compression

**Agent reads only:**
1. **SOUL.md** (identity, rules) — ~1K tokens — **ALWAYS cached**
2. **SNAPSHOT.md** (current project state) — ~2K tokens — **ALWAYS cached**
3. **Last 10 turns** (recent conversation) — ~5K tokens — **NOT cached, rolling**
4. **Active task context** (current file being edited) — ~3K tokens — **NOT cached**

**Total context: ~11K tokens maximum** (vs current 82K per turn!)

### Context Lifecycle

```
Turn 1-10:   Keep full history
Turn 11:     Compress turns 1-5 → MEMORY.md
Turn 12-20:  Keep turns 11-20
Turn 21:     Compress turns 11-15 → MEMORY.md
...
Turn 50:     Suggest: "Should we start fresh? I'll save summary to MEMORY.md"
```

---

## Implementation Strategy

### Phase 1: OpenClaw-Level (Requires OpenClaw Config)

**Check if OpenClaw supports model routing:**

```bash
openclaw config get models.routing
```

**If supported, configure:**

```json
{
  "models": {
    "routing": {
      "enabled": true,
      "default": "<economy-model>",  // set by docket models
      "rules": [
        {
          "pattern": "write|implement|create|build|refactor",
          "model": "<standard-model>"   // set by docket models
        },
        {
          "pattern": "architecture|design system|optimize|security audit",
          "model": "<premium-model>"    // set by docket models
        }
      ]
    }
  }
}
```

### Phase 2: Agent-Level (Works Today)

**Embed routing logic in SOUL.md:**

Each agent gets a "Task Classifier" section that self-selects model via delegation:

```markdown
## Task Classification (Self-Routing)

I analyze every request and choose the right specialist:

1. **Simple tasks** → Delegate to knowledge agent (economy tier)
   - "What is X?"
   - "Where is Y?"
   - "Show me Z"

2. **Standard tasks** → Delegate to programmer (standard tier)
   - "Write function..."
   - "Fix bug..."
   - "Refactor..."

3. **Complex tasks** → Delegate to manager (premium tier)
   - "Design system..."
   - "Architect solution..."
   - "Security review..."
```

### Phase 3: Context Management (Agent SOUL.md)

**Add to every agent's SOUL.md:**

```markdown
## Context Management (Critical!)

### What I Read Each Turn

1. **SOUL.md** (my identity) - cached, ~1K
2. **SNAPSHOT.md** (current project state) - cached, ~2K
3. **Last 10 messages** (recent context) - NOT cached, ~5K
4. **Current file** (if editing) - NOT cached, ~3K

**Maximum context: 11K tokens**

### What I DON'T Read

❌ Full conversation history (prevents 258-turn bloat)
❌ Entire codebase (use targeted file reads)
❌ Old memory logs (use SNAPSHOT.md instead)

### Compression Protocol

After every 10 turns:
1. Summarize turns 1-5 into MEMORY.md
2. Delete turns 1-5 from active context
3. Keep only last 10 turns in memory

After 50 turns:
1. Create comprehensive SNAPSHOT.md
2. Suggest session reset: "We've had 50 turns. Should I save context and start fresh?"
```

---

## Example: Smart Routing in Action

### Scenario: Bug Fix Workflow

**Turn 1 (User):** "The login page isn't working"

**Agent (economy tier):** "Let me check the logs..."
- **Model:** economy tier
- **Reason:** Investigation is cheap

**Turn 2 (Agent):** "Found error: JWT validation failing. Need to fix auth middleware."

**Turn 3 (Agent self-upgrades):** "Upgrading to standard tier to implement fix..."
- **Model:** standard tier
- **Reason:** Writing code requires standard model

**Turn 4 (Agent):** "Fix complete. Running tests with economy tier..."
- **Model:** economy tier
- **Reason:** Test execution is cheap

**Result:**
- 2 turns economy: ~cents
- 1 turn standard: ~few cents
- **Total: fraction of a dollar** (vs many times more if all standard)

---

## Cost Comparison

### Before (Manual Profiles)
- All tasks use standard tier: higher cost
- 258 turns × ~100K context = **$28.17**

### After (Smart Routing + Context Management)
- 90% economy tier: lowest cost
- 9% standard tier: moderate cost
- 1% premium tier: highest cost
- Max 50 turns × 11K context = **$1.50**

**Savings: 95%**

---

## Implementation Files Needed

1. **`lib/helpers/smart-routing.sh`** — Model selection logic
2. **`lib/helpers/context-manager.sh`** — Rolling window, compression
3. **`lib/templates/soul-smart.md`** — Template with routing logic
4. **`lib/commands/upgrade-smart.sh`** — Upgrade agents to smart routing

---

## Next Steps

1. **Detect OpenClaw Capabilities**
   - Check if native routing exists
   - Check if context limits are configurable

2. **Implement Agent-Level Routing**
   - Update SOUL.md templates with classifier
   - Add delegation-based routing

3. **Implement Context Management**
   - Rolling 10-turn window
   - Auto-compression after 10 turns
   - Session reset at 50 turns

4. **Test & Validate**
   - Run test conversation with a project agent
   - Verify context stays < 15K tokens
   - Verify 90% of turns use economy tier

---

**Goal:** Zero manual model selection. Agent automatically uses:

- Economy tier for 90% of tasks
- Standard tier when needed
- Premium tier rarely
- Context never exceeds 15K tokens
- Cost drops 90-95%
