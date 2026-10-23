# Workspace Structure Specification

**Version**: 2.1.2
**Status**: Complete. `DOCKET_HOME` is the only state root. Agent workspaces live under
`~/.docket/workspaces/projects/`; a pod's runtime resources, configuration overlay and learned
memory live under `~/.docket/workspaces/pods/<pod>/`. `docket init` provisions pods.
**Last Updated**: 2026-10-23

## Purpose

This specification defines the on-disk layout of an agent workspace: the files docket creates,
their roles, and the permission rules that keep a workspace valid. It also defines a pod's learned
memory file and the shipped, read-only package data that provisioning copies from.

## Scope

This specification covers:

- The directory and files that make up a project-agent (and pod-member) workspace
- Permission invariants
- A pod's learned memory (`memory.json`): how entries are recorded, decided, rendered and reviewed
- The boundary between a provisioned *workspace* and shipped, read-only *package data* under
  `templates/` (policies, recipes, providers, exporters, channels)

This specification does NOT cover the `.docket-meta.json` field schema (owned by
../data/docket-meta.spec.md), the pod task queue's semantics (see pod-dispatch.spec.md), *how* a
pod member's `SOUL.md`/`AGENTS.md` prose is generated (see role-archetypes.spec.md; this spec
covers only which files must exist and their permissions), *which roster/workspace kind* a pod is
provisioned with (see pod-blueprints.spec.md), or `DOCKET_HOME`'s own top-level registry files
(`docket-providers.json`, `docket-exporters.json`, `exporters-health.json`, ...), which their
owning specs document (model-profiles.spec.md, observability-export.spec.md).

## Requirements

### Project-agent workspace

1. Each project agent **MUST** have a workspace at `~/.docket/workspaces/projects/<agent-id>/`
   containing:
   - `SOUL.md` — agent identity, scope, and session key
   - `AGENTS.md` — session protocol and delegation rules
   - `TOOLS.md` — project-specific commands. Only an Implementer with allocated runtime resources
     or a `verifyCmd` gets one (allocated ports/scratch dir and the verify command, when set) —
     a Lead, Reviewer, Tester, or any other pod role has nothing role-specific to document and
     **MUST NOT** be flagged missing one by `docket setup`, and neither is an Implementer with
     neither resources nor a `verifyCmd`
   - `HEARTBEAT.md` — the durable task ledger (in-flight tasks written before starting;
     resumed after a context reset). For a pod **Lead**, this file additionally carries a
     delimited, docket-owned dispatch region inside `## Active Tasks`
     (`DISPATCH_BLOCK_BEGIN`/`DISPATCH_BLOCK_END`) that pod dispatch mechanically keeps in sync
     with `TASK_LIST.json`'s `running` tasks (pod-dispatch.spec.md, "Mechanical HEARTBEAT
     ledger"); everything outside that region, including any hand-written entries elsewhere in
     the same file, is never touched by that sync
   - `WORKFLOW_AUTO.md` — the runtime-forced startup file carrying the versioned
     resume/durability contract (`docket-contract` marker; regenerated, never hand-edited).
     Anchors either the **codebase** path (`## Your codebase`) or, for a `workdir`-kind pod
     (pod-blueprints.spec.md), the shared **working directory** (`## Your working directory`) —
     never both. It opens with a **"Manual-path contract"** header stating that its own
     `cd`/write-`HEARTBEAT.md` instructions apply only to an agent reading this file directly,
     outside docket's turn loop: the live turn loop never sends this raw file to the model and
     composes a small read-only projection instead (agent-loop.spec.md; role-archetypes.spec.md
     "Generated instructions agree with the runtime contract")
   - `MEMORY.md` — the operator's free notes about the project (seeded; docket never writes it
     again). The seed names no path: its stack line is the only fact it carries from
     provisioning. A live turn composes it only when it holds text beyond that template
     (agent-loop.spec.md). What a pod learns by itself lives in the pod's `memory.json` ("Pod
     memory" below), not here
   - `.docket-meta.json` — docket metadata (see data spec)
   - `memory/` — an empty directory at provisioning. docket seeds no daily log, distills none
     and archives none. A `YYYY-MM-DD.md` file or a `.distilled/` archive placed there stays as
     it is: docket never reads, moves or deletes it, `docket pod reset` included, and `docket
     setup` never counts one as missing
2. Every project agent has **either** a codebase path with auto-detected stack
   (`workspaceKind: codebase` — every `software`-blueprint pod)
   **or** a plain working directory with no codebase assumption (`workspaceKind: workdir` — a
   `research`/`content`/`ops`-blueprint pod; see pod-blueprints.spec.md), never both.
3. Pod members are project agents with ids `<project>-<role>[-N]`, each with its **own**
   workspace under `projects/`; the pod **Lead's** workspace additionally holds `TASK_LIST.json`,
   the pod's task queue (one queue per pod, owned by pod-dispatch.spec.md). `TASK_LIST.json` is
   created by the pod's first task, not at provisioning.
4. `INSTRUCTIONS.md` **MAY** exist in any project-agent workspace, pod member or not.
   Unlike every other file above it is **operator-owned**: docket **MUST NOT** create,
   write, regenerate, move, or delete it at any point — not at provisioning, not by
   `docket pod update`, not by the `TOOLS.md` rewrite of `docket pod set verify <cmd> --member <id>`, not by
   `docket pod reset`, and not by `docket setup --fix`. When present, its content is composed
   into the live prompt immediately after `SOUL.md` (agent-loop.spec.md) so an operator's own
   instructions survive every regeneration path that would otherwise overwrite a generated file.
   A pod member's `SOUL.md`/`AGENTS.md`/`TOOLS.md` remain fully regeneratable —
   `docket pod update [--dry-run]` re-renders whichever of them have drifted from the member's
   current role archetype and stored metadata (a template-version change, or the archetype's own
   content changing), applying the new text and restamping `templateVersion` in
   `.docket-meta.json`; `--dry-run` prints the same comparison as a diff without writing. A
   member with nothing stale is a no-op: nothing is written and `templateVersion` is left alone.
   `docket setup --fix` **MUST** flag a stale pod member (advisory: it never changes the exit
   status) and name `docket pod update` as the remedy.

### Pod memory

What a pod learns about its repository survives the task that learned it, in one file for the
whole pod and every member that reads it.

1. A pod **MAY** have `memory.json` at `$DOCKET_HOME/workspaces/pods/<pod>/memory.json`, shaped
   `{"entries": [...]}`. It is created by the first recorded entry, written only through the
   atomic JSON writer (filelocked, `0600`) and removed with the pod. An entry is
   `{id, kind, path | command, note, status, reason, provenance}` where `status` is `accepted`,
   `pending` or `refused`, `reason` says why in one phrase, and `provenance` is
   `{task, date, commit}`; a `command` entry carries `command` instead of `path` and also `exit`,
   the status docket read from the task's trace. The `id` is `mem-` plus ten hex digits derived
   from `(kind, subject)`, so it is also the deduplication key.
2. The kinds are closed: `generated` (a repository path not worth reading, with what it is),
   `command` (a command and what it showed), `pitfall` and `convention` (a repository path, or
   `.` for the whole repository, and one fact about it). A note is one sentence of at most 200
   characters.
3. **The memory section.** A step's reply **MAY** end with a section opened by a line that is
   exactly `## Memory` (case-insensitive), followed by one line per entry of the form
   `- <kind>: <path or command> -- <note>`. The last such heading wins; the section ends at the
   next line starting with `#`; a line that is not a bullet is ignored; a bullet that does not fit
   the grammar or names another kind is dropped and traced as refused (it is not stored). At most
   8 bullets are read per hop. docket reads the section of every hop that ended ok when the task
   reaches a terminal state. A failure while recording is audited (`pod.memory.error`) and never
   unwinds the finalized task.
4. **Acceptance is mixed.** docket decides each entry, never the model:
   - **refused**, with a reason: a subject that is not a repository-relative path (empty, absolute
     or starting `~`, containing a backslash or a control character, an empty, `.` or `..`
     segment, or over 200 characters; `.` alone is allowed), or, for a `command`, empty, over 200
     characters or carrying a URL; a note over 200 characters; a note that carries a URL, starts
     with an imperative verb from a fixed list, or contains `ignore`, `disregard`, `override`,
     `forget`, `always`, `never`, `must`, `should`, `you`, `your`, `instruction(s)`, `do not`,
     `don't`, `from now on` or `system prompt`; a `pre_input` verdict of `block`,
     `require_approval` or `redact` on `<subject> <note>` (screened untrusted, the pod's own
     policies included).
   - **pending**: every `pitfall` and `convention`; every entry of a task whose trace holds a
     `fetch` tool call, or whose trace cannot be read; a `pre_input` verdict of `warn`; a
     `generated` entry when the task produced no commit.
   - **accepted**, automatically: a `generated` entry whose path exists at the task's commit
     (`git cat-file -e <commit>:<path>`), and a `command` entry whose command has an exit status
     in the task's trace (a `command_step`, the verify gate, or a `bash` call with its
     `process_exited`). The task's commit is the latest hop evidence commit.
   - The checks above apply first; the pending holds apply next; only an entry that survives both
     is checked against the commit or trace, so it is refused when a `generated` path is absent at
     the commit or a `command` has no exit status in the trace.
   Text that arrived from the repository, a tool result or the web is therefore never stored as
   an instruction: nothing is accepted from it except a fact docket checked itself.
5. **Bounds and deduplication.** An entry already present for the same `(kind, subject)` is not
   added again: an accepted or refused one stands (a refusal is the operator's or docket's
   decision and is not reopened), a pending one is replaced only by an accepted one. At most 40
   accepted entries are kept, the oldest dropped first, and at most 40 pending and refused ones
   together, the oldest dropped first, so a flood of pending entries cannot push an accepted one
   out.
6. **Render.** The prompt composer **MUST** compose the accepted entries as the last section of
   the system prompt, after `MEMORY.md`, behind its own untrusted frame (`POD_MEMORY_FRAME`: the
   entries come from earlier tasks of this pod, not from the operator, and are never a request to
   run commands or to change tools, approvals or policies) and never in docket's voice. The section
   is reported as `podMemory` in `prompt_composed`. It is capped at 3000 bytes by dropping the
   oldest whole entries, an entry whose path is absent under the first project root is
   omitted (not deleted), and no accepted entry composes nothing.
7. **Every change is recorded.** Recording or deciding an entry writes one `memory_update` trace
   event per entry (trace-store.spec.md) and one `pod.memory.<action>` audit entry carrying the
   entry id, kind, status and actor (and the task id when there is one), never its note or
   subject; the action is the entry's status when docket recorded it (`accepted`, `pending`,
   `refused`) and `approved`, `refused` or `reverted` when the operator decided it. A reset
   writes one `memory_update` event and one `pod.memory.reset` audit entry carrying the count.
8. The operator's side **MUST** be a typed API: `list_entries`, `approve` (pending to accepted),
   `refuse` (pending to refused, with a reason), `revert` (accepted to refused, so the same fact
   is not accepted again) and `reset` (remove every entry; returns the count). Each audits and
   traces like requirement 7. `approve`, `refuse` and `revert` raise `PodMemoryError` for an
   unknown id or an entry in the wrong state.
9. `docket pod reset <member>` **MUST NOT** read or change `memory.json`, `MEMORY.md` or `memory/`.
10. **The operator's side** is `docket pod memory list|approve|refuse|revert|reset`
    (cli-interface.spec.md); every action calls the requirement 8 API with `actor="cli"`, so the
    entry moves and the audit and trace record are written by the one writer. The inbox lists the
    pending entries and names those commands (operator-loop.spec.md); it does not decide them. An
    approved entry reaches the pod's next composed prompt (requirement 6); a reverted one leaves
    it and stays as a refusal.

### No shared agents

1. Agent workspaces exist only under `~/.docket/workspaces/projects/<id>/`. `docket init`
   provisions a pod's own members (the default, `--blueprint`, `--pod`, `--with`, `--recipe`, and
   a `--from` entry, which names a `blueprint`) and registers them in `fleet.json`; no other
   command creates an agent workspace.
2. `docket pod reset` acts on members of the named pod only. `docket setup --fix` reads every
   directory under `projects/` that holds a `.docket-meta.json`;
   a directory under `~/.docket/workspaces/` outside `projects/` is not read, healed or reported.

### Permissions

1. Workspace directories **MUST** be `700`.
2. Workspace files **MUST** be `600`.
3. A pod Implementer's `tasks/<taskId>/` directories are git worktrees of the project codebase,
   created by dispatch at claim (pod-dispatch.spec.md "Task worktrees"), not a docket prompt/
   metadata file set. Permission healing **MUST NOT** recursively rewrite those checkouts' modes;
   executable bits and repository-owned permissions remain intact. Provisioning and maintenance
   enforce `700`/`600` on the managed workspace root, prompt/metadata/ledger files, and `memory/`.
4. A pod's directory under `workspaces/pods/`, its `config/`, `.scratch` and `cache`
   directories, and `memory.json` follow the same `700` (directories) and `600` (files) rule.

### Shipped-data templates (package, not workspace)

The package's `templates/` directory is package data shipped in the wheel — read-only source material a command
*copies from* or *reads*, never a workspace this spec's permission/provisioning rules apply to.

1. `templates/policies/*.yaml` (baseline guardrail policies, copied into `$DOCKET_HOME/policies/`
   by `docket init` and `docket setup --fix`, never overwriting an existing file; the loader also
   accepts `.yml` and `.json`) and `templates/recipes/<name>/` (role/pipeline/policy bundles,
   applied only by an explicit `docket init --recipe <name>` or `docket pod update <name|dir>`)
   **MUST** both resolve through the package's path accessors rather than a hardcoded relative
   path, so a template's real location can never drift from where the installed package actually
   put it.
2. A role a recipe provisions (e.g. `docket pod add security-vetter` after `docket pod update
   templates/recipes/secure-build/roles/security-vetter.yaml`) **MUST** produce a workspace
   satisfying every requirement above — the same `700`/`600` permissions, the same required core
   files, the same contract marker. A recipe is a source of *archetype data*
   (role-archetypes.spec.md); it creates no new provisioning path and is invisible to this
   spec's own requirements once the workspace exists.
3. Nothing under `templates/` is itself writable by a provisioned agent, and no workspace file is
   ever a symlink into it — copying (policies) or reading-then-validating (recipes) is always by
   value, so editing a shipped template after installation never mutates an already-provisioned
   workspace or an already-copied policy.
4. **`$DOCKET_HOME/recipes/<name>/` is operator-owned state, not package data (ADR 0013).** It is
   writable by the operator (a plain directory drop-in, no registration step), never shipped in
   the wheel, and `docket pod reset`/`docket setup` never touch it. Recipe resolution checks, in
   order, a directory path, this directory, then the shipped library, so a same-named operator
   recipe wins; `docket pod recipes [name]` (cli-interface.spec.md) is its read-only discovery
   surface, alongside the shipped library.
5. `templates/providers/`, `templates/exporters/` and `templates/channels/` (the built-in
   `kind: provider`, `kind: exporter` and `kind: channel` documents, ADR 0014) are the same
   read-only, wheel-shipped shape, each resolved through its own path accessor. The catalogs built
   from them (`docket-providers.json`, `docket-exporters.json`) and the exporter health file
   (`exporters-health.json`) are `DOCKET_HOME`-level registry files documented by their owning
   specs rather than by this one.

### Skills scopes

1. `~/.docket/skills/` (overridable by the `SKILLS_DIR` environment variable) is the operator's
   own global Agent Skills directory — writable runtime state docket reads, unlike the read-only
   `templates/` above. A pod's own `config/skills/` (under `workspaces/pods/<pod>/`) holds one
   directory per skill a recipe's own `skills/` applied there (pod-blueprints.spec.md, "Pod
   manifests: apply"/"export"). Both, once written, follow this spec's `700`/`600` permission
   rules the same way `config/policies/` and `config/plugins/` do. Discovery order (nearest-wins
   across a codebase's own `.docket/skills/`, the pod scope, and this global scope) and the
   `skill` tool are owned by agent-loop.spec.md, not here — this spec covers only the two
   directories' existence and permissions.

## Interface Contracts

Workspaces are created and repaired through commands, not edited by hand:

```bash
docket init [<project>] [<location>] [--blueprint <name>]  # Provision a pod (see pod-blueprints.spec.md)
docket pod add <role> [--pod <name>]    # Add a member workspace to an existing pod
docket pod reset <member>               # Clear the ledger, regenerate SOUL/AGENTS/TOOLS from metadata
docket pod update [--dry-run]           # Re-render stale pod-member SOUL/AGENTS/TOOLS
docket setup --fix                      # Report missing files, re-seed a missing/stale WORKFLOW_AUTO.md, re-sync the ledger
```

## Examples

### A provisioned Implementer workspace (`codebase`-kind)

```text
~/.docket/workspaces/projects/proj-implementer/
├── SOUL.md
├── AGENTS.md
├── TOOLS.md                  # ports, scratch dir, verify command
├── HEARTBEAT.md
├── WORKFLOW_AUTO.md          # anchors "## Your codebase"
├── MEMORY.md
├── .docket-meta.json
└── memory/                   # empty
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
└── memory/                   # empty
```

## Validation

### Pre-conditions

- `~/.docket` (or the configured `DOCKET_HOME`) **MUST** be writable; every workspace tier lives
  below that one docket-owned root.

### Post-conditions

- After `docket init` (or `docket pod add` for a new pod member), all required core files **MUST**
  exist with `700`/`600` permissions and a current-version contract marker in `WORKFLOW_AUTO.md`.
- After the first `docket init` in a fresh home, `projects/` holds only the pod's members.
- After `docket pod reset <member>`, `SOUL.md`, `AGENTS.md` and `TOOLS.md` (when applicable)
  **MUST** be regenerated from metadata and the `HEARTBEAT.md` ledger replaced by a fresh seed;
  `MEMORY.md`, `memory/` and the pod's `memory.json` are left as they were.

### Invariants

- Directory permissions **MUST** be `700` and file permissions `600`.
- A project agent is `workspaceKind: codebase` or `workspaceKind: workdir`, never both — a
  `workdir`-kind member's contract files never reference a codebase.
- A pod Lead's `HEARTBEAT.md` dispatch region (see requirement 1) **MUST NOT** be the only thing
  a mechanical sync ever rewrites in that file — every other byte, including an agent's own
  entries under the same `## Active Tasks` heading, survives byte-for-byte.
- `INSTRUCTIONS.md` (requirement 4) is never written by docket under any command —
  provisioning, `docket pod update`, `docket pod set`, `docket pod reset` and
  `docket setup --fix` alike leave an existing `INSTRUCTIONS.md` byte-for-byte untouched.

## Implementation

Where the names above live today; the only section that names source paths.

- `src/docket/kernel/home.py`: the `Home` members `projects_dir`, `pods_dir`, `skills_dir`,
  `pod_memory_path`, `pod_config_dir`, `user_recipes_dir`, `pod_memory_max_accepted`,
  `pod_memory_max_undecided`, `pod_memory_max_per_task`, `pod_memory_note_max_chars`,
  `pod_memory_render_max_bytes`
- `src/docket/kernel/templates.py`: `POLICY_TEMPLATES_DIR`, `RECIPES_DIR`, `PROVIDER_TEMPLATES_DIR`,
  `EXPORTER_TEMPLATES_DIR`, `CHANNEL_TEMPLATES_DIR`
- `src/docket/core/pod_provisioning.py`: `provision_member`, `rendered_member_files`,
  `member_sync_status`, `resync_member`, `POD_TEMPLATE_VERSION`, `TASK_WORKTREES_DIRNAME`
- `src/docket/core/memory.py`: `seed_contract`, `contract_ok`, `CONTRACT_VERSION`,
  `DISPATCH_BLOCK_BEGIN`, `DISPATCH_BLOCK_END`, `sync_dispatch_tasks`, `heartbeat_seed`
- `src/docket/core/pod_memory.py`: `record_task_memory`, `parse_memory_section`, `list_entries`,
  `approve`, `refuse`, `revert`, `reset`, `render_entries`, `PodMemoryError`, `KINDS`
- `src/docket/core/identity.py`: `compose_agent_prompt`, `POD_MEMORY_FRAME`, `POD_MEMORY_LABEL`,
  `INSTRUCTIONS_FILE`
- `src/docket/core/dispatch.py`: `pod_task_list_path`; `_finalize_task` calls `record_task_memory`
- `src/docket/core/pod_apply.py`: `resolve_recipe`
- `src/docket/core/policy.py`: `install_policies`
- `src/docket/core/utils.py`: `project_ids`
- `src/docket/cli/_pod.py`: `reset_member`, the `memory` sub-group, `_regenerate_member_tools`
- `src/docket/cli/_pod_config.py`: `cmd_update`, `_sync`
- `src/docket/cli/_setup.py` and `src/docket/cli/_setup_check.py`: `docket setup --fix`
  (`run_check`, `_check_project_agents`, `_check_pod_sync`, `_check_runtime_contract`)
- `src/docket/cli/_agents.py`: `cmd_init`
- `src/docket/edges/store.py`: the atomic JSON writer
