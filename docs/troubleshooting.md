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
rack doctor
# Look for "Model Configuration" section
```

**How to fix:**
```bash
# Check for invalid models
grep -i "haiku-3-5\|haiku-3\|sonnet-3-5" ~/.openclaw/openclaw.json

# Auto-fix with rack
rack doctor --fix

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

**Valid model names:**
- `anthropic/claude-haiku-4-5` (economy)
- `anthropic/claude-sonnet-4-6` (standard)
- `anthropic/claude-opus-4-6` (premium)

#### 2. **Missing Telegram Bindings**
**How to diagnose:**
```bash
rack list
# Check if agent shows "● telegram" with group ID
```

**How to fix:**
```bash
rack wire <agent-id>
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
rack wire <agent-id>
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
rack maintain <agent-id> clean

# Level 2: Clear memory + HEARTBEAT.md
rack maintain <agent-id> reset

# Level 3: Deep reset - regenerate all from metadata
rack maintain <agent-id> rebuild
```

#### 2. **Enable Smart Routing** (Auto model selection)
```bash
rack smart enable <agent-id>
```

This adds automatic model selection to SOUL.md:
- 90% of tasks use haiku-4-5 ($0.80/$4/MTok)
- 9% use sonnet-4-6 ($3/$15/MTok)
- 1% use opus-4-6 ($15/$75/MTok)

#### 3. **Monitor Costs**
```bash
rack cost <agent-id>
rack cost  # All agents
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

**Workaround:** Use rack's model validation:
```bash
# Validate all models
rack doctor

# Auto-fix invalid models
rack doctor --fix
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
rack maintain <agent-id> check
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
rack unwire <agent-id>
rack wire <agent-id>
```

## Session/Scope Issues

### Agent Accessing Wrong Project
**Symptom:** Agent mentions files from other projects

**Cause:** Session key collision or incorrect scoping

**Fix:**
```bash
# Check current scope
rack scope <agent-id> show

# Set unique project scope
rack scope <agent-id> set my-project-name

# Or reset to default
rack scope <agent-id> reset
```

## Getting Help

1. **Run diagnostics:**
   ```bash
   rack doctor
   openclaw doctor
   ```

2. **Check logs:**
   ```bash
   rack logs <agent-id>
   journalctl --user -u openclaw-gateway --since "1 hour ago"
   ```

3. **Verify configuration:**
   ```bash
   rack info <agent-id>
   rack list
   ```

4. **Test agent:**
   ```bash
   # Send test message in Telegram group
   # Agent should respond within 5-10 seconds
   ```

5. **Emergency reset:**
   ```bash
   # If all else fails
   rack maintain <agent-id> rebuild
   systemctl --user restart openclaw-gateway
   ```
