# docket specifications

Every document here is a **current-state contract**: it says what docket does today, and its
`**Status**` line matches the code. A requirement that is not yet true says so and names the card
that will make it true. When a spec, a prose claim and the live code disagree, the change contract
in [`AGENTS.md`](../AGENTS.md) applies: record the discrepancy and make spec, test, code and claim
agree in the same work.

A spec carries no history. What changed and when is `git log -- specs/<file>` and
[`CHANGELOG.md`](../CHANGELOG.md); decisions are in [`docs/adr/`](../docs/adr/) and `ROADMAP.md`.
`scripts/validate-specs.sh` refuses a `## Changelog` section.

## Layout

```text
specs/
├── README.md                              # This file — overview and index
├── test-framework.md                      # Test conventions and coverage methodology
├── functional/                            # Functional specifications
│   ├── agent-lifecycle.spec.md           # Agent CRUD and maintenance operations
│   ├── agent-loop.spec.md                # The turn loop and the RuntimeDriver port
│   ├── api-keys.spec.md                  # Provider credentials
│   ├── audit.spec.md                     # Audit log events, hash-chained + verify
│   ├── cost-tracking.spec.md             # Usage/cost reporting, budget caps and auto-pause
│   ├── mcp-client.spec.md                # MCP client: pluggable tool servers
│   ├── model-profiles.spec.md            # Role→model policy and pinning
│   ├── observability-export.spec.md      # Neutral span model and export policy over the trace store
│   ├── operator-loop.spec.md             # The operator contract: A2A states, MCP-elicitation questions, CloudEvents
│   ├── pipeline-format.spec.md           # The pipeline YAML format
│   ├── config-format.spec.md             # The `kind:` envelope, one loader, short forms, published schemas
│   ├── pod-blueprints.spec.md            # Built-in pod blueprints (software/research/content/ops/agentic-product)
│   ├── pod-dispatch.spec.md              # Pod dispatch pipeline state machine and gates
│   ├── role-archetypes.spec.md           # Declarative role archetypes (registry, overlay, CLI)
│   ├── security-gates.spec.md            # Tool-call gate (always on), approvals, isolation (on where the machine can jail)
│   ├── session-history.spec.md           # Durable per-session turn history and compaction
│   ├── session-scoping.spec.md           # Multi-project session isolation
│   ├── telegram-integration.spec.md      # Telegram bindings and docket's own bot
│   ├── trace-store.spec.md               # Durable per-session JSONL trace store, EVENT_TYPES, subscribe seam
│   └── workspace-structure.spec.md       # DOCKET_HOME and per-member workspace layout
├── api/                                   # API contracts
│   ├── a2a-binding.spec.md               # POST /a2a: the A2A JSON-RPC facade over tasks and escalations
│   ├── cli-interface.spec.md             # CLI command contracts and return codes
│   ├── mcp-server.spec.md                # docket start --mcp: the MCP tool surface
│   ├── operator-api.spec.md              # HTTP operator API 6: tasks, lifecycle, pods, escalations
│   └── runtime-library.spec.md           # docket-runtime: the embeddable substrate
├── data/                                  # Data specifications
│   ├── cli-json-shapes.spec.md           # --json output shapes per command
│   ├── docket-meta.spec.md               # .docket-meta.json schema
│   ├── docket-store.spec.md              # Atomic JSON writes and corrupt-primary recovery
│   └── serve-read-api.spec.md            # docket start read HTTP API
├── acceptance/                            # Acceptance criteria
│   ├── starter-journey.spec.md           # Extractable artifact-installed starter journey
│   └── user-stories.md                   # User stories
└── validation/                            # Validation rules
    ├── adoption-benchmark.spec.md        # Deterministic benchmark artifact contract
    └── input-validation.spec.md          # Input validation rules
```

A retired spec is deleted, not archived; git history keeps its text.

## Writing a spec

Each spec has a `**Version**`, a `**Status**` and a `**Last Updated**` header, then:

- **Purpose**: what the spec defines.
- **Scope**: what it covers, and a "does NOT cover" list naming the owning spec, so no two specs
  own the same contract.
- **Requirements**: numbered MUST/SHOULD/MAY statements (RFC 2119) about current behaviour.
- **Interfaces**, **Examples**, **Validation**: the contract, concrete usage, how to verify it.

`scripts/validate-specs.sh` checks the required sections per directory (CI-blocking).

Write the requirement, not its history: no card ids, wave numbers or "was false until" in a
requirement or a Status line. Cite code by behaviour where possible; a cited path or symbol must
exist.

### Versions

Semantic versioning per spec: MAJOR when a requirement is removed or changes meaning, MINOR when
one is added, PATCH for a clarification. Bump the version and `**Last Updated**` in the same
commit as the change, and update the table below.

## Changing a spec

The order is the change contract in [`AGENTS.md`](../AGENTS.md): update the owning spec, add a
failing behavioural test, implement the smallest change. Docket has no users (ADR 0022): a removed
behaviour is deleted from the spec in the same change, with no migration plan or notice.

## Index

This table mirrors each spec's own `**Version**`/`**Status**` header, which wins on disagreement.
`scripts/maint/check_spec_index.py` and the release-lane test
`test_spec_index_matches_current_headers` reconcile it.

| Specification | Version | Status |
| ------------- | ------- | ------ |
| Agent Lifecycle | 4.0.0 | Complete |
| Agent Loop | 3.10.0 | Implemented and live |
| API Keys | 2.0.3 | Complete |
| Audit | 3.3.1 | Implemented |
| Config Format | 2.8.0 | Implemented |
| Cost Tracking | 1.13.0 | Implemented, recorded dollars unavailable |
| Model Profiles | 6.4.1 | Complete |
| Observability Export | 3.1.0 | Implemented and live |
| Pipeline Format | 4.4.0 | Implemented |
| Pod Blueprints | 2.6.0 | Implemented |
| Pod Dispatch | 11.7.0 | Implemented |
| Role Archetypes | 4.8.1 | Implemented |
| Security Gates | 3.3.0 | Implemented (gate always on; init turns isolation on where a backend is detected) |
| Session History | 1.10.0 | Implemented and live |
| Session Scoping | 4.0.1 | Complete |
| Telegram Integration | 5.0.0 | Implemented |
| Trace Store | 4.3.0 | Implemented and live |
| Workspace Structure | 3.1.0 | Complete |
| CLI Interface | 5.4.0 | Complete |
| MCP Client | 3.0.0 | Implemented and wired to the live turn path |
| Runtime Library | 2.3.0 | Implemented (artifact-tested; **not published to any index**) |
| MCP Server | 2.0.0 | Implemented |
| CLI JSON Shapes | 4.6.1 | Complete |
| docket-meta schema | 5.5.1 | Complete |
| Docket Store | 3.1.0 | Implemented |
| Operator API | 7.5.0 | Implemented (Phase 43, ADR 0027) |
| A2a Binding | 1.2.0 | Implemented |
| Serve Read API | 5.2.0 | Stable |
| Adoption Benchmark | 2.2.0 | Implemented |
| Input Validation | 2.1.1 | Implemented |
| Test Framework | 4.4.0 | Active |
| Starter Journey | 2.1.0 | Implemented |
| Operator Loop | 3.3.0 | Implemented |
| User Stories | 2.1.0 | Active |

## Tools

```bash
bash scripts/validate-specs.sh                   # required sections, headers, no changelog (CI)
uv run python scripts/maint/check_spec_index.py  # this index against the spec headers
```
