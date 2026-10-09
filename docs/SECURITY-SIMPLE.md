# Security: Layered & Convention-Based

**Philosophy:** Security comes from layered defaults — an always-on tool-call gate, agent instructions, an optional read-only reviewer role, and human git review — so that the common cases are covered without extra commands, and nothing about a run leaves the host until you choose what may.

> **Status / honesty note.** docket runs the agent turn itself (`core/agent_loop.py`), and every
> tool call an agent makes passes through one chokepoint (`core/tools.py`'s `dispatch_tool`) before
> it executes — there is no external daemon in the loop any more, and nothing to bypass it. That
> chokepoint is **always active**: an argument-aware command classifier plus the `pre_tool_call`
> policy hook decide `allow`/`ask`/`deny` for every call; no flag or command turns it off. A
> dangerous operation not on the curated allowlist (`rm`, `dd`, `docker`, `systemctl`, an unlisted
> shell interpreter, ...) is routed to **docket's own approval store** and blocks the call until a
> human answers — the same store a pod-dispatch hop held on a `requireApprovalRoles`/pipeline
> `approval` step, or a task a guardrail policy flagged at enqueue, also uses (see "Guardrail
> Policies" below). `git`/`npm` stay on the curated allowlist for usability, so a plain `git push`
> isn't gated by itself — see "High-Risk Actions" below for the argument-aware exception.
>
> **There is exactly one approval system, and it is answerable from four places** — all
> audit-logged, tagged with the channel that answered: a CLI channel (`docket task approve`/
> `docket task deny`), a headless HTTP endpoint (`docket start`'s `POST /approvals/<token>`), MCP, and
> Telegram (docket's own bot, wired with `docket setup notify bind` — a decision there lands in the same audit
> chain as a CLI one, tagged `channel="telegram"`). The headless channels mean CI jobs and
> automation can vote without a chat account. **Approvals fail closed on timeout** — an in-turn
> "ask" that actually blocks a live tool call (an interactive foreground dispatch, which resolves
> to `approvalMode: wait`) denies itself after 120 seconds with nobody watching; a pre-hop
> `approval` gate (the async, pre-dispatch-level kind) denies after 15 minutes. **An unattended
> pod never blocks on that 120-second wait at all** — `docket start --dispatch`'s sweep and a
> non-interactive `docket run` both resolve an unset pod to `approvalMode: park` (Phase 34, D-50):
> the in-turn `ask` is recorded and the task is parked `waiting_approval` immediately, with no
> live wait and no risk of one stuck hop stalling every other pod in the same sweep. A parked
> approval is answered exactly the same way (any of the four channels above), re-runs the same
> hop on a grant rather than skipping ahead, and — left untouched — expires after the pod's
> `approvalExpiryHours` (24h by default) and denies, the identical fail-closed sweep a pre-hop
> gate's pending approval already used. See "The operator loop" below for how a human actually
> learns a task is waiting.
>
> An "ask" verdict always blocks the call and always sits in docket's own approval store,
> answerable identically by the CLI, HTTP, MCP, and Telegram channels. The Telegram bot itself
> is inbound-only and never messages a chat first (telegram-integration.spec.md's Command-grammar
> requirements 7-8). Notifications exist since Phase 34, but only through an opt-in `kind: channel`
> you enable yourself; every channel ships off except your own console, which sends nothing (see
> "The operator loop" below).
>
> A gated call's approval now carries a `rationale` (the model's own preceding sentence, screened
> and truncated, so a claim to weigh and not a verified fact) and the options `approve_once`,
> `approve_task` (the identical call for the rest of the task, only for the role that asked) and
> `deny`; `--reason` on approve/deny is
> screened and audited with the answering channel.
> bwrap/Docker **workspace isolation** is a
> separate layer on top, **opt-in** (`docket setup sandbox on`; it needs bubblewrap on Linux or a
> running Docker) and consulted by the turn loop: when it's on, every real dispatch hop runs
> sandboxed, and if neither backend is usable the
> turn **refuses to run rather than falling back unsandboxed** (an audited `isolation.refused`
> entry — no LLM call, no tool executes). `docket setup sandbox status` reports which state applies.
> Requirements and coverage: "Workspace isolation (opt-in)" below, and
> [`specs/functional/security-gates.spec.md`](../specs/functional/security-gates.spec.md).

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
see the status note above for who can answer, and for the `git`/`npm` carve-out.

### 2. A Reviewer Can Veto (when the pod has one)

The default pod from `docket init` is lean — Lead + Implementer, **no Reviewer**. Add one with
`docket init --pod full`, `docket init --with reviewer`, or later `docket pod add reviewer`. When present:

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
automatically. Answer any pending approvals (`docket task approve`).

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
- A small set of installed policies (`docket pod policies`) scan text at two points in docket's own
  pod-dispatch pipeline — not a raw Telegram chat, only work that goes through
  `docket task add`/`docket run`:
  - **Once**, when a task is added — before it's even added to the queue.
  - **On every hop's real reply**, as the pipeline runs.
- A match can `allow`/`warn` (just logged), `redact` (scrub it before it's stored), `block`
  (reject the task, or stop the pipeline where it tripped), or — enqueue-time only —
  `require_approval` (routes into the approval store above).
- `docket pod policies` to see what's installed, `docket pod check "<text>" --role <role> [--hook <hook>]`
  to dry-run one without touching anything real. Add `--tool <name>` when testing `pre_tool_call`
  against something other than `bash` (the default), so a non-shell tool isn't misclassified
  against the command allowlist.
- **A broken policy file fails closed.** Unparseable JSON, a pattern that doesn't compile as a
  regex, or an unknown action makes that file evaluate as `block` within its readable scope — the
  hook and roles it declares, or every hook and role if the JSON itself won't parse — named to the
  file so you know what to fix. `docket setup` catches this before a live turn does.

### Layer 5: High-Risk Action Classes (Automatic, and — since Phase 19 — argument-aware)
- A small, built-in list of especially consequential command patterns: money-movement,
  prod-deploy, secret-access (`docket setup sandbox classes` prints all of them).
- **Wired onto every `bash` call docket dispatches**, not just a pod's `verifyCmd`. Since docket
  runs the turn loop itself, `core/tools.py`'s `dispatch_tool` classifies the *whole command
  line* — including every segment behind a `;`/`&&`/`||`/pipe — before a call is allowed to run.
  `git status` is allowed; `git push origin production` asks, because the classifier reads the
  arguments, not just the binary name. A pod's `verifyCmd` still refuses outright on a match
  (fails closed, before the shell even starts) since it runs synchronously with no approver
  reachable mid-hop; a hop's real output is separately scanned for a match on the way through
  the pipeline (flagged, not blocked, by itself).
- **What this does NOT do by default:** lock down network egress. With the default `network open`,
  `bash` can still reach the network through interpreters and package managers on the curated
  allowlist (`python3`, `node`, `git clone`, ...) — the `fetch` tool is domain-allowlisted and the
  *inspectable* path, but not the only one until you run `docket setup sandbox network none`, which cuts
  the jail's network (verify commands and `run:` steps still run on the host). It is also scoped to what docket itself dispatches: a
  process started outside docket's turn loop is outside this gate entirely.
- **Only `bash` is jailed, and only with isolation on.** The command gate above applies to every
  `bash` call; the opt-in bwrap/Docker isolation (next section) jails `bash` and stdio MCP servers.
  The other built-in tools are not jailed: `fetch` is domain-allowlisted, and
  `write`/`edit`/`read`/`glob`/`grep` are bounded by role denials, policy and path confinement,
  not by a sandbox.
- **A pod can widen its own allowlist** with `docket pod set allowCommands pytest,uv`
  (comma-separated) for its own turns only — a high-risk-class binary like `git` or `npm` is
  refused at write time, and an allowlisted-by-pod binary is still redirect-sensitive, so
  `pytest > /etc/passwd` still asks. **`approvalMode`** is how a pod chooses what an unattended
  `ask` does: unset, it resolves per caller — `park` under `docket start --dispatch`'s sweep or a
  non-interactive `docket run`, `wait` under an interactive TTY. An explicit `wait` blocks the
  call for the usual 120-second in-turn timeout regardless of caller; `park` records the call and
  parks the task instead of blocking (see "The operator loop" below); `refuse` fails the call
  fast with `approval_unavailable`, the one posture that never gives a human a chance to grant it
  later.

### Workspace isolation (opt-in): the sandbox for the agents' shell

**Off by default.** Without it, an agent's `bash` runs on your machine as you, bounded by the
tool-call gate and the policies above but not by a sandbox. Turn it on when you want the shell
contained as well as gated:

```bash
docket setup sandbox on      # needs a backend (below); exits 1 naming the fix if there is none
docket setup                # names the backend a turn will use
docket setup sandbox off     # back to the host; both commands are audited
```

**What a host needs to turn it on.** One sandbox backend. docket probes bwrap first, then docker:

| Host | Backend | How to get it |
| --- | --- | --- |
| Linux | bubblewrap (`bwrap`), preferred: no daemon, and the jail sees the host's toolchain read-only | `apt install bubblewrap`, `dnf install bubblewrap`, `pacman -S bubblewrap` |
| Linux or macOS | Docker, with the daemon running | Docker Desktop, Colima or OrbStack on macOS (bwrap does not exist there) |

Under Docker the jail is only as capable as its image, `DOCKET_SANDBOX_IMAGE` (default
`alpine:3.20`): a jailed `git commit` needs `git` in the image, and Python work needs `python3`.
`docket setup` checks the image for `git` and warns with the fix. `DOCKET_SANDBOX_BACKEND=bwrap|docker`
forces one backend. Nothing here is needed while isolation is off.

**What it covers, once on.**
- Every `bash` call runs in the jail. Only the agent's workspace and the task's worktree are
  writable; the rest of the host is read-only or absent. The task worktree's git directories are
  writable, so the agent can commit, while the repository's hooks, config and attributes stay
  read-only, so nothing the jail writes runs later in your own unjailed git.
- Stdio MCP servers start in the same jail, unless you declared one `--no-isolate` (audited and
  listed by `docket setup`).
- A jailed process sees only `PATH`, the pod's injected variables and your git identity, never
  docket's credentials.
- **It fails closed.** If isolation is on and neither backend is usable when a turn starts, the
  turn is refused before any model call and audited as `isolation.refused`; it never falls back to
  running unsandboxed.
- `docket setup sandbox network none` (or a pod's `network: none`) cuts the jail's network. It needs
  isolation on: with isolation off, such a turn is refused, because only the jail can enforce it.

**What it does not cover.** `read`, `write`, `edit`, `glob` and `grep` run inside docket and are
confined to the workspace and codebase by path, not by the jail (symlinks out of those roots are
refused either way). `fetch` runs inside docket under its domain allowlist. A pod's `verifyCmd`
and pipeline `run:` steps are your own commands and run on the host, with docket's credentials
stripped from their environment.

### Layer 6: Telemetry export (what leaves the host)

- **Off by default.** Every built-in exporter (`docket setup export list`) ships `enabled: false`.
  Nothing is sent anywhere until an operator runs `docket setup export enable <name>`, which
  resolves a credential (prompted, never a CLI argument), probes the real endpoint, and only
  then writes the minimal override that turns it on.
- **Structure only, unless you choose more.** Each exporter declares a privacy level:
  `minimal` (the default for every built-in) sends model and tool names, timing, measured token
  counts, pass/fail and ids, and nothing a person wrote or read. `actions` adds tool arguments
  and error text; `conversation` adds prompts, replies and tool results; `full` adds the system
  prompt. `share: [...]` names the classes exactly. `docket setup export show <name>` lists what
  leaves ("Leaves this host"), and `docket setup export preview <name>` shows the exact spans a real
  local session would send, without sending them.
- **An allowlist, not a filter.** A span attribute leaves only when its class is granted, so a
  trace field nobody has classified stays home. A conversation is filtered part by part:
  sharing `prompts` does not carry a tool result inside it. Credentials and secret-shaped
  values are redacted before anything is written, at every level.
- **Captured only when asked for.** Prompts, replies and tool output enter the local trace only
  while an enabled exporter grants them; with every exporter at `minimal`, the local trace holds
  no more than it did before exporters existed.
- **Widening is deliberate and recorded.** `docket setup export privacy <name> <level>` (or
  `enable --privacy`) lists each newly shared class and the destination host and asks; off a TTY
  it refuses without `--yes`. Narrowing never asks. Every change is an `exporter.privacy` audit
  entry (`from`, `to`, `host`). Each exported session also carries `docket.privacy`, so the
  destination shows what it was allowed to receive.
- **A running `docket start` keeps the level it started with.** Export starts once per process,
  so a change — narrowing included — reaches a long-running `docket start --dispatch` only after it
  restarts. A one-shot `docket run` or `docket exec` picks it up at once. `DOCKET_NO_EXPORT=1`
  turns export off for one process.
- **No new dependency, no vendor SDK.** The wire format is hand-rolled OTLP/HTTP JSON over the
  stdlib (`edges/adapters/exporters/otlp_http.py`) — D-24's cut of the OpenTelemetry SDK stands
  (D-48), and export stays a zero-dependency projection of docket's own trace events, never a
  second source of truth.
- **Never blocks a turn.** The export pipeline is a bounded queue drained by a background
  thread — a slow or unreachable destination drops spans past the bound and records it in that
  exporter's health counters (`docket setup export show <name>`), it never raises into the agent
  loop.
- **A pod only documents intent, never activates.** `pod.yaml`'s `exporters:` list is validated
  against the live catalog and reported by `docket pod show`, but naming a destination there does
  not turn it on — `docket setup export enable` is still the one command that flips `enabled: true`.

### The operator loop: how you find out, and how you answer (Phase 34, D-50)

<p align="center">
  <img src="assets/governance.png" alt="Real terminal output: the Lead parks a question that docket task answer resolves; the Implementer's git push origin production parks the task for approval under high-risk-deploy; the audit log shows tool.ask, the trace shows the denial with executed false, and the chain verifies clean" width="760">
</p>

- **A parked task is not a silent one.** `docket inbox` (also `GET /inbox`, the MCP `inbox`
  tool, and Telegram's `/status`) is a live, read-only view — every pod's tasks and pending
  approvals sorted into needs-you, failed, done-since-last-look and running — computed fresh each
  call, not a separate store to fall out of sync with the truth. It's the one place that answers
  "does anything need me right now," across every pod, without opening each one.
- **Off by default, same as export.** A push notification is a separate, opt-in `kind: channel`
  document (`docket setup notify`): seven dialects ship (`console`, `desktop`, `webhook`, `command`,
  `ntfy`, `email`, `telegram`), and only `console` — your own terminal, already the inbox — ships
  enabled. Enabled is not the same as reaching you: console sends nothing, so `docket setup`
  flags a home with pods and nothing else on, and `docket init`/`docket start --dispatch` warn too; the fix
  is one command, never automatic. Nothing leaves this host to notify you of anything until
  you run `docket setup notify enable <name>`. Each dialect has a closed maximum of what it may do: every dialect can
  `notify`; only `console` and `telegram` may ever `decide` (act on an approval from inside the
  channel itself); a document that tries to exceed its dialect's maximum is refused at parse
  time, not silently ignored.
- **A notification carries as little as an exporter does, by the same default.** `content:
  minimal` (default) names what changed, nothing more; `actions` adds an approval's rendered
  command; `conversation` adds a task's question or brief. Widening is the same confirmed,
  audited command shape as `docket setup export privacy`: `docket setup notify privacy <name> <level>`
  lists what starts showing up and asks, refusing off a TTY without `--yes`; narrowing never
  asks.
- **Telegram's push is not the inbound bot talking to itself.** `core/telegram.py`'s bot is still
  exactly what "It isn't a chat" above describes: inbound-only, five verbs now (`/approve`,
  `/deny`, `/status`, `/delegate`, and `/answer <task-id> <text>` for a parked question), and it
  never sends anything it wasn't asked to. The `telegram` *channel* (`docket setup notify enable
  telegram --set actors=<chat-id>`) is a second, independent mechanism: it can push a
  notification to a chat id you explicitly listed, and only that chat id — never every
  `fleet.json` binding, never triggered from inside the bot's own poll loop.
- **Answering doesn't require re-running anything by hand.** A parked approval is answered like
  any other (`docket task approve`/`docket task deny`, HTTP, MCP or Telegram) and re-runs the exact hop it
  parked in, carrying a single-use pre-grant so the model's identical next call passes without
  asking again. A parked *question* (`waiting_input`, from a pipeline `input` step or a Lead's
  own intake brief) is answered with `docket task answer <task-id>` (interactive, prompts once per
  field) or non-interactively with `docket task answer <task-id> [text] [--field k=v]...
  [--decline]` — both call the same `answer_task` function HTTP and MCP use, so an answer is
  screened through the same input policy as any other text reaching an agent.

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
docket pod roles reviewer   # its denied_tools are what actually enforce it
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

## The Audit Log (`docket log`)

Every sandbox change, approval grant/deny, credential/model/pod change, and every exporter added,
removed, enabled, disabled or given a new privacy level, writes one line to
`~/.docket/audit.log` — who, what, when. Secret **values** are never written, only names (a
credential's NAME, a model id, an agent id).

```bash
docket log          # last 20 changes
docket log 50       # last 50
docket log verify   # walk the tamper-evidence chain
```

The log is hash-chained: each line records a hash of the one before it, so `docket log verify`
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
outside docket's turn loop — docket governs the tool calls **it** dispatches, not every process on
the host. That's a structural boundary of what docket can observe, not a gap a future version
quietly closes.

---

## Summary

**Security = 3 things you see, on top of the always-on tool-call gate:**

1. **Agent constraints** (in SOUL.md) → Discourages dangerous actions (prompt-level)
2. **Reviewer verdict** (optional pod role, read-only) → Can send work back or fail it
3. **Engineer review** (git diff) → Final human check

**Hard enforcement (the tool-call gate) is unconditionally on — no flag or command disables it.** Workspace isolation (bwrap, else Docker) is opt-in with `docket setup sandbox on`, which needs one of those backends on the host, and `docket setup sandbox network none` is the opt-in network lockdown. On top of all three, two automatic layers run with no engineer action at all — guardrail policies and the high-risk action classes (above) — and every gate/approval change either layer makes lands in the tamper-evident audit log. What leaves the host is governed the same way (Layer 6): every exporter ships off and at `minimal`, and sharing more is a confirmed, audited command. An unattended pod's "ask" now parks instead of blocking a sweep, and how you find out is the same shape again ("The operator loop" above): every notification channel ships off except your own console, which sends nothing, so `docket setup` warns until you enable one that delivers, and widening what one shares is a confirmed, audited command too.

---

## Inspecting the Automatic Layers

None of this needs a human to run day to day — it's here for when you want to check it yourself:

```bash
docket setup sandbox status       # gate always active; isolation mode
docket setup sandbox classes      # the high-risk action classes, and exactly what's wired vs. not
docket pod policies      # installed guardrail policies
docket setup             # catches a broken policy file before a live turn does, and more
docket task approve            # list pending approvals in docket's own store
docket log verify       # walk the hash chain -- surfaces an edited/removed line, doesn't prove none happened
docket setup export list     # every trace destination: on or off, and what it SHARES
docket setup export preview <name>   # the exact spans it would receive, without sending them
docket inbox               # everything across every pod that needs you, right now
docket setup notify list       # every notification destination: on or off, and what it shares
```

---

## Commands You Actually Use

```bash
# Initialize the current project once (Lead + Implementer)
docket init

# Check only this project's readiness and task state
docket status

# Queue and run work
docket task add "<task>"
docket run
# (a Reviewer, if you added one, reviews automatically)

# Review and commit
cd ~/Sites/myproject
git diff
git commit -m "Feature: ..."
```

**That's the whole loop.**

---

**Key Insight:** Good security is invisible. It just works.
