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
│   ├── audit.spec.md                     # Audit log events (partial coverage — stated inside)
│   ├── cost-tracking.spec.md             # Usage/cost reporting + budget caps (auto-pause pending)
│   ├── eval.spec.md                      # Specialist-role eval harness
│   ├── model-profiles.spec.md            # Role→model policy and pinning
│   ├── pod-dispatch.spec.md              # Pod dispatch pipeline state machine and gates
│   ├── security-gates.spec.md            # Exec-approval gates (on by default; daemon-enforced)
│   ├── session-scoping.spec.md           # Multi-project session isolation
│   ├── telegram-integration.spec.md      # Telegram wire/unwire bindings
│   ├── workflow-integration.spec.md      # Lobster YAML surface (slated for retirement, D-16)
│   └── workspace-structure.spec.md       # Per-agent workspace layout
├── api/                                   # API contracts
│   └── cli-interface.spec.md             # CLI command contracts and return codes
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
> Last synchronized: 2026-07-30.

| Specification | Version | Status | Notes |
| ------------- | ------- | ------ | ----- |
| Agent Lifecycle | 1.3.0 | Complete | |
| API Keys | 1.1.0 | Complete | |
| Audit | 1.1.0 | Partially implemented | Recorded families listed inside; coverage gap → Phase 15 G-4 |
| Cost Tracking | 1.1.0 | Partially implemented | Auto-pause unimplemented → Phase 14 R-5 |
| Eval | 1.0.1 | Complete | `--tier` is a results label (carved out of tier removal) |
| Model Profiles | 2.2.0 | Complete | |
| Pod Dispatch | 1.0.0 | Complete | Owns the dispatch state machine |
| Security Gates | 0.4.0 | Implemented (on by default) | Approval-seam gap stated inside → Phase 15 G-1/G-5 |
| Session Scoping | 1.0.1 | Complete | |
| Telegram Integration | 1.0.1 | Complete | |
| Workflow Integration | 1.2.0 | Complete (slated for retirement) | ROADMAP D-16 / Phase 16 W-3 |
| Workspace Structure | 1.2.0 | Complete | Specialist workspace contract shipped (Phase 17 C-4) |
| CLI Interface | 1.5.0 | Complete | Signatures/exit codes; semantics live in functional specs |
| CLI JSON Shapes | 1.1.0 | Complete | |
| docket-meta schema | 2.3.0 | Complete | |
| Serve Read API | 1.0.0 | Stable | Pinned by `tests/python/test_cd8_read_api.py` |
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
