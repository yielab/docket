# Security: Layered & Convention-Based

**Philosophy:** Security comes from layered defaults — agent instructions, a reviewer role, and human git review — so that the common cases are covered without extra commands.

> **Status / honesty note.** docket runs the agent turn itself (`core/agent_loop.py`), and every
> tool call an agent makes passes through one chokepoint (`core/tools.py`'s `dispatch_tool`) before
> it executes — there is no external daemon in the loop any more, and nothing to bypass it. That
> chokepoint is **always active**: an argument-aware command classifier plus the `pre_tool_call`
> policy hook decide `allow`/`ask`/`deny` for every call, regardless of `--gates`/`--no-gates`. A
> dangerous operation not on the curated allowlist (`rm`, `dd`, `docker`, `systemctl`, an unlisted
> shell interpreter, ...) is routed to **docket's own approval store** and blocks the call until a
> human answers — the same store a pod-dispatch hop held on a `requireApprovalRoles`/pipeline
> `approval` step, or a task a guardrail policy flagged at enqueue, also uses (see "Guardrail
> Policies" below). `git`/`npm` stay on the curated allowlist for usability, so a plain `git push`
> isn't gated by itself — see "High-Risk Actions" below for the argument-aware exception.
>
> **There is exactly one approval system, and it is answerable from four places** — all
> audit-logged, tagged with the channel that answered: a CLI channel (`docket approve`/
> `docket deny`), a headless HTTP endpoint (`docket serve`'s `POST /approvals/<token>`), MCP, and
> Telegram (docket's own bot, wired with `docket wire` — a decision there lands in the same audit
> chain as a CLI one, tagged `channel="telegram"`). The headless channels mean CI jobs and
> automation can vote without a chat account. **Approvals fail closed on timeout** — an in-turn
> "ask" (blocking a live tool call) denies itself after 120 seconds with nobody watching; an
> async dispatch-level approval denies after 15 minutes.
>
> `--no-gates` (at install, or `docket gates disable`) does **not** turn the tool-call gate off —
> it cannot be turned off. What it skips is **approval routing**: without it, an "ask" verdict
> still blocks the call, but there is no channel actively watching for it, so it simply times out
> to denied unless a human happens to run `docket approve` in time. Turn routing on anytime with
> `docket gates enable`. Docker **workspace isolation** (`docket gates isolate on`) is a separate,
> still-**opt-in** layer on top — and, as of this writing, recorded but not yet consulted by the
> turn loop (`docket gates isolate on` sets the flag; every tool call still runs unsandboxed until
> that wiring lands — `docket gates status` says so plainly). See
> [`specs/functional/security-gates.spec.md`](../specs/functional/security-gates.spec.md)
> (Status: Implemented, on by default).

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

These are **prompt-level constraints**: agents are instructed to follow them. On top of that,
docket's own tool-call chokepoint is always active regardless of the prompt: non-allowlisted
dangerous operations (`rm`, `dd`, `docker`, `systemctl`, ...) require approval before they run —
see the status note above for who can answer, and for the `git`/`npm` carve-out. A fresh `docket
install` also turns on approval **routing** by default so a prompt actually reaches a channel; if
you opted out at install (`--no-gates`), turn it on anytime with `docket gates enable`.

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

### Layer 5: High-Risk Action Classes (Automatic, and — since Phase 19 — argument-aware)
- A small, built-in list of especially consequential command patterns: money-movement,
  prod-deploy, secret-access (`docket gates classes` prints all of them).
- **Wired onto every `bash` call docket dispatches**, not just a pod's `verifyCmd`. Since docket
  runs the turn loop itself, `core/tools.py`'s `dispatch_tool` classifies the *whole command
  line* — including every segment behind a `;`/`&&`/`||`/pipe — before a call is allowed to run.
  `git status` is allowed; `git push origin production` asks, because the classifier reads the
  arguments, not just the binary name. A pod's `verifyCmd` still refuses outright on a match
  (fails closed, before the shell even starts) since it runs synchronously with no approver
  reachable mid-hop; a hop's real output is separately scanned for a match on the way through
  the pipeline (flagged, not blocked, by itself).
- **What this does NOT do:** lock down network egress. `bash` can still reach the network through
  interpreters and package managers on the curated allowlist (`python3`, `node`, `git clone`, ...)
  — the `fetch` tool is domain-allowlisted and the *inspectable* path, but not yet the *only* one.
  Tracked as an open gap, not glossed over. It is also scoped to what docket itself dispatches: a
  process started outside docket's turn loop is outside this gate entirely.

---

## Testing Security (Simple)

### Test 1: Can Agent Commit?
```bash
# Check the implementer's constraints (replace "myapp" with your project name)
grep "NEVER commit" ~/.docket/workspaces/projects/myapp-implementer/SOUL.md

# Should find: "NEVER commit to git"
```

### Test 2: Does Reviewer Check Security?
```bash
# Check the reviewer's checklist (replace "myapp" with your project name)
grep "prompt injection\|hardcoded secret" ~/.docket/workspaces/projects/myapp-reviewer/SOUL.md

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
to `~/.docket/audit.log` — who, what, when. Secret **values** are never written, only names
(a key's NAME, a model id, an agent id).

```bash
docket audit          # last 20 changes
docket audit 50       # last 50
docket audit verify   # walk the tamper-evidence chain
```

The log is hash-chained: each line records a hash of the one before it, so `docket audit verify`
can tell you the exact line where something stopped matching — i.e., where a line was edited or
removed after the fact. There's no environment switch to turn recording off.

**What it can't see.** The log only records what **docket** does. Since docket now owns the
Telegram bot itself, a bound chat's `/approve`, `/deny`, `/status`, and `/delegate` all go through
docket and land in this log, tagged `channel="telegram"`, the same as a CLI or HTTP decision. What
it genuinely can't see: a human editing docket's own JSON files (`fleet.json`, `.docket-meta.json`,
...) directly with a text editor instead of a docket command, or any process a user starts entirely
outside docket's turn loop — docket gates the tool calls **it** dispatches, not every process on
the host. That's a structural boundary of what docket can observe, not a gap a future version
quietly closes.

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
# Initialize the current project once (Lead + Implementer)
docket init

# Check only this project's readiness and task state
docket status

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
