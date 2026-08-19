# Development harness and context policy

This repository keeps the agent's always-loaded context deliberately small while preserving the
spec-first quality bar. The harness has four layers, each with a distinct cost and purpose.

| Layer | Loaded when | Purpose |
| --- | --- | --- |
| `AGENTS.md` | Every run | Stable routing and non-negotiable repository invariants |
| `.agents/skills/*/SKILL.md` | Only when the task matches | Task-specific workflow and decisions |
| Skill references | Only when their branch is relevant | Detailed, conditional contracts |
| `.codex/hooks.json` snapshot | Start, resume, or post-compaction | Bounded branch/board/dirty-state recovery |

Large documents remain sources, not startup prompts. `TODO.md` is the active board, `ROADMAP.md`
is the durable decision/history record, and `specs/` contains current-state contracts. Agents
locate a section with `rg` and read the bounded range instead of ingesting the whole corpus.

## Repository skills

- `$docket-roadmap` scopes, schedules, claims, or resumes work and emits a compact task packet.
- `$docket-spec-work` drives a behavior change from current-state spec through RED test and gates.
- `$docket-context-runtime` protects the live context path: session history, handoffs, compaction,
  loop budgets, memory, MCP, and model-visible tool output.

These scopes intentionally overlap only where both contracts matter. A context-runtime behavior
change uses both `$docket-context-runtime` and `$docket-spec-work`; an already-scoped ordinary code
change does not load the roadmap skill.

## Context-restoration hook

The project `SessionStart` hook runs
`.agents/skills/docket-roadmap/scripts/context_snapshot.py` on `startup`, `resume`, and `compact`.
Its output is capped at 1,800 characters and contains only the branch, current board heading,
bounded card headings, dirty paths, and source routing. It does not read the transcript, summarize
source files, call a model, or persist private state.

Project hooks require explicit trust. Inspect and approve the exact definition with `/hooks` after
cloning or whenever the hook changes. This is an intentional security boundary, not a setup bug.

Manual checks:

```bash
python3 .agents/skills/docket-roadmap/scripts/context_snapshot.py
python3 -m json.tool .codex/hooks.json >/dev/null
python3 <skill-creator-dir>/scripts/quick_validate.py .agents/skills/docket-roadmap
```

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
[lifecycle hooks](https://learn.chatgpt.com/docs/hooks).
