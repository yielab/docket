# Phase 49 start packet (integrator session)

Prepared 2026-10-24 on `plan/phase-46-structure`. Everything a fresh session needs is on the board;
this file only says where to begin and what is already done.

## State

- `ROADMAP.md` Status and §6 D-70; `TODO.md` first section `▶ PHASE 49 — ACTIVE` with cards
  P49-1..5 (`python3 .agents/skills/docket-roadmap/scripts/context_snapshot.py` lists them as ready).
- Fixtures for P49-1's round-trip test are committed under `tests/fixtures/task-records/`
  (scrubbed real queues; the `.normalized.json` is what `read_tasks()` returned at `e8a56f2b`
  minus `claimId` and `source`). No code has changed yet.
- `card_packet.py` accepts cards up to 16,000 bytes (P49-1 is the design card, about 12,300).

## How to run it

1. `python3 .agents/skills/docket-roadmap/scripts/card_packet.py P49-1` is the worker's packet; add
   `TODO.md` rules 1-9 of "How work runs on this board". Nothing else from the planning corpus.
2. One worker per card, in order P49-1 → P49-2 → P49-3; P49-4 is three lanes after the
   integrator's codemod commit; P49-5 is the integrator's. Worktree per card:
   `git worktree add -b p49-<n> .claude/worktrees/p49-<n> <integration head>`, its own
   `DOCKET_HOME` and temp dir in the scratchpad. The stale `p47-*` worktrees under
   `.claude/worktrees/` are leftovers; remove them with `git worktree remove` when convenient.
3. Workers are Sonnet; the integrator reviews the diff against the card's acceptance line by line,
   merges, and runs the default suite once per merge (`uv run pytest -n auto --dist loadfile -q
   --tb=line -p no:cacheprovider > <file>`, read the `FAILED` lines, `--lf` for the fixes).
4. Integrator-owned files: `TODO.md` statuses, `ROADMAP.md`, `CHANGELOG.md`, `README.md` counts.
   A worker reports; it does not edit them.
5. The local endpoint for P49-5's real run needs `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`; reinstall with
   `./install.sh` first; the live `fab-dev` queue is reset by hand (D-57).

## Standing rules that bit before

- No `git stash` (shared across worktrees); a WIP commit parks work.
- Diff from `git merge-base`, never from `HEAD`, when reviewing a worker branch.
- Commits: `Type: description`, ASCII, detailed body, no AI attribution; scrub `/home/<user>`.
- A script is a means: one fix at most, then by hand; never committed unless the card says so
  (P49-4's codemod is not committed).
- The 7 serial no-sandbox failures listed under "FOLLOW-UPS WITH TRIGGERS" are pre-existing; a new
  one stops the close.
