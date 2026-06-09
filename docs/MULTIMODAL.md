# Multimodal Capabilities (Images & Video)

## Agent Types Overview

**Important**: Understand the two types of agents in your system:

### Specialist Agents (The Team)
Created automatically by `rack install` - shared across all projects:
- **programmer** - Writes code for any project
- **reviewer** - Reviews code quality
- **tester** - Runs tests
- **knowledge** - Documentation & research
- **security** - Security audits
- **manager** - Coordinates team tasks

### Project Agents
Created by `rack add` - one per project/codebase:
- **mywebsite** - Your website project
- **mobile-app** - Your mobile app
- **content-blog** - Your blog
- etc.

**Use project agents for multimodal**, not specialists. Each project agent works on ONE specific project.

---

## Vision (Analyze Images)

All agents with Claude Sonnet 4.6+ can **already analyze images** - just send them via Telegram!

```bash
# Ensure your project agent has a vision-capable model
rack profile mywebsite standard
```

Send an image in Telegram → agent analyzes it. No setup needed!

---

## Generation (Create Images & Videos)

Want your **project agent** to **generate** images or videos? Add an API key.

### 2-Step Setup

```bash
# 1. Ensure project agent has vision model (required for image understanding)
rack profile mywebsite standard

# 2. Add API key (stored centrally, available to ALL agents)
rack keys add GOOGLE_AI_API_KEY
```

**Get your free key**: https://aistudio.google.com/
- Sign in with Google account
- Click "Get API key" → "Create API key"
- Copy and paste when prompted

**That's it!** Claude already knows how to:
- Read API keys from environment variables
- Call Google Imagen 3 / Veo APIs using curl
- Ask for your approval before spending money

No manual SOUL.md editing required.

---

## How It Works

When you add a key with `rack keys`, the system:
1. Stores it securely in `~/.openclaw/secrets.json` (600 permissions)
2. Syncs it to ALL agent `.env` files automatically
3. Restarts the OpenClaw gateway

Your project agents can then use the key without any additional configuration.

- **Vision**: Built-in with Sonnet 4.6 (free)
- **Generation**: Agent calls API when you request it
- **Cost**: ~$0.01-0.03 per image, ~$0.15 per 5sec video
- **Approval**: Agent always asks before generating (costs money)
- **Scope**: All agents share the same API keys

---

## Example Usage

**User** (in Telegram): *[sends screenshot of design]*
**mywebsite agent**: "This design uses a clean card layout with good spacing..."

**User**: "Generate a hero image for our homepage - mountains at sunset"
**mywebsite agent**: "This will use Google Imagen 3 (~$0.01). Proceed?"
**User**: "Yes"
**mywebsite agent**: *[generates and sends image]*

No special commands needed - natural conversation!

---

## Managing Keys

```bash
# Add a key (prompts securely for value)
rack keys add GOOGLE_AI_API_KEY

# List all keys (values masked for security)
rack keys list

# Remove a key (prompts for confirmation)
rack keys remove GOOGLE_AI_API_KEY
```

Keys automatically sync to all agent workspaces when you add/remove them.

---

## Available APIs

| Service | Cost | Quality | Best For | Get Key |
| --- | --- | --- | --- | --- |
| **Google Imagen 3** | $0.01/img | Excellent | Marketing, design, general | <https://aistudio.google.com/> |
| **Google Veo** | $0.15/5sec | Best video | Video content, demos | <https://aistudio.google.com/> |
| **OpenAI DALL-E 3** | $0.04/img | Good | Alternative to Imagen | <https://platform.openai.com/> |

All keys support the same format: `rack keys add <KEY_NAME>`

---

## Common Questions

### Q: Which agent should I enable multimodal for?

**A:** Your **project agents** (created with `rack add`), NOT specialist agents.

✅ **Good**: `rack profile mywebsite standard (project agent)
❌ **Wrong**: `rack profile programmer standard (specialist - shared across all projects)

### Q: Can multiple project agents use images?

**A:** Yes! All project agents share the same API keys. Just ensure each has Sonnet 4.6:

```bash
rack profile mywebsite standard
rack profile mobile-app standard
rack profile content-blog standard
```

### Q: Do I need to edit SOUL.md or IDENTITY.md?

**A:** No! Claude already knows:
- How to read environment variables
- How to call Google APIs with curl
- When to ask for approval before spending money

### Q: Can specialist agents generate images?

**A:** Technically yes (they share the keys), but you probably don't want this. Specialists like `programmer` and `reviewer` work across all projects - keep multimodal in project-specific agents.

---

## Technical Details

- **Storage**: `~/.openclaw/secrets.json` (600 permissions, user-only access)
- **Distribution**: Auto-synced to `<workspace>/.env` for each agent
- **Gateway**: Restarts automatically after key changes to load new environment
- **Security**: Never committed to git, never shown in logs
- **Scope**: All agents (both specialist and project) have access to all keys

This centralized approach keeps key management simple, secure, and transparent!
