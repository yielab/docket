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
│   ├── mcp-server.spec.md                # docket start --mcp — MCP tool surface (Phase 18 L-3)
│   ├── operator-api.spec.md              # HTTP operator API v5 — tasks, lifecycle, pods over HTTP (Phase 43, implemented)
│   └── runtime-library.spec.md           # docket-runtime: the embeddable substrate (Phase 21 P21-1)
├── data/                                  # Data specifications
│   ├── cli-json-shapes.spec.md           # --json output shapes per command
│   ├── docket-meta.spec.md               # .docket-meta.json schema
│   ├── docket-store.spec.md              # Atomic JSON writes and corrupt-primary recovery
│   └── serve-read-api.spec.md            # docket start read-only HTTP API (test-pinned)
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
`workflow`/`team` — has no successor command; since 2026-10-03 `eval` and `evals` are
ordinary unknown commands, as every removed name is.)

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
> Last synchronized: 2026-10-17 (Wave 111 close, Phase 43 complete: Operator API 5.4.0 Implemented, CLI
> Interface 2.12.0, Serve Read API 3.9.0, Pod Dispatch 6.52.1, Security Gates 0.57.0, the Harness Mode
> row deleted with the `exec` command, and the patch bumps of P43-12's prose sweep).
> Previously synchronized: 2026-10-17 (Wave 110 close: Operator API 5.2.0, Pod Blueprints 1.30.0, CLI
> Interface 2.9.0, CLI JSON Shapes 1.34.0, Serve Read API 3.7.0, Operator Loop 1.8.0).
> Previously synchronized 2026-10-14 (CLI Interface 2.7.2, the sdist member names; Security Gates 0.55.0,
> the Seatbelt profile).
> Previously synchronized 2026-10-13 (Wave 108 close: CLI Interface 2.7.1, Security Gates 0.54.0,
> Harness Mode 1.10.0, Operator Loop 1.7.0, Serve Read API 3.6.0, CLI JSON Shapes 1.32.0, Pod
> Dispatch 6.45.0).
> Previously synchronized 2026-10-13 (Wave 107 close: Security Gates 0.50.0, CLI JSON Shapes 1.31.0,
> Pipeline Format 2.17.0, Pod Dispatch 6.44.0).
> Previously synchronized 2026-10-13 (Wave 106: Security Gates 0.49.0, CLI Interface 2.6.0, Operator
> Loop 1.6.0, Pod Dispatch 6.43.0, CLI JSON Shapes 1.30.0).
> Previously synchronized 2026-10-13 (Wave 105: Pipeline Format 2.16.0, Pod Dispatch 6.42.0).
> Previously synchronized 2026-10-13 (Wave 104: Agent Loop 1.35.0, Pipeline Format 2.15.0, Pod
> Dispatch 6.41.0).
> Previously synchronized 2026-10-13 (harness contract 1.2: Harness Mode 1.9.0, CLI Interface 2.5.0,
> CLI JSON Shapes 1.29.0).
> Previously synchronized 2026-10-13 (Wave 103: Security Gates 0.48.0, Pod Dispatch 6.40.1).
> Previously synchronized 2026-10-13 (Wave 102: Security Gates 0.47.0, MCP Client 1.11.0, CLI Interface
> 2.4.0, CLI JSON Shapes 1.28.0, Config Format 1.10.0, Audit 2.14.1, Pod Blueprints 1.27.2).
> Previously synchronized 2026-10-13 (Wave 101: Security Gates 0.46.0, Pod Dispatch 6.40.0).
> Before that 2026-10-12 (Wave 100: Security Gates 0.44.0, Pod Blueprints 1.27.1, CLI
> Interface 2.3.0, CLI JSON Shapes 1.27.1). Before that (Phase 40 Wave 99: Security Gates 0.41.0, Audit 2.14.0,
> Telegram Integration 2.7.0, Serve Read API 3.5.0). Before that (Phase 40 Wave 98: Agent Loop 1.34.0, Security Gates 0.39.0, Pod
> Dispatch 6.38.0, Audit 2.13.0, Serve Read API 3.4.2).
> Previously synchronized 2026-10-12 (the Tack exec smoke fixes and the security audit's contained
> defects: CLI Interface 2.2.0, Harness Mode 1.8.0, Agent Loop 1.33.0, MCP Client 1.10.0, Security
> Gates 0.38.0, Telegram Integration 2.6.0, Trace Store 1.7.0).
> Previously synchronized 2026-09-29 (Phase 34 follow-up, closing the P34-17 gap: `docket inbox`,
> `docket setup notify`, the `task show` forecast and `task approve --for` documented in
> CLI Interface (1.58.0); `POST /tasks/<id>/pregrants` documented in Serve Read API (2.15.0);
> the `task_pregrant` MCP tool documented and the stale "twelve tools" claim in `docket setup mcp
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
> `run_turn` and `docket setup export enable/disable/test/add/remove` bumped Agent Loop to 1.26.0,
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
| Agent Lifecycle | 2.1.0 | Complete | `docket init` provisions the pod's own members and no shared agent (org specialists removed); `docket init` creates the project pod; `docket pod add` only extends an existing pod; pod deletion purges runtime/session/trace state but preserves audit; `maintain distill` + exact durable records |
| Agent Loop | 1.41.0 | Implemented and live | Condensation keeps older results whole within `HISTORY_FULL_RESULTS_CHARS` (1.41.0); In a task worktree, `AGENTS.md`, `projectInstructions` files and codebase skills are read from the task's base commit through host-side git on the recorded git dirs, never from the worktree (P42-3); Repository instructions and the skills index compose after the runtime contract behind a fixed untrusted-repository frame; The `skill` tool's body is screened as untrusted input; A batch containing a parked in-turn call (`denial_kind == "approval_parked"`) stops the turn exactly like `approval_unavailable`, naming tool/call/policy/token; `DocketDriver.run_turn` starts the observability export pipeline lazily and flushes it, writing the health file, on every return path; zero enabled exporters is a no-op; Every backend chat-completions exchange (each turn iteration, plus the compaction summarizer's own call) is a durable `llm_call` trace event carrying model, provider, measured latency and token counts, never a dollar figure; A `# Skills` index section (screened descriptions, capped, reported as `skills`) and the `skill` built-in tool of kind `read`; A codebase root `AGENTS.md` composes as the project-instructions section by default when `projectInstructions` is unset (screened, capped, reported); an explicit list replaces it; The production turn loop is gated, role-narrowed, composes one runtime-safe startup projection, durably compacts and trace-separates history, preflights every known-window request, reserves one bounded tool-free terminal response, bounds consecutive typed tool denials, and never recompacts the same logical request-fit segment without new tool growth |
| API Keys | 1.8.0 | Complete | Central keys feed resolved endpoints directly; a stored key alone readies a built-in hosted provider; `keys setup` prompts for every credential the provider catalog declares, in catalog order; credential presence alone never claims provider readiness |
| Audit | 2.14.1 | Implemented | An approval's actor and reason are capped at 512 characters; An `audit.head` sidecar makes a truncated tail a chain break; Rotation, head lookup, durable append, and coherent readers share one audit lock; approval terminal decisions emit exactly one matching winner event |
| Config Format | 1.11.0 | Implemented | `pipelines/*.yaml` (or `.yml`) are pipelines by location, validated by `pod validate`; A `kind: mcp-server` document has no `isolate` field (an unknown key); `kind: channel` joins the envelope (`core/channel.py::ChannelSpec`), canonical-only like `exporter`, with its published JSON Schema under `docs/contracts/config-v1/`; `pod.yaml`'s manifest key set gains `exporters`; `exporter` joins the `kind:` envelope (`core/exporter.py::ExporterSpec`), with its published JSON Schema under `docs/contracts/config-v1/`; The pod manifest key set gains an optional `description`; Every role, pipeline, policy, pod-manifest, provider, exporter and channel file declares `kind:` and `name:`; `core/config_docs.py::load_document` dispatches on `kind` to the parser that owns it (a file without `kind` loads with a deprecation note); short-form Pydantic models give `docket pod validate` field-level errors and generate the published JSON Schemas under `docs/contracts/config-v1/` (pinned byte-for-byte, shipped with the package for `export`'s `.schemas/`) |
| Cost Tracking | 1.10.1 | Implemented, recorded dollars unavailable | A budgeted pod's unpriced model is named (`budget_warning`, `budgetUnpriced`), not gated at $0; Auto-pause is real; measured tokens are durable, while `DocketDriver` reports no billed dollar amount. Budget gating uses a separately labelled estimate. Daily history remains empty because sessions do not store per-turn timestamps |
| Model Profiles | 3.5.0 | Complete | A preset names each pod and role it moved; A custom provider added without `--model` records the first id the registration probe advertises (one probe), else `local-model` with a notice; Roles are archetype names (`lead`, `implementer`, ...); `policyRole` and the `manager`/`programmer`/`knowledge`/`security`/`repo` rows are gone; an unknown `docket-models.json` key is ignored and reported by `doctor`; A pod-scoped archetype resolves its `modelClass` in its pod's registry (a recipe's role follows the fleet's preset, never the compiled-in literal) and an unknown role falls back to the registry default; A pipeline step's own `model:` (`cheap`/`strong`/literal) wins for that hop only and is never persisted; Providers are `kind: provider` documents in a catalog (fourteen built-in under `templates/providers/`, the operator's own in `docket-providers.json`, nearest-wins) that name their credentials and never hold a value, authenticate by bearer, a named header or nothing, and may send static headers; presets, prices, key prefixes and base URLs all derive from the catalog; registration probes `/models` with the resolved credential and classifies the answer (only a transport failure refuses); `config explain` reports provider, scope, credential source and the exact row; `doctor` reports a malformed global document; a pre-catalog `fleet.json` block migrates once |
| Observability Export | 1.12.3 | Implemented and live | `core/telemetry.py` deterministically projects `core/trace.py` records into a neutral `Span`/`SpanEvent` model, runs the bounded queue/background-sender `Pipeline`, and an `ExportPolicy` admits events and grants content classes through an allowlist (`core/privacy.py` levels `minimal`/`actions`/`conversation`/`full`, ADR 0015); `core/exporter.py`'s `kind: exporter` document, built-in + global catalog (five ready-made, disabled-by-default destinations under `templates/exporters/`), and `enable_exporter`/`disable_exporter`; `edges/adapters/exporters/otlp_http.py` encodes and sends the one shipped wire dialect; `edges/adapters/docket_runtime.py::run_turn` starts the pipeline lazily and flushes it on every return path; `docket setup export list|show|enable|disable|test|add|remove|export` turns a destination on by authenticating; `pod.yaml`'s `exporters:` key names a pod's destinations, validated, never itself activating; verified live against a real dispatch, a real OpenTelemetry Collector and a real, dashboard-confirmed Langfuse round-trip at every privacy level; one pod session is one trace, every hop's generations keeping their own span ids under one root that carries the session's task and last answer when `prompts`/`completions` are granted |
| Pipeline Format | 2.18.0 | Implemented | A short-form step with two gate keys is a load error naming both; A mechanical- or external-gated step that routes to the `input` step right after it must route `pass`; A step may carry an `external` gate (command + `exitMap`) whose `pass`/`fail`/`needs_human`/`error` labels route through `on:` (P42-2); A backward `on:` route out of a gate that did not pass carries the gate's output into the retry (P42-1); A step may declare `input: {from: <step id>, message?}` (ADR 0016 §4), running no agent turn: parks the task `waiting_input` and routes on `answered`/`declined`; A step may declare `model: cheap|strong|<provider>/<id>` (canonical and short form), refused at `validate`/`plan` when the provider is not in the catalog; `core/pipeline.py` format, `core/dispatch.py` executor, `core/orchestrator.py` planner; short form (`id: role` plus `verify`/`verdict`/`approval`); control flow as bounded data: `on:` routes any gate outcome to `fail`, `stop` or a step (a backward edge needs `max`), `until: verify` + `max`, `when: {changed, var/is, memberPresent}` skips a step, `run:` is a command step with no agent turn; `validate`/`plan` reject a missing bound and an unreachable step |
| Pod Blueprints | 1.33.0 | Implemented | A setting skipped as the default says `already the default`; `pod update`/`export` carry `pipelines/<name>.yaml` (reviewed, validated, refused when dispatch could not run it); A step gate's command (`verify: <cmd>`, `gate: {external: <cmd>}`) needs the review code like a `run:` step; `.docket/teams/<pod>/` keeps one team per pod (`repo_config_dir`; `init` without a matching `--name` exits 2 naming the teams, `export` writes `teams/<pod>/`); the review decision is one core function and `POST /pods/<p>/apply` applies the same rule with the code instead of the prompt (Wave 110); A repository's run-on-this-machine items (`run:` steps, MCP commands, plugins, `allowCommands`, `network open`, loosened roles) need the operator's OK, remembered in `reviewed-repos.json`, `--accept <code>` off a terminal; `docket run` picks repository changes up; `pod apply` is `pod update`; `code-intel`'s `ast-grep` server is declared `isolate: false` (measured: `uvx` cannot write its cache in the jail); A recipe's `pod.yaml` may name `exporters`; `apply`/`recipes show` report each one's activation state and never activate one; Recipe listing derives `brings`; three recipe scopes (path, `~/.docket/recipes/`, shipped) and `docket pod recipes|show`; a recipe's `skills/` is applied, exported and digested; `render()` prints `pipeline none`; The recipe library: twelve shipped recipes of three kinds (teams, policy packs on structured predicates, methodology pipelines `tdd`/`spec-first`/`reflexion`/`dual-review`/`frugal`); `summarize_recipe` derives what a directory brings; `pod.yaml` `description`; `apply` records source and digest on every validated apply; `pod <p> apply <name|dir>` resolves a shipped recipe by name; `docket init` validates and applies a present `<location>/.docket/` (or `--recipe <name|dir>`, `--no-apply`); `apply` records `configSource`/`configDigest`; `export [<dir>]` defaults to `<codebase>/.docket/`; Five built-ins — software/research/content/ops plus `agentic-product`; deliberately data, not scaffolding. `docket init --blueprint`/`--from`; dispatch runs a blueprint's default pipeline; `docket pod apply <dir>` applies a recipe/manifest (`roles/`, `policies/`, `plugins/`, `pipeline.yaml`, `pod.yaml`) to a pod's own scope and `export` writes it back in the short form with a schema header, proven by a round trip that plans every item `skip` |
| Pod Dispatch | 6.56.0 | Complete | Task usage carries `cached`/`cacheWrite` at the top level (6.56.0); `budget_warning` `unpriced_model` before a hop the cap cannot price; `dispatch_pod(stop=)` checked between tasks, the serve sweep resumes stale claims (6.52.0); `cancel_task` and `task_diff` in core (6.51.0); the in-place ephemeral pod is gone with the harness (6.52.1); `task cancel` on a parked task (Wave 108); A question minted after a failed gate carries the gate's report, and the retry behind its answer carries the answer; Evidence 1.1.0 adds `gate` per hop and `directives` per task from the hop's persisted `repoFiles` (P42-5); The external gate runs in the pod envelope, maps the process's exit status, reads screened reasons from `DOCKET_GATE_REASONS_FILE` and carries them into the retry, across an `input` answer too; unrouted labels fail as `gate_failed`/`gate_needs_human`/`gate_error` (P42-2); A backward route out of a failed gate gives the target's next hop a `--- GATE FAILED: <step id> ---` section with the redacted verify tail, rebuilt on resume (P42-1); With isolation on, `verifyCmd` and `run:` steps run inside the jail and fail closed with no backend; a pod cache dir (0700) is a jailed command's home and caches; Every enqueue persists its `channel` and audits `task.enqueue`; An `ok` Implementer hop's tree is pinned in a commit (task branch, or a branchless snapshot in place) before its evidence is read; `PodSettings.coerce` reports a rejected value as `invalid value`; only the read of a bad stored value says `invalid stored value`; A parked dispatch records `waiting_input`/`waiting_approval`, never `succeeded`; a `failed` task is retryable (`retry_task`, audited); `--resume` reclaims a stale claim (dead `claimPid` or lease past `turnTimeoutS + verifyTimeoutS`); one task-reference resolver (`core/task_ref.py`); One sweep worker per pod (`DISPATCH_SWEEP_WORKERS`); a refused isolation/network posture settles `dispatch_refused` without a retry; the pod `network` setting; Parked approvals (`approvalMode: "park"`) re-enter through the exact hop with a single-use pre-grant, never `gateOverridePipelineIndex`; operator `input` steps park `waiting_input` and `core.answers.answer_task` resumes on the step's own route; the Lead's typed `TaskBrief`, a deterministic `secret:`/`path:`/`verify` resource check, and the Implementer's `## Brief` view; `docket task approve <id> --for "<cmd>"` records a task-scoped exact-command pre-grant through the same digest matcher; Every hop-scoped trace event carries `task_id`; A step `model` is resolved once per hop and handed to the production driver for that hop only; Hop execution/history/handoff behavior is live; a retry waits `min(max(backoff x N, Retry-After), DISPATCH_RETRY_MAX_WAIT_S)` and `hop_retry` records `retry_after_s`; a step's `on:` map routes gate outcomes (`route_taken`), a `when` predicate skips a step (`step_skipped`), a `run` step executes a classified command with no agent turn (`command_step`); pod settings include `mcpServers` and `deniedTools`; the Lead's hop instruction is archetype data; conversation hops mutate one validated locked registry |
| Role Archetypes | 1.25.0 | Implemented | `policyRole` removed from the role document (refused as an unknown key); an archetype's model row is its own name; `kind: role` names the kind, not the form (a canonical-only key makes a document canonical; mixed forms refused); `editRights` is retired: accepted and dropped on read, never written; `deniedTools` is the only capability statement; Built-ins, load-bearing `gateContract`, pod-blueprint composition, per-role `tokenBudget`, enforced `deniedTools`, Docket-owned overlays at global and pod scope (`roles add|list|show --pod`, nearest-wins by name), and a short authoring form (`cannot`, `verdict|verify|approval`, `model`, prose in a `.md`) normalised by `normalize_role` |
| Security Gates | 0.58.0 | Implemented (gate always on; isolation opt-in) | the harness answer channel is gone; approval tokens and packs own that section (0.57.0); the Seatbelt profile may list `/` and read `/opt` (every seatbelt command had died of SIGABRT); every jailed launch gets a private temp dir instead of the shared one (Wave 108); the classifier sees through wrappers; every jail narrows ref writes to the task's branch (Wave 108); Every surface that prints the network mode says `not enforced` while isolation is off (`core.network_posture`) (P42-7); A recorded `lights-out` profile (global via `setup profile`, or per pod, stricter only) refuses a dispatch before its first hop unless isolation is on with a backend, network `none` is recorded, every Implementer step has an external gate and no injected variable is named in the secret store; audited `profile.refused` (P42-4); The escape matrix (`tests/integration/test_escape_matrix.py`) gates release on Linux and macOS; Landlock keeps git hooks and config read-only and refuses a root holding a `.git` directory; host-side git in a task worktree names its recorded git dirs; bwrap is deleted: `auto` is Landlock on Linux and Seatbelt on macOS, Docker only when chosen (`setup sandbox backend docker`); a Seatbelt jail on macOS; one jail builder (`system.jail_launch`) for `bash`, verify and `run:`; a Landlock + seccomp jail (`python -m docket.jail`) is the first Linux backend, no package needed; inside a working jail the allowlist stands down except for high-risk classes, opaque commands and redirects outside the roots; the jail's network defaults to `none`; a sandboxed call with no usable backend runs nothing; a repository can never allowlist a shell; `fetch` has a wall-clock deadline and a clamped timeout; the docket process is non-dumpable on Linux, so an unjailed child cannot read its credentials from `/proc`; A file tool's path escape and a `fetch` allowlist refusal are audited as `tool.refused`; An unquoted newline separates commands for the classifier; an output redirect is allowed when every target stays inside the turn's roots; approval tokens are `apr-<uuid4>` or not found; the bwrap jail hides `DOCKET_HOME`; `init` installs the baseline policies; Bare `gates isolate` is a read (posture + usage, exit 2, nothing written); Isolation opt-in again (ADR 0021: `gates isolate on`, needs bwrap or docker; bwrap first, fails closed naming both fixes, git dirs writable with hooks/config read-only); `gates network none` and a pod `network` setting cut the jail's network; `fetch` results pass `pre_input`; file tools skip walked paths outside the roots; task processes never see docket's credentials; `ToolContext.approval_mode` gains `"park"`: an in-turn `ask` ends the turn immediately with a durable approval record instead of blocking; `core.approval.create_pregrant`/`consume_pregrant` give a human's grant a single-use, digest-matched pass on a later re-entered turn, fail-closed on expiry; Every tool call Docket dispatches passes through `core/tools.py`; policies are short-form YAML or JSON with structured `when` predicates over the call (`tool`, `path`, `matches`, `branch`, `anyOf`) and a `plugin` predicate that runs operator-applied Python from `~/.docket/plugins/` or a pod's `config/plugins/` only, fail-closed, hashed and audited; pending approvals resolve through one conditional locked transition. General egress remains open by decision D-23 |
| Session History | 1.7.0 | Implemented and live | `condense_history` keeps older results whole while they fit 6,000 characters (1.7.0); `core/session.py`: durable opaque-key history, lossless round-trip, bounded hierarchical atomic/ranged compaction, isolated summarizer key, recursion guard, and whole-operation fail-closed behavior; request fit can preserve the current task while compacting selected history |
| Session Scoping | 3.0.0 | Complete | Base metadata scope remains `agent:<id>:<project>`; pod dispatch derives isolated step-history keys and keeps a separate task trace without deleting prior sessions (W20-C4) |
| Telegram Integration | 2.7.0 | Implemented | Refusals of unbound chats are one audit entry per chat per poll batch; A raising update is audited and skipped, and the offset still advances; A fifth verb, `/answer <task-id> <text>`, resolves through `core.answers.answer_task`; the outbound `telegram` `kind: channel` dialect pushes to every chat id in the channel's own `actors` list, never a `fleet.json` binding, never from `core/telegram.py` itself; outbound messages now exist through exactly two AST-pinned call sites; `docket setup notify bind` discovers a group from a one-time Telegram command with manual fallback; Docket owns the bot and approval path, unbound chats fail closed, and delegated text passes through input policy |
| Trace Store | 1.10.0 | Implemented and live | `redact` scrubs env-sourced credential values and bare vendor tokens; The key-shaped redaction pattern matches only at a word start; An optional `task_id` on the record, written only when truthy; `trace_ingest` notifies subscribers before appending; the durable per-session JSONL trace store every trace-emitting module writes through — the record shape, the full `EVENT_TYPES` vocabulary, `redact`'s secret-shape scrubbing, the `subscribe` seam a live consumer reads from without touching disk, the `trace_ingest` bridge, and retention |
| Workspace Structure | 1.22.0 | Complete | No shared agents: `workspaces/` holds pod members only; `templates/exporters/` ships the five built-in `kind: exporter` documents; `~/.docket/recipes/<name>/` is operator-owned; skills scopes `~/.docket/skills/` and a pod's `config/skills/`; `DOCKET_HOME` is the only state root; specialist and workdir workspace contracts plus role-aware `TOOLS.md` are live |
| CLI Interface | 2.15.0 | Complete | `setup provider add` names the pods a preset moved; Ten commands: `exec` and `setup harness` are deleted with the harness, declared version `0.2.0-beta.6` (P43-12); `start --bind <addr>` (P43-11); `task diff` prints the task branch's patch against its base and takes `--json` (P43-10); `init` in a repository with several teams and no `--name` exits 2 naming them (Wave 110); no release sdist member name contains `:`; `task cancel` cancels a parked task, `task diff` uses the recorded git dirs, `task prune --traces --pod` is scoped (Wave 108); `setup profile [lights-out|attended]` and the pod `profile` key (P42-4); `init`, `status` and `setup sandbox` show the sandbox (per-platform probe report); `setup sandbox backend auto|docker`; `pod update` replaces `pod apply`; `run` picks repository changes up; `status` shows allowed repository commands; `docket --version` names the source revision from a git checkout; The progress view names the task on its session lines and each hop on an indented line; `status` prints `N waiting input` and the sandbox posture on its `Isolation:` line; The ten commands (`init status inbox task run pod log setup start stop`), one section per command with its verbs (`init` with its two arguments and eight options declared on the command); pod targeting (`--pod`, `DOCKET_POD`, then the directory you stand in); grouped help with one tagline, `-h` everywhere, the bare three-part guide and tree-built completions; the console voice and the interaction contract (plain ASCII when piped or `NO_COLOR`, exit 2 for usage, no picker, no positional pod id); retired names are ordinary unknown commands and `CHANGELOG.md` is their only record |
| MCP Client | 1.11.0 | Implemented and wired to the live turn path | Description and result screens see the calling pod's `on: input` policies; stdio servers always start in the turn's jail (backend, roots, network) when isolation is on; results screened by the shared `screen_tool_result`; External tools are namespaced, description-screened, loaded before role narrowing, and dispatched through the same gated chokepoint. A server declares its `kind` (`read`/`write`, default `write`) and an optional `tools` allow-list; a pod selects its servers with `mcpServers`, and a stale selection refuses the dispatch. Remaining limits: stdio only, no listing cache, undeclared servers stay write-only. |
| Runtime Library | 2.2.0 | Implemented (artifact-tested; **not published to any index**) | `docket-runtime` `0.3.0` exclusively owns `docket_runtime/`; its bounded envelope and pinned standard OpenHands SDK/PydanticAI configurations preserve reported usage, sole-chokepoint dispatch, paired identity traces, hash-chained audit, and typed handoff when relevant tools are exclusively Docket-backed; wheel and sdist remain disjoint from `docket` |
| MCP Server | 1.9.2 | Implemented | `docket start --mcp` — 13 tools (`task_answer`, `task_pregrant`, `inbox` join the original ten), stdio, optional `docket[mcp]` extra, using the `mcp` 2.x SDK |
| CLI JSON Shapes | 1.36.0 | Complete | `budgetUnpriced` in `pod show --json` and `status --json`; `pod show --json` is built by `core/pod_report.py`, the same shape `GET /pods/<p>` returns (Wave 110); `setup --fix --json` reports every text check (Wave 108); `setup --json` and `setup sandbox --json` carry `networkEnforced` (P42-7); `task show --json` evidence is 1.1.0; `status --json`/`doctor --json` carry a `profile` block under `lights-out` (P42-4, P42-5); `setup sandbox --json` carries the probe report; `doctor --json` `securityGates.sandboxUsable`, no `unjailedMcpServers`; `status --json` optional `commands`; `status --json` `tasks.waitingInput`; a `waiting_input` task makes the pod `waiting`; `isolation` is the sandbox posture phrase; Run `state` admits `waiting_input | waiting_approval`; `models` keys are archetype names; `doctor --json` `checks.notifications {ok, delivering}`; `doctor --json` `securityGates.isolation` reads `off (default)` with no recorded choice and carries the sandbox backend and the network mode; `config explain --json` carries `network {mode, scope}`; `docket setup export list --json`; `config explain --json` carries an `exporters` block; `config explain --json` carries `skills: [{name, scope}]`; `config explain --json` carries `projectInstructions: {files, source}`; Docket-owned doctor/fleet contract and current snapshot channel provenance; `config explain --json` carries the `provider` block and `configSource`/`configDigest`/`drift` |
| docket-meta schema | 3.6.2 | Complete | `scope` is always `project`; `org` and `kind: specialist` are removed; Pod resource metadata is backed by collision-free allocation and attempt-owned rollback that preserves pre-existing runtime state |
| Docket Store | 1.0.0 | Implemented | Durability and recovery contract for Docket-owned JSON: a malformed primary never makes a valid backup unusable, and recovery never hides the bytes that explain the incident |
| Operator API | 5.7.0 | Implemented (Phase 43, ADR 0027) | Task `usage` carries `cached`/`cacheWrite` (5.7.0); `POST /pods` reads `name`/`location` as published; `POST /tasks/<pod>/<id>/cancel|retry`, `GET .../diff`, the `/health` dispatch block; `SERVE_API_VERSION` 5, the one door for a program (Wave 111); Pods over HTTP: `GET /pods`, `GET /pods/<p>`, `POST /pods` `ensure`, `POST /pods/<p>/apply` with the review code, `GET /pods/<p>/corrections?since=` (Wave 110); Addressable tasks (`externalRef`, `idempotencyKey`, `baseRef`, `pipeline`, `gate`, `maxTokens`, narrow-only `restrictions`), `hop_started`/`hop_finished`, task cancel/retry/diff, pods read/`ensure`/`apply`/corrections, `/health` dispatch block; API version 5 (ADR 0027) |
| Serve Read API | 3.10.1 | Stable | `POST /pods` takes `name`/`location` (`project`/`path` removed); API version 5 (`operator-api.spec.md` owns the write and lifecycle routes); `/health` carries `apiVersion` and `dispatch {on, inflight, stopping, workers}`; `POST /tasks/<pod>` starts the pod's sweep when dispatch is on; `--bind` (Wave 111); `GET /pods`, `GET /pods/<p>` and `POST /pods` `ensure`/`created` (Wave 110); `POST /dispatch` answers 404/400 on a broken bound pipeline (Wave 108); The unauthenticated `/status.json` carries each binding's channel, never its peer id; A task carries its `channel`; API version 4: `/status.json` agents are pod members only; run `state` admits the two parked states; API version 3: `gateway` removed from `/status.json`, `/health` is `{"status":"ok"}`, `docket_gateway_up` gone; `POST /tasks/<id>/pregrants` records a single-use pre-grant, the HTTP counterpart of `docket task approve <id> --for`; `GET /inbox` returns the derived `InboxView`; `POST /tasks/<id>/answer` resolves a parked question through `core.answers.answer_task(channel="http")`; `/traces/<project>` lines may carry an additive `task_id`; Concurrent pod provisioning serializes one project while different projects share only the short atomic allocation transition |
| Adoption Benchmark | 1.2.3 | Implemented | Versioned, machine-readable contract for the adoption benchmark: one fixed scenario plus durable Docket records to canonical per-attempt JSONL and a deterministic aggregate; fake-model results are reproducible evidence, not a quality measurement |
| Input Validation | 1.6.2 | Partial | Docket-owned store and protocol-boundary validation plus the project/pod-id check (§1, `validate_project_id`) are implemented; the path, numeric and session-key predicates (§2, §4, §5) have no implementing function |
| Test Framework | 2.20.1 | Active | Hermetic `DOCKET_HOME`, lane placement contract (product lanes in the default run, budgeted agent lane for prose/release/harness checks, one unit file per module, `cli/__init__.py` as a registry of short functions, comment hygiene), portable development harnesses, golden fixtures, proportional validation, deterministic CLI→HTTP→runtime smoke, opt-in real-model canaries, byte-exact artifact gates, and public release-truth checks |
| Starter Journey | 1.0.2 | Implemented | The smallest copied-outside-checkout path from an exact built artifact to an inspectable governed mutation, run against a deterministic loopback model with no source checkout, `docket-runtime`, or hosted credentials; requirement 6's `HandoffArtifact` field list corrected to include `brief` (Phase 34 added it, the starter's own persisted-shape check caught the drift) |
| Operator Loop | 1.9.0 | Implemented | the corrections ledger is readable by cursor over `GET /pods/<p>/corrections?since=` (Wave 110); the inbox indents multi-line questions (Wave 108); `status` and `doctor` show the `lights-out` profile and its unmet requirements, only when it is recorded (P42-4); The `task add` forecast pluralises its kinds; a policy interruption is described by its predicate kinds, never the pattern text; Only `setup notify flush` delivers; `console` is a silent dialect and `Catalog.delivering()`/`unreached_warning` make its being the only channel on a loud, counted `doctor` issue; the `operator-v1` contract (`core/operator_contract.py`): A2A 1.0.0 task states, MCP-elicitation-shaped questions/answers, CloudEvents 1.0 event envelopes; park/pre-grant, the Lead's intake, the derived inbox, notifications over every v1 channel dialect, answers, interruption forecasting and pre-grants from intake — every requirement area shipped across Phase 34 (D-50, ADR 0016) |
| User Stories | 1.6.0 | Active | Acceptance criteria (not a `.spec.md`) |

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
