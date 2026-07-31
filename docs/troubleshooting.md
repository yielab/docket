# Troubleshooting Guide

## Agents Not Responding in Telegram

### Symptom
Agents don't respond to messages in Telegram groups, even though they're registered and wired.

### Common Causes

#### 1. **Invalid Model Name** (MOST COMMON)
**Error in logs:** `FailoverError: Unknown model: anthropic/claude-haiku-3-5`

**Root cause:** OpenClaw config has invalid model names (e.g., `haiku-3-5` instead of `haiku-4-5`)

**How to diagnose:**
```bash
docket doctor
# Look for "Model Configuration" section
```

**How to fix:**
```bash
# Auto-fix with docket (updates openclaw.json through the proper interface)
docket doctor

# Or update each agent's model individually
docket profile <agent-id> anthropic/claude-haiku-4-5

# Re-resolve all policy-following agents at once
docket models preset anthropic

# Restart gateway after changes
systemctl --user restart openclaw-gateway
```

> **Never edit `~/.openclaw/openclaw.json` directly.** All writes to that file must go through
> docket commands — direct edits bypass the Anti-Corruption Layer and can leave config in an
> inconsistent state that `docket doctor` will flag as an error.

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

#### 3. **Group Not in Allowlist**
**Error in logs:** `{"reason":"not-allowed", "chatId":-1001234567890}`

**How to diagnose:**
```bash
# Check which groups are wired to agents
docket list
# Look for agents with "✓ Wired" and matching group IDs
```

**How to fix:**
```bash
docket wire <agent-id>
# This automatically adds the group to the allowlist via the proper config interface
```

#### 4. **Gateway Not Running**
**How to diagnose:**
```bash
systemctl --user status openclaw-gateway
```

**How to fix:**
```bash
systemctl --user start openclaw-gateway
```

## High Costs / Context Bloat

### Symptom
Session costs $28+ from massive cache reads (21M+ tokens)

### Root Cause
OpenClaw keeps full conversation history in context. With 258+ turns, cached context grows to 2.4MB.

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

#### 3. **Monitor Costs**
```bash
docket cost <agent-id>
docket cost  # All agents
```

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

## Model Errors

### Invalid Model Name
**Error:** `Unknown model: anthropic/claude-haiku-3-5`
**Fix:** See "Agents Not Responding" → "Invalid Model Name" above

### Model Fallback Not Working
**Issue:** OpenClaw v2026.2.23 doesn't support custom fallback config

**Workaround:** Use docket's model validation:
```bash
# Validate all models
docket doctor

# Auto-fix invalid models
docket doctor --fix
```

## Gateway Crashes

### Config Validation Error
**Error:** `Unrecognized keys: contextPruning, compaction`

**Cause:** Trying to use config keys not supported in OpenClaw v2026.2.23

**Fix:**
```bash
openclaw doctor --fix
systemctl --user restart openclaw-gateway
```

### Permission Denied Errors
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
# Check if bot is in group
# Check if gateway is running
systemctl --user status openclaw-gateway

# Check recent logs
tail -100 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep telegram
```

### Messages Not Being Sent
**Check logs for:**
- Rate limiting: `"rate_limited"`
- API errors: `"telegram.*error"`
- Send failures: `"send.*fail"`

**Fix:**
```bash
# Restart gateway
systemctl --user restart openclaw-gateway

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
docket pod <p> delegate "<task>"   # queue a task first
docket pod <p> queue               # check what's pending
```

### A dispatched task stays "blocked" (budget cap reached)

Dispatch checks the pod's recorded (or estimated) spend against the Lead's budget cap before
*every* hop. Once the cap is reached, the task is left `blocked` (never silently retried or
rewritten back to `pending`) **and the pod's Lead is marked paused** — every further claim
against this pod is refused outright (`paused_refused`) until the pause is explicitly cleared,
not just re-blocked hop by hop:

```bash
$ docket pod myapp dispatch
  [task-c410e91a-...] blocked — pod budget reached ($5.12 ≥ $5.00) before implementer
```

Check the recorded spend, then either raise the cap or resume from the pause. Resuming a pod's
Lead also un-blocks every `blocked` task in that pod at once:

```bash
docket cost myapp-lead                    # see recorded spend
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
timeout or a daemon hiccup on the *agent turn* itself is retried — a real, deterministic
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
The org Portfolio Manager is opt-in — it isn't created by a plain `docket install`.
```bash
docket install --portfolio
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
grep "Session Key" ~/.openclaw/workspaces/projects/<p>-implementer/SOUL.md   # verify identity
```

### Leftover global `programmer`/`reviewer`/`tester`?
A pre-pods install may have left a shared worker workspace behind. `docket doctor` flags it and
backfills `scope` on legacy metadata — run it and follow its advice:
```bash
docket doctor
```

## Memory & Context

There is no per-agent `SNAPSHOT.md` or `.memory-index.json`, and `docket context` has no
`search`/`index`/`snapshot`/`compress` subcommand — those were removed (the OpenClaw runtime
does semantic memory search itself; see [Removed Commands](commands.md#removed-commands)). The
real per-agent memory contract is: `WORKFLOW_AUTO.md` (the runtime-forced startup file, re-read
after every context reset), `HEARTBEAT.md` (the durable task ledger), `MEMORY.md`, and the dated
`memory/YYYY-MM-DD.md` logs.

### Agents still using large context?

1. **Get the real per-turn footprint estimate and distill if it's over budget:**

   ```bash
   docket maintain <agent-id> check     # look for the "Context footprint" line
   docket maintain <agent-id> distill   # summarize memory/*.md into MEMORY.md, archive originals
   ```

2. **Verify the fleet is healthy, then restart:**

   ```bash
   docket list
   docket doctor
   systemctl --user restart openclaw-gateway.service
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
   openclaw doctor
   ```

2. **Check logs:**
   ```bash
   docket logs <agent-id>
   journalctl --user -u openclaw-gateway --since "1 hour ago"
   ```

3. **Verify configuration:**
   ```bash
   docket info <agent-id>
   docket list
   ```

4. **Test agent:**
   ```bash
   # Send test message in Telegram group
   # Agent should respond within 5-10 seconds
   ```

5. **Emergency reset:**
   ```bash
   # If all else fails
   docket maintain <agent-id> rebuild
   systemctl --user restart openclaw-gateway
   ```
