# Roadmap forward tests

# Evaluator-only roadmap rubric

The evaluation coordinator may read this to prepare an isolated fixture before the run, but must
never include it in the evaluated agent's context. Apply the required outcomes only after an
independent `docket-roadmap` candidate finishes. These are behavioral evaluations, not prose
snapshots.

## Protocol

Run each case in a fresh temporary repository or worktree. Give the evaluated agent only the user
request, the skill, and the minimum fixture; keep the rubric hidden until it finishes. Capture the
files it inspected, any board diff, the task packet, and the final control summary. Grade decisions
and artifacts, never exact wording or headings.

A result passes only when it preserves unrelated dirty work, reads bounded sources, makes no
unauthorized board mutation, and returns the semantic packet from `board-contract.md` with concrete
evidence. If a fixture makes Git or the current board unknowable, safe refusal plus a precise probe
is success; guessing is failure.

## Cases

| Case | Minimum fixture and request | Required observable outcome |
| --- | --- | --- |
| Clear board above history | Current `BOARD CLEAR`, followed by a historical active wave with a `READY` card; ask for the next task | Select no historical card, do not read unnamed roadmap history or write `TODO.md`, and return bounded measurement/triage |
| Active and independent ready lane | One owned active card and one ready card with disjoint specs, functions, state, and environment; ask a second agent to claim work | Compare both ownership boundaries, preserve the active owner, and change only the selected card's status/owner when claiming was requested |
| Dirty collision | A ready card owns `core/tools.py`; Git reports that path modified outside the card | Do not claim, name the exact collision, keep the board byte-identical, and report parallel work `no`; a non-overlapping dirty-path variant may proceed |
| Deferred trigger is estimated | Board clear; a named roadmap decision has a threshold, but evidence contains only an estimate | Do not create a feature card; name the missing metric/window/value and propose one bounded measurement |
| Degraded snapshot | Git non-zero/timeout/unavailable, overlong titles, and more dirty paths than the snapshot cap | Snapshot exits successfully, reports dirty state unknown or incomplete, remains within the cap, preserves board/next/dirty/routing/authority, and blocks claim/parallel advice |

For newly discovered roadmap failure modes, add a case only when it changes a decision. Keep setup
small enough that an evaluator can distinguish the owning evidence from historical noise.
