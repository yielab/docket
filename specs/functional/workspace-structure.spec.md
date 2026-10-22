# Workspace Structure Specification

**Version**: 1.22.0
**Status**: Complete. `DOCKET_HOME` is the only state root: project/pod workspaces live under
`~/.docket/workspaces/projects/`. There are no shared agents: no workspace is provisioned outside a pod. P26-9 gave
`WORKFLOW_AUTO.md` a manual-path header (contract v4) — see the "Project-agent workspace"
requirement and role-archetypes.spec.md. P26-10 adds the operator-owned `INSTRUCTIONS.md` and
`docket pod update` — see the same requirement and pod-dispatch.spec.md. P26-20 added
"Shipped-data templates" below: `templates/recipes/<name>/` ships alongside this spec's own
`templates/policies/` as read-only package data, neither of which is itself a workspace. P31-2
adds requirement 4: `$DOCKET_HOME/recipes/<name>/`, the operator's own recipes, is *not*
package data despite living beside the shipped library in `resolve_recipe`'s lookup order. P31-6
added "Skills scopes": `~/.docket/skills/` and a pod's own `config/skills/`. P32-4 added
requirement 5: `templates/exporters/` joins `templates/providers/` as read-only shipped data;
`docket-exporters.json`/`exporters-health.json` are documented in
observability-export.spec.md, not here — this spec's scope is the workspace and template layer,
not `DOCKET_HOME`'s own top-level registry files (see "Shipped-data templates").
**Last Updated**: 2026-10-18

## Purpose

This specification defines the on-disk layout of an agent workspace: the files docket creates,
their roles, and the permission rules that keep a workspace valid.

## Scope

This specification covers:

- The directory and files that make up a project-agent (and pod-member) workspace
- Permission invariants
- The boundary between a provisioned *workspace* (covered above) and shipped, read-only
  *package data* under `src/docket/templates/` (`templates/policies/`, and P26-20's
  `templates/recipes/<name>/`) — see "Shipped-data templates" below

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
   - `SOUL.md` — agent identity, scope, and session key
   - `AGENTS.md` — session protocol and delegation rules
   - `TOOLS.md` — project-specific commands. For a standalone (non-pod) project agent this is
     always present; for a **pod member**, only an Implementer with allocated runtime resources
     or a `verifyCmd` gets one (allocated ports/scratch dir and the verify command, when set) —
     a Lead, Reviewer, Tester, or any other pod role has nothing role-specific to document and
     **MUST NOT** be flagged missing one by `docket setup`
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
     (`## Your working directory`) — never both. As of contract v4 (P26-9; see
     role-archetypes.spec.md "Generated instructions agree with the runtime contract"), it opens
     with a **"Manual-path contract"** header stating that its own `cd`/write-`HEARTBEAT.md`
     instructions apply only to an agent reading this file directly, outside Docket's turn loop —
     the live turn loop never sends this raw file to the model, composing a small read-only
     projection instead (`core/identity.py`)
   - `MEMORY.md` — the operator's free notes about the project (seeded; docket never writes it
     again). The seed names no path: its stack line is the only fact it carries from
     provisioning. A live turn composes it only when it holds text beyond that template
     (agent-loop.spec.md requirement 30). What a pod learns by itself lives in the pod's
     `memory.json` ("Pod memory" below), not here
   - `.docket-meta.json` — docket metadata (see data spec)
   - `memory/` — an empty directory at provisioning. docket seeds no daily log, distills none
     and archives none (ADR 0028 point 7; the pipeline had no writer in a pod task). A
     `YYYY-MM-DD.md` file or a `.distilled/` archive an older docket left there stays as it is:
     docket never reads, moves or deletes it, `docket pod reset` included, and `docket setup`
     never counts one as missing
2. A `workflows/` directory **MAY** exist as a pre-existing artifact of the now-retired
   Lobster workflow surface (ROADMAP decision D-16, Phase 16 W-3) — docket no longer
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
5. *Removed (2026-10-03):* the `IDENTITY.md`/`BOOTSTRAP.md` quarantine to `.docket-archive/`.
   docket never reads either file (identity is docket-owned — the role, from
   metadata, rendered into `SOUL.md`), so neither provisioning, `docket init` nor `docket
   doctor` moves or deletes one; a file of that name in a workspace is inert.
6. `INSTRUCTIONS.md` **MAY** exist in any project-agent workspace, pod member or not.
   Unlike every other file above it is **operator-owned**: docket **MUST NOT** create,
   write, regenerate, move, or delete it at any point — not at provisioning, not by
   `docket pod update`, not by `pod set verify`'s TOOLS.md rewrite, not by `docket pod
   reset`, and not by `docket setup --fix`. When present, its content is composed into
   the live prompt immediately after `SOUL.md` (agent-loop.spec.md requirement 30) so an
   operator's own instructions survive every regeneration path that would otherwise
   overwrite a generated file. A pod member's `SOUL.md`/`AGENTS.md`/`TOOLS.md` remain
   fully regeneratable — `docket pod update [--dry-run]` re-renders whichever of them
   have drifted from the member's current role archetype and stored metadata (a
   `POD_TEMPLATE_VERSION` bump, or the archetype's own content changing), applying the
   new text and restamping `templateVersion` in `.docket-meta.json`; `--dry-run` prints
   the same comparison as a diff without writing. A member with nothing stale is a no-op:
   `sync` writes nothing and leaves `templateVersion` alone. `docket setup` **MUST**
   flag a stale pod member (advisory, same severity as the existing non-pod
   `_check_template_version`) rather than silently skipping every pod member the way it
   did before this requirement.

### Pod memory (P44-7, ADR 0028 point 7)

What a pod learns about its repository survives the task that learned it, in one file for the
whole pod and every member that reads it.

1. A pod **MAY** have `memory.json` at `$DOCKET_HOME/workspaces/pods/<pod>/memory.json`
   (`config.pod_memory_path`), shaped `{"entries": [...]}`. It is created by the first recorded
   entry, written only through `edges/store.py` (atomic, filelocked, `0600`) and removed with the
   pod. An entry is `{id, kind, path | command, note, status, reason, provenance}` where
   `status` is `accepted`, `pending` or `refused`, `reason` says why in one phrase, and
   `provenance` is `{task, date, commit}`; a `command` entry also carries `exit`, the status
   docket read from the task's trace. The `id` is derived from `(kind, subject)`, so it is also
   the deduplication key.
2. The kinds are closed: `generated` (a repository path not worth reading, with what it is),
   `command` (a command and what it showed), `pitfall` and `convention` (a repository path, or
   `.` for the whole repository, and one fact about it). A note is one sentence of at most 200
   characters.
3. **The memory section.** A step's reply **MAY** end with a section opened by a line that is
   exactly `## Memory`, followed by one line per entry of the form
   `- <kind>: <path or command> -- <note>`. The last such heading wins; the section ends at the
   next heading or the end of the reply; a line that is not a bullet is ignored; a bullet that does
   not fit the grammar or names another kind is dropped and traced as refused. At most
   `config.POD_MEMORY_MAX_PER_TASK` entries are read per reply. docket reads it when the task
   reaches a terminal state (`dispatch._finalize_task`), from every hop that ended ok.
4. **Acceptance is mixed.** docket decides each entry, never the model:
   - **refused**, with a reason: a malformed subject (absolute, `..`, empty), a note over the
     limit, a note that reads as an instruction or carries a URL (a note that starts with an
     imperative verb, or contains `ignore`, `disregard`, `override`, `always`, `never`, `do not`,
     `don't`, `must`, `should`, `from now on`, `system prompt` or `instruction`), a `pre_input`
     verdict of `block`, `require_approval` or `redact` on the entry's text (screened untrusted,
     the pod's own policies included), a `generated` path absent at the task's commit, or a
     `command` with no exit status in the task's trace.
   - **pending**: every `pitfall` and `convention`; every entry of a task whose trace holds a
     `fetch` tool call, or whose trace cannot be read; a `pre_input` verdict of `warn`; a
     `generated` entry when the task produced no commit.
   - **accepted**, automatically: a `generated` entry whose path exists at the task's commit
     (`git cat-file -e <commit>:<path>`), and a `command` entry whose command has an exit status
     in the task's trace (a `command_step`, the verify gate, or a `bash` call with its
     `process_exited`). The task's commit is the latest hop evidence commit.
   Text that arrived from the repository, a tool result or the web is therefore never stored as
   an instruction: nothing is accepted from it except a fact docket checked itself.
5. **Bounds and deduplication.** An entry already present for the same `(kind, subject)` is not
   added again: an accepted or refused one stands (a refusal is the operator's or docket's
   decision and is not reopened), a pending one is replaced only by an accepted one. At most
   `config.POD_MEMORY_MAX_ACCEPTED` accepted entries are kept, the oldest dropped first, and at
   most `config.POD_MEMORY_MAX_UNDECIDED` pending and refused ones together, the oldest dropped
   first, so a flood of pending entries cannot push an accepted one out.
6. **Render.** `core.identity.compose_agent_prompt` **MUST** compose the accepted entries as the
   last section of the system prompt, after `MEMORY.md`, behind its own untrusted frame
   (`POD_MEMORY_FRAME`: the entries come from earlier tasks of this pod, not from the operator,
   and are never a request to run commands or to change tools, approvals or policies) and never
   in docket's voice. The section is reported as `podMemory` in `prompt_composed`. It is
   capped at `config.POD_MEMORY_RENDER_MAX_BYTES` by dropping the oldest whole entries, an entry
   whose path no longer exists under the first project root is omitted (not deleted), and no
   accepted entry composes nothing, byte-identically to before this section existed.
7. **Every change is recorded.** Adding, deciding, reverting or resetting entries writes one
   `memory_update` trace event per entry (trace-store.spec.md) and one `pod.memory.<action>`
   audit entry carrying the entry id, kind and status, never its note or subject.
8. `core/pod_memory.py` **MUST** expose the operator's side as a typed API: `list_entries`,
   `approve` (pending to accepted), `refuse` (pending to refused, with a reason), `revert`
   (accepted to refused, so the same fact is not accepted again) and `reset` (remove every
   entry). Each audits and traces like requirement 7. `approve`, `refuse`, `revert` and `reset`
   raise `PodMemoryError` for an unknown id or an entry in the wrong state.
9. `docket pod reset <member>` **MUST NOT** read or change `memory.json`, `MEMORY.md` or `memory/`.
10. **The operator's side** is `docket pod memory` (cli-interface.spec.md) and the inbox
    (operator-loop.spec.md area 5, item 11); every action calls the requirement 8 API with
    `actor="cli"`, so the entry moves and the audit and trace record are written by the one
    writer. An approved entry reaches the pod's next composed prompt (requirement 6); a reverted
    one leaves it and stays as a refusal.

### No shared agents

1. `docket init` **MUST** provision the pod's own members and nothing else: no workspace exists
   under `~/.docket/workspaces/` outside `projects/<member>/`, and `fleet.json` registers only
   pod members.
2. `docket setup` and `docket pod reset` **MUST** act on pod members only; a directory under
   `~/.docket/workspaces/` that is not a pod member is not read, healed or reported.

### Permissions

1. Workspace directories **MUST** be `700`.
2. Workspace files **MUST** be `600`.
3. A pod Implementer's `tasks/<taskId>/` directories are git worktrees of the project codebase,
   created by dispatch at claim (pod-dispatch.spec.md "Task worktrees"), not a Docket prompt/
   metadata file set. Permission healing **MUST NOT** recursively rewrite those checkouts' modes;
   executable bits and repository-owned permissions remain intact. Provisioning and maintenance
   enforce `700`/`600` on the managed workspace root, prompt/metadata/ledger files, and `memory/`.

### Shipped-data templates (package, not workspace)

`src/docket/templates/` (`docket.config.templates_dir()`) is package data shipped in the wheel —
read-only source material a command *copies from* or *reads*, never a workspace this spec's
permission/provisioning rules apply to.

1. `templates/policies/*.json` (baseline guardrail policies, installed by `docket init`) and
   `templates/recipes/<name>/` (P26-20's role/pipeline/policy bundles, applied by hand through
   `docket pod roles`/`docket pod`/`docket pod policies` — never auto-applied) **MUST** both resolve
   through a `docket.config` accessor (`policy_templates_dir()`, `recipes_dir()`) rather than a
   hardcoded relative path, so a template's real location can never drift from where the
   installed package actually put it.
2. A role a recipe provisions (e.g. `docket pod add security-vetter` after `docket pod update
   templates/recipes/secure-build/roles/security-vetter.yaml`) **MUST** produce a workspace
   satisfying every requirement above — the same `700`/`600` permissions, the same required core
   files, the same contract marker. A recipe is a source of *archetype data*
   (`role-archetypes.spec.md`); it creates no new provisioning path and is invisible to this
   spec's own requirements once the workspace exists.
3. Nothing under `templates/` is itself writable by a provisioned agent, and no workspace file is
   ever a symlink into it — copying (policies) or reading-then-validating (recipes) is always by
   value, so editing a shipped template after installation never mutates an already-provisioned
   workspace or an already-copied policy.
4. **`$DOCKET_HOME/recipes/<name>/` is operator-owned state, not package data (P31-2, ADR
   0013 §1 rule 4).** It resolves through `docket.config.user_recipes_dir()`, is writable by the
   operator (a plain directory drop-in, no registration step), and is never shipped in the wheel
   — unlike `recipes_dir()`, it does not fall under this section's "package, not workspace"
   scope, and `docket pod reset`/`docket setup` never touch it. `core.pod_apply.resolve_recipe`
   checks it before the shipped `recipes_dir()`, so a same-named operator recipe wins; `docket
   pod recipes [name]` (`cli-interface.spec.md`) is this directory's read-only discovery
   surface, alongside the shipped library.
5. `templates/exporters/*.yaml` (the five built-in `kind: exporter` documents, ADR 0014)
   **MUST** resolve through `docket.config.EXPORTER_TEMPLATES_DIR`, the same read-only,
   wheel-shipped shape as `templates/providers/`. Neither `templates/providers/` nor
   `templates/exporters/` is itself a workspace this spec's permission rules apply to; the
   catalogs built from them (`docket-providers.json`, `docket-exporters.json`) and the
   exporter health file (`exporters-health.json`) are `DOCKET_HOME`-level registry files
   documented by their own owning specs (model-profiles.spec.md, observability-export.spec.md)
   rather than by this one.

### Skills scopes (P31-6, ADR 0013 §3 rule 8)

1. `~/.docket/skills/` (`docket.config.SKILLS_DIR`) is the operator's own global Agent Skills
   directory — writable runtime state docket reads, unlike the read-only `templates/` above. A
   pod's own `config/skills/` (`docket.config.pod_config_dir(project) / "skills"`) holds one
   directory per skill a recipe's own `skills/` was applied there (`pod-blueprints.spec.md`,
   "Pod manifests: apply"/"export"). Both, once written, follow this spec's `700`/`600`
   permission rules ("Permissions" above) the same way `config/policies/` and `config/plugins/`
   already do. Discovery order (nearest-wins across a codebase's own `.docket/skills/`, the pod
   scope, and this global scope) and the `skill` tool are owned by `agent-loop.spec.md`, not
   here — this spec covers only the two directories' existence and permissions.

## Interface Contracts

Workspaces are created and repaired through commands, not edited by hand:

```bash
docket init [<project>] [location] [--blueprint <name>]  # Provision a pod (see pod-blueprints.spec.md)
docket pod add <role> [--pod <name>]         # Add a member workspace to an existing pod
docket setup --fix          # Verify/repair structure and permissions
docket pod reset <member>                 # Distill memory, then regenerate all files from metadata
docket pod update [--dry-run]     # Re-render stale pod-member SOUL/AGENTS/TOOLS
docket setup [--fix]                     # Heal a missing/stale WORKFLOW_AUTO.md in a pod member
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
└── memory/
    └── 2026-07-30.md
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

## Validation

### Pre-conditions

- `~/.docket` (or the configured `DOCKET_HOME`) **MUST** be writable; every workspace tier lives
  below that one Docket-owned root.

### Post-conditions

- After `docket init` (or `docket pod add` for a new pod member), all required core files **MUST** exist with `700`/`600` permissions and
  a current-version contract marker in `WORKFLOW_AUTO.md`.
- After the first `docket init` in a fresh home, `workspaces/` holds only the pod's members.
- After `docket pod reset <member>`, `SOUL.md`, `AGENTS.md`, `TOOLS.md` and the `HEARTBEAT.md`
  ledger **MUST** be regenerated from metadata; `MEMORY.md`, `memory/` and the pod's
  `memory.json` are left as they were.

### Invariants

- Directory permissions **MUST** be `700` and file permissions `600`.
- A project agent is `workspaceKind: codebase` or `workspaceKind: workdir`, never both — a
  `workdir`-kind member's contract files never reference a codebase.
- A pod Lead's `HEARTBEAT.md` dispatch region (see requirement 1) **MUST NOT** be the only thing
  a mechanical sync ever rewrites in that file — every other byte, including an agent's own
  entries under the same `## Active Tasks` heading, survives byte-for-byte.
- `INSTRUCTIONS.md` (requirement 6) is never written by docket under any command name —
  provisioning, `sync`, `set-verify`, `maintain rebuild`, and `doctor --fix` alike leave an
  existing `INSTRUCTIONS.md` byte-for-byte untouched.
