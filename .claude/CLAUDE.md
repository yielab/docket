# Claude Code project bridge

@../AGENTS.md

The canonical project skills live under `../.agents/skills/`. When the shared contract routes a
task to a skill, read that skill's complete `SKILL.md` and resolve its references relative to the
skill directory.

Do not copy or symlink these skills into `.claude/skills`: OpenCode discovers both locations and
requires skill names to be unique. The shared files are guidance; Claude Code's trust, permission,
and sandbox controls remain authoritative for actions.
