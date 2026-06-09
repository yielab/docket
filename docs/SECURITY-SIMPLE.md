# Security: Layered & Convention-Based

**Philosophy:** Security comes from layered defaults — agent instructions, a reviewer role, and human git review — so that the common cases are covered without extra commands.

> **Status / honesty note.** rack's current security model is **instruction- and review-based**, not hard-enforced. Agent constraints live in prompts (SOUL.md), not in a technical sandbox, and the reviewer is a specialist agent, not a blocking gate. **Enforced tool-approval gates are specified but not yet wired up** — see [`specs/functional/security-gates.spec.md`](../specs/functional/security-gates.spec.md) (Status: Planned). Treat the constraints below as strong defaults, not guarantees.

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

These are **prompt-level constraints**: agents are instructed to follow them, but they are not technically enforced. Enforcement (tool-approval gates) is the planned next layer.

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
- Agents have constraints built into identity
- Can't commit, can't push, can't delete
- **No code needed, just instructions**

### Layer 2: Detection (Reviewer Checklist)
- 6-point checklist runs automatically
- Rejects bad code immediately
- **No manual scanning needed**

### Layer 3: Engineer Review (Git Diff)
- Engineer reviews diff before commit
- Final human check
- **Simple git diff, that's it**

---

## Testing Security (Simple)

### Test 1: Can Agent Commit?
```bash
# Check agent constraints
grep "NEVER commit" ~/.openclaw/workspaces/programmer/SOUL.md

# Should find: "NEVER commit to git"
```

### Test 2: Does Reviewer Check Security?
```bash
# Check reviewer checklist
grep "prompt injection\|hardcoded secret" ~/.openclaw/workspaces/reviewer/SOUL.md

# Should find: 6-point checklist
```

### Test 3: Are There Agent Commits?
```bash
cd ~/Sites/myproject
git log --author="Claude" --since="30 days ago"

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
are the backstops. This is a convention, not a hard gate — enforced gating is planned (see the
status note above).

### Hardcoded Secret Found
```bash
# Reviewer will catch it and REJECT
# If missed, search manually:
grep -rn "api_key.*=.*['\"][a-zA-Z0-9]{20,}" ~/Sites/myproject/src/
```

---

## Summary

**Security = 3 things:**

1. **Agent constraints** (in SOUL.md) → Discourages dangerous actions (prompt-level)
2. **Reviewer checklist** (specialist agent) → Flags injection/secrets
3. **Engineer review** (git diff) → Final human check

**No complex commands today; enforced tool-approval gates are the planned next layer.**

---

## Commands You Actually Use

```bash
# Start work (creates agent if needed)
rack add

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
