# Pod Blueprints Specification

**Version**: 2.0.4
**Status**: Implemented
**Last Updated**: 2026-10-23

## Purpose

This specification defines the **pod blueprint**: a named, versioned pod shape composing an
archetype roster (`role-archetypes.spec.md`), a default pipeline (`pipeline-format.spec.md`), a
workspace kind, and an optional default budget cap. A blueprint generalizes pod *composition* the
way `role-archetypes.spec.md` generalizes individual *roles*: a research pod, a content pod and an
ops pod are one `docket init` away.

It also defines how a team shape is applied to a pod that already exists, written back out of
one, and reviewed before a repository's commands run on a machine: the pod manifest (`pod.yaml`),
the recipe library, the per-pod settings writers and the operator's review.

## Scope

This specification covers:

- The blueprint schema: `name`, `version`, `workspaceKind`, `roles`, `defaultPipeline`,
  `defaultBudgetUsd`, and `description`, and which fields are closed enums and which are open. A
  blueprint has no file or wire form; these are its attribute names
- The five built-in blueprints (`software`, `research`, `content`, `ops`, `agentic-product`)
- The `workspaceKind` (`codebase` | `workdir`) distinction and how a `workdir` blueprint's shared
  working directory is resolved and provisioned
- How `docket init --blueprint <name>` and `docket init --from <spec>` select and provision a
  blueprint
- The `.docket-meta.json` fields a blueprint-provisioned member carries (`blueprint`,
  `workspaceKind`, `workDir`); schema authority is `docket-meta.spec.md`, this spec covers when
  and why they are written
- Pod-local pipelines, the pod settings writers (`docket pod set` / `unset` / `add`), applying a
  directory, a recipe or one document to a pod (`docket pod update`), exporting a pod
  (`docket pod export`), the recipe library, and the review of what a repository's directory runs
  on this machine

This specification does NOT cover:

- The archetype schema (`name`, `scope`, `modelClass`, `soulTemplate`, `agentsTemplate`,
  `gateContract`, `toolProfile`, `deniedTools`): see `role-archetypes.spec.md`. A blueprint's
  `roles` list is a roster of archetype names
- The pipeline format (steps, gates, rework edges, variables): see `pipeline-format.spec.md`.
  A blueprint's `defaultPipeline` is one pipeline value; this spec covers which pipeline each
  built-in attaches
- Executing a pipeline: `pod-dispatch.spec.md`. A pod dispatched with no caller-supplied
  pipeline runs its bound pipeline, else its blueprint's `defaultPipeline` (named by the Lead's
  `blueprint` meta), else the built-in default pipeline; see "Pipeline order and participation"
  there for the exact resolution order. A `research`, `content` or `ops` pod dispatched that way
  runs its full roster and gates
- The document formats a directory holds (`kind:` envelope, short forms, schemas, `docket pod
  validate`): `config-format.spec.md`
- Blueprint definitions authored by a user: none exist; the five built-ins are the whole
  registry (see "User-authored blueprints")
- Per-role org-vs-pod scope: scope is a property of the *archetype* a role name resolves to
  (`role-archetypes.spec.md`), inherited by a blueprint's roster

## Requirements

### Blueprint schema

1. A pod blueprint **MUST** carry: `name` (string), `version` (positive integer), `workspaceKind`,
   `roles` (an ordered, non-empty list of archetype names), and `defaultPipeline` (a valid
   pipeline, see `pipeline-format.spec.md`). `defaultBudgetUsd` and `description` **MAY** be
   present (absent/empty is valid for both).
2. `workspaceKind` **MUST** be one of exactly `"codebase"` | `"workdir"`, a closed enum, matching
   the "closed typed sets docket can reason about" discipline `role-archetypes.spec.md` applies to
   `scope`/`modelClass`/`gateContract.kind`.
3. `roles`' first entry **MUST** be `"lead"`, and `"lead"` **MUST** appear exactly once: a pod has
   exactly one orchestrator. Every other entry is an open archetype-name reference: any built-in,
   starter-library, or user-defined archetype registered in `role-archetypes.spec.md`'s registry
   is valid roster material. The schema does not re-validate role names itself; pod planning does,
   the first time a blueprint's roster is provisioned.
4. `defaultBudgetUsd`, when present, **MUST** be a non-negative number. It is applied to the pod's
   **Lead only** at provisioning time (the same `budgetUsd` that `docket pod set budgetUsd` sets),
   never to any other member.
5. `name` **MUST** match `^[a-z][a-z0-9-]*$`. `version` **MUST** be a positive integer. An invalid
   definition **MUST** be rejected with a clear error naming the offending field
   (`BlueprintError`), never silently coerced.
6. Every gated step in `defaultPipeline` that targets a role in `roles` **MUST** carry a gate whose
   kind matches that role's own archetype `gateContract.kind` exactly (`none` -> no gate;
   `mechanical` -> a `MechanicalGate`; `verdict` -> a `VerdictGate`; `approval` -> an
   `ApprovalGate`). There is no separate "default gates" field that could drift from the pipeline;
   the pipeline *is* the gate declaration, inherited from the roster's own archetypes.

### Built-in blueprints

1. Five blueprints **MUST** ship: `software`, `research`, `content`, `ops`, `agentic-product` (see
   Interface Contracts for their exact rosters, kinds and budgets).
2. `software` **MUST** be the default pod: roster `lead`, `implementer` (the lean default roster),
   `workspaceKind` `codebase`, no default budget cap, and a `defaultPipeline` that is exactly the
   built-in default pipeline (`pipeline-format.spec.md`), not a second, independently hand-rolled
   copy.
3. `research`, `content`, and `ops` **MUST** be `workspaceKind: "workdir"`; none of the three
   assumes a codebase. `research` and `content` gate their final step on the Critic archetype's
   APPROVE/REJECT verdict with a bounded rework edge back to the Writer step (at dispatch the pod's
   `maxReworkCycles` setting sets the cycle count, `pod-dispatch.spec.md`); `ops` gates its
   Operator step mechanically (deferring to that member's own `verifyCmd`, mirroring the
   Implementer's convention) and its Monitor step on human approval. Each of the three **MUST**
   declare `instructions` (`pipeline-format.spec.md`, "Steps") on its `lead` step naming that
   pipeline's own next role (`research`: the Researcher; `content`: the Writer; `ops`: the
   Operator) instead of the built-in `lead` archetype's generic Implementer text, which none of
   these three pods has a member for. `software` and `agentic-product` declare no `instructions`
   on their `lead` step and **MUST** stay identical to the built-in default pipeline.
4. `docket init` with **no** `--blueprint` **MUST** resolve to `software`; omitting the flag and
   passing `--blueprint software` explicitly **MUST** be behaviorally indistinguishable.
5. `agentic-product` **MUST** be `workspaceKind: "codebase"` and its roster **MUST** be the full
   pod roster (`lead`, `implementer`, `reviewer`, `tester`): a product that ships an agent to end
   users carries more risk than an internal tool, so Reviewer and Tester run by default rather
   than being opt-in the way `software`'s `--pod full`/`--with` leaves them. Its `defaultPipeline`
   **MUST** be the same built-in default pipeline `software` attaches (no second,
   blueprint-specific pipeline): the difference from `software` is entirely in the roster, and the
   Reviewer/Tester steps that a lean `software` pod never reaches at dispatch time gate a hop here
   because the roles are present. It carries no `defaultBudgetUsd`, matching `software`, the other
   `codebase`-kind blueprint. This blueprint is declarative data only: it does not scaffold
   repository contents; a pod provisioned from it is expected (by convention, not mechanically
   enforced) to embed the `docket-runtime` library as its own guardrail substrate.

### Workspace kind and the working directory

1. A `codebase`-kind blueprint's location argument **MUST** be the pod's codebase: an
   operator-supplied path (the current directory when none is given), never created by docket.
2. A `workdir`-kind blueprint's location argument **MUST** be treated as the pod's **shared**
   working directory (one per pod, not per member: the same "one root shared by every member"
   pattern as a codebase). When no location is given, docket **MUST** auto-provision one at
   `$DOCKET_HOME/workspaces/pods/<project>/workdir`, next to the pod's scratch directory. docket
   creates the directory when it is absent (`mkdir -p`) and sets its mode to `700`. `docket init`
   always supplies a location (the current directory when none is passed), so the auto-provisioned
   path is reached from a `--from` entry without `workDir` or a `POST /pods` body without `path`.
3. Every workspace-contract file a `workdir`-kind member's provisioning writes (`WORKFLOW_AUTO.md`
   and `MEMORY.md`) **MUST** anchor the working directory, not imply a git-tracked codebase: no
   "cd into the codebase" language, no `## Your codebase` heading. A `codebase`-kind member's
   contract files **MUST** be unaffected by this distinction.
4. A pod member added later to an existing pod (`docket pod add <role>`) **MUST** inherit the
   pod's `workspaceKind`/working directory (or codebase) and `blueprint` from an existing member,
   never defaulting to `codebase`-kind for a pod that was provisioned `workdir`-kind.
5. `docket setup` **MUST NOT** flag a pod member other than an Implementer as broken for lacking a
   `TOOLS.md`; `TOOLS.md` is written only for an Implementer with allocated resources or a
   `verifyCmd` (`workspace-structure.spec.md`), and no built-in `workdir` blueprint's roster
   includes an Implementer.

### CLI surface

1. `docket init [project] [location] [--blueprint <name>]` **MUST** resolve the blueprint (default
   `software`) before provisioning anything, and **MUST** fail cleanly (exit 1, nothing
   provisioned) if `<name>` is not a registered blueprint. Its inputs are never prompted for: the
   location defaults to the current directory and the project id to that directory's name.
2. `--pod full` / `--with <roles>` **MUST** apply only to the `software` blueprint's roster;
   passing them against any other blueprint **MUST** warn and provision that blueprint's own fixed
   roster, not silently combine the two.
3. `docket init --from <spec>` (a JSON or YAML file: a list of entries, an object with an
   `agents` list, or one entry) takes no other argument or option and **MUST** require a
   `blueprint` field on every spec entry, which **MUST** provision a pod. An entry without one is
   refused and an entry naming an unknown blueprint **MUST** be skipped with a warning naming the
   valid blueprints (`agent-lifecycle.spec.md`'s declarative-provisioning contract).
4. A `blueprint`-bearing spec entry **MUST** accept `codebase` (for a `codebase`-kind blueprint) or
   `workDir` (for a `workdir`-kind blueprint) as its location field, plus `stack`, `description`,
   `telegram` (a group bound to the pod's Lead), `projectKey`, and `budgetUsd`. `budgetUsd`, when
   present, **MUST** override the blueprint's own `defaultBudgetUsd` for that pod's Lead.
5. A pod-shaped spec entry whose pod already exists **MUST** be skipped (warned, not recreated,
   not aborting the rest of the spec file): the same idempotence the single-agent declarative
   path has.

### User-authored blueprints

1. The five built-ins are the entire registry. No command, file or setting adds a blueprint.
   Composing a custom pod shape means provisioning from the closest built-in blueprint and adding
   roles with `docket pod add <role>`, or applying a team (see "Pod manifests: apply").

### Pod-local pipelines

1. A pod's own config directory (`$DOCKET_HOME/workspaces/pods/<pod>/config/`) **MAY** hold a
   `pipelines/` directory of `<name>.yaml` (or `.yml`) pipeline documents
   (`pipeline-format.spec.md`). Dispatch reads it live at claim time when a task names that
   pipeline (`pod-dispatch.spec.md`, "Pipeline order and participation"), ahead of any recipe of
   the same name. The directory is never a pod's default pipeline: binding one stays
   `docket pod set pipeline <file>`.
2. `docket pod update <dir>` **MUST** copy each `<dir>/pipelines/<name>.yaml` (or `.yml`) byte for
   byte into that directory (0600), planned `add`/`replace`/`skip` by content as
   `pipeline pipelines/<name>.yaml`, and `docket pod export` **MUST** write the pod's files back
   to `pipelines/`. A file dispatch could not run **MUST** refuse the whole update before anything
   is written: a pipeline that does not validate, a stem that is not a task pipeline name
   (lowercase letters, digits, `.`, `_`, `-`, starting with a letter or digit), or two files naming
   the same pipeline. A file the directory no longer carries stays in the pod, as a plugin does.
   Their commands are reviewed under requirement 12 of "Pod manifests: apply", each item named
   `<pipeline>/<step id>`; the recipe summary lists them as `pipelines`, and `docket pod validate`
   checks them (`config-format.spec.md`).

### Pod settings: set and unset

1. `docket pod set <key> <value>` and `docket pod unset <key>` **MUST** be the one writer for every
   settable pod setting (Interface Contracts, "Pod settings keys"), validated before anything is
   written and audited as `pod.config`. `pipeline` and `schedule` keep their dedicated writers (a
   validated bound pipeline copy; the `docket-schedules.json` entry); the recorded keys
   (`configSource`, `configDigest`, `exporters`) are refused, naming `docket pod update` as their
   writer; an unknown key exits 1 listing the valid ones.
2. `budgetUsd` is a setting like the rest: setting a cap, `0` or `unset` included, clears
   the Lead's `paused`/`pausedReason` and re-queues the pod's blocked tasks.
3. `verify` is the one key that belongs to a member, not the pod: `docket pod set verify "<cmd>"
   --member <id>` writes that Implementer's `verifyCmd` (validated: no NUL or newline, at most
   2000 characters; audited `pod.set-verify`; `TOOLS.md` re-rendered) and `docket pod unset verify
   --member <id>` removes the key (audited `pod.unset-verify`). Without `--member`, or with
   `--member` on any other key, the command exits 1 naming the flag; a non-implementer or a
   non-member exits 1.
4. `docket pod add <role> [--count N] [--verify "<cmd>"]` adds members to an existing pod; an
   unknown role exits 1 with one line, never a traceback.

### Pod manifests: apply

A blueprint shapes a pod at `docket init` time; this section covers applying a team shape to a pod
that already exists (ADR 0009). `docket pod update <dir>` composes the pod's writers (role
overlay, policies, members, pipeline binding, settings) into one command.

1. `docket pod update <name|dir> [--dry-run] [--json]` **MUST** read *dir* (an argument that is
   not an existing file resolves through requirement 8's `resolve_recipe` order, and an
   unresolvable name exits 1 naming the operator's and the shipped recipes) as these optional
   parts:
   - `roles/*.yaml|yml|json`: role definitions, the wire format `role-archetypes.spec.md` defines;
   - `policies/*.yaml|yml|json`: guardrail policies, the schema `security-gates.spec.md` defines;
   - `plugins/*.py`: predicate plugins;
   - `skills/<name>/SKILL.md`: each `<name>/` a complete Agent Skill, applied whole into this
     pod's own `config/skills/<name>/` (requirement 6's digest, "Pod manifests: export");
   - `mcp-servers/*.yaml|yml|json`: `kind: mcp-server` documents, applied into this pod's own
     pod-scoped MCP server list;
   - `pipelines/<name>.yaml|yml`: named pipelines (see "Pod-local pipelines");
   - `pipeline.yaml`, or the file `pod.yaml`'s `pipeline` key names: the pod's bound pipeline;
   - `pod.yaml`: a manifest of nine top-level keys. `kind: pod` and `name` are the envelope
     (`config-format.spec.md`); `members` (a list of role names to add if absent), `settings` (a
     mapping of any settable `docket pod set <key> <value>` key), `pipeline` (a filename inside
     *dir*, default `pipeline.yaml` when that file exists), `description` (a string, read only for
     display, requirement 9, never applied to the pod), `exporters` (a list of
     observability-destination names, requirement 11, reported and recorded, never activated),
     `prepare` (a string, the install command of a task's worktree, requirement 13), and
     `protects` (a list of path globs a task may not change without a person, requirement 14).

   An unrecognized top-level `pod.yaml` key, a `members`/`settings` value of the wrong type, a
   `description` that is not a string, or an `exporters` entry that is not a plain string naming a
   catalog exporter **MUST** be rejected before any other item is planned.
2. A role in `roles/*.yaml|yml|json` **MUST** be written into *that pod's own* role overlay
   (`$DOCKET_HOME/workspaces/pods/<pod>/config/roles.json`), the same target `docket pod update
   <file>` writes to (requirement 15). The pod's roster resolution reads that pod's own overlay too, so
   a role written into it is both provisionable as a member and resolvable back out of the roster a
   pipeline dispatches against, and stays invisible to every other pod.
3. A file in `policies/` **MUST** be validated as a guardrail policy and, once valid, written
   byte-for-byte under its own file name into *that pod's own* policy directory
   (`$DOCKET_HOME/workspaces/pods/<pod>/config/policies/<file>`), the directory the policy engine
   reads at evaluation time and `docket pod export` copies from, never the fleet-wide
   `~/.docket/policies/`. A file whose parsed content already matches the pod's copy plans as
   `skip`; a different one already present plans as `replace`; an invalid policy file **MUST** be
   rejected before anything else is written, naming the offending file.
4. `docket pod update` **MUST** validate everything before writing anything: each
   `roles/*.yaml|yml|json` definition (`role-archetypes.spec.md`'s schema), every policy file, every `pipelines/` file,
   every `mcp-servers/` document (a name declared twice, or equal to a global MCP server, is
   refused rather than shadowed), every `members` entry against the role registry *as it would be
   after* the directory's own roles are added, the resolved bound pipeline against the roster *as
   it would be after* `members` join (no skipped step; the same resolution `docket pod plan`
   renders), and every `settings` entry through the validators `docket pod set` uses. A validation
   failure **MUST** exit 1 naming the offending item and **MUST NOT** write any role, policy,
   plugin, skill, server, member, pipeline binding, or setting, including one that validated
   cleanly earlier in the same run.
5. `docket pod update` **MUST** be additive and idempotent: an item whose target state already
   matches disk plans and reports as `skip` (a plugin by sha256, a skill by a digest of its files,
   an MCP server by equality, a role by its normalized wire form, a policy by its parsed content, a
   named pipeline by bytes, the bound pipeline by digest); a member is only ever added, never
   replaced or removed; MCP servers the directory does not name are kept; a role, policy, plugin,
   skill, server, pipeline binding, or setting already present with different content plans as
   `replace`. Applying the same directory twice in a row **MUST** plan every item `skip` the second
   time and write nothing. `--dry-run` **MUST** print the plan and write nothing. A setting that
   plans `skip` because the pod holds that value by default **MUST** carry the note `already the
   default`, printed on its plan line (`[skip] setting: approvalMode (already the default)`) and
   returned as the item's `note`. `--json` prints `{"items": [...]}`, each item
   `{kind, name, action, note}`.
6. A successful `docket pod update <dir>` that wrote at least one item **MUST** write exactly one
   `pod.apply` audit entry naming every planned item and its action (and the channel when applied
   over HTTP); an all-`skip` plan **MUST NOT** write a new audit entry. Every successful apply, an
   all-`skip` plan included, **MUST** also record this pod's configuration of record (ADR 0012,
   amended by ADR 0013) in its settings: `configSource` (the absolute *dir*) and `configDigest` (a
   sha256 hex digest over the sorted relative paths and bytes of every `roles/`, `policies/`,
   `mcp-servers/` and `pipelines/` document, `pipeline.yaml` and `pod.yaml` in *dir*, plus any
   `plugins/*.py` and any file under `skills/`, excluding the generated `.schemas/`), so composing
   a second recipe onto an already-configured pod, even one whose every item plans `skip`, still
   moves the record to name the directory just applied. Both **MUST NEVER** be written by `docket
   pod set`, which **MUST** refuse both keys naming `docket pod update` as their writer; a
   `pod.yaml` `settings` mapping carrying either key is refused the same way any key outside the
   settable set is (requirement 1). `docket pod show` reports `configSource`, `configDigest`, and
   `drift`: `"yes"` when recomputing the digest against the still-present `configSource` disagrees
   with the recorded `configDigest`, `"no"` when it agrees, `""` when there is no recorded source
   or its directory is gone (drift is then unknown, never asserted either way).
7. Removing a role, policy, member, pipeline binding, or setting stays out of this command's
   scope: `docket pod remove <member-id>`, `docket pod unset <key>`, and manual file deletion are
   the explicit way to undo what a recipe added.
8. `docket init` **MUST** discover a present `<location>/.docket/` (the same directory shape and
   default this section reads) and, before provisioning anything, validate every document under it
   (as `docket pod validate` does); any error **MUST** exit 1 naming the offending file and field,
   with no pod provisioned. After provisioning succeeds, `init` **MUST** plan and apply that
   directory through this section's own plan and apply (never a second write path), and the
   resulting `pod.apply` audit entry is this requirement's, not a duplicate. `docket init --recipe
   <name|dir>` **MUST** resolve *name|dir* as: a directory path if one exists at that location,
   else the operator's own `$DOCKET_HOME/recipes/<name|dir>`, else a shipped recipe: three scopes,
   nearest wins by name (ADR 0013). It applies the result the same way; an unresolvable name
   **MUST** exit 1 naming both scopes' recipe names, before provisioning. `--recipe` together with
   a present `.docket/` **MUST** exit 1 naming both sources, before provisioning: two sources of
   record is an ambiguity this command refuses rather than picks between. `--no-apply` **MUST**
   provision the pod and skip applying either source, instead printing the `docket pod update
   <dir>` command that would apply it.
   A repository may hold several teams: the pod's configuration-of-record directory is
   `<codebase>/.docket/teams/<pod>/` when that directory exists, else `<codebase>/.docket/`, and
   `init --name <pod>`, the `pod update`/`export`/`validate` defaults and `docket run`'s change
   pickup all resolve through it. `docket init` without a name matching a team and without
   `--recipe`, in a repository whose `.docket/` has `teams/` and no `pod.yaml`, **MUST** apply
   nothing and exit 2 naming the teams, before provisioning. `pod export` with no `<dir>` **MUST**
   write `teams/<pod>/` when the repository already has `.docket/teams/`, and never touch a
   sibling team's directory.
9. **Recipe summary (ADR 0013).** A directory's scope is derived from its contents, never a
   declared field. The summary reads, without needing a project or a role registry: the count of
   `roles/*.yaml|yml|json`, `policies/*.yaml|yml|json`, `plugins/*.py`, and `skills/*/SKILL.md`
   directories directly under *directory*; `pod.yaml`'s `members`/`settings` entry counts (`0`
   when absent or of the wrong type); the names of the `mcp-servers/` documents and of the
   `pipelines/` files; the bound pipeline document's own `name` (the file `pod.yaml`'s `pipeline`
   key names, or `pipeline.yaml` when present and no key names one; `""` when no pipeline file
   resolves or it fails to parse); `pod.yaml`'s `description` (`""` when absent); and `pod.yaml`'s
   `exporters` list, filtered to string entries only (unvalidated against the catalog; that check
   is requirement 11's). Rendering **MUST** show every count, always in the same order (`roles`,
   `policies`, `members`, `pipeline`, `plugins`, `skills`, `settings`) as one line, e.g. `roles 1 ·
   policies 1 · members 1 · pipeline secure-build · plugins 0 · skills 1 · settings 0`
   (`pipeline none` when no pipeline resolves), with `· exporters <name>[, <name>...]`, then `·
   mcp-servers <name>[, ...]`, then `· pipelines <name>[, ...]` appended, in that order, only when
   present. `docket pod validate <dir>` (`config-format.spec.md`) prints this summary after its
   per-file lines; `docket pod update` and `docket init --recipe`/a discovered `.docket/` print it,
   and the directory's own `description` when set, before the plan itself
   (`cli-interface.spec.md`).
10. **Recipe listing (ADR 0013).** The recipe listing **MUST** return one entry (`name`, `scope`:
    `"operator"` or `"shipped"`, `directory`, summary) per name reachable across both scopes
    requirement 8 reads, sorted by name; a name present in both **MUST** resolve to the operator's
    own directory. `docket pod recipes [--json]` **MUST** print every entry: name, scope, a derived
    `brings`, and the description. `brings` is the non-empty parts among roles, policies, members,
    pipeline, plugins, skills, mcp-servers and settings joined with `+` in that order, e.g.
    `roles+policies+members+pipeline+skills`; `nothing` for an empty directory. It is never a
    stored field (requirement 9's rule). `docket pod recipes <name|dir> [--json]` has no `show`
    verb: it **MUST** resolve *name|dir* the same way (an unresolvable name **MUST** exit 1 naming
    both scopes' recipe names, matching requirement 8) and print the directory's name, description,
    scope (omitted for a path outside both scopes), directory, derived summary, the per-exporter
    state lines of requirement 11, and its `README.md` body when the file is present. Neither
    form **MUST** install, remove, fetch, or write anything: `docket pod update` and `docket init
    --recipe` remain the only writers.
11. **Recipe exporters (ADR 0014): a recipe may name a destination, never carry one.**
    `pod.yaml`'s optional `exporters` list names zero or more observability destinations by their
    exporter catalog name. Planning **MUST** validate every entry before anything else is written:
    an entry that is not a plain string matching the exporter name shape (`^[a-z0-9][a-z0-9-]*$`)
    (a document, a URL, or a credential-shaped string included) **MUST** be rejected naming
    `exporters` and the offending entry, and an entry that does not resolve in the live catalog
    **MUST** be rejected the same way naming the unknown name. A validated list **MUST** be
    recorded as the pod's `exporters` setting, a recorded key exactly like `configSource`/
    `configDigest` (requirement 6): written only by `docket pod update`, on every successful
    validated run (an all-`skip` plan included, overwriting rather than merging with what a prior
    apply recorded), and refused by `docket pod set exporters` naming `docket pod update` as its
    writer. Apply **MUST NOT** write to `docket-exporters.json` or otherwise change any exporter's
    `enabled` state: activation stays global, one operator's command (D-22), never a side effect
    of applying a team's configuration. Apply (and therefore `init --recipe`/a discovered
    `.docket/`) **MUST** print, after the plan, one line per named exporter: its activation state
    (computed without consulting `exporters-health.json`) and, unless already `enabled`, the
    exact `docket setup export enable <name>` command, e.g. `exporter langfuse: disabled ->
    docket setup export enable langfuse`, `exporter otel-collector: enabled`, or `exporter
    langfuse: needs credential <NAME> -> docket setup export enable langfuse`. `docket pod export`
    **MUST** write this pod's recorded `exporters` list back into `pod.yaml` (see "Pod manifests:
    export") when at least one is set: unlike `configSource`/`configDigest`, which describe
    provenance and are never written back, `exporters` is part of what a recipe declares and
    round-trips like `members`. `docket pod recipes <name|dir>` **MUST** print the same per-name
    state lines, from the directory's own declared list (requirement 9), without requiring a
    project.
12. **A repository's commands need the operator's OK (ADR 0024).** Before provisioning anything,
    `docket init` **MUST** classify a `.docket/` (or a `--recipe` given as a directory or resolved
    from the operator's own recipes) into *adds* and *runs on this machine*: pipeline `run:` steps
    (in `pipeline.yaml` and in each `pipelines/<name>.yaml`), a step gate's command (`verify:
    <command>`, `gate: {external: <command>}`, the canonical `mechanical`/`external` gate with a
    `command`, inside a `parallel` group too; a `verify: true` that defers to the member's
    `verifyCmd` runs nothing the repository wrote), MCP server commands, plugins, a `network: open`
    setting, `allowCommands`, a role overlay that removes a built-in role's denied tool, and the
    install command a task's worktree runs (`prepare`, requirement 13). A shipped recipe resolved
    by name **MUST** be exempt. When the second group is non-empty and the repository's remembered
    review (`$DOCKET_HOME/reviewed-repos.json`, 0600, written through the single JSON store) does
    not hold the same items, `init` **MUST**: on a terminal, print both groups with each item's
    exact command and ask `[y/N]` once, remember a `y` (repository root, pod, digest of exactly
    those items, date, items) and audit `repo.allow` with `repo`, `pod`, `code` and `items`; off a
    terminal, create nothing and exit 2 listing the numbered items, the 16-hex review code (64 bits,
    so a repository cannot be crafted to match a code a script already accepts) and the three ways
    on (`docket init` on a terminal, `docket init --accept <code>`, `docket init --no-apply`), or
    with `--json` print `{"status": "needs_review", "reviewCode", "items"}`. `--accept <code>`
    **MUST** match the code exactly and then behaves as a `y`; a different code **MUST** exit 2
    showing before/now per changed item against the pod's latest approval and **MUST NOT** print
    the current code. The code is independent of item order. A repository whose `allowCommands`
    names `sh`, `bash`, `zsh`, `dash`, `sudo`, `ssh`, `nc` or `socat` **MUST** exit 2 before
    provisioning (`security-gates.spec.md`). `--no-apply` skips the review because nothing is
    applied.
    `docket pod update <dir>` **MUST** put a directory that is not a shipped recipe through the
    same review against the pod's recorded codebase, on a terminal or with `--accept <code>`
    (`--dry-run` plans without review). `docket run` picks up the changes of the pod's
    configuration-of-record directory when its digest differs from the recorded `configDigest`: a
    changed run-on-this-machine item is shown as before/now and asked on a terminal; off a terminal
    or when declined, the dispatch proceeds with the pod as it is (the version the operator
    allowed), and a directory naming a refused `allowCommands` shell is never applied. Neither
    `docket start` nor pod dispatch reads `.docket/`. The digest of a set also covers the git blob
    id of each tracked file a command of the set names (`security-gates.spec.md`, "Protected paths
    and the reviewed digest"), so changing such a script asks again.
    The remembered review is kept per codebase and per pod, as a set: each pod keeps every item set
    it approved, an approval never replaces another pod's or the pod's earlier set, and a directory
    is `go` for any set its pod has approved (returning to an earlier set asks nothing; a new set
    asks). A `reviewed-repos.json` of one entry per codebase with no pod keys is read as holding no
    approval. The decision itself (go, refused, needs a code, wrong code, accepted) is one shared
    function used by the CLI and by `POST /pods/<p>/apply`, which is always off a terminal: without
    the matching `accept` it creates nothing and answers `409` with the code
    (`operator-api.spec.md`).
13. **A team prepares its task worktrees (ADR 0029).** `pod.yaml`'s optional top-level `prepare:`
    is the install command a task's fresh worktree runs before its first hop
    (`pod-dispatch.spec.md` "Task preparation"); `none` (or `""`) turns the lockfile-derived
    default off. It belongs at the top level, never inside `settings` (planning **MUST** refuse
    `settings.prepare` naming that, as it does for `pipeline`) and is applied as the pod's
    `prepare` setting, so it is listed as a `setting` item and `docket pod set prepare` writes the
    same value. A value that is not a string, has a newline or NUL, or exceeds 1,000 characters is
    rejected before anything is written. Classification **MUST** list the command as a
    run-on-this-machine item of kind `prepare` (name `prepare`, runs = the command) so requirement
    12's review shows and remembers it: the directory's own `prepare:` when it has one and it is
    not `none`, else, when *dir* is a repository's `.docket/` (or `.docket/teams/<pod>/`) whose
    repository root holds a lockfile, the command pod dispatch derives from it. `prepare: none`
    lists nothing. `docket pod export` writes the recorded setting back as `prepare:`.
14. **A team names what its tasks may not change alone (ADR 0029).** `pod.yaml`'s optional
    top-level `protects:` is a list of path globs added to the default protected paths
    (`security-gates.spec.md` "Protected paths and the reviewed digest"); a task whose diff touches
    one parks for a person (`pod-dispatch.spec.md` "A change that edits its own check"). It
    belongs at the top level, never inside `settings` (planning **MUST** refuse `settings.protects`
    naming that), and is applied as the pod's `protects` setting, so it is listed as a `setting`
    item and `docket pod set protects` writes the same value. A value that is not a list of
    strings, or an entry that the setting refuses (empty, over 200 characters, a comma, NUL or
    newline, a leading `/` or a `..` segment), or more than 50 entries, is rejected before
    anything is written. An empty list clears the pod's patterns. A `protects:` is not a run item:
    it only narrows what runs unattended, so it needs no review. `docket pod export` writes the
    recorded setting back as `protects:`.
15. **One file, and no argument (ADR 0022).** `docket pod update <file>` with an existing file
    **MUST** install that one document: a `kind: role` file into this pod's own role overlay (the
    target requirement 2 names) and a `kind: policy` file into this pod's own `config/policies/`
    (validated as a policy before it is written); any other kind **MUST** exit 1 naming the kind,
    since a pipeline, manifest or MCP server document is applied with its directory. It **MUST**
    support `--dry-run` and `--json` (`{"items": [...]}` as for a directory), write one
    `pod.apply` audit entry naming the file, and leave `configSource`/`configDigest` alone: a
    single document is not the configuration of record. `docket pod update` with **no** argument
    **MUST** re-render the SOUL/AGENTS/TOOLS of every member whose stored template version is
    stale from the current archetype and metadata (`--dry-run` shows the diffs without writing; an
    in-sync pod is a no-op), never touching the operator-owned `INSTRUCTIONS.md`, and writes one
    `pod.sync` audit entry per re-rendered member; `--json` with no argument exits 1.

### Pod manifests: export

`docket pod update` composes a directory *onto* a pod; `docket pod export` writes one back out in
the same shape, so a pod configured by hand, or evolved past the recipe that seeded it, can be
reproduced on a second machine.

1. `docket pod export [<dir>]` **MUST** write exactly this pod's own scope. *dir* defaults to the
   pod's configuration-of-record directory (requirement 8: `<codebase>/.docket/`, or
   `<codebase>/.docket/teams/<pod>/` when the repository already has `.docket/teams/`; `<codebase>`
   is the pod Lead's `codebase`) when omitted. The shape is the one `docket pod update` reads;
   every YAML file the command regenerates is in the **short form** (`config-format.spec.md`,
   "Short-form export") with a leading `# yaml-language-server:` header:
   - `roles/<name>.yaml` for this pod's own role overlay entries only (not built-in or starter
     ones), plus a paired `roles/<name>.md` holding that role's instructions (`soulTemplate`
     and, when it is not the generated starter template, a `## AGENTS` section with
     `agentsTemplate`);
   - `policies/<stem>.yaml` for every file in this pod's own policy directory, regenerated from the
     parsed policy, never a byte copy;
   - `mcp-servers/<name>.yaml` for this pod's pod-scoped MCP servers, never a global one;
   - `plugins/<name>.py`, `pipelines/<name>` and `skills/<name>/...` as byte-for-byte copies of
     this pod's own `config/` files (unlike a role or policy, they are not regenerated: they carry
     their own content rather than a document docket knows how to re-render);
   - `pipeline.yaml`, the pod's bound pipeline copy verbatim (no header of its own, since it is
     not regenerated), when the `pipeline` setting is set;
   - `pod.yaml`: `kind: pod` and `name: <project>` first, then `members` (every non-Lead role the
     pod's roster has), `settings` (every settable key other than `pipeline`, `prepare` and
     `protects`, which are top-level, that the pod has set; a key left at its default is never
     written, so a fresh pod has no `settings` key; `configSource`/`configDigest`, outside the
     settable set, are never written, requirement 6), `exporters` (the recorded list, requirement
     11, only when non-empty), `prepare` and `protects` (top-level, only when set).

   `export` **MUST NOT** write a `pipeline` key inside `pod.yaml`: the default `pipeline.yaml`
   filename `docket pod update` resolves makes one redundant. A recipe's `description`
   (requirement 9) is read-only display prose that apply never stores on the pod, so export has
   nothing to write it back from and **MUST NOT** write a `description` key: a round trip through
   apply and export drops a recipe's description, unlike every other manifest key. `export`
   **MUST** also copy the role, pipeline, policy and pod JSON Schemas into `<dir>/.schemas/`
   (`config-format.spec.md`, "Published schemas") so every header resolves without reaching outside
   the export; apply never looks under `.schemas/`.
2. Global scope is never exported: it is the operator's, not the team's. Fleet-wide policies
   (`~/.docket/policies/`), global MCP servers, other pods, and this pod's own secrets, sessions, traces, and task queue are all out
   of scope; only what the pod's `config/` directory and the bound-pipeline copy hold is written.
3. `docket pod export [<dir>]` **MUST** refuse a non-empty *dir*, including the defaulted
   `<codebase>/.docket/`, unless `--force` is given, so a stray argument (or an accidental bare
   `export`) cannot silently overwrite an operator's existing directory; an empty or
   not-yet-existing *dir* always succeeds. `--force` **MUST** proceed and write over any same-named
   file already there. A successful export **MUST** write one `pod.export` audit entry naming
   *project* and *dir*.
4. Round trip is this pair's own proof, not a separate contract: exporting a pod, applying the
   result to a second pod in a fresh `DOCKET_HOME`, and comparing `docket pod show <member>
   --json` for the matching members **MUST** agree once ids and paths specific to each pod are
   normalized away. Because a role or policy is regenerated (never byte-copied), planning
   **MUST** compare a role by its normalized wire form and a policy by its parsed content, not by
   raw text, so re-planning a pod's own export against itself plans every item `skip`.

### The recipe library

A recipe's scope is derived from what its directory holds, never declared (ADR 0013): a `pod.yaml`
naming only `members` plans roles/members/pipeline, one holding only `policies/` plans policy
items only, and planning treats every part as optional either way (see "Pod manifests: apply"
requirement 1). The shipped library groups by what a directory contains, not by a declared field:

| Kind | Recipe | What `docket pod update` plans on a lean pod |
| --- | --- | --- |
| Team | `secure-build` | roles (`security-vetter`, read-only) + policies + members + pipeline + skills (`security-review`) |
| Team | `research-review` | members (`researcher`, `analyst`, `writer`, `critic`) + pipeline |
| Team | `ops-approval` | policies + members (`operator`) + pipeline |
| Policy pack | `git-safety` | policies only |
| Policy pack | `no-egress` | policies only |
| Policy pack | `secrets-guard` | policies only |
| Policy pack | `prod-approval` | policies only |
| Tooling | `code-intel` | `mcp-servers` only: `ast-grep` and `language-intel`, both declared `access: read` with a tool allowlist |
| Methodology | `tdd` | members (`tester`); skills (`test-first`); a pipeline: `red` (Implementer writes one failing test) -> `check-red` (a `run` command step routed `on: {pass: fail, fail: green}`, so an unexpectedly passing test fails the task outright) -> `green` (Implementer, its own verify command) -> `test` (Tester, PASS/FAIL) |
| Methodology | `spec-first` | members (`writer`, `critic`, `reviewer`); skills (`writing-a-spec`); a pipeline: `spec` (Writer) -> `approve-spec` (Critic, APPROVE/REJECT, bounded rework to `spec`) -> `build` (Implementer, its own verify command) -> `review` (Reviewer, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |
| Methodology | `reflexion` | members (`critic`, `tester`); a pipeline: `build` (Implementer, its own verify command) -> `critique` (Critic, APPROVE/REQUEST-CHANGES, bounded rework to `build`, two cycles) -> `test` (Tester, PASS/FAIL) |
| Methodology | `dual-review` | members (`reviewer`, `critic`); a pipeline: `build` (Implementer, its own verify command) -> a `parallel` group of a Reviewer and a Critic, each falling back to its own role's default verdict gate |
| Methodology | `frugal` | members (`reviewer`); `settings` (`budgetUsd`, `maxReworkCycles`, `turnTimeoutS`); a pipeline: `plan` (Lead, `model: cheap`) -> `build` (Implementer, its own verify command) -> `review` (Reviewer, `model: cheap`, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |
| Methodology | `spec-writer` | no added members; a pipeline: `write-tests` (Implementer, `model: openai/gpt-4.1-mini`, custom instructions for test writing) -> `build` (Implementer, `model: anthropic/claude-sonnet-4-6`, its own verify command) |
| Methodology | `cross-family-review` | members (`reviewer`); a pipeline: `build` (Implementer, `model: anthropic/claude-sonnet-4-6`, its own verify command) -> `review` (Reviewer, `model: openai/gpt-4.1-mini`, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |
| Methodology | `anti-tautology` | no added members; a pipeline: `plan` (Lead) -> `build` (Implementer, its own verify command) -> `check-tests-fail-on-base` (a `run` command step that runs the test files added or changed since `DOCKET_BASE_COMMIT` in a disposable worktree of that commit and fails the task if they pass there; overridable through the step's `env:` entries `ANTI_TAUTOLOGY_GLOB`/`ANTI_TAUTOLOGY_RUNNER`) |
| Methodology | `mutation` | no added members; a pipeline: `plan` (Lead) -> `build` (Implementer, its own verify command) -> `check-mutation-score` (a `run` command step that runs `mutmut`, which must be installed, over the source files changed since `DOCKET_BASE_COMMIT` and fails the task below `MUTATION_THRESHOLD`, default 80, with `MUTATION_THRESHOLD`/`MUTATION_CMD` declared in the step's `env:`; scoped by file, not by line) |
| Methodology | `intake` | members (`reviewer`); a pipeline: `lead` (Lead writes a typed brief and ends with one of READY, NEEDS-INPUT, REJECT, routed with `on:`) -> `ask` (an `input` step that puts the brief's questions to the operator and returns to `lead`, at most three times) -> `build` (Implementer, its own verify command) -> `review` (Reviewer, APPROVE/REQUEST-CHANGES, bounded rework to `build`) |

A policy pack's `pod.yaml` carries `kind: pod`, `name`, and `description` only (no `members`,
`settings`, or `pipeline` key), and so does `code-intel`'s; applying one to any pod changes no
roster and no dispatch step. A policy pack's guardrails narrow what a role already in that pod's
own pipeline may do. Every policy pack states its rules with the policy engine's structured
predicates (`tool`, `path`, `branch`, `anyOf`), not free text, so a pack's guardrail fires on the
call itself: `git-safety` blocks force-push, hard reset, forced clean, forced branch delete, forced
checkout, and a global git config edit, and asks before a push that names or is made from a
protected branch (`main`/`master`/`production`/`prod`); `no-egress` asks before a bash-run network
client, a package install, or a `fetch` call; `secrets-guard` blocks a write/edit whose path looks
like a credential file (`.env`, `.pem`, `.key`, `id_rsa`, `.p12`) or whose rendered text carries a
private-key header, an AWS access-key id shape, or a bearer-token shape, and redacts the same
shapes from output; `prod-approval` asks before an implementer or operator runs a
deploy/production-shaped command, generalising `ops-approval`'s own policy beyond the operator
role. `secure-build`'s and `ops-approval`'s own policies are stated the same way (an `anyOf` of
`{tool, path}` pairs plus a `matches` for text; a `tool: bash` predicate beside the existing
`matches`, respectively) rather than free-text matching.

Each methodology recipe is expressed only with the dialect `pipeline-format.spec.md` defines
(`verify`, `verdict`, `on:` with `max`, `parallel`, `run:`, `model:`, `input`, and the manifest's
`settings`); a recipe adds no pipeline or manifest field. Every recipe's own `README.md` names the
practice, its one-line source idea, what docket's gates make structural about it (as opposed to
merely advisory), and how to undo it. `tdd`'s `check-red` step runs the literal shell command
`python3 -m pytest -q`: a step's `run` field carries no `${var}`-style interpolation (only a
step's own `instructions` does), so it cannot reference a pod's own verify command, and the
recipe's README says to edit the line by hand for a project whose test runner differs.

## Interface Contracts

### CLI Command Signatures

```text
docket init [project] [location] [--blueprint <name>]
docket init --from <spec.yaml>       # spec entries may carry a `blueprint` field
docket init --recipe <name|dir> [--no-apply] [--accept <code>]
docket pod set <key> <value> [--member <id>]
docket pod unset <key> [--member <id>]
docket pod add <role> [--count N] [--verify "<cmd>"]
docket pod update [<name|dir|file>] [--dry-run] [--json] [--accept <code>]
docket pod export [<dir>] [--force]
docket pod recipes [<name|dir>] [--json]
```

Every pod-scoped verb also takes `--pod <name>`; without it the pod is inferred from the current
directory.

### Pod settings keys

The settable keys of `docket pod set` / `unset` are: `budgetUsd`, `maxReworkCycles`,
`turnTimeoutS`, `verifyTimeoutS`, `approvalMode`, `approvalExpiryHours`, `inputExpiryHours`,
`allowCommands`, `pipeline`, `schedule`, `projectInstructions`, `mcpServers`, `deniedTools`,
`requireVerify`, `maxConsultationsPerTask`, `network`, `profile`, `readOnly`, `prepare`,
`protects`. The recorded keys, written only by `docket pod update`, are `configSource`,
`configDigest` and `exporters`.

### Built-in blueprints

| Name | workspaceKind | Roles | defaultBudgetUsd | Gated step(s) |
| --- | --- | --- | --- | --- |
| `software` | codebase | lead, implementer | (none) | implementer: mechanical (own `verifyCmd`) |
| `research` | workdir | lead, researcher, analyst, writer, critic | 20.0 | critic: verdict (APPROVE\|REJECT), rework -> writer |
| `content` | workdir | lead, writer, critic | 15.0 | critic: verdict (APPROVE\|REJECT), rework -> writer |
| `ops` | workdir | lead, operator, monitor | 30.0 | operator: mechanical (own `verifyCmd`); monitor: approval |
| `agentic-product` | codebase | lead, implementer, reviewer, tester | (none) | implementer: mechanical (own `verifyCmd`); reviewer: verdict (APPROVE\|REQUEST-CHANGES), rework -> implementer; tester: verdict (PASS\|FAIL) |

`software`'s `defaultPipeline` additionally declares `reviewer`/`tester` steps (inherited verbatim
from the built-in default pipeline) that a lean `software` pod never reaches at dispatch time;
which roles a pod actually has is a runtime/executor concern (see `pipeline-format.spec.md`).
`agentic-product` attaches the exact same `defaultPipeline`; its roster is the only difference, and
it is precisely what makes the Reviewer/Tester steps reachable.

### `.docket-meta.json` fields blueprints add (schema authority: `docket-meta.spec.md`)

| Field | Written when | Meaning |
| --- | --- | --- |
| `blueprint` | Always, for any member provisioned from a blueprint | The blueprint name that provisioned this pod |
| `workspaceKind` | Only when the pod is `workdir`-kind | `"workdir"`; absent (implicitly `"codebase"`) for every codebase-kind pod |
| `workDir` | Only when the pod is `workdir`-kind | The pod's shared working directory (the member's `codebase` is empty) |

### Return Codes

- `0`: success (pod provisioned, or a declarative spec file processed with only expected skips)
- `1`: unknown blueprint name, a pod that already exists, an invalid document under `.docket/` or
  `--recipe`, an unresolvable recipe, or pod provisioning failed to register any member
- `2`: the operator's review is needed, refused or changed (requirement 12), or a repository holds
  several teams and none was named

## Examples

### Provisioning a research pod

```bash
$ docket init my-market-scan /home/user/work/my-market-scan --blueprint research
-> Provisioning 'research' pod 'my-market-scan' (lead, researcher, analyst, writer, critic)...
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
$ docket init myproj --blueprint wizard-pod
x Error: unknown blueprint 'wizard-pod'; valid blueprints: software, research, content, ops, agentic-product
```

### Applying a shipped recipe

```bash
$ docket pod update secure-build --dry-run
  roles 1 · policies 1 · members 1 · pipeline secure-build · plugins 0 · skills 1 · settings 0
  [add] role: security-vetter
  [add] policy: require-approval-secret-writes.yaml
  [add] skill: security-review
  [add] member: security-vetter
  [add] pipeline: pipeline.yaml
```

## Validation

### Pre-conditions

- `~/.docket` **MUST** be writable (pod provisioning, same as any `docket init`).
- For a `workdir` blueprint with an explicit location, that path (or its parent) **MUST** be
  creatable: docket creates it (`mkdir -p`) if absent and sets its mode to `700`.

### Post-conditions

- After `docket init <project> --blueprint software` (or no flag at all), the resulting pod is the
  same either way (requirement 4 of "Built-in blueprints"), and its `.docket-meta.json` carries
  the `blueprint` key.
- After provisioning a `workdir` blueprint, every member's `WORKFLOW_AUTO.md` **MUST** contain
  `## Your working directory` and **MUST NOT** contain `## Your codebase`.
- `docket setup --fix` **MUST** report no workspace-file, template or ledger issue for a freshly
  provisioned, unmodified pod of any built-in blueprint (what it reports about provider
  credentials and notification bindings depends on the host).

### Invariants

- `workspaceKind`, when present, is always one of `"codebase"` | `"workdir"`.
- A blueprint's roster always starts with exactly one `"lead"`.
- Every gated step's gate kind in a built-in blueprint's `defaultPipeline` always matches the
  gated role's own archetype `gateContract.kind` (enforced by the blueprint unit tests).

## Implementation

Where the names above live today. This is the only section that names paths.

- `src/docket/teams/blueprints.py`: `PodBlueprint`, `BlueprintError`, `BUILTIN_BLUEPRINTS`,
  `DEFAULT_BLUEPRINT`, `WORKSPACE_KINDS`, `get_blueprint`, `load_registry`
- `src/docket/teams/pod.py`: `DEFAULT_POD_ROLES`, `FULL_POD_ROLES`, `PodSettings` (`KEYS`,
  `RECORDED_KEYS`, `coerce`, `load_for`, `value_and_source`), `plan_pod`, `normalize_role`,
  `bound_pipeline_path`, `member_id`
- `src/docket/teams/pod_provisioning.py`: `provision_pod`, `provision_members`,
  `validate_verify_cmd`, `parse_budget_usd`
- `src/docket/teams/apply/plan.py`: `plan_apply`, `apply`, `apply_directory`, `export_pod`,
  `resolve_recipe`, `summarize_recipe`, `RecipeSummary`, `list_recipes`, `RecipeInfo`,
  `directory_digest`, `classify_directory`, `review_decision`, `repo_changes`, `runs_changed`,
  `repo_config_dir`, `repo_root`, `is_shipped_recipe`, `PodApplyError`, `REPO_REFUSED_COMMANDS`
  (the manifest key set is `_MANIFEST_KEYS`)
- `src/docket/governance/review.py`: the remembered review (`remember`, `lookup`,
  `is_reviewed`, `review_code`)
- `src/docket/teams/config_docs.py`: `discover_config_paths`, `validate_directory`, the `pod`
  document model
- `src/docket/hops/application/steps.py`: `effective_pipeline`, `TASK_PIPELINE_NAME`
- `src/docket/tasks/application/queue.py`: `pod_full_roster`
- `src/docket/pipeline/domain/spec.py`: `default_pipeline`; `src/docket/pipeline/domain/plan.py`:
  `resolve_plan`
- `src/docket/governance/policy.py`: `validate_policy`, `read_policy`, `to_short_policy`;
  `src/docket/teams/roles.py`: `load_registry`, `add_user_archetype`, `to_short_role`
- `src/docket/observability/exporter.py`: `load_catalog`, `activation_state`;
  `src/docket/agent/tools/mcp_tools.py`: `load_pod_mcp_servers`, `write_pod_mcp_servers`
- `src/docket/teams/agent_memory.py`: `seed_contract` (the `WORKFLOW_AUTO.md` and `MEMORY.md` text)
- `src/docket/kernel/home.py`: the `Home` members `pod_config_dir`, `pod_work_dir`,
  `pod_scratch_dir`, `user_recipes_dir`, `reviewed_repos_file`
- `src/docket/kernel/templates.py`: `RECIPES_DIR`, `CONFIG_SCHEMAS_DIR`
- `src/docket/interfaces/cli/commands/agents.py`: `cmd_init`, `run_init`, `review_repo_source`, the `--from` path
- `src/docket/interfaces/cli/commands/pod.py`: `build_pod_from_blueprint`, `set_setting`, `unset_setting`,
  `add_members`
- `src/docket/interfaces/cli/commands/pod_config.py`: `cmd_update`, `cmd_export`, `cmd_validate`, `cmd_recipes`
- `src/docket/interfaces/cli/commands/run.py`: the change pickup before a dispatch;
  `src/docket/interfaces/cli/commands/setup_check.py`: the workspace-file check
- `src/docket/interfaces/http/routes/pod_create.py`: `POST /pods`
- `src/docket/interfaces/http/routes/pod_apply.py`: `POST /pods/<p>/apply`
- `src/docket/templates/recipes/<name>/`: the shipped recipes
- Tests: `tests/unit/teams/test_blueprints.py` (including `TestPipelineGateFidelity`),
  `tests/integration/teams/test_provisioning_contract.py` (`TestSeedContractWorkdir`),
  `tests/unit/teams/apply/test_plan.py`, `tests/integration/teams/test_recipes.py`
