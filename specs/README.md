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
│   ├── eval.spec.md                      # Specialist-role eval harness
│   ├── mcp-client.spec.md                # MCP client: pluggable tool servers (Phase 19 P19-10)
│   ├── model-profiles.spec.md            # Role→model policy and pinning
│   ├── pipeline-format.spec.md           # docket-native pipeline YAML format + executor (W-1/W-2)
│   ├── pod-dispatch.spec.md              # Pod dispatch pipeline state machine and gates
│   ├── role-archetypes.spec.md           # Declarative role archetypes (registry, overlay, CLI)
│   ├── security-gates.spec.md            # Exec-approval gates (on by default; daemon-enforced)
│   ├── session-history.spec.md           # Durable per-session turn history + compaction (Phase 19 P19-4)
│   ├── session-scoping.spec.md           # Multi-project session isolation
│   ├── telegram-integration.spec.md      # Telegram wire/unwire bindings
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
owns delegation now. workflow-integration.spec.md, 2026-07-30 — `docket workflow`'s Lobster YAML
surface was retired per D-16; pipeline-format.spec.md owns the pipeline dialect docket actually
executes now.)

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
> Last synchronized: 2026-07-31 (Phase 19 P19-5 added Agent Loop — see its row below).
> Previously synchronized 2026-07-31 (Phase 19 P19-4 added Session History — see its row below).
> Previously synchronized 2026-07-30 (wave 6 complete: L-5, W-5b, C-1, C-2, G-2 — after wave 5's
> L-4, G-4b, W-4, CL-2, W-5 and wave 4's CL-1, L-6, W-3, W-7, W-2+W-8 and wave 3's G-1, G-5, W-1,
> W-6, L-1, L-3).
> The `Workflow Integration` row was dropped here, one merge late: W-3 deleted the spec file itself
> (D-16) but the row survived the wave-4 index reconciliation. The row count is now exactly the 21
> `.spec.md` files on disk.
> Verified row-by-row against every spec's own `**Version**` header, not carried forward — an
> index table cannot be auto-merged correctly when several branches bump versions in parallel.

| Specification | Version | Status | Notes |
| ------------- | ------- | ------ | ----- |
| Agent Lifecycle | 1.5.0 | Complete | `docket add` blueprint selection (Phase 16 W-7); `maintain distill` + distill-before-delete (Phase 17 C-2) |
| Agent Loop | 1.0.0 | Implemented | `core/agent_loop.py` + `edges/adapters/docket_runtime.py`'s `DocketDriver` (Phase 19 P19-5): the turn loop docket now owns, dispatching every tool call through `core.tools.dispatch_tool`; not yet wired as any caller's default driver (Wave B / P19-6 / P19-7) |
| API Keys | 1.1.0 | Complete | |
| Audit | 2.3.0 | Implemented | Hash-chained + `docket audit verify`; `mcp.*` (Phase 18 L-3), `models.*` (Phase 15 G-4b) and `runs.cancel` (Phase 16 W-4) all covered — both formerly tracked gaps closed; what remains uncovered is structural (actions taken outside docket) |
| Cost Tracking | 1.3.0 | Implemented | Auto-pause is real (Phase 14 R-5); session-JSONL parsing now lives behind the RuntimeDriver port (Phase 18 L-1); enforcement stays scoped to the pod-dispatch lane |
| Eval | 1.0.1 | Complete | `--tier` is a results label (carved out of tier removal) |
| Model Profiles | 2.4.0 | Complete | Overridable rank anchors, local preset (Phase 18 L-2); archetype-modelClass fallback (Phase 16 W-6); `models.*` audit coverage (Phase 15 G-4b); carries the L-5 spike's evidence that a sidecar gateway needs no new capability (Phase 18 L-5) |
| Pipeline Format | 2.1.0 | Implemented | `core/pipeline.py` format + `core/orchestrator.py` executor; `docket pipeline validate/plan/run` (Phase 16 W-1 + W-2); webhook payload → pipeline variables (Phase 16 W-4) |
| Pod Blueprints | 1.0.0 | Implemented | Four built-ins (software/research/content/ops); `docket add --blueprint`/extended `--from` (Phase 16 W-7); no user-authored blueprints yet |
| Pod Dispatch | 5.0.0 | Complete | v2 state machine (Phase 14 R-1…R-7); require_approval + `waiting_approval` (Phase 15 G-1); RuntimeDriver port (Phase 18 L-1); executor-driven generalized gates, parallel groups, cancellation (Phase 16 W-2/W-8); typed handoff artifacts replace raw-text hop concatenation (Phase 16 W-5), with a real `files_changed`/`diff_ref` producer (W-5b); token-budgeted hop prompts via the context compiler, retiring R-7's byte cap (Phase 17 C-1) |
| Role Archetypes | 1.3.0 | Implemented | Built-ins byte-identical to pre-W-6 generators; `gateContract` now load-bearing via the executor (Phase 16 W-8); composed into pod blueprints (Phase 16 W-7); per-role `tokenBudget` for the context compiler (Phase 17 C-1) |
| Security Gates | 0.6.0 | Implemented (on by default) | Approval store has a real producer (Phase 15 G-1); daemon-gate bridge confirmed unavailable upstream, with evidence (Phase 15 G-5); the policy engine is on the live dispatch path — `pre_input` at enqueue, `pre_output` per hop (Phase 15 G-2) |
| Session History | 1.0.0 | Implemented | `core/session.py` (Phase 19 P19-4): durable per-session turn history, lossless message round-trip, atomic tool-call/tool-result compaction, fail-closed summarisation; first caller is `core/agent_loop.py` (Phase 19 P19-5, see Agent Loop row) |
| Session Scoping | 1.0.1 | Complete | |
| Telegram Integration | 1.0.1 | Complete | |
| Workspace Structure | 1.4.0 | Complete | Specialist workspace contract shipped (Phase 17 C-4); `workdir` workspace kind + role-aware `TOOLS.md` (Phase 16 W-7) |
| CLI Interface | 1.11.0 | Complete | Signatures/exit codes; semantics live in functional specs; `docket pipeline`/`docket runs cancel` (Phase 16 W-2); `pipeline run --follow` (Phase 16 W-4) |
| MCP Server | 1.2.0 | Implemented | `docket mcp serve` — 10 tools, stdio, optional `docket[mcp]` extra (Phase 18 L-3); on the `mcp` 2.x SDK, pin `>=2.0.0` (Phase 18 L-6); carries the L-4 spike's dated evidence that the daemon-side MCP registry is real upstream but absent from the targeted daemon |
| CLI JSON Shapes | 1.4.0 | Complete | |
| docket-meta schema | 2.7.0 | Complete | `requireApprovalRoles` (Phase 15 G-1); `blueprint`/`workspaceKind`/`workDir` (Phase 16 W-7) |
| Serve Read API | 2.2.0 | Stable | Pinned by `tests/python/test_cd8_read_api.py`; `/runs` tier (Phase 14 R-3); `mcp` run source (Phase 18 L-3); `POST /dispatch/<project>` variable binding + 400s (Phase 16 W-4) |
| Input Validation | 1.2.0 | Complete | |
| Test Framework | 2.0.0 | Active | Conventions doc (not a `.spec.md`) |
| User Stories | 1.3.0 | Active | Acceptance criteria (not a `.spec.md`) |

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
