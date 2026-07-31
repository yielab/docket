# Security: Layered & Convention-Based

**Philosophy:** Security comes from layered defaults — agent instructions, a reviewer role, and human git review — so that the common cases are covered without extra commands.

> **Status / honesty note.** docket layers two things: instruction-level agent constraints (SOUL.md, a reviewer role, human git review) plus **enforced tool-approval gates, which are ON by default for new installs** (`docket install`, unless you pass `--no-gates`). When gates are on, a dangerous operation not on the curated allowlist (`rm`, `dd`, `docker`, `systemctl`, ...) is stopped by the **OpenClaw daemon's own** exec-approval prompt, delivered to the agent's chat session and answered there with the daemon's own `/approve <id>`; if nobody answers, the daemon denies it by itself (`askFallback: deny`). `git`/`npm` stay on the allowlist for usability, so a `git push` isn't gated by this layer alone — see "High-Risk Actions" below.
>
> Separately, **docket keeps its own approval store** for things docket itself gates — a pod-dispatch hop held on a `requireApprovalRoles`/pipeline `approval` step, or a task a guardrail policy flagged at enqueue (see "Guardrail Policies" below). That one *is* answerable headlessly, from any shell or CI job: `docket approve`/`docket deny`, or `docket serve`'s `POST /approvals/<token>`. Both genuinely resume or kill the task they gated, both write an audit-log entry, and an unanswered one fail-closes to denied after a timeout (while `docket serve` is running to sweep it).
>
> **These two approval systems are not connected.** `docket approve`/`docket deny` cannot answer a live daemon exec-approval prompt — there's no bridge today (investigated and found not practically buildable against the current OpenClaw daemon; see the spec). Answering the daemon's own prompt in Telegram works, but writes nothing to docket's audit log, because docket never sees it happen. Docker **workspace isolation** (`docket gates isolate on`) is a separate, still-**opt-in** layer on top. See [`specs/functional/security-gates.spec.md`](../specs/functional/security-gates.spec.md) (Status: Implemented, on by default). If you ran `docket install --no-gates`, treat the constraints below as strong defaults, not guarantees — re-enable anytime with `docket gates enable`.

---

## How Security Works (Layered)

### 1. Agents Are Instructed Not to Do Dangerous Things

**Every agent SOUL.md includes:**
```markdown
## Safety Constraints (NEVER Violate)
1. NEVER commit to git
2. NEVER push to remote
3. NEVER delete files without explicit instruction
4. NEVER run production commands
5. NEVER store secrets
```

These are **prompt-level constraints**: agents are instructed to follow them. On top of that, a fresh `docket install` also turns on the enforced tool-approval gates layer by default, so non-allowlisted dangerous operations (`rm`, `dd`, `docker`, `systemctl`, ...) require the daemon's own approval prompt regardless of what the prompt says — see the status note above for exactly who answers that prompt, and for the `git`/`npm` carve-out. If you opted out at install (`--no-gates`), turn it on anytime with `docket gates enable`.

### 2. Reviewer Checks Everything (Automatic)

**Reviewer runs 6-point checklist on EVERY change:**

1. ✓ No prompt injection in comments
2. ✓ No hardcoded secrets
3. ✓ No SQL injection / XSS
4. ✓ Auth checks present
5. ✓ No dangerous operations (rm -rf, git push, etc.)
6. ✓ Tests cover critical paths

**If ANY fail → REJECTED automatically**

That's the entire security model. Simple.

---

## What Engineers Do

### Before Starting Work
**Nothing.** Security is built-in.

### During Agent Work
**Nothing.** Reviewer checks automatically.

### Before Committing
```bash
# 1. Review the diff
git diff

# 2. If looks good, commit
git commit -m "Feature: description"

# That's it.
```

### Optional: Manual Scan (if suspicious)
```bash
# Only if you suspect injection, run:
grep -rn "ignore previous" ~/Sites/myproject/src/

# That's it. No complex tools needed.
```

---

## How Each Layer Works

### Layer 1: Prevention (Agent SOUL.md)
- Agents have constraints written into their identity prompt
- Instructed not to commit, push, or delete (prompt-level, not enforced)
- **No code — just instructions**

### Layer 2: Detection (Reviewer Checklist)
- 6-point checklist runs automatically
- Rejects bad code immediately
- **No manual scanning needed**

### Layer 3: Engineer Review (Git Diff)
- Engineer reviews diff before commit
- Final human check
- **Simple git diff, that's it**

### Layer 4: Guardrail Policies (Automatic, on real dispatch tasks)
- A small set of installed policies (`docket policies`) scan text at two points in docket's own
  pod-dispatch pipeline — not a raw Telegram chat, only work that goes through
  `docket pod <p> delegate`/`dispatch`:
  - **Once**, when a task is delegated — before it's even added to the queue.
  - **On every hop's real reply**, as the pipeline runs.
- A match can `allow`/`warn` (just logged), `redact` (scrub it before it's stored), `block`
  (reject the task, or stop the pipeline where it tripped), or — enqueue-time only —
  `require_approval` (routes into the approval store above).
- `docket policies list` to see what's installed, `docket policies test <hook> <role> "<text>"`
  to dry-run one without touching anything real.

### Layer 5: High-Risk Action Classes (Automatic, narrow, and honestly incomplete)
- A small, built-in list of especially consequential command patterns: money-movement,
  prod-deploy, secret-access (`docket gates classes` prints all of them).
- Wired onto exactly two things docket itself runs: a pod's `verifyCmd` refuses outright if it
  matches (the command never even starts), and a hop's real reply is scanned for one on the way
  through the pipeline (flagged, not blocked, by itself).
- **What this does NOT do:** stop a live agent's own tool call. The daemon's own exec-approval
  gate (top of this doc) only ever looks at the *binary path* — `git`, `npm`, ... — never its
  arguments, so it cannot tell `git push origin production` apart from `git status`. A live agent
  can still run either. Per-argument enforcement isn't available from the daemon today; this is a
  documented gap, not a bug docket is hiding.

---

## Testing Security (Simple)

### Test 1: Can Agent Commit?
```bash
# Check the implementer's constraints (replace "myapp" with your project name)
grep "NEVER commit" ~/.openclaw/workspaces/projects/myapp-implementer/SOUL.md

# Should find: "NEVER commit to git"
```

### Test 2: Does Reviewer Check Security?
```bash
# Check the reviewer's checklist (replace "myapp" with your project name)
grep "prompt injection\|hardcoded secret" ~/.openclaw/workspaces/projects/myapp-reviewer/SOUL.md

# Should find: 6-point checklist
```

### Test 3: Are There Agent Commits?
```bash
cd ~/Sites/myproject
git log --since="30 days ago" --format="%an"  # review automated/agent commit authors

# Should return: NOTHING (agents don't commit!)
```

**If all 3 pass → Security works. Done.**

---

## What If Something Goes Wrong?

### Prompt Injection Found
```bash
# Reviewer will catch it and REJECT
# If somehow missed, search manually:
grep -rn "ignore previous\|you are now" ~/Sites/myproject/src/
```

### Agent Tries to Commit
The agent is instructed never to commit (SOUL.md), and the reviewer plus your git-diff review
are the backstops. Note: `git` stays on the gates' curated allowlist (it's used constantly for
benign work), so `git push` does **not** by itself trigger an approval prompt even with gates
enabled — the prompt-level instruction and your git-diff review are what actually stop it today.
Truly destructive bins (`rm`, `dd`, `docker`, `systemctl`, ...) are gated on a default install
(see the status note above).

### Hardcoded Secret Found
```bash
# Reviewer will catch it and REJECT
# If missed, search manually:
grep -rn "api_key.*=.*['\"][a-zA-Z0-9]{20,}" ~/Sites/myproject/src/
```

---

## The Audit Log (`docket audit`)

Every gate flip, approval grant/deny, key/model/profile/pod change docket makes writes one line
to `~/.openclaw/audit.log` — who, what, when. Secret **values** are never written, only names
(a key's NAME, a model id, an agent id).

```bash
docket audit          # last 20 changes
docket audit 50       # last 50
docket audit verify   # walk the tamper-evidence chain
```

The log is hash-chained: each line records a hash of the one before it, so `docket audit verify`
can tell you the exact line where something stopped matching — i.e., where a line was edited or
removed after the fact. There's no environment switch to turn recording off.

**What it can't see.** The log only records what **docket** does. A raw Telegram conversation
with an agent, a human editing `openclaw.json` by hand, or the `openclaw` CLI used directly —
none of that goes through docket, so none of it is in this log. That's a structural boundary of
what docket can observe, not a gap a future version quietly closes.

---

## Summary

**Security = 3 things:**

1. **Agent constraints** (in SOUL.md) → Discourages dangerous actions (prompt-level)
2. **Reviewer checklist** (specialist agent) → Flags injection/secrets
3. **Engineer review** (git diff) → Final human check

**Hard enforcement (tool-approval gates) is on by default for new installs.** Opted out with `--no-gates`? Turn it on with `docket gates enable`. Docker workspace isolation stays opt-in: `docket gates isolate on`. On top of all three, two automatic layers run with no engineer action at all — guardrail policies and the high-risk action classes (above) — and every gate/approval change either layer makes lands in the tamper-evident audit log.

---

## Inspecting the Automatic Layers

None of this needs a human to run day to day — it's here for when you want to check it yourself:

```bash
docket gates status       # is exec-approval on, is isolation on, what's the routing
docket gates classes      # the high-risk action classes, and exactly what's wired vs. not
docket policies list      # installed guardrail policies
docket approve            # list pending approvals in docket's own store
docket audit verify       # confirm the audit log hasn't been tampered with
```

---

## Commands You Actually Use

```bash
# Start work (creates agent if needed)
docket add

# Agent does work automatically
# (Reviewer checks security automatically)

# Review and commit
cd ~/Sites/myproject
git diff
git commit -m "Feature: ..."
```

**That's it. 3 commands total.**

---

**Key Insight:** Good security is invisible. It just works.
