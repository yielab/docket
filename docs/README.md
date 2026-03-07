# rack Documentation

**rack** is a production-ready CLI for managing OpenClaw autonomous agent teams with RACK architecture.

---

## Quick Links

- **New to rack?** → Start with [Quick Start Guide](QUICK-START-RACK.md) (5 minutes)
- **Need examples?** → See [Workflow Guide](WORKFLOW-GUIDE.md) (complete examples)
- **Security questions?** → Read [Security Model](SECURITY-SIMPLE.md) (automatic & simple)
- **Command reference?** → Check [Commands](commands.md) (all commands explained)

---

## Documentation Structure

### 🚀 Getting Started

**[Quick Start Guide](QUICK-START-RACK.md)** - 5-minute setup
- Install rack + OpenClaw
- Upgrade to RACK architecture
- Create your first project agent
- Assign work and review results

### 📖 Core Guides

**[Workflow Guide](WORKFLOW-GUIDE.md)** - Complete workflow examples
- Project agents vs. specialist agents
- Two workflow models (direct vs. via manager)
- Step-by-step examples (bug fixes, features)
- Engineer's daily workflow
- Cost & token management

**[Commands Reference](commands.md)** - All rack commands
- Lifecycle: `install`, `add`, `list`, `info`, `delete`
- Team: `team status`, `team upgrade`, `team roles`
- Memory: `memory snapshot`, `memory index`, `memory search`
- Utilities: `wire`, `model`, `cost`, `doctor`

**[Security Model](SECURITY-SIMPLE.md)** - Automatic security
- Three-layer defense (built-in, automatic, simple)
- Prompt injection protection
- Commit prevention
- Dangerous action prevention

### 🏗️ Architecture

**[RACK Architecture](RACK.md)** - Technical deep dive
- What is RACK? (Routing, Autonomy, Context, Knowledge)
- Performance improvements (50-98% token reduction)
- Agent roles and responsibilities
- Implementation details
- Cost analysis

### 🎨 Specialized Topics

**[Multimodal Guide](MULTIMODAL.md)** - Image & video generation
- Setup API keys for image generation
- Using project agents for media
- Cost management for media generation

**[Billing & Alerts](billing-alerts.md)** - Cost management
- Check API credits
- Set up billing alerts
- Monitor token usage
- Add credits when needed

---

## Quick Reference

### Most Common Commands

```bash
# Setup (once)
rack install            # Install OpenClaw + create specialists
rack team upgrade       # Upgrade to RACK architecture

# Daily use
rack add               # Create project agent
rack list              # Show all agents
rack memory snapshot   # Create fast-access context

# Utilities
rack team status       # Check RACK optimization
rack cost              # View token usage
rack doctor            # Health check
```

### File Locations

```
~/.openclaw/
├── openclaw.json                  # OpenClaw config
└── workspaces/
    ├── manager/                   # Specialist: orchestrator
    ├── programmer/                # Specialist: code implementation
    ├── reviewer/                  # Specialist: security gate
    ├── tester/                    # Specialist: validation
    ├── knowledge/                 # Specialist: pattern extraction
    ├── security/                  # Specialist: security audits
    └── projects/
        ├── mywebsite/             # Project agent workspace
        │   ├── SOUL.md           # Agent identity
        │   ├── SNAPSHOT.md       # Fast-access context
        │   ├── MEMORY.md         # Architectural decisions
        │   ├── HEARTBEAT.md      # Active tasks
        │   └── memory/           # Daily logs
        └── mobile-app/            # Another project agent
```

---

## Learning Path

### Beginner (First Hour)
1. Read [Quick Start](QUICK-START-RACK.md) - 5 min
2. Run `rack install` - 2 min
3. Run `rack team upgrade` - 1 min
4. Create project: `rack add` - 2 min
5. Assign first task in Telegram - 10 min
6. Review results and commit - 5 min

**Total: ~25 minutes to first working agent**

### Intermediate (First Day)
7. Read [Workflow Guide](WORKFLOW-GUIDE.md) - 20 min
8. Understand project vs. specialist agents
9. Try both workflow models (direct & via manager)
10. Review [Security Model](SECURITY-SIMPLE.md) - 10 min
11. Check `rack cost` to see token savings

**Total: Add ~30 minutes for deeper understanding**

### Advanced (First Week)
12. Read [RACK Architecture](RACK.md) - 30 min
13. Optimize memory management (`rack memory`)
14. Set up multimodal (if needed)
15. Customize agent SOUL.md files
16. Set up billing alerts

**Total: Ongoing learning as you use rack**

---

## Troubleshooting

### Quick Fixes

**Agent not responding?**
```bash
rack team status  # Check RACK status
systemctl --user restart openclaw-gateway.service  # Restart
```

**Using too many tokens?**
```bash
rack memory snapshot <project>  # Create fast context
# Agent will read this instead of full history
```

**Security concerns?**
```bash
grep "NEVER commit" ~/.openclaw/workspaces/programmer/SOUL.md
# Should find: "NEVER commit to git"
```

**More issues?**
- Check [Quick Start Troubleshooting](QUICK-START-RACK.md#troubleshooting)
- Check [Workflow Guide Issues](WORKFLOW-GUIDE.md#troubleshooting)
- Run `rack doctor` for health check

---

## Support & Community

- **GitHub Issues:** https://github.com/anthropics/claude-code/issues (or your repo)
- **Documentation:** You're reading it!
- **Help Command:** `rack help` - Quick command reference

---

## What's New

### Version 1.0 (RACK Architecture)
- ✅ 50-98% token reduction through context compression
- ✅ Automatic security with 6-point checklist
- ✅ Behavior-only validation (objective testing)
- ✅ Memory management system
- ✅ Team management commands
- ✅ Bug-fix pipeline (Lobster workflows)

See [RACK Architecture](RACK.md) for full details.

---

## Contributing

Documentation improvements welcome! Key principles:

1. **Simple over comprehensive** - Clear, practical examples
2. **User-focused** - Answer "how do I..." not "here's how it works"
3. **Tested examples** - All code examples should work
4. **Consistent formatting** - Follow existing style

---

## Quick Tips

💡 **Create memory snapshots regularly** - Saves tokens
```bash
rack memory snapshot <project>
```

💡 **Check cost often** - Monitor token usage
```bash
rack cost
```

💡 **Use project agents, not specialists directly** - Better isolation
```bash
# ✅ Good: Create project agent
rack add mywebsite

# ❌ Bad: Message programmer directly
# (Programmer is shared, not project-specific)
```

💡 **Review before committing** - Always check git diff
```bash
git diff  # Review changes
git commit -m "..."  # Only if approved
```

---

**Happy automating! 🤖**

For questions or issues, start with [Quick Start Guide](QUICK-START-RACK.md) or run `rack help`.
