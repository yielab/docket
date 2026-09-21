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
> ## ◇ BOARD CLEAR (2026-09-21) — no claimable card
>
> **Wave 36 closed 2026-09-21.** Its eleven cards (the code-side defects the 2026-09-19
> documentation audit found, ROADMAP D-40) were run by one-card Sonnet workers in isolated
> worktrees with a single integrator, merged in three batches, and archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). Worker packets stay in
> [.agents/handoffs/wave-36-worker-packets.md](.agents/handoffs/wave-36-worker-packets.md) as the
> template for the next multi-agent wave. `ROADMAP.md`, this file, `README.md`, `CHANGELOG.md`,
> `CONTRIBUTING.md` counts, `specs/README.md` and every spec's version header and changelog stay
> integrator-owned.
>
> **`v0.2.0-beta.3` was published on 2026-09-18** from `release.yml`; cutting the next beta stays
> a maintainer action, not a card. Every numbered phase 0–25 is complete. Waves 33 to 35 and
> Wave 29 are archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> Wiring or retiring `docket gates enable/disable` remains an open maintainer decision recorded in
> `specs/functional/security-gates.spec.md`; it is not in this wave.
>
> **Measured, not scheduled:**
> `tests/integration/test_agent_loop.py::TestCooperativeRunCancellation::test_cancellation_after_concurrent_approval_grant_never_runs_handler`
> failed once in three full-suite runs under the load of seven concurrent suites and passed
> twenty of twenty in isolation; it waits on three 5-second deadlines. Same shape as W34-C5. A new
> wave starts from bounded triage, not from this note. Also measured by the Wave 36 triage and
> **not** scheduled, for want of a measured need: an entry point that runs a turn for an org
> specialist (Portfolio Manager, manager); registering a verify command's pid so `runs cancel`
> can interrupt it; a role-aware `maintain rebuild` for pod members.
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

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
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---


