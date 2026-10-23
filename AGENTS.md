# Docket development contract

Keep the default context small. Do not read `ROADMAP.md`, `TODO.md`, `CLAUDE.md`, or an entire
spec directory wholesale. Start with `git status`, targeted `rg`, and the skill that matches the
task; load only the referenced section or spec.

## Source routing

- Planning, card selection, or roadmap updates: load the `docket-roadmap` skill.
- Any behavior change: load the `docket-spec-work` skill before editing implementation code.
- Session history, handoffs, token budgets, tool output, agent loop, memory, or MCP context:
  also load the `docket-context-runtime` skill.
- `TODO.md` is the active board. `ROADMAP.md` holds durable decisions and history. `specs/` holds
  current-state contracts. Tests and the live code path are the implementation evidence.
- If a spec, prose claim, and live behavior disagree, do not choose the convenient one: record the
  discrepancy and make the spec status, test, code, and user-facing claim agree in the same work.
- Test placement, comment and docstring budget, or documentation generation: the contract is
  `specs/test-framework.md` §"Lanes and placement" and ROADMAP D-36. A test that reads prose or
  builds an artifact belongs to the agent lane with its `LANE`/`REASON`/`RETIRE_WHEN` header, never
  to the default suite. Run `scripts/maint/comment_lint.py --check` on touched files before handoff.
- `README.md` is descriptive, not a requirements document (ROADMAP D-37). It lists the features
  that exist; requirements live in `specs/`, and that is what a test answers to. Never keep or
  shape a test because the README mentions something. When work changes what is true, rewrite the
  README sentence in the same commit and name it in the body. A `specs/` requirement is different:
  change it by amending the spec, never by deleting its test.
- Mechanical steps (moving files, rewriting paths, generating headers or reference docs, archiving
  board sections) are done by a script under `scripts/maint/`, not by reading and rewriting files
  in a model context. Model work is bounded to one module or one file per packet.

## Change contract

1. Identify the measured need and the exact live call path.
2. Read only the owning spec and neighboring tests.
3. Update the spec, add a failing behavioral test, then implement the smallest coherent change.
4. Preserve the import contracts of ADR 0030 (D-66), `dispatch_tool` as the sole tool chokepoint
   and the store module as the sole writer of docket-owned JSON. The contracts, as the ADR's
   table states them: `kernel` imports nothing in `docket`; `<context>/domain` imports `kernel`
   and its own `domain`; `<context>/application` imports `kernel`, its own `domain` and `ports`,
   and other contexts' `__init__`; `<context>/adapters`, `platform` and `sandbox` import `kernel`,
   `platform`'s `__init__` and the ports and domain types they implement; `agent` imports `kernel` only (plus its own
   packages); `interfaces` imports `kernel`, `bootstrap` and contexts' `__init__`; `bootstrap`
   imports everything. No function-local `docket.*` import; no module over 700 lines. The
   contracts are enforced by `tests/architecture/`; `cli/`, `core/` and `edges/` no longer exist.
   `dispatch_tool` is in `agent/tools/registry.py` and the store in `platform/store.py`.
5. Nothing is kept for the past (ROADMAP D-57, ADR 0022): docket has no users. Delete a removed
   or renamed command, flag, alias, route, persisted shape or behaviour in the same change,
   with its tests, spec text and docs. No alias, notice, migration, hidden command or no-op
   flag; a retired name is an ordinary unknown command. `CHANGELOG.md` is the only record.
6. Run focused checks first; run the full required gates before handoff. Never regenerate a golden
   to hide an unintended change or edit a counting script to make a claim pass.

Prefer compact evidence in handoffs: decision, files changed, tests run, unresolved risk, next
action. Do not paste raw logs or whole documents when a path and precise section are sufficient.

## End-of-work control

End every roadmap, implementation, diagnosis, or review handoff with a compact control summary:

- **Feature:** explain the product capability in plain language before internal details.
- **Outcome:** say `complete`, `partial`, or `blocked`, with the decisive evidence.
- **Missing / failed:** name any unmet acceptance criterion, failed check, skipped evidence, or
  unresolved defect; say `none` when there is none.
- **Pending:** separate work still required by the current card from newly discovered follow-ups.
- **Next ideal task:** recommend exactly one evidence-backed next action. If no ready board card or
  measured trigger exists, say that triage/measurement is required instead of inventing work.
- **Parallel work:** say `no` when the next action depends on current work or overlaps its files,
  functions, specs, persisted state, or live environment. Otherwise name at most two independent
  lanes and their non-overlap boundary.

Do not equate “interesting” with “scheduled,” or a passing focused test with a complete feature.
Keep this summary short enough to resume from directly without reopening large planning documents.
