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
# Check for invalid models
grep -i "haiku-3-5\|haiku-3\|sonnet-3-5" ~/.openclaw/openclaw.json

# Auto-fix with docket
docket doctor --fix

# Manual fix
python3 << 'EOF'
import json, os
config_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(config_path, 'r') as f:
    config = json.load(f)
config_str = json.dumps(config, indent=2)
fixed = config_str.replace('haiku-3-5', 'haiku-4-5')
fixed = fixed.replace('haiku-3', 'haiku-4-5')
fixed = fixed.replace('sonnet-3-5', 'sonnet-4-6')
with open(config_path, 'w') as f:
    f.write(fixed)
EOF

# Restart gateway
systemctl --user restart openclaw-gateway
```

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
**Error in logs:** `{"reason":"not-allowed", "chatId":-4857844358}`

**How to diagnose:**
```bash
python3 << 'EOF'
import json, os
config = json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))
groups = config.get('channels', {}).get('telegram', {}).get('groups', {})
print("Allowed groups:")
for gid, settings in groups.items():
    print(f"  {gid}: {settings}")
EOF
```

**How to fix:**
```bash
docket wire <agent-id>
# This automatically adds group to allowlist
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

#### 2. **Enable Smart Routing** (Auto model selection)
```bash
docket smart enable <agent-id>
```

This adds automatic model selection to SOUL.md:
- 90% of tasks use haiku-4-5 ($0.80/$4/MTok)
- 9% use sonnet-4-6 ($3/$15/MTok)
- 1% use opus-4-6 ($15/$75/MTok)

#### 3. **Monitor Costs**
```bash
docket cost <agent-id>
docket cost  # All agents
```

#### 4. **Context Management** (Manual)
Add to agent's SOUL.md:
```markdown
## Context Management

What I Read Each Turn:
1. SOUL.md (~1K) - cached
2. SNAPSHOT.md (~2K) - cached
3. Last 10 messages (~5-10K) - NOT cached
4. Current file (~3K) - NOT cached

Max context: ~15K tokens

Auto-Compression:
- After 10 turns: compress to summary
- After 50 turns: suggest reset
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

### A dispatched task stays "pending" (blocked)
The pod is over its budget cap — dispatch is budget-gated before each hop, so an over-budget pod
leaves the task pending instead of running it. Check or raise the Lead's cap:
```bash
docket cost <p>-lead               # see recorded spend
docket profile <p>-lead --budget <N>   # raise the cap (USD)
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
