# Docket development contract

Keep the default context small. Do not read `ROADMAP.md`, `TODO.md`, `CLAUDE.md`, or an entire
spec directory wholesale. Start with `git status`, targeted `rg`, and the skill that matches the
task; load only the referenced section or spec.

## Source routing

- Planning, card selection, or roadmap updates: use `$docket-roadmap`.
- Any behavior change: use `$docket-spec-work` before editing implementation code.
- Session history, handoffs, token budgets, tool output, agent loop, memory, or MCP context:
  also use `$docket-context-runtime`.
- `TODO.md` is the active board. `ROADMAP.md` holds durable decisions and history. `specs/` holds
  current-state contracts. Tests and the live code path are the implementation evidence.
- If a spec, prose claim, and live behavior disagree, do not choose the convenient one: record the
  discrepancy and make the spec status, test, code, and user-facing claim agree in the same work.

## Change contract

1. Identify the measured need and the exact live call path.
2. Read only the owning spec and neighboring tests.
3. Update the spec, add a failing behavioral test, then implement the smallest coherent change.
4. Preserve `cli -> core -> edges`, `core/tools.py::dispatch_tool` as the sole tool chokepoint,
   and `edges/store.py` as the sole writer of docket-owned JSON.
5. Run focused checks first; run the full required gates before handoff. Never regenerate a golden
   to hide an unintended change or edit a counting script to make a claim pass.

Prefer compact evidence in handoffs: decision, files changed, tests run, unresolved risk, next
action. Do not paste raw logs or whole documents when a path and precise section are sufficient.
