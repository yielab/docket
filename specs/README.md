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
│   ├── pipeline-format.spec.md           # docket-native pipeline YAML format + executor (W-1/W-2)
│   ├── pod-dispatch.spec.md              # Pod dispatch pipeline state machine and gates
│   ├── role-archetypes.spec.md           # Declarative role archetypes (registry, overlay, CLI)
│   ├── security-gates.spec.md            # Tool-approval gates (on by default; docket-enforced)
│   ├── session-history.spec.md           # Durable per-session turn history + compaction (Phase 19 P19-4)
│   ├── session-scoping.spec.md           # Multi-project session isolation
│   ├── telegram-integration.spec.md      # Telegram bindings + docket-owned bot (Phase 19 P19-8)
│   └── workspace-structure.spec.md       # Per-agent workspace layout
├── api/                                   # API contracts
│   ├── cli-interface.spec.md             # CLI command contracts and return codes
│   ├── mcp-server.spec.md                # docket mcp serve — MCP tool surface (Phase 18 L-3)
│   └── runtime-library.spec.md           # docket-runtime: the embeddable substrate (Phase 21 P21-1)
├── data/                                  # Data specifications
│   ├── cli-json-shapes.spec.md           # --json output shapes per command
│   ├── docket-meta.spec.md               # .docket-meta.json schema
│   └── serve-read-api.spec.md            # docket serve read-only HTTP API (test-pinned)
├── acceptance/                            # Acceptance criteria
│   └── user-stories.md                   # User stories with Gherkin scenarios
└── validation/                            # Validation rules
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
> Last synchronized: 2026-08-31 (W26-C5/C7/C9 reconciled runtime packaging, approval atomicity,
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
> (D-16) but the row survived the wave-4 index reconciliation. The row count is now exactly the 23
> `.spec.md` files on disk.
> Verified row-by-row against every spec's own `**Version**` header, not carried forward — an
> index table cannot be auto-merged correctly when several branches bump versions in parallel.

| Specification | Version | Status | Notes |
| ------------- | ------- | ------ | ----- |
| Agent Lifecycle | 1.12.0 | Complete | `docket init` creates the project pod; `docket add` only extends an existing pod; pod deletion purges runtime/session/trace state but preserves audit; `maintain distill` + exact durable records |
| Agent Loop | 1.16.0 | Implemented and live | The production turn loop is gated, role-narrowed, composes one runtime-safe startup projection, durably compacts and trace-separates history, preflights every known-window request, reserves one bounded tool-free terminal response, bounds consecutive typed tool denials, and never recompacts the same logical request-fit segment without new tool growth |
| API Keys | 1.3.0 | Complete | Central keys feed resolved endpoints directly; credential presence alone never claims provider readiness |
| Audit | 2.9.1 | Implemented | Rotation, head lookup, durable append, and coherent readers share one audit lock; approval terminal decisions emit exactly one matching winner event |
| Cost Tracking | 1.6.0 | Implemented, recorded dollars unavailable | Auto-pause is real; measured tokens are durable, while `DocketDriver` reports no billed dollar amount. Budget gating uses a separately labelled estimate. Daily history remains empty because sessions do not store per-turn timestamps |
| Model Profiles | 2.8.0 | Complete | Fail-closed provider readiness separates coding subscriptions, credentials, endpoints, and the keyless local tool path |
| Pipeline Format | 2.2.0 | Implemented | `core/pipeline.py` format + `core/orchestrator.py` executor; verdict gates accept one unambiguous line-anchored marker across complete output; `docket pipeline validate/plan/run` (Phase 16 W-1 + W-2) |
| Pod Blueprints | 1.3.0 | Implemented | Five built-ins — software/research/content/ops plus `agentic-product`; deliberately data, not scaffolding. `docket init --blueprint`/`--from`; no user-authored blueprints yet |
| Pod Dispatch | 6.6.0 | Complete | Hop execution/history/handoff behavior is live; conversation hops mutate one validated locked registry and retain concurrent updates |
| Role Archetypes | 1.6.0 | Implemented | Built-ins, load-bearing `gateContract`, pod-blueprint composition, per-role `tokenBudget`, enforced `deniedTools`, and Docket-owned user overlays |
| Security Gates | 0.17.0 | Implemented (on by default) | Every tool call Docket dispatches passes through `core/tools.py`; pending approvals resolve through one conditional locked transition, and argument-aware policy, optional isolation, and inspectable allowlisted fetch share that chokepoint. General egress remains open by decision D-23 |
| Session History | 1.4.0 | Implemented and live | `core/session.py`: durable opaque-key history, lossless round-trip, bounded hierarchical atomic/ranged compaction, isolated summarizer key, recursion guard, and whole-operation fail-closed behavior; request fit can preserve the current task while compacting selected history |
| Session Scoping | 2.0.0 | Complete | Base metadata scope remains `agent:<id>:<project>`; pod dispatch derives isolated step-history keys and keeps a separate task trace without deleting prior sessions (W20-C4) |
| Telegram Integration | 2.2.0 | Implemented | `docket wire` discovers a group from a one-time Telegram command with manual fallback; Docket owns the bot and approval path, unbound chats fail closed, and delegated text passes through input policy |
| Workspace Structure | 1.9.0 | Complete | `DOCKET_HOME` is the only state root; specialist and workdir workspace contracts plus role-aware `TOOLS.md` are live |
| CLI Interface | 1.22.0 | Complete | The root wheel/sdist installs canonical `docket` with artifact-only version/help/init-help and metadata/uninstall contracts |
| MCP Client | 1.3.0 | Implemented and wired to the live turn path | External tools are namespaced, description-screened, loaded before role narrowing, and dispatched through the same gated chokepoint. Remote results honor the live `DOCKET_TOOL_MAX_OUTPUT_CHARS` context ceiling per call. Remaining limits: stdio only, no listing cache, and fail-closed zero MCP tools for read-only roles without trusted capability metadata. |
| Runtime Library | 2.1.0 | Implemented (artifact-tested; **not published to any index**) | `docket-runtime` `0.3.0` exclusively owns `docket_runtime/` and adds one bounded governed-execution envelope with reported-usage/tool-call limits, sole-chokepoint dispatch, paired traces, isolated approval stubs, and typed terminal handoff; wheel and sdist remain disjoint from `docket` and private transformed modules remain unsupported internals |
| MCP Server | 1.4.0 | Implemented | `docket mcp serve` — 10 tools, stdio, optional `docket[mcp]` extra, using the `mcp` 2.x SDK |
| CLI JSON Shapes | 1.6.0 | Complete | Docket-owned doctor/fleet contract and current snapshot channel provenance |
| docket-meta schema | 3.0.0 | Complete | Pod resource metadata is backed by collision-free allocation and attempt-owned rollback that preserves pre-existing runtime state |
| Serve Read API | 2.10.0 | Stable | Concurrent pod provisioning serializes one project while different projects share only the short atomic allocation transition |
| Input Validation | 1.4.0 | Complete | Docket-owned store and protocol-boundary validation |
| Test Framework | 2.12.0 | Active | Hermetic `DOCKET_HOME`, portable Codex/Claude/OpenCode development harnesses, golden fixtures, proportional validation, deterministic CLI→HTTP→runtime smoke, opt-in real-model canaries, byte-exact artifact gates, and public release-truth checks |
| User Stories | 1.4.0 | Active | Acceptance criteria (not a `.spec.md`) |

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
