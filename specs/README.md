# Docket CLI Specification Documentation

This directory contains all specifications following the SSD (Spec-driven Development) workflow
for the docket project.

**The prime rule: a spec's Status line matches the code, always.** Every spec is a
current-state contract. When a requirement is aspirational, the spec says so explicitly and
names the ROADMAP card that will make it true (the 2026-07-30 Platformization baseline pass
re-trued every spec; Phase 14's R-8 card keeps them true as behavior changes).

## Specification Structure

```text
specs/
├── README.md                              # This file — overview and index
├── test-framework.md                      # Test conventions and coverage methodology
├── functional/                            # Functional specifications
│   ├── agent-lifecycle.spec.md           # Agent CRUD and maintenance operations
│   ├── agent-loop.spec.md                # The turn loop + daemon-free RuntimeDriver (Phase 19 P19-5)
│   ├── api-keys.spec.md                  # API key management
│   ├── audit.spec.md                     # Audit log events, hash-chained + verify
│   ├── cost-tracking.spec.md             # Usage/cost reporting + budget caps (auto-pause shipped)
│   ├── mcp-client.spec.md                # MCP client: pluggable tool servers (Phase 19 P19-10)
│   ├── model-profiles.spec.md            # Role→model policy and pinning
│   ├── observability-export.spec.md      # Neutral span model + export policy over the trace store (Phase 32 D-48)
│   ├── operator-loop.spec.md             # The operator-v1 contract: A2A states, MCP-elicitation questions, CloudEvents (Phase 34 D-50)
│   ├── pipeline-format.spec.md           # docket-native pipeline YAML format + executor (W-1/W-2)
│   ├── config-format.spec.md             # The `kind:` envelope, one loader, short forms, published schemas
│   ├── pod-blueprints.spec.md            # Built-in pod blueprints (software/research/content/ops/agentic-product)
│   ├── pod-dispatch.spec.md              # Pod dispatch pipeline state machine and gates
│   ├── role-archetypes.spec.md           # Declarative role archetypes (registry, overlay, CLI)
│   ├── security-gates.spec.md            # Tool-approval gates (on by default; docket-enforced)
│   ├── session-history.spec.md           # Durable per-session turn history + compaction (Phase 19 P19-4)
│   ├── session-scoping.spec.md           # Multi-project session isolation
│   ├── telegram-integration.spec.md      # Telegram bindings + docket-owned bot (Phase 19 P19-8)
│   ├── trace-store.spec.md               # Durable per-session JSONL trace store, EVENT_TYPES, subscribe seam
│   └── workspace-structure.spec.md       # Per-agent workspace layout
├── api/                                   # API contracts
│   ├── cli-interface.spec.md             # CLI command contracts and return codes
│   ├── harness-mode.spec.md              # docket harness — one agent, one turn, NDJSON wire (Phase 24 D-35)
│   ├── mcp-server.spec.md                # docket mcp serve — MCP tool surface (Phase 18 L-3)
│   └── runtime-library.spec.md           # docket-runtime: the embeddable substrate (Phase 21 P21-1)
├── data/                                  # Data specifications
│   ├── cli-json-shapes.spec.md           # --json output shapes per command
│   ├── docket-meta.spec.md               # .docket-meta.json schema
│   ├── docket-store.spec.md              # Atomic JSON writes and corrupt-primary recovery
│   └── serve-read-api.spec.md            # docket serve read-only HTTP API (test-pinned)
├── acceptance/                            # Acceptance criteria
│   ├── starter-journey.spec.md           # Extractable artifact-installed starter journey
│   └── user-stories.md                   # User stories with Gherkin scenarios
└── validation/                            # Validation rules
    ├── adoption-benchmark.spec.md        # Deterministic benchmark artifact contract
    └── input-validation.spec.md          # Input validation rules
```

Retired specs are **deleted**, not archived here: the durable retirement record lives in
ROADMAP.md's decision table, and git history retains the text. (Removed so far:
team-coordination.spec.md, 2026-07-30 — `docket team` was retired per D-11; pod-dispatch.spec.md
owns delegation now. workflow-integration.spec.md, 2026-07-30 — `docket workflow`'s Lobster YAML
surface was retired per D-16; pipeline-format.spec.md owns the pipeline dialect docket actually
executes now. eval.spec.md, 2026-08-04 — `docket eval` was removed per CL-J; the specialist-role
eval harness (`tests/evals/`) was dead code wired to the retired runtime, and — unlike
`workflow`/`team` — has no successor command; `docket eval`/`docket evals` now print a
removed-command notice with no replacement.)

## SSD Workflow Process

### 1. Specification First

Before implementing any feature:

1. Write the functional specification in `specs/functional/`
2. Define API contracts in `specs/api/`
3. Document acceptance criteria in `specs/acceptance/`
4. Create validation rules in `specs/validation/`

### 2. Test-Driven Development

1. Write tests based on specifications
2. Tests should fail initially (red phase)
3. Implement minimum code to pass tests (green phase)
4. Refactor while maintaining passing tests (refactor phase)

### 3. Continuous Validation

- All changes must have corresponding spec updates
- Specs are version controlled and reviewed
- Breaking changes require spec migration plans
- CI validates spec structure on every push (`scripts/validate-specs.sh`, blocking)

## Specification Standards

### Document Structure

Each specification document must include:

- **Purpose**: Clear statement of what the spec defines
- **Scope**: Boundaries and limitations — and a "does NOT cover" list naming the owning spec,
  so no two specs own the same contract
- **Requirements**: Numbered list of MUST/SHOULD/MAY requirements
- **Interfaces**: Detailed API/CLI contracts
- **Examples**: Concrete usage examples
- **Validation**: How to verify compliance
- **Version**: Spec version and changelog

### Requirement Keywords (RFC 2119)

- **MUST/SHALL**: Absolute requirement
- **MUST NOT/SHALL NOT**: Absolute prohibition
- **SHOULD**: Strong recommendation
- **SHOULD NOT**: Strong discouragement
- **MAY/OPTIONAL**: Truly optional

### Versioning

- Specs use semantic versioning (MAJOR.MINOR.PATCH)
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Clarifications and fixes

## Current Specification Status

> This table mirrors each spec's own `**Version**`/`**Status**` header (the authoritative
> source). If they disagree, the spec header wins — fix this table.
> Last synchronized: 2026-09-29 (Phase 34 follow-up, closing the P34-17 gap: `docket inbox`,
> `docket channels`, `docket notify`, `pod <p> explain interruptions`/`pregrant` documented in
> CLI Interface (1.58.0); `POST /tasks/<id>/pregrants` documented in Serve Read API (2.15.0);
> the `task_pregrant` MCP tool documented and the stale "twelve tools" claim in `docket mcp
> serve --help` corrected to thirteen (MCP Server 1.7.0); `scripts/maint/check_spec_index.py`
> reconciled clean).
> Last synchronized: 2026-09-29 (Phase 34 close, P34-17 integrator, D-50/ADR 0016: added the
> Operator Loop row (every requirement area now Implemented, two stub areas corrected from
> "Planned — owned by P34-N" to match the merged code); bumped Agent Loop to 1.29.0, Security
> Gates to 0.28.0, Pod Dispatch to 6.24.0, Pipeline Format to 2.11.0, Config Format to 1.6.0,
> Serve Read API to 2.14.0, MCP Server to 1.6.0 (12 tools), CLI Interface to 1.57.0, and
> Telegram Integration to 2.3.0; corrected Starter Journey to 1.0.1 (a real regression the
> starter's own persisted-shape check caught: `HandoffArtifact` gained `brief`, unnoted in the
> spec or the starter's own field list); `scripts/maint/check_spec_index.py` reconciled clean.
> Previously synchronized 2026-09-28 (Wave 59, P32-9: external verification against a real dispatch
> and a real OpenTelemetry Collector bumped Observability Export to 1.5.0, "Implemented and
> live" — Phase 32, D-48, closes; Langfuse verification stays open, named in the spec's
> "External verification" section as blocked on the operator's own credentials;
> `scripts/maint/check_spec_index.py` reconciled clean).
> Previously synchronized 2026-09-27 (Wave 58, P32-6/P32-7/P32-8: the pipeline wired into
> `run_turn` and `docket exporters enable/disable/test/add/remove` bumped Agent Loop to 1.26.0,
> Config Format to 1.5.0, Pod Blueprints to 1.20.0, CLI Interface to 1.55.0 and CLI JSON Shapes
> to 1.15.0; Observability Export reached 1.4.0, "Implemented — awaiting external verification";
> `scripts/maint/check_spec_index.py` reconciled clean).
> Previously synchronized 2026-09-27 (Wave 57, P32-3/P32-4/P32-5: `task_id` on the trace record and
> the ingest-notifies-subscribers fix bumped Trace Store to 1.1.0, Pod Dispatch to 6.23.0 and
> Serve Read API to 2.13.2; the `kind: exporter` document, its built-in + global catalog, and
> the five shipped destinations bumped Observability Export to 1.1.0, Config Format to 1.4.0
> and Workspace Structure to 1.15.0; the `otlp-http` wire dialect bumped Observability Export
> again to 1.2.0; `scripts/maint/check_spec_index.py` reconciled clean).
> Previously synchronized 2026-09-27 (Wave 56, P32-1/P32-2: added Trace Store and Observability
> Export — the trace store's first spec of its own, and the neutral span/projection layer
> above it — bumped Agent Loop to 1.25.0 for the `llm_call` trace event and Harness Mode to
> 1.1.2 for its additive `event` row; `scripts/maint/check_spec_index.py` reconciled clean).
> Previously synchronized 2026-09-12 (added the three rows this table was missing — Starter Journey,
> Docket Store, Adoption Benchmark — added Pod Blueprints to the file tree, corrected three drifted
> versions — Agent Loop, Security Gates, CLI Interface — corrected the Harness Mode row's fixtures
> path, and replaced the stale on-disk spec-file count below; `scripts/maint/check_spec_index.py`
> now derives this reconciliation instead of a model re-reading the tree).
> Previously synchronized 2026-08-31 (W26-C5/C7/C9 reconciled runtime packaging, approval atomicity,
> and conversation mutation contracts/versions; the on-disk index remains authoritative).
> Previously synchronized 2026-08-26 (W25-C8 made the live startup projection non-contradictory
> and reconciled the agent-loop contract/version).
> Previously synchronized 2026-08-25 (W25-C3/C4/C6/C7 reconciled agent-loop, serve-run, and
> test-harness contracts plus their current versions and on-disk index count).
> Previously synchronized 2026-08-19 (W21-C1 daemon-free truth pass: current contracts, examples,
> and fixture paths now describe Docket's owned runtime and state root).
> Previously synchronized 2026-08-03 (Phase 19 CLOSED — the removal wave P19-7a/P19-7b deleted the
> daemon, and P19-8 made Telegram a real approval channel; every row below re-derived from its
> spec's own header, not carried forward).
> Previously synchronized 2026-07-31 (Phase 19 P19-5 added Agent Loop — see its row below).
> Previously synchronized 2026-07-31 (Phase 19 P19-4 added Session History — see its row below).
> Previously synchronized 2026-07-30 (wave 6 complete: L-5, W-5b, C-1, C-2, G-2 — after wave 5's
> L-4, G-4b, W-4, CL-2, W-5 and wave 4's CL-1, L-6, W-3, W-7, W-2+W-8 and wave 3's G-1, G-5, W-1,
> W-6, L-1, L-3).
> The `Workflow Integration` row was dropped here, one merge late: W-3 deleted the spec file itself
> (D-16) but the row survived the wave-4 index reconciliation. The row count is now exactly the 27
> `.spec.md` files on disk (`Test Framework` and `User Stories` are separate rows for plain `.md`
> docs, not counted in that total).
> Verified row-by-row against every spec's own `**Version**` header, not carried forward — an
> index table cannot be auto-merged correctly when several branches bump versions in parallel.

| Specification | Version | Status | Notes |
| ------------- | ------- | ------ | ----- |
| Agent Lifecycle | 2.0.0 | Complete | `docket init` provisions the pod's own members and no shared agent (org specialists removed); `docket init` creates the project pod; `docket add` only extends an existing pod; pod deletion purges runtime/session/trace state but preserves audit; `maintain distill` + exact durable records |
| Agent Loop | 1.32.0 | Implemented and live | A batch containing a parked in-turn call (`denial_kind == "approval_parked"`) stops the turn exactly like `approval_unavailable`, naming tool/call/policy/token; harness mode always sets `refuse`, so this stop reason structurally never reaches the harness-v1 contract; `DocketDriver.run_turn` starts the observability export pipeline lazily and flushes it, writing the health file, on every return path; zero enabled exporters is a no-op; Every backend chat-completions exchange (each turn iteration, plus the compaction summarizer's own call) is a durable `llm_call` trace event carrying model, provider, measured latency and token counts, never a dollar figure; A `# Skills` index section (screened descriptions, capped, reported as `skills`) and the `skill` built-in tool of kind `read`; A codebase root `AGENTS.md` composes as the project-instructions section by default when `projectInstructions` is unset (screened, capped, reported); an explicit list replaces it; The production turn loop is gated, role-narrowed, composes one runtime-safe startup projection, durably compacts and trace-separates history, preflights every known-window request, reserves one bounded tool-free terminal response, bounds consecutive typed tool denials, and never recompacts the same logical request-fit segment without new tool growth |
| API Keys | 1.8.0 | Complete | Central keys feed resolved endpoints directly; a stored key alone readies a built-in hosted provider; `keys setup` prompts for every credential the provider catalog declares, in catalog order; credential presence alone never claims provider readiness |
| Audit | 2.12.0 | Implemented | Rotation, head lookup, durable append, and coherent readers share one audit lock; approval terminal decisions emit exactly one matching winner event |
| Config Format | 1.9.0 | Implemented | A `kind: mcp-server` document may declare `isolate: false`; `kind: channel` joins the envelope (`core/channel.py::ChannelSpec`), canonical-only like `exporter`, with its published JSON Schema under `docs/contracts/config-v1/`; `pod.yaml`'s manifest key set gains `exporters`; `exporter` joins the `kind:` envelope (`core/exporter.py::ExporterSpec`), with its published JSON Schema under `docs/contracts/config-v1/`; The pod manifest key set gains an optional `description`; Every role, pipeline, policy, pod-manifest, provider, exporter and channel file declares `kind:` and `name:`; `core/config_docs.py::load_document` dispatches on `kind` to the parser that owns it (a file without `kind` loads with a deprecation note); short-form Pydantic models give `docket validate` field-level errors and generate the published JSON Schemas under `docs/contracts/config-v1/` (pinned byte-for-byte, shipped with the package for `export`'s `.schemas/`) |
| Cost Tracking | 1.8.0 | Implemented, recorded dollars unavailable | Auto-pause is real; measured tokens are durable, while `DocketDriver` reports no billed dollar amount. Budget gating uses a separately labelled estimate. Daily history remains empty because sessions do not store per-turn timestamps |
| Model Profiles | 3.2.0 | Complete | Roles are archetype names (`lead`, `implementer`, ...); `policyRole` and the `manager`/`programmer`/`knowledge`/`security`/`repo` rows are gone; an unknown `docket-models.json` key is ignored and reported by `doctor`; A pod-scoped archetype resolves its `modelClass` in its pod's registry (a recipe's role follows the fleet's preset, never the compiled-in literal) and an unknown role falls back to the registry default; A pipeline step's own `model:` (`cheap`/`strong`/literal) wins for that hop only and is never persisted; Providers are `kind: provider` documents in a catalog (fourteen built-in under `templates/providers/`, the operator's own in `docket-providers.json`, nearest-wins) that name their credentials and never hold a value, authenticate by bearer, a named header or nothing, and may send static headers; presets, prices, key prefixes and base URLs all derive from the catalog; registration probes `/models` with the resolved credential and classifies the answer (only a transport failure refuses); `config explain` reports provider, scope, credential source and the exact row; `doctor` reports a malformed global document; a pre-catalog `fleet.json` block migrates once |
| Observability Export | 1.12.1 | Implemented and live | `core/telemetry.py` deterministically projects `core/trace.py` records into a neutral `Span`/`SpanEvent` model, runs the bounded queue/background-sender `Pipeline`, and an `ExportPolicy` admits events and grants content classes through an allowlist (`core/privacy.py` levels `minimal`/`actions`/`conversation`/`full`, ADR 0015); `core/exporter.py`'s `kind: exporter` document, built-in + global catalog (five ready-made, disabled-by-default destinations under `templates/exporters/`), and `enable_exporter`/`disable_exporter`; `edges/adapters/exporters/otlp_http.py` encodes and sends the one shipped wire dialect; `edges/adapters/docket_runtime.py::run_turn` starts the pipeline lazily and flushes it on every return path; `docket exporters list|show|enable|disable|test|add|remove|export` turns a destination on by authenticating; `pod.yaml`'s `exporters:` key names a pod's destinations, validated, never itself activating; verified live against a real dispatch, a real OpenTelemetry Collector and a real, dashboard-confirmed Langfuse round-trip at every privacy level; one pod session is one trace, every hop's generations keeping their own span ids under one root that carries the session's task and last answer when `prompts`/`completions` are granted |
| Pipeline Format | 2.14.0 | Implemented | A step may declare `input: {from: <step id>, message?}` (ADR 0016 §4), running no agent turn: parks the task `waiting_input` and routes on `answered`/`declined`; A step may declare `model: cheap|strong|<provider>/<id>` (canonical and short form), refused at `validate`/`plan` when the provider is not in the catalog; `core/pipeline.py` format, `core/dispatch.py` executor, `core/orchestrator.py` planner; short form (`id: role` plus `verify`/`verdict`/`approval`); control flow as bounded data: `on:` routes any gate outcome to `fail`, `stop` or a step (a backward edge needs `max`), `until: verify` + `max`, `when: {changed, var/is, memberPresent}` skips a step, `run:` is a command step with no agent turn; `validate`/`plan` reject a missing bound and an unreachable step |
| Pod Blueprints | 1.26.0 | Implemented | `code-intel`'s `ast-grep` server is declared `isolate: false` (measured: `uvx` cannot write its cache in the jail); A recipe's `pod.yaml` may name `exporters`; `apply`/`recipes show` report each one's activation state and never activate one; Recipe listing derives `brings`; three recipe scopes (path, `~/.docket/recipes/`, shipped) and `docket recipes list|show`; a recipe's `skills/` is applied, exported and digested; `render()` prints `pipeline none`; The recipe library: twelve shipped recipes of three kinds (teams, policy packs on structured predicates, methodology pipelines `tdd`/`spec-first`/`reflexion`/`dual-review`/`frugal`); `summarize_recipe` derives what a directory brings; `pod.yaml` `description`; `apply` records source and digest on every validated apply; `pod <p> apply <name|dir>` resolves a shipped recipe by name; `docket init` validates and applies a present `<location>/.docket/` (or `--recipe <name|dir>`, `--no-apply`); `apply` records `configSource`/`configDigest`; `export [<dir>]` defaults to `<codebase>/.docket/`; Five built-ins — software/research/content/ops plus `agentic-product`; deliberately data, not scaffolding. `docket init --blueprint`/`--from`; dispatch runs a blueprint's default pipeline; `docket pod <p> apply <dir>` applies a recipe/manifest (`roles/`, `policies/`, `plugins/`, `pipeline.yaml`, `pod.yaml`) to a pod's own scope and `export` writes it back in the short form with a schema header, proven by a round trip that plans every item `skip` |
| Pod Dispatch | 6.36.0 | Complete | A parked dispatch records `waiting_input`/`waiting_approval`, never `succeeded`; a `failed` task is retryable (`retry_task`, audited); `--resume` reclaims a stale claim (dead `claimPid` or lease past `turnTimeoutS + verifyTimeoutS`); one task-reference resolver (`core/task_ref.py`); One sweep worker per pod (`DISPATCH_SWEEP_WORKERS`); a refused isolation/network posture settles `dispatch_refused` without a retry; the pod `network` setting; Parked approvals (`approvalMode: "park"`) re-enter through the exact hop with a single-use pre-grant, never `gateOverridePipelineIndex`; operator `input` steps park `waiting_input` and `core.answers.answer_task` resumes on the step's own route; the Lead's typed `TaskBrief`, a deterministic `secret:`/`path:`/`verify` resource check, and the Implementer's `## Brief` view; `docket pod <p> pregrant` records a task-scoped exact-command pre-grant through the same digest matcher; Every hop-scoped trace event carries `task_id`; A step `model` is resolved once per hop and handed to the production driver for that hop only; Hop execution/history/handoff behavior is live; a retry waits `min(max(backoff x N, Retry-After), DISPATCH_RETRY_MAX_WAIT_S)` and `hop_retry` records `retry_after_s`; a step's `on:` map routes gate outcomes (`route_taken`), a `when` predicate skips a step (`step_skipped`), a `run` step executes a classified command with no agent turn (`command_step`); pod settings include `mcpServers` and `deniedTools`; the Lead's hop instruction is archetype data; conversation hops mutate one validated locked registry |
| Role Archetypes | 1.23.1 | Implemented | `policyRole` removed from the role document (refused as an unknown key); an archetype's model row is its own name; `kind: role` names the kind, not the form (a canonical-only key makes a document canonical; mixed forms refused); `editRights` is retired: accepted and dropped on read, never written; `deniedTools` is the only capability statement; Built-ins, load-bearing `gateContract`, pod-blueprint composition, per-role `tokenBudget`, enforced `deniedTools`, Docket-owned overlays at global and pod scope (`roles add|list|show --pod`, nearest-wins by name), and a short authoring form (`cannot`, `verdict|verify|approval`, `model`, prose in a `.md`) normalised by `normalize_role` |
| Security Gates | 0.36.0 | Implemented (gate always on; isolation opt-in) | Bare `gates isolate` is a read (posture + usage, exit 2, nothing written); Isolation opt-in again (ADR 0021: `gates isolate on`, needs bwrap or docker; bwrap first, fails closed naming both fixes, git dirs writable with hooks/config read-only); `gates network none` and a pod `network` setting cut the jail's network; `fetch` results pass `pre_input`; file tools skip walked paths outside the roots; task processes never see docket's credentials; `ToolContext.approval_mode` gains `"park"`: an in-turn `ask` ends the turn immediately with a durable approval record instead of blocking; `core.approval.create_pregrant`/`consume_pregrant` give a human's grant a single-use, digest-matched pass on a later re-entered turn, fail-closed on expiry; Every tool call Docket dispatches passes through `core/tools.py`; policies are short-form YAML or JSON with structured `when` predicates over the call (`tool`, `path`, `matches`, `branch`, `anyOf`) and a `plugin` predicate that runs operator-applied Python from `~/.docket/plugins/` or a pod's `config/plugins/` only, fail-closed, hashed and audited; pending approvals resolve through one conditional locked transition. General egress remains open by decision D-23 |
| Session History | 1.5.0 | Implemented and live | `core/session.py`: durable opaque-key history, lossless round-trip, bounded hierarchical atomic/ranged compaction, isolated summarizer key, recursion guard, and whole-operation fail-closed behavior; request fit can preserve the current task while compacting selected history |
| Session Scoping | 3.0.0 | Complete | Base metadata scope remains `agent:<id>:<project>`; pod dispatch derives isolated step-history keys and keeps a separate task trace without deleting prior sessions (W20-C4) |
| Telegram Integration | 2.5.0 | Implemented | A fifth verb, `/answer <task-id> <text>`, resolves through `core.answers.answer_task`; the outbound `telegram` `kind: channel` dialect pushes to every chat id in the channel's own `actors` list, never a `fleet.json` binding, never from `core/telegram.py` itself; outbound messages now exist through exactly two AST-pinned call sites; `docket wire` discovers a group from a one-time Telegram command with manual fallback; Docket owns the bot and approval path, unbound chats fail closed, and delegated text passes through input policy |
| Trace Store | 1.6.0 | Implemented and live | The key-shaped redaction pattern matches only at a word start; An optional `task_id` on the record, written only when truthy; `trace_ingest` notifies subscribers before appending; the durable per-session JSONL trace store every trace-emitting module writes through — the record shape, the full `EVENT_TYPES` vocabulary, `redact`'s secret-shape scrubbing, the `subscribe` seam a live consumer reads from without touching disk, the `trace_ingest` bridge, and retention |
| Workspace Structure | 1.19.0 | Complete | No shared agents: `workspaces/` holds pod members only; `templates/exporters/` ships the five built-in `kind: exporter` documents; `~/.docket/recipes/<name>/` is operator-owned; skills scopes `~/.docket/skills/` and a pod's `config/skills/`; `DOCKET_HOME` is the only state root; specialist and workdir workspace contracts plus role-aware `TOOLS.md` are live |
| CLI Interface | 2.0.0 | Complete | The eleven commands of ADR 0022 (`init status inbox task run pod log setup start stop exec`), one section per command with its verbs; pod targeting (`--pod`, `DOCKET_POD`, then the directory you stand in); grouped help with one tagline, `-h` everywhere, the bare three-part guide and tree-built completions; the console voice and the interaction contract (plain ASCII when piped or `NO_COLOR`, exit 2 for usage, no picker, no positional pod id); `docket exec` keeps the harness contract 1.0/1.1; retired names are ordinary unknown commands and `CHANGELOG.md` is their only record |
| MCP Client | 1.9.1 | Implemented and wired to the live turn path | stdio servers start in the turn's jail (backend, roots, network) unless declared `isolate: false`; results screened by the shared `screen_tool_result`; External tools are namespaced, description-screened, loaded before role narrowing, and dispatched through the same gated chokepoint. A server declares its `kind` (`read`/`write`, default `write`) and an optional `tools` allow-list; a pod selects its servers with `mcpServers`, and a stale selection refuses the dispatch. Remaining limits: stdio only, no listing cache, undeclared servers stay write-only. |
| Runtime Library | 2.2.0 | Implemented (artifact-tested; **not published to any index**) | `docket-runtime` `0.3.0` exclusively owns `docket_runtime/`; its bounded envelope and pinned standard OpenHands SDK/PydanticAI configurations preserve reported usage, sole-chokepoint dispatch, paired identity traces, hash-chained audit, and typed handoff when relevant tools are exclusively Docket-backed; wheel and sdist remain disjoint from `docket` |
| Harness Mode | 1.7.0 | Implemented | `docket harness run`/`status` — one agent, one turn, to completion, in a caller-owned workspace and home; NDJSON events and one versioned result on stdout, with the published schema under `docs/contracts/harness-v1/` and fixtures under `tests/fixtures/harness-contract/v1/`; the `event` field row is additive-only (an `llm_call` event may appear on the stream; the schema is unchanged) |
| MCP Server | 1.9.1 | Implemented | `docket mcp serve` — 13 tools (`task_answer`, `task_pregrant`, `inbox` join the original ten), stdio, optional `docket[mcp]` extra, using the `mcp` 2.x SDK |
| CLI JSON Shapes | 1.26.0 | Complete | Run `state` admits `waiting_input | waiting_approval`; `models` keys are archetype names; `doctor --json` `checks.notifications {ok, delivering}`; `doctor --json` `securityGates.isolation` reads `off (default)` with no recorded choice and carries the sandbox backend and the network mode; `config explain --json` carries `network {mode, scope}`; `docket exporters list --json`; `config explain --json` carries an `exporters` block; `config explain --json` carries `skills: [{name, scope}]`; `config explain --json` carries `projectInstructions: {files, source}`; Docket-owned doctor/fleet contract and current snapshot channel provenance; `config explain --json` carries the `provider` block and `configSource`/`configDigest`/`drift` |
| docket-meta schema | 3.6.0 | Complete | `scope` is always `project`; `org` and `kind: specialist` are removed; Pod resource metadata is backed by collision-free allocation and attempt-owned rollback that preserves pre-existing runtime state |
| Docket Store | 1.0.0 | Implemented | Durability and recovery contract for Docket-owned JSON: a malformed primary never makes a valid backup unusable, and recovery never hides the bytes that explain the incident |
| Serve Read API | 3.4.0 | Stable | API version 4: `/status.json` agents are pod members only; run `state` admits the two parked states; API version 3: `gateway` removed from `/status.json`, `/health` is `{"status":"ok"}`, `docket_gateway_up` gone; `POST /tasks/<id>/pregrants` records a single-use pre-grant, the HTTP counterpart of `docket pod <p> pregrant`; `GET /inbox` returns the derived `InboxView`; `POST /tasks/<id>/answer` resolves a parked question through `core.answers.answer_task(channel="http")`; `/traces/<project>` lines may carry an additive `task_id`; Concurrent pod provisioning serializes one project while different projects share only the short atomic allocation transition |
| Adoption Benchmark | 1.2.3 | Implemented | Versioned, machine-readable contract for the adoption benchmark: one fixed scenario plus durable Docket records to canonical per-attempt JSONL and a deterministic aggregate; fake-model results are reproducible evidence, not a quality measurement |
| Input Validation | 1.6.1 | Partial | Docket-owned store and protocol-boundary validation plus the project/pod-id check (§1, `validate_project_id`) are implemented; the path, numeric and session-key predicates (§2, §4, §5) have no implementing function |
| Test Framework | 2.20.0 | Active | Hermetic `DOCKET_HOME`, lane placement contract (product lanes in the default run, budgeted agent lane for prose/release/harness checks, one unit file per module, `cli/__init__.py` as a registry of short functions, comment hygiene), portable development harnesses, golden fixtures, proportional validation, deterministic CLI→HTTP→runtime smoke, opt-in real-model canaries, byte-exact artifact gates, and public release-truth checks |
| Starter Journey | 1.0.1 | Implemented | The smallest copied-outside-checkout path from an exact built artifact to an inspectable governed mutation, run against a deterministic loopback model with no source checkout, `docket-runtime`, or hosted credentials; requirement 6's `HandoffArtifact` field list corrected to include `brief` (Phase 34 added it, the starter's own persisted-shape check caught the drift) |
| Operator Loop | 1.5.0 | Implemented | Bare `docket notify` is a usage error (exit 2); only `flush` flushes; `console` is a silent dialect and `Catalog.delivering()`/`unreached_warning` make its being the only channel on a loud, counted `doctor` issue; the `operator-v1` contract (`core/operator_contract.py`): A2A 1.0.0 task states, MCP-elicitation-shaped questions/answers, CloudEvents 1.0 event envelopes; park/pre-grant, the Lead's intake, the derived inbox, notifications over every v1 channel dialect, answers, interruption forecasting and pre-grants from intake — every requirement area shipped across Phase 34 (D-50, ADR 0016) |
| User Stories | 1.5.0 | Active | Acceptance criteria (not a `.spec.md`) |

## Quick Links

- [Functional Specifications](./functional/)
- [API Contracts](./api/)
- [Data Specifications](./data/)
- [Acceptance Criteria](./acceptance/)
- [Validation Rules](./validation/)

## Contributing to Specifications

1. All new features MUST have specs before implementation
2. Spec changes require review before code changes
3. Use pull requests with "spec:" prefix
4. Include examples and test cases
5. Update version and changelog — and this README's status table

## Spec Validation Tools

```bash
# Validate spec structure (required sections, Version/Status headers) — CI-blocking
./scripts/validate-specs.sh

# Project metrics incl. the spec-file count (drift-guards README numbers)
uv run python scripts/metrics.py
```

## References

- [RFC 2119](https://www.ietf.org/rfc/rfc2119.txt) - Requirement Keywords
- [OpenAPI Specification](https://swagger.io/specification/) - API Documentation
- [JSON Schema](https://json-schema.org/) - Data Validation
