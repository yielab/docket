# Security: Layered & Convention-Based

**Philosophy:** Security comes from layered defaults — an always-on tool-call gate, agent instructions, an optional read-only reviewer role, and human git review — so that the common cases are covered without extra commands.

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
> `--no-gates` (on `docket init`, or `docket gates disable`) does **not** turn the tool-call gate off —
> it cannot be turned off, and it does not change how an "ask" verdict is answered either. What
> `--gates`/`--no-gates` and `docket gates enable`/`disable` actually control is
> `security.approvalRoutingState`/`approvalRoutingMode`, a recorded, audited posture flag that
> `docket gates status` and `docket doctor` report — nothing on the live path (`core/tools.py`,
> `core/approval.py`, `core/telegram.py`, `core/agent_loop.py`, `serve.py`) reads it. An "ask"
> verdict always blocks the call and always sits in docket's own approval store, answerable
> identically by the CLI, HTTP, MCP, and Telegram channels whether this flag is on or off; docket
> never pushes a prompt to any of them on its own, so there is no "channel actively watching" for
> this flag to turn on (see telegram-integration.spec.md's Command-grammar requirements 7-8:
> inbound-only, no notification on a newly-created approval). Wiring this flag into a real
> consumer, or retiring `docket gates enable`/`disable`, is an open maintainer decision this repo
> has not made. Docker/bwrap **workspace isolation** (`docket gates isolate on`) is a
> separate, still-**opt-in** layer on top — but it is consulted by the turn loop: when it's on,
> every real dispatch hop runs sandboxed if docker or bwrap is available, and if neither is, the
> turn **refuses to run rather than falling back unsandboxed** (an audited `isolation.refused`
> entry — no LLM call, no tool executes). `docket gates status` reports which of the two states
> applies. See
> [`specs/functional/security-gates.spec.md`](../specs/functional/security-gates.spec.md)
> (Status: Implemented, on by default).

---

## How Security Works (Layered)

### 1. Agents Are Instructed Not to Do Dangerous Things

**A pod member's SOUL.md/AGENTS.md carry short safety lines** (the Implementer's, verbatim):
```markdown
- Never push to main/master without HITL approval; never delete files without explicit instruction.
```
and every member's AGENTS.md `## Red Lines` repeats "Never push to main/master or delete files
without HITL approval" plus the stay-in-this-pod rule. Nothing instructs an agent not to *commit*.

These are **prompt-level constraints**: agents are instructed to follow them. On top of that,
docket's own tool-call chokepoint is always active regardless of the prompt: non-allowlisted
dangerous operations (`rm`, `dd`, `docker`, `systemctl`, ...) require approval before they run —
see the status note above for who can answer, and for the `git`/`npm` carve-out. A first `docket
init` also records approval-**routing** posture as on by default (`docket gates status`
reports it); that posture flag is recorded and audited but not read by the approval path itself,
so opting out with `--no-gates` on `docket init`, or later with `docket gates disable`, changes nothing
about who can answer an "ask" verdict — CLI, HTTP, MCP, and Telegram always can.

### 2. A Reviewer Can Veto (when the pod has one)

The default pod from `docket init` is lean — Lead + Implementer, **no Reviewer**. Add one with
`docket init --pod full`, `--with reviewer`, or later `docket add reviewer`. When present:

- Its role prompt tells it to review diffs "for correctness, security, and requirement fit". There
  is **no fixed checklist** — what it catches is the model's judgment, not a scanner.
- It is **structurally read-only**: its role's `denied_tools` remove `write`/`edit`/`bash` from its
  tool registry, so it *cannot* modify code rather than being told not to.
- Its reply must carry one `APPROVE` or `REQUEST-CHANGES` marker line. `REQUEST-CHANGES` sends the
  task back to the Implementer for one bounded rework cycle (default), then fails it; a missing or
  ambiguous marker blocks the pipeline like a rejection.

---

## What Engineers Do

### Before Starting Work
**Nothing.** Security is built-in.

### During Agent Work
**Nothing.** The tool-call gate runs on every call; a Reviewer, if the pod has one, reviews
automatically. Answer any pending approvals (`docket approve`).

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
- Instructed not to push to main/master or delete files without approval (prompt-level, not
  enforced by the prompt itself — the tool-call gate is what enforces)
- **No code — just instructions**

### Layer 2: Detection (Reviewer verdict, optional role)
- Runs on every dispatched task in a pod that has a Reviewer
- `REQUEST-CHANGES` triggers one rework cycle, then fails the task
- **Model judgment, not a scanner** — keep reviewing diffs yourself

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

### Test 1: Does the Implementer Carry Its Safety Lines?
```bash
# Check the implementer's constraints (replace "myapp" with your project name)
grep "Never push" ~/.docket/workspaces/projects/myapp-implementer/SOUL.md

# Should find: "Never push to main/master without HITL approval; ..."
```

### Test 2: Is the Reviewer Read-Only?
```bash
# Only if the pod has a Reviewer (replace "myapp" with your project name)
grep "Read-only" ~/.docket/workspaces/projects/myapp-reviewer/SOUL.md
docket roles show reviewer   # its denied_tools are what actually enforce it
```

### Test 3: Review Agent Commits
```bash
cd ~/Sites/myproject
git log --since="30 days ago" --format="%an %s"  # review automated/agent commit authors
```
`git commit` is on the curated allowlist and no prompt forbids it, so an Implementer **can** commit
locally. Review what landed before you push.

**The gate itself is covered by docket's own test suite; these checks confirm your pod's setup.**

---

## What If Something Goes Wrong?

### Prompt Injection Found
```bash
# Reviewer will catch it and REJECT
# If somehow missed, search manually:
grep -rn "ignore previous\|you are now" ~/Sites/myproject/src/
```

### Agent Tries to Commit
Nothing stops a local `git commit`: `git` stays on the gate's curated allowlist (it's used
constantly for benign work), and no prompt forbids committing. A plain `git push` is also allowed;
`git push ... main|master|production|prod` matches the `prod-deploy` high-risk class and **asks**.
The prompt-level "never push to main/master" line, a Reviewer if present, and your git-diff review
are the backstops for the rest.
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
removed after the fact. There's no environment switch to turn recording off. The log rotates to a
**single** `audit.log.1` backup; the new file's first line claims its predecessor, so `verify`
reports a break if that backup is missing or altered. Only one generation back is checkable, and
deleting `audit.log` *and* `audit.log.1` together looks like a fresh install — erasure is made
evident, not prevented.

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

**Security = 3 things you see, on top of the always-on tool-call gate:**

1. **Agent constraints** (in SOUL.md) → Discourages dangerous actions (prompt-level)
2. **Reviewer verdict** (optional pod role, read-only) → Can send work back or fail it
3. **Engineer review** (git diff) → Final human check

**Hard enforcement (the tool-call gate) is unconditionally on — no install flag disables it.** `--no-gates` (on `docket init`) and `docket gates disable` only record approval-routing posture as off, a flag nothing on the live path reads; `docket gates enable` records it as on for the same reason `docket gates status`/`doctor` display it, not because it changes how an "ask" verdict is answered. Docker workspace isolation stays opt-in: `docket gates isolate on`. On top of all three, two automatic layers run with no engineer action at all — guardrail policies and the high-risk action classes (above) — and every gate/approval change either layer makes lands in the tamper-evident audit log.

---

## Inspecting the Automatic Layers

None of this needs a human to run day to day — it's here for when you want to check it yourself:

```bash
docket gates status       # gate always active; approval-routing posture; isolation mode
docket gates classes      # the high-risk action classes, and exactly what's wired vs. not
docket policies list      # installed guardrail policies
docket approve            # list pending approvals in docket's own store
docket audit verify       # walk the hash chain -- surfaces an edited/removed line, doesn't prove none happened
```

---

## Commands You Actually Use

```bash
# Initialize the current project once (Lead + Implementer)
docket init

# Check only this project's readiness and task state
docket status

# Queue and run work
docket pod myproject delegate "<task>"
docket pod myproject dispatch
# (a Reviewer, if you added one, reviews automatically)

# Review and commit
cd ~/Sites/myproject
git diff
git commit -m "Feature: ..."
```

**That's the whole loop.**

---

**Key Insight:** Good security is invisible. It just works.
