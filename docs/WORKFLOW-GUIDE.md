# Complete Workflow Guide: Project Agents + Specialists + Engineer

**Date:** 2026-03-06
**Status:** Production Guide

---

## The Three Actors

### 1. **Engineer (You)** 👤
The main user who:
- Creates projects
- Assigns tasks via Telegram
- Reviews and commits code
- Makes architectural decisions
- Approves HITL gates

### 2. **Project Agents** 📁
One per project/codebase (created with `rack add`):
- **Examples:** `mywebsite`, `mobile-app`, `myshop`
- **Role:** Project coordinator for ONE specific codebase
- **Telegram:** Each has own dedicated group
- **Works on:** Single project only (session-scoped)
- **Delegates to:** Specialist agents for implementation

### 3. **Specialist Agents** 🛠️
Shared team (created with `rack install`):
- **manager** - Orchestrates cross-project work
- **programmer** - Implements code
- **reviewer** - Reviews + security checks
- **tester** - Runs tests + validation
- **knowledge** - Memory distillation
- **security** - Deep security audits

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    ENGINEER (You)                           │
│  • Sends tasks via Telegram                                 │
│  • Reviews code changes                                     │
│  • Commits to git                                           │
│  • Approves HITL gates                                      │
└────────────┬────────────────────────────────────────────────┘
             │
             ├─► Project Agent: mywebsite (Telegram group)
             │   └─► Delegates to specialists
             │
             ├─► Project Agent: mobile-app (Telegram group)
             │   └─► Delegates to specialists
             │
             └─► Manager Agent (Telegram group)
                 └─► Coordinates specialists directly

┌─────────────────────────────────────────────────────────────┐
│              SPECIALIST AGENTS (Shared Team)                │
├─────────────────────────────────────────────────────────────┤
│  programmer  │  reviewer  │  tester  │  knowledge  │  security│
│  (Haiku/Son) │  (Sonnet)  │ (Haiku)  │  (Haiku)    │ (Sonnet) │
└─────────────────────────────────────────────────────────────┘
```

---

## Two Workflow Models

### Model A: Direct to Project Agent (Recommended for Most Tasks)
**Use when:** Working on a specific project/codebase

```
Engineer → Project Agent → Specialists → Done
```

### Model B: Via Manager Agent (Recommended for Multi-Project)
**Use when:** Coordinating across multiple projects

```
Engineer → Manager → Project Agent(s) → Specialists → Done
```

---

## Model A: Direct to Project Agent (Detailed)

### Setup
```bash
# Create project agent
rack add
  Name: mywebsite
  Type: repo
  Codebase: ~/Sites/mywebsite
  Stack: Next.js
  Model: standard (Sonnet)

# Wire to Telegram
rack wire mywebsite
  → Create Telegram group: "MyWebsite Project"
  → Add your bot
  → Run command to link
```

### Workflow: Feature Request

**Step 1: Engineer sends task (Telegram)**
```
Telegram group: "MyWebsite Project"

Engineer:
Add a dark mode toggle to the settings page
```

**Step 2: Project Agent acknowledges**
```
Project Agent (mywebsite):
✓ Got it - adding dark mode toggle
→ Analyzing current settings page...
👥 Will delegate: programmer, reviewer
⏱ ETA: ~10 minutes
```

**Step 3: Project Agent creates brief**
```
[Internal - Project Agent reads:]
- SNAPSHOT.md (project state)
- ~/Sites/mywebsite/src/pages/settings.tsx (current code)
- MEMORY.md (past decisions)

[Project Agent creates compressed brief:]
TASK: Add dark mode toggle
FILE: src/pages/settings.tsx
COMPONENT: SettingsPanel
CHANGE: Add toggle button + useTheme hook
ACCEPTANCE:
  • Toggle visible in settings
  • Theme persists across sessions
  • No layout breaks

[Saves to: memory/tasks/T001/BRIEF.md]
```

**Step 4: Project Agent delegates to programmer**
```
[Via Telegram to "Programmer Team" group OR via memory file]

Project Agent → Programmer:
Read brief: memory/tasks/T001/BRIEF.md
Project: mywebsite
Codebase: ~/Sites/mywebsite
Signal completion: memory/tasks/T001/DONE.md
```

**Step 5: Programmer implements**
```
Programmer:
✓ Got it - implementing dark mode toggle
→ Reading settings.tsx...
[30s] Writing toggle component...
[60s] Adding theme context...
[90s] Testing in browser...

✓ Done - dark mode toggle implemented
→ Files changed:
  • src/pages/settings.tsx
  • src/contexts/ThemeContext.tsx
  • src/styles/themes.css

→ memory/tasks/T001/DONE.md written
```

**Step 6: Project Agent delegates to reviewer**
```
Project Agent → Reviewer:
Review task: T001
Read: memory/tasks/T001/DONE.md
Check: Security, correctness, acceptance criteria
```

**Step 7: Reviewer audits**
```
Reviewer:
✓ Got it - reviewing dark mode toggle
→ Running security checklist...
[20%] Checking prompt injection vectors... OK
[40%] Checking XSS risks... OK
[60%] Verifying acceptance criteria... OK
[80%] Checking test coverage... WARNING (no tests)
[100%] Done

✓ APPROVED (with note: add tests)
→ memory/tasks/T001/APPROVED.md

Suggestion: Add unit tests for ThemeContext
(Non-blocking - can be done later)
```

**Step 8: Project Agent delegates to tester**
```
Project Agent → Tester:
Validate task: T001
Reproduction steps:
  1. Navigate to /settings
  2. Click dark mode toggle
  3. Verify theme changes
  4. Reload page
  5. Verify theme persists

DO NOT read implementation code!
```

**Step 9: Tester validates**
```
Tester:
✓ Got it - validating dark mode toggle
→ Running browser tests...
[25%] Opening /settings... OK
[50%] Clicking toggle... Theme changed ✓
[75%] Reloading page... Theme persisted ✓
[100%] Done

✓ VALIDATION PASSED
→ All acceptance criteria met
→ memory/tasks/T001/VALIDATED.md
```

**Step 10: Project Agent reports to Engineer**
```
Project Agent → Engineer (Telegram):
✅ Dark mode toggle complete!

**Changes:**
• src/pages/settings.tsx - Added toggle button
• src/contexts/ThemeContext.tsx - Theme state management
• src/styles/themes.css - Dark theme styles

**Pipeline:**
• Programmer: Implemented ✓
• Reviewer: Approved ✓ (suggested adding tests)
• Tester: Validated ✓

**Next Steps:**
1. Review changes: cd ~/Sites/mywebsite
2. Test locally: npm run dev
3. Commit: git commit -m "Add dark mode toggle"

**Evidence:**
memory/tasks/T001/ contains full task history
```

**Step 11: Engineer reviews and commits**
```bash
# Engineer (in terminal):
cd ~/Sites/mywebsite
git diff  # Review changes

# If looks good:
git add src/pages/settings.tsx src/contexts/ThemeContext.tsx src/styles/themes.css
git commit -m "Add dark mode toggle to settings

- Add ThemeContext for state management
- Add toggle button in settings panel
- Theme persists across sessions


"

git push
```

**Step 12: Project Agent updates memory**
```
[Automatic after engineer commits]

Project Agent writes to memory/2026-03-06.md:
## [17:45] Dark mode toggle - DEPLOYED

**Task:** Add dark mode toggle
**Status:** ✅ Committed and pushed
**Commit:** abc123f
**Team:** programmer, reviewer, tester
**Time:** 12 minutes (brief → deployed)
**Cost:** ~8K tokens ($0.024)
```

---

## Model B: Via Manager Agent (Detailed)

### Setup
```bash
# Manager already exists (created by rack install)
# Wire to Telegram
rack wire manager
  → Create Telegram group: "Manager"
  → Add your bot
  → Run command to link
```

### Workflow: Cross-Project Task

**Use case:** "Implement authentication across all projects"

**Step 1: Engineer sends to Manager**
```
Telegram group: "Manager"

Engineer:
Implement OAuth2 authentication for mywebsite and mobile-app projects
Use the same auth service for both
```

**Step 2: Manager analyzes**
```
Manager:
✓ Got it - cross-project auth implementation
→ Analyzing affected projects...

[Manager reads:]
- ~/.openclaw/workspaces/projects/mywebsite/SNAPSHOT.md
- ~/.openclaw/workspaces/projects/mobile-app/SNAPSHOT.md

[Manager identifies:]
Projects: mywebsite (Next.js), mobile-app (React Native)
Scope: OAuth2 + shared auth service
HITL needed: Architecture decision (which auth provider?)

⚠️ Architecture Decision Required

**Options:**
A) Auth0 (easiest, $25/month, 7K users free)
B) Supabase Auth (open source, self-host, complex setup)
C) Custom OAuth2 (full control, most work)

**Recommendation:** A (Auth0)

Please approve before proceeding.
```

**Step 3: Engineer approves**
```
Engineer (in Telegram):
Approved - use Auth0
```

**Step 4: Manager creates task breakdown**
```
Manager:
✓ Approved - proceeding with Auth0

**Task Breakdown:**
T001: Set up Auth0 tenant + configure apps
T002: Implement auth in mywebsite (Next.js)
T003: Implement auth in mobile-app (React Native)
T004: Create shared auth library (npm package)
T005: Test end-to-end (both apps)

⏱ Total ETA: ~2 hours

Starting with T001...
```

**Step 5: Manager delegates to Project Agents**
```
Manager → mywebsite Project Agent:
Task: T002 - Implement Auth0 in Next.js
Brief: memory/tasks/T002/BRIEF.md
Dependencies: T001 (Auth0 setup) must complete first
Codebase: ~/Sites/mywebsite

---

Manager → mobile-app Project Agent:
Task: T003 - Implement Auth0 in React Native
Brief: memory/tasks/T003/BRIEF.md
Dependencies: T001, T002 (learn from mywebsite implementation)
Codebase: ~/Sites/mobile-app
```

**Step 6: Project Agents delegate to Specialists**
```
[Each Project Agent follows Model A workflow internally]

mywebsite Agent → programmer → reviewer → tester → done
mobile-app Agent → programmer → reviewer → tester → done
```

**Step 7: Manager monitors progress**
```
Manager (updates every 60s):
[15 min] T001 complete - Auth0 configured ✓
[30 min] T002 in progress - programmer implementing...
[45 min] T002 complete - validated ✓
[60 min] T003 in progress - mobile-app auth...
[90 min] T003 complete - validated ✓
[100 min] T004 starting - shared library...
[120 min] All tasks complete ✓
```

**Step 8: Manager reports final status**
```
Manager → Engineer:
✅ OAuth2 authentication complete!

**Completed Tasks:**
• T001: Auth0 tenant configured
• T002: mywebsite - Auth0 integration ✓
• T003: mobile-app - Auth0 integration ✓
• T004: Shared auth library created
• T005: End-to-end tests passing

**Projects Modified:**
• mywebsite: 8 files changed
• mobile-app: 6 files changed
• auth-lib: New package created

**Next Steps:**
1. Review mywebsite: cd ~/Sites/mywebsite
2. Review mobile-app: cd ~/Sites/mobile-app
3. Test login flow in both apps
4. Commit both projects

**Total Time:** 2h 3min
**Total Cost:** ~180K tokens ($0.54)
```

---

## When to Use Which Model?

### Use Model A (Direct to Project Agent)
✅ **Single project tasks:**
- "Add feature X to mywebsite"
- "Fix bug Y in mobile-app"
- "Refactor component Z"
- "Update dependencies"

✅ **Quick iterations:**
- "Change button color"
- "Update copy on homepage"
- "Add logging to API"

✅ **Project-specific work:**
- Anything scoped to one codebase

**Why:** Faster (no manager overhead), simpler communication

### Use Model B (Via Manager)
✅ **Cross-project coordination:**
- "Implement auth across all projects"
- "Update API contracts in backend + frontend"
- "Standardize error handling"

✅ **Strategic planning:**
- "Plan Q1 roadmap"
- "Audit security across all projects"
- "Generate architecture diagrams"

✅ **Resource allocation:**
- "Prioritize which bug to fix first"
- "Estimate effort for feature X"

**Why:** Manager has cross-project context, can coordinate specialists

---

## Project Agent Configuration

### What Makes a Project Agent?

**Identity (SOUL.md):**
```markdown
## Identity
You are the autonomous agent for **MyWebsite**.
You know this project deeply.
You do not discuss or act on other projects.

**Session Key:** `agent:mywebsite:main`
```

**Scope (Session Key):**
- `agent:mywebsite:main` - Isolates this agent to mywebsite only
- Cannot access other projects' memory/files
- Change with: `rack scope mywebsite set mywebsite-staging`

**Codebase Path:**
- Hardcoded in SOUL.md: `~/Sites/mywebsite`
- Agent only operates within this directory
- Cannot modify files outside this path

**Delegation Rules (AGENTS.md):**
```markdown
## Delegation
| Task              | Delegate to  |
|-------------------|--------------|
| Code              | programmer   |
| Review            | reviewer     |
| Tests             | tester       |
| Memory/patterns   | knowledge    |
| Risky actions     | security     |
```

**Memory (Project-Specific):**
```
~/.openclaw/workspaces/projects/mywebsite/
├── SOUL.md              # Identity + scope
├── AGENTS.md            # Delegation rules
├── HEARTBEAT.md         # Active tasks
├── MEMORY.md            # Architectural decisions
├── SNAPSHOT.md          # Fast-access context
├── memory/
│   ├── 2026-03-06.md   # Today's log
│   ├── 2026-03-05.md   # Yesterday
│   └── tasks/
│       └── T001/       # Task coordination
│           ├── BRIEF.md
│           ├── DONE.md
│           ├── APPROVED.md
│           └── VALIDATED.md
└── workflows/          # Lobster pipelines (optional)
```

---

## Specialist Agent Behavior

### Context Isolation (Critical!)

**Specialists are session-scoped:**
```
When programmer receives:
  "Project: mywebsite"
  "Brief: memory/tasks/T001/BRIEF.md"

Programmer ONLY:
  • Reads brief file
  • Reads files in ~/Sites/mywebsite/
  • Writes to ~/Sites/mywebsite/
  • Cannot access other projects
```

**Why this matters:**
- Prevents context contamination
- Ensures changes stay scoped
- Reduces token usage (no irrelevant memory)

### Delegation Format (RACK-Optimized)

**Before RACK (wasteful):**
```
Project Agent → Programmer:
[Sends full conversation history: 100K tokens]
[Sends investigation notes: 20K tokens]
[Sends brief: 2K tokens]
Total: 122K tokens
```

**After RACK (efficient):**
```
Project Agent → Programmer:
Read brief: memory/tasks/T001/BRIEF.md

[Brief contains only:]
TASK: Add dark mode
FILE: src/settings.tsx
LINE: 42
CHANGE: Add toggle button
ACCEPTANCE: Toggle works, theme persists

Total: 500 tokens
```

**Token savings: 99.6%!**

---

## Engineer's Daily Workflow (Recommended)

### Morning Routine
```bash
# Check all projects
rack list

# Check for stalled tasks
rack team status

# Create snapshots (if not recent)
for project in mywebsite mobile-app; do
  rack memory snapshot $project
done
```

### Assigning Work

**Option 1: Direct to project (most common)**
```
Telegram → "MyWebsite Project"
Message: "Add contact form to homepage"
```

**Option 2: Via Manager (multi-project)**
```
Telegram → "Manager"
Message: "Implement contact forms in all projects"
```

### Monitoring Progress

**Via Telegram:**
- Project agents send updates every 60s
- Final notification when done

**Via CLI:**
```bash
# Check recent activity
rack logs mywebsite

# Check task status
cat ~/.openclaw/workspaces/projects/mywebsite/memory/tasks/T001/STATUS.md
```

### Reviewing Changes

**After notification:**
```bash
# Navigate to project
cd ~/Sites/mywebsite

# Review diff
git diff

# Review task evidence
cat ~/.openclaw/workspaces/projects/mywebsite/memory/tasks/T001/DONE.md
cat ~/.openclaw/workspaces/projects/mywebsite/memory/tasks/T001/APPROVED.md
cat ~/.openclaw/workspaces/projects/mywebsite/memory/tasks/T001/VALIDATED.md

# If approved:
git add .
git commit -m "Feature: Contact form


"
git push
```

### End of Day

```bash
# Compress old memory (optional)
rack memory compress mywebsite

# Check cost
rack cost

# Check for any alerts
rack doctor
```

---

## Advanced Patterns

### Pattern 1: Feature Branches (Manual)

```bash
# Engineer creates branch
cd ~/Sites/mywebsite
git checkout -b feature/dark-mode

# Tell Project Agent
Telegram → "MyWebsite Project"
Message: "Work on branch feature/dark-mode for dark mode implementation"

# Agent works on that branch
# When done, engineer reviews PR
git push origin feature/dark-mode
gh pr create
```

### Pattern 2: Parallel Tasks

```bash
# Send multiple tasks to same project
Telegram → "MyWebsite Project"
Message: "Task A: Add contact form
Task B: Update footer
Task C: Fix navigation bug

Please work on these in parallel where possible"

# Project Agent creates multiple task IDs
# Delegates to programmer (may use same or different instances)
```

### Pattern 3: HITL Gates

**Trigger:** Architectural decision needed

```
Project Agent → Engineer:
⚠️ HITL Required

**Decision:** Should we use REST or GraphQL for new API?

**Context:**
- Current: REST
- Proposed: GraphQL (better for mobile app)
- Impact: Requires refactoring 12 endpoints

**Options:**
A) Keep REST (less work, familiar)
B) Switch to GraphQL (better DX, more setup)

Please approve A or B to proceed.
```

**Engineer responds:**
```
Approved: B (GraphQL)
Reason: Mobile team requested it
```

**Project Agent continues:**
```
✓ Approved - proceeding with GraphQL
→ Creating task breakdown...
```

---

## Cost & Token Management

### Per-Task Estimates

**Simple Task (CSS change):**
```
Project Agent: 2K tokens (read SNAPSHOT, create brief)
Programmer: 2K tokens (Haiku - implement)
Reviewer: 1K tokens (quick check)
Tester: 1K tokens (Haiku - validate)
---
Total: ~6K tokens = $0.005 (half a cent!)
Time: 2 minutes
```

**Medium Task (feature):**
```
Project Agent: 5K tokens
Programmer: 20K tokens (Sonnet - complex logic)
Reviewer: 5K tokens (Sonnet - thorough)
Tester: 3K tokens (Haiku - tests)
---
Total: ~33K tokens = $0.10 (ten cents)
Time: 10 minutes
```

**Complex Task (refactor):**
```
Project Agent: 10K tokens
Programmer: 50K tokens (Sonnet - multi-file)
Reviewer: 10K tokens (Sonnet - security critical)
Tester: 5K tokens (extensive tests)
---
Total: ~75K tokens = $0.23 (twenty-three cents)
Time: 20 minutes
```

### Monthly Budget Estimate

**Typical project (active development):**
```
Simple tasks: 30/month × $0.005 = $0.15
Medium tasks: 15/month × $0.10 = $1.50
Complex tasks: 5/month × $0.23 = $1.15
Queries/status: 50/month × $0.006 = $0.30
---
Total per project: ~$3.10/month
```

**For 3 projects:**
```
3 × $3.10 = $9.30/month
Manager overhead: +$2/month
---
Total: ~$11.30/month
```

**Compare to manual:**
- 1 engineer hour = $50-150 (freelance rate)
- Rack saves ~10-20 hours/month = $500-3000/month
- **ROI: 44x - 265x**

---

## Troubleshooting

### Project Agent Not Responding?

1. **Check if agent exists:**
   ```bash
   rack list
   ```

2. **Check Telegram binding:**
   ```bash
   rack list  # Shows wire status
   ```

3. **Re-wire if needed:**
   ```bash
   rack wire mywebsite
   ```

4. **Check gateway:**
   ```bash
   systemctl --user status openclaw-gateway.service
   ```

### Project Agent Working on Wrong Project?

1. **Check session key:**
   ```bash
   rack scope mywebsite show
   ```

2. **Reset if needed:**
   ```bash
   rack scope mywebsite reset
   ```

3. **Verify SOUL.md:**
   ```bash
   grep "Session Key" ~/.openclaw/workspaces/projects/mywebsite/SOUL.md
   ```

### Specialists Not Receiving Tasks?

1. **Check if specialists exist:**
   ```bash
   rack team check
   ```

2. **Verify RACK optimization:**
   ```bash
   rack team status
   ```

3. **Check delegation logic in Project Agent:**
   ```bash
   grep "Delegation" ~/.openclaw/workspaces/projects/mywebsite/AGENTS.md
   ```

4. **Check task files:**
   ```bash
   ls ~/.openclaw/workspaces/projects/mywebsite/memory/tasks/
   ```

---

## Summary

**Project Agents:**
- One per project/codebase
- Coordinates work for that project only
- Delegates to specialists
- Reports to engineer

**Specialists:**
- Shared across all projects
- Receive compressed briefs
- Work in isolated sessions
- Signal completion via memory files

**Engineer:**
- Assigns tasks (Telegram or CLI)
- Reviews changes (git diff)
- Commits code (git commit)
- Approves HITL gates

**Workflow:**
```
Engineer → Project Agent → Specialists → Done → Engineer Reviews → Commit
```

**Or:**
```
Engineer → Manager → Project Agents → Specialists → Done → Engineer Reviews → Commit
```

**Key Benefits:**
- ✅ 50-98% token reduction (RACK optimization)
- ✅ 6-20x faster responses (SNAPSHOT.md, compression)
- ✅ Autonomous execution (minimal engineer intervention)
- ✅ Security-first (mandatory 6-point checklist)
- ✅ Cost-effective ($3-11/month for active development)

---

**Next:** Read [QUICK-START-RACK.md](QUICK-START-RACK.md) to test your first workflow!
