# Cycles ended — the archive of closed work

Everything here was moved **verbatim** out of `TODO.md`, `ROADMAP.md` and `.agents/handoffs/`, first
on 2026-09-11 so the live files carry only active and planned work. Nothing here is outstanding and
nothing here is a source of tasks. `manifest.json` records every archived section's heading, byte
length and SHA-256; verify with:

```bash
uv run python scripts/maint/split_board.py check docs/cycles-ended/manifest.json
```

<!-- archive-index:begin -->
| File | Holds |
|---|---|
| [todo-waves.md](todo-waves.md) | Closed board sections: waves, phase boards and registers (42 archived) |
| [roadmap-phases.md](roadmap-phases.md) | Completed-initiative and phase records (23 archived) |
| [roadmap-changelog.md](roadmap-changelog.md) | The roadmap decision changelog (new entries go under its live heading) (1 archived) |
| [handoffs/](handoffs/) | Superseded coordinator handoff packets |

## Index by date (newest first)

| Date | Section | File | Bytes |
|---|---|---|---|
| 2026-09-25 | ◇ WAVE 37 CLOSED (2026-09-25) — defects found by running the product (D-41) | `todo-waves.md` | 10,940 |
| 2026-09-21 | ◇ WAVE 36 CLOSED (2026-09-21) — eleven defects the documentation audit found in code | `todo-waves.md` | 19,222 |
| 2026-09-14 | PHASE 23 — Product truth and ecosystem proof  *(☑ COMPLETE 2026-09-14 — Waves 26–29; W29-C7's closing half removed by D-39)* | `roadmap-phases.md` | 12,841 |
| 2026-09-14 | ◇ WAVE 29 CLOSED (2026-09-14) — adoption evidence and public release | `todo-waves.md` | 6,343 |
| 2026-09-13 | ◇ WAVE 34 CLOSED (2026-09-13) — finish the D-36 function split, two measured fixes, one audit | `todo-waves.md` | 16,893 |
| 2026-09-13 | ◇ WAVE 35 CLOSED (2026-09-13) — second docstring sweep, one dead flag, one lane rule | `todo-waves.md` | 15,483 |
| 2026-09-12 | ◇ WAVE 32 CLOSED (2026-09-12) — documentation truth pass and two deferred follow-ups | `todo-waves.md` | 1,977 |
| 2026-09-11 | ☑ WAVE 31 COMPLETE (2026-09-11 to 2026-09-12) — human maintainability: test lanes, comment budget, generated docs (Phase 25, D-36) | `todo-waves.md` | 43,947 |
| 2026-09-11 | ☑ WAVE 30 COMPLETE (2026-09-11 to 2026-09-12) — harness mode seams and contract (Phase 24, D-35) | `todo-waves.md` | 14,956 |
| 2026-09-02 | ☑ WAVE 28 COMPLETE (2026-09-02) — portable governance proof | `todo-waves.md` | 23,624 |
| 2026-09-01 | ☑ WAVE 27 COMPLETE (2026-09-01) — dependency safety and public front door | `todo-waves.md` | 6,988 |
| 2026-08-31 | ☑ WAVE 26 COMPLETE (2026-08-31) — first successful turn and release/governance truth | `todo-waves.md` | 52,820 |
| 2026-08-30 | ☑ WAVE 25 COMPLETE (2026-08-30) — live-model request and outcome truth | `todo-waves.md` | 48,706 |
| 2026-08-19 | ☑ WAVE 24 COMPLETE (2026-08-19) — realistic local-model evaluation | `todo-waves.md` | 8,250 |
| 2026-08-19 | ☑ WAVE 23 COMPLETE (2026-08-19) — real local-model workflow evidence | `todo-waves.md` | 6,649 |
| 2026-08-19 | ☑ WAVE 22 COMPLETE (2026-08-19) — observable full-workflow proof | `todo-waves.md` | 3,585 |
| 2026-08-19 | ☑ WAVE 21 COMPLETE (2026-08-19) — daemon-free truth pass | `todo-waves.md` | 2,016 |
| 2026-08-19 | ☑ WAVE 20 COMPLETE (2026-08-19) — bounded development context and live-turn efficiency | `todo-waves.md` | 10,750 |
| 2026-08-05 | ▶ LOCAL ENVIRONMENT — rebuilt and verified against the real tree (2026-08-05) | `todo-waves.md` | 5,534 |
| 2026-08-05 | ☑ WAVE 19 COMPLETE (2026-08-05) — what running a real pod found; board CLEAR | `todo-waves.md` | 7,104 |
| 2026-08-05 | ☑ WAVE 18 COMPLETE (2026-08-05) — two false security claims, both now true; board CLEAR | `todo-waves.md` | 3,745 |
| 2026-08-05 | ☑ WAVE 18 board (closed) — opened 2026-08-05 | `todo-waves.md` | 3,026 |
| 2026-08-05 | ☑ WAVE 17 COMPLETE (2026-08-05) — the MCP wire landed | `todo-waves.md` | 3,805 |
| 2026-08-05 | ☑ WAVE 17 board (closed) — opened 2026-08-05 | `todo-waves.md` | 2,839 |
| 2026-08-04 | ☑ WAVE 16 — Phase 22 COMPLETE (2026-08-04). All six cards shipped | `todo-waves.md` | 3,095 |
| 2026-08-04 | ☑ WAVE 16 board (closed) — Phase 22, the control-plane write API (opened 2026-08-04) | `todo-waves.md` | 3,193 |
| 2026-08-04 | ☑ Wave 13 close (2026-08-04) — Phases 19, 20 and 21 all shipped | `todo-waves.md` | 1,147 |
| 2026-08-04 | ☑ WAVE 14 — the cleanup wave (2026-08-04). Docs re-trued, dead code gone, archaeology stripped | `todo-waves.md` | 2,709 |
| 2026-08-04 | ☑ WAVE 15 — the last legacy sweep (2026-08-04) | `todo-waves.md` | 3,550 |
| 2026-08-04 | PHASE 22 — Control-plane write API for an external plan-of-record  *(☑ COMPLETE — all 6 cards, wave 16, 2026-08-04)* | `roadmap-phases.md` | 9,065 |
| 2026-08-03 | PHASE 19 — docket takes the runtime (D-19)  *(☑ COMPLETE — all 13 cards, waves 8–11, closed 2026-08-03)* | `roadmap-phases.md` | 3,501 |
| 2026-07-31 | Wave 7 — ☑ COMPLETE (2026-07-31) — and with it, the whole Platformization program | `todo-waves.md` | 6,947 |
| 2026-07-31 | Dead-code register — wave 3-6 sweep (CL-3, 2026-07-31) | `todo-waves.md` | 10,940 |
| 2026-07-31 | Phase 19 — docket owns the runtime (opened 2026-07-31) | `todo-waves.md` | 34,566 |
| 2026-07-31 | PHASE 15 — Platformization II: deterministic governance, wired  *(☑ COMPLETE — all 6 cards G-1…G-6 shipped; G-3 closed it 2026-07-31)* | `roadmap-phases.md` | 3,868 |
| 2026-07-31 | PHASE 17 — Platformization IV: context engineering & memory management  *(☑ COMPLETE — all 5 cards C-1…C-5 shipped; C-3/C-5 closed it 2026-07-31)* | `roadmap-phases.md` | 2,376 |
| 2026-07-30 | Wave 5 — ☑ COMPLETE (2026-07-30, all five merged; Phase 16 finished with it) | `todo-waves.md` | 1,652 |
| 2026-07-30 | Wave 6 — ☑ COMPLETE (2026-07-30, all five merged) | `todo-waves.md` | 1,481 |
| 2026-07-30 | Dead-code register (CL-1, 2026-07-30) — the standing "no legacy code" work list | `todo-waves.md` | 5,812 |
| 2026-07-30 | PHASE 14 — Platformization I: runtime truth & dispatch hardening  *(☑ COMPLETE 2026-07-30)* | `roadmap-phases.md` | 8,187 |
| 2026-07-30 | PHASE 16 — Platformization III: declarative orchestration & diverse role archetypes  *(☑ COMPLETE — all 8 cards W-1…W-8 shipped 2026-07-30)* | `roadmap-phases.md` | 22,523 |
| 2026-07-30 | PHASE 18 — Platformization V: runtime-driver port, LLM agnosticism & MCP  *(☑ COMPLETE — L-1/L-2/L-3/L-6 shipped; L-4 and L-5 both answered as spikes, 2026-07-30)* | `roadmap-phases.md` | 3,460 |
| 2026-07-02 | PHASE 12 — Consolidation & hardening  *(☑ COMPLETE 2026-07-02)* | `roadmap-phases.md` | 4,827 |
| 2026-07-02 | PHASE 13 — Close the differentiation gaps  *(☑ COMPLETE 2026-07-02)* | `roadmap-phases.md` | 6,142 |
| 2026-06-25 | PHASE 11 — Competitive differentiation (OpenClaw fleet-management space)  *(☑ COMPLETE 2026-06-25)* | `roadmap-phases.md` | 5,403 |
| 2026-06-12 | PHASE 6b — Tier-less role→model policy: unified agent/model architecture  *(✅ complete 2026-06-12)* | `roadmap-phases.md` | 11,113 |

## Undated sections

| Section | File | Bytes |
|---|---|---|
| Historical — Phase 19 waves 8-9 shipped; the daemon is unused | `todo-waves.md` | 5,308 |
| Known-open gaps carried forward (do not let these get quietly re-claimed) | `todo-waves.md` | 4,275 |
| 0. Completed initiatives (historical record) | `roadmap-phases.md` | 1,526 |
| 5. Phase records (historical — every phase below is COMPLETE) | `roadmap-phases.md` | 15,596 |
| PHASE 20 — Fleet observability  *(☑ COMPLETE at cut scope — D-24 cut ~half; P20-2 shipped, P20-4 was a phantom card)* | `roadmap-phases.md` | 8,962 |
| PHASE 21 — The product substrate  *(☑ COMPLETE at cut scope — P21-1 + P21-5 shipped; the rest cut by D-24)* | `roadmap-phases.md` | 4,639 |
| PHASE 5 — Channel portability + system snapshot  *(☑ COMPLETE)* | `roadmap-phases.md` | 3,274 |
| PHASE 6 — Model & provider agnosticism  *(☑ COMPLETE)* | `roadmap-phases.md` | 18,553 |
| PHASE 8 — Agent observability, guardrails & drift (HITL)  *(☑ COMPLETE)* | `roadmap-phases.md` | 21,002 |
| PHASE 9 — Contract integrity: close the spec↔runtime gap (de-ceremony)  *(☑ COMPLETE)* | `roadmap-phases.md` | 11,054 |
| PHASE 10 — Agent architecture: project pods (scope ≠ role ≠ lifecycle)  *(☑ COMPLETE)* | `roadmap-phases.md` | 20,441 |
| Changelog | `roadmap-changelog.md` | 74,031 |
| W29-C1 — recover a corrupt Docket JSON primary from its valid backup | `todo-waves.md` | 3,255 |
| W29-C2 — ship an extractable, artifact-installed ten-minute starter | `todo-waves.md` | 3,419 |
| W29-C3 — define the adoption benchmark schema and deterministic runner | `todo-waves.md` | 3,207 |
| W29-C4 — add adversarial governance and crash/recovery benchmark scenarios | `todo-waves.md` | 2,976 |
| W29-C5 — publish truthful support, deprecation, governance, and succession policy | `todo-waves.md` | 2,884 |
| W29-C6 — generate and publish the reproducible adoption baseline | `todo-waves.md` | 5,649 |
| Planned program — PHASE 25: human maintainability (D-36) | `roadmap-phases.md` | 8,260 |
| Planned program — PHASE 24: harness mode (D-35) | `roadmap-phases.md` | 7,010 |
<!-- archive-index:end -->

## Handoffs

- `handoffs/phase-23-productization.md` — Wave 26 closure packet (2026-08-31); superseded by the Wave 27–29 records in `roadmap-phases.md` Phase 23.
