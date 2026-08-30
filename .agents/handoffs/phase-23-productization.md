# Phase 23 coordinator handoff — product truth and ecosystem proof

This is the bounded resumption packet for Phase 23. It does not duplicate card bodies. `TODO.md`
owns executable card detail; `ROADMAP.md` owns D-25–D-29 and later-wave triggers; current-state
specs own shipped behavior.

## Current control state

- Branch: `platform`.
- Active work: Phase 23 / Wave 26. Wave 25's complete 45-path tree landed at `6b925f0`; W25-C11,
  W25-C7, and the authorized live acceptance are DONE.
- Ready pool: W26-C1, C2, and C6–C10. Extract exactly one card before claim and apply the conflict
  graph below; W26-C10 must be split before claim.
- W26-C0 remains blocked on the maintainer's release-source decision. C3–C5 and C11 retain their
  explicit dependency blockers.
- Pre-plan dirty evidence: 22 modified paths across Wave 25 runtime, security, specs, smoke, and
  tests. Planning edits add central roadmap/board/skill/handoff paths; they do not make the runtime
  baseline clean.
- Commit-level closure validation on `6b925f0`: 2,377 passed and five expected skips; Ruff, format,
  strict mypy, 24 spec validations, 18 goldens, metrics, deterministic smoke, and `git diff
  --check` passed.
- No product code is changed by the Phase 23 planning packet.
- At packet creation these planning files are working-tree changes, and new handoff/helper files may
  be untracked. A fresh worktree based on the current commit will not contain them until the
  integrator reviews and commits the packet; do not copy fragments manually between worktrees.

## Authority and loading order

Load only what the current decision needs:

1. Run `python3 .agents/skills/docket-roadmap/scripts/context_snapshot.py`.
2. If dirty output is clipped or unknown, run `git status --short` once and keep that result in the
   coordinator evidence ledger.
3. Extract one card with
   `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`.
4. Read only the named ROADMAP decision/Phase 23 subsection, the owning spec section, neighboring
   tests, and exact live callers named by that card.
5. Do not load all of `TODO.md`, `ROADMAP.md`, a spec directory, another worker's conversation, or
   raw test logs.

Authority order when sources disagree:

```text
explicit user scope
  -> TODO selected card and active owner
  -> owning current-state spec
  -> live caller/state transition
  -> focused and whole-product evidence
  -> ROADMAP durable decision/history
```

Record the discrepancy and make all affected sources agree in the same integration; do not choose
the convenient source.

## Activation gate — satisfied 2026-08-30

The coordinator completed activation:

1. Treat W25-C11 and W25-C7 as satisfied only from their recorded deterministic/live evidence; do
   not repeat the accepted canary.
2. Obtain a complete dirty status and attribute every path to a commit, retained user work, or a
   named pending card. Never discard or reset user work.
3. Run the full Wave 25 gates on the integrated commit and record command plus compact outcome, not
   logs.
4. Change the TODO active marker once, convert dependency-free W26 cards from `BLOCKED` to `TODO`,
   and assign one owner per claimed card.

All four steps are satisfied by `6b925f0`, its recorded closure gates, and the single active-marker
change in the follow-up board commit. Phase 23 / Wave 26 is active.

## Parallel execution graph

With four available execution slots, use one coordinator and at most three mutating workers. With
more slots, dispatch every ready card whose ownership sets are disjoint. Every worker uses a
separate worktree/branch and unique `DOCKET_HOME`, temp root, ports, fake endpoint, and cache path.

```text
W25-C11 -> W25-C7 -> Wave 25 integration/close
                         |
                         +-> W26-C0 release-source decision --------+
                         +-> W26-C1 provider first turn ------------+-> W26-C4 release journey
                         +-> W26-C2 canonical package -> W26-C3 ----+
                         |                         \-> W26-C5 runtime package
                         +-> W26-C6 atomic audit
                         +-> W26-C7 atomic approval
                         +-> W26-C8 atomic resources
                         +-> W26-C9 atomic conversations
                         +-> W26-C10a -> C10b -> C10c cancellation

W26-C0..C10 -> W26-C11 public truth/integration -> Wave 27 measurement
Wave 27 evidence -> Wave 28 two-runtime enforcement proof -> Wave 29 adoption evidence
```

Suggested three-worker refill order after activation:

| Batch | Worker A | Worker B | Worker C | Coordinator |
| --- | --- | --- | --- | --- |
| 1 | C1 provider | C2 package | C6 audit | C0 decision, reviews, central state |
| 2 | C7 approval | C8 resources | C9 conversations | merge/regenerate shared rollups |
| 3 | C3 release artifacts | C5 runtime package (after C2) | C10a cancellation contract | merge and dependency checks |
| 4 | C4 release journey | C10b/C10c sequentially | measured follow-up only | C11 final truth and gates |

The table is a safe default, not a reason to idle: refill from any dependency-free card after
checking full status, function ownership, spec ownership, persisted state, and mutable environment.

## Ownership boundaries

- Coordinator only: `ROADMAP.md`, `TODO.md`, `README.md`, `specs/README.md`, metric/command rollups,
  public branch/default settings, release approval, and the live model endpoint.
- Worker: selected card's named functions/files, owning behavior spec, focused tests, and no other
  central rollup.
- A worker may report an adjacent defect but must not fix it without a separately claimed card.
- Two agents may read the same stable module. They may not concurrently edit the same file/function,
  owning spec, persisted registry shape, or mutable live environment.
- A card touching `dispatch.py`, `agent_loop.py`, `serve.py`, `store.py`, or packaging metadata must
  state function/section ownership and merge order before claim.
- Shared-root simultaneous mutation is forbidden. Use worktrees; the integrator merges one reviewed
  commit at a time and reruns affected cross-card tests.

## Worker and integration protocol

Use the canonical start/return packets, conflict checks, isolation rules, and merge procedure in
`.agents/skills/docket-roadmap/references/multi-agent-delivery.md`; use the delta-only evidence
ledger in `.agents/skills/docket-context-runtime/references/handoff-economy.md`. Do not duplicate
those templates in prompts or handoffs. Phase 23 adds only these constraints:

- Include the selected card ID, base commit, exact function/spec/test locators, assigned worktree,
  and unique mutable-state paths; the worker extracts the card locally with `card_packet.py`.
- Spawn without inherited conversation history when those sources are sufficient. Market-audit
  prose and unrelated cards are not worker context.
- The coordinator owns all central files and integrates one reviewed commit at a time in dependency
  order. It regenerates shared rollups from live state and runs cross-card gates once per batch.
- Stop on an unexplained dirty path, ownership collision, ambiguous active marker, failed required
  gate, changed persisted contract without migration evidence, or shared live endpoint. Return one
  actionable blocker locator, not the attempted transcript.

## Evidence ledger for first resumption

| Finding | Evidence kind | Locator | Planned owner |
| --- | --- | --- | --- |
| Default Anthropic model has no built-in direct endpoint | direct static | `config.py::DEFAULT_MODEL`, `llm.py::resolve_endpoint` | W26-C1 |
| Canonical `docket` artifact is absent | inventory gap | root `pyproject.toml` scripts/build | W26-C2 |
| Formula/installer are mutable or unverifiable | direct static | `Formula/docket-cli.rb`, `install.sh`, release workflow | W26-C3 |
| No artifact-to-first-turn release gate | inventory gap | test/release workflow inventory | W26-C4 |
| Runtime distributions overlap files | direct static | `packages/docket-runtime/pyproject.toml` force-include | W26-C5 |
| Audit head+append is unlocked | direct static | `core/audit.py::audit_log` | W26-C6 |
| Approval transition admits contradictory winners | reproduced live | `core/approval.py::approval_grant/deny`; grant/deny barrier dry run | W26-C7 |
| Resource allocation and rollback cross attempts | direct static; race outcome pending RED | `provision_pod` → `allocate_pod_resources`/`free_pod_resources` | W26-C8 |
| Conversation hop touch is load+save | direct static | `core/dispatch.py::_persist_hop`, `core/conversations.py` | W26-C9 |
| In-process cancel does not stop the loop | direct static | `core/runs.py::cancel_run`, `DocketDriver.run_turn` | W26-C10 |
| Reviewer marker placement and private-boundary canary | accepted live evidence | `/tmp/docket-w25-c7-live-L8nkOm`; W25-C7/C11 shipped evidence | closed |

This ledger is an index, not a substitute for reproducing the selected card's RED case.
