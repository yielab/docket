# Example Configurations

Sample `.docket-meta.json` files demonstrating different agent setups.

## Files

### repo-agent-meta.json

Standard repository-based agent for active development.

- **Type**: `repo` (codebase-based)
- **Stack**: Node.js, React, TypeScript, PostgreSQL
- **Model**: `sonnet-4-6` (standard tier)
- **Use case**: Active web application development

**Create similar:**
```bash
docket add
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
docket add
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
docket add
# Create normally, then:
docket scope ecommerce set staging
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
docket add
# Choose: repo type
# Model: Premium (opus-4-6)

# Or upgrade existing:
docket profile myagent premium
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
~/.openclaw/workspaces/projects/<agent-id>/.docket-meta.json
```

**Example:**
```
~/.openclaw/workspaces/projects/mywebapp/.docket-meta.json
~/.openclaw/workspaces/projects/research/.docket-meta.json
```

## Accessing Metadata

### Via docket CLI

```bash
# View metadata (formatted)
docket info myagent

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

meta_file = "/home/user/.openclaw/workspaces/projects/myagent/.docket-meta.json"

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
cat ~/.openclaw/workspaces/projects/myagent/.docket-meta.json | jq -r '.name'

# Or use docket's helper
source /path/to/docket-cli/bin/docket
name=$(meta_get myagent name)
echo "$name"
```

## Syncing with OpenClaw

docket maintains two configuration sources:

1. **`.docket-meta.json`** (per-project) - Source of truth for docket
2. **`openclaw.json`** (global) - Source of truth for OpenClaw daemon

When you update metadata via docket, both are synced automatically:

```bash
# These commands update BOTH sources
docket profile myagent premium
docket profile myagent premium
docket scope myagent set alpha
```

**Manual sync (if needed):**
```bash
# If metadata gets out of sync, repair fixes it
docket repair myagent
```

## Custom Fields

You can add custom fields to `.docket-meta.json`:

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

**Note:** Custom fields won't appear in `docket info` output unless you modify the command.

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
   docket scope backend-api set production
   docket scope backend-api set staging
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
docket repair myagent
```

### Metadata out of sync

```bash
# Sync session keys and bindings
docket repair myagent
```

### Corrupted JSON

```bash
# Backup corrupted file
cp ~/.openclaw/workspaces/projects/myagent/.docket-meta.json \
   ~/.openclaw/workspaces/projects/myagent/.docket-meta.json.backup

# Deep reset (regenerates from openclaw.json)
docket reset myagent 3
```

### Permission errors

```bash
# Fix permissions (should be 600)
chmod 600 ~/.openclaw/workspaces/projects/myagent/.docket-meta.json

# Or use repair
docket repair myagent
```

## See Also

- [Architecture Documentation](../../docs/architecture.md)
- [Command Reference](../../docs/commands.md)
- [Development Guide](../../docs/development.md)
