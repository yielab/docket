# Pod Blueprints Specification

**Version**: 1.3.0
**Status**: Implemented
**Last Updated**: 2026-08-19

## Purpose

This specification defines the **pod blueprint**: a named, versioned pod shape (`core/blueprints.py`)
composing an archetype roster (`role-archetypes.spec.md`), a default pipeline (`pipeline-format.spec.md`),
a workspace kind, and an optional default budget cap. Before ROADMAP Phase 16 W-7, `docket add`
always provisioned the same four-role shape and every project agent implicitly assumed a
codebase — a research pod, a content pod, an ops pod were inexpressible in one command. This spec
documents the registry that generalizes pod *composition* the way `role-archetypes.spec.md`
generalized individual *roles*.

## Scope

This specification covers:

- The blueprint schema: `name`, `version`, `workspaceKind`, `roles`, `defaultPipeline`,
  `defaultBudgetUsd`, and `description` — which fields are closed typed enums and which are open
- The five built-in blueprints (`software`, `research`, `content`, `ops`, `agentic-product`) and
  the byte-identical guarantee `software` carries over the pre-W-7 default `docket add`
- The `workspaceKind` (`codebase` | `workdir`) distinction and how a `workdir` blueprint's shared
  working directory is resolved/auto-provisioned
- How `docket init --blueprint <name>` and `docket init --from <spec.yaml>` select and
  provision a blueprint
- The additive `.docket-meta.json` fields a blueprint-provisioned pod member carries (`blueprint`,
  `workspaceKind`, `workDir`) — schema authority for these fields is `docket-meta.spec.md`; this
  spec only covers when/why they are written

This specification does NOT cover:

- The archetype schema itself (`name`, `scope`, `modelClass`, `soulTemplate`, `agentsTemplate`,
  `gateContract`, `editRights`, `toolProfile`) — see `role-archetypes.spec.md`. A blueprint's
  `roles` list is a roster of archetype names; this spec does not redefine what an archetype is
- The pipeline format itself (steps, gates, rework edges, variables) — see
  `pipeline-format.spec.md`. A blueprint's `defaultPipeline` is one `PipelineSpec` value; this spec
  only covers which pipeline each built-in blueprint attaches and why
- Executing a pipeline, or wiring `gateContract`/pipeline gates into the dispatch executor —
  `core/dispatch.py` still drives every pod through its own hardcoded role order regardless of a
  pod's blueprint or attached pipeline. Tracked as ROADMAP Phase 16 W-2 (executor) / W-8
  (generalized gates); out of scope here
- User-authored blueprint definitions. Unlike `docket roles add` for archetypes, there is no
  `docket blueprints add <file.yaml>` yet — the five built-ins are the whole registry today (see
  Requirements, "User-authored blueprints" below)
- Per-role org-vs-pod scope as a blueprint-level concept — scope is a property of the *archetype*
  a role name resolves to (`role-archetypes.spec.md`), inherited by a blueprint's roster, not
  redeclared by this schema

## Requirements

### Blueprint schema

1. A pod blueprint **MUST** carry: `name` (string), `version` (positive integer), `workspaceKind`,
   `roles` (an ordered, non-empty list of archetype names), and `defaultPipeline` (a valid
   `PipelineSpec`, see `pipeline-format.spec.md`). `defaultBudgetUsd` and `description` **MAY** be
   present (absent/empty is valid for both).
2. `workspaceKind` **MUST** be one of exactly `"codebase"` | `"workdir"` — a closed enum, matching
   the same "closed typed sets docket can reason about" discipline `role-archetypes.spec.md`
   applies to `scope`/`modelClass`/`gateContract.kind`/`editRights`.
3. `roles`' first entry **MUST** be `"lead"`, and `"lead"` **MUST** appear exactly once — a pod has
   exactly one orchestrator (`core/pod.py`'s pre-existing singleton-Lead invariant, unaffected by
   this spec). Every other entry is an open archetype-name reference: any built-in, starter-library,
   or user-defined archetype registered in `role-archetypes.spec.md`'s registry is valid roster
   material — this schema does not re-validate role names itself; `core/pod.py`'s
   `plan_pod`/`normalize_role` do, the first time a blueprint's roster is actually provisioned.
4. `defaultBudgetUsd`, when present, **MUST** be a non-negative number. It is applied to the pod's
   **Lead only** at provisioning time (the same `budgetUsd` meta field `docket profile --budget`
   sets) — never to any other member.
5. `name` **MUST** match `^[a-z][a-z0-9-]*$`. `version` **MUST** be a positive integer. An
   invalid definition **MUST** be rejected with a clear error naming the offending field
   (`BlueprintError`), never silently coerced.
6. Every gated step in `defaultPipeline` that targets a role in `roles` **MUST** carry a gate whose
   kind matches that role's own archetype `gateContract.kind` exactly (`none` → no gate; `mechanical`
   → a `MechanicalGate`; `verdict` → a `VerdictGate`; `approval` → an `ApprovalGate`) — there is no
   separate "default gates" field on this schema that could drift from the pipeline; the pipeline
   *is* the gate declaration, inherited from the roster's own archetypes.

### Built-in blueprints

1. Five blueprints **MUST** ship (`core/blueprints.py`'s `BUILTIN_BLUEPRINTS`): `software`,
   `research`, `content`, `ops`, `agentic-product` (see Interface Contracts for their exact
   rosters/kinds/budgets).
2. `software` **MUST** be byte-identical to the pre-W-7 default `docket add` pod for any given
   input: same roster (`lead`, `implementer` — `core/pod.py`'s pre-existing `DEFAULT_POD_ROLES`),
   same `workspaceKind` (`codebase`), no default budget cap, and a `defaultPipeline` that is
   exactly `core.pipeline.default_pipeline()` (`pipeline-format.spec.md`'s own zero-migration
   pipeline) — not a second, independently hand-rolled copy.
3. `research`, `content`, and `ops` **MUST** be `workspaceKind: "workdir"` — none of the three
   assumes a codebase. `research` and `content` gate their final step on the Critic archetype's
   APPROVE/REJECT verdict with a bounded rework edge back to the Writer step; `ops` gates its
   Operator step mechanically (deferring to that member's own `verifyCmd`, mirroring the
   Implementer's convention) and its Monitor step on human approval.
4. `docket init <project>` with **no** `--blueprint` **MUST** resolve to `software`
   (`core.blueprints.DEFAULT_BLUEPRINT`) — omitting the flag and passing `--blueprint software`
   explicitly **MUST** be behaviorally indistinguishable.
5. `agentic-product` (ROADMAP Phase 21 P21-5) **MUST** be `workspaceKind: "codebase"` and its
   roster **MUST** be `core/pod.py`'s `FULL_POD_ROLES` (`lead`, `implementer`, `reviewer`,
   `tester`) — a product that ships an agent to end users carries more risk than an internal tool,
   so Reviewer and Tester run by default rather than being opt-in the way `software`'s `--pod
   full`/`--with` leaves them. Its `defaultPipeline` **MUST** be the same
   `core.pipeline.default_pipeline()` object `software` attaches (no second, blueprint-specific
   pipeline) — the difference from `software` is entirely in the roster, not the pipeline: the
   same Reviewer/Tester steps that a lean `software` pod never reaches at dispatch time actually
   gate a hop here because the roles are present. It carries no `defaultBudgetUsd`, matching
   `software`, the other `codebase`-kind blueprint. This blueprint is declarative data only — it
   does not scaffold repository contents; a pod provisioned from it is expected (by convention, not
   mechanically enforced by this schema) to embed the `docket-runtime` library (ROADMAP Phase 21
   P21-1) as its own guardrail substrate.

### Workspace kind and the working directory

1. A `codebase`-kind blueprint's location argument **MUST** be treated exactly as `docket add`
   treated its codebase-path argument before this spec existed — an operator-supplied (or empty)
   absolute path, never created by docket.
2. A `workdir`-kind blueprint's location argument **MUST** be treated as the pod's **shared**
   working directory (one per pod, not per member — the same "one codebase root shared by every
   software-pod member" pattern, generalized). When no location is given, docket **MUST**
   auto-provision one at `config.pod_work_dir(<project>)` (mode `700`), mirroring how
   `config.pod_scratch_dir()` auto-provisions a pod's scratch directory.
3. Every workspace-contract file a `workdir`-kind member's provisioning writes (`WORKFLOW_AUTO.md`,
   `MEMORY.md`, today's daily log) **MUST** anchor the working directory, not imply a git-tracked
   codebase — no "cd into the codebase" language, no `## Your codebase` heading. A `codebase`-kind
   member's contract files **MUST** be byte-for-byte unaffected by this distinction (verified by
   `tests/python/test_provisioning_contract.py`'s `TestSeedContractWorkdir`).
4. A pod member added later to an existing pod (`docket pod <project> add <role>`) **MUST**
   inherit the pod's `workspaceKind`/working-directory (or codebase) from an existing member,
   never defaulting to `codebase`-kind for a pod that was provisioned `workdir`-kind.
5. `docket doctor` **MUST NOT** flag a `workdir`-kind pod member as broken for lacking a `TOOLS.md`
   — `TOOLS.md` is written only for an Implementer with allocated resources or a `verifyCmd`
   (`workspace-structure.spec.md`), which no built-in `workdir` blueprint's roster includes.

### CLI surface

1. `docket init <project> [location] [--blueprint <name>]` **MUST** select a blueprint (default
   `software`) before prompting for anything else, and **MUST** fail cleanly (exit 1, no prompts
   issued) if `<name>` is not a registered blueprint.
2. `--pod full` / `--with <roles>` **MUST** continue to apply only to the `software` blueprint's
   roster (unchanged pre-W-7 behavior); passing them against any other blueprint **MUST** warn and
   provision that blueprint's own fixed roster, not silently combine the two.
3. `docket init --from <spec.yaml>` **MUST** accept a `blueprint` field on any spec entry. An entry
   carrying one **MUST** provision a pod (`build_pod_from_blueprint`) instead of the single flat
   agent the declarative path has always provisioned for an entry without that field — existing
   spec files with no `blueprint` field anywhere **MUST** be entirely unaffected (same single-agent
   path, same output, per `agent-lifecycle.spec.md`'s declarative-provisioning contract).
4. A `blueprint`-bearing spec entry **MUST** accept `codebase` (for a `codebase`-kind blueprint) or
   `workDir` (for a `workdir`-kind blueprint) as its location field, plus the existing `stack`,
   `description`, `telegram`, `projectKey`, and `budgetUsd` fields — `budgetUsd`, when present,
   **MUST** override the blueprint's own `defaultBudgetUsd` for that pod's Lead.
5. A pod-shaped spec entry whose pod already exists **MUST** be skipped (warned, not recreated,
   not aborting the rest of the spec file) — the same idempotence contract the single-agent
   declarative path already has.

### User-authored blueprints

1. Unlike role archetypes (`docket roles add <file.yaml>`), there is currently no
   `docket blueprints add` — the four built-ins in `core/blueprints.py` are Python literals and
   are the entire registry. A future card may add a `~/.docket/docket-blueprints.json` user
   overlay following the same pattern `docket-roles.json` established; until then, composing a
   custom pod shape means adding roles to an existing pod with `docket pod <project> add <role>`
   after provisioning from the closest built-in blueprint.

## Interface Contracts

### CLI Command Signatures

```text
docket init <project> [location] [--blueprint <name>]
docket init --from <spec.yaml>       # spec entries may carry a `blueprint` field
```

### Built-in blueprints

| Name | workspaceKind | Roles | defaultBudgetUsd | Gated step(s) |
| --- | --- | --- | --- | --- |
| `software` | codebase | lead, implementer | (none) | implementer: mechanical (own `verifyCmd`) |
| `research` | workdir | lead, researcher, analyst, writer, critic | 20.0 | critic: verdict (APPROVE\|REJECT), rework → writer |
| `content` | workdir | lead, writer, critic | 15.0 | critic: verdict (APPROVE\|REJECT), rework → writer |
| `ops` | workdir | lead, operator, monitor | 30.0 | operator: mechanical (own `verifyCmd`); monitor: approval |
| `agentic-product` | codebase | lead, implementer, reviewer, tester | (none) | implementer: mechanical (own `verifyCmd`); reviewer: verdict (APPROVE\|REQUEST-CHANGES), rework → implementer; tester: verdict (PASS\|FAIL) |

`software`'s `defaultPipeline` additionally declares `reviewer`/`tester` steps (inherited verbatim
from `core.pipeline.default_pipeline()`) that a lean `software` pod never reaches at dispatch time
— which roles a pod actually has is a runtime/executor concern, unchanged by this spec (see
`pipeline-format.spec.md`). `agentic-product` attaches the exact same `defaultPipeline` object; its
roster is the only difference, and it is precisely what makes the Reviewer/Tester steps reachable.

### `.docket-meta.json` fields this spec adds (schema authority: `docket-meta.spec.md`)

| Field | Written when | Meaning |
| --- | --- | --- |
| `blueprint` | Always, for any member provisioned via `build_pod_from_blueprint` | The blueprint name that provisioned this pod |
| `workspaceKind` | Only when the pod is `workdir`-kind | `"workdir"` — absent (implicitly `"codebase"`) for every codebase-kind pod, including every pre-W-7 record |
| `workDir` | Only when the pod is `workdir`-kind | The pod's shared working directory (mutually exclusive with `codebase`) |

### Return Codes

- `0`: success (pod provisioned, or a declarative spec file processed with only expected skips)
- `1`: unknown blueprint name, or pod provisioning failed to register any member

## Examples

### Provisioning a research pod interactively

```bash
docket add my-market-scan --blueprint research
# Working directory [/home/user/my-market-scan]:
# Display name [my-market-scan]:
# Agent ID [my-market-scan]:
# Stack [unknown]:
# Description (one line): quarterly competitive landscape scan
# Provisioning 'research' pod 'my-market-scan' (lead, researcher, analyst, writer, critic)...
```

### Provisioning a workdir pod declaratively

```yaml
# spec.yaml
agents:
  - id: launch-brief
    blueprint: content
    workDir: /home/user/work/launch-brief
    description: product launch one-pager
    budgetUsd: "10"
```

```bash
docket init --from spec.yaml
```

### An unknown blueprint fails cleanly

```bash
docket add myproj --blueprint wizard-pod
# [ERROR] unknown blueprint 'wizard-pod'; valid blueprints: software, research, content, ops, agentic-product
```

## Validation

### Pre-conditions

- `~/.docket` **MUST** be writable (pod provisioning, same as any `docket add`).
- For a `workdir` blueprint with an explicit location, that path (or its parent) **MUST** be
  creatable — docket creates it (`mkdir -p`, mode `700`) if absent.

### Post-conditions

- After `docket init <project> --blueprint software` (or no flag at all), the resulting pod's
  workspace files and `.docket-meta.json` (modulo the additive `blueprint` key) **MUST** be
  identical to what `docket init <project>` produced before this spec existed.
- After provisioning a `workdir` blueprint, every member's `WORKFLOW_AUTO.md` **MUST** contain
  `## Your working directory` and **MUST NOT** contain `## Your codebase`.
- `docket doctor` **MUST** report zero issues for a freshly provisioned, unmodified pod of any
  built-in blueprint.

### Invariants

- `workspaceKind`, when present, is always one of `"codebase"` | `"workdir"`.
- A blueprint's roster always starts with exactly one `"lead"`.
- Every gated step's gate kind in a built-in blueprint's `defaultPipeline` always matches the
  gated role's own archetype `gateContract.kind` (enforced by
  `tests/python/test_pod_blueprints.py`'s `TestPipelineGateFidelity`).

## Changelog

### Version 1.2.0 (2026-08-19)

- Corrected the prospective user-overlay and provisioning paths to Docket-owned state.

### Version 1.1.0 (2026-08-03)

- Added the fifth built-in blueprint, `agentic-product` (ROADMAP Phase 21 P21-5): `codebase`-kind,
  `core/pod.py`'s `FULL_POD_ROLES` roster (lead, implementer, reviewer, tester), the same
  `core.pipeline.default_pipeline()` object `software` attaches, no `defaultBudgetUsd`. Declarative
  data only — a fifth row in `BUILTIN_BLUEPRINTS`, not a new pipeline, gate, or role archetype, and
  no repository-scaffolding machinery. Updated the built-in-blueprint requirement, the Interface
  Contracts table, and the unknown-blueprint example's valid-blueprints list accordingly.

### Version 1.0.0 (2026-07-30)

- Initial specification (ROADMAP Phase 16 W-7): the blueprint schema, the four built-in
  blueprints, the `workspaceKind` distinction and `workdir` auto-provisioning, the
  `docket add --blueprint`/extended `--from spec.yaml` CLI surface, and the additive
  `.docket-meta.json` fields (`blueprint`, `workspaceKind`, `workDir`).
