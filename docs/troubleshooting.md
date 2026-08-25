# Troubleshooting Guide

## Agents Not Responding in Telegram

### Symptom
Agents don't respond to messages in Telegram groups, even though they're registered and wired.

### Common Causes

#### 1. **Invalid Model Name**

**Error you might see:** `HTTP 404 from https://api.anthropic.com/v1/...: model not found` (or
similar — the exact text comes straight from the model provider's error response, since docket's
own turn loop calls the endpoint directly and does not pre-validate model names against a
catalog).

**Root cause:** a stale or misspelled model id in an agent's `.docket-meta.json` (e.g.
`haiku-3-5` instead of `haiku-4-5`).

**How to diagnose:**
```bash
docket doctor
# Look for a flagged stale/aliased model name
```

**How to fix:**
```bash
# Auto-fix with docket
docket doctor --fix

# Or update each agent's model individually
docket profile <agent-id> anthropic/claude-haiku-4-5

# Re-resolve all policy-following agents at once
docket models preset anthropic
```

> **Never edit an agent's `.docket-meta.json` model field directly** — go through `docket profile`
> or `docket models` so the change is validated, applied consistently, and audit-logged.

**Valid model names (Anthropic defaults):**
- `anthropic/claude-haiku-4-5` (cheap class — manager, reviewer, tester, knowledge, task)
- `anthropic/claude-sonnet-4-6` (strong class — programmer, security, repo)
- `anthropic/claude-opus-4-6` (pin-only via `docket profile <id> <model>`)

Check the live mapping anytime with `docket models`.

#### 2. **Missing Telegram Bindings**
**How to diagnose:**
```bash
docket list
# Check if agent shows "● telegram" with group ID
```

**How to fix:**
```bash
docket wire <agent-id>
```

#### 3. **Unbound / unauthorized chat**
Since docket owns the Telegram bot itself, the `docket wire` binding **is** the entire
authorization boundary — there is no separate daemon-side allowlist to also configure. A message
from a chat that isn't bound to an agent gets a plain refusal, and the attempt is audit-logged
(`telegram.unauthorized`) rather than silently dropped.

**How to diagnose:**
```bash
docket audit | grep telegram.unauthorized
docket list
# Look for agents with "✓ Wired" and matching group IDs
```

**How to fix:**
```bash
docket wire <agent-id>
```

#### 4. **The Telegram poller isn't running, or no bot token is stored**
Telegram is docket's own bot (ROADMAP Phase 19 P19-8) — there is no external gateway process to
be "down." Two things have to both be true for a wired chat to get an answer:

**How to diagnose:**
```bash
docket keys list                    # is TELEGRAM_BOT_TOKEN stored?
# and: is a `docket serve --telegram` process actually running?
```

**How to fix:**
```bash
docket keys add TELEGRAM_BOT_TOKEN  # if not already stored
docket serve --telegram             # or: docket serve --dispatch --telegram
```

## High Costs / Context Bloat

### Symptom
A session accumulates an unusually large context, or an agent's turn count keeps climbing.

### Root Cause
docket's turn loop keeps a growing message history for a session across turns. With enough turns,
cached/re-sent context grows — the same shape of problem any long-lived chat session has.

### Solutions

#### 1. **Reset Agent Sessions**
```bash
# Level 1: Clear memory logs only
docket maintain <agent-id> clean

# Level 2: Clear memory + HEARTBEAT.md
docket maintain <agent-id> reset

# Level 3: Deep reset - regenerate all from metadata
docket maintain <agent-id> rebuild
```

#### 2. **Switch to a cheaper model policy**

Set the whole fleet to a lower-cost provider preset, or pin a specific agent:

```bash
# Switch the role policy for all agents at once (pins are untouched)
docket models preset openrouter-free

# Or pin just one agent to a cheaper model
docket profile <agent-id> anthropic/claude-haiku-4-5
```

See `docket models` for the current role→model table and all available presets.

#### 3. **Monitor token usage**
```bash
docket cost <agent-id>
docket cost  # All agents
```
Token counts here are real and measured; the dollar column is not — docket's own turn loop
reports no billed spend today. See
[Cost reporting and its limits](../README.md#cost-reporting-and-its-limits).

#### 4. **Check the per-turn context footprint**
`docket maintain <agent-id> check` estimates the tokens re-sent every turn from the files that
actually get re-injected (SOUL.md, AGENTS.md, TOOLS.md, HEARTBEAT.md, MEMORY.md) and warns when
they exceed the configured budget:
```bash
docket maintain <agent-id> check
# ⚠ Context footprint: ~7,400 tok/turn (budget 6,000) — trim MEMORY.md/HEARTBEAT.md
```
If it's over budget, summarize the daily logs into MEMORY.md and archive them instead of letting
`memory/` grow unbounded:
```bash
docket maintain <agent-id> distill
```

#### 5. **A single turn is running away**
docket's own turn loop bounds every turn: a hard cap on model round-trips
(`AGENT_LOOP_MAX_ITERATIONS`, default 20), a hard cap on total tool calls
(`AGENT_LOOP_MAX_TOOL_CALLS`, default 40), a wall-clock timeout
(`AGENT_LOOP_WALL_CLOCK_TIMEOUT_S`, default 300s), and a measured-token budget
(`AGENT_LOOP_TOKEN_BUDGET`, default 100,000). These are deliberate stop conditions, not
throughput knobs — if you're hitting one legitimately, override it via its environment variable
rather than assuming something is broken.

## Model / Endpoint Errors

### "no endpoint configured for this model"
**Cause:** `edges/adapters/llm.py`'s `resolve_endpoint` couldn't find a base URL for the model's
provider — no `DOCKET_LLM_BASE_URL`, no registered provider entry, and no built-in hosted mapping.
OpenRouter (`openrouter/...`) and Vercel AI Gateway (`ai-gateway/...`) have built-in mappings;
arbitrary hosted provider prefixes do not.

**Fix:** for OpenRouter/Vercel, apply the matching preset and store its key. For any other hosted or
local server, register it first (`docket models provider add <name> <base-url>`). A credential
authenticates a known endpoint; it cannot supply a missing URL.

### "cannot reach `<url>`: ..." / "timed out after Ns calling `<url>`"
**Cause:** the configured endpoint (hosted or local) isn't reachable — wrong URL, the local
server isn't running, or a network/firewall issue.

**Fix:** confirm the endpoint is up (`curl <base-url>/models`), check for typos from
`docket models provider add`, and re-run.

### "HTTP 4xx/5xx from `<url>`: ..."
**Cause:** the provider itself rejected the request — most commonly an invalid model id, an
invalid/expired API key, or a context-length overflow. The detail text in the error is the
provider's own response body, truncated to 500 characters.

**Fix:** see "Invalid Model Name" above for a bad model id; `docket keys rotate <KEY>` for a bad
credential; `docket maintain <agent-id> distill` (or `clean`/`reset`) if the context has grown
past what the model accepts.

### "docket doctor" flags a model but a turn otherwise succeeds
```bash
docket doctor          # look for the flagged stale/aliased model name
docket doctor --fix    # apply the fix
```

## Permission Denied Errors
**Fix:**
```bash
docket maintain <agent-id> check
```

This fixes:
- Workspace permissions (700 for dirs, 600 for files)
- Missing files
- Broken symlinks

## Telegram Issues

### Bot Not Receiving Messages
**Diagnose:**
```bash
# Is the bot actually in the group?
# Is TELEGRAM_BOT_TOKEN stored?
docket keys list

# Is a docket serve --telegram process actually running?
# (docket has no separate gateway process or log to check instead)
```

### Messages Not Being Sent
Since docket owns the Telegram integration directly, a send failure surfaces in whatever terminal
is running `docket serve --telegram` (or in `docket audit`/`docket trace` for the triggering
action), not in a separate daemon log.

**Fix:**
```bash
# Confirm the poller is actually running
docket serve --telegram

# Re-wire agent
docket unwire <agent-id>
docket wire <agent-id>
```

## Session/Scope Issues

### Agent Accessing Wrong Project
**Symptom:** Agent mentions files from other projects

**Cause:** Session key collision or incorrect scoping

**Fix:**
```bash
# Check current scope
docket scope <agent-id> show

# Set unique project scope
docket scope <agent-id> set my-project-name

# Or reset to default
docket scope <agent-id> reset
```

## Pods & Dispatch

### `docket pod <p> dispatch` does nothing / "No pending tasks"
There's nothing queued for the pod to run.
```bash
docket pod <p> delegate <task>     # quote only when shell metacharacters require it
docket pod <p> queue               # check what's pending
```

### A dispatched task stays "blocked" (budget cap reached)

Dispatch checks the pod's token-based dollar estimate against the Lead's budget cap before
*every* hop (docket's own turn loop reports no billed spend, so the gate always runs off this
estimate). Once the cap is reached, the task is left `blocked` (never silently retried or
rewritten back to `pending`) **and the pod's Lead is marked paused** — every further claim
against this pod is refused outright (`paused_refused`) until the pause is explicitly cleared,
not just re-blocked hop by hop:

```bash
$ docket pod myapp dispatch
  [task-c410e91a-...] blocked — pod budget reached ($5.12 ≥ $5.00) before implementer
```

Check the estimated spend, then either raise the cap or resume from the pause. Resuming a pod's
Lead also un-blocks every `blocked` task in that pod at once:

```bash
docket cost myapp-lead                    # see measured token usage
docket profile myapp-lead --budget <N>    # raise the cap (USD), if the spend is expected
docket profile myapp-lead --resume        # clear the auto-pause + unblock the pod's queue
# → Unblocked 1 budget-blocked task(s) in pod 'myapp'.
# ✓ Resumed 'myapp-lead' — auto-pause cleared.
```

To retry a single blocked task without touching the pod-wide pause, use `docket pod myapp queue
--retry <task-id>` instead — it moves just that task back to `pending`.

### A dispatched task fails with "verification_failed" / the verify command failed

The Implementer's hop is gated on its `verifyCmd` (if one is set — see `docket pod <p> add
--verify`/`set-verify`). A non-zero exit from that command fails the hop and leaves the task
`pending` with a `verification_failed` trace event; it is **not** retried automatically (only a
timeout or an endpoint hiccup on the *agent turn* itself is retried — a real, deterministic
non-zero exit or a bad verdict never is). Inspect the recorded output and either fix the
underlying failure or clear/adjust the gate:

```bash
docket trace tail <p>                       # see the verify command's (redacted) output
docket pod <p> set-verify <p>-implementer "npm test"   # change the gate command
docket pod <p> queue --retry <task-id>      # re-run once you believe it will pass
```

The command runs in the Implementer's git worktree when one exists, otherwise the pod's shared
codebase root — if it's failing only because it ran in the wrong directory, that's the first
thing to check.

### A task fails with "tester reported FAIL" (or an unparseable verdict)

The Tester gate is a structural PASS/FAIL parse of the first non-blank line of its reply. `FAIL`
or anything that doesn't parse as PASS/FAIL (`tester_verdict_failed`) fails the task outright —
there is no rework cycle for a Tester verdict (only a Reviewer's `REQUEST-CHANGES` gets one):

```bash
$ docket pod myapp dispatch
  [task-91a2c410-...] failed — tester reported FAIL
```

Read the Tester's full reply via `docket trace tail <p>`, fix the underlying issue, then requeue:

```bash
docket pod myapp queue --retry task-91a2c410-...
```

### "pod has no lead — cannot dispatch"
The pod is missing its Lead. A pod must have exactly one Lead, which orchestrates dispatch.
Recreate the pod:
```bash
docket add <p>
```

### The Portfolio Manager didn't appear
The org Portfolio Manager is opt-in — it isn't created by a plain `docket init`.
```bash
docket init --portfolio
```

### A pod member wasn't created
Inspect the pod and run diagnostics to find and fix the gap:
```bash
docket pod <p>     # list the pod's members
docket doctor      # system-wide diagnostics + auto-fix
```

### Implementer touching the wrong project?
Check its session key / scope, and reset if needed:
```bash
docket scope <p>-implementer show
docket scope <p>-implementer reset
grep "Session Key" ~/.docket/workspaces/projects/<p>-implementer/SOUL.md   # verify identity
```

### Leftover global `programmer`/`reviewer`/`tester`?
A pre-pods install may have left a shared worker workspace behind. `docket doctor` flags it and
backfills `scope` on legacy metadata — run it and follow its advice:
```bash
docket doctor
```

## Memory & Context

There is no per-agent `SNAPSHOT.md` or `.memory-index.json`, and `docket context` has no
`search`/`index`/`snapshot`/`compress` subcommand — those were removed because the per-agent
index/snapshot artifacts they wrote were read by nothing else (see
[Removed Commands](commands.md#removed-commands)). There is also no separate semantic memory
index today: docket's own turn loop has no `memory_search` tool of its own, so an agent searches
its memory files with the same `read`/`grep` tools it uses for anything else. The real per-agent
memory contract is: `WORKFLOW_AUTO.md` (the runtime-forced startup file, re-read after every
context reset), `HEARTBEAT.md` (the durable task ledger), `MEMORY.md`, and the dated
`memory/YYYY-MM-DD.md` logs.

### Agents still using large context?

1. **Get the real per-turn footprint estimate and distill if it's over budget:**

   ```bash
   docket maintain <agent-id> check     # look for the "Context footprint" line
   docket maintain <agent-id> distill   # summarize memory/*.md into MEMORY.md, archive originals
   ```

2. **Verify the fleet is healthy:**

   ```bash
   docket list
   docket doctor
   ```

### Agent stuck re-reading/re-creating its startup file, or ignoring HEARTBEAT.md on resume?

`docket doctor` re-seeds a missing or stale `WORKFLOW_AUTO.md` (the runtime's post-compaction
contract file — a weak model loops offering to (re)create this instead of working when it's
missing or carries an old contract-version marker):

```bash
docket doctor
# Runtime startup contract:
# ✓ myproject-implementer: seeded WORKFLOW_AUTO.md (codebase /home/user/code/myproject)
```

If HEARTBEAT.md itself looks wrong (not just the startup file), regenerate everything from
metadata instead:

```bash
docket maintain <agent-id> rebuild
```

## Getting Help

1. **Run diagnostics:**
   ```bash
   docket doctor
   ```

2. **Check logs:**
   ```bash
   docket logs <agent-id>       # latest memory log
   docket trace tail <project>  # live dispatch trace, if it's pod-related
   docket audit                 # recent docket-initiated changes
   ```

3. **Verify configuration:**
   ```bash
   docket info <agent-id>
   docket list
   ```

4. **Test agent:**
   ```bash
   # Send a test message in Telegram (if wired), or:
   docket pod <project> delegate "test task"
   docket pod <project> dispatch
   ```

5. **Emergency reset:**
   ```bash
   # If all else fails
   docket maintain <agent-id> rebuild
   ```
