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
> Last synchronized: 2026-09-27 (Wave 57, P32-3/P32-4/P32-5: `task_id` on the trace record and
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
| Agent Lifecycle | 1.14.0 | Complete | `docket init` creates the project pod; `docket add` only extends an existing pod; pod deletion purges runtime/session/trace state but preserves audit; `maintain distill` + exact durable records |
| Agent Loop | 1.26.0 | Implemented and live | `DocketDriver.run_turn` starts the observability export pipeline lazily and flushes it, writing the health file, on every return path; zero enabled exporters is a no-op; Every backend chat-completions exchange (each turn iteration, plus the compaction summarizer's own call) is a durable `llm_call` trace event carrying model, provider, measured latency and token counts, never a dollar figure; A `# Skills` index section (screened descriptions, capped, reported as `skills`) and the `skill` built-in tool of kind `read`; A codebase root `AGENTS.md` composes as the project-instructions section by default when `projectInstructions` is unset (screened, capped, reported); an explicit list replaces it; The production turn loop is gated, role-narrowed, composes one runtime-safe startup projection, durably compacts and trace-separates history, preflights every known-window request, reserves one bounded tool-free terminal response, bounds consecutive typed tool denials, and never recompacts the same logical request-fit segment without new tool growth |
| API Keys | 1.6.0 | Complete | Central keys feed resolved endpoints directly; a stored key alone readies a built-in hosted provider; `keys setup` prompts for every credential the provider catalog declares, in catalog order; credential presence alone never claims provider readiness |
| Audit | 2.10.0 | Implemented | Rotation, head lookup, durable append, and coherent readers share one audit lock; approval terminal decisions emit exactly one matching winner event |
| Config Format | 1.5.0 | Implemented | `pod.yaml`'s manifest key set gains `exporters`; `exporter` joins the `kind:` envelope (`core/exporter.py::ExporterSpec`), with its published JSON Schema under `docs/contracts/config-v1/`; The pod manifest key set gains an optional `description`; Every role, pipeline, policy, pod-manifest, provider and exporter file declares `kind:` and `name:`; `core/config_docs.py::load_document` dispatches on `kind` to the parser that owns it (a file without `kind` loads with a deprecation note); short-form Pydantic models give `docket validate` field-level errors and generate the published JSON Schemas under `docs/contracts/config-v1/` (pinned byte-for-byte, shipped with the package for `export`'s `.schemas/`) |
| Cost Tracking | 1.7.0 | Implemented, recorded dollars unavailable | Auto-pause is real; measured tokens are durable, while `DocketDriver` reports no billed dollar amount. Budget gating uses a separately labelled estimate. Daily history remains empty because sessions do not store per-turn timestamps |
| Model Profiles | 2.17.0 | Complete | A pod-scoped archetype resolves its `modelClass` in its pod's registry (a recipe's role follows the fleet's preset, never the compiled-in literal) and an unknown role falls back to the registry default; A pipeline step's own `model:` (`cheap`/`strong`/literal) wins for that hop only and is never persisted; Providers are `kind: provider` documents in a catalog (fourteen built-in under `templates/providers/`, the operator's own in `docket-providers.json`, nearest-wins) that name their credentials and never hold a value, authenticate by bearer, a named header or nothing, and may send static headers; presets, prices, key prefixes and base URLs all derive from the catalog; registration probes `/models` with the resolved credential and classifies the answer (only a transport failure refuses); `config explain` reports provider, scope, credential source and the exact row; `doctor` reports a malformed global document; a pre-catalog `fleet.json` block migrates once |
| Observability Export | 1.4.0 | Implemented — awaiting external verification (P32-9) | `core/telemetry.py` deterministically projects `core/trace.py` records into a neutral `Span`/`SpanEvent` model, runs the bounded queue/background-sender `Pipeline`, and an `ExportPolicy` decides `metadata`/`full` payload reduction; `core/exporter.py`'s `kind: exporter` document, built-in + global catalog (five ready-made, disabled-by-default destinations under `templates/exporters/`), and `enable_exporter`/`disable_exporter`; `edges/adapters/exporters/otlp_http.py` encodes and sends the one shipped wire dialect; `edges/adapters/docket_runtime.py::run_turn` starts the pipeline lazily and flushes it on every return path; `docket exporters list|show|enable|disable|test|add|remove|export` turns a destination on by authenticating; `pod.yaml`'s `exporters:` key does not exist yet |
| Pipeline Format | 2.10.0 | Implemented | A step may declare `model: cheap|strong|<provider>/<id>` (canonical and short form), refused at `validate`/`plan` when the provider is not in the catalog; `core/pipeline.py` format, `core/dispatch.py` executor, `core/orchestrator.py` planner; short form (`id: role` plus `verify`/`verdict`/`approval`); control flow as bounded data: `on:` routes any gate outcome to `fail`, `stop` or a step (a backward edge needs `max`), `until: verify` + `max`, `when: {changed, var/is, memberPresent}` skips a step, `run:` is a command step with no agent turn; `validate`/`plan` reject a missing bound and an unreachable step |
| Pod Blueprints | 1.20.0 | Implemented | A recipe's `pod.yaml` may name `exporters`; `apply`/`recipes show` report each one's activation state and never activate one; Recipe listing derives `brings`; three recipe scopes (path, `~/.docket/recipes/`, shipped) and `docket recipes list|show`; a recipe's `skills/` is applied, exported and digested; `render()` prints `pipeline none`; The recipe library: twelve shipped recipes of three kinds (teams, policy packs on structured predicates, methodology pipelines `tdd`/`spec-first`/`reflexion`/`dual-review`/`frugal`); `summarize_recipe` derives what a directory brings; `pod.yaml` `description`; `apply` records source and digest on every validated apply; `pod <p> apply <name|dir>` resolves a shipped recipe by name; `docket init` validates and applies a present `<location>/.docket/` (or `--recipe <name|dir>`, `--no-apply`); `apply` records `configSource`/`configDigest`; `export [<dir>]` defaults to `<codebase>/.docket/`; Five built-ins — software/research/content/ops plus `agentic-product`; deliberately data, not scaffolding. `docket init --blueprint`/`--from`; dispatch runs a blueprint's default pipeline; `docket pod <p> apply <dir>` applies a recipe/manifest (`roles/`, `policies/`, `plugins/`, `pipeline.yaml`, `pod.yaml`) to a pod's own scope and `export` writes it back in the short form with a schema header, proven by a round trip that plans every item `skip` |
| Pod Dispatch | 6.23.0 | Complete | Every hop-scoped trace event carries `task_id`; A step `model` is resolved once per hop and handed to the production driver for that hop only; Hop execution/history/handoff behavior is live; a retry waits `min(max(backoff x N, Retry-After), DISPATCH_RETRY_MAX_WAIT_S)` and `hop_retry` records `retry_after_s`; a step's `on:` map routes gate outcomes (`route_taken`), a `when` predicate skips a step (`step_skipped`), a `run` step executes a classified command with no agent turn (`command_step`); pod settings include `mcpServers` and `deniedTools`; the Lead's hop instruction is archetype data; conversation hops mutate one validated locked registry |
| Role Archetypes | 1.20.0 | Implemented | `kind: role` names the kind, not the form (a canonical-only key makes a document canonical; mixed forms refused); `editRights` is retired: accepted and dropped on read, never written; `deniedTools` is the only capability statement; Built-ins, load-bearing `gateContract`, pod-blueprint composition, per-role `tokenBudget`, enforced `deniedTools`, Docket-owned overlays at global and pod scope (`roles add|list|show --pod`, nearest-wins by name), and a short authoring form (`cannot`, `verdict|verify|approval`, `model`, prose in a `.md`) normalised by `normalize_role` |
| Security Gates | 0.27.0 | Implemented (on by default) | Every tool call Docket dispatches passes through `core/tools.py`; policies are short-form YAML or JSON with structured `when` predicates over the call (`tool`, `path`, `matches`, `branch`, `anyOf`) and a `plugin` predicate that runs operator-applied Python from `~/.docket/plugins/` or a pod's `config/plugins/` only, fail-closed, hashed and audited; pending approvals resolve through one conditional locked transition. General egress remains open by decision D-23 |
| Session History | 1.5.0 | Implemented and live | `core/session.py`: durable opaque-key history, lossless round-trip, bounded hierarchical atomic/ranged compaction, isolated summarizer key, recursion guard, and whole-operation fail-closed behavior; request fit can preserve the current task while compacting selected history |
| Session Scoping | 2.0.1 | Complete | Base metadata scope remains `agent:<id>:<project>`; pod dispatch derives isolated step-history keys and keeps a separate task trace without deleting prior sessions (W20-C4) |
| Telegram Integration | 2.2.1 | Implemented | `docket wire` discovers a group from a one-time Telegram command with manual fallback; Docket owns the bot and approval path, unbound chats fail closed, and delegated text passes through input policy |
| Trace Store | 1.1.0 | Implemented and live | An optional `task_id` on the record, written only when truthy; `trace_ingest` notifies subscribers before appending; the durable per-session JSONL trace store every trace-emitting module writes through — the record shape, the full `EVENT_TYPES` vocabulary, `redact`'s secret-shape scrubbing, the `subscribe` seam a live consumer reads from without touching disk, the `trace_ingest` bridge, and retention |
| Workspace Structure | 1.15.0 | Complete | `templates/exporters/` ships the five built-in `kind: exporter` documents; `~/.docket/recipes/<name>/` is operator-owned; skills scopes `~/.docket/skills/` and a pod's `config/skills/`; `DOCKET_HOME` is the only state root; specialist and workdir workspace contracts plus role-aware `TOOLS.md` are live |
| CLI Interface | 1.55.0 | Complete | `pod apply`/`recipes show` print one line per named exporter's activation state, never activating one; `docket exporters list|show|enable|disable|test|add|remove|export`; `docket recipes list [--json]` (NAME, SCOPE, BRINGS, DESCRIPTION) and `show <name|dir>`; `config explain` lists skills; `config explain` reports the project-instructions files and source; `validate <dir>` prints a derived summary line and `apply`/`init --recipe` the same header; `pod <p> apply [<name|dir>]` takes a shipped recipe name; `init`'s member count includes what the apply step added; `roles list` drops the `EDIT` column (`editRights` retired); `docket init --recipe <name|dir>` / `--no-apply`; `pod <p> export [<dir>]` defaults to `<codebase>/.docket`; `config explain` reports `configSource`/`configDigest`/`drift`; `docket models provider add <file.yaml>|<name> <url> [--credential NAME]`, `list`, `show [--json]`, `remove`, `export`; `models preset` prints a readiness line; `config explain` carries a `provider` block and `doctor` a provider-catalog check; `docket auth` is a removed command (notice + exit 1); `docket validate [dir|file]` checks every configuration document; `docket plugins list [--pod <p>]`; `roles` and `policies` accept `--pod <p>`; `pod <p> apply [<dir>]` and `pod <p> export <dir>` (short form + `.schemas/`); `mcp servers add` takes `--kind read|write` and `--tools`; `pod dispatch` and `pipeline run` exit 1 when a task ends `failed` |
| MCP Client | 1.6.0 | Implemented and wired to the live turn path | External tools are namespaced, description-screened, loaded before role narrowing, and dispatched through the same gated chokepoint. A server declares its `kind` (`read`/`write`, default `write`) and an optional `tools` allow-list; a pod selects its servers with `mcpServers`, and a stale selection refuses the dispatch. Remaining limits: stdio only, no listing cache, undeclared servers stay write-only. |
| Runtime Library | 2.2.0 | Implemented (artifact-tested; **not published to any index**) | `docket-runtime` `0.3.0` exclusively owns `docket_runtime/`; its bounded envelope and pinned standard OpenHands SDK/PydanticAI configurations preserve reported usage, sole-chokepoint dispatch, paired identity traces, hash-chained audit, and typed handoff when relevant tools are exclusively Docket-backed; wheel and sdist remain disjoint from `docket` |
| Harness Mode | 1.1.2 | Implemented | `docket harness run`/`status` — one agent, one turn, to completion, in a caller-owned workspace and home; NDJSON events and one versioned result on stdout, with the published schema under `docs/contracts/harness-v1/` and fixtures under `tests/fixtures/harness-contract/v1/`; the `event` field row is additive-only (an `llm_call` event may appear on the stream; the schema is unchanged) |
| MCP Server | 1.5.0 | Implemented | `docket mcp serve` — 10 tools, stdio, optional `docket[mcp]` extra, using the `mcp` 2.x SDK |
| CLI JSON Shapes | 1.15.0 | Complete | `docket exporters list --json`; `config explain --json` carries an `exporters` block; `config explain --json` carries `skills: [{name, scope}]`; `config explain --json` carries `projectInstructions: {files, source}`; Docket-owned doctor/fleet contract and current snapshot channel provenance; `config explain --json` carries the `provider` block and `configSource`/`configDigest`/`drift` |
| docket-meta schema | 3.1.0 | Complete | Pod resource metadata is backed by collision-free allocation and attempt-owned rollback that preserves pre-existing runtime state |
| Docket Store | 1.0.0 | Implemented | Durability and recovery contract for Docket-owned JSON: a malformed primary never makes a valid backup unusable, and recovery never hides the bytes that explain the incident |
| Serve Read API | 2.13.2 | Stable | `/traces/<project>` lines may carry an additive `task_id`; Concurrent pod provisioning serializes one project while different projects share only the short atomic allocation transition |
| Adoption Benchmark | 1.2.3 | Implemented | Versioned, machine-readable contract for the adoption benchmark: one fixed scenario plus durable Docket records to canonical per-attempt JSONL and a deterministic aggregate; fake-model results are reproducible evidence, not a quality measurement |
| Input Validation | 1.6.0 | Partial | Docket-owned store and protocol-boundary validation plus the project/pod-id check (§1, `validate_project_id`) are implemented; the path, numeric and session-key predicates (§2, §4, §5) have no implementing function |
| Test Framework | 2.17.0 | Active | Hermetic `DOCKET_HOME`, lane placement contract (product lanes in the default run, budgeted agent lane for prose/release/harness checks, one unit file per module, comment hygiene), portable development harnesses, golden fixtures, proportional validation, deterministic CLI→HTTP→runtime smoke, opt-in real-model canaries, byte-exact artifact gates, and public release-truth checks |
| Starter Journey | 1.0.0 | Implemented | The smallest copied-outside-checkout path from an exact built artifact to an inspectable governed mutation, run against a deterministic loopback model with no source checkout, `docket-runtime`, or hosted credentials |
| User Stories | 1.4.1 | Active | Acceptance criteria (not a `.spec.md`) |

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
