# Workspace Structure Specification

**Version**: 1.3.0
**Status**: Complete
**Last Updated**: 2026-07-30

## Purpose

This specification defines the on-disk layout of an agent workspace: the files docket creates,
their roles, and the permission rules that keep a workspace valid.

## Scope

This specification covers:

- The directory and files that make up a project-agent (and pod-member) workspace
- The org-specialist layout
- Permission invariants and scaffolding quarantine

This specification does NOT cover the `.docket-meta.json` field schema or the
meta↔`openclaw.json` synchronization contract (both owned by ../data/docket-meta.spec.md), the
pod task queue's semantics (see pod-dispatch.spec.md), *how* a pod member's SOUL.md/AGENTS.md
prose is generated (ROADMAP Phase 16 W-6's declarative role archetypes — see
role-archetypes.spec.md; this spec covers only which files must exist and their permissions, not
the mechanism that fills SOUL.md/AGENTS.md in), or *which roster/workspace-kind a pod is
provisioned with* (ROADMAP Phase 16 W-7's pod blueprints — see pod-blueprints.spec.md; this spec
covers the resulting file set for either workspace kind, not blueprint selection/composition).

## Requirements

### Project-agent workspace

1. Each project agent **MUST** have a workspace at
   `~/.openclaw/workspaces/projects/<agent-id>/` containing:
   - `SOUL.md` — agent identity, scope, session key, and (optional) docket-owned persona block
   - `AGENTS.md` — session protocol and delegation rules
   - `TOOLS.md` — project-specific commands. For a standalone (non-pod) project agent this is
     always present; for a **pod member**, only an Implementer with allocated runtime resources
     or a `verifyCmd` gets one (allocated ports/scratch dir and the verify command, when set) —
     a Lead, Reviewer, Tester, or any other pod role has nothing role-specific to document and
     **MUST NOT** be flagged missing one by `docket doctor`
   - `HEARTBEAT.md` — the durable task ledger (in-flight tasks written before starting;
     resumed after a context reset)
   - `WORKFLOW_AUTO.md` — the runtime-forced startup file carrying the versioned
     resume/durability contract (`docket-contract` marker; regenerated, never hand-edited).
     Anchors either the **codebase** path (`## Your codebase`) or, for a `workdir`-kind pod
     (ROADMAP Phase 16 W-7 — see pod-blueprints.spec.md), the shared **working directory**
     (`## Your working directory`) — never both
   - `MEMORY.md` — long-lived memory rollup (seeded; thereafter agent-written)
   - `.docket-meta.json` — docket metadata (see data spec)
   - `memory/` — daily logs named `YYYY-MM-DD.md` (today's log seeded at provisioning)
2. A `workflows/` directory **MAY** exist as a pre-existing artifact of the now-retired
   `docket workflow`/Lobster surface (ROADMAP decision D-16, Phase 16 W-3) — docket no longer
   creates, reads, or manages it; any `*.lobster.yml` files inside are left untouched on disk.
3. Every project agent is provisioned from one template family; the former repo/task
   dual-type model was removed (the `type` field no longer exists). Every project agent has
   **either** a codebase path with auto-detected stack (`workspaceKind: codebase` — every project
   agent before W-7, and every `software`-blueprint pod today) **or** a plain working directory
   with no codebase assumption (`workspaceKind: workdir` — a `research`/`content`/`ops`-blueprint
   pod; see pod-blueprints.spec.md), never both.
4. Pod members are project agents with ids `<project>-<role>[-N]`, each with its **own**
   workspace under `projects/`; the pod **Lead's** workspace additionally holds
   `TASK_LIST.json`, the pod's task queue (one queue per pod, owned by pod-dispatch.spec.md).
5. OpenClaw self-authoring scaffolding (`IDENTITY.md`, `BOOTSTRAP.md`) **MUST NOT** remain
   live in a managed workspace: provisioning and `docket doctor` quarantine it to
   `.docket-archive/` (identity is docket-owned — role + optional persona from metadata).

### Org specialists

1. Org specialists (security, knowledge, manager, and the opt-in
   `portfolio-manager`) live at `~/.openclaw/workspaces/<role>/` and **MUST**
   have the same durable workspace set a project agent gets, minus `TOOLS.md`
   and any codebase-specific field neither exists for:
   - `SOUL.md` — role identity, scope, and a session key of the form
     `agent:<role>:org` (the org-scoped counterpart of a project agent's
     `agent:<id>:<project>`)
   - `AGENTS.md` — the same session-startup protocol every project agent follows
   - `HEARTBEAT.md` — the durable task ledger
   - `WORKFLOW_AUTO.md` / `MEMORY.md` / `memory/YYYY-MM-DD.md` — the runtime
     contract set, from the same `core/memory.py` `seed_contract` a project
     agent uses
   - `.docket-meta.json` (`kind: specialist`)
   - `TOOLS.md` **MUST NOT** be written for a specialist — it has no fixed
     codebase or build commands to document.
2. `docket install` provisions the full set above for every org specialist and
   the opt-in Portfolio Manager (`docket install --portfolio`). Provisioning is
   idempotent and backfill-safe: `SOUL.md`/`AGENTS.md`/`HEARTBEAT.md` are
   written only when absent (never clobbering agent-written content or a
   persona-decorated `SOUL.md`), and `seed_contract` never overwrites an
   existing `MEMORY.md` or daily log.
3. `docket doctor`'s runtime-contract healer covers org specialists as well as
   project agents (ROADMAP Phase 17 C-4 closed the gap where specialists had
   no contract files and this healer never saw them): a specialist with a
   missing or stale `WORKFLOW_AUTO.md` is re-seeded exactly like a project
   agent's. A specialist workspace left fully bare by a pre-C-4 install
   (`.docket-meta.json` only, no `SOUL.md`/`AGENTS.md`/`HEARTBEAT.md` at all)
   is backfilled by re-running `docket install`, which never touches a file
   that already exists.
4. The legacy org-wide manager queue (`~/.openclaw/workspaces/manager/TASK_LIST.json`) is
   retired; if present from a pre-Phase-10 install it is left on disk untouched and is read
   by nothing.

### Permissions

1. Workspace directories **MUST** be `700`.
2. Workspace files **MUST** be `600`.

## Interface Contracts

Workspaces are created and repaired through commands, not edited by hand:

```bash
docket add <agent-id> [location] [--blueprint <name>]  # Provision a pod (see pod-blueprints.spec.md)
docket maintain <agent-id> check          # Verify/repair structure and permissions
docket maintain <agent-id> rebuild        # Regenerate all files from metadata
docket install                            # Provision (or backfill) org specialist workspaces
docket doctor [--fix]                     # Heal a missing/stale WORKFLOW_AUTO.md, project or specialist
```

## Examples

### A provisioned project-agent workspace (`codebase`-kind)

```text
~/.openclaw/workspaces/projects/mywebsite/
├── SOUL.md
├── AGENTS.md
├── TOOLS.md
├── HEARTBEAT.md
├── WORKFLOW_AUTO.md
├── MEMORY.md
├── .docket-meta.json
├── memory/
│   └── 2026-07-30.md
└── workflows/
```

### A provisioned pod member with no TOOLS.md (`workdir`-kind, non-Implementer)

```text
~/.openclaw/workspaces/projects/my-market-scan-researcher/
├── SOUL.md
├── AGENTS.md
├── HEARTBEAT.md
├── WORKFLOW_AUTO.md          # anchors "## Your working directory", not a codebase
├── MEMORY.md
├── .docket-meta.json         # workspaceKind: "workdir", workDir: <path>
└── memory/
    └── 2026-07-30.md
```

### A provisioned org-specialist workspace

```text
~/.openclaw/workspaces/security/
├── SOUL.md
├── AGENTS.md
├── HEARTBEAT.md
├── WORKFLOW_AUTO.md
├── MEMORY.md
├── .docket-meta.json
└── memory/
    └── 2026-07-30.md
```

## Validation

### Pre-conditions

- `~/.openclaw` **MUST** be writable.

### Post-conditions

- After `docket add`, all required core files **MUST** exist with `700`/`600` permissions and
  a current-version contract marker in `WORKFLOW_AUTO.md`.
- After `docket install`, every org specialist (and the opt-in Portfolio Manager, when
  provisioned) **MUST** have the specialist file set above with `700`/`600` permissions and a
  current-version contract marker in `WORKFLOW_AUTO.md`.
- After `docket maintain rebuild`, core files **MUST** be regenerated from metadata (persona
  reapplied from `.docket-meta.json`).

### Invariants

- Directory permissions **MUST** be `700` and file permissions `600`.
- No live `IDENTITY.md`/`BOOTSTRAP.md` in a managed workspace (quarantined to
  `.docket-archive/`).
- A project agent is `workspaceKind: codebase` or `workspaceKind: workdir`, never both — a
  `workdir`-kind member's contract files never reference a codebase.

## Changelog

### Version 1.3.0 (2026-07-30)

- ROADMAP Phase 16 W-7 (pod blueprints): documented the `workdir` workspace kind (a plain working
  directory, no codebase assumption — see the new pod-blueprints.spec.md) alongside the existing
  `codebase` kind, and the corresponding `WORKFLOW_AUTO.md`/`MEMORY.md` anchoring difference.
  Corrected the `TOOLS.md` requirement: it was never actually written for a non-Implementer pod
  member (Lead/Reviewer/Tester/other role) — a gap `docket doctor` incorrectly flagged as broken
  until this same wave's fix — this spec now states the real, role-aware contract instead of the
  "every project agent has TOOLS.md" claim that was already false for those members.

### Version 1.2.2 (2026-07-30)
- ROADMAP Phase 16 W-3 (D-16) landed: `workflows/` is no longer a surface "slated for
  retirement" — `docket workflow`/Lobster is actually gone. Reworded requirement 2 to describe
  it as a leftover artifact docket no longer touches.

### Version 1.2.1 (2026-07-30)

- Cross-reference only (ROADMAP Phase 16 W-6): noted that a pod member's SOUL.md/AGENTS.md
  content is now generated from a declarative role archetype (`core/archetypes.py`) rather than
  per-role hardcoded string-building in `cli/_pod.py` — see the new role-archetypes.spec.md.
  This file's own contract (which files must exist, permissions) is unchanged; the four legacy
  roles' generated content remains byte-identical to before.

### Version 1.2.0 (2026-07-30)

- **ROADMAP Phase 17 C-4 shipped**: org specialists (security, knowledge, manager, and the
  opt-in Portfolio Manager) now get the same durable workspace set a project agent gets —
  `SOUL.md`/`AGENTS.md`/`HEARTBEAT.md` plus the `WORKFLOW_AUTO.md`/`MEMORY.md`/daily-log
  contract from `core/memory.py`'s `seed_contract` — instead of `.docket-meta.json` alone.
  `TOOLS.md` is deliberately never written for a specialist (no fixed codebase/build commands).
  `docket doctor`'s runtime-contract healer now enumerates specialist workspaces too (previously
  project-agent-only), so a missing/stale `WORKFLOW_AUTO.md` is healed for a specialist exactly
  as it is for a project agent. Provisioning and healing are both idempotent/backfill-safe: a
  file is written only when absent, so a real `HEARTBEAT.md`/`MEMORY.md` or a persona-decorated
  `SOUL.md` is never clobbered by a second `docket install` or `docket doctor --fix`. Replaced
  the "known gap" framing in the org-specialists section with the shipped contract. Also closed
  a latent gap this surfaced: `seed_contract`'s own files (`WORKFLOW_AUTO.md`/`MEMORY.md`/daily
  log) are now normalized to `600` like every other workspace file (previously created with
  whatever the process umask gave them).

### Version 1.1.0 (2026-07-30)

- Truth pass (Platformization baseline): file set updated to the real contract
  (`WORKFLOW_AUTO.md` + `MEMORY.md` added — both required and doctor-healed). Removed the
  repo/task dual-template MUST (the `type` field was deleted; one template family). Replaced
  the retired manager-queue section with the pod model (per-Lead `TASK_LIST.json`; legacy
  manager queue left untouched, read by nothing) and an org-specialists section that names
  the real provisioning gap (Phase 17 C-4). Sync contract ownership moved wholly to
  docket-meta.spec.md. Added the scaffolding-quarantine invariant (docket-owned identity).

### Version 1.0.0 (2026-06-09)

- Initial workspace-structure specification
- Documented the project and manager layouts, permissions, and sync invariants
