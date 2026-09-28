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
> ## ▶ ACTIVE BOARD — WAVE 57 (Phase 32, D-48) · Wave 56 complete 2026-09-27
>
> **Nine cards over Waves 56–59**, one Sonnet worker per card in an isolated worktree under one
> integrator. Decision, the rules, the verdict table and the test discipline are in
> [docs/adr/0014-observability-export.md](docs/adr/0014-observability-export.md). Worker packets:
> [.agents/handoffs/wave-56-worker-packets.md](.agents/handoffs/wave-56-worker-packets.md).
> Wave 56 (P32-1 `8576090`, P32-2 `7f6a364`) merged 2026-09-27 with rollup after it. Wave 57 runs
> P32-3, P32-4 and P32-5 in parallel (merge order P32-4, P32-5, P32-3), one Sonnet worker per card.
> **Phase 32 closes when the Wave 59 rollup merges green.**
>
> **Phase 31 closed 2026-09-27** — see the record below.
>
> **Phase 31 closed 2026-09-27** (ROADMAP D-47, [ADR 0013](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md)):
> seven cards over Waves 53–55, four Sonnet workers in parallel, then two, then the integrator;
> the section is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md)
> and packets stay in [.agents/handoffs/wave-53-worker-packets.md](.agents/handoffs/wave-53-worker-packets.md).
> What shipped: a recipe's scope derived from its directory and shown everywhere (`validate`,
> `apply --dry-run`, `init --recipe`, `docket recipes list|show`), `pod.yaml` `description`, the
> configuration of record written on every validated apply, three recipe scopes with the
> operator's own `~/.docket/recipes/`, twelve shipped recipes of three kinds (teams, policy packs
> on structured predicates, methodology pipelines), `AGENTS.md` read by default as screened
> project instructions, skills in the Agent Skills shape with a prompt index and one `skill` tool
> through the chokepoint, and `docs/recipes.md` generated from the recipes and checked in CI.
> Nothing is parked.
>
>
> **Phase 30 closed 2026-09-27** (ROADMAP D-46, [ADR 0012](docs/adr/0012-the-team-lives-in-the-repo.md)):
> seven cards over Waves 50–51, four Sonnet workers in parallel then the integrator; the section
> is archived verbatim in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and
> packets stay in [.agents/handoffs/wave-50-worker-packets.md](.agents/handoffs/wave-50-worker-packets.md).
> What shipped: `docket init` validates and applies a repository's `.docket/` (or `--recipe`),
> `apply` records the configuration of record and `config explain` reports drift, `export`
> defaults to the repo, a pipeline step names its model, `editRights` is retired, the assets were
> re-captured from one real run, the README leads with "agent teams as configuration, your rules,
> in YAML" with its prose tests rebuilt from it, and the real run's defect (a recipe's role
> resolving to the compiled-in default on a local fleet) is fixed.
>
> No phase is planned. The next card comes from a measured trigger (ROADMAP §4.5), not from
> this file. The two follow-ups parked at the close (`load_role_file`'s `is_short` heuristic and
> `docket init`'s member count) were closed 2026-09-27 in Wave 52, together with
> `docket pod <p> apply <name>` and the newcomer docs pass (see the roadmap changelog). Nothing
> is parked.
>
> **☑ Phase 29 complete (2026-09-27).**
>
> **Phase 29 closed 2026-09-27** (ROADMAP D-45, [ADR 0011](docs/adr/0011-provider-catalog.md)):
> seven cards over Waves 47–49, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> What shipped: providers as `kind: provider` documents in two scopes with every table derived
> from them, verified registration and a CLI round trip, header auth and static headers,
> `Retry-After` with a ceiling, `config explain`/`doctor` coverage, `docket auth` retired.
>
> Waves 47 (P29-1, `0be9812`) and 48 (P29-5 `7bfbbe2`, P29-7 `04a0ffd`, P29-2 `d9e05f8`)
> merged 2026-09-27 with rollups after each. Wave 49 runs P29-4 and P29-3 in parallel (merge
> order P29-4, P29-3), then P29-6 once both are in; one Sonnet worker per card in an isolated
> worktree under one integrator; packets in
> [.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
> Phase 29 closes when the Wave 49 rollup merges green.
>
> **☑ Phase 28 complete (2026-09-26).**
>
> **Phase 28 closed 2026-09-26** (ROADMAP D-44, [ADR 0010](docs/adr/0010-config-format-v1-and-extension-points.md)):
> eight cards over Waves 44–46, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> What shipped: the `kind` envelope and `docket validate`, short forms for policies, pipelines
> and roles over the unchanged canonical form, structured policy predicates, `on:` outcome
> routing with bounded loops, `when` skips and command steps, operator-scoped hashed predicate
> plugins, generated schemas and short-form export.
>
> Waves 44 and 45 (P28-1..P28-6) merged 2026-09-26 (rollups `ea9e354`, Wave 45 rollup after
> `5622d13`). Wave 46 runs P28-7 (predicate plugins) and P28-8 (schemas, short-form export, docs)
> in parallel; packets (Wave 46 section) in
> [.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md).
> Phase 28 closes when the Wave 46 rollup merges green.
>
> **☑ Phase 27 complete (2026-09-26).**
>
> **Phase 27 closed 2026-09-26** (ROADMAP D-43, [ADR 0009](docs/adr/0009-per-pod-configuration-and-portable-teams.md)):
> ten cards over Waves 41–43, one Sonnet worker per card in isolated worktrees under one
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-41-worker-packets.md](.agents/handoffs/wave-41-worker-packets.md).
> What shipped: pod role overlays and pod policies (`--pod`), MCP servers that declare `kind`
> and `tools`, pod `mcpServers`/`deniedTools` with live readers, the Lead's instruction as
> archetype data, `docket pod <p> apply|export` with a round-trip proof, scope labels in
> `config explain`/`doctor`. Two defects found and fixed inside the phase: pod-overlay roles were
> dropped from the roster (P27-9) and `apply` skipped policies (P27-10).
>
> **◇ WAVE 37 CLOSED (2026-09-25) — no card claimed.**
>
> **Wave 37 closed 2026-09-25** (ROADMAP D-41). A bounded triage ran the product on six surfaces
> and found twelve reproducible defects; six cards fixed them in two batches of one-card Sonnet
> workers under one integrator, archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md); packets stay in
> [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md). Live
> evidence on the local endpoint: the journey's dispatch scene reaches `done — 3 hop(s)` with the
> reviewer's `APPROVE`, and a `cd`-prefixed production push still asks.
>
> **◇ PHASE 26 CLOSED (2026-09-26) — the configuration contract (D-42).**
>
> **Phase 26 closed 2026-09-26**, 20/20 cards over Waves 38–40, one integrator + one Sonnet
> worker per card in isolated worktrees; the full board section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-38-worker-packets.md](.agents/handoffs/wave-38-worker-packets.md).
> What shipped: fail-closed policies, visible prompt truncation with window-scaled budgets,
> `docket pod <p> config` (nine typed keys), bindable pipelines, step instructions with
> `--var`, `docket config explain`, one default model of record, registry retention,
> `INSTRUCTIONS.md` + `pod sync`, `projectInstructions`, loud doctor config errors, and three
> shipped recipes. Reasoning: [ADR 0008](docs/adr/0008-configuration-contract.md); user guide:
> [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
>
> **Follow-ups parked with named triggers** (small, none scheduled): serve.py's webhook does not
> catch a bound-pipeline `DispatchError`; `cli/_agents.py`/`cli/_install.py` carry their own copy
> of the retired HEARTBEAT-write instruction; `doctor --json` lacks the new checks; pod
> subcommand completions omit `set-verify`/`sync`; `cli-interface.spec.md` prose for
> `runs prune`/`conversations prune`.
>
> `v0.2.0-beta.3` (2026-09-18) is the latest release; the next beta stays a maintainer action.
> A card becomes claimable only when the integrator opens a planned section below and confirms its
> batching from function-level contention.
>
> **Measured, not scheduled:** `tee` is on the bash allowlist, so `echo x | tee f` writes a file
> without asking (pre-existing, not introduced by W37-C1); `docket help <command>` renders through
> `typer.testing.CliRunner`; `turnTimeoutS`/`verifyTimeoutS` gained their typed writer in
> Phase 26 (P26-4), superseding the earlier "no dedicated writer" note here. A new wave starts from bounded triage, not from this note.
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




## ▶ WAVE 57 — ACTIVE (opened 2026-09-27): Phase 32, observability as configuration (D-48)

**Opened 2026-09-27 (Wave 57 active; Wave 56 done).** Nine cards in four waves (two Sonnet
workers in parallel, then three, then three, then the integrator). Decision, the rules, the
destination table, the verdict table and the test discipline are in
[docs/adr/0014-observability-export.md](docs/adr/0014-observability-export.md).
Worker packets: [.agents/handoffs/wave-56-worker-packets.md](.agents/handoffs/wave-56-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 31 closed at `3f39484`, README follow-up at `0191ffe`;
batching confirmed from the function-level ownership below; the packets file records the base
commit. **Wave 56 merged 2026-09-27:** P32-1 at `8576090`, P32-2 at `7f6a364`; full gates green
(3,153 tests, 31 specs, 19/19 goldens, mypy/ruff/spec-index clean); `specs/README.md` and
`CONTRIBUTING.md` re-trued. Analysis and plan (gitignored):
`internal-docs/observability-export-audit-2026-09-27.es.md`,
`internal-docs/observability-export-plan-2026-09-27.es.md`.

**Trigger (explicit request, 2026-09-27):** observability and telemetry configurable and adaptable
to standards such as OpenTelemetry or Langfuse; solid and maintainable, with enough abstraction to
add remote destinations simply; destinations as YAML like providers; Langfuse and OpenTelemetry
shipped ready, only to be authenticated; no over-sizing. Measured on `0191ffe`: `core/trace.py`
has one record shape, a closed `EVENT_TYPES` and a synchronous `subscribe` seam with one consumer
(`cli/_harness.py::_emit`); no event exists for the model call (usage goes to the session record
in `_TurnState.call_backend_and_handle_response`; `edges/adapters/llm.py::complete` measures no
latency; `ChatResponse` carries neither model nor latency); `trace_ingest` appends past the seam;
`taskId` rides only in dispatch payloads; telemetry is configured by five environment variables
while every other surface is a `kind:` document (`core/config_docs.py::KINDS`); the store has no
owning spec. D-24 (ADR 0005) cut the OpenTelemetry SDK and D-25's two-runtime trigger has not
fired: ADR 0014 records what changed and keeps the SDK cut.

**Test rule (ADR 0014):** one RED behavioural test per card in the module's `SUBJECT` file or the
integration file the card names; a negative case only for a fail-closed property (P32-2, P32-6,
P32-7); existing tests, goldens and specs are the no-change oracle; no agent-lane tests, no
guards, no new test files unless the card names one; goldens change only where a card lists the
lines. **No worker probes a real vendor host or a real model endpoint**; every HTTP target in a
test is a local `http.server` the test starts. The integrator performs the external verification
(P32-9).

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 56 | P32-1 ∥ P32-2 | `core/llm.py::ChatResponse`, `edges/adapters/llm.py::OpenAIChatClient.complete`, `core/agent_loop.py::_TurnState.call_backend_and_handle_response` + new `_trace_llm_call`, `core/trace.py::EVENT_TYPES` (one entry), `cli/_trace.py::_render_event`, new `specs/functional/trace-store.spec.md` → P32-1; `core/telemetry.py` (new: `Span`, `SpanEvent`, `ProjectionState`, `project`, `ExportPolicy`, `DEFAULT_EVENTS`), `tests/unit/core/test_telemetry.py` (new), `tests/fixtures/traces/` (new), new `specs/functional/observability-export.spec.md` → P32-2 |
| 57 | P32-3 ∥ P32-4 ∥ P32-5 | `core/trace.py::trace_event` (+`task_id`) + `::trace_ingest` (notify), `core/agent_loop.py::run_agent_turn`/`_TurnState` (`trace_task_id` threaded to the `_trace_*` helpers), `edges/adapters/docket_runtime.py::run_turn` (one kwarg), `core/dispatch.py` (the one call site that passes it) → P32-3; `core/exporter.py` (new), `config.py` (five constants + `no_export`), `core/config_docs.py::KINDS`/`_MODEL_FOR_KIND`, `docs/contracts/config-v1/exporter.schema.json` + `src/docket/templates/schemas/` copy, `src/docket/templates/exporters/` (new), `tests/unit/core/test_exporter.py` (new) → P32-4; `edges/adapters/exporters/otlp_http.py` (new; `encode`, `OtlpHttpSink`, `probe`), `tests/unit/edges/test_otlp_http.py` (new), `tests/fixtures/otlp-v1/` (new) → P32-5 |
| 58 | P32-6 ∥ P32-7 ∥ P32-8 | `core/telemetry.py::Pipeline` + module-level `start`/`flush`/`close`/`health` (new), `edges/adapters/exporters/__init__.py` (`_DIALECTS`, `sink_for`), `edges/adapters/docket_runtime.py::run_turn` (lazy start + flush), `tests/integration/test_otlp_export.py` (new), `packages/docket-runtime/hatch_build.py` closure → P32-6; `cli/_exporters.py` (new), `cli/__init__.py` (one command block), `cli/_keys.py::prompt_and_store` (extracted), `cli/_config.py::_explain` (`exporters` key + renderer line), `cli/_doctor.py::_check_exporters` (new), `core/exporter.py::enable_exporter`/`disable_exporter` (new), `completions` golden, `docs/commands.md` → P32-7; `core/pod_apply.py::summarize_recipe`/`plan_apply`/`_MANIFEST_KEYS`/`_export_manifest`, `core/config_docs.py::PodDocument.exporters`, `pod.schema.json` (both copies), `cli/_pod.py` (the apply header renderer), `cli/_recipes.py::show` → P32-8 |
| 59 | P32-9 | integrator: `specs/README.md`, `docs/CONFIGURATION.md`, `docs/SECURITY-SIMPLE.md`, `docs/README.md`, `mkdocs.yml`, `README.md`, `CHANGELOG.md`, `tests/fixtures/traces/` (real capture), the external verification, rollups, archive |

Every card follows the §"How to use this board" definition of done.

### P32-1 — the model call is a trace event

**Status:** DONE (2026-09-27, `8576090`) · **Size:** M · **Wave:** 56 · **Spec:** new `specs/functional/trace-store.spec.md` → 1.0.0 (the record shape, `EVENT_TYPES` with `llm_call`, redaction, `subscribe`, `trace_ingest`, retention — the owner the store never had; Status "Implemented and live"), `agent-loop.spec.md` → 1.25.0 ("Tracing": one `llm_call` per backend request; Module API: `ChatResponse.latency_ms`, `.model`, `.provider`), `harness-mode.spec.md` → 1.1.2 (event table: `llm_call` appears on stdout like any record; additive)

**Trigger:** `core/trace.py::EVENT_TYPES` has no event for the model call; usage is persisted
only through `append_messages(..., usage=)` in `_TurnState.call_backend_and_handle_response`;
`edges/adapters/llm.py::OpenAIChatClient.complete` uses `timeout` and measures nothing;
`ChatResponse` has `usage` but no `model`/`latency_ms`. OpenTelemetry GenAI and Langfuse both
need one "generation" per request with model, tokens and latency.

**Goal:**
- `core/llm.py::ChatResponse` gains `model: str = ""`, `provider: str = ""`, `latency_ms: int = 0`.
  `OpenAIChatClient.complete` fills all three on every return path (success, HTTP error,
  timeout, transport error): `model`/`provider` from its `Endpoint`, `latency_ms` from
  `time.perf_counter()` around the request.
- `core/trace.py::EVENT_TYPES` gains `"llm_call"`.
- `core/agent_loop.py`: a new module-level `_trace_llm_call(project, session, role, response,
  iteration)` beside `_trace_tool_call`, called from `_TurnState.call_backend_and_handle_response`
  once per `complete()` return, before any early return. Payload: `{"model", "provider", "ok",
  "finishReason", "failureKind", "inputTokens", "outputTokens", "cachedTokens", "iteration"}`;
  `duration_ms=response.latency_ms`; **never** `cost_usd`. The compaction summariser's own call
  (`summarize_without_reentry`) is also traced, with `"purpose": "compaction"`.
- `cli/_trace.py::_render_event` renders `llm_call` on one line (`model`, `in/out` tokens,
  `ms`, and `failed: <kind>` when not ok); colour entry added.
- `docs/contracts/harness-v1/schema.json` unchanged (`event` is `additionalProperties: true`);
  the spec says so.

**Non-goals:** exporting anything; `task_id` (P32-3); changing `TokenUsage`; any dollar figure.

**Owns:** `core/llm.py::ChatResponse`; `edges/adapters/llm.py::OpenAIChatClient.complete`;
`core/agent_loop.py::_trace_llm_call` (new) + the call inside
`call_backend_and_handle_response` only; `core/trace.py::EVENT_TYPES` (one line); `cli/_trace.py`;
the three specs. **Forbidden:** `core/trace.py` beyond that line, `core/dispatch.py`,
`core/session.py`, `serve.py`, `core/telemetry.py` (P32-2).

**Acceptance:**
- Fixture: `run_agent_turn` with a fake `ChatBackend` that answers one tool call then a final
  message (the pattern in `tests/integration/test_agent_loop.py`, `rg -n "class .*Backend"`).
  Action: run the turn under a `trace.subscribe` list sink. Result: exactly two `llm_call`
  records, `iteration` 1 and 2, `inputTokens`/`outputTokens` equal to the fake's usage,
  `duration_ms` an int ≥ 0, no `cost_usd` key. Oracle: the subscribed records.
- Fixture: a fake backend whose second answer is `ChatResponse(ok=False, failure_kind="timeout")`.
  Result: the second `llm_call` has `ok: false`, `failureKind: "timeout"`; the turn result is
  unchanged from the base. Oracle: records + `AgentLoopResult`.
- `OpenAIChatClient.complete` against a local `http.server` that sleeps 50 ms: `latency_ms ≥ 50`,
  `model` = the endpoint's `model_id`. Against a closed port: `ok=False`, `latency_ms ≥ 0`.
- `docket trace <session>` on a trace holding an `llm_call` prints the one-line render.

**RED test:** `tests/integration/test_agent_loop.py` (the two-records case fails on the base:
no `llm_call` records; `SUBJECT` importable) and `tests/integration/test_llm_port.py`
(the latency case fails: no attribute `latency_ms`).

**Gates:** worker gates. Goldens: check `rg -ln "trace" tests/golden/cases`; if a `trace` render
case exists it gains one line per request — list the lines. `docs/commands.md` unchanged.

### P32-2 — a neutral span model and the projection

**Status:** DONE (2026-09-27, `7f6a364`) · **Size:** M · **Wave:** 56 · **Spec:** new `specs/functional/observability-export.spec.md` → 1.0.0 (Purpose, Scope; Requirements "Span model", "Projection", "Export policy"; Status "Draft — model and projection implemented; no exporter yet"; later cards add sections and bump)

**Trigger:** the only consumer of the trace vocabulary outside docket is the harness, which
forwards raw records. A vendor format written from records directly would put a wire format in
`core/` and re-derive pairing (`tool_call`/`tool_result` by `callId`) in every exporter.

**Goal:** `core/telemetry.py` (new; imports nothing from `edges/`, opens no socket):
- `SpanEvent(name, ts, attributes)` and `Span(trace_id, span_id, parent_id, name, start_ts,
  end_ts, status, attributes, events)` — frozen dataclasses; attribute values `str | int | bool`.
- Deterministic ids: `trace_id = sha256(session_id)[:32]`, `span_id = sha256(f"{session_id}|{kind}|{key}")[:16]`.
- `ProjectionState` (per-session open spans, keyed) and `project(record, state) -> list[Span]`
  — incremental: returns the spans **closed** by this record (a `tool_result` closes its
  `execute_tool` span; `session_end` closes the root and everything still open with `status:
  unset`), and `flush_open(state) -> list[Span]` closes the rest at flush time. Rules: `session_start`
  opens `docket.session` (root; attributes `docket.project`, `docket.role`, `docket.session_id`,
  `session.id`); `llm_call` is a complete child `gen_ai.chat` (`gen_ai.system`,
  `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.response.finish_reasons`, `docket.iteration`; start = `ts − duration_ms`; `status: error`
  when `ok` is false); `tool_call` opens `execute_tool <name>` (`gen_ai.tool.name`,
  `gen_ai.tool.call.id`) and `tool_result` closes it (`docket.tool.ok`, `docket.tool.blocked_by`
  when present); `hop_retry`, `rework_started`, `verdict_*`, `route_taken`, `command_step`,
  `review_rejected`, `tester_verdict_failed`, `verification_failed` are span events on the root
  named by their event type with `docket.hop`/`docket.task_id` when the payload has them; every
  other member of `EVENT_TYPES` is a span event on the innermost open span, attributes = the
  payload's scalar fields prefixed `docket.`. A record whose `event_type` is not in `EVENT_TYPES`
  is ignored, never raises.
- `ExportPolicy(events: frozenset[str] | None, payload: Literal["metadata","full"], payload_max_chars: int)`
  with `DEFAULT_EVENTS` (session_start, session_end, llm_call, tool_call, tool_result,
  guardrail_check, guardrail_block, approval_*, budget_*, error, hop_retry, verdict_*,
  rework_started, review_rejected, route_taken, command_step, verification_failed,
  tester_verdict_failed, reviewer_verdict_unparseable, stale_claim, paused_refused,
  run_cancelled) and `policy.admit(record) -> dict | None`: `None` when the event type is not
  admitted; otherwise the record with its payload reduced — `metadata` keeps scalar
  non-content keys (ids, names, counts, booleans, `tool`, `callId`, `model`, `hop`, `verdict`,
  `finishReason`, `exitCode`…) and drops `arguments`, `text`, `content`, `output`, `result`,
  `prompt`, `messages`, `summary`; `full` keeps them truncated to `payload_max_chars`. Pure, O(1).

**Non-goals:** any wire encoding (P32-5); the queue/thread (P32-6); `task_id` on the record
(P32-3 — read it from `record.get("task_id", "")` so nothing changes later).

**Owns:** `core/telemetry.py` (new), `tests/unit/core/test_telemetry.py` (new, `SUBJECT =
docket.core.telemetry`), `tests/fixtures/traces/dispatch-3-hops.jsonl` (new; hand-built to
`trace-store.spec.md`'s record shape with the P32-1 `llm_call` payload keys — the integrator
replaces it with a real capture in P32-9 and this card's assertions must still hold), the spec.
**Forbidden:** everything else.

**Acceptance:**
- Fixture: the JSONL fixture (one session: `session_start`, two `llm_call`, one
  `tool_call`+`tool_result`, one `guardrail_block`, `session_end`). Action: feed every record to
  `project` then `flush_open`. Result: one root `docket.session`, two `gen_ai.chat` children
  with `gen_ai.usage.input_tokens` from the payload, one `execute_tool read` with
  `docket.tool.ok: true`, the `guardrail_block` as a span event on the root; every `parent_id`
  refers to a span in the output; ids identical on a second run. Oracle: the dataclasses.
- Every member of `core.trace.EVENT_TYPES` fed as a minimal record produces no exception and
  either a span or a span event (the coverage test; fails when a new event type is added
  without a rule).
- Negative: `ExportPolicy(payload="metadata").admit(tool_call record with arguments)` returns a
  record whose payload has no `arguments`; `payload="full"` keeps it truncated to
  `payload_max_chars`; a `prompt_composed` record is `None` under `DEFAULT_EVENTS`.

**RED test:** `tests/unit/core/test_telemetry.py` (the file does not exist on the base; the
import fails). **Gates:** worker gates; no goldens; `comment_lint` on the new module.

### P32-3 — `task_id` on the record; the ingestion bridge notifies the seam

**Status:** TODO · **Size:** S · **Wave:** 57 (after the Wave 56 rollup) · **Spec:** `trace-store.spec.md` → 1.1.0 (record gains optional `task_id`; `trace_ingest` MUST notify subscribers), `pod-dispatch.spec.md` → 6.23.0 (hop records carry the task id), `serve-read-api.spec.md` → 2.13.2 (`/traces` lines may carry `task_id`; additive)

**Trigger:** `core/dispatch.py` passes `context={"taskId": ...}` into the hop and
`docket_runtime.py::run_turn` receives `trace_project`/`trace_session_key` but no task id, so
a record's task is recoverable only from some payloads; `core/trace.py::trace_ingest` calls
`_append` directly, so a subscriber never sees ingested `tool_call`/`tool_result` records.

**Goal:**
- `core/trace.py::trace_event(..., task_id: str = "")` writes `"task_id"` only when non-empty
  (older readers unaffected). `trace_ingest` builds its records and passes each through
  `_notify_subscribers` before `_append` (ingested records carry `payload.source: "ingested"`
  already).
- `core/agent_loop.py::run_agent_turn(..., trace_task_id: str = "")`; `_TurnState` stores it and
  every `_trace_*` helper (including P32-1's `_trace_llm_call`) passes it through.
- `edges/adapters/docket_runtime.py::run_turn(..., trace_task_id: str | None = None)` forwards it;
  the one dispatch call site that already passes `trace_project=ctx.project` passes
  `trace_task_id=ctx.task_id`.

**Non-goals:** a span/parent id on the record (ids are derived in `core/telemetry.py`);
changing the ingest index or offsets.

**Owns:** `core/trace.py::trace_event` + `::trace_ingest`; `core/agent_loop.py::run_agent_turn`
signature, `_TurnState` field, the `_trace_*` helpers' one extra argument;
`edges/adapters/docket_runtime.py::run_turn` signature + forwarding; `core/dispatch.py` (the one
call site only); the three specs. **Forbidden:** `core/dispatch.py` beyond that line,
`core/telemetry.py`, `core/exporter.py`, `serve.py`.

**Acceptance:**
- Fixture: a pod dispatch against the fake driver (`tests/integration/test_dispatch.py`).
  Action: one hop. Result: every record of that hop's trace carries `task_id` equal to the
  claimed task's id; a record written by `trace_event` with no `task_id` has no such key. Oracle:
  the JSONL lines.
- Fixture: a session log the driver can ingest (`tests/unit/core/test_trace.py::*ingest*`).
  Action: `trace_ingest(project)` under `trace.subscribe(list.append)`. Result: the sink received
  every ingested record, in file order, before they were appended. Oracle: the list.

**RED test:** `tests/integration/test_dispatch.py` (the `task_id` case fails: key absent) and
`tests/unit/core/test_trace.py` (the ingest-notifies case fails: sink stays empty).
**Gates:** worker gates; no goldens.

### P32-4 — `kind: exporter`: the document, the catalog, the built-ins

**Status:** TODO · **Size:** M · **Wave:** 57 · **Spec:** `observability-export.spec.md` → 1.1.0 (new sections "Exporter documents", "Catalog and scopes", "Activation state", "Health file"), `config-format.spec.md` → 1.4.0 (`exporter` joins the envelope kinds), `workspace-structure.spec.md` → 1.15.0 (`docket-exporters.json`, `exporters-health.json`)

**Trigger:** telemetry is configured by five environment variables (`TRACES_DIR`,
`DOCKET_NO_TRACE`, `TRACE_RETENTION_DAYS`, `AUDIT_LOG_MAX_BYTES`, `METRICS_WINDOW`) and nothing
else; `core/config_docs.py::KINDS` is `role, pipeline, policy, pod, provider`. The request asks
for destinations as YAML like providers, with Langfuse and OpenTelemetry shipped ready.

**Goal:** `core/exporter.py` (new), a deliberate copy of `core/provider.py`'s shape:
- `ExporterSpec` (Pydantic, `populate_by_name`): `kind: Literal["exporter"]`, `name`
  (`^[a-z0-9][a-z0-9-]*$`), `dialect: Literal["otlp-http"]`, `endpoint: str` (http/https),
  `auth: ExporterAuth` (`type: bearer|header|basic|none`, `header` required for `header`,
  `credentials: list[str]` names `^[A-Z][A-Z0-9_]*$`; `basic` requires exactly two names,
  user then password; `bearer`/`header` exactly one; `none` zero), `headers: dict[str,str]`
  (reserved names refused as in provider), `resource: dict[str,str]` (default
  `{"service.name": "docket"}`), `aliases: dict[str,str]`, `events: "default" | "all" | list[str]`
  (each a member of `core.trace.EVENT_TYPES`), `payload: Literal["metadata","full"] = "metadata"`,
  `payloadMaxChars: int = 2000`, `enabled: bool = False`, `note: str = ""`. A credential value
  in a document (a field matching `^[A-Za-z0-9/_\-+.]{20,}$` where a name is expected) is
  refused naming the field.
- `load_exporter_document(path)`, `Catalog` (built-in `config.EXPORTER_TEMPLATES_DIR` + global
  `config.EXPORTERS_FILE` through `edges/store.py`, nearest-wins, `source_of(name)`),
  `load_catalog`, `save_exporter`, `delete_exporter` (refuses a built-in name that has no global
  entry), `_with_inherited_identity` (a global entry under a built-in's name inherits every
  field it does not set), `resolve_credentials(spec) -> tuple[list[str], str]` (values in
  declaration order via `core/secrets.py`, plus the source label), `load_enabled_exporters()`,
  `export_exporter(name) -> str` (YAML, no values).
- `ExporterState = Literal["enabled","needs credential","disabled","unreachable"]` and
  `activation_state(spec, health) -> tuple[ExporterState, list[str]]` (the missing credential
  names), pure; `unreachable` when enabled and the health file's `lastError` is newer than
  `lastOk`.
- `verify_endpoint(spec, probe: ProbeResult) -> ExporterVerification` (pure, same table as the
  provider's: transport failure → unreachable; 401/403 → credential warning; 2xx → ok; other →
  warning naming the status). `ProbeResult` here is a plain dataclass (`status`, `error`) so this
  module imports nothing from `edges/`.
- Health file: `config.EXPORTERS_HEALTH_FILE` (`exporters-health.json`), documented shape
  `{"<name>": {"exported": int, "dropped": int, "failed": int, "lastOk": ts, "lastError": str,
  "lastErrorAt": ts}}`; `read_health()` here, writes happen in P32-6 through `store.py`.
- `config.py`: `EXPORTERS_FILE`, `EXPORTER_TEMPLATES_DIR`, `EXPORTERS_HEALTH_FILE`,
  `EXPORT_QUEUE_MAX` (1000), `EXPORT_FLUSH_TIMEOUT_S` (5.0), `no_export()` (`DOCKET_NO_EXPORT=1`,
  same shape as `no_trace`).
- `core/config_docs.py`: `KINDS` gains `"exporter"`, `_MODEL_FOR_KIND["exporter"] = ExporterSpec`;
  `docket validate <file>` accepts an exporter document; `scripts/gen_config_schemas.py` emits
  `exporter.schema.json` into both copies.
- `src/docket/templates/exporters/`: `01-otel-collector.yaml` (`http://127.0.0.1:4318/v1/traces`,
  `auth: none`, `payload: full`, note: stays on this host), `02-jaeger.yaml` (same endpoint
  shape, `payload: metadata`), `03-langfuse.yaml` (`https://cloud.langfuse.com/api/public/otel/v1/traces`,
  `auth: basic`, `[LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY]`, `aliases: {"session.id":
  "langfuse.session.id"}`, note: EU cloud; override `endpoint` for US or self-hosted),
  `04-honeycomb.yaml` (`https://api.honeycomb.io/v1/traces`, `auth: header`, header
  `x-honeycomb-team`, `[HONEYCOMB_API_KEY]`), `05-phoenix.yaml` (`http://127.0.0.1:6006/v1/traces`,
  `auth: none`). All `enabled: false`. Every file validates with `docket validate`.

**Non-goals:** the wire (P32-5); the queue and the health writer (P32-6); `enable`/`disable`
and the CLI (P32-7).

**Owns:** `core/exporter.py` (new), `config.py` (the constants and `no_export`),
`core/config_docs.py` (the two entries), the schema (both copies), `templates/exporters/`
(new), `tests/unit/core/test_exporter.py` (new, `SUBJECT = docket.core.exporter`), the three
specs. **Forbidden:** `core/provider.py`, `cli/`, `edges/adapters/`, `core/telemetry.py`.

**Acceptance:**
- Fixture: the five templates. Action: `load_catalog()` in a fresh `DOCKET_HOME`. Result: five
  specs, `source_of` = `builtin` for each, `activation_state` = `disabled` for all; with
  `LANGFUSE_PUBLIC_KEY` stored but the secret key absent and a global `{name: langfuse, enabled:
  true}` entry: `("needs credential", ["LANGFUSE_SECRET_KEY"])`; with both stored: `enabled`.
  Oracle: the dataclasses and the state tuple.
- Fixture: a global document `{kind: exporter, name: langfuse, enabled: true, endpoint:
  https://lf.internal/api/public/otel/v1/traces}`. Action: `load_catalog().get("langfuse")`.
  Result: `endpoint` overridden, `auth`/`aliases`/`resource` inherited from the built-in,
  `source_of` = `global`.
- Negative: a document with `credentials: ["pk-lf-<20 chars>"]` is refused naming
  `auth.credentials`; `dialect: otlp-grpc` is refused listing `otlp-http`; `events: [nope]` is
  refused naming the event.
- `docket validate src/docket/templates/exporters/03-langfuse.yaml` prints `ok`.

**RED test:** `tests/unit/core/test_exporter.py` (file absent on the base). **Gates:** worker
gates including `gen_config_schemas.py --check`; no goldens.

### P32-5 — the `otlp-http` dialect

**Status:** TODO · **Size:** M · **Wave:** 57 · **Spec:** `observability-export.spec.md` → 1.2.0 (new section "The otlp-http dialect": encoding rules, auth, timeout, retry, the wire golden)

**Trigger:** no module in docket knows OTLP; D-19 rents protocols through one adapter module
each (`edges/adapters/llm.py` for chat completions) and the runtime library allows no new
dependency.

**Goal:** `edges/adapters/exporters/otlp_http.py` (new; the **only** module that knows the OTLP
JSON mapping; stdlib `urllib` and `json` only), with `edges/adapters/exporters/__init__.py`
holding only the package docstring (P32-6 adds `_DIALECTS`/`sink_for`):
- `encode(spans: Sequence[Span], *, resource: Mapping[str,str], aliases: Mapping[str,str]) -> dict`
  → `{"resourceSpans": [{"resource": {"attributes": [...]}, "scopeSpans": [{"scope": {"name":
  "docket", "version": <docket version>}, "spans": [...]}]}]}`; each span: `traceId`/`spanId`/
  `parentSpanId` hex strings, `name`, `kind` 1 (INTERNAL) or 3 (CLIENT) for `gen_ai.chat`,
  `startTimeUnixNano`/`endTimeUnixNano` as **decimal strings**, `attributes` as a list of
  `{"key", "value": {"stringValue"|"intValue"(string)|"boolValue"}}`, `events` with
  `timeUnixNano`, `status` `{"code": 1|2}` (`unset` → no status). `aliases` duplicates an
  attribute under the alias key (never renames). Deterministic key order (sorted attributes).
- `OtlpHttpSink(endpoint, auth_header: tuple[str,str] | None, headers, resource, aliases,
  timeout_s=5.0, clock=time.monotonic, opener=urllib.request.urlopen)` with
  `emit(spans) -> SinkResult(accepted: int, status: int | None, error: str, retry_after_s: float | None)`
  and `close()`. Auth: `bearer` → `Authorization: Bearer <v>`; `basic` → `Authorization: Basic
  base64(user:pass)`; `header` → `<name>: <v>`; the sink receives the already-resolved header
  pair, never credential names. One retry only on 429/502/503/504, sleeping `min(Retry-After,
  DISPATCH_RETRY_MAX_WAIT_S)` (default 1 s without a header); a 4xx other than 429 is not
  retried and reports `accepted 0`. A transport failure is `status None`. Never raises.
- `probe(endpoint, auth_header, headers, timeout_s) -> ProbeResult(status, error)`: POSTs
  `{"resourceSpans": []}`.
- `tests/fixtures/otlp-v1/dispatch-3-hops.json`: `encode()` of P32-2's projected fixture,
  committed; the unit test compares byte-for-byte (`json.dumps(sort_keys=True, indent=2)`).

**Non-goals:** any queue/thread; reading `ExporterSpec` (P32-6's `sink_for` maps spec →
constructor); protobuf.

**Owns:** `edges/adapters/exporters/__init__.py` (docstring only), `edges/adapters/exporters/
otlp_http.py` (new), `tests/unit/edges/test_otlp_http.py` (new, `SUBJECT =
docket.edges.adapters.exporters.otlp_http`), `tests/fixtures/otlp-v1/` (new), the spec section.
**Forbidden:** `core/`, `cli/`, `edges/adapters/llm.py`.

**Acceptance:**
- Fixture: P32-2's projected spans (build them in the test from
  `tests/fixtures/traces/dispatch-3-hops.jsonl` through `core.telemetry.project`). Action:
  `encode`. Result: byte-identical to the golden; a `gen_ai.chat` span has `kind: 3`,
  `gen_ai.usage.input_tokens` as `{"intValue": "<n>"}`, and `langfuse.session.id` present when
  `aliases` maps it. Oracle: the golden file.
- Fixture: a local `http.server` that records requests and answers 200. Action: `emit`. Result:
  one POST, `Content-Type: application/json`, `Authorization: Basic <base64>` for a basic pair,
  body parses back to the encoded dict; `accepted == len(spans)`.
- Fixture: the server answers 429 with `Retry-After: 1` then 200. Result: exactly two POSTs,
  `accepted` full, the sleep observed through the injected clock is 1 s. Answers 400: one POST,
  `accepted 0`, `status 400`. Closed port: `status None`, `error` non-empty, no exception.

**RED test:** `tests/unit/edges/test_otlp_http.py` (absent on the base). **Gates:** worker
gates; no goldens (the OTLP golden is a fixture, not a CLI golden).

### P32-6 — the pipeline, wired where turns run

**Status:** TODO · **Size:** M · **Wave:** 58 (after the Wave 57 rollup) · **Spec:** `observability-export.spec.md` → 1.3.0 (new sections "Pipeline" and "Wiring"; Status "Implemented — awaiting external verification (P32-9)"), `agent-loop.spec.md` → 1.26.0 (`DocketDriver` conformance: `run_turn` starts export lazily and flushes on return; zero enabled exporters change nothing)

**Trigger:** the fifth unwired-machinery instance (CLAUDE.md) is machinery with a writer, a CLI
reader and no consumer on the live path. This card is the consumer: without it P32-2/4/5 are
that shape again.

**Goal:**
- `core/telemetry.py::Pipeline(sink: SpanSink, policy: ExportPolicy, *, queue_max, batch_max=100,
  batch_wait_s=1.0, clock)`: `SpanSink` is a `Protocol` (`emit(spans) -> SinkResult`, `close()`);
  `offer(record)` runs `policy.admit` and `project` in the caller's thread and puts closed spans
  on a `queue.Queue(maxsize=queue_max)` with `put_nowait` — on `queue.Full` increments
  `dropped` and returns; one daemon thread drains in batches and calls `sink.emit`, adding
  `accepted` to `exported` and the rest to `failed` with `last_error`; `flush(timeout_s)` drains
  what is queued plus `flush_open(state)` and waits at most `timeout_s`; `close()` flushes and
  joins. Never raises out of `offer`/`flush`/`close`. `stats() -> PipelineStats`.
- Module-level registry: `start(specs: Sequence[ExporterSpec], sink_for) -> int` (builds one
  `Pipeline` per enabled spec whose credentials resolve, subscribes **one** fan-out sink through
  `core.trace.subscribe`'s non-context form — add `trace.add_subscriber(sink) -> Callable[[], None]`
  beside `subscribe`, same lock, same semantics; returns the count started; a second `start` is a
  no-op), `flush(timeout_s)`, `close()`, `health() -> dict` (the P32-4 shape). `start` with zero
  specs subscribes nothing and starts no thread. `no_export()` makes `start` return 0.
- `edges/adapters/exporters/__init__.py`: `_DIALECTS = {"otlp-http": _otlp_sink}` and
  `sink_for(spec, credential_values) -> SpanSink` (builds the auth header pair from
  `spec.auth.type` and the resolved values; raises `ValueError` for an unknown dialect).
- `edges/adapters/docket_runtime.py::run_turn`: before the turn, if the registry is not started,
  `telemetry.start(load_enabled_exporters(), sink_for)`; after the turn (every return path),
  `telemetry.flush(EXPORT_FLUSH_TIMEOUT_S)` and `store.write_json(EXPORTERS_HEALTH_FILE, telemetry.health())`
  through `edges/store.py`; `atexit.register(telemetry.close)` once.
- `packages/docket-runtime/hatch_build.py`: `core/telemetry.py`, `core/exporter.py` and
  `edges/adapters/exporters/` join the measured closure (P31-6's lesson: a module on the turn
  path missing from the wheel).

**Non-goals:** the CLI (P32-7); changing `serve.py` or `cli/_harness.py` (both reach `run_turn`).

**Owns:** `core/telemetry.py::Pipeline`, `PipelineStats`, `start`/`flush`/`close`/`health`
(new); `core/trace.py::add_subscriber` (new, beside `subscribe`); `edges/adapters/exporters/
__init__.py`; `edges/adapters/docket_runtime.py::run_turn` (the start/flush/health lines only);
`packages/docket-runtime/hatch_build.py`; `tests/integration/test_otlp_export.py` (new); the two
specs. **Forbidden:** `core/telemetry.py::project`/`ExportPolicy` internals, `core/exporter.py`,
`cli/`, `otlp_http.py`.

**Acceptance:**
- Fixture: a fresh `DOCKET_HOME` with a global exporter document `{name: local, dialect:
  otlp-http, endpoint: http://127.0.0.1:<port>/v1/traces, auth: none, enabled: true, payload:
  full}` and a local `http.server` recording bodies; a `DocketDriver` with the fake backend from
  `tests/integration/test_docket_driver.py`. Action: `run_turn`. Result: the server received ≥ 1
  POST whose body has a `gen_ai.chat` span with `gen_ai.usage.input_tokens` > 0 and a
  `docket.session` root; `exporters-health.json` shows `local.exported ≥ 2`, `failed 0`. Oracle:
  the recorded bodies and the health file.
- Negative (fail-closed on the turn): the server accepts the connection and never answers.
  Result: `run_turn` returns within `EXPORT_FLUSH_TIMEOUT_S + turn time` (assert `< 2×` the
  no-exporter duration measured in the same test), `AgentLoopResult` identical to the
  no-exporter run, health shows `failed ≥ 1` or `dropped ≥ 1` with `lastError` set.
- Zero enabled exporters: `run_turn` starts no thread (`threading.enumerate()` unchanged) and
  registers no subscriber (`trace._SUBSCRIBERS` empty).
- `DOCKET_NO_EXPORT=1` with the enabled document: no POST, health untouched.

**RED test:** `tests/integration/test_otlp_export.py` (absent on the base). **Gates:** worker
gates; `tests/agent/release/test_runtime_adapter_public_truth.py` if the closure list is asserted
there (`rg -n "skills.py" tests/agent packages/docket-runtime`).

### P32-7 — `docket exporters`: enable by authenticating

**Status:** TODO · **Size:** M · **Wave:** 58 · **Spec:** `observability-export.spec.md` → 1.4.0 (new section "Activation": `enable`/`disable`/`test`, the audit entries, the TTY rule), `cli-interface.spec.md` → 1.54.0 (`docket exporters list|show|enable|disable|test|add|remove|export`; `config explain` `exporters` lines; `doctor` check), `cli-json-shapes.spec.md` → 1.15.0 (`exporters list --json`, `config explain --json` `exporters`)

**Trigger:** the request's experience is "the YAML exists, I only put the key". `cli/_keys.py::
_keys_add` holds the hidden prompt inline; `cli/_provider.py::_run_add` shows the verify-then-
register flow; `cli/_config.py::_explain` names the provider and credential source; nothing does
any of that for an exporter.

**Goal:**
- `cli/_keys.py::prompt_and_store(name) -> bool` extracted from `_keys_add` (hidden input,
  format warning, 0600 store, meta touch); `_keys_add` calls it; behaviour byte-identical.
- `cli/_exporters.py::run_exporters(action, args) -> int`, registered in `cli/__init__.py` exactly
  as `cmd_recipes` is (one block): `list [--json]` (NAME, DIALECT, STATE, CREDENTIALS, SCOPE;
  state from `activation_state`), `show <name>` (effective document, source, state, health
  counters), `enable <name> [--endpoint URL] [--payload metadata|full] [--events ...]
  [--no-verify]` → for each missing credential: if `sys.stdin.isatty()` call `prompt_and_store`,
  else print `docket keys add <NAME>` for each and exit 1 writing nothing; then `probe` through
  `edges.adapters.exporters.otlp_http.probe` (or the dialect's), `verify_endpoint`; a transport
  failure exits 1 and writes nothing unless `--no-verify`; success writes **only** `{kind, name,
  enabled: true, <overrides given>}` via `core/exporter.py::enable_exporter(name, overrides)`
  (new; global entry, inheriting identity), prints the source and `payload`, and when `payload`
  is `full` prints `tool arguments and results leave this host`; `disable <name>`
  (`disable_exporter`, keeps keys); `test <name>` (probe + classification, exit 0/1); `add
  <file>` (a full document, verified like `enable`); `remove <name>` (global entries only; a
  built-in name without a global entry says so and exits 1); `export <name>`. Audit:
  `exporter.enabled` / `exporter.disabled` / `exporter.added` / `exporter.removed`, detail
  `name=<n> payload=<p> endpoint=<url>`, never a value.
- `cli/_config.py::_explain`: `"exporters": [{name, dialect, state, scope, credentialSource,
  payload, exported, dropped, failed, lastError}]` and one rendered line per exporter under a
  `Exporters:` header (`none enabled` when empty).
- `cli/_doctor.py::_check_exporters()`: warns per enabled exporter whose health has `failed >
  0` since `lastOk`, names `docket exporters test <name>`; ok line otherwise.
- `completions` golden gains `exporters`; `docs/commands.md` regenerated.

**Non-goals:** per-pod scope; any change to `core/telemetry.py` or the wire; `keys setup`
walking exporters (a later card if asked).

**Owns:** `cli/_exporters.py` (new), `cli/__init__.py` (one command block), `cli/_keys.py::
prompt_and_store` (+ the call in `_keys_add`), `cli/_config.py::_explain` (the key + renderer
line), `cli/_doctor.py::_check_exporters` (+ its call in `run_doctor`), `core/exporter.py::
enable_exporter`/`disable_exporter` (new functions only), `tests/golden/cases/completions*`,
`docs/commands.md`, `tests/integration/test_exporters_cli.py` (new), the three specs.
**Forbidden:** `core/exporter.py` beyond the two functions, `core/telemetry.py`,
`edges/adapters/docket_runtime.py`, `cli/__init__.py::cmd_pod`.

**Acceptance:**
- Fixture: fresh `DOCKET_HOME`, no keys, stdin not a TTY. Action: `docket exporters enable
  langfuse`. Result: exit 1, output names `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` with
  the `docket keys add` command, `docket-exporters.json` absent. Oracle: exit code + file.
- Fixture: both keys stored, a local server answering 200 at `--endpoint`. Action: `enable
  langfuse --endpoint http://127.0.0.1:<port>/v1/traces`. Result: exit 0; the global file holds
  exactly `{kind: exporter, name: langfuse, enabled: true, endpoint: <url>}`; `list` shows
  `enabled`; `read_audit()` has `exporter.enabled` with `payload=metadata`; `show langfuse`
  prints the inherited `aliases`. `disable langfuse` flips it, keys remain.
- Negative: `remove jaeger` (built-in, no global entry) exits 1 naming it as built-in.
- `docket config explain <agent> --json` carries `exporters[0].state == "enabled"`; `doctor`
  after a health file with `failed: 3, lastOk: ""` warns naming `docket exporters test langfuse`.

**RED test:** `tests/integration/test_exporters_cli.py` (absent on the base). **Gates:** worker
gates; `completions` golden regenerated with the one line listed; `gen_cli_docs.py --check`.

### P32-8 — a recipe names its destinations

**Status:** TODO · **Size:** S · **Wave:** 58 · **Spec:** `pod-blueprints.spec.md` → 1.20.0 ("Pod manifests: apply" key set gains `exporters`; "Recipe summary" gains the names; `apply` reports state, activates nothing), `config-format.spec.md` → 1.5.0 (manifest key), `cli-interface.spec.md` → 1.55.0 (`apply` state lines; `recipes show` line)

**Trigger:** ADR 0014 rule 7: a repository can state that its team is observed in Langfuse
without carrying a credential or activating anything; `core/pod_apply.py::_MANIFEST_KEYS` is
`members, settings, pipeline, description`.

**Goal:**
- `pod.yaml` accepts `exporters: [<name>, ...]` (list of names; each must resolve in
  `core.exporter.load_catalog()` at `plan_apply` time or the plan fails naming it; a document,
  a URL or a credential-shaped string is refused naming the key). `_MANIFEST_KEYS` gains it;
  `core/config_docs.py::PodDocument.exporters: list[str] | None`; both schema copies regenerated;
  `_export_manifest` writes it when the pod's settings hold one (store it under
  `PodSettings` as a typed key `exporters` — a recorded, not configurable, key like
  `configSource`; `pod config set exporters` refused).
- `summarize_recipe` gains `exporters: tuple[str, ...]`; `render()` appends `· exporters langfuse`
  when non-empty.
- `apply` (and therefore `init --recipe`/`init` from `.docket/`) prints, after the plan, one line
  per name: `exporter langfuse: needs credential LANGFUSE_SECRET_KEY -> docket exporters enable
  langfuse` / `exporter otel-collector: enabled` / `exporter jaeger: disabled -> docket exporters
  enable jaeger`, from `activation_state`; **writes nothing** to `docket-exporters.json`.
  `recipes show` prints the same lines.

**Non-goals:** activating; per-pod routing of spans; anything in `core/telemetry.py`.

**Owns:** `core/pod_apply.py::summarize_recipe`/`RecipeSummary`/`plan_apply`/`_MANIFEST_KEYS`/
`_export_manifest`/`apply` (the state lines' data), `core/pod.py::PodSettings` (one recorded
key), `core/config_docs.py::PodDocument.exporters`, `pod.schema.json` (both copies),
`cli/_pod.py` (the shared apply header/plan renderer: the state lines), `cli/_recipes.py::show`,
`tests/unit/core/test_pod_apply.py`, the three specs. **Forbidden:** `cli/__init__.py`,
`core/exporter.py`, `cli/_exporters.py`, `templates/recipes/` (no shipped recipe names an
exporter in this phase).

**Acceptance:**
- Fixture: a recipe directory whose `pod.yaml` is `{kind: pod, name: x, exporters: [langfuse]}`;
  no keys stored. Action: `apply(plan_apply(p, dir))`. Result: every item `skip`, the pod's
  settings record `exporters: ["langfuse"]`, `docket-exporters.json` absent, and the CLI prints
  `exporter langfuse: needs credential LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY -> docket
  exporters enable langfuse`. Oracle: the settings file, the absent file, the output.
- Negative: `exporters: [{endpoint: ...}]` and `exporters: [nope]` each raise `PodApplyError`
  naming `exporters`, nothing written.
- `summarize_recipe(dir).render()` ends with `· exporters langfuse`; `docket validate <dir>`
  shows it.

**RED test:** `tests/unit/core/test_pod_apply.py` (the summary case fails: unknown key
`exporters`). **Gates:** worker gates including `gen_config_schemas.py --check`; no goldens.

### P32-9 — docs, external verification, close (integrator)

**Status:** TODO · **Size:** M · **Wave:** 59 (after the Wave 58 rollup) · **Spec:** `observability-export.spec.md` → 1.5.0 (Status "Implemented and live"; "External verification" records the collector's and Langfuse's answers with dates; the fixture is a real capture), `specs/README.md` rows for the two new specs and every bumped one

**Goal:**
- Live proof on this machine: `otel/opentelemetry-collector` (`debug` exporter) in Docker,
  `docket exporters enable otel-collector`, one real dispatch of the `docket-dev` pod against
  the local endpoint (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`): the collector log shows
  `docket.session`, ≥ 1 `gen_ai.chat` with real token counts and `execute_tool` spans; `docket
  trace <session>` shows the matching `llm_call` lines; `config explain` shows `exported > 0`.
  Then `docket exporters enable langfuse` with the operator's keys and the same dispatch: the
  trace appears in Langfuse with generations. If Langfuse rejects `application/json`, record it
  and open the deferred protobuf card instead of patching inside this one.
- Replace `tests/fixtures/traces/dispatch-3-hops.jsonl` with the real capture (secrets scrubbed,
  paths generic) and regenerate `tests/fixtures/otlp-v1/` from it; P32-2's and P32-5's tests
  must pass unchanged in their assertions.
- Docs: `docs/CONFIGURATION.md` §3.14 "Export traces to OpenTelemetry or Langfuse" (the three
  `enable` transcripts, `payload` rule, `exporters:` in `pod.yaml`, the health counters);
  `docs/SECURITY-SIMPLE.md` (what leaves the host under `metadata` and `full`); `docs/README.md`,
  `mkdocs.yml`; **one** README sentence in the "gate and record" lane naming that traces can be
  sent to any OpenTelemetry or Langfuse endpoint from a YAML document; `CHANGELOG.md`;
  `docs/commands.md` regenerated; `tests/agent` rebuilt only if a pinned README sentence moved.
- Board: rollup commits, `scripts/metrics.py --check` re-measured, `split_board.py archive` of
  this section at close, ROADMAP status line and D-48 row re-trued to what shipped.

**Acceptance:** every gate in §"How to use this board" green on `main`; the two live transcripts
pasted into the spec's "External verification"; `docket exporters list` golden added.
