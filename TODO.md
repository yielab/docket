# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## ◇ WAVE 108 — close every carried item (no phase), opened 2026-10-13

The owner asked to close every item carried out of every phase. A read-only verification at
`7e28ad07` found these still open (W108-5/6 come from a second pass over the Phase 26 close, W108-7 from measuring its `tee` note); everything else carried in the roadmap was already closed or is
a trigger-deferred decision (ROADMAP "Deliberately not scheduled"). Packets:
[.agents/handoffs/wave-108-worker-packets.md](.agents/handoffs/wave-108-worker-packets.md); one
Sonnet worker per card in `../rack-cli-wt/w108-<n>`, all four in parallel by function-level
ownership. Integrator-owned and done on `develop`: `isolation.png` re-rendered with the Landlock
report (`ad2172f5`); ROADMAP cut to a one-line-per-phase status with its old sections archived.

| Card | What | Status |
| --- | --- | --- |
| W108-1 | `task cancel` ends a parked (`waiting_input`) task; CLI-side git on a task worktree uses the recorded git dirs | IN-PROGRESS |
| W108-2 | The Landlock jail grants ref writes only for the task's own branch | IN-PROGRESS |
| W108-3 | `docket exec`: a cache dir, a per-run approval wait, a reader thread that stops with the run | IN-PROGRESS |
| W108-4 | `dispatch.hop_env` public for `core/profile.py`; the inbox indents a multi-line question | IN-PROGRESS |
| W108-5 | The dispatch webhook answers a broken bound pipeline with 404/400; the retired HEARTBEAT line leaves AGENTS.md; the smoke script's removed verb; `task prune --traces --pod` scoped to the pod | IN-PROGRESS |
| W108-6 | `setup --fix --json` reports every check the text report runs | IN-PROGRESS |
| W108-7 | The classifier sees through `env`/`xargs` and the deleting flags of `find`/`awk` | IN-PROGRESS |

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model (D-52, amending D-31):** **`develop`** is the integration branch. Every card
branch or isolated worktree bases on `develop` and is integrated into `develop` without
rewriting history. **`main`** stays the canonical public/default and release lineage: it moves
only by a fast-forward (or a merge) from `develop`, when the maintainer cuts a release or
decides `main` has fallen too far behind. Tags and release jobs still originate from `main`.
`platform` may remain as a synchronized historical ref, but it is not a release source.

---


