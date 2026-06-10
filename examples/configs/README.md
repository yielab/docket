# Example Configurations

Sample `.rack-meta.json` files demonstrating different agent setups.

## Files

### repo-agent-meta.json

Standard repository-based agent for active development.

- **Type**: `repo` (codebase-based)
- **Stack**: Node.js, React, TypeScript, PostgreSQL
- **Model**: `sonnet-4-6` (standard tier)
- **Use case**: Active web application development

**Create similar:**
```bash
rack add
# Choose: repo type
# Stack: Auto-detected or manual entry
# Model: Standard (sonnet-4-6)
```

---

### task-agent-meta.json

General-purpose task agent without a specific codebase.

- **Type**: `task` (general work)
- **Stack**: General purpose
- **Model**: `haiku-4-5` (economy tier)
- **Use case**: Research, documentation, coordination

**Create similar:**
```bash
rack add
# Choose: task type
# Model: Economy (haiku-4-5)
```

---

### multi-project-agent-meta.json

Agent with session scoping for multi-environment work.

- **Type**: `repo`
- **Session Key**: `agent:ecommerce:staging`
- **Project Key**: `staging`
- **Use case**: Isolating staging work from production

**Create similar:**
```bash
rack add
# Create normally, then:
rack scope ecommerce set staging
```

**Why use session scoping?**
- Prevents mixing staging and production context
- Enables parallel work on different branches
- Isolates memory and task history

---

### premium-agent-meta.json

High-cost agent for complex tasks requiring Opus.

- **Type**: `repo`
- **Model**: `opus-4-6` (premium tier)
- **Use case**: Complex security analysis, architecture design

**Create similar:**
```bash
rack add
# Choose: repo type
# Model: Premium (opus-4-6)

# Or upgrade existing:
rack profile myagent premium
```

**When to use Opus:**
- Complex architecture decisions
- Security threat modeling
- Advanced debugging
- Large-scale refactoring

---

## Metadata Field Reference

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `type` | string | Agent type: `repo` or `task` | `"repo"` |
| `name` | string | Display name | `"My Project"` |
| `codebase` | string | Absolute path to codebase | `"/home/user/Sites/myapp"` |
| `stack` | string | Tech stack (comma-separated) | `"Node.js, React"` |
| `model` | string | Full model identifier | `"anthropic/claude-sonnet-4-6"` |
| `description` | string | Optional description | `"My awesome project"` |
| `created` | string | ISO 8601 timestamp | `"2026-02-25T10:00:00Z"` |
| `sessionKey` | string | Session coordinate | `"agent:myapp:default"` |
| `projectKey` | string | Project scope key | `"default"` |
| `notes` | string | Optional notes (custom field) | `"Using staging scope"` |

## Location

Metadata files are stored in each agent's workspace:

```
~/.openclaw/workspaces/projects/<agent-id>/.rack-meta.json
```

**Example:**
```
~/.openclaw/workspaces/projects/mywebapp/.rack-meta.json
~/.openclaw/workspaces/projects/research/.rack-meta.json
```

## Accessing Metadata

### Via rack CLI

```bash
# View metadata (formatted)
rack info myagent

# Read specific field (programmatic)
meta_get myagent name
meta_get myagent model
meta_get myagent sessionKey

# Update field (programmatic)
meta_set myagent description "New description"
```

### Via Python

```python
import json

meta_file = "/home/user/.openclaw/workspaces/projects/myagent/.rack-meta.json"

# Read
with open(meta_file) as f:
    meta = json.load(f)
    print(meta["name"])
    print(meta["model"])

# Write
meta["description"] = "Updated description"
with open(meta_file, 'w') as f:
    json.dump(meta, f, indent=2)
```

### Via Bash

```bash
# Read (requires jq)
cat ~/.openclaw/workspaces/projects/myagent/.rack-meta.json | jq -r '.name'

# Or use rack's helper
source /path/to/rack-cli/bin/rack
name=$(meta_get myagent name)
echo "$name"
```

## Syncing with OpenClaw

rack maintains two configuration sources:

1. **`.rack-meta.json`** (per-project) - Source of truth for rack
2. **`openclaw.json`** (global) - Source of truth for OpenClaw daemon

When you update metadata via rack, both are synced automatically:

```bash
# These commands update BOTH sources
rack profile myagent premium
rack profile myagent premium
rack scope myagent set alpha
```

**Manual sync (if needed):**
```bash
# If metadata gets out of sync, repair fixes it
rack repair myagent
```

## Custom Fields

You can add custom fields to `.rack-meta.json`:

```json
{
  "type": "repo",
  "name": "My Project",
  "model": "anthropic/claude-sonnet-4-6",

  "customField": "custom value",
  "tags": ["web", "production"],
  "owner": "john@example.com",
  "lastDeployment": "2026-02-20T15:30:00Z"
}
```

**Access via helpers:**
```bash
meta_get myagent customField
meta_set myagent owner "jane@example.com"
```

**Note:** Custom fields won't appear in `rack info` output unless you modify the command.

## Best Practices

1. **Use descriptive names**: Make agent purpose clear
   ```json
   "name": "E-commerce Backend API"  // Good
   "name": "Project 1"                // Bad
   ```

2. **Keep descriptions current**: Update as project evolves
   ```bash
   meta_set myagent description "New focus: migration to microservices"
   ```

3. **Use session scoping**: Isolate different environments
   ```bash
   rack scope backend-api set production
   rack scope backend-api set staging
   ```

4. **Choose appropriate models**: Match cost to task complexity
   - Haiku (economy): Simple tasks, triage, documentation
   - Sonnet (standard): Active development, code review
   - Opus (premium): Architecture, security, complex debugging

5. **Document custom fields**: Add comments in description
   ```json
   {
     "description": "Payment processing service. Custom field 'pciCompliant' tracks compliance status.",
     "pciCompliant": true
   }
   ```

## Troubleshooting

### Metadata file missing

```bash
# Regenerate from OpenClaw config
rack repair myagent
```

### Metadata out of sync

```bash
# Sync session keys and bindings
rack repair myagent
```

### Corrupted JSON

```bash
# Backup corrupted file
cp ~/.openclaw/workspaces/projects/myagent/.rack-meta.json \
   ~/.openclaw/workspaces/projects/myagent/.rack-meta.json.backup

# Deep reset (regenerates from openclaw.json)
rack reset myagent 3
```

### Permission errors

```bash
# Fix permissions (should be 600)
chmod 600 ~/.openclaw/workspaces/projects/myagent/.rack-meta.json

# Or use repair
rack repair myagent
```

## See Also

- [Architecture Documentation](../../docs/architecture.md)
- [Command Reference](../../docs/commands.md)
- [Development Guide](../../docs/development.md)
