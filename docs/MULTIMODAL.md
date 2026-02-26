# Multimodal Capabilities (Images & Video)

Your agents can already analyze images - just send them via Telegram! Claude Sonnet 4.6 has built-in vision.

## Add Image/Video Generation

Want your agent to **generate** images or videos? Just add an API key.

### 2-Step Setup

```bash
# 1. Make sure agent has vision model
rack model marketing anthropic/claude-sonnet-4-6

# 2. Add API key (stored centrally, synced to all agents)
rack keys add GOOGLE_AI_API_KEY
```

Get your key at: https://aistudio.google.com/

**That's it!** The key is stored in `~/.openclaw/secrets.json` and automatically synced to all agent workspaces. Claude already knows how to use curl and read environment variables - no manual configuration needed.

## How It Works

- **Vision**: Built-in with Sonnet 4.6 (free)
- **Generation**: Agent calls API when user asks
- **Cost**: ~$0.01-0.03 per image, ~$0.15 per 5sec video
- **Approval**: Agent will always ask before spending money
- **Central Storage**: One key, all agents can use it

Claude figures out when/how to call the API based on user requests.

## Example Usage

```
User: "Analyze this design" [sends image]
Agent: [Uses built-in vision - free]

User: "Generate a marketing banner"
Agent: "This will cost ~$0.01. Proceed?"
User: "Yes"
Agent: [Calls Imagen API, delivers image]
```

No special commands needed - it just works!

## Managing Keys

```bash
# Add a key
rack keys add GOOGLE_AI_API_KEY

# List all keys (values masked)
rack keys list

# Remove a key
rack keys remove GOOGLE_AI_API_KEY
```

Keys are automatically synced to all agent `.env` files whenever you add/remove them.

## Available APIs

| Service | Cost | Quality | Get Key |
| --- | --- | --- | --- |
| Google Imagen 3 | $0.01/img | Excellent | <https://aistudio.google.com/> |
| Google Veo | $0.15/5sec | Best video | <https://aistudio.google.com/> |
| OpenAI DALL-E 3 | $0.04/img | Good | <https://platform.openai.com/> |

## Technical Details

- **Storage**: `~/.openclaw/secrets.json` (600 permissions, secure)
- **Distribution**: Auto-synced to `<workspace>/.env` for each agent
- **Gateway**: Restarts automatically after key changes
- **Scope**: All agents have access to all keys

This centralized approach makes key management simple and clear - no need to edit individual agent files!
