# Quick Start: DOCKET Architecture

**DOCKET = Roles, Autonomy, Context isolation, Knowledge**

Get started with DOCKET-optimized agents in under 5 minutes.

---

## What is DOCKET?

DOCKET is an architecture for autonomous agent teams that:
- ✅ **Reduces token usage** by isolating each project in its own pod + workspace
- ✅ **Keeps roles clean** — the Lead orchestrates, the Implementer writes code
- ✅ **Enforces security** through a read-only reviewer veto + mandatory checklist
- ✅ **Validates objectively** through behavior-only testing
- ✅ **Eliminates redundancy** through clear per-role responsibilities

---

## Installation

### Create the Org Specialists
```bash
docket install
```

This creates 3 shared org specialists: **manager**, **knowledge**, **security**.

Optionally add the cross-pod **Portfolio Manager** — an advisory, opt-in org agent
that sees fleet metadata (queues, budgets, health) but never code and never dispatches:
```bash
docket install --portfolio
```

### Add a Project Pod
```bash
docket add myapp ~/code/myapp
```

Each project is an isolated **pod**: a **lead** + **implementer** by default. Grow it
when the work earns it:
```bash
docket add myapp --pod full           # + reviewer + tester
docket add myapp --with reviewer      # lean pod + a reviewer
docket pod myapp add reviewer         # add a role later
```

Templates are generated per-pod at `add` time — there is no separate upgrade step.

---

## Verify Installation

```bash
docket list                 # org specialists + pods, with scope and pod
docket pod myapp            # just this project's pod members
docket doctor              # health check + auto-fix
```

**Expected:** `docket list` shows the org specialists (manager, knowledge, security)
and each project's pod members; `docket pod myapp` shows the pod's lead + implementer;
`docket doctor` reports them healthy.

---

## Assign and Run Work — the payoff

A pod isn't just a list of agents — docket can **actually run** its pipeline,
**one real agent turn per hop**:

```
Lead  →  Implementer  →  Reviewer (if present)  →  Tester (if present)
```

Queue a task, see the queue, then dispatch it:

```bash
docket pod myapp delegate "Fix the null-token login crash"   # queue a task
docket pod myapp queue                                        # see it (+ per-task status/cost)
docket pod myapp dispatch                                     # run the pipeline once, now
```

Or let docket drive every pod's queue in the background:

```bash
docket serve --dispatch                                       # autonomous: drain queues each refresh
```

Each hop is a **real, costed LLM turn**, so dispatch is always explicit (`dispatch`)
or opt-in (`serve --dispatch`) — never silent. Before each hop docket checks the pod's
recorded spend against the Lead's budget cap (`docket profile myapp-lead --budget N`);
over budget, the task stays **pending** instead of running. Every hop is traced
(`docket trace`) for a fully auditable run.

> The read-only `docket serve` monitor does **not** dispatch — only `--dispatch` does.

### Next: understand the team model
This is just the entry point. For the full scope/role model, how big a pod should be,
and how isolation works, read **[Agent Teams (Pods)](AGENT-TEAMS.md)** — the heart of docket.

---

## How It Works

### Before DOCKET (One Shared Context)

```
User: "Fix the login bug"
         ↓
A single agent (or a shared pool) carries every project's
history in one context window:
         [Reads 100K tokens of mixed-project conversation]
         [Implements fix]
         [Reviews its own work]
         ↓
TOTAL: ~320K tokens (one bloated context)
PROBLEM: projects contaminate each other; no role separation
```

### After DOCKET (Isolated Pod Workflow)

```
User: "Fix the login bug"  (to the <project> pod's Lead)
         ↓
Lead: [Owns the pod's context/memory + human comms]
      [Reads SNAPSHOT.md for this project — 2K tokens]
      [Decomposes the work, dispatches to the Implementer]
      [NEVER edits code]
         ↓
Implementer: [Runs INSIDE the project workspace]
             [Reads the project files it needs — full read/write]
             [Implements fix]
             [Signals DONE.md]
             ↓
Reviewer (optional): [Read-only veto on the diff]
                     [Runs 6-point checklist]
                     [Approves]
             ↓
Tester (optional): [Behaviour only — runs reproduction steps]
                   [PASS / FAIL]
             ↓
RESULT: each project's work stays in its own pod + workspace,
        so one project's context never bleeds into another's
```

Each pod has its own workspace and per-pod session key, so no worker is
ever shared across projects — that isolation is what keeps each agent's
context (and token count) scoped to a single project.

---

## Key Commands

### Fleet Management
```bash
docket list               # Org specialists + pods (with scope)
docket doctor             # Health check + auto-fix
docket pod <project>      # Inspect a project's pod and its roles
docket team queue         # The org manager's pending task queue
```

### Run a Pod's Work
```bash
docket pod <project> delegate "<task>"   # Queue a task for the pod
docket pod <project> queue               # See the pod's queue + per-task status/cost
docket pod <project> dispatch            # Run the pipeline once (Lead→Implementer→…)
docket serve --dispatch                  # Background: drive every pod's queue
```

### Memory Management
```bash
docket memory snapshot <project-id>   # Create fast-access context
docket memory index <project-id>      # Index memory for search
docket memory search <project-id> <q> # Search indexed memory
docket memory compress <project-id>   # Archive old logs
```

---

## Testing Your Setup

### Test 1: Memory Snapshot
```bash
# Create snapshot for a project
docket memory snapshot <project-name>

# Verify it exists
cat ~/.openclaw/workspaces/projects/<project-name>/SNAPSHOT.md
```

**What you should see:**
- Project metadata (codebase path, stack, model)
- Active tasks (from HEARTBEAT.md)
- Recent activity (last 7 days)
- Architectural decisions (from MEMORY.md)

### Test 2: Run a Task Through the Pod
Queue a task and dispatch it — this exercises the real pipeline end to end:

```bash
docket pod myapp delegate "Fix bug: login crashes when token is null"
docket pod myapp queue          # confirm the task is queued
docket pod myapp dispatch       # run Lead → Implementer → (Reviewer) → (Tester)
```

**Expected workflow (all within one isolated pod, one real agent turn per hop):**
1. **Lead** decomposes the task and hands off (the Lead never edits code).
2. **Implementer** runs *inside* the project workspace, writes the change, signals DONE.
3. **Reviewer** *(if the pod has one)* read-only veto on the diff.
4. **Tester** *(if the pod has one)* behaviour-only PASS / FAIL.
5. **Lead** reports the result; the queue shows per-task status and recorded cost.

Each hop is budget-gated against the Lead's cap and traced (`docket trace`), so a run
is fully auditable. Re-check the queue afterward:

```bash
docket pod myapp queue          # status flips to done (or pending if over budget)
```

> **Alternative — Telegram:** you can also message the pod's **Lead** directly in
> Telegram (`What's the status of myapp?` or `Fix bug: login crashes when token is null`)
> for mobile-first, conversational dispatch. The `delegate`/`dispatch` loop above is the
> scriptable, traced path; Telegram is the same pipeline driven from your phone.

**Why the Lead is fast:** it reads this pod's SNAPSHOT.md (~2K tokens) instead of full
cross-project conversation history.

---

## Pod Roles

A project pod is created by `docket add <project>` and managed with
`docket pod <project>`. By default it is a lean **Lead + Implementer**; add a
Reviewer and Tester with `--pod full` or `--with reviewer,tester`. The org
specialists (`manager`, `knowledge`, `security`) are shared and created once by
`docket install` — they are not part of any single pod.

### Lead
The per-pod orchestrator.
- Owns the pod's context, memory, and human (Telegram) comms
- Reads this pod's SNAPSHOT.md instead of full history
- Decomposes work and dispatches to the pod's workers
- **NEVER edits code**

### Implementer
The agent that actually writes the code.
- Runs **inside the project workspace**, so it has full read/write on the project
- Reads the project files it needs directly (it is in the workspace, not handed a tiny brief)
- Implements the requested change and signals completion via DONE.md
- Replaces the old global "programmer" role — now per-pod and project-scoped

### Reviewer (optional)
- **Read-only veto** on the diff
- **6-point mandatory checklist:**
  1. Prompt injection vectors
  2. Authentication & authorization
  3. Data security (SQL injection, XSS)
  4. Side effects & scope
  5. Completeness (root cause fixed)
  6. Test coverage
- Bad code doesn't proceed

### Tester (optional)
- **Behaviour-only validation** (does NOT read code!)
- Executes reproduction steps objectively
- Binary verdict: PASS or FAIL
- Runs on the cheap model class (sufficient for validation)

---

## Token Savings Examples

> The reduction here is in **tokens**, which is what per-pod context isolation actually controls
> and what you can measure directly. We don't quote dollar savings — your real spend depends on your
> models and current pricing; read it with `docket cost`. See
> [Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

### Example 1: Status Query
**Before (one shared context):**
```
Engineer: "What's the status?"
Agent reads 100K tokens of mixed-project history
```

**After (isolated pod):**
```
Engineer: "What's the status?"
The pod's Lead reads this project's SNAPSHOT.md (2K tokens)
```
**Far fewer tokens** — the Lead only ever reads this pod's snapshot, not a shared
cross-project history.

### Example 2: Simple Change
**Before (one shared context):**
```
Shared history read + implementation = 200K tokens
```

**After (isolated pod):**
```
Implementer works in the project workspace, reading only the files it touches
```
**Far fewer tokens** — the Implementer's context is scoped to one project's
workspace, not the whole fleet's history.

### Example 3: Bug Fix Pipeline
**Before (one shared context):**
```
Investigation + fix + review + test all share one bloated context
```

**After (isolated pod):**
```
Lead → Implementer → Reviewer → Tester, each scoped to this pod's workspace
```
**Fewer tokens, no cross-project contamination** — every role's context stays
inside the pod. Read your actual numbers with `docket cost`.

---

## Common Questions

### Q: Will this break my existing agents?
**A:** No. Templates are generated per-pod by `docket add` and refreshed by
`docket maintain <id> rebuild`:
- Org specialists (manager, knowledge, security) are created once by `docket install`
- Each project pod (lead + implementer, optionally reviewer/tester) is isolated
- Another project's setup never touches your project agents

### Q: How do I assign work to a pod?
**A:** Two ways, same pipeline:
- **CLI (scriptable, traced):** `docket pod <project> delegate "<task>"` then
  `docket pod <project> dispatch` (or `docket serve --dispatch` to run queues in the background).
- **Telegram (mobile-first):** message the pod's Lead directly — conversational dispatch of
  the same Lead → Implementer → (Reviewer) → (Tester) pipeline.

Either way the agents respond faster (each pod processes only its own context) and use fewer
tokens (context isolated per project).

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
docket edit manager    # Opens manager's SOUL.md in $EDITOR
```

Then restart the gateway to apply changes:
```bash
systemctl --user restart openclaw-gateway.service
```

### Q: How do I know it's working?
**A:** Check token usage:
1. Message a pod's Lead with a status query
2. Check OpenClaw logs for token count
3. The Lead should read this pod's SNAPSHOT.md (~2K tokens), not a full cross-project history

---

## Troubleshooting

### Agents Still Using Large Context?
1. **Verify the fleet is healthy:**
   ```bash
   docket list
   docket doctor
   ```

2. **Check SNAPSHOT.md exists:**
   ```bash
   ls ~/.openclaw/workspaces/projects/*/SNAPSHOT.md
   ```

3. **Create snapshot if missing:**
   ```bash
   docket memory snapshot <project-id>
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

2. If missing, regenerate the agent's templates from its metadata:
   ```bash
   docket maintain manager rebuild
   ```

### Memory Index Not Working?
1. Create index first:
   ```bash
   docket memory index <project-id>
   ```

2. Verify index file:
   ```bash
   ls ~/.openclaw/workspaces/projects/<project-id>/.memory-index.json
   ```

---

## Next Steps

1. **Run real work:** `docket pod <project> delegate "<task>"` → `docket pod <project> dispatch`
2. **Understand the team model:** Read **[Agent Teams (Pods)](AGENT-TEAMS.md)** — the heart of docket
3. **Monitor cost:** Check recorded spend with `docket cost`
4. **Create snapshots & index memory:** `docket memory snapshot` / `docket memory index` per project
5. **Go autonomous:** `docket serve --dispatch` to drive every pod's queue in the background

---

## Resources

- **Agent Teams (Pods):** [AGENT-TEAMS.md](AGENT-TEAMS.md) — the canonical team-model reference
- **Full Implementation Guide:** [DOCKET-IMPLEMENTATION-COMPLETE.md](DOCKET-IMPLEMENTATION-COMPLETE.md)
- **Architecture Analysis:** [DOCKET-ANALYSIS.md](DOCKET-ANALYSIS.md)
- **Original Proposal:** [DOCKET.md](../DOCKET.md) (in manager's workspace)
- **docket-cli Documentation:** [README.md](../README.md)
- **Help Command:** `docket help`

---

**Questions?** Check the docs or run `docket help`

**Issues?** File at https://github.com/yielab/docket/issues (adjust URL)

---

**🎉 You're now running DOCKET-optimized agents!**

Typical results (workload-dependent):
- Lower token usage from per-pod context isolation (measure with `docket cost`)
- Clean role separation (Lead orchestrates, Implementer codes)
- Better security (read-only reviewer veto + mandatory checklist)
- More reliable validation (objective behavior tests)
