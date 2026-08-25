# Development harness and context policy

This repository keeps the agent's always-loaded context deliberately small while preserving the
spec-first quality bar. The harness has four layers, each with a distinct cost and purpose.

| Layer | Loaded when | Purpose |
| --- | --- | --- |
| `AGENTS.md` | Every run | Stable routing and non-negotiable repository invariants |
| `.agents/skills/*/SKILL.md` | Only when the task matches | Task-specific workflow and decisions |
| Skill references | Only when their branch is relevant | Detailed, conditional contracts |
| Harness hook snapshot | Start, resume, or post-compaction where supported | Bounded branch/board/dirty-state recovery |

Large documents remain sources, not startup prompts. `TODO.md` is the active board, `ROADMAP.md`
is the durable decision/history record, and `specs/` contains current-state contracts. Agents
locate a section with `rg` and read the bounded range instead of ingesting the whole corpus.

## Repository skills

- `docket-roadmap` scopes, schedules, claims, or resumes work and emits a compact task packet.
- `docket-spec-work` drives a behavior change from current-state spec through RED test and gates.
- `docket-context-runtime` protects the live context path: session history, handoffs, compaction,
  loop budgets, memory, MCP, and model-visible tool output.

These scopes intentionally overlap only where both contracts matter. A context-runtime behavior
change uses both `docket-context-runtime` and `docket-spec-work`; an already-scoped ordinary code
change does not load the roadmap skill.

## Harness compatibility

The coding harness and Docket's model provider are separate choices. A Codex/Claude Code/OpenCode
session reads repository instructions and edits/tests this tree; Docket independently calls the
model selected in its own role policy. Changing one does not silently change the other.
This repository does not override the harness's own inference backend; configure that in the
harness's user/account settings and never commit its credentials here.

| Harness | Project instructions | Skills | Snapshot | Important boundary |
| --- | --- | --- | --- | --- |
| Codex | Native `AGENTS.md` | Native `.agents/skills` | Tracked `.codex/hooks.json` | Project hook still requires trust |
| Claude Code | `.claude/CLAUDE.md` imports `AGENTS.md` | Bridge loads canonical `.agents/skills` | Tracked `.claude/settings.json` | Do not publish local permission grants |
| OpenCode | Native `AGENTS.md` | Native `.agents/skills` discovery | Run snapshot manually | Markdown guidance does not replace OpenCode permissions |

There is deliberately no `.claude/skills` mirror. OpenCode scans both `.agents/skills` and
`.claude/skills` and requires unique skill names, so copying or symlinking the same skills would
make discovery ambiguous. `.claude/settings.local.json` and a root local `CLAUDE.md` remain ignored;
they may contain machine-specific permissions or personal notes and are not the shared contract.
Claude Code may load an existing root `CLAUDE.md` in addition to the bridge, so audit or move that
local file when validating clean-clone behavior.

## Context-restoration hook

The project `SessionStart` hook runs
`.agents/skills/docket-roadmap/scripts/context_snapshot.py` on `startup`, `resume`, `clear`, and
`compact`.
Its output is capped at 1,800 characters and contains the branch, current board heading, bounded
card/status detail, next decision, dirty-state completeness, skill routing, and authority summary.
It does not read the transcript, summarize source files, call a model, or persist private state.

The snapshot fails closed. An unavailable Git probe is `dirty: unknown`, an ambiguous or completed
board cannot expose historical cards as ready work, and optional card detail is clipped before the
board, next decision, dirty state, routing, or authority fields. A clipped dirty list must be
expanded before claiming work or declaring lanes parallel-safe.

Project hooks require explicit trust. Inspect and approve the exact definition in the active
harness after cloning or whenever it changes. This is an intentional security boundary, not a
setup bug. If no compatible hook runs, invoke the snapshot manually before planning.

Manual checks:

```bash
python3 "$(git rev-parse --show-toplevel)/.agents/skills/docket-roadmap/scripts/context_snapshot.py"
python3 -m json.tool .codex/hooks.json >/dev/null
python3 -m json.tool .claude/settings.json >/dev/null
for skill in .agents/skills/docket-*; do
  python3 <skill-creator-dir>/scripts/quick_validate.py "$skill"
done
uv run pytest tests/python/test_development_harness.py
```

`quick_validate.py` checks skill structure, frontmatter, and unfinished scaffolding; it does not
prove that an agent makes safe decisions. Behavioral skill changes also use the relevant
`references/forward-tests.md` as an evaluator-only rubric: run a fresh agent in an isolated temporary
worktree with the request, skill, ordinary references, and minimal fixture, but exclude the rubric.
After it finishes, grade inspected sources, diffs, exit codes, persisted artifacts, and decisions.
Never grade exact prose or reveal the intended answer to the evaluated agent.

## Context quality rules

1. Omit irrelevant sources before truncating or summarizing relevant ones.
2. Keep typed decisions, changed files, test evidence, unresolved risk, and next action; drop raw
   logs and repeated prose first.
3. Never conflate estimated context tokens with measured backend usage.
4. Never send typed cross-role handoff data and the same raw cross-role history by default.
5. Verify context behavior against a deliberately small window; large hosted windows hide waste.
6. Prove that the default production caller consumes new machinery. A helper plus unit tests is not
   a shipped capability without a live wire.

The design follows the official Codex mechanisms for [project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[progressively disclosed skills](https://learn.chatgpt.com/docs/build-skills), and
[lifecycle hooks](https://learn.chatgpt.com/docs/hooks); Claude Code's
[project memory](https://code.claude.com/docs/en/memory), [skills](https://code.claude.com/docs/en/skills),
and [hooks](https://code.claude.com/docs/en/hooks); and OpenCode's
[instructions](https://opencode.ai/v2/docs/instructions) and
[skill discovery](https://opencode.ai/docs/skills).
