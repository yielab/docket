# Workspace Structure Specification

**Version**: 1.9.0
**Status**: Complete. `DOCKET_HOME` is the only state root: project/pod workspaces live under
`~/.docket/workspaces/projects/`, and org specialists under `~/.docket/workspaces/`.
**Last Updated**: 2026-08-19

## Purpose

This specification defines the on-disk layout of an agent workspace: the files docket creates,
their roles, and the permission rules that keep a workspace valid.

## Scope

This specification covers:

- The directory and files that make up a project-agent (and pod-member) workspace
- The org-specialist layout
- Permission invariants and scaffolding quarantine

This specification does NOT cover the `.docket-meta.json` field schema (owned by
../data/docket-meta.spec.md), the
pod task queue's semantics (see pod-dispatch.spec.md), *how* a pod member's SOUL.md/AGENTS.md
prose is generated (ROADMAP Phase 16 W-6's declarative role archetypes — see
role-archetypes.spec.md; this spec covers only which files must exist and their permissions, not
the mechanism that fills SOUL.md/AGENTS.md in), or *which roster/workspace-kind a pod is
provisioned with* (ROADMAP Phase 16 W-7's pod blueprints — see pod-blueprints.spec.md; this spec
covers the resulting file set for either workspace kind, not blueprint selection/composition).

## Requirements

### Project-agent workspace

1. Each project agent **MUST** have a workspace at
   `~/.docket/workspaces/projects/<agent-id>/` (`docket.config.PROJECTS_DIR`) containing:
   - `SOUL.md` — agent identity, scope, session key, and (optional) docket-owned persona block
   - `AGENTS.md` — session protocol and delegation rules
   - `TOOLS.md` — project-specific commands. For a standalone (non-pod) project agent this is
     always present; for a **pod member**, only an Implementer with allocated runtime resources
     or a `verifyCmd` gets one (allocated ports/scratch dir and the verify command, when set) —
     a Lead, Reviewer, Tester, or any other pod role has nothing role-specific to document and
     **MUST NOT** be flagged missing one by `docket doctor`
   - `HEARTBEAT.md` — the durable task ledger (in-flight tasks written before starting;
     resumed after a context reset). For a pod **Lead**, this file additionally carries a
     delimited, docket-owned dispatch region inside `## Active Tasks`
     (`core/memory.py`'s `DISPATCH_BLOCK_BEGIN`/`_END`) that pod dispatch mechanically
     keeps in sync with `TASK_LIST.json`'s `running` tasks (ROADMAP Phase 17 C-3 — see
     pod-dispatch.spec.md's "Mechanical HEARTBEAT ledger"); everything outside that
     region, including any hand-written entries elsewhere in the same file, is never
     touched by that sync
   - `WORKFLOW_AUTO.md` — the runtime-forced startup file carrying the versioned
     resume/durability contract (`docket-contract` marker; regenerated, never hand-edited).
     Anchors either the **codebase** path (`## Your codebase`) or, for a `workdir`-kind pod
     (ROADMAP Phase 16 W-7 — see pod-blueprints.spec.md), the shared **working directory**
     (`## Your working directory`) — never both
   - `MEMORY.md` — long-lived memory rollup (seeded; thereafter agent-written)
   - `.docket-meta.json` — docket metadata (see data spec)
   - `memory/` — daily logs named `YYYY-MM-DD.md` (today's log seeded at provisioning);
     `memory/.distilled/<YYYY-MM-DD>/` **MAY** additionally exist — an archive `docket maintain
     distill` (and `clean`/`reset` when `--distill-first` is on, the default; ROADMAP Phase 17
     C-2) writes daily logs into instead of deleting them, one dated subdirectory per distillation
     run. Never created at provisioning, never read by the runtime contract (a plain
     `memory/*.md` glob does not descend into it), and never counted as a "missing" file by
     `docket doctor`
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
5. Self-authoring scaffolding (`IDENTITY.md`, `BOOTSTRAP.md`) **MUST NOT** remain
   live in a managed workspace: provisioning and `docket doctor` quarantine it to
   `.docket-archive/` (identity is docket-owned — role + optional persona from metadata).

### Org specialists

1. Org specialists (security, knowledge, manager, and the opt-in
   `portfolio-manager`) live at `~/.docket/workspaces/<role>/` and **MUST**
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
2. The first `docket init` lazily provisions the full set above for every org specialist before
   it creates the project pod. Provisioning is
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
   is backfilled by the internal workstation bootstrap, which never touches a file
   that already exists.
4. The retired org-wide manager queue (`~/.docket/workspaces/manager/TASK_LIST.json`) is not part
   of the current contract; if present it is left untouched and read by nothing.

### Permissions

1. Workspace directories **MUST** be `700`.
2. Workspace files **MUST** be `600`.
3. A pod Implementer's `worktree/` is a checkout of the project codebase, not a Docket prompt/
   metadata file set. Permission healing **MUST NOT** recursively rewrite that checkout's modes;
   executable bits and repository-owned permissions remain intact. Provisioning and maintenance
   enforce `700`/`600` on the managed workspace root, prompt/metadata/ledger files, and `memory/`.

## Interface Contracts

Workspaces are created and repaired through commands, not edited by hand:

```bash
docket add <agent-id> [location] [--blueprint <name>]  # Provision a pod (see pod-blueprints.spec.md)
docket maintain <agent-id> check          # Verify/repair structure and permissions
docket maintain <agent-id> rebuild        # Regenerate all files from metadata
docket doctor [--fix]                     # Heal a missing/stale WORKFLOW_AUTO.md, project or specialist
```

## Examples

### A provisioned project-agent workspace (`codebase`-kind)

```text
~/.docket/workspaces/projects/mywebsite/
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
~/.docket/workspaces/projects/my-market-scan-researcher/
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
~/.docket/workspaces/security/
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

- `~/.docket` (or the configured `DOCKET_HOME`) **MUST** be writable; every workspace tier lives
  below that one Docket-owned root.

### Post-conditions

- After `docket add`, all required core files **MUST** exist with `700`/`600` permissions and
  a current-version contract marker in `WORKFLOW_AUTO.md`.
- After the first `docket init`, every org specialist (and the opt-in Portfolio Manager, when
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
- A pod Lead's `HEARTBEAT.md` dispatch region (see requirement 1) **MUST NOT** be the only thing
  a mechanical sync ever rewrites in that file — every other byte, including an agent's own
  entries under the same `## Active Tasks` heading, survives byte-for-byte.

## Changelog

### Version 1.9.0 (2026-08-19)

- Closed the pod-provisioning permission gap: newly written managed root files are owner-only even
  under a permissive user umask. Clarified that an Implementer's nested Git worktree retains
  repository-owned modes and is excluded from workspace permission healing.

### Version 1.8.0 (2026-08-19)

- W21-C1 daemon-free truth pass: collapsed migration prose into the single current
  `DOCKET_HOME`/`~/.docket` contract and removed retired-runtime paths from normative sections.

### Version 1.7.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7b (the OpenClaw daemon is deleted).** Completes the move version
  1.6.0 started: `docket.config.WORKSPACES_DIR` (the base every org-specialist workspace
  resolves against, and `PROJECTS_DIR`'s own parent) now points at `DOCKET_HOME`
  unconditionally — `OPENCLAW_DIR` itself is deleted, not merely superseded for one workspace
  tier. An org-specialist workspace (`manager`, `knowledge`, `security`, `portfolio-manager`)
  lives at `~/.docket/workspaces/<role>/`, not `~/.openclaw/workspaces/<role>/`, as of this
  version. Updated the "Org specialists" requirement, the org-specialist example tree, the
  legacy manager-queue path, and the pre-conditions section (one `~/.docket` writability
  pre-condition now, not two). No migration: per D-19's clean break, a pre-existing install's
  specialist workspaces at the old `~/.openclaw` path are not moved or read from; `docket
  install` on this version simply writes new specialist workspaces at the new path.

### Version 1.6.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7a (the runtime cutover).** `docket.config.PROJECTS_DIR` moved from
  `OPENCLAW_DIR` to `DOCKET_HOME` — every project-agent (pod-member) workspace now lives at
  `~/.docket/workspaces/projects/<agent-id>/`, not `~/.openclaw/workspaces/projects/<agent-id>/`.
  Updated requirement 1 and both project-agent example trees. Org-specialist workspaces
  (`~/.openclaw/workspaces/<role>/`, requirement in "Org-specialist workspace") are unaffected —
  they stay under `OPENCLAW_DIR` until ROADMAP P19-7b. Added a `~/.docket` writability
  pre-condition alongside the existing `~/.openclaw` one. No migration: per D-19's clean break, a
  pre-existing install's workspaces at the old path are not moved or read from.

### Version 1.5.0 (2026-07-31)

- ROADMAP Phase 17 C-3 (one durable task state): documented the pod Lead's docket-owned
  dispatch region inside `HEARTBEAT.md`'s `## Active Tasks` (requirement 1), mechanically
  synced from `TASK_LIST.json` by `core/dispatch.py` — full behavior lives in
  pod-dispatch.spec.md's "Mechanical HEARTBEAT ledger"; this spec only states that the file
  now carries it and that everything else in the file is unaffected.

### Version 1.4.0 (2026-07-30)

- ROADMAP Phase 17 C-2 (memory distillation): documented `memory/.distilled/<YYYY-MM-DD>/`, the
  archive `docket maintain distill` (and `clean`/`reset` with `--distill-first`, the default)
  moves daily logs into instead of deleting them. `MAY` exist, never created at provisioning,
  never read by the runtime contract, never flagged missing by `docket doctor`.

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
