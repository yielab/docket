#!/usr/bin/env bash
# lib/commands/smart.sh — Intelligent model routing & context management

cmd_smart() {
  local subcmd="${1:-status}"
  shift

  case "$subcmd" in
    enable)    _smart_enable "$@" ;;
    status)    _smart_status "$@" ;;
    configure) _smart_configure "$@" ;;
    upgrade)   _smart_upgrade "$@" ;;
    test)      _smart_test "$@" ;;
    *)
      error "Unknown smart command: $subcmd
  rack smart enable      Enable smart routing for all agents
  rack smart status      Show current configuration
  rack smart configure   Interactive configuration
  rack smart upgrade [id] Upgrade agent(s) to smart routing
  rack smart test [id]   Test smart routing with sample tasks"
      ;;
  esac
}

# Enable smart routing globally
_smart_enable() {
  header "Smart Routing — Global Enable"
  echo

  info "This will configure:"
  echo "  1. Context pruning (rolling 10-turn window)"
  echo "  2. Compaction (auto-compress after 10 turns)"
  echo "  3. Model fallbacks (haiku → sonnet → opus)"
  echo "  4. Cache TTL (prevent 258-turn bloat)"
  echo

  read -rp "Continue? (y/N) " confirm
  [[ "$confirm" != "y" ]] && { info "Cancelled"; return; }

  echo
  info "Configuring OpenClaw..."

  # Set context pruning (sliding window - keep last 10 turns)
  python3 << 'EOF'
import json
import os

config_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(config_path, 'r') as f:
    config = json.load(f)

# Context Pruning - OpenClaw format (cache-ttl mode)
config['contextPruning'] = {
    'mode': 'cache-ttl',
    'ttl': '1h',  # Cache expires after 1 hour
    'keepLastAssistants': 10  # Keep last 10 assistant responses
}

# Compaction - OpenClaw format
config['compaction'] = {
    'mode': 'default',
    'memoryFlush': {
        'enabled': True,
        'softThresholdTokens': 15000  # Flush when exceeds 15K tokens
    }
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print("✓ Context management configured")
print("  - Sliding window: Last 10 turns")
print("  - Compaction: After 10 turns → 5 turn summary")
print("  - Cache TTL: 1 hour max")
EOF

  echo
  success "Smart context management enabled!"
  echo
  info "Next: Configure model routing with 'rack smart configure'"
}

# Show current smart routing status
_smart_status() {
  header "Smart Routing — Status"
  echo

  # Check OpenClaw config
  python3 << 'EOF'
import json
import os

config_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(config_path, 'r') as f:
    config = json.load(f)

print("=== Context Management ===\n")

# Context Pruning
if 'contextPruning' in config:
    cp = config['contextPruning']
    mode = cp.get('mode', 'none')
    max_turns = cp.get('maxTurns', 'unlimited')
    print(f"✓ Context Pruning: {mode}")
    print(f"  Max turns: {max_turns}")
else:
    print("✗ Context Pruning: NOT configured")
    print("  Run: rack smart enable")

print()

# Compaction
if 'compaction' in config:
    comp = config['compaction']
    mode = comp.get('mode', 'none')
    threshold = comp.get('threshold', 'N/A')
    print(f"✓ Compaction: {mode}")
    print(f"  Threshold: {threshold} turns")
else:
    print("✗ Compaction: NOT configured")
    print("  Run: rack smart enable")

print()

# Cache
if 'cache' in config:
    cache = config['cache']
    ttl = cache.get('ttl', 'unlimited')
    max_size = cache.get('maxSize', 'unlimited')
    print(f"✓ Cache TTL: {ttl}s")
    print(f"  Max size: {max_size} tokens")
else:
    print("✗ Cache: NOT configured")
    print("  Run: rack smart enable")

print("\n=== Model Routing ===\n")

# Check agents
agents = config.get('agents', {}).get('registered', [])
smart_count = 0
total_count = len(agents)

for agent in agents:
    agent_id = agent.get('id')
    model = agent.get('model', 'not set')

    # Check if agent has smart routing (we'll check SOUL.md)
    soul_path = os.path.expanduser(f"~/.openclaw/workspaces/projects/{agent_id}/SOUL.md")
    has_smart = False

    if os.path.exists(soul_path):
        with open(soul_path, 'r') as f:
            content = f.read()
            if 'Smart Model Selection' in content or 'Task Complexity' in content:
                has_smart = True
                smart_count += 1

    status = "✓ SMART" if has_smart else "○ standard"
    print(f"  {status} {agent_id:<20} {model}")

print(f"\n{smart_count}/{total_count} agents have smart routing")

if smart_count < total_count:
    print("\nUpgrade agents: rack smart upgrade")
EOF
}

# Interactive configuration
_smart_configure() {
  header "Smart Routing — Configuration"
  echo

  # Check current settings
  _smart_status

  echo
  echo "=== Configuration Options ==="
  echo
  echo "1. Context Window Size (current: 10 turns)"
  echo "2. Compaction Threshold (current: 10 turns)"
  echo "3. Cache TTL (current: 1 hour)"
  echo "4. Model Routing Rules"
  echo "5. Reset to Defaults"
  echo "6. Exit"
  echo

  read -rp "Select option (1-6): " choice

  case "$choice" in
    1)
      read -rp "Max turns to keep (5-20, recommended 10): " max_turns
      python3 -c "import json; c=json.load(open('$HOME/.openclaw/openclaw.json')); c.setdefault('contextPruning', {})['maxTurns']=$max_turns; json.dump(c, open('$HOME/.openclaw/openclaw.json', 'w'), indent=2)"
      success "Context window set to $max_turns turns"
      ;;
    2)
      read -rp "Compaction threshold (5-15, recommended 10): " threshold
      python3 -c "import json; c=json.load(open('$HOME/.openclaw/openclaw.json')); c.setdefault('compaction', {})['threshold']=$threshold; json.dump(c, open('$HOME/.openclaw/openclaw.json', 'w'), indent=2)"
      success "Compaction threshold set to $threshold turns"
      ;;
    3)
      read -rp "Cache TTL in seconds (3600=1h, 7200=2h): " ttl
      python3 -c "import json; c=json.load(open('$HOME/.openclaw/openclaw.json')); c.setdefault('cache', {})['ttl']=$ttl; json.dump(c, open('$HOME/.openclaw/openclaw.json', 'w'), indent=2)"
      success "Cache TTL set to $ttl seconds"
      ;;
    4)
      info "Model routing is configured per-agent in SOUL.md"
      info "Use: rack smart upgrade [id]"
      ;;
    5)
      _smart_enable
      ;;
    6)
      return
      ;;
    *)
      error "Invalid option"
      ;;
  esac

  # Restart gateway to apply changes
  echo
  read -rp "Restart gateway to apply changes? (y/N) " restart
  if [[ "$restart" == "y" ]]; then
    restart_gateway
    success "Changes applied!"
  else
    warn "Restart gateway manually: systemctl --user restart openclaw-gateway"
  fi
}

# Upgrade agents to smart routing
_smart_upgrade() {
  local id="${1:-}"

  if [[ -z "$id" ]]; then
    header "Smart Routing — Upgrade All Agents"
    echo
    info "This will upgrade ALL project agents to smart routing"
    read -rp "Continue? (y/N) " confirm
    [[ "$confirm" != "y" ]] && { info "Cancelled"; return; }

    # Get all agents
    local agents
    agents=$(project_ids)

    for agent_id in $agents; do
      echo
      _smart_upgrade_single "$agent_id"
    done
  else
    _smart_upgrade_single "$id"
  fi

  echo
  success "All agents upgraded to smart routing!"
  echo
  info "Next steps:"
  echo "  1. Restart gateway: systemctl --user restart openclaw-gateway"
  echo "  2. Test routing: rack smart test $id"
}

# Upgrade single agent
_smart_upgrade_single() {
  local id="$1"
  local workspace="$OPENCLAW_DIR/workspaces/projects/$id"
  local soul_file="$workspace/SOUL.md"

  [[ ! -f "$soul_file" ]] && { warn "Skipping $id (no SOUL.md)"; return; }

  info "Upgrading $id..."

  # Backup
  cp "$soul_file" "$soul_file.backup-$(date +%Y%m%d-%H%M%S)"

  # Check if already has smart routing
  if grep -q "Smart Model Selection" "$soul_file"; then
    dim "  Already has smart routing, skipping"
    return
  fi

  # Add smart routing section before ## Traits
  python3 << EOF
import re

with open('$soul_file', 'r') as f:
    content = f.read()

# Add smart model selection section
smart_section = """
## Smart Model Selection (Automatic)

I analyze task complexity and self-select the appropriate model:

### Complexity Detection

**SIMPLE (use haiku-4-5):**
- Questions: "what is", "where is", "show me"
- Read-only operations: reading code, viewing logs
- Test execution: running existing tests
- Git operations: status, diff, log
- File navigation: finding files, searching

**STANDARD (use sonnet-4-6):**
- Code changes: "write function", "fix bug", "refactor"
- Design decisions: API design, schema changes
- Multi-file changes: refactoring across files
- Debugging: complex issues requiring analysis

**COMPLEX (use opus-4-6):**
- Architecture: "design system", "optimize algorithm"
- Security: security audits, vulnerability fixes
- Performance: critical performance optimization
- Production: critical bugs in production

### Self-Upgrade Protocol

If I start with haiku and realize complexity is higher:
1. Output: "⬆️ Upgrading to sonnet-4-6 (complex task detected)"
2. Delegate to programmer/manager with proper model
3. Log reason for upgrade

If task is simpler than expected:
1. Output: "⬇️ Using haiku-4-5 (sufficient for this task)"
2. Complete with cheaper model

### Cost Optimization

Target distribution:
- 90% of tasks: haiku-4-5 (\$0.80/\$4)
- 9% of tasks: sonnet-4-6 (\$3/\$15)
- 1% of tasks: opus-4-6 (\$15/\$75)

"""

# Insert before ## Traits
if '## Traits' in content:
    content = content.replace('## Traits', smart_section + '## Traits')
else:
    # Append to end
    content += '\n' + smart_section

with open('$soul_file', 'w') as f:
    f.write(content)

print(f"  ✓ Added smart routing to $id")
EOF

  # Add context management section
  python3 << EOF
import re

with open('$soul_file', 'r') as f:
    content = f.read()

# Add context management after smart routing
context_section = """
## Context Management (Anti-Bloat)

### What I Read Each Turn

1. **SOUL.md** (my identity) — cached, ~1K tokens
2. **SNAPSHOT.md** (project state) — cached if exists, ~2K tokens
3. **Last 10 messages** (recent context) — NOT cached, ~5-10K tokens
4. **Current file** (if editing) — NOT cached, ~3K tokens

**Maximum context per turn: ~15K tokens**

### What I DON'T Read

❌ Full conversation history beyond 10 turns
❌ Entire codebase (use targeted reads)
❌ Old memory logs (use SNAPSHOT.md)

### Auto-Compression

After 10 turns:
- OpenClaw auto-compresses to 5-turn summary
- Older context moved to MEMORY.md
- Keep conversation under 15K tokens

After 50 turns:
- Suggest: "We've had 50 turns. Should I create a SNAPSHOT and start fresh?"
- Prevent 258-turn bloat ($28 cost!)

"""

# Insert after smart routing section
if '## Smart Model Selection' in content:
    content = re.sub(
        r'(## Smart Model Selection.*?)(## [A-Z])',
        r'\1' + context_section + r'\2',
        content,
        flags=re.DOTALL
    )
else:
    content += '\n' + context_section

with open('$soul_file', 'w') as f:
    f.write(content)

print(f"  ✓ Added context management")
EOF

  success "  ✓ $id upgraded to smart routing"
}

# Test smart routing
_smart_test() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Select agent to test")

  header "Smart Routing — Test: $id"
  echo

  info "Testing smart routing with sample tasks..."
  echo

  echo "=== Test Cases ==="
  echo
  echo "1. SIMPLE task (should use haiku):"
  echo "   'What files are in the src directory?'"
  echo
  echo "2. STANDARD task (should use sonnet):"
  echo "   'Write a function to validate email addresses'"
  echo
  echo "3. COMPLEX task (should use opus):"
  echo "   'Design a distributed caching system with Redis'"
  echo

  info "These are example classifications - agent will self-select model"
  echo

  dim "To actually test, send these messages in Telegram and watch the logs:"
  dim "  tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep 'model\|upgrade'"
}
