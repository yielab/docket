# Security: Layered & Convention-Based

**Philosophy:** Security comes from layered defaults — agent instructions, a reviewer role, and human git review — so that the common cases are covered without extra commands.

> **Status / honesty note.** docket layers two things: instruction-level agent constraints (SOUL.md, a reviewer role, human git review) plus **enforced tool-approval gates, which are ON by default for new installs** (`docket install`, unless you pass `--no-gates`). Gates require explicit approval — via `docket approve`/`docket deny` (headless, any shell), `docket serve`'s `POST /approvals/<token>` (headless HTTP, for CI/automation), or Telegram — before dangerous operations not on the curated allowlist (`rm`, `dd`, `docker`, `systemctl`, ...) run, and fail closed (deny) on timeout. `git`/`npm` stay on the allowlist for usability, so a `git push` isn't gated by this layer alone — see the spec's high-risk-class section. Docker **workspace isolation** (`docket gates isolate on`) is a separate, still-**opt-in** layer on top. See [`specs/functional/security-gates.spec.md`](../specs/functional/security-gates.spec.md) (Status: Implemented, on by default). If you ran `docket install --no-gates`, treat the constraints below as strong defaults, not guarantees — re-enable anytime with `docket gates enable`.

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

These are **prompt-level constraints**: agents are instructed to follow them. On top of that, a fresh `docket install` also turns on the enforced tool-approval gates layer by default, so non-allowlisted dangerous operations (`rm`, `dd`, `docker`, `systemctl`, ...) require a human (or CI) approval regardless of what the prompt says — see the status note above for the `git`/`npm` carve-out. If you opted out at install (`--no-gates`), turn it on anytime with `docket gates enable`.

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

## Summary

**Security = 3 things:**

1. **Agent constraints** (in SOUL.md) → Discourages dangerous actions (prompt-level)
2. **Reviewer checklist** (specialist agent) → Flags injection/secrets
3. **Engineer review** (git diff) → Final human check

**Hard enforcement (tool-approval gates) is on by default for new installs.** Opted out with `--no-gates`? Turn it on with `docket gates enable`. Docker workspace isolation stays opt-in: `docket gates isolate on`.

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
