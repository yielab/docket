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
> ## ▶ ACTIVE BOARD — WAVE 60 (Phase 33, D-49) · opened 2026-09-28
>
> **Six cards over Waves 60–63**, one Sonnet worker per card in an isolated worktree under one
> integrator: what a trace destination may see becomes a declared privacy level (`minimal`,
> `actions`, `conversation`, `full`, or an explicit `share:` list of content classes) in the
> exporter's own document, enforced by an allowlist where spans are built, captured upstream
> only when a destination asks, widened only by a confirmed and audited command, and visible in
> `list`/`show`/`explain`/`doctor`, on the span itself, and in an offline `preview`. Decision
> and rules: [docs/adr/0015-export-privacy-levels.md](docs/adr/0015-export-privacy-levels.md).
> Worker packets: [.agents/handoffs/wave-60-worker-packets.md](.agents/handoffs/wave-60-worker-packets.md).
> Wave 60 is P33-1 alone. **Phase 33 closes when the Wave 63 rollup merges green.**
>
> **Phase 32 closed 2026-09-28** (ROADMAP D-48, [ADR 0014](docs/adr/0014-observability-export.md)):
> nine cards over Waves 56–59, one Sonnet worker per card in an isolated worktree then the
> integrator; the section is archived verbatim in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md) and packets stay in
> [.agents/handoffs/wave-56-worker-packets.md](.agents/handoffs/wave-56-worker-packets.md).
> What shipped: every backend chat-completions exchange is a durable `llm_call` trace event;
> `core/telemetry.py` deterministically projects the trace into a neutral `Span`/`SpanEvent`
> model with `metadata`/`full` payload reduction; a destination is a `kind: exporter` YAML
> document (five ready-made, disabled-by-default: `otel-collector`, `jaeger`, `langfuse`,
> `honeycomb`, `phoenix`) speaking one hand-rolled `otlp-http` wire dialect, no SDK dependency
> (D-24 stands); a bounded queue/background-sender `Pipeline` is wired into every turn;
> `docket exporters list|show|enable|disable|test|add|remove|export` turns a destination on by
> authenticating; a pod names its destinations in `pod.yaml`'s `exporters:`, reported, never
> itself activating. Verified live 2026-09-28 against a real dispatch and a real
> `otel/opentelemetry-collector`; a live Langfuse round-trip stays open, named as blocked on the
> operator's own `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in
> `observability-export.spec.md` §"External verification" rather than skipped silently. Two
> recurring integration lessons: independent cards that version-bump the same still-Draft spec
> from the same base conflict on merge, predictably (happened three times, reconciled by hand
> each time); a card's own literal acceptance text can be stale relative to already-shipped code
> from an earlier card in the same phase (P32-8, P32-9) — implement against the verified live
> behavior and record the discrepancy, per AGENTS.md's rule, rather than choosing the convenient
> reading.
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




## ▶ WAVE 60 — ACTIVE (opened 2026-09-28): Phase 33, export privacy levels (D-49)

**Opened 2026-09-28 (Wave 60 active).** Six cards in four waves (one Sonnet worker, then two in
parallel, then two, then the integrator). Decision, the class and level tables, the eleven rules
and the verdict table are in [docs/adr/0015-export-privacy-levels.md](docs/adr/0015-export-privacy-levels.md).
Worker packets: [.agents/handoffs/wave-60-worker-packets.md](.agents/handoffs/wave-60-worker-packets.md).
**Activation gate met 2026-09-28:** Phase 32 closed at `5f53e52`, the Langfuse follow-up at
`940c3cd`; batching below is by function-level ownership.

**Trigger (explicit request + live evidence, 2026-09-28):** a real dispatch exported to Langfuse
rendered every generation's Input/Output as `null`/`undefined`; the operator asked for privacy
levels that are solid, configurable from the exporter's own settings, chosen consciously and
evident, so they know what they share and can turn it off. Measured at `940c3cd`: `payload:
full` changes nothing a destination renders (`gen_ai.chat`/`execute_tool` attribute sets are
closed; `core/agent_loop.py::_trace_llm_call` records no content); `payload: metadata` is a
denylist of eight key names (`core/telemetry.py::_CONTENT_KEYS`), so `approval_requested.action`
(a command line) and `error.error` (free text) already reach every enabled destination through
`_handle_generic_event`; nothing shows the operator what leaves. OTel GenAI semantic conventions
make content `Opt-In` and name the attributes; Langfuse reads those names natively.

**Spec ownership rule (the Phase 32 lesson, applied up front):** three Phase 32 merges conflicted
because parallel cards bumped the same spec from the same base. In this phase **workers add
requirements under their own new section heading in a pre-assigned number range and do not
touch `**Version**`, `**Status**` or the changelog**; the integrator bumps each spec once per
rollup. Ranges in `observability-export.spec.md` (last requirement today: 63): P33-1 64–79,
P33-2 80–87, P33-4 88–97, P33-5 98–101. P33-3 owns its sections in `trace-store.spec.md` and
`agent-loop.spec.md`.

**Test rule (ADR 0015):** one RED behavioural test per card in the module's `SUBJECT` file; a
negative case only for a fail-closed property (P33-1 canary under `minimal`, P33-3 byte-identical
record with no exporter above `minimal`, P33-4 widening off a TTY without `--yes`). Existing
tests, goldens and specs are the no-change oracle except where a card lists the change. No
worker probes a real vendor host or a real model endpoint.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 60 | P33-1 | `core/privacy.py` (new), `core/telemetry.py` (`ExportPolicy`, `project`, every `_handle_*`, `_new_root`, `capture_classes`, the one `ExportPolicy(...)` line in `start`), `tests/unit/core/test_privacy.py` (new), `tests/unit/core/test_telemetry.py`, `tests/fixtures/otlp-v1/` (two root attributes) |
| 61 | P33-2 ∥ P33-3 | `core/exporter.py::ExporterSpec` + audit detail lines, `core/telemetry.py::start` (policy from spec), `templates/exporters/*.yaml`, exporter schema (both copies), `cli/_exporters.py` + `cli/_config.py::_exporters_report` (`payload` readers only) → P33-2; `core/agent_loop.py::_trace_llm_call` + its two call sites, `cli/_trace.py::_render_event` (llm_call line only) → P33-3 |
| 62 | P33-4 ∥ P33-5 | `cli/_exporters.py` (`_run_list`, `_run_show`, `_run_enable`, `_run_add`, new `_run_privacy`), `cli/_config.py::_explain` renderer line, `cli/_doctor.py::_check_exporters`, `core/exporter.py::set_privacy` (new), `exporters list` golden → P33-4; `cli/_exporters_preview.py` (new), one `run_exporters` handler entry → P33-5 (the handler dict, usage text and `cli/__init__.py` exporters help are shared lines: the integrator reconciles) |
| 63 | P33-6 | integrator: seam test, docs, live proof at three levels, canary on the real wire, rollups, archive |

Every card follows the §"How to use this board" definition of done.

### P33-1 — what may leave is a class; the projection is an allowlist

**Status:** TODO · **Size:** M · **Wave:** 60 · **Spec:** `observability-export.spec.md` new sections "Privacy classes and levels" and "Allowlist projection" (requirements 64–79); requirements 11, 16 and 17 amended in place (integrator bumps the version)

**Trigger:** `core/telemetry.py::_CONTENT_KEYS` is a denylist; `_handle_generic_event` forwards
every scalar as `docket.<key>`, so `approval_requested.action` and `error.error` leave under the
default `metadata`; no handler can emit prompt/tool content at any setting.

**Goal:**
- `core/privacy.py` (new, pure data, imports nothing from `core/` but `typing`):
  `CONTENT_CLASSES = ("toolArguments", "errors", "toolResults", "completions", "prompts",
  "instructions")`; `LEVELS: dict[str, frozenset[str]]` with `minimal` = ∅, `actions` =
  {toolArguments, errors}, `conversation` = actions ∪ {toolResults, completions, prompts},
  `full` = all six; `resolve(privacy: str | None, share: Sequence[str] | None) ->
  tuple[str, frozenset[str]]` returning the label (`minimal`…`full`, or `custom` for a `share`
  list that equals no level) and the class set, raising `ValueError` on an unknown level, an
  unknown class, or both arguments given; `describe(classes) -> list[tuple[str, bool, tuple[str,
  ...]]]` (class, granted, attribute names) for the CLI.
- `core/telemetry.py`: `ExportPolicy(events, classes: frozenset[str] = frozenset(),
  label: str = "minimal", content_max_chars: int = 4000)`; `admit` filters by event only and
  never rewrites the payload. `project(record, state, policy=MINIMAL_POLICY)` threads the policy
  to handlers; `ATTRIBUTE_CLASSES: dict[str, str]` maps every attribute any handler can emit to
  `structure` or one content class, and one helper (`_granted(policy, cls)`) is the only way a
  content attribute is set. `_handle_tool_call` adds `gen_ai.tool.call.arguments` (toolArguments);
  `_handle_tool_result` adds `gen_ai.tool.call.result` from `text`/`output` (toolResults);
  `_handle_llm_call` adds `gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions` from the payload keys `inputMessages`, `outputMessages`,
  `systemInstructions` (written by P33-3; read defensively, absent today) and always
  `docket.instructions.sha256` when `systemInstructionsSha256` is present. Input messages are
  filtered **per part** (ADR 0015 rule 3): a `tool` role turn needs toolResults, an assistant
  `tool_call` part's arguments need toolArguments, a `system` turn needs instructions; a withheld
  part becomes `{"type": "withheld", "class": "<class>"}`. Every text part and every content
  attribute is cut to `content_max_chars` with the suffix `…[truncated <n> chars]`, JSON
  structure kept; message attributes are JSON strings.
- `_handle_generic_event` forwards only the keys in a per-event table `_STRUCTURAL_KEYS`
  (derive it from the call sites: `guardrail_*` → `hook`, `policy`, `action`; `approval_*` →
  `token`; `error` → `run`, `source`; budget/stale/paused/cancel events → their counters and
  ids; unlisted keys drop). `approval_requested.action` becomes `docket.approval.action`
  (toolArguments); `error.error` becomes `docket.error.message` (errors).
- `_new_root` gains `docket.privacy` (the policy label) and `docket.privacy.classes`
  (comma-joined, sorted, `""` for minimal).
- `capture_classes() -> frozenset[str]`: the union of the classes of the started pipelines'
  policies (empty when none is started). `start` builds `ExportPolicy(events=..., classes=
  frozenset(), label="minimal")` until P33-2 wires the document — the interim state narrows,
  never widens.
- Remove `_CONTENT_KEYS`, `_reduce_metadata`, `_reduce_full`.

**Non-goals:** the exporter document fields (P33-2); capturing model content (P33-3); any CLI.

**Owns:** `core/privacy.py` (new), `core/telemetry.py` (the functions named in the wave table),
`tests/unit/core/test_privacy.py` (new, `SUBJECT = docket.core.privacy`),
`tests/unit/core/test_telemetry.py`, `tests/fixtures/otlp-v1/dispatch-3-hops.json` (only the two
new root attributes), the spec sections. **Forbidden:** `core/exporter.py`, `core/agent_loop.py`,
`cli/`, `edges/`, `tests/fixtures/traces/`.

**Acceptance:**
- Fixture: every member of `core.trace.EVENT_TYPES` gets a synthetic record whose every string
  payload field is `CANARY-<event>-<key>`, plus an `llm_call` carrying `inputMessages` (system,
  user, assistant-with-tool-call, tool turns), `outputMessages`, `systemInstructions`, each part
  a distinct canary. Action: project and flush under each level and under each single-class
  `share`, then `otlp_http.encode`. Result: under `minimal` the encoded bytes contain no
  `CANARY-`; under each policy every canary found sits in an attribute whose
  `ATTRIBUTE_CLASSES` class is granted, and every granted class's canary is present. Oracle: a
  substring search over the encoded JSON, not the handler's own return value.
- `share: [prompts]` exports the user/assistant text of `gen_ai.input.messages` and a
  `withheld` part (class `toolResults`) in place of the tool turn's content.
- The committed wire golden differs from its base only by `docket.privacy: "minimal"` and
  `docket.privacy.classes: ""` on the root; P32-2's and P32-5's other assertions hold unchanged.
- A 10,000-character part under `content_max_chars=4000` exports as 4,000 characters plus the
  marker, and the attribute still parses as JSON.

**RED test:** the canary case in `tests/unit/core/test_telemetry.py` fails on the base
(`approval_requested`'s and `error`'s canaries appear under `metadata`). **Gates:** worker gates;
`tests/golden/run.sh verify-all` unchanged (no CLI output moves).

### P33-2 — the exporter document declares its privacy

**Status:** TODO · **Size:** M · **Wave:** 61 (after the Wave 60 rollup) · **Spec:** `observability-export.spec.md` "Exporter documents" amended + requirements 80–87; `config-format.spec.md` (exporter fields); `workspace-structure.spec.md` only if a template path changes (integrator bumps)

**Trigger:** privacy must be configurable from the exporter's own settings (the request);
`ExporterSpec.payload`/`payloadMaxChars` no longer mean anything after P33-1.

**Goal:**
- `core/exporter.py::ExporterSpec`: `privacy: Literal["minimal","actions","conversation","full"]
  | None = None`, `share: list[str] | None = None`, `content_max_chars: int = Field(4000,
  alias="contentMaxChars", gt=0, le=100_000)`; a model validator calls `core.privacy.resolve`
  (both set → refused naming both; unknown level/class → refused naming it); `privacy_label` and
  `privacy_classes` properties (unset = `minimal`). `payload`/`payloadMaxChars` removed; a stored
  document still carrying `payload` loads as `minimal` and `legacy_fields` names it (never a wider
  level; ADR 0015 rule 7).
- Every file in `templates/exporters/` declares `privacy: minimal` (including `otel-collector`,
  whose `payload: full` goes; its `note` says why: a collector forwards). Schemas regenerated
  (`scripts/gen_config_schemas.py`, both copies).
- `core/telemetry.py::start` builds `ExportPolicy(events=..., classes=spec.privacy_classes,
  label=spec.privacy_label, content_max_chars=spec.content_max_chars)`.
- Every reader of `spec.payload` moves to `privacy_label` (`cli/_exporters.py` show/enable
  lines, `cli/_config.py::_exporters_report` key `privacy` replacing `payload`, the audit detail
  strings in `core/exporter.py`), with no new UX (P33-4 owns that).

**Non-goals:** the `privacy` command, confirmation, `SHARES`, preview (P33-4/P33-5); capture
(P33-3).

**Owns:** `core/exporter.py` (`ExporterSpec`, the audit detail lines), `core/telemetry.py::start`
(the one constructor call), `templates/exporters/*.yaml`, the exporter schema (both copies),
`cli/_exporters.py` and `cli/_config.py` (the `payload` readers only), `tests/unit/core/test_exporter.py`,
`tests/integration/test_otlp_export.py` (only where it sets `payload`), the spec text.
**Forbidden:** `core/agent_loop.py`, `core/privacy.py` (read it; return a contention note if it
needs a change), every other `core/telemetry.py` function.

**Acceptance:**
- `docket validate` accepts `privacy: conversation`, accepts `share: [toolArguments]`, refuses
  both together, refuses `privacy: everything` and `share: [secrets]`, each naming the field.
- A global document `{kind: exporter, name: langfuse, payload: full, enabled: true}` in
  `docket-exporters.json` resolves to label `minimal`, classes ∅, and `legacy_fields == ["payload"]`.
- With a local `http.server` sink and `privacy: actions`, one real `run_turn` through the fake
  backend exports a span whose attributes include `gen_ai.tool.call.arguments`; the same with the
  document at `minimal` exports none (integration, `tests/integration/test_otlp_export.py`).
- `docket exporters list` golden unchanged; every built-in validates.

**RED test:** the `privacy: actions` integration case fails on the base (policy still minimal).
**Gates:** worker gates including `gen_config_schemas.py --check`.

### P33-3 — the model call records its content when, and only when, a destination asks

**Status:** TODO · **Size:** M · **Wave:** 61 (after the Wave 60 rollup) · **Spec:** `trace-store.spec.md` new section "Captured content" (the three optional `llm_call` keys, the capture rule, the dedup rule); `agent-loop.spec.md` "Tracing" amended; `harness-mode.spec.md` event row note (additive) (integrator bumps)

**Trigger:** `core/agent_loop.py::_trace_llm_call` records model, provider, tokens and latency,
never the conversation, so no level can show Langfuse a generation's Input/Output.

**Goal:**
- `_trace_llm_call(..., messages: Sequence[ChatMessage] | None = None)`; both call sites
  (`_TurnState.call_backend_and_handle_response` and the compaction summarizer) pass the exact
  list sent to `backend.complete`. With `granted = telemetry.capture_classes()`:
  `completions` ∈ granted → `outputMessages` (the reply: text parts + `tool_call` parts with id,
  name, arguments); `prompts` ∈ granted → `inputMessages` without the system turn (OTel shape:
  `{"role", "parts": [...]}`; tool turns as `tool_call_response` parts; P33-1 withholds the parts
  of classes an exporter was not granted); `instructions` ∈ granted → `systemInstructions` (the system
  turn's text) on the session's first call and whenever its SHA-256 differs from the last one
  recorded for that trace key, and `systemInstructionsSha256` whenever any content is captured.
  Parts cut to 4,000 characters here too (the bound on disk); the per-exporter cut is P33-1's.
- Empty `granted` → the payload is byte-identical to today's (no key added, no JSON reordering).
- `cli/_trace.py::_render_event`: an `llm_call` line with captured content ends in
  `+content(<keys>)`; nothing changes otherwise.

**Non-goals:** filtering per exporter (P33-1 does it at projection); any exporter field (P33-2).

**Owns:** `core/agent_loop.py::_trace_llm_call` and its two call lines, a module-level helper for
the message shape, `cli/_trace.py::_render_event` (the `llm_call` branch), `tests/integration/test_agent_loop.py::TestLlmCallTrace`,
the three spec sections. **Forbidden:** `core/telemetry.py` (call `capture_classes()` only),
`core/exporter.py`, `edges/`, `core/session.py`.

**Acceptance:**
- With `capture_classes` returning ∅ (no pipeline started), a two-iteration turn through the
  fake backend writes `llm_call` records byte-identical to the base branch's for the same input.
- Monkeypatching `capture_classes` to `{"prompts","completions"}`: the second call's record
  holds `inputMessages` (user, assistant with a tool call, tool turn) and `outputMessages`, no
  `systemInstructions`; a secret-shaped string in a tool result arrives redacted (`redact` at
  write). With `{"instructions"}` the first call records `systemInstructions` and the second
  does not (same hash), both carry the hash.
- `docket trace <session>` shows `+content(inputMessages,outputMessages)` on those lines.

**RED test:** the `{"prompts","completions"}` case in `TestLlmCallTrace` fails on the base.
**Gates:** worker gates; the `docket trace` golden unchanged (its fixture has no content).

### P33-4 — widening is a confirmed command; the level is shown everywhere

**Status:** TODO · **Size:** M · **Wave:** 62 (after the Wave 61 rollup) · **Spec:** `observability-export.spec.md` new section "Privacy commands and disclosure" (88–97); `cli-interface.spec.md`, `cli-json-shapes.spec.md` (integrator bumps)

**Trigger:** nothing tells the operator what leaves before or after enabling; a level must be
chosen consciously (the request).

**Goal:**
- `core/exporter.py::set_privacy(name, privacy=None, share=None, content_max_chars=None) ->
  ExporterSpec`: writes only the changed keys into the global override (the `enable_exporter`
  mould), returns the effective spec; `is_widening(old, new) -> bool` (new classes ⊄ old).
- `docket exporters privacy <name> [<level>|--share a,b] [--max-chars N] [--yes]`: no argument
  prints the "Leaves this host" block; a widening prints each newly granted class with one example
  attribute and the destination host, then asks on a TTY (`y/N`) and, off a TTY, exits 1 naming
  `--yes` and writes nothing; narrowing never asks. `enable --privacy <level>|--share` follows the
  same rule. `add <file>` with a document above `minimal` follows it too.
- Audit `exporter.privacy` with `name`, `from`, `to`, `host` (never content).
- `exporters list`: a `SHARES` column (label). `show`: "Leaves this host" (`core.privacy.describe`:
  ✓/✗ per class, its attributes, and "never: credentials, secret-shaped values (redacted)").
  `enable` always prints `shares: <label> (<classes or "structure only">)`. `config explain`
  prints the label per exporter; `--json` carries `privacy: {label, classes}`. `doctor` adds an
  informational line for `conversation`/`full` to a non-loopback host, and one per legacy
  `payload` field naming `docket exporters privacy <name> <level>`.

**Non-goals:** preview (P33-5); any projection change.

**Owns:** `cli/_exporters.py` (`_run_list`, `_run_show`, `_run_enable`, `_run_add`, new
`_run_privacy`, one handler entry), `cli/__init__.py` (the exporters help text),
`cli/_config.py::_explain` renderer, `cli/_doctor.py::_check_exporters`,
`core/exporter.py::set_privacy`/`is_widening` (new), `tests/unit/cli/test__exporters.py`,
`tests/integration/test_exporters_cli.py`, the `exporters list` golden, `docs/commands.md`
(regenerated), the spec sections. **Forbidden:** `core/telemetry.py`, `core/privacy.py`,
`cli/_exporters_preview.py`.

**Acceptance:**
- Off a TTY, `docket exporters privacy langfuse conversation` exits 1 naming `--yes`, and the
  global file and audit log are byte-identical before and after; with `--yes` it exits 0, the
  override holds `privacy: conversation` only, and one `exporter.privacy` entry names
  `from=minimal to=conversation host=cloud.langfuse.com`.
- `docket exporters privacy langfuse minimal` after that never asks and audits the narrowing.
- `list` shows `SHARES`; `show langfuse` lists every class with ✓/✗; the `list` golden changes
  by exactly the new column (listed line by line).

**RED test:** the off-TTY widening case in `tests/integration/test_exporters_cli.py` fails on the
base (no `privacy` action). **Gates:** worker gates; `gen_cli_docs.py --check` after regeneration.

### P33-5 — see what a destination would receive before sharing it

**Status:** TODO · **Size:** S · **Wave:** 62 (after the Wave 61 rollup) · **Spec:** `observability-export.spec.md` new section "Preview" (98–101); `cli-interface.spec.md` (integrator bumps)

**Trigger:** the request asks that the operator *know what they are sharing*; the only proof
today is opening the destination after the fact.

**Goal:** `cli/_exporters_preview.py` (new): `docket exporters preview <name> [--session <id>]
[--level <level>|--share a,b] [--json]`. It reads the named local session (default: the newest
trace under `TRACES_DIR`), projects every record through that exporter's `ExportPolicy` (or the
overriding `--level`/`--share`, which is never written), and prints, per span, its name and each
attribute with its class, content shown to 200 characters; a footer counts spans, attributes per
class and total bytes. `--json` prints the exact `otlp_http.encode` document. No network call, no
write, no audit.

**Non-goals:** changing the policy (P33-4); capture (P33-3).

**Owns:** `cli/_exporters_preview.py` (new), one `run_exporters` handler entry,
`tests/integration/test_exporters_cli.py` (a new class), the spec section. **Forbidden:**
`core/`, `edges/`, every other function in `cli/_exporters.py`.

**Acceptance:**
- With a seeded session containing a canary in a tool argument, `preview langfuse` (minimal)
  prints no canary and a footer with zero content attributes; `preview langfuse --level actions`
  prints the canary under `gen_ai.tool.call.arguments [toolArguments]`; the global file, the
  health file and the audit log are unchanged after both.
- `--json` output equals `otlp_http.encode` of the same projection (byte comparison).

**RED test:** the minimal/actions pair fails on the base (no `preview` action). **Gates:**
worker gates.

### P33-6 — docs, live proof at three levels, close (integrator)

**Status:** TODO · **Size:** M · **Wave:** 63 (after the Wave 62 rollup) · **Spec:** `observability-export.spec.md` → final version, Status "Implemented and live", "External verification" gains a "Privacy levels" subsection; `specs/README.md` rows for every bumped spec

**Goal:**
- The seam test ADR 0015 assigns the integrator: the real `_trace_llm_call` (P33-3) into the
  real projection (P33-1) under `conversation`, asserting the generation carries both message
  attributes and under `share: [prompts]` a `withheld` tool part.
- Live proof on this machine, one real dispatch per level, with a unique canary in the delegated
  task and in a file the agent reads: `minimal` — the collector's debug log and Langfuse show no
  canary, Input/Output empty; `actions` — tool spans show arguments, no file contents;
  `conversation` — Langfuse generations show Input/Output and tool results. `preview` run before
  each and matched against what arrived.
- Docs: `docs/CONFIGURATION.md` §3.14 rewritten around the level table and the three commands
  (`privacy`, `preview`, `enable --privacy`); `docs/SECURITY-SIMPLE.md` Layer 6 around classes;
  the README "gate and record" sentence only if its claim moves; `CHANGELOG.md`;
  `docs/commands.md` regenerated.
- Board: rollups, `scripts/metrics.py --check` re-measured, `split_board.py archive`, ROADMAP
  status line and D-49 row re-trued.

**Acceptance:** every gate in §"How to use this board" green on `main`; the three live results
recorded in the spec with dates; no canary found at `minimal` in either destination.
