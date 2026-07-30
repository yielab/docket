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
│   ├── api-keys.spec.md                  # API key management
│   ├── audit.spec.md                     # Audit log events, hash-chained + verify
│   ├── cost-tracking.spec.md             # Usage/cost reporting + budget caps (auto-pause shipped)
│   ├── eval.spec.md                      # Specialist-role eval harness
│   ├── model-profiles.spec.md            # Role→model policy and pinning
│   ├── pipeline-format.spec.md           # docket-native pipeline YAML format (no executor yet)
│   ├── pod-dispatch.spec.md              # Pod dispatch pipeline state machine and gates
│   ├── role-archetypes.spec.md           # Declarative role archetypes (registry, overlay, CLI)
│   ├── security-gates.spec.md            # Exec-approval gates (on by default; daemon-enforced)
│   ├── session-scoping.spec.md           # Multi-project session isolation
│   ├── telegram-integration.spec.md      # Telegram wire/unwire bindings
│   ├── workflow-integration.spec.md      # Lobster YAML surface (slated for retirement, D-16)
│   └── workspace-structure.spec.md       # Per-agent workspace layout
├── api/                                   # API contracts
│   ├── cli-interface.spec.md             # CLI command contracts and return codes
│   └── mcp-server.spec.md                # docket mcp serve — MCP tool surface (Phase 18 L-3)
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
owns delegation now.)

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
> Last synchronized: 2026-07-30 (after the Phases 15/16/18 wave: G-1, G-5, W-1, W-6, L-1, L-3).
> Verified row-by-row against every spec's own `**Version**` header, not carried forward — an
> index table cannot be auto-merged correctly when several branches bump versions in parallel.

| Specification | Version | Status | Notes |
| ------------- | ------- | ------ | ----- |
| Agent Lifecycle | 1.3.0 | Complete | |
| API Keys | 1.1.0 | Complete | |
| Audit | 2.1.0 | Implemented | Hash-chained + `docket audit verify`; `mcp.*` action family added (Phase 18 L-3); `models.*`/`runs.cancel` still uncovered (Phase 15 G-4 follow-up) |
| Cost Tracking | 1.3.0 | Implemented | Auto-pause is real (Phase 14 R-5); session-JSONL parsing now lives behind the RuntimeDriver port (Phase 18 L-1); enforcement stays scoped to the pod-dispatch lane |
| Eval | 1.0.1 | Complete | `--tier` is a results label (carved out of tier removal) |
| Model Profiles | 2.3.1 | Complete | Overridable rank anchors, local preset (Phase 18 L-2); archetype-modelClass fallback (Phase 16 W-6) |
| Pipeline Format | 1.0.0 | Implemented (format only) | `core/pipeline.py`; no executor/CLI yet (Phase 16 W-1; executor is W-2) |
| Pod Dispatch | 2.1.0 | Complete | v2 state machine: locked claims, crash resume, retries, bounded rework, auto-pause (Phase 14 R-1…R-7); require_approval gate + `waiting_approval` (Phase 15 G-1); hops run through the RuntimeDriver port (Phase 18 L-1) |
| Role Archetypes | 1.0.0 | Implemented | Built-ins byte-identical to pre-W-6 generators; gateContract not yet wired to dispatch (Phase 16 W-8) |
| Security Gates | 0.5.0 | Implemented (on by default) | Approval store has a real producer (Phase 15 G-1); daemon-gate bridge confirmed unavailable upstream, with evidence (Phase 15 G-5) |
| Session Scoping | 1.0.1 | Complete | |
| Telegram Integration | 1.0.1 | Complete | |
| Workflow Integration | 1.2.0 | Complete (slated for retirement) | ROADMAP D-16 / Phase 16 W-3 |
| Workspace Structure | 1.2.1 | Complete | Specialist workspace contract shipped (Phase 17 C-4) |
| CLI Interface | 1.8.0 | Complete | Signatures/exit codes; semantics live in functional specs |
| MCP Server | 1.0.0 | Implemented | `docket mcp serve` — 10 tools, stdio, optional `docket[mcp]` extra (Phase 18 L-3) |
| CLI JSON Shapes | 1.4.0 | Complete | |
| docket-meta schema | 2.6.0 | Complete | `requireApprovalRoles` added (Phase 15 G-1) |
| Serve Read API | 2.1.0 | Stable | Pinned by `tests/python/test_cd8_read_api.py`; `/runs` tier added (Phase 14 R-3); `mcp` run source added (Phase 18 L-3) |
| Input Validation | 1.2.0 | Complete | |
| Test Framework | 2.0.0 | Active | Conventions doc (not a `.spec.md`) |
| User Stories | 1.2.0 | Active | Acceptance criteria (not a `.spec.md`) |

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
